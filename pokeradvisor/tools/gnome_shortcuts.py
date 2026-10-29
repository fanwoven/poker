"""Add the poker keyboard shortcuts to GNOME (Settings > Keyboard > Custom Shortcuts).

  python -m pokeradvisor.tools.gnome_shortcuts          # add / update
  python -m pokeradvisor.tools.gnome_shortcuts --remove

Default keys (change them later in GNOME Settings if you like):
  Ctrl+Alt+R read   Ctrl+Alt+A auto on/off   Ctrl+Alt+L lock
  Ctrl+Alt+O opponents   Ctrl+Alt+D "I didn't follow"   Ctrl+Alt+G range grid
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
CTL = Path(__file__).resolve().parents[2] / "bin" / "pa-ctl"
KEYS = [("read", "<Control><Alt>r"), ("auto", "<Control><Alt>a"), ("lock", "<Control><Alt>l"),
        ("opp", "<Control><Alt>o"), ("deviate", "<Control><Alt>d"), ("grid", "<Control><Alt>g")]


def gs(*args) -> str:
    return subprocess.run(["gsettings", *args], capture_output=True, text=True, check=True).stdout.strip()


def current() -> list[str]:
    raw = gs("get", SCHEMA, "custom-keybindings")
    raw = raw.replace("@as ", "")
    return list(ast.literal_eval(raw)) if raw else []


def main():
    remove = "--remove" in sys.argv
    paths = [p for p in current() if "pokeradvisor-" not in p]
    if not remove:
        for cmd, key in KEYS:
            path = f"{BASE}pokeradvisor-{cmd}/"
            sch = f"{SCHEMA}.custom-keybinding:{path}"
            gs("set", sch, "name", f"Poker: {cmd}")
            gs("set", sch, "command", f"{CTL} {cmd}")
            gs("set", sch, "binding", key)
            paths.append(path)
            print(f"  {key:22} -> pa-ctl {cmd}")
    gs("set", SCHEMA, "custom-keybindings", str(paths))
    print("Removed." if remove else "Done. You can change the keys in Settings > Keyboard > Custom Shortcuts.")


if __name__ == "__main__":
    main()
