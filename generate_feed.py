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
import json
import os

from geopolitical_scorer import load_scoring_config, rank_news
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


def save_feed(feed: list):
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(FEED_PATH, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)


def main():
    scoring_cfg = load_scoring_config("config.yaml")
    seen = load_seen()

    items = fetch_all()
    if not items:
        print("[SKIP] ニュースを取得できませんでした。")
        return

    ranked = rank_news(
        items,
        scoring_cfg["weights"],
        top_n=10,
        exclude_keywords=scoring_cfg["exclude_keywords"],
    )
    target = None
    for item in ranked:
        h = _hash_item(item)
        if h in seen:
            continue
        if item.score < scoring_cfg["minimum_score"]:
            continue  # 閾値未満、または除外キーワードに一致(score=-1)
        target = (item, h)
        break

    if target is None:
        print("[SKIP] 新規かつ重要度十分なニュースがありませんでした。")
        return

    item, h = target
    text = generate_commentary(item, prefer_llm=True)

    entry = {
        "id": h[:12],
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "text": text,
        "theme": item.theme,
        "score": item.score,
        "source": item.source,
        "source_title": item.title,
        "source_url": item.url,
    }

    feed = load_feed()
    feed.insert(0, entry)
    feed = feed[:MAX_FEED_ITEMS]
    save_feed(feed)

    seen.add(h)
    save_seen(seen)

    print(f"[OK] feed.json に追加しました: {item.title}")


if __name__ == "__main__":
    main()
