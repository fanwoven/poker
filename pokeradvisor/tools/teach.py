"""Teach screen: label the card symbols, digits and "my turn" looks the reader
doesn't know yet, all in one batch, AFTER playing.

  python -m pokeradvisor.tools.teach <preset>
  python -m pokeradvisor.tools.teach <preset> --ai      # local AI suggestions (Ollama)

Each unknown symbol is shown ONCE (look-alikes are grouped). Type what it is
and press Enter to go to the next one:
  card rank : 2 3 4 5 6 7 8 9 T J Q K A   (10 is fine too)
  suit      : s h d c   (spades hearts diamonds clubs)
  character : the digit / letter / , / .   or  _  for junk to ignore
  'turn' box: on (my turn) / off (not my turn)
Leave a box empty to skip it. Then click "Save & rescan".
"""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

import cv2
import numpy as np

from ..config import load_config
from ..profile import Profile
from ..vision.learn import Unknown, apply_label, cluster, label_is_valid, unknowns_in_frame
from ..vision.reader import TableReader

HINTS = {
    "rank": "rank: 2-9 T J Q K A",
    "suit": "suit: s h d c",
    "char": "character, or _ to ignore",
}


def look_hint(group: str) -> str:
    if group == "ind_turn":
        return "on = my turn, off = not my turn"
    if group.endswith("_cards"):
        return "in = still in the hand, out = folded/empty"
    if group.endswith("_dealer"):
        return "yes = dealer button here, no = not here"
    return "a short word"


def scan(reader: TableReader, files: list[Path], progress=print) -> list[Unknown]:
    items: list[Unknown] = []
    for i, f in enumerate(files):
        img = cv2.imread(str(f))
        if img is None:
            continue
        items += unknowns_in_frame(reader, img)
        if i % 25 == 0:
            progress(f"  scanned {i + 1}/{len(files)} screenshots, {len(items)} unknown symbols")
    return cluster(items)


def frames_for(profile: Profile, limit: int = 500) -> list[Path]:
    files = []
    for sub in ("captures", "samples"):
        d = profile.dir / sub
        if d.exists():
            files += sorted(d.glob("*.png"))
    if (profile.dir / "calibration.png").exists():
        files.append(profile.dir / "calibration.png")
    return files[-limit:]


def to_pixmap(img: np.ndarray, scale: float):
    from PySide6.QtGui import QImage, QPixmap
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    h, w = rgb.shape[:2]
    return QPixmap.fromImage(QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy())


def run_gui(reader: TableReader, files: list[Path], suggester=None):
    from PySide6.QtCore import Qt, QTimer, Signal, QObject
    from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                                   QScrollArea, QVBoxLayout, QWidget)

    app = QApplication.instance() or QApplication(sys.argv)

    class Bridge(QObject):
        suggested = Signal(int, str)

    class Win(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(f"Teach: {reader.p.name}")
            self.bridge = Bridge()
            self.bridge.suggested.connect(self.on_suggest)
            self.info = QLabel()
            self.info.setWordWrap(True)
            self.rows_box = QVBoxLayout()
            inner = QWidget()
            inner.setLayout(self.rows_box)
            self.scroll = QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setWidget(inner)
            self.save_btn = QPushButton("Save && rescan")
            self.save_btn.clicked.connect(self.save)
            lay = QVBoxLayout(self)
            lay.addWidget(self.info)
            lay.addWidget(self.scroll, 1)
            lay.addWidget(self.save_btn)
            self.items: list[Unknown] = []
            self.edits: list[QLineEdit] = []
            self.resize(900, 800)
            QTimer.singleShot(0, self.rescan)

        def rescan(self):
            self.info.setText("Scanning screenshots...")
            app.processEvents()
            self.items = scan(reader, files)[:200]
            self.build()

        def build(self):
            while self.rows_box.count():
                w = self.rows_box.takeAt(0).widget()
                if w:
                    w.deleteLater()
            self.edits = []
            n = len(self.items)
            self.info.setText(
                f"<b>{n} unknown symbol(s)</b> in {len(files)} screenshots. "
                f"Learned so far: {reader.store.count()} templates. "
                "Type what each one is, Enter = next. Empty = skip." if n else
                f"<b>Nothing unknown!</b> {reader.store.count()} templates learned. "
                "Next: check accuracy with the truth + benchmark tools.")
            for i, it in enumerate(self.items):
                row = QWidget()
                h = QHBoxLayout(row)
                ctx = QLabel()
                ctx.setPixmap(to_pixmap(it.crop, max(1.0, min(4.0, 120 / max(it.crop.shape[:2])))))
                h.addWidget(ctx)
                if it.glyph is not None:
                    g = QLabel()
                    g.setPixmap(to_pixmap(it.glyph.thumb, 3))
                    h.addWidget(g)
                hint = HINTS.get(it.kind) or look_hint(it.group)
                h.addWidget(QLabel(f"{it.group}\n{it.region}, seen {it.count}x\n{hint}"), 1)
                e = QLineEdit()
                e.setMaximumWidth(120)
                e.returnPressed.connect(lambda i=i: self.next(i))
                h.addWidget(e)
                self.edits.append(e)
                self.rows_box.addWidget(row)
            self.rows_box.addStretch(1)
            if self.edits:
                self.edits[0].setFocus()
            if suggester is not None:
                threading.Thread(target=self.suggest_all, daemon=True).start()

        def suggest_all(self):
            items = list(self.items)
            for i, it in enumerate(items):
                if it.glyph is None:
                    continue
                lab, _dt = suggester.suggest(it.kind, it.glyph.thumb)
                if lab:
                    self.bridge.suggested.emit(i, lab)

        def on_suggest(self, i, lab):
            if i < len(self.edits) and not self.edits[i].text():
                self.edits[i].setPlaceholderText(f"AI: {lab}  (Enter=accept)")
                self.edits[i].setProperty("suggestion", lab)

        def next(self, i):
            e = self.edits[i]
            if not e.text() and e.property("suggestion"):
                e.setText(e.property("suggestion"))
            if i + 1 < len(self.edits):
                self.edits[i + 1].setFocus()
                self.scroll.ensureWidgetVisible(self.edits[i + 1])

        def save(self):
            bad = []
            for it, e in zip(self.items, self.edits):
                lab = e.text().strip()
                if not lab:
                    continue
                if not label_is_valid(it.kind, lab):
                    bad.append(f"{it.group}: '{lab}'")
                    continue
                apply_label(reader, it, lab)
            reader.store.save()
            if bad:
                self.info.setText("Not saved (bad label): " + ", ".join(bad[:6]))
                return
            self.rescan()

    w = Win()
    w.show()
    return app, w


def main(argv=None):
    ap = argparse.ArgumentParser(description="Label unknown symbols in one batch.")
    ap.add_argument("preset")
    ap.add_argument("--ai", action="store_true", help="ask the local Ollama vision model for suggestions")
    ap.add_argument("--tesseract", action="store_true", help="ask Tesseract for digit suggestions")
    a = ap.parse_args(argv)
    prof = Profile.load(a.preset)
    reader = TableReader(prof)
    files = frames_for(prof)
    if not files:
        sys.exit(f"No screenshots yet. Run: python -m pokeradvisor.tools.collect {prof.name}")
    sug = None
    if a.ai:
        from ..vision.suggest import OllamaSuggester
        cfg = load_config().get("teach", {})
        sug = OllamaSuggester(cfg.get("ollama_model", "qwen2.5vl:7b"), cfg.get("ollama_url", "http://127.0.0.1:11434"))
        if not sug.available():
            print(f"Ollama model {sug.model} not found; continuing without AI suggestions.")
            sug = None
    elif a.tesseract:
        from ..vision.suggest import TesseractSuggester
        sug = TesseractSuggester() if TesseractSuggester().available() else None
    app, _w = run_gui(reader, files, sug)
    app.exec()


if __name__ == "__main__":
    main()
