"""Decision engine sanity checks."""
import pytest

from pokeradvisor.config import load_config
from pokeradvisor.engine.cards import cards
from pokeradvisor.engine.positions import position_for, in_position
from pokeradvisor.engine.strategy import Engine, Spot, dice_roll


@pytest.fixture(scope="module")
def eng():
    return Engine(load_config())


def spot(**kw):
    kw.setdefault("bb", 10)
    kw.setdefault("hero_stack", 1000)
    kw["hero"] = cards(kw["hero"])
    kw["board"] = cards(kw.get("board", ""))
    return Spot(**kw)


def test_positions():
    assert position_for(6, 0) == "BTN" and position_for(6, 1) == "SB"
    assert position_for(6, 2) == "BB" and position_for(6, 3) == "UTG"
    assert position_for(9, 5) == "UTG2" and position_for(9, 8) == "CO"
    assert position_for(2, 0) == "BTN" and position_for(2, 1) == "BB"
    assert position_for(3, 0) == "BTN" and position_for(3, 2) == "BB"
    assert in_position("BTN", "BB") and not in_position("SB", "BTN")


def test_open_and_fold_preflop(eng):
    a = eng.decide(spot(hero="AsAd", position="UTG", pot=15, to_call=10))
    assert a.action == "RAISE" and a.amount == 25
    assert eng.decide(spot(hero="7c2d", position="UTG", pot=15, to_call=10)).action == "FOLD"
    # BB checks junk in an unraised pot, never folds for free
    assert eng.decide(spot(hero="7c2d", position="BB", pot=20, to_call=0)).action == "CHECK"


def test_value_3bet_and_4bet(eng):
    a = eng.decide(spot(hero="KsKd", position="BTN", villain_position="CO", pot=40, to_call=25))
    assert a.action == "RAISE" and a.amount == 75             # 3x the 25 open, in position
    a = eng.decide(spot(hero="AsAd", position="CO", pot=125, to_call=65, hero_bet=25, preflop="3bet"))
    assert a.action == "RAISE"


def test_trash_folds_to_3bet(eng):
    a = eng.decide(spot(hero="9c8d", position="CO", pot=125, to_call=65, hero_bet=25, preflop="3bet"))
    assert a.action == "FOLD" and "need" in a.reason


def test_postflop_value_and_fold(eng):
    # flopped set, checked to us -> bet
    a = eng.decide(spot(hero="7s7d", board="7h Kc 2d", pot=60, to_call=0, position="BTN"))
    assert a.action == "BET" and 0 < a.amount <= 60
    # nothing on the river facing a pot-size bet -> fold
    a = eng.decide(spot(hero="4c3c", board="AsKdQh9s8d", pot=200, to_call=100, position="BB", hand_id="h1"))
    assert a.action == "FOLD"
    # nuts facing a bet -> raise
    a = eng.decide(spot(hero="AhKh", board="Qh Jh Th 2c", pot=200, to_call=60, position="BB"))
    assert a.action == "RAISE"


def test_draw_calls_with_odds(eng):
    # flush draw facing a small bet: price is right
    a = eng.decide(spot(hero="Ah5h", board="Kh 9h 2c", pot=130, to_call=30, position="BTN"))
    assert a.action in ("CALL", "RAISE")
    assert "flush draw" in a.hand


def test_short_stack_shove(eng):
    # value hand with tiny SPR -> all-in, never bet more than the stack
    a = eng.decide(spot(hero="AsAd", board="Ac 7d 2s", pot=500, to_call=0, hero_stack=300))
    assert a.action == "BET" and a.allin and a.amount == 300


def test_same_spot_same_answer(eng):
    s1 = spot(hero="Ts9s", board="8s 7d 2c", pot=100, to_call=0, hand_id="42")
    s2 = spot(hero="Ts9s", board="8s 7d 2c", pot=100, to_call=0, hand_id="42")
    assert dice_roll(s1) == dice_roll(s2)
    a, b = eng.decide(s1), eng.decide(s2)
    assert a.label() == b.label()


def test_bankroll_warning_only_by_default(eng):
    a = eng.decide(spot(hero="AsAd", position="UTG", pot=15, to_call=10, hero_stack=40))
    assert a.action == "RAISE" and a.warnings   # warns but still raises


def test_bankroll_enforced():
    cfg = load_config()
    cfg["bankroll"]["enforce"] = True
    e = Engine(cfg)
    a = e.decide(spot(hero="AsAd", position="UTG", pot=15, to_call=10, hero_stack=40))
    assert a.action == "FOLD"


def test_narrowing_keeps_strong_hands(eng):
    from pokeradvisor.engine.ranges import Range
    base = Range.parse("any")
    board = cards("Ks 7d 2c")
    big = eng.narrow(base, board, set(board), 1.5)
    small = eng.narrow(base, board, set(board), 0.3)
    assert len(big) < len(small)
    assert big.contains_hand(*cards("KhKd")) > 0        # sets stay in
    assert big.contains_hand(*cards("AhKh")) > 0        # top pair stays in


def test_decision_speed(eng):
    import time
    s = spot(hero="Ah5h", board="Kh 9h 2c 3d", pot=130, to_call=30, position="BTN")
    eng.decide(s)
    t = time.perf_counter(); eng.decide(s); assert (time.perf_counter() - t) < 0.05  # cached
