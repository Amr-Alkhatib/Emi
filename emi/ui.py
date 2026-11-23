"""How Emi looks: a dynamic island at the top of the screen, and a Control Center window.

* The island (emi/web/island.html) stays hidden until you need it. It drops out of the top edge when you
  say "Hey Emi" or press a shortcut, shows a live waveform while you talk and while Emi speaks, opens into
  a card when the answer is better read than heard, then tucks itself away again.
* The Control Center (emi/web/control.html) is a normal window for settings. Open it from the tray icon
  near the clock, the ⋯ button on the island, or by starting Emi again while it's running.

Both are HTML/CSS shown through pywebview (Microsoft Edge WebView2, part of Windows 11).
"""
from __future__ import annotations

import ctypes
import itertools
import json
import logging
import os
import queue
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .config import DATA_DIR, ROOT

log = logging.getLogger("emi.ui")
WEB = Path(__file__).parent / "web"
THEMES = ("glacier", "midnight")
ISLAND_BG = {"glacier": "#E5F1FF", "midnight": "#0F1728"}
CONTROL_BG = {"glacier": "#E6F1FD", "midnight": "#0D182B"}
REPLY_MODES = ("auto", "voice", "text", "both")
START_W, START_H = 156, 74          # the window while the island is a small bud (css px, incl. margins)
TOP = 10                            # css px between the screen edge and the island (matches island.html)
ROUND_CSS = 56                      # corner diameter: pills are 56 tall, cards have 28 px corners

SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x10, 0x40
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x80, 0x40000


# ── Win32, with proper 64-bit prototypes (on a private copy of user32, so nobody else is affected) ──
def _win() -> bool:
    return sys.platform == "win32"


if _win():
    from ctypes import wintypes as wt

    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi = ctypes.WinDLL("gdi32")
    _k32 = ctypes.WinDLL("kernel32")
    _LONG_PTR = ctypes.c_ssize_t
    _u32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    _u32.SetWindowPos.restype = wt.BOOL
    _u32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    _u32.SetWindowRgn.argtypes = [wt.HWND, wt.HANDLE, wt.BOOL]
    _u32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    _u32.GetWindowLongPtrW.restype = _LONG_PTR
    _u32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, _LONG_PTR]
    _u32.SetWindowLongPtrW.restype = _LONG_PTR
    _u32.GetForegroundWindow.restype = wt.HWND
    _u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.c_void_p]
    _u32.GetWindowThreadProcessId.restype = wt.DWORD
    _u32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    _u32.SetForegroundWindow.argtypes = [wt.HWND]
    _u32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    _u32.GetDpiForWindow.argtypes = [wt.HWND]
    _u32.GetDpiForWindow.restype = ctypes.c_uint
    _gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
    _gdi.CreateRoundRectRgn.restype = wt.HANDLE
    _gdi.CreateRectRgn.argtypes = [ctypes.c_int] * 4
    _gdi.CreateRectRgn.restype = wt.HANDLE
    _HWND_TOPMOST = wt.HWND(-1)
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    _u32.EnumWindows.argtypes = [_WNDENUMPROC, wt.LPARAM]
    _u32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    _u32.ShowWindowAsync.argtypes = [wt.HWND, ctypes.c_int]
    _u32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    _u32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
    _u32.MonitorFromWindow.restype = wt.HANDLE
    _u32.IsIconic.argtypes = [wt.HWND]
    _u32.IsWindowVisible.argtypes = [wt.HWND]
    _gdi.CreateEllipticRgn.argtypes = [ctypes.c_int] * 4
    _gdi.CreateEllipticRgn.restype = wt.HANDLE
    _gdi.CombineRgn.argtypes = [wt.HANDLE, wt.HANDLE, wt.HANDLE, ctypes.c_int]
    _gdi.DeleteObject.argtypes = [wt.HANDLE]
    _dwm = ctypes.WinDLL("dwmapi")
    _dwm.DwmSetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
    _u32.SetWindowDisplayAffinity.argtypes = [wt.HWND, wt.DWORD]
    _u32.SetWindowDisplayAffinity.restype = wt.BOOL
    WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
    _u32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(_MONITORINFO)]


RGN_OR, RGN_DIFF = 2, 4


def _plain_window(hwnd):
    """Switch off everything Windows 11 paints around a window by itself: the dark Mica backdrop (it ignores
    the island's shape and shows as a dark box), rounded corners, the 1 px border and the shadow."""
    for attr, value in ((38, 1),            # DWMWA_SYSTEMBACKDROP_TYPE = none
                        (20, 0),            # DWMWA_USE_IMMERSIVE_DARK_MODE = off
                        (33, 1),            # DWMWA_WINDOW_CORNER_PREFERENCE = do not round
                        (34, 0xFFFFFFFE),   # DWMWA_BORDER_COLOR = none
                        (2, 1)):            # DWMWA_NCRENDERING_POLICY = disabled (no shadow)
        v = ctypes.c_uint(value)
        try:
            _dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        except Exception:
            pass


def _shape_region(shape, k: float):
    """A window region for one shape the page reported (css px × k = window px).
    round: a rounded rectangle · notch: flat top, rounded bottom corners and curved shoulders into the screen edge."""
    kind, x, y, w, h, r = shape[:6]
    X, Y, W, H, R = (int(round(v * k)) for v in (x, y, w, h, r))
    if kind == "round":
        d = max(1, 2 * R)
        return _gdi.CreateRoundRectRgn(X, Y, X + W + 1, Y + H + 1, d, d)
    S = int(round((shape[6] if len(shape) > 6 else 0) * k))
    d = max(1, 2 * R)
    rgn = _gdi.CreateRoundRectRgn(X, Y - d, X + W + 1, Y + H + 1, d, d)   # top corners sit above the window
    if S > 0:
        for sx, cx in ((X - S, X - S), (X + W, X + W + S)):              # left and right shoulder
            square = _gdi.CreateRectRgn(sx, 0, sx + S, S)
            circle = _gdi.CreateEllipticRgn(cx - S, 0, cx + S + 1, 2 * S + 1)
            _gdi.CombineRgn(square, square, circle, RGN_DIFF)
            _gdi.CombineRgn(rgn, rgn, square, RGN_OR)
            _gdi.DeleteObject(square)
            _gdi.DeleteObject(circle)
    return rgn


def _fullscreen_app(own_pid: int) -> bool:
    """Is some other app filling the whole screen right now (a video, a game, a slideshow)?"""
    if not _win():
        return False
    try:
        fg = _u32.GetForegroundWindow()
        if not fg or not _u32.IsWindowVisible(fg) or _u32.IsIconic(fg):
            return False
        pid = wt.DWORD()
        _u32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        if pid.value == own_pid:
            return False
        cls = ctypes.create_unicode_buffer(64)
        _u32.GetClassNameW(fg, cls, 64)
        if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Windows.UI.Core.CoreWindow"):
            return False   # the desktop, the taskbar, the Start menu
        r = wt.RECT()
        _u32.GetWindowRect(fg, ctypes.byref(r))
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        _u32.GetMonitorInfoW(_u32.MonitorFromWindow(fg, 2), ctypes.byref(mi))
        m = mi.rcMonitor
        return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom
    except Exception:
        return False


def _own_window(title: str):
    """Find this process's top-level window with exactly this title (a fallback if pywebview won't say)."""
    if not _win():
        return None
    pid, found = os.getpid(), []

    def check(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        _u32.GetWindowTextW(hwnd, buf, 256)
        if buf.value == title:
            owner = wt.DWORD()
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid:
                found.append(int(hwnd))
                return False
        return True
    _u32.EnumWindows(_WNDENUMPROC(check), 0)
    return found[0] if found else None


def _work_area() -> tuple[int, int, int, int]:
    """Screen area above the taskbar on the main display: left, top, right, bottom (window coordinates)."""
    if not _win():
        return 0, 0, 1280, 800
    try:
        r = wt.RECT()
        _u32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return 0, 0, 1280, 800


def _scale() -> float:
    if not _win():
        return 1.0
    try:
        return _u32.GetDpiForSystem() / 96.0
    except Exception:
        return 1.0


def _on_ui(window, fn, wait: bool = False, title: str = ""):
    """Run fn(form, hwnd) on the window's own UI thread, where its handle lives. Returns fn's result if wait.
    If pywebview can't hand us the form, find the window by its title and run fn(None, hwnd) right here."""
    if not _win():
        return None
    form = getattr(window, "native", None)
    if form is None:
        hwnd = _own_window(title) if title else None
        if not hwnd:
            log.warning("window call %s: window not found", getattr(fn, "__name__", "?"))
            return None
        try:
            return fn(None, hwnd)
        except Exception as e:
            log.warning("window call %s failed: %s", getattr(fn, "__name__", "?"), e)
            return None
    out = {}

    def call():
        try:
            handle = form.Handle
            try:
                hwnd = int(handle.ToInt64())
            except AttributeError:   # some pythonnet versions hand back a plain number
                hwnd = int(handle)
            out["v"] = fn(form, hwnd)
        except Exception as e:
            log.warning("window call %s failed: %s", getattr(fn, "__name__", "?"), e)
        return None
    try:
        from System import Func, Type  # pythonnet, already loaded by pywebview
        d = Func[Type](call)
        form.Invoke(d) if wait else form.BeginInvoke(d)
    except Exception as e:
        log.warning("couldn't reach the window: %s", e)
    return out.get("v")


def _round_corners(hwnd):
    try:  # Windows 11 rounded corners for a frameless window
        pref = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(pref), ctypes.sizeof(pref))
    except Exception:
        pass


def _bring_to_front(form, hwnd):
    """Give this window the keyboard. Windows blocks focus-stealing; borrowing the foreground thread's input
    for a moment is the polite way around it. Must run on the window's UI thread."""
    fg = _u32.GetForegroundWindow()
    fg_thread = _u32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = _k32.GetCurrentThreadId()
    attached = bool(fg_thread and fg_thread != me and _u32.AttachThreadInput(fg_thread, me, True))
    try:
        _u32.SetForegroundWindow(hwnd)
        if form is not None:
            form.Activate()
            try:
                form.webview.Focus()
            except Exception:
                pass
    finally:
        if attached:
            _u32.AttachThreadInput(fg_thread, me, False)


def _no_user_close(form, on_close):
    """Closing from the taskbar, Alt+F4 or the window's ✕ hides instead (Emi keeps running in the tray).
    Shutting Windows down still closes normally."""
    def handler(sender, args):
        try:
            if "UserClosing" in str(args.CloseReason):
                args.Cancel = True
                on_close()
        except Exception as e:
            log.debug("closing handler: %s", e)
    form.FormClosing += handler


def _pretty_key(combo: str) -> str:
    names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win", "esc": "Esc", "space": "Space",
             "enter": "Enter", "tab": "Tab"}
    return " + ".join(names.get(p.strip().lower(), p.strip().upper() if len(p.strip()) == 1 else p.strip().title())
                      for p in str(combo).split("+") if p.strip())


class _Api:
    """Methods the island and the Control Center can call as window.pywebview.api.<name>(...)."""

    def __init__(self, ui: "WebUI"):
        self._ui = ui

    # ── island ──
    def ready(self):
        self._ui._ready.set()
        return self._ui._island_payload()

    def place(self, w, h, dpr=0):
        self._ui._place(float(w), float(h), float(dpr or 0))

    def clip(self, seq, shapes, dpr=0):
        self._ui._clip(int(seq), list(shapes or []), float(dpr or 0))

    def remember_app(self):
        self._ui._remember_app()

    focus = remember_app   # (older island pages)

    def unfocus(self):
        self._ui._unfocus_island()

    def island_in_front(self):
        return self._ui._island_in_front()

    def menu_closed(self, why=""):
        log.info("quick menu closed (%s)", str(why or "?")[:40])

    def menu_info(self):
        return self._ui._menu_info()

    def menu_action(self, name):
        self._ui._menu_action(str(name))

    def menu_recent(self, i):
        self._ui._menu_recent(int(i))

    def showing(self):
        self._ui._island_visible(True)

    def hidden(self):
        self._ui._island_visible(False)

    def submit(self, text, mode="ask"):
        if self._ui.on_submit:
            self._ui.on_submit(str(text), "typed", "screen" if mode == "screen" else "ask")

    def talk(self):
        if self._ui.on_talk:
            self._ui.on_talk()

    def stop(self):
        if self._ui.on_stop:
            self._ui.on_stop()

    def answer(self, cid, ok):
        cb = self._ui._confirms.pop(int(cid), None)
        if cb:
            cb(bool(ok))

    def suggestion(self, sid, yes):
        cb = self._ui._suggestions.pop(int(sid), None)
        if cb:
            cb(bool(yes))

    def crop(self):
        if self._ui.on_crop:
            self._ui.on_crop()

    def say(self, text):
        tts = self._ui.tts
        if tts and str(text).strip():
            tts.stop()
            threading.Thread(target=self._ui._read_aloud, args=(str(text),), daemon=True).start()

    def open_control(self):
        self._ui.open_control()

    def open_link(self, href):
        if str(href).startswith(("http://", "https://")):
            webbrowser.open(str(href))

    # ── Control Center ──
    def ready_control(self):
        return self._ui._control_payload()

    def type(self):
        (self._ui.on_type or self._ui.open_input)()

    def control_minimize(self):
        if self._ui.control is not None:
            self._ui.control.minimize()

    def control_close(self):
        self._ui.hide_control()

    def set_setting(self, key, value):
        self._ui.change_setting(str(key), value)

    def brain_info(self):
        return self._ui._brain_info()

    def voice_info(self):
        return self._ui.tts.options() if self._ui.tts else [{"current": ""}]

    def set_voice(self, value):
        self._ui._set_voice(str(value))

    def design_voice(self, description, name):
        return self._ui._design_voice(str(description), str(name))

    def memories(self):
        return [{"id": m["id"], "text": m["text"]} for m in reversed(self._ui.storage.memories())]

    def forget(self, mid):
        self._ui.storage.remove_memory(str(mid))

    def open_data(self):
        if _win():
            os.startfile(str(DATA_DIR))

    def quit(self):
        self._ui.quit()


class WebUI:
    def __init__(self, cfg, state, storage, start_hidden: bool = False, brain=None):
        import webview
        self.webview = webview
        self.cfg, self.state, self.storage, self.brain = cfg, state, storage, brain
        self.tts = None                                       # set by main.py
        self.on_submit = self.on_talk = self.on_stop = self.on_crop = self.on_type = None
        self.on_quit = None                                   # e.g. take the tray icon down
        self._confirms: dict[int, callable] = {}
        self._suggestions: dict[int, callable] = {}
        self._ids = itertools.count(1)
        self._models_cache: tuple[float, list] = (0.0, [])
        self._prefs = self._load_prefs()
        self.theme = self._prefs.get("theme") if self._prefs.get("theme") in THEMES else (
            str(cfg.get("ui.theme", "glacier")) if str(cfg.get("ui.theme", "")) in THEMES else "glacier")
        # The island window is cut to the island's exact shape (a window region), so it never shows a box
        # around it and never blocks clicks next to it.
        self.island_style = "solid"

        self._q: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._loaded = False
        self._status = "idle"
        self._js_shown = False      # the island page says it's on screen
        self._win_shown = False     # the native window is visible (or about to be)
        self._css = (START_W, START_H)
        self._dpr = 0.0             # the page's devicePixelRatio (css px → window px)
        self._geom = (0, 0, 0, 0)   # x, y, w, h of the island window in window coordinates
        self._clip_seq = 0
        self._last_clip = None
        self._logged = 0
        self._native_hidden = False   # True while the island window is hidden outright (gaming)
        self._hwnd = None
        self._setting_up = False
        self._shots: dict[str, int] = {}
        self._fullscreen = False
        self._menu_prev_fg = None
        self.on_menu = None          # set by main.py: quick-menu actions
        self._control_open = False
        self.voice_ok = True         # main.py sets False if the microphone isn't available
        self._level_t = 0.0
        self._level_peak = 0.0
        self._lock = threading.RLock()
        self.control = None
        self._control_ready = False
        self._normal_state = None
        self._control_lock = threading.Lock()
        self._start_hidden = start_hidden
        self.api = _Api(self)
        if _win():
            try:  # own taskbar identity, so the Control Center shows Emi's icon instead of Python's
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Emi.Assistant")
            except Exception:
                pass

        # A normal window (pywebview's hidden/transparent modes misbehave with WebView2), created far
        # off-screen so you never see it load; once loaded it moves to the top of the screen, cut to nothing.
        self._prev_fg = _u32.GetForegroundWindow() if _win() else None
        html = (WEB / "island.html").read_text(encoding="utf-8")
        self.island = webview.create_window(
            cfg.name, html=html, js_api=self.api, width=START_W, height=START_H, x=-7000, y=-7000,
            frameless=True, easy_drag=False, on_top=True, resizable=False, shadow=False, min_size=(40, 30),
            background_color=ISLAND_BG[self.theme])
        self.window = self.island  # older code calls it the window
        self.island.events.loaded += self._on_island_loaded
        state.watch(self._on_state)
        threading.Thread(target=self._dispatch, daemon=True, name="ui-dispatch").start()

    # ── plumbing ──
    def _load_prefs(self) -> dict:
        try:
            return json.loads((DATA_DIR / "ui.json").read_text(encoding="utf-8")) or {}
        except Exception:
            return {}

    def _save_prefs(self, **kv):
        self._prefs.update(kv)
        try:
            (DATA_DIR / "ui.json").write_text(json.dumps(self._prefs), encoding="utf-8")
        except Exception:
            pass

    def _js(self, fn: str, *args):
        self._q.put(f"window.emi && window.emi.{fn}({', '.join(json.dumps(a) for a in args)})")

    def _dispatch(self):
        self._ready.wait()
        while True:
            code = self._q.get()
            try:
                self.island.evaluate_js(code)
            except Exception as e:
                log.debug("evaluate_js failed: %s", e)

    def _cjs(self, fn: str, *args):
        """Same, for the Control Center (only once it's open)."""
        win = self.control
        if win is None or not self._control_ready:
            return
        code = f"window.emi && window.emi.{fn}({', '.join(json.dumps(a) for a in args)})"

        def run():
            try:
                win.evaluate_js(code)
            except Exception as e:
                log.debug("control evaluate_js failed: %s", e)
        threading.Thread(target=run, daemon=True).start()

    def _on_island_loaded(self):
        with self._lock:
            if self._loaded or self._setting_up:
                return
            self._setting_up = True
        # The island window stays on screen from now on, but cut down to nothing (an empty window region):
        # invisible, can't be clicked, and it can pop up instantly without stealing your keyboard focus.
        def setup(form, hwnd):
            _u32.ShowWindow(hwnd, SW_HIDE)
            ex = _u32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            _u32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)  # no taskbar button
            _plain_window(hwnd)
            _u32.SetWindowRgn(hwnd, _gdi.CreateRectRgn(0, 0, 0, 0), True)
            x, y, w, h = self._target_geom(*self._css)
            self._geom = (x, y, w, h)
            ok = _u32.SetWindowPos(hwnd, _HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW | 0x20)
            if self._prev_fg and _u32.GetForegroundWindow() == hwnd:
                _u32.SetForegroundWindow(self._prev_fg)   # give the keyboard back to what you were using
            self._hwnd = hwnd
            log.info("island window ready (handle %#x via %s, %s dpi, move %s)", hwnd,
                     "pywebview" if form is not None else "title", _u32.GetDpiForWindow(hwnd), "ok" if ok else
                     f"failed {ctypes.get_last_error()}")
            return hwnd
        _on_ui(self.island, setup, wait=True, title=self.cfg.name)
        try:
            _no_user_close(self.island.native, lambda: self._js("dismiss"))
        except Exception as e:
            log.debug("couldn't guard the island against closing: %s", e)
        self._loaded = True
        threading.Timer(3.0, self._ready.set).start()  # safety net if the page never says "ready"
        if self._win_shown:  # something asked for the island while it was loading
            with self._lock:
                self._win_shown = False
            self._show_window()

    def _watchdog(self):
        """If pywebview never reports the island as loaded, set it up anyway after a while."""
        time.sleep(12)
        if not self._loaded:
            log.warning("the island page didn't report in; setting the window up anyway")
            self._on_island_loaded()

    def _on_state(self, key, value):
        self._push_settings()

    # ── the island window ──
    def _island_visible(self, on: bool):
        self._js_shown = on
        if on:
            self._show_window()
        else:
            self._hide_window()

    def _ratio(self) -> float:
        return self._dpr or _scale()

    def _target_geom(self, w_css: float, h_css: float) -> tuple[int, int, int, int]:
        k = self._ratio()
        l, t, r, _ = _work_area()
        w, h = int(round(w_css * k)), int(round(h_css * k))
        return l + (r - l - w) // 2, t, w, h

    def _show_window(self):
        if getattr(self.state, "gaming", False):
            return  # never pop up over a game (it could kick a fullscreen game to the desktop)
        with self._lock:
            if self._win_shown or not _win():
                return
            self._win_shown = True
        if not self._loaded:
            return  # _on_island_loaded shows it once the window exists

        def show(form, hwnd):
            if not self._win_shown:
                return
            x, y, w, h = self._target_geom(*self._css)
            self._geom = (x, y, w, h)
            if not self._last_clip:   # a small bud until the page reports the real shapes
                self._last_clip = [["round", (self._css[0] - 120) / 2, TOP, 120, 36, 18]]
            _plain_window(hwnd)       # (Windows may switch the dark backdrop back on when the theme changes)
            self._apply_clip(hwnd)
            flags = SWP_NOACTIVATE | (SWP_SHOWWINDOW if self._native_hidden else 0)
            ok = _u32.SetWindowPos(hwnd, _HWND_TOPMOST, x, y, w, h, flags)   # also keeps it above other windows
            self._native_hidden = False
            if not ok:
                log.warning("showing the island failed (error %s)", ctypes.get_last_error())
            self._log_rect(hwnd, "shown")
            self._snapshot("shown")
        _on_ui(self.island, show, title=self.cfg.name)

    def _hide_window(self, fully: bool = False):
        """Cut the island window down to nothing. fully=True also hides the window itself (for games)."""
        with self._lock:
            self._win_shown = False
            self._last_clip = None

        def hide(form, hwnd):
            if self._win_shown:
                return   # shown again in the meantime
            _u32.SetWindowRgn(hwnd, _gdi.CreateRectRgn(0, 0, 0, 0), True)
            self._snapshot("hidden")
            if fully:
                _u32.ShowWindow(hwnd, SW_HIDE)
                self._native_hidden = True
        if self._loaded:
            _on_ui(self.island, hide, title=self.cfg.name)

    def _log_rect(self, hwnd, what):
        if self._logged >= 4:
            return
        self._logged += 1
        r = wt.RECT()
        _u32.GetWindowRect(hwnd, ctypes.byref(r))
        log.info("island %s: asked %s, window is at %d,%d size %dx%d (ratio %.2f)", what, self._geom,
                 r.left, r.top, r.right - r.left, r.bottom - r.top, self._ratio())

    def _place(self, w_css: float, h_css: float, dpr: float = 0.0):
        """The page wants a window this big (island + a little room), centred at the top of the screen."""
        self._css = (w_css, h_css)
        if dpr:
            self._dpr = dpr

        def place(form, hwnd):
            x, y, w, h = self._target_geom(*self._css)
            self._geom = (x, y, w, h)
            _u32.SetWindowPos(hwnd, _HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE)
            self._apply_clip(hwnd)
            if self._win_shown:
                self._log_rect(hwnd, "resized")
                self._snapshot("resized")
        if self._loaded:
            _on_ui(self.island, place, title=self.cfg.name)

    def _clip(self, seq: int, shapes: list, dpr: float = 0.0):
        """Cut the window to the shapes on show (the page reports them every frame while they move)."""
        with self._lock:
            if seq <= self._clip_seq:
                return  # an older frame arriving late
            self._clip_seq = seq
            self._last_clip = shapes
        if dpr:
            self._dpr = dpr
        if self._loaded and self._win_shown:
            _on_ui(self.island, lambda form, hwnd: self._apply_clip(hwnd), title=self.cfg.name)

    def _apply_clip(self, hwnd):
        """UI thread only: the window region = the union of the visible shapes; everything else is cut away."""
        shapes = self._last_clip or []
        k = self._ratio()
        rgn = _gdi.CreateRectRgn(0, 0, 0, 0)
        for shape in shapes:
            try:
                part = _shape_region(shape, k)
                _gdi.CombineRgn(rgn, rgn, part, RGN_OR)
                _gdi.DeleteObject(part)
            except Exception as e:
                log.debug("bad shape %s: %s", shape, e)
        _u32.SetWindowRgn(hwnd, rgn, True)   # Windows owns rgn from here on

    def hidden_from_capture(self, on: bool) -> None:
        """While Emi takes a screenshot for herself, the island is left out of the picture (it stays on your
        screen). Otherwise she sees her own "Thinking…" card covering whatever she was looking for."""
        if not _win() or not self._hwnd or self._native_hidden:
            return
        flag = WDA_EXCLUDEFROMCAPTURE if on else WDA_NONE

        def affinity(form, hwnd):
            return _u32.SetWindowDisplayAffinity(hwnd, flag)
        _on_ui(self.island, affinity, wait=True, title=self.cfg.name)

    def _snapshot(self, what: str):
        """Save a small picture of the island's spot on screen (data/island_<what>.png) for the first few
        times, so problems can be checked without asking for screenshots. ui.debug_snapshots: false turns it off."""
        if not self.cfg.get("ui.debug_snapshots", True) or self._shots.get(what, 0) >= 2:
            return
        self._shots[what] = self._shots.get(what, 0) + 1
        geom = self._geom

        def grab():
            time.sleep(0.9)
            try:
                import mss
                import mss.tools
                x, y, w, h = geom
                box = {"left": x - 40, "top": y, "width": w + 80, "height": h + 40}
                with mss.mss() as sct:
                    img = sct.grab(box)
                    mss.tools.to_png(img.rgb, img.size, output=str(DATA_DIR / f"island_{what}.png"))
            except Exception as e:
                log.debug("snapshot failed: %s", e)
        threading.Thread(target=grab, daemon=True).start()

    # ── focus for the quick menu ──
    # Clicking the notch is what gives the island the keyboard. Emi used to grab it again on top of that
    # (SetForegroundWindow + Activate + Focus), which made the page blink out of focus and the menu shut at once.
    def _remember_app(self):
        """Your mouse just reached the notch: note the app you're in, to hand the keyboard back to it later."""
        fg = _u32.GetForegroundWindow() if _win() else None
        if fg and int(fg) != (self._hwnd or 0):
            self._menu_prev_fg = fg

    def _island_in_front(self) -> bool:
        """Is the island (or another Emi window) still the window you're using?"""
        if not _win():
            return True
        fg = _u32.GetForegroundWindow()
        if not fg:
            return False
        if self._hwnd and int(fg) == int(self._hwnd):
            return True
        pid = wt.DWORD()
        _u32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        return pid.value == os.getpid()

    def _unfocus_island(self):
        prev = getattr(self, "_menu_prev_fg", None)
        if _win() and prev and int(_u32.GetForegroundWindow() or 0) == (self._hwnd or -1):
            _u32.SetForegroundWindow(prev)

    # ── the quick menu ──
    def _recent(self, n: int = 3) -> list[dict]:
        try:
            lines = (self.storage.dir / "history.jsonl").read_text(encoding="utf-8").splitlines()[-60:]
        except Exception:
            return []
        items, q = [], None
        for line in lines:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("role") == "user":
                q = e
            elif e.get("role") == "assistant" and q:
                items.append({"q": q.get("text", ""), "a": e.get("text", ""), "t": q.get("t", "")})
                q = None
        return list(reversed(items))[:n]

    def _menu_info(self) -> dict:
        k = self._hotkeys()
        info = self._menu_payload()
        info["recent"] = [{"q": r["q"][:120], "t": r["t"]} for r in self._recent()]
        info["keys"] = {"talk": k["talk"].replace(" + ", "+"), "type": k["type"].replace(" + ", "+"),
                        "crop": k["crop"].replace(" + ", "+")}
        return info

    def _menu_payload(self) -> dict:
        return {"name": self.cfg.name, "status": self._control_payload()["statusText"], "voice": self.voice_ok,
                "incognito": self.state.incognito}

    def _menu_action(self, name: str):
        if self.on_menu:
            try:
                self.on_menu(name)
            except Exception:
                log.exception("menu action %s failed", name)

    def _menu_recent(self, i: int):
        rec = self._recent(8)
        if 0 <= i < len(rec):
            self.show_user(rec[i]["q"])
            self.show_reply(rec[i]["a"], True)
            self.set_status("idle")

    def _watch_fullscreen(self):
        """Keep the notch out of the way while a video, game or slideshow fills the screen."""
        pid = os.getpid()
        while True:
            time.sleep(1.5)
            fs = _fullscreen_app(pid)
            if fs != self._fullscreen:
                self._fullscreen = fs
                self._js("settings", {"fullscreen": fs})

    # ── settings for both windows ──
    def _hotkeys(self) -> dict:
        d = {"talk": "ctrl+alt+space", "type": "alt+shift+s", "stop": "esc", "incognito": "ctrl+alt+i", "crop": "ctrl+alt+c",
             "end": "alt+x"}
        return {k: _pretty_key(self.cfg.get(f"hotkeys.{k}", v)) for k, v in d.items()}

    def _idle_hint(self) -> str:
        wake = str(self.cfg.get("hearing.wake_mode", "whisper")) != "off"
        return f"Say “Hey {self.cfg.name}”" if wake else f"Press {self._hotkeys()['talk'].replace(' + ', '+')}"

    def _island_payload(self) -> dict:
        return {"name": self.cfg.name, "theme": self.theme, "idleHint": self._idle_hint(),
                "idleLook": getattr(self.state, "idle_look", "notch"), "incognito": self.state.incognito,
                "paused": bool(getattr(self.state, "paused", False)), "menu": self._menu_payload(),
                "solid": self.island_style == "solid"}

    def _control_payload(self) -> dict:
        k = self._hotkeys()
        summon = str(self.cfg.get("hotkeys.summon", "ctrl+alt+shift+e"))
        keys = [[k["talk"], f"Talk to {self.cfg.name} (no need to say the name)"],
                [k["type"], "Type a question instead"],
                [k["crop"], "Drag around part of the screen, then ask about it"],
                [k["end"], "End the conversation: she stops listening for follow-ups"],
                [k["stop"], "Stop talking or cancel what she's doing (she keeps listening)"],
                [k["incognito"], "Incognito on or off"],
                [_pretty_key(summon), f"Start {self.cfg.name} and listen, even when she's closed"]]
        st = self.state
        if self.brain is not None and self.brain.error:
            status, warn = "Needs setup: check the Brain page", True
        elif getattr(st, "gaming", False):
            status, warn = "Quiet while you play", False
        elif st.incognito:
            status, warn = "Incognito", False
        else:
            b = self.brain
            if getattr(b, "auto_mode", False):
                status, warn = "Ready · Auto", False
            else:
                model = str((b.fast_model if getattr(b, "instant", False) else getattr(b, "model", "")) or "")
                pretty = " ".join(w if any(c.isdigit() for c in w) else w.capitalize()
                                  for w in model.replace("-preview", "").split("-"))
                status, warn = (f"Ready · {pretty}" if pretty else "Ready"), False
        return {"name": self.cfg.name, "theme": self.theme, "summonKey": k["talk"], "keys": keys,
                "incognito": st.incognito, "proactive": bool(getattr(st, "proactive", False)),
                "proactiveEvery": int(getattr(st, "proactive_every", 120)),
                "gamingAuto": bool(getattr(st, "gaming_auto", True)), "gaming": bool(getattr(st, "gaming", False)),
                "fullAccess": st.full_access, "speak": st.speak_replies,
                "claudeHelper": bool(getattr(st, "claude_helper", False)),
                "replyMode": getattr(st, "reply_mode", "auto"), "personality": st.personality,
                "idleLook": getattr(st, "idle_look", "notch"), "speed": getattr(st, "speed", "instant"),
                "statusText": status, "statusWarn": warn}

    def _push_settings(self):
        self._js("settings", self._island_payload())
        self._cjs("settings", self._control_payload())

    def _brain_info(self) -> dict:
        from .tools.claude_code import find_claude
        info = {"label": "Brain", "current": "", "options": [], "error": "",
                "claude": {"installed": find_claude() is not None, "on": bool(self.state.claude_helper)}}
        b = self.brain
        if b is None:
            return info
        info.update(label=b.label, current=b.model or "", error=b.error or "",
                    speed=getattr(self.state, "speed", "auto"),
                    autoModels=b.auto_summary() if hasattr(b, "auto_summary") else {})
        stamp, cached = self._models_cache
        if not cached or time.time() - stamp > 600:
            cached = b.list_models()
            self._models_cache = (time.time(), cached)
        info["options"] = cached
        return info

    def change_setting(self, key: str, value):
        st = self.state
        if key == "theme" and value in THEMES:
            self.theme = value
            self._save_prefs(theme=value)
            self._push_settings()
        elif key in ("incognito", "speak_replies", "full_access", "claude_helper", "proactive", "gaming_auto"):
            st.set(key, bool(value))                    # → _push_settings via state.watch
        elif key == "personality" and str(value) in ("hype", "chill", "sleepy"):
            st.set(key, str(value))
        elif key == "reply_mode" and str(value) in REPLY_MODES:
            st.set(key, str(value))
        elif key == "idle_look" and str(value) in ("notch", "hide"):
            st.set(key, str(value))
            if value == "hide" and self._status in ("idle", "error"):
                self._js("dismiss")
        elif key == "speed" and str(value) in ("auto", "instant", "smart"):
            st.set(key, str(value))
        elif key == "proactive_every":
            st.set(key, max(30, int(value)))
        elif key == "model" and self.brain is not None:
            self.brain.set_model(str(value))
            self._push_settings()
            self.notify(f"Now thinking with {value}.")

    def _set_voice(self, value: str):
        engine, _, voice = value.partition("|")
        if self.tts and self.tts.set_voice(engine, voice):
            threading.Thread(target=self.tts.speak, args=("Hi! This is my new voice.",), daemon=True).start()
        else:
            self.notify("That voice isn't available right now. Check its key in the .env file.")

    def _design_voice(self, description: str, name: str) -> dict:
        from .tts import _decode_audio, design_gemini_voice
        try:
            vid, sample = design_gemini_voice(description, name or self.cfg.name,
                                              self.cfg.get("voice.gemini_tts_model", "gemini-3.8-flash-tts"))
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}
        voices = list(getattr(self.state, "custom_voices", []) or [])
        voices.insert(0, {"id": vid, "name": name or "My voice"})
        self.state.set("custom_voices", voices[:20])
        if self.tts:
            self.tts.set_voice("gemini", vid)
            if sample:
                audio, sr = _decode_audio(sample)
                threading.Thread(target=self.tts.player.play, args=(audio, sr, self.tts._stop), daemon=True).start()
        return {"ok": True, "id": vid}

    def _read_aloud(self, text: str):
        self.set_status("speaking", "Reading aloud")
        try:
            self.tts.speak(text)
        finally:
            self.set_status("idle")

    # ── Control Center ──
    def open_control(self, page: str | None = None):
        self._control_open = True
        with self._control_lock:
            win = self.control
            if win is not None:   # already made: bring it back (it hides instead of closing)
                def front(form, hwnd):
                    if form is None:
                        _u32.ShowWindow(hwnd, 9)   # SW_RESTORE
                    else:
                        if "Minimized" in str(form.WindowState) and self._normal_state is not None:
                            form.WindowState = self._normal_state
                        form.Show()
                    _bring_to_front(form, hwnd)
                _on_ui(win, front, title=f"{self.cfg.name} Control Center")
                if page:
                    self._cjs("open", page)
                return
            l, t, r, b = _work_area()
            sc = _scale()
            w = int(min(1040, (r - l) / sc - 60))
            h = int(min(700, (b - t) / sc - 60))
            html = (WEB / "control.html").read_text(encoding="utf-8")
            win = self.webview.create_window(
                f"{self.cfg.name} Control Center", html=html, js_api=self.api, width=w, height=h,
                x=int((l + (r - l - w * sc) / 2) / sc), y=int((t + (b - t - h * sc) / 2) / sc),
                frameless=True, easy_drag=False, resizable=False, shadow=True,
                background_color=CONTROL_BG[self.theme])
            self.control = win
            win.events.loaded += lambda: self._on_control_loaded(win, page)
            win.events.closed += lambda: self._on_control_closed(win)

    def _on_control_loaded(self, win, page):
        def setup(form, hwnd):
            self._normal_state = form.WindowState   # FormWindowState.Normal, for restoring later
            _round_corners(hwnd)
            ico = ROOT / "emi.ico"
            if ico.exists():
                from System.Drawing import Icon
                form.Icon = Icon(str(ico))
            _bring_to_front(form, hwnd)
        _on_ui(win, setup, wait=True, title=f"{self.cfg.name} Control Center")
        try:
            _no_user_close(win.native, self.hide_control)
        except Exception as e:
            log.debug("couldn't keep the Control Center from closing: %s", e)
        self._control_ready = True
        if page:
            self._cjs("open", page)

    def busy_with_you(self) -> bool:
        """Are you in the middle of something on screen with Emi (a card, the quick menu, the Control Center)?"""
        return self._status not in ("idle", "error") or bool(self._confirms) or (self._control_open and self._control_in_front())

    def _control_in_front(self) -> bool:
        if not _win():
            return False
        try:
            buf = ctypes.create_unicode_buffer(128)
            _u32.GetWindowTextW(_u32.GetForegroundWindow(), buf, 128)
            return buf.value == f"{self.cfg.name} Control Center"
        except Exception:
            return False

    def hide_control(self):
        """The ✕ on the Control Center: put it away; Emi keeps running in the tray."""
        self._control_open = False
        win = self.control
        if win is not None:
            _on_ui(win, lambda form, hwnd: form.Hide() if form is not None else _u32.ShowWindow(hwnd, SW_HIDE),
                   title=f"{self.cfg.name} Control Center")
            if not self._prefs.get("told_tray"):
                self._save_prefs(told_tray=True)
                self._js("flash", f"Still here! Find me in the tray, or say “Hey {self.cfg.name}”", 4200)

    def _on_control_closed(self, win):
        with self._control_lock:
            if self.control is win:
                self.control = None
                self._control_ready = False

    def first_run(self):
        """Very first start: say hello and open the Control Center so you see where things are."""
        self.state.set("welcomed", True)
        self.open_control()
        self._js("flash", f"Hi! Say “Hey {self.cfg.name}” anytime", 4200)

    # ── public API used by the agent, listener, etc. (safe from any thread) ──
    def set_status(self, kind: str, text: str = ""):
        self._status = kind
        if kind not in ("idle", "loading"):
            self._show_window()
        self._js("status", kind, text)

    def level(self, value: float):
        """Live loudness 0..1 (your voice while listening, Emi's while speaking) for the waveform."""
        if self._status not in ("listening", "speaking") or not self._win_shown:
            return
        self._level_peak = max(self._level_peak, float(value))
        now = time.monotonic()
        if now - self._level_t >= 0.07 and self._q.qsize() < 6:
            self._level_t = now
            self._js("level", round(self._level_peak, 3))
            self._level_peak = 0.0

    def show_user(self, text: str):
        self._show_window()
        self._js("user", text)

    def show_reply(self, text: str, expand: bool = True):
        """expand=True opens the answer card; False keeps it in the pill (click the pill to read it)."""
        if expand:
            self._show_window()
        self._js("reply", text, bool(expand))

    def clear_steps(self):
        self._js("clearSteps")

    def add_step(self, label: str) -> int:
        sid = next(self._ids)
        self._js("addStep", sid, label)
        return sid

    def finish_step(self, sid: int, ok: bool):
        self._js("finishStep", sid, ok)

    def ask_confirm(self, text: str, decide, voice: bool = False) -> int:
        cid = next(self._ids)
        self._confirms[cid] = decide
        self._show_window()
        self._js("confirm", cid, text, voice)
        return cid

    def close_confirm(self, cid: int):
        self._confirms.pop(cid, None)
        self._js("closeConfirm", cid)

    def notify(self, text: str):
        self._show_window()
        self._js("toast", text)

    def suggest(self, text: str, decide, timeout: float = 90.0) -> int:
        """Proactive idea with Do it / Not now. Quietly withdrawn after `timeout` seconds."""
        sid = next(self._ids)
        self._suggestions[sid] = decide
        self._show_window()
        self._js("suggest", sid, text)

        def expire():
            cb = self._suggestions.pop(sid, None)
            if cb:
                self._js("closeSuggestion", sid)
                cb(False)
        threading.Timer(timeout, expire).start()
        return sid

    def open_input(self, mode: str = ""):
        self._show_window()
        if self._loaded:
            _on_ui(self.island, _bring_to_front, title=self.cfg.name)   # so you can type straight away
        self._js("openInput", mode)

    def show_card(self):
        """Pop the island (it tucks itself away again when there's nothing to show)."""
        self._show_window()
        self._js("wake")

    def dismiss(self):
        """Put the island away (Esc), with its usual animation."""
        if self._win_shown:
            self._js("dismiss")

    def hide_card(self):
        """Hide the island right now (e.g. before a screenshot)."""
        self._js("dismiss")
        self._hide_window()

    def set_gaming(self, on: bool):
        if on:
            self._hide_window(fully=True)
        elif self._js_shown:
            self._show_window()
        self._push_settings()

    def open_crop(self, image_b64_jpeg: str, on_done):
        """Freeze-frame of the screen in a fullscreen window; you drag a box; on_done(fractions or None)."""
        html = (WEB / "crop.html").read_text(encoding="utf-8")
        html = html.replace("__IMAGE__", "data:image/jpeg;base64," + image_b64_jpeg)
        done = {"called": False}

        class CropApi:
            def finish(self_api, x0, y0, x1, y1):
                if not done["called"]:
                    done["called"] = True
                    threading.Thread(target=on_done, args=((float(x0), float(y0), float(x1), float(y1)),),
                                     daemon=True).start()
                win.destroy()

            def cancel(self_api):
                if not done["called"]:
                    done["called"] = True
                    threading.Thread(target=on_done, args=(None,), daemon=True).start()
                win.destroy()

        win = self.webview.create_window(f"{self.cfg.name} - select an area", html=html, js_api=CropApi(),
                                         fullscreen=True, on_top=True, frameless=True, background_color="#000000")

    def run(self, on_start):
        threading.Thread(target=self._watchdog, daemon=True, name="island-watchdog").start()
        threading.Thread(target=self._watch_fullscreen, daemon=True, name="fullscreen-watch").start()
        self.webview.start(on_start, private_mode=True)

    def quit(self):
        """Quit Emi completely (tray → Quit). Closing windows only hides them."""
        log.info("quitting")
        try:
            if self.on_quit:
                self.on_quit()
        except Exception:
            pass
        os._exit(0)


class ConsoleUI:
    """Same interface, printed to the terminal (python main.py --text)."""

    def __init__(self):
        self._ids = itertools.count(1)

    def set_status(self, kind, text=""):
        if kind in ("working",) and text:
            print(f"   … {text}")

    def level(self, value):
        pass

    def show_user(self, text):
        pass

    def show_reply(self, text, expand=True):
        print(f"\nEmi> {text}\n")

    def clear_steps(self):
        pass

    def add_step(self, label):
        print(f"   ▸ {label}")
        return next(self._ids)

    def finish_step(self, sid, ok):
        if not ok:
            print("     (that step failed)")

    def ask_confirm(self, text, decide, voice=False):
        print(f"\n⚠  {text}")
        decide(input("   Allow? [y/N] ").strip().lower() in ("y", "yes"))
        return next(self._ids)

    def close_confirm(self, cid):
        pass

    def notify(self, text):
        print(f"\n🔔 {text}\n")

    def open_input(self, mode=""):
        pass

    def show_card(self):
        pass

    def hide_card(self):
        pass

    def dismiss(self):
        pass

    def open_control(self, page=None):
        pass

    def suggest(self, text, decide, timeout=90.0):
        print(f"\n💡 {text}")
        return 0
