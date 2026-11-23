"""Seeing and clicking: screenshots (full, active window, around your mouse, or an area you selected) and
clicking things on screen by describing them. Never in incognito."""
from __future__ import annotations

import base64
import io
import re
import time

from .. import winutil
from . import IS_WINDOWS, ToolError, require_windows, tool

_selection: dict = {"img": None, "t": 0.0}


def set_selection(img) -> None:
    """The crop tool stores the area you dragged here."""
    _selection.update(img=img, t=time.time())


def to_b64(img, max_side: int = 1600) -> str:
    img = img.copy()
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def _monitor_for(x: int, y: int, monitors: list) -> dict:
    for m in monitors[1:]:
        if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
            return m
    return monitors[1]


def capture(region: str = "full"):
    """Returns (PIL image, box) where box = {"left", "top", "width", "height"} in screen pixels."""
    import mss
    from PIL import Image, ImageDraw
    if region == "selection":
        if _selection["img"] is None or time.time() - _selection["t"] > 600:
            raise ToolError("There's no recent selection. Press the crop shortcut and drag around something first.")
        img = _selection["img"]
        return img, {"left": 0, "top": 0, "width": img.width, "height": img.height}
    with mss.mss() as sct:
        px, py = winutil.cursor_pos()
        box = dict(_monitor_for(px, py, sct.monitors) if IS_WINDOWS else sct.monitors[1])
        mark = None
        if region == "active_window" and IS_WINDOWS:
            fg = winutil.foreground()
            l, t, r, b = fg.rect
            if r - l > 50 and b - t > 50:
                box = {"left": max(l, 0), "top": max(t, 0), "width": r - max(l, 0), "height": b - max(t, 0)}
        elif region == "pointer":
            p = winutil.last_pointer() or {"x": px, "y": py}
            mon = _monitor_for(p["x"], p["y"], sct.monitors) if IS_WINDOWS else sct.monitors[1]
            w, h = min(1100, mon["width"]), min(700, mon["height"])
            left = min(max(p["x"] - w // 2, mon["left"]), mon["left"] + mon["width"] - w)
            top = min(max(p["y"] - h // 2, mon["top"]), mon["top"] + mon["height"] - h)
            box = {"left": left, "top": top, "width": w, "height": h}
            mark = (p["x"] - left, p["y"] - top)
        shot = sct.grab(box)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    if mark:  # draw where the mouse was, so "this" is unambiguous
        d = ImageDraw.Draw(img)
        x, y = mark
        for r_, w_ in ((22, 5), (22, 2)):
            d.ellipse((x - r_, y - r_, x + r_, y + r_), outline=(255, 40, 80) if w_ == 5 else (255, 255, 255), width=w_)
    return img, box


def screenshot_jpeg_b64(region: str = "full", max_side: int = 1600) -> str:
    img, _ = capture(region)
    return to_b64(img, max_side)


@tool("look_at_screen",
      "Take a screenshot and answer a question about it (read text, explain an error, describe a chart, find "
      "something). region: 'full' (whole screen), 'active_window' (current app), 'pointer' (around where the user's "
      "mouse was when they spoke — use it when they say 'this', 'that' or 'here'; a red ring marks the spot), "
      "'selection' (the area the user just dragged with the crop shortcut).",
      {"question": {"type": "string", "description": "What to find out from the screen"},
       "region": {"type": "string", "enum": ["full", "active_window", "pointer", "selection"]}},
      ["question"], label="Looking at your screen")
def look_at_screen(ctx, a):
    if ctx.state.incognito:
        raise ToolError("Incognito is on, so I'm not looking at the screen.")
    region = a.get("region", "full")
    question = str(a["question"])
    if region == "pointer":
        question += "\n(The red ring marks where the user's mouse pointer was — that's what 'this' refers to.)"
    elif region == "selection":
        question += "\n(This is the exact area the user selected on their screen.)"
    answer = ctx.brain.see(screenshot_jpeg_b64(region), question)
    return answer or "I couldn't make out anything useful on the screen."


# ── clicking ─────────────────────────────────────────────────
RISKY = re.compile(r"\b(send|submit|post|publish|delete|remove|erase|uninstall|install|buy|purchase|pay|checkout|"
                   r"order|confirm|accept|agree|allow|transfer|sign ?out|log ?out|reply all|format|reset|discard|"
                   r"senden|löschen|kaufen|bestellen|bestätigen|bezahlen)\b", re.I)
POINT_PROMPT = ('Find this on the screenshot: "{target}".\nReply with JSON only: {{"found": true, "box_2d": [ymin, '
                'xmin, ymax, xmax], "label": "<what you found, a few words>"}} with coordinates normalized to '
                '0-1000 relative to the image, or {{"found": false, "reason": "<short reason>"}} if it isn\'t '
                'visible.')


def _confirm_click(a):
    target = str(a.get("target", ""))
    if RISKY.search(target):
        return f"Click “{target}”? That could send, buy, delete or change something."
    return None


def locate(ctx, target: str):
    """Ask the vision model where `target` is. Returns (x, y, label) in screen pixels."""
    from ..proactive import parse_json
    img, box = capture("full")
    ans = parse_json(ctx.brain.see(to_b64(img), POINT_PROMPT.format(target=target), raw=True))
    if not ans.get("found"):
        raise ToolError(f"I can't see “{target}” on the screen{': ' + ans['reason'] if ans.get('reason') else ''}.")
    coords = ans.get("box_2d") or ans.get("box") or ans.get("point")
    try:
        if len(coords) == 4:
            ymin, xmin, ymax, xmax = (float(v) for v in coords)
            nx, ny = (xmin + xmax) / 2, (ymin + ymax) / 2
        else:
            ny, nx = (float(v) for v in coords[:2])
    except Exception:
        raise ToolError("The vision model gave me coordinates I couldn't use. Try describing it differently.")
    nx, ny = min(max(nx, 0), 1000), min(max(ny, 0), 1000)
    x = int(box["left"] + nx / 1000 * box["width"])
    y = int(box["top"] + ny / 1000 * box["height"])
    return x, y, str(ans.get("label") or target)


@tool("screen_click",
      "Click something on screen by describing it — a button, link, icon, tab, menu item or text field, e.g. "
      "'the Send button', 'the search box', 'the second video thumbnail'. action: click, double_click, right_click, "
      "hover, scroll_up or scroll_down (scrolls where the thing is). After clicking, use look_at_screen if you need "
      "to check the result. To type into a field: click it first, then use type_text. Never for passwords.",
      {"target": {"type": "string", "description": "What to click, described so it's unambiguous"},
       "action": {"type": "string", "enum": ["click", "double_click", "right_click", "hover", "scroll_up",
                                              "scroll_down"]}},
      ["target"], confirm=_confirm_click, label=lambda a: f"Clicking {a.get('target')}")
def screen_click(ctx, a):
    require_windows()
    if ctx.state.incognito:
        raise ToolError("Incognito is on, so I can't look at the screen to click.")
    action = a.get("action", "click")
    x, y, label = locate(ctx, str(a["target"]))
    if action in ("scroll_up", "scroll_down"):
        winutil.click(x, y, move_only=True)
        winutil.scroll(5 if action == "scroll_up" else -5)
        return f"Scrolled {'up' if action == 'scroll_up' else 'down'} over {label}."
    winutil.click(x, y, button="right" if action == "right_click" else "left",
                  double=action == "double_click", move_only=action == "hover")
    time.sleep(0.4)
    verb = {"click": "Clicked", "double_click": "Double-clicked", "right_click": "Right-clicked",
            "hover": "Moved the mouse to"}[action]
    return f"{verb} {label} at ({x}, {y})."
