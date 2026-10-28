"""Fast vectorised poker hand evaluator (numpy).

evaluate(hands) takes an (N, k) int array of cards (k = 5..7, VOID=52 allowed
as filler) and returns N scores. A higher score is a better hand, equal
scores are a tie.

Score layout:  category << 20 | five 4-bit rank "nibbles"
  category: 8 straight flush, 7 quads, 6 full house, 5 flush, 4 straight,
            3 trips, 2 two pair, 1 pair, 0 high card
  nibbles:  ranks that break ties inside the category, most important first.

Speed: a few million 7-card hands per second on one CPU core, which is what
makes exact enumeration and big Monte Carlo runs possible in pure Python.
"""
from __future__ import annotations

import numpy as np

from .cards import VOID

CATEGORY_NAMES = [
    "high card", "pair", "two pair", "three of a kind", "straight",
    "flush", "full house", "four of a kind", "straight flush",
]

_NMASK = 1 << 13


def _build_tables():
    """Tables indexed by a 13-bit rank mask."""
    straight = np.full(_NMASK, -1, dtype=np.int64)  # high rank of best straight
    topk = np.zeros((6, _NMASK), dtype=np.int64)     # top k ranks packed in nibbles
    windows = [(t, sum(1 << r for r in range(t - 4, t + 1))) for t in range(12, 3, -1)]
    wheel = (1 << 12) | 0b1111  # A-2-3-4-5, high card is the 5 (rank 3)
    for m in range(_NMASK):
        for t, w in windows:
            if m & w == w:
                straight[m] = t
                break
        else:
            if m & wheel == wheel:
                straight[m] = 3
        ranks = [r for r in range(12, -1, -1) if m >> r & 1]
        for k in range(1, 6):
            v = 0
            for i in range(k):
                v = (v << 4) | (ranks[i] if i < len(ranks) else 0)
            topk[k, m] = v
    return straight, topk


_STRAIGHT, _TOPK = _build_tables()
_BITS = (1 << np.arange(13, dtype=np.int64))


def evaluate(hands) -> np.ndarray:
    """Score many hands at once. hands: (N, k) array-like of card ints."""
    h = np.asarray(hands, dtype=np.int64)
    if h.ndim == 1:
        h = h[None, :]
    n = h.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.int64)
    valid = h != VOID
    r = np.where(valid, h >> 2, 13)          # 13 = "no rank" column
    s = np.where(valid, h & 3, 4)            # 4 = "no suit" column
    row = np.arange(n)[:, None]
    rc = np.bincount((r + 14 * row).ravel(), minlength=14 * n).reshape(n, 14)[:, :13]
    sc = np.bincount((s + 5 * row).ravel(), minlength=5 * n).reshape(n, 5)[:, :4]

    rank_mask = (rc > 0).astype(np.int64) @ _BITS
    bit = np.where(valid, 1 << np.where(valid, h >> 2, 0), 0)
    suit_masks = np.stack([np.where(s == j, bit, 0).sum(1) for j in range(4)], 1)

    fsuit = sc.argmax(1)
    is_flush = sc.max(1) >= 5
    fmask = suit_masks[np.arange(n), fsuit]
    sf_high = np.where(is_flush, _STRAIGHT[fmask], -1)
    st_high = _STRAIGHT[rank_mask]

    # groups sorted by (count, rank): top two give quads/trips/pairs
    key = np.where(rc > 0, rc * 16 + np.arange(13), 0)
    key.sort(axis=1)
    k0, k1 = key[:, -1], key[:, -2]
    c0, r0, c1, r1 = k0 >> 4, k0 & 15, k1 >> 4, k1 & 15

    one = np.int64(1)
    without_r0 = rank_mask & ~(one << r0)
    without_r01 = without_r0 & ~(one << r1)

    cat = np.zeros(n, dtype=np.int64)
    val = _TOPK[5, rank_mask]  # high card

    def put(cond, c, v):
        nonlocal cat, val
        upd = cond & (cat <= c)  # only upgrade, higher categories win
        cat = np.where(upd, c, cat)
        val = np.where(upd, v, val)

    put(c0 == 2, 1, (r0 << 16) | (_TOPK[3, without_r0] << 4))
    put((c0 == 2) & (c1 == 2), 2, (r0 << 16) | (r1 << 12) | (_TOPK[1, without_r01] << 8))
    put(c0 == 3, 3, (r0 << 16) | (_TOPK[2, without_r0] << 8))
    put(st_high >= 0, 4, np.maximum(st_high, 0) << 16)
    put(is_flush, 5, _TOPK[5, fmask])
    put((c0 == 3) & (c1 >= 2), 6, (r0 << 16) | (r1 << 12))
    put(c0 == 4, 7, (r0 << 16) | (_TOPK[1, without_r0] << 12))
    put(sf_high >= 0, 8, np.maximum(sf_high, 0) << 16)
    return (cat << 20) | val


def evaluate_one(cards) -> int:
    """Score a single hand (list of 5-7 card ints)."""
    return int(evaluate([list(cards)])[0])


def category(score) -> int:
    return int(score) >> 20


def describe(score) -> str:
    return CATEGORY_NAMES[category(score)]
