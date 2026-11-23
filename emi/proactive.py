"""Proactive mode (off by default): every so often Emi glances at your screen and, only if she has one
genuinely useful idea, offers it on her island with "Do it" / "Not now". Otherwise she stays quiet.

Cost/privacy guards: never in incognito or gaming mode, never while you're away, only when the window you're
in has changed (or every few minutes), and a cooldown after you say "Not now".
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from difflib import SequenceMatcher

from . import winutil

log = logging.getLogger("emi.proactive")

PROMPT = """You are {name}, a helpful desktop assistant quietly glancing at the user's screen.
Active window: "{title}".
{memories}
Decide whether there is ONE genuinely useful, specific thing you could do for them right now (e.g. explain an \
error that's visible, summarise a long article they're reading, offer to set a reminder for a deadline on screen, \
fix a typo in what they're writing, find a file they seem to look for). Most of the time the answer is NO — \
don't interrupt for small talk, obvious things, games, videos, or private content (passwords, banking, messages).
Reply with JSON only:
{{"suggest": false}}
or
{{"suggest": true, "text": "<one short friendly sentence offering the help, max 15 words>", \
"action": "<a complete instruction for yourself to carry out if they say yes>"}}"""


def parse_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


class Proactive(threading.Thread):
    def __init__(self, cfg, state, brain, ui, agent, storage):
        super().__init__(daemon=True, name="proactive")
        self.cfg, self.state, self.brain, self.ui, self.agent, self.storage = cfg, state, brain, ui, agent, storage
        self.last_title = ""
        self.last_check = 0.0
        self.cooldown_until = 0.0
        self.recent: list[str] = []
        self.pending = False

    @property
    def interval(self) -> int:
        return int(getattr(self.state, "proactive_every", 0) or self.cfg.get("proactive.every_seconds", 120))

    def should_check(self, now: float, title: str) -> tuple[bool, str]:
        st = self.state
        if not getattr(st, "proactive", False):
            return False, "off"
        if st.incognito:
            return False, "incognito"
        if getattr(st, "gaming", False):
            return False, "gaming"
        if self.agent.busy.is_set() or self.pending:
            return False, "busy"
        if now < self.cooldown_until:
            return False, "cooldown"
        if winutil.idle_seconds() > 180:
            return False, "user away"
        if now - self.last_check < self.interval:
            return False, "too soon"
        if title == self.last_title and now - self.last_check < max(300, self.interval * 3):
            return False, "same window"
        return True, ""

    def run(self):
        while True:
            time.sleep(5)
            try:
                fg = winutil.foreground()
                now = time.time()
                ok, _why = self.should_check(now, fg.title)
                if ok:
                    self.check(fg.title)
            except Exception:
                log.exception("proactive check failed")

    def check(self, title: str):
        from .tools.screen import screenshot_jpeg_b64
        self.last_check, self.last_title = time.time(), title
        mems = self.storage.memories()[-20:]
        memories = ("Things you know about the user: " + "; ".join(m["text"] for m in mems)) if mems else ""
        image = screenshot_jpeg_b64("full", max_side=1280)
        prompt = PROMPT.format(name=self.cfg.name, title=title[:120], memories=memories)
        model = self.cfg.get("proactive.model") or None
        answer = parse_json(self.brain.see(image, prompt, raw=True, model=model))
        if not answer.get("suggest") or not answer.get("text") or not answer.get("action"):
            return
        text = str(answer["text"]).strip()[:160]
        if any(SequenceMatcher(None, text.lower(), r.lower()).ratio() > 0.7 for r in self.recent):
            return
        self.recent = (self.recent + [text])[-8:]
        self.offer(text, str(answer["action"]))

    def offer(self, text: str, action: str):
        self.pending = True

        def decide(yes: bool):
            self.pending = False
            if yes:
                self.agent.submit(action, "typed")
            else:
                self.cooldown_until = time.time() + float(self.cfg.get("proactive.cooldown_minutes", 10)) * 60
        self.ui.suggest(text, decide)
