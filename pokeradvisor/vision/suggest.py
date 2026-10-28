"""Optional label SUGGESTIONS from a local AI (Ollama vision model) or Tesseract.

Only used in the Teach screen, never during live play, and never trusted
automatically: you always confirm. Everything stays on your PC.
"""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
import time
import urllib.request

import cv2
import numpy as np

PROMPTS = {
    "rank": "This image shows the rank symbol from the corner of a playing card. "
            "Answer with exactly one of: 2 3 4 5 6 7 8 9 10 J Q K A. Nothing else.",
    "suit": "This image shows a playing card suit symbol. Answer with exactly one word: "
            "spades, hearts, diamonds or clubs.",
    "char": "This image shows ONE character from a number or a button label in a game. "
            "Answer with only that single character (a digit, a letter, a comma or a dot).",
}
SUIT_WORDS = {"spades": "s", "spade": "s", "hearts": "h", "heart": "h",
              "diamonds": "d", "diamond": "d", "clubs": "c", "club": "c"}


def _png_b64(img: np.ndarray, scale: int = 6) -> str:
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    if big.ndim == 2:  # glyph thumbs are white-on-black ink; show dark-on-white
        big = 255 - big
    pad = cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    ok, buf = cv2.imencode(".png", pad)
    return base64.b64encode(buf.tobytes()).decode()


class OllamaSuggester:
    def __init__(self, model: str, url: str = "http://127.0.0.1:11434", timeout: float = 60):
        self.model, self.url, self.timeout = model, url.rstrip("/"), timeout

    def _post(self, path, payload, timeout=None):
        req = urllib.request.Request(self.url + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
            return json.loads(r.read())

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/api/tags", timeout=2) as r:
                tags = json.loads(r.read())
            return any(m.get("name", "").split(":")[0] == self.model.split(":")[0] for m in tags.get("models", []))
        except Exception:
            return False

    def gpu_report(self) -> str:
        """Is the model loaded on the GPU? (Ollama /api/ps size_vram)"""
        try:
            with urllib.request.urlopen(self.url + "/api/ps", timeout=2) as r:
                ps = json.loads(r.read())
        except Exception as e:
            return f"Ollama not reachable: {e}"
        for m in ps.get("models", []):
            if m.get("name", "").split(":")[0] == self.model.split(":")[0]:
                vram, size = m.get("size_vram", 0), m.get("size", 1)
                return f"{m['name']}: {100 * vram / max(size, 1):.0f}% on GPU ({vram / 1e9:.1f} GB VRAM)"
        return f"{self.model} is not loaded right now"

    def suggest(self, kind: str, img: np.ndarray) -> tuple[str, float]:
        """-> (suggested label or '', seconds taken)"""
        t0 = time.time()
        prompt = PROMPTS.get(kind)
        if not prompt:
            return "", 0.0
        try:
            res = self._post("/api/generate", {"model": self.model, "prompt": prompt, "stream": False,
                                               "images": [_png_b64(img)], "options": {"temperature": 0}})
        except Exception:
            return "", time.time() - t0
        ans = res.get("response", "").strip().strip(".").strip()
        dt = time.time() - t0
        if kind == "suit":
            return SUIT_WORDS.get(ans.lower().split()[0] if ans else "", ""), dt
        if kind == "rank":
            a = ans.upper().split()[0] if ans else ""
            return ("T" if a == "10" else a) if a in {"2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"} else "", dt
        return (ans[0] if len(ans) == 1 else ""), dt


class TesseractSuggester:
    """Single-character OCR suggestion (only if 'tesseract' is installed)."""

    def available(self) -> bool:
        return shutil.which("tesseract") is not None

    def suggest(self, kind: str, img: np.ndarray) -> tuple[str, float]:
        if kind != "char":
            return "", 0.0
        t0 = time.time()
        big = 255 - cv2.resize(img, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        ok, buf = cv2.imencode(".png", cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255))
        try:
            out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "10"], input=buf.tobytes(),
                                 capture_output=True, timeout=10).stdout.decode().strip()
        except Exception:
            return "", time.time() - t0
        return (out[0] if len(out) == 1 else ""), time.time() - t0
