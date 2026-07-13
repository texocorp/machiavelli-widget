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


def clean_news_text(text: str) -> str:
    """
    ニュースの見出し・概要から、【随時更新】【速報】【独自】のような
    全角ブラケットの編集ラベルや、半角[LIVE]等のラベルを除去する。

    【このクリーニングが必要な理由】
    NHK等の一部のニュース配信は、見出し自体に「【随時更新】ウクライナ情勢」
    のような編集上のラベルを含めている。これをクリーニングせずに
    そのままテンプレート文やLLMへのプロンプトに渡すと、
    「見出しに書かれていた」という理由だけでラベルがつぶやきの
    分析文にそのまま紛れ込んでしまう(実際に発生した不具合)。

    見出し・概要は、ニュースを取得した直後(news_fetcher.py)の時点で
    このクリーニングを通すことを想定しているが、念のため
    machiavelli_engine.py 側(_title_fragment、LLMプロンプト組み立て時)でも
    同じ関数を呼び、二重に防御する。
    """
    if not text:
        return text
    cleaned = re.sub(r"【[^】]{0,20}】", "", text)
    cleaned = re.sub(r"\[[^\]]{0,20}\]", "", cleaned)
    cleaned = re.sub(r"[ \u3000]{2,}", " ", cleaned)
    return cleaned.strip()


# ニュースのトピック→ quotes.json のテーマキーへのマッピング
TOPIC_THEME_MAP = {
    "war_conflict": "guerra",                       # 戦争・武力衝突・攻撃
    "deterrence_fear": "paura_amore",                # 抑止・威嚇・恐怖による統制
    "military_alliance": "alleanze_dipendenza",      # 同盟・保護国・駐留・属国的依存
    "deception_diplomacy": "inganno_simulazione",    # 外交的欺瞞・二枚舌
    "empire_decline": "imperi_declino",              # 覇権の興亡・秩序の変化
    "domestic_populace": "popolo_principe",          # 世論・国内政治の移ろいやすさ
    "neutrality_choice": "neutralita",                # 中立という選択の是非
    "necessity_realpolitik": "necessita",             # 必要による正当化
    "military_selfreliance": "armi_proprie",          # 自前の軍事力 vs 傭兵/他国依存
    "fortune_timing": "fortuna_virtu",                 # 好機・時勢の変化
}

# テーマ分類の優先順位(上から順にチェックし、最初に一致したものを採用する)。
#
# 【なぜ「一致数の多数決」ではなく「優先順位」にしたか】
# 以前は KEYWORD_TOPIC_HINTS の一致数が最も多いトピックを採用していたが、
# 同点の場合は「辞書内で先に定義されたトピック」が常に勝つ実装になっており、
# 「米軍」(military_alliance)が先に定義されていたせいで、
# 実際には武力攻撃・報復を報じる記事(例:「米軍とイランの攻撃応酬」)まで
# war_conflict ではなく military_alliance に誤分類され続け、
# 結果として alleanze_dipendenza テーマ(箴言2件のみ)ばかりが選ばれ、
# 同じ箴言が繰り返し引用される原因になっていた。
#
# 優先順位方式では、より具体的・深刻な事象(実際の武力衝突)を、
# より一般的・周辺的なシグナル(米軍関与・同盟という語の存在)より
# 優先して判定する。これにより、記事の実態に即したテーマ分類がなされ、
# 結果として箴言の使用もテーマ単位でより広く分散するようになる。
TOPIC_PRIORITY = [
    "war_conflict",
    "deterrence_fear",
    "military_alliance",
    "deception_diplomacy",
    "empire_decline",
    "domestic_populace",
    "neutrality_choice",
    "necessity_realpolitik",
    "military_selfreliance",
    "fortune_timing",
]

# キーワード→トピック の粗いマッピング。
# 同じキーワードが複数トピックに関わる場合があるが、最終判定は
# TOPIC_PRIORITY の順序(上記)で決まるため、ここでの記載順自体は問わない。
KEYWORD_TOPIC_HINTS = {
    # war_conflict: 実際の武力行使・攻撃・侵攻・封鎖
    "台湾有事": "war_conflict", "侵攻": "war_conflict", "戦争": "war_conflict",
    "invasion": "war_conflict", "war": "war_conflict", "封鎖": "war_conflict",
    "攻撃": "war_conflict", "反撃": "war_conflict", "報復": "war_conflict",
    "攻撃応酬": "war_conflict", "空爆": "war_conflict", "ミサイル": "war_conflict",
    "武力行使": "war_conflict", "交戦": "war_conflict", "砲撃": "war_conflict",
    # deterrence_fear: 抑止・威嚇・核
    "抑止": "deterrence_fear", "威嚇": "deterrence_fear", "核": "deterrence_fear",
    "nuclear": "deterrence_fear", "deterrence": "deterrence_fear", "軍事的圧力": "deterrence_fear",
    # military_alliance: 同盟・駐留・基地・依存関係(実際の武力衝突が無い場合の話題)
    "米軍": "military_alliance", "駐留": "military_alliance", "基地": "military_alliance",
    "同盟": "military_alliance", "alliance": "military_alliance",
    "NATO": "military_alliance", "地位協定": "military_alliance", "共同訓練": "military_alliance",
    "結束": "military_alliance",
    # deception_diplomacy: 外交・会談・声明・首脳会議
    "外交": "deception_diplomacy", "会談": "deception_diplomacy", "声明": "deception_diplomacy",
    "首脳会議": "deception_diplomacy", "サミット": "deception_diplomacy", "共同声明": "deception_diplomacy",
    # empire_decline: 覇権・秩序・衰退
    "覇権": "empire_decline", "秩序": "empire_decline", "衰退": "empire_decline",
    "国際秩序": "empire_decline",
    # domestic_populace: 世論・内政
    "世論": "domestic_populace", "選挙": "domestic_populace", "内政": "domestic_populace",
    # neutrality_choice: 中立
    "中立": "neutrality_choice", "neutral": "neutrality_choice",
    # necessity_realpolitik: 制裁・関税・貿易摩擦
    "制裁": "necessity_realpolitik", "関税": "necessity_realpolitik", "sanction": "necessity_realpolitik",
    "貿易摩擦": "necessity_realpolitik",
    # military_selfreliance: 傭兵・自主防衛
    "傭兵": "military_selfreliance", "自主防衛": "military_selfreliance",
    # fortune_timing: 好機・時勢
    "好機": "fortune_timing", "タイミング": "fortune_timing",
}


def load_weights(config_path: str = "config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["scoring_weights"]


def load_scoring_config(config_path: str = "config.yaml") -> dict:
    """
    スコアリングに必要な設定一式(重み・除外キーワード・最低選別スコア)を
    まとめて読み込む。
    """
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return {
        "weights": cfg["scoring_weights"],
        "exclude_keywords": cfg.get("exclude_keywords", []),
        "minimum_score": cfg.get("selection", {}).get("minimum_score", 1),
    }


def score_item(item: NewsItem, weights: dict, exclude_keywords: list = None) -> NewsItem:
    """
    テキスト中に出現するキーワードの重みを合算してスコアリングする。
    high=4点, medium=2点, low=1点。
    地政学的に「力の実相」に関わる語(軍事・領土・核・同盟等)を最重視する設計。

    exclude_keywords のいずれかに一致した場合は、他の一致点数に関わらず
    score=-1(除外)を返す。スポーツ・芸能等のノイズ記事を弾くための仕組み。
    """
    text = f"{item.title} {item.summary}"

    for ex in (exclude_keywords or []):
        if re.search(re.escape(ex), text, re.IGNORECASE):
            item.score = -1
            item.matched_keywords = [f"[除外理由: {ex}]"]
            item.theme = "necessita"
            return item

    total = 0
    matched = []
    matched_topics = set()

    for level, words in weights.items():
        pts = {"high": 4, "medium": 2, "low": 1}[level]
        for w in words:
            if re.search(re.escape(w), text, re.IGNORECASE):
                total += pts
                matched.append(w)

    for kw, topic in KEYWORD_TOPIC_HINTS.items():
        if re.search(re.escape(kw), text, re.IGNORECASE):
            matched_topics.add(topic)

    item.score = total
    item.matched_keywords = matched

    # 優先順位(TOPIC_PRIORITY)の順に見ていき、最初に一致したトピックを採用する。
    # 「一致数が最も多いトピック」ではなく「最も具体的・深刻なトピック」を
    # 優先することで、例えば実際の武力攻撃を報じる記事が、
    # 単に「米軍」という語を含むだけで同盟関連テーマに誤分類される事態を防ぐ。
    item.theme = "necessita"  # デフォルト: 必要性の論理
    for topic in TOPIC_PRIORITY:
        if topic in matched_topics:
            item.theme = TOPIC_THEME_MAP.get(topic, "necessita")
            break
    return item


def rank_news(items: list, weights: dict, top_n: int = 5, exclude_keywords: list = None) -> list:
    """スコア降順でニュースを並べ、上位 top_n 件を返す(除外対象は score=-1 として最下位になる)。"""
    scored = [score_item(i, weights, exclude_keywords) for i in items]
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:top_n]
