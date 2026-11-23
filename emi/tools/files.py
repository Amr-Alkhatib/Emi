"""Find, read, write, move and delete files (deletes go to the Recycle Bin)."""
from __future__ import annotations

import fnmatch
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from ..config import ROOT
from . import IS_WINDOWS, ToolError, tool

KNOWN = {"desktop": "Desktop", "downloads": "Downloads", "documents": "Documents", "pictures": "Pictures",
         "music": "Music", "videos": "Videos", "home": ""}
SKIP_DIRS = {"appdata", "node_modules", ".git", "$recycle.bin", "windows", "program files",
             "program files (x86)", "programdata", ".venv", "venv", "__pycache__", ".cache"}
EXECUTABLE = {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".msi", ".scr", ".com", ".jar", ".reg", ".lnk"}


REG_NAMES = {"Desktop": "Desktop", "Documents": "Personal", "Pictures": "My Pictures", "Music": "My Music",
             "Videos": "My Video", "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}"}


def known_folder(name: str) -> Path:
    home = Path.home()
    sub = KNOWN.get(name.lower())
    if sub is None:
        raise KeyError(name)
    if not sub:
        return home
    if IS_WINDOWS:  # ask Windows where the folder really is (it may live inside OneDrive)
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                value, _ = winreg.QueryValueEx(k, REG_NAMES[sub])
                p = Path(os.path.expandvars(value))
                if p.exists():
                    return p
        except Exception:
            pass
    onedrive = home / "OneDrive" / sub
    return onedrive if onedrive.exists() and not (home / sub).exists() else home / sub


SECRET_FILES = {(ROOT / ".env").resolve()}


def resolve(p: str) -> Path:
    p = os.path.expandvars(os.path.expanduser(str(p).strip().strip('"')))
    path = Path(p)
    if not path.is_absolute():
        first, *rest = path.parts or ("",)
        try:
            path = known_folder(first).joinpath(*rest)
        except KeyError:
            path = Path.home() / path
    try:
        if path.resolve() in SECRET_FILES:
            raise ToolError("That file holds Emi's API key, so I keep my hands off it.")
    except OSError:
        pass
    return path


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


@tool("list_folder", "List what's inside a folder. Accepts full paths or names like 'Downloads', 'Desktop', 'Documents'.",
      {"path": {"type": "string"}, "sort": {"type": "string", "enum": ["name", "newest", "largest"]}},
      ["path"], label=lambda a: f"Looking in {a.get('path')}")
def list_folder(ctx, a):
    folder = resolve(a["path"])
    if not folder.is_dir():
        raise ToolError(f"Folder not found: {folder}")
    entries = []
    for e in folder.iterdir():
        try:
            st = e.stat()
            entries.append((e, st))
        except OSError:
            continue
    sort = a.get("sort", "name")
    if sort == "newest":
        entries.sort(key=lambda x: -x[1].st_mtime)
    elif sort == "largest":
        entries.sort(key=lambda x: -x[1].st_size)
    else:
        entries.sort(key=lambda x: (not x[0].is_dir(), x[0].name.lower()))
    lines = [f"{'[folder] ' if e.is_dir() else ''}{e.name}"
             f"{'' if e.is_dir() else '  ' + _human(st.st_size)}  {datetime.fromtimestamp(st.st_mtime):%Y-%m-%d}"
             for e, st in entries[:80]]
    more = f"\n…and {len(entries) - 80} more" if len(entries) > 80 else ""
    return f"{folder} ({len(entries)} items):\n" + "\n".join(lines) + more


@tool("search_files",
      "Search for files by name (wildcards ok, e.g. '*.pdf' or 'invoice'). Searches the user's home folder "
      "unless a folder is given.",
      {"name": {"type": "string"}, "folder": {"type": "string"}}, ["name"],
      label=lambda a: f"Searching for {a.get('name')}")
def search_files(ctx, a):
    pattern = str(a["name"]).lower()
    if not any(c in pattern for c in "*?["):
        pattern = f"*{pattern}*"
    root = resolve(a.get("folder") or "home")
    found, start = [], time.time()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")]
        for f in filenames + dirnames:
            if fnmatch.fnmatch(f.lower(), pattern):
                found.append(os.path.join(dirpath, f))
                if len(found) >= 40:
                    break
        if len(found) >= 40 or time.time() - start > 12:
            break
    if not found:
        return f"Nothing matching '{a['name']}' in {root}."
    return "Found:\n" + "\n".join(found)


def extract_text(path: Path, limit: int = 15000) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        parts, total = [], 0
        for i, page in enumerate(reader.pages):
            t = page.extract_text() or ""
            parts.append(f"--- page {i + 1} ---\n{t}")
            total += len(t.strip())
            if total > limit:
                break
        text = "\n".join(parts)
        if total == 0:
            return "(This PDF has no text layer — it's probably scanned images.)"
    elif ext == ".docx":
        import docx
        d = docx.Document(str(path))
        text = "\n".join(p.text for p in d.paragraphs)
        for table in d.tables:
            for row in table.rows:
                text += "\n" + " | ".join(c.text for c in row.cells)
    elif ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        lines = []
        for ws in wb.worksheets[:5]:
            lines.append(f"--- sheet: {ws.title} ---")
            for row in ws.iter_rows(values_only=True):
                if any(v is not None for v in row):
                    lines.append("\t".join("" if v is None else str(v) for v in row))
                if len(lines) > 400:
                    break
        text = "\n".join(lines)
    else:
        raw = path.read_bytes()[: limit * 4]
        if b"\x00" in raw[:4000]:
            return f"(This is a binary file — {_human(path.stat().st_size)}, can't read it as text.)"
        text = raw.decode("utf-8", errors="replace")
    if len(text) > limit:
        text = text[:limit] + "\n…(cut off — file is longer)"
    return text


@tool("read_file", "Read a file's contents so you can answer questions about it. Supports PDF, Word (.docx), "
      "Excel (.xlsx), and any text/code/CSV file.",
      {"path": {"type": "string"}}, ["path"], label=lambda a: f"Reading {Path(str(a.get('path'))).name}")
def read_file(ctx, a):
    path = resolve(a["path"])
    if not path.is_file():
        raise ToolError(f"File not found: {path}")
    return f"{path}:\n{extract_text(path)}"


def _confirm_write(a):
    path = resolve(a.get("path", ""))
    mode = a.get("mode", "create")
    if path.exists() and mode == "overwrite":
        return f"Overwrite the existing file?\n{path}"
    return None


@tool("write_file", "Create a text file (notes, code, lists...). mode: create (default, fails if it exists), "
      "overwrite, or append.",
      {"path": {"type": "string"}, "content": {"type": "string"},
       "mode": {"type": "string", "enum": ["create", "overwrite", "append"]}},
      ["path", "content"], confirm=_confirm_write, label=lambda a: f"Writing {Path(str(a.get('path'))).name}")
def write_file(ctx, a):
    path = resolve(a["path"])
    mode = a.get("mode", "create")
    if path.exists() and mode == "create":
        raise ToolError(f"{path} already exists. Use mode 'append' or 'overwrite'.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a" if mode == "append" else "w", encoding="utf-8") as f:
        f.write(str(a["content"]))
    return f"Saved {path}"


@tool("move_file", "Move or rename a file or folder.",
      {"source": {"type": "string"}, "destination": {"type": "string"}}, ["source", "destination"],
      confirm=lambda a: f"Move\n{resolve(a.get('source', ''))}\n→ {resolve(a.get('destination', ''))}?",
      label="Moving files")
def move_file(ctx, a):
    src, dst = resolve(a["source"]), resolve(a["destination"])
    if not src.exists():
        raise ToolError(f"Not found: {src}")
    if dst.is_dir():
        dst = dst / src.name
    if dst.exists():
        raise ToolError(f"Something already exists at {dst}.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return f"Moved to {dst}"


@tool("delete_file", "Delete a file or folder by sending it to the Recycle Bin (recoverable).",
      {"path": {"type": "string"}}, ["path"],
      confirm=lambda a: f"Send this to the Recycle Bin?\n{resolve(a.get('path', ''))}",
      label="Deleting")
def delete_file(ctx, a):
    path = resolve(a["path"])
    if not path.exists():
        raise ToolError(f"Not found: {path}")
    if path == Path.home() or len(path.parts) <= 2:
        raise ToolError("That's a top-level folder — I won't delete it.")
    from send2trash import send2trash
    send2trash(str(path))
    return f"Sent {path.name} to the Recycle Bin."


@tool("open_path", "Open a file or folder with its default app (e.g. open a PDF, a photo, or the Downloads folder).",
      {"path": {"type": "string"}}, ["path"],
      confirm=lambda a: (f"Run this program?\n{resolve(a.get('path', ''))}"
                         if resolve(a.get("path", "")).suffix.lower() in EXECUTABLE else None),
      label=lambda a: f"Opening {Path(str(a.get('path'))).name}")
def open_path(ctx, a):
    path = resolve(a["path"])
    if not path.exists():
        raise ToolError(f"Not found: {path}")
    if not IS_WINDOWS:
        raise ToolError("This only works on Windows.")
    os.startfile(str(path))
    return f"Opened {path}"
