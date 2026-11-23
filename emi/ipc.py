"""Single-instance plumbing: lets the summon shortcut (or a second copy of Emi) reach the copy that's
already running. Uses a private loopback socket (127.0.0.1 only) and a random token. Standard library
only, so the summon shortcut starts fast."""
from __future__ import annotations

import json
import os
import secrets
import socket
import threading
from pathlib import Path

import sys

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
INFO = ROOT / "data" / "running.json"


def send(command: str, timeout: float = 1.5) -> bool:
    """Ask a running Emi to do something. Returns False if Emi isn't running."""
    try:
        info = json.loads(INFO.read_text(encoding="utf-8"))
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=timeout) as s:
            s.sendall(f"{info['token']} {command}\n".encode())
            s.settimeout(timeout)
            return s.recv(8).startswith(b"ok")
    except (OSError, ValueError, KeyError):
        return False


class Server(threading.Thread):
    def __init__(self, handlers: dict):
        super().__init__(daemon=True, name="ipc")
        self.handlers = handlers
        self.token = secrets.token_hex(16)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        INFO.parent.mkdir(exist_ok=True)
        INFO.write_text(json.dumps({"port": self.sock.getsockname()[1], "token": self.token, "pid": os.getpid()}),
                        encoding="utf-8")

    def run(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(2)
                    line = conn.recv(256).decode("utf-8", "replace").strip()
                    token, _, command = line.partition(" ")
                    fn = self.handlers.get(command) if secrets.compare_digest(token, self.token) else None
                    if fn:
                        conn.sendall(b"ok\n")
                        threading.Thread(target=fn, daemon=True).start()
                    else:
                        conn.sendall(b"no\n")
                except OSError:
                    pass

    def close(self):
        try:
            self.sock.close()
            INFO.unlink(missing_ok=True)
        except OSError:
            pass
