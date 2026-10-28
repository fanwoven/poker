"""The decision engine: turns a game spot into one clear recommendation.

Pure math, explainable. Everything tunable lives in config.yaml.

Conventions (all amounts in chips):
  pot       = every chip in the middle, INCLUDING bets already made on this
              street (so the opponent's bet you are facing is in the pot).
  to_call   = chips you must add to call (0 = you can check).
  hero_stack= your chips behind (not yet in the pot).
  RAISE/BET amounts are "to" amounts: your total bet on this street.
"""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np

from .cards import VOID, names
from .equity import EquityResult, equity as calc_equity
from .evaluator import evaluate
from .handinfo import draws, made_hand
from .positions import in_position as pos_in_position, is_early
from .ranges import Range, hand_class

STREETS = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}


@dataclass
class Spot:
    hero: list[int]
    board: list[int] = field(default_factory=list)
    pot: float = 0.0
    to_call: float = 0.0
    hero_stack: float = 0.0
    bb: float = 1.0
    position: str = "BTN"
    n_opponents: int = 1                 # opponents still in the hand
    villain_position: str | None = None
    villain_stack: float | None = None   # biggest opponent stack behind
    hero_bet: float | None = None        # what I already bet this street (None = guess)
    preflop: str | None = None           # unopened / open / 3bet / 4bet (None = guess)
    pot_type: str | None = None          # postflop: limped / srp / 3bet / 4bet
    hero_aggressor: bool | None = None   # postflop: did I make the last preflop raise?
    in_position: bool | None = None      # None = work it out from positions
    hand_id: str = ""
    session_result: float = 0.0          # chips won/lost this session (for warnings)
    antes: float = 0.0                   # total antes in the pot (so they aren't counted as limpers)

    @property
    def street(self) -> str:
        return STREETS.get(len(self.board), "?")


@dataclass
class Advice:
    action: str                          # FOLD CHECK CALL BET RAISE
    amount: float = 0.0                  # call amount, or bet/raise "to" amount
    allin: bool = False
    reason: str = ""
    equity: EquityResult | None = None
    pot_odds: float = 0.0                # equity needed to call (0..1)
    spr: float = 0.0
    pct_stack: float = 0.0               # % of my stack this action puts in
    dice: int | None = None              # 0..99, None when no dice was used
    hand: str = ""                       # "top pair", "flush draw" ...
    villain_range: str = ""              # what we assume they have
    warnings: list[str] = field(default_factory=list)
    ms: float = 0.0

    def label(self) -> str:
        if self.action in ("FOLD", "CHECK"):
            return self.action
        amt = fmt_chips(self.amount)
        if self.action == "CALL":
            return f"CALL {amt}" + (" (all-in)" if self.allin else "")
        if self.allin:
            return f"ALL-IN {amt}"
        if self.action == "BET":
            return f"BET {amt}"
        return f"RAISE to {amt}"


def fmt_chips(x: float) -> str:
    if abs(x - round(x)) < 1e-9 or abs(x) >= 100:
        return f"{int(round(x)):,}"
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def dice_roll(spot: Spot) -> int:
    """0..99, fixed for the same spot so re-reading gives the same answer."""
    key = f"{spot.hand_id}|{names(spot.hero)}|{names(spot.board)}|{spot.to_call:.2f}|{spot.pot:.2f}"
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") % 100


def _seed(spot: Spot) -> int:
    key = f"{names(spot.hero)}|{names(spot.board)}"
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")


class Engine:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.e = cfg.get("engine", {})
        self.r = cfg.get("ranges", {})
        self.b = cfg.get("bankroll", {})
        self._ranges: dict[str, Range] = {}
        self._eq_cache: OrderedDict = OrderedDict()
        self._narrow_cache: OrderedDict = OrderedDict()

    # ---------------------------------------------------------------- helpers
    def rng(self, text: str) -> Range:
        if text not in self._ranges:
            self._ranges[text] = Range.parse(text)
        return self._ranges[text]

    def open_range(self, pos: str | None) -> Range:
        opens = self.r["open"]
        pos = pos if pos in opens else ("BTN" if pos == "BB" else self.r.get("villain_default_open", "CO"))
        return self.rng(opens.get(pos, opens["CO"]))

    def equity(self, hero, board, ranges: list[Range], seed=None) -> EquityResult:
        """Cached equity. Same cards + same ranges = instant second time."""
        key = (tuple(hero), tuple(board), tuple(id(r) for r in ranges))
        if key in self._eq_cache:
            self._eq_cache.move_to_end(key)
            return self._eq_cache[key]
        res = calc_equity(hero, board, ranges,
                          samples=self.e.get("monte_carlo_samples", 20000),
                          time_limit_ms=self.e.get("monte_carlo_time_limit_ms", 250),
                          seed=seed, exact_max_evals=self.e.get("exact_max_evals", 400000))
        self._eq_cache[key] = res
        while len(self._eq_cache) > 512:
            self._eq_cache.popitem(last=False)
        return res

    def _round(self, amount: float, bb: float) -> float:
        step = max(bb * self.e.get("round_to_bb", 0.5), 1e-9)
        return max(step, round(amount / step) * step)

    def _hero_in(self, s: Spot) -> float:
        """Chips I already have in on this street."""
        if s.hero_bet is not None:
            return s.hero_bet
        if not s.board:
            return {"SB": 0.5 * s.bb, "BB": s.bb}.get(s.position, 0.0)
        return 0.0

    def _ip(self, s: Spot) -> bool:
        return s.in_position if s.in_position is not None else pos_in_position(s.position, s.villain_position)

    def _realization(self, s: Spot) -> float:
        ip = self._ip(s)
        if not s.board:
            return self.e.get("realization_preflop_in_position" if ip else "realization_preflop_out_of_position", 0.8)
        if len(s.board) == 5:
            return 1.0  # no cards to come
        return self.e.get("realization_in_position" if ip else "realization_out_of_position", 0.9)

    # ------------------------------------------------------------- preflop
    def classify_preflop(self, s: Spot) -> str:
        if s.preflop:
            return s.preflop
        facing = (s.to_call + self._hero_in(s)) / s.bb
        if s.to_call <= 1e-9 or facing <= 1.0 + 1e-6:
            return "unopened"
        if facing <= self.e.get("preflop_open_max_bb", 5.0):
            return "open"
        if facing <= self.e.get("preflop_3bet_max_bb", 14.0):
            return "3bet"
        return "4bet"

    def preflop_villain_ranges(self, s: Spot, kind: str) -> list[Range]:
        n = max(1, s.n_opponents)
        if kind == "unopened":
            return [self.rng(self.r["villain_blind_defend"])] * n
        if kind == "open":
            main = self.open_range(s.villain_position)
        elif kind == "3bet":
            main = self.rng(self.r["villain_threebet"])
        else:
            main = self.rng(self.r["villain_fourbet"])
        return [main] + [self.rng(self.r["villain_call_open"])] * (n - 1)

    def _raise_to(self, s: Spot, to: float) -> tuple[float, bool]:
        """Round a raise, turn it into all-in if it uses most of my stack."""
        hero_in = self._hero_in(s)
        max_to = s.hero_stack + hero_in
        to = self._round(to, s.bb)
        if to >= self.e.get("allin_if_bet_over_stack", 0.6) * max_to or to >= max_to:
            return max_to, True
        return to, False

    def _preflop(self, s: Spot, a: Advice, dice: int) -> Advice:
        kind = self.classify_preflop(s)
        hc = hand_class(*s.hero)
        c1, c2 = s.hero
        hero_in = self._hero_in(s)
        facing = s.to_call + hero_in
        ip = self._ip(s)
        a.hand = hc

        if kind == "unopened":
            if s.to_call <= 1e-9:  # big blind, nobody raised: free option
                if self.rng(self.r["iso_raise"]).contains_hand(c1, c2) > 0:
                    limpers = max(0, round((s.pot - s.antes - 1.5 * s.bb) / s.bb))
                    to, allin = self._raise_to(s, (self.e["open_size_bb"] + 1 + limpers) * s.bb)
                    return self._fill(a, "RAISE", to, allin, f"{hc} is strong enough to raise a limped pot.")
                return self._fill(a, "CHECK", 0, False, f"Nobody raised and {hc} is not strong enough to raise. Check for free.")
            w = self.open_range(s.position).contains_hand(c1, c2)
            if w > 0 and dice < w * 100:
                limpers = max(0, round((s.pot - s.antes - 1.5 * s.bb) / s.bb))
                to, allin = self._raise_to(s, (self.e["open_size_bb"] + limpers) * s.bb)
                why = f"{hc} is in your {s.position} opening range. Raise first in."
                if w < 1:
                    why += f" (mixed hand: raise {w:.0%} of the time, dice {dice})"
                return self._fill(a, "RAISE", to, allin, why)
            return self._fill(a, "FOLD", 0, False, f"{hc} is not in your {s.position} opening range.")

        vil = self.preflop_villain_ranges(s, kind)
        a.villain_range = vil[0].text
        eq = self.equity(s.hero, [], vil, seed=_seed(s))
        a.equity = eq
        needed = s.to_call / (s.pot + s.to_call) if s.to_call else 0
        a.pot_odds = needed
        real = self._realization(s)
        eff = eq.equity * real

        if kind == "open":
            early = is_early(s.villain_position or "")
            value = self.r["threebet_value_vs_early" if early else "threebet_value_vs_late"]
            mult = self.e["threebet_multiplier_ip" if ip else "threebet_multiplier_oop"]
            if self.rng(value).contains_hand(c1, c2) > 0:
                to, allin = self._raise_to(s, facing * mult)
                return self._fill(a, "RAISE", to, allin, f"{hc} is a value 3-bet: you win {eq.equity:.0%} against their opening range.")
            f = self.e["threebet_bluff_freq"]
            if self.rng(self.r["threebet_bluff"]).contains_hand(c1, c2) > 0 and dice < f * 100:
                to, allin = self._raise_to(s, facing * mult)
                return self._fill(a, "RAISE", to, allin, f"3-bet bluff: {hc} has good blockers/playability and the dice said bluff ({dice} < {f*100:.0f}).", dice)
        elif kind == "3bet":
            if self.rng(self.r["fourbet_value"]).contains_hand(c1, c2) > 0:
                to, allin = self._raise_to(s, facing * self.e["fourbet_multiplier"])
                return self._fill(a, "RAISE", to, allin, f"{hc} is a value 4-bet: you win {eq.equity:.0%} against a 3-bet range.")
            f = self.e["fourbet_bluff_freq"]
            if self.rng(self.r["fourbet_bluff"]).contains_hand(c1, c2) > 0 and dice < f * 100:
                to, allin = self._raise_to(s, facing * self.e["fourbet_multiplier"])
                return self._fill(a, "RAISE", to, allin, f"4-bet bluff with {hc} (dice {dice} < {f*100:.0f}).", dice)
        else:  # 4-bet or more
            if self.rng(self.r["fivebet_value"]).contains_hand(c1, c2) > 0:
                to = s.hero_stack + hero_in
                return self._fill(a, "RAISE", to, True, f"{hc} is strong enough to go all-in against a 4-bet.")

        if s.to_call >= s.hero_stack:
            if eq.equity >= needed:
                return self._fill(a, "CALL", s.hero_stack, True, f"You win {eq.equity:.0%}, you need {needed:.0%}. Call all-in.")
            return self._fill(a, "FOLD", 0, False, f"You win only {eq.equity:.0%} but need {needed:.0%} to call all-in.")
        if eff >= needed:
            return self._fill(a, "CALL", s.to_call, False,
                              f"You win {eq.equity:.0%} (about {eff:.0%} after position), you need {needed:.0%}. Call.")
        return self._fill(a, "FOLD", 0, False,
                          f"You win {eq.equity:.0%} (about {eff:.0%} after position) but need {needed:.0%}. Fold.")

    # ------------------------------------------------------------ postflop
    def postflop_base_range(self, s: Spot) -> Range:
        pt = s.pot_type or "srp"
        agg = bool(s.hero_aggressor)
        if pt == "limped":
            return self.rng(self.r["villain_limp"])
        if pt == "3bet":
            return self.rng(self.r["villain_call_threebet" if agg else "villain_threebet"])
        if pt == "4bet":
            return self.rng(self.r["villain_fourbet"])
        return self.rng(self.r["villain_call_open"]) if agg else self.open_range(s.villain_position)

    def narrow(self, base: Range, board, dead, bet_frac: float) -> Range:
        """Keep the strongest part of a range (value) plus some draws/air
        (bluffs), based on how big the opponent's bet is."""
        table = self.e.get("narrow_by_bet_size", [[99, 0.4]])
        keep = table[-1][1]
        bucket = len(table) - 1
        for i, (lim, k) in enumerate(table):
            if bet_frac <= lim:
                keep, bucket = k, i
                break
        key = (id(base), tuple(board), tuple(sorted(dead)), bucket)
        if key in self._narrow_cache:
            return self._narrow_cache[key]
        combos, w = base.arrays(dead)
        if len(combos) == 0:
            return base
        pad = [VOID] * (5 - len(board))
        hands = np.hstack([combos, np.broadcast_to(np.array(list(board) + pad), (len(combos), 5))])
        score = evaluate(hands)
        order = np.argsort(-score, kind="stable")
        cum = np.cumsum(w[order]) / w.sum()
        value_idx = order[cum <= keep + 1e-9]
        if len(value_idx) == 0:
            value_idx = order[:1]
        new = {}
        for i in value_idx:
            new[(int(combos[i, 0]), int(combos[i, 1]))] = float(w[i])
        # bluffs: share of the final range = bet / (pot + 2 bet)
        bluff_share = bet_frac / (1 + 2 * bet_frac)
        bluff_w = w[value_idx].sum() * bluff_share / max(1e-9, 1 - bluff_share)
        rest = [i for i in order[::-1] if (int(combos[i, 0]), int(combos[i, 1])) not in new]
        if len(board) < 5:  # draws first
            rest.sort(key=lambda i: -len(draws(combos[i].tolist(), board)[0]))
        for i in rest:
            if bluff_w <= 0:
                break
            take = min(float(w[i]), bluff_w)
            new[(int(combos[i, 0]), int(combos[i, 1]))] = take
            bluff_w -= take
        r = Range(new, f"top {keep:.0%} of range + bluffs")
        self._narrow_cache[key] = r
        while len(self._narrow_cache) > 256:
            self._narrow_cache.popitem(last=False)
        return r

    def villain_ranges(self, s: Spot) -> list[Range]:
        if not s.board:
            return self.preflop_villain_ranges(s, self.classify_preflop(s))
        base = self.postflop_base_range(s)
        if s.to_call > 0:
            vbet = s.to_call + self._hero_in(s)
            before = max(s.pot - vbet - self._hero_in(s), 1e-9)
            base = self.narrow(base, s.board, set(s.hero) | set(s.board), vbet / before)
        return [base] * max(1, s.n_opponents)

    def _bet_size(self, s: Spot, frac: float) -> tuple[float, bool]:
        amt = self._round(frac * s.pot, s.bb)
        amt = max(amt, s.bb)
        eff = self._eff_stack(s)
        if amt >= self.e.get("allin_if_bet_over_stack", 0.6) * eff or amt >= eff:
            # betting more than the shorter stack is pointless: bet exactly that
            return eff, eff >= s.hero_stack
        return amt, False

    def _eff_stack(self, s: Spot) -> float:
        return min(s.hero_stack, s.villain_stack) if s.villain_stack else s.hero_stack

    def _postflop(self, s: Spot, a: Advice, dice: int) -> Advice:
        vil = self.villain_ranges(s)
        a.villain_range = vil[0].text
        eq = self.equity(s.hero, s.board, vil, seed=_seed(s))
        a.equity = eq
        e = eq.equity
        n = max(1, s.n_opponents)
        fair = 1.0 / (n + 1)
        river = len(s.board) == 5
        made = made_hand(s.hero, s.board)
        dlabels, outs = draws(s.hero, s.board)
        a.hand = ", ".join([made] + dlabels)
        is_draw = bool(dlabels) and not river
        strong = e >= self.e["strong_equity"]
        value = e >= fair + self.e["value_bet_margin"]
        spr = self._eff_stack(s) / max(s.pot, 1e-9)
        a.spr = spr

        if s.to_call <= 1e-9:
            if value:
                if spr <= self.e["allin_spr"]:
                    amt = self._eff_stack(s)
                    allin = amt >= s.hero_stack
                else:
                    frac = (self.e["size_river_strong"] if river else self.e["size_strong"]) if strong else \
                           (self.e["size_river_medium"] if river else self.e["size_medium"])
                    amt, allin = self._bet_size(s, frac)
                return self._fill(a, "BET", amt, allin,
                                  f"You win {e:.0%} against their likely hands (fair share {fair:.0%}). Bet for value.")
            if is_draw and dice < self.e["semi_bluff_freq"] * 100:
                amt, allin = self._bet_size(s, self.e["size_semi_bluff"])
                return self._fill(a, "BET", amt, allin,
                                  f"Semi-bluff with your {' and '.join(dlabels)} (~{outs} outs). Dice {dice} said bet.", dice)
            if river and e <= self.e["river_bluff_max_equity"]:
                frac = self.e["size_river_bluff"]
                p = self.e["river_bluff_scale"] * frac / (1 + frac)
                if dice < p * 100:
                    amt, allin = self._bet_size(s, frac)
                    return self._fill(a, "BET", amt, allin,
                                      f"River bluff: your hand can't win at showdown ({e:.0%}). Dice {dice} < {p*100:.0f} said bluff.", dice)
            return self._fill(a, "CHECK", 0, False,
                              f"You win {e:.0%}, not enough to bet for value (need {fair + self.e['value_bet_margin']:.0%}). Check.")

        # facing a bet
        needed = s.to_call / (s.pot + s.to_call)
        a.pot_odds = needed
        real = self._realization(s)
        eff = e * real
        hero_in = self._hero_in(s)
        vbet = s.to_call + hero_in
        allin_call = s.to_call >= s.hero_stack

        if not allin_call and e >= fair + self.e["value_raise_margin"]:
            if spr <= self.e["allin_spr"] * 1.5:
                to, allin = s.hero_stack + hero_in, True
            else:
                to, allin = self._raise_to(s, 3 * vbet)
            return self._fill(a, "RAISE", to, allin,
                              f"You win {e:.0%} even against their betting range. Raise for value.")
        if allin_call:
            if e >= needed:
                return self._fill(a, "CALL", s.hero_stack, True, f"You win {e:.0%}, you need {needed:.0%}. Call all-in.")
            return self._fill(a, "FOLD", 0, False, f"You win {e:.0%} but need {needed:.0%} to call all-in. Fold.")
        if eff >= needed:
            return self._fill(a, "CALL", s.to_call, False,
                              f"You win {e:.0%}, you need {needed:.0%} to call. Call.")
        if is_draw:
            implied = self.e["implied_odds_factor"] * min(max(self._eff_stack(s) - s.to_call, 0), s.pot)
            needed_imp = s.to_call / (s.pot + s.to_call + implied)
            if eff >= needed_imp:
                return self._fill(a, "CALL", s.to_call, False,
                                  f"Call with your {' and '.join(dlabels)}: {e:.0%} now, need {needed:.0%}, but you can win more chips if you hit (implied odds).")
            if dice < self.e["semi_bluff_raise_freq"] * 100:
                to, allin = self._raise_to(s, 3 * vbet)
                return self._fill(a, "RAISE", to, allin,
                                  f"Semi-bluff raise with your {' and '.join(dlabels)}. Dice {dice} said raise.", dice)
        return self._fill(a, "FOLD", 0, False, f"You win {e:.0%} but need {needed:.0%} to call. Fold.")

    # ---------------------------------------------------------------- main
    def _fill(self, a: Advice, action, amount, allin, reason, dice=None) -> Advice:
        a.action, a.amount, a.allin, a.reason = action, float(amount), bool(allin), reason
        if dice is not None:
            a.dice = dice
        return a

    def decide(self, s: Spot) -> Advice:
        t0 = time.perf_counter()
        if len(s.hero) != 2 or len(set(s.hero) | set(s.board)) != 2 + len(s.board):
            raise ValueError("need 2 hole cards and no duplicate cards")
        dice = dice_roll(s)
        a = Advice("CHECK")
        a.spr = (min(s.hero_stack, s.villain_stack) if s.villain_stack else s.hero_stack) / max(s.pot, 1e-9)
        if s.board:
            self._postflop(s, a, dice)
        else:
            self._preflop(s, a, dice)
        # how much of my stack this puts in
        put_in = a.amount - (self._hero_in(s) if a.action == "RAISE" else 0) if a.action in ("CALL", "BET", "RAISE") else 0
        a.pct_stack = 100.0 * put_in / s.hero_stack if s.hero_stack > 0 else 0.0
        self._bankroll(s, a, put_in)
        a.ms = (time.perf_counter() - t0) * 1000
        return a

    def _bankroll(self, s: Spot, a: Advice, put_in: float):
        b = self.b
        if not b:
            return
        broke = []
        maxp = b.get("max_pct_stack_per_decision") or 0
        if maxp and a.pct_stack > maxp:
            broke.append(f"risks {a.pct_stack:.0f}% of your stack (rule: max {maxp}%)")
        floor = b.get("stack_floor") or 0
        if floor and s.hero_stack - put_in < floor:
            broke.append(f"stack would drop below {fmt_chips(floor)}")
        stop = b.get("stop_loss") or 0
        if stop and s.session_result <= -abs(stop):
            broke.append(f"session loss reached stop-loss {fmt_chips(stop)}")
        a.warnings += broke
        if broke and b.get("enforce") and a.action in ("CALL", "BET", "RAISE"):
            a.reason += " Bankroll rule enforced: " + "; ".join(broke) + "."
            a.action = "CHECK" if s.to_call <= 1e-9 else "FOLD"
            a.amount, a.allin = 0.0, False

    def precompute(self, s: Spot) -> None:
        """Warm the caches as soon as cards are known (call from a background
        thread while opponents act), so decide() is instant on my turn."""
        try:
            self.equity(s.hero, s.board, self.villain_ranges(s), seed=_seed(s))
        except Exception:
            pass
