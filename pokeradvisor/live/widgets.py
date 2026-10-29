"""Extra windows: 13x13 range grid, practice (manual entry), results graph."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..engine.cards import cards
from ..engine.positions import ALL_POSITIONS
from ..engine.ranges import Range, grid_label
from ..engine.strategy import Engine, Spot

ACTION_COLORS = {"FOLD": "#e05555", "CHECK": "#8aa4c8", "CALL": "#f0b030",
                 "BET": "#3cc070", "RAISE": "#3cc070", "ALLIN": "#c060f0"}


def action_color(advice) -> str:
    if advice is None:
        return "#bbbbbb"
    return ACTION_COLORS["ALLIN"] if advice.allin else ACTION_COLORS.get(advice.action, "#ffffff")


class RangeGrid(QWidget):
    """13x13 grid: top-right suited, bottom-left offsuit, diagonal pairs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rng: Range | None = None
        self.title = ""
        self.setMinimumSize(390, 410)
        self.setWindowTitle("Opponent range")

    def set_range(self, rng: Range | None, title: str = ""):
        self.rng, self.title = rng, title
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1b1e24"))
        p.setPen(QColor("#dddddd"))
        p.drawText(6, 16, (self.title or "no range")[:70] +
                   (f"   ({self.rng.percent():.0f}% of hands)" if self.rng else ""))
        if not self.rng:
            return
        g = self.rng.grid()
        size = min(self.width(), self.height() - 24) / 13
        f = QFont()
        f.setPointSizeF(max(6.0, size / 4))
        p.setFont(f)
        for i in range(13):
            for j in range(13):
                w = g[i][j]
                r = QRectF(j * size, 24 + i * size, size - 1, size - 1)
                base = QColor(40, 44, 52)
                on = QColor(220, 70, 70) if i < j else (QColor(70, 140, 220) if i > j else QColor(80, 190, 110))
                c = QColor(int(base.red() + (on.red() - base.red()) * w),
                           int(base.green() + (on.green() - base.green()) * w),
                           int(base.blue() + (on.blue() - base.blue()) * w))
                p.fillRect(r, c)
                p.setPen(QColor("#f0f0f0") if w > 0 else QColor("#777777"))
                p.drawText(r, Qt.AlignCenter, grid_label(i, j))


class PracticeWindow(QWidget):
    """Type a spot in by hand (no timer) and see the advice + the math."""

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("Practice: type a hand")
        self.hero = QLineEdit("AsKd")
        self.board = QLineEdit("")
        self.pot = QDoubleSpinBox(maximum=1e12, decimals=0, value=150)
        self.call = QDoubleSpinBox(maximum=1e12, decimals=0, value=0)
        self.stack = QDoubleSpinBox(maximum=1e12, decimals=0, value=10000)
        self.bb = QDoubleSpinBox(maximum=1e12, decimals=0, value=100)
        self.pos = QComboBox()
        self.pos.addItems(ALL_POSITIONS)
        self.pos.setCurrentText("BTN")
        self.vpos = QComboBox()
        self.vpos.addItems(["unknown"] + ALL_POSITIONS)
        self.opp = QSpinBox(minimum=1, maximum=8, value=1)
        self.pot_type = QComboBox()
        self.pot_type.addItems(["srp", "limped", "3bet", "4bet"])
        self.aggr = QComboBox()
        self.aggr.addItems(["they raised preflop", "I raised preflop"])
        form = QFormLayout()
        for lab, w in [("My cards (AsKd)", self.hero), ("Board (Jh6s2h, empty = preflop)", self.board),
                       ("Pot (incl. bets on table)", self.pot), ("To call (0 = check)", self.call),
                       ("My stack", self.stack), ("Big blind", self.bb), ("My position", self.pos),
                       ("Opponent position", self.vpos), ("Opponents in hand", self.opp),
                       ("Pot type (postflop)", self.pot_type), ("Preflop aggressor", self.aggr)]:
            form.addRow(lab, w)
        go = QPushButton("Advise")
        go.clicked.connect(self.run)
        self.out = QLabel("")
        self.out.setWordWrap(True)
        self.out.setTextFormat(Qt.RichText)
        self.grid = RangeGrid()
        left = QVBoxLayout()
        left.addLayout(form)
        left.addWidget(go)
        left.addWidget(self.out, 1)
        lay = QHBoxLayout(self)
        lay.addLayout(left)
        lay.addWidget(self.grid)
        self.hero.returnPressed.connect(self.run)
        self.board.returnPressed.connect(self.run)

    def run(self):
        try:
            s = Spot(hero=cards(self.hero.text()), board=cards(self.board.text()), pot=self.pot.value(),
                     to_call=self.call.value(), hero_stack=self.stack.value(), bb=self.bb.value(),
                     position=self.pos.currentText(),
                     villain_position=None if self.vpos.currentText() == "unknown" else self.vpos.currentText(),
                     n_opponents=self.opp.value(), pot_type=self.pot_type.currentText(),
                     hero_aggressor=self.aggr.currentIndex() == 1, hand_id="practice")
            a = self.engine.decide(s)
        except Exception as e:
            self.out.setText(f"<span style='color:#e05555'>Problem: {e}</span>")
            return
        eq = a.equity.text() if a.equity else "-"
        self.out.setText(
            f"<div style='font-size:22pt;font-weight:bold;color:{action_color(a)}'>{a.label()}</div>"
            f"<p>{a.reason}</p>"
            f"<p>Win odds: <b>{eq}</b> | needed: {a.pot_odds:.0%} | SPR {a.spr:.1f} | "
            f"stack used {a.pct_stack:.0f}%{'' if a.dice is None else f' | dice {a.dice}'}</p>"
            f"<p>Hand: {a.hand}</p>" + "".join(f"<p style='color:#f0b030'>⚠ {w}</p>" for w in a.warnings))
        self.grid.set_range(a.villain, a.villain_range)


class ResultsGraph(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values: list[float] = []
        self.setMinimumSize(500, 220)

    def set_values(self, v):
        self.values = v
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#1b1e24"))
        if len(self.values) < 2:
            p.setPen(QColor("#aaaaaa"))
            p.drawText(self.rect(), Qt.AlignCenter, "Graph appears after 2 hands")
            return
        lo, hi = min(self.values + [0]), max(self.values + [0])
        span = (hi - lo) or 1
        W, H, m = self.width(), self.height(), 30

        def pt(i, v):
            return QPointF(m + (W - 2 * m) * i / (len(self.values) - 1), H - m - (H - 2 * m) * (v - lo) / span)

        p.setPen(QPen(QColor("#666666"), 1, Qt.DashLine))
        p.drawLine(pt(0, 0), pt(len(self.values) - 1, 0))
        p.setPen(QPen(QColor("#3cc070"), 2))
        for i in range(1, len(self.values)):
            p.drawLine(pt(i - 1, self.values[i - 1]), pt(i, self.values[i]))
        p.setPen(QColor("#dddddd"))
        p.drawText(4, 14, f"Big blinds won (running total), {len(self.values)} hands")
        p.drawText(4, H - 8, f"min {lo:+.1f}   max {hi:+.1f}   now {self.values[-1]:+.1f}")


class StatsWindow(QWidget):
    def __init__(self, db, session: str | None = None):
        super().__init__()
        from ..stats.report import report
        self.setWindowTitle("Results")
        rows = db.rows(None)
        total, run = 0.0, []
        for r in rows:
            total += r["result_bb"]
            run.append(total)
        self.graph = ResultsGraph()
        self.graph.set_values(run)
        txt = QLabel("\n\n".join(report(db, None).split("\n\n")[:3]))  # summary, positions, followed
        txt.setFont(QFont("monospace"))
        lay = QVBoxLayout(self)
        lay.addWidget(self.graph, 1)
        lay.addWidget(txt)
