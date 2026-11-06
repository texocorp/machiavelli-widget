# -*- coding: utf-8 -*-
"""
montaigne_scorer.py
--------------------
社会面・科学医療のニュースを、モンテーニュボット向けにスコアリングし、
『エセー』の箴言テーマ(data/montaigne_quotes.json の tags)に分類する。

記事のデータ構造(NewsItem)・見出しの清掃(clean_news_text)・
LLMに渡す事実の整形(facts_for_prompt)は、マキャベリボットの
geopolitical_scorer.py のものをそのまま使う。

【選別の考え方】
モンテーニュは国家の興亡よりも、人間の性(恐れ・虚栄・習慣・思い込み・
残酷さ・移ろいやすさ)が露わになる出来事を好んで論じた。そこで
死・裁き・教育・医療・技術・慣習・他者との摩擦に関わる記事を重く見る。
"""

import re
import unicodedata
import yaml

from geopolitical_scorer import NewsItem, clean_news_text, _MEDIA_SUFFIX  # noqa: F401


# ---------------------------------------------------------------
# キーワードの照合
# ---------------------------------------------------------------
def keyword_hit(keyword: str, text: str) -> bool:
    """
    手がかり語が本文に含まれるか。

    英字の語(「AI」「SNS」など)は、前後が英字でないことを条件にする。
    Python の \\b は日本語の文字も「単語の文字」とみなすため、
    「生成AIが」のように日本語に挟まれた英字に \\b を使うと一致しない。
    また「AI」が「email」「said」に当たるのも防ぐ。
    """
    if keyword.isascii():
        pattern = rf"(?<![A-Za-z]){re.escape(keyword)}(?![A-Za-z])"
        return re.search(pattern, text, re.IGNORECASE) is not None
    return keyword in text


def load_scoring_config(config_path: str = "montaigne_config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return {
        "weights": cfg["scoring_weights"],
        "exclude_keywords": cfg.get("exclude_keywords", []),
        "minimum_score": cfg.get("selection", {}).get("minimum_score", 1),
    }


def _topic_text(item: NewsItem) -> str:
    # 見出し末尾の媒体名(「 - 日本経済新聞」など)を除いた文で判定する
    # 全角の英数字(「生成ＡＩ」「ＳＮＳ」)も手がかり語に当たるよう、NFKC で半角にそろえる
    # (2026-11-06: 「災害報道、生成ＡＩ課題議論」が「生成AI」「AI」に当たらず点数不足で外れていた)
    text = f"{_MEDIA_SUFFIX.sub('', clean_news_text(item.title))} {clean_news_text(item.summary)}"
    return unicodedata.normalize("NFKC", text)


# ---------------------------------------------------------------
# テーマ分類
# ---------------------------------------------------------------
# 上から順に優先する(先頭に当たったものが主テーマ)。
# より具体的で重い出来事(暴力・裁き・死)を、一般的なシグナル
# (変化・自己)より先に判定する。考え方はマキャベリ側の TOPIC_PRIORITY と同じ。
THEME_PRIORITY = [
    "cruaute",
    "lois",
    "opinion",
    "mort",
    "medecine",
    "savoir",
    "presomption",
    "autrui",
    "profit",
    "vanite",
    "coutume",
    "nouveaute",
    "soi",
    "peur",
    "inconstance",
]

DEFAULT_THEME = "inconstance"  # どれにも当たらないときは「人の移ろいやすさ」

THEME_KEYWORDS = {
    "cruaute": [
        "虐待", "暴行", "殺害", "殺人", "傷害", "いじめ", "拷問", "虐殺", "刺され",
        "刺殺", "暴力", "監禁", "動物虐待", "体罰", "ハラスメント",
    ],
    "lois": [
        "判決", "裁判", "地裁", "高裁", "最高裁", "起訴", "逮捕", "容疑", "冤罪",
        "再審", "死刑", "法改正", "条例", "規制", "校則", "法律", "取り調べ",
        "検察", "書類送検", "賠償", "違法", "不正", "隠蔽", "改ざん",
    ],
    "mort": [
        "死亡", "死去", "亡くなっ", "死者", "遺体", "事故", "災害", "地震", "津波",
        "終活", "葬儀", "寿命", "安楽死", "尊厳死", "孤独死", "看取り", "遺族", "犠牲",
    ],
    "medecine": [
        "医療", "病院", "医師", "治療", "新薬", "ワクチン", "感染", "がん", "診療",
        "健康", "検診", "手術", "患者", "病気", "認知症", "介護", "薬", "医薬品",
        "インフルエンザ", "厚労省", "厚生労働省",
    ],
    "opinion": [
        "デマ", "偽情報", "フェイク", "噂", "SNS", "炎上", "誤報", "拡散", "陰謀",
        "風評", "投稿", "世論", "報道", "広告", "ステマ", "詐欺", "誹謗中傷", "ネット",
    ],
    "savoir": [
        "教育", "学校", "大学", "入試", "試験", "学力", "研究", "研究者", "論文",
        "専門家", "教員", "教師", "授業", "学習", "発見", "博物館", "図書館",
    ],
    "presomption": [
        "AI", "人工知能", "生成AI", "ロボット", "原発", "宇宙", "遺伝子", "ゲノム",
        "想定外", "自動運転", "技術", "開発", "実験", "安全神話", "ロケット",
    ],
    "autrui": [
        "外国人", "移民", "差別", "ヘイト", "観光客", "多文化", "難民", "国籍",
        "異文化", "動物", "クマ", "ペット", "野生", "先住民", "共生",
    ],
    "profit": [
        "値上げ", "物価", "賃金", "給料", "利益", "企業", "格差", "貧困", "転売",
        "品薄", "高騰", "資源", "取引", "販売", "売り上げ", "ビジネス",
    ],
    "vanite": [
        "不祥事", "謝罪", "辞任", "肩書", "学歴", "経歴詐称", "ブランド", "名誉",
        "有名人", "著名人", "富裕層", "社長", "市長", "知事", "町長", "村長", "会見",
    ],
    "coutume": [
        "伝統", "慣習", "しきたり", "慣行", "前例", "風習", "祭り", "常識", "文化",
        "同調", "年功", "伝承", "老舗", "風物詩",
    ],
    "nouveaute": [
        "改革", "新制度", "見直し", "導入", "廃止", "改正", "刷新", "再編",
        "初めて", "新たな", "新しい",
    ],
    "soi": [
        "働き方", "過労", "長時間労働", "孤独", "孤立", "家族", "結婚", "離婚",
        "子育て", "高齢者", "老後", "幸福", "生き方", "余暇", "引退", "定年",
        "一人暮らし", "若者", "少子化",
    ],
    "peur": [
        "不安", "恐怖", "パニック", "買い占め", "心配", "懸念", "警戒", "避難",
        "被害", "注意喚起",
    ],
    "inconstance": [
        "豹変", "撤回", "一転", "方針転換", "翻意", "心変わり", "矛盾", "変更", "転換",
    ],
}


def classify_themes(item: NewsItem) -> NewsItem:
    """記事が当たるテーマを全て拾い、item.themes(優先順位順)と item.theme(先頭)に設定する。"""
    text = _topic_text(item)
    if getattr(item, "title_ja", ""):
        text += f" {item.title_ja} {item.summary_ja}"
    themes = [t for t in THEME_PRIORITY
              if any(keyword_hit(kw, text) for kw in THEME_KEYWORDS[t])]
    item.themes = themes
    item.theme = themes[0] if themes else DEFAULT_THEME
    return item


# ---------------------------------------------------------------
# スコアリング
# ---------------------------------------------------------------
def score_item(item: NewsItem, weights: dict, exclude_keywords: list = None) -> NewsItem:
    """
    キーワードの重みを合算する(high=4, medium=2, low=1)。
    exclude_keywords に当たった記事は score=-1(除外)。
    """
    text = _topic_text(item)
    for ex in (exclude_keywords or []):
        if keyword_hit(ex, text):
            item.score = -1
            item.matched_keywords = [f"[除外理由: {ex}]"]
            item.theme = DEFAULT_THEME
            return item

    total, matched = 0, []
    for level, words in weights.items():
        pts = {"high": 4, "medium": 2, "low": 1}[level]
        for w in words:
            if keyword_hit(w, text):
                total += pts
                matched.append(w)
    item.score = total
    item.matched_keywords = matched
    return classify_themes(item)


def rank_news(items: list, weights: dict, top_n: int = 10, exclude_keywords: list = None) -> list:
    """スコア降順で並べ、上位 top_n 件を返す。"""
    scored = [score_item(i, weights, exclude_keywords) for i in items]
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:top_n]
