"""Gaming mode: when a game is in front, Emi keeps her island away (so it never covers or minimises the game),
pauses proactive screen checks, and answers by voice only. Saying her name still works."""
from __future__ import annotations

import logging
import threading
import time

from . import winutil

log = logging.getLogger("emi.gaming")

GAME_FOLDERS = ("\\steamapps\\common\\", "\\epic games\\", "\\riot games\\", "\\xboxgames\\", "\\gog galaxy\\games\\",
                "\\ea games\\", "\\ubisoft game launcher\\games\\", "\\battle.net\\", "\\modifiablewindowsapps\\")
DEFAULT_GAMES = {"minecraft.windows.exe", "minecraftlauncher.exe", "terraria.exe", "eldenring.exe",
                 "valorant-win64-shipping.exe", "fortniteclient-win64-shipping.exe", "cs2.exe", "robloxplayerbeta.exe",
                 "league of legends.exe", "gta5.exe", "rocketleague.exe", "overwatch.exe", "r5apex.exe",
                 "eurotrucks2.exe", "worms 3d.exe", "wormsmayhem.exe"}
NOT_GAMES = {"explorer.exe", "chrome.exe", "msedge.exe", "firefox.exe", "code.exe", "vlc.exe", "powerpnt.exe",
             "pythonw.exe", "python.exe", "emi.exe", "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe"}


def looks_like_game(fg: winutil.Foreground, extra_games: set[str], notification_state: int) -> bool:
    exe = (fg.exe or "").lower()
    if not exe or exe in NOT_GAMES:
        return False
    if notification_state == 3:                      # Windows says: Direct3D game running fullscreen
        return True
    if exe in DEFAULT_GAMES or exe in extra_games:
        return True
    path = (fg.path or "").lower()
    if any(folder in path for folder in GAME_FOLDERS):
        return True
    # Minecraft Java runs as javaw.exe — but so does Eclipse, so check the window title too
    if exe == "javaw.exe" and "minecraft" in (fg.title or "").lower():
        return True
    return False


class GamingWatcher(threading.Thread):
    def __init__(self, cfg, state, on_change):
        super().__init__(daemon=True, name="gaming")
        self.cfg, self.state, self.on_change = cfg, state, on_change
        self.extra = {str(g).lower() for g in (cfg.get("gaming.games", []) or [])}

    def run(self):
        hits = 0
        while True:
            time.sleep(4)
            try:
                if not getattr(self.state, "gaming_auto", True):
                    is_game = False
                else:
                    fg = winutil.foreground()
                    is_game = looks_like_game(fg, self.extra, winutil.notification_state())
                # need two checks in a row to switch on (alt-tabbing through a game shouldn't flip it)
                hits = hits + 1 if is_game else 0
                want = hits >= 2 or (is_game and getattr(self.state, "gaming", False))
                if want != getattr(self.state, "gaming", False):
                    self.state.set("gaming", want)
                    log.info("gaming mode %s", "on" if want else "off")
                    self.on_change(want)
            except Exception:
                log.exception("gaming check failed")
