"""Microphone input, a simple voice-activity detector, and audio playback."""
from __future__ import annotations

import collections
import logging
import queue
import threading
import time

import numpy as np

log = logging.getLogger("emi.audio")

SAMPLE_RATE = 16000          # what Whisper wants
FRAME_MS = 30
FRAME = SAMPLE_RATE * FRAME_MS // 1000   # 480 samples


class Microphone:
    """Streams 30 ms float32 frames at 16 kHz into a queue."""

    def __init__(self, device=None):
        import sounddevice as sd
        self.sd = sd
        self.device = device
        self.q: queue.Queue = queue.Queue(maxsize=2000)
        self.stream = None
        self.rate = SAMPLE_RATE

    def start(self):
        sd = self.sd
        try:
            self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                         blocksize=FRAME, device=self.device, callback=self._cb)
            self.rate = SAMPLE_RATE
        except Exception as e:  # some mics refuse 16 kHz: record at their native rate and resample
            info = sd.query_devices(self.device, "input")
            self.rate = int(info["default_samplerate"])
            log.info("mic doesn't support 16 kHz (%s); using %d Hz + resampling", e, self.rate)
            self.stream = sd.InputStream(samplerate=self.rate, channels=1, dtype="float32",
                                         blocksize=int(self.rate * FRAME_MS / 1000), device=self.device,
                                         callback=self._cb)
        self.stream.start()

    def _cb(self, indata, frames, time_info, status):
        x = indata[:, 0]
        if self.rate != SAMPLE_RATE:
            x = np.interp(np.linspace(0, len(x), FRAME, endpoint=False), np.arange(len(x)), x).astype(np.float32)
        try:
            self.q.put_nowait(x.copy())
        except queue.Full:
            pass

    def read(self, timeout=0.5):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def flush(self):
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()


class Segmenter:
    """Energy-based voice activity detection: feed frames, get back finished utterances.

    It learns the background-noise level on its own. `sensitivity` > 1 needs louder speech.
    """

    def __init__(self, sensitivity=1.0, silence_ms=800, max_seconds=20, preroll_ms=300):
        self.sensitivity = float(sensitivity)
        self.silence_frames = max(1, int(silence_ms / FRAME_MS))
        self.max_frames = int(max_seconds * 1000 / FRAME_MS)
        self.preroll = collections.deque(maxlen=max(1, int(preroll_ms / FRAME_MS)))
        self.noise = 0.004
        self.last_rms = 0.0
        self.reset()

    def reset(self):
        self.in_speech = False
        self.buf: list[np.ndarray] = []
        self.voiced_run = 0
        self.silent_run = 0
        self.voiced_total = 0
        self.rms_log: list[float] = []
        self.preroll.clear()

    @property
    def threshold(self) -> float:
        return max(self.noise * 3.0, 0.006) * self.sensitivity

    def level(self) -> float:
        """How loud the last frame was compared with the room, roughly 0..1 for speech."""
        floor = max(self.noise * 1.5, 0.002)
        return float(min(1.0, max(0.0, (self.last_rms - floor) / 0.07)) ** 0.6)

    def feed(self, frame: np.ndarray):
        rms = float(np.sqrt(np.mean(frame ** 2)) + 1e-9)
        self.last_rms = rms
        thr = self.threshold
        if not self.in_speech:
            if rms < thr:  # slowly track the room's noise level
                self.noise = 0.95 * self.noise + 0.05 * rms
                self.voiced_run = 0
            else:
                self.voiced_run += 1
            self.preroll.append(frame)
            if self.voiced_run >= 3:  # ~90 ms of sound → speech started
                self.in_speech = True
                self.buf = list(self.preroll)
                self.silent_run = 0
                self.voiced_total = self.voiced_run
            return None

        self.buf.append(frame)
        self.rms_log.append(rms)
        if rms < thr * 0.8:
            self.silent_run += 1
        else:
            self.silent_run = 0
            self.voiced_total += 1
        if self.silent_run >= self.silence_frames or len(self.buf) >= self.max_frames:
            audio = np.concatenate(self.buf)
            enough = self.voiced_total * FRAME_MS >= 250
            if len(self.buf) >= self.max_frames:  # never went quiet → the room got louder; adapt
                self.noise = 0.5 * self.noise + 0.5 * float(np.median(self.rms_log)) / 2.5
            self.reset()
            return audio if enough else None
        return None


class Player:
    """Plays audio and can be interrupted (Esc)."""

    def __init__(self, device=None):
        self.device = device
        self._lock = threading.Lock()
        self.on_level = None          # callable(0..1) — drives the island's waveform while Emi talks

    @staticmethod
    def envelope(audio: np.ndarray, sr: int, step_s: float = 0.03) -> np.ndarray:
        """Loudness every 30 ms, scaled to roughly 0..1 for speech."""
        n = max(1, int(sr * step_s))
        usable = len(audio) // n * n
        if usable == 0:
            return np.zeros(1, dtype=np.float32)
        rms = np.sqrt(np.mean(np.square(audio[:usable].astype(np.float32)).reshape(-1, n), axis=1))
        peak = float(np.percentile(rms, 95)) or 1.0
        return np.clip(rms / peak, 0, 1) ** 0.8

    def play(self, audio: np.ndarray, sr: int, stop_event: threading.Event) -> bool:
        import sounddevice as sd
        env = self.envelope(audio, sr) if self.on_level else None
        with self._lock:
            sd.play(audio, sr, device=self.device)
            start = time.time()
            end = start + len(audio) / sr + 1.0
            time.sleep(0.05)
            while time.time() < end:
                if stop_event.is_set():
                    sd.stop()
                    return False
                try:
                    if not sd.get_stream().active:
                        break
                except Exception:
                    pass
                if env is not None:
                    i = int((time.time() - start) / 0.03)
                    if i < len(env):
                        try:
                            self.on_level(float(env[i]))
                        except Exception:
                            pass
                time.sleep(0.03)
            return True

    def stop(self):
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    def chime(self, kind: str = "wake"):
        """Little 'I'm listening' / 'got it' sound, generated on the fly."""
        try:
            import sounddevice as sd
            sr = 24000
            notes = {"wake": (880, 1320), "done": (1320, 880), "error": (440, 330)}.get(kind, (880, 1320))
            parts = []
            for f in notes:
                t = np.arange(int(sr * 0.08)) / sr
                tone = 0.18 * np.sin(2 * np.pi * f * t)
                fade = np.minimum(1, np.minimum(t, t[::-1]) * 60)
                parts.append((tone * fade).astype(np.float32))
            sd.play(np.concatenate(parts), sr, device=self.device)
        except Exception:
            pass
