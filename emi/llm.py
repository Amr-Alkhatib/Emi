"""The 'brain': Gemini by default; Claude API (native, with prompt caching) or a local Ollama model also work.

The agent talks to this through four calls:
    messages = brain.start(history, user_text)
    step = brain.step(messages, system_static, system_dynamic, tools)   # → text + tool calls
    brain.add_results(messages, [(call, result_text), ...])
    brain.see(screenshot_b64, question)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

from .config import PROVIDERS, Config, ConfigError

log = logging.getLogger("emi.llm")


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    error: str | None = None       # set if the model sent arguments we couldn't parse


@dataclass
class Step:
    text: str
    calls: list[ToolCall] = field(default_factory=list)


def _parse_args(raw) -> tuple[dict, str | None]:
    if isinstance(raw, dict):
        return raw, None
    try:
        val = json.loads(raw or "{}")
        return (val if isinstance(val, dict) else {}), None
    except json.JSONDecodeError:
        return {}, "Error: your tool arguments were not valid JSON. Try again."


# ── Claude (native Messages API) ─────────────────────────────────────────────
class ClaudeBackend:
    def __init__(self, api_key: str, model: str, vision_model: str, effort: str | None, max_tokens: int):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=120)
        self.model, self.vision_model = model, vision_model
        self.effort, self.max_tokens = effort, max_tokens

    def _extra(self) -> dict:
        # effort controls how much Claude thinks; "low" keeps voice replies snappy
        return {"extra_body": {"output_config": {"effort": self.effort}}} if self.effort else {}

    def start(self, history: list[dict], user_text: str) -> list[dict]:
        return [dict(m) for m in history] + [{"role": "user", "content": user_text}]

    def step(self, messages, system_static, system_dynamic, tools) -> Step:
        tool_defs = [{"name": t["function"]["name"], "description": t["function"]["description"],
                      "input_schema": t["function"]["parameters"]} for t in tools]
        if tool_defs:  # cache the (big, unchanging) tool list + static instructions → cheaper & faster
            tool_defs[-1] = {**tool_defs[-1], "cache_control": {"type": "ephemeral"}}
        system = [{"type": "text", "text": system_static, "cache_control": {"type": "ephemeral"}}]
        if system_dynamic:
            system.append({"type": "text", "text": system_dynamic})
        kwargs = {"model": self.model, "max_tokens": self.max_tokens, "system": system, "messages": messages}
        if tool_defs:
            kwargs["tools"] = tool_defs
        resp = self.client.messages.create(**kwargs, **self._extra())

        content, texts, calls = [], [], []
        for b in resp.content:
            kind = getattr(b, "type", "")
            if kind == "text":
                if b.text:
                    content.append({"type": "text", "text": b.text})
                    texts.append(b.text)
            elif kind == "tool_use":
                content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                args, err = _parse_args(b.input)
                calls.append(ToolCall(b.id, b.name, args, err))
            elif kind == "thinking":   # must be passed back unchanged during tool use
                content.append({"type": "thinking", "thinking": b.thinking, "signature": b.signature})
            elif kind == "redacted_thinking":
                content.append({"type": "redacted_thinking", "data": b.data})
            else:
                try:
                    content.append(b.model_dump(exclude_none=True))
                except Exception:
                    pass
        if content:
            messages.append({"role": "assistant", "content": content})
        text = "\n".join(texts).strip()
        if resp.stop_reason == "refusal" and not text:
            text = "I can't help with that one."
        return Step(text, calls)

    def add_results(self, messages, results):
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call.id, "content": result,
             **({"is_error": True} if result.startswith("Error") else {})}
            for call, result in results]})

    def see(self, image_b64: str, question: str, raw: bool = False, model: str | None = None) -> str:
        resp = self.client.messages.create(
            model=model or self.vision_model, max_tokens=1500,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                {"type": "text", "text": question if raw else VISION_PROMPT + question}]}],
            **self._extra())
        return "\n".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


# ── Gemini, local Ollama, or any other OpenAI-compatible API ────────────────
class OpenAIBackend:
    def __init__(self, api_key: str, base_url: str | None, model: str, vision_model: str, temperature,
                 reasoning_effort: str | None = None):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=120, max_retries=2)
        self.model, self.vision_model, self.temperature = model, vision_model, temperature
        self.reasoning_effort = reasoning_effort
        self._bad_efforts: dict[str, set] = {}

    def start(self, history, user_text):
        return [dict(m) for m in history] + [{"role": "user", "content": user_text}]

    def _create(self, kwargs: dict, effort: str | None):
        """Call the API; if this model doesn't accept that thinking level, retry with the next one up."""
        last = None
        for level in [effort] + [lv for lv in ("low", None) if lv != effort]:
            if level in self._bad_efforts.get(kwargs["model"], ()):
                continue
            if level:
                kwargs["reasoning_effort"] = level
            else:
                kwargs.pop("reasoning_effort", None)
            try:
                return self.client.chat.completions.create(**kwargs)
            except Exception as e:
                if type(e).__name__ != "BadRequestError" or not level:
                    raise
                last = e      # most likely this model doesn't take that thinking level
                self._bad_efforts.setdefault(kwargs["model"], set()).add(level)
                log.info("%s refused reasoning_effort=%s (%s); trying the next level", kwargs["model"], level,
                         str(e)[:160])
        raise last or RuntimeError("The model refused every thinking level.")

    def step(self, messages, system_static, system_dynamic, tools, model: str | None = None,
             effort: str | None = None) -> Step:
        system = system_static + ("\n\n" + system_dynamic if system_dynamic else "")
        kwargs = {"model": model or self.model, "messages": [{"role": "system", "content": system}] + messages}
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        if self.temperature is not None:
            kwargs["temperature"] = float(self.temperature)
        resp = self._create(kwargs, effort or self.reasoning_effort)
        if not resp.choices:
            raise RuntimeError("The model returned an empty response.")
        msg = resp.choices[0].message
        # keep every field the provider sent (some need extra fields passed back unchanged)
        raw = msg.model_dump(exclude_none=True)
        keep = {k: v for k, v in raw.items() if k in ("role", "content", "tool_calls", "extra_content")}
        keep["role"] = "assistant"
        messages.append(keep)
        calls = []
        for tc in msg.tool_calls or []:
            args, err = _parse_args(tc.function.arguments)
            calls.append(ToolCall(tc.id, tc.function.name, args, err))
        return Step((msg.content or "").strip(), calls)

    def add_results(self, messages, results):
        for call, result in results:
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    def see(self, image_b64: str, question: str, raw: bool = False, model: str | None = None,
            effort: str | None = None) -> str:
        kwargs = {"model": model or self.vision_model, "messages": [{"role": "user", "content": [
            {"type": "text", "text": question if raw else VISION_PROMPT + question},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]}]}
        resp = self._create(kwargs, effort or self.reasoning_effort)
        return (resp.choices[0].message.content or "").strip()


VISION_PROMPT = ("This is a screenshot of the user's Windows screen. Answer their question about it accurately and "
                 "concisely. Quote exact on-screen text when it matters. If something isn't visible, say so.\n\n"
                 "Question: ")


class Brain:
    def __init__(self, cfg: Config, state=None):
        self.cfg, self.state = cfg, state
        self.provider = str(cfg.get("brain.provider", "gemini")).lower()
        if self.provider == "ollama":
            self.provider = "local"
        preset = PROVIDERS.get(self.provider, {})
        self.error: str | None = None
        self.backend = None
        self.model = None
        self._fast_model: str | None = None
        self._auto_models: dict[str, str] = {}
        self._unavailable: set[str] = set()
        self.active_route = None
        if not preset and self.provider != "custom":
            self.error = f"Unknown brain.provider '{self.provider}' in config.yaml."
            return
        self.preset = preset
        key_env = cfg.get("brain.api_key_env") or preset.get("key_env")
        picked = (getattr(state, "models", None) or {}).get(self.provider)   # chosen in the Control Center
        model_cfg = cfg.get(f"brain.models.{self.provider}") or cfg.get("brain.model")
        self.model = picked or model_cfg or preset.get("model")
        self.fixed_vision_model = cfg.get("brain.vision_model") or ""
        vision_model = self.fixed_vision_model or self.model
        api_key = os.environ.get(key_env, "") if key_env else "local"
        self._api_key = api_key
        if key_env and not api_key:
            self.error = (f"I don't have an API key yet. Create one at {preset.get('key_url', 'your provider')}, "
                          f"put it in the .env file as {key_env}=..., then restart me.")
            return
        if not self.model:
            self.error = "No model is set. Put a model name in config.yaml under brain.model."
            return
        try:
            effort = cfg.get("brain.effort", "low")
            if self.provider == "claude":
                self.backend = ClaudeBackend(api_key, self.model, vision_model, effort,
                                             int(cfg.get("brain.max_tokens", 4096)))
            else:
                base_url = cfg.get("brain.base_url") or preset.get("base_url")
                self.backend = OpenAIBackend(api_key, base_url, self.model, vision_model,
                                             cfg.get("brain.temperature"),
                                             effort if self.provider == "gemini" else None)
        except ImportError as e:
            self.error = f"A package is missing ({e}). Run setup.bat again."

    def _check(self):
        if self.error:
            raise ConfigError(self.error)

    # ── speed & auto routing ──
    # Auto (default): picks Flash, Hydrogen, Neon, or hands heavy coding/engineering to Claude helper per request.
    # Instant: every request goes to a fast "flash" model with minimal thinking.
    # Smart: the model you picked in the Control Center, at the thinking level in config.yaml.
    @property
    def speed_mode(self) -> str:
        return getattr(self.state, "speed", "auto")

    @property
    def auto_mode(self) -> bool:
        return self.provider == "gemini" and self.speed_mode == "auto"

    @property
    def instant(self) -> bool:
        return self.provider == "gemini" and self.speed_mode == "instant"

    @property
    def fast_model(self) -> str:
        return self._fast_model or self._auto_models.get("flash") or self.preset.get("model") or self.model

    def auto_model(self, tier: str) -> str:
        """Resolved model ID for an Auto tier: flash | hydrogen | neon."""
        if tier in self._auto_models and self._auto_models[tier] not in self._unavailable:
            return self._auto_models[tier]
        defaults = {
            "flash": self.fast_model,
            "hydrogen": "gemini-4-hydrogen",
            "neon": "gemini-4-neon",
        }
        cand = defaults.get(tier, self.model)
        if cand in self._unavailable:
            return self.fast_model if self.fast_model not in self._unavailable else self.model
        return cand

    def auto_summary(self) -> dict[str, str]:
        return {t: self.auto_model(t) for t in ("flash", "hydrogen", "neon")}

    def find_fast_model(self) -> None:
        """Resolve Flash, Hydrogen, and Neon models available on this account (runs once in the background)."""
        import re
        models = self.list_models() if self.provider == "gemini" else []

        def pick(cfg_key: str, predicate, fallback: str) -> str:
            wanted = str(self.cfg.get(cfg_key, "auto") or "auto").strip()
            if wanted.lower() != "auto":
                return wanted
            matches = [m for m in models if predicate(m)]
            return sorted(matches, key=_model_sort_key)[0] if matches else fallback

        wanted_fast = str(self.cfg.get("brain.auto_models.flash", "") or
                          self.cfg.get("brain.fast_model", "auto") or "auto").strip()
        if wanted_fast.lower() != "auto":
            flash_m = wanted_fast
        else:
            flash_exact = [m for m in models if re.fullmatch(r"gemini-[\d.]+-flash", m)]
            flash_lite = [m for m in models if "flash-lite" in m]
            flash_any = flash_exact or flash_lite or [m for m in models if "flash" in m]
            flash_m = sorted(flash_any, key=_model_sort_key)[0] if flash_any else (self.preset.get("model") or self.model)

        hydrogen_m = pick("brain.auto_models.hydrogen", lambda m: "hydrogen" in m, flash_m)
        neon_m = pick("brain.auto_models.neon", lambda m: "neon" in m,
                      pick("brain.auto_models.neon", lambda m: "-pro" in m, hydrogen_m))

        self._fast_model = flash_m
        self._auto_models = {"flash": flash_m, "hydrogen": hydrogen_m, "neon": neon_m}
        log.info("auto models resolved: flash=%s, hydrogen=%s, neon=%s", flash_m, hydrogen_m, neon_m)

    def classify(self, text: str, claude_enabled: bool = False) -> str | None:
        """Tiny, fast tie-breaker call on Flash for ambiguous prompts. Returns tier or None."""
        if self.error or not isinstance(self.backend, OpenAIBackend):
            return None
        tiers = "flash, hydrogen, neon, or claude" if claude_enabled else "flash, hydrogen, or neon"
        guide = (
            "Classify this desktop assistant request into ONE word:\n"
            "- flash: simple one-step PC action, quick factual question, short lookup\n"
            "- hydrogen: organizing/sorting/renaming files, everyday writing, summarizing, explaining, planning, web search\n"
            "- neon: complex reasoning, math, data analysis, architecture, debugging/code questions in chat\n"
        )
        if claude_enabled:
            guide += "- claude: heavy coding and software engineering (building/fixing/refactoring codebases, apps, scripts, tests)\n"
        guide += f"Reply with ONLY one word ({tiers})."
        try:
            model = self.auto_model("flash")
            kwargs = {
                "model": model,
                "max_tokens": 12,
                "messages": [
                    {"role": "system", "content": guide},
                    {"role": "user", "content": text[:600]},
                ],
            }
            resp = self.backend.client.chat.completions.create(timeout=4.0, **kwargs)
            ans = (resp.choices[0].message.content or "").strip().lower()
            for k in ("claude", "neon", "hydrogen", "flash"):
                if k in ans:
                    return k
        except Exception as e:
            log.debug("classifier skipped (%s)", e)
        return None

    def warm(self) -> None:
        """Open the connection to the AI while you're still talking (saves the handshake on the real request)."""
        import threading
        import time
        if self.error or not self.backend or time.monotonic() - getattr(self, "_warm_t", 0) < 30:
            return
        self._warm_t = time.monotonic()

        def ping():
            try:
                client = getattr(self.backend, "client", None)
                if client is not None:
                    client.models.list()
            except Exception:
                pass
        threading.Thread(target=ping, daemon=True, name="warm").start()

    def _route(self) -> tuple[str | None, str | None]:
        """(model, thinking level) for the next request."""
        if self.active_route is not None:
            return self.active_route.model, _safe_effort(self.active_route.model, self.active_route.effort)
        if self.instant:
            return self.fast_model, _safe_effort(self.fast_model, "minimal")
        return None, None

    @property
    def label(self) -> str:
        return self.preset.get("label", self.provider.capitalize()) if getattr(self, "preset", None) else "AI"

    def set_model(self, model: str) -> None:
        """Switch model while running (from the Control Center)."""
        model = str(model).strip()
        if not model:
            return
        self.model = model
        if self.backend:
            self.backend.model = model
            if not self.fixed_vision_model:
                self.backend.vision_model = model
        if self.state is not None:
            self.state.models[self.provider] = model
            self.state.set("models", self.state.models)

    def list_models(self) -> list[str]:
        """Models this account can use, newest first. Falls back to a built-in list if offline."""
        found: list[str] = []
        try:
            if self.error:
                raise RuntimeError(self.error)
            if self.provider == "gemini":
                import httpx
                r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models",
                              params={"pageSize": 1000}, headers={"x-goog-api-key": self._api_key}, timeout=10)
                r.raise_for_status()
                skip = ("embedding", "image", "tts", "audio", "live", "veo", "imagen", "aqa", "robotics")
                for m in r.json().get("models", []):
                    mid = m.get("name", "").removeprefix("models/")
                    if (mid.startswith("gemini") and "generateContent" in m.get("supportedGenerationMethods", [])
                            and not any(x in mid for x in skip)):
                        found.append(mid)
            elif self.provider == "claude":
                found = [m.id for m in self.backend.client.models.list(limit=100)]
            else:
                found = [m.id for m in self.backend.client.models.list()]
        except Exception as e:
            log.info("couldn't list models (%s); using the built-in list", e)
        if not found:
            found = list(self.preset.get("fallback_models", []))
        found = sorted(set(found), key=_model_sort_key)
        if self.model and self.model not in found:
            found.insert(0, self.model)
        return found

    def start(self, history, user_text):
        self._check()
        return self.backend.start(history, user_text)

    def step(self, messages, system_static, system_dynamic, tools,
             model_override: str | None = None, effort_override: str | None = None,
             fallbacks: list[tuple[str, str | None]] | None = None) -> Step:
        self._check()
        model, effort = (model_override, _safe_effort(model_override, effort_override)) if model_override else self._route()
        if model and isinstance(self.backend, OpenAIBackend):
            attempts = [(model, effort)] + [(m, _safe_effort(m, ef)) for m, ef in (fallbacks or [])]
            last_err = None
            for idx, (m, ef) in enumerate(attempts):
                if m in self._unavailable and idx < len(attempts) - 1:
                    continue
                try:
                    return self.backend.step(messages, system_static, system_dynamic, tools, model=m, effort=ef)
                except Exception as e:
                    name = type(e).__name__
                    msg = str(e).lower()
                    recoverable = (
                        name in ("NotFoundError", "RateLimitError", "InternalServerError", "OverloadedError")
                        or "resource_exhausted" in msg or "overloaded" in msg or "not found" in msg
                    )
                    if name == "NotFoundError":
                        self._unavailable.add(m)
                    if not recoverable or idx == len(attempts) - 1:
                        raise
                    last_err = e
                    log.warning("model %s failed (%s); falling back to %s", m, name, attempts[idx + 1][0])
            raise last_err
        return self.backend.step(messages, system_static, system_dynamic, tools)

    def add_results(self, messages, results):
        self.backend.add_results(messages, results)

    def see(self, image_b64: str, question: str, raw: bool = False, model: str | None = None) -> str:
        """Ask about a screenshot. raw=True sends `question` as the whole prompt (for JSON-style answers)."""
        self._check()
        routed_model, effort = self._route()
        if isinstance(self.backend, OpenAIBackend):
            if not model and not self.fixed_vision_model:
                model = routed_model
            return self.backend.see(image_b64, question, raw=raw, model=model, effort=effort)
        return self.backend.see(image_b64, question, raw=raw, model=model)


def _safe_effort(model: str | None, effort: str | None) -> str | None:
    """Gemini 4 and Pro models don't support 'minimal' thinking; promote safely to 'low'."""
    if not model or not effort:
        return effort
    if effort == "minimal" and any(x in model for x in ("gemini-4-", "hydrogen", "neon", "carbon", "argon", "-pro")):
        return "low"
    return effort


def _model_sort_key(mid: str):
    """Newest versions first; within a version: hydrogen/flash, flash-lite, neon/pro, carbon/argon, others."""
    import re
    nums = [int(n) for n in re.findall(r"\d+", mid)[:2]] + [0, 0]
    if "hydrogen" in mid or mid.endswith("flash"):
        tier = 0
    elif "flash-lite" in mid:
        tier = 1
    elif "neon" in mid or "pro" in mid:
        tier = 2
    elif "carbon" in mid or "argon" in mid:
        tier = 3
    else:
        tier = 4
    return (-nums[0], -nums[1], "preview" in mid or "exp" in mid, tier, mid)


def friendly_error(e: Exception) -> str:
    """Turn API exceptions into something Emi can say out loud."""
    name = type(e).__name__
    msg = str(getattr(e, "message", "") or e)
    if "credit balance" in msg.lower():
        return "My Claude account is out of credit. Top it up in the Claude Console, then try again."
    if "api key not valid" in msg.lower() or "api_key_invalid" in msg.lower():
        return "My API key was rejected. Check the key in the .env file."
    if any(w in msg.lower() for w in ("quota", "billing", "credits are depleted", "resource_exhausted")):
        return ("I've hit my usage limit or the account has a billing problem. Wait a bit, or check billing "
                "in Google AI Studio.")
    if name in ("AuthenticationError", "PermissionDeniedError"):
        return "My API key was rejected. Check the key in the .env file."
    if name == "RateLimitError":
        return "I'm being rate-limited right now. Give it a few seconds and ask again."
    if name in ("APIConnectionError", "APITimeoutError", "ConnectError"):
        return "I can't reach my brain. Are you online? (For the local brain: is Ollama running?)"
    if name in ("InternalServerError", "OverloadedError") or "overloaded" in msg.lower():
        return "The AI service is overloaded at the moment. Try again in a minute."
    if name == "NotFoundError":
        return "That model isn't available on your account. Pick another one in my Control Center, on the Brain page."
    log.exception("brain error")
    return f"Something went wrong talking to the AI: {msg[:200]}"
