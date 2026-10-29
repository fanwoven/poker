"""Benchmark the capture methods on THIS computer.

  python -m pokeradvisor.capture.bench            # the method the advisor uses
  python -m pokeradvisor.capture.bench portal     # just one

Prints: start-up time, ms per grab, frames per second, frame size.
Saves one frame per method into data/bench_<method>.png so you can check
it is not black.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

from . import is_wayland, make_capturer

OUT = Path(__file__).resolve().parents[2] / "data"


def bench(method: str, seconds: float = 5.0):
    print(f"\n=== {method} ===")
    try:
        t0 = time.perf_counter()
        cap = make_capturer(method=method)
        cap.start()
        start_ms = (time.perf_counter() - t0) * 1000
        img = cap.grab()
        print(f"  started in {start_ms:.0f} ms, frame {img.shape[1]}x{img.shape[0]}")
        times = []
        distinct = 0
        last = None
        t_end = time.perf_counter() + seconds
        n = 0
        while time.perf_counter() < t_end and n < 200:
            t = time.perf_counter()
            img = cap.grab()
            times.append((time.perf_counter() - t) * 1000)
            if last is None or img is not last:
                distinct += 1
            last = img
            n += 1
            if method == "portal":
                time.sleep(0.02)
        if hasattr(cap, "frames"):
            print(f"  new frames received: {cap.frames} (screen changes + keepalive)")
        if hasattr(cap, "frame_age_ms"):
            print(f"  newest frame age: {cap.frame_age_ms():.0f} ms")
        if hasattr(cap, "backend") and isinstance(cap.backend, str):
            print(f"  backend: {cap.backend}")
        times.sort()
        print(f"  grab: median {times[len(times)//2]:.1f} ms, worst {times[-1]:.1f} ms ({len(times)} grabs)")
        black = float(np.mean(img)) < 3
        OUT.mkdir(exist_ok=True)
        cv2.imwrite(str(OUT / f"bench_{method}.png"), img)
        print(f"  saved data/bench_{method}.png" + ("  WARNING: frame is black!" if black else ""))
        cap.close()
        return True
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        return False


def main():
    # portal_screenshot is NOT tested by default: GNOME flashes the screen and
    # shows a "Screenshot captured" notice for every shot. Test it only on request:
    #   python -m pokeradvisor.capture.bench portal_screenshot
    methods = sys.argv[1:] or (["portal"] if is_wayland() else ["mss"])
    print("Wayland session" if is_wayland() else "X11 / Windows session")
    for m in methods:
        bench(m, seconds=5 if m != "portal_screenshot" else 3)


if __name__ == "__main__":
    main()
