"""Global keyboard shortcuts (work from any app)."""
from __future__ import annotations

import logging

log = logging.getLogger("emi.hotkeys")


def register(cfg, actions: dict) -> bool:
    """actions: {"talk": fn, "type": fn, "stop": fn, "incognito": fn, "crop": fn, "end": fn}"""
    try:
        import keyboard
    except Exception as e:
        log.warning("global hotkeys unavailable: %s", e)
        return False
    defaults = {"talk": "ctrl+alt+space", "type": "alt+shift+s", "stop": "esc", "incognito": "ctrl+alt+i",
                "crop": "ctrl+alt+c", "end": "alt+x"}
    ok = True
    for name, fn in actions.items():
        combo = cfg.get(f"hotkeys.{name}", defaults.get(name))
        if not combo:
            continue
        try:
            keyboard.add_hotkey(str(combo), fn, suppress=False)
        except Exception as e:
            ok = False
            log.warning("couldn't register hotkey %s (%s): %s", name, combo, e)
    return ok
