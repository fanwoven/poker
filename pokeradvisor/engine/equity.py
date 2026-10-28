"""Equity = how often my hand wins (ties count as a share) against opponent ranges.

- Heads-up with few cards to come (turn / river, or flop when the range is
  small): EXACT enumeration of every opponent combo and every runout.
- Otherwise: Monte Carlo sampling, reported with a 95% error margin (±).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from itertools import combinations

import numpy as np

from .cards import VOID
from .evaluator import evaluate
from .ranges import Range

CHUNK = 150_000  # rows per evaluator call, keeps memory small


@dataclass
class EquityResult:
    equity: float        # 0..1, my share of the pot on average
    error: float         # ± margin (95%), 0 for exact
    win: float           # fraction of outright wins
    tie: float           # fraction of ties
    method: str          # "exact" or "monte carlo"
    samples: int         # combos x runouts (exact) or simulated hands
    ms: float            # time taken

    def text(self) -> str:
        if self.method == "exact":
            return f"{self.equity * 100:.1f}% (exact)"
        return f"{self.equity * 100:.1f}% ±{self.error * 100:.1f}"


def _eval(h: np.ndarray) -> np.ndarray:
    if len(h) <= CHUNK:
        return evaluate(h)
    return np.concatenate([evaluate(h[i:i + CHUNK]) for i in range(0, len(h), CHUNK)])


def _pad(board: list[int]) -> list[int]:
    return list(board) + [VOID] * (5 - len(board))


def exact_heads_up(hero, board, villain: Range, max_evals: int | None = None) -> EquityResult | None:
    """Exact equity vs one range. Returns None if it would exceed max_evals."""
    t0 = time.perf_counter()
    dead = set(hero) | set(board)
    combos, w = villain.arrays(dead)
    if len(combos) == 0:
        return None
    deck = [c for c in range(52) if c not in dead]
    need = 5 - len(board)
    n_run = 1
    for i in range(need):
        n_run = n_run * (len(deck) - i) // (i + 1)
    if max_evals is not None and n_run * (len(combos) + 1) > max_evals:
        return None
    runs = np.array(list(combinations(deck, need)), dtype=np.int64).reshape(n_run, need)
    base = np.array(list(board), dtype=np.int64)
    boards = np.hstack([np.broadcast_to(base, (n_run, len(base))), runs])      # (R,5)
    hero_s = _eval(np.hstack([np.broadcast_to(np.array(hero), (n_run, 2)), boards]))  # (R,)

    # which (combo, runout) pairs are possible (no shared card)
    run_hot = np.zeros((n_run, 52), dtype=np.int32)
    if need:
        np.put_along_axis(run_hot, runs, 1, axis=1)
    combo_hot = np.zeros((len(combos), 52), dtype=np.int32)
    np.put_along_axis(combo_hot, combos, 1, axis=1)
    valid = (combo_hot @ run_hot.T) == 0                                         # (M,R)

    m_idx, r_idx = np.nonzero(valid)
    vil_s = _eval(np.hstack([combos[m_idx], boards[r_idx]]))
    hs = hero_s[r_idx]
    ww = w[m_idx]
    wins = (hs > vil_s) * ww
    ties = (hs == vil_s) * ww
    tot = ww.sum()
    eq = (wins.sum() + 0.5 * ties.sum()) / tot
    return EquityResult(float(eq), 0.0, float(wins.sum() / tot), float(ties.sum() / tot),
                        "exact", int(len(m_idx)), (time.perf_counter() - t0) * 1000)


def monte_carlo(hero, board, villains: list[Range], samples: int = 20000,
                time_limit_ms: float | None = None, seed: int | None = None,
                batch: int = 10000) -> EquityResult:
    """Simulated equity vs one or more ranges (multiway supported)."""
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    dead = set(hero) | set(board)
    vr = []
    for v in villains:
        cs, w = v.arrays(dead)
        if len(cs) == 0:
            cs, w = Range.parse("any").arrays(dead)
        vr.append((cs, w / w.sum()))
    need = 5 - len(board)
    base_used = np.zeros(52, dtype=bool)
    base_used[list(dead)] = True
    hero_a = np.array(hero, dtype=np.int64)
    board_a = np.array(board, dtype=np.int64)

    shares, wins, ties, n = [], 0.0, 0.0, 0
    while n < samples:
        if time_limit_ms is not None and n > 0 and (time.perf_counter() - t0) * 1000 > time_limit_ms:
            break
        b = batch
        used = np.broadcast_to(base_used, (b, 52)).copy()
        ok = np.ones(b, dtype=bool)
        rows = np.arange(b)
        vhands = []
        for cs, p in vr:
            pick = cs[rng.choice(len(cs), b, p=p)]
            clash = used[rows, pick[:, 0]] | used[rows, pick[:, 1]]
            ok &= ~clash
            used[rows, pick[:, 0]] = True
            used[rows, pick[:, 1]] = True
            vhands.append(pick)
        if need:
            keys = rng.random((b, 52))
            keys[used] = 2.0
            fill = np.argpartition(keys, need - 1, axis=1)[:, :need]
            boards = np.hstack([np.broadcast_to(board_a, (b, len(board_a))), fill])
        else:
            boards = np.broadcast_to(board_a, (b, 5))
        boards, vhands = boards[ok], [v[ok] for v in vhands]
        m = len(boards)
        if m == 0:
            continue
        hs = _eval(np.hstack([np.broadcast_to(hero_a, (m, 2)), boards]))
        vs = np.stack([_eval(np.hstack([v, boards])) for v in vhands], 1)
        best = vs.max(1)
        n_tied = (vs == hs[:, None]).sum(1)
        win = hs > best
        tie = hs == best
        share = win + tie / (1 + n_tied)
        shares.append(share)
        wins += win.sum()
        ties += tie.sum()
        n += m
    allv = np.concatenate(shares)
    eq = float(allv.mean())
    err = float(1.96 * allv.std() / np.sqrt(len(allv)))
    return EquityResult(eq, err, wins / n, ties / n, "monte carlo", n,
                        (time.perf_counter() - t0) * 1000)


def equity(hero, board, villains: list[Range], samples: int = 20000,
           time_limit_ms: float | None = None, seed: int | None = None,
           exact_max_evals: int = 400_000) -> EquityResult:
    """Best method automatically: exact when heads-up and small enough."""
    if len(villains) == 1 and len(board) >= 3:
        r = exact_heads_up(hero, board, villains[0], max_evals=exact_max_evals)
        if r is not None:
            return r
    return monte_carlo(hero, board, villains, samples, time_limit_ms, seed)
