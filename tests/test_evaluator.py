"""Fast evaluator vs. brute-force reference."""
import numpy as np
import pytest

from pokeradvisor.engine.cards import cards
from pokeradvisor.engine.evaluator import evaluate, evaluate_one, describe
from pokeradvisor.engine.reference import best_of


def test_random_7card_hands_match_reference():
    rng = np.random.default_rng(1)
    hands = np.array([rng.choice(52, 7, replace=False) for _ in range(30000)])
    fast = evaluate(hands)
    ref = np.array([best_of(h) for h in hands])
    assert (fast == ref).all()


@pytest.mark.parametrize("k", [5, 6])
def test_short_hands_with_void_filler(k):
    rng = np.random.default_rng(k)
    hands = np.array([list(rng.choice(52, k, replace=False)) + [52] * (7 - k) for _ in range(5000)])
    assert (evaluate(hands) == np.array([best_of(h) for h in hands])).all()


def test_all_5card_hands_give_7462_classes():
    # Every 5-card hand: there are exactly 7462 distinct hand values in poker.
    from itertools import combinations
    allh = np.array(list(combinations(range(52), 5)), dtype=np.int64)
    scores = evaluate(allh)
    assert len(np.unique(scores)) == 7462
    cats = np.bincount(scores >> 20, minlength=9)
    # known counts: high, pair, 2pair, trips, straight, flush, FH, quads, SF
    assert cats.tolist() == [1302540, 1098240, 123552, 54912, 10200, 5108, 3744, 624, 40]


@pytest.mark.parametrize("a,b", [
    ("AsKsQsJsTs", "9s8s7s6s5s"),       # royal > lower SF
    ("5s4s3s2sAs", "AhAdAcAs2d"),        # steel wheel > quads
    ("AhAdAcAsKd", "KhKdKcKsAd"),
    ("2h2d2cAsAd", "AhAdAcKsQd"),        # FH > trips
    ("2h3h4h5h7h", "AsKdQcJdTh"),        # flush > straight
    ("6s5d4c3h2d", "Ad2s3c4d5h"),        # 6-high straight > wheel
    ("AsAdKcKh2d", "AhAcQdQs2c"),
    ("AsAdKcKh3d", "AhAcKdKs2c"),        # kicker on two pair
    ("9s9d8c7h6d", "9h9c8d7s5c"),        # kicker on pair
])
def test_known_orderings(a, b):
    assert evaluate_one(cards(a)) > evaluate_one(cards(b))


def test_tie_and_board_plays():
    board = "AsKdQcJhTs"
    assert evaluate_one(cards(board + "2c3d")) == evaluate_one(cards(board + "4h5h"))
    assert describe(evaluate_one(cards("AsAdAcKsKd"))) == "full house"
