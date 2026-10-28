"""Card helpers.

A card is an int 0..51:  rank * 4 + suit
  rank: 0='2' ... 8='T', 9='J', 10='Q', 11='K', 12='A'
  suit: 0='s', 1='h', 2='d', 3='c'
VOID (52) is a "no card" filler, used to evaluate 5- or 6-card hands
with the same 7-card code.
"""
from __future__ import annotations

RANKS = "23456789TJQKA"
SUITS = "shdc"
VOID = 52


def card(text: str) -> int:
    """'As' -> 48. Accepts '10s' too. Raises ValueError on bad input."""
    t = text.strip()
    if len(t) == 3 and t[:2] == "10":
        t = "T" + t[2]
    if len(t) != 2:
        raise ValueError(f"bad card: {text!r}")
    r, s = t[0].upper(), t[1].lower()
    if r not in RANKS or s not in SUITS:
        raise ValueError(f"bad card: {text!r}")
    return RANKS.index(r) * 4 + SUITS.index(s)


def cards(text: str) -> list[int]:
    """'AsKd' or 'As Kd' or 'As,Kd' -> [48, 46]. Empty / '-' -> []."""
    t = text.replace(",", " ").replace(" ", "").strip()
    if t in ("", "-"):
        return []
    t = t.replace("10", "T")
    if len(t) % 2:
        raise ValueError(f"bad card list: {text!r}")
    out = [card(t[i:i + 2]) for i in range(0, len(t), 2)]
    if len(set(out)) != len(out):
        raise ValueError(f"duplicate card in {text!r}")
    return out


def name(c: int) -> str:
    """48 -> 'As'."""
    return RANKS[c >> 2] + SUITS[c & 3]


def names(cs) -> str:
    return "".join(name(c) for c in cs)


def rank_of(c: int) -> int:
    return c >> 2


def suit_of(c: int) -> int:
    return c & 3
