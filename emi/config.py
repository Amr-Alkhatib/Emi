"""Loads config.yaml + .env and holds the AI provider presets."""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

import sys

# Where config.yaml, .env, data/ and models/ live: next to main.py, or next to Emi.exe in the packaged app
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"

# Brains Emi can use:
#   gemini — Gemini API (cloud). Needs GEMINI_API_KEY from aistudio.google.com/apikey.
#   claude — Claude API (cloud). Needs ANTHROPIC_API_KEY (API credit is billed separately from a Claude plan).
#   local  — a model on your own laptop through Ollama. Nothing leaves the PC; slower and less capable.
#   custom — any other OpenAI-compatible API (set base_url, api_key_env and model in config.yaml).
# Big tasks can also go to Claude Code on your Claude plan, with no API key — see emi/tools/claude_code.py.
PROVIDERS: dict[str, dict] = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "model": "gemini-3.8-flash",
        "label": "Gemini",
        "key_url": "https://aistudio.google.com/apikey",
        # shown in the model picker if the live list can't be fetched
        "fallback_models": ["gemini-4-hydrogen", "gemini-4-neon", "gemini-3.8-flash",
                            "gemini-3.1-flash-lite", "gemini-3.1-pro-preview"],
    },
    "claude": {   # native Claude API (see emi/llm.py ClaudeBackend)
        "key_env": "ANTHROPIC_API_KEY",
        "model": "claude-sonnet-5-5",
        "label": "Claude",
        "key_url": "https://platform.claude.com/settings/keys",
        "fallback_models": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
    },
    "local": {    # Ollama on this PC: https://ollama.com/download
        "base_url": "http://localhost:11434/v1",
        "key_env": None,
        "model": "qwen3:8b",
        "label": "Local",
        "key_url": "https://ollama.com/download",
        "fallback_models": ["qwen3:8b", "qwen3:4b"],
    },
}
PROVIDERS["ollama"] = PROVIDERS["local"]

# Cloud speech-to-text (only used when hearing.stt is not "local")
STT_PROVIDERS = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",
             "model": "whisper-large-v3-turbo"},
    "openai": {"base_url": None, "key_env": "OPENAI_API_KEY", "model": "whisper-1"},
}


class ConfigError(Exception):
    """A setup problem the user can fix (missing key, bad value...)."""


def load_env(path: Path) -> None:
    """Tiny .env reader so we don't need python-dotenv."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value


class Config:
    def __init__(self, data: dict | None):
        self.data = data or {}

    def get(self, dotted: str, default=None):
        cur = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return default if cur is None else cur

    @property
    def name(self) -> str:
        return str(self.get("assistant.name", "Emi"))


def load_config(path: Path | None = None) -> Config:
    load_env(ROOT / ".env")
    path = path or ROOT / "config.yaml"
    if not path.exists():
        raise ConfigError(f"Can't find {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    DATA_DIR.mkdir(exist_ok=True)
    MODELS_DIR.mkdir(exist_ok=True)
    return Config(data)


class State:
    """Settings that can change while Emi runs (by voice or the Control Center). Saved in data/state.json."""

    SAVED = ("personality", "speak_replies", "full_access", "models", "claude_helper", "proactive",
             "proactive_every", "gaming_auto", "voice", "custom_voices", "reply_mode", "idle_look", "welcomed", "speed")
    REPLY_MODES = ("auto", "voice", "text", "both")

    def __init__(self, cfg: Config, path: Path = DATA_DIR / "state.json"):
        self.path = path
        saved = {}
        if path.exists():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                saved = {}
        self.personality: str = saved.get("personality") or cfg.get("assistant.personality", "hype")
        self.speak_replies: bool = saved.get("speak_replies", cfg.get("voice.speak_replies", True))
        # full access = no Allow/Deny questions. Only the user can change this (menu or config), never the AI.
        self.full_access: bool = saved.get("full_access", str(cfg.get("safety.mode", "ask")).lower() == "full")
        self.models: dict = saved.get("models") or {}          # model picked in the menu, per provider
        self.claude_helper: bool = saved.get("claude_helper", bool(cfg.get("claude_code.enabled", True)))
        self.proactive: bool = saved.get("proactive", bool(cfg.get("proactive.enabled", False)))
        self.proactive_every: int = int(saved.get("proactive_every") or cfg.get("proactive.every_seconds", 120))
        self.gaming_auto: bool = saved.get("gaming_auto", bool(cfg.get("gaming.auto", True)))
        self.voice: dict = saved.get("voice") or {}            # {"engine": ..., "voice": ...} picked in the menu
        self.custom_voices: list = saved.get("custom_voices") or []   # voices you designed: [{"id", "name"}]
        # how answers come back: auto = spoken, plus a text card when it's long or has code/lists;
        # voice = spoken only; text = written only; both = always spoken and written
        mode = saved.get("reply_mode") or str(cfg.get("voice.reply_mode", "")).lower()
        if mode not in self.REPLY_MODES:
            mode = "auto" if self.speak_replies else "text"
        self.reply_mode: str = mode
        # what Emi looks like when she's idle: notch = a slim tab at the top of the screen that drops down when your
        # mouse reaches it (click it for the quick menu) | hide = nothing until "Hey Emi"
        idle = saved.get("idle_look") or str(cfg.get("ui.idle", "notch")).lower()
        self.idle_look: str = "notch" if idle in ("notch", "pill") else "hide"
        self.paused: bool = False     # wake word paused from the quick menu (not saved)
        # auto = automatically switches Flash / Hydrogen / Neon (+ Claude helper) per request |
        # instant = a fast model with minimal thinking for everything (about a second per step) |
        # smart = the model picked in the Control Center
        sp = saved.get("speed") or str(cfg.get("brain.speed", "auto")).lower()
        self.speed: str = sp if sp in ("auto", "instant", "smart") else "auto"
        self.welcomed: bool = bool(saved.get("welcomed", False))
        self.incognito: bool = False  # always off when Emi starts
        self.gaming: bool = False     # set by the gaming watcher
        self._watchers = []

    def watch(self, fn):
        self._watchers.append(fn)

    def set(self, key: str, value) -> None:
        setattr(self, key, value)
        if key in self.SAVED:
            try:
                self.path.write_text(json.dumps({k: getattr(self, k) for k in self.SAVED}, indent=2),
                                     encoding="utf-8")
            except Exception:
                pass
        for fn in self._watchers:
            try:
                fn(key, value)
            except Exception:
                pass
