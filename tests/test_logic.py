from datetime import datetime
import pytest

from emi import agent, quick, router, stt
from emi.config import Config
from emi.tools import ToolError
from emi.tools.productivity import parse_when


class DummyBrain:
    """Minimal offline stub for router tests (no API calls)."""
    provider = "gemini"
    auto_mode = True
    model = "gemini-4-hydrogen"

    def __init__(self):
        self.cfg = Config({"brain": {"auto_classifier": False}})

    def auto_model(self, tier: str) -> str:
        return {"flash": "gemini-3.8-flash", "hydrogen": "gemini-4-hydrogen", "neon": "gemini-4-neon"}[tier]


# ── Instant commands (emi/quick.py) ───────────────────────────────────────────
def test_quick_open_app():
    res = quick.match("Hey Emi, open Spotify please")
    assert res == ("tool", "open_app", {"name": "spotify"}, "Opening Spotify.")


def test_quick_volume_clamps_to_100():
    res = quick.match("set volume to 150%")
    assert res[0] == "tool" and res[1] == "media_control"
    assert res[2] == {"action": "set_volume", "level": 100}


def test_quick_time_skips_llm():
    res = quick.match("what time is it?")
    assert res is not None and res[0] == "say" and res[1].startswith("It's ")


def test_quick_skips_multi_step_requests():
    assert quick.match("open Word and write an essay") is None
    assert quick.match("explain how hash tables work") is None


# ── Tiered model router (emi/router.py) ───────────────────────────────────────
def test_router_claude_handoff_when_enabled():
    d = router.choose_route(DummyBrain(), "refactor my project codebase", claude_enabled=True)
    assert d.tier == "claude" and d.claude_handoff is True


def test_router_falls_back_to_neon_when_claude_off():
    d = router.choose_route(DummyBrain(), "refactor my project codebase", claude_enabled=False)
    assert d.tier == "neon" and d.claude_handoff is False


def test_router_tiers():
    brain = DummyBrain()
    assert router.choose_route(brain, "prove this theorem step by step").tier == "neon"
    assert router.choose_route(brain, "write an email to my professor").tier == "hydrogen"
    assert router.choose_route(brain, "open Spotify").tier == "flash"


def test_router_manual_override_wins():
    d = router.choose_route(DummyBrain(), "/flash prove this theorem step by step")
    assert d.tier == "flash" and d.cleaned_text == "prove this theorem step by step"


# ── Wake word, yes/no & noise filters (emi/stt.py) ────────────────────────────
def test_wake_word_matching():
    assert stt.match_wake("Hey Emi, open Spotify", ["emi", "emmy"]) == (True, "open Spotify")
    assert stt.match_wake("Emi", ["emi"]) == (True, "")
    assert stt.match_wake("I was talking to Emi yesterday", ["emi"]) == (False, "")


def test_yes_no_parser():
    assert stt.yes_no("yeah go ahead") is True
    assert stt.yes_no("no cancel that") is False
    assert stt.yes_no("maybe later") is None


def test_noise_filter():
    assert stt.is_noise("thank you for watching") is True
    assert stt.is_noise("um hmm") is True
    assert stt.is_noise("open Chrome") is False


# ── Reminder time parser (emi/tools/productivity.py) ──────────────────────────
def test_parse_when():
    now = datetime(2026, 11, 23, 10, 0)
    assert parse_when("in 30 minutes", now=now) == datetime(2026, 11, 23, 10, 30)
    assert parse_when("2026-12-01T09:15", now=now) == datetime(2026, 12, 1, 9, 15)
    assert parse_when("tomorrow 8:30 am", now=now) == datetime(2026, 11, 24, 8, 30)
    with pytest.raises(ToolError):
        parse_when("someday soon", now=now)


# ── Reply mode planner (emi/agent.py) ─────────────────────────────────────────
def test_plan_reply():
    assert agent.plan_reply("anything", "voice", "auto", "long text", gaming=True) == (True, False)
    assert agent.plan_reply("show me the list", "voice", "auto", "item 1") == (False, True)
    assert agent.plan_reply("what is 2+2", "typed", "auto", "4") == (False, True)
    assert agent.plan_reply("what time is it", "voice", "auto", "It is 5 PM.") == (True, False)
    assert agent.plan_reply("write a loop", "voice", "auto", "```python\npass\n```") == (True, True)