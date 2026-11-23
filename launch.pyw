"""The summon shortcut runs this. If Emi is running, she starts listening; if not, she starts up
(and listens as soon as she's ready). The .pyw extension means no console window flashes."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from emi.ipc import send  # noqa: E402  (standard library only → fast)

command = sys.argv[1] if len(sys.argv) > 1 else "summon"
if not send(command):
    if (ROOT / "data" / "admin_task").exists():  # set up by install_shortcuts.bat → run as administrator
        subprocess.Popen(["schtasks", "/run", "/tn", "Emi"], creationflags=0x08000000)
    else:
        pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
        exe = str(pythonw) if pythonw.exists() else sys.executable
        flags = (0x00000008 | 0x00000200) if os.name == "nt" else 0  # detached, own process group
        subprocess.Popen([exe, str(ROOT / "main.py"), f"--{command}"], cwd=str(ROOT), creationflags=flags)
