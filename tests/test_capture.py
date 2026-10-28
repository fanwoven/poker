import shutil, subprocess, sys
from pathlib import Path
import pytest


@pytest.mark.skipif(not shutil.which("dbus-run-session"), reason="no dbus")
def test_portal_dbus_conversation(tmp_path):
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(["dbus-run-session", "--", sys.executable, str(root / "tests" / "portal_flow_check.py"),
                          str(tmp_path / "token")], capture_output=True, text=True, timeout=60, cwd=root)
    assert "PORTAL FLOW OK" in out.stdout, out.stdout + out.stderr


def test_file_capturer(tmp_path):
    import cv2, numpy as np
    from pokeradvisor.capture import make_capturer
    cv2.imwrite(str(tmp_path / "a.png"), np.zeros((5, 6, 3), np.uint8))
    cap = make_capturer(method=f"files:{tmp_path}")
    assert cap.grab().shape == (5, 6, 3)
