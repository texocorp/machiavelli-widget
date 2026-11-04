# -*- coding: utf-8 -*-
"""
schedule_guard.py
------------------
毎時起動される定時実行のうち、実際に生成を行うかを決める。
3つのボットのワークフロー(tweet.yml / montaigne.yml / bacon.yml)の guard ジョブから呼ばれ、
結果を GitHub Actions の出力 run=true / run=false として返す。

【2026-11-04 改訂: ストック方式】
GitHub の定時実行は、毎時起動を試みても1日に2〜3回しか起動されないことがある。
そこで、起動された回にまとめて論評を作り、表示の時刻はウィジェットが決める方式にした(feed_stock.py)。
この判定は「ストックが足りているか」だけを見る。

【規則】
- 手動実行(workflow_dispatch)は常に実行する
- 定時実行は、ストック(未表示の論評)が feed_stock.REFILL_HOURS 時間先まで無ければ実行する
- フィードを読めないときは実行する(読めないせいで掲載が止まることを避ける)

使い方(ワークフローの guard ジョブから):
    python3 schedule_guard.py montaigne
環境変数: GITHUB_EVENT_NAME、GITHUB_OUTPUT
"""

import datetime
import json
import os
import sys

import feed_stock

BOTS = feed_stock.BOTS


def decide(bot: str, now: datetime.datetime, event: str, feed) -> tuple:
    """(実行するか, 理由) を返す。feed はフィードの内容(読めなければ None)。"""
    if event != "schedule":
        return True, f"手動実行など({event})なので実行する"
    if feed is None:
        return True, "フィードを読めないので実行する"
    hours = feed_stock.stock_hours(feed, now)
    if hours < feed_stock.REFILL_HOURS:
        return True, f"ストックが{hours:.1f}時間先までしか無い({feed_stock.REFILL_HOURS}時間未満)ので実行する"
    return False, f"ストックが{hours:.1f}時間先まであるので見送る"


def main():
    bot = sys.argv[1] if len(sys.argv) > 1 else ""
    if bot not in BOTS:
        print(f"使い方: python3 schedule_guard.py {{{'|'.join(BOTS)}}}")
        sys.exit(2)
    now = datetime.datetime.now(datetime.timezone.utc)
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    feed = None
    try:
        with open(os.path.join(feed_stock.BASE_DIR, BOTS[bot][2]), encoding="utf-8") as f:
            feed = json.load(f)
        print(f"[判定] {bot}: {feed_stock.summary(feed, now)}")
    except Exception as e:
        print(f"[判定] フィードを読めなかった: {e}")
    run, reason = decide(bot, now, event, feed)
    print(f"[判定] {reason}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"run={'true' if run else 'false'}\n")


if __name__ == "__main__":
    main()
