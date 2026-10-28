"""Runs inside dbus-run-session together with fake_portal.py."""
from pathlib import Path

import subprocess, sys, time, faulthandler; faulthandler.dump_traceback_later(8, exit=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

srv = subprocess.Popen([sys.executable, str(Path(__file__).with_name("fake_portal.py"))], stdout=subprocess.PIPE, text=True)
srv.stdout.readline()
from pokeradvisor.capture import portal as P
P.TOKEN_FILE = Path(sys.argv[1])
cap = P.PortalCapturer()
fd, node, size = cap._open_session()
assert node == 42 and size == (1920, 1080) and fd > 2, (fd, node, size)
assert P.TOKEN_FILE.read_text() == "tok123"
cap.portal.close()
# second time: restore token is sent
cap2 = P.PortalCapturer(); cap2._open_session(); cap2.portal.close()
from pokeradvisor.capture.portal_screenshot import PortalScreenshotCapturer
img = PortalScreenshotCapturer().grab()
assert img.shape == (10, 20, 3)
srv.kill()
print("PORTAL FLOW OK")
