"""Tiny command tool to control the running overlay (bind these to keys).

  pa-ctl read        read the table now and show advice
  pa-ctl auto        auto mode on/off
  pa-ctl lock        click-through lock on/off (overlay ignores the mouse)
  pa-ctl opp         cycle number of opponents (auto, 1..8)
  pa-ctl pos BTN     set my position (pa-ctl pos = back to automatic)
  pa-ctl bb 20000    set the big blind
  pa-ctl deviate     mark "I did NOT follow the advice" for this hand
  pa-ctl grid        show/hide the opponent range grid
  pa-ctl practice    open the practice (manual entry) window
  pa-ctl stats       open the results window
  pa-ctl status      print what the overlay sees
  pa-ctl quit        close the overlay

Standard library only, so it starts fast.
"""
import os
import socket
import sys

TCP_PORT = 47533


def address():
    if sys.platform.startswith("win"):
        return ("127.0.0.1", TCP_PORT)
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(base, f"pokeradvisor-{os.getuid()}.sock")


def send(cmd: str, timeout: float = 3.0) -> str:
    addr = address()
    fam = socket.AF_INET if isinstance(addr, tuple) else socket.AF_UNIX
    with socket.socket(fam, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(addr)
        s.sendall((cmd.strip() + "\n").encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
    return data.decode(errors="replace").strip()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    try:
        print(send(" ".join(sys.argv[1:])))
    except (FileNotFoundError, ConnectionRefusedError):
        print("The overlay is not running.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
