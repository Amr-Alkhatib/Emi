"""Instant commands: everyday requests Emi can do on her own, without asking the AI first.

"Open Spotify", "next song", "volume to 30", "what time is it", "lock my PC"… are recognised here and done
right away (well under a second). Anything that isn't a clear match goes to the AI as usual, and so does
anything that fails here (for example an app that isn't installed: the AI then tries a website instead).
"""
from __future__ import annotations

import random
import re
from datetime import datetime

POLITE = re.compile(r"^(?:(?:hey|ok|okay|hi)[, ]+)?(?:emi[,.!]?\s+)?(?:(?:can|could|would|will) you\s+|please\s+|just\s+)*",
                    re.I)
TAIL = re.compile(r"(?:\s+(?:please|for me|now|thanks|thank you|real quick))+$", re.I)


def normalise(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"[.!?,;:]+$", "", t)
    t = POLITE.sub("", t)
    t = TAIL.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" ,.")
    return t


APP = r"(?P<app>[a-z0-9][\w .+&'-]{1,30}?)"
# (pattern, tool, args builder, reply builder)
RULES: list[tuple] = [
    (r"^open (?:my |the )?(?P<folder>downloads|documents|desktop|pictures|music|videos)(?: folder)?$",
     "open_path", lambda m: {"path": m["folder"].capitalize()}, lambda m: f"Opening {m['folder'].capitalize()}."),
    (rf"^(?:open|launch|start|run|fire up|bring up|pull up)(?: up)?(?: the| my)? {APP}(?: app| application| program)?$",
     "open_app", lambda m: {"name": m["app"]}, lambda m: f"Opening {_title(m['app'])}."),
    (r"^(?:play|resume|unpause|pause)(?: (?:the|my))?(?: music| song| video| it| playback)?$",
     "media_control", lambda m: {"action": "play_pause"}, lambda m: random.choice(["Done.", "Got it."])),
    (r"^(?:next|skip)(?: (?:song|track|video|one))?$|^skip (?:this|it)(?: song| track)?$|^play the next (?:song|track|one)$",
     "media_control", lambda m: {"action": "next"}, lambda m: "Skipping."),
    (r"^(?:previous|go back|last)(?: (?:song|track|video|one))?$|^play the (?:previous|last) (?:song|track|one)$",
     "media_control", lambda m: {"action": "previous"}, lambda m: "Going back."),
    (r"^(?:turn (?:it|the volume|the sound) up|volume up|louder|make it louder|turn up the volume)$",
     "media_control", lambda m: {"action": "volume_up"}, lambda m: "Louder."),
    (r"^(?:turn (?:it|the volume|the sound) down|volume down|quieter|make it quieter|turn down the volume)$",
     "media_control", lambda m: {"action": "volume_down"}, lambda m: "Quieter."),
    (r"^(?:mute|unmute)(?: (?:the )?(?:sound|volume|audio|pc|computer|it))?$",
     "media_control", lambda m: {"action": "mute"}, lambda m: "Done."),
    (r"^(?:set )?(?:the )?volume (?:to |at )?(?P<level>\d{1,3})(?: ?%| percent)?$|^(?:set|turn) (?:the )?volume to (?P<level2>\d{1,3})(?: ?%| percent)?$",
     "media_control", lambda m: {"action": "set_volume", "level": min(100, int(m["level"] or m["level2"]))},
     lambda m: f"Volume {min(100, int(m['level'] or m['level2']))}."),
    (r"^lock(?: (?:the|my) (?:pc|computer|laptop|screen))?$|^lock (?:it|the screen)$",
     "power", lambda m: {"action": "lock"}, lambda m: "Locking."),
]
def _title(name: str) -> str:
    return " ".join(w.upper() if len(w) <= 2 else w.capitalize() for w in name.split())


TIME = re.compile(r"^what(?:'s| is) the time(?: now)?$|^what time is it(?: now)?$|^time$")
DATE = re.compile(r"^what(?:'s| is) (?:the |today'?s )?date(?: today)?$|^what day is (?:it|today)$|^what(?:'s| is) today$")
TOO_MUCH = re.compile(r"\b(and|then|after|also|with|in|on|to|about|that|which|where)\b")   # sounds like more than one step


def match(text: str):
    """→ ("say", reply) | ("tool", name, args, reply) | None"""
    t = normalise(text)
    if not t or len(t) > 60:
        return None
    if TIME.match(t):
        return "say", datetime.now().strftime("It's %H:%M.")
    if DATE.match(t):
        return "say", datetime.now().strftime("It's %A, %d %B.").replace(" 0", " ")
    for pattern, tool, args, reply in RULES:
        m = re.match(pattern, t)
        if not m:
            continue
        if tool == "open_app" and (TOO_MUCH.search(m["app"]) or len(m["app"].split()) > 3):
            return None       # "open word and write…" is a job for the AI
        return "tool", tool, args(m), reply(m)
    return None
