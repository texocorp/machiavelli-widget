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
import time

import bacon_engine
import feed_stock
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


# 2026-11-06: 言説の検索フィード15本だけでは、毎日入れ替わる記事が少なく、1回の起動で候補が尽きて
# 0件で終わった(取得464件のうち新しい記事は十数件)。姉妹ボットが読む一般の配信(国内・社会・国際など、
# 毎時入れ替わる)も読み、ベーコンの選別(言説の語・除外語・点数)で絞る。姉妹が論評した記事は従来どおり外す。
BORROWED_CONFIGS = [os.path.join(BASE_DIR, "montaigne_config.yaml"), os.path.join(BASE_DIR, "config.yaml")]


def fetch_pool() -> list:
    """自分のフィードを先に、姉妹ボットのフィードを後に読み、同じ記事(URLか見出し)を1件にまとめる。"""
    items = fetch_all(CONFIG_PATH, per_feed_limit=50)
    own = len(items)
    for path in BORROWED_CONFIGS:
        items += fetch_all(path, per_feed_limit=50)
    pool, urls, keys = [], set(), set()
    for it in items:
        key = _title_key(it.title)
        if (it.url and it.url in urls) or key in keys:
            continue
        urls.add(it.url)
        keys.add(key)
        pool.append(it)
    print(f"[取得] 自分のフィード {own}件、姉妹のフィード {len(items) - own}件、重複を除いて {len(pool)}件")
    return pool


def main():
    scoring_cfg = load_scoring_config(CONFIG_PATH)
    seen_list = _load_json(SEEN_PATH, [])
    seen = set(seen_list)
    _, sibling_titles = _sibling_records()
    own_titles = {_title_key(e.get("source_title", "")) for e in _load_json(FEED_PATH, [])}

    # ストック方式では1回の起動で1日分を作るので、各フィードから多めに読む(10件では新しい記事がすぐ尽きた)
    # 2026-11-05: 30件→50件。候補が尽きて、生成に使える時間を半分以上余らせて終わる回が続いた
    items = fetch_pool()
    if not items:
        print("[SKIP] ニュースを取得できませんでした。")
        return

    # 上位40件に限ると、そのほとんどが試し済みで新しい記事が数件しか残らなかった。全件を点数順に試す
    ranked = rank_news(items, scoring_cfg["weights"], top_n=len(items),
                       exclude_keywords=scoring_cfg["exclude_keywords"],
                       discourse_keywords=scoring_cfg["discourse_keywords"],
                       priority_sources=scoring_cfg["priority_sources"],
                       priority_bonus=scoring_cfg["priority_bonus"])
    no_discourse = sum(1 for i in items if getattr(i, "matched_keywords", None) == ["[言説の語なし]"])
    print(f"[選別] 取得{len(items)}件のうち、言説の語を含まず外したもの {no_discourse}件")
    # 【ストック方式】起動された回に、表示の時刻を割り当てた論評をまとめて作る(feed_stock.py)。
    # ストックが TARGET_HOURS 先まで埋まるか、生成に使える時間が尽きるまで、記事を順に試す。
    import quote_commentary
    started = time.time()
    deadline = started + feed_stock.generation_budget_sec("bacon")
    quote_commentary.DEADLINE = deadline  # 1件の途中でも、ここで打ち切る(ワークフローの上限の手前)
    feed = _load_json(FEED_PATH, [])
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
        key = _title_key(item.title)
        if h in seen or item.score < scoring_cfg["minimum_score"]:
            continue
        # 姉妹が「試して載せなかった」記事は使ってよい(載せた記事だけを避ける)。2026-11-06 まで試しただけの記事も
        # 外していたが、姉妹のフィードを読むようになると、姉妹の見送った記事が大量に候補から消える
        if key in sibling_titles:
            print(f"[見送り] 他のボットが論評済み: {item.title}")
            continue
        if key in own_titles:
            continue  # 別の配信元から届いた同じ記事
        if not is_japanese(clean_news_text(item.title)):
            continue  # 題材は日本語の配信に限る(訳の工程を持たない)
        if feed_stock.suspicious_source(item.title):
            print(f"[見送り] 素性の疑わしい配信: {item.title}")
            continue
        if feed_stock.story_id(item.title) in seen or feed_stock.same_story(item.title, story_titles):
            print(f"[見送り] 同じ記事を既に試した・載せた(別の配信): {item.title}")
            continue
        print(f"[選出] {item.title}(score={item.score}, themes={item.themes})")
        text = bacon_engine.generate_commentary(item, prefer_llm=True)
        # 同じ記事で毎回やり直さないよう、試した記事は成否にかかわらず既出にする
        seen.add(h)
        seen_list.append(h)
        sid = feed_stock.story_id(item.title)
        seen.add(sid)
        seen_list.append(sid)
        story_titles.append(item.title)
        _save_json(SEEN_PATH, seen_list[-MAX_SEEN:])
        if text is None:
            continue
        if has_english_text(text):
            print(f"[SKIP] 本文に英語が残っているため掲載を見送りました:\n{text}")
            continue
        quote = bacon_engine.QUOTES_BY_ID[bacon_engine.LAST_QUOTE_ID]
        entry = {
            "id": h[:12],
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
        feed = feed_stock.trim(feed_stock.add_entry(feed, entry, "bacon", now), now, MAX_FEED_ITEMS)
        _save_json(FEED_PATH, feed)  # 1件ごとに書き出す(途中で打ち切られても、それまでの分は残す)
        own_titles.add(key)
        added += 1
        print(f"[OK] 表示 {feed[0]['publish_at'][:16]}Z: {item.title}\n{text}\n{entry['original']}")

    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"[ストック] 終了時: {feed_stock.summary(feed, now)}。この回に加えた論評 {added}件")


# 1件の記事に掛かる時間の上限の目安。残りがこれを切ったら、新しい記事には手を付けない
PER_ARTICLE_RESERVE_SEC = 8 * 60


if __name__ == "__main__":
    main()
