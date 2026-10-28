"""mss capture: X11 and Windows (does NOT work on Wayland: black frames)."""
from __future__ import annotations

import numpy as np

from .base import Capturer


class MssCapturer(Capturer):
    name = "mss"

    def __init__(self, monitor: int = 1):
        self.monitor = monitor
        self._sct = None

    def start(self):
        import mss
        self._sct = mss.mss()

    def grab(self) -> np.ndarray:
        if self._sct is None:
            self.start()
        img = np.asarray(self._sct.grab(self._sct.monitors[self.monitor]))
        return np.ascontiguousarray(img[:, :, :3])  # BGRA -> BGR

    def close(self):
        if self._sct:
            self._sct.close()
            self._sct = None
