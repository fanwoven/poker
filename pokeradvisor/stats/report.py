"""Results report in the terminal.

  python -m pokeradvisor.stats.report              # all hands
  python -m pokeradvisor.stats.report --last       # last session only
  python -m pokeradvisor.stats.report --hands 20   # also list the last 20 hands
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime

from .db import HandDB, win_rate

POS_ORDER = ["UTG", "UTG1", "UTG2", "LJ", "HJ", "CO", "BTN", "SB", "BB", None]


def ascii_graph(values: list[float], width: int = 60, height: int = 12) -> str:
    if len(values) < 2:
        return "  (graph needs at least 2 hands)"
    step = max(1, len(values) // width)
    pts = values[::step][:width]
    lo, hi = min(pts + [0]), max(pts + [0])
    span = (hi - lo) or 1
    rows = []
    for r in range(height, -1, -1):
        level = lo + span * r / height
        line = "".join("*" if abs(v - level) <= span / height / 2 else
                       ("-" if abs(level) <= span / height / 2 else " ") for v in pts)
        rows.append(f"{level:+9.1f} |{line}")
    return "\n".join(rows) + f"\n          hands 1 .. {len(values)}  (big blinds won, running total)"


def report(db: HandDB, session: str | None = None, last_hands: int = 0, preset: str | None = None) -> str:
    rows = db.rows(session, preset)
    out = []
    wr = win_rate(rows)
    out.append(f"Hands: {wr.hands}   Result: {wr.total_chips:+,.0f} chips = {wr.total_bb:+.1f} BB")
    if wr.hands:
        out.append(f"Win rate: {wr.bb100:+.1f} bb/100   95% range: {wr.low:+.0f} .. {wr.high:+.0f}")
    out.append(wr.verdict())
    out.append("")
    out.append(f"{'position':9} {'hands':>6} {'BB won':>8} {'bb/100':>8}")
    by = defaultdict(list)
    for r in rows:
        by[r["position"]].append(r)
    for p in POS_ORDER:
        if p in by:
            w = win_rate(by[p])
            out.append(f"{p or '?':9} {w.hands:6} {w.total_bb:+8.1f} {w.bb100:+8.1f}")
    out.append("")
    fol = [r for r in rows if r["followed"]]
    dev = [r for r in rows if not r["followed"]]
    for name, rs in (("followed advice", fol), ("did NOT follow", dev)):
        w = win_rate(rs)
        out.append(f"{name:16} {w.hands:6} hands {w.total_bb:+8.1f} BB  {w.bb100:+8.1f} bb/100")
    out.append("")
    run, total = [], 0.0
    for r in rows:
        total += r["result_bb"]
        run.append(total)
    out.append(ascii_graph(run))
    if last_hands:
        out.append("")
        out.append("Last hands:")
        for r in rows[-last_hands:]:
            adv = " / ".join(f"{a.get('street', '')[:1].upper()}:{a.get('label', '')}" for a in json.loads(r["advice"] or "[]"))
            t = datetime.fromtimestamp(r["ts"]).strftime("%H:%M")
            out.append(f"  {t} {r['position'] or '?':4} {r['hole']} {r['board'] or '':10} "
                       f"{r['result_bb']:+7.1f} BB {'' if r['followed'] else '(deviated) '}{adv}")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Poker results report.")
    ap.add_argument("--last", action="store_true", help="only the last session")
    ap.add_argument("--hands", type=int, default=0, help="list the last N hands")
    ap.add_argument("--preset", default=None)
    a = ap.parse_args(argv)
    db = HandDB()
    ses = db.sessions()[-1] if a.last and db.sessions() else None
    print(report(db, ses, a.hands, a.preset))


if __name__ == "__main__":
    main()
