"""Read the table: cards, numbers, button text and "my turn" from one frame.

Every field comes back with a status:
  ok    read with confidence
  none  nothing there (no card yet, empty box)
  ?     could not read safely -> shown as "?" on the overlay, never guessed

Each box is only re-read when its pixels change (cheap hash), so reading
the same frame again, or a frame where only the timer moved, costs ~nothing.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..engine.cards import RANKS, SUITS
from ..profile import Profile, Region
from .glyphs import card_present, split_card, text_glyphs
from .templates import IGNORE, Look, TemplateStore


@dataclass
class Read:
    value: Any = None
    text: str = ""
    status: str = "?"
    approx: bool = False      # number shown shortened (1.2K) -> not exact
    ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def show(self) -> str:
        if self.status == "none":
            return "-"
        if self.status != "ok":
            return "?"
        return ("~" if self.approx else "") + self.text


@dataclass
class TableState:
    fields: dict[str, Read] = field(default_factory=dict)
    frame_ok: bool = True
    message: str = ""
    ms: float = 0.0

    def get(self, name: str) -> Read:
        return self.fields.get(name, Read(status="none"))

    def hole(self) -> list[int] | None:
        """Both hole cards, or None if not both read safely."""
        h = [self.get("hole1"), self.get("hole2")]
        if all(r.ok for r in h):
            return [r.value for r in h]
        return None

    def board(self) -> list[int] | None:
        """Board cards in order; None if any visible card is unreadable or there is a gap."""
        out = []
        seen_none = False
        for i in range(1, 6):
            r = self.get(f"board{i}")
            if r.status == "?":
                return None
            if r.status == "none":
                seen_none = True
                continue
            if seen_none:
                return None  # a card after an empty slot: something is off
            out.append(r.value)
        if len(out) not in (0, 3, 4, 5):
            return None  # mid-animation (only 1 or 2 flop cards drawn yet)
        return out


# ------------------------------------------------------------------ parsing

_NUM = re.compile(r"^([0-9][0-9,]*(?:\.[0-9]+)?)([A-Z])?$")


def parse_amount(text: str, abbreviations: dict) -> tuple[float | None, bool]:
    """'1,250' -> (1250, False); '5.58M' -> (5580000, True); bad -> (None, False)."""
    t = text.replace(" ", "").upper()
    m = _NUM.match(t)
    if not m:
        return None, False
    num, suf = m.groups()
    if "," in num:
        parts = num.split(",")
        if "." in parts[-1]:
            last, _ = parts[-1].split(".", 1)
        else:
            last = parts[-1]
        if not (1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:-1]) and len(last) == 3):
            return None, False  # "1,25" -> not a valid thousands format: don't guess
        num = num.replace(",", "")
    try:
        val = float(num)
    except ValueError:
        return None, False
    if suf:
        mult = {k.upper(): v for k, v in abbreviations.items()}.get(suf)
        if mult is None:
            return None, False
        return val * mult, True
    return val, False


def parse_button(text: str, abbreviations: dict) -> tuple[str, float | None, bool]:
    """Button text -> (kind, amount, approx). kind: check / call / call_any / allin / other."""
    t = " ".join(text.upper().split())
    compact = t.replace(" ", "").replace("-", "")
    if "CALLANY" in compact:
        return "call_any", None, False
    m = re.search(r"([0-9][0-9,.]*[A-Z]?)$", compact)
    amt, approx = (parse_amount(m.group(1), abbreviations) if m else (None, False))
    if compact.startswith("ALLIN"):
        return "allin", amt, approx
    if compact.startswith("CALL"):
        return "call", amt, approx
    if "CHECK" in compact:
        return "check", 0.0, False
    return "other", amt, approx


def card_from_labels(rank: str, suit: str) -> int | None:
    rank = "T" if rank == "10" else rank.upper()
    suit = suit.lower()
    if rank not in RANKS or suit not in SUITS:
        return None
    return RANKS.index(rank) * 4 + SUITS.index(suit)


# ------------------------------------------------------------------- reader

class TableReader:
    def __init__(self, profile: Profile, store: TemplateStore | None = None):
        self.p = profile
        self.store = store or TemplateStore(profile.dir / "templates")
        self._cache: dict[str, tuple[bytes, Read]] = {}

    def reload_templates(self):
        self.store = TemplateStore(self.p.dir / "templates")
        self._cache.clear()

    # -- one box ---------------------------------------------------------
    def read_card(self, reg: Region, crop: np.ndarray) -> Read:
        if not card_present(crop):
            return Read(None, "", "none")
        parts = split_card(crop, self.p.card_layout)
        if parts is None:
            return Read(None, "", "?")
        rank_g, suit_g = parts
        grp = reg.card_group
        mr = self.store.match(f"{grp}_rank", rank_g, self.p.min_score, self.p.min_margin)
        ms = self.store.match(f"{grp}_suit", suit_g, self.p.min_score, self.p.min_margin)
        r_txt = mr.label if mr.ok else "?"
        s_txt = ms.label if ms.ok else "?"
        if mr.ok and ms.ok:
            c = card_from_labels(mr.label, ms.label)
            if c is not None:
                return Read(c, ("T" if r_txt == "10" else r_txt) + s_txt, "ok")
        return Read(None, r_txt + s_txt, "?")

    def read_chars(self, reg: Region, crop: np.ndarray) -> tuple[str, bool]:
        """Glyphs -> string. Second value False if any glyph was unknown."""
        gl = text_glyphs(crop, reg.text)
        if not gl:
            return "", True
        line_h = max(g.h for g in gl)
        out, ok, last_end = [], True, None
        for g in gl:
            m = self.store.match(reg.font, g, self.p.min_score, self.p.min_margin)
            if m.ok and m.label == IGNORE:
                continue
            if last_end is not None and g.x - last_end > 0.45 * line_h:
                out.append(" ")
            if m.ok:
                out.append(m.label)
            else:
                out.append("?")
                ok = False
            last_end = g.x + g.w
        return "".join(out).strip(), ok

    def read_number(self, reg: Region, crop: np.ndarray) -> Read:
        txt, ok = self.read_chars(reg, crop)
        if not txt:
            return Read(None, "", "none")
        if not ok:
            return Read(None, txt, "?")
        val, approx = parse_amount(txt, self.p.abbreviations)
        if val is None:
            return Read(None, txt, "?")
        return Read(val, txt, "ok", approx)

    def read_text(self, reg: Region, crop: np.ndarray) -> Read:
        txt, ok = self.read_chars(reg, crop)
        if not txt:
            return Read(None, "", "none")
        return Read(txt if ok else None, txt, "ok" if ok else "?")

    def read_indicator(self, name: str, crop: np.ndarray) -> Read:
        m = self.store.match_look(f"ind_{name}", Look.from_crop(crop), self.p.min_score, self.p.min_margin)
        if not m.ok:
            return Read(None, "", "?")
        return Read(m.label, m.label, "ok")

    def read_region(self, name: str, frame: np.ndarray) -> Read:
        reg = self.p.regions[name]
        crop = reg.crop(frame)
        t0 = time.perf_counter()
        key = hashlib.blake2b(np.ascontiguousarray(crop).tobytes(), digest_size=12).digest()
        hit = self._cache.get(name)
        if hit and hit[0] == key:
            r = hit[1]
            return Read(r.value, r.text, r.status, r.approx, (time.perf_counter() - t0) * 1000)
        if reg.kind == "card":
            r = self.read_card(reg, crop)
        elif reg.kind == "number":
            r = self.read_number(reg, crop)
        elif reg.kind == "text":
            r = self.read_text(reg, crop)
        else:
            r = self.read_indicator(name, crop)
        r.ms = (time.perf_counter() - t0) * 1000
        self._cache[name] = (key, r)
        return r

    # -- whole table -----------------------------------------------------
    def check_frame(self, frame: np.ndarray) -> str:
        fw, fh = self.p.frame_size
        if fw and (frame.shape[1], frame.shape[0]) != (fw, fh):
            return (f"screen size changed: preset is {fw}x{fh}, now {frame.shape[1]}x{frame.shape[0]}. "
                    "Re-calibrate or restore the window size.")
        return ""

    def read(self, frame: np.ndarray, names: list[str] | None = None) -> TableState:
        t0 = time.perf_counter()
        st = TableState()
        msg = self.check_frame(frame)
        if msg:
            st.frame_ok, st.message = False, msg
            return st
        for n in names or list(self.p.regions):
            if n in self.p.regions:
                st.fields[n] = self.read_region(n, frame)
        st.ms = (time.perf_counter() - t0) * 1000
        return st

    def is_my_turn(self, frame: np.ndarray) -> bool | None:
        """Cheap check, call often. True / False / None (can't tell)."""
        if "turn" not in self.p.regions or self.check_frame(frame):
            return None
        r = self.read_region("turn", frame)
        if not r.ok:
            return None
        return r.value == "on"
