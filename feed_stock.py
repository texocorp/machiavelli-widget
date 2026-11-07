# -*- coding: utf-8 -*-
"""
feed_stock.py
--------------
論評のストックと、表示の時刻の割り当て(2026-11-04 導入)。3つのボットが共用する。

【なぜ必要か】
GitHub の定時実行は、毎時起動を試みても1日に2〜3回しか起動されないことがある
(2026-11-03 17:30〜11-04 09:00 の約16時間で、各ボット16回の試みのうち起動は2回)。
起動のたびに1件ずつ掲載する方式では、起動されない時間がそのまま掲載の空白になる。

【仕組み】
- 起動された回は、時間の許す限り論評を作り、それぞれに「表示してよい時刻」(publish_at)を付けて
  フィードに書き込む。時刻は各ボットの受け持ちの時刻(UTC の時 % 3 == SLOT、毎時17分)を順に割り当てる
- ウィジェット(docs/*/widget.js)は、publish_at を過ぎた論評だけを表示する。表示の時刻は閲覧者の
  ブラウザで判定するので、GitHub が何時間起動しなくても、ストックがある限り時刻どおりに表示が進む
- ストックが TARGET_HOURS 先まであれば、それ以上は作らない(記事の鮮度を保つため)
- ストックが尽きていたら(最後の表示の時刻が過去なら)、最初の1件はすぐに表示する

フィードの項目の timestamp は、表示の時刻(publish_at と同じ)にする。ウィジェットが表示する時刻がこれ。
生成した時刻は generated_at に残す。
"""

import datetime
import hashlib
import json
import os
import re
import unicodedata

UTC = datetime.timezone.utc

# ボット名: (ワークフローのファイル, 受け持ちの時刻 UTCの時 % 3, フィードのファイル)
BOTS = {
    "machiavelli": ("tweet.yml", 0, os.path.join("docs", "feed.json")),
    "montaigne": ("montaigne.yml", 1, os.path.join("docs", "montaigne", "feed.json")),
    "bacon": ("bacon.yml", 2, os.path.join("docs", "bacon", "feed.json")),
}
SLOT_MINUTE = 17
INTERVAL_HOURS = 3
TARGET_HOURS = 24    # ストックをこの時間先まで作る(1日8件)
REFILL_HOURS = 18    # 定時実行では、ストックがこの時間先を下回っていれば作る
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _parse(ts: str):
    try:
        t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def publish_time(entry: dict):
    """項目の表示の時刻。publish_at が無い古い項目は timestamp。"""
    return _parse(entry.get("publish_at") or entry.get("timestamp") or "")


def sort_feed(feed: list) -> list:
    """表示の時刻の新しい順(未来の項目が先頭)。"""
    far_past = datetime.datetime(2000, 1, 1, tzinfo=UTC)
    return sorted(feed, key=lambda e: publish_time(e) or far_past, reverse=True)


def last_publish_time(feed: list):
    times = [t for t in (publish_time(e) for e in feed) if t]
    return max(times) if times else None


def stock_hours(feed: list, now: datetime.datetime) -> float:
    """いまから、最後の表示の時刻までの時間(過去なら0)。"""
    last = last_publish_time(feed)
    return max((last - now).total_seconds() / 3600, 0.0) if last else 0.0


def queued(feed: list, now: datetime.datetime) -> int:
    """まだ表示されていない(表示の時刻が未来の)項目の数。"""
    return sum(1 for e in feed if (publish_time(e) or now) > now)


def next_slot_after(bot: str, t: datetime.datetime) -> datetime.datetime:
    """t より後の、最初の受け持ちの時刻。"""
    slot = BOTS[bot][1]
    c = t.replace(minute=SLOT_MINUTE, second=0, microsecond=0)
    if c <= t:
        c += datetime.timedelta(hours=1)
    while c.hour % INTERVAL_HOURS != slot:
        c += datetime.timedelta(hours=1)
    return c


def assign_publish_time(feed: list, bot: str, now: datetime.datetime) -> datetime.datetime:
    """次に作る論評の表示の時刻。最後の表示の時刻の次の受け持ち。それが過去なら、いま。"""
    last = last_publish_time(feed)
    if last is None:
        return now
    nxt = next_slot_after(bot, last)
    return nxt if nxt > now else now


def needs_more(feed: list, now: datetime.datetime, target_hours: float = TARGET_HOURS) -> bool:
    """もう1件作るべきか。最後の表示の時刻がいまから target_hours 先より手前なら作る。"""
    return stock_hours(feed, now) < target_hours - INTERVAL_HOURS + 0.01


def add_entry(feed: list, entry: dict, bot: str, now: datetime.datetime) -> list:
    """表示の時刻を割り当てて項目を加え、新しい順に並べて返す。"""
    when = assign_publish_time(feed, bot, now)
    entry = dict(entry)
    entry["generated_at"] = now.isoformat()
    entry["publish_at"] = when.isoformat()
    entry["timestamp"] = when.isoformat()
    return sort_feed(feed + [entry])


def trim(feed: list, now: datetime.datetime, keep_published: int) -> list:
    """表示済みの項目は新しい順に keep_published 件まで残す。未来の項目は常に残す。"""
    feed = sort_feed(feed)
    future = [e for e in feed if (publish_time(e) or now) > now]
    past = [e for e in feed if (publish_time(e) or now) <= now]
    return future + past[:keep_published]


def generation_budget_sec(bot: str, setup_and_commit_min: float = 8) -> float:
    """
    この回の生成に使ってよい秒数。ワークフローの update-feed ジョブの timeout-minutes から、
    準備(約2分)と書き込み・余裕を引く。上限を延ばす変更(ワークフローのファイルはユーザーが変える)に
    自動で合わせるため、ファイルから読む。読めなければ 30分の上限を前提にする。
    """
    timeout = 30
    path = os.path.join(BASE_DIR, ".github", "workflows", BOTS[bot][0])
    try:
        text = open(path, encoding="utf-8").read()
        job = text[text.index("update-feed:"):]
        m = re.search(r"timeout-minutes:\s*(\d+)", job)
        if m:
            timeout = int(m.group(1))
    except (OSError, ValueError):
        pass
    return max(timeout - setup_and_commit_min, 10) * 60


def summary(feed: list, now: datetime.datetime) -> str:
    last = last_publish_time(feed)
    last_s = last.astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime("%m/%d %H:%M") if last else "なし"
    return f"未表示のストック{queued(feed, now)}件、最後の表示 {last_s} JST(いまから{stock_hours(feed, now):.1f}時間先)"


# ---------------------------------------------------------------
# 同じ記事の別配信(2026-11-04 導入)
# ---------------------------------------------------------------
# 同じ記事が配信元を変えて何度も届く(「…（ABEMA TIMES） - Yahoo!ニュース」「… 1枚目 - ABEMA TIMES」
# 「…（2026年11月2日掲載） - ライブドアニュース」、「〜」と「～」の違いなど)。見出しの完全一致では見分けられず、
# ベーコンの 2026-11-04 の回では、112分のうち約3割を同じ記事の試し直しに使い、既に載せた記事をもう一度載せた。
# 見出しから媒体名と添え書きを除き、2文字ずつの重なり(Dice係数)で比べる。
# 既存のフィード48件の見出しで測ると、同じ記事どうしは1.0、別の記事どうしは最大0.61だった。
STORY_SIMILARITY = 0.8
_TAIL_MEDIA = re.compile(r"\s+[-|]\s+[^-|]+$")
_TAIL_PAREN = re.compile(r"[(（][^()（）]*[)）]\s*$")
_NOTES = re.compile(r"写真・画像\s*\d+/\d+|\d+枚目|\d{4}年\d+月\d+日掲載")


def story_key(title: str) -> str:
    t = unicodedata.normalize("NFKC", title or "").replace("〜", "~")
    for _ in range(2):
        t = _TAIL_MEDIA.sub("", t).strip()
        t = _NOTES.sub("", t).strip()
        t = _TAIL_PAREN.sub("", t).strip()
    return re.sub(r"[\W_]", "", t)


def story_id(title: str) -> str:
    """既出の一覧(seen)に入れる、記事の鍵。配信元が違っても同じ記事なら同じ値。"""
    return "t:" + hashlib.sha1(story_key(title).encode("utf-8")).hexdigest()[:16]


def _bigrams(s: str) -> set:
    return {s[i:i + 2] for i in range(len(s) - 1)}


def same_story(title: str, titles, threshold: float = STORY_SIMILARITY) -> bool:
    a = _bigrams(story_key(title))
    if not a:
        return False
    for other in titles:
        key_b = story_key(other)
        b = _bigrams(key_b)
        if b and 2 * len(a & b) / (len(a) + len(b)) >= threshold:
            return True
        # 一方の見出しが他方を丸ごと含む(実例: 「ケインズの予言が問うもの - 愛媛新聞」と
        # 「ケインズの予言が問うもの ＢＮＰパリバ証券チーフエコノミスト 河野龍太郎 - 沖縄タイムス社」)
        short, long_ = sorted((story_key(title), key_b), key=len)
        if len(short) >= 10 and short in long_:
            return True
    return False


def published_titles() -> list:
    """3つのボットのフィードにある見出し(他のボットが載せた記事も、同じ記事を二度論評しないために見る)。"""
    out = []
    for _, _, path in BOTS.values():
        try:
            with open(os.path.join(BASE_DIR, path), encoding="utf-8") as f:
                out += [e.get("source_title", "") for e in json.load(f) if e.get("source_title")]
        except (OSError, ValueError):
            pass
    return out


# 素性の疑わしい配信(2026-11-05 導入)
# Google News の検索には、他社の記事を無断で転載・加工したらしい海外のサイトが混ざる。
# 実例: 「デマ拡散の岡本さゆり市議「保身の謝罪」。…Heart (ac40zvlr7H) - Unisba Media」(大学のドメインに置かれた転載)。
# 見出しの末尾の、英数字の乱数のような符号を目印にする。実在の個人を名指す記事が多く、真偽も確かめられないので試さない。
_RANDOM_TOKEN = re.compile(r"[(（](?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{8,}[)）]")
SUSPICIOUS_SOURCES = ("Unisba", "- YouTube",  # YouTube の動画題(実例: 「…激怒！返り討ち論破に遭いニタニタ顔で逃亡 - YouTube」)
                     )


def suspicious_source(title: str) -> bool:
    t = unicodedata.normalize("NFKC", title or "")
    # 実例(2026-11-05): 「\u200d\u200d\u200dai 画像 生成 サイト 規制 なし ai」— 検索語を並べた宣伝ページ。
    # ゼロ幅文字を仕込んだ見出しは、まともな報道には無い
    if re.search("[\u200b-\u200d\u2060\ufeff]", title or ""):
        return True
    return bool(_RANDOM_TOKEN.search(t)) or any(s in t for s in SUSPICIOUS_SOURCES)
