"""Follows the hand over time from the table reads, and builds the Spot the
engine needs (cards, pot, amount to call, position, opponents...).

Anything it can't know safely is listed in `missing` and shown as "?".
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..engine.cards import names
from ..engine.positions import position_for
from ..engine.strategy import Spot
from ..profile import Profile
from ..vision.reader import TableState, parse_button


@dataclass
class HandInfo:
    hand_id: str
    hole: list[int]
    start_time: float
    start_stack: float | None
    position: str | None = None
    n_players: int | None = None
    board: list[int] = field(default_factory=list)
    preflop_max_bb: float = 0.0          # biggest preflop bet seen, in big blinds
    hero_aggressor: bool | None = None
    advice: list[dict] = field(default_factory=list)   # advice shown on my turns
    deviated: bool = False
    saw_my_turn: bool = False


class HandTracker:
    def __init__(self, profile: Profile, live_cfg: dict, engine_cfg: dict):
        self.p = profile
        self.cfg = live_cfg
        self.ecfg = engine_cfg
        self.bb = float(profile.big_blind or live_cfg.get("big_blind") or 0)
        self.manual_opponents: int | None = None
        self.manual_position: str | None = None
        self.hand: HandInfo | None = None
        self.counter = 0
        self.last_stack: float | None = None
        self.finished: list[tuple[HandInfo, float | None]] = []  # (hand, end stack) ready to be logged
        self.pending: HandInfo | None = None   # ended hand, waiting for the next hand's start stack

    # ------------------------------------------------------------- helpers
    def _num(self, st: TableState, name: str) -> tuple[float | None, bool]:
        """(value, known). Box not calibrated -> (None, False)."""
        if name not in self.p.regions:
            return None, False
        r = st.get(name)
        if r.ok:
            return float(r.value), True
        if r.status == "none":
            return 0.0, True
        return None, False

    def seats_in(self, st: TableState) -> list[int] | None:
        seats = [i for i in self.p.opponent_seats() if f"seat{i}_cards" in self.p.regions]
        if not seats:
            return None
        out = []
        for i in seats:
            r = st.get(f"seat{i}_cards")
            if not r.ok:
                return None
            if r.value == "in":
                out.append(i)
        return out

    def dealer_seat(self, st: TableState) -> int | None:
        """0 = me, k = opponent seat k, None = unknown."""
        cands = []
        if "hero_dealer" in self.p.regions:
            r = st.get("hero_dealer")
            if r.ok and r.value == "yes":
                cands.append(0)
        for i in self.p.opponent_seats():
            n = f"seat{i}_dealer"
            if n in self.p.regions:
                r = st.get(n)
                if r.ok and r.value == "yes":
                    cands.append(i)
        return cands[0] if len(cands) == 1 else None

    def _position_of(self, seat: int, dealer: int, in_seats: list[int]) -> tuple[str, int]:
        """Position of `seat` (0 = me) given the dealer seat and who is dealt in."""
        ring = [0] + sorted(in_seats)                 # clockwise from me
        n = len(ring)
        # seats clockwise starting after the dealer
        all_seats = [0] + self.p.opponent_seats()
        if dealer not in all_seats:
            raise ValueError
        start = all_seats.index(dealer)
        order = all_seats[start + 1:] + all_seats[:start + 1]
        order = [s for s in order if s in ring]       # only players dealt in
        k = (order.index(seat) + 1) % n               # dealer itself is offset 0
        return position_for(n, k), n

    # -------------------------------------------------------------- update
    def update(self, st: TableState, now: float | None = None) -> list[str]:
        """Feed a new read. Returns events: 'new_hand', 'street', 'hand_end'."""
        now = now or time.time()
        events = []
        hole = st.hole()
        stack, _ = self._num(st, "stack")
        hero_bet, _ = self._num(st, "hero_bet")
        h_none = all(st.get(n).status == "none" for n in ("hole1", "hole2"))

        if self.hand and (h_none or (hole and hole != self.hand.hole)):
            # the hand is over; its result is known when the next hand starts
            # (winnings are often pushed after the cards disappear)
            if self.pending:
                self.finished.append((self.pending, None))
            self.pending = self.hand
            self.hand = None
            events.append("hand_end")
        if stack is not None:
            self.last_stack = stack + (hero_bet or 0)
        if hole and self.hand is None:
            self.counter += 1
            start = stack + (hero_bet or 0) if stack is not None else None
            if self.pending:
                self.finished.append((self.pending, start))
                self.pending = None
            self.hand = HandInfo(f"{time.strftime('%Y%m%d-%H%M%S')}-{self.counter}-{names(hole)}",
                                 hole, now, start)
            events.append("new_hand")
            self._fix_position(st)
        if self.hand is None:
            return events
        board = st.board()
        if board is not None and len(board) > len(self.hand.board):
            self.hand.board = board
            events.append("street")
        if self.hand.position is None:
            self._fix_position(st)
        if not self.hand.board:
            self._track_preflop(st)
        return events

    def _fix_position(self, st: TableState):
        h = self.hand
        dealer = self.dealer_seat(st)
        in_seats = self.seats_in(st)
        if dealer is not None and in_seats is not None:
            try:
                h.position, h.n_players = self._position_of(0, dealer, in_seats)
            except ValueError:
                pass

    def _track_preflop(self, st: TableState):
        if not self.bb:
            return
        bets = [self._num(st, f"seat{i}_bet")[0] for i in self.p.opponent_seats()]
        bets = [b for b in bets if b]
        btn = st.get("button")
        if btn.ok:
            kind, amt, _ = parse_button(btn.text, self.p.abbreviations)
            hero_bet, _ = self._num(st, "hero_bet")
            if kind == "call" and amt:
                bets.append(amt + (hero_bet or 0))
        if bets:
            self.hand.preflop_max_bb = max(self.hand.preflop_max_bb, max(bets) / self.bb)
        hero_bet, known = self._num(st, "hero_bet")
        if known and hero_bet and hero_bet > self.bb * 1.01:
            others = max(bets) if bets else 0
            self.hand.hero_aggressor = hero_bet >= others

    def mark_deviation(self):
        if self.hand:
            self.hand.deviated = True

    def pop_finished(self):
        out, self.finished = self.finished, []
        return out

    def close(self):
        """Session over: log the last hands with the last stack we saw."""
        for h in (self.pending, self.hand):
            if h:
                self.finished.append((h, self.last_stack))
        self.pending = self.hand = None

    # ---------------------------------------------------------------- spot
    def opponents(self, st: TableState) -> int | None:
        if self.manual_opponents:
            return self.manual_opponents
        seats = self.seats_in(st)
        if seats is not None:
            return max(1, len(seats))
        return None

    def build_spot(self, st: TableState) -> tuple[Spot | None, list[str], dict]:
        """-> (spot or None, missing items, extra info for the overlay)."""
        missing, info = [], {}
        h = self.hand
        if h is None:
            return None, ["cards"], info
        board = st.board()
        if board is None:
            missing.append("board")
        stack, known = self._num(st, "stack")
        if not known or not stack:
            missing.append("stack")
        if not self.bb:
            missing.append("big blind (set it: pa-ctl bb 20000)")

        # amount to call
        to_call, approx = None, False
        hero_bet, _ = self._num(st, "hero_bet")
        btn = st.get("button")
        if btn.ok:
            kind, amt, approx = parse_button(btn.text, self.p.abbreviations)
            if kind in ("check", "bet"):
                to_call = 0.0
            elif kind in ("call", "allin") and amt is not None:
                to_call = amt
        if to_call is None:
            bets = [self._num(st, f"seat{i}_bet") for i in self.p.opponent_seats()
                    if f"seat{i}_bet" in self.p.regions]
            if bets and all(k for _, k in bets):
                to_call = max(0.0, max(b or 0 for b, _ in bets) - (hero_bet or 0))
        if to_call is None:
            missing.append("call amount")
        info["call_approx"] = approx

        # pot = middle pot (+ bets on the table if the app doesn't include them)
        pot, pk = self._num(st, "pot")
        if not pk:
            missing.append("pot")
        elif not self.p.pot_includes_bets:
            for i in self.p.opponent_seats():
                if f"seat{i}_bet" in self.p.regions:
                    b, k = self._num(st, f"seat{i}_bet")
                    if not k:
                        missing.append(f"bet of seat {i}")
                    pot += b or 0
            pot += hero_bet or 0
            if not any(f"seat{i}_bet" in self.p.regions for i in self.p.opponent_seats()) and to_call:
                pot += to_call  # at least the bet I'm facing
        if pk and not board and pot is not None and self.bb:
            pot = max(pot, 1.5 * self.bb + (self.p.ante or 0))
        info["pot"] = pot

        n_opp = self.opponents(st)
        if n_opp is None:
            n_opp = int(self.cfg.get("default_opponents", 1))
            info["opp_guess"] = True
        pos = self.manual_position or h.position
        if pos is None:
            pos = self.cfg.get("default_position", "CO")
            info["pos_guess"] = True

        # villain: biggest bettor if known
        villain_pos, villain_stack = None, None
        if h.position and self.dealer_seat(st) is not None and self.seats_in(st) is not None:
            best = None
            for i in self.seats_in(st):
                b, k = self._num(st, f"seat{i}_bet")
                if k and b and (best is None or b > best[0]):
                    best = (b, i)
            if best:
                try:
                    villain_pos, _ = self._position_of(best[1], self.dealer_seat(st), self.seats_in(st))
                except ValueError:
                    pass
                vs, k = self._num(st, f"seat{best[1]}_stack")
                if k:
                    villain_stack = vs

        if missing:
            return None, missing, info
        pot_type = None
        if board:
            m = h.preflop_max_bb
            pot_type = ("limped" if m <= 1.01 else "srp" if m <= self.ecfg.get("preflop_open_max_bb", 5)
                        else "3bet" if m <= self.ecfg.get("preflop_3bet_max_bb", 14) else "4bet")
            if h.hero_aggressor is None and h.advice:
                pre = [a for a in h.advice if a.get("street") == "preflop"]
                if pre and not h.deviated:
                    h.hero_aggressor = pre[-1].get("action") == "RAISE"
        spot = Spot(hero=h.hole, board=board, pot=pot, to_call=to_call, hero_stack=stack, bb=self.bb,
                    position=pos, n_opponents=n_opp, villain_position=villain_pos, villain_stack=villain_stack,
                    hero_bet=hero_bet if "hero_bet" in self.p.regions else None,
                    pot_type=pot_type, hero_aggressor=h.hero_aggressor, hand_id=h.hand_id, antes=self.p.ante)
        return spot, [], info
