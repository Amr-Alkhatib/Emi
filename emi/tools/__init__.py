"""Tool registry. A 'tool' is a Python function the AI is allowed to call.

Add your own tool in any file in this folder:

    from . import tool

    @tool("flip_coin", "Flip a coin.", {"times": {"type": "integer", "description": "How many flips"}})
    def flip_coin(ctx, a):
        import random
        return ", ".join(random.choice(["heads", "tails"]) for _ in range(int(a.get("times", 1))))

then import that file in Registry.__init__ below. That's it — Emi can now use it.
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger("emi.tools")
IS_WINDOWS = sys.platform == "win32"


class ToolError(Exception):
    """Raise this inside a tool to return a friendly error to the AI."""


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    required: list
    func: Callable
    confirm: Any = False          # False | True | callable(args) -> str | None
    label: Any = None             # str | callable(args) -> str   (shown in the UI while running)

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": self.params, "required": self.required}}}

    def confirmation_text(self, args: dict) -> str | None:
        if callable(self.confirm):
            return self.confirm(args)
        if self.confirm:
            return f"Allow {self.name}?\n{json.dumps(args, ensure_ascii=False, indent=1)}"
        return None


_TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, params: dict | None = None, required: list | None = None,
         confirm: Any = False, label: Any = None):
    def deco(fn):
        _TOOLS[name] = Tool(name, description, params or {}, required or [], fn, confirm, label)
        return fn
    return deco


def require_windows():
    if not IS_WINDOWS:
        raise ToolError("This only works on Windows.")


@dataclass
class ToolContext:
    cfg: Any
    storage: Any
    state: Any
    brain: Any
    ui: Any
    registry: Any = None
    stop_event: Any = None


class Registry:
    def __init__(self, cfg):
        # importing these files registers their tools
        from . import apps, claude_code, documents, files, productivity, screen, system, web  # noqa: F401
        disabled = set(cfg.get("tools.disabled", []) or [])
        self.always_allow = set(cfg.get("safety.always_allow", []) or [])
        self.tools = {n: t for n, t in _TOOLS.items() if n not in disabled}
        self.confirm_fn: Callable[[str], bool] | None = None
        # set by main.py: returns True when the user switched on full access (no Allow/Deny questions)
        self.full_access: Callable[[], bool] = lambda: False
        # set by main.py: lets tools switch on/off at runtime (e.g. the Claude helper toggle)
        self.is_enabled: Callable[[str], bool] = lambda name: True

    def schemas(self) -> list[dict]:
        return [t.schema() for n, t in self.tools.items() if self.is_enabled(n)]

    def label(self, name: str, args: dict) -> str:
        t = self.tools.get(name)
        if t and t.label:
            try:
                return t.label(args) if callable(t.label) else str(t.label)
            except Exception:
                pass
        return name.replace("_", " ").capitalize()

    def run(self, name: str, args: Any, ctx: ToolContext) -> str:
        t = self.tools.get(name)
        if not t or not self.is_enabled(name):
            return f"Error: there is no tool called '{name}'."
        if not isinstance(args, dict):
            args = {}
        missing = [r for r in t.required if args.get(r) in (None, "")]
        if missing:
            return f"Error: missing argument(s): {', '.join(missing)}"

        if name not in self.always_allow and not self.full_access():
            try:
                question = t.confirmation_text(args)
            except ToolError as e:
                return f"Error: {e}"
            if question:
                ok = bool(self.confirm_fn and self.confirm_fn(question))
                log.info("confirm %s -> %s", name, ok)
                if not ok:
                    return "The user did NOT allow this. Don't retry it; tell them it was cancelled."
        try:
            result = t.func(ctx, args)
        except ToolError as e:
            return f"Error: {e}"
        except Exception as e:  # never let a tool crash the assistant
            log.exception("tool %s failed", name)
            return f"Error while running {name}: {type(e).__name__}: {e}"
        result = "" if result is None else str(result)
        if len(result) > 9000:
            result = result[:9000] + "\n…(truncated)"
        return result or "Done."
