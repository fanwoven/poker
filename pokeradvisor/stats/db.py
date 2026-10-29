"""Hand history database (SQLite file: data/hands.sqlite).

One row per hand: result in chips and big blinds, position, starting hand,
board, the advice shown on each of my turns, and whether I followed it.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from ..engine.cards import names
from ..engine.ranges import hand_class

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "hands.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS hands (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  hand_id TEXT, session TEXT, preset TEXT, ts REAL,
  position TEXT, n_players INTEGER, hole TEXT, hand_class TEXT, board TEXT,
  start_stack REAL, end_stack REAL, result REAL, bb REAL, result_bb REAL,
  advice TEXT, followed INTEGER, saw_turn INTEGER, note TEXT
);
"""


class HandDB:
    def __init__(self, path: Path | str = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path), check_same_thread=False)
        self.con.executescript(SCHEMA)

    def add(self, *, hand_id, session, preset, hole, board, position, n_players, start_stack,
            end_stack, bb, advice, followed, saw_turn, ts=None, note=""):
        result = (end_stack - start_stack) if (start_stack is not None and end_stack is not None) else None
        rbb = result / bb if (result is not None and bb) else None
        self.con.execute(
            "INSERT INTO hands (hand_id, session, preset, ts, position, n_players, hole, hand_class, board, "
            "start_stack, end_stack, result, bb, result_bb, advice, followed, saw_turn, note) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (hand_id, session, preset, ts or time.time(), position, n_players, names(hole),
             hand_class(*hole), names(board), start_stack, end_stack, result, bb, rbb,
             json.dumps(advice), int(bool(followed)), int(bool(saw_turn)), note))
        self.con.commit()

    def add_hand(self, hand, end_stack, *, session, preset, bb):
        self.add(hand_id=hand.hand_id, session=session, preset=preset, hole=hand.hole, board=hand.board,
                 position=hand.position, n_players=hand.n_players, start_stack=hand.start_stack,
                 end_stack=end_stack, bb=bb, advice=hand.advice, followed=not hand.deviated,
                 saw_turn=hand.saw_my_turn, ts=hand.start_time)

    def rows(self, session: str | None = None, preset: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM hands WHERE result_bb IS NOT NULL", []
        if session:
            q += " AND session = ?"
            args.append(session)
        if preset:
            q += " AND preset = ?"
            args.append(preset)
        cur = self.con.execute(q + " ORDER BY ts", args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def sessions(self) -> list[str]:
        return [r[0] for r in self.con.execute("SELECT session FROM hands GROUP BY session ORDER BY MIN(ts)")]


@dataclass
class WinRate:
    hands: int
    bb100: float
    low: float           # 95% range
    high: float
    total_bb: float
    total_chips: float

    def verdict(self) -> str:
        if self.hands == 0:
            return "No hands yet."
        if self.hands < 30:
            return f"Only {self.hands} hands: far too few to know anything yet."
        if self.low < 0 < self.high:
            return (f"Not enough hands to know yet: your real win rate is somewhere between "
                    f"{self.low:+.0f} and {self.high:+.0f} bb/100 (95% sure). Poker needs thousands of hands.")
        word = "winning" if self.low > 0 else "losing"
        return f"After {self.hands} hands you are {word} (95% sure): {self.low:+.0f} to {self.high:+.0f} bb/100."


def win_rate(rows: list[dict]) -> WinRate:
    xs = [r["result_bb"] for r in rows if r["result_bb"] is not None]
    n = len(xs)
    if n == 0:
        return WinRate(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    half = 1.96 * sd / math.sqrt(n) * 100 if n > 1 else float("inf")
    return WinRate(n, m * 100, m * 100 - half, m * 100 + half, sum(xs),
                   sum(r["result"] or 0 for r in rows))
