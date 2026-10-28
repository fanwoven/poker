"""Wayland capture through xdg-desktop-portal ScreenCast + PipeWire.

How it works:
  1. Ask the desktop portal (D-Bus) for a screen-cast session. The FIRST time,
     GNOME/KDE shows a dialog where you pick the screen or the poker window.
     We save a "restore token" so later sessions start without the dialog.
  2. The portal gives us a PipeWire stream. GStreamer (pipewiresrc) turns it
     into raw frames, and a background thread always keeps the newest frame.
  3. grab() just returns that newest frame: about 0 ms.

D-Bus talk uses 'jeepney' (pure Python, installed in the venv).
Frames come from GStreamer, either in-process (needs the system 'gi' module,
venv created with --system-site-packages) or from a 'gst-launch-1.0'
subprocess (works without 'gi').
"""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from .base import Capturer, CaptureError

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
TOKEN_FILE = Path(__file__).resolve().parents[2] / "data" / "portal_restore_token"


class Portal:
    """Minimal xdg-desktop-portal client (request/response pattern)."""

    def __init__(self):
        try:
            from jeepney.io.blocking import open_dbus_connection
        except ImportError as e:  # pragma: no cover
            raise CaptureError("python package 'jeepney' missing: pip install jeepney") from e
        self.conn = open_dbus_connection(bus="SESSION", enable_fds=True)
        self.sender = self.conn.unique_name[1:].replace(".", "_")

    def addr(self, interface: str):
        from jeepney import DBusAddress
        return DBusAddress(PORTAL_PATH, bus_name=PORTAL_BUS, interface=interface)

    def call(self, interface, method, signature, args, timeout=30):
        """Plain method call, returns the reply body."""
        from jeepney import new_method_call
        from jeepney.wrappers import unwrap_msg
        reply = self.conn.send_and_get_reply(new_method_call(self.addr(interface), method, signature, args),
                                             timeout=timeout)
        return unwrap_msg(reply)

    def request(self, interface, method, signature, args, timeout=180) -> dict:
        """Call a portal method that answers later with a Request::Response signal."""
        from jeepney import MatchRule
        from jeepney.bus_messages import message_bus
        token = "pa" + secrets.token_hex(6)
        args = list(args)
        args[-1] = dict(args[-1], handle_token=("s", token))
        path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{token}"
        rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request",
                         member="Response", path=path)
        self.conn.send_and_get_reply(message_bus.AddMatch(rule), timeout=10)
        with self.conn.filter(rule) as queue:
            self.call(interface, method, signature, tuple(args))
            msg = self.conn.recv_until_filtered(queue, timeout=timeout)
        code, results = msg.body
        if code == 1:
            raise CaptureError("you cancelled the screen sharing dialog")
        if code != 0:
            raise CaptureError(f"portal {method} failed (code {code})")
        return {k: v[1] for k, v in results.items()}

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


def _gi_available() -> bool:
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # noqa: F401
        return True
    except Exception:
        return False


class PortalCapturer(Capturer):
    name = "portal"

    def __init__(self, fps: int = 15, source: str = "monitor_or_window", backend: str = "auto"):
        self.fps = fps
        self.types = {"monitor": 1, "window": 2}.get(source, 3)
        self.backend = backend
        self.portal: Portal | None = None
        self._frame: np.ndarray | None = None
        self._frame_time = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None
        self._pipeline = None
        self.size: tuple[int, int] | None = None
        self.frames = 0

    # ----------------------------------------------------------- session
    def _open_session(self) -> tuple[int, int, tuple[int, int] | None]:
        p = self.portal = Portal()
        iface = "org.freedesktop.portal.ScreenCast"
        res = p.request(iface, "CreateSession", "a{sv}",
                        ({"session_handle_token": ("s", "ps" + secrets.token_hex(6))},))
        session = res["session_handle"]
        opts = {"types": ("u", self.types), "multiple": ("b", False),
                "cursor_mode": ("u", 1), "persist_mode": ("u", 2)}
        if TOKEN_FILE.exists():
            opts["restore_token"] = ("s", TOKEN_FILE.read_text().strip())
        p.request(iface, "SelectSources", "oa{sv}", (session, opts))
        res = p.request(iface, "Start", "osa{sv}", (session, "", {}))
        if "restore_token" in res:
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_FILE.write_text(res["restore_token"])
        streams = res.get("streams") or []
        if not streams:
            raise CaptureError("portal returned no video stream")
        node_id, props = streams[0]
        size = props.get("size", (None, None))[1] if "size" in props else None
        fd_obj = p.call(iface, "OpenPipeWireRemote", "oa{sv}", (session, {}))[0]
        fd = fd_obj.to_raw_fd() if hasattr(fd_obj, "to_raw_fd") else int(fd_obj)
        return fd, node_id, tuple(size) if size else None

    def start(self):
        if self._thread:
            return
        fd, node, size = self._open_session()
        use_gi = self.backend == "gi" or (self.backend == "auto" and _gi_available())
        if use_gi:
            self._start_gi(fd, node)
        else:
            if not size:
                raise CaptureError("stream size unknown; install system 'gi' or choose a monitor")
            self._start_subprocess(fd, node, size)
        t0 = time.time()
        while self._frame is None and time.time() - t0 < 8:
            time.sleep(0.02)
        if self._frame is None:
            self.close()
            raise CaptureError("no frames from PipeWire within 8 s")

    # -------------------------------------------------- in-process GStreamer
    def _start_gi(self, fd: int, node: int):
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        desc = (f"pipewiresrc fd={fd} path={node} always-copy=true keepalive-time=1000 ! "
                f"videorate max-rate={self.fps} drop-only=true ! videoconvert ! "
                "video/x-raw,format=BGRx ! appsink name=sink max-buffers=1 drop=true sync=false")
        self._pipeline = Gst.parse_launch(desc)
        sink = self._pipeline.get_by_name("sink")
        self._pipeline.set_state(Gst.State.PLAYING)
        self.backend = "gi"

        def loop():
            while not self._stop.is_set():
                sample = sink.emit("try-pull-sample", 200 * Gst.MSECOND)
                if sample is None:
                    continue
                st = sample.get_caps().get_structure(0)
                w, h = st.get_value("width"), st.get_value("height")
                buf = sample.get_buffer()
                ok, info = buf.map(Gst.MapFlags.READ)
                if not ok:
                    continue
                try:
                    arr = np.frombuffer(info.data, np.uint8)
                    stride = arr.size // h
                    img = arr[: stride * h].reshape(h, stride)[:, : w * 4].reshape(h, w, 4)[:, :, :3].copy()
                finally:
                    buf.unmap(info)
                self._store(img)

        self._thread = threading.Thread(target=loop, daemon=True, name="pipewire-gi")
        self._thread.start()

    # ------------------------------------------------ gst-launch subprocess
    def _start_subprocess(self, fd: int, node: int, size: tuple[int, int]):
        exe = shutil.which("gst-launch-1.0")
        if not exe:
            raise CaptureError("gst-launch-1.0 not found (GStreamer missing)")
        w, h = size
        self.size = (w, h)
        cmd = [exe, "-q", "pipewiresrc", f"fd={fd}", f"path={node}", "always-copy=true",
               "keepalive-time=1000", "!", "videorate", f"max-rate={self.fps}", "drop-only=true", "!",
               "videoconvert", "!", "videoscale", "!",
               f"video/x-raw,format=BGRx,width={w},height={h}", "!", "fdsink", "fd=1", "sync=false"]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      pass_fds=(fd,), bufsize=0)
        self.backend = "gst-launch"
        frame_bytes = w * h * 4

        def loop():
            out = self._proc.stdout
            buf = bytearray(frame_bytes)
            view = memoryview(buf)
            while not self._stop.is_set():
                got = 0
                while got < frame_bytes:
                    n = out.readinto(view[got:])
                    if not n:
                        return
                    got += n
                img = np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, :3].copy()
                self._store(img)

        self._thread = threading.Thread(target=loop, daemon=True, name="pipewire-gst")
        self._thread.start()

    # ------------------------------------------------------------- common
    def _store(self, img):
        with self._lock:
            self._frame = img
            self._frame_time = time.time()
            self.frames += 1

    def grab(self) -> np.ndarray:
        if self._thread is None:
            self.start()
        with self._lock:
            if self._frame is None:
                raise CaptureError("no frame yet")
            return self._frame

    def frame_age_ms(self) -> float:
        return (time.time() - self._frame_time) * 1000

    def close(self):
        self._stop.set()
        if self._pipeline is not None:
            from gi.repository import Gst
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
        if self._proc:
            self._proc.terminate()
            self._proc = None
        if self.portal:
            self.portal.close()
            self.portal = None
        self._thread = None


def forget_permission():
    """Delete the saved restore token, so the share dialog shows again."""
    if TOKEN_FILE.exists():
        os.remove(TOKEN_FILE)
