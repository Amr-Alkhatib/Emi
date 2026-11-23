"""new_document: make a Word / Excel / text document with the content already in it, then open it.

Much faster than opening the app, clicking "Blank document" and typing: one step, no screen reading, no
keyboard typing. Files go to Documents\\Emi (an existing name gets " (2)", " (3)"… instead of being replaced).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import ToolError, tool


def _folder() -> Path:
    try:
        from .files import known_folder
        base = known_folder("documents")
    except Exception:
        base = Path.home() / "Documents"
    folder = base / "Emi"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _free_name(folder: Path, title: str, ext: str) -> Path:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip(" .")[:80] or datetime.now().strftime("Note %Y-%m-%d %H%M")
    path = folder / f"{stem}{ext}"
    n = 2
    while path.exists():
        path = folder / f"{stem} ({n}){ext}"
        n += 1
    return path


def _open(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # opens in Word / Excel / Notepad, whatever is set for that file type


def _word(path: Path, title: str, text: str) -> None:
    from docx import Document
    doc = Document()
    lines = text.replace("\r\n", "\n").split("\n")
    if title and not (lines and lines[0].lstrip("# ").strip().lower() == title.lower()):
        doc.add_heading(title, level=0)
    para: list[str] = []

    def flush():
        if para:
            doc.add_paragraph(" ".join(para))
            para.clear()
    for raw in lines:
        line = raw.rstrip()
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            flush()
            doc.add_heading(m.group(2).strip(), level=len(m.group(1)))
        elif re.match(r"^\s*[-*•]\s+", line):
            flush()
            doc.add_paragraph(re.sub(r"^\s*[-*•]\s+", "", line).replace("**", ""), style="List Bullet")
        elif re.match(r"^\s*\d+[.)]\s+", line):
            flush()
            doc.add_paragraph(re.sub(r"^\s*\d+[.)]\s+", "", line).replace("**", ""), style="List Number")
        elif not line.strip():
            flush()
        else:
            para.append(line.strip().replace("**", ""))
    flush()
    doc.save(str(path))


def _excel(path: Path, title: str, text: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = (title or "Sheet1")[:31]
    rows = [r for r in text.replace("\r\n", "\n").split("\n") if r.strip()]
    sep = "\t" if any("\t" in r for r in rows) else ("|" if any("|" in r for r in rows) else ",")
    for r in rows:
        if sep == "|" and set(r.replace("|", "").strip()) <= set("-: "):
            continue  # markdown table divider
        cells = [c.strip() for c in r.strip().strip("|").split(sep)]
        ws.append([_number(c) for c in cells])
    if rows:
        for c in ws[1]:
            c.font = Font(bold=True)
    wb.save(str(path))


def _number(cell: str):
    try:
        return int(cell) if re.fullmatch(r"-?\d+", cell) else float(cell) if re.fullmatch(r"-?\d+\.\d+", cell) else cell
    except ValueError:
        return cell


@tool("new_document",
      "Create a NEW document with content and open it — the fast way to write anything in Word, Excel or a text "
      "file (one step, no clicking or typing). app: word (essays, letters, notes; use # headings and - bullets), "
      "excel (tables: one row per line, cells separated by commas or |), text (Notepad). With empty text it just "
      "opens a blank document.",
      {"app": {"type": "string", "enum": ["word", "excel", "text"]},
       "title": {"type": "string", "description": "Short title, also used as the file name"},
       "text": {"type": "string", "description": "The full content"}},
      ["app"], label=lambda a: f"Writing it in {str(a.get('app', 'word')).capitalize()}")
def new_document(ctx, a):
    app = str(a.get("app") or "word").lower()
    title = str(a.get("title") or "").strip()
    text = str(a.get("text") or "")
    if app == "word" and not text.strip() and sys.platform == "win32":
        try:  # a blank, unsaved document straight away (skips Word's start screen)
            subprocess.Popen(["cmd", "/c", "start", "", "winword", "/w"], creationflags=0x08000000)
            return "Opened a blank Word document."
        except Exception:
            pass
    folder = _folder()
    try:
        if app == "word":
            path = _free_name(folder, title or "Document", ".docx")
            _word(path, title, text)
        elif app == "excel":
            path = _free_name(folder, title or "Sheet", ".xlsx")
            _excel(path, title, text)
        else:
            path = _free_name(folder, title or "Note", ".txt")
            path.write_text(text, encoding="utf-8")
    except ImportError as e:
        raise ToolError(f"A package is missing ({e}). Run setup.bat again.")
    _open(path)
    return f"Created and opened {path.name} (in {path.parent})."
