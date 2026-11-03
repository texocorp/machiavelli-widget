# -*- coding: utf-8 -*-
"""
schedule_guard.py
------------------
毎時起動される定時実行のうち、実際に生成を行うかを決める。
3つのボットのワークフロー(tweet.yml / montaigne.yml / bacon.yml)の guard ジョブから呼ばれ、
結果を GitHub Actions の出力 run=true / run=false として返す。

【なぜ必要か】
GitHub の定時実行は、混雑すると遅れたり取りこぼされたりする(公式文書にも明記)。
2026-11-03 には、3つのボットとも11時半ごろから5時間以上、一度も起動しなかった。
そこで起動の試みを毎時に増やし、実際に生成するかどうかをこのスクリプトで決める。
いくつかの回が取りこぼされても、どれかが起動すれば掲載が続く。

【規則】
- 手動実行(workflow_dispatch)は常に実行する
- 定時実行は、次のどちらかなら実行する
  (1) いまが自分の受け持ちの時刻(UTC の時 % 3 == SLOT)で、前回の実際の生成から MIN_GAP 分以上たっている
  (2) 前回の実際の生成から CATCH_UP 分以上たっている(受け持ちの時刻を取りこぼした後の追いつき)
- 「前回の実際の生成」は、このワークフローの直近の実行のうち、update-feed ジョブが
  成功で終わったものの開始時刻(GitHub の実行履歴から読む。状態ファイルは使わない)
- 実行履歴を読めないときは実行する(読めないせいで掲載が止まることを避ける)

GitHub が時刻どおりに動かしている間は、受け持ちの時刻どおり3時間おきに1時間ずつずれて順に動き
(マキャベリ 0,3,6…時 / モンテーニュ 1,4,7…時 / ベーコン 2,5,8…時 UTC)、
取りこぼしがあれば次の時刻に追いつく。追いついた後は、次の受け持ちの時刻で元の順に戻る。

使い方(ワークフローの guard ジョブから):
    python3 schedule_guard.py montaigne
環境変数: GH_TOKEN(github.token)、GITHUB_REPOSITORY、GITHUB_RUN_ID、GITHUB_EVENT_NAME、GITHUB_OUTPUT
"""

import datetime
import json
import os
import subprocess
import sys

BOTS = {
    # ボット名: (ワークフローのファイル名, 受け持ちの時刻 UTCの時 % 3)
    "machiavelli": ("tweet.yml", 0),
    "montaigne": ("montaigne.yml", 1),
    "bacon": ("bacon.yml", 2),
}
JOB_NAME = "update-feed"
MIN_GAP = 100     # 分。受け持ちの時刻でも、前回からこれ未満なら実行しない(追いつきの直後の二重実行を防ぐ)
CATCH_UP = 200    # 分。前回からこれ以上たっていれば、受け持ちの時刻でなくても実行する
RUNS_TO_SCAN = 20


def _gh_api(path: str) -> dict:
    out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True, timeout=30)
    return json.loads(out.stdout)


def _parse(ts: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def last_real_run(repo: str, workflow: str, current_run_id: str, api=_gh_api):
    """update-feed ジョブが成功で終わった直近の実行の、ジョブの開始時刻。見つからなければ None。"""
    runs = api(f"repos/{repo}/actions/workflows/{workflow}/runs?per_page={RUNS_TO_SCAN}").get("workflow_runs", [])
    for run in runs:
        if str(run.get("id")) == str(current_run_id) or run.get("status") != "completed":
            continue
        jobs = api(f"repos/{repo}/actions/runs/{run['id']}/jobs").get("jobs", [])
        for job in jobs:
            if job.get("name") == JOB_NAME and job.get("conclusion") == "success" and job.get("started_at"):
                return _parse(job["started_at"])
    return None


def decide(bot: str, now: datetime.datetime, event: str, last) -> tuple:
    """(実行するか, 理由) を返す。last は前回の実際の生成の時刻(None なら不明)。"""
    if event != "schedule":
        return True, f"手動実行など({event})なので実行する"
    if last is None:
        return True, "前回の実際の生成が見つからないので実行する"
    slot = BOTS[bot][1]
    gap = (now - last).total_seconds() / 60
    mine = now.hour % 3 == slot
    if mine and gap >= MIN_GAP:
        return True, f"受け持ちの時刻(UTC {now.hour}時)で、前回から{gap:.0f}分たっているので実行する"
    if gap >= CATCH_UP:
        return True, f"前回から{gap:.0f}分たっている(受け持ちの時刻を取りこぼした後の追いつき)ので実行する"
    if mine:
        return False, f"受け持ちの時刻だが、前回から{gap:.0f}分しかたっていない(追いつきの直後)ので見送る"
    return False, f"受け持ちの時刻ではなく(UTC {now.hour}時)、前回から{gap:.0f}分なので見送る"


def main():
    bot = sys.argv[1] if len(sys.argv) > 1 else ""
    if bot not in BOTS:
        print(f"使い方: python3 schedule_guard.py {{{'|'.join(BOTS)}}}")
        sys.exit(2)
    now = datetime.datetime.now(datetime.timezone.utc)
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    last = None
    if event == "schedule":
        try:
            last = last_real_run(os.environ["GITHUB_REPOSITORY"], BOTS[bot][0], os.environ.get("GITHUB_RUN_ID", ""))
        except Exception as e:  # 実行履歴を読めないときは実行する(掲載が止まるのを避ける)
            print(f"[判定] 実行履歴を読めなかった: {e}")
    run, reason = decide(bot, now, event, last)
    print(f"[判定] {bot}: 現在 {now:%Y-%m-%d %H:%M} UTC / 前回の実際の生成 "
          f"{last:%Y-%m-%d %H:%M} UTC" if last else f"[判定] {bot}: 現在 {now:%Y-%m-%d %H:%M} UTC / 前回の実際の生成 不明")
    print(f"[判定] {reason}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"run={'true' if run else 'false'}\n")


if __name__ == "__main__":
    main()
