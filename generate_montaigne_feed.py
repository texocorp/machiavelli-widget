# -*- coding: utf-8 -*-
"""
generate_montaigne_feed.py
---------------------------
モンテーニュボットのフィード(docs/montaigne/feed.json)を生成・更新する。
GitHub Actions(.github/workflows/montaigne.yml)から定期的に呼び出す。

実行のたびに、まだ取り上げていない社会面・科学医療の記事を1件選び、
モンテーニュの人間観察による論評を生成してフィードの先頭に追加する。

マキャベリボット(generate_feed.py)とはファイルを共有しない:
  フィード   docs/montaigne/feed.json
  既出記事   logs/montaigne_seen.json
  箴言履歴   logs/montaigne_recent_quotes.json, logs/montaigne_quote_usage.json

使い方:
    python generate_montaigne_feed.py
"""

import datetime
import json
import os

import montaigne_engine
from montaigne_scorer import load_scoring_config, rank_news
from news_fetcher import fetch_all
from geopolitical_scorer import clean_news_text, is_japanese
from generate_feed import has_english_text
from bot import _hash_item

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "montaigne_config.yaml")
FEED_DIR = os.path.join(BASE_DIR, "docs", "montaigne")
FEED_PATH = os.path.join(FEED_DIR, "feed.json")
SEEN_PATH = os.path.join(BASE_DIR, "logs", "montaigne_seen.json")
MAX_FEED_ITEMS = 30
MAX_SEEN = 2000  # 既出記事の記録が際限なく膨らまないよう、古いものから捨てる


def _load_json(path: str, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    scoring_cfg = load_scoring_config(CONFIG_PATH)
    seen_list = _load_json(SEEN_PATH, [])
    seen = set(seen_list)

    items = fetch_all(CONFIG_PATH)
    if not items:
        print("[SKIP] ニュースを取得できませんでした。")
        return

    ranked = rank_news(items, scoring_cfg["weights"], top_n=15,
                       exclude_keywords=scoring_cfg["exclude_keywords"])
    target = None
    for item in ranked:
        h = _hash_item(item)
        if h in seen or item.score < scoring_cfg["minimum_score"]:
            continue
        if not is_japanese(clean_news_text(item.title)):
            continue  # 題材は日本語の配信に限る(訳の工程を持たない)
        target = (item, h)
        break

    if target is None:
        print("[SKIP] 新規かつ重要度十分なニュースがありませんでした。")
        return

    item, h = target
    print(f"[選出] {item.title}(score={item.score}, themes={item.themes})")
    text = montaigne_engine.generate_commentary(item, prefer_llm=True)

    seen_list.append(h)
    _save_json(SEEN_PATH, seen_list[-MAX_SEEN:])

    if has_english_text(text):
        print(f"[SKIP] 本文に英語が残っているため掲載を見送りました:\n{text}")
        return

    entry = {
        "id": h[:12],
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "text": text,
        "theme": item.theme,
        "score": item.score,
        "source": item.source,
        "source_title": item.title,
        "source_url": item.url,
        # 以下はウィジェットには表示されない。動作確認・品質点検用の記録
        "generator": montaigne_engine.LAST_ANALYSIS_SOURCE,
        "themes": item.themes,
        "quote_id": montaigne_engine.LAST_QUOTE_ID,
        "quote_choice": montaigne_engine.LAST_QUOTE_CHOICE,
    }
    feed = _load_json(FEED_PATH, [])
    feed.insert(0, entry)
    _save_json(FEED_PATH, feed[:MAX_FEED_ITEMS])
    print(f"[OK] docs/montaigne/feed.json に追加しました:\n{text}")


if __name__ == "__main__":
    main()
