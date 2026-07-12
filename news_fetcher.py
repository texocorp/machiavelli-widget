# -*- coding: utf-8 -*-
"""
news_fetcher.py
-----------------
config.yaml の news_sources (RSS) から最新記事を取得する。
実行環境にインターネットアクセスが必要(このモジュールはユーザーの実行環境で動作する)。

依存: pip install feedparser
"""

import feedparser
import yaml
from geopolitical_scorer import NewsItem, clean_news_text


def load_sources(config_path: str = "config.yaml") -> list:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["news_sources"]


def fetch_all(config_path: str = "config.yaml", per_feed_limit: int = 10) -> list:
    sources = load_sources(config_path)
    items = []
    for src in sources:
        try:
            feed = feedparser.parse(src["url"])
        except Exception as e:
            print(f"[WARN] フィード取得失敗: {src['name']} ({e})")
            continue
        for entry in feed.entries[:per_feed_limit]:
            title = clean_news_text(getattr(entry, "title", "").strip())
            summary = clean_news_text(
                getattr(entry, "summary", getattr(entry, "description", "")).strip()
            )
            link = getattr(entry, "link", "")
            if not title:
                continue
            items.append(NewsItem(title=title, summary=summary, source=src["name"], url=link))
    return items


if __name__ == "__main__":
    for it in fetch_all():
        print(f"- [{it.source}] {it.title}")
