"""Ranges and equity against well-known values."""
import pytest

from pokeradvisor.engine.cards import cards
from pokeradvisor.engine.ranges import Range, hand_class
from pokeradvisor.engine.equity import exact_heads_up, monte_carlo, equity


def test_range_sizes():
    assert len(Range.parse("AA")) == 6
    assert len(Range.parse("AKs")) == 4
    assert len(Range.parse("AKo")) == 12
    assert len(Range.parse("AK")) == 16
    assert len(Range.parse("22+")) == 78
    assert len(Range.parse("A2s+")) == 48           # A2s..AKs = 12 classes
    assert len(Range.parse("KTo+")) == 36           # KTo, KJo, KQo
    assert len(Range.parse("T9s-65s")) == 20        # T9s 98s 87s 76s 65s
    assert len(Range.parse("A5s-A2s")) == 16
    assert len(Range.parse("77-55")) == 18
    assert len(Range.parse("any")) == 1326
    assert Range.parse("AKo:0.5").contains_hand(*cards("AsKd")) == 0.5


def test_grid_and_class():
    g = Range.parse("AA, AKs").grid()
    assert g[0][0] == 1 and g[0][1] == 1 and g[1][0] == 0
    assert hand_class(*cards("Ts9s")) == "T9s"
    assert hand_class(*cards("9sTd")) == "T9o"


def test_bad_tokens_raise():
    for bad in ["AAs", "XYs", "AK-QJs"]:
        with pytest.raises(ValueError):
            Range.parse(bad)


@pytest.mark.parametrize("hero,vil,expected", [
    ("AsAh", "KdKc", 0.813),   # AA vs KK (no shared suits)
    ("AsKs", "QhQd", 0.462),   # AKs vs QQ
])
def test_exact_preflop_known_values(hero, vil, expected):
    r = exact_heads_up(cards(hero), [], Range.parse(vil))
    assert abs(r.equity - expected) < 0.003


def test_monte_carlo_matches_ranges():
    r = monte_carlo(cards("AsAh"), [], [Range.parse("KK")], samples=60000, seed=3)
    assert abs(r.equity - 0.82) < 0.01          # AA vs KK ≈ 82%
    r = monte_carlo(cards("AsKs"), [], [Range.parse("QQ")], samples=60000, seed=4)
    assert abs(r.equity - 0.46) < 0.01


def test_monte_carlo_agrees_with_exact_on_flop():
    hero, board, vil = cards("7s8s"), cards("Jh6s2h"), Range.parse("22+,A2s+,KTs+,ATo+,KJo+")
    ex = exact_heads_up(hero, board, vil)
    mc = monte_carlo(hero, board, [vil], samples=60000, seed=5)
    assert abs(ex.equity - mc.equity) < max(mc.error * 1.5, 0.006)


def test_river_and_ties():
    # both play the board (royal flush on board) -> 50%
    r = equity(cards("2c3d"), cards("AsKsQsJsTs"), [Range.parse("any")])
    assert r.method == "exact" and abs(r.equity - 0.5) < 1e-9
    # nut flush on river vs anything is near 100%
    r = equity(cards("AhKh"), cards("2h7h9hJc3s"), [Range.parse("any")])
    assert r.equity > 0.97


def test_multiway_is_lower():
    hu = monte_carlo(cards("AsAh"), [], [Range.parse("any")], samples=20000, seed=1)
    four = monte_carlo(cards("AsAh"), [], [Range.parse("any")] * 4, samples=20000, seed=1)
    assert 0.83 < hu.equity < 0.87 and 0.53 < four.equity < 0.59
