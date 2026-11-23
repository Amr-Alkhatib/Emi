"""Everything Emi remembers lives as plain files in the data/ folder on your PC.

data/memory.json      facts you asked Emi to remember
data/reminders.json   reminders and timers
data/notes/*.md       notes
data/history.jsonl    chat log (not written in incognito)
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Storage:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.notes_dir = self.dir / "notes"
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ── helpers ──────────────────────────────────────────────
    def _load(self, name: str) -> list:
        p = self.dir / name
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            # keep a copy of a broken file instead of silently losing it
            p.rename(p.with_suffix(f".broken-{datetime.now():%Y%m%d%H%M%S}.json"))
            return []

    def _save(self, name: str, items: list) -> None:
        p = self.dir / name
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    @staticmethod
    def _next_id(items: list, prefix: str) -> str:
        nums = [int(i["id"][1:]) for i in items if str(i.get("id", ""))[1:].isdigit()]
        return f"{prefix}{max(nums, default=0) + 1}"

    # ── memory ───────────────────────────────────────────────
    def memories(self) -> list[dict]:
        with self._lock:
            return self._load("memory.json")

    def add_memory(self, text: str) -> dict:
        with self._lock:
            items = self._load("memory.json")
            for m in items:  # don't store exact duplicates
                if m["text"].strip().lower() == text.strip().lower():
                    return m
            item = {"id": self._next_id(items, "m"), "text": text.strip(), "created": _now_iso()}
            items.append(item)
            self._save("memory.json", items)
            return item

    def remove_memory(self, key: str) -> dict | None:
        with self._lock:
            items = self._load("memory.json")
            key_l = key.strip().lower()
            for i, m in enumerate(items):
                if m["id"].lower() == key_l or key_l in m["text"].lower():
                    removed = items.pop(i)
                    self._save("memory.json", items)
                    return removed
            return None

    def search_memories(self, query: str) -> list[dict]:
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
        hits = []
        for m in self.memories():
            text = m["text"].lower()
            score = sum(1 for w in words if w in text)
            if score or not words:
                hits.append((score, m))
        return [m for _, m in sorted(hits, key=lambda x: -x[0])]

    # ── reminders ────────────────────────────────────────────
    def reminders(self, include_done: bool = False) -> list[dict]:
        with self._lock:
            items = self._load("reminders.json")
        if not include_done:
            items = [r for r in items if not r.get("done")]
        return sorted(items, key=lambda r: r["due"])

    def add_reminder(self, text: str, due: datetime) -> dict:
        with self._lock:
            items = self._load("reminders.json")
            item = {"id": self._next_id(items, "r"), "text": text.strip(),
                    "due": due.isoformat(timespec="seconds"), "done": False, "fired": False,
                    "created": _now_iso()}
            items.append(item)
            self._save("reminders.json", items)
            return item

    def update_reminder(self, rid: str, **changes) -> dict | None:
        with self._lock:
            items = self._load("reminders.json")
            for r in items:
                if r["id"].lower() == rid.strip().lower():
                    r.update(changes)
                    self._save("reminders.json", items)
                    return r
            return None

    def due_reminders(self, now: datetime) -> list[dict]:
        out = []
        for r in self.reminders():
            try:
                if not r.get("fired") and datetime.fromisoformat(r["due"]) <= now:
                    out.append(r)
            except ValueError:
                continue
        return out

    # ── notes ────────────────────────────────────────────────
    def save_note(self, title: str, content: str) -> Path:
        slug = re.sub(r"[^\w\- ]", "", title).strip().replace(" ", "-").lower()[:60] or "note"
        path = self.notes_dir / f"{slug}.md"
        with self._lock:
            if path.exists():
                with open(path, "a", encoding="utf-8") as f:
                    f.write(f"\n\n_{_now_iso()}_\n\n{content.strip()}\n")
            else:
                path.write_text(f"# {title.strip()}\n\n_{_now_iso()}_\n\n{content.strip()}\n", encoding="utf-8")
        return path

    def search_notes(self, query: str) -> list[str]:
        q = query.strip().lower()
        results = []
        for p in sorted(self.notes_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
            text = p.read_text(encoding="utf-8", errors="replace")
            if not q or q in text.lower() or q in p.stem:
                snippet = " ".join(text.split())[:300]
                results.append(f"[{p.stem}] {snippet}")
        return results

    # ── history ──────────────────────────────────────────────
    def append_history(self, role: str, text: str) -> None:
        with self._lock, open(self.dir / "history.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": _now_iso(), "role": role, "text": text}, ensure_ascii=False) + "\n")
