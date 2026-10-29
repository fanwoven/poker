"""The always-on-top overlay window.

Shows one big colour-coded play, the reason, the numbers behind it, what was
read, timing, and the session result. Never asks anything during a hand:
anything unknown is shown as "?".
"""
from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ..engine.cards import names
from ..engine.strategy import fmt_chips
from .advisor import Update
from .widgets import PracticeWindow, RangeGrid, StatsWindow, action_color

DATA = Path(__file__).resolve().parents[2] / "data"


def _beep_file() -> Path:
    f = DATA / "beep.wav"
    if not f.exists():
        DATA.mkdir(exist_ok=True)
        rate = 22050
        with wave.open(str(f), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            frames = b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * 880 * i / rate)
                                                    * min(1, (rate * 0.15 - i) / 800)))
                              for i in range(int(rate * 0.15)))
            w.writeframes(frames)
    return f


def beep():
    """Short sound without blocking. Works on PipeWire / PulseAudio / ALSA / Windows."""
    if sys.platform.startswith("win"):
        import winsound
        winsound.MessageBeep()
        return
    f = str(_beep_file())
    for player in ("pw-play", "paplay", "aplay"):
        if shutil.which(player):
            subprocess.Popen([player, f], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    QApplication.beep()


class Bridge(QObject):
    update = Signal(object)
    command = Signal(str)


def _fmt_cards(st, names_):
    out = []
    for n in names_:
        r = st.get(n)
        out.append("?" if r.status == "?" else ("" if r.status == "none" else r.text))
    return " ".join(x for x in out if x) or "-"


class Overlay(QWidget):
    def __init__(self, advisor, cfg: dict, db=None):
        super().__init__()
        self.adv = advisor
        self.cfg = cfg.get("overlay", {})
        self.db = db
        self.locked = False
        self.grid_win: RangeGrid | None = None
        self.practice_win = None
        self.stats_win = None
        self._drag: QPoint | None = None
        self._beeped_for = None
        self.last: Update | None = None
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Poker advisor")
        scale = float(self.cfg.get("font_scale", 1.0))
        self.action = QLabel("WAITING")
        self.action.setStyleSheet(f"font-size:{int(26 * scale)}pt;font-weight:bold;color:#bbbbbb")
        self.reason = QLabel("")
        self.numbers = QLabel("")
        self.reads = QLabel("")
        self.status = QLabel("")
        self.session = QLabel("")
        for w in (self.reason, self.numbers, self.reads, self.status, self.session):
            w.setWordWrap(True)
            w.setStyleSheet(f"font-size:{int(10 * scale)}pt;color:#e6e6e6")
        self.status.setStyleSheet(f"font-size:{int(9 * scale)}pt;color:#9aa0a8")
        self.session.setStyleSheet(f"font-size:{int(9 * scale)}pt;color:#9aa0a8")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        for w in (self.action, self.reason, self.numbers, self.reads, self.status, self.session):
            lay.addWidget(w)
        self.setFixedWidth(int(self.cfg.get("width", 430) * scale))
        self.bridge = Bridge()
        self.bridge.update.connect(self.show_update)
        self.bridge.command.connect(self.run_command_gui)
        self._restore_pos()

    # --------------------------------------------------------- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(18, 20, 26, int(255 * float(self.cfg.get("opacity", 0.88))))
        p.setBrush(c)
        p.setPen(QColor(255, 255, 255, 40) if not self.locked else QColor(240, 176, 48, 160))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)

    # ----------------------------------------------------------- updates
    def show_update(self, u: Update):
        self.last = u
        a = u.advice
        st = u.state
        if u.message and a is None:
            self.action.setText("?")
            self.action.setStyleSheet(self.action.styleSheet().split(";color")[0] + ";color:#bbbbbb")
            self.reason.setText(u.message)
        elif a is None:
            self.action.setText("?" if (u.missing and u.missing != ["cards"]) else "WAITING")
            self.action.setStyleSheet(self.action.styleSheet().split(";color")[0] + ";color:#bbbbbb")
            self.reason.setText("Can't read: " + ", ".join(u.missing) if u.missing and u.missing != ["cards"]
                                else "Waiting for my cards...")
        else:
            prefix = "" if u.final else "NEXT: "
            col = action_color(a)
            if not u.final:
                col = QColor(col).darker(130).name()
            self.action.setText(prefix + a.label())
            self.action.setStyleSheet(self.action.styleSheet().split(";color")[0] + f";color:{col}")
            self.reason.setText(a.reason)
            eq = a.equity.text() if a.equity else "-"
            parts = [f"Win <b>{eq}</b>"]
            if a.pot_odds:
                parts.append(f"need {a.pot_odds:.0%}")
            parts += [f"SPR {a.spr:.1f}", f"stack {a.pct_stack:.0f}%"]
            if a.dice is not None:
                parts.append(f"dice {a.dice}")
            warn = "".join(f"<br><span style='color:#f0b030'>⚠ {w}</span>" for w in a.warnings)
            self.numbers.setText(" | ".join(parts) + (f"<br>{a.hand}" if a.hand else "") + warn)
            if u.final and self._beeped_for != (u.spot.hand_id, u.spot.street, u.spot.to_call) and self.adv.auto:
                self._beeped_for = (u.spot.hand_id, u.spot.street, u.spot.to_call)
                if self.cfg.get("beep", True):
                    beep()
            if self.grid_win and self.grid_win.isVisible():
                self.grid_win.set_range(a.villain, a.villain_range)
        if a is None:
            self.numbers.setText("")
        # what was read
        if st is not None and st.frame_ok:
            s = u.spot
            info = u.info or {}
            pot = info.get("pot")
            pos = (s.position if s else "?") + ("?" if info.get("pos_guess") else "")
            opp = (str(s.n_opponents) if s else "?") + ("?" if info.get("opp_guess") else "")
            call = "?" if s is None else ("~" if info.get("call_approx") else "") + fmt_chips(s.to_call)
            self.reads.setText(
                f"Cards <b>{_fmt_cards(st, ['hole1', 'hole2'])}</b> | Board {_fmt_cards(st, [f'board{i}' for i in range(1, 6)])}"
                f"<br>Pot {fmt_chips(pot) if pot is not None else '?'} | Call {call} | "
                f"Stack {st.get('stack').show()} | {pos} | {opp} opp")
        lat = f"advice in {u.latency_ms:.0f} ms" if u.latency_ms is not None else f"read {u.read_ms:.0f} ms"
        self.status.setText(f"{'MY TURN' if u.my_turn else 'waiting'} | {lat} | "
                            f"{'AUTO' if self.adv.auto else 'manual'}{' | LOCKED' if self.locked else ''}")
        bbtxt = f" = {u.session_bb:+.1f} BB" if self.adv.tracker.bb else ""
        self.session.setText(f"Session: {u.session_chips:+,.0f}{bbtxt} in {u.session_hands} hands")
        self.adjustSize()

    # ---------------------------------------------------------- commands
    def handle_command(self, cmd: str) -> str:
        """Called from the socket thread: answer quickly, do GUI work in the GUI thread."""
        parts = cmd.split()
        if not parts:
            return "empty command"
        c = parts[0].lower()
        if c == "status":
            u = self.adv.last_update
            if u.advice:
                return f"{'TURN ' if u.final else 'NEXT '}{u.advice.label()} | {u.advice.reason}"
            return "no advice: " + (", ".join(u.missing) or u.message or "waiting")
        if c == "read":
            self.adv.force_read()
            return "reading"
        if c == "auto":
            return "auto " + ("on" if self.adv.toggle_auto() else "off")
        if c == "opp":
            n = self.adv.cycle_opponents()
            return f"opponents: {n or 'auto'}"
        if c == "pos":
            pos = parts[1].upper() if len(parts) > 1 else None
            self.adv.set_position(pos)
            return f"position: {pos or 'auto'}"
        if c == "bb" and len(parts) > 1:
            self.adv.set_bb(float(parts[1].replace(",", "")))
            return f"big blind: {parts[1]}"
        if c == "deviate":
            self.adv.mark_deviation()
            return "marked: I did not follow the advice this hand"
        if c in ("lock", "grid", "practice", "stats", "quit"):
            self.bridge.command.emit(c)
            return c
        return f"unknown command {c!r}"

    def run_command_gui(self, c: str):
        if c == "lock":
            self.locked = not self.locked
            self.setWindowFlag(Qt.WindowTransparentForInput, self.locked)
            self.show()
            self.update()
        elif c == "grid":
            if self.grid_win is None:
                self.grid_win = RangeGrid()
                self.grid_win.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
            if self.grid_win.isVisible():
                self.grid_win.hide()
            else:
                a = self.last.advice if self.last else None
                self.grid_win.set_range(a.villain if a else None, a.villain_range if a else "")
                self.grid_win.show()
        elif c == "practice":
            self.practice_win = PracticeWindow(self.adv.engine)
            self.practice_win.show()
        elif c == "stats" and self.db is not None:
            self.stats_win = StatsWindow(self.db)
            self.stats_win.show()
        elif c == "quit":
            QApplication.instance().quit()

    # ------------------------------------------------------- drag & place
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):
        self._drag = None
        self._save_pos()

    def _save_pos(self):
        DATA.mkdir(exist_ok=True)
        (DATA / "overlay.json").write_text(json.dumps({"x": self.x(), "y": self.y()}))

    def _restore_pos(self):
        try:
            d = json.loads((DATA / "overlay.json").read_text())
            self.move(d["x"], d["y"])
        except Exception:
            self.move(40, 40)
