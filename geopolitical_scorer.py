# -*- coding: utf-8 -*-
"""
geopolitical_scorer.py
-----------------------
ニュース記事を「地政学的重要性」でスコアリングし、
マキャベリ的分析テーマ(quotes.json のキー)に分類するモジュール。

近現代のリベラルな規範(理想主義的な国際法秩序・主権平等の建前)ではなく、
古典的現実主義(勢力均衡・力の実相・恐怖/信義の道具性)の基準で重要度を測る。
すなわち「誰が誰に対して実効的な軍事的優位/依存関係を持つか」を最重要視する。
"""

import re
import yaml
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NewsItem:
    title: str
    summary: str
    source: str
    url: str = ""
    score: int = 0
    theme: Optional[str] = None
    matched_keywords: list = field(default_factory=list)


# ニュースのトピック→ quotes.json のテーマキーへのマッピング
TOPIC_THEME_MAP = {
    "military_alliance": "alleanze_dipendenza",   # 同盟・保護国・駐留・属国的依存
    "war_conflict": "guerra",                     # 戦争・武力衝突
    "deterrence_fear": "paura_amore",              # 抑止・威嚇・恐怖による統制
    "deception_diplomacy": "inganno_simulazione",  # 外交的欺瞞・二枚舌
    "empire_decline": "imperi_declino",            # 覇権の興亡・秩序の変化
    "domestic_populace": "popolo_principe",        # 世論・国内政治の移ろいやすさ
    "neutrality_choice": "neutralita",              # 中立という選択の是非
    "necessity_realpolitik": "necessita",           # 必要による正当化
    "military_selfreliance": "armi_proprie",        # 自前の軍事力 vs 傭兵/他国依存
    "fortune_timing": "fortuna_virtu",               # 好機・時勢の変化
}

# キーワード→トピック の粗いマッピング(スコアリング後、最尤テーマを推定)
KEYWORD_TOPIC_HINTS = {
    "米軍": "military_alliance", "駐留": "military_alliance", "基地": "military_alliance",
    "同盟": "military_alliance", "alliance": "military_alliance",
    "台湾有事": "war_conflict", "侵攻": "war_conflict", "戦争": "war_conflict",
    "invasion": "war_conflict", "war": "war_conflict", "封鎖": "war_conflict",
    "抑止": "deterrence_fear", "威嚇": "deterrence_fear", "核": "deterrence_fear",
    "nuclear": "deterrence_fear", "deterrence": "deterrence_fear",
    "外交": "deception_diplomacy", "会談": "deception_diplomacy", "声明": "deception_diplomacy",
    "覇権": "empire_decline", "秩序": "empire_decline", "衰退": "empire_decline",
    "世論": "domestic_populace", "選挙": "domestic_populace", "内政": "domestic_populace",
    "中立": "neutrality_choice", "neutral": "neutrality_choice",
    "制裁": "necessity_realpolitik", "関税": "necessity_realpolitik", "sanction": "necessity_realpolitik",
    "傭兵": "military_selfreliance", "自主防衛": "military_selfreliance",
    "好機": "fortune_timing", "タイミング": "fortune_timing",
}


def load_weights(config_path: str = "config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["scoring_weights"]


def score_item(item: NewsItem, weights: dict) -> NewsItem:
    """
    テキスト中に出現するキーワードの重みを合算してスコアリングする。
    high=3点, medium=2点, low=1点。
    地政学的に「力の実相」に関わる語(軍事・領土・核・同盟等)を最重視する設計。
    """
    text = f"{item.title} {item.summary}"
    total = 0
    matched = []
    topic_votes = {}

    for level, words in weights.items():
        pts = {"high": 3, "medium": 2, "low": 1}[level]
        for w in words:
            if re.search(re.escape(w), text, re.IGNORECASE):
                total += pts
                matched.append(w)

    for kw, topic in KEYWORD_TOPIC_HINTS.items():
        if re.search(re.escape(kw), text, re.IGNORECASE):
            topic_votes[topic] = topic_votes.get(topic, 0) + 1

    item.score = total
    item.matched_keywords = matched
    if topic_votes:
        best_topic = max(topic_votes.items(), key=lambda x: x[1])[0]
        item.theme = TOPIC_THEME_MAP.get(best_topic, "necessita")
    else:
        item.theme = "necessita"  # デフォルト: 必要性の論理
    return item


def rank_news(items: list, weights: dict, top_n: int = 5) -> list:
    """スコア降順でニュースを並べ、上位 top_n 件を返す。"""
    scored = [score_item(i, weights) for i in items]
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:top_n]
