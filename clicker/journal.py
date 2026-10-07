"""Append-only text log of every prompt the app agreed to, for later review."""
from datetime import datetime
import threading
from .settings import settings_path


def journal_path():
    return settings_path().parent / "approvals.log"


class Journal:
    def __init__(self, path=None):
        self.path = path or journal_path()
        self.lock = threading.Lock()

    def record(self, console, rule, text, dry_run=False):
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        action = "WOULD APPROVE (test mode)" if dry_run else "APPROVED"
        screen = "\n".join("    " + line for line in (text or "").splitlines() if line.strip())
        entry = f"{stamp}  {action}  [{console}]  {rule}\n{screen}\n\n"
        # Several console watchers share one file.
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as file:
                file.write(entry)
