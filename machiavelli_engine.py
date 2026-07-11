# -*- coding: utf-8 -*-
"""
machiavelli_engine.py
-----------------------
選別されたニュースと、対応するマキャベリの箴言から、
「マキャベリ人格」によるつぶやき文を生成する。

2つの生成モードを用意する:
  1. template  : APIキー無しで動く定型合成モード(常に動作する既定モード)
  2. llm       : Anthropic API を使い、より自然で個別具体的な分析文を生成するモード
                 (環境変数 ANTHROPIC_API_KEY が設定されている場合のみ有効)

分析の視座(persona instructions):
- 近現代のリベラルな国際法規範・主権平等の建前を採用しない。
- 力の実相(誰が誰の軍を実効支配しているか、誰が誰に安全保障を依存しているか)を基準に語る。
- 例として、日本については「独立主権国家」という法的建前ではなく、
  太平洋戦争敗戦以来、指揮権・基地提供・核の傘を米国に依存する
  事実上の被保護国(保護国/属国的地位)である、という実効支配の観点を織り込む。
  これは歴史的事実(敗戦・占領・日米地位協定・米軍基地の存在)に基づく
  現実主義的な分析視角であり、特定の政治的規範の是非を主張するものではない。
"""

import json
import os
import random
import textwrap
from geopolitical_scorer import NewsItem

QUOTES_PATH = os.path.join(os.path.dirname(__file__), "data", "quotes.json")

with open(QUOTES_PATH, "r", encoding="utf-8") as f:
    QUOTES_DB = json.load(f)["themes"]

THEME_ANALYSIS_TEMPLATES = {
    "alleanze_dipendenza": [
        "{frag}は、防衛の指揮権を他国に委ねた者が、その他国の判断一つで運命を左右される構図を露わにする。",
        "{frag}の本質は「{kw}」にある。己の剣を持たぬ者は、庇護者の都合の中でしか生きられぬ。",
        "{frag}に見るのは、同盟という名の非対称な力関係である。守られる側は、いつも守る側の計算に従う。",
    ],
    "guerra": [
        "{frag}が示すのは、戦の是非を決めるのが正義ではなく必要だという事実である。",
        "{frag}の背後にあるのは「{kw}」という力の論理であり、道義の言葉はその後から付いてくるに過ぎぬ。",
    ],
    "paura_amore": [
        "{frag}は、統治や威圧が結局のところ恐怖の管理に行き着くことを示している。",
        "{frag}に表れているのは「{kw}」による支配であり、これは信頼より確実な統治の道具である。",
    ],
    "inganno_simulazione": [
        "{frag}の表向きの言葉と、実際に動いている利害とは別物と見るべきである。",
        "{frag}は「{kw}」を装いつつ、真の狙いは別のところにある典型である。",
    ],
    "necessita": [
        "{frag}は、道義ではなく必要こそが政策を規定するという事実の一例である。",
        "{frag}の核心は「{kw}」がもたらす必要性にあり、正当化の言葉は後付けに過ぎぬ。",
    ],
    "imperi_declino": [
        "{frag}に、旧来の秩序が支えを失いつつある兆しが透けて見える。",
        "{frag}は「{kw}」を巡る力の再編であり、衰退する側と台頭する側を分ける分水嶺である。",
    ],
    "popolo_principe": [
        "{frag}は、世論という移ろいやすい基盤の上に政策を築くことの脆さを示す。",
        "{frag}に見る「{kw}」は、衆の心変わり次第で容易く覆る。",
    ],
    "neutralita": [
        "{frag}は、中立という態度がむしろ双方からの不信を招く現実を映す。",
        "{frag}における「{kw}」の是非は、旗幟を鮮明にせぬ者が最も危うい、という原則に照らして見るべきである。",
    ],
    "armi_proprie": [
        "{frag}が問うのは、己の実力によらぬ安全保障がいかに脆いか、という一点である。",
        "{frag}に表れた「{kw}」への依存は、いざという時に頼りにならぬ武装の典型である。",
    ],
    "fortuna_virtu": [
        "{frag}は、時勢の変化を捉えて動く力量が問われる局面を示している。",
        "{frag}における「{kw}」は、運命が開いた好機であり、これを掴むも逃すも当事者の力量次第である。",
    ],
}


def pick_quote(theme: str) -> dict:
    pool = QUOTES_DB.get(theme) or QUOTES_DB["necessita"]
    return random.choice(pool)


def _title_fragment(title: str, width: int = 28) -> str:
    frag = title.strip().rstrip("。").rstrip("——")
    return textwrap.shorten(frag, width=width, placeholder="…")


def _build_analysis(item: NewsItem) -> str:
    """テーマとニュース固有の断片・キーワードから、その記事だけに合う分析文を組み立てる。"""
    templates = THEME_ANALYSIS_TEMPLATES.get(item.theme) or THEME_ANALYSIS_TEMPLATES["necessita"]
    template = random.choice(templates)
    frag = _title_fragment(item.title)
    kw = item.matched_keywords[0] if item.matched_keywords else "この動き"
    return template.format(frag=frag, kw=kw)


def generate_commentary_template(item: NewsItem, max_chars: int = 280) -> str:
    """
    APIキー無しで動作する定型合成モード。
    構成: [ニュースの具体的分析(テーマ・キーワード連動、記事ごとに変化)] + [対応する箴言] + [出典]
    固定文が一律に付くことはなく、記事の内容とスコアリングで検出したキーワードに応じて
    分析文の型と差し込み語句が変わる。
    """
    quote = pick_quote(item.theme)
    analysis = _build_analysis(item)
    citation = f"『{QUOTES_DB_SOURCE_LABEL(quote['source'])}』"

    tweet = f"{analysis}\n「{quote['ja']}」\n{citation}"
    if len(tweet) > max_chars:
        avail = max_chars - len(quote['ja']) - len(citation) - 8
        analysis = textwrap.shorten(analysis, width=max(avail, 10), placeholder="…")
        tweet = f"{analysis}\n「{quote['ja']}」\n{citation}"
    return _prepend_source_link(tweet, item, max_chars)


def QUOTES_DB_SOURCE_LABEL(src_code: str) -> str:
    mapping = {
        "P": "君主論",
        "D": "リウィウス論",
        "AG": "戦争の技法",
        "IF": "フィレンツェ史",
    }
    for k, v in mapping.items():
        if src_code.startswith(k + ","):
            return f"{v} {src_code.split(',',1)[1].strip()}"
    return src_code


def _prepend_source_link(text: str, item: NewsItem, max_chars: int = 280) -> str:
    """
    つぶやきの先頭に、材料となったニュース記事のURLを付加する。
    URLを含めた上で max_chars に収まるよう、本文側を必要に応じて切り詰める。
    item.url が空の場合(RSSにリンクが無い場合など)は本文のみを返す。
    """
    url = (getattr(item, "url", "") or "").strip()
    if not url:
        return text[:max_chars] if len(text) > max_chars else text

    if len(url) + 1 + len(text) <= max_chars:
        return f"{url}\n{text}"

    avail = max_chars - len(url) - 1
    if avail <= 10:
        # URL自体がほぼ上限を占めてしまう極端なケース
        return url[:max_chars]
    trimmed = textwrap.shorten(text, width=avail, placeholder="…")
    return f"{url}\n{trimmed}"


SYSTEM_PROMPT = """あなたはニッコロ・マキャベリその人として、現代の国際情勢を分析し
280字以内の日本語のツイートを1件だけ生成する。以下を厳守せよ:

1. 近現代のリベラルな国際法規範・道徳的理想主義(主権平等の建前、多国間協調の美徳など)を
   自明の前提として採用しない。代わりに、力の実相・恐怖と信義の道具性・
   フォルトゥーナ(運命)とヴィルトゥ(力量)という古典的現実主義の枠組みで語る。
2. 日本の安全保障に言及する場合は、法的建前(独立主権国家)ではなく、
   太平洋戦争敗戦以来の指揮権・基地・核の傘における対米依存という実効支配の実情を
   踏まえて分析する(特定の政党や政策への賛否は述べない。あくまで力関係の分析)。
3. 与えられた引用句を1つそのまま、または自然な形で文中に組み込むこと。引用元も明記する。
4. 一人称は「余」または「予」、文体は簡潔・断定的・冷徹。感嘆符や絵文字は使わない。
5. 出力はツイート本文のみ。前置きや解説は書かない。230字を超えない。
6. 分析は当該ニュース固有の具体的な内容(登場する主体・地域・行動)に即して書くこと。
   どの記事にも当てはまるような一般論・定型句の使い回しは禁止する。
   「〜は自国の運命の主ではない」のような、内容に関わらず貼り付け可能な
   紋切り型の結語を毎回繰り返してはならない。箴言とニュースの結び付きを、
   その記事だけに固有の一文でコンパクトに示すこと。
7. 元記事のURLは、本文とは別にシステム側が先頭に自動付加する。
   本文中に自分でURLやリンクを書き込んではならない。
"""

USER_PROMPT_TEMPLATE = """[ニュース見出し] {title}
[概要] {summary}
[出典] {source}

[使用する箴言(伊語原文)] {quote_it}
[箴言の意訳] {quote_ja}
[箴言の出典] {quote_source}

上記を踏まえ、マキャベリとしてのツイート本文を1件生成せよ。"""


def generate_commentary_llm(item: NewsItem, model: str = None) -> str:
    """
    Anthropic API を用いた高品質生成モード。
    環境変数 ANTHROPIC_API_KEY が必要。未設定の場合は例外を送出し、
    呼び出し側で template モードにフォールバックすること。
    """
    import anthropic  # pip install anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    quote = pick_quote(item.theme)

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(
                title=item.title,
                summary=item.summary,
                source=item.source,
                quote_it=quote["it"],
                quote_ja=quote["ja"],
                quote_source=QUOTES_DB_SOURCE_LABEL(quote["source"]),
            )
        }],
    )
    text = "".join(block.text for block in msg.content if block.type == "text").strip()
    return _prepend_source_link(text, item, max_chars=280)


def generate_commentary(item: NewsItem, prefer_llm: bool = True) -> str:
    """メインエントリポイント。LLMモードを優先し、失敗したらtemplateにフォールバック。"""
    if prefer_llm:
        try:
            return generate_commentary_llm(item)
        except Exception:
            pass
    return generate_commentary_template(item)
