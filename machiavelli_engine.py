# -*- coding: utf-8 -*-
"""
machiavelli_engine.py
-----------------------
選別されたニュースと、対応するマキャベリの箴言から、
「マキャベリ人格」によるつぶやき文を生成する。

【生成プロセスの設計方針】
処理を4つの明確な役割に分離し、それぞれ何が(誰が)担当するかを固定している:

  1. 箴言を選ぶ            … pick_quote()            常にPythonが決定的に選ぶ
  2. 分析文を1文だけ得る    … _get_analysis()         LLM(失敗時はテンプレート)
  3. 分析文+引用+出典を結合 … generate_commentary()内  常にPythonが機械的に結合
  4. 先頭にURLを付加        … _prepend_source_link()  常にPythonが決定的に付加

LLMに任せるのは「ニュースの本質を一文で言い当てる」ことだけであり、
引用文・出典・URLにはLLMを一切関与させない。これにより、LLMが失敗・迷走しても
影響は分析文1文に限定され、引用の正確さや出典表記は常に保証される。

【箴言のローテーション】
pick_quote() は、直近5回の投稿で使った箴言を(同テーマ内に他の
選択肢がある限り)避け、さらに残った候補の中では通算使用回数が
最も少ないものを優先する。これにより、特定の箴言ばかりが繰り返し
引用されることを防ぎ、データベース全体をまんべんなく活用する。
使用履歴は logs/recent_quotes.json・logs/quote_usage.json に
永続化され、generate_commentary() が実際に採用した箴言についてのみ記録する。

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
import textwrap
from geopolitical_scorer import NewsItem, clean_news_text

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


RECENT_QUOTES_PATH = os.path.join(os.path.dirname(__file__), "logs", "recent_quotes.json")
QUOTE_USAGE_PATH = os.path.join(os.path.dirname(__file__), "logs", "quote_usage.json")
RECENT_QUOTES_WINDOW = 5  # 直近何回分の投稿で重複を避けるか


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


def pick_quote(theme: str) -> dict:
    """
    テーマに合う箴言を1つ選ぶ。「なるべく多くの箴言をまんべんなく活用する」ため、
    以下の優先順位(LRU: Least Recently Used)で選定する:

      1. 最も長く使われていない(直近の使用履歴に無い、または履歴上より古い)
         箴言を最優先する。プールが小さいテーマでも、これにより
         「2件しかないテーマで同じ箴言が連続で選ばれる」ような事態を避けられる。
      2. 同率で並んだ場合は、通算使用回数が最も少ないものを優先する。
      3. さらに同率の場合はランダムに選ぶ。

    使用履歴は logs/recent_quotes.json(直近RECENT_QUOTES_WINDOW件、新しい順)、
    通算使用回数は logs/quote_usage.json に永続化される。
    """
    pool = QUOTES_DB.get(theme) or QUOTES_DB["necessita"]
    recent_ids = load_recent_quote_ids()  # 新しい順のリスト
    usage = load_quote_usage()

    def recency_rank(qid):
        # 直近履歴に無ければ「一番古い(=最優先で選んでよい)」scoreとして扱う。
        # 履歴にあれば、そのインデックス(0が最も最近)をそのままscoreにする
        # ことで、「値が大きいほど、より長く使われていない」という指標にする。
        if qid in recent_ids:
            return recent_ids.index(qid)
        return len(recent_ids)

    max_rank = max(recency_rank(q.get("id")) for q in pool)
    candidates = [q for q in pool if recency_rank(q.get("id")) == max_rank]

    min_count = min(usage.get(q.get("id"), 0) for q in candidates)
    least_used = [q for q in candidates if usage.get(q.get("id"), 0) == min_count]
    return random.choice(least_used)


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


def _title_fragment(title: str, width: int = 28) -> str:
    frag = clean_news_text(title).strip().rstrip("。").rstrip("——")
    return _trim_japanese(frag, width)


def _build_analysis(item: NewsItem) -> str:
    """テーマとニュース固有の断片・キーワードから、その記事だけに合う分析文を組み立てる。"""
    templates = THEME_ANALYSIS_TEMPLATES.get(item.theme) or THEME_ANALYSIS_TEMPLATES["necessita"]
    template = random.choice(templates)
    frag = _title_fragment(item.title)
    kw = item.matched_keywords[0] if item.matched_keywords else "この動き"
    return template.format(frag=frag, kw=kw)


def _build_draft(item: NewsItem, max_chars: int = 230) -> str:
    """
    テーマ別分析文 + 箴言 + 出典からなる「下書き」を組み立てる(URLは含まない)。
    定型合成モードの本体であり、Ollama推敲モードの入力素材としても使う。
    """
    quote = pick_quote(item.theme)
    analysis = _build_analysis(item)
    citation = f"『{QUOTES_DB_SOURCE_LABEL(quote['source'])}』"

    draft = f"{analysis}\n「{quote['ja']}」\n{citation}"
    if len(draft) > max_chars:
        avail = max_chars - len(quote['ja']) - len(citation) - 8
        analysis = _trim_japanese(analysis, max(avail, 10))
        draft = f"{analysis}\n「{quote['ja']}」\n{citation}"
    return draft


def generate_commentary_template(item: NewsItem, max_chars: int = 280) -> str:
    """
    APIキー無しで動作する定型合成モード。
    構成: [ニュースの具体的分析(テーマ・キーワード連動、記事ごとに変化)] + [対応する箴言] + [出典]
    固定文が一律に付くことはなく、記事の内容とスコアリングで検出したキーワードに応じて
    分析文の型と差し込み語句が変わる。
    """
    draft = _build_draft(item, max_chars=max_chars - 40)
    return _prepend_source_link(draft, item, max_chars)


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
    import re
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
    trimmed = _trim_japanese(text, avail)
    return f"{url}\n{trimmed}"


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

条件:
- 出力は1文のみ。40字以上90字以内
- 必ず句点「。」で終わる、文法的に完結した1文にすること。
  文の途中で終わらせたり、「…」「...」で終えたりしてはならない
- 文末は「だ・である」調(〜である、〜だ、〜べし等)に統一する
- 「」『』などの引用符、URL、見出しラベル、前置きや説明は一切書かない
- 人名・組織名・役職名等の固有名詞は、見出しや概要に明記されているものだけを使うこと。
  正確な名称が分からない場合は、無理に固有名詞を作り出さず、
  「当局者」「政府筋」「軍当局」のような一般的な言い方に置き換えること
- このニュース固有の具体的な内容(登場する主体・地域・行動)に触れる。
  どの記事にも当てはまる一般論は禁止
- 出力は分析文一文のみ。それ以外は何も書くな
"""


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
    text = text.strip().split("\n")[0].strip()

    if not (min_len <= len(text) <= max_len):
        raise ValueError(f"分析文の長さが不正({len(text)}字): {text!r}")

    if "…" in text or "..." in text:
        raise ValueError(f"分析文が省略記号で終わっている(生成途中で切れた疑い): {text!r}")

    if not text.endswith(("。", "だ", "である", "べし", "べきだ", "ねばならぬ")):
        raise ValueError(f"分析文が文として完結していない: {text!r}")

    return text


def _analysis_via_ollama(item: NewsItem) -> str:
    """
    無料・独立のローカルLLM(Ollama)に、分析文1文だけを書かせる。
    外部APIに一切データを送らず、ローカル(またはCI実行環境内)で完結する。

    前提: Ollama (https://ollama.com) がインストールされ、`ollama serve` が起動していること。
    環境変数:
      OLLAMA_HOST  既定 "http://localhost:11434"
      OLLAMA_MODEL 既定 "qwen2.5:3b"(軽量・無料のオープンモデル。他の導入済みモデル名も指定可)
    Ollamaが起動していない、応答が不正、等の場合は例外を送出し、
    呼び出し側で他モードにフォールバックすること。
    """
    import requests  # pip install requests

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

    prompt = ANALYSIS_PROMPT.format(
        title=clean_news_text(item.title),
        summary=clean_news_text(item.summary),
    )
    resp = requests.post(
        f"{host}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.6,
                # 生成トークン数の上限が低すぎると、文の途中で打ち切られて
                # 尻切れの分析文になる。日本語は1文字が複数トークンに
                # 分割されることも多いため、90字の文を確実に書き切れるよう
                # 十分な余裕を持たせている。
                "num_predict": 200,
            },
        },
        timeout=(5, 60),
    )
    resp.raise_for_status()
    text = resp.json().get("response") or ""
    return _validate_analysis(text)


def _analysis_via_anthropic(item: NewsItem, model: str = None) -> str:
    """
    Anthropic APIに、分析文1文だけを書かせる。
    環境変数 ANTHROPIC_API_KEY が設定されている場合のみ有効。
    """
    import anthropic  # pip install anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": ANALYSIS_PROMPT.format(
                title=clean_news_text(item.title),
                summary=clean_news_text(item.summary),
            ),
        }],
    )
    text = "".join(block.text for block in msg.content if block.type == "text")
    return _validate_analysis(text)


def _get_analysis(item: NewsItem, prefer_llm: bool = True) -> str:
    """
    分析文(1文)を得る。優先順位:
      1. Ollama(無料・ローカル、既定で最優先)
      2. Anthropic API(ANTHROPIC_API_KEY設定時)
      3. テーマ別テンプレート(常に成功する最終フォールバック、_build_analysis)
    """
    if prefer_llm:
        try:
            return _analysis_via_ollama(item)
        except Exception:
            pass
        try:
            return _analysis_via_anthropic(item)
        except Exception:
            pass
    return _build_analysis(item)


def generate_commentary(item: NewsItem, prefer_llm: bool = True, max_chars: int = 280) -> str:
    """
    メインエントリポイント。つぶやきを組み立てる。

    処理の流れ(常にこの順序・この役割分担で行われる):
      1. 箴言を選ぶ               … pick_quote()             (決定的・直近5回の重複回避+偏り是正)
      2. 分析文を1文だけ得る       … _get_analysis()          (LLM、失敗時はテンプレート)
      3. 分析文+引用+出典を結合    … ここで直接組み立てる       (決定的・Pythonが結合)
      4. 先頭に元記事URLを付加     … _prepend_source_link()  (決定的・常に正確)

    引用文・出典・URLは常にPython側が組み立てるため、LLMの出力内容に
    関わらず、これらが改変されたり欠落したりすることはない。

    この関数は「実際に投稿される1件」に対してのみ呼び出す想定であるため、
    箴言の選定と同時に使用履歴(record_quote_usage)を記録する。
    プレビュー目的で候補を試すだけの場合は generate_commentary_template を使うこと。
    """
    quote = pick_quote(item.theme)
    citation = f"『{QUOTES_DB_SOURCE_LABEL(quote['source'])}』"
    analysis = _get_analysis(item, prefer_llm=prefer_llm)

    draft = f"{analysis}\n「{quote['ja']}」\n{citation}"
    if len(draft) > max_chars - 40:
        avail = (max_chars - 40) - len(quote['ja']) - len(citation) - 8
        analysis = _trim_japanese(analysis, max(avail, 10))
        draft = f"{analysis}\n「{quote['ja']}」\n{citation}"

    result = _prepend_source_link(draft, item, max_chars)

    if quote.get("id"):
        record_quote_usage(quote["id"])

    return result
