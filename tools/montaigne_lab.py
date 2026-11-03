# -*- coding: utf-8 -*-
"""
tools/montaigne_lab.py
-----------------------
モンテーニュボットの試験環境。掲載はしない(フィード・既出記事・箴言の使用履歴に書き込まない)。

過去に問題の出た見出し(FIXED_CASES)と、いま配信されている記事の上位(--live 件)について、
読む→選ぶ→書く→確かめる の全工程を実行し、途中経過をすべて表示する。
GitHub Actions(.github/workflows/montaigne-lab.yml)で、記事を --shards 個に分けて並列に動かす。

使い方:
    python -u tools/montaigne_lab.py --shard 0 --shards 4 --live 8
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import montaigne_engine as mtg                         # noqa: E402
from geopolitical_scorer import NewsItem, clean_news_text, is_japanese  # noqa: E402
from montaigne_scorer import load_scoring_config, rank_news, score_item  # noqa: E402
import generate_montaigne_feed as gen                  # noqa: E402

# 過去の実行で問題が出た見出し(配信されたままの形)。
FIXED_CASES = [
    ("特殊詐欺グループトップの男逮捕、高齢女性４人から５６０万円盗んだ疑い…５００人が２２億円被害か - 読売新聞",
     "被害者の人柄を論評した(2026-11-02)"),
    ("ＪＰドラゴンのメンバー逮捕 フィリピン入管、幹部か：時事ドットコム - 時事ドットコム",
     "「決まりが人を縛る」の空論しか出なかった(2026-11-03)"),
    ("がんを撃退する「遺伝子改変T細胞療法」をAIで改良 - Yahoo!ニュース",
     "手がかりの文を丸写しした(2026-11-03)"),
    ("社説：インフル流行の長期化 拡大警戒し対策の徹底を - 毎日新聞",
     "「行動範囲を拡張する性質」という意味の通らない文(2026-11-02)"),
    ("辺野古沖転覆事故 学校法人同志社の記者会見は「ようやく行われた」と関文科相 - 産経ニュース",
     "動機の作話と文法の崩れ(2026-11-02)"),
    ("給食費など徴収怠った職員、「大ごとにしたくない」校長と計４６００万円を私費で補填…市教委は引き続き穴埋め求める - 読売新聞",
     "第1回試験で、指示の言葉が混ざった文が通った"),
    ("画期的新薬「ダラクソンラシブ」に高まる期待 「百年に一度の薬」と絶賛されるも、日本で保険診療として承認されるためには“高すぎる薬価”の壁(マネーポストWEB) - Yahoo!ファイナンス",
     "第2版で、意味の通る候補が無いとされた"),
    ("［医療ルネサンス］攻めのリハビリ＜１＞遊びまじえ 子の発達支援 - 読売新聞",
     "第2版で、無害な取り組みを皮肉る文が通った(常識的に不適切)"),
    ("生命の起源巡る理論、彗星を契機とする定説が覆る可能性 新研究（CNN.co.jp） - Yahoo!ニュース",
     "第2版で、理屈が逆の文(「新たな発見に怯えて疑う」)が通った"),
    ("熊本地震 死者1人増える 災害関連死の疑い1人含め 死者39人に",
     "死者数の記事に死の箴言を添えた(2026-11-03)。現在は除外されるはず"),
]


def build_cases(live: int) -> list:
    cfg = load_scoring_config(gen.CONFIG_PATH)
    cases = []
    for title, note in FIXED_CASES:
        item = NewsItem(title=title, summary="", source="Google News 国内", url="https://news.google.com/lab")
        score_item(item, cfg["weights"], cfg["exclude_keywords"])
        cases.append({"item": item, "kind": "fixed", "note": note})
    if live > 0:
        items = gen.fetch_fresh(gen.CONFIG_PATH)
        ranked = rank_news(items, cfg["weights"], top_n=len(items), exclude_keywords=cfg["exclude_keywords"])
        ranked.sort(key=lambda it: (-it.score, it.title))
        known = {c["item"].title for c in cases}
        for it in ranked:
            if len([c for c in cases if c["kind"] == "live"]) >= live:
                break
            if it.title in known or it.score < cfg["minimum_score"] or not is_japanese(clean_news_text(it.title)):
                continue
            known.add(it.title)
            cases.append({"item": it, "kind": "live", "note": it.source})
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--live", type=int, default=8)
    args = ap.parse_args()

    mtg.record_quote_usage = lambda quote_id: None  # 試験では使用履歴を残さない

    cases = build_cases(args.live)
    mine = [c for i, c in enumerate(cases) if i % args.shards == args.shard]
    print(f"[試験] 全{len(cases)}件のうち、この分担は{len(mine)}件")
    report = []
    for c in mine:
        item = c["item"]
        print("\n" + "=" * 70)
        print(f"[記事] ({c['kind']}) {item.title}  score={item.score} themes={item.themes}")
        print(f"[備考] {c['note']}")
        row = {"kind": c["kind"], "title": item.title, "score": item.score, "themes": item.themes, "note": c["note"]}
        if item.score < 0:
            row["result"] = f"除外({item.matched_keywords})"
            print(f"[結果] {row['result']}")
            report.append(row)
            continue
        started = time.time()
        text = mtg.generate_commentary(item)
        row.update({"seconds": round(time.time() - started), "trace": dict(mtg.LAST_TRACE), "output": text})
        quote = mtg.QUOTES_BY_ID.get(mtg.LAST_TRACE.get("quote", ""))
        print(f"[結果] {mtg.LAST_TRACE.get('result')}({row['seconds']}秒)")
        if quote:
            print(f"[箴言] {quote['id']} {quote['ja']}")
        for cand in mtg.LAST_TRACE.get("candidates", []):
            print(f"  - {cand.get('text')}\n      → {cand.get('verdict')}")
        if mtg.LAST_TRACE.get("quote_candidates"):
            print(f"  [箴言の採点] {mtg.LAST_TRACE['quote_candidates']} 理由: {mtg.LAST_TRACE.get('quote_reason')}")
        for ed in mtg.LAST_TRACE.get("editor", []):
            print(f"  [編集] 候補{len(ed.get('options', []))}件の順位 {ed.get('ranking')}")
        calls = mtg.LAST_TRACE.get("calls", [])
        print(f"  [呼び出し] {len(calls)}回 " + " ".join(f"{c['step']}:{c['seconds']}s" for c in calls))
        if text:
            print("[掲載文]\n" + text.split("\n", 1)[-1])
        report.append(row)

    print("\n<<<LAB_REPORT_JSON")
    print(json.dumps(report, ensure_ascii=False))
    print("LAB_REPORT_JSON>>>")


if __name__ == "__main__":
    main()
