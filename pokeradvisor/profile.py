"""Table presets ("profiles"): one per poker app / table layout.

A profile lives in  profiles/<name>/
  profile.yaml      boxes you drew + reading settings
  templates/        learned card symbols, digits, "my turn" looks
  captures/         screenshots saved automatically while you play (setup mode)
  samples/          screenshots + labels.csv used by the benchmark

Box coordinates are pixels in the captured frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profiles"

# Every box the calibration tool can ask for: name -> (kind, help text, required)
REGION_SPECS: dict[str, tuple[str, str, bool]] = {
    "hole1": ("card", "Your 1st card: draw around its corner (rank + small suit)", True),
    "hole2": ("card", "Your 2nd card: draw around its corner (rank + small suit)", True),
    "board1": ("card", "Board card 1: corner (rank + small suit)", True),
    "board2": ("card", "Board card 2: corner", True),
    "board3": ("card", "Board card 3: corner", True),
    "board4": ("card", "Board card 4 (turn): corner", True),
    "board5": ("card", "Board card 5 (river): corner", True),
    "pot": ("number", "The pot number", True),
    "stack": ("number", "Your stack (balance at the table)", True),
    "button": ("text", "The Call/Check button text (shows 'CALL 450' / 'CHECK')", True),
    "turn": ("indicator", "Something that ONLY shows on your turn (e.g. your timer ring or the FOLD button)", True),
    "hero_bet": ("number", "Your bet in front of you (optional)", False),
}
MAX_SEATS = 9
for _i in range(1, MAX_SEATS):
    REGION_SPECS[f"seat{_i}_bet"] = ("number", f"Opponent {_i}: the bet chips in front of them (optional)", False)
    REGION_SPECS[f"seat{_i}_stack"] = ("number", f"Opponent {_i}: their stack (optional)", False)
    REGION_SPECS[f"seat{_i}_cards"] = ("indicator", f"Opponent {_i}: their card backs (shows they are still in) (optional)", False)
    REGION_SPECS[f"seat{_i}_dealer"] = ("indicator", f"Opponent {_i}: where the dealer button sits (optional)", False)
REGION_SPECS["hero_dealer"] = ("indicator", "Where the dealer button sits when YOU are the dealer (optional)", False)


@dataclass
class Region:
    x: int
    y: int
    w: int
    h: int
    kind: str = "card"          # card / number / text / indicator
    # number/text settings
    text: str = "auto"          # auto / light / dark : text colour vs background
    font: str = "char"          # template group for glyphs (share fonts between boxes)

    def crop(self, img):
        return img[self.y:self.y + self.h, self.x:self.x + self.w]

    _name: str = ""             # filled in when loading (not saved)

    @property
    def card_group(self) -> str:
        """Hole and board cards are drawn at different sizes, so they get
        separate template groups."""
        return "hole" if self._name.startswith("hole") else "board"


@dataclass
class Profile:
    name: str
    frame_size: tuple[int, int] = (0, 0)     # (width, height) of the calibration frame
    regions: dict[str, Region] = field(default_factory=dict)
    seats: int = 6                           # players at a full table
    big_blind: float = 0.0                   # 0 = unknown (read from the app or set here)
    ante: float = 0.0
    pot_includes_bets: bool = False          # WSOP: the middle pot does NOT include this street's bets
    card_layout: str = "vertical"            # rank above suit in the corner (or "horizontal")
    abbreviations: dict = field(default_factory=lambda: {"K": 1e3, "M": 1e6, "B": 1e9})
    # reading thresholds (see reader.py)
    min_score: float = 0.80
    min_margin: float = 0.06

    @property
    def dir(self) -> Path:
        return PROFILES / self.name

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        d = asdict(self)
        d["regions"] = {k: {kk: vv for kk, vv in asdict(r).items() if not kk.startswith("_")}
                        for k, r in self.regions.items()}
        d["frame_size"] = list(self.frame_size)
        with open(self.dir / "profile.yaml", "w", encoding="utf-8") as f:
            f.write("# Table preset. Made by the calibration tool; you can edit it by hand.\n")
            yaml.safe_dump(d, f, sort_keys=False)

    @classmethod
    def load(cls, name: str) -> "Profile":
        p = PROFILES / name / "profile.yaml"
        if not p.exists():
            raise FileNotFoundError(f"no preset called {name!r} (expected {p})")
        with open(p, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        regs = {}
        for k, v in (d.pop("regions", None) or {}).items():
            r = Region(**v)
            r._name = k
            regs[k] = r
        d["frame_size"] = tuple(d.get("frame_size", (0, 0)))
        prof = cls(**d)
        prof.regions = regs
        return prof

    def set_region(self, name: str, x: int, y: int, w: int, h: int):
        kind = REGION_SPECS.get(name, ("number", "", False))[0]
        old = self.regions.get(name)
        r = Region(int(x), int(y), int(w), int(h), kind,
                   old.text if old else "auto", old.font if old else "char")
        r._name = name
        self.regions[name] = r

    def missing_required(self) -> list[str]:
        return [n for n, (_, _, req) in REGION_SPECS.items() if req and n not in self.regions]

    def opponent_seats(self) -> list[int]:
        return sorted({int(n[4]) for n in self.regions if n.startswith("seat")})


def list_profiles() -> list[str]:
    if not PROFILES.exists():
        return []
    return sorted(p.name for p in PROFILES.iterdir() if (p / "profile.yaml").exists())
