"""Recently watched YouTube videos, from the browsers' history on this computer.

YouTube's API doesn't give out watch history, but every browser keeps it locally. The history files are
locked while the browser runs, so they're copied to a temporary folder and read from there; nothing is changed.
"""
import glob
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOME = Path.home()
FIREFOX = ["~/.mozilla/firefox/*/places.sqlite", "~/snap/firefox/common/.mozilla/firefox/*/places.sqlite",
           "~/.var/app/org.mozilla.firefox/.mozilla/firefox/*/places.sqlite",
           "~/AppData/Roaming/Mozilla/Firefox/Profiles/*/places.sqlite"]
CHROMIUM = ["~/.config/chromium/*/History", "~/.config/google-chrome/*/History",
            "~/.config/BraveSoftware/Brave-Browser/*/History", "~/.config/microsoft-edge/*/History",
            "~/snap/chromium/common/chromium/*/History",
            "~/AppData/Local/Google/Chrome/User Data/*/History", "~/AppData/Local/Microsoft/Edge/User Data/*/History"]
_CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)  # Chromium counts microseconds from here, in UTC


def _files(patterns: list[str]) -> list[Path]:
    return [Path(p) for pattern in patterns for p in glob.glob(str(HOME / pattern.removeprefix("~/")))]


def _query(db: Path, sql: str) -> list[tuple]:
    """Run a read-only query on a copy of a (possibly locked) browser database, WAL file included."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / db.name
        for suffix in ("", "-wal"):
            if Path(f"{db}{suffix}").exists():
                shutil.copy2(f"{db}{suffix}", f"{copy}{suffix}")
        with closing(sqlite3.connect(copy)) as conn:
            return conn.execute(sql).fetchall()


def _video_id(url: str) -> str | None:
    u = urlparse(url)
    if u.netloc.endswith("youtube.com") and u.path == "/watch":
        return (parse_qs(u.query).get("v") or [None])[0]
    if u.netloc == "youtu.be":
        return u.path.strip("/") or None
    return None


def _clean_title(title: str) -> str:
    title = (title or "").strip()
    if title.startswith("(") and ") " in title[:6]:  # "(3) Song - YouTube": the notification count
        title = title.split(") ", 1)[1]
    return title.removesuffix(" - YouTube").strip()


def _visits() -> list[tuple[datetime, str, str, str]]:
    """(when, url, title, browser) for every YouTube watch page in every browser's history."""
    rows = []
    for db in _files(FIREFOX):
        try:
            for url, title, micros in _query(db, """
                    SELECT p.url, p.title, v.visit_date FROM moz_historyvisits v JOIN moz_places p ON p.id = v.place_id
                    WHERE p.url LIKE '%youtube.com/watch%' OR p.url LIKE '%youtu.be/%'
                    ORDER BY v.visit_date DESC LIMIT 400"""):
                rows.append((datetime.fromtimestamp(micros / 1e6), url, title, "Firefox"))
        except (sqlite3.Error, OSError):
            continue
    for db in _files(CHROMIUM):
        try:
            for url, title, micros in _query(db, """
                    SELECT u.url, u.title, v.visit_time FROM visits v JOIN urls u ON u.id = v.url
                    WHERE u.url LIKE '%youtube.com/watch%' OR u.url LIKE '%youtu.be/%'
                    ORDER BY v.visit_time DESC LIMIT 400"""):
                when = (_CHROME_EPOCH + timedelta(microseconds=micros)).astimezone().replace(tzinfo=None)
                rows.append((when, url, title, "Chromium"))
        except (sqlite3.Error, OSError):
            continue
    return rows


def recent(limit: int = 15) -> list[dict]:
    """Most recently watched videos first, one entry per video."""
    seen, out = set(), []
    for when, url, title, browser in sorted(_visits(), key=lambda r: r[0], reverse=True):
        vid = _video_id(url)
        title = _clean_title(title)
        if not vid or vid in seen or not title:  # no title: the page never finished loading
            continue
        seen.add(vid)
        out.append({"title": title, "url": f"https://www.youtube.com/watch?v={vid}",
                    "when": when.strftime("%a %d %b %H:%M"), "browser": browser})
        if len(out) >= limit:
            break
    return out
