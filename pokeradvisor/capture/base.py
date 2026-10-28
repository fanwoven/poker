"""Common interface for all capture methods."""
from __future__ import annotations

import numpy as np


class CaptureError(RuntimeError):
    pass


class Capturer:
    name = "base"

    def start(self) -> None:
        """Prepare (may show a one-time permission dialog). Call BEFORE play."""

    def grab(self) -> np.ndarray:
        """Newest frame as a BGR numpy array (height, width, 3)."""
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *a):
        self.close()
