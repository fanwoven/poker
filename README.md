# Poker Advisor (local, offline)

Watches your poker table and shows one clear recommendation in a small
always-on-top window. Everything runs on your own PC: no cloud, no accounts.

**Status:** milestone (c), the math engine, is done and tested.
Screen capture, the reader, the overlay and the statistics come next.

## Install on Bazzite (one command at a time)

Bazzite's system is read-only, so everything goes in a Python "venv"
inside the project folder. Nothing is installed system-wide.

```bash
git clone https://github.com/fanwoven/poker.git ~/poker
```

```bash
cd ~/poker
```

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

Check that everything works (should end with "passed"):

```bash
.venv/bin/python -m pytest -q
```

## Try the brain from the terminal

```bash
.venv/bin/python -m pokeradvisor.engine.cli --hero 7s8s --board Jh6s2h --pot 150000 --call 50000 --stack 400000 --bb 20000 --pos BTN
```

Cards: rank `2-9 T J Q K A` + suit `s h d c` (`Ts` = ten of spades).
`--pot` = all chips in the middle *including* bets on this street.
`--call` = what you must add to call (0 = you can check).
Run with `--help` to see every option.

## Settings

Everything is in `config.yaml`: bet sizes, bluff frequencies, opponent
ranges (standard notation like `22+, A2s+, KTo+`), bankroll warnings.
Bankroll rules only warn unless you set `enforce: true`.

## How the brain decides

- **Win chance (equity)** against the hands the opponent probably has.
  Exact counting heads-up on the turn and river; otherwise a simulation
  with a ± error shown.
- **Opponent ranges** come from their preflop action (open, 3-bet, 4-bet)
  and position, and get narrower when they bet big (with some bluffs kept).
- **Pot odds**: the win chance you need to call = call / (pot + call).
  Out of position you realise less of your equity, so it's discounted.
  Draws also count implied odds.
- **Mixed strategy**: some bluffs and semi-bluffs, driven by a dice roll
  (0-99) that is fixed per spot, so re-reading gives the same answer.
