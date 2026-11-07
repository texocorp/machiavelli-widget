# -*- coding: utf-8 -*-
"""
試験(montaigne-lab 専用・本番には入れない): ベーコンの「引用の当てはまり」の判定方式を、同じ記事で比べる。
  V0(現行): 場面で選んだ3件+従来順2件を1件ずつ0〜3点で採点 → 3点を見出しの導入文で校閲
  V1(比較): 同じ5件を1回の呼び出しで比べて上位2件と「つながり」を答えさせる → つながりを示して校閲
            (同じ組み合わせを現行の校閲にもかけ、つながりを示す効果を切り分ける)
記事は直近の本番実行で試した40件(tools/bacon_ab_cases.json)。各シャードが cases[shard::4] を受け持つ。
"""
import argparse, json, os, sys, time


def actor_ok(actor, src):
    import montaigne_engine as mtg
    a = mtg._compact(actor)
    if len(a) < 2:
        return False
    if a in src:
        return True
    pairs = [a[i:i + 2] for i in range(len(a) - 1)]
    return sum(p in src for p in pairs) * 10 >= len(pairs) * 6
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bacon_engine as be
import montaigne_engine as mtg
import quote_commentary as qc
from bacon_scorer import load_scoring_config, score_item
from geopolitical_scorer import NewsItem

BUDGET = 36 * 60
COMPARE_PROMPT = """新聞のコラムで、ニュースの後に{author}の一節を引く。下の候補から、この出来事に当てはまる一節を選ぶ。

見出し: {title}
出来事: {facts}

候補:
{cands}

picks に、当てはまる候補を、よく当てはまる順に最大2つ挙げよ。それぞれ次を答える。
n: 候補の番号
actor: その一節の言う構図が当てはまる、見出しの中の主体(国・組織・人)。見出しの表記のまま
bridge: 見出しの「何」が一節の「何」に当たるかを、30〜60字で
挙げてよいのは、一節の言う構図(誰が、誰に対して、何をすると、どうなるか)が、その主体の行動や立場にはっきり当てはまるものだけ。
話題や言葉が重なるだけのもの、役回り(欺く側・欺かれる側など)が逆になるもの、亡くなった人・被害に遭った人を責める響きになるものは挙げない。
当てはまるものが無ければ picks は空にする。"""


def compare_schema(n):
    return {"type": "object",
            "properties": {"picks": {"type": "array", "maxItems": 2, "items": {
                "type": "object",
                "properties": {"n": {"type": "integer", "minimum": 1, "maximum": n},
                               "actor": {"type": "string"}, "bridge": {"type": "string"}},
                "required": ["n", "actor", "bridge"]}}},
            "required": ["picks"]}


BRIDGED_REVIEW = mtg.REVIEW_PROMPT + """
opinion: 導入文に、見出しに無い書き手の評価・推測(「〜すぎる」「〜に惑わされ」「〜を狙って」「〜の表れ」など)が入っているか
fits: 選者は「{bridge}」という理由でこの一節を選んだ。この理由が見出しの事実に照らして正しく、導入文の後に一節を続けて読むと、一節がこの出来事について筋の通ったことを言っているか(理由が見出しの事実と違う、または一節の話題が出来事と違うなら false)"""


SANITY_PROMPT = """新聞のコラムで、ニュースの見出しの後に{author}の一節を引く。選者はその理由を下のように説明した。

見出し: {title}
一節: {quote}
選者の説明: {bridge}

次に答えよ。
true_reading: 説明は見出しの事実を正しく述べているか(見出しに無いこと、見出しと逆のこと、見出しの主張と反対の立場を事実として述べていれば false)
natural: 新聞の読者が、見出しの後にこの一節を読んで、説明が無くても「なるほど」と思えるか(説明でこじつけないとつながらない、一節の言う構図と出来事の構図が違うなら false)"""
SANITY_SCHEMA = {"type": "object", "properties": {"true_reading": {"type": "boolean"}, "natural": {"type": "boolean"}},
                 "required": ["true_reading", "natural"]}


def sanity(title, q, bridge):
    r = mtg._ollama_json(SANITY_PROMPT.format(author="ベーコン", title=title, quote=q["ja"], bridge=bridge),
                         SANITY_SCHEMA, qc.JUDGE, "sanity")
    return [k for k, bad in (("読み違い", not r.get("true_reading")), ("こじつけ", not r.get("natural"))) if bad]


def review_result(prompt):
    r = mtg._ollama_json(prompt, qc.REVIEW_SCHEMA, qc.JUDGE, "review")
    probs = [k for k, bad in (("文意", not r.get("coherent")), ("沿わない", not r.get("on_topic")),
                              ("被害者", r.get("hurts_victims")), ("評価", r.get("opinion")),
                              ("取り違え", not r.get("same_doer")), ("不適合", not r.get("fits"))) if bad]
    return probs


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--shard", type=int, default=0); ap.add_argument("--shards", type=int, default=4)
    a, _ = ap.parse_known_args()
    start = time.time()
    cases = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bacon_ab_cases2.json")))[a.shard::a.shards]
    cfg = load_scoring_config(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bacon_config.yaml"))
    bot = be.llm_bot()
    for title in cases:
        if time.time() - start > BUDGET:
            print("[時間切れ]"); break
        item = score_item(NewsItem(title=title, summary="", source="lab"), cfg["weights"], cfg["exclude_keywords"],
                          cfg["discourse_keywords"], cfg["priority_sources"], cfg["priority_bonus"])
        rec = {"title": title}
        t0 = time.time()
        try:
            reading = qc.read_article(bot, item)
        except Exception as e:
            print("AB:" + json.dumps({**rec, "error": f"read {e}"}, ensure_ascii=False)); continue
        rec["facts"] = reading.get("facts")
        if reading.get("problem"):
            print("AB:" + json.dumps({**rec, "error": reading["problem"]}, ensure_ascii=False)); continue
        picked, cands = qc.scene_candidates(bot, item, reading)
        rec["cands"] = [q["id"] for q in cands]
        rec["t_common"] = round(time.time() - t0)
        intro = qc.headline_intro_text(item)
        rec["intro"] = intro
        t_title, _ = mtg._facts(item)
        src = mtg._compact(t_title)
        rec["v0"] = []; rec["v0_result"] = None; rec["t_v0"] = 0
        # ---- V1
        t0 = time.time()
        listing = "\n".join(f"{i}. 一節: {q['ja']}\n   当てはまる場面: {q.get('scene', '')}" for i, q in enumerate(cands, 1))
        d = mtg._ollama_json(COMPARE_PROMPT.format(author=bot.author, title=t_title, facts=reading["facts"], cands=listing),
                             compare_schema(len(cands)), {**qc.JUDGE, "num_ctx": 8192}, "compare")
        v1 = []; v1_result = None; v1_plain_result = None
        for p in (d.get("picks") or [])[:2]:
            if not isinstance(p.get("n"), int) or not 1 <= p["n"] <= len(cands):
                continue
            q = cands[p["n"] - 1]; actor = (p.get("actor") or "").strip()
            entry = {"q": q["id"], "actor": actor, "bridge": p.get("bridge", "")}
            if not actor_ok(actor, src):
                entry["skip"] = "主体が見出しに無い"; v1.append(entry); continue
            if intro and not v1_result:
                entry["review_bridged"] = review_result(BRIDGED_REVIEW.format(title=t_title, analysis=intro, quote=q["ja"],
                                                                             author=bot.author, bridge=entry["bridge"]))
                if not entry["review_bridged"]:
                    entry["sanity"] = sanity(t_title, q, entry["bridge"])
                    if not entry["sanity"]:
                        v1_result = q["id"]
            if False:
                entry["review_plain"] = review_result(qc.REVIEW_PROMPT.format(title=t_title, analysis=intro, quote=q["ja"], author=bot.author))
                if not entry["review_plain"]:
                    v1_plain_result = q["id"]
            v1.append(entry)
        rec["v1"] = v1; rec["v1_result"] = v1_result; rec["v1_plain_result"] = v1_plain_result; rec["t_v1"] = round(time.time() - t0)
        print("AB:" + json.dumps(rec, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
