"""Teach the reader on some fake tables, then check it on NEW fake tables.
Goal: 0 wrong values; unknowns ('?') are allowed but should be rare."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

from pokeradvisor.tools.benchmark import read_fields, score, report  # noqa: E402
from pokeradvisor.vision.glyphs import split_card, text_glyphs, card_present  # noqa: E402
from pokeradvisor.vision.learn import unknowns_in_frame, cluster  # noqa: E402
from pokeradvisor.vision.reader import TableReader, parse_amount, parse_button  # noqa: E402
from pokeradvisor.vision.templates import TemplateStore, Look  # noqa: E402


def teach_from_truth(reader, frame, truth):
    """What the user does in the Teach screen, done automatically from truth."""
    p, st = reader.p, reader.store
    cards = {"hole": truth["hole"], "board": truth["board"]}
    for name, reg in p.regions.items():
        crop = reg.crop(frame)
        if reg.kind == "card":
            grp = reg.card_group
            idx = int(name[-1]) - 1
            txt = cards[grp]
            if idx * 2 >= len(txt) or not card_present(crop):
                continue
            parts = split_card(crop)
            st.add(f"{grp}_rank", txt[idx * 2], parts[0])
            st.add(f"{grp}_suit", txt[idx * 2 + 1], parts[1])
        elif reg.kind in ("number", "text"):
            chars = truth[name].replace(" ", "")
            gl = text_glyphs(crop, reg.text)
            assert len(gl) == len(chars), (name, truth[name], len(gl))
            for g, ch in zip(gl, chars):
                st.add(reg.font, ch, g)
        else:
            st.add_look(f"ind_{name}", truth[name], Look.from_crop(crop))
    reader._cache.clear()


def to_label_row(t):
    kind, amt, _ = parse_button(t["button"], {"K": 1e3, "M": 1e6})
    return {"file": "", "hole": t["hole"] or "-", "board": t["board"] or "-", "pot": t["pot"],
            "stack": t["stack"], "button": t["button"], "my_turn": "yes" if t["turn"] == "on" else "no",
            "call": "" if amt is None else f"{amt:g}"}


@pytest.fixture(scope="module")
def taught():
    p = synth.profile()
    reader = TableReader(p, TemplateStore())
    for seed in range(1000, 1060):
        f, t = synth.table(seed, street=5)
        if reader.store.count() > 400:
            break
        teach_from_truth(reader, f, t)
    return reader


def test_untaught_reader_says_unknown_not_wrong():
    p = synth.profile()
    reader = TableReader(p, TemplateStore())
    f, t = synth.table(7, street=5)
    st = reader.read(f)
    res = score([(to_label_row(t), read_fields(reader, st))], p.abbreviations)
    assert sum(r["wrong"] for r in res.values()) == 0
    assert res["hole"]["unknown"] == 1


def test_reader_zero_wrong_on_new_tables(taught):
    rows, times = [], []
    import time
    for seed in range(1, 201):
        f, t = synth.table(seed)
        taught._cache.clear()
        t0 = time.perf_counter()
        st = taught.read(f)
        times.append((time.perf_counter() - t0) * 1000)
        rows.append((to_label_row(t), read_fields(taught, st)))
    res = score(rows, taught.p.abbreviations)
    print("\n" + report(res, times))
    assert sum(r["wrong"] for r in res.values()) == 0
    unknown = sum(r["unknown"] for r in res.values())
    assert unknown <= 0.02 * 200 * 7, report(res, times)
    assert sorted(times)[100] < 40  # median full read under 40 ms here


def test_unknowns_are_grouped_for_teaching():
    p = synth.profile()
    reader = TableReader(p, TemplateStore())
    items = []
    for seed in range(5):
        f, _ = synth.table(seed, street=5)
        items += unknowns_in_frame(reader, f)
    groups = cluster(items)
    assert len(groups) < len(items) / 2   # look-alikes merged
    assert {g.group for g in groups} >= {"hole_rank", "hole_suit", "board_rank", "board_suit", "char", "ind_turn"}


def test_cache_makes_rereads_free(taught):
    f, _ = synth.table(3)
    taught.read(f)
    st = taught.read(f)
    assert st.ms < 5


def test_parse_amounts():
    ab = {"K": 1e3, "M": 1e6, "B": 1e9}
    assert parse_amount("1,250", ab) == (1250, False)
    assert parse_amount("5.58M", ab) == (5.58e6, True)
    assert parse_amount("20K", ab) == (20000, True)
    assert parse_amount("1,25", ab) == (None, False)        # malformed -> unknown, never guess
    assert parse_amount("12,345,678", ab) == (12345678, False)
    assert parse_button("CALL 20K", ab) == ("call", 20000, True)
    assert parse_button("CHECK", ab)[0] == "check"
    assert parse_button("CHECK/FOLD", ab)[0] == "check"
    assert parse_button("CALL ANY", ab)[0] == "call_any"
    assert parse_button("ALL-IN 5,000", ab) == ("allin", 5000, False)


def test_unseen_font_gives_unknown_not_wrong(taught, monkeypatch):
    """App changed its graphics: the reader must say '?' rather than guess."""
    monkeypatch.setattr(synth, "FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf")
    rows = []
    for seed in range(300, 340):
        f, t = synth.table(seed)
        taught._cache.clear()
        rows.append((to_label_row(t), read_fields(taught, taught.read(f))))
    res = score(rows, taught.p.abbreviations)
    print("\n" + report(res, []))
    assert sum(r["wrong"] for r in res.values() if r is not res["my_turn"]) == 0
