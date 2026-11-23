"""Updates take effect by themselves: when Emi's own files change (a new version was copied in), she restarts
quietly as soon as she isn't busy, so you never have to quit and start her again by hand.
Turn off with `updates.auto_restart: false` in config.yaml."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time

from .config import ROOT

log = logging.getLogger("emi.updater")


def _files() -> dict[str, float]:
    paths = [ROOT / "main.py", ROOT / "config.yaml"]
    paths += list((ROOT / "emi").rglob("*.py")) + list((ROOT / "emi" / "web").glob("*.html"))
    out = {}
    for p in paths:
        try:
            out[str(p)] = p.stat().st_mtime
        except OSError:
            pass
    return out


def restart_command() -> list[str]:
    """How to start a fresh copy of Emi that skips the 'already running?' hand-off."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--background", "--fresh"]
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.name == "nt" and os.path.exists(pyw):
        exe = pyw   # no console window
    return [exe, str(ROOT / "main.py"), "--background", "--fresh"]


class Updater(threading.Thread):
    def __init__(self, is_idle, restart):
        super().__init__(daemon=True, name="updater")
        self.is_idle = is_idle      # callable → True when nothing is going on
        self.restart = restart      # callable that starts the new copy and quits this one

    def run(self):
        if getattr(sys, "frozen", False):
            return   # the .exe is updated by rebuilding it
        base = _files()
        while True:
            time.sleep(4)
            now = _files()
            if now == base:
                continue
            time.sleep(4)                 # let the whole update finish copying
            if _files() != now:
                continue
            log.info("my files were updated; restarting as soon as I'm free")
            while not self.is_idle():
                time.sleep(1)
            time.sleep(1.5)
            if not self.is_idle():
                continue
            self.restart()
            return


def start_fresh_copy() -> None:
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0   # detached, own process group
    subprocess.Popen(restart_command(), cwd=str(ROOT), creationflags=flags)
