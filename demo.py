# -*- coding: utf-8 -*-
"""
demo.py
--------
実際の直近ニュース(2026年7月時点の台湾情勢・日中緊張・米中覇権競争)を
サンプルデータとして与え、選別→分析→つぶやき生成の一連の流れを
ネットワーク接続無しで確認するためのデモスクリプト。

実運用では news_fetcher.py が RSS から自動取得したデータに置き換わる。
"""

from geopolitical_scorer import NewsItem, load_weights, rank_news
from machiavelli_engine import generate_commentary_template

SAMPLE_NEWS = [
    NewsItem(
        title="高市首相、国会答弁で台湾有事に言及「逃げれば同盟崩壊」",
        summary="首相が台湾有事の際の対応について踏み込んだ発言をし、中国が反発。"
                "中国政府は自国民に日本への渡航自粛を呼びかけ、対中事業を展開する日本企業の株価が下落した。",
        source="国内政治/外交報道",
    ),
    NewsItem(
        title="中国、台湾包囲を見据えた軍備増強を継続",
        summary="人民解放軍は台湾封鎖・隔離能力を継続的に強化。ミサイル・軍用機・"
                "米軍の介入阻止を狙う兵器体系の整備を進め、威圧戦略を下支えしている。",
        source="Bloomberg",
    ),
    NewsItem(
        title="米台関係、内政のもつれと関税・防衛費交渉で不安定化",
        summary="台湾は米国への依存度が高いにもかかわらず、内政の分裂により結束を欠く。"
                "貿易・防衛費・対中交渉を巡る複雑な問題が米台関係を揺さぶっている。",
        source="Bloomberg",
    ),
    NewsItem(
        title="トランプ政権、関税政策で既存の自由貿易体制を揺さぶる",
        summary="第2次トランプ政権は国際安全保障体制への関与を弱めつつ、"
                "大規模な関税政策を展開。パクス・アメリカーナの限界が指摘されている。",
        source="PwC地政学リスク展望2026",
    ),
    NewsItem(
        title="中国とロシア、覇権主義への反対とパートナーシップ強化を共同声明",
        summary="中露両国が既存の国際秩序への異議を共同声明として発表し、連携強化を確認した。",
        source="経済安保ニュース",
    ),
]


def main():
    weights = load_weights("config.yaml")
    ranked = rank_news(SAMPLE_NEWS, weights, top_n=len(SAMPLE_NEWS))

    print("=" * 70)
    print("地政学的重要度ランキング(マキャベリ的基準: 力の実相を最重視)")
    print("=" * 70)
    for i, item in enumerate(ranked, 1):
        print(f"{i}. [score={item.score:>2}] [theme={item.theme}] {item.title}")
        print(f"   キーワード一致: {', '.join(item.matched_keywords) if item.matched_keywords else 'なし'}")
    print()

    print("=" * 70)
    print("生成されたつぶやき(上位3件・templateモード)")
    print("=" * 70)
    for item in ranked[:3]:
        tweet = generate_commentary_template(item)
        print(f"\n--- 元記事: {item.title} [{item.source}] ---")
        print(tweet)
        print(f"(文字数: {len(tweet)})")


if __name__ == "__main__":
    main()
