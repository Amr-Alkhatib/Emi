"""Small Windows helpers (mouse, foreground window, idle time, fullscreen detection) via ctypes.
Everything degrades to harmless defaults on other systems so the rest of Emi stays testable."""
from __future__ import annotations

import ctypes
import os
import sys
import time
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"


@dataclass
class Foreground:
    title: str = ""
    exe: str = ""          # e.g. "eldenring.exe"
    path: str = ""         # full exe path
    rect: tuple = (0, 0, 0, 0)   # left, top, right, bottom (physical pixels)
    pid: int = 0


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def cursor_pos() -> tuple[int, int]:
    if not IS_WINDOWS:
        return (0, 0)
    pt = _POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


def foreground() -> Foreground:
    if not IS_WINDOWS:
        return Foreground()
    u32 = ctypes.windll.user32
    hwnd = u32.GetForegroundWindow()
    if not hwnd:
        return Foreground()
    n = u32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, buf, n + 1)
    r = _RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    pid = ctypes.c_ulong()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    path = ""
    try:
        import psutil
        path = psutil.Process(pid.value).exe()
    except Exception:
        pass
    return Foreground(buf.value, os.path.basename(path).lower(), path, (r.left, r.top, r.right, r.bottom), pid.value)


def idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input."""
    if not IS_WINDOWS:
        return 0.0

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(lii)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    return max(0.0, (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0)


def notification_state() -> int:
    """Windows' own 'do not disturb' signal. 3 = a Direct3D game runs fullscreen, 2 = a fullscreen app/presentation."""
    if not IS_WINDOWS:
        return 0
    state = ctypes.c_int(0)
    try:
        ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    except Exception:
        return 0
    return state.value


def covers_monitor(fg: Foreground) -> bool:
    """True if the foreground window fills its whole monitor (borderless-fullscreen games do this)."""
    if not IS_WINDOWS or not fg.title:
        return False
    try:
        import mss
        l, t, r, b = fg.rect
        with mss.mss() as sct:
            for m in sct.monitors[1:]:
                if l <= m["left"] and t <= m["top"] and r >= m["left"] + m["width"] and b >= m["top"] + m["height"]:
                    return True
    except Exception:
        pass
    return False


# ── where the mouse was when you started talking ("what's this?") ──
_pointer = {"x": 0, "y": 0, "t": 0.0, "title": ""}


def mark_pointer():
    x, y = cursor_pos()
    _pointer.update(x=x, y=y, t=time.time(), title=foreground().title if IS_WINDOWS else "")


def last_pointer(max_age: float = 60.0) -> dict | None:
    if _pointer["t"] and time.time() - _pointer["t"] <= max_age:
        return dict(_pointer)
    return None


# ── mouse actions ──
MOUSE = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}


def click(x: int, y: int, button: str = "left", double: bool = False, move_only: bool = False) -> None:
    if not IS_WINDOWS:
        raise RuntimeError("Clicking only works on Windows.")
    u32 = ctypes.windll.user32
    u32.SetCursorPos(int(x), int(y))
    if move_only:
        return
    time.sleep(0.05)
    down, up = MOUSE[button]
    for _ in range(2 if double else 1):
        u32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.03)
        u32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.08)


def scroll(clicks: int) -> None:
    """Positive = up, negative = down. One click = one wheel notch."""
    if not IS_WINDOWS:
        raise RuntimeError("Scrolling only works on Windows.")
    ctypes.windll.user32.mouse_event(0x0800, 0, 0, int(clicks) * 120, 0)
