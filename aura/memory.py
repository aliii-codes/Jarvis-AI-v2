"""Long-term memory: durable facts about the user plus a short note per day.

Stored in a LangGraph SqliteStore (Data/memory_store.sqlite), separate from conversation threads, so it
survives "New chat". Facts and recent days are injected into the system prompt; a background
"memory agent" (`learn`) extracts new facts from finished conversations.
"""
import re
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta

from langgraph.store.sqlite import SqliteStore

from . import config, embeddings

DB = config.DATA_DIR / "memory_store.sqlite"
FACTS, DAYS, META = ("facts",), ("days",), ("meta",)
MAX_FACTS_IN_PROMPT = 60
RECENT_DAYS_IN_PROMPT = 3

_lock = threading.RLock()  # the store is used from the UI thread, the agent worker and the learner
_store: SqliteStore | None = None


def _db() -> SqliteStore:
    global _store
    with _lock:
        if _store is None:
            _store = SqliteStore(sqlite3.connect(DB, check_same_thread=False, isolation_level=None))
            _store.setup()
        return _store


def _all(namespace: tuple[str, ...]) -> list:
    items, offset = [], 0
    while True:
        page = _db().search(namespace, limit=200, offset=offset)
        items += page
        if len(page) < 200:
            return items
        offset += 200


# ── facts ────────────────────────────────────────────────────────────────
def facts() -> list[dict]:
    """[{"id", "text", "updated"}], oldest first."""
    with _lock:
        rows = [{"id": i.key, **i.value} for i in _all(FACTS)]
    return sorted(rows, key=lambda r: r.get("created", ""))


def add_fact(text: str) -> str | None:
    text = " ".join(text.split()).rstrip(".")
    if not text:
        return None
    with _lock:
        if any(_norm(f["text"]) == _norm(text) for f in facts()):
            return None  # already known
        key, now = uuid.uuid4().hex[:8], datetime.now().isoformat(timespec="seconds")
        _db().put(FACTS, key, {"text": text, "created": now, "updated": now})
        return key


def edit_fact(key: str, text: str) -> bool:
    text = " ".join(text.split()).rstrip(".")
    with _lock:
        item = _db().get(FACTS, key)
        if not item or not text:
            return False
        _db().put(FACTS, key, {**item.value, "text": text, "updated": datetime.now().isoformat(timespec="seconds")})
        return True


def delete_fact(key: str) -> bool:
    with _lock:
        if not _db().get(FACTS, key):
            return False
        _db().delete(FACTS, key)
        return True


# ── daily notes ──────────────────────────────────────────────────────────
def days(limit: int | None = None) -> list[dict]:
    """[{"date": "YYYY-MM-DD", "notes": [...]}], newest first."""
    with _lock:
        rows = [{"date": i.key, "notes": i.value.get("notes", [])} for i in _all(DAYS)]
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows[:limit] if limit else rows


def add_day_note(note: str, day: date | None = None) -> bool:
    note = " ".join(note.split())
    if not note:
        return False
    key = (day or date.today()).isoformat()
    with _lock:
        item = _db().get(DAYS, key)
        notes = item.value.get("notes", []) if item else []
        if any(_norm(n) == _norm(note) for n in notes):
            return False
        _db().put(DAYS, key, {"notes": (notes + [note])[-8:]})
        return True


def delete_day(key: str) -> bool:
    with _lock:
        if not _db().get(DAYS, key):
            return False
        _db().delete(DAYS, key)
        return True


# ── settings & bookkeeping ───────────────────────────────────────────────
def learning_enabled() -> bool:
    with _lock:
        item = _db().get(META, "settings")
    return item.value.get("learning", True) if item else True


def set_learning(enabled: bool) -> None:
    with _lock:
        _db().put(META, "settings", {"learning": bool(enabled)})


def last_learned(thread_id: str) -> str | None:
    """Id of the last message of this thread the learner has already read."""
    with _lock:
        item = _db().get(META, f"progress:{thread_id}")
    return item.value.get("last_id") if item else None


def set_last_learned(thread_id: str, message_id: str) -> None:
    with _lock:
        _db().put(META, f"progress:{thread_id}", {"last_id": message_id})


def forget_everything() -> None:
    with _lock:
        for ns in (FACTS, DAYS):
            for item in _all(ns):
                _db().delete(ns, item.key)


def snapshot() -> dict:
    """Everything the Memory panel shows."""
    return {"facts": facts(), "days": days(), "learning": learning_enabled()}


# ── retrieval ────────────────────────────────────────────────────────────
def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _words(text: str) -> set[str]:
    return {w for w in _norm(text).split() if len(w) > 2}


_vectors: dict[str, "np.ndarray"] = {}  # text -> embedding, cached for the session


def _semantic(query: str, texts: list[str], k: int) -> list[str]:
    """The k texts closest in meaning to the query ("when's my test?" -> "Networks exam on ...").
    Memory is small, so vectors are computed on demand and compared directly; no index needed."""
    import numpy as np
    missing = [t for t in texts if t not in _vectors]
    if missing:
        for t, v in zip(missing, embeddings.current.embed_documents(missing)):
            _vectors[t] = np.asarray(v)
    q = np.asarray(embeddings.current.embed_query(query))
    scores = [(float(_vectors[t] @ q / ((np.linalg.norm(_vectors[t]) * np.linalg.norm(q)) or 1)), t) for t in texts]
    return [t for _, t in sorted(scores, reverse=True)[:k]]


def search(query: str, limit: int = 8) -> list[str]:
    """Facts and daily notes matching the query: closest in meaning first, then exact keyword hits.
    Returns several candidates on purpose: small embedding models often tie close meanings
    (an exam and a dentist appointment both match "test"), and the model picks the right one."""
    entries = [f["text"] for f in facts()] + [f"{d['date']}: {n}" for d in days() for n in d["notes"]]
    want = _words(query)
    keyword = [t for score, t in sorted(((len(want & _words(t)), t) for t in entries), key=lambda s: -s[0]) if score]
    meaning = []
    if entries:
        try:
            meaning = _semantic(query, entries, k=5)
        except Exception:  # embedding model unavailable: keywords only
            pass
    seen, out = set(), []
    for t in meaning + keyword:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:limit]


def prompt_block() -> str:
    """Memory section for the system prompt (empty if nothing is known yet)."""
    known = facts()[-MAX_FACTS_IN_PROMPT:]
    recent = [d for d in days(RECENT_DAYS_IN_PROMPT) if d["date"] >= (date.today() - timedelta(days=7)).isoformat()]
    if not known and not recent:
        return ""
    parts = []
    if known:
        parts.append(f"What you know about {config.USERNAME} (use naturally when relevant; don't recite it):\n"
                     + "\n".join(f"- {f['text']}" for f in known))
    if recent:
        lines = []
        for d in recent:
            label = datetime.fromisoformat(d["date"]).strftime("%a %d %b")
            lines.append(f"- {label}: " + "; ".join(d["notes"]))
        parts.append("Recent days:\n" + "\n".join(lines))
    return "\n\n".join(parts)
