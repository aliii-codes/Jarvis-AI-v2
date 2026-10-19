"""Chat history: an index of conversation threads (title, last activity) for the sidebar, plus search.

Conversations themselves live in the LangGraph checkpointer (Data/memory.sqlite). The index is kept in the
memory store so the sidebar doesn't have to load every conversation; it's backfilled for threads that
existed before it, and refreshed after every turn.
"""
import re
import sqlite3
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage

from . import config
from .memory import _all, _db, _lock

THREADS = ("threads",)


def _is_summary(m) -> bool:
    return m.additional_kwargs.get("lc_source") == "summarization"


def _messages(graph, thread_id: str) -> list:
    return graph.get_state({"configurable": {"thread_id": thread_id}}).values.get("messages", [])


def _title_from(messages: list) -> str:
    # Skip openers like "hey" / "hi": use the first message with some substance, else the first one.
    def shown(m) -> str:  # what the user typed (not extracted attachment text), or the attachment's name
        files = m.additional_kwargs.get("attachments") or []
        typed = m.additional_kwargs.get("display_text", m.content) if files else m.content
        return " ".join(str(typed).split()) or ("📎 " + files[0]["name"] if files else "")

    texts = [shown(m) for m in messages if isinstance(m, HumanMessage) and not _is_summary(m)]
    first = next((t for t in texts if len(t.split()) >= 3), texts[0] if texts else "")
    return (first[:57] + "…") if len(first) > 58 else first


def _checkpoint_threads() -> list[str]:
    """Every thread id the checkpointer knows, newest activity first."""
    conn = sqlite3.connect(f"file:{config.MEMORY_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT thread_id FROM checkpoints GROUP BY thread_id ORDER BY MAX(checkpoint_id) DESC")
        return [r[0] for r in rows]
    except sqlite3.OperationalError:  # no conversations yet
        return []
    finally:
        conn.close()


def touch(graph, thread_id: str) -> None:
    """Refresh one thread's index entry (called after each turn)."""
    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    messages = snapshot.values.get("messages", [])
    if not any(isinstance(m, HumanMessage) and not _is_summary(m) for m in messages):
        return
    with _lock:
        item = _db().get(THREADS, thread_id)
        entry = item.value if item else {}
        if not entry.get("custom_title"):
            entry["title"] = _title_from(messages) or "Untitled chat"
        entry["updated"] = snapshot.created_at or datetime.now().isoformat()
        _db().put(THREADS, thread_id, entry)


def list_threads(graph) -> list[dict]:
    """[{"id", "title", "updated"}], most recent first. Backfills threads missing from the index."""
    with _lock:
        known = {i.key: i.value for i in _all(THREADS)}
    for tid in _checkpoint_threads():
        if tid not in known:
            touch(graph, tid)
    with _lock:
        rows = [{"id": i.key, "title": i.value.get("title", "Untitled chat"), "updated": i.value.get("updated", "")}
                for i in _all(THREADS)]
    return sorted(rows, key=lambda r: r["updated"], reverse=True)


def rename(thread_id: str, title: str) -> bool:
    title = " ".join(title.split())[:80]
    with _lock:
        item = _db().get(THREADS, thread_id)
        if not item or not title:
            return False
        _db().put(THREADS, thread_id, {**item.value, "title": title, "custom_title": True})
        return True


def delete(checkpointer, thread_id: str) -> None:
    checkpointer.delete_thread(thread_id)
    with _lock:
        if _db().get(THREADS, thread_id):
            _db().delete(THREADS, thread_id)


def search(graph, query: str, limit: int = 25) -> list[dict]:
    """Chats whose title or messages contain all the query's words: [{"id", "title", "updated", "snippet"}]."""
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
    if not words:
        return []
    results = []
    for t in list_threads(graph):
        if all(w in t["title"].lower() for w in words):
            results.append({**t, "snippet": ""})
            continue
        for m in _messages(graph, t["id"]):
            if not isinstance(m, (HumanMessage, AIMessage)) or _is_summary(m) or not m.content:
                continue
            text = " ".join(str(m.content).split())
            low = text.lower()
            if all(w in low for w in words):
                at = low.find(words[0])
                snippet = ("…" if at > 40 else "") + text[max(0, at - 40):at + 90] + ("…" if at + 90 < len(text) else "")
                results.append({**t, "snippet": snippet})
                break
        if len(results) >= limit:
            break
    return results
