# -*- coding: utf-8 -*-
"""
generate_bacon_feed.py
-----------------------
ベーコンボットのフィード(docs/bacon/feed.json)を生成・更新する。
GitHub Actions(.github/workflows/bacon.yml)から定期的に呼び出す。

実行のたびに、まだ取り上げていない世論・メディア・科学技術の記事を1件選び、
ベーコンのイドラ論による論評を生成してフィードの先頭に追加する。

他のボットとはファイルを共有しない:
  フィード   docs/bacon/feed.json
  既出記事   logs/bacon_seen.json
  引用履歴   logs/bacon_recent_quotes.json, logs/bacon_quote_usage.json

ただし、マキャベリ・モンテーニュの両ボットがすでに論評した記事は読むだけ読んで避ける
(同じ記事に三人が順に論評を付ける事態を防ぐ)。

使い方:
    python generate_bacon_feed.py
"""

import datetime
import json
import os
import re

import bacon_engine
from bacon_scorer import load_scoring_config, rank_news
from news_fetcher import fetch_all
from geopolitical_scorer import clean_news_text, is_japanese, _MEDIA_SUFFIX
from generate_feed import has_english_text
from bot import _hash_item

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "bacon_config.yaml")
FEED_DIR = os.path.join(BASE_DIR, "docs", "bacon")
FEED_PATH = os.path.join(FEED_DIR, "feed.json")
SEEN_PATH = os.path.join(BASE_DIR, "logs", "bacon_seen.json")
MAX_FEED_ITEMS = 30
MAX_SEEN = 2000  # 既出記事の記録が際限なく膨らまないよう、古いものから捨てる

# 姉妹ボットの記録(読むだけで書き換えない)
SIBLING_SEEN = [
    os.path.join(BASE_DIR, "logs", "seen.json"),
    os.path.join(BASE_DIR, "logs", "montaigne_seen.json"),
]
SIBLING_FEEDS = [
    os.path.join(BASE_DIR, "docs", "feed.json"),
    os.path.join(BASE_DIR, "docs", "montaigne", "feed.json"),
]


def _load_json(path: str, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _title_key(title: str) -> str:
    """媒体名と空白・記号を除いた見出し。配信元が違っても同じ記事を同一とみなすための鍵。"""
    t = _MEDIA_SUFFIX.sub("", clean_news_text(title or ""))
    return re.sub(r"[\s　「」『』【】()()、。・,.!?!?…\-—―]", "", t)


def _sibling_records() -> tuple:
    hashes, titles = set(), set()
    for path in SIBLING_SEEN:
        hashes.update(_load_json(path, []))
    for path in SIBLING_FEEDS:
        for entry in _load_json(path, []):
            key = _title_key(entry.get("source_title", ""))
            if key:
                titles.add(key)
    return hashes, titles


def main():
    scoring_cfg = load_scoring_config(CONFIG_PATH)
    seen_list = _load_json(SEEN_PATH, [])
    seen = set(seen_list)
    sibling_hashes, sibling_titles = _sibling_records()
    own_titles = {_title_key(e.get("source_title", "")) for e in _load_json(FEED_PATH, [])}

    items = fetch_all(CONFIG_PATH)
    if not items:
        print("[SKIP] ニュースを取得できませんでした。")
        return

    ranked = rank_news(items, scoring_cfg["weights"], top_n=20,
                       exclude_keywords=scoring_cfg["exclude_keywords"])
    target = None
    for item in ranked:
        h = _hash_item(item)
        key = _title_key(item.title)
        if h in seen or item.score < scoring_cfg["minimum_score"]:
            continue
        if h in sibling_hashes or key in sibling_titles:
            print(f"[見送り] 他のボットが論評済み: {item.title}")
            continue
        if key in own_titles:
            continue  # 別の配信元から届いた同じ記事
        if not is_japanese(clean_news_text(item.title)):
            continue  # 題材は日本語の配信に限る(訳の工程を持たない)
        target = (item, h)
        break

    if target is None:
        print("[SKIP] 新規かつ重要度十分なニュースがありませんでした。")
        return

    item, h = target
    print(f"[選出] {item.title}(score={item.score}, themes={item.themes})")
    text = bacon_engine.generate_commentary(item, prefer_llm=True)

    seen_list.append(h)
    _save_json(SEEN_PATH, seen_list[-MAX_SEEN:])

    if has_english_text(text):
        print(f"[SKIP] 本文に英語が残っているため掲載を見送りました:\n{text}")
        return

    quote = bacon_engine.QUOTES_BY_ID[bacon_engine.LAST_QUOTE_ID]
    entry = {
        "id": h[:12],
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "text": text,
        # 引用の原文(英語またはラテン語)。本文の字数に含めず、ウィジェットが別の行に小さく表示する
        "original": bacon_engine.display_original(quote),
        "original_lang": quote["lang"],
        "theme": item.theme,
        "score": item.score,
        "source": item.source,
        "source_title": item.title,
        "source_url": item.url,
        # 以下はウィジェットには表示されない。動作確認・品質点検用の記録
        "generator": bacon_engine.LAST_ANALYSIS_SOURCE,
        "themes": item.themes,
        "quote_id": bacon_engine.LAST_QUOTE_ID,
        "quote_choice": bacon_engine.LAST_QUOTE_CHOICE,
    }
    feed = _load_json(FEED_PATH, [])
    feed.insert(0, entry)
    _save_json(FEED_PATH, feed[:MAX_FEED_ITEMS])
    print(f"[OK] docs/bacon/feed.json に追加しました:\n{text}\n{entry['original']}")


if __name__ == "__main__":
    main()
