"""Emi's icon in the tray near the clock: open the Control Center, talk, type, incognito, quit.

Needs the small `pystray` package (setup.bat installs it). Without it Emi still works; you just
open the Control Center from the ⋯ button on the island or by starting Emi again.
"""
from __future__ import annotations

import logging
import threading

from .config import ROOT

log = logging.getLogger("emi.tray")


def _icon_image():
    from PIL import Image, ImageDraw
    ico = ROOT / "emi.ico"
    if ico.exists():
        try:
            return Image.open(ico)
        except Exception:
            pass
    size = 64  # fallback: a little glossy blue orb
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(size // 2, 0, -1):
        t = i / (size / 2)
        d.ellipse((size / 2 - i, size / 2 - i, size / 2 + i, size / 2 + i),
                  fill=(int(47 + 120 * (1 - t)), int(123 + 90 * (1 - t)), 255, 255))
    d.ellipse((18, 12, 36, 26), fill=(255, 255, 255, 170))
    return img


class Tray:
    def __init__(self, name: str, actions: dict, is_incognito):
        """actions: control, talk, type, incognito, quit → callables."""
        self.name = name
        self.actions = actions
        self.is_incognito = is_incognito
        self.icon = None

    def _do(self, key):
        def run(*_):
            fn = self.actions.get(key)
            if fn:
                threading.Thread(target=fn, daemon=True, name=f"tray-{key}").start()
        return run

    def start(self) -> bool:
        try:
            import pystray
        except Exception as e:
            log.info("no tray icon (%s). Run setup.bat again to add it.", e)
            return False
        try:
            item, menu = pystray.MenuItem, pystray.Menu
            self.icon = pystray.Icon(
                "emi", _icon_image(), f"{self.name}: say “Hey {self.name}”",
                menu(item("Control Center", self._do("control"), default=True),
                     item("Talk", self._do("talk")),
                     item("Type a question", self._do("type")),
                     item("Incognito", self._do("incognito"), checked=lambda _: bool(self.is_incognito())),
                     menu.SEPARATOR,
                     item(f"Quit {self.name}", self._do("quit"))))
            threading.Thread(target=self.icon.run, daemon=True, name="tray").start()
            return True
        except Exception:
            log.exception("tray icon failed")
            return False

    def refresh(self):
        try:
            if self.icon:
                self.icon.update_menu()
        except Exception:
            pass

    def stop(self):
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass
