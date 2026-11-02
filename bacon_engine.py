# -*- coding: utf-8 -*-
"""
bacon_engine.py
----------------
選別された世論・メディア・科学技術のニュースと、ベーコンの著作の一節から、
「ベーコン人格」による論評を生成する。

【マキャベリボット・モンテーニュボットから受け継いだ設計】
処理の役割分担は machiavelli_engine.py / montaigne_engine.py と同じ。

  1. 引用を選ぶ            … select_quote()    Pythonが候補を絞り、LLMが1件を選ぶ
  2. 分析文を1文だけ得る    … _get_analysis()   LLM(失敗時はテンプレート)
  3. 分析文+引用+出典を結合 … _assemble_body()  常にPythonが機械的に結合
  4. 先頭にURLを付加        … machiavelli_engine._prepend_source_link()

引用文(訳と原文)・出典・URLにLLMは一切関与しない。LLMの出力は分析文1文だけで、
それも形式検査・説教口調の検査・引用の丸写し検査・語句照合(作話検出)・
事実照合を通す。Ollama 呼び出し、思考ブロック除去、「動詞+だ」の修正、
語句照合の仕組みは machiavelli_engine.py の関数を import して使う。

【ベーコンの視座(persona)— イドラの摘発】
- ニュースの出来事そのもの、またそれをめぐる報道・世論・専門家・技術の言説に、
  人間の知性を欺く四つのイドラのどれが働いているかを冷徹に指摘する。
    種族のイドラ … 人間に共通する癖(願望で信じる、肯定例だけを数える、目立つものに飛びつく)
    洞窟のイドラ … 個人の気質・教育・専門・立場による偏り
    市場のイドラ … 言葉・呼び名・レッテルが思考を支配すること
    劇場のイドラ … 権威・学説・イデオロギーという「舞台の上の世界」
- 断罪・称賛・説教・政策提言はしない。指摘するのは「知性の欺かれ方」であって、
  誰が善で誰が悪かではない。特定の政治的立場にも与しない。
- 技術や学問の進歩を手放しで讃えることも、恐れることもしない。
  「知は力なり」— 誰の知が誰の力になっているのか、という実相を見る。
"""

import json
import os
import random
import re

from geopolitical_scorer import NewsItem, facts_for_prompt, is_japanese, _MEDIA_SUFFIX
import machiavelli_engine as me    # 実績のある共通部品(Ollama呼び出し・検査・整形)
import montaigne_engine as mtg     # 説教口調の検査・丸写し検査など、姉妹ボットの部品

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUOTES_PATH = os.path.join(BASE_DIR, "data", "bacon_quotes.json")

with open(QUOTES_PATH, "r", encoding="utf-8") as f:
    QUOTES = json.load(f)["quotes"]
QUOTES_BY_ID = {q["id"]: q for q in QUOTES}

# 出典表記に添える篇題(本ボットによる訳。E59 は没後刊行の断章)
ESSAY_TITLES_JA = {
    "E1": "真理について",
    "E6": "偽装と隠し立てについて",
    "E9": "嫉妬について",
    "E12": "大胆について",
    "E15": "騒乱と動揺について",
    "E16": "無神論について",
    "E17": "迷信について",
    "E20": "助言について",
    "E22": "狡猾について",
    "E24": "革新について",
    "E26": "賢く見えることについて",
    "E31": "疑惑について",
    "E32": "談論について",
    "E35": "予言について",
    "E39": "習慣と教育について",
    "E50": "学問について",
    "E53": "称賛について",
    "E54": "虚栄について",
    "E58": "事物の転変について",
    "E59": "風評について",
}
FRAGMENT_ESSAYS = {"E59"}  # 1625年版には含まれない未完の断章


def source_label(quote: dict) -> str:
    """
    出典表記を作る。
      随筆集      『随筆集』第15篇「騒乱と動揺について」
      断章        『随筆集』断章「風評について」
      ノヴム・オルガヌム 『ノヴム・オルガヌム』第1巻 アフォリズム46
    """
    src = quote["source"]
    m = re.fullmatch(r"NO(\d)\.(\d+)", src)
    if m:
        return f"『ノヴム・オルガヌム』第{m.group(1)}巻 アフォリズム{m.group(2)}"
    title = ESSAY_TITLES_JA.get(src, "")
    if src in FRAGMENT_ESSAYS:
        return f"『随筆集』断章「{title}」"
    return f"『随筆集』第{src[1:]}篇「{title}」" if title else f"『随筆集』第{src[1:]}篇"


_DROP_CAPS = re.compile(r"^([A-Z]{2,})((?: [A-Z]{2,})*)(?=[\s?,;])")


def display_original(quote: dict) -> str:
    """
    原文を表示用に整える。照合済みの文字列(quote["orig"])自体は変えない。
      - 底本の篇冒頭の大文字書き(WHAT is truth / AS THE births)を通常の表記に戻す
      - 文の途中から始まる抜粋は先頭に「… 」、文の途中で終わる抜粋は末尾に「 …」を付け、
        抜粋であることを明示する
    """
    text = quote["orig"].strip()
    m = _DROP_CAPS.match(text)
    if m:
        head = m.group(1).capitalize() + m.group(2).lower()
        text = head + text[m.end():]
    if text[:1].islower():
        text = "… " + text
    if not text.endswith((".", "?", "!")):
        text = text.rstrip(";:,") + " …"
    return text


# ---------------------------------------------------------------
# 引用の使用履歴(他のボットとは別ファイルに永続化する)
# ---------------------------------------------------------------
RECENT_QUOTES_PATH = os.path.join(BASE_DIR, "logs", "bacon_recent_quotes.json")
QUOTE_USAGE_PATH = os.path.join(BASE_DIR, "logs", "bacon_quote_usage.json")
RECENT_QUOTES_WINDOW = 32  # 引用96件に対し、直近32回分(1日8回で4日分)は候補から外す


def load_recent_quote_ids() -> list:
    return me._load_json_file(RECENT_QUOTES_PATH, [])


def load_quote_usage() -> dict:
    return me._load_json_file(QUOTE_USAGE_PATH, {})


def record_quote_usage(quote_id: str) -> None:
    recent = [q for q in load_recent_quote_ids() if q != quote_id]
    recent.append(quote_id)
    me._save_json_file(RECENT_QUOTES_PATH, recent[-RECENT_QUOTES_WINDOW:])
    usage = load_quote_usage()
    usage[quote_id] = usage.get(quote_id, 0) + 1
    me._save_json_file(QUOTE_USAGE_PATH, usage)


# ---------------------------------------------------------------
# 引用の選び方(他のボットと同じ手順)
#   1. 直近に使った引用を外す
#   2. 記事のテーマ・適用場面の語との一致で関連度を付ける
#   3. 上位8件を LLM に見せ、最もよく当てはまる1件を番号で選ばせる
# ---------------------------------------------------------------
CANDIDATE_COUNT = 8
MIN_RELATED = 4


def _quote_relevance(quote: dict, themes: list, news_text: str) -> int:
    """テーマ一致(主テーマ3点・2番目2点・以降1点)+適用場面の語の一致(1語2点、最大6点)。"""
    score = 0
    for idx, theme in enumerate(themes):
        if theme in quote["tags"]:
            score += max(3 - idx, 1)
    score += 2 * min(sum(1 for w in mtg._scene_words(quote) if w in news_text), 3)
    return score


def rank_quote_candidates(item: NewsItem, count: int = CANDIDATE_COUNT) -> list:
    themes = getattr(item, "themes", None) or [item.theme or "tribus"]
    title, summary = facts_for_prompt(item)
    news_text = f"{title} {summary}"
    recent = set(load_recent_quote_ids())
    usage = load_quote_usage()

    pool = [q for q in QUOTES if q["id"] not in recent] or list(QUOTES)
    scored = [(_quote_relevance(q, themes, news_text), q) for q in pool]
    random.shuffle(scored)
    scored.sort(key=lambda sq: (-sq[0], usage.get(sq[1]["id"], 0)))

    related = [q for s, q in scored if s > 0]
    if len(related) >= MIN_RELATED:
        return related[:count]
    return (related + [q for s, q in scored if s == 0])[:count]


QUOTE_CHOICE_PROMPT = """次のニュースに、フランシス・ベーコンの著作の一節を一つ添えて論評する。
論評の主眼は、このニュース(出来事そのもの、またはそれをめぐる報道・世論・専門家・技術の言説)に
働いている「人間の知性の欺かれ方」を指摘することにある。
候補の中から、それに最もよく当てはまる一節を一つ選べ。

ニュース見出し: {title}
概要: {summary}

候補:
{candidates}

選ぶ基準:
- ニュースに現れた人々(当事者・報道・世間・専門家)の考え方や言葉の使い方に、
  一節の述べる知性の欺かれ方や知と力の関係が直接当てはまること
- 言葉が似ているだけのものではなく、構図が一致するものを選ぶこと
- 亡くなった人や被害に遭った人を愚かだと言うような響きになるものは選ばないこと

答えは候補の番号(半角数字)だけを書け。
"""

LAST_QUOTE_ID = None
LAST_QUOTE_CHOICE = None
LAST_ANALYSIS_SOURCE = None


def _choose_quote_with_ollama(item: NewsItem, candidates: list) -> dict:
    host, model = mtg._ollama_env()
    title, summary = facts_for_prompt(item)
    listing = "\n".join(
        f"{i}. 「{q['ja']}」(当てはまる場面: {q['scene']})" for i, q in enumerate(candidates, 1)
    )
    answer = me._ollama_generate(
        host, model,
        QUOTE_CHOICE_PROMPT.format(title=title, summary=summary, candidates=listing),
        {"temperature": 0.0, "top_k": 1, "num_predict": 8},
    )
    m = re.search(r"\d+", answer.translate(str.maketrans("０１２３４５６７８９", "0123456789")))
    if not m or not (1 <= int(m.group()) <= len(candidates)):
        raise ValueError(f"引用の選択結果を読み取れない: {answer!r}")
    return candidates[int(m.group()) - 1]


def select_quote(item: NewsItem, prefer_llm: bool = True) -> dict:
    global LAST_QUOTE_CHOICE
    candidates = rank_quote_candidates(item)
    if prefer_llm and len(candidates) > 1:
        try:
            quote = _choose_quote_with_ollama(item, candidates)
            LAST_QUOTE_CHOICE = "llm"
            print(f"[引用] 候補{len(candidates)}件からLLMが選択: {quote['id']}")
            return quote
        except Exception as e:
            print(f"[引用] LLMによる選択ができず、関連度1位を採用します: {e}")
    LAST_QUOTE_CHOICE = "rule"
    print(f"[引用] 関連度1位を採用: {candidates[0]['id']}")
    return candidates[0]


# ---------------------------------------------------------------
# テンプレート(LLMが使えないときの最終フォールバック)
# ---------------------------------------------------------------
THEME_ANALYSIS_TEMPLATES = {
    "tribus": [
        "{frag}をめぐる受け止め方には、望むことを真と信じ、当たった例だけを数える種族のイドラが働いている。",
        "{frag}に人々が見ているのは事実そのものより、人間の知性という歪んだ鏡に映った像である。",
    ],
    "specus": [
        "{frag}をめぐる見方の食い違いは、各人がそれぞれの洞窟から自然の光を眺めていることの表れである。",
        "{frag}の評価が立場ごとに割れるのは、教育と専門と慣れが、それぞれの知性を染めているからだ。",
    ],
    "fori": [
        "{frag}をめぐる議論では、言葉が事物を指すのをやめ、言葉そのものが人々の思考を引き回している。",
        "{frag}は、名づけ方ひとつで人の判断が動くという、市場のイドラの力を示している。",
    ],
    "theatri": [
        "{frag}をめぐる言説には、論証よりも権威と学説に拠って立つ、劇場のイドラの舞台装置が見える。",
        "{frag}に語られる筋書きは、事実から組み上げられたものというより、あらかじめ用意された舞台の台本に近い。",
    ],
    "fama": [
        "{frag}をめぐる反響は、評判の川が軽いものを浮かべ、重いものを沈める様をそのまま映している。",
        "{frag}の広がり方には、論証ではなく評判と世論によって物事が決まってゆく構図が見える。",
    ],
    "superstitio": [
        "{frag}には、当たった例だけを記憶し、外れた例を忘れる人間の性が、迷信の形をとって現れている。",
        "{frag}は、事物のうちに実際以上の秩序と意図を読み込む知性の癖を、改めて示している。",
    ],
    "simulatio": [
        "{frag}は、心を通り過ぎる嘘よりも、心に沈み込んで住みつく嘘のほうが害をなすことを示している。",
        "{frag}に見えるのは、真実を語る時を知る強さを欠いた者が、隠し立てに頼る構図である。",
    ],
    "experientia": [
        "{frag}をめぐっては、経験と検証が答えを出す前に、意見が先に結論を急いでいる。",
        "{frag}は、否定的な事例を顧みない限り、知性は肯定的な事例に引きずられるということを思い出させる。",
    ],
    "potentia": [
        "{frag}は、知識と力とが一つに重なり、技術を握る者が力を握るという理を映している。",
        "{frag}の行方を決めるのは理念ではなく、誰がその技術の原因と仕組みを知り、使いこなすかである。",
    ],
    "novitas": [
        "{frag}は、時の産み落とす革新がいつも初めは不格好であり、古い物差しでは測れないことを示している。",
        "{frag}をめぐる期待と警戒は、新しいものを古いものの類推で占う、人の当て推量の表れである。",
    ],
    "studium": [
        "{frag}は、学問が人間の生活に新たな発明と富を授けるという目標から、どれほど隔たっているかを映している。",
        "{frag}をめぐる議論には、学問を軽んじる者、崇める者、用いる者の違いがそのまま表れている。",
    ],
}


def _build_analysis(item: NewsItem, quote: dict = None) -> str:
    """
    テンプレートから分析文を作る。引用が決まっていれば、そのタグのうち
    記事のテーマとも一致するものを優先して型を選ぶ(引用と分析文の食い違いを避ける)。
    """
    themes = getattr(item, "themes", None) or [item.theme or "tribus"]
    theme = themes[0]
    if quote:
        shared = [t for t in themes if t in quote["tags"]]
        theme = shared[0] if shared else quote["tags"][0]
    templates = THEME_ANALYSIS_TEMPLATES.get(theme) or THEME_ANALYSIS_TEMPLATES["tribus"]
    # 見出し末尾の媒体名(「 - 日本経済新聞」)を除いてから断片を取る
    title = _MEDIA_SUFFIX.sub("", facts_for_prompt(item)[0]).strip()
    frag = me._title_fragment(title) if is_japanese(title) else "この報道"
    frag = re.sub(r"[ 　]+", "、", frag.strip())
    return random.choice(templates).format(frag=frag)


# ---------------------------------------------------------------
# 本文の組み立て
# ---------------------------------------------------------------
BODY_MAX_CHARS = 280  # 引用が長めで出典表記も長いため、モンテーニュ側(260)より少し長く取る


def _assemble_body(analysis: str, quote: dict, max_chars: int = BODY_MAX_CHARS) -> str:
    """分析文・引用(訳)・出典を結合する。上限を超えたら削るのは分析文だけ。
    原文(英語・ラテン語)は本文に入れず、フィードの別欄(original)で配信する。"""
    citation = source_label(quote)
    quote_line = f"「{quote['ja']}」"
    fixed_len = len(quote_line) + len(citation) + 2
    if len(analysis) + 1 + fixed_len > max_chars:
        analysis = me._trim_japanese(analysis, max(max_chars - fixed_len - 1, 20))
    return f"{analysis}\n{quote_line}\n{citation}"


# ---------------------------------------------------------------
# LLM による分析文
# ---------------------------------------------------------------
ANALYSIS_PROMPT = """次のニュースに働いている「人間の知性の欺かれ方」を、フランシス・ベーコンの
イドラ論の視座から、冷徹に一文で指摘せよ。

ニュース見出し: {title}
概要: {summary}

この分析文のあとに、次のベーコンの言葉を引用として添える:
「{quote}」

分析文はこの言葉への導入になるように書け。言葉の述べる知性の欺かれ方
(願望で信じること、肯定的な例だけを数えること、目立つものに飛びつくこと、
立場や専門による偏り、言葉や呼び名に思考が支配されること、権威や学説への追従など)
あるいは知と力の関係が、このニュースの、誰の、どの考え方・言葉・反応に
現れているのかを具体的に示すこと。
ただし言葉そのものを言い換えて繰り返すだけの文にはしないこと。

視座(厳守):
- 指摘するのは「知性の欺かれ方」であって、誰が善で誰が悪かではない。
  誰かを断罪することも称賛することもしない
- 説教、教訓、政策提言は書かない。「〜すべきだ」「〜が求められる」「〜が必要だ」の類は禁止
- 特定の政治的立場や陣営に与しない。偏りを指摘するなら、どの陣営の偏りも同じ冷たさで扱う
- 技術や学問の進歩を手放しで讃えることも、恐れることもしない
- 亡くなった人や被害に遭った人を愚かだと評してはならない(例: 詐欺の被害者を
  「欲に目がくらんだ」と評する)。知性の欺かれ方を論じるなら、欺いた側や、
  出来事を語る報道・世間・専門家の言説に目を向けること
- 「イドラ」という語は使ってよいが、使わなくてもよい。使うなら、どのイドラかが
  ニュースの具体的な内容と結びついていること

最優先の条件(事実の扱い):
- 根拠にしてよい事実は、上の見出しと概要に書かれていることだけである。
  書かれていない出来事・行為・数字・動機・因果関係・世間の反応を補ってはならない
- 誰が何をしたのか、主語と行為の関係を見出しのとおりに保つこと。主客を入れ替えてはならない
- 見出しが短く情報が乏しい場合は、書かれている範囲だけを控えめに論じ、
  事情を想像で埋めないこと

その他の条件:
- 出力は1文のみ。40字以上90字以内
- 必ず句点「。」で終わる、文法的に完結した1文にすること。
  文の途中で終わらせたり、「…」「...」で終えたりしてはならない
- 文体は「だ・である調」にすること。ただし「だ」は名詞・形容動詞の
  言い切りにのみ付ける助動詞であり、動詞の終止形(〜る、〜れる、〜られる等)
  にはそもそも付けない。動詞の終止形はそれ自体で言い切りが完成している。
  【正しい例】「人は望むものを真と信じる。」「呼び名が判断を先回りしている。」
  【誤った例(絶対にしないこと)】「人は望むものを真と信じるだ。」「呼び名が判断を先回りしているだ。」
  【名詞の言い切りの正しい例】「これは市場のイドラの働きだ。」「知と力は一つである。」
- 「」『』などの引用符、URL、見出しラベル、前置きや説明は一切書かない
- 人名・組織名・地名などの固有名詞は、見出しや概要に明記されているものだけを使うこと
- このニュース固有の具体的な内容(登場する人々・技術・出来事)に触れる。
  どの記事にも当てはまる一般論は禁止
- 出力は分析文一文のみ。それ以外は何も書くな
"""

# 見出しに無くても分析文に出てきてよい一般的なカタカナ語・英字
_GENERIC_TERMS = set(mtg._GENERIC_TERMS) | {
    "ベーコン", "イドラ", "ノヴム・オルガヌム", "オルガヌム", "バイアス", "レッテル",
    "ラベル", "スローガン", "キャッチフレーズ", "ブーム", "イメージ", "ストーリー",
    "シナリオ", "ナラティブ", "テクノロジー", "メカニズム", "データ", "エビデンス",
    "ロジック", "パニック", "デマ", "センセーショナル", "インパクト", "ノイズ",
}


def _check_grounded_terms(analysis: str, title: str, summary: str, quote_text: str = "") -> None:
    """
    分析文のカタカナ語・英字・数字が見出し・概要(と引用)に含まれるかを照合する。
    仕組みは machiavelli_engine._check_grounded_terms と同じで、
    許容する一般語だけをベーコン用に広げている。
    """
    source = me._normalize_for_match(f"{title} {summary} {quote_text}")
    norm = me._normalize_for_match(analysis)
    missing = []
    for pattern in (me._KATAKANA_RUN, me._LATIN_RUN, me._DIGIT_RUN):
        for term in pattern.findall(norm):
            term = term.strip("ー・")
            if len(term) < 2 and pattern is not me._DIGIT_RUN:
                continue
            if term in _GENERIC_TERMS or term in source:
                continue
            missing.append(term)
    if missing:
        raise ValueError(f"見出し・概要に無い語句を含む(作話の疑い): {missing}")


def _analysis_via_ollama(item: NewsItem, quote: dict, attempts: int = 3) -> str:
    """設定・検査の段取りは montaigne_engine._analysis_via_ollama と同じ。"""
    host, model = mtg._ollama_env()
    title, summary = facts_for_prompt(item)
    prompt = ANALYSIS_PROMPT.format(title=title, summary=summary, quote=quote["ja"])
    options = {
        "temperature": 0.5,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 0.5,
        "num_predict": 256,
    }
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            text = mtg._validate_analysis(me._ollama_generate(host, model, prompt, options))
            mtg._check_not_restating(text, quote["ja"])
            _check_grounded_terms(text, title, summary, quote["ja"])
            mtg._verify_with_ollama(host, model, text, title, summary)
            return text
        except ValueError as e:
            last_error = e
            print(f"[分析文] Ollama 生成結果が不合格(試行 {attempt}/{attempts}): {e}")
    raise last_error


def _analysis_via_anthropic(item: NewsItem, quote: dict) -> str:
    import anthropic  # pip install anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    title, summary = facts_for_prompt(item)
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
        max_tokens=150,
        messages=[{"role": "user",
                   "content": ANALYSIS_PROMPT.format(title=title, summary=summary, quote=quote["ja"])}],
    )
    text = mtg._validate_analysis("".join(b.text for b in msg.content if b.type == "text"))
    mtg._check_not_restating(text, quote["ja"])
    _check_grounded_terms(text, title, summary, quote["ja"])
    return text


def _get_analysis(item: NewsItem, quote: dict, prefer_llm: bool = True) -> str:
    """Ollama → Anthropic API → テンプレート の順に試す。"""
    global LAST_ANALYSIS_SOURCE
    if prefer_llm:
        _, model = mtg._ollama_env()
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
    return _build_analysis(item, quote)


def generate_commentary(item: NewsItem, prefer_llm: bool = True, max_chars: int = BODY_MAX_CHARS) -> str:
    """
    メインエントリポイント。論評を組み立て、採用した引用の使用履歴を記録する。
    実際に掲載する1件に対してのみ呼ぶこと。
    """
    global LAST_QUOTE_ID
    quote = select_quote(item, prefer_llm=prefer_llm)
    analysis = _get_analysis(item, quote, prefer_llm=prefer_llm)
    body = _assemble_body(analysis, quote, max_chars)
    result = me._prepend_source_link(body, item)

    LAST_QUOTE_ID = quote["id"]
    record_quote_usage(LAST_QUOTE_ID)
    return result
