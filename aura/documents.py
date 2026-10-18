"""Q&A over the user's own files: index chosen folders (text, Markdown, PDFs) and search them by meaning.

Passages live in a LangGraph SqliteStore with a vector index (sqlite-vec), separate from memory:
Data/docs_store.sqlite. Indexing is incremental (only changed files are re-read) and runs in the background.
"""
import os
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from dotenv import set_key
from langgraph.store.sqlite import SqliteStore
from pypdf import PdfReader

from . import config, embeddings

DB_NAME = "docs_store.sqlite"
PASSAGES, FILES, META = ("docs",), ("doc_files",), ("doc_meta",)
EXTENSIONS = {".txt", ".md", ".markdown", ".org", ".rst", ".tex", ".pdf"}
SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv", "site-packages", ".git"}
MAX_FILE_BYTES = 30 * 1024 * 1024
CHUNK, OVERLAP = 1000, 150

_store: SqliteStore | None = None
_store_lock = threading.RLock()
_index_lock = threading.Lock()  # one indexing run at a time
progress = {"running": False, "done": 0, "total": 0}


def _db() -> SqliteStore:
    global _store
    with _store_lock:
        if _store is None:
            index = embeddings.index_config()
            if index is None:
                raise RuntimeError("Document search needs the local embedding model, which couldn't be loaded.")
            conn = sqlite3.connect(config.DATA_DIR / DB_NAME, check_same_thread=False, isolation_level=None)
            _store = SqliteStore(conn, index=index)
            _store.setup()
        return _store


def _all(namespace: tuple) -> list:
    items, offset = [], 0
    while True:
        page = _db().search(namespace, limit=500, offset=offset)
        items += page
        if len(page) < 500:
            return items
        offset += 500


# ── folders (saved in .env as DocumentFolders, separated by "|") ──────────
def folders() -> list[str]:
    from dotenv import dotenv_values
    raw = dotenv_values(config.ENV_FILE).get("DocumentFolders") or ""
    return [f for f in raw.split("|") if f]


def _save_folders(items: list[str]) -> None:
    config.ENV_FILE.touch(exist_ok=True)
    set_key(str(config.ENV_FILE), "DocumentFolders", "|".join(items), quote_mode="never")


def add_folder(path: str) -> str:
    from .tools import _in_home
    folder = _in_home(path)
    if not folder.is_dir():
        raise ValueError(f"{folder} isn't a folder.")
    items = folders()
    if str(folder) not in items:
        _save_folders(items + [str(folder)])
    return str(folder)


def remove_folder(path: str) -> None:
    _save_folders([f for f in folders() if f != path])
    with _store_lock:
        for item in _all(FILES):
            if item.key.startswith(path.rstrip("/") + "/"):
                _forget_file(item.key, item.value.get("chunks", 0))


# ── reading & chunking ────────────────────────────────────────────────────
def _chunks(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK)
        if end < len(text):  # prefer to break at a paragraph or sentence boundary
            cut = max(text.rfind("\n\n", start + CHUNK // 2, end), text.rfind(". ", start + CHUNK // 2, end))
            end = cut + 1 if cut > 0 else end
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - OVERLAP, start + 1)
    return out


def _read(path: Path) -> list[tuple[int | None, str]]:
    """[(page or None, text)]"""
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    data = path.read_bytes()
    if b"\0" in data[:4096]:
        return []
    return [(None, data.decode("utf-8", errors="replace"))]


def _files_in(folder: str):
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        for name in filenames:
            p = Path(dirpath, name)
            if p.suffix.lower() in EXTENSIONS and not name.startswith("."):
                yield p


def _forget_file(path: str, chunks: int) -> None:
    for i in range(chunks):
        _db().delete(PASSAGES, f"{path}#{i}")
    _db().delete(FILES, path)


# ── indexing ──────────────────────────────────────────────────────────────
def index_all() -> dict:
    """Bring the index up to date with the chosen folders. Safe to call often: unchanged files are skipped."""
    if not _index_lock.acquire(blocking=False):
        return status()  # already running
    try:
        progress.update(running=True, done=0, total=0)
        wanted = {str(p): p for folder in folders() if Path(folder).is_dir() for p in _files_in(folder)}
        known = {item.key: item.value for item in _all(FILES)}
        for gone in set(known) - set(wanted):
            with _store_lock:
                _forget_file(gone, known[gone].get("chunks", 0))
        todo = [p for key, p in wanted.items()
                if p.stat().st_size <= MAX_FILE_BYTES and known.get(key, {}).get("mtime") != p.stat().st_mtime]
        progress["total"] = len(todo)
        for path in todo:
            key = str(path)
            try:
                pieces = [(page, c) for page, text in _read(path) for c in _chunks(text)]
            except Exception:
                pieces = []  # unreadable file (encrypted PDF...): remember it so it isn't retried every time
            with _store_lock:
                if key in known:
                    _forget_file(key, known[key].get("chunks", 0))
                for i, (page, chunk) in enumerate(pieces):
                    _db().put(PASSAGES, f"{key}#{i}", {"text": chunk, "path": key, "page": page})
                _db().put(FILES, key, {"mtime": path.stat().st_mtime, "chunks": len(pieces)}, index=False)
            progress["done"] += 1
        with _store_lock:
            _db().put(META, "last_run", {"at": datetime.now().isoformat(timespec="seconds")}, index=False)
        return status()
    finally:
        progress["running"] = False
        _index_lock.release()


def status() -> dict:
    try:
        files = _all(FILES)
        last = _db().get(META, "last_run")
    except RuntimeError as e:
        return {"folders": folders(), "files": 0, "passages": 0, "error": str(e), **progress}
    return {"folders": folders(), "files": len(files), "passages": sum(f.value.get("chunks", 0) for f in files),
            "last_run": last.value["at"] if last else None, "error": None, **progress}


def search(query: str, k: int = 6) -> list[dict]:
    """Passages closest in meaning to the query: [{"path", "page", "text", "score"}]."""
    hits = _db().search(PASSAGES, query=query, limit=k)
    return [{**h.value, "score": round(h.score or 0, 3)} for h in hits]
