"""The 'ears': listens for the name, then for your command.

Flow:  mic → voice-activity detection → while you're still talking, a tiny Whisper model peeks at
the first second or so: if it hears the name ("Hey Emi, …") the island pops up right away and shows
your voice as a live waveform. When you stop, the full sentence is transcribed with the better model
and sent to the agent. Saying just "Hey Emi" plays a chime and waits a few seconds for the command.
Everything here runs on your CPU — nothing is sent anywhere.

Conversation mode (on by default): once you've said "Hey Emi", she keeps listening. After each answer she
waits for your next request, no name needed, until you press the end shortcut (Alt+X), say "that's all",
or stay quiet for a few minutes.
"""
from __future__ import annotations

import logging
import queue
import re
import threading
import time

from . import winutil
from .audio import SAMPLE_RATE, Microphone, Segmenter
from .stt import is_noise, match_wake

log = logging.getLogger("emi.listener")

# "that's all", "stop listening", "bye Emi"… end a conversation (only when that's basically all you said)
END_RE = re.compile(r"\b(that'?s (all|it)|that is all|stop listening|good ?bye|bye( bye)?|we'?re done|"
                    r"nothing else|i'?m done|no,? (thanks|thank you))\b", re.I)


def is_goodbye(text: str) -> bool:
    return bool(END_RE.search(text or "")) and len((text or "").split()) <= 6


def _pretty_key(combo: str) -> str:
    return " + ".join(p.strip().capitalize() if len(p.strip()) > 1 else p.strip().upper()
                      for p in str(combo).split("+") if p.strip())


class Listener(threading.Thread):
    def __init__(self, cfg, mic: Microphone, wake_stt, cmd_stt, on_command, ui, player, is_paused, is_busy=None,
                 is_muted=None, on_wake=None):
        super().__init__(daemon=True, name="listener")
        self.cfg = cfg
        self.mic = mic
        self.wake_stt = wake_stt
        self.cmd_stt = cmd_stt
        self.on_command = on_command
        self.ui = ui
        self.player = player
        self.is_paused = is_paused             # callable → True while Emi is speaking
        self.assistant_name = cfg.name
        self.wake_words = [str(w) for w in cfg.get("assistant.wake_words", [])] + [cfg.name.lower()]
        self.wake_mode = str(cfg.get("hearing.wake_mode", "whisper")).lower()
        self.prompt = f"{cfg.name}, "
        self.segmenter = Segmenter(cfg.get("hearing.sensitivity", 1.0), cfg.get("hearing.silence_ms", 650),
                                   cfg.get("hearing.max_command_seconds", 20))
        self._trigger = threading.Event()
        self._cancel = threading.Event()
        self._capture: tuple[queue.Queue, float] | None = None
        self.awaiting_until = 0.0
        self.running = True
        self.early = bool(cfg.get("hearing.early_wake", True))
        self._utt = 0                      # counts utterances, so a late early-check can't touch the next one
        self._woken_utt = -1               # the utterance in which the name was already heard
        self._checks: set[int] = set()     # early checks started for the current utterance (by length)
        self._done_utt = -1                # the utterance that's already being handled
        self._wl = threading.Lock()
        # conversation mode
        self.is_busy = is_busy or (lambda: False)   # callable → True while Emi is working on or saying an answer
        self.is_muted = is_muted or (lambda: False) # callable → True while "Pause listening" is on (hotkeys still work)
        self.on_wake = on_wake or (lambda: None)    # called the moment she knows you're talking to her
        self.conversation = bool(cfg.get("hearing.conversation", True))
        self.conv_timeout = float(cfg.get("hearing.conversation_timeout", 180) or 0)
        self.end_key = _pretty_key(cfg.get("hotkeys.end", "alt+x"))
        self.in_conversation = False
        self._last_active = 0.0
        self._was_busy = False
        self._end = threading.Event()
        self._hearing_shown = False
        self._awaited_since_answer = False   # this command wait was opened by the conversation, not by the name

    # ── called from other threads ──
    def trigger(self):
        """Hotkey: listen for a command right now, no name needed."""
        self._trigger.set()

    def cancel(self):
        self._cancel.set()

    def end_conversation(self):
        """The end shortcut (Alt+X): stop listening for follow-ups."""
        self._end.set()

    def _start_conversation(self):
        if self.conversation:
            self.in_conversation = True
            self._last_active = time.time()

    def _listen_for_more(self) -> float:
        """How long to wait for the command after the name / hotkey."""
        return float("inf") if self.in_conversation else time.time() + 8

    def listen_once(self, timeout: float = 8.0) -> str | None:
        """Used for spoken yes/no confirmations. Returns the transcript or None."""
        q: queue.Queue = queue.Queue()
        self._capture = (q, time.time() + timeout)
        try:
            return q.get(timeout=timeout + 15)
        except queue.Empty:
            return None
        finally:
            self._capture = None

    # ── main loop ──
    def run(self):
        try:
            self.mic.start()
        except Exception as e:
            log.exception("microphone failed")
            self.ui.set_status("error", f"Mic problem: {e}. You can still type (Alt+Shift+S).")
            return
        self.ui.set_status("idle")
        seg = self.segmenter
        was_paused = False
        while self.running:
            frame = self.mic.read(0.3)
            now = time.time()

            if self._end.is_set():   # Alt+X: the conversation is over
                self._end.clear()
                if self.in_conversation or self.awaiting_until:
                    self.in_conversation = False
                    self.awaiting_until = 0
                    seg.reset()
                    self.player.chime("done")
                    log.info("conversation ended (shortcut)")
                    if not self.is_busy():
                        self.ui.set_status("idle")
            busy = self.is_busy()
            if busy:
                self._last_active = now
                self._was_busy = True
                if self.in_conversation and self.awaiting_until == float("inf") and not seg.in_speech:
                    self.awaiting_until = 0           # re-armed (with "your turn") once she's done

            if self.is_paused():  # don't listen to ourselves talking
                was_paused = True
                continue
            if was_paused:  # just finished speaking: drop any echo still in the buffer
                was_paused = False
                self.mic.flush()
                seg.reset()
                continue
            if self._cancel.is_set():
                self._cancel.clear()
                self.awaiting_until = 0
                seg.reset()
                self.ui.set_status("idle")
            if self._trigger.is_set():
                self._trigger.clear()
                self.mic.flush()
                seg.reset()
                self.player.chime("wake")
                self.on_wake()
                self._start_conversation()
                self.awaiting_until = self._listen_for_more()
                self._awaited_since_answer = False
                self.ui.set_status("listening", self._listening_text())
                continue
            if self._capture and now > self._capture[1] and not seg.in_speech:
                self._capture[0].put(None)
                self._capture = None
            if self.awaiting_until and now > self.awaiting_until and not seg.in_speech:
                self.awaiting_until = 0
                self.ui.set_status("idle")
            if self.in_conversation and not busy and not self._capture and not seg.in_speech:
                if self.conv_timeout and now - self._last_active > self.conv_timeout:
                    self.in_conversation = False      # nobody said anything for a while
                    self.awaiting_until = 0
                    log.info("conversation ended after %.0f s of quiet", self.conv_timeout)
                    self.ui.set_status("idle")
                elif not self.awaiting_until:         # she's done answering → your turn again
                    self.awaiting_until = float("inf")
                    self._awaited_since_answer = True
                    if self._was_busy:
                        self.player.chime("wake")
                    self._was_busy = False
                    self.ui.set_status("listening", self._listening_text())
            if frame is None:
                continue
            if self.is_muted() and not (self.awaiting_until or self._capture or self.in_conversation):
                if seg.in_speech:
                    seg.reset()
                continue

            started = seg.in_speech
            audio = seg.feed(frame)
            if seg.in_speech and not started:
                self._utt += 1
                self._checks = set()
                winutil.mark_pointer()   # remember where the mouse is, for "what's this?"
                self._hearing_shown = False
            if (seg.in_speech and not self._hearing_shown and (self.awaiting_until or self._capture)
                    and seg.voiced_total >= 10):   # ~0.3 s of real sound, not just a click or a sniff
                self._hearing_shown = True
                self.on_wake()
                self.ui.set_status("listening", "Hearing you…")
            if self.awaiting_until or self._capture or self._woken_utt == self._utt:
                level = getattr(self.ui, "level", None)
                if level:
                    level(seg.level())           # live waveform on the island
            if seg.in_speech and audio is None:
                self._maybe_early_check()
            if audio is None:
                continue
            try:
                self._handle_utterance(audio)
            except Exception:
                log.exception("failed to handle speech")
                self.ui.set_status("idle")

    def _maybe_early_check(self):
        """Peek for the name ~1.2 s and ~2.4 s into speech, so the island appears while you're still talking."""
        if (not self.early or self.wake_mode == "off" or self.awaiting_until or self._capture
                or self._woken_utt == self._utt):
            return
        ms = len(self.segmenter.buf) * 30
        for mark in (1200, 2400):
            if ms >= mark and mark not in self._checks:
                self._checks.add(mark)
                import numpy as np
                head = np.concatenate(self.segmenter.buf)[: SAMPLE_RATE * 3]
                threading.Thread(target=self._early_check, args=(head, self._utt), daemon=True).start()
                return

    def _early_check(self, head, utt: int):
        try:
            heard = self._spot(head)
        except Exception:
            return
        ok, _ = match_wake(heard, self.wake_words)
        log.debug("early check: %r wake=%s", heard, ok)
        with self._wl:
            if ok and utt == self._utt and utt != self._done_utt and self._woken_utt != utt:
                self._woken_utt = utt
                self.on_wake()
                self.ui.set_status("listening", "I'm listening…")

    def _transcribe(self, stt, audio, prompt=None, strict=False) -> str:
        try:
            return stt.transcribe(audio, prompt=prompt, strict=strict)
        except TypeError:   # a speech-to-text without the strict option
            return stt.transcribe(audio, prompt=prompt)

    def _spot(self, audio) -> str:
        """Transcribe just to look for the name: no hint about the name (that makes Whisper invent it in
        noise), and the speech detector on (so sniffs, coughs and lighters never get that far)."""
        return self._transcribe(self.wake_stt, audio, prompt=None, strict=True)

    def _listening_text(self) -> str:
        return f"Your turn · {self.end_key} to finish" if self.in_conversation else "Listening…"

    def _handle_utterance(self, audio):
        if self._capture:  # someone is waiting for a yes/no answer
            q, _ = self._capture
            self._capture = None
            q.put(self.cmd_stt.transcribe(audio, prompt="Yes. No."))
            return

        if self.awaiting_until:  # we already heard the name (or we're mid-conversation); this is the command
            self.awaiting_until = 0
            follow_up = self.in_conversation and self._awaited_since_answer
            if not follow_up:
                self.ui.set_status("thinking", "Got it…")
            text = self._transcribe(self.cmd_stt, audio, prompt=self.prompt, strict=follow_up)
            ok, rest = match_wake(text, self.wake_words)
            text = rest if ok and rest else text
            if follow_up and not is_noise(text):
                self.ui.set_status("thinking", "Got it…")
            if self.in_conversation and is_goodbye(text):
                self.in_conversation = False
                self.player.chime("done")
                log.info("conversation ended (%r)", text)
                self.ui.set_status("idle")
                return
            if is_noise(text):
                if not self.in_conversation:      # (in a conversation we simply keep listening)
                    self.ui.set_status("idle")
                return
            self._last_active = time.time()
            self.on_command(text)
            return

        if self.wake_mode == "off":
            return
        with self._wl:
            self._done_utt = self._utt
            woken = self._woken_utt == self._utt   # the early check already heard the name
        head = audio[: SAMPLE_RATE * 3]  # the name is at the start; only check the first 3 s
        heard = self._spot(head)
        ok, rest = match_wake(heard, self.wake_words)
        log.debug("heard: %r wake=%s (early=%s)", heard, ok, woken)
        if not ok and not woken:
            return
        if len(audio) > len(head) or self.cmd_stt is not self.wake_stt or not ok:
            full = self._transcribe(self.cmd_stt, audio, prompt=self.prompt, strict=not ok)
            ok2, rest2 = match_wake(full, self.wake_words)
            if not ok and not ok2:          # the early peek was wrong after all → put the island away
                self.ui.set_status("idle")
                return
            rest = rest2 if ok2 else full
        self._start_conversation()
        if len(rest.split()) >= 2 and not is_noise(rest):
            self.player.chime("done")
            self.ui.set_status("thinking", "Got it…")
            self.on_command(rest)          # "Emi, open Spotify" → one shot
        else:
            self.player.chime("wake")      # just "Emi" → wait for the command
            self.awaiting_until = self._listen_for_more()
            self._awaited_since_answer = False
            self.ui.set_status("listening", self._listening_text())
