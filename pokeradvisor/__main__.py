"""Start the poker advisor.

  python -m pokeradvisor <preset>              live overlay (auto mode)
  python -m pokeradvisor <preset> --manual     only read when you press your "read" key
  python -m pokeradvisor --practice            practice window only (type hands in)
  python -m pokeradvisor <preset> --capture files:some/folder   replay screenshots (testing)
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description="Local poker advisor overlay.")
    ap.add_argument("preset", nargs="?", help="table preset made with the calibration tool")
    ap.add_argument("--practice", action="store_true", help="open only the practice window")
    ap.add_argument("--manual", action="store_true", help="start with auto mode off")
    ap.add_argument("--capture", default=None, help="capture method: auto, portal, portal_screenshot, mss, files:DIR")
    a = ap.parse_args(argv)

    from .config import load_config
    cfg = load_config()
    # On Wayland, "always on top" only works for X11 windows: run the overlay through XWayland.
    if sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = cfg.get("overlay", {}).get("qt_platform", "xcb")

    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    if a.practice or not a.preset:
        from .engine.strategy import Engine
        from .live.widgets import PracticeWindow
        w = PracticeWindow(Engine(cfg))
        w.show()
        return app.exec()

    from .capture import make_capturer
    from .live.advisor import Advisor
    from .live.control import ControlServer
    from .live.overlay import Overlay
    from .profile import Profile
    from .stats.db import HandDB

    prof = Profile.load(a.preset)
    missing = prof.missing_required()
    if missing:
        print("This preset is missing boxes: " + ", ".join(missing))
        print(f"Run: python -m pokeradvisor.tools.calibrate {prof.name}")
    cap = make_capturer(cfg, a.capture)
    print("Starting screen capture (the first time, your desktop asks what to share)...")
    cap.start()
    db = HandDB()
    adv = Advisor(cfg, prof, cap, db=db)
    if a.manual:
        adv.auto = False
    ov = Overlay(adv, cfg, db)
    adv.on_update = ov.bridge.update.emit
    ctl = ControlServer(ov.handle_command)
    ctl.start()
    adv.start()
    ov.show()
    print("Overlay running. Commands: bin/pa-ctl read | auto | lock | opp | deviate | grid | practice | stats | quit")
    try:
        code = app.exec()
    finally:
        adv.stop()
        ctl.stop()
        cap.close()
        from .stats.report import report
        print("\n" + report(db, adv.session))
    return code


if __name__ == "__main__":
    sys.exit(main())
