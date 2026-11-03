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

    allowed = list(QUOTES)
    if getattr(item, "political", False):
        # 政治がらみの記事では、人を愚か・軽率・盲従と評する響きの引用を使わない
        allowed = [q for q in QUOTES if not q.get("avoid_in_politics")]
    pool = [q for q in allowed if q["id"] not in recent] or allowed
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
- 政治家・政党の支持者や有権者、特定の集団を愚か・軽率だと評する響きになるものは選ばないこと

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
# 【注意】型の文面には、特定の引用に固有の比喩(「評判の川」「歪んだ鏡」「洞窟」
# 「当たった例だけを数える」など)を使わない。型は引用と無関係に選ばれうるので、
# 別の引用と並んだときに比喩が食い違う(実例: 「評判の川」の型が、集団の習慣を
# 述べる第39篇の引用と並んだ)。各テーマの心の動きを、平易な言葉でだけ述べる。
THEME_ANALYSIS_TEMPLATES = {
    "tribus": [
        "{frag}をめぐる受け止め方には、確かめられた事実よりも、受け取る側の期待や不安が先に立っている。",
        "{frag}には、人が物事をあるがままにではなく、見たいように見てしまう癖が表れている。",
    ],
    "specus": [
        "{frag}への見方は、それぞれの立場や経験によって、同じ出来事が別の姿に見えることを示している。",
        "{frag}の評価が割れるのは、各人が自分の慣れ親しんだ物差しで測っているからである。",
    ],
    "fori": [
        "{frag}をめぐっては、出来事の中身よりも、それに付けられた言葉や呼び名が人々の判断を左右している。",
        "{frag}は、言葉の選び方ひとつで、同じ事柄の受け取られ方が変わることを示している。",
    ],
    "theatri": [
        "{frag}をめぐる言説には、事実を確かめるより先に、権威や既存の筋書きに寄りかかる傾きが見える。",
        "{frag}について語られる説明は、事実から組み上げたものというより、用意された筋書きに事実を当てはめたものに近い。",
    ],
    "fama": [
        "{frag}は、物事の重みとは別に、話題性と評判によって人の関心が動いてゆく様を映している。",
        "{frag}の広がり方には、確かめることよりも語り広めることが先に立つ、世評の性質が表れている。",
    ],
    "superstitio": [
        "{frag}には、偶然の出来事にも意味や意図を読み込もうとする、人の心の癖が現れている。",
        "{frag}は、根拠の確かさよりも、話のもっともらしさが人を信じさせることを示している。",
    ],
    "simulatio": [
        "{frag}は、事実を隠し、あるいは装うことが、かえって疑いと不信を育てる構図を示している。",
        "{frag}に見えるのは、見せたい姿と実際の姿との食い違いである。",
    ],
    "experientia": [
        "{frag}をめぐっては、検証の結果が出る前に、意見のほうが先に結論を急いでいる。",
        "{frag}は、試して確かめることを経なければ、思い込みと事実とを分けられないことを示している。",
    ],
    "potentia": [
        "{frag}は、技術を知り使いこなす者が、そのまま力を持つ者になるという構図を映している。",
        "{frag}の行方を決めるのは理念ではなく、誰がその仕組みを理解し、扱えるかである。",
    ],
    "novitas": [
        "{frag}は、新しい技術や仕組みが、古い物差しでは測りきれないものであることを示している。",
        "{frag}をめぐる期待と警戒には、新しいものを古いものになぞらえて推し量る人の習いが表れている。",
    ],
    "studium": [
        "{frag}は、学問と研究が社会のなかでどう扱われているかを、はっきりと映し出している。",
        "{frag}をめぐる議論には、知識の中身よりも、誰がそれを語るかに目が向く傾きが見える。",
    ],
}


def _build_analysis(item: NewsItem, quote: dict = None) -> str:
    """
    テンプレートから分析文を作る。引用が決まっていれば、そのタグのうち
    記事のテーマとも一致するものを優先して型を選ぶ(引用と分析文の食い違いを避ける)。
    """
    themes = getattr(item, "themes", None) or [item.theme or "tribus"]
    theme = _theme_for(item, quote) if quote else themes[0]
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
# 【分析文の手がかり】
# 引用の文言をそのまま LLM に見せて「同じ心の動きを示せ」と求めると、小型モデルは
# 引用の語句を文に無理に取り込み、事実照合で落ちる(実例: 「機械的発明が人間に及ぼす
# 影響力という期待に引きずり込んでいる」)。そこで引用そのものは見せず、引用のテーマに
# 対応する心の動きを平易な言葉で渡し、「見出しの出来事 → そこに見える心の動き」の型で書かせる。
# テーマは、記事のテーマと引用のタグが重なるものを優先する(テンプレートと同じ選び方)。
THEME_HINTS = {
    "tribus": "人が、確かめた事実よりも、自分の期待や不安、目を引く印象に引きずられて物事を受け止めていること",
    "specus": "人が、自分の立場・専門・経験という狭い見方から物事を判断していること",
    "fori": "出来事の中身より先に、言葉や呼び名・レッテルが人の受け止め方を決めてしまっていること",
    "theatri": "人が、自分で確かめるより先に、権威や専門家の名、出来上がった筋書きに寄りかかっていること",
    "fama": "物事の重みとは別に、噂・評判・話題性によって人の関心や判断が動いていること",
    "superstitio": "人が、根拠の乏しい話や当たった例だけを信じ、偶然に意味を読み込んでいること",
    "simulatio": "誰かが事実を隠したり装ったりして、見せかけと実際とが食い違っていること",
    "experientia": "試して確かめる前に結論が先走っていること、あるいは確かめてはじめて真偽が分かること",
    "potentia": "技術や知識を持つ者が、そのまま力を持つ者になっていること",
    "novitas": "新しい技術や仕組みが、古い物差しや過去の例からの類推で推し量られていること",
    "studium": "学問や研究が、その中身よりも、扱われ方や誰が語るかによって評価されていること",
}


def _theme_for(item: NewsItem, quote: dict) -> str:
    themes = getattr(item, "themes", None) or [item.theme or "tribus"]
    shared = [t for t in themes if t in quote["tags"]]
    return shared[0] if shared else quote["tags"][0]


def _analysis_prompt(item: NewsItem, quote: dict) -> str:
    title, summary = facts_for_prompt(item)
    return ANALYSIS_PROMPT.format(title=title, summary=summary,
                                  hint=THEME_HINTS[_theme_for(item, quote)])


ANALYSIS_PROMPT = """次のニュースについて、フランシス・ベーコンのように突き放した目で、平易な言葉で一文を書け。

ニュース見出し: {title}
概要: {summary}

観察の手がかり(このニュースのどこにこれが見えるかを書く):
{hint}

書き方:
- 文の前半で、見出しに書かれた具体的な出来事(誰が何をしたか、何が起きたか)を短く押さえる
- 文の後半で、その出来事のどこに上の手がかりの心の動きが見えるのかを、ふつうの言葉で言い当てる
- 型の目安:「(見出しの出来事)には、(誰が)(何に)(どう引きずられているか)が表れている。」
  ただし言い回しはこの型どおりでなくてよい
- 手がかりの文をそのまま書き写さないこと。「心の動き」「観察」「手がかり」「冷徹」という語
  そのものは書かず、その中身(誰が、何を、どう受け止め、どう扱っているか)を書くこと
- 見出しに出来事が乏しい場合も、書かれている範囲で、誰の受け止め方や扱い方かを具体的に書く

視座(厳守):
- 指摘するのは「知性の欺かれ方」であって、誰が善で誰が悪かではない。
  誰かを断罪することも称賛することもしない
- 説教、教訓、政策提言は書かない。「〜すべきだ」「〜が求められる」「〜が必要だ」の類は禁止
- 特定の政治的立場や陣営に与しない。偏りを指摘するなら、どの陣営の偏りも同じ冷たさで扱う
- 技術や学問の進歩を手放しで讃えることも、恐れることもしない
- 政治家・政党の支持者や有権者、特定の世代・集団を、愚か・軽率・流されやすいと評してはならない。
  世論の動きを論じるなら、その動きを生んだ報道や話題の扱われ方に目を向けること
- 亡くなった人や被害に遭った人を愚かだと評してはならない(例: 詐欺の被害者を
  「欲に目がくらんだ」と評する)。知性の欺かれ方を論じるなら、欺いた側や、
  出来事を語る報道・世間・専門家の言説に目を向けること
- 「イドラ」「知性が欺かれる」「思考が支配される」のような抽象的な用語や決まり文句は使わない。
  学術用語で飾らず、何が起きていて、そこにどんな心の動きが見えるかだけを書く

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
  【名詞の言い切りの正しい例】「これは呼び名の力だ。」「知と力は一つである。」
- 「」『』などの引用符、URL、見出しラベル、前置きや説明は一切書かない
- 人名・組織名・地名などの固有名詞は、見出しや概要に明記されているものだけを使うこと
- このニュース固有の具体的な内容(登場する人々・技術・出来事)に触れる。
  どの記事にも当てはまる一般論は禁止
- 出力は分析文一文のみ。それ以外は何も書くな
"""

# 見出しに無くても分析文に出てきてよい一般的なカタカナ語・英字
_GENERIC_TERMS = set(mtg._GENERIC_TERMS) | {
    "ベーコン", "バイアス", "レッテル",
    "ラベル", "スローガン", "キャッチフレーズ", "ブーム", "イメージ", "ストーリー",
    "シナリオ", "ナラティブ", "テクノロジー", "メカニズム", "データ", "エビデンス",
    "ロジック", "パニック", "デマ", "センセーショナル", "インパクト", "ノイズ",
}


# 小型モデルが飛びつきやすい、中身のない抽象語・決まり文句
# (実例: 「言葉の呼び名に思考が支配されるイドラによって知性が欺かれた姿だ」が3回続いた)
# プロンプトの指示語をそのまま文に持ち込んだものも落とす
# (実例: 「…をどう扱うかという冷徹な観察が見える」)
_JARGON_PATTERN = re.compile(
    r"(イドラ|知性が欺|知性を欺|思考が支配|思考を支配|欺かれ方|冷徹|観察が見え|心の動きが見え|手がかり)"
)
_JA = r"[\u3040-\u30ff\u3400-\u9fff々ー]"
_SPACE_AROUND_ASCII = re.compile(rf"(?<={_JA})[ \u3000]+(?=[A-Za-z0-9])|(?<=[A-Za-z0-9])[ \u3000]+(?={_JA})")


def _validate_analysis(text: str) -> str:
    """
    モンテーニュ側の検査(形式・説教口調)に、抽象語の検査を加える。
    あわせて「生成 AI」のような和文と英数字の間の空白を詰める。
    """
    text = mtg._validate_analysis(text)
    text = _SPACE_AROUND_ASCII.sub("", text)
    if _JARGON_PATTERN.search(text):
        raise ValueError(f"抽象語・決まり文句に頼っている(具体的に書かれていない): {text!r}")
    return text


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
    prompt = _analysis_prompt(item, quote)
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
            text = _validate_analysis(me._ollama_generate(host, model, prompt, options))
            mtg._check_not_restating(text, quote["ja"])
            mtg._check_not_restating(text, THEME_HINTS[_theme_for(item, quote)])
            _check_grounded_terms(text, title, summary, quote["ja"])
            mtg._verify_with_ollama(host, model, text, title, summary)
            me.deep_check(text, item, quote, "ベーコン")
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
                   "content": _analysis_prompt(item, quote)}],
    )
    text = _validate_analysis("".join(b.text for b in msg.content if b.type == "text"))
    mtg._check_not_restating(text, quote["ja"])
    mtg._check_not_restating(text, THEME_HINTS[_theme_for(item, quote)])
    _check_grounded_terms(text, title, summary, quote["ja"])
    me.deep_check(text, item, quote, "ベーコン")
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
    # 以前はここでテンプレートに代えて掲載していたが、見出しの切れ端を型にはめるため
    # 文として崩れた(実例 2026-11-04: 「…どう守るか？、東大など…の広がり方には」)。
    # 検査を通る分析文が得られなければ、この記事は見送る。
    LAST_ANALYSIS_SOURCE = None
    raise RuntimeError("検査を通る分析文が得られなかった")


def llm_bot():
    """quote_commentary(共用の論評の組み立て)に渡す、ベーコンボットの設定。"""
    import quote_commentary as qc
    return qc.Bot(
        author="ベーコン",
        focus="人々や組織が、情報・言葉・評判・予測・技術をどう扱い、どう受け止めているか",
        rank=rank_quote_candidates,
        # 手本: 架空の見出しと実際の引用。導入の一文は事実の言い直しだけで、心の動きの推測は書かない
        examples=[
            {"title": "人気インフルエンサー「この健康法で病気が治った」と投稿 専門家は根拠を否定",
             "key_phrase": "「この健康法で病気が治った」と投稿", "actor": "人気インフルエンサー",
             "quote": QUOTES_BY_ID["NO1.46b"],
             "sentence": "人気インフルエンサーが『この健康法で病気が治った』と投稿し、専門家はその根拠を否定しているという。"},
            {"title": "「AIで仕事の8割が消える」 民間予測が話題、試算の前提には疑問も", "key_phrase": "民間予測が話題",
             "actor": "民間予測", "quote": QUOTES_BY_ID["E35b"],
             "sentence": "『AIで仕事の8割が消える』という民間の予測が話題になっているが、試算の前提には疑問も出ているという。"},
            {"title": "新薬の効果、発表を撤回 研究チームがデータの誤りを認める", "key_phrase": "データの誤りを認める",
             "actor": "研究チーム", "quote": QUOTES_BY_ID["NO1.84b"],
             "sentence": "研究チームは、データに誤りがあったことを認め、新薬の効果についての発表を撤回したという。"},
        ],
        meta_words=("ベーコン", "イドラ", "ノヴム", "オルガヌム", "知性が", "心の動き"),
        generic_terms=set(_GENERIC_TERMS),
    )


def generate_commentary(item: NewsItem, prefer_llm: bool = True, max_chars: int = BODY_MAX_CHARS) -> str:
    """
    メインエントリポイント。論評を組み立て、採用した引用の使用履歴を記録する。
    実際に掲載する1件に対してのみ呼ぶこと。
    検査を通る分析文が得られなければ None を返す(呼び出し側は次の記事に進む)。
    """
    global LAST_QUOTE_ID, LAST_QUOTE_CHOICE, LAST_ANALYSIS_SOURCE
    LAST_QUOTE_ID = None
    if not prefer_llm:
        print("[見送り] LLMを使わない設定")
        return None
    import quote_commentary as qc
    got = qc.run(llm_bot(), item)
    if got is None:
        LAST_ANALYSIS_SOURCE = None
        return None
    analysis, quote = got
    LAST_QUOTE_CHOICE = "llm"
    LAST_ANALYSIS_SOURCE = "ollama:" + mtg._ollama_env()[1]
    body = _assemble_body(analysis, quote, max_chars)
    result = me._prepend_source_link(body, item)

    LAST_QUOTE_ID = quote["id"]
    record_quote_usage(LAST_QUOTE_ID)
    return result
