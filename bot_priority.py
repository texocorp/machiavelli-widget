# -*- coding: utf-8 -*-
"""
bot_priority.py
----------------
3つのボットの間で、同じ記事の取り合いを優先順位で裁く(2026-11-09 導入)。

優先順位: マキャベリ > ベーコン > モンテーニュ

【それまでの仕組み】
どのボットも、他のボットがすでに載せた(ストック中を含む)記事は feed_stock.published_titles()
と same_story() で避けていた。ただしこれは「先に作った者勝ち」で、実行の順番
(マキャベリ → 1時間後モンテーニュ → 2時間後ベーコン)で取り合いの勝敗が決まっていた。

【この仕組み】
下位のボットは、上位のボットが選びうる記事(上位のボットの選別をそのまま当てて合格する記事)を
最初から候補にしない。上位のボットが先に載せたかどうかに関わらず、その記事は上位の領分とみなす。
  - ベーコンは、マキャベリが選びうる記事を外す
  - モンテーニュは、マキャベリとベーコンが選びうる記事を外す
  - マキャベリは何も外さない(載せ済みの記事の重複回避は従来どおり)

ただし、上位のボットが「試したが掲載できなかった」記事(上位の既出記録にある記事)は、
上位がもう使わないので、下位のボットが使ってよい。

選別の判定は、各ボットの設定ファイル(重み・除外語・最低点・言説の語)をそのまま読むので、
設定を変えれば領分の線引きも自動的に追従する。
"""

import copy
import json
import os

import feed_stock
from geopolitical_scorer import NewsItem, clean_news_text, is_japanese

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PRIORITY = ["machiavelli", "bacon", "montaigne"]

_SEEN_PATHS = {
    "machiavelli": os.path.join(BASE_DIR, "logs", "seen.json"),
    "bacon": os.path.join(BASE_DIR, "logs", "bacon_seen.json"),
    "montaigne": os.path.join(BASE_DIR, "logs", "montaigne_seen.json"),
}

_cache = {}


def _seen(bot: str) -> set:
    if ("seen", bot) not in _cache:
        try:
            with open(_SEEN_PATHS[bot], encoding="utf-8") as f:
                _cache[("seen", bot)] = set(json.load(f))
        except (OSError, ValueError):
            _cache[("seen", bot)] = set()
    return _cache[("seen", bot)]


def _accepts_machiavelli(item: NewsItem) -> bool:
    import geopolitical_scorer as gs
    if "cfg_m" not in _cache:
        _cache["cfg_m"] = gs.load_scoring_config(os.path.join(BASE_DIR, "config.yaml"))
    cfg = _cache["cfg_m"]
    it = gs.score_item(copy.copy(item), cfg["weights"], cfg["exclude_keywords"])
    return it.score >= cfg["minimum_score"]


def _accepts_bacon(item: NewsItem) -> bool:
    import bacon_scorer as bs
    if "cfg_b" not in _cache:
        _cache["cfg_b"] = bs.load_scoring_config(os.path.join(BASE_DIR, "bacon_config.yaml"))
    cfg = _cache["cfg_b"]
    if not is_japanese(clean_news_text(item.title)):
        return False  # ベーコンは日本語の配信しか扱わない
    it = bs.score_item(copy.copy(item), cfg["weights"], cfg["exclude_keywords"],
                       cfg["discourse_keywords"], cfg["priority_sources"], cfg["priority_bonus"])
    return it.score >= cfg["minimum_score"]


_ACCEPTS = {
    "machiavelli": _accepts_machiavelli,
    "bacon": _accepts_bacon,
}


def claimed_by(item: NewsItem, me: str):
    """
    自分(me)より上位のボットがこの記事を選びうるなら、そのボット名を返す。なければ None。
    上位のボットがすでに試して掲載できなかった記事は、上位がもう使わないので None とする。
    """
    for bot in PRIORITY[:PRIORITY.index(me)]:
        try:
            if not _ACCEPTS[bot](item):
                continue
        except Exception as e:  # 判定の失敗で自分の実行を止めない
            print(f"[優先順位] {bot} の判定に失敗したため、この記事は {bot} の領分とみなさない: {e}")
            continue
        seen = _seen(bot)
        try:
            from bot import _hash_item
            tried = _hash_item(item) in seen or feed_stock.story_id(item.title) in seen
        except Exception:
            tried = False
        if tried:
            continue
        return bot
    return None
