"""Learned templates: what each card rank, suit, digit and "my turn" look looks
like in YOUR app. Stored per preset in profiles/<name>/templates/.

Matching rule (NEVER GUESS): the best label must score at least min_score AND
beat the best DIFFERENT label by at least min_margin. Otherwise: unknown.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .glyphs import Glyph, SIZE

IGNORE = "_"  # label for junk (chip icons, separators you don't care about)


@dataclass
class Match:
    label: str | None        # None = unknown
    score: float
    second: float            # best score of a DIFFERENT label
    second_label: str | None

    @property
    def ok(self) -> bool:
        return self.label is not None


def glyph_score(a: Glyph, b: Glyph) -> float:
    """Similarity 0..1 (1 = identical). Shape facts must also agree."""
    s = float(np.dot(a.vec, b.vec))
    if abs(np.log(max(a.aspect, 1e-3) / max(b.aspect, 1e-3))) > 0.25:
        s -= 0.3
    if abs(a.rel_h - b.rel_h) > 0.2:
        s -= 0.3
    if abs(a.rel_y - b.rel_y) > 0.15:
        s -= 0.3
    if a.color and b.color and a.color != b.color:
        s -= 0.5
    return s


@dataclass
class Look:
    """A small colour thumbnail of an indicator box (e.g. 'my turn' ring)."""
    img: np.ndarray  # float32 (16,16,3) 0..1

    @classmethod
    def from_crop(cls, bgr: np.ndarray) -> "Look":
        small = cv2.resize(bgr, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        return cls(small)


def look_score(a: Look, b: Look) -> float:
    """1 = identical; brightness matters (a dimmed button is different)."""
    return float(1.0 - np.abs(a.img - b.img).mean() * 4.0)


class TemplateStore:
    def __init__(self, folder: Path | None = None):
        self.folder = Path(folder) if folder else None
        self.glyphs: dict[str, list[tuple[str, Glyph]]] = {}
        self.looks: dict[str, list[tuple[str, Look]]] = {}
        if self.folder and (self.folder / "index.json").exists():
            self.load()

    # ------------------------------------------------------------ matching
    @staticmethod
    def _decide(scores: dict[str, float], min_score: float, min_margin: float) -> Match:
        if not scores:
            return Match(None, 0.0, 0.0, None)
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        best_l, best = ranked[0]
        sec_l, sec = ranked[1] if len(ranked) > 1 else (None, -1.0)
        if best >= min_score and best - sec >= min_margin:
            return Match(best_l, best, sec, sec_l)
        return Match(None, best, sec, sec_l if best >= min_score else best_l)

    def match(self, group: str, g: Glyph, min_score=0.80, min_margin=0.06) -> Match:
        scores: dict[str, float] = {}
        for label, t in self.glyphs.get(group, []):
            s = glyph_score(g, t)
            if s > scores.get(label, -9):
                scores[label] = s
        return self._decide(scores, min_score, min_margin)

    def match_look(self, group: str, look: Look, min_score=0.80, min_margin=0.06) -> Match:
        scores: dict[str, float] = {}
        for label, t in self.looks.get(group, []):
            s = look_score(look, t)
            if s > scores.get(label, -9):
                scores[label] = s
        return self._decide(scores, min_score, min_margin)

    # ------------------------------------------------------------ learning
    def add(self, group: str, label: str, g: Glyph, dedupe: float = 0.985):
        """Add a template unless an identical one with this label exists."""
        lst = self.glyphs.setdefault(group, [])
        for l, t in lst:
            if l == label and glyph_score(g, t) >= dedupe:
                return False
        lst.append((label, g))
        return True

    def add_look(self, group: str, label: str, look: Look, dedupe: float = 0.97):
        lst = self.looks.setdefault(group, [])
        for l, t in lst:
            if l == label and look_score(look, t) >= dedupe:
                return False
        lst.append((label, look))
        return True

    def labels(self, group: str) -> set[str]:
        return {l for l, _ in self.glyphs.get(group, [])} | {l for l, _ in self.looks.get(group, [])}

    def count(self) -> int:
        return sum(len(v) for v in self.glyphs.values()) + sum(len(v) for v in self.looks.values())

    # ---------------------------------------------------------- save / load
    def save(self):
        if not self.folder:
            raise ValueError("no folder for templates")
        self.folder.mkdir(parents=True, exist_ok=True)
        idx = {"glyphs": [], "looks": []}
        vecs, thumbs, looks = [], [], []
        for group, lst in self.glyphs.items():
            for label, g in lst:
                idx["glyphs"].append({"group": group, "label": label, "aspect": g.aspect,
                                      "rel_h": g.rel_h, "rel_y": g.rel_y, "color": g.color})
                vecs.append(g.vec)
                thumbs.append(g.thumb)
        for group, lst in self.looks.items():
            for label, lk in lst:
                idx["looks"].append({"group": group, "label": label})
                looks.append(lk.img)
        np.savez_compressed(self.folder / "data.npz",
                            vecs=np.array(vecs, np.float32).reshape(-1, SIZE * SIZE),
                            thumbs=np.array(thumbs, np.uint8).reshape(-1, SIZE, SIZE),
                            looks=np.array(looks, np.float32).reshape(-1, 16, 16, 3))
        with open(self.folder / "index.json", "w", encoding="utf-8") as f:
            json.dump(idx, f, indent=1, ensure_ascii=False)
        # a picture sheet so you can see what was learned
        self._contact_sheet()

    def load(self):
        with open(self.folder / "index.json", encoding="utf-8") as f:
            idx = json.load(f)
        data = np.load(self.folder / "data.npz")
        self.glyphs, self.looks = {}, {}
        for i, m in enumerate(idx["glyphs"]):
            g = Glyph(data["vecs"][i], data["thumbs"][i], m["aspect"], m["rel_h"], m["rel_y"], m["color"])
            self.glyphs.setdefault(m["group"], []).append((m["label"], g))
        for i, m in enumerate(idx["looks"]):
            self.looks.setdefault(m["group"], []).append((m["label"], Look(data["looks"][i])))

    def _contact_sheet(self):
        rows = []
        for group, lst in sorted(self.glyphs.items()):
            for label, g in sorted(lst, key=lambda x: x[0]):
                tile = cv2.copyMakeBorder(g.thumb, 2, 14, 2, 2, cv2.BORDER_CONSTANT, value=40)
                cv2.putText(tile, label[:3], (2, SIZE + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.35, 255, 1)
                rows.append(tile)
        if not rows:
            return
        per = 24
        while len(rows) % per:
            rows.append(np.zeros_like(rows[0]))
        sheet = np.vstack([np.hstack(rows[i:i + per]) for i in range(0, len(rows), per)])
        cv2.imwrite(str(self.folder / "learned.png"), sheet)
