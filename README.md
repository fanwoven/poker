# Poker Advisor (local, offline)

Watches your poker table and shows one clear recommendation (FOLD / CHECK /
CALL 450 / BET 600 / RAISE to 1,200 / ALL-IN) in a small always-on-top window,
with the numbers behind it. It **never clicks for you**: it only tells you.

Everything runs on your PC: no cloud, no accounts, free.
It works with **any** poker app or website: you make a **preset** for each one.

---

## 1. Install (Bazzite, one command at a time)

Bazzite's system is read-only, so everything goes into a Python "venv"
inside the project folder. Nothing is installed system-wide, and no
`rpm-ostree` is needed.

```bash
git clone https://github.com/fanwoven/poker.git ~/poker
```

```bash
cd ~/poker
```

`--system-site-packages` lets the venv use the system's GStreamer bindings
(faster screen capture) if your system has them.

```bash
python3 -m venv --system-site-packages .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

Check that everything works (it should end with "passed"):

```bash
.venv/bin/python -m pytest -q
```

Measure screen capture speed on your PC. The first time, your desktop asks
what to share: pick your screen (or the browser window) and tick "remember".

```bash
.venv/bin/python -m pokeradvisor.capture.bench
```

It saves `data/bench_portal.png`. Open it and check that it shows your
screen (not a black picture).

---

## 2. Make a preset for your app (once per app / table size)

Open the poker table at the size you will play at, and leave the window there.

**a) Draw the boxes.** It takes a screenshot after 5 seconds, so switch to the table:

```bash
.venv/bin/python -m pokeradvisor.tools.calibrate wsop6
```

Click a box name on the left, drag a rectangle on the picture, and it jumps
to the next one. Mouse wheel = zoom, right-button drag = move.

| Box | What to draw around |
|---|---|
| hole1, hole2 | the **corner** of each of your cards: rank + small suit |
| board1..board5 | the **corner** of each board card (draw all 5, even if empty now) |
| pot | the pot number |
| stack | your chips |
| button | the Call/Check button text ("CALL 20K", "CHECK") |
| turn | something that **only** appears on your turn (e.g. part of your timer ring) |
| optional | each opponent's bet, stack, card backs, and the dealer button spot |

Opponent 1 is the first seat to your **left** (clockwise), then 2, 3...
Draw the dealer-button and card-back boxes if you want automatic position and
opponent counting. Without them, set them with keys (see section 4).

Tick "It is my turn in this screenshot" if it is, then **Save preset**.

Then open `profiles/wsop6/profile.yaml` and set `big_blind:` (for example 20000).
WSOP's middle pot does not include this street's bets, so keep
`pot_includes_bets: false` and draw the opponent bet boxes.

**b) Collect screenshots while you play or watch** (no windows, no questions):

```bash
.venv/bin/python -m pokeradvisor.tools.collect wsop6 --minutes 20
```

**c) Teach it (after the session)**. Every unknown card symbol, digit and
"my turn" look is shown **once**. Type what it is and press Enter:

```bash
.venv/bin/python -m pokeradvisor.tools.teach wsop6
```

- rank: `2-9 T J Q K A` (10 is fine)
- suit: `s h d c`
- digits/letters: the character, or `_` for junk like a chip icon
- turn box: `on` or `off`

Optional: `--ai` asks your local Ollama vision model for suggestions. You
still confirm each one, and it never runs during play.

**d) Check accuracy (target: 0 wrong values).** First write the true values
for 20 screenshots (the reader's answer is filled in; check every field):

```bash
.venv/bin/python -m pokeradvisor.tools.truth wsop6
```

```bash
.venv/bin/python -m pokeradvisor.tools.benchmark wsop6
```

It shows right / wrong / "?" per field, and milliseconds per read.
"?" is fine: teach more and it goes away. **Wrong** values are bugs; please
send me the output.

---

## 3. Play

```bash
bin/poker-advisor wsop6
```

- It watches by itself (auto mode). Before your turn it shows `NEXT: ...`;
  when your turn starts it shows the final advice, **beeps**, and shows
  `advice in ... ms`.
- Anything it can't read safely shows as `?`. It never guesses a card or a number.
- Drag the overlay with the mouse. Keep it **away from the table** (it must
  not cover any box).
- When you close it, it prints the session report.

Practice without a timer (type a hand in):

```bash
bin/poker-advisor --practice
```

---

## 4. Keyboard shortcuts (GNOME)

Wayland doesn't let apps grab global keys, so the overlay listens to a tiny
command (`bin/pa-ctl`), and GNOME runs it when you press a key.

Add all shortcuts with one command:

```bash
.venv/bin/python -m pokeradvisor.tools.gnome_shortcuts
```

| Keys | Does |
|---|---|
| Ctrl+Alt+R | read now |
| Ctrl+Alt+A | auto mode on/off |
| Ctrl+Alt+L | lock (clicks go through the overlay) on/off |
| Ctrl+Alt+O | number of opponents: auto, 1, 2 ... 8 |
| Ctrl+Alt+D | "I did NOT follow the advice" this hand |
| Ctrl+Alt+G | show/hide the 13x13 opponent range grid |

To do it by hand instead: **Settings > Keyboard > View and Customize Shortcuts
> Custom Shortcuts > +**. Name: `Poker read`. Command:
`/home/YOURNAME/poker/bin/pa-ctl read`. Then press the keys you want.

More commands (try them in a terminal):

```bash
bin/pa-ctl bb 20000
```

```bash
bin/pa-ctl pos BTN
```

```bash
bin/pa-ctl status
```

`pa-ctl practice` opens practice mode, `pa-ctl stats` opens the results
window, `pa-ctl quit` closes the overlay.

---

## 5. Statistics

Every hand is saved in `data/hands.sqlite`: result in chips and big blinds,
position, starting hand, the advice on each of your turns, and whether you
followed it.

```bash
.venv/bin/python -m pokeradvisor.stats.report
```

```bash
.venv/bin/python -m pokeradvisor.stats.report --last --hands 30
```

It shows your win rate in bb/100 with a 95% range, and says plainly when there
aren't enough hands to know yet. It also shows results by position,
followed-vs-not-followed, and a graph.

A hand's result = your stack at the start of the next hand minus your stack at
the start of this one. If you add chips between hands, that hand will look
like a win.

---

## 6. Settings

Everything is in `config.yaml`, with comments: bet sizes, bluff frequencies,
opponent ranges (`22+, A2s+, KTo+`), timing, overlay look, and bankroll rules.
Bankroll rules only **warn** unless you set `enforce: true`.

---

## 7. Problems

- **Black benchmark picture / capture fails**: run the benchmark again and
  pick the screen in the share dialog. To get the dialog again, delete
  `data/portal_restore_token`. Slow fallback: set `capture: method: portal_screenshot`.
- **Overlay is not on top**: it runs through XWayland for this. If it doesn't
  start, try `overlay: qt_platform: wayland` in `config.yaml` (it then may
  not stay on top).
- **Screen size changed**: the preset is tied to the window size. Restore it,
  or calibrate again.
- **Windows** (bonus): the same commands work with `.venv\Scripts\python`;
  capture uses `mss`. The shortcuts must be set up with your own hotkey tool.

---

## How the brain decides

- **Win chance (equity)** against the hands the opponent probably has: exact
  counting heads-up on the turn and river, simulation otherwise (with ±).
  Verified: AA vs KK ≈ 82%, AKs vs QQ ≈ 46%.
- **Opponent ranges** come from their preflop action and position, and get
  narrower when they bet big (with some bluffs kept).
- **Pot odds**: needed = call / (pot + call). Out of position your equity is
  discounted. Draws also count implied odds.
- **Mixed strategy**: some 3-bet bluffs, semi-bluffs and river bluffs. The dice
  roll (0-99) is fixed per spot and shown on screen.

## Project layout

```
pokeradvisor/engine    cards, evaluator, ranges, equity, decisions
pokeradvisor/capture   screen capture (portal/PipeWire, mss, files) + benchmark
pokeradvisor/vision    reading boxes, templates, learning
pokeradvisor/live      tracker, live loop, overlay, control socket
pokeradvisor/stats     hand database and report
pokeradvisor/tools     calibrate, collect, teach, truth, benchmark, gnome shortcuts
profiles/<preset>      your presets (boxes, learned templates, screenshots)
```
