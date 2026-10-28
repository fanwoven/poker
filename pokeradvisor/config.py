"""Load config.yaml (project root by default, or $POKERADVISOR_CONFIG)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return Path(os.environ.get("POKERADVISOR_CONFIG", ROOT / "config.yaml"))


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else config_path()
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
