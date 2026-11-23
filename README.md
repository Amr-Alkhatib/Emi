# Emi: your own voice assistant for Windows

Emi sits in the corner of your screen. Say **"Emi, …"** from any app, or press your summon shortcut (even when she isn't running), and she answers out loud. She can open and close apps, control music, find, read and organise files, run commands, search the web, look at your screen, remember things about you, set reminders, run your routines, and do multi-step jobs on your PC.

Her brain is **Gemini** (you can pick the model in her Control Center). Big jobs such as code, documents, sorting lots of files, or research go to **Claude** through Claude Code, which runs on your Claude plan with no API key or credits. Hearing runs on your laptop's CPU, and your memories are plain files in the `data` folder.

> Emi is your own project. It was inspired by desktop assistants like AYO but isn't affiliated with them and doesn't use any of their code or assets.

---

## Will it run on my MagicBook? Yes, and you don't need a graphics card

| Part | Where it runs |
|---|---|
| Hearing the name "Emi" and turning speech into text | Your CPU (Whisper). Audio never leaves the laptop |
| Thinking, quick PC tasks, reading the screen | **Gemini API** (cloud) |
| Big jobs (code, documents, many files, research) | **Claude Code** on your Claude plan (optional) |
| Voice | Microsoft Edge neural voices (online, free), or Kokoro (offline, on your CPU) |
| Memory, notes, reminders, history | Files in `data\` on your PC |

---

## Your Gemini API key, explained

**What it is.** A password-like code that lets Emi use Gemini and bills or counts the usage on your Google account. Create it at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

**Your Google AI Pro plan.** The plan by itself doesn't pay for API keys: its AI Studio perks apply in the AI Studio website, and API use through keys is billed separately. What Pro *does* include is a monthly Google Cloud credit you can put toward the Gemini API. To use it:
1. Open [Google AI Studio](https://aistudio.google.com), set up your Google Developer Program profile, link a billing account, and claim the monthly credit. AI Studio walks you through it.
2. Create your API key in AI Studio, in the project that has billing linked.

Without billing, the key still works on the free tier, with lower limits.

**Free vs. paid tier and your data.**
- If the key is on the **free tier**, Google may use what you send to improve its products, and human reviewers may read it. Google's own terms say not to send anything sensitive on the free tier.
- With **billing linked**, which is what claiming the Pro credit does, the key counts as a paid service and Google doesn't use your prompts to improve its products.

**Where the key lives.** Only in the `.env` file inside Emi's folder, on your PC. Emi's file tools refuse to read, move or delete `.env`. Don't share or upload that file. If the key leaks, delete it in AI Studio and make a new one.

**Picking a model.** Open the Control Center → **Brain** to see the models your key can use. *Flash* models are fast and good at doing things; *Flash Lite* is the cheapest and fastest; *Pro* is smartest but slower and pricier. Your choice is remembered.

---

## The Claude helper (no API key)

Gemini is quick at everyday things. For careful, many-step work, Emi hands the job to **Claude Code**, Anthropic's agent app, and it runs on **your Claude plan**, not on API credit.
- **What it's good for:** writing or fixing code, creating or editing documents and reports, organising or renaming many files, research write-ups, and analysing spreadsheets.
- **How it works:** Claude works in a folder, reports back, and Emi tells you what it did. "Also add a title" continues the same job.
- **Set it up:** double-click `install_claude_helper.bat`. It installs Claude Code and asks you to sign in once with your Claude account. Claude Code needs a paid Claude plan (Pro, Max, Team or Enterprise); the free plan doesn't include it.
- **Usage limits:** jobs count toward the same usage limits as your Claude chats. If you hit the limit, Emi tells you and you can try again later.
- **No API charges:** Emi starts Claude Code with your plan's login and never passes an API key to it.
- **Permissions:** with *Ask before risky actions* on, you approve each job, and Claude may create and edit files in that folder but can't run other commands. With full access, it can do anything without asking.
- **Switch it off** with **Claude helper** on the Control Center's **Brain** page.

---

## What leaves your PC (and what doesn't)

| Goes to | What | When |
|---|---|---|
| **Google** (Gemini API) | Your request, your saved memories, and results of the tools Emi used | Every request |
| | A screenshot | Only when you ask about your screen, never in incognito |
| **Anthropic** (Claude Code) | The job description and the files Claude reads in that folder | Only when Emi hands Claude a job |
| **Microsoft** (Edge voice) | The text of Emi's spoken replies | When she speaks. Set `voice.engine: kokoro` to keep this offline |
| **DuckDuckGo** | Your search words | Only when she searches the web |
| **Hugging Face** | Nothing about you; it's just the speech model download | Once, on first run |

Your voice recordings, memories, notes, reminders and chat history stay on your PC. Want nothing to leave for the thinking part? Use the local brain (see *Other brains*).

---

## Setup (about 15 minutes)

1. **Have Python 3.13** (or 3.12) installed from [python.org/downloads](https://www.python.org/downloads/), with **"Add python.exe to PATH"** ticked. `setup.bat` finds it automatically, even if you also have a newer Python. Python 3.14 is too new for some of Emi's packages.
2. **Get your Gemini API key** at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). To use your Pro plan's monthly credit, see above.
3. **Unzip** `emi-agent` somewhere permanent, for example `Documents\emi-agent`. Don't move the folder later; the shortcuts point to it.
   If Windows says it "protected your PC" when you run a `.bat` file, click **More info → Run anyway**.
4. **Double-click `setup.bat`.** It installs everything. Then:
   - Notepad opens `.env`. Paste your key after `GEMINI_API_KEY=`, save, and close it.
   - It asks about your **summon shortcut**, **start with Windows**, and **administrator rights** (see below). Pressing Enter picks the safe default.
5. **Optional: double-click `install_claude_helper.bat`** so Emi can hand big jobs to Claude (see above).
6. **Double-click `check.bat`.** It tests the key, the Claude helper, the mic, speakers and voice, and downloads the speech model (about 150 MB, first time only).
7. **Press your summon shortcut** (default `Ctrl + Alt + Shift + E`). Emi starts and listens. Say *"Emi, what can you do?"*

To change shortcut, startup or admin choices later, run `install_shortcuts.bat` again. `uninstall_shortcuts.bat` removes them all.

---

## Summoning Emi

| Do this | What happens |
|---|---|
| **Summon shortcut** (`Ctrl + Alt + Shift + E`) | Works **even when Emi isn't running**. If she's off, she starts and listens as soon as she's ready (the first time takes a few seconds). If she's on, she listens right away |
| Say **"Emi, open Spotify"** | Name and command in one breath (while she's running) |
| Say **"Emi"**, wait for the chime, then talk | Two-step version |
| `Ctrl + Alt + Space` | Talk without saying the name |
| `Alt + Shift + S` | Type instead. Tab switches between **Ask** and **Screen** mode |
| `Alt + X` | **End the conversation**: she stops listening for follow-ups (see below) |
| `Esc` | Stop talking or cancel the current task (she keeps listening) |
| `Ctrl + Alt + I` | Incognito: no new memories, screen looks or saved chat |
| `Ctrl + Alt + C` | **Crop**: the screen freezes, you drag a box around something, then ask about it (type or speak) |
| Point with the mouse while asking "what's this?" | **Hover to ask**: Emi looks right where your pointer was when you started talking |
| The **Emi** icon in the Start menu or on the Desktop | Same as the summon shortcut |

**Fast by default.** Emi is built to answer in about a second:
- **Everyday commands skip the AI entirely**: "open Spotify", "next song", "pause", "volume 30", "mute", "what time is it", "what's the date", "open my downloads", "lock my PC". Anything else, or anything that fails there, goes to the AI.
- **Instant speed** (Control Center → Brain → Speed) sends every request to a fast *Flash* model with minimal thinking, screen questions included. *Smart* uses the model you picked and thinks longer. Use it for hard questions.
- **Writing in Word, Excel or Notepad is one step**: Emi creates the document with the text already in it (saved in `Documents\Emi`) and opens it. No clicking "Blank document", no typing letter by letter. Longer text she does type into other apps is pasted in one go.
- A job that's done in one action needs only one AI turn. She doesn't ask the AI again just to say "done".
- She opens the connection to the AI while you're still talking, and short phrases she has said before ("Done.", "Opening Spotify.") play instantly the next time.
- `data\emi.log` shows how long each request took (`answered … in 1.2 s`) and how long her voice took to start. The Gemini voices take a second or two longer to start than the free Microsoft ones.

**Updates apply by themselves.** When Emi's files are updated, she restarts quietly the next time she's free (not while she's talking, working or you're in the Control Center). Switch off with `updates.auto_restart: false`.

**Only your voice wakes her.** Before checking for her name, Emi runs a speech detector that throws away sniffs, breaths, coughs, lighters and clicks, and it no longer hints the name to the speech recognizer (that made it "hear" *Emi* in plain noise). If she still wakes up by herself, raise `hearing.sensitivity` in `config.yaml` (for example to 1.5), or pause listening from the quick menu.

**Conversations.** After "Hey Emi" she keeps listening. When she's done (and has told you what she did), the island says **Your turn** and you can give the next request straight away, without saying her name. It ends when you press `Alt + X`, say *"that's all"* / *"stop listening"* / *"bye"*, or after 3 minutes without anyone talking. While a conversation is on, anything said near the mic counts as a request, so end it when you're done. Turn it off with `hearing.conversation: false` in `config.yaml`, or change the 3 minutes with `hearing.conversation_timeout`.

## The island and the Control Center

Emi stays out of sight until you need her.

- **The island.** Say *"Hey Emi"* and a pill drops out of the top of your screen while you're still talking. Its waveform moves with your voice, then with hers when she answers. If an answer is better read than heard (a list, a plan, code, a long explanation) the pill opens into a card. The card stays while you read and while your mouse is on it, then tucks itself away. Click the pill during an answer to see it written down.
- **Spoken or written.** Choose on the Control Center's **Voice** page under **Answers**: *Auto* (speaks, and writes it out when it's long), *Speak*, *Text* or *Both*. For one answer, say *"show me…"* or *"…on screen"* to get text, or *"read it out"* to hear it. Typed questions are answered in writing.
- **The Control Center** is where the settings live: voice, answers, personality, model, Claude helper, memories, shortcuts, light or dark theme. Open it from the **tray icon** near the clock, the `⋯` button on the island, or by starting Emi again while she's running.
- **The notch.** When Emi is idle, a slim glowing line waits at the top centre of your screen. Point at it and it drops down with her orb; click it for the **quick menu**: Talk, Type, ask about your screen or an area, translate / explain / copy text from an area, explain what's on your clipboard, pause listening, incognito, the Control Center, and your last few requests (click one to read its answer again). It steps aside while a video, game or slideshow fills the screen. Prefer nothing at all when idle? Control Center → Voice → **When idle** → *Hide*.
- **Tray icon:** left-click opens the Control Center; right-click has Talk, Type, Incognito and Quit.
- **Closing isn't quitting.** The ✕ on the Control Center (or closing it from the taskbar) just puts it away, like the Claude app: Emi keeps listening in the tray. To stop her completely, right-click the tray icon → **Quit Emi**.

**Why that shortcut?** Windows only allows letter, number or F-key shortcuts for this, so `Space` can't be used. On German keyboards, `Ctrl + Alt + E` types €, so the default adds `Shift`. You can pick your own in `install_shortcuts.bat`.

---

## Full access

Out of the box, Emi asks **Allow / Deny** before anything risky: running commands, deleting (to the Recycle Bin), moving, overwriting or adding to existing files, creating files that can run as programs (scripts, `.bat`, `.exe` and the like) or that land where apps keep their settings and the Startup folder, closing windows, ending programs, shutting down, or pressing Enter for you. For voice requests you can answer "yes" or "no" out loud.

**To give her full access**, switch off **Ask first** on the Control Center's home page, or set `safety.mode: full` in `config.yaml`. She then acts without asking, and the Control Center shows **Full access** so you always know. Some things stay the same either way:
- Deleted files still go to the Recycle Bin, so you can get them back.
- She won't end core Windows processes, won't touch her own API key file, and won't change anything in her own folder (her code, settings and saved choices).
- Only *you* can turn full access on or off. Emi can't change it herself, even if a web page or file tells her to.

**Administrator rights** (offered by `install_shortcuts.bat`) go one step further. Emi can change system settings, install programs for all users and control admin windows, all without UAC pop-ups. Windows asks you once while setting it up.

Be aware that with full access, and especially with admin rights, a mistake or a malicious web page or file that Emi reads could make her do something harmful without asking first. A good middle ground: keep asking switched on and add the tools you trust to `safety.always_allow` (for example `[move_file, press_keys, processes]`).

---

## Things to try
- "Open Discord and set the volume to 30."
- "What's on my screen?" or "Explain this error."
- "Find the PDF I downloaded about the internship and summarise it."
- "Have Claude write me a one-page study plan for my exams and save it in Documents." (Claude helper)
- "Ask Claude to build a little Python script that renames my screenshots by date." (Claude helper)
- "Clean up my Downloads folder: put images, videos and PDFs into their own folders."
- "Close Chrome, it's eating my RAM." / "What's using the most memory?"
- "Compress the video on my desktop to under 50 megabytes." (she can install ffmpeg with winget)
- "Remember that my exam is on the 14th." / "Remind me to take the laundry out in 40 minutes."
- "Start study mode." (a routine from `config.yaml`) / "Switch to sleepy mode."
- "Lock my PC." / "Shut down in 30 minutes."

---

## Cost

- **Gemini:** pay-per-use on the key's billing account, covered first by your Pro plan's monthly Cloud credit once you've claimed it, or free with lower limits. *Flash Lite* is the cheapest; *Pro* models cost the most. AI Studio's dashboard shows your usage.
- **Claude helper:** no extra cost. It uses your Claude plan's normal usage limits.

---

## Make her yours (`config.yaml`)

- **Name and wake word:** `assistant.name` plus `assistant.wake_words`. Whisper spells names in odd ways, so list a few spellings.
- **Personality:** `hype`, `chill`, or `sleepy`. It changes her tone and voice speed, not what she's allowed to do.
- **Theme:** `glacier` (light) or `midnight` (dark), also switchable with the moon button in the Control Center. The looks live in `emi/web/island.html` and `emi/web/control.html` (plain HTML/CSS), so you can restyle everything there.
- **Voice:** any Edge voice. List them with `.venv\Scripts\edge-tts --list-voices`.
- **Offline voice (Kokoro):** run `.venv\Scripts\pip install -r requirements-offline-voice.txt`. Then put `kokoro-v1.0.onnx` and `voices-v1.0.bin` from the [kokoro-onnx model releases](https://github.com/thewh1teagle/kokoro-onnx/releases) into `models\kokoro\` and set `voice.engine: kokoro`.
- **German:** set `assistant.language: de`, `hearing.local_model: small`, `hearing.wake_model: base`, and `voice.edge_voice: de-DE-SeraphinaMultilingualNeural`.
- **Routines ("your usual"):** add your own under `routines:`.
- **Hotkeys while running:** under `hotkeys:`.

### Add your own tool
Create a function in any file in `emi/tools/` and Emi can use it right away:

```python
from . import tool

@tool("flip_coin", "Flip a coin.", {"times": {"type": "integer"}},
      confirm=False)            # or a function that returns a question to ask first
def flip_coin(ctx, a):
    import random
    return ", ".join(random.choice(["heads", "tails"]) for _ in range(int(a.get("times", 1))))
```

If you make a new file, import it at the top of `Registry.__init__` in `emi/tools/__init__.py`. To test tools without voice, run `run.bat --text`.

---

## Other brains

Set `brain.provider` in `config.yaml`:
- `gemini` (default): fast, with a model picker in the Control Center.
- `claude`: the Claude API, if you ever get API credit (`ANTHROPIC_API_KEY`). It's the best at long PC tasks.
- `local`: **nothing leaves your PC** for thinking. Install [Ollama](https://ollama.com/download), run `ollama pull qwen3:8b`, and set `provider: local`. Expect slower replies and clumsier multi-step tasks.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "I don't have an API key yet" | Paste the key into `.env` after `GEMINI_API_KEY=` (no spaces or quotes), then restart |
| "Usage limit" or "billing problem" | Free tier: wait a bit or pick *Flash Lite*. Paid: check billing and credits in Google AI Studio |
| "That model isn't available" | Pick another model on the Control Center's **Brain** page |
| "Claude Code isn't logged in" | Open a terminal, run `claude`, sign in, then type `/exit` |
| "Claude's usage limit is reached" | Your Claude plan's limit resets after a while; Emi keeps working with Gemini meanwhile |
| The summon shortcut does nothing | Run `install_shortcuts.bat` again. Check that no other app uses the same keys, and that the "Emi" shortcut is in the Start menu. The first press after boot can take a few seconds |
| She doesn't hear you | Run `check.bat` to see the mic level. Check Settings → Privacy & security → Microphone → *Let desktop apps access your microphone*. Lower `hearing.sensitivity` (try 0.7) |
| Noise sets her off | Raise `hearing.sensitivity` (try 1.5) |
| She misses her name | Add the spelling she heard (see `data\emi.log`) to `wake_words`, or set `wake_model: base.en` |
| The island or Control Center is blank | Install the [WebView2 runtime](https://developer.microsoft.com/microsoft-edge/webview2/). It's built into Windows 11 |
| No tray icon | Run `setup.bat` again (it installs the small `pystray` package). The Control Center also opens from the island's `⋯` button |
| Hotkeys don't work in some apps | Windows blocks them in admin apps unless Emi runs as administrator |
| Setup stops or packages fail | Open `data\setup.log` (or send it to Claude). Make sure Python 3.13 is installed, delete the `.venv` folder, and run `setup.bat` again |
| The .exe build fails | See `data\build.log`. Emi works the same with `run.bat` and the shortcut |
| Anything else | Look in `data\emi.log` |

---

## How it's built

```
main.py              starts everything (island, tray, ears, agent, hotkeys, reminders)
launch.pyw           what the summon shortcut runs: wakes the running Emi or starts her
install_shortcuts.*  summon shortcut, start with Windows, admin rights   (uninstall_shortcuts.* removes them)
config.yaml          your settings          .env  your API key (keep it private)
emi/agent.py         the agent loop: think → use tools → answer
emi/llm.py           Gemini (default), Claude API or a local model; model list for the picker
emi/listener.py      wake word + command listening       emi/audio.py  mic, voice detection, playback
emi/stt.py           Whisper speech-to-text              emi/tts.py    the voice
emi/ui.py            the island + Control Center windows emi/tray.py   the tray icon
emi/web/island.html  the dynamic island's look          emi/web/control.html  the Control Center's look
emi/ipc.py           lets the shortcut reach an already-running Emi
emi/proactive.py     proactive suggestions        emi/gaming.py   gaming mode
emi/winutil.py       mouse, foreground window, idle time (Windows)
emi/web/crop.html    the drag-a-box crop screen   build_exe.bat   builds Emi.exe
emi/tools/           everything Emi can do (apps, files, system, power, web, screen, memory…)
emi/tools/claude_code.py   the Claude helper (hands big jobs to Claude Code on your Claude plan)
install_claude_helper.bat  installs Claude Code and signs you in
data/                memories, notes, reminders, history, log
```

## Extra features

### Proactive mode (off by default)
Switch on **Proactive ideas** in the Control Center and Emi glances at your screen every 1, 2 or 5 minutes. She does this only when you've switched to a different window. If she has *one* useful idea, like explaining an error on screen or offering a reminder for a deadline she sees, it pops up on the island with **Do it** / **Not now**. Otherwise she stays silent.
- She skips the check while you're away, in incognito and in gaming mode, and stays quiet for 10 minutes after "Not now".
- The quick look uses the cheap `gemini-3.5-flash-lite` model (`proactive.model`).
- Each check sends a screenshot to Google, so only switch it on if you're fine with that.

### Hover to ask and Crop
- **Hover:** point at something and say *"Emi, what's this?"* She remembers where your mouse was when you started talking and looks right there; a red ring marks the spot for her.
- **Crop:** press `Ctrl + Alt + C`, or pick **Crop** in the typing box. Drag a box around anything, then ask about it by typing or speaking.

### Gaming mode (automatic)
When a game is in front (anything from Steam, Epic, Riot, Xbox or GOG, known games like Minecraft and Elden Ring, or anything Windows reports as a fullscreen game), Emi keeps the island away so it can never cover or minimise the game, and pauses proactive checks. She still hears her name and answers out loud. Add other games under `gaming.games` in `config.yaml`, or switch it off in the Control Center.

### Clicking in apps
Emi can now operate app windows: *"click the Send button"*, *"open the second video"*, *"scroll down in Spotify"*. She looks at the screen, finds the thing you described, clicks it, then checks the result.
- With **Ask before risky actions** on, clicks on things like Send, Delete, Buy, Install or Confirm ask you first.
- She never types passwords.

### Her own browser (website jobs)
For anything on a website that takes more than one step (*"go to Moodle, open each course's Download Center and download everything into my semester folder"*), Emi uses a browser window of her own instead of screenshots. She reads each page as text and clicks things by name (about a second per click instead of five), and files land straight in the folder she was told, with ZIPs unzipped there. There are no Save dialogs.
- It's Brave (or Edge) with a separate profile in `data\browser`. The first time a site asks for a password, sign in there yourself and say "continue". It stays signed in after that.
- The first use installs Playwright into Emi's `.venv` (about 30 s, once). Settings are under `browser:` in `config.yaml`.

### Big jobs and "continue"
One request can take up to 60 steps or 20 minutes (`brain.max_steps`, `brain.max_minutes`). If a job stops (the limit, Esc, or a sign-in she needs from you), say **"continue"** within 30 minutes. She picks up exactly where she stopped, with everything she'd already done in mind.

### Your own voice
Open the Control Center → **Voice** to switch voices instantly. You hear a sample right away.
- **Free voices** from Microsoft Edge (the default).
- **Gemini voices:** 30 expressive voices that follow her personality (hype sounds excited, sleepy sounds sleepy). They use your Gemini key.
- **Design my own voice:** describe it (*"a young, energetic woman with a light British accent who sounds like she's smiling"*) and Gemini creates a brand-new voice just for Emi.
- **ElevenLabs:** add `ELEVENLABS_API_KEY=...` to `.env` and your ElevenLabs voices appear in the list, including a clone of your own voice if your ElevenLabs plan allows it.
- **Kokoro (offline):** set a blend like `kokoro_voice: "af_heart:60,af_bella:40"` to mix two voices into a new one.

### One .exe
Double-click **`build_exe.bat`** after setup. It builds `dist\Emi\Emi.exe` (5–10 minutes; details in `data\build.log`).
- Move the `dist\Emi` folder wherever you like, then run `install_shortcuts.bat` inside it so your shortcut starts `Emi.exe`.
- Your settings, key and downloaded models are copied along.
- The app isn't code-signed, so SmartScreen may warn the first time: **More info → Run anyway**.
