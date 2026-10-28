"""Hand ranges in standard poker notation.

Supported tokens (comma separated):
  AA  AKs  AKo  AK         single hand classes (AK = suited + offsuit)
  22+  A2s+  KTo+          "this and better" (pairs up to AA, kicker up to one below)
  77-55  A5s-A2s  T9s-65s  dash ranges
  AsKs                     one exact combo
  any / random             all 1326 combos
  token:0.5                weight (play the hand 50% of the time)
Example: "22+, A2s+, KTo+, QJs, T9s-65s, AKo:0.5"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

from .cards import RANKS, SUITS

R = {c: i for i, c in enumerate(RANKS)}


def _class_combos(hi: int, lo: int, kind: str) -> list[tuple[int, int]]:
    """All combos of a hand class. kind: 'p' pair, 's' suited, 'o' offsuit, '' both."""
    out = []
    if hi == lo:
        for s1, s2 in combinations(range(4), 2):
            out.append((hi * 4 + s1, hi * 4 + s2))
        return out
    for s1 in range(4):
        for s2 in range(4):
            if kind == "s" and s1 != s2:
                continue
            if kind == "o" and s1 == s2:
                continue
            out.append((hi * 4 + s1, lo * 4 + s2))
    return out


def _parse_class(t: str) -> tuple[int, int, str]:
    """'AKs' -> (12, 11, 's'). Higher rank first."""
    if len(t) not in (2, 3) or t[0] not in R or t[1] not in R:
        raise ValueError(f"bad hand: {t!r}")
    a, b = R[t[0]], R[t[1]]
    kind = t[2] if len(t) == 3 else ""
    if kind not in ("", "s", "o"):
        raise ValueError(f"bad hand: {t!r}")
    if a == b:
        if kind:
            raise ValueError(f"pairs can't be suited/offsuit: {t!r}")
        return a, b, "p"
    hi, lo = max(a, b), min(a, b)
    return hi, lo, kind


def _expand_token(tok: str) -> list[tuple[int, int, str]]:
    """Expand one token into hand classes (hi, lo, kind)."""
    if tok.endswith("+"):
        hi, lo, kind = _parse_class(tok[:-1])
        if kind == "p":
            return [(r, r, "p") for r in range(hi, 13)]
        return [(hi, k, kind) for k in range(lo, hi)]
    if "-" in tok:
        a, b = tok.split("-")
        h1, l1, k1 = _parse_class(a)
        h2, l2, k2 = _parse_class(b)
        if k1 != k2:
            raise ValueError(f"mixed kinds in {tok!r}")
        if k1 == "p":
            lo_, hi_ = sorted((h1, h2))
            return [(r, r, "p") for r in range(lo_, hi_ + 1)]
        if h1 == h2:  # A5s-A2s: kicker varies
            lo_, hi_ = sorted((l1, l2))
            return [(h1, k, k1) for k in range(lo_, hi_ + 1)]
        if h1 - l1 == h2 - l2:  # T9s-65s: same gap, slide down
            lo_, hi_ = sorted((h1, h2))
            gap = h1 - l1
            return [(h, h - gap, k1) for h in range(lo_, hi_ + 1)]
        raise ValueError(f"can't understand range {tok!r}")
    return [_parse_class(tok)]


@dataclass
class Range:
    """A weighted set of 2-card combos."""
    weights: dict[tuple[int, int], float] = field(default_factory=dict)
    text: str = ""

    @classmethod
    def parse(cls, text: str) -> "Range":
        w: dict[tuple[int, int], float] = {}
        for raw in text.replace("\n", ",").split(","):
            tok = raw.strip().replace(" ", "")
            if not tok:
                continue
            weight = 1.0
            if ":" in tok:
                tok, ws = tok.split(":")
                weight = float(ws)
            if tok.lower() in ("any", "random", "all"):
                for a, b in combinations(range(52), 2):
                    w[(b, a)] = weight
                continue
            # exact combo like AsKs
            if len(tok) == 4 and tok[1] in SUITS and tok[3] in SUITS:
                a, b = R[tok[0]] * 4 + SUITS.index(tok[1]), R[tok[2]] * 4 + SUITS.index(tok[3])
                w[(max(a, b), min(a, b))] = weight
                continue
            for hi, lo, kind in _expand_token(tok):
                for a, b in _class_combos(hi, lo, "" if kind == "p" else kind):
                    w[(max(a, b), min(a, b))] = weight
        return cls(w, text)

    def __len__(self):
        return len(self.weights)

    def arrays(self, dead=()) -> tuple[np.ndarray, np.ndarray]:
        """(combos (M,2), weights (M,)) without combos that use a dead card."""
        dead = set(dead)
        items = [(c, w) for c, w in self.weights.items()
                 if w > 0 and c[0] not in dead and c[1] not in dead]
        if not items:
            return np.zeros((0, 2), np.int64), np.zeros(0)
        cs, ws = zip(*items)
        return np.array(cs, dtype=np.int64), np.array(ws, dtype=float)

    def percent(self) -> float:
        """How much of all 1326 starting hands this range covers."""
        return 100.0 * sum(self.weights.values()) / 1326.0

    def contains_class(self, hi: int, lo: int, suited: bool) -> float:
        """Average weight of a hand class in this range (0..1)."""
        kind = "p" if hi == lo else ("s" if suited else "o")
        cs = _class_combos(max(hi, lo), min(hi, lo), "" if kind == "p" else kind)
        return sum(self.weights.get((max(a, b), min(a, b)), 0.0) for a, b in cs) / len(cs)

    def contains_hand(self, c1: int, c2: int) -> float:
        return self.weights.get((max(c1, c2), min(c1, c2)), 0.0)

    def grid(self) -> list[list[float]]:
        """13x13 grid, row/col 0 = Ace. Above diagonal suited, below offsuit."""
        g = [[0.0] * 13 for _ in range(13)]
        for i in range(13):
            for j in range(13):
                ri, rj = 12 - i, 12 - j
                if i == j:
                    g[i][j] = self.contains_class(ri, ri, False)
                elif i < j:
                    g[i][j] = self.contains_class(ri, rj, True)
                else:
                    g[i][j] = self.contains_class(rj, ri, False)
        return g


def hand_class(c1: int, c2: int) -> str:
    """Two cards -> 'AKs' / 'AKo' / 'QQ'."""
    r1, r2 = c1 >> 2, c2 >> 2
    hi, lo = max(r1, r2), min(r1, r2)
    if hi == lo:
        return RANKS[hi] * 2
    return RANKS[hi] + RANKS[lo] + ("s" if (c1 & 3) == (c2 & 3) else "o")


def grid_label(i: int, j: int) -> str:
    ri, rj = 12 - i, 12 - j
    if i == j:
        return RANKS[ri] * 2
    if i < j:
        return RANKS[ri] + RANKS[rj] + "s"
    return RANKS[rj] + RANKS[ri] + "o"
