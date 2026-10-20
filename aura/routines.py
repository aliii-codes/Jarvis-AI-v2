"""Routines: things that repeat every week ("gym at 16:30 every day except Friday", "school 7:30-13:30 Mon-Fri").

Unlike tasks they never pile up as overdue. Each day AURA reminds the user shortly before one starts and,
once it's over, asks how it went; the answer is logged per date (done / skipped / missed).
Kept in the same SqliteStore as memory and tasks, under their own namespace.
"""
import re
import uuid
from datetime import date, datetime, timedelta

from . import config
from .lists import _now, _same_task, _task_words
from .memory import _all, _db, _lock

ROUTINES = ("routines",)
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ASK_AFTER = timedelta(minutes=15)       # ask how it went this long after it ends
DEFAULT_LENGTH = timedelta(hours=1)     # "ends" this long after the start when no end time is given
LATEST_ASK_HOUR = 23
STATUSES = ("done", "skipped", "missed")

_DAY_WORDS = {name.lower(): i for i, name in enumerate(DAY_NAMES)}
_DAY_WORDS.update({full: i for i, full in enumerate(
    ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])})
_DAY_WORDS.update({"tues": 1, "wednes": 2, "thur": 3, "thurs": 3})


def _day(word: str) -> int:
    word = word.strip().lower()
    if word not in _DAY_WORDS and word.endswith("s"):  # "fridays"
        word = word[:-1]
    if word not in _DAY_WORDS:
        raise ValueError(f"Unknown day {word!r}. Use names like 'mon, wed, fri' or 'mon-fri'.")
    return _DAY_WORDS[word]


def parse_days(text: str) -> list[int]:
    """'mon-fri', 'mon, wed, fri', 'daily', 'weekdays', 'weekends', 'every day except friday' -> [0..6] (Mon=0)."""
    text = " ".join((text or "").lower().replace("&", ",").replace(" and ", ",").split())
    if not text:
        raise ValueError("Say which days, e.g. 'mon-fri' or 'every day except fri'.")
    m = re.search(r"\b(?:except|but not|but|not)\b", text)
    base, excluded = (text[:m.start()], text[m.end():]) if m else (text, "")
    days: set[int] = set()
    for part in filter(None, (p.strip() for p in re.split(r"[,/;]", base))):
        part = re.sub(r"^(every|each|on)\s+", "", part)
        if part in ("daily", "day", "every day", "everyday", "all week", "all days", "week", "the week", "all"):
            days |= set(range(7))
        elif part in ("weekdays", "weekday"):
            days |= set(range(5))
        elif part in ("weekends", "weekend"):
            days |= {5, 6}
        elif m := re.fullmatch(r"(\w+)\s*(?:-|to|through|till|until)\s*(\w+)", part):
            start, end = _day(m.group(1)), _day(m.group(2))
            days |= {(start + i) % 7 for i in range((end - start) % 7 + 1)}
        else:
            days |= {_day(w) for w in part.split()}
    if excluded.strip():
        days -= set(parse_days(excluded))
    if not days:
        raise ValueError("That leaves no days.")
    return sorted(days)


def parse_time(text: str) -> str:
    """'16:30', '4:30pm', '7:30 am', '13' -> 'HH:MM'."""
    t = (text or "").strip().lower().replace(".", ":").replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", t)
    if not m:
        raise ValueError(f"Time must look like '16:30' or '4:30pm', got {text!r}.")
    hour, minute, half = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if half == "pm" and hour < 12:
        hour += 12
    elif half == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        raise ValueError(f"{text!r} isn't a valid time.")
    return f"{hour:02d}:{minute:02d}"


def days_label(days: list[int]) -> str:
    days = sorted(days)
    if days == list(range(7)):
        return "every day"
    if days == list(range(5)):
        return "Mon–Fri"
    if days == [5, 6]:
        return "weekends"
    if len(days) == 6:
        return f"every day except {DAY_NAMES[next(d for d in range(7) if d not in days)]}"
    if len(days) >= 3 and days == list(range(days[0], days[-1] + 1)):
        return f"{DAY_NAMES[days[0]]}–{DAY_NAMES[days[-1]]}"
    return ", ".join(DAY_NAMES[d] for d in days)


def time_label(r: dict) -> str:
    return f"{r['start']}–{r['end']}" if r.get("end") else r["start"]


def _at(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time())


def _ends(r: dict, day: date) -> datetime:
    start = _at(day, r["start"])
    if r.get("end"):
        end = _at(day, r["end"])
        return end if end > start else end + timedelta(days=1)
    return start + DEFAULT_LENGTH


# ── storage ──────────────────────────────────────────────────────────────
def routines() -> list[dict]:
    """All routines, by start time."""
    with _lock:
        rows = [{"id": i.key, **i.value} for i in _all(ROUTINES)]
    return sorted(rows, key=lambda r: (r["start"], r["text"]))


def _get(key: str) -> dict | None:
    with _lock:
        item = _db().get(ROUTINES, key)
    return {"id": item.key, **item.value} if item else None


def _save(r: dict) -> None:
    with _lock:
        _db().put(ROUTINES, r["id"], {k: v for k, v in r.items() if k != "id"})


def add(text: str, days: str, start: str, end: str = "") -> dict:
    """Add a routine, or update the one with the same name (so "gym is at 5 now" doesn't make a second gym)."""
    text = " ".join(text.split())
    if not text:
        raise ValueError("Routine name is empty.")
    fields = {"text": text, "days": parse_days(days), "start": parse_time(start),
              "end": parse_time(end) if end.strip() else None}
    with _lock:
        existing = next((r for r in routines() if _same_task(r["text"], text)), None)
        if existing:
            _save({**existing, **fields})
            return {**existing, **fields, "existing": True}
        r = {"id": uuid.uuid4().hex[:6], **fields, "created": _now(), "log": {}, "reminded": None, "asked": None}
        _save(r)
    return {**r, "existing": False}


def find(query: str) -> dict | None:
    """Match by id or by the words of the routine ("gym", "going to the gym")."""
    q = query.strip().lstrip("#")
    candidates = routines()
    for r in candidates:
        if r["id"] == q:
            return r
    want = _task_words(query)
    scored = sorted(((len(want & _task_words(r["text"])), r) for r in candidates), key=lambda s: -s[0])
    return scored[0][1] if scored and scored[0][0] else None


def delete(key: str) -> dict | None:
    r = _get(key)
    if r:
        with _lock:
            _db().delete(ROUTINES, key)
    return r


def set_status(key: str, status: str | None, day: date | None = None) -> dict | None:
    """Log how a day went: done / skipped / missed (None clears it). Skipping ahead of time also
    silences that day's reminder and question."""
    if status is not None and status not in STATUSES:
        raise ValueError(f"Status must be one of {', '.join(STATUSES)}.")
    r = _get(key)
    if not r:
        return None
    day_key = (day or date.today()).isoformat()
    log = dict(r.get("log") or {})
    if status:
        log[day_key] = status
    else:
        log.pop(day_key, None)
    # Keep about three months of history: enough for streaks, small enough to stay fast.
    r["log"] = dict(sorted(log.items())[-100:])
    _save(r)
    return r


def streak(r: dict, today: date | None = None) -> int:
    """Scheduled days in a row it was done, counting back from the latest one with an answer.
    Skipped days don't break it; missed ones do; days nobody asked about are ignored."""
    today, log, count = today or date.today(), r.get("log") or {}, 0
    for i in range(120):
        day = today - timedelta(days=i)
        status = log.get(day.isoformat())
        if day.weekday() not in r["days"] or status in (None, "skipped"):
            continue
        if status != "done":
            break
        count += 1
    return count


# ── today ────────────────────────────────────────────────────────────────
def today(now: datetime | None = None) -> list[dict]:
    """Today's routines with their status: done / skipped / missed, or upcoming / now / over."""
    now = now or datetime.now()
    out = []
    for r in routines():
        if now.weekday() not in r["days"]:
            continue
        status = (r.get("log") or {}).get(now.date().isoformat())
        if not status:
            status = ("upcoming" if now < _at(now.date(), r["start"])
                      else "now" if now < _ends(r, now.date()) else "over")
        out.append({**r, "status": status, "time_label": time_label(r), "streak": streak(r, now.date())})
    return out


def due_reminders(now: datetime | None = None) -> list[dict]:
    """Routines starting within the reminder lead time that haven't been reminded about today; marks them.
    The UI polls this; a reminder whose start has already passed (AURA was closed) is dropped, not fired late."""
    now, lead = now or datetime.now(), timedelta(minutes=config.ROUTINE_REMINDER)
    if not lead:
        return []
    ready = []
    with _lock:
        for r in today(now):
            start = _at(now.date(), r["start"])
            if (r["status"] == "upcoming" and start - lead <= now
                    and r.get("reminded") != now.date().isoformat()):
                _save({k: v for k, v in r.items() if k not in ("status", "time_label", "streak")}
                      | {"reminded": now.date().isoformat()})
                ready.append(r)
    return ready


def reminder_text(r: dict, now: datetime | None = None) -> str:
    now = now or datetime.now()
    minutes = max(1, round((_at(now.date(), r["start"]) - now).total_seconds() / 60))
    return f"{r['text']} in {minutes} min ({time_label(r)})"


def to_ask_about(now: datetime | None = None) -> list[dict]:
    """Today's routines that finished a little while ago with no answer yet, not asked about today; marks them.
    Only when follow-ups are on, and not late at night."""
    now = now or datetime.now()
    if not config.FOLLOWUPS or now.hour >= LATEST_ASK_HOUR:
        return []
    ready = []
    with _lock:
        for r in today(now):
            if (r["status"] == "over" and now >= _ends(r, now.date()) + ASK_AFTER
                    and r.get("asked") != now.date().isoformat()):
                _save({k: v for k, v in r.items() if k not in ("status", "time_label", "streak")}
                      | {"asked": now.date().isoformat()})
                ready.append(r)
    return ready


def prompt_block(now: datetime | None = None) -> str:
    """The weekly routine and how today is going, for the system prompt (short: it's sent every turn)."""
    rows = routines()
    if not rows:
        return ""
    week = "; ".join(f"{r['text']} {days_label(r['days'])} {time_label(r)}" for r in rows)
    todays = ", ".join(f"{r['text']} {r['time_label']} ({r['status']})" for r in today(now)) or "nothing"
    return f"{config.USERNAME}'s weekly routine: {week}.\nToday: {todays}."
