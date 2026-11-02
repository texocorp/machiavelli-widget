# -*- coding: utf-8 -*-
"""
tools/verify_bacon_quotes.py
-----------------------------
data/bacon_quotes.json の全引用の原文を、原典の当該篇・当該アフォリズムの中で
逐語照合する(空白と大小文字の差だけを吸収する)。引用を追加・修正したら必ず実行する。

原典(いずれもパブリックドメイン)は GitHub 上の写しから取得する:
  随筆集(1625年版)   Project Gutenberg #575 の写し(GITenberg)
  ノヴム・オルガヌム   The Latin Library 本文の写し(CLTK)

使い方:
    python tools/verify_bacon_quotes.py
不一致が1件でもあれば終了コード1で終わり、どの語まで一致したかを表示する。
"""

import json
import os
import re
import sys

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUOTES_PATH = os.path.join(BASE_DIR, "data", "bacon_quotes.json")

ESSAYS_URL = "https://raw.githubusercontent.com/GITenberg/The-Essays-or-Counsels-Civil-and-Moral_575/master/575.txt"
NO_URL = "https://raw.githubusercontent.com/cltk/lat_text_latin_library/master/bacon/bacon.liber{book}.txt"


def _get(url: str) -> str:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content.decode("utf-8", errors="replace")


def _roman(s: str) -> int:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total = prev = 0
    for ch in reversed(s):
        v = vals[ch]
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def load_essays() -> dict:
    """篇番号(1625年版の配列、目次順)→ 本文。"""
    lines = _get(ESSAYS_URL).splitlines()
    toc = [l.strip() for l in lines[40:110] if l.strip().lower().startswith("of ")]
    toc = [t for t in toc if not t.upper().startswith("OF FRANCIS")]
    norm = lambda s: re.sub(r"\s+", " ", s.strip().lower())
    toc_norm = [norm(t) for t in toc]
    start = next(i for i, l in enumerate(lines) if l.strip() == "Of Truth" and i > 110)
    end = next(i for i, l in enumerate(lines) if "END OF" in l and "PROJECT GUTENBERG" in l.upper())
    body = lines[start:end]
    heads = [(i, toc_norm.index(norm(l))) for i, l in enumerate(body)
             if norm(l) in toc_norm and (i == 0 or body[i - 1].strip() == "")]
    essays = {}
    for k, (i, idx) in enumerate(heads):
        j = heads[k + 1][0] if k + 1 < len(heads) else len(body)
        essays[f"E{idx + 1}"] = re.sub(r"\s+", " ", " ".join(body[i + 1:j]))
    return essays


def load_aphorisms(book: str) -> dict:
    aph, cur = {}, None
    for p in (x.strip() for x in _get(NO_URL.format(book=book)).splitlines()):
        m = re.fullmatch(r"([IVXLC]+)\.", p)
        if m:
            cur = _roman(m.group(1))
            aph[f"NO{book}.{cur}"] = ""
        elif cur is not None and p:
            aph[f"NO{book}.{cur}"] += " " + p
    return aph


def main() -> int:
    sections = load_essays()
    for book in ("1", "2"):
        sections.update(load_aphorisms(book))
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()

    quotes = json.load(open(QUOTES_PATH, encoding="utf-8"))["quotes"]
    bad = 0
    for q in quotes:
        sec = norm(sections.get(q["source"], ""))
        if norm(q["orig"]) in sec:
            continue
        bad += 1
        words = q["orig"].split()
        k = next((k for k in range(len(words), 0, -1) if norm(" ".join(words[:k])) in sec), 0)
        print(f"不一致 {q['id']}({q['source']}): 先頭{k}語まで一致 … {q['orig'][:80]}")
    print(f"照合結果: {len(quotes)}件中 不一致 {bad}件")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
