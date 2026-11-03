# -*- coding: utf-8 -*-
"""
quote_commentary.py
--------------------
マキャベリ・ベーコンのボットが共用する、論評の組み立て(2026-11-04 改訂)。
モンテーニュボット(montaigne_engine.py)で効果を確かめた方式を、引用の著者を問わず使える形にしたもの。

【方式】論評は「導入の一文」+「原典の引用」。洞察は原典の言葉に任せ、LLM には書かせない。
  1. 読む   見出しの出来事を言い直させ、中心の語句を見出しから一字一句抜き出させる(Pythonで実在を照合)
  2. 選ぶ   引用の候補(各ボットの rank_quote_candidates が出す数件)を1件ずつ別の呼び出しで採点させる。
            引用の構図が当てはまる「主体」を見出しから抜き出させ、見出しに実在しなければ0点。
            2点以上が無ければ、この記事は見送る
  3. 書く   見出しの出来事を、その主体に光が当たるように言い直した導入の一文を、3通り書かせる
  4. 確かめる 機械の検査(見出しに無い漢語・カタカナ語・数字、説教口調、指示の言葉、引用や手本の丸写し)、
            見出しへの忠実さの順に、事実の主張の照合(Chain-of-Verification)と校閲。最初に通ったものを採る

【以前の方式で起きたこと】分析文に「X は、敵が決戦を挑むとき避けられぬというマキャベリの理だ」のように
引用の理屈を当てはめて言い切らせていた。9Bのモデルはその当てはめを誤り(脅している側を「挑まれた側」とした)、
事実も足した(「米仲介を避ける姿勢」)。導入を事実に限ると、当てはめの誤りは文に出ず、
引用が合うかどうかは「選ぶ」の採点で別に確かめられる。

使い方: 各ボットの generate_commentary から run(bot, item) を呼ぶ。bot は Bot の値。
"""

import re
from dataclasses import dataclass, field

from geopolitical_scorer import NewsItem
import machiavelli_engine as me
import montaigne_engine as mtg

LAST_TRACE = {}   # 直近の run() の途中経過(試験環境 tools/sibling_lab.py が読む)


@dataclass
class Bot:
    author: str                   # 「マキャベリ」「ベーコン」
    focus: str                    # 読む工程で目を向けるもの
    rank: object                  # rank(item, count) -> 引用の候補の一覧
    examples: list                # 手本: {"title", "key_phrase", "actor", "quote", "sentence"}
    meta_words: tuple = ()        # 本文に混ざってはならない指示の言葉(著者名・書名など)
    generic_terms: set = field(default_factory=set)  # 見出しに無くてもよいカタカナ語
    neutral_kanji: str = ""       # 見出しに無くてもよい漢字(例: 「米」を「米国」と書く「国」)


JUDGE = mtg.JUDGE_OPTIONS
WRITE = mtg.WRITE_OPTIONS
CANDIDATES_TO_SCORE = 6
MIN_FIT = 2
WRITE_SAMPLES = 3
MIN_CHARS, MAX_CHARS = 30, 90


# ---------------------------------------------------------------
# 1. 読む
# ---------------------------------------------------------------
READ_SYSTEM = """あなたは新聞の論説委員である。ニュースの見出しと概要を読み、次の2つを JSON で答える。

facts: 見出しに書かれた出来事を、誰が・何を・どうしたかの一文で言い直す。見出しに無いことは足さない。
  見出しの「〜か」「〜へ」「〜も」などの切り詰めた言い方は、意味を変えずにふつうの文に直す
  (「〜か」は推測・疑い、「〜へ」は予定・方針であって、起きたことではない)
key_phrase: 見出しの中で、{focus}がいちばんよく表れている語句を、見出しから一字一句そのまま抜き出す。"""

READ_EXAMPLES = [
    (mtg._news_prompt("隣国、国境付近に部隊増派か 政府は「注視」", "(見出し以外の情報なし)"),
     {"facts": "隣国が国境付近に部隊を増やした可能性があり、政府は注視しているとした",
      "key_phrase": "国境付近に部隊増派か"}),
    (mtg._news_prompt("新型の検索AI、誤情報を断定口調で回答 開発元は改善へ", "(見出し以外の情報なし)"),
     {"facts": "新型の検索AIが誤った情報を断定する口調で答え、開発元は改善する方針を示した",
      "key_phrase": "誤情報を断定口調で回答"}),
]

READ_SCHEMA = {"type": "object",
               "properties": {"facts": {"type": "string"}, "key_phrase": {"type": "string"}},
               "required": ["facts", "key_phrase"]}


def read_article(bot: Bot, item: NewsItem) -> dict:
    """読み違いは Python で止める: 語句が見出しに無い、言い直しに見出しに無いカタカナ語がある → None。"""
    title, summary = mtg._facts(item)
    data = mtg._ollama_chat_json(READ_SYSTEM.format(focus=bot.focus), READ_EXAMPLES,
                                 mtg._news_prompt(title, summary), READ_SCHEMA, JUDGE, "read")
    data = {k: (data.get(k) or "").strip() for k in ("facts", "key_phrase")}
    key = mtg._compact(data["key_phrase"])
    if len(key) < 2 or key not in mtg._compact(f"{title}{summary}"):
        data["problem"] = "抜き出した語句が見出しに無い"
    elif mtg._ungrounded_kana(data["facts"], f"{title} {summary}"):
        data["problem"] = f"言い直しに見出しに無い語がある: {mtg._ungrounded_kana(data['facts'], f'{title} {summary}')}"
    return data


# ---------------------------------------------------------------
# 2. 選ぶ
# ---------------------------------------------------------------
FIT_PROMPT = """新聞のコラムで、ニュースの後に{author}の一節を引く。

見出し: {title}
出来事: {facts}

一節: {quote}
(この一節が当てはまる場面の目安: {scene})

次の順に答えよ。
actor: 一節の言う構図が当てはまる、見出しの中の主体(国・組織・人)。見出しの表記のまま書く。当てはまる主体が無ければ空
common: その主体が見出しの中でしたこと・置かれた立場と、一節の言う構図との共通点を、20〜40字で書く(無ければ「無し」)
fit: 次の基準で点数を付ける
  3: 一節の言う構図(誰が、誰に対して、何をすると、どうなるか)が、その主体の行動や立場にぴったり当てはまる
  2: はっきり当てはまる
  1: 話題や言葉が重なるだけで、構図は違う。または一節の役回り(攻める側・守る側、欺く側・欺かれる側など)が逆になる
  0: 当てはまらない。または出来事の後に続けると、亡くなった人・被害に遭った人・その家族を責めたり嘲ったりする響きになる"""

FIT_SCHEMA = {"type": "object",
              "properties": {"actor": {"type": "string"}, "common": {"type": "string"},
                             "fit": {"type": "integer", "minimum": 0, "maximum": 3}},
              "required": ["actor", "common", "fit"]}


def choose_quote(bot: Bot, item: NewsItem, reading: dict):
    """候補を1件ずつ採点し、最高点(MIN_FIT 以上)の (引用, 主体) を返す。無ければ (None, None)。"""
    title, summary = mtg._facts(item)
    src = mtg._compact(f"{title}{summary}")
    scored = []
    for q in bot.rank(item, CANDIDATES_TO_SCORE):
        data = mtg._ollama_json(FIT_PROMPT.format(author=bot.author, title=title, facts=reading["facts"],
                                                  quote=q["ja"], scene=q.get("scene", "")),
                                FIT_SCHEMA, JUDGE, "fit")
        actor = (data.get("actor") or "").strip()
        fit = data.get("fit") if isinstance(data.get("fit"), int) else 0
        if len(mtg._compact(actor)) < 2 or mtg._compact(actor) not in src:
            fit = 0  # 当てはまる主体を見出しの中に示せない(見出しに無い主体を想定した)
        scored.append((q, fit, actor, data.get("common", "")))
    LAST_TRACE["quote_candidates"] = [(q["id"], fit, actor, common) for q, fit, actor, common in scored]
    best = max((s[1] for s in scored), default=0)
    if best < MIN_FIT:
        return None, None
    q, _, actor, _ = next(s for s in scored if s[1] == best)
    return q, actor


# ---------------------------------------------------------------
# 3. 書く
# ---------------------------------------------------------------
WRITE_SYSTEM = """新聞の小さなコラムで、ニュースの後に{author}の一節を引く。
その一節の前に置く、導入の一文を JSON で答える。

- 見出しの出来事を、見出しの言葉を生かして一文で言い直す。渡された「語句」は必ず使う
- 渡された「主体」を主語にして、その主体のしたことに光が当たるように、語順と言葉の選び方を工夫する
- 見出しに特有の切り詰めた言い方は、意味を変えずにふつうの文章の言い方に直す。
  「〜か」は疑い・推測、「〜へ」は予定・方針として書き、起きたこととして書かない
- 見出しに無い事情・動機・感情・行動・場所・数字は書かない
- 自分の評価・解釈・教訓や、一節の理屈の当てはめは書かない。それは一節に任せる
- 一節の言葉を言い換えて繰り返さない
- だ・である調か「〜という。」で結ぶ、40〜80字の一文"""

WRITE_SCHEMA = mtg.WRITE_SCHEMA


def _write_prompt(title: str, key_phrase: str, actor: str, quote_ja: str) -> str:
    return f"見出し: {title}\n語句: {key_phrase}\n主体: {actor}\n一節: {quote_ja}"


def write_candidates(bot: Bot, item: NewsItem, reading: dict, quote: dict, actor: str) -> list:
    title, _ = mtg._facts(item)
    examples = [(_write_prompt(e["title"], e["key_phrase"], e["actor"], e["quote"]["ja"]),
                 {"sentence": e["sentence"]}) for e in bot.examples]
    user = _write_prompt(title, reading["key_phrase"], actor, quote["ja"])
    out = []
    for _ in range(WRITE_SAMPLES):
        data = mtg._ollama_chat_json(WRITE_SYSTEM.format(author=bot.author), examples, user,
                                     WRITE_SCHEMA, WRITE, "write")
        text = (data.get("sentence") or "").strip()
        if text and text not in out:
            out.append(text)
    return out


# ---------------------------------------------------------------
# 4. 確かめる
# ---------------------------------------------------------------
_META = r"見出し|語句|一節|主体|材料|導入"


def mechanical_check(bot: Bot, text: str, item: NewsItem, quote: dict, reading: dict) -> str:
    """LLM を使わない検査。合格なら整えた文を返し、不合格なら ValueError(montaigne_engine と同じ基準)。"""
    text = mtg._SPACE_AROUND_ASCII.sub("", text.strip())
    if re.fullmatch(r"[「『][^「『」』]*[」』]", text):
        text = text[1:-1]
    text = text.replace("「", "『").replace("」", "』")
    title, summary = mtg._facts(item)
    source = f"{title} {summary}"
    text = mtg._arabic_numbers(text, source)
    text = mtg._validate_analysis(text)          # 完結した一文か・説教口調・決まり文句
    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        raise ValueError(f"字数が範囲外({len(text)}字)")
    if text.count("。") > 1:
        raise ValueError("一文になっていない")
    m = re.search("|".join([_META] + [re.escape(w) for w in bot.meta_words]), text)
    if m:
        raise ValueError(f"指示の言葉が混ざっている: {m.group()!r}")
    m = mtg._GENERAL_WORDS.search(text)
    if m:
        raise ValueError(f"導入に評価・一般論を書いている: {m.group()!r}")
    words = [w for w in mtg._CONTENT_WORD.findall(reading["key_phrase"]) if w not in {"する", "した"}]
    if words and not any(w in text for w in words):
        raise ValueError(f"見出しの語句({reading['key_phrase']})に触れていない")
    mtg._check_not_restating(text, quote["ja"])
    for e in bot.examples:
        mtg._check_not_restating(text, e["sentence"])
    # 見出しに無いカタカナ語・英字・数字(人名・国名・組織名の作話)
    norm_src = me._normalize_for_match(f"{source} {quote['ja']}")
    allowed = mtg._GENERIC_TERMS | bot.generic_terms
    foreign = [t for t in mtg._ungrounded_kana(text, f"{source} {quote['ja']}") if t not in allowed]
    foreign += [d for d in me._DIGIT_RUN.findall(me._normalize_for_match(text)) if d not in norm_src]
    if foreign:
        raise ValueError(f"見出しに無い語句を含む(作話の疑い): {foreign}")
    foreign = mtg._ungrounded_kanji(text, f"{source} {' '.join(bot.neutral_kanji)}")
    if foreign:
        raise ValueError(f"見出しに無い漢語を使っている: {foreign}")
    return text


# ---------------------------------------------------------------
# 全体
# ---------------------------------------------------------------
WRITE_ROUNDS = 2


def run(bot: Bot, item: NewsItem):
    """(導入の一文, 引用) を返す。掲載できる文が得られなければ None(理由は LAST_TRACE["result"])。"""
    LAST_TRACE.clear()
    mtg.LAST_TRACE.clear()

    def give_up(reason: str):
        LAST_TRACE["result"] = reason
        print(f"[見送り] {reason}")
        return None

    try:
        reading = read_article(bot, item)
    except Exception as e:
        return give_up(f"読む工程で失敗: {e}")
    LAST_TRACE["reading"] = reading
    print(f"[読む] {reading}")
    if reading.get("problem"):
        return give_up(f"読み違いの疑い({reading['problem']})")

    try:
        quote, actor = choose_quote(bot, item, reading)
    except Exception as e:
        return give_up(f"選ぶ工程で失敗: {e}")
    for qid, fit, a, common in LAST_TRACE.get("quote_candidates", []):
        print(f"[採点] {qid} {fit}点 主体={a} … {common}")
    if quote is None:
        return give_up(f"構図の当てはまる引用が候補に無い(すべて{MIN_FIT}点未満)")
    LAST_TRACE["quote"], LAST_TRACE["actor"] = quote["id"], actor
    print(f"[選ぶ] {quote['id']} 主体={actor} {quote['ja'][:40]}")

    LAST_TRACE["candidates"] = []
    for rnd in range(1, WRITE_ROUNDS + 1):
        try:
            drafts = write_candidates(bot, item, reading, quote, actor)
        except Exception as e:
            LAST_TRACE["candidates"].append({"round": rnd, "text": None, "verdict": f"書く工程で失敗: {e}"})
            continue
        records, clean = {}, []
        for draft in drafts:
            record = {"round": rnd, "text": draft}
            LAST_TRACE["candidates"].append(record)
            try:
                text = mechanical_check(bot, draft, item, quote, reading)
            except ValueError as e:
                record["verdict"] = str(e)
                continue
            if text in records:
                record["verdict"] = "重複"
                continue
            record["verdict"] = "機械検査は合格"
            records[text] = record
            clean.append(text)
        try:
            for text in mtg.faithfulness_order(clean, item):
                try:
                    mtg.verify_claims(text, item)
                    mtg.review(text, item, quote, author=bot.author)
                except ValueError as e:
                    records[text]["verdict"] = str(e)
                    continue
                records[text]["verdict"] = "合格"
                LAST_TRACE["result"] = "掲載"
                LAST_TRACE["adopted"] = text
                print(f"[採用] {text}")
                return text, quote
        except Exception as e:
            return give_up(f"確かめる工程で失敗: {e}")
        for c in LAST_TRACE["candidates"]:
            if c.get("round") == rnd:
                print(f"  [不採用] {c.get('text')} … {c.get('verdict')}")
    return give_up("検査を通る導入文が無かった")
