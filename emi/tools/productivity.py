"""Memory, notes, reminders, routines ('your usual') and settings."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

from . import ToolError, tool
from .apps import best_match

UNITS = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
         "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
         "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
         "d": 86400, "day": 86400, "days": 86400}


def parse_when(when: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    s = str(when).strip().lower()
    # relative: "in 10 minutes", "1 hour 30 min", "90s"
    pairs = re.findall(r"(\d+(?:\.\d+)?)\s*([a-z]+)", s)
    if pairs and all(u in UNITS for _, u in pairs) and re.fullmatch(r"(in\s+)?[\d.\sa-z]+", s):
        return now + timedelta(seconds=sum(float(n) * UNITS[u] for n, u in pairs))
    # ISO: 2026-11-23T09:00 or 2026-11-23 09:00
    try:
        dt = datetime.fromisoformat(str(when).strip().replace("Z", "+00:00"))
        return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        pass
    # clock time: "9:30", "7pm", "tomorrow 8:15 am"
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", s)
    if m:
        hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        if hour < 24 and minute < 60:
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if "tomorrow" in s:
                dt += timedelta(days=1)
            elif dt <= now:
                dt += timedelta(days=1)
            return dt
    raise ToolError(f"I couldn't understand the time '{when}'. Use ISO like 2026-11-23T09:00 or 'in 20 minutes'.")


# ── memory ──────────────────────────────────────────────────
@tool("remember", "Save a fact about the user for the future (preferences, names, projects, routines). "
      "Use whenever the user says 'remember...'.",
      {"fact": {"type": "string", "description": "The fact, written as a short sentence"}}, ["fact"],
      label="Saving to memory")
def remember(ctx, a):
    if ctx.state.incognito:
        raise ToolError("Incognito is on, so I'm not saving new memories.")
    m = ctx.storage.add_memory(str(a["fact"]))
    return f"Saved memory {m['id']}: {m['text']}"


@tool("forget", "Delete a saved memory, by its id (like m3) or by words it contains.",
      {"memory": {"type": "string"}}, ["memory"], label="Forgetting")
def forget(ctx, a):
    removed = ctx.storage.remove_memory(str(a["memory"]))
    return f"Forgot: {removed['text']}" if removed else "I couldn't find that memory."


@tool("search_memory", "Search everything saved in memory. Use an empty query to list all memories.",
      {"query": {"type": "string"}}, ["query"], label="Checking memory")
def search_memory(ctx, a):
    hits = ctx.storage.search_memories(str(a.get("query", "")))
    return "\n".join(f"{m['id']}: {m['text']}" for m in hits[:40]) or "No memories found."


# ── notes ───────────────────────────────────────────────────
@tool("save_note", "Save a note (appends if a note with this title exists).",
      {"title": {"type": "string"}, "content": {"type": "string"}}, ["title", "content"], label="Saving a note")
def save_note(ctx, a):
    path = ctx.storage.save_note(str(a["title"]), str(a["content"]))
    return f"Saved note: {path.name}"


@tool("search_notes", "Find notes containing some text. Empty query lists recent notes.",
      {"query": {"type": "string"}}, ["query"], label="Searching notes")
def search_notes(ctx, a):
    hits = ctx.storage.search_notes(str(a.get("query", "")))
    return "\n".join(hits[:15]) or "No notes found."


# ── reminders ───────────────────────────────────────────────
@tool("set_reminder", "Set a reminder or timer. Emi will speak it out loud when it's due.",
      {"text": {"type": "string", "description": "What to remind about"},
       "when": {"type": "string", "description": "ISO local time like 2026-11-23T09:00, or relative like 'in 20 minutes'"}},
      ["text", "when"], label="Setting a reminder")
def set_reminder(ctx, a):
    due = parse_when(a["when"])
    r = ctx.storage.add_reminder(str(a["text"]), due)
    return f"Reminder {r['id']} set for {due:%A %H:%M} ({due:%Y-%m-%d}): {r['text']}"


@tool("list_reminders", "List open reminders (or all, including done ones).",
      {"include_done": {"type": "boolean"}}, [], label="Checking reminders")
def list_reminders(ctx, a):
    items = ctx.storage.reminders(include_done=bool(a.get("include_done")))
    if not items:
        return "No reminders."
    return "\n".join(f"{r['id']}: {r['text']} — {r['due'].replace('T', ' ')}{' (done)' if r.get('done') else ''}"
                     for r in items)


@tool("complete_reminder", "Mark a reminder as done / cancel it, by id (like r2).",
      {"id": {"type": "string"}}, ["id"], label="Updating reminders")
def complete_reminder(ctx, a):
    r = ctx.storage.update_reminder(str(a["id"]), done=True)
    return f"Done: {r['text']}" if r else "No reminder with that id."


# ── routines ('your usual') ────────────────────────────────
STEP_TOOLS = {"open_app": ("open_app", "name"), "open_url": ("open_url", "url"),
              "open_path": ("open_path", "path"), "media": ("media_control", "action")}


@tool("run_routine", "Run one of the user's saved routines (a set of apps/links/settings), e.g. 'study mode'.",
      {"name": {"type": "string"}}, ["name"], label=lambda a: f"Starting {a.get('name')}")
def run_routine(ctx, a):
    routines = ctx.cfg.get("routines", {}) or {}
    if not routines:
        raise ToolError("No routines are set up yet. Add them in config.yaml under 'routines'.")
    match = best_match(str(a["name"]), [str(k).lower() for k in routines])
    if not match:
        raise ToolError(f"No routine called '{a['name']}'. Available: {', '.join(routines)}")
    steps = next(v for k, v in routines.items() if str(k).lower() == match) or []
    log, said = [], []
    for step in steps:
        if ctx.stop_event is not None and ctx.stop_event.is_set():
            log.append("stopped by user")
            break
        if not isinstance(step, dict) or len(step) != 1:
            continue
        kind, value = next(iter(step.items()))
        if kind in STEP_TOOLS:
            tool_name, arg = STEP_TOOLS[kind]
            log.append(f"{kind} {value}: " + ctx.registry.run(tool_name, {arg: value}, ctx))
        elif kind == "volume":
            log.append(ctx.registry.run("media_control", {"action": "set_volume", "level": int(value)}, ctx))
        elif kind == "wait":
            time.sleep(min(float(value), 15))
        elif kind == "say":
            said.append(str(value))
    result = f"Routine '{match}' finished.\n" + "\n".join(log)
    if said:
        result += "\nTell the user: " + " ".join(said)
    return result


# ── settings ────────────────────────────────────────────────
@tool("change_setting", "Change Emi's own settings: personality (hype, chill, sleepy), incognito (on/off), "
      "reply_mode (auto = speak and also show long answers, voice = speak only, text = written answers only, "
      "both = always speak and write), island (notch = a slim tab at the top of the screen when idle, hide = nothing).",
      {"setting": {"type": "string", "enum": ["personality", "incognito", "reply_mode", "island", "speak_replies"]},
       "value": {"type": "string"}}, ["setting", "value"], label="Updating settings")
def change_setting(ctx, a):
    from ..personality import PERSONALITIES
    setting, value = a["setting"], str(a["value"]).strip().lower()
    if setting not in ("personality", "incognito", "reply_mode", "island", "speak_replies"):
        # safety settings (like full access) can only be changed by the user, in the Control Center or config.yaml
        raise ToolError("I can't change that one myself. It's in my Control Center.")
    if setting == "personality":
        if value not in PERSONALITIES:
            raise ToolError(f"Personalities: {', '.join(PERSONALITIES)}")
        ctx.state.set("personality", value)
        return f"Personality is now {value}."
    if setting == "reply_mode" or setting == "speak_replies":
        if setting == "speak_replies":   # older wording: speak replies on/off
            value = "auto" if value in ("on", "true", "yes", "1", "enable", "enabled") else "text"
        value = {"spoken": "voice", "speak": "voice", "written": "text", "write": "text"}.get(value, value)
        if value not in ("auto", "voice", "text", "both"):
            raise ToolError("Reply modes: auto, voice, text, both")
        ctx.state.set("reply_mode", value)
        return f"Reply mode is now {value}."
    if setting == "island":
        value = "notch" if value in ("pill", "show", "on", "tab") else value
        if value not in ("hide", "notch"):
            raise ToolError("Island options: notch, hide")
        ctx.state.set("idle_look", value)
        return "I'll disappear completely when idle." if value == "hide" else "I'll wait as a slim notch at the top."
    on = value in ("on", "true", "yes", "1", "enable", "enabled")
    ctx.state.set(setting, on)
    return f"{setting.replace('_', ' ').capitalize()} is now {'on' if on else 'off'}."
