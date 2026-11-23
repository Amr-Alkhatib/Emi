"""Text-to-speech: Emi's voice.

edge       — Microsoft's neural voices via the free Edge read-aloud service (online, no key, sounds great)
gemini     — Gemini's expressive voices (30 built in), or a voice you design from a description. Uses your Gemini key.
elevenlabs — any ElevenLabs voice, including one cloned from your own recordings (needs ELEVENLABS_API_KEY)
kokoro     — Kokoro-82M, a small open model that runs offline on your CPU; blend voices like "af_heart:60,af_bella:40"
sapi       — the built-in Windows voices (offline, robotic, always works)
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import personality
from .config import MODELS_DIR

log = logging.getLogger("emi.tts")


def clean_for_speech(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"```.*?```", " The code is on your screen. ", text, flags=re.S)
    text = re.sub(r"https?://\S+?(?=[.,;:!?)]*(?:\s|$))", "the link", text)
    text = re.sub(r"[*_#`>|]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def split_chunks(text: str, first_max: int = 90, max_len: int = 260) -> list[str]:
    """Short first chunk so Emi starts talking fast; later chunks are generated while she speaks."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, cur = [], ""
    for s in sentences:
        limit = first_max if not chunks else max_len
        if cur and len(cur) + len(s) + 1 > limit:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


class EdgeEngine:
    def __init__(self, voice: str, state):
        import edge_tts  # noqa: F401  (fail early if missing)
        self.voice = voice
        self.state = state

    def synth(self, text: str):
        import edge_tts
        import soundfile as sf
        p = personality.get(self.state.personality)
        comm = edge_tts.Communicate(text, self.voice, rate=p["edge_rate"], pitch=p["edge_pitch"])
        data = bytearray()
        for chunk in comm.stream_sync():
            if chunk.get("type") == "audio":
                data.extend(chunk["data"])
        if not data:
            raise RuntimeError("edge-tts returned no audio")
        audio, sr = sf.read(io.BytesIO(bytes(data)), dtype="float32")
        return audio, sr


def _decode_audio(raw: bytes, default_sr: int = 24000):
    """WAV/MP3 bytes → float32 array. Falls back to raw 16-bit PCM."""
    import soundfile as sf
    try:
        audio, sr = sf.read(io.BytesIO(raw), dtype="float32")
        return audio, sr
    except Exception:
        pcm = np.frombuffer(raw[: len(raw) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
        return pcm, default_sr


def _find_audio_b64(obj):
    """Gemini puts audio at steps[] → model_output → content[] → {type: audio, data}. Take the last one."""
    found = None
    if isinstance(obj, dict):
        if obj.get("type") == "audio" and isinstance(obj.get("data"), str):
            found = obj["data"]
        for v in obj.values():
            found = _find_audio_b64(v) or found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_audio_b64(v) or found
    return found


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiEngine:
    def __init__(self, voice: str, state, model: str = "gemini-3.8-flash-tts"):
        self.key = os.environ.get("GEMINI_API_KEY", "")
        if not self.key:
            raise RuntimeError("Gemini voices need GEMINI_API_KEY in .env")
        self.voice, self.state, self.model = voice or "Kore", state, model

    def synth(self, text: str):
        import httpx
        style = personality.get(self.state.personality).get("tts_style", "")
        content = {"type": "text", "text": text}
        if style:
            content["annotations"] = [{"type": "speech_metadata", "style": style}]
        body = {"model": self.model, "input": [{"type": "user_input", "content": [content]}],
                "response_format": {"type": "audio"},
                "generation_config": {"speech_config": [{"voice": self.voice}]}}
        r = httpx.post(f"{GEMINI_URL}/interactions", json=body, headers={"x-goog-api-key": self.key}, timeout=60)
        r.raise_for_status()
        data = _find_audio_b64(r.json())
        if not data:
            raise RuntimeError("Gemini returned no audio")
        return _decode_audio(base64.b64decode(data))


def design_gemini_voice(description: str, name: str, model: str = "gemini-3.8-flash-tts") -> tuple[str, bytes]:
    """Create a brand-new Gemini voice from a description. Returns (voice id, sample WAV bytes)."""
    import httpx
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("Designing a voice needs GEMINI_API_KEY in .env")
    body = {"store": True, "voice": {"model": model, "type": "prompted", "display_name": name[:60] or "Emi",
                                      "prompted": {"input": description[:1000]}}}
    r = httpx.post(f"{GEMINI_URL}/voices", json=body, headers={"x-goog-api-key": key}, timeout=90)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini said: {r.text[:300]}")
    js = r.json()
    sample = (js.get("sample_audio") or {}).get("data")
    return js["id"], base64.b64decode(sample) if sample else b""


class ElevenLabsEngine:
    def __init__(self, voice_id: str, state, model: str = ""):
        self.key = os.environ.get("ELEVENLABS_API_KEY", "")
        if not self.key or not voice_id:
            raise RuntimeError("ElevenLabs needs ELEVENLABS_API_KEY in .env and voice.elevenlabs_voice_id")
        self.voice_id, self.state, self.model = voice_id, state, model

    def synth(self, text: str):
        import httpx
        body = {"text": text}
        if self.model:
            body["model_id"] = self.model
        r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}",
                       params={"output_format": "mp3_44100_128"}, headers={"xi-api-key": self.key},
                       json=body, timeout=60)
        r.raise_for_status()
        return _decode_audio(r.content)


def elevenlabs_voices() -> list[tuple[str, str]]:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        return []
    try:
        import httpx
        r = httpx.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key}, timeout=8)
        r.raise_for_status()
        return [(v["voice_id"], v.get("name", v["voice_id"])) for v in r.json().get("voices", [])][:40]
    except Exception:
        return []


class KokoroEngine:
    def __init__(self, voice: str, state):
        from kokoro_onnx import Kokoro
        folder = MODELS_DIR / "kokoro"
        models = sorted(folder.glob("kokoro*.onnx"))
        voices = sorted(folder.glob("voices*.bin"))
        if not models or not voices:
            raise RuntimeError(f"Put kokoro-v1.0.onnx and voices-v1.0.bin in {folder} (see README)")
        self.kokoro = Kokoro(str(models[0]), str(voices[0]))
        self.state = state
        self.voice = self._blend(voice) if ":" in voice else voice

    def _blend(self, spec: str):
        """'af_heart:60,af_bella:40' → a new voice mixed from two (or more) Kokoro voices."""
        parts = [p.split(":") for p in spec.split(",") if ":" in p]
        total = sum(float(w) for _, w in parts) or 1.0
        return sum(self.kokoro.get_voice_style(n.strip()) * (float(w) / total) for n, w in parts)

    def synth(self, text: str):
        speed = personality.get(self.state.personality)["kokoro_speed"]
        samples, sr = self.kokoro.create(text, voice=self.voice, speed=speed, lang="en-us")
        return np.asarray(samples, dtype=np.float32), sr


class SapiEngine:
    """Windows' built-in voices through PowerShell. Text goes via a temp file (no command injection)."""

    def __init__(self, *_):
        if sys.platform != "win32":
            raise RuntimeError("SAPI voices are Windows-only")

    def synth(self, text: str):
        import soundfile as sf
        with tempfile.TemporaryDirectory() as d:
            txt, wav = Path(d) / "t.txt", Path(d) / "o.wav"
            txt.write_text(text, encoding="utf-8")
            q = lambda p: str(p).replace("'", "''")  # noqa: E731  (escape for a PowerShell '...' string)
            ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  f"$s.SetOutputToWaveFile('{q(wav)}'); $s.Speak((Get-Content -Raw -Encoding UTF8 '{q(txt)}')); "
                  "$s.Dispose()")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=60,
                           creationflags=0x08000000)
            audio, sr = sf.read(str(wav), dtype="float32")
        return audio, sr


EDGE_VOICES = [("en-US-EmmaMultilingualNeural", "Emma · US, warm"), ("en-US-AvaMultilingualNeural", "Ava · US, bright"),
               ("en-US-AndrewMultilingualNeural", "Andrew · US"), ("en-US-BrianMultilingualNeural", "Brian · US"),
               ("en-GB-SoniaNeural", "Sonia · UK"), ("en-AU-NatashaNeural", "Natasha · Australia"),
               ("de-DE-SeraphinaMultilingualNeural", "Seraphina · German"),
               ("de-DE-FlorianMultilingualNeural", "Florian · German")]
GEMINI_VOICES = [("Zephyr", "bright"), ("Puck", "upbeat"), ("Kore", "firm"), ("Fenrir", "excitable"),
                 ("Leda", "youthful"), ("Aoede", "breezy"), ("Autonoe", "bright"), ("Laomedeia", "upbeat"),
                 ("Sadachbia", "lively"), ("Achird", "friendly"), ("Sulafat", "warm"), ("Callirrhoe", "easy-going"),
                 ("Umbriel", "easy-going"), ("Despina", "smooth"), ("Algieba", "smooth"), ("Erinome", "clear"),
                 ("Iapetus", "clear"), ("Vindemiatrix", "gentle"), ("Achernar", "soft"), ("Enceladus", "breathy"),
                 ("Charon", "informative"), ("Rasalgethi", "informative"), ("Sadaltager", "knowledgeable"),
                 ("Orus", "firm"), ("Alnilam", "firm"), ("Schedar", "even"), ("Gacrux", "mature"),
                 ("Pulcherrima", "forward"), ("Zubenelgenubi", "casual"), ("Algenib", "gravelly")]
KOKORO_VOICES = ["af_heart", "af_bella", "af_nicole", "af_sky", "am_michael", "am_adam", "bf_emma", "bm_george"]


class TTS:
    def __init__(self, cfg, state, player):
        self.cfg = cfg
        self.player = player
        self.state = state
        self.speaking = threading.Event()
        self._cache: dict = {}    # short phrases already spoken once → their audio
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.fallback = SapiEngine() if sys.platform == "win32" else None
        picked = getattr(state, "voice", None) or {}
        self.engine_name, self.voice_name = "", ""
        self.engine = None
        if not self.set_voice(picked.get("engine") or str(cfg.get("voice.engine", "edge")).lower(),
                              picked.get("voice") or "", remember=False):
            self.engine = self.fallback
            self.engine_name, self.voice_name = "sapi", ""

    def _default_voice(self, engine: str) -> str:
        return {"edge": self.cfg.get("voice.edge_voice", "en-US-EmmaMultilingualNeural"),
                "gemini": self.cfg.get("voice.gemini_voice", "Kore"),
                "elevenlabs": self.cfg.get("voice.elevenlabs_voice_id", ""),
                "kokoro": self.cfg.get("voice.kokoro_voice", "af_heart")}.get(engine, "")

    def set_voice(self, engine: str, voice: str = "", remember: bool = True) -> bool:
        """Switch voice while running (from the menu). Returns False if that voice can't be used."""
        engine = (engine or "edge").lower()
        voice = voice or self._default_voice(engine)
        try:
            new = {"edge": lambda: EdgeEngine(voice, self.state),
                   "gemini": lambda: GeminiEngine(voice, self.state,
                                                  self.cfg.get("voice.gemini_tts_model", "gemini-3.8-flash-tts")),
                   "elevenlabs": lambda: ElevenLabsEngine(voice, self.state,
                                                          self.cfg.get("voice.elevenlabs_model", "")),
                   "kokoro": lambda: KokoroEngine(voice, self.state),
                   "sapi": lambda: SapiEngine()}[engine]()
        except Exception as e:
            log.warning("voice %s/%s unavailable: %s", engine, voice, e)
            return False
        self.engine, self.engine_name, self.voice_name = new, engine, voice
        if remember:
            self.state.set("voice", {"engine": engine, "voice": voice})
        return True

    def options(self) -> list[dict]:
        """Voices for the picker: [{group, items: [{value: 'engine|voice', label}]}]."""
        groups = [{"group": "Free voices (Microsoft Edge)",
                   "items": [{"value": f"edge|{v}", "label": n} for v, n in EDGE_VOICES]}]
        if os.environ.get("GEMINI_API_KEY"):
            mine = [{"value": f"gemini|{v['id']}", "label": f"★ {v['name']} · your design"}
                    for v in (getattr(self.state, "custom_voices", None) or [])]
            groups.append({"group": "Gemini voices (expressive)",
                           "items": mine + [{"value": f"gemini|{v}", "label": f"{v} · {d}"} for v, d in GEMINI_VOICES]})
        el = elevenlabs_voices()
        if el:
            groups.append({"group": "ElevenLabs", "items": [{"value": f"elevenlabs|{v}", "label": n} for v, n in el]})
        if (MODELS_DIR / "kokoro").exists() and any((MODELS_DIR / "kokoro").glob("kokoro*.onnx")):
            items = [{"value": f"kokoro|{v}", "label": v} for v in KOKORO_VOICES]
            blend = self.cfg.get("voice.kokoro_voice", "")
            if ":" in str(blend):
                items.insert(0, {"value": f"kokoro|{blend}", "label": f"Your blend ({blend})"})
            groups.append({"group": "Kokoro (offline)", "items": items})
        if sys.platform == "win32":
            groups.append({"group": "Windows (offline)", "items": [{"value": "sapi|", "label": "Windows voice"}]})
        current = f"{self.engine_name}|{self.voice_name}"
        if not any(i["value"] == current for g in groups for i in g["items"]):
            groups[0]["items"].insert(0, {"value": current, "label": f"{self.voice_name or self.engine_name} (current)"})
        return [{"current": current}] + groups

    def _synth(self, text: str):
        key = (self.engine_name, self.voice_name, getattr(self.state, "personality", ""), text)
        if len(text) <= 60 and key in self._cache:
            return self._cache[key]
        out = self._synth_now(text)
        if len(text) <= 60 and out[0] is not None:
            if len(self._cache) > 80:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = out
        return out

    def _synth_now(self, text: str):
        for eng in (self.engine, self.fallback):
            if eng is None:
                continue
            try:
                return eng.synth(text)
            except Exception as e:
                log.warning("tts %s failed: %s", type(eng).__name__, e)
        return None, None

    def stop(self):
        self._stop.set()
        self.player.stop()

    def speak(self, text: str, on_chunk=None) -> None:
        """Say it. on_chunk(text) is called as each sentence starts playing (the island shows it)."""
        text = clean_for_speech(text)
        if not text or self.engine is None:
            return
        with self._lock:
            self._stop.clear()
            self.speaking.set()
            pool = ThreadPoolExecutor(max_workers=2)
            try:
                chunks = split_chunks(text)
                t0 = time.monotonic()
                futures = [pool.submit(self._synth, c) for c in chunks]
                for n, (chunk, fut) in enumerate(zip(chunks, futures)):
                    if self._stop.is_set():
                        break
                    audio, sr = fut.result()
                    if audio is None:
                        continue
                    if audio.ndim > 1:
                        audio = audio.mean(axis=1)
                    if n == 0:
                        log.info("voice (%s) started after %.1f s", self.engine_name, time.monotonic() - t0)
                    if on_chunk:
                        try:
                            on_chunk(chunk)
                        except Exception:
                            pass
                    if not self.player.play(audio, sr, self._stop):
                        break
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
                self.speaking.clear()
