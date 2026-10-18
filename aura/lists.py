"""Tasks (with optional due dates, linked to reminders) and quick notes.

Kept in the same LangGraph SqliteStore as long-term memory, under their own namespaces.
"""
import uuid
from datetime import date, datetime, timedelta

from . import reminders
from .memory import _all, _db, _lock, _norm, _words

TASKS, NOTES = ("tasks",), ("notes",)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_due(text: str) -> str | None:
    """'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' (also accepts 'T') -> normalized string, or None."""
    text = (text or "").strip().replace("T", " ")
    if not text:
        return None
    for fmt, out in (("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"), ("%Y-%m-%d", "%Y-%m-%d")):
        try:
            return datetime.strptime(text, fmt).strftime(out)
        except ValueError:
            pass
    raise ValueError(f"Due date must be 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM', got {text!r}")


def due_label(due: str | None) -> str:
    if not due:
        return ""
    d = datetime.fromisoformat(due)
    days = (d.date() - date.today()).days
    day = {0: "today", 1: "tomorrow", -1: "yesterday"}.get(days, d.strftime("%a %d %b"))
    return f"{day} {d:%H:%M}" if "T" in due else day


def _is_overdue(task: dict) -> bool:
    if task["done"] or not task.get("due"):
        return False
    due = datetime.fromisoformat(task["due"])
    return due < datetime.now() if "T" in task["due"] else due.date() < date.today()


# ── tasks ────────────────────────────────────────────────────────────────
def tasks(include_done: bool = False) -> list[dict]:
    """Open tasks first (by due date, undated last), then recently completed ones."""
    with _lock:
        rows = [{"id": i.key, **i.value} for i in _all(TASKS)]
    for t in rows:
        t["overdue"] = _is_overdue(t)
        t["due_label"] = due_label(t.get("due"))
    open_ = sorted((t for t in rows if not t["done"]), key=lambda t: (t.get("due") or "9999", t["created"]))
    if not include_done:
        return open_
    done = sorted((t for t in rows if t["done"]), key=lambda t: t.get("done_at", ""), reverse=True)
    return open_ + done[:20]


_FILLER = {"my", "the", "a", "an", "to", "of", "for", "and", "on", "in", "at", "i", "need", "have"}


def _task_words(text: str) -> set[str]:
    # Unlike memory search, keep short words: "OS" vs "DB" assignment are different tasks.
    return {w for w in _norm(text).split() if w not in _FILLER}


def _same_task(a: str, b: str) -> bool:
    wa, wb = _task_words(a), _task_words(b)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.75


def add_task(text: str, due: str = "") -> dict:
    """Add a task, or update the matching open task if it's already on the list.
    (The model sometimes issues the same add several times in parallel; this keeps one task, one reminder.)"""
    text = " ".join(text.split())
    if not text:
        raise ValueError("Task text is empty.")
    due_norm = parse_due(due)
    with _lock:  # parallel tool calls run on separate threads; make check-then-insert atomic
        existing = next((t for t in tasks() if _same_task(t["text"], text)), None)
        if existing:
            if due_norm and due_norm != existing.get("due"):
                existing = edit_task(existing["id"], due=due_norm)
            return {**existing, "existing": True}
        reminder_id = None
        if due_norm and "T" in due_norm and datetime.fromisoformat(due_norm) > datetime.now():
            reminder_id = reminders.add(f"Task: {text}", datetime.fromisoformat(due_norm))
        task = {"text": text, "due": due_norm, "done": False, "created": _now(), "reminder_id": reminder_id}
        key = uuid.uuid4().hex[:6]
        _db().put(TASKS, key, task)
    return {"id": key, **task, "existing": False}


def _get_task(key: str) -> dict | None:
    with _lock:
        item = _db().get(TASKS, key)
    return {"id": item.key, **item.value} if item else None


def _save_task(task: dict) -> None:
    with _lock:
        _db().put(TASKS, task["id"], {k: v for k, v in task.items() if k not in ("id", "overdue", "due_label")})


def set_done(key: str, done: bool = True) -> dict | None:
    task = _get_task(key)
    if not task:
        return None
    task["done"], task["done_at"] = done, (_now() if done else None)
    if done and task.get("reminder_id"):
        reminders.cancel(task["reminder_id"])
        task["reminder_id"] = None
    _save_task(task)
    return task


def edit_task(key: str, text: str | None = None, due: str | None = None) -> dict | None:
    task = _get_task(key)
    if not task:
        return None
    if text is not None and text.strip():
        task["text"] = " ".join(text.split())
    if due is not None:
        if task.get("reminder_id"):
            reminders.cancel(task["reminder_id"])
            task["reminder_id"] = None
        task["due"] = parse_due(due)
        if task["due"] and "T" in task["due"] and datetime.fromisoformat(task["due"]) > datetime.now():
            task["reminder_id"] = reminders.add(f"Task: {task['text']}", datetime.fromisoformat(task["due"]))
    _save_task(task)
    return task


def delete_task(key: str) -> dict | None:
    task = _get_task(key)
    if not task:
        return None
    if task.get("reminder_id"):
        reminders.cancel(task["reminder_id"])
    with _lock:
        _db().delete(TASKS, key)
    return task


def find_task(query: str, include_done: bool = False) -> dict | None:
    """Match by id ('#a1b2c3' or 'a1b2c3') or by the words of the task."""
    q = query.strip().lstrip("#")
    candidates = tasks(include_done=include_done)
    for t in candidates:
        if t["id"] == q:
            return t
    want = _task_words(query)
    scored = sorted(((len(want & _task_words(t["text"])), t) for t in candidates), key=lambda s: -s[0])
    return scored[0][1] if scored and scored[0][0] else None


def attention() -> list[dict]:
    """Open tasks that are overdue or due today: shown in the prompt and as the header badge."""
    today = date.today().isoformat()
    return [t for t in tasks() if t["overdue"] or (t.get("due") or "").startswith(today)]


# ── notes ────────────────────────────────────────────────────────────────
def notes() -> list[dict]:
    """Newest first."""
    with _lock:
        rows = [{"id": i.key, **i.value} for i in _all(NOTES)]
    return sorted(rows, key=lambda n: n["created"], reverse=True)


def add_note(text: str) -> dict:
    text = text.strip()
    if not text:
        raise ValueError("Note is empty.")
    note = {"text": text, "created": _now(), "updated": _now()}
    key = uuid.uuid4().hex[:6]
    with _lock:
        _db().put(NOTES, key, note)
    return {"id": key, **note}


def edit_note(key: str, text: str) -> bool:
    with _lock:
        item = _db().get(NOTES, key)
        if not item or not text.strip():
            return False
        _db().put(NOTES, key, {**item.value, "text": text.strip(), "updated": _now()})
        return True


def delete_note(key: str) -> bool:
    with _lock:
        if not _db().get(NOTES, key):
            return False
        _db().delete(NOTES, key)
        return True


def search_notes(query: str, limit: int = 8) -> list[dict]:
    want = _words(query)
    if not want:
        return notes()[:limit]
    scored = [(len(want & _words(n["text"])), n) for n in notes()]
    return [n for score, n in sorted(scored, key=lambda s: -s[0]) if score][:limit]


def snapshot() -> dict:
    return {"tasks": tasks(include_done=True), "notes": notes(), "attention": len(attention())}
