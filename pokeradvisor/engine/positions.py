"""Table positions for any table size from 2 to 9 players."""
from __future__ import annotations

# Preflop action order (first to act ... last), by number of players dealt in.
PREFLOP_ORDER = {
    2: ["BTN", "BB"],                       # heads-up: the button is also small blind
    3: ["BTN", "SB", "BB"],
    4: ["CO", "BTN", "SB", "BB"],
    5: ["HJ", "CO", "BTN", "SB", "BB"],
    6: ["UTG", "HJ", "CO", "BTN", "SB", "BB"],
    7: ["UTG", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
    8: ["UTG", "UTG1", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
    9: ["UTG", "UTG1", "UTG2", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
}

# Postflop order: blinds act first, button last.
POSTFLOP_RANK = {"SB": 0, "BB": 1, "UTG": 2, "UTG1": 3, "UTG2": 4, "LJ": 5,
                 "HJ": 6, "CO": 7, "BTN": 8}

ALL_POSITIONS = ["UTG", "UTG1", "UTG2", "LJ", "HJ", "CO", "BTN", "SB", "BB"]


def position_for(n_players: int, seats_after_button: int) -> str:
    """Position name from how many seats (clockwise, counting only players
    dealt in) the player sits after the dealer button. 0 = on the button."""
    n = max(2, min(9, n_players))
    order = PREFLOP_ORDER[n]
    if n == 2:
        return "BTN" if seats_after_button % 2 == 0 else "BB"
    k = seats_after_button % n
    if k == 0:
        return "BTN"
    if k == 1:
        return "SB"
    if k == 2:
        return "BB"
    return order[k - 3]


def in_position(hero: str, villain: str | None) -> bool:
    """True if hero acts after the villain on the flop, turn and river.
    Unknown villain: assume in position only on the button or cutoff."""
    if villain is None:
        return hero in ("BTN", "CO")
    if hero == "BTN" and villain == "BB":
        return True  # also true heads-up
    return POSTFLOP_RANK.get(hero, 0) > POSTFLOP_RANK.get(villain, 0)


def is_early(pos: str) -> bool:
    return pos in ("UTG", "UTG1", "UTG2", "LJ")
