"""Long jobs: step budget, "continue", trimming old results, the browser tool's page reading, safe unzipping."""
import io
import threading
import zipfile

from emi import agent
from emi.config import Config
from emi.llm import Step, ToolCall
from emi.tools import ToolError, files
from emi.tools.browser import best_match, format_page


# ── fakes ──────────────────────────────────────────────────────────────────────
class FakeBrain:
    instant, fast_model, model, provider, auto_mode = True, "fake", "fake", "gemini", False
    active_route = None

    def __init__(self, steps):
        self.steps = list(steps)
        self.seen = []                     # the messages each step was given

    def start(self, history, text):
        return [dict(m) for m in history] + [{"role": "user", "content": text}]

    def step(self, messages, static, dynamic, tools, **kw):
        self.seen.append([dict(m) for m in messages])
        s = self.steps.pop(0)
        messages.append({"role": "assistant", "content": s.text})
        if s.calls:
            messages[-1]["tool_calls"] = [{"id": c.id, "name": c.name} for c in s.calls]
        return s

    def add_results(self, messages, results):
        for call, result in results:
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})


class FakeRegistry:
    def __init__(self):
        self.tools = {"press_keys": None, "browser": None}
        self.ran = []

    def is_enabled(self, name):
        return name != "ask_claude"

    def schemas(self):
        return []

    def label(self, name, args):
        return name

    def run(self, name, args, ctx):
        self.ran.append((name, args))
        if args.get("fail"):
            return "Error: can't find it"
        return f"{name} ok " + "x" * 3000


class FakeUI:
    def __getattr__(self, name):
        return lambda *a, **k: 0


class FakeStorage:
    def memories(self):
        return []

    def reminders(self):
        return []

    def append_history(self, *a):
        pass


class FakeState:
    personality, incognito, full_access, reply_mode = "chill", True, False, "text"


def make_agent(steps, **brain_cfg):
    cfg = Config({"brain": brain_cfg, "assistant": {"name": "Emi"}})
    a = agent.Agent(cfg, FakeBrain(steps), FakeRegistry(), FakeStorage(), FakeState(), FakeUI())
    a.stop_event = threading.Event()
    return a


def call(name, n, **args):
    return ToolCall(f"c{n}", name, args)


# ── the agent loop ───────────────────────────────────────────────────────────
def test_step_budget_then_continue_picks_up_exactly_there():
    # 3 steps allowed; the job needs 5 browser steps, then a final reply
    steps = [Step("", [call("browser", i, action="click", target=f"course {i}")]) for i in range(5)]
    steps.append(Step("All 5 courses downloaded.", []))
    a = make_agent(steps, max_steps=3)
    first = a.handle("download all 5 courses", "typed")
    assert "continue" in first.lower() and a.last_run["unfinished"]
    assert len(a.registry.ran) == 3

    final = a.handle("continue", "typed")
    assert final == "All 5 courses downloaded."
    assert len(a.registry.ran) == 5
    # the resumed run saw everything the first run did (its tool results), not just the reply
    resumed = a.brain.seen[3]
    assert sum(1 for m in resumed if m["role"] == "tool") == 3
    assert resumed[-1]["role"] == "user" and resumed[-1]["content"].startswith("[typed] continue")


def test_continue_does_not_stop_after_a_finishing_tool():
    # the old bug: "continue" → press Enter → "Done." without carrying on
    steps = [Step("", [call("browser", 0, action="click", target="ZIP")]) for _ in range(1)]
    a = make_agent(steps + [Step("", [call("browser", 1)])], max_steps=1)
    a.handle("download the courses and unzip them", "typed")
    a.max_steps = 10
    a.brain.steps = [Step("", [call("press_keys", 2, keys="enter")]),
                     Step("", [call("browser", 3, action="download")]),
                     Step("Finished.", [])]
    assert a.handle("continue", "typed") == "Finished."
    assert [n for n, _ in a.registry.ran][-2:] == ["press_keys", "browser"]


def test_plain_resume_after_a_finished_job_is_not_a_continue():
    a = make_agent([Step("Opened it.", [])])
    a.handle("what's on moodle", "typed")
    assert a._resumable("resume") is None                 # → the music command
    assert a._resumable("ok I'm logged in, continue") is not None
    assert a._resumable("go on") is not None
    assert a._resumable("open spotify") is None


def test_old_results_are_trimmed_newest_kept():
    msgs = [{"role": "user", "content": "x"}]
    for i in range(10):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": str(i)}]})
        msgs.append({"role": "tool", "tool_call_id": str(i), "content": f"r{i} " + "y" * 5000})
    agent.compact(msgs, keep=3, limit=100)
    tools = [m for m in msgs if m["role"] == "tool"]
    assert all(len(m["content"]) > 4000 for m in tools[-3:])
    assert all(len(m["content"]) < 200 and m["content"].startswith(f"r{i}") for i, m in enumerate(tools[:-3]))


def test_action_note_is_kept_with_the_reply():
    a = make_agent([Step("", [call("browser", 0, action="open", url="moodle")]), Step("Opened.", [])])
    a.handle("open moodle in your browser and read it", "typed")
    assert "[What I did: browser(" in a.history[-1]["content"]


def test_real_folder_paths_are_in_the_prompt():
    a = make_agent([])
    a.folders = {"Desktop": r"C:\Users\x\OneDrive - TUM\Desktop"}
    static, _ = a.system_prompt()
    assert r"OneDrive - TUM\Desktop" in static and "make_folder" in static and "browser tool" in static


# ── browser page reading ─────────────────────────────────────────────────────
ELS = [
    {"n": 1, "kind": "link", "label": "Alle Kurse", "href": "https://m/x", "main": False},
    {"n": 2, "kind": "link", "label": "Alle", "href": "https://m/#", "main": True},
    {"n": 3, "kind": "button", "label": "ZIP-Archiv erstellen", "href": "", "main": True},
    {"n": 4, "kind": "text field", "label": "Download Center suchen", "href": "", "main": True},
    {"n": 5, "kind": "link", "label": "Download Center", "href": "https://m/local/downloadcenter/index.php?courseid=7",
     "main": True},
]


def test_best_match_prefers_exact_names_and_buttons():
    assert best_match(ELS, "Alle")["n"] == 2
    assert best_match(ELS, "zip-archiv")["n"] == 3
    assert best_match(ELS, "Download Center")["n"] == 5          # the link, not the search box
    assert best_match(ELS, "downloadcenter")["n"] == 5           # by address
    assert best_match(ELS, "nothing like it") is None


def test_format_page_lists_main_area_first_and_flags_passwords():
    snap = {"title": "DC", "url": "https://m/local/x", "text": "hello\nVorlesung.pdf",
            "els": ELS + [{"n": 6, "kind": "password field", "label": "pw", "href": "", "main": True}]}
    out = format_page(snap)
    assert out.index("[2] link") < out.index("[1] link")
    assert "→ /local/downloadcenter/index.php?courseid=7" in out
    assert "never type passwords" in out
    assert "Vorlesung.pdf" in format_page(snap, "pdf") and "hello" not in format_page(snap, "pdf")


# ── files ────────────────────────────────────────────────────────────────────
def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    buf.seek(0)
    return buf


def test_safe_extract_blocks_zip_slip_and_keeps_umlauts(tmp_path):
    z = _zip({"Übungen/Blatt 1: Intro.pdf": b"a", "../evil.txt": b"b", "/abs.txt": b"c", "ok/x.txt": b"d"})
    dest = tmp_path / "course"
    written, existing, skipped = files.safe_extract(z, dest)
    assert written == 2 and len(skipped) == 2
    assert (dest / "Übungen" / "Blatt 1_ Intro.pdf").read_bytes() == b"a"
    assert not (tmp_path / "evil.txt").exists()
    z.seek(0)
    assert files.safe_extract(z, dest)[:2] == (0, 2)          # second run: nothing overwritten


def test_zip_names_without_utf8_flag_are_fixed():
    class Info:
        filename = "Prüfung.pdf".encode("utf-8").decode("cp437")
        flag_bits = 0
    assert files._zip_name(Info()) == "Prüfung.pdf"


def test_make_folder_with_subfolders(tmp_path):
    out = files.make_folder(None, {"path": str(tmp_path / "third semester"),
                                   "subfolders": ["CNS | Rechnernetze", "Grundlagen: Datenbanken", "..", "a/../b"]})
    names = sorted(p.name for p in (tmp_path / "third semester").iterdir())
    assert names == ["CNS _ Rechnernetze", "Grundlagen_ Datenbanken", "a"]
    assert (tmp_path / "third semester" / "a" / "b").is_dir()        # ".." parts are dropped, never followed
    assert "Created" in out
    try:
        files.make_folder(None, {"path": str(files.OWN_DIR / "x")})
        assert False, "Emi's own folder must stay off-limits"
    except ToolError:
        pass


def test_chained_browser_steps_stop_after_a_failure():
    a = make_agent([Step("", [call("browser", 0, action="open"), call("browser", 1, action="click", fail=True),
                              call("browser", 2, action="download")]),
                    Step("Couldn't find it.", [])])
    a.handle("download it from the site", "typed")
    assert [x.get("action") for _, x in a.registry.ran] == ["open", "click"]
    tool_msgs = [m for m in a.brain.seen[1] if m["role"] == "tool"]
    assert tool_msgs[-1]["content"].startswith("Error: skipped")
