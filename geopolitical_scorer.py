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

import html
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
    # 記事が当たった全テーマ(優先順位順)。theme はその先頭(主テーマ)
    themes: list = field(default_factory=list)


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
    # Google News 等は概要欄を HTML(<a>見出し</a>&nbsp;<font>媒体名</font>)で
    # 配信する。タグや &nbsp; が残ったままモデルに渡ると、読解の妨げになる。
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = html.unescape(cleaned).replace("\xa0", " ")
    cleaned = re.sub(r"【[^】]{0,20}】", "", cleaned)
    cleaned = re.sub(r"\[[^\]]{0,20}\]", "", cleaned)
    cleaned = re.sub(r"[ \u3000]{2,}", " ", cleaned)
    return cleaned.strip()


_MEDIA_SUFFIX = re.compile(r"\s+-\s+[^-]{1,40}$")


def facts_for_prompt(item: "NewsItem") -> tuple:
    """
    LLMに渡す(見出し, 概要)を整える。

    ・Google News の見出し末尾に付く「 - 読売新聞」のような媒体名を除く
      (媒体名を出来事の当事者と取り違えるのを防ぐ)
    ・概要が見出しの繰り返し+媒体名にすぎない場合は「(見出し以外の情報なし)」
      と明示する。情報が見出しだけであることをモデルに自覚させ、
      見出しに無い事情を補って作文するのを抑えるため。

    item.title 自体は書き換えない(重複判定のハッシュに使われているため)。
    """
    title = clean_news_text(item.title)
    summary = clean_news_text(item.summary)
    if "news.google.com" in (item.url or ""):
        bare = _MEDIA_SUFFIX.sub("", title)
        if summary.startswith(bare) or summary.startswith(title):
            summary = ""
        title = bare
    return title, (summary or "(見出し以外の情報なし)")


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
    "economy": "economia",                             # 経済・財政・制裁・資源・援助
    "advisors": "consiglio",                           # 側近・助言者・人事・意思決定
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
    "economy",
    "advisors",
    "necessity_realpolitik",
    "military_selfreliance",
    "fortune_timing",
]

# トピックごとの手がかり語。1つの記事が複数のトピックに当たることがあり、
# 当たったトピックは全て item.themes に(TOPIC_PRIORITY の順で)記録される。
# 箴言選びはこの全テーマを使う。item.theme(主テーマ)はその先頭。
#
# 【複数テーマにした理由】
# 以前は記事ごとにテーマを1つだけに決め、そのテーマの箴言(2〜3件)からしか
# 選ばなかった。実際の公開分53件のうち33件が「戦争」テーマになり、戦争テーマの
# 箴言2件が交互に使われ続けた。記事の持つ複数の側面(戦争と同盟、戦争と経済など)
# を全て拾うことで、より記事に合い、かつ偏らない箴言を選べるようにした。
TOPIC_KEYWORDS = {
    "war_conflict": [
        "台湾有事", "侵攻", "戦争", "invasion", "war", "封鎖", "攻撃", "反撃", "報復",
        "空爆", "爆撃", "ミサイル", "武力行使", "交戦", "砲撃", "戦闘", "軍事作戦", "侵入",
        "ドローン", "撃墜", "占領", "前線",
    ],
    "deterrence_fear": [
        "抑止", "威嚇", "核", "nuclear", "deterrence", "軍事的圧力", "軍事演習", "演習",
        "示威", "武力誇示", "挑発", "警告", "自走砲", "大砲", "砲口",
    ],
    "military_alliance": [
        "米軍", "駐留", "基地", "同盟", "alliance", "NATO", "地位協定", "共同訓練",
        "結束", "安保", "日米", "米韓", "防衛協力", "条約", "後ろ盾", "支援",
    ],
    "deception_diplomacy": [
        "外交", "会談", "声明", "首脳会議", "サミット", "共同声明", "停戦", "和平",
        "交渉", "仲介", "合意", "訪問", "外相", "国務長官", "特使",
        "訪中", "訪米", "訪朝", "訪露", "訪日",
    ],
    "empire_decline": [
        "覇権", "秩序", "衰退", "国際秩序", "崩壊", "クーデター", "政権交代", "後継",
        "最高指導者", "体制", "台頭", "大国",
    ],
    "domestic_populace": [
        "世論", "選挙", "内政", "支持率", "デモ", "抗議", "議会", "政局", "中間選挙",
        "大統領選", "国民", "不支持", "分断", "暴動",
    ],
    "neutrality_choice": ["中立", "neutral", "日和見", "両天秤", "どっちつかず"],
    "economy": [
        "関税", "制裁", "経済", "原油", "石油", "エネルギー", "資源", "輸出", "輸入",
        "投資", "財政", "インフレ", "物価", "ガソリン", "援助", "貿易", "製油所", "市場",
    ],
    "advisors": [
        "側近", "閣僚", "長官", "補佐官", "内閣", "人事", "更迭", "辞任", "解任", "顧問",
        "諜報", "情報機関", "後任",
    ],
    "necessity_realpolitik": ["制裁", "関税", "sanction", "貿易摩擦", "やむを得", "苦渋"],
    "military_selfreliance": [
        "傭兵", "自主防衛", "防衛費", "防衛力", "軍備", "徴兵", "兵力", "兵器", "国防",
        "軍拡", "武器",
    ],
    "fortune_timing": ["好機", "タイミング", "危機", "災害", "誤算", "転機"],
}


def _keyword_hit(keyword: str, text: str) -> bool:
    """
    手がかり語が本文に含まれるか。英字の語は単語単位で照合する
    (「war」が「award」「Warsaw」に誤って当たるのを防ぐ)。
    """
    if keyword.isascii():
        return re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE) is not None
    return keyword in text


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

    # テーマの判定には、見出し末尾の媒体名(「 - 日本経済新聞」など)を除いた
    # 文を使う。媒体名の「経済」に当たって経済テーマにされるのを防ぐため。
    topic_text = f"{_MEDIA_SUFFIX.sub('', clean_news_text(item.title))} {clean_news_text(item.summary)}"
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(_keyword_hit(kw, topic_text) for kw in keywords):
            matched_topics.add(topic)

    item.score = total
    item.matched_keywords = matched

    # 当たったトピックを優先順位(TOPIC_PRIORITY)の順に並べ、テーマ名に直して記録する。
    # 先頭が主テーマ(item.theme)。「一致数が最も多いトピック」ではなく
    # 「最も具体的・深刻なトピック」を主テーマにすることで、実際の武力攻撃を
    # 報じる記事が「米軍」という語を含むだけで同盟テーマにされる事態を防ぐ。
    themes = []
    for topic in TOPIC_PRIORITY:
        theme = TOPIC_THEME_MAP[topic]
        if topic in matched_topics and theme not in themes:
            themes.append(theme)
    item.themes = themes
    item.theme = themes[0] if themes else "necessita"  # デフォルト: 必要性の論理
    return item


def rank_news(items: list, weights: dict, top_n: int = 5, exclude_keywords: list = None) -> list:
    """スコア降順でニュースを並べ、上位 top_n 件を返す(除外対象は score=-1 として最下位になる)。"""
    scored = [score_item(i, weights, exclude_keywords) for i in items]
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:top_n]
