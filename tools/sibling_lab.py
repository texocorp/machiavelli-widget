# -*- coding: utf-8 -*-
"""
tools/sibling_lab.py
---------------------
マキャベリ・ベーコンのボットの試験環境。掲載はしない(フィード・既出記事・箴言の使用履歴に書き込まない)。

実際に掲載された見出し(CASES)について、本番と同じ generate_commentary を実行し、
掲載される文か見送りかを表示する。2026-11-04 に入れた検査(事実の照合・校閲・テンプレートの廃止)の
効き目と、見送りが増えすぎないかを確かめるためのもの。

使い方:
    python -u tools/sibling_lab.py --shard 0 --shards 4
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import machiavelli_engine as me                         # noqa: E402
import bacon_engine as be                               # noqa: E402
from geopolitical_scorer import NewsItem, score_item, load_scoring_config  # noqa: E402

# (ボット, 見出し, 備考)。見出しは配信されたままの形。
CASES = [
    ("machiavelli", "ロシア、ウクライナのエネ施設に大規模攻撃　米仲介の3者協議再開控え - ｄメニューニュース",
     "「米仲介を避ける姿勢」と読み違えた(2026-11-04)"),
    ("machiavelli", "米軍がイランの島を攻撃 中間選挙前日「限定的空爆」 - テレ朝NEWS", "掲載済み"),
    ("machiavelli", "トランプ氏、中間選挙直後のイラン再攻撃は否定 バンス氏も交渉明言 - 日本経済新聞", "掲載済み"),
    ("machiavelli", "露統計局にサイバー攻撃、ハッカー集団が主張 ウクライナ侵攻の軍損失情報取得か - 産経ニュース", "掲載済み"),
    ("machiavelli", "迫り来るイラン戦争「第3幕」の足音、米中間選挙の後に何が起こるのか？ - JBpress",
     "「米国の野心が…昇華し」と見出しに無いことを書いた"),
    ("machiavelli", "米条件受け入れ兆候か イラン主張 再攻撃受ければ核製造や保有の基本方針変更も示唆 - テレ朝NEWS", "掲載済み"),
    ("machiavelli", "トランプ大統領「ピックアックス山」攻撃示唆 「10分で対処できる」軍事攻撃の計画を示し交渉有利に - Yahoo!ニュース", "掲載済み"),
    ("machiavelli", "ルビオ米国務長官「イラン再攻撃は未決定」 対話の継続に軸足 - 日本経済新聞", "掲載済み"),
    ("bacon", "アスリートをネットの誹謗中傷からどう守るか？ 東大などが競技活動への影響を徹底検証（スポーティングニュース日本版） - Yahoo!ニュース",
     "テンプレートで崩れた文、内容も逆(2026-11-04)"),
    ("bacon", "ラーメン店「蔦」大西祐貴さん死因めぐる“誤情報”に注意喚起「どうか事実と異なる情報の拡散ではなく…」 - 山陽新聞",
     "テンプレートで崩れた文"),
    ("bacon", "ＳＮＳで揺らぐ表現の自由 偽情報拡散、自主規制難しく―識者「国が情報空間に関与を」・憲法公布８０年 - 時事ドットコム",
     "テンプレートで崩れた文"),
    ("bacon", "GMO熊谷代表「認知戦、心理戦、陽動作戦」投稿の真意は？「最初の7〜8つが全体の流れを作る」SNS炎上の“仕掛け”を独自分析（ABEMA TIMES） - Yahoo!ニュース", "掲載済み"),
    ("bacon", "アラブ連盟、偽情報およびAI生成の虚偽コンテンツへの共同対策を呼びかけ - アラブニュース",
     "「冷徹な観察が見える」と指示の言葉が混ざった"),
    ("bacon", "（世論調査 タテ軸ヨコ軸）ＳＮＳ重視層の「高市推し」陰り - 朝日新聞", "掲載済み"),
    ("bacon", "次世代のAI「AIエージェント」とは－従来の生成AIとの違いを分かりやすく解説 - ニッセイ基礎研究所", "テンプレートで崩れた文"),
    ("bacon", "「無断生成AI」反対表明してた声優が自身のSNSで生成AIイラスト公開で波紋 - ｄメニューニュース", "テンプレートで崩れた文"),
]


def build_item(bot: str, title: str) -> NewsItem:
    item = NewsItem(title=title, summary="", source="Google News", url="https://news.google.com/lab")
    if bot == "machiavelli":
        cfg = load_scoring_config("config.yaml")
        score_item(item, cfg["weights"], cfg["exclude_keywords"])
    else:
        import bacon_scorer
        cfg = bacon_scorer.load_scoring_config(os.path.join(os.path.dirname(be.__file__), "bacon_config.yaml"))
        bacon_scorer.rank_news([item], cfg["weights"], top_n=1, exclude_keywords=cfg["exclude_keywords"],
                               discourse_keywords=cfg["discourse_keywords"],
                               priority_sources=cfg["priority_sources"], priority_bonus=cfg["priority_bonus"])
    if not getattr(item, "themes", None):
        item.themes = [item.theme] if getattr(item, "theme", None) else []
    return item


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    args = ap.parse_args()

    me.record_quote_usage = lambda quote_id: None  # 試験では使用履歴を残さない
    be.record_quote_usage = lambda quote_id: None

    mine = [c for i, c in enumerate(CASES) if i % args.shards == args.shard]
    print(f"[試験] 全{len(CASES)}件のうち、この分担は{len(mine)}件")
    report = []
    for bot, title, note in mine:
        print("\n" + "=" * 70)
        print(f"[記事] ({bot}) {title}")
        print(f"[備考] {note}")
        item = build_item(bot, title)
        engine = me if bot == "machiavelli" else be
        started = time.time()
        try:
            text = engine.generate_commentary(item, prefer_llm=True)
        except Exception as e:  # 試験なので、例外も結果として記録する
            text = None
            print(f"[例外] {type(e).__name__}: {e}")
        secs = round(time.time() - started)
        print(f"[結果] {'掲載' if text else '見送り'}({secs}秒) 箴言={engine.LAST_QUOTE_ID}")
        if text:
            print("[掲載文]\n" + text.split("\n", 1)[-1])
        report.append({"bot": bot, "title": title, "note": note, "seconds": secs, "output": text})

    print("\n<<<LAB_REPORT_JSON")
    print(json.dumps(report, ensure_ascii=False))
    print("LAB_REPORT_JSON>>>")


if __name__ == "__main__":
    main()
