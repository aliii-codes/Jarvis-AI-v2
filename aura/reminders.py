"""Reminder storage. The agent adds reminders via tools; the UI polls `due()` and fires them."""
import sqlite3
from contextlib import closing
from datetime import datetime

from . import config

DB = config.DATA_DIR / "reminders.sqlite"


def _conn() -> sqlite3.Connection:
    # One short-lived connection per call: used from both the agent worker thread and the UI thread.
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY, message TEXT NOT NULL, due_at TEXT NOT NULL, fired INTEGER DEFAULT 0)""")
    return conn


def add(message: str, due_at: datetime) -> int:
    with closing(_conn()) as c, c:
        return c.execute("INSERT INTO reminders (message, due_at) VALUES (?, ?)",
                         (message, due_at.isoformat(timespec="seconds"))).lastrowid


def pending() -> list[tuple[int, str, datetime]]:
    with closing(_conn()) as c:
        rows = c.execute("SELECT id, message, due_at FROM reminders WHERE fired = 0 ORDER BY due_at").fetchall()
    return [(i, m, datetime.fromisoformat(d)) for i, m, d in rows]


def cancel(reminder_id: int) -> bool:
    with closing(_conn()) as c, c:
        return c.execute("DELETE FROM reminders WHERE id = ? AND fired = 0", (reminder_id,)).rowcount > 0


def due() -> list[tuple[int, str, datetime]]:
    """Unfired reminders whose time has come; marks them fired."""
    now = datetime.now()
    ready = [r for r in pending() if r[2] <= now]
    if ready:
        with closing(_conn()) as c, c:
            c.executemany("UPDATE reminders SET fired = 1 WHERE id = ?", [(r[0],) for r in ready])
    return ready
