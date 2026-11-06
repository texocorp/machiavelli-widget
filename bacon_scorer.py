# -*- coding: utf-8 -*-
"""
bacon_scorer.py
----------------
世論・メディア・言説、科学技術・AI・研究政策のニュースを、ベーコンボット向けに
スコアリングし、引用テーマ(data/bacon_quotes.json の tags)に分類する。

記事のデータ構造(NewsItem)・見出しの清掃・キーワード照合・設定の読み込みは、
マキャベリボットとモンテーニュボットの部品をそのまま使う。

【選別の考え方】
ベーコンは『ノヴム・オルガヌム』で、人間の知性を欺く四つのイドラ
(種族・洞窟・市場・劇場)を数え上げ、同時に「知は力なり」として、
技術と学問が人間の支配力を決めると説いた。そこで
 - 言葉・噂・世論・偽情報が人を惑わす出来事(イドラが働く現場)
 - 技術・研究が社会の力関係を変える出来事(知が力となる現場)
を重く見る。
"""

import yaml

from geopolitical_scorer import NewsItem  # noqa: F401
from montaigne_scorer import keyword_hit, _topic_text  # noqa: F401


def load_scoring_config(config_path: str = "bacon_config.yaml") -> dict:
    """montaigne_scorer の読み込みに、言説の語と優先する配信元を加えたもの。"""
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    prio = cfg.get("priority_sources", {}) or {}
    return {
        "weights": cfg["scoring_weights"],
        "exclude_keywords": cfg.get("exclude_keywords", []),
        "minimum_score": cfg.get("selection", {}).get("minimum_score", 1),
        "discourse_keywords": cfg.get("discourse_keywords", []),
        "priority_sources": set(prio.get("names", [])),
        "priority_bonus": prio.get("bonus", 0),
    }


# ---------------------------------------------------------------
# テーマ分類
# ---------------------------------------------------------------
# 上から順に優先する(先頭に当たったものが主テーマ)。
# 欺き・迷信・言葉といった、イドラが露骨に働く具体的な出来事を先に判定し、
# 技術・研究・変化といった一般的なシグナルを後に回す。
# 考え方はマキャベリ側の TOPIC_PRIORITY、モンテーニュ側の THEME_PRIORITY と同じ。
THEME_PRIORITY = [
    "simulatio",
    "superstitio",
    "fori",
    "fama",
    "theatri",
    "experientia",
    "potentia",
    "studium",
    "novitas",
    "specus",
    "tribus",
]

DEFAULT_THEME = "tribus"  # どれにも当たらないときは「人間に共通する知性の癖」

THEME_KEYWORDS = {
    "simulatio": [
        "偽情報", "誤情報", "フェイク", "ディープフェイク", "なりすまし", "捏造", "ねつ造",
        "改ざん", "隠蔽", "虚偽", "粉飾", "ステマ", "情報操作", "世論工作", "詐欺", "偽装",
        "論文不正", "研究不正", "不正",
    ],
    "superstitio": [
        "陰謀論", "予言", "占い", "疑似科学", "ニセ科学", "霊感", "オカルト", "都市伝説",
        "迷信", "スピリチュアル", "デマ",
    ],
    "fori": [
        "言葉", "用語", "呼称", "名称", "レッテル", "流行語", "失言", "発言", "言い換え",
        "定義", "表現", "キャッチフレーズ", "ヘイトスピーチ", "差別発言", "造語",
    ],
    "fama": [
        "世論", "世論調査", "報道", "メディア", "SNS", "炎上", "拡散", "噂", "風評",
        "評判", "誹謗中傷", "バッシング", "投稿", "記者会見", "広報", "トレンド", "バズ",
        "ファクトチェック", "支持率", "インフルエンサー", "ネット",
    ],
    "theatri": [
        "専門家", "権威", "通説", "定説", "学説", "イデオロギー", "前例", "有識者", "学会",
        "理論", "主義", "教授", "常識",
    ],
    "experientia": [
        "実験", "検証", "治験", "臨床試験", "データ", "観測", "再現", "エビデンス", "根拠",
        "試験", "測定", "分析", "調査結果",
    ],
    "potentia": [
        "AI", "人工知能", "生成AI", "半導体", "量子", "ロボット", "宇宙", "ロケット", "衛星",
        "原発", "核融合", "遺伝子", "ゲノム", "自動運転", "スパコン", "データセンター",
        "電力", "エネルギー", "技術覇権", "特許",
    ],
    "studium": [
        "研究", "研究者", "論文", "大学", "学術", "研究費", "科研費", "教育", "学校",
        "入試", "図書館", "学術会議", "博士", "読書", "教科書", "ノーベル",
    ],
    "novitas": [
        "新技術", "導入", "初めて", "世界初", "開発", "実用化", "革新", "イノベーション",
        "新型", "次世代", "規制", "改正", "解禁", "発見",
    ],
    "specus": [
        "世代", "若者", "高齢者", "業界", "立場", "分断", "価値観", "エコーチェンバー",
        "習慣", "依存", "スマホ",
    ],
    "tribus": [
        "不安", "思い込み", "錯覚", "偏見", "楽観", "悲観", "パニック", "誤解", "過信",
        "印象", "期待", "懸念", "想定外",
    ],
}


# 政治家・政党・選挙・支持率に関わる記事を見分ける語。
# 世論の動きそのものはこのボットの題材として残すが、こうした記事では、人を愚か・軽率・盲従と
# 評する響きの引用(data/bacon_quotes.json の avoid_in_politics)を候補から外す。
# 実例: SNS重視層の首相支持の陰りを報じた世論調査に、「人間の本性には賢者よりも愚者の部分が多い」
# が添えられ、特定の政治家の支持層を愚かだと評しているように読めた。
POLITICAL_KEYWORDS = [
    "支持率", "世論調査", "推し", "首相", "内閣", "政権", "政党", "与党", "野党", "選挙",
    "候補", "議員", "知事", "市長", "投票", "有権者", "支持層", "支持者", "総理", "大臣",
]


def classify_themes(item: NewsItem) -> NewsItem:
    """記事が当たるテーマを全て拾い、item.themes(優先順位順)と item.theme(先頭)に設定する。"""
    text = _topic_text(item)
    themes = [t for t in THEME_PRIORITY
              if any(keyword_hit(kw, text) for kw in THEME_KEYWORDS[t])]
    item.themes = themes
    item.theme = themes[0] if themes else DEFAULT_THEME
    item.political = any(keyword_hit(kw, text) for kw in POLITICAL_KEYWORDS)
    return item


# ---------------------------------------------------------------
# スコアリング(仕組みは montaigne_scorer と同じ。分類だけをベーコン用に差し替える)
# ---------------------------------------------------------------
def score_item(item: NewsItem, weights: dict, exclude_keywords: list = None,
               discourse_keywords: list = None, priority_sources: set = None,
               priority_bonus: int = 0) -> NewsItem:
    """
    キーワードの重みを合算する(high=4, medium=2, low=1)。
    - exclude_keywords に当たった記事は score=-1(除外)
    - discourse_keywords が与えられていて、その語を一つも含まない記事は score=0(素材にならない)
    - priority_sources の配信元の記事には priority_bonus を加点する
    """
    text = _topic_text(item)
    for ex in (exclude_keywords or []):
        if keyword_hit(ex, text):
            item.score = -1
            item.matched_keywords = [f"[除外理由: {ex}]"]
            item.theme = DEFAULT_THEME
            item.themes = []
            return item

    if discourse_keywords and not any(keyword_hit(w, text) for w in discourse_keywords):
        item.score = 0
        item.matched_keywords = ["[言説の語なし]"]
        item.theme = DEFAULT_THEME
        item.themes = []
        return item

    total, matched = 0, []
    for level, words in weights.items():
        pts = {"high": 4, "medium": 2, "low": 1}[level]
        for w in words:
            if keyword_hit(w, text):
                total += pts
                matched.append(w)
    # 言説の語そのものにも点を与える(1語2点)。2026-11-06 まで点数は話題の語(AI・研究など)だけで決まり、
    # 「街に広がる『排除アート』、大阪では物議に」「『合理性』は思い込みだった」のような、まさに
    # イドラの場面の記事が点数不足で外れていた(取得1185件のうち新しい候補は7件)。
    for w in (discourse_keywords or []):
        if w not in matched and keyword_hit(w, text):
            total += 2
            matched.append(w)
    if total > 0 and priority_sources and item.source in priority_sources:
        total += priority_bonus
        matched.append(f"[優先配信元 +{priority_bonus}]")
    item.score = total
    item.matched_keywords = matched
    return classify_themes(item)


def rank_news(items: list, weights: dict, top_n: int = 10, exclude_keywords: list = None,
              discourse_keywords: list = None, priority_sources: set = None,
              priority_bonus: int = 0) -> list:
    """スコア降順で並べ、上位 top_n 件を返す。"""
    scored = [score_item(i, weights, exclude_keywords, discourse_keywords,
                         priority_sources, priority_bonus) for i in items]
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:top_n]
