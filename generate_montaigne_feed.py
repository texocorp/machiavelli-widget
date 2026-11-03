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
import calendar
import re
import time

import feedparser
import yaml

from geopolitical_scorer import NewsItem, clean_news_text, is_japanese
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


# 記事の鮮度の上限(時間)。これより古い記事は選ばない。
# 実例(2026-11-03): NHK社会のRSSから、8月8日付の「熊本 各地で9日も厳しい暑さに」が選ばれた。
# RSS の中に古い記事が残っていることがあるため、配信日時(無ければURL中の日付)で判定する。
MAX_AGE_HOURS = 48
_URL_DATE = re.compile(r"/(20\d{2})(\d{2})(\d{2})/")


def _published_epoch(entry) -> float:
    """
    記事の配信日時(UNIX時刻)。RSSの日時とURL中の /YYYYMMDD/ の両方があれば、古いほうを採る
    (RSSの日時だけが新しく付け直された古い記事も弾くため)。どちらも無ければ None。
    """
    stamps = []
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            stamps.append(calendar.timegm(st))
            break
    m = _URL_DATE.search(entry.get("link", "") or "")
    if m:
        stamps.append(calendar.timegm((int(m.group(1)), int(m.group(2)), int(m.group(3)), 0, 0, 0)))
    return min(stamps) if stamps else None


def fetch_fresh(config_path: str, per_feed_limit: int = 15) -> list:
    """
    news_fetcher.fetch_all と同じ取得処理に、鮮度の判定を加えたもの。
    フィードごとの件数と最新記事の日時をログに出し、配信が止まったフィードに気づけるようにする。
    """
    with open(config_path, "r", encoding="utf-8") as f:
        sources = yaml.safe_load(f)["news_sources"]
    now = time.time()
    items = []
    for src in sources:
        try:
            feed = feedparser.parse(src["url"])
        except Exception as e:
            print(f"[WARN] フィード取得失敗: {src['name']} ({e})")
            continue
        fresh = stale = undated = 0
        newest = None
        for entry in feed.entries[:per_feed_limit]:
            title = clean_news_text(getattr(entry, "title", "").strip())
            if not title:
                continue
            ts = _published_epoch(entry)
            if ts is not None:
                newest = max(newest or ts, ts)
                if now - ts > MAX_AGE_HOURS * 3600:
                    stale += 1
                    continue
            else:
                undated += 1
            fresh += 1
            summary = clean_news_text(
                getattr(entry, "summary", getattr(entry, "description", "")).strip()
            )
            items.append(NewsItem(title=title, summary=summary, source=src["name"],
                                  url=getattr(entry, "link", "")))
        newest_s = time.strftime("%Y-%m-%d %H:%M", time.gmtime(newest)) + "Z" if newest else "不明"
        print(f"[フィード] {src['name']}: 採用{fresh}件 / 古い{stale}件 / 日時不明{undated}件(最新 {newest_s})")
    return items


def main():
    scoring_cfg = load_scoring_config(CONFIG_PATH)
    seen_list = _load_json(SEEN_PATH, [])
    seen = set(seen_list)

    items = fetch_fresh(CONFIG_PATH)
    if not items:
        print("[SKIP] ニュースを取得できませんでした。")
        return

    ranked = rank_news(items, scoring_cfg["weights"], top_n=15,
                       exclude_keywords=scoring_cfg["exclude_keywords"])
    # LLM の分析文がすべての検査を通った記事だけを掲載する。
    # テンプレート(LLMが使えないときの代替)の文は掲載しない。
    # 実例(2026-11-03): 交通事故の記事に、裁きをめぐる型の文と節度の箴言が組み合わさり、
    # 「鳴子峡近くの5人けが事故…は、裁きもまた人の手によるものであり…」という筋の通らない論評が出た。
    # 1回の実行で試す記事は MAX_ARTICLES_PER_RUN 件まで(1件あたり CPU で数分かかるため)。
    MAX_ARTICLES_PER_RUN = 2
    tried = 0
    text = item = h = None
    for cand in ranked:
        ch = _hash_item(cand)
        if ch in seen or cand.score < scoring_cfg["minimum_score"]:
            continue
        if not is_japanese(clean_news_text(cand.title)):
            continue  # 題材は日本語の配信に限る(訳の工程を持たない)
        if tried >= MAX_ARTICLES_PER_RUN:
            break
        tried += 1
        print(f"[選出] {cand.title}(score={cand.score}, themes={cand.themes})")
        result = montaigne_engine.generate_commentary(cand, prefer_llm=True)
        # 同じ記事で毎回やり直さないよう、試した記事は成否にかかわらず既出にする
        seen.add(ch)
        seen_list.append(ch)
        if montaigne_engine.LAST_ANALYSIS_SOURCE == "template":
            print("[見送り] LLMの分析文が検査を通らなかったため、この記事は掲載しません")
            continue
        text, item, h = result, cand, ch
        break
    _save_json(SEEN_PATH, seen_list[-MAX_SEEN:])

    if text is None:
        print("[SKIP] 掲載できる論評がありませんでした(新規の記事が無いか、検査を通る分析文が得られなかった)。")
        return

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
