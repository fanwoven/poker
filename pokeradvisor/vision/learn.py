"""Find things the reader doesn't know yet, group look-alikes, and learn labels.

Used by the Teach screen (after a session) and by tests. Never runs during
live play.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .glyphs import Glyph, card_present, split_card, text_glyphs
from .reader import TableReader
from .templates import IGNORE, Look, glyph_score, look_score

SAME = 0.95  # two unknowns this similar are shown as one item to label


@dataclass
class Unknown:
    group: str               # template group, e.g. "board_rank", "char", "ind_turn"
    kind: str                # "rank" / "suit" / "char" / "look"
    glyph: Glyph | None = None
    look: Look | None = None
    crop: np.ndarray | None = None        # what the user sees (bigger context)
    region: str = ""
    count: int = 1
    members: list = field(default_factory=list)
    suggestion: str = ""


def unknowns_in_frame(reader: TableReader, frame: np.ndarray) -> list[Unknown]:
    p, st = reader.p, reader.store
    out: list[Unknown] = []
    if reader.check_frame(frame):
        return out
    for name, reg in p.regions.items():
        crop = reg.crop(frame)
        if reg.kind == "card":
            if not card_present(crop):
                continue
            parts = split_card(crop, p.card_layout)
            if not parts:
                continue
            for g, part in zip(parts, ("rank", "suit")):
                grp = f"{reg.card_group}_{part}"
                if not st.match(grp, g, p.min_score, p.min_margin).ok:
                    out.append(Unknown(grp, part, glyph=g, crop=crop.copy(), region=name))
        elif reg.kind in ("number", "text"):
            for g in text_glyphs(crop, reg.text):
                if not st.match(reg.font, g, p.min_score, p.min_margin).ok:
                    out.append(Unknown(reg.font, "char", glyph=g, crop=crop.copy(), region=name))
        else:
            lk = Look.from_crop(crop)
            if not st.match_look(f"ind_{name}", lk, p.min_score, p.min_margin).ok:
                out.append(Unknown(f"ind_{name}", "look", look=lk, crop=crop.copy(), region=name))
    return out


def cluster(items: list[Unknown]) -> list[Unknown]:
    """Merge look-alike unknowns so each is labelled once."""
    reps: list[Unknown] = []
    for it in items:
        for r in reps:
            if r.group != it.group:
                continue
            s = glyph_score(it.glyph, r.glyph) if it.glyph is not None else look_score(it.look, r.look)
            if s >= SAME:
                r.count += 1
                r.members.append(it)
                break
        else:
            it.members = [it]
            reps.append(it)
    reps.sort(key=lambda u: (u.group, -u.count))
    return reps


def apply_label(reader: TableReader, item: Unknown, label: str):
    """Save the label for this item and every look-alike merged into it."""
    label = label.strip()
    if not label:
        return
    if item.kind == "rank":
        label = "T" if label in ("10", "t") else label.upper()
    if item.kind == "suit":
        label = label.lower()[:1]
    for m in item.members or [item]:
        if m.glyph is not None:
            reader.store.add(m.group, label, m.glyph)
        else:
            reader.store.add_look(m.group, label, m.look)
    reader._cache.clear()


VALID = {
    "rank": set("23456789TJQKA"),
    "suit": set("shdc"),
}


def label_is_valid(kind: str, label: str) -> bool:
    label = label.strip()
    if kind == "rank":
        return (label.upper() if label != "10" else "T") in VALID["rank"]
    if kind == "suit":
        return label.lower() in VALID["suit"]
    if kind == "char":
        return len(label) == 1 or label == IGNORE
    return bool(label)
