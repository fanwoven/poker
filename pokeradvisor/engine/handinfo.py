"""Plain-English description of my hand: made hand and draws."""
from __future__ import annotations

from .cards import VOID
from .evaluator import evaluate_one, category, CATEGORY_NAMES

# 10 straight windows as rank sets (wheel uses Ace = rank 12)
_WINDOWS = [set(range(t - 4, t + 1)) for t in range(12, 3, -1)] + [{12, 0, 1, 2, 3}]


def made_hand(hero, board) -> str:
    """'top pair', 'two pair', 'flush', ... (postflop only)."""
    if len(board) < 3:
        return ""
    score = evaluate_one(list(hero) + list(board) + [VOID] * (5 - len(board)))
    cat = category(score)
    board_score = evaluate_one(list(board) + [VOID] * (7 - len(board))) if len(board) >= 5 else None
    if board_score is not None and board_score == score:
        return "the board plays (" + CATEGORY_NAMES[cat] + ")"
    if cat == 1:
        pair_rank = (score >> 16) & 15
        hr = sorted((c >> 2 for c in hero), reverse=True)
        br = sorted({c >> 2 for c in board}, reverse=True)
        if hr[0] == hr[1]:
            return "overpair" if pair_rank > br[0] else "pocket pair below the board"
        if pair_rank not in hr:
            return "high card (pair on board)"
        if pair_rank == br[0]:
            return "top pair"
        if pair_rank == br[-1]:
            return "bottom pair"
        return "middle pair"
    return CATEGORY_NAMES[cat]


def draws(hero, board) -> tuple[list[str], int]:
    """Draws that use at least one of my cards. Returns (labels, approx outs).
    Only on flop and turn."""
    if len(board) not in (3, 4):
        return [], 0
    allc = list(hero) + list(board)
    labels, outs = [], 0
    cat_now = category(evaluate_one(allc + [VOID] * (7 - len(allc))))

    # flush draw: exactly 4 of a suit, one of them mine
    if cat_now < 5:
        for s in range(4):
            n_all = sum(1 for c in allc if c & 3 == s)
            n_mine = sum(1 for c in hero if c & 3 == s)
            if n_all == 4 and n_mine >= 1:
                labels.append("flush draw")
                outs += 9

    # straight draws: ranks that would complete a straight using my cards
    if cat_now < 4:
        ranks_all = {c >> 2 for c in allc}
        ranks_board = {c >> 2 for c in board}
        completing = set()
        for w in _WINDOWS:
            missing = w - ranks_all
            if len(missing) == 1:
                # the straight must use one of my cards (not just the board)
                if len(w - ranks_board) >= 2:
                    completing |= missing
        if len(completing) >= 2:
            labels.append("open-ended straight draw")
            outs += 8 if "flush draw" not in labels else 6
        elif len(completing) == 1:
            labels.append("gutshot straight draw")
            outs += 4 if "flush draw" not in labels else 3
    return labels, outs
