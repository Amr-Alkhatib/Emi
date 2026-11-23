"""Emi — a voice-controlled AI assistant for your Windows PC.

    python main.py            normal mode: dynamic island + voice + hotkeys + tray icon
    python main.py --no-voice island + typing only (no microphone)
    python main.py --text     chat in this terminal (great for testing tools)
    python main.py --check    test your setup: API key, mic, speakers, voice
    python main.py --summon   start (or wake up the running copy) and listen right away
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time

from emi.config import DATA_DIR, ConfigError, State, load_config


def setup_logging():
    DATA_DIR.mkdir(exist_ok=True)
    handlers = [logging.FileHandler(DATA_DIR / "emi.log", encoding="utf-8")]
    if sys.stderr is not None:  # pythonw has no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpcore", "anthropic", "openai", "faster_whisper", "pywebview", "primp", "ddgs",
                  "huggingface_hub", "httpx2", "PIL", "pystray"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def make_dpi_aware():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # sharp text on high-res screens
        except Exception:
            pass


def make_confirm(cfg, ui, agent, tts, get_listener):
    """Returns confirm(text) -> bool. Shows Allow/Deny on the card and, for voice requests, also asks out loud."""
    from emi.stt import yes_no

    def confirm(text: str) -> bool:
        done = threading.Event()
        result = {"ok": False}

        def decide(ok: bool):
            if not done.is_set():
                result["ok"] = ok
                done.set()

        listener = get_listener()
        use_voice = bool(cfg.get("safety.voice_confirm", True) and listener and tts
                         and agent.current_source == "voice")
        ui.set_status("listening" if use_voice else "working", "Needs your OK")
        cid = ui.ask_confirm(text, decide, use_voice)

        if use_voice:
            def ask_out_loud():
                tts.speak(text.split("\n")[0] + " Should I go ahead?")
                for _ in range(2):
                    if done.is_set():
                        return
                    heard = listener.listen_once(timeout=8)
                    if heard:
                        verdict = yes_no(heard)
                        if verdict is not None:
                            decide(verdict)
                            return
            threading.Thread(target=ask_out_loud, daemon=True).start()

        start = time.time()
        while not done.wait(0.2):
            if agent.stop_event.is_set() or time.time() - start > 120:
                decide(False)
        ui.close_confirm(cid)
        ui.set_status("working", "Allowed" if result["ok"] else "Cancelled")
        return result["ok"]

    return confirm


def doctor(cfg):
    """python main.py --check"""
    print(f"\nPython {sys.version.split()[0]} on {sys.platform}")
    from emi.llm import Brain, friendly_error
    brain = Brain(cfg)
    print(f"\n[brain] provider={brain.provider} model={getattr(brain, 'model', '?')}")
    if brain.error:
        print("  ✗", brain.error)
    else:
        try:
            msgs = brain.start([], "Reply with exactly: ready")
            step = brain.step(msgs, "You are a test.", "", [])
            print("  ✓ the model answered:", step.text[:80])
        except Exception as e:
            print("  ✗", friendly_error(e))

    print("\n[Claude helper]")
    from emi.tools.claude_code import find_claude
    exe = find_claude()
    if not exe:
        print("  – Claude Code isn't installed (optional). Run install_claude_helper.bat to add it.")
    else:
        try:
            import json as _json
            import subprocess
            env = os.environ.copy()
            env.pop("ANTHROPIC_API_KEY", None)
            out = subprocess.run([exe, "-p", "Reply with exactly: ready", "--output-format", "json"],
                                 capture_output=True, text=True, timeout=120, env=env,
                                 encoding="utf-8", errors="replace")
            res = _json.loads(out.stdout or "{}")
            if res.get("is_error") or not res:
                print("  ✗ Claude Code answered with an error:", (res.get("result") or out.stderr)[:200])
                print("    Open a terminal, run `claude` and log in with your Claude account.")
            else:
                print("  ✓ Claude Code works on your Claude plan:", str(res.get("result"))[:60])
        except Exception as e:
            print("  ✗ couldn't run Claude Code:", e)

    print("\n[audio devices]")
    try:
        import numpy as np
        import sounddevice as sd
        print(sd.query_devices())
        print("\n  Recording 3 seconds — say something…")
        rec = sd.rec(int(3 * 16000), samplerate=16000, channels=1, dtype="float32")
        sd.wait()
        level = float(np.sqrt(np.mean(rec ** 2)))
        print(f"  mic level: {level:.4f}  " + ("✓ good" if level > 0.01 else "(quiet — check the mic or lower hearing.sensitivity)"))
    except Exception as e:
        print("  ✗ audio problem:", e)

    print("\n[voice]")
    try:
        from emi.audio import Player
        from emi.tts import TTS
        tts = TTS(cfg, State(cfg), Player(cfg.get("voice.output_device")))
        print("  engine:", type(tts.engine).__name__ if tts.engine else "none")
        tts.speak(f"Hi! I'm {cfg.name}. If you can hear me, the voice works.")
        print("  ✓ spoke a test sentence")
    except Exception as e:
        print("  ✗ voice problem:", e)

    print("\n[ears] loading Whisper (first time downloads ~150 MB)…")
    try:
        from emi.stt import LocalWhisper
        LocalWhisper(cfg.get("hearing.local_model", "base.en"))
        print("  ✓ speech recognition ready")
    except Exception as e:
        print("  ✗", e)
    print("\nDone. Logs are in data/emi.log\n")


def text_mode(cfg, agent, registry, ui):
    registry.confirm_fn = make_confirm(cfg, ui, agent, None, lambda: None)
    print(f"\n{cfg.name} — terminal mode. Type a request (or 'quit').\n")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("quit", "exit"):
            break
        if text:
            agent.handle(text, "typed")


def main():
    parser = argparse.ArgumentParser(description="Emi, your PC assistant")
    parser.add_argument("--text", action="store_true", help="chat in the terminal")
    parser.add_argument("--no-voice", action="store_true", help="no microphone, typing only")
    parser.add_argument("--check", action="store_true", help="test your setup")
    parser.add_argument("--summon", action="store_true", help="listen right away once started")
    parser.add_argument("--type", action="store_true", help="open the typing box once started")
    parser.add_argument("--show", action="store_true", help="just start / open the Control Center")
    parser.add_argument("--background", action="store_true", help="start quietly (used at Windows startup)")
    parser.add_argument("--fresh", action="store_true", help="(internal) restarting after an update")
    args = parser.parse_args()

    if not (args.text or args.check or args.fresh):  # already running? hand the request over and quit
        from emi import ipc
        if ipc.send("summon" if args.summon else "type" if args.type else "show"):
            return
        if sys.platform == "win32" and (ipc.ROOT / "data" / "admin_task").exists() and not args.background:
            import ctypes
            import subprocess
            if not ctypes.windll.shell32.IsUserAnAdmin():  # set up to run as administrator → start that copy
                subprocess.Popen(["schtasks", "/run", "/tn", "Emi"], creationflags=0x08000000)
                return

    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    make_dpi_aware()
    try:
        cfg = load_config()
    except ConfigError as e:
        print("Config problem:", e)
        sys.exit(1)
    setup_logging()
    log = logging.getLogger("emi")

    if args.check:
        return doctor(cfg)

    from emi.agent import Agent
    from emi.llm import Brain
    from emi.storage import Storage
    from emi.tools import Registry

    storage = Storage(DATA_DIR)
    state = State(cfg)
    brain = Brain(cfg, state)
    registry = Registry(cfg)
    registry.full_access = lambda: state.full_access
    from emi.tools.claude_code import helper_available
    registry.is_enabled = lambda name: helper_available(state) if name == "ask_claude" else True

    if args.text:
        from emi.ui import ConsoleUI
        ui = ConsoleUI()
        agent = Agent(cfg, brain, registry, storage, state, ui, tts=None)
        if brain.error:
            print("⚠ ", brain.error)
        return text_mode(cfg, agent, registry, ui)

    try:
        from emi.ui import WebUI
        ui = WebUI(cfg, state, storage, start_hidden=args.background, brain=brain)
    except Exception as e:
        print(f"The window couldn't start ({e}). Falling back to terminal mode.\n")
        from emi.ui import ConsoleUI
        ui = ConsoleUI()
        agent = Agent(cfg, brain, registry, storage, state, ui, tts=None)
        return text_mode(cfg, agent, registry, ui)

    from emi.audio import Player
    from emi.tts import TTS
    player = Player(cfg.get("voice.output_device"))
    player.on_level = ui.level            # Emi's voice drives the island's waveform
    tts = TTS(cfg, state, player)
    agent = Agent(cfg, brain, registry, storage, state, ui, tts)
    ui.tts = tts
    holder: dict = {"listener": None}
    registry.confirm_fn = make_confirm(cfg, ui, agent, tts, lambda: holder["listener"])

    def start_ears():
        if args.no_voice:
            ui.voice_ok = False
            ui.set_status("idle", "Voice is off. Press the keyboard button or Alt + Shift + S to type.")
            if args.summon:
                on_type()
            return
        ui.set_status("loading", "Warming up my ears…")
        if args.summon:
            ui.show_card()      # started by the shortcut: show that she's coming
        try:
            from emi.audio import Microphone
            from emi.listener import Listener
            from emi.stt import CloudWhisper, LocalWhisper
            stt_kind = str(cfg.get("hearing.stt", "local")).lower()
            lang = str(cfg.get("assistant.language", "en"))
            cmd = (LocalWhisper(cfg.get("hearing.local_model", "base.en"), lang) if stt_kind == "local"
                   else CloudWhisper(stt_kind, lang))
            wake_name = cfg.get("hearing.wake_model", "tiny.en")
            wake = cmd if (stt_kind == "local" and wake_name == cmd.name) else LocalWhisper(wake_name, lang)
            listener = Listener(cfg, Microphone(cfg.get("hearing.mic_device")), wake, cmd,
                                on_command=lambda t: agent.submit(t, "voice"), ui=ui, player=player,
                                is_paused=tts.speaking.is_set,
                                is_busy=lambda: agent.busy.is_set() or tts.speaking.is_set(),
                                is_muted=lambda: state.paused, on_wake=brain.warm)
            holder["listener"] = listener
            listener.start()
        except Exception as e:
            log.exception("voice input failed")
            ui.voice_ok = False
            ui.set_status("error", f"Voice input is off: {e}. You can still type.")
            holder["ears_failed"] = True
        if args.summon:   # started by the summon shortcut → listen straight away
            time.sleep(0.5)
            on_summon()

    def on_talk():
        if holder["listener"]:
            tts.stop()
            holder["listener"].trigger()
        else:
            ui.open_input()

    def on_summon():
        if holder["listener"]:
            on_talk()
        elif not args.no_voice and not holder.get("ears_failed"):
            ui.notify("Still warming up my ears. One sec…")
        else:
            ui.open_input()

    def on_type():
        ui.open_input()

    CROP_PRESETS = {   # quick-menu shortcuts that ask a fixed question about the area you select
        "translate": f"Translate the text in this area into {cfg.get('assistant.translate_to', 'English')}. "
                     "Show only the translation.",
        "explain": "Explain what this shows, simply and in a few sentences.",
        "copy": "Read the exact text in this area and put it on my clipboard with the clipboard tool. "
                "Then reply with just: Copied, and the first few words.",
    }

    def on_crop(preset: str | None = None):
        """Freeze the screen, let you drag a box, then ask about it (typing or voice)."""
        if state.incognito:
            ui.notify("Incognito is on, so I'm not capturing the screen.")
            return
        if state.gaming:
            return
        ui.hide_card()          # so the card isn't in the picture
        time.sleep(0.2)
        try:
            from emi.tools.screen import capture, set_selection, to_b64
            img, _ = capture("full")
        except Exception as e:
            ui.notify(f"Couldn't capture the screen: {e}")
            return

        def done(frac):
            if not frac:
                return
            x0, y0, x1, y1 = frac
            crop = img.crop((int(x0 * img.width), int(y0 * img.height), int(x1 * img.width), int(y1 * img.height)))
            set_selection(crop)
            if preset in CROP_PRESETS:
                agent.submit(CROP_PRESETS[preset], "typed", "crop")
                return
            agent.pending_mode = ("crop", time.time())
            ui.show_card()
            ui.notify("Got that area. Ask me about it.")
            if holder["listener"]:
                on_talk()
            else:
                ui.open_input()
        ui.open_crop(to_b64(img, max_side=2560), done)

    def on_stop():
        agent.stop()
        if holder["listener"]:
            holder["listener"].cancel()
        ui.dismiss()

    def on_end():
        """Alt+X: stop listening for follow-up requests (the conversation is over)."""
        if holder["listener"]:
            holder["listener"].end_conversation()

    def on_incognito():
        state.set("incognito", not state.incognito)
        ui.notify("Incognito is on. Nothing new is saved." if state.incognito else "Incognito is off.")

    def on_reminder(r):
        ui.notify(f"Reminder: {r['text']}")
        player.chime("wake")
        threading.Thread(target=tts.speak, args=(f"Hey, reminder: {r['text']}",), daemon=True).start()

    def on_menu(name: str):
        """A tile in the quick menu (click the notch at the top of the screen)."""
        if name == "talk":
            on_talk()
        elif name == "type":
            on_type()
        elif name == "screen":
            agent.pending_mode = ("screen", time.time())
            if holder["listener"]:
                on_talk()
            else:
                ui.open_input("screen")
        elif name == "area":
            on_crop()
        elif name in CROP_PRESETS:
            on_crop(name)
        elif name == "clipboard":
            agent.submit("Read what's on my clipboard (clipboard tool) and explain or summarise it briefly.", "typed")
        elif name == "pause":
            state.set("paused", not state.paused)
        elif name == "incognito":
            on_incognito()
        elif name == "control":
            ui.open_control()

    ui.on_menu = on_menu
    ui.on_submit = agent.submit
    ui.on_talk = on_talk
    ui.on_stop = on_stop
    ui.on_crop = on_crop
    ui.on_type = on_type

    from emi.tray import Tray
    tray = Tray(cfg.name, {"control": ui.open_control, "talk": on_talk, "type": on_type,
                           "incognito": on_incognito, "quit": ui.quit}, lambda: state.incognito)
    ui.on_quit = tray.stop
    state.watch(lambda k, v: k == "incognito" and tray.refresh())

    def on_start():  # runs once the window is up
        from emi.hotkeys import register
        from emi.scheduler import ReminderScheduler
        agent.start()
        from emi import ipc
        ipc.Server({"summon": on_summon, "show": ui.open_control, "type": on_type}).start()
        tray.start()
        register(cfg, {"talk": on_talk, "type": on_type, "stop": on_stop, "incognito": on_incognito,
                       "crop": on_crop, "end": on_end})
        from emi.gaming import GamingWatcher
        from emi.proactive import Proactive
        GamingWatcher(cfg, state, ui.set_gaming).start()
        Proactive(cfg, state, brain, ui, agent, storage).start()
        if args.type:
            on_type()
        ReminderScheduler(storage, on_reminder).start()
        if not state.welcomed:
            ui.first_run()
        elif args.show and not args.background:
            ui.open_control()
        if brain.error:
            ui.open_control("brain")
            ui.notify(brain.error)
        threading.Thread(target=start_ears, daemon=True).start()
        threading.Thread(target=brain.find_fast_model, daemon=True, name="fast-model").start()
        if cfg.get("updates.auto_restart", True):
            from emi.updater import Updater, start_fresh_copy

            def idle() -> bool:
                lst = holder["listener"]
                return (not agent.busy.is_set() and not tts.speaking.is_set() and not ui.busy_with_you()
                        and not (lst and (lst.in_conversation or lst.awaiting_until)))

            def restart():
                log.info("restarting to use the updated files")
                start_fresh_copy()
                ui.quit()
            Updater(idle, restart).start()

    log.info("starting %s with %s / %s", cfg.name, brain.provider, getattr(brain, "model", "?"))
    ui.run(on_start)
    os._exit(0)  # window closed → stop every background thread


if __name__ == "__main__":
    main()
