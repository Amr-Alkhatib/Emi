"""Fires reminders when they're due."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

log = logging.getLogger("emi.scheduler")


class ReminderScheduler(threading.Thread):
    def __init__(self, storage, on_fire, interval: float = 10):
        super().__init__(daemon=True, name="reminders")
        self.storage, self.on_fire, self.interval = storage, on_fire, interval

    def run(self):
        while True:
            try:
                for r in self.storage.due_reminders(datetime.now()):
                    self.storage.update_reminder(r["id"], fired=True, done=True)
                    self.on_fire(r)
            except Exception:
                log.exception("reminder check failed")
            time.sleep(self.interval)
