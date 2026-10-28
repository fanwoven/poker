"""Draws fake poker tables (with known true values) to test the reader here,
since the real screenshots stay on the user's PC."""
from __future__ import annotations

import random

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pokeradvisor.engine.cards import RANKS, SUITS, name
from pokeradvisor.profile import Profile

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SUIT_CH = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
W, H = 1280, 720
BOARD_XY = [(400 + i * 80, 250) for i in range(5)]
HOLE_XY = [(560, 440), (612, 440)]


def _font(sz):
    return ImageFont.truetype(FONT, sz)


def _card(d: ImageDraw.ImageDraw, x, y, c, w, h, rs, ss, jitter):
    r, s = RANKS[c >> 2], SUITS[c & 3]
    col = (200, 20, 30) if s in "hd" else (15, 15, 15)
    d.rounded_rectangle([x, y, x + w, y + h], 6, fill=(250, 250, 250), outline=(180, 180, 180))
    txt = "10" if r == "T" else r
    d.text((x + 5 + jitter, y + 3), txt, font=_font(rs), fill=col)
    d.text((x + 6 + jitter, y + 6 + rs), SUIT_CH[s], font=_font(ss), fill=col)
    d.text((x + w // 2 - 4, y + h // 2), SUIT_CH[s], font=_font(ss * 2), fill=col)


def fmt_amount(v: int) -> str:
    if v >= 1_000_000 and random.random() < 0.7:
        return f"{v / 1e6:.2f}M".replace(".00M", "M")
    if v >= 10_000 and v % 1000 == 0 and random.random() < 0.5:
        return f"{v // 1000}K"
    return f"{v:,}"


def profile() -> Profile:
    p = Profile("synthetic", frame_size=(W, H), seats=6)
    for i, (x, y) in enumerate(BOARD_XY):
        p.set_region(f"board{i + 1}", x + 1, y + 1, 30, 52)
    for i, (x, y) in enumerate(HOLE_XY):
        p.set_region(f"hole{i + 1}", x + 1, y + 1, 36, 64)
    p.set_region("pot", 548, 352, 184, 44)
    p.set_region("stack", 548, 572, 184, 44)
    p.set_region("button", 905, 640, 230, 56)
    p.set_region("turn", 425, 475, 30, 30)
    return p


def table(seed: int, street: int | None = None, my_turn: bool | None = None):
    """-> (BGR frame, truth dict)"""
    rnd = random.Random(seed)
    random.seed(seed)
    deck = list(range(52))
    rnd.shuffle(deck)
    street = rnd.choice([0, 3, 4, 5]) if street is None else street
    my_turn = rnd.random() < 0.5 if my_turn is None else my_turn
    hole, board = deck[:2], deck[2:2 + street]
    pot = rnd.choice([rnd.randrange(1, 999) * 50, rnd.randrange(1, 60) * 10000, rnd.randrange(1, 900) * 10000])
    stack = rnd.randrange(1, 99999) * 10
    btn = rnd.choice(["CHECK", f"CALL {fmt_amount(rnd.randrange(1, 50) * 1000)}", "BET", "RAISE"])

    img = Image.new("RGB", (W, H), (20, 30, 70))
    d = ImageDraw.Draw(img)
    d.ellipse([200, 120, 1080, 620], fill=(40, 140, 60))
    for (x, y), c in zip(BOARD_XY, board):
        _card(d, x, y, c, 64, 90, 22, 16, rnd.randint(0, 2))
    for (x, y), c in zip(HOLE_XY, hole):
        _card(d, x, y, c, 80, 112, 28, 22, 0)
    pot_txt = fmt_amount(pot)
    d.rounded_rectangle([556, 358, 724, 390], 10, fill=(10, 10, 10))
    d.text((566 + rnd.randint(0, 20), 361), pot_txt, font=_font(22), fill=(255, 255, 255))
    d.rectangle([556, 578, 724, 610], fill=(30, 50, 110))
    stack_txt = f"{stack:,}"
    d.text((570 + rnd.randint(0, 10), 581), stack_txt, font=_font(22), fill=(225, 235, 255))
    d.rounded_rectangle([910, 645, 1130, 691], 18, fill=(20, 60, 160))
    d.text((925 + rnd.randint(0, 6), 652), btn, font=_font(26), fill=(240, 240, 255))
    d.ellipse([420, 470, 520, 570], outline=(80, 255, 60) if my_turn else (90, 90, 90), width=8)
    frame = np.array(img)[:, :, ::-1].copy()
    noise = np.random.default_rng(seed).normal(0, 1.5, frame.shape)
    frame = np.clip(frame + noise, 0, 255).astype(np.uint8)
    truth = {
        "hole": "".join(name(c) for c in hole), "board": "".join(name(c) for c in board),
        "pot": pot_txt, "stack": stack_txt, "button": btn, "turn": "on" if my_turn else "off",
    }
    return frame, truth
