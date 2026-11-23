"""Speech-to-text (local faster-whisper or a cloud API) and wake-word matching."""
from __future__ import annotations

import difflib
import io
import logging
import os
import threading
import re

import numpy as np

from .config import MODELS_DIR, STT_PROVIDERS, ConfigError

log = logging.getLogger("emi.stt")


class LocalWhisper:
    """Runs Whisper on the CPU with int8 — fast enough on a Core Ultra, no GPU needed."""

    def __init__(self, model_name: str = "base.en", language: str = "en"):
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        from faster_whisper import WhisperModel
        self.name = model_name
        self.language = "en" if model_name.endswith(".en") else (language or None)
        log.info("loading whisper %s (first run downloads it)…", model_name)
        threads = max(2, min(8, (os.cpu_count() or 4) // 2))
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=threads,
                                  download_root=str(MODELS_DIR / "whisper"))
        self._lock = threading.Lock()   # the early name check runs while the listener keeps going

    def transcribe(self, audio: np.ndarray, prompt: str | None = None, strict: bool = False) -> str:
        """strict=True is for "did someone actually say something?" moments (spotting the name, follow-ups in a
        conversation): a speech detector first throws away sniffs, breaths, coughs and clicks, and Whisper's
        unsure guesses are dropped. Without it, Whisper tends to "hear" words in plain noise."""
        kw = dict(language=self.language, beam_size=1, initial_prompt=prompt, condition_on_previous_text=False,
                  without_timestamps=True, vad_filter=False)
        if strict:
            kw.update(vad_filter=True, vad_parameters={"threshold": 0.55, "min_speech_duration_ms": 200,
                                                        "min_silence_duration_ms": 400, "speech_pad_ms": 150})
        if strict and getattr(self, "_no_vad", False):
            kw.update(vad_filter=False)
            kw.pop("vad_parameters", None)
        with self._lock:
            try:
                segments = list(self.model.transcribe(audio.astype(np.float32), **kw)[0])
            except Exception as e:   # older faster-whisper, or its speech detector can't load: go without it
                if not kw.get("vad_filter"):
                    raise
                log.warning("speech detector unavailable (%s); using confidence checks only", e)
                self._no_vad = True
                kw.update(vad_filter=False)
                kw.pop("vad_parameters", None)
                segments = list(self.model.transcribe(audio.astype(np.float32), **kw)[0])
        if strict:
            segments = [s for s in segments
                        if getattr(s, "no_speech_prob", 0) < 0.6 and getattr(s, "avg_logprob", 0) > -1.0]
        return " ".join(s.text.strip() for s in segments).strip()


class CloudWhisper:
    """Groq / OpenAI speech-to-text. Faster on slow PCs, but your audio leaves the laptop."""

    def __init__(self, provider: str, language: str = "en"):
        preset = STT_PROVIDERS.get(provider)
        if not preset:
            raise ConfigError(f"hearing.stt must be local, {', or '.join(STT_PROVIDERS)}")
        key = os.environ.get(preset["key_env"], "")
        if not key:
            raise ConfigError(f"hearing.stt is '{provider}' but {preset['key_env']} isn't set in .env")
        from openai import OpenAI
        self.client = OpenAI(api_key=key, base_url=preset["base_url"], timeout=30)
        self.model = preset["model"]
        self.language = language or None

    def transcribe(self, audio: np.ndarray, prompt: str | None = None, strict: bool = False) -> str:
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, audio, 16000, format="WAV", subtype="PCM_16")
        kwargs = {"model": self.model, "file": ("speech.wav", buf.getvalue(), "audio/wav")}
        if self.language:
            kwargs["language"] = self.language
        if prompt:
            kwargs["prompt"] = prompt
        return (self.client.audio.transcriptions.create(**kwargs).text or "").strip()


# ── wake word ───────────────────────────────────────────────
FILLERS = {"hey", "hi", "ok", "okay", "yo", "oh", "um", "uh", "so", "and", "hello"}
NOISE_PHRASES = {"thank you", "thanks for watching", "you", "bye", "thank you for watching"}


def _norm(token: str) -> str:
    return re.sub(r"[^\w']", "", token.lower()).strip("'")


def match_wake(text: str, wake_words: list[str]) -> tuple[bool, str]:
    """Is the assistant's name said near the start? Returns (matched, the rest of the sentence)."""
    tokens = text.split()
    norm = [_norm(t) for t in tokens]
    wake = sorted({w.lower().strip() for w in wake_words if w.strip()}, key=lambda w: -len(w.split()))
    for i in range(min(5, len(norm))):
        if i > 0 and not all(n in FILLERS or not n for n in norm[:i]):
            break  # only fillers like "hey"/"ok" may come before the name
        for w in wake:
            parts = w.split()
            cand = " ".join(norm[i:i + len(parts)]).removesuffix("'s")
            if not cand:
                continue
            if cand == w or (len(w) >= 4 and difflib.SequenceMatcher(None, cand, w).ratio() >= 0.85):
                rest = " ".join(tokens[i + len(parts):]).lstrip(",.!?;: ").strip()
                return True, rest
    return False, ""


YES = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "go", "allow", "confirm", "do", "please", "correct",
       "absolutely", "affirmative", "ja"}
NO = {"no", "nope", "nah", "don't", "dont", "stop", "cancel", "deny", "wait", "never", "nein", "not"}


def yes_no(text: str) -> bool | None:
    words = {_norm(t) for t in text.split()}
    if words & NO:
        return False
    if words & YES or "go ahead" in text.lower() or "do it" in text.lower():
        return True
    return None


NOISE_SOUNDS = {"uh", "um", "umm", "uhm", "hmm", "hm", "mm", "mmm", "mhm", "ah", "oh", "er", "erm", "huh"}


def is_noise(text: str) -> bool:
    """Whisper's usual hallucinations on silence, and bare filler sounds ("uh", "hmm")."""
    t = re.sub(r"[^\w ]", "", text.lower()).strip()
    return not t or t in NOISE_PHRASES or all(w in NOISE_SOUNDS for w in t.split())
