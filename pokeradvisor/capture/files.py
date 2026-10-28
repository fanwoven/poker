"""Replay saved screenshots as if they were the live screen."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .base import Capturer, CaptureError


class FileCapturer(Capturer):
    name = "files"

    def __init__(self, path: str):
        p = Path(path)
        self.files = sorted(p.glob("*.png")) if p.is_dir() else [p]
        if not self.files:
            raise CaptureError(f"no PNG files in {path}")
        self.i = 0

    def grab(self) -> np.ndarray:
        f = self.files[self.i % len(self.files)]
        self.i += 1
        img = cv2.imread(str(f), cv2.IMREAD_COLOR)
        if img is None:
            raise CaptureError(f"can't read {f}")
        return img
