"""Open apps and manage windows."""
from __future__ import annotations

import difflib
import json
import os
import subprocess
import time
from pathlib import Path

from . import IS_WINDOWS, ToolError, require_windows, tool

NO_WINDOW = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW: don't flash a console

BUILTIN = {
    "settings": "ms-settings:", "windows settings": "ms-settings:",
    "bluetooth settings": "ms-settings:bluetooth", "wifi settings": "ms-settings:network-wifi",
    "display settings": "ms-settings:display", "sound settings": "ms-settings:sound",
    "calculator": "calc.exe", "notepad": "notepad.exe", "paint": "mspaint.exe",
    "file explorer": "explorer.exe", "explorer": "explorer.exe", "files": "explorer.exe",
    "task manager": "taskmgr.exe", "command prompt": "cmd.exe", "cmd": "cmd.exe",
    "powershell": "powershell.exe", "terminal": "wt.exe", "control panel": "control.exe",
    "snipping tool": "ms-screenclip:", "camera": "microsoft.windows.camera:",
    "microsoft store": "ms-windows-store:", "store": "ms-windows-store:",
}

_cache: dict = {"time": 0.0, "items": {}}


def _ps(command: str, timeout: int = 20) -> str:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command],
        capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    return out.stdout.decode("utf-8", errors="replace")


def _installed_apps() -> dict[str, str]:
    """name -> launch target, from the Start menu + Store apps. Cached for 5 minutes."""
    if time.time() - _cache["time"] < 300 and _cache["items"]:
        return _cache["items"]
    items: dict[str, str] = {}
    roots = [Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
             Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"]
    for root in roots:
        if root.exists():
            for p in root.rglob("*"):
                if p.suffix.lower() in (".lnk", ".url", ".appref-ms") and "uninstall" not in p.stem.lower():
                    items.setdefault(p.stem.lower(), str(p))
    try:  # Store / UWP apps (Spotify from the Store, WhatsApp, Settings pages...)
        data = json.loads(_ps("Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress") or "[]")
        for app in data if isinstance(data, list) else [data]:
            name, app_id = (app.get("Name") or "").lower(), app.get("AppID")
            if name and app_id:
                items.setdefault(name, "shell:AppsFolder\\" + app_id)
    except Exception:
        pass
    _cache.update(time=time.time(), items=items)
    return items


def best_match(query: str, names: list[str]) -> str | None:
    q = query.lower().strip()
    if q in names:
        return q
    starts = [n for n in names if n.startswith(q)]
    if starts:
        return min(starts, key=len)
    contains = [n for n in names if q in n]
    if contains:
        return min(contains, key=len)
    close = difflib.get_close_matches(q, names, n=1, cutoff=0.6)
    return close[0] if close else None


def _launch(target: str) -> None:
    if target.startswith("shell:AppsFolder"):
        subprocess.Popen(["explorer.exe", target], creationflags=NO_WINDOW)
    else:
        os.startfile(target)  # ShellExecute — no shell parsing, safe with odd names


@tool("open_app",
      "Open/launch an installed application by name, e.g. 'Spotify', 'Discord', 'Chrome', 'VS Code', "
      "'Settings', 'Calculator', 'File Explorer'.",
      {"name": {"type": "string", "description": "The app's name"}}, ["name"],
      label=lambda a: f"Opening {a.get('name')}")
def open_app(ctx, a):
    require_windows()
    name = str(a["name"]).strip()
    key = name.lower()
    if key in BUILTIN:
        _launch(BUILTIN[key])
        return f"Opened {name}."
    apps = _installed_apps()
    match = best_match(key, list(apps))
    if match:
        _launch(apps[match])
        return f"Opened '{match}'."
    try:
        os.startfile(name)  # works for things registered in App Paths, e.g. 'chrome', 'winword'
        return f"Asked Windows to start '{name}'."
    except OSError:
        raise ToolError(f"I couldn't find an installed app called '{name}'.")


def _windows():
    import pygetwindow as gw  # Windows only
    return [w for w in gw.getAllWindows() if w.title and w.title.strip() and w.width > 0]


def _find_window(title: str):
    wins = _windows()
    titles = [w.title.lower() for w in wins]
    m = best_match(title, titles)
    if not m:
        raise ToolError(f"No open window matches '{title}'.")
    return wins[titles.index(m)]


def _confirm_window(a):
    if a.get("action") == "close":
        return f"Close the window '{a.get('title')}'? Unsaved work there could be lost."
    return None


@tool("window_control",
      "See and control open windows. action: list (show open windows), focus (bring to front), "
      "minimize, maximize, restore, close, minimize_all (show desktop).",
      {"action": {"type": "string", "enum": ["list", "focus", "minimize", "maximize", "restore", "close",
                                             "minimize_all"]},
       "title": {"type": "string", "description": "Part of the window title, e.g. 'Spotify' or 'Chrome'"}},
      ["action"], confirm=_confirm_window,
      label=lambda a: f"{a.get('action', '').replace('_', ' ').capitalize()} {a.get('title', '')}".strip())
def window_control(ctx, a):
    require_windows()
    action = a.get("action")
    if action == "list":
        seen, out = set(), []
        for w in _windows():
            if w.title not in seen and w.visible:
                seen.add(w.title)
                out.append(("[min] " if w.isMinimized else "") + w.title)
        return "Open windows:\n" + "\n".join(out[:40]) if out else "No open windows."
    if action == "minimize_all":
        _ps("(New-Object -ComObject Shell.Application).MinimizeAll()")
        return "Minimized everything."
    title = a.get("title")
    if not title:
        raise ToolError("Which window? Give part of its title.")
    w = _find_window(title)
    if action == "focus":
        try:
            if w.isMinimized:
                w.restore()
            w.activate()
        except Exception:  # Windows sometimes blocks focus-stealing; this trick usually works
            w.minimize()
            w.restore()
    elif action == "minimize":
        w.minimize()
    elif action == "maximize":
        w.maximize()
    elif action == "restore":
        w.restore()
    elif action == "close":
        w.close()
    else:
        raise ToolError(f"Unknown action '{action}'.")
    return f"{action.capitalize()}d '{w.title}'." if action != "focus" else f"Focused '{w.title}'."
