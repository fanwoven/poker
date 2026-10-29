"""Local command socket the overlay listens on (see pokeradvisor/ctl.py)."""
from __future__ import annotations

import os
import socket
import threading

from ..ctl import address


class ControlServer:
    def __init__(self, handler):
        """handler(command: str) -> reply str (called from the server thread)."""
        self.handler = handler
        self.addr = address()
        self.sock = None
        self._stop = threading.Event()

    def start(self):
        if isinstance(self.addr, tuple):
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        else:
            if os.path.exists(self.addr):
                os.remove(self.addr)
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(self.addr)
        if not isinstance(self.addr, tuple):
            os.chmod(self.addr, 0o600)  # only you can send commands
        self.sock.listen(4)
        self.sock.settimeout(0.5)
        threading.Thread(target=self._loop, daemon=True, name="control").start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            with conn:
                try:
                    conn.settimeout(2)
                    cmd = conn.recv(1024).decode(errors="replace").strip()
                    reply = self.handler(cmd) or "ok"
                except Exception as e:  # never crash the overlay over a command
                    reply = f"error: {e}"
                try:
                    conn.sendall(reply.encode())
                except OSError:
                    pass

    def stop(self):
        self._stop.set()
        if self.sock:
            self.sock.close()
        if not isinstance(self.addr, tuple) and os.path.exists(self.addr):
            os.remove(self.addr)
