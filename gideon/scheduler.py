from __future__ import annotations

import threading
from datetime import datetime

from dateutil.relativedelta import relativedelta

from .db import Database
from .integrations.system import notify


class Scheduler:
    def __init__(self, db: Database):
        self.db = db
        self.stop_event = threading.Event()
        self.timers: dict[str, threading.Timer] = {}

    def start_timer(self, seconds: int, label: str = "Timer") -> str:
        import uuid

        timer_id = uuid.uuid4().hex[:8]
        timer = threading.Timer(seconds, notify, args=("Gideon timer", f"{label} finished."))
        timer.daemon = True
        self.timers[timer_id] = timer
        timer.start()
        return timer_id

    def cancel_timers(self) -> int:
        count = len(self.timers)
        for timer in self.timers.values():
            timer.cancel()
        self.timers.clear()
        return count

    def run(self) -> None:
        while not self.stop_event.wait(15):
            for reminder in self.db.due_reminders():
                notify("Gideon reminder", reminder["text"])
                recurrence = reminder.get("recurrence")
                if recurrence:
                    due = datetime.fromisoformat(reminder["due_at"])
                    delta = {
                        "daily": relativedelta(days=1),
                        "weekly": relativedelta(weeks=1),
                        "monthly": relativedelta(months=1),
                    }.get(recurrence)
                    if delta:
                        self.db.update_reminder(reminder["id"], due_at=(due + delta).isoformat())
                else:
                    self.db.update_reminder(reminder["id"], state="fired")

    def stop(self) -> None:
        self.stop_event.set()
        self.cancel_timers()
