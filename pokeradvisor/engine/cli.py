"""Try the engine from the terminal (practice / testing).

Example:
  python -m pokeradvisor.engine.cli --hero AsKd --pos CO --pot 30 --call 0 --stack 1000 --bb 10
  python -m pokeradvisor.engine.cli --hero 7s8s --board Jh6s2h --pot 150000 --call 50000 --stack 40000 --bb 20000
"""
from __future__ import annotations

import argparse

from ..config import load_config
from .cards import cards
from .strategy import Engine, Spot


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ask the engine about one spot.")
    ap.add_argument("--hero", required=True, help="your cards, e.g. AsKd")
    ap.add_argument("--board", default="", help="board cards, e.g. Jh6s2h")
    ap.add_argument("--pot", type=float, required=True, help="all chips in the middle incl. current bets")
    ap.add_argument("--call", type=float, default=0, help="chips you must add to call (0 = check)")
    ap.add_argument("--stack", type=float, required=True, help="your chips behind")
    ap.add_argument("--bb", type=float, required=True, help="big blind")
    ap.add_argument("--pos", default="BTN", help="your position: UTG..BTN, SB, BB")
    ap.add_argument("--vpos", default=None, help="opponent position (optional)")
    ap.add_argument("--opp", type=int, default=1, help="opponents still in the hand")
    ap.add_argument("--pot-type", default=None, help="limped / srp / 3bet / 4bet")
    ap.add_argument("--aggressor", action="store_true", help="you made the last preflop raise")
    ap.add_argument("--hand-id", default="cli")
    a = ap.parse_args(argv)
    eng = Engine(load_config())
    s = Spot(hero=cards(a.hero), board=cards(a.board), pot=a.pot, to_call=a.call,
             hero_stack=a.stack, bb=a.bb, position=a.pos.upper(), villain_position=a.vpos,
             n_opponents=a.opp, pot_type=a.pot_type, hero_aggressor=a.aggressor or None,
             hand_id=a.hand_id)
    adv = eng.decide(s)
    print(f"\n  >>> {adv.label()} <<<\n")
    print("  " + adv.reason)
    if adv.equity:
        print(f"  win odds: {adv.equity.text()}   ({adv.equity.method}, {adv.equity.ms:.0f} ms)")
    if adv.pot_odds:
        print(f"  pot odds needed: {adv.pot_odds:.0%}")
    print(f"  SPR: {adv.spr:.1f}   % of stack: {adv.pct_stack:.0f}%")
    if adv.hand:
        print(f"  your hand: {adv.hand}")
    if adv.dice is not None:
        print(f"  dice: {adv.dice}")
    for w in adv.warnings:
        print(f"  WARNING: {w}")
    print(f"  decided in {adv.ms:.0f} ms\n")


if __name__ == "__main__":
    main()
