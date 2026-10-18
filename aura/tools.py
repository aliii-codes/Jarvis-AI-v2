"""Tools the agent can call. Docstrings are what the model reads to decide when to use each one."""
import fnmatch
import io
import os
import platform
import re
import time
import shutil
import subprocess
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from langchain_core.tools import tool
from pypdf import PdfReader

from . import config, lists
from . import documents as docs_store
from . import memory as memory_store  # the `memory` and `reminders` names are tools below
from . import reminders as reminder_store

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

HOME = Path.home()
_BLOCKS = ["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "pre", "blockquote", "section", "dd", "dt", "td", "th"]
MAX_CHARS = 8000  # keeps a page or file within Groq's free-tier tokens-per-minute budget

# Set by the UI: closing the window, and running a function on the UI thread (needed for the clipboard).
on_quit: Callable[[], None] = lambda: None
ui_call: Callable[[Callable[[], Any]], Any] = lambda fn: fn()


def open_path(path: str) -> None:
    """Open a file with the OS default application."""
    if IS_WINDOWS:
        os.startfile(path)
    else:
        subprocess.Popen(["open" if IS_MAC else "xdg-open", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _slug(text: str, limit: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:limit] or "untitled"


def _truncate(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    return text[:MAX_CHARS] + f"\n\n[truncated: showing {MAX_CHARS} of {len(text)} characters]"


def _pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def _expand(path: str) -> Path:
    """'~/x' -> HOME/x. (Not Path.expanduser, so '~' always means the same HOME the safety check uses.)"""
    path = path.strip()
    if path == "~" or path.startswith("~/"):
        return HOME / path[2:]
    return Path(path)


def _in_home(path: str) -> Path:
    """Resolve a user-supplied path, refusing anything outside the home folder."""
    p = _expand(path)
    p = (p if p.is_absolute() else HOME / p).resolve()
    if not p.is_relative_to(HOME):
        raise PermissionError(f"Only files inside {HOME} can be accessed.")
    return p


@tool
def web_search(query: str) -> str:
    """Quick web lookup for a single current fact: news, prices, scores, recent events, or anything
    you are not sure about. Returns titles, snippets and URLs. For comparisons ("X vs Y"),
    recommendations or in-depth questions, use research instead."""
    results = DDGS().text(query, max_results=6)
    if not results:
        return "No results found."
    return "\n\n".join(f"{r['title']}\n{r['body']}\n{r['href']}" for r in results)


@tool
def get_weather(city: str) -> str:
    """Get the current weather and today's forecast for a city."""
    data = requests.get(f"https://wttr.in/{quote_plus(city)}?format=j1", timeout=10).json()
    now, today = data["current_condition"][0], data["weather"][0]
    area = data["nearest_area"][0]
    place = f"{area['areaName'][0]['value']}, {area['country'][0]['value']}"
    return (f"{place}: {now['weatherDesc'][0]['value']}, {now['temp_C']}°C "
            f"(feels like {now['FeelsLikeC']}°C), humidity {now['humidity']}%, "
            f"wind {now['windspeedKmph']} km/h. Today: min {today['mintempC']}°C, max {today['maxtempC']}°C.")


def _open_app(name: str) -> str:
    """Open a desktop application installed on this computer, e.g. "firefox", "spotify", "code"."""
    if IS_WINDOWS:
        from AppOpener import open as appopen
        appopen(name, match_closest=True, throw_error=True)
        return f"Opened {name}."
    candidates = [name, name.lower(), name.lower().replace(" ", "-"), name.lower().replace(" ", "")]
    exe = next((p for c in candidates if (p := shutil.which(c))), None)
    if not exe:
        return f"No application called '{name}' is installed. If it is a website, use open_website instead."
    subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return f"Opened {name}."


def _close_app(name: str) -> str:
    """Close a running desktop application by name."""
    if IS_WINDOWS:
        from AppOpener import close
        close(name, match_closest=True, throw_error=True)
        return f"Closed {name}."
    if subprocess.run(["pkill", "-if", name]).returncode != 0:
        return f"No running application matching '{name}'."
    return f"Closed {name}."


def _open_website(url: str) -> str:
    """Open a website in the user's browser. Accepts a full URL or a domain like "github.com"."""
    if not re.match(r"^https?://", url):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url} in the browser."


def _search_in_browser(query: str, site: Literal["google", "youtube"] = "google") -> str:
    """Open a Google or YouTube search results page in the user's browser.
    Use this only when the user wants to see the results themselves; use web_search to answer questions."""
    base = "https://www.youtube.com/results?search_query=" if site == "youtube" else "https://www.google.com/search?q="
    webbrowser.open(base + quote_plus(query))
    return f"Opened {site} search for '{query}'."


def _play_on_youtube(query: str) -> str:
    """Play a song or video on YouTube: finds the best match and opens it in the browser."""
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    html = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10).text
    match = re.search(r'"videoId":"([\w-]{11})"', html)
    if match:
        url = f"https://www.youtube.com/watch?v={match.group(1)}"
    webbrowser.open(url)
    return f"Playing '{query}' on YouTube."


@tool
def set_volume(action: Literal["mute", "unmute", "up", "down"]) -> str:
    """Change the computer's speaker volume."""
    if IS_WINDOWS:
        import keyboard
        key = {"mute": "volume mute", "unmute": "volume mute", "up": "volume up", "down": "volume down"}[action]
        keyboard.press_and_release(key)
    else:
        sink = "@DEFAULT_SINK@"
        cmd = {
            "mute": ["pactl", "set-sink-mute", sink, "1"],
            "unmute": ["pactl", "set-sink-mute", sink, "0"],
            "up": ["pactl", "set-sink-volume", sink, "+10%"],
            "down": ["pactl", "set-sink-volume", sink, "-10%"],
        }[action]
        subprocess.run(cmd, check=True)
    return f"Volume {action}."


_XDG_DIRS = {"desktop": "DESKTOP", "downloads": "DOWNLOAD", "download": "DOWNLOAD", "documents": "DOCUMENTS",
             "pictures": "PICTURES", "music": "MUSIC", "videos": "VIDEOS"}
_TEXT_EXTENSIONS = {".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", ".csv", ".tex", ".sh", ".yaml",
                    ".yml", ".xml", ".sql", ".c", ".cpp", ".h", ".java", ".rs", ".go", ".rb", ".php", ".ini", ".toml"}


def _resolve_folder(folder: str) -> Path:
    """'Downloads/Sick leave', '~/Desktop', 'Documents' -> a path inside home (standard folders via xdg-user-dir)."""
    folder = folder.strip().replace("\\", "/")
    if folder.startswith("~/"):
        folder = folder[2:]  # "~/Downloads" is the same as "Downloads"
    parts = Path(folder).parts
    if parts and not Path(folder).is_absolute() and parts[0].lower() in _XDG_DIRS and shutil.which("xdg-user-dir"):
        base = subprocess.run(["xdg-user-dir", _XDG_DIRS[parts[0].lower()]], capture_output=True, text=True).stdout.strip()
        if base:
            return _in_home(str(Path(base, *parts[1:])))
    return _in_home(folder)


def _safe_filename(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", title)
    return " ".join(name.split()).strip(" .")[:80] or "Untitled"


def _unique(path: Path) -> Path:
    """Never overwrite: 'Letter.txt' -> 'Letter (2).txt' if it already exists."""
    if not path.exists():
        return path
    n = 2
    while (candidate := path.with_name(f"{path.stem} ({n}){path.suffix}")).exists():
        n += 1
    return candidate


@tool
def save_document(title: str, content: str, folder: str = "") -> str:
    """Save text you wrote (an email, letter, essay, code, notes...) to a file and open it.
    Write the full content yourself, then call this.
    `folder`: where the user asked to save it, relative to their home or starting with ~, e.g. "Downloads",
    "Desktop/Sick leave", "~/Documents/uni" (missing folders are created). Leave empty if they didn't say.
    `title` becomes the file name; include an extension for code or Markdown (e.g. "app.py", "notes.md")."""
    target = _resolve_folder(folder) if folder.strip() else config.DATA_DIR / "documents"
    target.mkdir(parents=True, exist_ok=True)
    name = _safe_filename(title)
    if Path(name).suffix.lower() not in _TEXT_EXTENSIONS:
        name += ".txt"
    path = _unique(target / name)
    path.write_text(content, encoding="utf-8")
    open_path(str(path))
    return f"Saved and opened {path}"


def _open_folder(path: str) -> str:
    """Open a folder in the file manager (e.g. after saving a file: "open that folder"). Path inside home."""
    folder = _resolve_folder(path)
    if folder.is_file():
        folder = folder.parent
    if not folder.is_dir():
        return f"{folder} doesn't exist."
    open_path(str(folder))
    return f"Opened {folder} in the file manager."


_hf_images_unavailable = False  # set after a credits/availability failure, so we don't retry it every time


def _image_from_hf(prompt: str) -> bytes:
    """Best quality, via Hugging Face Inference Providers (needs account credits)."""
    from huggingface_hub import InferenceClient
    client = InferenceClient(provider="auto", api_key=config.HF_API_KEY, timeout=120)
    image = client.text_to_image(prompt, model=config.IMAGE_MODEL)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _image_from_pollinations(prompt: str) -> bytes:
    """Free, no key needed; lower quality and a small watermark. The prompt is sent to pollinations.ai.
    The free tier allows one image every ~45s per IP and is sometimes overloaded: wait out short
    "retry after" delays (with a visible countdown) a couple of times before giving up."""
    from langgraph.config import get_stream_writer
    for attempt in range(3):
        resp = requests.get(f"https://image.pollinations.ai/prompt/{quote_plus(prompt)}",
                            params={"width": 1024, "height": 1024, "model": "flux", "nologo": "true"}, timeout=120)
        if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("image/"):
            return resp.content
        wait = re.search(r"[Rr]etry after (\d+)s", resp.text)
        if attempt < 2 and resp.status_code in (402, 429, 503) and wait and int(wait.group(1)) <= 60:
            seconds = int(wait.group(1)) + 1
            try:
                get_stream_writer()({"status": f"free image limit · waiting {seconds}s"})
            except Exception:
                pass  # not running inside the agent graph
            time.sleep(seconds)
            continue
        raise RuntimeError(f"Pollinations returned {resp.status_code}: {resp.text[:150]}")
    raise RuntimeError("Pollinations is rate limiting; try again in a minute.")


@tool(response_format="content_and_artifact")
def generate_image(prompt: str) -> tuple[str, dict]:
    """Generate an image from a text description; it's shown to the user right in the chat.
    Write a detailed visual prompt in English."""
    global _hf_images_unavailable
    data, source, note = None, "", ""
    if config.HF_API_KEY and not _hf_images_unavailable:
        try:
            data, source = _image_from_hf(prompt), "Hugging Face (FLUX)"
        except Exception as e:
            _hf_images_unavailable = True
            note = (" Hugging Face credits are used up, so the free service was used."
                    if "402" in str(e) or "credits" in str(e).lower() else f" Hugging Face failed ({type(e).__name__}).")
    if data is None:
        data, source = _image_from_pollinations(prompt), "Pollinations (free)"
    images = config.DATA_DIR / "images"
    images.mkdir(exist_ok=True)
    ext = "png" if data[:4] == b"\x89PNG" else "jpg"
    path = images / f"{_slug(prompt, 40)}_{datetime.now():%H%M%S}.{ext}"
    path.write_bytes(data)
    # The path travels as an artifact: the UI shows the image inline, and it's saved with the conversation.
    return (f"Generated with {source}. The image is now displayed to the user in the chat "
            f"(saved at {path}; don't repeat the path unless asked).{note}", {"image": str(path)})


@tool
def read_url(url: str) -> str:
    """Fetch a web page or online PDF and return its main text, e.g. to summarize an article
    or read a page found with web_search."""
    if not re.match(r"^https?://", url):
        url = "https://" + url
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()
    if "pdf" in resp.headers.get("Content-Type", "") or url.lower().endswith(".pdf"):
        return _truncate(_pdf_text(resp.content))
    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else url
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "sup"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    # Break lines only at block elements so inline links/spans stay within their sentence.
    for br in root.find_all("br"):
        br.replace_with("\n")
    for block in root.find_all(_BLOCKS):
        block.insert_before("\n")
        block.insert_after("\n")
    lines = (" ".join(line.split()) for line in root.get_text().splitlines())
    return _truncate(f"{title}\n\n" + "\n".join(line for line in lines if line))


def _read_clipboard() -> str:
    """Get the text currently in the user's clipboard (what they just copied)."""
    from PyQt5.QtWidgets import QApplication
    text = ui_call(lambda: QApplication.clipboard().text())
    return _truncate(text) if text else "The clipboard is empty."


def _copy_to_clipboard(text: str) -> str:
    """Put text into the user's clipboard so they can paste it."""
    from PyQt5.QtWidgets import QApplication
    ui_call(lambda: QApplication.clipboard().setText(text))
    return "Copied to clipboard."


def _list_folder(path: str = "~") -> str:
    """List the files and folders in a directory inside the user's home folder (e.g. "~/Downloads")."""
    folder = _in_home(path)
    entries = sorted((e for e in folder.iterdir() if not e.name.startswith(".")),
                     key=lambda e: (not e.is_dir(), e.name.lower()))
    lines = []
    for e in entries[:100]:
        if e.is_dir():
            lines.append(f"{e.name}/")
        else:
            st = e.stat()
            size = f"{st.st_size} bytes" if st.st_size < 1024 else f"{st.st_size / 1024:.0f} KB"
            lines.append(f"{e.name}  ({size}, modified {datetime.fromtimestamp(st.st_mtime):%Y-%m-%d})")
    more = f"\n...and {len(entries) - 100} more" if len(entries) > 100 else ""
    return f"{folder}:\n" + ("\n".join(lines) or "(empty)") + more


def _find_files(name: str, folder: str = "~") -> str:
    """Find files by name inside the user's home folder. `name` is part of the file name
    or a glob like "*.pdf". Returns up to 25 matching paths, newest first."""
    root = _in_home(folder)
    pattern = name.lower() if any(ch in name for ch in "*?[") else f"*{name.lower()}*"
    skip = {"node_modules", "__pycache__", "venv", ".venv", "site-packages"}
    matches, deadline = [], time.monotonic() + 4
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in skip]
        matches += [Path(dirpath, f) for f in filenames if fnmatch.fnmatch(f.lower(), pattern)]
        if len(matches) >= 200 or time.monotonic() > deadline:
            break
    if not matches:
        return f"No files matching '{name}' in {root}."
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return "\n".join(str(p) for p in matches[:25])


def _read_file(path: str) -> str:
    """Read a text file or PDF inside the user's home folder (notes, code, documents, logs...)."""
    p = _in_home(path)
    data = p.read_bytes()
    if p.suffix.lower() == ".pdf":
        return _truncate(_pdf_text(data))
    if b"\0" in data[:4096]:
        return f"{p.name} is a binary file and can't be read as text."
    return _truncate(data.decode("utf-8", errors="replace"))


def _set_reminder(message: str, at: str = "", in_minutes: float = 0) -> str:
    """Remind the user about something later with a desktop notification.
    Give either `in_minutes` (e.g. 20) or `at` as a local date-time "YYYY-MM-DD HH:MM"."""
    if in_minutes:
        due_at = datetime.now() + timedelta(minutes=in_minutes)
    elif at:
        due_at = datetime.fromisoformat(at.strip().replace("T", " "))
    else:
        return "Specify when: either in_minutes or at."
    if due_at <= datetime.now():
        return f"{due_at:%Y-%m-%d %H:%M} is in the past; pick a future time."
    rid = reminder_store.add(message, due_at)
    return f"Reminder #{rid} set for {due_at:%A %d %B, %H:%M}: {message}"


def _list_reminders() -> str:
    """List upcoming reminders with their ids."""
    items = reminder_store.pending()
    if not items:
        return "No upcoming reminders."
    return "\n".join(f"#{i} {due:%a %d %b %H:%M}: {msg}" for i, msg, due in items)


def _cancel_reminder(reminder_id: int) -> str:
    """Cancel an upcoming reminder by its id (see list_reminders)."""
    return f"Cancelled reminder #{reminder_id}." if reminder_store.cancel(reminder_id) else f"No upcoming reminder #{reminder_id}."


def _best_match(text: str) -> dict | None:
    want = memory_store._words(text)
    scored = sorted(((len(want & memory_store._words(f["text"])), f) for f in memory_store.facts()), key=lambda s: -s[0])
    return scored[0][1] if scored and scored[0][0] else None


def _remember(fact: str, replaces: str = "") -> str:
    """Save something about the user to long-term memory: when they ask you to remember it, or tell you
    something lasting that changed (moved city, new job). Write a short statement without their name
    and with absolute dates ("Has a cat named Mochi", "Moved to Islamabad in Oct 2026", never "last week"). If it updates something you already know,
    put the old fact's text in `replaces` so it's corrected instead of duplicated."""
    old = _best_match(replaces) if replaces else None
    if old:
        memory_store.edit_fact(old["id"], fact)
        return f"Updated memory: {old['text']} -> {fact}"
    return f"Remembered: {fact}" if memory_store.add_fact(fact) else "That's already in memory."


def _forget(what: str) -> str:
    """Remove something from long-term memory when the user asks you to forget it.
    `what` describes the fact; the closest matching saved fact is deleted."""
    fact = _best_match(what)
    if not fact:
        return "Nothing in memory matches that."
    memory_store.delete_fact(fact["id"])
    return f"Forgot: {fact['text']}"


def _recall(query: str) -> str:
    """Search long-term memory, including notes from past days that aren't in your context,
    e.g. "what did I work on last week", "when is my exam"."""
    hits = memory_store.search(query)
    return "\n".join(hits) if hits else "Nothing in memory about that."


def _task_line(t: dict) -> str:
    due = f" (due {t['due_label']}{', OVERDUE' if t['overdue'] else ''})" if t.get("due") else ""
    return f"{'[done] ' if t['done'] else ''}{t['text']}{due}"


def _add_task(text: str, due: str = "") -> str:
    """Add a to-do to the user's task list ("add buy charger to my list", "I need to submit the report by Friday").
    `due` is optional: "YYYY-MM-DD", or "YYYY-MM-DD HH:MM" to also get a reminder at that time."""
    task = lists.add_task(text, due)
    task = {**task, "due_label": lists.due_label(task.get("due")), "overdue": False}
    extra = " A reminder will pop up at that time." if task.get("reminder_id") else ""
    verb = "Already on the list" if task["existing"] else "Added task"
    return f"{verb}: {_task_line(task)}.{extra}"


def _list_tasks(include_done: bool = False) -> str:
    """Show the user's open tasks (to-do list), with ids and due dates."""
    items = lists.tasks(include_done=include_done)
    return "\n".join(_task_line(t) for t in items) if items else "The task list is empty."


def _complete_task(task: str) -> str:
    """Mark a task as done. `task` is its id (e.g. "#a1b2c3") or a few words from it."""
    match = lists.find_task(task)
    if not match:
        return f"No open task matches '{task}'."
    lists.set_done(match["id"])
    return f"Completed: {match['text']}"


def _delete_task(task: str) -> str:
    """Remove a task entirely (not completed, just deleted). `task` is its id or a few words from it."""
    match = lists.find_task(task, include_done=True)
    if not match:
        return f"No task matches '{task}'."
    lists.delete_task(match["id"])
    return f"Deleted task: {match['text']}"


def _save_note(text: str) -> str:
    """Save a quick note the user wants to keep and look up later (a wifi password, a code, an idea,
    a parking spot, a book recommendation). For facts about the user themselves, use remember instead;
    for long documents, use save_document."""
    note = lists.add_note(text)
    return "Saved the note."


def _search_notes(query: str = "") -> str:
    """Look up the user's saved notes by keywords (empty query returns the latest notes)."""
    found = lists.search_notes(query)
    if not found:
        return "No notes match that."
    return "\n\n".join(f"({n['created'][:10]}) {n['text']}" for n in found)


def _delete_note(note: str) -> str:
    """Delete a saved note by its id (e.g. "#a1b2c3") or by keywords from it."""
    key = note.strip().lstrip("#")
    target = next((n for n in lists.notes() if n["id"] == key), None) or next(iter(lists.search_notes(note, 1)), None)
    if not target:
        return "No note matches that."
    lists.delete_note(target["id"])
    return f"Deleted note: {target['text'][:80]}"


@tool
def quit_aura() -> str:
    """Close the AURA app. Only use when the user clearly says goodbye or asks to quit."""
    on_quit()
    return "Closing."


# ── merged tools ─────────────────────────────────────────────────────────
# Related actions share one tool: every tool description is sent with every request, so fewer, broader
# tools cost far fewer tokens (31 separate tools were ~1,500 tokens per request).

@tool
def app(action: Literal["open", "close"], name: str) -> str:
    """Open or close a desktop application, e.g. "firefox", "spotify", "code"."""
    return _open_app(name) if action == "open" else _close_app(name)


@tool
def browser(action: Literal["open_website", "google", "youtube_search", "play_youtube"], target: str) -> str:
    """Use the user's web browser: open_website (URL or domain), google / youtube_search (show results
    for the user to browse), play_youtube (find a song or video and play it). To answer a question
    yourself, use web_search instead."""
    if action == "open_website":
        return _open_website(target)
    if action == "play_youtube":
        return _play_on_youtube(target)
    return _search_in_browser(target, "youtube" if action == "youtube_search" else "google")


@tool
def files(action: Literal["list", "find", "read", "open_folder"], path: str = "~", name: str = "") -> str:
    """Files in the user's home folder. list: a folder's contents. find: files whose name contains `name`
    (or a glob like "*.pdf") under `path`. read: a text file or PDF at `path`. open_folder: show `path` in
    the file manager. Paths are relative to home or start with ~."""
    if action == "list":
        return _list_folder(path)
    if action == "find":
        return _find_files(name or path, "~" if not name else path)
    if action == "read":
        return _read_file(path)
    return _open_folder(path)


@tool
def clipboard(action: Literal["read", "copy"], text: str = "") -> str:
    """read: get what the user copied (use when they say "this" or "what I copied"). copy: put `text` on it."""
    return _read_clipboard() if action == "read" else _copy_to_clipboard(text)


@tool
def reminders(action: Literal["set", "list", "cancel"], message: str = "", at: str = "",
              in_minutes: float = 0, reminder_id: int = 0) -> str:
    """Desktop-notification reminders. set: `message` plus `in_minutes` or `at` ("YYYY-MM-DD HH:MM").
    list: upcoming ones with ids. cancel: by `reminder_id`."""
    if action == "set":
        return _set_reminder(message, at, in_minutes)
    if action == "list":
        return _list_reminders()
    return _cancel_reminder(reminder_id)


@tool
def memory(action: Literal["remember", "forget", "recall"], text: str, replaces: str = "") -> str:
    """Long-term memory about the user. remember: save a short fact with absolute dates, no name
    ("Has a cat named Mochi"); if it updates a known fact, put the old fact in `replaces`.
    forget: delete the fact best matching `text`. recall: search facts and past days' notes."""
    if action == "remember":
        return _remember(text, replaces)
    if action == "forget":
        return _forget(text)
    return _recall(text)


@tool
def tasks(action: Literal["add", "list", "done", "delete"], task: str = "", due: str = "",
          include_done: bool = False) -> str:
    """The user's to-do list. add: `task` text, optional `due` "YYYY-MM-DD" or "YYYY-MM-DD HH:MM" (a time also
    sets a reminder). list: open tasks. done / delete: `task` is a few words from the task."""
    if action == "add":
        return _add_task(task, due)
    if action == "list":
        return _list_tasks(include_done)
    return _complete_task(task) if action == "done" else _delete_task(task)


@tool
def notes(action: Literal["save", "search", "delete"], text: str = "") -> str:
    """Quick notes the user wants to keep (wifi password, a code, an idea). save: `text`.
    search: by keywords (empty = latest). delete: keywords from the note. Facts about the user go in memory."""
    if action == "save":
        return _save_note(text)
    if action == "search":
        return _search_notes(text)
    return _delete_note(text)


@tool
def documents(query: str) -> str:
    """Search the user's own files (notes, lecture PDFs, documents in the folders they chose in Settings)
    by meaning. Use for questions about their course material, notes or documents, and cite the file
    names (and pages) you used."""
    if not docs_store.folders():
        return "No document folders are set up yet. The user can add folders in Settings → Documents."
    hits = docs_store.search(query)
    if not hits:
        return "Nothing relevant in the user's documents (indexing may still be running)."
    lines = []
    for h in hits:
        where = Path(h["path"]).name + (f", p.{h['page']}" if h.get("page") else "")
        lines.append(f"[{where}] {h['text'][:700]}")
    return "\n\n".join(lines)


@tool(return_direct=True)  # the cited answer goes straight to the user, not re-written (and stripped) by the model
def research(question: str) -> str:
    """Research a question that needs several sources: comparisons ("X vs Y"), recommendations, pros and
    cons, or explaining something recent in depth. Reads several web pages and returns an answer with
    numbered citations and a source list. For a quick fact, use web_search instead."""
    from . import research as research_agent
    from langgraph.config import get_stream_writer
    try:
        writer = get_stream_writer()
        status = lambda text: writer({"status": text})
    except Exception:  # not running inside the agent graph
        status = lambda text: None
    return research_agent.run(question, status)


TOOLS = [web_search, research, read_url, get_weather, app, browser, set_volume, save_document, files,
         generate_image, clipboard, reminders, memory, tasks, notes, documents, quit_aura]
