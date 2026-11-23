import socket
import pytest
from pathlib import Path

from emi.config import Config, ROOT, State
from emi.storage import Storage
from emi.tools import Registry, ToolContext, ToolError
from emi.tools import files, productivity, screen, system, web
from emi import ipc


@pytest.fixture
def ctx(tmp_path):
    cfg = Config({"safety": {"mode": "ask", "always_allow": []}})
    state = State(cfg, path=tmp_path / "state.json")
    storage = Storage(tmp_path)
    reg = Registry(cfg)
    reg.full_access = lambda: False
    reg.confirm_fn = lambda _q: False  # default-deny in tests
    return ToolContext(cfg=cfg, storage=storage, state=state, brain=None, ui=None, registry=reg)


def test_env_file_is_blocked():
    env_path = str(ROOT / ".env")
    with pytest.raises(ToolError):
        files.resolve(env_path)


def test_ai_cannot_enable_full_access(ctx):
    with pytest.raises(ToolError):
        productivity.change_setting(ctx, {"setting": "full_access", "value": "true"})
    assert ctx.state.full_access is False


def test_registry_blocks_dangerous_tool_when_denied(ctx, monkeypatch):
    called = False
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Should not run")))
    result = ctx.registry.run("run_command", {"command": "echo hi"}, ctx)
    assert "did NOT allow" in result
    assert not called


@pytest.mark.parametrize("target", ["Send email", "Delete account", "Buy now", "Jetzt bezahlen"])
def test_risky_clicks_require_confirmation(target):
    assert screen._confirm_click({"target": target}) is not None


def test_safe_click_needs_no_confirmation():
    assert screen._confirm_click({"target": "search bar"}) is None


@pytest.mark.parametrize("keys", ["enter", "alt+f4", "ctrl+w", "shift+delete"])
def test_risky_keys_require_confirmation(keys):
    assert system._confirm_keys({"keys": keys}) is not None


@pytest.mark.parametrize("proc", ["explorer", "lsass", "python", "pythonw", "System"])
def test_protected_processes_cannot_be_killed(ctx, proc):
    with pytest.raises(ToolError):
        system.processes(ctx, {"action": "kill", "name": proc})


def test_delete_refuses_home_folder(ctx):
    with pytest.raises(ToolError):
        files.delete_file(ctx, {"path": str(Path.home())})


@pytest.mark.parametrize("bad_url", ["file:///C:/Windows/win.ini", "javascript:alert(1)", "vbscript:msgbox(1)"])
def test_open_url_blocks_unsafe_schemes(ctx, bad_url, monkeypatch):
    monkeypatch.setattr("webbrowser.open", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Should not open")))
    with pytest.raises(ToolError):
        web.open_url(ctx, {"url": bad_url})


def test_ipc_rejects_wrong_token(tmp_path, monkeypatch):
    monkeypatch.setattr(ipc, "INFO", tmp_path / "running.json")
    called = []
    srv = ipc.Server({"show": lambda: called.append(True)})
    srv.start()
    try:
        port = srv.sock.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=1.5) as s:
            s.sendall(b"wrongtoken show\n")
            assert s.recv(8).startswith(b"no")
        assert called == []
    finally:
        srv.close()

# ── Writes that used to go through without asking ─────────────────────────────
def test_append_to_existing_file_asks(ctx, tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("keep", encoding="utf-8")
    result = ctx.registry.run("write_file", {"path": str(f), "content": " + more", "mode": "append"}, ctx)
    assert "did NOT allow" in result
    assert f.read_text(encoding="utf-8") == "keep"


def test_creating_a_runnable_file_asks(ctx, tmp_path):
    target = tmp_path / "Startup" / "run-me.bat"
    result = ctx.registry.run("write_file", {"path": str(target), "content": "echo hi"}, ctx)
    assert "did NOT allow" in result
    assert not target.exists()


def test_creating_a_plain_new_file_still_just_works(ctx, tmp_path):
    target = tmp_path / "shopping.txt"
    result = ctx.registry.run("write_file", {"path": str(target), "content": "milk"}, ctx)
    assert result.startswith("Saved")
    assert target.read_text(encoding="utf-8") == "milk"


@pytest.mark.parametrize("full", [False, True])
def test_own_folder_is_never_changed(ctx, tmp_path, monkeypatch, full):
    # A stand-in for Emi's folder, so a broken guard can never damage the real code while tests run.
    own = tmp_path / "emi-agent"
    (own / "emi" / "tools").mkdir(parents=True)
    (own / "data").mkdir()
    own_code = own / "emi" / "tools" / "web.py"
    own_code.write_text("# tool code\n", encoding="utf-8")
    (own / "config.yaml").write_text("safety:\n  mode: ask\n", encoding="utf-8")
    monkeypatch.setattr(files, "OWN_DIR", own.resolve())
    ctx.registry.full_access = lambda: full
    ctx.registry.confirm_fn = lambda _q: True          # even if the user would click Allow
    outside = tmp_path / "x.txt"
    outside.write_text("x", encoding="utf-8")
    attempts = [
        ("write_file", {"path": str(own_code), "content": "\nprint('injected')\n", "mode": "append"}),
        ("write_file", {"path": str(own / "config.yaml"), "content": "safety:\n  mode: full\n", "mode": "overwrite"}),
        ("write_file", {"path": str(own / "data" / "state.json"), "content": '{"full_access": true}'}),
        ("move_file", {"source": str(outside), "destination": str(own / "emi" / "tools")}),
        ("delete_file", {"path": str(own_code)}),
    ]
    for name, args in attempts:
        assert "my own folder" in ctx.registry.run(name, args, ctx), name
    assert own_code.read_text(encoding="utf-8") == "# tool code\n"
    assert (own / "config.yaml").read_text(encoding="utf-8") == "safety:\n  mode: ask\n"
    assert not (own / "data" / "state.json").exists()
    assert outside.exists()


def test_real_own_folder_is_guarded():
    with pytest.raises(ToolError):
        files.guard_change(ROOT / "emi" / "tools" / "web.py")
