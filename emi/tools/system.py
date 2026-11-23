"""Media keys, volume, keyboard, clipboard, system info and PowerShell."""
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from . import IS_WINDOWS, ToolError, require_windows, tool

NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

MEDIA_KEYS = {
    "play_pause": "play/pause media", "next": "next track", "previous": "previous track",
    "stop": "stop media", "volume_up": "volume up", "volume_down": "volume down", "mute": "volume mute",
}


def _keyboard():
    try:
        import keyboard
        return keyboard
    except Exception as e:
        raise ToolError(f"Keyboard control isn't available: {e}")


def set_volume(level: int) -> None:
    level = max(0, min(100, int(level)))
    try:  # exact volume via Windows audio API (pycaw), if installed
        from pycaw.pycaw import AudioUtilities
        dev = AudioUtilities.GetSpeakers()
        vol = getattr(dev, "EndpointVolume", None)
        if vol is None:  # older pycaw versions
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import IAudioEndpointVolume
            vol = cast(dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))
        vol.SetMasterVolumeLevelScalar(level / 100.0, None)
        return
    except Exception:
        pass
    kb = _keyboard()  # fallback: each volume key press = 2%
    for _ in range(50):
        kb.send("volume down")
    for _ in range(round(level / 2)):
        kb.send("volume up")


@tool("media_control",
      "Control music/video playback and volume: play_pause, next, previous, stop, volume_up, volume_down, "
      "mute, set_volume (needs level 0-100).",
      {"action": {"type": "string", "enum": list(MEDIA_KEYS) + ["set_volume"]},
       "level": {"type": "integer", "description": "Volume 0-100, only for set_volume"}},
      ["action"], label=lambda a: "Adjusting audio")
def media_control(ctx, a):
    require_windows()
    action = a["action"]
    if action == "set_volume":
        if a.get("level") is None:
            raise ToolError("set_volume needs a level from 0 to 100.")
        set_volume(int(a["level"]))
        return f"Volume set to {int(a['level'])}%."
    if action not in MEDIA_KEYS:
        raise ToolError(f"Unknown action '{action}'.")
    kb = _keyboard()
    presses = 5 if action in ("volume_up", "volume_down") else 1
    for _ in range(presses):
        kb.send(MEDIA_KEYS[action])
    return "Done."


TERMINALS = ("windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe", "wt.exe")


def _type_confirm(a):
    """Pasting several lines into a terminal would run them, so that one is checked with you first."""
    text = a.get("text", "")
    if "\n" not in text:
        return None
    try:
        from ..winutil import foreground
        if foreground().exe in TERMINALS:
            return f"Paste these lines into the terminal (they will run)?\n{text[:300]}"
    except Exception:
        pass
    return None


@tool("type_text",
      "Type text into whatever window/field is focused right now (like the user typing). Longer text is pasted "
      "in one go. To write a whole document, prefer new_document. Never use for passwords.",
      {"text": {"type": "string"}}, ["text"], confirm=_type_confirm, label="Typing")
def type_text(ctx, a):
    require_windows()
    text = str(a["text"])
    if len(text) <= 24 and "\n" not in text:
        _keyboard().write(text, delay=0.002)
        return "Typed it."
    import time

    import pyperclip
    try:
        old = pyperclip.paste()
    except Exception:
        old = None
    pyperclip.copy(text)
    time.sleep(0.05)
    _keyboard().send("ctrl+v")
    time.sleep(0.25)
    if old is not None:
        try:
            pyperclip.copy(old)   # put your clipboard back the way it was
        except Exception:
            pass
    return "Typed it."


RISKY_KEYS = {"enter", "return", "delete", "del", "shift+delete", "alt+f4", "ctrl+w", "ctrl+shift+w", "ctrl+q"}


def _confirm_keys(a):
    keys = str(a.get("keys", "")).lower().replace(" ", "")
    parts = set(keys.split("+"))
    if keys in RISKY_KEYS or parts & {"enter", "return", "delete", "del"}:
        return f"Press {a.get('keys')}? (this can send, submit, close or delete things)"
    return None


@tool("press_keys",
      "Press a keyboard shortcut, e.g. 'ctrl+c', 'ctrl+v', 'alt+tab', 'win+d', 'ctrl+shift+t', 'enter', 'f5'.",
      {"keys": {"type": "string", "description": "Shortcut using + between keys"}}, ["keys"],
      confirm=_confirm_keys, label=lambda a: f"Pressing {a.get('keys')}")
def press_keys(ctx, a):
    require_windows()
    alias = {"win": "left windows", "windows": "left windows", "super": "left windows", "cmd": "left windows",
             "control": "ctrl", "return": "enter", "escape": "esc", "del": "delete"}
    keys = "+".join(alias.get(k.strip(), k.strip()) for k in str(a["keys"]).lower().split("+"))
    _keyboard().send(keys)
    return f"Pressed {a['keys']}."


@tool("clipboard", "Read the clipboard (action get) or put text on it (action set).",
      {"action": {"type": "string", "enum": ["get", "set"]}, "text": {"type": "string"}}, ["action"],
      label="Using the clipboard")
def clipboard(ctx, a):
    import pyperclip
    if a["action"] == "set":
        pyperclip.copy(str(a.get("text", "")))
        return "Copied to clipboard."
    text = pyperclip.paste() or ""
    return f"Clipboard contains:\n{text[:5000]}" if text else "The clipboard is empty."


@tool("system_info", "Get the time/date, battery, CPU, memory (RAM) or disk usage of this PC.",
      {"what": {"type": "string", "enum": ["time", "battery", "cpu", "memory", "disk", "all"]}}, ["what"],
      label="Checking the PC")
def system_info(ctx, a):
    import psutil
    what = a.get("what", "all")
    out = []
    if what in ("time", "all"):
        out.append(datetime.now().strftime("Time: %A %d %B %Y, %H:%M"))
    if what in ("battery", "all"):
        b = psutil.sensors_battery()
        out.append(f"Battery: {b.percent:.0f}% ({'charging' if b.power_plugged else 'on battery'})"
                   if b else "Battery: no battery info")
    if what in ("cpu", "all"):
        out.append(f"CPU: {psutil.cpu_percent(interval=0.4):.0f}% used, {psutil.cpu_count()} threads")
    if what in ("memory", "all"):
        m = psutil.virtual_memory()
        out.append(f"RAM: {m.percent:.0f}% used ({m.used / 2**30:.1f} of {m.total / 2**30:.1f} GB)")
    if what in ("disk", "all"):
        d = psutil.disk_usage(str(Path.home().anchor or "/"))
        out.append(f"Disk: {d.free / 2**30:.0f} GB free of {d.total / 2**30:.0f} GB")
    return "\n".join(out)


@tool("run_command",
      "Run a PowerShell command on this Windows PC and get its output. Powerful: use it for things no other "
      "tool covers (e.g. ffmpeg to compress a video, winget to install apps, git, zipping files, network info). "
      "The user is always asked before it runs.",
      {"command": {"type": "string", "description": "PowerShell command"},
       "timeout_seconds": {"type": "integer", "description": "Default 60, max 600"}},
      ["command"],
      confirm=lambda a: f"Run this PowerShell command?\n{a.get('command')}",
      label="Running a command")
def run_command(ctx, a):
    command = str(a["command"])
    timeout = max(5, min(int(a.get("timeout_seconds") or 60), 600))
    if IS_WINDOWS:
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command]
    else:  # lets you test on Mac/Linux
        args = [shutil.which("bash") or "sh", "-c", command]
    try:
        out = subprocess.run(args, capture_output=True, timeout=timeout, cwd=str(Path.home()),
                             creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise ToolError(f"The command took longer than {timeout}s and was stopped.")
    stdout = out.stdout.decode("utf-8", errors="replace").strip()
    stderr = out.stderr.decode("utf-8", errors="replace").strip()
    parts = [f"exit code {out.returncode}"]
    if stdout:
        parts.append("output:\n" + stdout[-6000:])
    if stderr:
        parts.append("errors:\n" + stderr[-2500:])
    return "\n".join(parts)



def _confirm_proc(a):
    return f"End the process '{a.get('name')}'? Unsaved work in it will be lost." if a.get("action") == "kill" else None


@tool("processes", "List running programs (by memory use) or end/kill one by name, e.g. 'chrome' or 'notepad.exe'.",
      {"action": {"type": "string", "enum": ["list", "kill"]},
       "name": {"type": "string", "description": "Process name for kill, e.g. 'spotify'"}},
      ["action"], confirm=_confirm_proc, label=lambda a: "Checking running programs" if a.get("action") == "list"
      else f"Closing {a.get('name')}")
def processes(ctx, a):
    import psutil
    if a["action"] == "list":
        procs = []
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                procs.append((p.info["memory_info"].rss, p.info["name"]))
            except Exception:
                continue
        totals: dict[str, int] = {}
        for rss, name in procs:
            totals[name] = totals.get(name, 0) + rss
        top = sorted(totals.items(), key=lambda x: -x[1])[:25]
        return "Top programs by memory:\n" + "\n".join(f"{n}: {r / 2**20:.0f} MB" for n, r in top)
    target = str(a.get("name") or "").lower().removesuffix(".exe")
    if not target:
        raise ToolError("Which process? Give its name.")
    protected = {"system", "explorer", "csrss", "wininit", "winlogon", "lsass", "services", "smss", "svchost",
                 "dwm", "python", "pythonw"}
    if target in protected:
        raise ToolError(f"'{target}' is part of Windows (or me) — I won't end it.")
    killed = 0
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower().removesuffix(".exe") == target:
                p.terminate()
                killed += 1
        except Exception:
            continue
    return f"Ended {killed} '{target}' process(es)." if killed else f"No running process called '{target}'."


def _confirm_power(a):
    act = a.get("action")
    if act in ("shutdown", "restart", "log_off", "sleep"):
        when = f" in {a.get('delay_minutes')} minutes" if a.get("delay_minutes") else " now"
        return f"{act.replace('_', ' ').capitalize()} the PC{when}? Save your work first."
    return None


@tool("power", "Lock the PC, put it to sleep, shut down, restart, log off, or cancel a scheduled shutdown.",
      {"action": {"type": "string", "enum": ["lock", "sleep", "shutdown", "restart", "log_off", "cancel"]},
       "delay_minutes": {"type": "integer", "description": "For shutdown/restart: wait this long first"}},
      ["action"], confirm=_confirm_power, label=lambda a: f"{str(a.get('action')).replace('_', ' ').capitalize()}")
def power(ctx, a):
    require_windows()
    import ctypes
    act = a["action"]
    secs = max(0, int(a.get("delay_minutes") or 0) * 60)
    if act == "lock":
        ctypes.windll.user32.LockWorkStation()
        return "Locked."
    if act == "sleep":
        subprocess.Popen(["powershell", "-NoProfile", "-Command",
                          "Add-Type -AssemblyName System.Windows.Forms; "
                          "[System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)"],
                         creationflags=NO_WINDOW)
        return "Going to sleep."
    args = {"shutdown": ["/s", "/t", str(secs)], "restart": ["/r", "/t", str(secs)],
            "log_off": ["/l"], "cancel": ["/a"]}[act]
    subprocess.run(["shutdown", *args], creationflags=NO_WINDOW)
    return "Cancelled any scheduled shutdown." if act == "cancel" else f"{act.capitalize()} scheduled."
