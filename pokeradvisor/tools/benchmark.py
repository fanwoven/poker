"""Reader benchmark: accuracy per field and milliseconds per read, on YOUR
saved screenshots with YOUR true values.

  python -m pokeradvisor.tools.benchmark <preset>

Uses profiles/<preset>/samples/*.png and profiles/<preset>/samples/labels.csv
(make that file with:  python -m pokeradvisor.tools.truth <preset>).

labels.csv columns:  file,hole,board,pot,stack,call,my_turn,button
  cards like AsKd, '-' = not on screen, '?' = you're not sure (skipped).
"""
from __future__ import annotations

import csv
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2

from ..engine.cards import names
from ..profile import Profile
from ..vision.reader import TableReader, TableState, parse_amount, parse_button

FIELDS = ["hole", "board", "pot", "stack", "call", "my_turn", "button"]


def read_fields(reader: TableReader, st: TableState) -> dict[str, tuple[str, str]]:
    """Reader output per benchmark field: (status, text). status ok / none / ?"""
    p = reader.p
    out = {}
    # cards: concatenation, '?' if any visible card unknown
    for fld, slots in (("hole", ["hole1", "hole2"]), ("board", [f"board{i}" for i in range(1, 6)])):
        rs = [st.get(s) for s in slots if s in p.regions]
        if any(r.status == "?" for r in rs):
            out[fld] = ("?", "")
        else:
            txt = "".join(names([r.value]) for r in rs if r.ok)
            out[fld] = ("ok", txt) if txt else ("none", "-")
    for fld in ("pot", "stack"):
        r = st.get(fld)
        out[fld] = (r.status, r.text if r.ok else "")
    b = st.get("button")
    out["button"] = (b.status, b.text if b.ok else "")
    if b.ok:
        kind, amt, _ = parse_button(b.text, p.abbreviations)
        out["call"] = ("ok", f"{amt:g}") if amt is not None else ("?", "")
    else:
        out["call"] = (b.status, "")
    t = st.get("turn")
    out["my_turn"] = ("ok", "yes" if t.value == "on" else "no") if t.ok else (t.status, "")
    return out


def same(fld: str, truth: str, got: str, abbreviations: dict) -> bool:
    if fld in ("pot", "stack", "call"):
        a, _ = parse_amount(truth, abbreviations) if truth not in ("-", "") else (None, False)
        b, _ = parse_amount(got, abbreviations) if fld != "call" else (float(got) if got else None, False)
        return a is not None and b is not None and abs(a - b) < 1e-6 * max(1, abs(a))
    if fld == "button":
        return " ".join(truth.upper().split()) == " ".join(got.upper().split())
    return truth.replace(" ", "") == got.replace(" ", "")


def score(rows: list[tuple[dict, dict]], abbreviations: dict) -> dict:
    """rows: (truth row, reader fields) -> per field counts."""
    res = defaultdict(lambda: {"right": 0, "wrong": 0, "unknown": 0, "skipped": 0, "wrong_examples": []})
    for truth, got in rows:
        for fld in FIELDS:
            t = (truth.get(fld) or "").strip()
            if fld not in got or t in ("", "?"):
                res[fld]["skipped"] += 1
                continue
            status, text = got[fld]
            if status == "?":
                res[fld]["unknown"] += 1
            elif status == "none":
                if t == "-":
                    res[fld]["right"] += 1
                else:
                    res[fld]["wrong"] += 1
                    res[fld]["wrong_examples"].append((truth.get("file"), t, "-"))
            elif t != "-" and same(fld, t, text, abbreviations):
                res[fld]["right"] += 1
            else:
                res[fld]["wrong"] += 1
                res[fld]["wrong_examples"].append((truth.get("file"), t, text))
    return res


def report(res: dict, times: list[float]) -> str:
    lines = [f"{'field':10} {'right':>6} {'wrong':>6} {'?':>6} {'skip':>6}"]
    total_wrong = 0
    for fld in FIELDS:
        r = res.get(fld)
        if not r:
            continue
        total_wrong += r["wrong"]
        lines.append(f"{fld:10} {r['right']:6} {r['wrong']:6} {r['unknown']:6} {r['skipped']:6}")
    for fld in FIELDS:
        for f, t, g in (res.get(fld) or {}).get("wrong_examples", [])[:5]:
            lines.append(f"  WRONG {fld} in {f}: true {t!r}, read {g!r}")
    if times:
        ts = sorted(times)
        lines.append(f"read time per screenshot: median {ts[len(ts)//2]:.1f} ms, worst {ts[-1]:.1f} ms")
    lines.append("RESULT: " + ("0 wrong values" if total_wrong == 0 else f"{total_wrong} WRONG values"))
    return "\n".join(lines)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    prof = Profile.load(argv[0])
    sdir = prof.dir / "samples"
    lab = sdir / "labels.csv"
    if not lab.exists():
        print(f"missing {lab}. Make it with: python -m pokeradvisor.tools.truth {prof.name}")
        return 2
    reader = TableReader(prof)
    rows, times = [], []
    with open(lab, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            img = cv2.imread(str(sdir / row["file"]))
            if img is None:
                print(f"can't open {row['file']}")
                continue
            reader._cache.clear()  # measure a full read, not a cached one
            t0 = time.perf_counter()
            st = reader.read(img)
            times.append((time.perf_counter() - t0) * 1000)
            rows.append((row, read_fields(reader, st)))
    print(f"preset {prof.name}: {len(rows)} screenshots, {reader.store.count()} learned templates\n")
    print(report(score(rows, prof.abbreviations), times))
    return 0


if __name__ == "__main__":
    sys.exit(main())
