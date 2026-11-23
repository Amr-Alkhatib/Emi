"""Automatic model routing: Flash, Hydrogen, Neon, and Claude helper (for heavy coding/engineering)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("emi.router")

TIER_LABELS = {
    "flash": "Flash",
    "hydrogen": "Hydrogen",
    "neon": "Neon",
    "claude": "Claude helper",
}

SLASH_OVERRIDE = re.compile(r"^/(flash|hydrogen|neon|claude)\b\s*", re.I)
VOICE_OVERRIDE = re.compile(
    r"^(?:hey\s+\w+[,\s]+)?(?:use|switch\s+to|with|ask)\s+(flash|hydrogen|neon|claude)\b(?:\s+(?:to|for))?[\s,:,-]*",
    re.I,
)

# Heavy coding & software engineering jobs -> Claude helper (or Neon if Claude helper is off)
CLAUDE_PATTERNS = re.compile(
    r"\b("
    r"ask\s+claude|have\s+claude|hand\s+(?:this|it)\s+to\s+claude|"
    r"refactor\s+(?:the\s+|my\s+|this\s+)?(?:project|repo|repository|codebase|app|module|files?|code)|"
    r"fix\s+(?:the\s+)?(?:bug|bugs|tests?|build|errors?|issues?|code)\s+in\b|"
    r"debug\s+(?:the\s+|my\s+|this\s+)?(?:project|repo|codebase|app|script|server|backend|frontend)|"
    r"implement\s+(?:a|an|the)?\s*(?:feature|api|endpoint|service|system|module|component|pipeline|auth|database)|"
    r"build\s+(?:me\s+)?(?:a|an)?\s*(?:app|web\s*app|website|script|cli|tool|service|bot|plugin|extension|backend|frontend|program|pipeline)|"
    r"write\s+(?:unit\s+|integration\s+)?tests?\s+(?:for|in)\b|"
    r"code\s+review|pull\s+request|git\s+(?:rebase|bisect|merge\s+conflict)|"
    r"docker(?:file|[\s-]compose)?|ci/cd|github\s+actions|terraform|kubernetes|migration\s+script|"
    r"edit\s+(?:the\s+|my\s+)?(?:code|script|repo|project|source\s+files?)|"
    r"engineer(?:ing)?\s+(?:a|an|the|this)"
    r")\b",
    re.I,
)

# Deep reasoning, math, analysis, architecture, coding Q&A in chat -> Neon
NEON_PATTERNS = re.compile(
    r"(```|traceback|stack\s*trace|exception|syntaxerror|typeerror|valueerror|nullreference|segfault|"
    r"\b("
    r"root\s*cause|architect(?:ure)?|system\s*design|algorithm|big[\s-]*o|complexity|"
    r"prove|proof|theorem|calculus|integral|derivative|differential|matrix|eigen|"
    r"optimi[sz]e|benchmark|concurrency|deadlock|race\s+condition|memory\s+leak|"
    r"regex|regular\s+expression|sql\s+query|security\s+audit|vulnerabilit|"
    r"analy[sz]e\s+(?:this|the|my)\s+(?:spreadsheet|csv|excel|dataset|data|logs?)|"
    r"step\s+by\s+step|in\s+depth|deep\s+dive|trade[\s-]*offs?|pros?\s+and\s+cons?|"
    r"why\s+(?:does|is|did)\s+(?:this|my)\s+(?:code|script|app|function|query)\b"
    r")\b)",
    re.I,
)

# Organizing files & folders, everyday synthesis, writing, multi-step PC work -> Hydrogen
HYDROGEN_PATTERNS = re.compile(
    r"\b("
    r"organis[ez]|sort\s+(?:all\s+|my\s+|the\s+)?(?:files?|folder|downloads|desktop|documents)|"
    r"clean\s*up\s+(?:my\s+|the\s+)?(?:folder|downloads|desktop|documents|files?)|"
    r"rename\s+(?:all|multiple|these|those|the|my)\s+files?|"
    r"move\s+(?:all|the|my)\s+.*?\s+(?:into|to)\s+|"
    r"write|draft|compose|summari[sz]e|summary|rewrite|rephrase|polish|proofread|"
    r"explain|how\s+do\s+i|how\s+does|brainstorm|outline|plan\s+(?:a|my|the)|"
    r"email|letter|essay|cover\s+letter|blog|post|message|reply\s+to|report|"
    r"compare|difference\s+between|recommend|suggest|best\s+way\s+to|"
    r"search\s+(?:for|the\s+web)|look\s+up|latest\s+news|what\s+happened"
    r")\b",
    re.I,
)

# Fast single-step commands & quick lookups -> Flash
FLASH_PATTERNS = re.compile(
    r"^(?:open|launch|start|close|quit|play|pause|resume|next|previous|skip|stop|mute|unmute|"
    r"volume|brightness|set\s+(?:a\s+)?(?:timer|reminder|alarm)|remind\s+me|"
    r"what(?:'s|\s+is)\s+the\s+(?:time|date|weather|temperature)|"
    r"convert\s+\d|how\s+(?:much|many)\s+\w+\s+in\s+|"
    r"translate|define|spell|remember\s+that|save\s+(?:a\s+)?note|copy\b|clipboard\b|"
    r"turn\s+(?:on|off)|toggle|lock|sleep|shutdown|restart)\b",
    re.I,
)


@dataclass
class RouteDecision:
    tier: str                                         # flash | hydrogen | neon | claude
    model: str
    effort: str | None
    reason: str
    claude_handoff: bool = False
    cleaned_text: str | None = None
    fallbacks: list[tuple[str, str | None]] = field(default_factory=list)

    @property
    def label(self) -> str:
        return TIER_LABELS.get(self.tier, self.tier.capitalize())


def strip_override(text: str) -> tuple[str | None, str]:
    raw = (text or "").strip()
    m = SLASH_OVERRIDE.match(raw)
    if m:
        return m.group(1).lower(), raw[m.end():].strip() or raw
    m = VOICE_OVERRIDE.match(raw)
    if m:
        return m.group(1).lower(), raw
    return None, raw


def _build_decision(brain, tier: str, reason: str, claude_enabled: bool,
                    cleaned_text: str | None = None) -> RouteDecision:
    cfg = brain.cfg
    default_efforts = {
        "flash": str(cfg.get("brain.auto_efforts.flash", "minimal") or "minimal"),
        "hydrogen": str(cfg.get("brain.auto_efforts.hydrogen", "low") or "low"),
        "neon": str(cfg.get("brain.auto_efforts.neon", cfg.get("brain.effort", "medium")) or "medium"),
    }

    if tier == "claude" and claude_enabled:
        # Use Hydrogen (not minimal Flash) so Emi writes a sharp, accurate engineering brief for ask_claude
        primary_model = brain.auto_model("hydrogen")
        primary_effort = default_efforts["hydrogen"]
        fb_tiers = ["neon", "flash"]
        handoff = True
    else:
        if tier == "claude":
            tier = "neon"
            reason += " (Claude helper off -> Neon)"
        primary_model = brain.auto_model(tier)
        primary_effort = default_efforts.get(tier, "low")
        fb_tiers = {
            "neon": ["hydrogen", "flash"],
            "hydrogen": ["neon", "flash"],
            "flash": ["hydrogen"],
        }.get(tier, ["hydrogen", "flash"])
        handoff = False

    fallbacks: list[tuple[str, str | None]] = []
    seen = {primary_model}
    for ft in fb_tiers:
        fm = brain.auto_model(ft)
        if fm and fm not in seen:
            seen.add(fm)
            fallbacks.append((fm, default_efforts.get(ft, "low")))
    if brain.model and brain.model not in seen:
        fallbacks.append((brain.model, None))

    return RouteDecision(
        tier=tier,
        model=primary_model,
        effort=primary_effort,
        reason=reason,
        claude_handoff=handoff,
        cleaned_text=cleaned_text,
        fallbacks=fallbacks,
    )


def choose_route(brain, text: str, mode: str = "ask", claude_enabled: bool = False,
                 history_len: int = 0) -> RouteDecision | None:
    override, cleaned = strip_override(text)

    if override:
        if brain.provider == "gemini" or override == "claude":
            return _build_decision(brain, override, "manual override", claude_enabled,
                                   cleaned_text=cleaned if cleaned != text else None)
        return None

    if not getattr(brain, "auto_mode", False):
        return None

    t = (text or "").strip()
    word_count = len(t.split())

    # 1) Heavy coding & engineering -> Claude helper (or Neon if Claude helper is off)
    if CLAUDE_PATTERNS.search(t):
        return _build_decision(brain, "claude" if claude_enabled else "neon", "heavy coding/engineering", claude_enabled)

    # 2) Deep reasoning, math, analysis, code debugging Q&A -> Neon
    if NEON_PATTERNS.search(t) or len(t) > 550:
        return _build_decision(brain, "neon", "complex reasoning / math / analysis", claude_enabled)

    # 3) Screen / crop requests
    if mode in ("screen", "crop"):
        if re.search(r"\b(error|bug|exception|crash|fix|code|solve|equation|formula)\b", t, re.I):
            return _build_decision(brain, "neon", "screen debugging/math", claude_enabled)
        if word_count <= 10 and re.search(r"\b(translate|copy|read|what is this)\b", t, re.I):
            return _build_decision(brain, "flash", "quick screen lookup", claude_enabled)
        return _build_decision(brain, "hydrogen", "screen explanation", claude_enabled)

    # 4) Organizing files, writing, summarizing, planning, research -> Hydrogen
    if HYDROGEN_PATTERNS.search(t):
        return _build_decision(brain, "hydrogen", "organizing / writing / everyday task", claude_enabled)

    # 5) Fast single-step commands & short simple lookups -> Flash
    if word_count <= 14 and FLASH_PATTERNS.search(t):
        return _build_decision(brain, "flash", "quick command/lookup", claude_enabled)
    if word_count <= 9 and "?" not in t[40:]:
        return _build_decision(brain, "flash", "short everyday query", claude_enabled)

    # 6) Ambiguous prompt -> optional fast AI tie-breaker
    if brain.cfg.get("brain.auto_classifier", True):
        picked = brain.classify(t, claude_enabled)
        if picked in ("flash", "hydrogen", "neon", "claude"):
            return _build_decision(brain, picked, "AI classifier", claude_enabled)

    return _build_decision(brain, "hydrogen", "balanced default", claude_enabled)
