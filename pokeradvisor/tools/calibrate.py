"""Calibration: draw boxes on a screenshot of your table and save a preset.

  python -m pokeradvisor.tools.calibrate <preset>                 # take a screenshot in 5 s
  python -m pokeradvisor.tools.calibrate <preset> --image shot.png
  python -m pokeradvisor.tools.calibrate <preset> --delay 10

How to use the window:
  1. Click a box name on the left (it starts at the first one).
  2. Drag a rectangle on the screenshot with the LEFT mouse button.
     It jumps to the next box automatically.
  3. Mouse wheel = zoom, RIGHT button drag = move the picture.
  4. Tick "It is my turn in this screenshot" if it is (teaches the turn box).
  5. Click Save.
Do this BEFORE playing. Make a new preset per app / table size.
"""
from __future__ import annotations

import argparse
import sys
import time

import cv2
import numpy as np

from ..profile import MAX_SEATS, REGION_SPECS, Profile, list_profiles
from ..vision.templates import Look, TemplateStore

KIND_COLORS = {"card": (255, 200, 0), "number": (0, 220, 255), "text": (255, 120, 255), "indicator": (120, 255, 120)}


def grab_screenshot(delay: float) -> np.ndarray:
    from ..capture import make_capturer
    from ..config import load_config
    cap = make_capturer(load_config())
    cap.start()  # first time on Wayland: the system asks what to share
    for i in range(int(delay), 0, -1):
        print(f"  screenshot in {i} s ... switch to the poker table", flush=True)
        time.sleep(1)
    img = cap.grab().copy()
    cap.close()
    return img


def run_gui(profile: Profile, img: np.ndarray):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QBrush, QColor, QImage, QPen, QPixmap
    from PySide6.QtWidgets import (QApplication, QCheckBox, QGraphicsScene, QGraphicsView, QHBoxLayout,
                                   QLabel, QListWidget, QListWidgetItem, QPushButton, QSpinBox,
                                   QVBoxLayout, QWidget)

    app = QApplication.instance() or QApplication(sys.argv)

    class View(QGraphicsView):
        def __init__(self, win):
            super().__init__()
            self.win = win
            self.setScene(QGraphicsScene())
            h, w = img.shape[:2]
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            self.qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
            self.scene().addPixmap(QPixmap.fromImage(self.qimg))
            self.setDragMode(QGraphicsView.NoDrag)
            self.start = None
            self.rubber = None
            self.pan = None
            self.items = {}

        def wheelEvent(self, e):
            f = 1.25 if e.angleDelta().y() > 0 else 0.8
            self.scale(f, f)

        def mousePressEvent(self, e):
            if e.button() == Qt.RightButton:
                self.pan = e.position()
                return
            if e.button() == Qt.LeftButton:
                self.start = self.mapToScene(e.position().toPoint())
                pen = QPen(QColor(255, 255, 255), 0, Qt.DashLine)
                self.rubber = self.scene().addRect(QRectF(self.start, self.start), pen)

        def mouseMoveEvent(self, e):
            if self.pan is not None:
                d = e.position() - self.pan
                self.pan = e.position()
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
                return
            if self.start is not None and self.rubber is not None:
                self.rubber.setRect(QRectF(self.start, self.mapToScene(e.position().toPoint())).normalized())

        def mouseReleaseEvent(self, e):
            if e.button() == Qt.RightButton:
                self.pan = None
                return
            if self.start is None:
                return
            r = self.rubber.rect()
            self.scene().removeItem(self.rubber)
            self.rubber, self.start = None, None
            if r.width() >= 3 and r.height() >= 3:
                self.win.box_drawn(int(r.x()), int(r.y()), int(r.width()), int(r.height()))

        def draw_boxes(self, regions):
            for it in self.items.values():
                for x in it:
                    self.scene().removeItem(x)
            self.items = {}
            for name, reg in regions.items():
                c = QColor(*KIND_COLORS.get(reg.kind, (255, 255, 255)))
                rect = self.scene().addRect(QRectF(reg.x, reg.y, reg.w, reg.h), QPen(c, 0))
                c2 = QColor(c)
                c2.setAlpha(40)
                rect.setBrush(QBrush(c2))
                txt = self.scene().addSimpleText(name)
                txt.setBrush(QBrush(c))
                txt.setPos(reg.x, reg.y - 14)
                self.items[name] = (rect, txt)

    class Win(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(f"Calibrate preset: {profile.name}")
            self.view = View(self)
            self.list = QListWidget()
            self.help = QLabel()
            self.help.setWordWrap(True)
            self.seats = QSpinBox()
            self.seats.setRange(2, MAX_SEATS)
            self.seats.setValue(profile.seats)
            self.seats.valueChanged.connect(self.fill_list)
            self.my_turn = QCheckBox("It is my turn in this screenshot")
            self.save_btn = QPushButton("Save preset")
            self.save_btn.clicked.connect(self.save)
            self.del_btn = QPushButton("Delete selected box")
            self.del_btn.clicked.connect(self.delete)
            self.status = QLabel()
            left = QVBoxLayout()
            left.addWidget(QLabel("Players at a full table:"))
            left.addWidget(self.seats)
            left.addWidget(QLabel("Boxes (* = required):"))
            left.addWidget(self.list, 1)
            left.addWidget(self.help)
            left.addWidget(self.my_turn)
            left.addWidget(self.del_btn)
            left.addWidget(self.save_btn)
            left.addWidget(self.status)
            lw = QWidget()
            lw.setLayout(left)
            lw.setFixedWidth(330)
            lay = QHBoxLayout(self)
            lay.addWidget(lw)
            lay.addWidget(self.view, 1)
            self.list.currentRowChanged.connect(self.show_help)
            self.fill_list()
            self.view.draw_boxes(profile.regions)
            self.resize(1500, 900)

        def names(self):
            n_opp = self.seats.value() - 1
            out = []
            for name, (kind, _, req) in REGION_SPECS.items():
                if name.startswith("seat") and int(name[4]) > n_opp:
                    continue
                out.append(name)
            return out

        def fill_list(self):
            cur = self.list.currentRow()
            self.list.clear()
            for n in self.names():
                req = REGION_SPECS[n][2]
                done = "✔ " if n in profile.regions else "   "
                QListWidgetItem(f"{done}{n}{' *' if req else ''}", self.list)
            self.list.setCurrentRow(max(0, cur))
            missing = profile.missing_required()
            self.status.setText("Missing: " + ", ".join(missing) if missing else "All required boxes done.")

        def current(self):
            row = self.list.currentRow()
            names = self.names()
            return names[row] if 0 <= row < len(names) else None

        def show_help(self, _row):
            n = self.current()
            if n:
                self.help.setText(f"<b>{n}</b>: {REGION_SPECS[n][1]}")

        def box_drawn(self, x, y, w, h):
            n = self.current()
            if not n:
                return
            profile.set_region(n, x, y, w, h)
            self.view.draw_boxes(profile.regions)
            row = self.list.currentRow()
            self.fill_list()
            self.list.setCurrentRow(min(row + 1, self.list.count() - 1))

        def delete(self):
            n = self.current()
            if n and n in profile.regions:
                del profile.regions[n]
                self.view.draw_boxes(profile.regions)
                self.fill_list()

        def save(self):
            profile.seats = self.seats.value()
            profile.frame_size = (img.shape[1], img.shape[0])
            profile.save()
            cv2.imwrite(str(profile.dir / "calibration.png"), img)
            if "turn" in profile.regions:
                store = TemplateStore(profile.dir / "templates")
                lk = Look.from_crop(profile.regions["turn"].crop(img))
                store.add_look("ind_turn", "on" if self.my_turn.isChecked() else "off", lk)
                store.save()
            self.status.setText(f"Saved to {profile.dir}")

    w = Win()
    w.show()
    return app, w


def main(argv=None):
    ap = argparse.ArgumentParser(description="Draw the boxes for a table preset.")
    ap.add_argument("preset", help="a short name, e.g. wsop6")
    ap.add_argument("--image", help="use this screenshot instead of taking one")
    ap.add_argument("--delay", type=float, default=5, help="seconds before the screenshot")
    a = ap.parse_args(argv)
    try:
        profile = Profile.load(a.preset)
        print(f"Editing existing preset {a.preset!r}")
    except FileNotFoundError:
        profile = Profile(a.preset)
        print(f"New preset {a.preset!r} (existing: {', '.join(list_profiles()) or 'none'})")
    if a.image:
        img = cv2.imread(a.image)
        if img is None:
            sys.exit(f"can't open {a.image}")
    else:
        img = grab_screenshot(a.delay)
    app, _w = run_gui(profile, img)
    app.exec()


if __name__ == "__main__":
    main()
