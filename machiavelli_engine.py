# -*- coding: utf-8 -*-
"""
machiavelli_engine.py
-----------------------
選別されたニュースと、対応するマキャベリの箴言から、
「マキャベリ人格」によるつぶやき文を生成する。

【生成プロセスの設計方針】
処理を4つの明確な役割に分離し、それぞれ何が(誰が)担当するかを固定している:

  1. 箴言を選ぶ            … select_quote()          Pythonが候補を絞り、LLMが1件を選ぶ
  2. 分析文を1文だけ得る    … _get_analysis()         LLM(失敗時はテンプレート)
  3. 分析文+引用+出典を結合 … _assemble_body()        常にPythonが機械的に結合
  4. 先頭にURLを付加        … _prepend_source_link()  常にPythonが決定的に付加

LLMに任せるのは「候補の中から当てはまる箴言の番号を選ぶ」ことと
「ニュースの本質を一文で言い当てる」ことだけであり、引用文・出典・URLの
文字列にはLLMを一切関与させない。これにより、LLMが失敗・迷走しても
引用の正確さや出典表記は常に保証される。

【箴言の選び方】
data/quotes.json の箴言(原典の章・節まで確認済み)にはそれぞれ複数のテーマの
タグと「当てはまる場面」が付いている。select_quote() は記事のテーマ・場面の語と
照らして候補を8件に絞り、LLM に最もよく当てはまる1件を選ばせる。
直近30回の投稿で使った箴言は候補から外す。使用履歴は
logs/recent_quotes.json・logs/quote_usage.json に永続化され、
generate_commentary() が実際に採用した箴言についてのみ記録する。

分析文の生成は以下の優先順で試み、失敗したら次にフォールバックする:
  1. ollama : 無料・独立のローカルLLM(Ollamaが起動している場合、既定で最優先)
  2. llm    : Anthropic API(環境変数 ANTHROPIC_API_KEY 設定時のみ)
  3. template: テーマ別テンプレート(APIキー等が無くても常に成功する最終フォールバック)

【分析の視座(persona instructions)】
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
import re
import textwrap
from geopolitical_scorer import NewsItem, clean_news_text, facts_for_prompt, is_japanese, classify_themes

QUOTES_PATH = os.path.join(os.path.dirname(__file__), "data", "quotes.json")

with open(QUOTES_PATH, "r", encoding="utf-8") as f:
    QUOTES = json.load(f)["quotes"]

QUOTES_BY_ID = {q["id"]: q for q in QUOTES}

# テーマ名 -> そのテーマのタグを持つ箴言の一覧(1つの箴言が複数テーマに属しうる)
QUOTES_DB = {}
for _q in QUOTES:
    for _t in _q["tags"]:
        QUOTES_DB.setdefault(_t, []).append(_q)

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
    "economia": [
        "{frag}は、金銭と資源の流れがそのまま力の配分を決めることを示している。",
        "{frag}に見る「{kw}」は、剣を交えずに相手を締め上げる、もう一つの戦である。",
    ],
    "consiglio": [
        "{frag}は、君主の器量がその周りに置く人間によって測られることを示している。",
        "{frag}に表れた人の配置こそ、指導者の判断の質を映す鏡である。",
    ],
}


RECENT_QUOTES_PATH = os.path.join(os.path.dirname(__file__), "logs", "recent_quotes.json")
QUOTE_USAGE_PATH = os.path.join(os.path.dirname(__file__), "logs", "quote_usage.json")
# 直近何回分の投稿で使った箴言を候補から外すか。
# 箴言が122件あるので、30回(約6日分)は同じ箴言が二度と出ないようにしている。
RECENT_QUOTES_WINDOW = 30


def _load_json_file(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def _save_json_file(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def load_recent_quote_ids() -> list:
    """直近 RECENT_QUOTES_WINDOW 回分で使用した箴言idのリスト(新しい順)。"""
    return _load_json_file(RECENT_QUOTES_PATH, [])


def load_quote_usage() -> dict:
    """箴言id -> 通算使用回数、の辞書。多くの箴言を偏りなく活用するための集計。"""
    return _load_json_file(QUOTE_USAGE_PATH, {})


def record_quote_usage(quote_id: str) -> None:
    """
    箴言が実際に使用された(=つぶやきとして採用された)ことを記録する。
    ・直近使用リストの先頭に追加し、RECENT_QUOTES_WINDOW件を超えたら古いものを捨てる
    ・通算使用回数を+1する
    プレビューや失敗した試行では呼ばないこと(実際に採用された場合のみ記録する)。
    """
    recent = load_recent_quote_ids()
    recent.insert(0, quote_id)
    _save_json_file(RECENT_QUOTES_PATH, recent[:RECENT_QUOTES_WINDOW])

    usage = load_quote_usage()
    usage[quote_id] = usage.get(quote_id, 0) + 1
    _save_json_file(QUOTE_USAGE_PATH, usage)


# ---------------------------------------------------------------
# 箴言の選び方
# ---------------------------------------------------------------
#
# 【以前の方式とその問題】
# 以前は、記事ごとにテーマを1つだけ決め、そのテーマの箴言(2〜3件)の中で
# 順番に回すだけだった。箴言の中身と記事の中身は照らし合わされず、
# 分析文も箴言を見ずに書かれていた。公開分53件のうち33件が「戦争」テーマで、
# その2件の箴言が交互に使われ、24件中14件は一度も使われなかった。
#
# 【現在の方式】
#   1. 候補を絞る: 記事が当たった全テーマ(item.themes)と、各箴言の
#      「適用場面」に含まれる語が記事に出てくるかで、関連度の点数を付ける
#   2. 直近30回の投稿で使った箴言は候補から外す
#   3. 関連度の高い順(同点なら通算使用回数の少ない順)に上位8件を残す
#   4. LLM に、記事の見出し・概要と8件の候補を見せ、最もよく当てはまる
#      1件を番号で選ばせる(LLM が使えない・答えが読めない時は1位を採用)
#   5. 分析文は、選ばれた箴言を踏まえて書かせる(_get_analysis に渡す)

CANDIDATE_COUNT = 8      # LLM に見せる候補の数
MIN_RELATED = 4          # 関連する候補がこれより少なければ、関連の薄い箴言も候補に加える


# 適用場面に頻出するが、どの記事にも出てきうるため手がかりにならない語
_SCENE_STOPWORDS = {
    "指導者", "外交", "危機", "他国", "行動", "国家", "構図", "対応", "結果", "政治",
    "選択", "判断", "態度", "情勢", "国内", "政策", "支持", "安定", "大胆", "決断",
    "限界", "動機", "失敗", "場合", "状況", "問題", "関係", "一方", "自国",
}
_SCENE_TERM = re.compile(r"[一-龥々ァ-ヴー]{2,}")


def _scene_words(quote: dict) -> list:
    """適用場面の文(「封鎖、経済制裁、兵糧攻め」など)から、漢字・カタカナの語句を取り出す。"""
    return [w for w in dict.fromkeys(_SCENE_TERM.findall(quote.get("scene", "")))
            if w not in _SCENE_STOPWORDS]


def _quote_relevance(quote: dict, themes: list, news_text: str) -> int:
    """
    箴言と記事の関連度。
      ・記事のテーマとの一致: 主テーマなら3点、2番目なら2点、それ以降は1点
      ・適用場面の語が記事の見出し・概要に出てくれば、1語につき2点(最大6点)
    """
    score = 0
    for idx, theme in enumerate(themes):
        if theme in quote["tags"]:
            score += max(3 - idx, 1)
    score += 2 * min(sum(1 for w in _scene_words(quote) if w in news_text), 3)
    return score


def rank_quote_candidates(item: NewsItem, count: int = CANDIDATE_COUNT) -> list:
    """記事に対する箴言の候補を、関連度の高い順に count 件返す(直近の使用分は除く)。"""
    themes = getattr(item, "themes", None) or [item.theme or "necessita"]
    title, summary = facts_for_prompt(item)
    news_text = f"{title} {summary}"
    recent = set(load_recent_quote_ids())
    usage = load_quote_usage()

    pool = [q for q in QUOTES if q["id"] not in recent] or list(QUOTES)
    scored = [(_quote_relevance(q, themes, news_text), q) for q in pool]
    random.shuffle(scored)  # 完全な同点の並びを毎回変える
    scored.sort(key=lambda sq: (-sq[0], usage.get(sq[1]["id"], 0)))

    related = [q for s, q in scored if s > 0]
    if len(related) >= MIN_RELATED:
        return related[:count]
    others = [q for s, q in scored if s == 0]
    return (related + others)[:count]


QUOTE_CHOICE_PROMPT = """次のニュースに、マキャベリの箴言を一つ添えて論評する。
候補の中から、このニュースの本質に最もよく当てはまる箴言を一つ選べ。

ニュース見出し: {title}
概要: {summary}

候補:
{candidates}

選ぶ基準:
- ニュースに登場する主体の行動や置かれた立場に、箴言の述べる理が直接当てはまること
- 言葉が似ているだけのものではなく、構図が一致するものを選ぶこと

答えは候補の番号(半角数字)だけを書け。
"""


# 直近の generate_commentary() で採用した箴言のidと、その選び方("llm" / "rule")。
# generate_feed.py が feed.json に記録する。
LAST_QUOTE_ID = None
LAST_QUOTE_CHOICE = None


def _choose_quote_with_ollama(item: NewsItem, candidates: list) -> dict:
    """候補の中から、LLM(Ollama)に最もよく当てはまる箴言を番号で選ばせる。"""
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    title, summary = facts_for_prompt(item)
    listing = "\n".join(
        f"{i}. 「{q['ja']}」(当てはまる場面: {q['scene']})" for i, q in enumerate(candidates, 1)
    )
    answer = _ollama_generate(
        host, model,
        QUOTE_CHOICE_PROMPT.format(title=title, summary=summary, candidates=listing),
        {"temperature": 0.0, "top_k": 1, "num_predict": 8},
    )
    m = re.search(r"\d+", answer.translate(str.maketrans("０１２３４５６７８９", "0123456789")))
    if not m or not (1 <= int(m.group()) <= len(candidates)):
        raise ValueError(f"箴言の選択結果を読み取れない: {answer!r}")
    return candidates[int(m.group()) - 1]


def select_quote(item: NewsItem, prefer_llm: bool = True) -> dict:
    """
    記事に添える箴言を1つ選ぶ(使用履歴の記録は呼び出し側が行う)。
    prefer_llm=True なら、関連度上位の候補から LLM に最適な1件を選ばせる。
    """
    global LAST_QUOTE_CHOICE
    candidates = rank_quote_candidates(item)
    if prefer_llm and len(candidates) > 1:
        try:
            quote = _choose_quote_with_ollama(item, candidates)
            LAST_QUOTE_CHOICE = "llm"
            print(f"[箴言] 候補{len(candidates)}件からLLMが選択: {quote['id']}({quote['source']})")
            return quote
        except Exception as e:
            print(f"[箴言] LLMによる選択ができず、関連度1位を採用します: {e}")
    LAST_QUOTE_CHOICE = "rule"
    print(f"[箴言] 関連度1位を採用: {candidates[0]['id']}({candidates[0]['source']})")
    return candidates[0]


def pick_quote(theme: str) -> dict:
    """
    テーマだけを手がかりに箴言を1つ選ぶ(旧来の呼び出し口。LLMは使わない)。
    記事がある場合は select_quote(item) を使うこと。
    """
    return select_quote(NewsItem(title="", summary="", source="", theme=theme, themes=[theme]),
                        prefer_llm=False)


def _trim_japanese(text: str, max_len: int) -> str:
    """
    日本語テキストを安全に切り詰める。

    【重要な既知の不具合と、その回避】
    Python標準の textwrap.shorten() は英語のような「スペース区切りの単語」を
    前提としており、スペースを含まない日本語の文に使うと、文章全体が
    "1つの巨大な単語" とみなされ、幅に収まらない場合は中身が丸ごと消えて
    プレースホルダー(「…」)だけが返る、という不具合がある
    (実際に textwrap.shorten("長い日本語文...", width=40, placeholder="…") が
    "…" のみを返すことを確認済み)。これがツイートの意味不明な途切れの
    直接的な原因だったため、textwrap.shorten は日本語には一切使わず、
    この関数(文字単位でのスライス)に統一する。
    """
    if len(text) <= max_len:
        return text
    cut = text[: max(max_len - 1, 1)]
    # できるだけ句読点の直後で切れるよう、直近の「。」「、」を探す
    # (切り詰め幅の半分より前で見つかった場合は、削りすぎになるため採用しない)
    for punct in ("。", "、"):
        idx = cut.rfind(punct)
        if idx >= max_len // 2:
            return cut[: idx + 1]
    return cut.rstrip("、。 ") + "…"


_TRAILING_MEDIA = re.compile(r"[（(][^（）()]{1,20}[）)]$")


def _title_fragment(title: str, width: int = 28) -> str:
    """
    テンプレート文に差し込む見出しの断片を作る。
    末尾の「（朝鮮日報日本語版）」のような媒体名を除き、
    鉤括弧の途中で切れて「「北朝鮮が見えるス…」のように
    括弧が閉じないまま残る場合は、その鉤括弧の手前で切る。
    """
    frag = clean_news_text(title).strip()
    frag = _TRAILING_MEDIA.sub("", frag).strip().rstrip("。").rstrip("——")
    if len(frag) <= width:
        return frag
    cut = frag[:width]
    open_idx = max(cut.rfind("「"), cut.rfind("『"))
    if open_idx > max(cut.rfind("」"), cut.rfind("』")) and open_idx >= 6:
        return cut[:open_idx].rstrip(" 　、") + "…"
    return _trim_japanese(frag, width)


def _build_analysis(item: NewsItem) -> str:
    """テーマとニュース固有の断片・キーワードから、その記事だけに合う分析文を組み立てる。"""
    templates = THEME_ANALYSIS_TEMPLATES.get(item.theme) or THEME_ANALYSIS_TEMPLATES["necessita"]
    template = random.choice(templates)
    title = facts_for_prompt(item)[0]
    # 英語の見出しを日本語の文に差し込まないよう、訳が無ければ「この報道」で受ける
    frag = _title_fragment(title) if is_japanese(title) else "この報道"
    kws = [k for k in item.matched_keywords if not k.isascii()]
    kw = kws[0] if kws else "この動き"
    return template.format(frag=frag, kw=kw)


# 本文(分析文+箴言+出典)の字数上限。URLはこの字数に数えない。
#
# 【以前の不具合】
# 以前は「URLを含めた全体」を280字以内に収めていたため、Google News の
# 記事URL(200字を超えることが多い)が字数の大半を占め、本文側が
# 削られて、箴言が途中で切れたり出典が丸ごと消えたりしていた。
#
# 現在は本文だけに上限を適用する。サイト表示ではURLは
# 「〇〇の記事より」というリンクに置き換わるので、URLの長さは問題にならない。
# 250字は、ウィジェットの枠内で読み切れる長さとして決めた値である。
BODY_MAX_CHARS = 250


def _assemble_body(analysis: str, quote: dict, max_chars: int = BODY_MAX_CHARS) -> str:
    """
    分析文・箴言・出典を結合して本文を作る。
    上限を超える場合に削るのは分析文だけで、箴言と出典は決して削らない
    (引用が途中で切れたり出典が消えたりすることを構造的に防ぐ)。
    """
    citation = f"『{QUOTES_DB_SOURCE_LABEL(quote['source'])}』"
    quote_line = f"「{quote['ja']}」"
    fixed_len = len(quote_line) + len(citation) + 2  # 改行2つ分
    if len(analysis) + 1 + fixed_len > max_chars:
        analysis = _trim_japanese(analysis, max(max_chars - fixed_len - 1, 20))
    return f"{analysis}\n{quote_line}\n{citation}"


def _build_draft(item: NewsItem, max_chars: int = BODY_MAX_CHARS) -> str:
    """
    テーマ別分析文 + 箴言 + 出典からなる本文を組み立てる(URLは含まない)。
    定型合成モード(テンプレート)の本体。
    """
    return _assemble_body(_build_analysis(item), select_quote(item, prefer_llm=False), max_chars)


def generate_commentary_template(item: NewsItem, max_chars: int = BODY_MAX_CHARS) -> str:
    """
    APIキー無しで動作する定型合成モード。
    構成: [元記事URL] + [ニュースの具体的分析(テーマ・キーワード連動)] + [対応する箴言] + [出典]
    """
    return _prepend_source_link(_build_draft(item, max_chars=max_chars), item)


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


def _strip_bracket_annotations(text: str) -> str:
    """
    LLMが指示に反して付け加えることがある【随時更新】【引用】【下書き】や
    半角の[DRAFT]等の注釈・ラベルを機械的に除去する安全策。
    念のための二重の防御であり、プロンプト側の指示(付け加えないこと)が
    主たる対策である。全角【】・半角[]の両方に対応する。
    """
    # 全角【...】、半角[...] のいずれも、20文字以内の短いラベルとして除去する
    # (引用の出典表記『...』は対象外なので誤って消えることはない)
    cleaned = re.sub(r"【[^】]{0,20}】", "", text)
    cleaned = re.sub(r"\[[^\]]{0,20}\]", "", cleaned)
    # 文頭に残りがちな「下書き:」「回答:」等のラベル的接頭辞も除去
    cleaned = re.sub(
        r"^\s*(下書き|推敲(後|案)?|回答|出力|結果|返答|ツイート本文|DRAFT|Draft|Answer)\s*[:：]\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(r"[ \u3000]{2,}", " ", cleaned)  # 除去後にできる余分な空白を整理
    return cleaned.strip()


def _prepend_source_link(text: str, item: NewsItem) -> str:
    """
    つぶやきの先頭に、材料となったニュース記事のURLを付加する。
    URLは字数に数えず、本文を削ることもない(字数調整は _assemble_body で
    本文だけを対象に済ませてある)。
    item.url が空の場合(RSSにリンクが無い場合など)は本文のみを返す。
    """
    url = (getattr(item, "url", "") or "").strip()
    return f"{url}\n{text}" if url else text


SYSTEM_PROMPT_NOTE = """
以前はLLM(特にOllamaの軽量モデル)に「下書き全体(分析文+引用+出典)を
渡し、引用と出典は一字一句変えるな」という複雑な指示で丸ごと書き直させていたが、
小型モデルには同時に守るべき制約が多すぎ、品質不安定・余計なラベルの
混入(【下書き】等)の原因になっていた。

そこで役割を明確に分離した:
  ・LLMの仕事は「ニュースの本質を一文で言い当てる」ことだけに限定する
  ・引用文・出典・URLは常にPython側が機械的に(=確実に)組み立てる
この分離により、LLMが失敗・迷走してもその影響は分析文1文に限定され、
つぶやき全体の構成(引用の正確さ・出典・URL)は常に保証される。
"""

ANALYSIS_PROMPT = """次のニュースの本質を、マキャベリの現実主義的な視座から一文で言い当てよ。

ニュース見出し: {title}
概要: {summary}

この分析文のあとに、次のマキャベリの言葉を引用として添える:
「{quote}」

分析文はこの言葉への導入になるように書け。言葉の述べる理が、
このニュースのどの主体のどの行動・立場に当てはまるのかを具体的に示すこと。
ただし言葉そのものを言い換えて繰り返すだけの文にはしないこと。

最優先の条件(事実の扱い):
- 根拠にしてよい事実は、上の見出しと概要に書かれていることだけである。
  書かれていない出来事・行為・数字・動機・因果関係を補ってはならない
- 誰が何をしたのか、主語と行為の関係を見出しのとおりに保つこと。
  位置関係や主客を入れ替えてはならない。
  【誤りの例】見出し「A国側の国境から1.5km先にB国の砲台」を
  「A国が砲台を据えた」と書き換えるのは、主客を取り違えた誤りである
- 見出しが短く情報が乏しい場合は、書かれている範囲だけを控えめに論じ、
  事情を想像で埋めないこと
- マキャベリ的な評価・解釈を加えることは求められているが、それは
  書かれた事実に対する評価に限る

その他の条件:
- 出力は1文のみ。40字以上90字以内
- 必ず句点「。」で終わる、文法的に完結した1文にすること。
  文の途中で終わらせたり、「…」「...」で終えたりしてはならない
- 文体は「だ・である調」にすること。ただし「だ」は名詞・形容動詞の
  言い切りにのみ付ける助動詞であり、動詞の終止形(〜る、〜れる、〜られる等)
  にはそもそも付けない。動詞の終止形はそれ自体で言い切りが完成している。
  【正しい例】「現実的対応が求められる。」「米欧の結束が試される。」
  【誤った例(動詞に不要な「だ」を付けている。絶対にしないこと)】
  「現実的対応が求められるだ。」「米欧の結束が試されるだ。」
  【名詞・形容動詞の言い切りの正しい例】「これは力の論理の表れだ。」「危機は深刻である。」
- 「」『』などの引用符、URL、見出しラベル、前置きや説明は一切書かない
- 人名・組織名・役職名等の固有名詞は、見出しや概要に明記されているものだけを使うこと。
  正確な名称が分からない場合は、無理に固有名詞を作り出さず、
  「当局者」「政府筋」「軍当局」のような一般的な言い方に置き換えること
- このニュース固有の具体的な内容(登場する主体・地域・行動)に触れる。
  どの記事にも当てはまる一般論は禁止
- 出力は分析文一文のみ。それ以外は何も書くな
"""

# 動詞の終止形(〜れる・〜られる・〜する等)の直後に、文法的に誤って
# 「だ」が付加されるパターン(例:「求められるだ。」)を検出・修正する。
# 「だ」は名詞・形容動詞にのみ付く言い切りの助動詞であり、
# 動詞の終止形に付けるのは日本語として誤りである。
_INVALID_DA_PATTERN = re.compile(
    r"(れる|られる|できる|なる|かかる|向かう|進む|高まる|強まる|深まる|"
    r"広がる|続く|迫る|変わる|する|来る|示す|問う|映す|露わにする)"
    r"だ(?=[。」』]|$)"
)


def _fix_predicate_grammar(text: str) -> str:
    """
    「動詞の終止形+だ」という不自然な日本語(例:「求められるだ。」)を、
    「だ」を取り除くことで正しい形(「求められる。」)に修正する。
    プロンプト側で例示済みだが、小型モデルは指示を無視することがあるため、
    機械的な二重の防御としてここでも修正する。
    """
    return _INVALID_DA_PATTERN.sub(lambda m: m.group(1), text)


def _validate_analysis(text: str, min_len: int = 8, max_len: int = 120) -> str:
    """
    LLMが返した分析文を検証する。1行だけ取り出し、注釈ラベルを除去し、
    長さと文の完結性を確認する。条件を満たさない場合は例外を送出し、
    呼び出し側でのフォールバック(他モード・最終的にはテンプレート)を促す。

    特に「…」「...」で終わる、または句点で終わっていない文は、
    生成が途中で切れた不完全な文である可能性が高いため拒否する
    (これが以前、意味不明な尻切れのつぶやきが生成された主因だった)。
    """
    text = _strip_bracket_annotations(text)
    text = _fix_predicate_grammar(text)
    text = text.strip().split("\n")[0].strip()

    if not (min_len <= len(text) <= max_len):
        raise ValueError(f"分析文の長さが不正({len(text)}字): {text!r}")

    if "…" in text or "..." in text:
        raise ValueError(f"分析文が省略記号で終わっている(生成途中で切れた疑い): {text!r}")

    if not text.endswith(("。", "だ", "である", "べし", "べきだ", "ねばならぬ")):
        raise ValueError(f"分析文が文として完結していない: {text!r}")

    return text


# ---------------------------------------------------------------
# 事実の読み違い・作話への対策
# ---------------------------------------------------------------

# 分析文に出てきてよい、見出しに無くても構わない一般的なカタカナ語・英字
# (事実ではなく評価・修辞のための語)
_GENERIC_TERMS = {
    "マキャベリ", "マキャヴェリ", "マキアヴェッリ", "リアリズム", "パワー", "バランス",
    "パワーバランス", "リスク", "カード", "シグナル", "メッセージ", "ゲーム", "コスト",
    "ジレンマ", "イニシアチブ", "プレゼンス", "レバレッジ", "ライン", "ルール",
    "システム", "モデル", "パターン", "ポーズ", "アピール", "トップ", "リーダー",
    "エスカレーション", "ブラフ", "プロパガンダ", "メンツ", "タイミング", "チャンス",
    "サイン", "デモンストレーション", "パフォーマンス", "ポジション", "スタンス",
    "ストラテジー", "レトリック", "ナショナリズム", "ヘゲモニー", "リアリスト",
    "ヴィルトゥ", "フォルトゥーナ", "コントロール", "ゼロサム", "ダブルスタンダード",
    "ニュース", "サービス", "ステップ", "ネットワーク", "アクセス", "プロセス", "グループ",
    "レベル", "ポイント", "テーマ", "ケース", "イメージ", "ビジョン", "プラン", "オプション",
    "ベース", "スピード", "ペース", "トーン", "ムード", "ショック", "ダメージ",
}

_KATAKANA_RUN = re.compile(r"[ァ-ヴー・]{2,}")
_LATIN_RUN = re.compile(r"[A-Za-z]{2,}")
_DIGIT_RUN = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def _normalize_for_match(text: str) -> str:
    # 全角英数字を半角に揃え、中黒の有無の揺れを吸収して照合する
    text = text.translate(str.maketrans(
        "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ．",
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz."))
    return text.replace("・", "")


def _check_grounded_terms(analysis: str, title: str, summary: str, quote_text: str = "") -> None:
    """
    分析文に現れるカタカナ語(人名・地名・組織名の多くはカタカナ)、英字、数字が、
    見出し・概要に実際に含まれているかを機械的に照合する。
    含まれていないものがあれば、見出しに無い固有名詞や数字を作り出した
    (作話した)疑いがあるとして例外を送出し、生成をやり直させる。

    【この照合で防げるもの・防げないもの】
    防げる: 実在しない人名(以前発生した「伊ラキス・ハリーナク」のような例)、
            見出しに無い国名・組織名・数字の付け加え
    防げない: 語句は見出しどおりでも関係を取り違える誤り(例:「スタバの先に大砲」を
            「北朝鮮がスタバを要塞化」と読む誤り)。こちらは下記の
            _verify_with_ollama による事実照合で対処する。
    """
    # 添える箴言に出てくる語(「ローマ人」など)は、分析文で触れても作話ではない
    source = _normalize_for_match(f"{title} {summary} {quote_text}")
    norm = _normalize_for_match(analysis)
    missing = []
    for pattern in (_KATAKANA_RUN, _LATIN_RUN, _DIGIT_RUN):
        for term in pattern.findall(norm):
            term = term.strip("ー")
            if len(term) < 2 and pattern is not _DIGIT_RUN:
                continue
            if term in _GENERIC_TERMS or term in source:
                continue
            missing.append(term)
    if missing:
        raise ValueError(f"見出し・概要に無い語句を含む(作話の疑い): {missing}")


VERIFY_PROMPT = """あなたは報道の事実確認係である。
次の「分析文」を、「見出し」「概要」と照らし合わせて判定せよ。

見出し: {title}
概要: {summary}
分析文: {analysis}

判定基準:
- 分析文が、見出し・概要の事実と矛盾している(主語と行為の取り違え、
  位置関係や因果の取り違えを含む)なら「不適合」
- 分析文が、見出し・概要に書かれていない出来事・行為・数字を
  事実として付け加えているなら「不適合」
- 評価・比喩・マキャベリ的な解釈を述べているだけなら、それは問題にしない
- 上のどれにも当たらなければ「適合」

答えは「適合」か「不適合」の一語だけを書け。
"""


DEFAULT_OLLAMA_MODEL = "qwen3.5:9b"

# 推論型モデルが本文に混ぜて出力することがある思考ブロックを除去する
_THINK_BLOCK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """
    <think>...</think> で囲まれた思考過程を除去する。
    think:false を指定しても、モデルによっては思考を本文側に
    書き出すことがあるため(Ollamaの仕様上、無効化は「要求」であり
    保証ではない)、念のための防御としてここで取り除く。
    閉じタグが無い(=思考の途中で生成が打ち切られた)場合は、
    本文が無いものとして空文字を返し、検証段階で不合格にする。
    """
    text = _THINK_BLOCK_PATTERN.sub("", text)
    if "<think>" in text:
        return ""
    return text.strip()


def _ollama_generate(host: str, model: str, prompt: str, options: dict) -> str:
    """
    Ollama の /api/generate を呼び、思考ブロックを除いた本文を返す。
    think 指定に対応していないモデル・版でエラーになった場合は、
    指定を外して1回だけ再送する。
    """
    import requests  # pip install requests

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "options": options,
    }
    resp = requests.post(f"{host}/api/generate", json=payload, timeout=(5, 300))
    if resp.status_code == 400 and "think" in resp.text.lower():
        payload.pop("think")
        resp = requests.post(f"{host}/api/generate", json=payload, timeout=(5, 300))
    resp.raise_for_status()
    return _strip_thinking(resp.json().get("response") or "")


# ---------------------------------------------------------------
# 英語の記事の日本語化
# ---------------------------------------------------------------
#
# BBC・Al Jazeera など英語の配信から選ばれた記事は、見出しも概要も英語である。
# そのまま扱うと、(1) 分析文に訳したカタカナの人名・地名が「見出しに無い語」と
# 判定されて LLM の分析文が全て不合格になり、(2) 代わりのテンプレートに英語の
# 見出しがそのまま差し込まれていた(「Palestinians injured, arres…の核心は」)。
# そこで分析の前に見出しと概要を日本語に訳し、以後の処理は全て訳文で行う。

TRANSLATE_PROMPT = """次の英語のニュースの見出しと概要を、日本語に正確に訳せ。

見出し: {title}
概要: {summary}

条件:
- 書かれている内容だけを訳し、説明や推測を付け加えない
- 人名・地名・組織名は、日本の新聞で一般的な表記にする
  (例: West Bank → ヨルダン川西岸、Hamas → ハマス)
- 見出しは新聞の見出しらしく簡潔に、概要は「だ・である調」の文にする
- 次の2行の形式だけで答えよ。他には何も書くな
見出し: (訳)
概要: (訳)
"""

_SUMMARY_TRANSLATE_MAX = 500  # 英語の概要は長いことがあるので、訳す前にこの字数で切る


def _parse_translation(text: str, has_summary: bool) -> tuple:
    title_m = re.search(r"見出し\s*[:：]\s*(.+)", text)
    summary_m = re.search(r"概要\s*[:：]\s*(.+)", text)
    if not title_m:
        raise ValueError(f"訳の形式が読み取れない: {text!r}")
    title_ja = _strip_bracket_annotations(title_m.group(1).strip().strip("「」『』\"'"))
    summary_ja = summary_m.group(1).strip() if (summary_m and has_summary) else ""
    for part in (title_ja, summary_ja):
        if part and not is_japanese(part):
            raise ValueError(f"訳が日本語になっていない: {part!r}")
    if not (4 <= len(title_ja) <= 120):
        raise ValueError(f"訳した見出しの長さが不正: {title_ja!r}")
    return title_ja, summary_ja


def ensure_japanese(item: NewsItem) -> bool:
    """
    記事が日本語でなければ、見出しと概要を日本語に訳して item.title_ja・item.summary_ja に入れ、
    テーマも訳文で判定し直す。訳せなかった場合は例外を送出する(呼び出し側で記事を見送る)。
    日本語の記事、または訳済みの記事には何もせず False を返す。訳した場合は True。
    """
    title = clean_news_text(item.title)
    if is_japanese(title) or getattr(item, "title_ja", ""):
        return False
    summary = clean_news_text(item.summary or "")
    if summary.startswith(title):
        summary = summary[len(title):].strip(" -—")
    summary = summary[:_SUMMARY_TRANSLATE_MAX]
    prompt = TRANSLATE_PROMPT.format(title=title, summary=summary or "(なし)")

    errors = []
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    for attempt in range(2):
        try:
            answer = _ollama_generate(host, model, prompt,
                                      {"temperature": 0.0, "top_k": 1, "num_predict": 400})
            item.title_ja, item.summary_ja = _parse_translation(answer, bool(summary))
            break
        except Exception as e:
            errors.append(f"Ollama: {e}")
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(f"英語の記事を日本語に訳せなかった: {errors}")
        import anthropic  # pip install anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = "".join(b.text for b in msg.content if b.type == "text")
        item.title_ja, item.summary_ja = _parse_translation(answer, bool(summary))

    classify_themes(item)
    print(f"[翻訳] {title} → {item.title_ja}")
    return True


def _verify_with_ollama(host: str, model: str, analysis: str, title: str, summary: str) -> None:
    """
    同じモデルに事実確認係として判定させ、「不適合」なら例外を送出する。
    語句は見出しどおりでも関係を取り違える誤り(主客の入れ替え等)は、
    機械的な照合では見抜けないため、ここで判定させる。

    【限界】判定するのも同じ9Bクラスのモデルなので、誤りを見逃すことはある。
    判定が「適合」「不適合」のどちらとも読めない場合は、判定不能として
    通過させる(照合が原因で常に不合格になる事態を避けるため)。
    """
    verdict = _ollama_generate(
        host, model,
        VERIFY_PROMPT.format(title=title, summary=summary, analysis=analysis),
        {"temperature": 0.0, "top_k": 1, "num_predict": 16},
    )
    if "不適合" in verdict:
        raise ValueError(f"事実照合で不適合と判定された: {analysis!r}")
    if "適合" not in verdict:
        print(f"[分析文] 事実照合の判定を読み取れず、通過させました: {verdict!r}")


def _analysis_via_ollama(item: NewsItem, quote: dict, attempts: int = 3) -> str:
    """
    無料・独立のローカルLLM(Ollama)に、分析文1文だけを書かせる。
    外部APIに一切データを送らず、ローカル(またはCI実行環境内)で完結する。

    前提: Ollama (https://ollama.com) がインストールされ、`ollama serve` が起動していること。
    環境変数:
      OLLAMA_HOST  既定 "http://localhost:11434"
      OLLAMA_MODEL 既定 "qwen3.5:9b"(無料のオープンモデル。他の導入済みモデル名も指定可)

    【qwen3.5:9b 向けの設定】
    ・Qwen3.5 は「思考(thinking)」機能を持つ推論型モデルである。思考が有効だと、
      生成トークンの上限を思考だけで使い切り、本文が空になる恐れがある。
      そこで think:false を指定して思考を無効化する。
    ・think 指定に対応していないモデル・Ollamaの版でエラーになった場合は、
      think 指定を外して1回だけ再送する。
    ・GPUの無いGitHub Actions上では、初回はモデルをメモリに読み込むため
      応答に時間がかかる。読み取りタイムアウトは300秒と長めに取っている。
    ・生成した分析文は、次の3段階の検査を順に通す。1つでも不合格なら、
      最大 attempts 回まで生成をやり直す。それでも駄目なら例外を送出し、
      呼び出し側が他モード(最終的にはテンプレート)にフォールバックする。
        1. 形式の検査(文の完結性・長さ・省略記号)   … _validate_analysis
        2. 語句の照合(見出しに無い固有名詞・数字)   … _check_grounded_terms
        3. 事実照合(主客の取り違え・事実の付け加え) … _verify_with_ollama

    【サンプリング設定について】
    Qwen3.5 の汎用推奨値は temperature 0.7 / presence_penalty 1.5 だが、
    presence_penalty は「既に出た語を避ける」働きをするため、見出しの語句を
    そのまま使わず言い換え・作文に走らせる方向に効く。本用途では記事への
    忠実さを優先し、temperature 0.5 / presence_penalty 0.5 に下げている。
    """
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)

    title, summary = facts_for_prompt(item)
    prompt = ANALYSIS_PROMPT.format(title=title, summary=summary, quote=quote["ja"])
    options = {
        "temperature": 0.5,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 0.5,
        # 90字前後の日本語1文を確実に書き切れるだけの余裕
        "num_predict": 256,
    }

    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            text = _validate_analysis(_ollama_generate(host, model, prompt, options))
            _check_grounded_terms(text, title, summary, quote["ja"])
            _verify_with_ollama(host, model, text, title, summary)
            return text
        except ValueError as e:
            last_error = e
            print(f"[分析文] Ollama 生成結果が不合格(試行 {attempt}/{attempts}): {e}")
    raise last_error


def _analysis_via_anthropic(item: NewsItem, quote: dict, model: str = None) -> str:
    """
    Anthropic APIに、分析文1文だけを書かせる。
    環境変数 ANTHROPIC_API_KEY が設定されている場合のみ有効。
    """
    import anthropic  # pip install anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    title, summary = facts_for_prompt(item)
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": ANALYSIS_PROMPT.format(title=title, summary=summary, quote=quote["ja"]),
        }],
    )
    text = "".join(block.text for block in msg.content if block.type == "text")
    text = _validate_analysis(text)
    _check_grounded_terms(text, title, summary, quote["ja"])
    return text


# 直近の generate_commentary() で、分析文をどの生成元が作ったか。
# generate_feed.py が feed.json の "generator" 欄に記録する。
LAST_ANALYSIS_SOURCE = None


def _get_analysis(item: NewsItem, quote: dict, prefer_llm: bool = True) -> str:
    """
    分析文(1文)を得る。優先順位:
      1. Ollama(無料・ローカル、既定で最優先)
      2. Anthropic API(ANTHROPIC_API_KEY設定時)
      3. テーマ別テンプレート(常に成功する最終フォールバック、_build_analysis)

    以前は失敗理由を黙って握りつぶしていたため、Ollamaが動かずテンプレートに
    戻っていても気づけなかった。現在は失敗理由と、実際に採用した生成元を
    GitHub Actions のログに出力し、LAST_ANALYSIS_SOURCE にも記録する。
    """
    global LAST_ANALYSIS_SOURCE
    if prefer_llm:
        model = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        try:
            text = _analysis_via_ollama(item, quote)
            LAST_ANALYSIS_SOURCE = f"ollama:{model}"
            print(f"[分析文] Ollama({model}) で生成しました")
            return text
        except Exception as e:
            print(f"[分析文] Ollama({model}) を使えませんでした: {e}")
        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                text = _analysis_via_anthropic(item, quote)
                LAST_ANALYSIS_SOURCE = "anthropic"
                print("[分析文] Anthropic API で生成しました")
                return text
            except Exception as e:
                print(f"[分析文] Anthropic API を使えませんでした: {e}")
    LAST_ANALYSIS_SOURCE = "template"
    print("[分析文] テンプレートで生成しました(LLMが使えなかったための代替)")
    return _build_analysis(item)


def generate_commentary(item: NewsItem, prefer_llm: bool = True, max_chars: int = BODY_MAX_CHARS) -> str:
    """
    メインエントリポイント。つぶやきを組み立てる。

    処理の流れ(常にこの順序・この役割分担で行われる):
      1. 箴言を選ぶ               … select_quote()           (候補8件に絞り、LLMが1件を選ぶ)
      2. 分析文を1文だけ得る       … _get_analysis()          (選んだ箴言を踏まえてLLMが書く。失敗時はテンプレート)
      3. 分析文+引用+出典を結合    … ここで直接組み立てる       (決定的・Pythonが結合)
      4. 先頭に元記事URLを付加     … _prepend_source_link()  (決定的・常に正確)

    引用文・出典・URLは常にPython側が組み立てるため、LLMの出力内容に
    関わらず、これらが改変されたり欠落したりすることはない。

    この関数は「実際に投稿される1件」に対してのみ呼び出す想定であるため、
    箴言の選定と同時に使用履歴(record_quote_usage)を記録する。
    プレビュー目的で候補を試すだけの場合は generate_commentary_template を使うこと。
    """
    global LAST_QUOTE_ID
    if not is_japanese(clean_news_text(item.title)) and not item.title_ja:
        try:
            ensure_japanese(item)
        except Exception as e:
            # 訳せないまま進むと英語が本文に混ざるので、分析文はテンプレート
            # (見出しを差し込まない形)に切り替える
            print(f"[翻訳] {e}")
            prefer_llm = False
    quote = select_quote(item, prefer_llm=prefer_llm)
    analysis = _get_analysis(item, quote, prefer_llm=prefer_llm)
    body = _assemble_body(analysis, quote, max_chars)
    result = _prepend_source_link(body, item)

    LAST_QUOTE_ID = quote.get("id")
    if LAST_QUOTE_ID:
        record_quote_usage(LAST_QUOTE_ID)

    return result
