# -*- coding: utf-8 -*-
"""
bot.py
-------
Machiavelli Geopolitics Bot 本体。

使い方:
    python bot.py --once          # 1回だけ実行して終了(テスト向け)
    python bot.py                 # config.yaml の頻度設定に従い常駐実行

頻度調整は config.yaml の schedule セクションで行う:
    posting_interval_minutes / posts_per_day_cap / quiet_hours

投稿を実際にXへ送るには:
    1. config.yaml の mode.dry_run を false にする
    2. 環境変数 TWITTER_API_KEY / TWITTER_API_SECRET /
       TWITTER_ACCESS_TOKEN / TWITTER_ACCESS_SECRET を設定する
       (pip install tweepy が必要)
"""

import argparse
import datetime
import hashlib
import json
import os
import time

import yaml

from geopolitical_scorer import load_weights, rank_news
from machiavelli_engine import generate_commentary
from news_fetcher import fetch_all

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "tweets.jsonl")
SEEN_PATH = os.path.join(os.path.dirname(__file__), "logs", "seen.json")


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _hash_item(item) -> str:
    return hashlib.sha256(f"{item.title}|{item.source}".encode("utf-8")).hexdigest()


def load_seen() -> set:
    if os.path.exists(SEEN_PATH):
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False)


def in_quiet_hours(cfg) -> bool:
    tz_cfg = cfg["schedule"]["quiet_hours"]
    now = datetime.datetime.now().time()
    start = datetime.time.fromisoformat(tz_cfg["start"])
    end = datetime.time.fromisoformat(tz_cfg["end"])
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end  # 日をまたぐ場合


def count_today_posts() -> int:
    if not os.path.exists(LOG_PATH):
        return 0
    today = datetime.date.today().isoformat()
    n = 0
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                if rec["timestamp"].startswith(today):
                    n += 1
            except Exception:
                continue
    return n


def post_tweet(text: str, cfg: dict):
    """dry_run=false の場合、tweepy 経由で実際にXへ投稿する。"""
    if cfg["mode"]["dry_run"]:
        print("[DRY-RUN] 投稿は行われません。以下は生成結果のプレビューです:\n")
        print(text)
        print("-" * 40)
        return

    import tweepy  # pip install tweepy

    keys = cfg["twitter_api"]
    client = tweepy.Client(
        consumer_key=os.environ[keys["api_key_env"]],
        consumer_secret=os.environ[keys["api_secret_env"]],
        access_token=os.environ[keys["access_token_env"]],
        access_token_secret=os.environ[keys["access_secret_env"]],
    )
    client.create_tweet(text=text)
    print("[POSTED] X へ投稿しました。")


def log_tweet(text: str, item):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": datetime.datetime.now().isoformat(),
            "text": text,
            "source_title": item.title,
            "source": item.source,
            "score": item.score,
            "theme": item.theme,
        }, ensure_ascii=False) + "\n")


def run_once(cfg: dict, seen: set) -> bool:
    """1サイクル実行。投稿できた場合 True を返す。"""
    if in_quiet_hours(cfg):
        print("[SKIP] 静粛時間帯のため見送り。")
        return False

    if count_today_posts() >= cfg["schedule"]["posts_per_day_cap"]:
        print("[SKIP] 本日の投稿上限に達しました。")
        return False

    weights = cfg["scoring_weights"]
    exclude_keywords = cfg.get("exclude_keywords", [])
    minimum_score = cfg.get("selection", {}).get("minimum_score", 1)

    items = fetch_all()
    if not items:
        print("[SKIP] ニュースを取得できませんでした。")
        return False

    ranked = rank_news(items, weights, top_n=10, exclude_keywords=exclude_keywords)
    for item in ranked:
        h = _hash_item(item)
        if h in seen:
            continue  # 既につぶやいた話題はスキップ
        if item.score < minimum_score:
            continue  # 地政学的重要度が閾値未満、または除外キーワードに一致(score=-1)

        text = generate_commentary(item, prefer_llm=True)
        post_tweet(text, cfg)
        log_tweet(text, item)
        seen.add(h)
        save_seen(seen)
        return True

    print("[SKIP] 新規かつ重要度十分なニュースがありませんでした。")
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="1回だけ実行して終了")
    args = parser.parse_args()

    cfg = load_config()
    seen = load_seen()

    if args.once:
        run_once(cfg, seen)
        return

    interval = cfg["schedule"]["posting_interval_minutes"] * 60
    print(f"Machiavelli Bot 起動。投稿間隔: {cfg['schedule']['posting_interval_minutes']}分 "
          f"/ dry_run={cfg['mode']['dry_run']}")
    while True:
        try:
            run_once(cfg, seen)
        except Exception as e:
            print(f"[ERROR] {e}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
