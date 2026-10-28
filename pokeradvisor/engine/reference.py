"""Slow, simple brute-force evaluator used ONLY to test the fast one.

It ranks every 5-card subset with plain, easy-to-read rules and keeps the
best. It returns scores in exactly the same format as evaluator.evaluate,
so the two can be compared number for number.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations

from .cards import VOID


def _pack(cat: int, ranks: list[int]) -> int:
    v = 0
    for i in range(5):
        v = (v << 4) | (ranks[i] if i < len(ranks) else 0)
    return (cat << 20) | v


def rank5(cards5) -> int:
    ranks = sorted((c >> 2 for c in cards5), reverse=True)
    suits = [c & 3 for c in cards5]
    flush = len(set(suits)) == 1
    uniq = sorted(set(ranks), reverse=True)
    straight_high = None
    if len(uniq) == 5 and uniq[0] - uniq[4] == 4:
        straight_high = uniq[0]
    if uniq == [12, 3, 2, 1, 0]:
        straight_high = 3  # wheel
    cnt = Counter(ranks)
    # groups ordered by (count, rank) descending
    groups = sorted(cnt.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    shape = [c for _, c in groups]
    gr = [r for r, _ in groups]
    if straight_high is not None and flush:
        return _pack(8, [straight_high])
    if shape[0] == 4:
        return _pack(7, gr)
    if shape[:2] == [3, 2]:
        return _pack(6, gr)
    if flush:
        return _pack(5, ranks)
    if straight_high is not None:
        return _pack(4, [straight_high])
    if shape[0] == 3:
        return _pack(3, gr)
    if shape[:2] == [2, 2]:
        return _pack(2, gr)
    if shape[0] == 2:
        return _pack(1, gr)
    return _pack(0, ranks)


def best_of(cards) -> int:
    cs = [c for c in cards if c != VOID]
    return max(rank5(c5) for c5 in combinations(cs, 5))
