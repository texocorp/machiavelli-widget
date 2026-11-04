# -*- coding: utf-8 -*-
"""
generate_feed.py
-------------------
X(Twitter)へ投稿する代わりに、ウェブサイト埋め込み用のJSONフィード
(docs/feed.json) を生成・更新するスクリプト。

GitHub Actions などのスケジューラから定期的に呼び出す想定。
実行のたびに、まだ取り上げていない最重要ニュースを1件選び、
マキャベリ的分析文を生成して feed.json の先頭に追加する。

使い方:
    python generate_feed.py
"""

import datetime
import time
import json
import os
import re

from geopolitical_scorer import load_scoring_config, rank_news
import feed_stock
import machiavelli_engine
from machiavelli_engine import generate_commentary
from news_fetcher import fetch_all
from bot import _hash_item, load_seen, save_seen  # 重複排除ロジックを再利用

DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
FEED_PATH = os.path.join(DOCS_DIR, "feed.json")
MAX_FEED_ITEMS = 30


def load_feed() -> list:
    if os.path.exists(FEED_PATH):
        with open(FEED_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


# 本文に英語の文(英単語が3語以上続く箇所)が混ざっているか。
# 1行目のURLは除いて調べる。「cap.XVII」のような出典表記は1語なので当たらない。
_ENGLISH_RUN = re.compile(r"[A-Za-z]+(?:[ ,'’-]+[A-Za-z]+){2,}")


def has_english_text(text: str) -> bool:
    lines = text.split("\n")
    if lines and lines[0].startswith("http"):
        lines = lines[1:]
    return bool(_ENGLISH_RUN.search("\n".join(lines)))


def save_feed(feed: list):
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(FEED_PATH, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)


def main():
    scoring_cfg = load_scoring_config("config.yaml")
    seen = load_seen()

    # ストック方式では1回の起動で1日分を作るので、各フィードから多めに読む(10件では新しい記事がすぐ尽きた)
    items = fetch_all(per_feed_limit=30)
    if not items:
        print("[SKIP] ニュースを取得できませんでした。")
        return

    ranked = rank_news(
        items,
        scoring_cfg["weights"],
        top_n=40,
        exclude_keywords=scoring_cfg["exclude_keywords"],
    )
    # 【ストック方式】起動された回に、表示の時刻を割り当てた論評をまとめて作る(feed_stock.py)。
    # ストックが TARGET_HOURS 先まで埋まるか、生成に使える時間が尽きるまで、記事を順に試す。
    # 検査をすべて通った論評だけを加える(generate_commentary が None を返したら次の記事へ)。
    import quote_commentary
    started = time.time()
    deadline = started + feed_stock.generation_budget_sec("machiavelli")
    quote_commentary.DEADLINE = deadline  # 1件の途中でも、ここで打ち切る(ワークフローの上限の手前)
    # 以前の版で掲載されてしまった、英語が混ざった論評も取り除く
    feed = [e for e in load_feed() if not has_english_text(e.get("text", ""))]
    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"[ストック] 開始時: {feed_stock.summary(feed, now)}(生成に使える時間 {(deadline - started) / 60:.0f}分)")
    story_titles = feed_stock.published_titles()
    added = 0
    for item in ranked:
        now = datetime.datetime.now(datetime.timezone.utc)
        if not feed_stock.needs_more(feed, now):
            break
        if deadline - time.time() < PER_ARTICLE_RESERVE_SEC:
            print("[ストック] 生成に使える時間が尽きたので打ち切る")
            break
        h = _hash_item(item)
        if h in seen:
            continue
        if item.score < scoring_cfg["minimum_score"]:
            continue  # 閾値未満、または除外キーワードに一致(score=-1)
        # 英語などの記事は、先に日本語に訳す。訳せなければこの記事は見送り、次の候補に進む
        try:
            machiavelli_engine.ensure_japanese(item)
        except Exception as e:
            print(f"[SKIP] 日本語に訳せないため見送り: {item.title} ({e})")
            continue
        if feed_stock.story_id(item.title) in seen or feed_stock.same_story(item.title, story_titles):
            print(f"[見送り] 同じ記事を既に試した・載せた(別の配信): {item.title}")
            continue
        print(f"[選出] {item.title}(score={item.score})")
        text = generate_commentary(item, prefer_llm=True)
        # 同じ記事で毎回やり直さないよう、試した記事は成否にかかわらず既出にする
        seen.add(h)
        seen.add(feed_stock.story_id(item.title))
        story_titles.append(item.title)
        save_seen(seen)
        if text is None:
            continue
        if has_english_text(text):
            # 最後の安全策。英語が混ざった論評は掲載しない
            print(f"[SKIP] 本文に英語が残っているため掲載を見送りました:\n{text}")
            continue
        entry = {
            "id": h[:12],
            "text": text,
            "theme": item.theme,
            "score": item.score,
            "source": item.source,
            "source_title": item.title,
            # 英語の記事を日本語に訳した見出し(日本語の記事では空)
            "source_title_ja": item.title_ja,
            "source_url": item.url,
            # 以下はウィジェットには表示されない。動作確認・品質点検用の記録
            "generator": machiavelli_engine.LAST_ANALYSIS_SOURCE,
            "themes": item.themes,
            "quote_id": machiavelli_engine.LAST_QUOTE_ID,
            "quote_choice": machiavelli_engine.LAST_QUOTE_CHOICE,
        }
        feed = feed_stock.trim(feed_stock.add_entry(feed, entry, "machiavelli", now), now, MAX_FEED_ITEMS)
        save_feed(feed)  # 1件ごとに書き出す(途中で打ち切られても、それまでの分は残す)
        added += 1
        print(f"[OK] 表示 {feed[0]['publish_at'][:16]}Z: {item.title}")

    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"[ストック] 終了時: {feed_stock.summary(feed, now)}。この回に加えた論評 {added}件")


# 1件の記事に掛かる時間の上限の目安。残りがこれを切ったら、新しい記事には手を付けない
PER_ARTICLE_RESERVE_SEC = 8 * 60


if __name__ == "__main__":
    main()
