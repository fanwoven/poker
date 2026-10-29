"""End to end: fake screen -> reader -> tracker -> engine -> update, timed."""
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402
from test_reader import teach_from_truth  # noqa: E402

import pokeradvisor.profile as P  # noqa: E402
from pokeradvisor.config import load_config  # noqa: E402
from pokeradvisor.live.advisor import Advisor  # noqa: E402
from pokeradvisor.stats.db import HandDB  # noqa: E402
from pokeradvisor.vision.reader import TableReader  # noqa: E402
from pokeradvisor.vision.templates import TemplateStore  # noqa: E402


class ScriptCap:
    """Shows each frame for a given time, like a real screen."""
    def __init__(self, script):
        self.script, self.t0 = script, None

    def grab(self):
        if self.t0 is None:
            self.t0 = time.time()
        el = time.time() - self.t0
        for frame, until in self.script:
            if el < until:
                return frame
        return self.script[-1][0]


@pytest.fixture()
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "PROFILES", tmp_path)
    p = synth.profile()
    p.big_blind = 1000
    p.save()
    reader = TableReader(p, TemplateStore(p.dir / "templates"))
    for seed in range(1000, 1060):
        teach_from_truth(reader, *synth.table(seed, street=5))
        teach_from_truth(reader, *synth.table(seed + 500, street=0))
    reader.store.save()
    return P.Profile.load(p.name)


def frame_for(seed, street, turn):
    return synth.table(seed, street=street, my_turn=turn)[0]


def test_live_flow_and_latency(profile, tmp_path):
    script = [
        (frame_for(11, 0, False), 0.6),   # preflop, opponents acting
        (frame_for(11, 0, True), 1.4),    # my turn preflop
        (frame_for(11, 3, False), 2.0),   # flop, waiting
        (frame_for(11, 3, True), 2.8),    # my turn on the flop
        (frame_for(12, 0, False), 4.0),   # next hand
    ]
    ups = []
    db = HandDB(tmp_path / "h.sqlite")
    adv = Advisor(load_config(), profile, ScriptCap(script), ups.append, db=db, session="t")
    adv.start()
    time.sleep(3.6)
    adv.stop()
    finals = [u for u in ups if u.final]
    assert finals, [u.missing for u in ups[-3:]]
    streets = {u.spot.street for u in finals}
    assert streets == {"preflop", "flop"}
    lat = max(u.latency_ms for u in finals)
    print(f"\nturn -> advice latency: {[round(u.latency_ms) for u in finals]} ms")
    assert lat < 2000
    previews = [u for u in ups if u.advice and not u.final]
    assert previews, [(u.missing, u.my_turn) for u in ups[:6]]  # advice was ready before my turn
    rows = db.rows()
    import json
    assert len(rows) == 2  # finished hand + the hand still running when we stopped
    assert [a["street"] for a in json.loads(rows[0]["advice"])] == ["preflop", "flop"]
