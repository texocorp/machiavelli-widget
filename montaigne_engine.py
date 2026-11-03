# -*- coding: utf-8 -*-
"""
montaigne_engine.py
--------------------
選別された社会面・科学医療のニュースと、『エセー』の箴言から、
「モンテーニュ人格」による論評を生成する。

【マキャベリボットから受け継いだ設計】
処理の役割分担は machiavelli_engine.py と同じで、実績のある部品はそのまま使う。

  1. 箴言を選ぶ            … select_quote()    Pythonが候補を絞り、LLMが1件を選ぶ
  2. 分析文を1文だけ得る    … _get_analysis()   LLM(失敗時はテンプレート)
  3. 分析文+引用+出典を結合 … _assemble_body()  常にPythonが機械的に結合
  4. 先頭にURLを付加        … machiavelli_engine._prepend_source_link()

引用文・出典・URLにLLMは一切関与しない。LLMの出力は分析文1文だけで、
それも形式検査・語句照合(作話検出)・事実照合の3段階を通す。
Ollama 呼び出し、思考ブロック除去、「動詞+だ」の修正、語句照合の仕組みは
machiavelli_engine.py の関数を import して使う。

【モンテーニュの視座(persona)】
- 人間観察に徹する。善悪を裁かず、断罪も称賛も説教も政策提言もしない。
- ニュースに現れた人間の性(恐れ・習慣・思い込み・虚栄・残酷さ・移ろいやすさ)を
  「人は」「我々は」という人間一般の相で言い当てる。
- 制度・技術・改革で人間が良くなるという進歩の建前を前提にしない。
  同時に、特定の政治的立場から論じることもしない。
"""

import json
import os
import random
import re

from geopolitical_scorer import NewsItem, clean_news_text, facts_for_prompt, is_japanese, _MEDIA_SUFFIX
import machiavelli_engine as me  # 実績のある共通部品(Ollama呼び出し・検査・整形)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUOTES_PATH = os.path.join(BASE_DIR, "data", "montaigne_quotes.json")

with open(QUOTES_PATH, "r", encoding="utf-8") as f:
    QUOTES = json.load(f)["quotes"]
QUOTES_BY_ID = {q["id"]: q for q in QUOTES}

# 出典表記に添える章題(本ボットによる訳。原題は quotes.json の chapter_title)
CHAPTER_TITLES_JA = {
    "I.3": "我々の情念は我々の先へ運ばれる",
    "I.8": "無為について",
    "I.9": "嘘つきについて",
    "I.14": "善悪の味わいは我々の考え方による",
    "I.18": "恐怖について",
    "I.20": "哲学するとは死ぬことを学ぶこと",
    "I.21": "想像の力について",
    "I.22": "一方の得は他方の損",
    "I.23": "慣習について",
    "I.25": "衒学について",
    "I.26": "子供の教育について",
    "I.27": "真偽を己の力量で測る愚かさ",
    "I.28": "友情について",
    "I.30": "節度について",
    "I.31": "人食い人種について",
    "I.39": "孤独について",
    "I.42": "我々の間の不平等について",
    "I.49": "古い慣習について",
    "I.50": "デモクリトスとヘラクレイトスについて",
    "I.54": "むなしい精緻さについて",
    "II.1": "我々の行為の一貫しなさについて",
    "II.5": "良心について",
    "II.6": "実地の訓練について",
    "II.11": "残酷さについて",
    "II.12": "レーモン・スボンの弁護",
    "II.15": "我々の欲望は困難によって募る",
    "II.16": "栄光について",
    "II.17": "うぬぼれについて",
    "II.18": "嘘をつくことについて",
    "II.27": "臆病は残酷の母",
    "II.37": "子が父に似ることについて",
    "III.1": "有益と誠実について",
    "III.2": "後悔について",
    "III.6": "馬車について",
    "III.8": "談論の術について",
    "III.9": "むなしさについて",
    "III.10": "自分の意志を節約することについて",
    "III.11": "足の不自由な人々について",
    "III.12": "人相について",
    "III.13": "経験について",
}


def source_label(quote: dict) -> str:
    """『エセー I.31「人食い人種について」』の形の出典表記を作る。"""
    src = quote["source"]
    title = CHAPTER_TITLES_JA.get(src)
    return f"『エセー {src}「{title}」』" if title else f"『エセー {src}』"


# ---------------------------------------------------------------
# 箴言の使用履歴(マキャベリ側とは別ファイルに永続化する)
# ---------------------------------------------------------------
RECENT_QUOTES_PATH = os.path.join(BASE_DIR, "logs", "montaigne_recent_quotes.json")
QUOTE_USAGE_PATH = os.path.join(BASE_DIR, "logs", "montaigne_quote_usage.json")
RECENT_QUOTES_WINDOW = 40  # 箴言117件に対し、直近40回分(1日8回で5日分)は候補から外す


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
# 箴言の選び方(マキャベリ側と同じ手順)
#   1. 直近に使った箴言を外す
#   2. 記事のテーマ・適用場面の語との一致で関連度を付ける
#   3. 上位8件を LLM に見せ、最もよく当てはまる1件を番号で選ばせる
# ---------------------------------------------------------------
CANDIDATE_COUNT = 8
MIN_RELATED = 4

_SCENE_STOPWORDS = {
    "人間", "社会", "議論", "問題", "関係", "状況", "場合", "結果", "対応", "人々",
    "出来事", "事件", "変化", "行為", "態度", "意見", "判断", "見方", "一般",
}
_SCENE_TERM = re.compile(r"[一-龥々ァ-ヴー]{2,}")


def _scene_words(quote: dict) -> list:
    return [w for w in dict.fromkeys(_SCENE_TERM.findall(quote.get("scene", "")))
            if w not in _SCENE_STOPWORDS]


def _quote_relevance(quote: dict, themes: list, news_text: str) -> int:
    """テーマ一致(主テーマ3点・2番目2点・以降1点)+適用場面の語の一致(1語2点、最大6点)。"""
    score = 0
    for idx, theme in enumerate(themes):
        if theme in quote["tags"]:
            score += max(3 - idx, 1)
    score += 2 * min(sum(1 for w in _scene_words(quote) if w in news_text), 3)
    return score


def rank_quote_candidates(item: NewsItem, count: int = CANDIDATE_COUNT) -> list:
    themes = getattr(item, "themes", None) or [item.theme or "inconstance"]
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


QUOTE_CHOICE_PROMPT = """次のニュースに、モンテーニュ『エセー』の一節を一つ添えて論評する。
候補の中から、このニュースに現れた人間の振る舞いや心の動きに最もよく当てはまる一節を一つ選べ。

ニュース見出し: {title}
概要: {summary}

候補:
{candidates}

選ぶ基準:
- ニュースに登場する人々(当事者・周囲・世間)の振る舞いや反応に、一節の述べる人間の性が直接当てはまること
- 言葉が似ているだけのものではなく、人間の性の構図が一致するものを選ぶこと
- 亡くなった人や被害に遭った人を軽んじる響きになるものは選ばないこと

答えは候補の番号(半角数字)だけを書け。
"""

LAST_QUOTE_ID = None
LAST_QUOTE_CHOICE = None
LAST_ANALYSIS_SOURCE = None


def _ollama_env() -> tuple:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", me.DEFAULT_OLLAMA_MODEL)
    return host, model


def _choose_quote_with_ollama(item: NewsItem, candidates: list) -> dict:
    host, model = _ollama_env()
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
        raise ValueError(f"箴言の選択結果を読み取れない: {answer!r}")
    return candidates[int(m.group()) - 1]


def select_quote(item: NewsItem, prefer_llm: bool = True) -> dict:
    global LAST_QUOTE_CHOICE
    candidates = rank_quote_candidates(item)
    if prefer_llm and len(candidates) > 1:
        try:
            quote = _choose_quote_with_ollama(item, candidates)
            LAST_QUOTE_CHOICE = "llm"
            print(f"[箴言] 候補{len(candidates)}件からLLMが選択: {quote['id']}")
            return quote
        except Exception as e:
            print(f"[箴言] LLMによる選択ができず、関連度1位を採用します: {e}")
    LAST_QUOTE_CHOICE = "rule"
    print(f"[箴言] 関連度1位を採用: {candidates[0]['id']}")
    return candidates[0]


# ---------------------------------------------------------------
# テンプレート(LLMが使えないときの最終フォールバック)
# ---------------------------------------------------------------
THEME_ANALYSIS_TEMPLATES = {
    "cruaute": [
        "{frag}は、人が同類に向ける残酷さが、時代ごとに衣を替えてなお現れることを示している。",
        "{frag}に見えるのは、弱い者に向かうときほど人がたやすく残酷になるという、古くからの性である。",
    ],
    "lois": [
        "{frag}は、裁きもまた人の手によるものであり、人の誤りを免れないことを思い起こさせる。",
        "{frag}をめぐる成り行きは、規則がその正しさよりも、規則であることによって人を従わせている様を映している。",
    ],
    "mort": [
        "{frag}は、死が予告もなく日常のただ中へ入り込んでくることを、改めて我々に突きつける。",
        "{frag}に接して人が覚える動揺は、死を遠いものと思い込んで暮らす我々の習いの裏返しである。",
    ],
    "medecine": [
        "{frag}には、健康を願うあまり、人が医術とその権威に身を委ねてゆく姿が見える。",
        "{frag}は、身体について我々が知っていると思うことが、なお実例と経験の途上にあることを示している。",
    ],
    "opinion": [
        "{frag}は、人が真偽よりも、信じたいものを信じて言い伝えていく性を映している。",
        "{frag}に見えるのは、一人の思い込みが人から人へ渡るうちに、確かな事実の顔つきを帯びてゆく過程である。",
    ],
    "savoir": [
        "{frag}は、知識を蓄えることと、よく判断することとが別のことであると思い出させる。",
        "{frag}をめぐる議論には、知っていることの量を知恵の深さと取り違える、我々の癖が表れている。",
    ],
    "presomption": [
        "{frag}には、自らの作り出したものを過信する、人間の生まれつきの思い上がりが透けて見える。",
        "{frag}は、人が自然と自分の力の限りを、いつも少しばかり見誤ることを示している。",
    ],
    "autrui": [
        "{frag}は、人が自分の習いにないものを、まず異様なものとして眺める性を映している。",
        "{frag}に見える戸惑いは、他者を測る物差しが、結局は自分の慣れ親しんだ流儀でしかないことの表れである。",
    ],
    "profit": [
        "{frag}は、ある者の得が別の者の損の上に成り立つという、商いの古い理を映している。",
        "{frag}には、利を求める人の営みが、知らず知らず他人の負担を生む構図が見える。",
    ],
    "vanite": [
        "{frag}は、地位や肩書という借り物の衣装と、その下にいる生身の人間との隔たりを露わにする。",
        "{frag}に見えるのは、人が名を実と取り違え、外見のために中身を差し出してしまう性である。",
    ],
    "coutume": [
        "{frag}は、長く続いた習いが、いつしか自然の掟のような顔をして人を縛ることを示している。",
        "{frag}をめぐる反応には、慣れ親しんだものを当然とみなす、慣習の静かな力が表れている。",
    ],
    "nouveaute": [
        "{frag}は、新しい仕組みが古い弊を除くと同時に、思いがけぬ混乱をも呼び込みうることを思い起こさせる。",
        "{frag}には、変えることそのものに期待をかける、人の気の移ろいが見える。",
    ],
    "soi": [
        "{frag}は、人が外のことに追われるうちに、自分自身のための場所を失ってゆく姿を映している。",
        "{frag}に見えるのは、人とつながりたいと願いながら、人と交わることに疲れもする我々の矛盾である。",
    ],
    "peur": [
        "{frag}は、出来事そのものよりも、出来事について抱く思いのほうが人を苦しめることを示している。",
        "{frag}に広がる不安は、まだ来ぬものに心を奪われ、今あるものを見失う人間の性の表れである。",
    ],
    "inconstance": [
        "{frag}は、人の振る舞いがいかに一貫せず、時と場合によって別人のように変わるかを映している。",
        "{frag}に見えるのは、昨日の判断を今日には翻す、我々の移ろいやすさである。",
    ],
}


def _build_analysis(item: NewsItem, quote: dict = None) -> str:
    """
    テンプレートから分析文を作る。箴言が決まっていれば、その箴言のタグのうち
    記事のテーマとも一致するものを優先して型を選ぶ(引用と分析文の食い違いを避ける)。
    """
    themes = getattr(item, "themes", None) or [item.theme or "inconstance"]
    theme = themes[0]
    if quote:
        shared = [t for t in themes if t in quote["tags"]]
        theme = shared[0] if shared else quote["tags"][0]
    templates = THEME_ANALYSIS_TEMPLATES.get(theme) or THEME_ANALYSIS_TEMPLATES["inconstance"]
    # 見出し末尾の媒体名(「 - 日本経済新聞」)を除いてから断片を取る
    # (除かないと「…懸念の声、-、日…」のように媒体名の切れ端が文に混じる)
    title = _MEDIA_SUFFIX.sub("", facts_for_prompt(item)[0]).strip()
    frag = me._title_fragment(title) if is_japanese(title) else "この報道"
    # 見出しの語句の区切りの空白(「再審で無罪判決 逮捕から40年」)は、
    # 文に差し込むと読みにくいので読点に置き換える
    frag = re.sub(r"[ \u3000]+", "、", frag.strip())
    return random.choice(templates).format(frag=frag)


# ---------------------------------------------------------------
# 本文の組み立て
# ---------------------------------------------------------------
BODY_MAX_CHARS = 260  # 箴言が長めで章題も付くため、マキャベリ側(250)より少し長く取る


def _assemble_body(analysis: str, quote: dict, max_chars: int = BODY_MAX_CHARS) -> str:
    """分析文・箴言・出典を結合する。上限を超えたら削るのは分析文だけ。"""
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
# 以前は箴言の訳文をそのまま LLM に見せて「この言葉への導入を書け」と求めていたが、
# 小型モデルは箴言の言い回しを分析文に持ち込み(丸写しを禁じても言い換えて繰り返す)、
# 足りない筋を見出しに無い事情で埋めた。
# 実例(2026-11-03): 地震の死者数の記事に「人々は慣れ親しんだ日常の崩壊を恐れて避難所へと
# 集まり、死の待ち受ける場所を選ばずいたる所でその影を受け入れる性質を見せる」。
# 避難所も恐れも見出しに無く、後半は箴言(I.20)の言い換えで、文意も通っていない。
# そこでベーコンボットと同じく、箴言そのものは見せず、箴言のテーマに当たる人の振る舞いを
# 平易な言葉で渡し、「見出しの出来事 → そこに見える振る舞い」の型で書かせる。
THEME_HINTS = {
    "coutume": "長く続いた慣わしや前例が、理由を問われないまま当たり前として人を動かしていること",
    "nouveaute": "新しい仕組みや変更が、期待とは別の戸惑いや混乱を呼んでいること",
    "lois": "決まりや手続き、裁きが、それ自体の正しさとは別の理由で通用し、あるいは人を縛っていること",
    "savoir": "知識や肩書・試験の結果が、判断の確かさとは別に重んじられていること",
    "presomption": "人が、自分たちの技術や見通しを、確かめた以上に当てにしていること",
    "opinion": "確かめられていない話や印象が、人から人へ渡るうちに事実のように扱われていること",
    "mort": "死や老いが身近に迫るとき、人がそれをどう語り、どう備え、あるいはどう避けているか",
    "peur": "出来事そのものより、それについての不安や思いが人の振る舞いを動かしていること",
    "medecine": "健康や治療をめぐって、人が医術や専門家の判断にどこまで身を委ねているか",
    "cruaute": "力の弱い相手に向けて、人がたやすく残酷になっていること",
    "autrui": "人が、自分の慣れた流儀を物差しにして、異なるものを奇妙だと見なしていること",
    "inconstance": "同じ人や組織の言うことやすることが、時と場合によって食い違っていること",
    "vanite": "地位や肩書、名声という外側が、その人の中身と取り違えられていること",
    "profit": "ある人の得が、別の人の損や負担の上に成り立っていること",
    "soi": "人が、外のことや他人の期待に追われて、自分の暮らしや時間を手放していること",
}


def _theme_for(item: NewsItem, quote: dict) -> str:
    """記事のテーマと箴言のタグが重なるものを優先する(テンプレートと同じ選び方)。"""
    themes = getattr(item, "themes", None) or [item.theme or "inconstance"]
    shared = [t for t in themes if t in quote["tags"]]
    return shared[0] if shared else quote["tags"][0]


def _analysis_prompt(item: NewsItem, quote: dict) -> str:
    title, summary = facts_for_prompt(item)
    return ANALYSIS_PROMPT.format(title=title, summary=summary,
                                  hint=THEME_HINTS[_theme_for(item, quote)])


ANALYSIS_PROMPT = """次のニュースについて、モンテーニュのように落ち着いた人間観察の目で、平易な言葉で一文を書け。

ニュース見出し: {title}
概要: {summary}

観察の手がかり(このニュースのどこにこれが見えるかを書く):
{hint}

書き方:
- 文の前半で、見出しに書かれた具体的な出来事(誰が何をしたか、何が起きたか)を短く押さえる
- 文の後半で、その出来事のどこに上の手がかりの振る舞いが見えるのかを、ふつうの言葉で言い当てる
- 型の目安:「(見出しの出来事)には、(誰が)(何を)(どう扱っているか)が表れている。」
  ただし言い回しはこの型どおりでなくてよい
- 手がかりの文をそのまま書き写さないこと。「人間の性」「観察」「手がかり」という語そのものは書かず、
  その中身(誰が、何を、どう受け止め、どう扱っているか)を書くこと
- 読み返して、一文として意味がまっすぐ通ることを確かめること。比喩を重ねたり、
  主語と述語が噛み合わない文にしたりしない

視座(厳守):
- 人間観察に徹する。善悪を裁かない。誰かを断罪することも称賛することもしない
- 説教、教訓、政策提言は書かない。「〜すべきだ」「〜が求められる」「〜が必要だ」の類は禁止
- 制度や技術や改革によって人間が良くなるという前提に立たない。かといって、
  特定の政治的立場から論じることもしない
- 亡くなった人、被害に遭った人、被災した人、その家族の性格や心の在り方・受け止め方を論じてはならない
  (例: 詐欺の被害者を「欲深い」と評する、被災者が「死を受け入れている」と評する)。
  人の振る舞いを論じるなら、加害した側、組織や制度の扱い方、出来事を取り巻く世間の振る舞いに目を向けること

最優先の条件(事実の扱い):
- 根拠にしてよい事実は、上の見出しと概要に書かれていることだけである。
  書かれていない出来事・行為・場所・数字・感情・動機・因果関係・世間の反応を補ってはならない
  (例: 見出しに無いのに「避難所に集まった」「不安に駆られた」と書くのは誤り)
- 誰が何をしたのか、主語と行為の関係を見出しのとおりに保つこと。主客を入れ替えてはならない
- 見出しが短く情報が乏しい場合は、書かれている範囲だけを控えめに論じ、事情を想像で埋めないこと

その他の条件:
- 出力は1文のみ。40字以上90字以内
- 必ず句点「。」で終わる、文法的に完結した1文にすること。
  文の途中で終わらせたり、「…」「...」で終えたりしてはならない
- 文体は「だ・である調」にすること。ただし「だ」は名詞・形容動詞の
  言い切りにのみ付ける助動詞であり、動詞の終止形(〜る、〜れる、〜られる等)
  にはそもそも付けない。動詞の終止形はそれ自体で言い切りが完成している。
  【正しい例】「人は慣れたものを疑わない。」「前例が判断を先回りしている。」
  【誤った例(絶対にしないこと)】「人は慣れたものを疑わないだ。」「前例が判断を先回りしているだ。」
  【名詞の言い切りの正しい例】「これは習慣の力の表れだ。」「人の性は変わらぬものである。」
- 「」『』などの引用符、URL、見出しラベル、前置きや説明は一切書かない
- 人名・組織名・地名などの固有名詞は、見出しや概要に明記されているものだけを使うこと
- このニュース固有の具体的な内容(登場する人々・場所・出来事)に触れる。
  どの記事にも当てはまる一般論は禁止
- 出力は分析文一文のみ。それ以外は何も書くな
"""

# 事実照合(ベーコンボットも共用する)。
# 以前は「人間の性についての観察・比喩・一般化は問題にしない」と書いていたため、
# 見出しに無い感情や行動(「日常の崩壊を恐れて避難所へと集まり」)まで「観察」として
# 通っていた。見出しに無い人の感情・動機・行動は事実の付け加えとして扱い、
# 意味の通らない文と、被害者を論評する文も落とす。
VERIFY_PROMPT = """あなたは新聞の校閲係である。
次の「分析文」を、「見出し」「概要」と照らし合わせて判定せよ。

見出し: {title}
概要: {summary}
分析文: {analysis}

次のどれか一つにでも当たれば「不適合」:
1. 見出し・概要の事実と矛盾している(主語と行為の取り違え、位置関係や因果の取り違えを含む)
2. 見出し・概要に書かれていない出来事・行為・場所・数字を付け加えている
3. 見出し・概要に書かれていない、特定の人々の感情・動機・行動を、事実のように書いている
   (例: 見出しに無いのに「人々は恐れて避難所へ集まった」と書く)
4. 亡くなった人、被害に遭った人、被災した人、その家族の性格や心の在り方・受け止め方を論評している
5. 主語と述語が噛み合わない、比喩が重なって意味が取れないなど、一文として意味が通らない

出来事に対する評価・解釈を述べているだけで、上のどれにも当たらなければ「適合」。

答えは「適合」か「不適合」の一語だけを書け。
"""

# 説教・提言の言い回し(人間観察に徹する視座に反するので不合格にする)
_SERMON_PATTERN = re.compile(
    r"(べきだ|べきである|べきであろう|べきなのだ|求められる|必要だ|必要である|必要がある|"
    r"ねばならない|ねばならぬ|なければならない|しなければ|しよう。|ましょう)"
)

# 見出しに無くても分析文に出てきてよい一般的なカタカナ語・英字
_GENERIC_TERMS = set(me._GENERIC_TERMS) | {
    "モンテーニュ", "エセー", "モラル", "エゴ", "ジレンマ", "ドラマ", "ヒューマン",
    "コミュニティ", "プライド", "ブーム", "パニック", "トラブル", "ストレス", "イメージ",
}


def _check_grounded_terms(analysis: str, title: str, summary: str, quote_text: str = "") -> None:
    """
    分析文のカタカナ語・英字・数字が見出し・概要(と箴言)に含まれるかを照合する。
    仕組みは machiavelli_engine._check_grounded_terms と同じで、
    許容する一般語だけをモンテーニュ用に広げている。
    """
    source = me._normalize_for_match(f"{title} {summary} {quote_text}")
    norm = me._normalize_for_match(analysis)
    missing = []
    for pattern in (me._KATAKANA_RUN, me._LATIN_RUN, me._DIGIT_RUN):
        for term in pattern.findall(norm):
            term = term.strip("ー")
            if len(term) < 2 and pattern is not me._DIGIT_RUN:
                continue
            if term in _GENERIC_TERMS or term in source:
                continue
            missing.append(term)
    if missing:
        raise ValueError(f"見出し・概要に無い語句を含む(作話の疑い): {missing}")


# プロンプトの指示語をそのまま持ち込んだ、中身のない結び(ベーコンボットでの実例に倣う)
_JARGON_PATTERN = re.compile(r"(人間の性|性質を見せ|性を見せ|観察が見え|手がかり|人間観察)")


def _validate_analysis(text: str) -> str:
    """形式の検査(マキャベリ側と共通)に、説教口調と決まり文句の検査を加える。"""
    text = me._validate_analysis(text)
    if _SERMON_PATTERN.search(text):
        raise ValueError(f"説教・提言の言い回しを含む(人間観察の視座に反する): {text!r}")
    if _JARGON_PATTERN.search(text):
        raise ValueError(f"指示の言葉を写しただけの決まり文句に頼っている: {text!r}")
    return text


def _verify_with_ollama(host: str, model: str, analysis: str, title: str, summary: str) -> None:
    verdict = me._ollama_generate(
        host, model,
        VERIFY_PROMPT.format(title=title, summary=summary, analysis=analysis),
        {"temperature": 0.0, "top_k": 1, "num_predict": 16},
    )
    if "不適合" in verdict:
        raise ValueError(f"事実照合で不適合と判定された: {analysis!r}")
    if "適合" not in verdict:
        print(f"[分析文] 事実照合の判定を読み取れず、通過させました: {verdict!r}")


def _check_not_restating(analysis: str, quote_text: str, run: int = 10) -> None:
    """
    分析文が、添える箴言の文言を丸写ししていないかを調べる。
    箴言の中の連続する run 字(句読点を除く)が分析文にそのまま現れたら不合格にする。
    (実例: 分析文の後半が「財の貧しさは癒やしやすいが、魂の貧しさは癒やしようがない」と
    箴言をそのまま繰り返し、直後の引用と同じ文が二度並んだ)
    """
    strip = lambda t: re.sub(r"[、。「」『』・,. ]", "", t)
    a, q = strip(analysis), strip(quote_text)
    for i in range(0, max(len(q) - run + 1, 0)):
        if q[i:i + run] in a:
            raise ValueError(f"箴言の文言を繰り返している: {q[i:i + run]!r}")


def _analysis_via_ollama(item: NewsItem, quote: dict, attempts: int = 3) -> str:
    """設定・検査の段取りは machiavelli_engine._analysis_via_ollama と同じ。"""
    host, model = _ollama_env()
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
            _check_not_restating(text, quote["ja"])
            _check_not_restating(text, THEME_HINTS[_theme_for(item, quote)])
            _check_grounded_terms(text, title, summary, quote["ja"])
            _verify_with_ollama(host, model, text, title, summary)
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
    _check_not_restating(text, quote["ja"])
    _check_not_restating(text, THEME_HINTS[_theme_for(item, quote)])
    _check_grounded_terms(text, title, summary, quote["ja"])
    return text


def _get_analysis(item: NewsItem, quote: dict, prefer_llm: bool = True) -> str:
    """Ollama → Anthropic API → テンプレート の順に試す。"""
    global LAST_ANALYSIS_SOURCE
    if prefer_llm:
        _, model = _ollama_env()
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
    メインエントリポイント。論評を組み立て、採用した箴言の使用履歴を記録する。
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
