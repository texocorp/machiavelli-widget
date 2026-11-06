# -*- coding: utf-8 -*-
"""試験: ベーコンの候補の数を数える(LLM を使わない)。自分のフィードだけの場合と、姉妹のフィードも読む場合。"""
import collections, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import generate_bacon_feed as g
import feed_stock
from bacon_scorer import load_scoring_config, rank_news
from news_fetcher import fetch_all
from geopolitical_scorer import clean_news_text, is_japanese

cfg = load_scoring_config(g.CONFIG_PATH)
seen = set(g._load_json(g.SEEN_PATH, []))
_, sib_titles = g._sibling_records()
own_titles = {g._title_key(e.get("source_title", "")) for e in g._load_json(g.FEED_PATH, [])}
own_names = {s["name"] for s in __import__("news_fetcher").load_sources(g.CONFIG_PATH)}


EXC = collections.Counter()
SAMPLE = collections.defaultdict(list)


def census(items, label):
    EXC.clear(); SAMPLE.clear()
    ranked = rank_news(items, cfg["weights"], top_n=len(items), exclude_keywords=cfg["exclude_keywords"],
                       discourse_keywords=cfg["discourse_keywords"], priority_sources=cfg["priority_sources"],
                       priority_bonus=cfg["priority_bonus"])
    c = collections.Counter(); stories = feed_stock.published_titles(); ok = []
    for it in ranked:
        h = g._hash_item(it); key = g._title_key(it.title)
        if h in seen: c["試し済み"] += 1; continue
        if it.score < 0: c["除外語"] += 1; EXC[it.matched_keywords[0]] += 1; SAMPLE["除外語"].append(f"{it.matched_keywords[0]} {it.title}"); continue
        if it.score == 0: c["言説の語なし"] += 1; SAMPLE["言説の語なし"].append(it.title); continue
        if it.score < cfg["minimum_score"]: c["点数不足"] += 1; SAMPLE["点数不足"].append(f"{it.score} {it.title}"); continue
        if key in sib_titles or key in own_titles: c["載せた記事"] += 1; continue
        if not is_japanese(clean_news_text(it.title)): c["日本語でない"] += 1; continue
        if feed_stock.suspicious_source(it.title): c["不審な配信"] += 1; continue
        if feed_stock.story_id(it.title) in seen or feed_stock.same_story(it.title, stories):
            c["同じ話題"] += 1; continue
        stories.append(it.title); ok.append(it)
    print(f"\n===== {label}: 取得 {len(items)}件 → 新しい候補 {len(ok)}件 ({dict(c)})")
    print("除外語の内訳:", EXC.most_common(25))
    import random
    random.seed(1)
    for k, v in SAMPLE.items():
        print(f"--- {k}(例)")
        for t in random.sample(v, min(20, len(v))):
            print("   ", t[:90])
    return ok


pool = g.fetch_pool()
own = [i for i in pool if i.source in own_names]
census(own, "自分のフィードだけ")
ok = census(pool, "姉妹のフィードも読む")
by = collections.Counter("自分" if i.source in own_names else i.source for i in ok)
print("候補の出どころ:", dict(by))
for i in ok[:80]:
    print(f"  {i.score:>2} [{'自' if i.source in own_names else '借'}] {i.title[:80]}")
