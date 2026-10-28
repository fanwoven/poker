"""Make the test set for the benchmark: pick screenshots, and write down the TRUE
values for each one (the reader's answer is filled in to save typing; check
every field against the zoomed picture next to it!).

  python -m pokeradvisor.tools.truth <preset>             # 20 screenshots from captures/
  python -m pokeradvisor.tools.truth <preset> --count 30

Writes profiles/<preset>/samples/*.png and samples/labels.csv. Then run:
  python -m pokeradvisor.tools.benchmark <preset>
Field format: cards AsKd ('-' none), numbers as shown (1,250 or 5.58M),
call = amount on the Call button (0 for Check, empty if no button),
my_turn yes/no. Use ? if you can't tell.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys

import cv2

from ..profile import Profile
from ..vision.reader import TableReader
from .benchmark import FIELDS, read_fields
from .teach import to_pixmap

FIELD_REGIONS = {"hole": ["hole1", "hole2"], "board": [f"board{i}" for i in range(1, 6)],
                 "pot": ["pot"], "stack": ["stack"], "call": ["button"], "button": ["button"], "my_turn": ["turn"]}


def pick(profile: Profile, count: int):
    caps = sorted((profile.dir / "captures").glob("*.png"))
    sdir = profile.dir / "samples"
    sdir.mkdir(parents=True, exist_ok=True)
    have = {p.name for p in sdir.glob("*.png")}
    caps = [c for c in caps if c.name not in have]
    if not caps:
        return []
    step = max(1, len(caps) // count)
    chosen = caps[::step][:count]
    for c in chosen:
        shutil.copy(c, sdir / c.name)
    return [sdir / c.name for c in chosen]


def run_gui(profile: Profile, files):
    from PySide6.QtWidgets import (QApplication, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                                   QPushButton, QVBoxLayout, QWidget)
    app = QApplication.instance() or QApplication(sys.argv)
    reader = TableReader(profile)
    lab_path = profile.dir / "samples" / "labels.csv"
    rows = {}
    if lab_path.exists():
        with open(lab_path, newline="", encoding="utf-8") as f:
            rows = {r["file"]: r for r in csv.DictReader(f)}

    class Win(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(f"True values: {profile.name}")
            self.i = 0
            self.title = QLabel()
            self.form = QFormLayout()
            self.edits, self.zooms = {}, {}
            for fld in FIELDS:
                e = QLineEdit()
                e.setMinimumWidth(160)
                z = QLabel()
                box = QHBoxLayout()
                box.addWidget(z)
                box.addWidget(e)
                w = QWidget()
                w.setLayout(box)
                self.form.addRow(fld, w)
                self.edits[fld], self.zooms[fld] = e, z
            nxt = QPushButton("Save && next")
            nxt.clicked.connect(self.next)
            lay = QVBoxLayout(self)
            lay.addWidget(self.title)
            lay.addWidget(QLabel("Check EVERY field against the zoomed picture. '-' = nothing, '?' = can't tell."))
            lay.addLayout(self.form)
            lay.addWidget(nxt)
            self.load()

        def load(self):
            f = files[self.i]
            img = cv2.imread(str(f))
            self.title.setText(f"<b>{self.i + 1}/{len(files)}</b>  {f.name}")
            got = read_fields(reader, reader.read(img))
            old = rows.get(f.name, {})
            for fld in FIELDS:
                st, txt = got.get(fld, ("?", ""))
                guess = txt if st == "ok" else ("-" if st == "none" else "")
                self.edits[fld].setText(old.get(fld, guess))
                crops = [profile.regions[r].crop(img) for r in FIELD_REGIONS[fld] if r in profile.regions]
                crops = [c for c in crops if c.size]
                if crops:
                    h = max(c.shape[0] for c in crops)
                    strip = cv2.hconcat([cv2.copyMakeBorder(c, 0, h - c.shape[0], 0, 4, cv2.BORDER_CONSTANT)
                                         for c in crops])
                    self.zooms[fld].setPixmap(to_pixmap(strip, min(3.0, 400 / strip.shape[1])))

        def next(self):
            f = files[self.i]
            rows[f.name] = {"file": f.name, **{fld: self.edits[fld].text().strip() for fld in FIELDS}}
            with open(lab_path, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, ["file"] + FIELDS)
                w.writeheader()
                for r in rows.values():
                    w.writerow(r)
            self.i += 1
            if self.i >= len(files):
                self.title.setText(f"Done. Now run: python -m pokeradvisor.tools.benchmark {profile.name}")
                return
            self.load()

    w = Win()
    w.show()
    return app, w


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write the true values for benchmark screenshots.")
    ap.add_argument("preset")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--all-samples", action="store_true", help="edit all existing samples again")
    a = ap.parse_args(argv)
    prof = Profile.load(a.preset)
    files = sorted((prof.dir / "samples").glob("*.png")) if a.all_samples else pick(prof, a.count)
    if not files:
        sys.exit("No new screenshots. Run the collect tool first (or use --all-samples).")
    app, _w = run_gui(prof, files)
    app.exec()


if __name__ == "__main__":
    main()
