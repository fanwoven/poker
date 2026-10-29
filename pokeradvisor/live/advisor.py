"""The live loop: watch the table, follow the hand, decide, report.

Timing plan (all automatic, no key presses needed):
  - every `turn_poll_s` (0.1 s): check ONLY the "my turn" box (cheap).
  - every `read_interval_s` (0.5 s): read the whole table. Unchanged boxes are
    cached, so this is cheap too. Cards are effectively read once per hand /
    street, and win odds are computed while opponents act (preview advice).
  - the moment my turn starts: read + decide immediately, beep, and measure
    the time from "turn started" to "advice ready".
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from ..engine.strategy import Advice, Engine, Spot
from ..profile import Profile
from ..stats.db import HandDB
from ..vision.reader import TableReader, TableState
from .tracker import HandTracker


@dataclass
class Update:
    state: TableState | None = None
    spot: Spot | None = None
    missing: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)
    advice: Advice | None = None
    my_turn: bool | None = None
    final: bool = False               # True = advice for my current turn
    latency_ms: float | None = None   # my turn started -> advice ready
    read_ms: float = 0.0
    message: str = ""
    session_chips: float = 0.0
    session_bb: float = 0.0
    session_hands: int = 0


def _spot_key(s: Spot | None):
    if s is None:
        return None
    return (tuple(s.hero), tuple(s.board), round(s.pot, 2), round(s.to_call, 2), round(s.hero_stack, 2),
            s.position, s.n_opponents, s.villain_position, s.pot_type, s.hero_aggressor, s.bb)


class Advisor:
    def __init__(self, cfg: dict, profile: Profile, capturer, on_update=None, db: HandDB | None = None,
                 session: str | None = None):
        self.cfg = cfg
        self.live = cfg.get("live", {})
        self.p = profile
        self.cap = capturer
        self.reader = TableReader(profile)
        self.engine = Engine(cfg)
        self.tracker = HandTracker(profile, self.live, cfg.get("engine", {}))
        self.on_update = on_update or (lambda u: None)
        self.db = db
        self.session = session or time.strftime("%Y-%m-%d %H:%M")
        self.auto = bool(self.live.get("auto", True))
        self._force = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_key = None
        self._last_advice: Advice | None = None
        self._was_turn = False
        self._turn_t0: float | None = None
        self._turn_logged = False
        self._turn_latency: float | None = None
        self._last_unknown_save = 0.0
        self.session_chips = 0.0
        self.session_bb = 0.0
        self.session_hands = 0
        self.last_update = Update()

    # ------------------------------------------------------------ control
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="advisor")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.tracker.close()
        self._log_hands()

    def force_read(self):
        self._force.set()

    def toggle_auto(self) -> bool:
        self.auto = not self.auto
        return self.auto

    def mark_deviation(self):
        self.tracker.mark_deviation()

    def cycle_opponents(self) -> int | None:
        cur = self.tracker.manual_opponents
        nxt = None if cur == 8 else (1 if cur is None else cur + 1)
        self.tracker.manual_opponents = nxt
        self._last_key = None
        self.force_read()
        return nxt

    def set_bb(self, bb: float):
        self.tracker.bb = float(bb)
        self._last_key = None
        self.force_read()

    def set_position(self, pos: str | None):
        self.tracker.manual_position = pos
        self._last_key = None
        self.force_read()

    # ------------------------------------------------------------- loop
    def _run(self):
        poll = float(self.live.get("turn_poll_s", 0.1))
        interval = float(self.live.get("read_interval_s", 0.5))
        last_full = 0.0
        while not self._stop.is_set():
            t0 = time.time()
            try:
                frame = self.cap.grab()
            except Exception as e:  # capture hiccup: report, keep going
                self.on_update(Update(message=f"capture problem: {e}"))
                time.sleep(1)
                continue
            age = self.cap.frame_age_ms() / 1000 if hasattr(self.cap, "frame_age_ms") else 0.0
            turn = self.reader.is_my_turn(frame)
            turn_started = bool(turn) and not self._was_turn
            if turn_started:
                self._turn_t0 = t0 - age
                self._turn_logged = False
            if not turn:
                self._turn_t0 = None
            self._was_turn = bool(turn)
            forced = self._force.is_set()
            if forced or turn_started or (self.auto and t0 - last_full >= interval):
                self._force.clear()
                last_full = t0
                self._full(frame, turn, forced or turn_started)
            time.sleep(max(0.0, poll - (time.time() - t0)))

    def _full(self, frame, turn, urgent):
        st = self.reader.read(frame)
        u = Update(state=st, my_turn=turn, read_ms=st.ms)
        if not st.frame_ok:
            u.message = st.message
            self._emit(u)
            return
        events = self.tracker.update(st)
        if "hand_end" in events or "new_hand" in events:
            self._log_hands()
        spot, missing, info = self.tracker.build_spot(st)
        u.spot, u.missing, u.info = spot, missing, info
        if spot is not None:
            spot.session_result = self.session_chips
            key = _spot_key(spot)
            if key != self._last_key or self._last_advice is None:
                try:
                    self._last_advice = self.engine.decide(spot)
                    self._last_key = key
                except Exception as e:
                    u.message = f"engine: {e}"
                    self._last_advice = None
            u.advice = self._last_advice
        else:
            self._last_advice, self._last_key = None, None
        if turn and self._turn_t0 is not None and u.advice is not None:
            u.final = True
            if not self._turn_logged:  # time to the FIRST advice of this turn
                self._turn_latency = (time.time() - self._turn_t0) * 1000
            u.latency_ms = self._turn_latency
            h = self.tracker.hand
            if h and not self._turn_logged:
                h.saw_my_turn = True
                h.advice.append({"street": spot.street, "label": u.advice.label(), "action": u.advice.action,
                                 "equity": round(u.advice.equity.equity, 3) if u.advice.equity else None,
                                 "ms": round(u.latency_ms)})
                self._turn_logged = True
        if self.live.get("save_unknown_frames", True) and any(r.status == "?" for r in st.fields.values()):
            self._save_unknown(frame)
        self._emit(u)

    def _emit(self, u: Update):
        u.session_chips, u.session_bb, u.session_hands = self.session_chips, self.session_bb, self.session_hands
        self.last_update = u
        self.on_update(u)

    def _log_hands(self):
        for hand, end in self.tracker.pop_finished():
            if hand.start_stack is not None and end is not None:
                res = end - hand.start_stack
                self.session_chips += res
                if self.tracker.bb:
                    self.session_bb += res / self.tracker.bb
                self.session_hands += 1
            if self.db is not None:
                self.db.add_hand(hand, end, session=self.session, preset=self.p.name, bb=self.tracker.bb)

    def _save_unknown(self, frame):
        """Keep frames with '?' so they can be taught later (in the background)."""
        now = time.time()
        if now - self._last_unknown_save < float(self.live.get("unknown_save_every_s", 5)):
            return
        self._last_unknown_save = now
        d: Path = self.p.dir / "captures"
        d.mkdir(parents=True, exist_ok=True)
        name = d / (time.strftime("%Y%m%d_%H%M%S") + "_unknown.png")
        img = frame.copy()
        threading.Thread(target=cv2.imwrite, args=(str(name), img), daemon=True).start()
