import random

from pokeradvisor.engine.cards import cards
from pokeradvisor.stats.db import HandDB, win_rate
from pokeradvisor.stats.report import report


def test_db_and_report(tmp_path):
    db = HandDB(tmp_path / "h.sqlite")
    rnd = random.Random(1)
    stack = 10000
    for i in range(200):
        res = rnd.choice([-100, -50, 0, 0, 150, 300, -200])
        db.add(hand_id=str(i), session="s1", preset="p", hole=cards("AsKd"), board=[],
               position=rnd.choice(["BTN", "BB", "CO"]), n_players=6, start_stack=stack,
               end_stack=stack + res, bb=100, advice=[{"street": "preflop", "label": "RAISE to 250"}],
               followed=i % 5 != 0, saw_turn=True)
        stack += res
    rows = db.rows("s1")
    wr = win_rate(rows)
    assert wr.hands == 200 and wr.low < wr.bb100 < wr.high
    txt = report(db, "s1", last_hands=3)
    assert "bb/100" in txt and "BTN" in txt and "did NOT follow" in txt and "95%" in txt


def test_small_sample_says_not_enough():
    rows = [{"result_bb": x, "result": x} for x in (5, -3, 2)]
    assert "too few" in win_rate(rows).verdict()
