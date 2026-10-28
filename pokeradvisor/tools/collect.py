"""Setup mode: quietly save table screenshots while you play or watch.

  python -m pokeradvisor.tools.collect <preset>            # until you press Ctrl+C
  python -m pokeradvisor.tools.collect <preset> --minutes 20

It checks the screen every --interval seconds and saves a screenshot only when
something in your boxes changed (new cards, new numbers, your turn...).
No windows, no questions: it never interrupts your game.
Afterwards, run the Teach screen to label what it found.
"""
from __future__ import annotations

import argparse
import hashlib
import time
from datetime import datetime

import cv2

from ..capture import make_capturer
from ..config import load_config
from ..profile import Profile


def signature(profile: Profile, frame) -> dict[str, bytes]:
    """Small fingerprint per box (ignores tiny noise by downscaling)."""
    out = {}
    for name, reg in profile.regions.items():
        crop = reg.crop(frame)
        if crop.size == 0:
            continue
        small = cv2.resize(crop, (8, 8), interpolation=cv2.INTER_AREA) // 16
        out[name] = hashlib.blake2b(small.tobytes(), digest_size=8).digest()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Save screenshots automatically for teaching.")
    ap.add_argument("preset")
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--minutes", type=float, default=0, help="stop after this long (0 = until Ctrl+C)")
    ap.add_argument("--max-files", type=int, default=600)
    a = ap.parse_args(argv)
    prof = Profile.load(a.preset)
    out = prof.dir / "captures"
    out.mkdir(parents=True, exist_ok=True)
    cap = make_capturer(load_config())
    cap.start()
    print(f"Collecting into {out}. Play normally. Ctrl+C to stop.")
    last_sig: dict = {}
    saved = 0
    t_end = time.time() + a.minutes * 60 if a.minutes else None
    try:
        while saved < a.max_files and (t_end is None or time.time() < t_end):
            t0 = time.time()
            frame = cap.grab()
            fw, fh = prof.frame_size
            if fw and (frame.shape[1], frame.shape[0]) != (fw, fh):
                print("  screen size differs from the preset; skipping", flush=True)
            else:
                sig = signature(prof, frame)
                changed = [n for n in sig if sig[n] != last_sig.get(n)]
                if changed and set(changed) - {"turn"}:
                    name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".png"
                    cv2.imwrite(str(out / name), frame)
                    saved += 1
                    print(f"  saved {name} ({', '.join(changed[:4])}{'...' if len(changed) > 4 else ''})", flush=True)
                last_sig = sig
            time.sleep(max(0.0, a.interval - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        cap.close()
    print(f"Done: {saved} screenshots. Next: python -m pokeradvisor.tools.teach {prof.name}")


if __name__ == "__main__":
    main()
