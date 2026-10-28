"""Cut a screen box into "glyphs" (single symbols) and describe them.

Used for both card corners (rank + suit) and numbers / button text.
A Glyph holds a small normalised picture plus shape facts (aspect ratio,
height relative to the text line, colour) that the matcher also checks,
so "," and "." or a red and a black suit can't be confused.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

SIZE = 24  # normalised glyph picture is SIZE x SIZE


@dataclass
class Glyph:
    vec: np.ndarray          # normalised picture, zero-mean, unit length (SIZE*SIZE,)
    thumb: np.ndarray        # uint8 picture for showing to the user (SIZE x SIZE)
    aspect: float            # width / height
    rel_h: float = 1.0       # height / text line height
    rel_y: float = 0.0       # bottom offset below the baseline / line height
    color: str = ""          # card ink colour: black / red / blue / green
    x: int = 0               # position in the box (for ordering / spaces)
    w: int = 0
    h: int = 0


def normalise(ink: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Float ink image (any size) -> (unit vector, uint8 thumbnail)."""
    h, w = ink.shape
    scale = (SIZE - 2) / max(h, w)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    small = cv2.resize(ink.astype(np.float32), (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((SIZE, SIZE), np.float32)
    y0, x0 = (SIZE - nh) // 2, (SIZE - nw) // 2
    canvas[y0:y0 + nh, x0:x0 + nw] = small
    thumb = np.clip(canvas * 255, 0, 255).astype(np.uint8)
    v = canvas.ravel() - canvas.mean()
    n = np.linalg.norm(v)
    return (v / n if n > 1e-9 else v), thumb


def make_glyph(ink: np.ndarray, mask: np.ndarray, **kw) -> Glyph | None:
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return None
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = ink[y0:y1, x0:x1] * (mask[y0:y1, x0:x1] > 0)
    vec, thumb = normalise(crop)
    return Glyph(vec, thumb, (x1 - x0) / (y1 - y0), x=int(x0), w=int(x1 - x0), h=int(y1 - y0), **kw)


# ----------------------------------------------------------------- cards

def card_ink(bgr: np.ndarray) -> np.ndarray:
    """0..1 'how much ink': white card face = 0, red/black symbols = high."""
    return (255.0 - bgr.min(axis=2).astype(np.float32)) / 255.0


def card_present(bgr: np.ndarray, white_frac: float = 0.30) -> bool:
    """Is there a face-up card in this corner box? (enough white card face)"""
    if bgr.size == 0:
        return False
    white = bgr.min(axis=2) > 185
    return float(white.mean()) >= white_frac


def ink_color(bgr: np.ndarray, mask: np.ndarray) -> str:
    px = bgr[mask > 0].astype(np.float32)
    if len(px) == 0:
        return ""
    # use the most saturated half of the pixels (edges are blended with white)
    sat = px.max(1) - px.min(1)
    core = px[sat >= np.median(sat)]
    b, g, r = core.mean(0)
    if max(b, g, r) - min(b, g, r) < 50:
        return "black"
    return ["blue", "green", "red"][int(np.argmax([b, g, r]))]


def _groups(profile: np.ndarray, min_count: int = 1) -> list[tuple[int, int]]:
    """Runs of non-empty rows/columns: [(start, end), ...]"""
    on = profile >= min_count
    runs, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(on)))
    return runs


def split_card(bgr: np.ndarray, layout: str = "vertical", thresh: float = 0.35):
    """Corner box -> (rank Glyph, suit Glyph) or None if it can't be split cleanly."""
    ink = card_ink(bgr)
    mask = (ink > thresh).astype(np.uint8)
    # drop specks and anything touching the box edge (card border, neighbour card)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    H, W = mask.shape
    keep = np.zeros_like(mask)
    biggest = max([stats[i][4] for i in range(1, n)], default=0)
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a < 3:
            continue
        touches = x == 0 or y == 0 or x + w >= W or y + h >= H
        if touches and (h > 0.8 * H or w > 0.8 * W):  # long border lines
            continue
        if touches and a < 0.15 * biggest:            # table showing in a rounded corner
            continue
        keep[lab == i] = 1
    axis = 1 if layout == "vertical" else 0
    prof = keep.sum(axis=axis)
    runs = [r for r in _groups(prof) if r[1] - r[0] >= 2]
    if runs:  # ignore faint runs (specks) next to real symbols
        big = max(prof[a:b].sum() for a, b in runs)
        runs = [(a, b) for a, b in runs if prof[a:b].sum() >= 0.1 * big]
    if len(runs) < 2:
        return None
    (a0, a1), (b0, b1) = runs[0], runs[1]
    if layout == "vertical":
        rm, sm = np.zeros_like(keep), np.zeros_like(keep)
        rm[a0:a1] = keep[a0:a1]
        sm[b0:b1] = keep[b0:b1]
    else:
        rm, sm = np.zeros_like(keep), np.zeros_like(keep)
        rm[:, a0:a1] = keep[:, a0:a1]
        sm[:, b0:b1] = keep[:, b0:b1]
    rank = make_glyph(ink, rm, color=ink_color(bgr, rm))
    suit = make_glyph(ink, sm, color=ink_color(bgr, sm))
    if rank is None or suit is None:
        return None
    return rank, suit


# ----------------------------------------------------------- numbers / text

def _text_mask(gray: np.ndarray, light: bool) -> tuple[np.ndarray, np.ndarray]:
    thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    g = gray.astype(np.float32)
    if light:
        ink = np.clip((g - thr) / max(1.0, 255 - thr), 0, 1)
        mask = gray > thr
    else:
        ink = np.clip((thr - g) / max(1.0, thr), 0, 1)
        mask = gray < thr
    # remove anything touching the box edge: that's background, not text
    m = mask.astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    H, W = m.shape
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if x == 0 or y == 0 or x + w >= W or y + h >= H or a < 2:
            m[lab == i] = 0
    return ink, m


def _components(m: np.ndarray) -> list[list[int]]:
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    comps = [[int(v) for v in stats[i][:4]] + [i] for i in range(1, n)]  # x,y,w,h,label
    comps.sort(key=lambda c: c[0])
    # merge pieces that sit above each other (e.g. ':' or a broken glyph)
    merged: list[list] = []
    for c in comps:
        if merged:
            p = merged[-1]
            ov = min(p[0] + p[2], c[0] + c[2]) - max(p[0], c[0])
            if ov > 0.5 * min(p[2], c[2]):
                x0, y0 = min(p[0], c[0]), min(p[1], c[1])
                x1, y1 = max(p[0] + p[2], c[0] + c[2]), max(p[1] + p[3], c[1] + c[3])
                merged[-1] = [x0, y0, x1 - x0, y1 - y0] + p[4:] + [c[4]]
                continue
        merged.append(c)
    return [[c[0], c[1], c[2], c[3], c[4:]] for c in merged], lab


def _score_polarity(m: np.ndarray) -> float:
    n, _, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    hs = [stats[i][3] for i in range(1, n) if stats[i][4] >= 4]
    if not hs:
        return 0
    top = max(hs)
    if top < 5:
        return 0
    return sum(1 for h in hs if h >= 0.55 * top)


def text_glyphs(bgr: np.ndarray, polarity: str = "auto") -> list[Glyph]:
    """Number / text box -> glyphs left to right (spaces are found later)."""
    if bgr.size == 0:
        return []
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if polarity == "auto":
        cand = [(True, *_text_mask(gray, True)), (False, *_text_mask(gray, False))]
        light, ink, m = max(cand, key=lambda c: (_score_polarity(c[2]), c[0]))
    else:
        ink, m = _text_mask(gray, polarity == "light")
    comps, lab = _components(m)
    if not comps:
        return []
    line_h = max(c[3] for c in comps)
    tall = [c for c in comps if c[3] >= 0.6 * line_h]
    baseline = float(np.median([c[1] + c[3] for c in tall])) if tall else line_h
    out = []
    for x, y, w, h, labels in comps:
        cm = np.isin(lab, labels).astype(np.uint8)
        g = make_glyph(ink, cm, rel_h=h / line_h, rel_y=(y + h - baseline) / line_h)
        if g is not None:
            out.append(g)
    return out
