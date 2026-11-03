# -*- coding: utf-8 -*-
"""
montaigne_engine.py
--------------------
社会面・科学医療のニュースに、『エセー』の一節を添えて論評する。

【生成の手順(2026-11-03 改訂)】
小型のローカルLLM(qwen3.5:9b)に「記事を読み、人の振る舞いを見つけ、洞察を考え、
名文で、事実を守って、規則を20個守りながら」一度に書かせると、指示の丸写し・空疎な
決まり文句・見出しに無い事情の作話が起きた。また9Bのモデルに人間一般についての
洞察を考えさせると、凡庸か、理屈が逆か、不当な皮肉になった。そこで、
  ・洞察は、原典と照合済みのモンテーニュ本人の言葉(箴言)に任せる
  ・LLM には、出来事のどこに光を当てるかを決めさせ、その一節の前に置く導入として、
    見出しの出来事を正確に言い直させる(評価・一般論は書かせない)
と役割を定め、仕事を4つに分けて、1回の呼び出しには1つの仕事だけを短い指示と手本で頼む。

  1. 読む       read_article()      見出しの事実を言い直し、人の振る舞いが表れた語句を
                                     見出しから抜き出す(Pythonが実在を照合)。目の付けどころ
                                     (レンズ)を選ぶ。論じるべきものが無ければ「なし」で見送る
  2. 選ぶ       choose_quote()      Pythonが箴言の候補を8件に絞り、LLMが響き合う1件を選ぶ。
                                     どれも合わなければ0と答えさせ、見送る
  3. 書く       write_candidates()  一節の前に置く導入の一文を、手本(会話形式)に倣って3通り書かせる
  4. 確かめる   mechanical_check()  字数・説教口調・一般論・指示語の混入・丸写し・見出しに無い固有名詞
                editor_order()      候補を比べ、良い順に選ばせる(どれも駄目なら0)
                verify_claims()     下書きの事実の主張を抜き出し、下書きを見せずに見出しと照らす
                review()            文意が通るか、記事に沿うか、一節と続けて被害者を責める響きにならないか

引用文・出典・URLにLLMは一切関与しない(Pythonが機械的に組み立てる)。
検査を通る文が得られなければ、何も掲載しない(None を返す)。

【取り入れた知見】
- 同時に与える指示が多いほど守られにくくなる(Jaroslawicz ほか 2025, "How Many Instructions
  Can LLMs Follow at Once?")。字数や文体などの機械的な規則はプロンプトに書かず、Pythonで検査する
- 作話を減らすには、下書きの事実の主張を抜き出し、下書きを見せずに確かめさせるとよい
  (Dhuliawala ほか 2024, Chain-of-Verification の factored / 2-step 方式)
- 出力の形は Ollama の structured outputs(JSONスキーマ)で固定し、読み取りの失敗をなくす

【モンテーニュの視座】
- 人間観察に徹する。善悪を裁かず、説教も政策提言もしない
- 亡くなった人・被害に遭った人・その家族の人柄や心の在り方は論じない

【ベーコンボットとの共用】
bacon_engine.py は、このモジュールの _GENERIC_TERMS, _check_not_restating, _ollama_env,
_scene_words, _validate_analysis, _verify_with_ollama を使う。これらは名前も動作も変えないこと。
"""

import json
import os
import random
import re
import time

from geopolitical_scorer import NewsItem, clean_news_text, facts_for_prompt, is_japanese, _MEDIA_SUFFIX
import machiavelli_engine as me  # 実績のある共通部品(思考ブロック除去・字数調整・検査)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUOTES_PATH = os.path.join(BASE_DIR, "data", "montaigne_quotes.json")

with open(QUOTES_PATH, "r", encoding="utf-8") as f:
    QUOTES = json.load(f)["quotes"]
QUOTES_BY_ID = {q["id"]: q for q in QUOTES}

# 出典表記に添える章題(本ボットによる訳。原題は quotes.json の chapter_title)
CHAPTER_TITLES_JA = {
    "I.3": "我々の情念は我々の先へ運ばれる",
    "I.8": "無為について",
    "I.9": "嘘つきについて",
    "I.14": "善悪の味わいは我々の考え方による",
    "I.18": "恐怖について",
    "I.20": "哲学するとは死ぬことを学ぶこと",
    "I.21": "想像の力について",
    "I.22": "一方の得は他方の損",
    "I.23": "慣習について",
    "I.25": "衒学について",
    "I.26": "子供の教育について",
    "I.27": "真偽を己の力量で測る愚かさ",
    "I.28": "友情について",
    "I.30": "節度について",
    "I.31": "人食い人種について",
    "I.39": "孤独について",
    "I.42": "我々の間の不平等について",
    "I.49": "古い慣習について",
    "I.50": "デモクリトスとヘラクレイトスについて",
    "I.54": "むなしい精緻さについて",
    "II.1": "我々の行為の一貫しなさについて",
    "II.5": "良心について",
    "II.6": "実地の訓練について",
    "II.11": "残酷さについて",
    "II.12": "レーモン・スボンの弁護",
    "II.15": "我々の欲望は困難によって募る",
    "II.16": "栄光について",
    "II.17": "うぬぼれについて",
    "II.18": "嘘をつくことについて",
    "II.27": "臆病は残酷の母",
    "II.37": "子が父に似ることについて",
    "III.1": "有益と誠実について",
    "III.2": "後悔について",
    "III.6": "馬車について",
    "III.8": "談論の術について",
    "III.9": "むなしさについて",
    "III.10": "自分の意志を節約することについて",
    "III.11": "足の不自由な人々について",
    "III.12": "人相について",
    "III.13": "経験について",
}


def source_label(quote: dict) -> str:
    """『エセー I.31「人食い人種について」』の形の出典表記を作る。"""
    src = quote["source"]
    title = CHAPTER_TITLES_JA.get(src)
    return f"『エセー {src}「{title}」』" if title else f"『エセー {src}』"


# ---------------------------------------------------------------
# 箴言の使用履歴(マキャベリ側とは別ファイルに永続化する)
# ---------------------------------------------------------------
RECENT_QUOTES_PATH = os.path.join(BASE_DIR, "logs", "montaigne_recent_quotes.json")
QUOTE_USAGE_PATH = os.path.join(BASE_DIR, "logs", "montaigne_quote_usage.json")
RECENT_QUOTES_WINDOW = 40  # 箴言117件に対し、直近40回分(1日8回で5日分)は候補から外す


def load_recent_quote_ids() -> list:
    return me._load_json_file(RECENT_QUOTES_PATH, [])


def load_quote_usage() -> dict:
    return me._load_json_file(QUOTE_USAGE_PATH, {})


def record_quote_usage(quote_id: str) -> None:
    recent = [q for q in load_recent_quote_ids() if q != quote_id]
    recent.append(quote_id)
    me._save_json_file(RECENT_QUOTES_PATH, recent[-RECENT_QUOTES_WINDOW:])
    usage = load_quote_usage()
    usage[quote_id] = usage.get(quote_id, 0) + 1
    me._save_json_file(QUOTE_USAGE_PATH, usage)


# ---------------------------------------------------------------
# Ollama 呼び出し(JSONスキーマで出力の形を固定する)
# ---------------------------------------------------------------
LAST_QUOTE_ID = None
LAST_QUOTE_CHOICE = None
LAST_ANALYSIS_SOURCE = None
LAST_TRACE = {}   # 直近の generate_commentary() の途中経過(試験環境 tools/montaigne_lab.py が読む)


def _ollama_env() -> tuple:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", me.DEFAULT_OLLAMA_MODEL)
    return host, model


# 判定・抽出は決定的に、書く工程だけは幅を持たせる(Qwen の非思考モードの推奨値に近い)
JUDGE_OPTIONS = {"temperature": 0.0, "top_k": 1, "num_predict": 300}
WRITE_OPTIONS = {"temperature": 0.8, "top_p": 0.9, "top_k": 30, "presence_penalty": 0.5, "num_predict": 200}


def _post_ollama(path: str, payload: dict, step: str) -> str:
    """Ollama を呼び、本文(思考ブロックを除く)を返す。所要時間とトークン数を LAST_TRACE に記録する。"""
    import requests  # pip install requests

    host, model = _ollama_env()
    payload = dict(payload, model=model, stream=False, think=False, keep_alive="15m")
    started = time.time()
    resp = requests.post(f"{host}{path}", json=payload, timeout=(5, 400))
    if resp.status_code == 400 and "think" in resp.text.lower():
        payload.pop("think")
        resp = requests.post(f"{host}{path}", json=payload, timeout=(5, 400))
    resp.raise_for_status()
    body = resp.json()
    LAST_TRACE.setdefault("calls", []).append({
        "step": step, "seconds": round(time.time() - started, 1),
        "prompt_tokens": body.get("prompt_eval_count"), "output_tokens": body.get("eval_count"),
    })
    text = body.get("response") if path == "/api/generate" else (body.get("message") or {}).get("content")
    return me._strip_thinking(text or "")


def _parse_json(text: str, step: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{step}: JSONとして読めない出力: {text[:120]!r}") from e


def _ollama_json(prompt: str, schema: dict, options: dict, step: str) -> dict:
    """一問一答。出力の形を JSONスキーマ(Ollama の structured outputs)で固定する。"""
    return _parse_json(_post_ollama("/api/generate", {"prompt": prompt, "format": schema, "options": options},
                                    step), step)


def _ollama_chat_json(system: str, examples: list, user: str, schema: dict, options: dict, step: str) -> dict:
    """
    手本つきの問い。手本は「別の記事への問いと答え」の会話として渡す。
    1つのプロンプトに手本と本題を並べると、小型モデルは手本の記事について書いてしまった
    (実例: 辺野古の記事に、手本の「押印」「元社長」の話を書いた)。会話の形にすると、
    答えるべきは最後の問いだけだと区別しやすい。
    """
    messages = [{"role": "system", "content": system}]
    for q, a in examples:
        messages += [{"role": "user", "content": q},
                     {"role": "assistant", "content": json.dumps(a, ensure_ascii=False)}]
    messages.append({"role": "user", "content": user})
    return _parse_json(_post_ollama("/api/chat", {"messages": messages, "format": schema, "options": options},
                                    step), step)


# 見出しに付いた連載名・回数・媒体名の札。読ませる前に外す
# (実例: 「［医療ルネサンス］攻めのリハビリ＜１＞」の連載名を、取り組みの名前と読み違えた)
_TITLE_LABELS = [
    re.compile(r"[［\[〔【][^］\]〕】]{1,20}[］\]〕】]"),          # ［医療ルネサンス］【独自】
    re.compile(r"[＜<〈《][0-9０-９一二三四五六七八九十上中下]{1,3}[＞>〉》]"),  # ＜１＞
    re.compile(r"[（(][^（）()]{1,25}[）)]\s*$"),               # 末尾の（CNN.co.jp）(マネーポストWEB)
    re.compile(r"[：:][^：:]{1,15}$"),                           # 末尾の「：時事ドットコム」
]


def _facts(item: NewsItem) -> tuple:
    """LLM に渡す(見出し, 概要)。facts_for_prompt の整形に加え、連載名などの札を外す。"""
    title, summary = facts_for_prompt(item)
    for _ in range(2):  # 「…(媒体)：媒体」のように重なっていることがある
        for pat in _TITLE_LABELS:
            title = pat.sub(" ", title).strip()
    title = re.sub(r"[ \u3000]{2,}", " ", title).strip()
    return title, summary


def _news_prompt(title: str, summary: str) -> str:
    return f"見出し: {title}\n概要: {summary}"


def _compact(text: str) -> str:
    """照合用に、空白・括弧・句読点を除き、全角英数字を半角に揃える。"""
    return re.sub(r"[\s「」『』()（）、。・,.!！?？…:：\-－―]", "", me._normalize_for_match(text or ""))


# ---------------------------------------------------------------
# 1. 読む
# ---------------------------------------------------------------
# 目の付けどころ(レンズ)。モンテーニュが繰り返し書いた人の振る舞いを、平易な言葉で示す。
# 右の英語名は箴言のタグ(data/montaigne_quotes.json の tags)。
LENSES = {
    "慣習": ("coutume", "慣わしや前例が、理由を問われないまま続いている"),
    "新奇": ("nouveaute", "新しい仕組みや変更が、戸惑いや混乱を生んでいる"),
    "法と裁き": ("lois", "決まりや裁きが、正しさとは別の理由で通用している、人を縛っている、あるいは誤っている"),
    "知識と肩書": ("savoir", "知識・学歴・試験・肩書・定説が、判断の確かさとは別に重んじられている"),
    "思い上がり": ("presomption", "技術や見通しを、確かめた以上に当てにしている"),
    "思い込みと噂": ("opinion", "確かめられていない話や印象が、事実のように広まり扱われている"),
    "死と老い": ("mort", "死や老いを前に、人がどう備え、どう語り、どう避けているか"),
    "恐れ": ("peur", "出来事そのものより、不安や思いが人を動かしている"),
    "医術と健康": ("medecine", "健康や治療をめぐり、人が医術や専門家にどこまで身を委ねているか"),
    "残酷": ("cruaute", "力の弱い相手に、人がたやすく残酷になっている"),
    "他者": ("autrui", "自分の流儀を物差しにして、異なるものを奇妙だと見なしている"),
    "移り気": ("inconstance", "同じ人や組織の言うこと・することが、食い違ったり翻ったりしている"),
    "虚栄": ("vanite", "地位・肩書・体面・名目が、中身と取り違えられている"),
    "損得": ("profit", "ある人の得が、別の人の損や負担の上に成り立っている"),
    "自分を失う": ("soi", "仕事や他人の期待に追われ、自分の暮らしや時間を手放している"),
}
NO_LENS = "なし"

READ_SYSTEM = """あなたはモンテーニュの『エセー』を愛読する新聞の論説委員である。
ニュースの見出しと概要を読み、次の3つを JSON で答える。

facts: 見出しに書かれた出来事を、誰が・何を・どうしたかの一文で言い直す。見出しに無いことは足さない。
key_phrase: 見出しの中で、人の振る舞いがいちばんよく表れている語句を、見出しから一字一句そのまま抜き出す。
lens: その語句に表れた振る舞いが、次のどれに当たるか。
{lens_list}
  なし: どれにもはっきり当たらない。あるいは見出しに人の言動がほとんど無い(数字の発表、気象、告知だけなど)

亡くなった人・被害に遭った人・被災した人・その家族の振る舞いや心の在り方は取り上げない。
目を向けるなら、加害した側、組織や制度の扱い方、出来事を語る言葉に向ける。"""

READ_EXAMPLES = [
    (_news_prompt("粉飾決算の元社長に有罪判決 「会社のためだった」と主張", "(見出し以外の情報なし)"),
     {"facts": "粉飾決算をした元社長に有罪判決が出て、元社長は会社のためだったと主張した",
      "key_phrase": "「会社のためだった」と主張", "lens": "虚栄"}),
    (_news_prompt("新規感染者 前週の1.2倍に 厚労省まとめ", "(見出し以外の情報なし)"),
     {"facts": "厚労省のまとめで、新規感染者が前週の1.2倍になった", "key_phrase": "", "lens": "なし"}),
    (_news_prompt("地震後に「外国人窃盗団」のうわさ SNSで拡散、警察は事実確認できず", "(見出し以外の情報なし)"),
     {"facts": "地震の後、外国人窃盗団がいるといううわさがSNSで広まったが、警察は事実を確認できていない",
      "key_phrase": "警察は事実確認できず", "lens": "思い込みと噂"}),
]

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "string"},
        "key_phrase": {"type": "string"},
        "lens": {"type": "string", "enum": list(LENSES) + [NO_LENS]},
    },
    "required": ["facts", "key_phrase", "lens"],
}


def read_article(item: NewsItem) -> dict:
    """
    見出しを読ませる。論じるべき振る舞いが無ければ lens=なし。
    抜き出した語句(key_phrase)が見出しに実在するかを Python で照合し、無ければ「なし」とみなす
    (見出しの読み違いを、ここで機械的に止める)。
    """
    title, summary = _facts(item)
    lens_list = "\n".join(f"  {name}: {desc}" for name, (_, desc) in LENSES.items())
    data = _ollama_chat_json(READ_SYSTEM.format(lens_list=lens_list), READ_EXAMPLES,
                             _news_prompt(title, summary), READ_SCHEMA, JUDGE_OPTIONS, "read")
    for k in ("facts", "key_phrase"):
        data[k] = (data.get(k) or "").strip()
    if data.get("lens") != NO_LENS:
        key = _compact(data["key_phrase"])
        foreign = _ungrounded_kana(data["facts"], f"{title} {summary}")
        if len(key) < 2 or key not in _compact(f"{title}{summary}"):
            data["reason"] = "抜き出した語句が見出しに無い"
            data["lens"] = NO_LENS
        elif foreign:
            # 実例: 「ＪＰドラゴンのメンバー逮捕」を「J-POPグループのメンバーが逮捕」と読み違えた
            data["reason"] = f"言い直しに見出しに無い語がある(読み違いの疑い): {foreign}"
            data["lens"] = NO_LENS
    return data


# ---------------------------------------------------------------
# 2. 選ぶ
# ---------------------------------------------------------------
CANDIDATE_COUNT = 8

_SCENE_STOPWORDS = {
    "人間", "社会", "議論", "問題", "関係", "状況", "場合", "結果", "対応", "人々",
    "出来事", "事件", "変化", "行為", "態度", "意見", "判断", "見方", "一般",
}
_SCENE_TERM = re.compile(r"[一-龥々ァ-ヴー]{2,}")


def _scene_words(quote: dict) -> list:
    return [w for w in dict.fromkeys(_SCENE_TERM.findall(quote.get("scene", "")))
            if w not in _SCENE_STOPWORDS]





def _quote_relevance(quote: dict, lens_tag: str, themes: list, news_text: str) -> int:
    """
    LLM が挙げたレンズとの一致を最も重く見る(5点)。
    次にキーワードで判定した記事のテーマ(主テーマ3点・2番目2点・以降1点)、
    適用場面の語が見出しに出る数(1語2点、最大6点)。
    """
    score = 5 if lens_tag in quote["tags"] else 0
    for idx, theme in enumerate(themes):
        if theme in quote["tags"]:
            score += max(3 - idx, 1)
    score += 2 * min(sum(1 for w in _scene_words(quote) if w in news_text), 3)
    return score


def rank_quote_candidates(item: NewsItem, lens_tag: str, count: int = CANDIDATE_COUNT) -> list:
    """関連度の高い順に count 件(直近に使った箴言は除く)。同点は使用回数の少ない順。"""
    themes = getattr(item, "themes", None) or []
    title, summary = _facts(item)
    news_text = f"{title} {summary}"
    recent = set(load_recent_quote_ids())
    usage = load_quote_usage()
    pool = [q for q in QUOTES if q["id"] not in recent] or list(QUOTES)
    scored = [(_quote_relevance(q, lens_tag, themes, news_text), q) for q in pool]
    random.shuffle(scored)
    scored.sort(key=lambda sq: (-sq[0], usage.get(sq[1]["id"], 0)))
    return [q for _, q in scored[:count]]


CHOOSE_PROMPT = """新聞のコラムで、ニュースの後にモンテーニュ『エセー』の一節を引く。

出来事: {facts}
とくに目に留まる語句: {key_phrase}

候補(場面は、その一節が当てはまる場面の目安):
{candidates}

それぞれの候補が、この出来事、とくに「目に留まる語句」に表れた人の振る舞いと、どれだけ響き合うかを採点せよ。
  3: 言っている中身が、この振る舞いの構図にぴったり当てはまる
  2: はっきり当てはまる
  1: 言葉や話題が少し重なるだけ
  0: 当てはまらない、または出来事の後に続けると、亡くなった人・被害に遭った人・その家族を責めたり嘲ったりする響きになる
scores に候補の順で点数を入れ、reason に、いちばん点の高い候補と出来事の共通点を20〜40字で書け。"""

QUOTE_MIN_SCORE = 2  # これ未満しか無ければ、箴言が合わないとして見送る


def choose_quote(item: NewsItem, reading: dict):
    """
    候補を1件ずつ採点させ、最高点の一節を選ぶ(同点は Python の関連度順)。
    「1つ選べ」と頼むと小型モデルはほとんど「どれも合わない」と答えないため、採点にして
    QUOTE_MIN_SCORE 未満しか無ければ見送る。
    """
    lens_tag = LENSES[reading["lens"]][0]
    candidates = rank_quote_candidates(item, lens_tag)
    listing = "\n".join(f"{i}. {q['ja']}(場面: {q['scene']})" for i, q in enumerate(candidates, 1))
    n = len(candidates)
    schema = {"type": "object",
              "properties": {"scores": {"type": "array", "minItems": n, "maxItems": n,
                                        "items": {"type": "integer", "minimum": 0, "maximum": 3}},
                             "reason": {"type": "string"}},
              "required": ["scores", "reason"]}
    data = _ollama_json(CHOOSE_PROMPT.format(facts=reading["facts"], key_phrase=reading["key_phrase"],
                                             candidates=listing),
                        schema, JUDGE_OPTIONS, "choose")
    scores = [x if isinstance(x, int) else 0 for x in data.get("scores", [])][:n]
    LAST_TRACE["quote_candidates"] = [(q["id"], sc) for q, sc in zip(candidates, scores)]
    LAST_TRACE["quote_reason"] = data.get("reason")
    if not scores or max(scores) < QUOTE_MIN_SCORE:
        return None
    return candidates[scores.index(max(scores))]


# ---------------------------------------------------------------
# 3. 書く
# ---------------------------------------------------------------
# 【導入の一文という役割(第3版)】
# 第2版では「人間一般についての洞察」を LLM に考えさせたが、9Bのモデルでは凡庸か、理屈が逆か、
# 不当な皮肉になった(実例: 子どもの発達支援のリハビリを「専門用語で正当化しようとする」と皮肉った)。
# 洞察は原典照合済みのモンテーニュ本人の言葉に任せ、LLM には、その一節の前に置く導入として、
# 見出しの出来事を正確に言い直させる。どこに光を当てるか(語順・語の選び方)だけを工夫させ、
# 評価・一般論は書かせない。皮肉は、事実と一節を並べたときに生まれる。
#
# 手本。架空の見出しと、実際の箴言の組み合わせ。分析文がこれらを写していないかも検査する。
EXAMPLES = [
    {
        "title": "市役所、窓口の押印を全廃へ 長年の慣行を見直し",
        "key_phrase": "長年の慣行を見直し",
        "quote_id": "I.23a",
        "sentence": "市役所が、長年の慣行として続いてきた窓口の押印を見直し、全廃するという。",
    },
    {
        "title": "粉飾決算の元社長に有罪判決 「会社のためだった」と主張",
        "key_phrase": "「会社のためだった」と主張",
        "quote_id": "II.16",
        "sentence": "粉飾決算で有罪判決を受けた元社長は、それでも『会社のためだった』と主張しているという。",
    },
    {
        "title": "AIで新薬候補を発見 開発期間を半分に短縮と研究チーム",
        "key_phrase": "開発期間を半分に短縮",
        "quote_id": "II.17d",
        "sentence": "研究チームは、AIで新薬の候補を見つけ、開発期間を半分に短縮したと発表した。",
    },
    {
        "title": "地震後に「外国人窃盗団」のうわさ SNSで拡散、警察は事実確認できず",
        "key_phrase": "警察は事実確認できず",
        "quote_id": "III.11b",
        "sentence": "地震の後、外国人窃盗団のうわさがSNSで拡散したが、警察はその事実を確認できていないという。",
    },
]

WRITE_SYSTEM = """新聞の小さなコラムで、ニュースの後にモンテーニュ『エセー』の一節を引く。
その一節の前に置く、導入の一文を JSON で答える。

- 見出しの出来事を、見出しの言葉を生かして一文で言い直す。渡された「語句」は必ず使う
- 一節と響き合う点が読者の目に留まるように、語順と言葉の選び方を工夫する
- 見出しに無い事情・感情・行動・場所・数字は書かない
- 自分の評価や教訓、人間一般についての言葉(「人は〜」「我々は〜」)は書かない。それは一節に任せる
- 一節の言葉を言い換えて繰り返さない
- だ・である調か「〜という。」で結ぶ、40〜80字の一文"""

WRITE_SCHEMA = {"type": "object", "properties": {"sentence": {"type": "string"}}, "required": ["sentence"]}
WRITE_SAMPLES = 3   # 同じ問いを3回、毎回ちがう乱数で書かせる(手本と問いが同じなので2回目以降は速い)


def _write_prompt(title: str, key_phrase: str, quote_ja: str) -> str:
    return f"見出し: {title}\n語句: {key_phrase}\n一節: {quote_ja}"


def write_candidates(item: NewsItem, reading: dict, quote: dict) -> list:
    title, _ = _facts(item)
    examples = [(_write_prompt(e["title"], e["key_phrase"], QUOTES_BY_ID[e["quote_id"]]["ja"]),
                 {"sentence": e["sentence"]}) for e in EXAMPLES]
    user = _write_prompt(title, reading["key_phrase"], quote["ja"])
    out = []
    for _ in range(WRITE_SAMPLES):
        data = _ollama_chat_json(WRITE_SYSTEM, examples, user, WRITE_SCHEMA, WRITE_OPTIONS, "write")
        text = (data.get("sentence") or "").strip()
        if text and text not in out:
            out.append(text)
    return out


# ---------------------------------------------------------------
# 4. 確かめる
# ---------------------------------------------------------------
_JA = r"[぀-ヿ㐀-鿿々ー]"
_SPACE_AROUND_ASCII = re.compile(rf"(?<={_JA})[ 　]+(?=[A-Za-z0-9])|(?<=[A-Za-z0-9])[ 　]+(?={_JA})")
MIN_CHARS, MAX_CHARS = 30, 90
# 指示の言葉が本文に漏れたもの(実例: 「見出しに記された逮捕の事実と…」「振る舞いとして現れた行動からは…」)
_META_WORDS = re.compile(r"(見出し|振る舞い|語句|一節|材料|観察|エセー|モンテーニュ)")
# 導入の一文に、評価・一般論を書いたもの(それは一節に任せる)
_GENERAL_WORDS = re.compile(r"(人は|人間は|人々は|我々は|われわれは|私たちは|ものだ|ものである|ものなのだ|に他ならない|にほかならない)")
_CONTENT_WORD = re.compile(r"[一-龥々]{2,}|[ァ-ヴー]{2,}|[A-Za-z0-9]{2,}")


# 見出しに無くても使ってよい漢字1字(一般的な動詞・助数詞・位置など)と漢語
_NEUTRAL_KANJI = set("中件際後前今同側者人方上下的性化等内外間度時日年月行取入示見言語述求受出決進続始持使得伝報向呼名続")
_NEUTRAL_WORDS = {"可能性", "発表", "報道", "事件", "一方", "今回", "場合", "以上", "以下", "対象",
                  "問題", "発生", "子供", "子ども"}


def _ungrounded_kanji(text: str, source: str) -> list:
    """
    text に出てくる漢字の連なりのうち、source(見出し・概要)の語で組み立てられないものを返す。
    見出しの部分文字列を長い順に当てはめていき、余った1字が見出しにも _NEUTRAL_KANJI にも
    無ければ「見出しに無い漢語」とする(例: 見出しに無い「関与」「巨額」)。
    漢字1字だけの連なり(「対し」「訴え」「促す」のような動詞の語幹など)は対象にしない。
    動詞による事実の付け加えは、verify_claims(主張の抜き出しと照合)が受け持つ。
    """
    src = _compact(source)
    missing = []
    for run in re.findall(r"[一-龥々]+", _compact(text)):
        if len(run) == 1 or run in src or run in _NEUTRAL_WORDS:
            continue
        i, ok = 0, True
        while i < len(run):
            for size in range(len(run) - i, 1, -1):
                if run[i:i + size] in src or run[i:i + size] in _NEUTRAL_WORDS:
                    i += size
                    break
            else:
                if run[i] in src or run[i] in _NEUTRAL_KANJI:
                    i += 1
                else:
                    ok = False
                    break
        if not ok:
            missing.append(run)
    return missing


def _ungrounded_kana(text: str, source: str) -> list:
    """text のカタカナ語・英字のうち、source に無く、一般語でもないもの。"""
    src = me._normalize_for_match(source)
    src_kana = [k.strip("ー") for k in me._KATAKANA_RUN.findall(src) if len(k.strip("ー")) >= 3]
    missing = []
    for pattern in (me._KATAKANA_RUN, me._LATIN_RUN):
        for term in pattern.findall(me._normalize_for_match(text)):
            term = term.strip("ー・")
            if len(term) < 2 or term in _GENERIC_TERMS or term in src:
                continue
            if pattern is me._KATAKANA_RUN and any(term.startswith(k) for k in src_kana):
                continue
            missing.append(term)
    return missing


_KANJI_DIGITS = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_NUM_RUN = re.compile(r"[〇一二三四五六七八九十百千万億]{2,}")


def _kanji_number(run: str):
    """「四千六百万」→ 46000000。読めなければ None。"""
    total, section, digit = 0, 0, None
    for ch in run:
        if ch in _KANJI_DIGITS:
            if digit is not None:
                return None
            digit = _KANJI_DIGITS[ch]
        elif ch in "十百千":
            section += (digit if digit is not None else 1) * {"十": 10, "百": 100, "千": 1000}[ch]
            digit = None
        else:  # 万・億
            total += (section + (digit or 0)) * (10_000 if ch == "万" else 100_000_000)
            section, digit = 0, None
    return total + section + (digit or 0)


def _arabic_numbers(text: str, source: str) -> str:
    """
    小型モデルは見出しの算用数字を漢数字に書き換えがちである(「４６００万円」→「四千六百万円」)。
    見出しに算用数字で書かれている数に限って、算用数字に戻す。
    「百年に一度」のように見出しでも漢数字の言い回しは、そのまま残す。
    """
    src = _compact(source)

    def repl(m):
        run = m.group()
        if run in src:
            return run
        value = _kanji_number(run)
        if value is None:
            return run
        forms = [str(value)]
        if value >= 100_000_000 and value % 100_000_000 == 0:
            forms.insert(0, f"{value // 100_000_000}億")
        elif value >= 10_000 and value % 10_000 == 0:
            forms.insert(0, f"{value // 10_000}万")
        for f in forms:
            if f in src:
                return f
        return run
    return _KANJI_NUM_RUN.sub(repl, text)


def mechanical_check(text: str, item: NewsItem, quote: dict, reading: dict) -> str:
    """
    LLM を使わない検査。合格なら整えた文を返し、不合格なら ValueError。
    字数・一文か・説教口調・決まり文句・指示の言葉の混入・抜き出した語句への言及・
    箴言や手本の丸写し・見出しに無い固有名詞と数字。
    """
    text = _SPACE_AROUND_ASCII.sub("", text.strip())
    # 文全体が括弧でくくられているときだけ外す(文頭の引用「大ごとに…」の括弧は残す)
    if re.fullmatch(r"[「『][^「『」』]*[」』]", text):
        text = text[1:-1]
    text = text.replace("「", "『").replace("」", "』")  # 直後の引用の「」と紛れないように
    title, summary = _facts(item)
    text = _arabic_numbers(text, f"{title} {summary}")
    text = _validate_analysis(text)
    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        raise ValueError(f"字数が範囲外({len(text)}字)")
    if text.count("。") > 1:
        raise ValueError("一文になっていない")
    m = _META_WORDS.search(text)
    if m:
        raise ValueError(f"指示の言葉が混ざっている: {m.group()!r}")
    m = _GENERAL_WORDS.search(text)
    if m:
        raise ValueError(f"導入に評価・一般論を書いている: {m.group()!r}")
    words = [w for w in _CONTENT_WORD.findall(reading["key_phrase"]) if w not in {"する", "した"}]
    if words and not any(w in text for w in words):
        raise ValueError(f"見出しの語句({reading['key_phrase']})に触れていない")
    title, summary = _facts(item)
    _check_not_restating(text, quote["ja"])
    for e in EXAMPLES:
        _check_not_restating(text, e["sentence"])
    _check_grounded_terms(text, title, summary, quote["ja"])
    # 導入文は見出しの言い直しなので、漢語も見出しの語に限る(実例: 見出しに無い「関与」で誤報になった)
    foreign = _ungrounded_kanji(text, f"{title} {summary}")
    if foreign:
        raise ValueError(f"見出しに無い漢語を使っている: {foreign}")
    return text


CLAIMS_PROMPT = """次の文が、事実として述べている事柄を書き出せ。

- 「誰が何をした」「何が起きた」「何がどうなっている」という、確かめられる事柄だけを、短い文に分けて書く
- 書き手の評価・解釈・たとえ・一般論(「人は〜」「我々は〜」「〜らしい」「〜の癖」など)は書き出さない

例
文: 市役所が、長年の慣行として続いてきた窓口の押印を見直し、全廃するという。
答え: {{"claims": ["市役所が窓口の押印を見直す", "市役所が窓口の押印を全廃する", "押印は長年の慣行だった"]}}

文: {analysis}
答え:"""

CLAIMS_SCHEMA = {"type": "object",
                 "properties": {"claims": {"type": "array", "items": {"type": "string"}, "maxItems": 6}},
                 "required": ["claims"]}

SUPPORT_PROMPT = """あなたは新聞の校閲係である。

見出し: {title}
概要: {summary}

次の事柄それぞれについて、上の見出し・概要に書かれている、またはそこからそのまま言えるなら true、
見出し・概要に無い出来事・行動・様子・感情・数字を含むなら false を、同じ順に答えよ。

{claims}"""


def verify_claims(text: str, item: NewsItem) -> None:
    """
    下書きから事実の主張を抜き出し(評価・一般論は除く)、主張だけを、下書きを見せずに見出しと照らす
    (Chain-of-Verification の方式)。主張が一つも無い文は、記事に触れない一般論として落とす。
    """
    title, summary = _facts(item)
    claims = [c.strip() for c in _ollama_json(CLAIMS_PROMPT.format(analysis=text), CLAIMS_SCHEMA,
                                              JUDGE_OPTIONS, "claims").get("claims", []) if c.strip()]
    if not claims:
        raise ValueError("事実の主張が無い(記事に触れない一般論)")
    support_schema = {"type": "object",
                      "properties": {"supported": {"type": "array", "items": {"type": "boolean"},
                                                   "minItems": len(claims), "maxItems": len(claims)}},
                      "required": ["supported"]}
    listing = "\n".join(f"{i}. {c}" for i, c in enumerate(claims, 1))
    supported = _ollama_json(SUPPORT_PROMPT.format(title=title, summary=summary, claims=listing),
                             support_schema, JUDGE_OPTIONS, "support").get("supported", [])
    unsupported = [c for c, ok in zip(claims, supported) if ok is not True]
    if len(supported) != len(claims) or unsupported:
        raise ValueError(f"見出しから言えない主張: {unsupported or claims}")


# 文意・品位の判定は、候補同士を比べて選ばせる(はい/いいえの絶対判定は甘く、
# 「関文科相は…単にその言葉で評価している」のような意味の通らない文を通した)。
EDITOR_PROMPT = """あなたは新聞のコラムの編集者である。ニュースの後に、モンテーニュの一節を引く。

見出し: {title}
引く一節: {quote}

一節の前に置く導入の候補:
{candidates}

次の条件をすべて満たす候補の番号を、一節への導入として良い順に ranking に並べよ。
条件を満たさない候補は ranking に入れない。満たすものが一つも無ければ ranking は空にする。
- 日本語として自然で、一文として意味がまっすぐ通る
- 見出しの出来事を、見出しのとおりに正確に伝えている
- 一節と響き合う点が、読者の目に留まる"""

REVIEW_PROMPT = """あなたは新聞の校閲係である。ニュースの導入文の後に、モンテーニュの一節を引く。

見出し: {title}
導入文: {analysis}
引く一節: {quote}

次に答えよ。
coherent: 導入文は、一文として意味がまっすぐ通り、主語と述語が噛み合っているか
on_topic: 導入文は、見出しの出来事について述べているか
hurts_victims: 導入文と一節を続けて読むと、亡くなった人・被害に遭った人・被災した人・その家族を責めたり嘲ったりする響きになるか"""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "boolean"} for k in ("coherent", "on_topic", "hurts_victims")},
    "required": ["coherent", "on_topic", "hurts_victims"],
}


def review(text: str, item: NewsItem, quote: dict) -> None:
    title, _ = _facts(item)
    r = _ollama_json(REVIEW_PROMPT.format(title=title, analysis=text, quote=quote["ja"]), REVIEW_SCHEMA,
                     JUDGE_OPTIONS, "review")
    problems = [k for k, bad in (("文意が通らない", not r.get("coherent")),
                                 ("記事に沿っていない", not r.get("on_topic")),
                                 ("被害者を責める響き", r.get("hurts_victims"))) if bad]
    if problems:
        raise ValueError(f"校閲で不合格: {problems}")


def editor_order(texts: list, item: NewsItem, quote: dict) -> list:
    """
    機械的な検査を通った候補を、編集者に1回で順位付けさせる。条件を満たさない候補は
    順位に入れさせない(全部が駄目なら空)。順位の高い順に返す。
    """
    if not texts:
        return []
    title, _ = _facts(item)
    listing = "\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1))
    schema = {"type": "object",
              "properties": {"ranking": {"type": "array", "maxItems": len(texts),
                                         "items": {"type": "integer", "minimum": 1, "maximum": len(texts)}}},
              "required": ["ranking"]}
    ranking = _ollama_json(EDITOR_PROMPT.format(title=title, quote=quote["ja"], candidates=listing),
                           schema, JUDGE_OPTIONS, "editor").get("ranking", [])
    order = []
    for n in ranking:
        if isinstance(n, int) and 1 <= n <= len(texts) and texts[n - 1] not in order:
            order.append(texts[n - 1])
    LAST_TRACE.setdefault("editor", []).append({"options": list(texts), "ranking": ranking})
    return order


# ---------------------------------------------------------------
# 共用の検査部品(ベーコンボットも使う。名前と動作を変えないこと)
# ---------------------------------------------------------------
# 事実照合(ベーコンボットも共用する)。
# 以前は「人間の性についての観察・比喩・一般化は問題にしない」と書いていたため、
# 見出しに無い感情や行動(「日常の崩壊を恐れて避難所へと集まり」)まで「観察」として
# 通っていた。見出しに無い人の感情・動機・行動は事実の付け加えとして扱い、
# 意味の通らない文と、被害者を論評する文も落とす。
VERIFY_PROMPT = """あなたは新聞の校閲係である。
次の「分析文」を、「見出し」「概要」と照らし合わせて判定せよ。

見出し: {title}
概要: {summary}
分析文: {analysis}

次のどれか一つにでも当たれば「不適合」:
1. 見出し・概要の事実と矛盾している(主語と行為の取り違え、位置関係や因果の取り違えを含む)
2. 見出し・概要に書かれていない出来事・行為・場所・数字を付け加えている
3. 見出し・概要に書かれていない、特定の人々の感情・動機・行動を、事実のように書いている
   (例: 見出しに無いのに「人々は恐れて避難所へ集まった」と書く)
4. 亡くなった人、被害に遭った人、被災した人、その家族の性格や心の在り方・受け止め方を論評している
5. 主語と述語が噛み合わない、比喩が重なって意味が取れないなど、一文として意味が通らない

出来事に対する評価・解釈を述べているだけで、上のどれにも当たらなければ「適合」。

答えは「適合」か「不適合」の一語だけを書け。
"""

# 説教・提言の言い回し(人間観察に徹する視座に反するので不合格にする)
_SERMON_PATTERN = re.compile(
    r"(べきだ|べきである|べきであろう|べきなのだ|求められる|必要だ|必要である|必要がある|"
    r"ねばならない|ねばならぬ|なければならない|しなければ|しよう。|ましょう)"
)

# 見出しに無くても分析文に出てきてよい一般的なカタカナ語・英字
_GENERIC_TERMS = set(me._GENERIC_TERMS) | {
    "モンテーニュ", "エセー", "モラル", "エゴ", "ジレンマ", "ドラマ", "ヒューマン",
    "コミュニティ", "プライド", "ブーム", "パニック", "トラブル", "ストレス", "イメージ",
}


def _check_grounded_terms(analysis: str, title: str, summary: str, quote_text: str = "") -> None:
    """
    分析文のカタカナ語・英字・数字が見出し・概要(と箴言)に含まれるかを照合する。
    仕組みは machiavelli_engine._check_grounded_terms と同じで、
    許容する一般語だけをモンテーニュ用に広げている。
    """
    source = me._normalize_for_match(f"{title} {summary} {quote_text}")
    norm = me._normalize_for_match(analysis)
    # 見出しの略語を正式名で書いただけのもの(「インフル」→「インフルエンザ」)は作話ではない
    source_kana = [k.strip("ー") for k in me._KATAKANA_RUN.findall(source) if len(k.strip("ー")) >= 3]
    missing = []
    for pattern in (me._KATAKANA_RUN, me._LATIN_RUN, me._DIGIT_RUN):
        for term in pattern.findall(norm):
            term = term.strip("ー")
            if len(term) < 2 and pattern is not me._DIGIT_RUN:
                continue
            if term in _GENERIC_TERMS or term in source:
                continue
            if pattern is me._KATAKANA_RUN and any(term.startswith(k) for k in source_kana):
                continue
            missing.append(term)
    if missing:
        raise ValueError(f"見出し・概要に無い語句を含む(作話の疑い): {missing}")


# プロンプトの指示語をそのまま持ち込んだ、中身のない結び(ベーコンボットでの実例に倣う)
_JARGON_PATTERN = re.compile(r"(人間の性|性質を見せ|性を見せ|観察が見え|手がかり|人間観察)")


def _validate_analysis(text: str) -> str:
    """形式の検査(マキャベリ側と共通)に、説教口調と決まり文句の検査を加える。"""
    text = me._validate_analysis(text)
    if _SERMON_PATTERN.search(text):
        raise ValueError(f"説教・提言の言い回しを含む(人間観察の視座に反する): {text!r}")
    if _JARGON_PATTERN.search(text):
        raise ValueError(f"指示の言葉を写しただけの決まり文句に頼っている: {text!r}")
    return text


# 事実照合の2問目。1問目(5つの基準をまとめて判定)は同じ9Bモデルが判定するため、
# 見出しに無い人々の行動の書き足しを見逃すことがある。
# 実例(2026-11-03): 見出し「熊本 各地で9日も厳しい暑さに」に対し、2回は不適合と判定したが、
# 3回目の「住民が熱中症対策を続ける様子は」を通した。そこでこの一点だけを、
# 分析文から行動を書き出させたうえで問い直す。
ACTION_CHECK_PROMPT = """見出し: {title}
概要: {summary}
分析文: {analysis}

分析文に書かれている、人や組織の行動・様子(「〜した」「〜している」「〜を続ける」など)を、
すべて短く書き出せ。そのうえで、その中に、見出しにも概要にも書かれていないものが一つでもあるかを判定せよ。

最後の行に「判定: ある」か「判定: ない」のどちらかだけを書け。
"""


def _verify_with_ollama(host: str, model: str, analysis: str, title: str, summary: str) -> None:
    verdict = me._ollama_generate(
        host, model,
        VERIFY_PROMPT.format(title=title, summary=summary, analysis=analysis),
        {"temperature": 0.0, "top_k": 1, "num_predict": 16},
    )
    if "不適合" in verdict:
        raise ValueError(f"事実照合で不適合と判定された: {analysis!r}")
    if "適合" not in verdict:
        print(f"[分析文] 事実照合の判定を読み取れず、通過させました: {verdict!r}")

    answer = me._ollama_generate(
        host, model,
        ACTION_CHECK_PROMPT.format(title=title, summary=summary, analysis=analysis),
        {"temperature": 0.0, "top_k": 1, "num_predict": 200},
    )
    m = re.search(r"判定\s*[:：]\s*(ある|ない)", answer)
    if m and m.group(1) == "ある":
        raise ValueError(f"見出しに無い行動を書き足している: {analysis!r}")
    if not m:
        print(f"[分析文] 行動の照合の判定を読み取れず、通過させました: {answer[-60:]!r}")


def _check_not_restating(analysis: str, quote_text: str, run: int = 10) -> None:
    """
    分析文が、添える箴言の文言を丸写ししていないかを調べる。
    箴言の中の連続する run 字(句読点を除く)が分析文にそのまま現れたら不合格にする。
    (実例: 分析文の後半が「財の貧しさは癒やしやすいが、魂の貧しさは癒やしようがない」と
    箴言をそのまま繰り返し、直後の引用と同じ文が二度並んだ)
    """
    strip = lambda t: re.sub(r"[、。「」『』・,. ]", "", t)
    a, q = strip(analysis), strip(quote_text)
    for i in range(0, max(len(q) - run + 1, 0)):
        if q[i:i + run] in a:
            raise ValueError(f"箴言の文言を繰り返している: {q[i:i + run]!r}")


# ---------------------------------------------------------------
# 本文の組み立て
# ---------------------------------------------------------------
BODY_MAX_CHARS = 260  # 箴言が長めで章題も付くため、マキャベリ側(250)より少し長く取る


def _assemble_body(analysis: str, quote: dict, max_chars: int = BODY_MAX_CHARS) -> str:
    """分析文・箴言・出典を結合する。上限を超えたら削るのは分析文だけ。"""
    citation = source_label(quote)
    quote_line = f"「{quote['ja']}」"
    fixed_len = len(quote_line) + len(citation) + 2
    if len(analysis) + 1 + fixed_len > max_chars:
        analysis = me._trim_japanese(analysis, max(max_chars - fixed_len - 1, 20))
    return f"{analysis}\n{quote_line}\n{citation}"


# ---------------------------------------------------------------
# 全体
# ---------------------------------------------------------------
WRITE_ROUNDS = 2   # 1回目の候補がすべて事実確認で落ちたら、もう一度だけ書かせる


def generate_commentary(item: NewsItem, prefer_llm: bool = True, max_chars: int = BODY_MAX_CHARS):
    """
    論評を組み立てて返す。掲載できる文が得られなければ None(理由は LAST_TRACE["result"])。
    掲載する1件についてだけ、箴言の使用履歴を記録する。
    """
    global LAST_QUOTE_ID, LAST_QUOTE_CHOICE, LAST_ANALYSIS_SOURCE
    LAST_TRACE.clear()
    LAST_QUOTE_ID = LAST_QUOTE_CHOICE = LAST_ANALYSIS_SOURCE = None
    _, model = _ollama_env()

    def give_up(reason: str):
        LAST_TRACE["result"] = reason
        print(f"[見送り] {reason}")
        return None

    if not prefer_llm:
        return give_up("LLMを使わない設定")
    try:
        reading = read_article(item)
    except Exception as e:
        return give_up(f"読む工程で失敗: {e}")
    LAST_TRACE["reading"] = reading
    print(f"[読む] {reading}")
    if reading.get("lens") == NO_LENS:
        return give_up(f"論じるべき人の振る舞いが見出しに無い({reading.get('reason', 'LLMの判断')})")

    try:
        quote = choose_quote(item, reading)
    except Exception as e:
        return give_up(f"選ぶ工程で失敗: {e}")
    if quote is None:
        return give_up("人について言えることに合う箴言が候補に無い")
    LAST_TRACE["quote"] = quote["id"]
    print(f"[選ぶ] {quote['id']} {quote['ja'][:40]}")

    LAST_TRACE["candidates"] = []
    adopted = None
    for rnd in range(1, WRITE_ROUNDS + 1):
        try:
            drafts = write_candidates(item, reading, quote)
        except Exception as e:
            LAST_TRACE["candidates"].append({"round": rnd, "text": None, "verdict": f"書く工程で失敗: {e}"})
            continue
        records, clean = {}, []
        for draft in drafts:
            record = {"round": rnd, "text": draft}
            LAST_TRACE["candidates"].append(record)
            try:
                text = mechanical_check(draft, item, quote, reading)
            except ValueError as e:
                record["verdict"] = str(e)
                continue
            record["verdict"] = "機械検査は合格(編集待ち)"
            records[text] = record
            clean.append(text)
        # 編集者が良いと選んだ順に、事実確認と校閲にかける。最初に通ったものを採る
        try:
            for text in editor_order(clean, item, quote):
                try:
                    verify_claims(text, item)
                    review(text, item, quote)
                except ValueError as e:
                    records[text]["verdict"] = str(e)
                    continue
                records[text]["verdict"] = "合格"
                adopted = text
                break
        except Exception as e:
            return give_up(f"確かめる工程で失敗: {e}")
        for t in clean:
            if records[t]["verdict"].startswith("機械検査は合格"):
                records[t]["verdict"] = "編集で選ばれず"
        if adopted:
            break
    if adopted is None:
        return give_up("検査を通る導入文が無かった")
    text = adopted

    print(f"[採用] {text}")
    LAST_QUOTE_ID, LAST_QUOTE_CHOICE = quote["id"], "llm"
    LAST_ANALYSIS_SOURCE = f"ollama:{model}"
    LAST_TRACE["result"] = "掲載"
    LAST_TRACE["adopted"] = text
    body = _assemble_body(text, quote, max_chars)
    record_quote_usage(quote["id"])
    return me._prepend_source_link(body, item)
