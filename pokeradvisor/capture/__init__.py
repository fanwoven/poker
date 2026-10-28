"""Screen capture backends.

make_capturer() picks the best one for this computer:
  - Linux Wayland (GNOME / KDE): xdg-desktop-portal ScreenCast + PipeWire.
    Continuous frames, so a "grab" just returns the newest frame (~0 ms).
  - Linux X11 / Windows: mss.
  - "files": replays saved screenshots (testing, practice, benchmarks).
"""
from __future__ import annotations

import os
import sys

from .base import Capturer


def is_wayland() -> bool:
    return sys.platform.startswith("linux") and (
        os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY")))


def make_capturer(cfg: dict | None = None, method: str | None = None) -> Capturer:
    cfg = (cfg or {}).get("capture", {})
    method = method or cfg.get("method", "auto")
    if method == "auto":
        method = "portal" if is_wayland() else "mss"
    if method == "portal":
        from .portal import PortalCapturer
        return PortalCapturer(fps=cfg.get("fps", 15), source=cfg.get("source", "monitor_or_window"),
                              backend=cfg.get("pipewire_backend", "auto"))
    if method == "portal_screenshot":
        from .portal_screenshot import PortalScreenshotCapturer
        return PortalScreenshotCapturer()
    if method == "mss":
        from .mss_cap import MssCapturer
        return MssCapturer(monitor=cfg.get("monitor", 1))
    if method.startswith("files:"):
        from .files import FileCapturer
        return FileCapturer(method[6:])
    raise ValueError(f"unknown capture method {method!r}")
