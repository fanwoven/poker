"""Fallback: one screenshot per call through the portal Screenshot API.
Slower (typically 100-500 ms per shot) but needs nothing except the portal."""
from __future__ import annotations

import os
from urllib.parse import unquote, urlparse

import cv2
import numpy as np

from .base import Capturer, CaptureError
from .portal import Portal


class PortalScreenshotCapturer(Capturer):
    name = "portal_screenshot"

    def __init__(self):
        self.portal: Portal | None = None

    def start(self):
        if self.portal is None:
            self.portal = Portal()

    def grab(self) -> np.ndarray:
        self.start()
        res = self.portal.request("org.freedesktop.portal.Screenshot", "Screenshot", "sa{sv}",
                                  ("", {"interactive": ("b", False)}), timeout=30)
        path = unquote(urlparse(res["uri"]).path)
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        try:
            os.remove(path)  # don't fill the Pictures folder
        except OSError:
            pass
        if img is None:
            raise CaptureError("portal screenshot could not be read")
        return img

    def close(self):
        if self.portal:
            self.portal.close()
            self.portal = None
