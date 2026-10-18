"""Desktop window: a local web page (aura/web) rendered by QtWebEngine, driven over QWebChannel."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

from PyQt5.QtCore import QObject, Qt, QThread, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor, QDesktopServices, QGuiApplication, QImage, QKeySequence
from PyQt5.QtNetwork import QLocalServer
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineView
from PyQt5.QtWidgets import QApplication, QMainWindow, QShortcut

from . import config, instance, learner, lists, memory, reminders, threads, tools
from .agent import Aura

WEB_DIR = config.ROOT / "aura" / "web"
LEARN_AFTER_IDLE_MS = 45_000  # learn once the user pauses, so it doesn't compete with chat for rate limits
BACKGROUND = {"dark": "#0e0e11", "light": "#ffffff"}  # matches app.css, avoids a white flash on load


def _file_url(path: str) -> str:
    return QUrl.fromLocalFile(path).toString()


def _history_json(aura: Aura | None) -> str:
    """History for the page; images become [role, url, path]."""
    rows = []
    for role, text in (aura.history() if aura else []):
        rows.append(["image", _file_url(text), text] if role == "image" else [role, text])
    return json.dumps(rows)


def _generated_image(path: str) -> Path | None:
    """Only files AURA generated (inside Data/images) may be opened or copied from the page."""
    p = Path(path).resolve()
    return p if p.is_file() and p.is_relative_to((config.DATA_DIR / "images").resolve()) else None

# (while running, when done) — shown as chips under the user's message.
TOOL_LABELS = {
    "web_search": ("Searching the web", "Searched the web"),
    "read_url": ("Reading the page", "Read the page"),
    "get_weather": ("Checking the weather", "Checked the weather"),
    "app:open": ("Opening app", "Opened app"),
    "app:close": ("Closing app", "Closed app"),
    "browser:open_website": ("Opening website", "Opened website"),
    "browser:google": ("Opening search", "Opened search"),
    "browser:youtube_search": ("Opening YouTube", "Opened YouTube"),
    "browser:play_youtube": ("Finding on YouTube", "Playing on YouTube"),
    "set_volume": ("Changing volume", "Changed volume"),
    "save_document": ("Saving document", "Saved document"),
    "files:list": ("Looking in folder", "Looked in folder"),
    "files:find": ("Searching files", "Searched files"),
    "files:read": ("Reading file", "Read file"),
    "files:open_folder": ("Opening folder", "Opened folder"),
    "generate_image": ("Generating image", "Generated image"),
    "clipboard:read": ("Reading clipboard", "Read clipboard"),
    "clipboard:copy": ("Copying", "Copied to clipboard"),
    "reminders:set": ("Setting reminder", "Set reminder"),
    "reminders:list": ("Checking reminders", "Checked reminders"),
    "reminders:cancel": ("Cancelling reminder", "Cancelled reminder"),
    "memory:remember": ("Saving to memory", "Saved to memory"),
    "memory:forget": ("Forgetting", "Forgot"),
    "memory:recall": ("Checking memory", "Checked memory"),
    "tasks:add": ("Adding task", "Added task"),
    "tasks:list": ("Checking tasks", "Checked tasks"),
    "tasks:done": ("Completing task", "Completed task"),
    "tasks:delete": ("Deleting task", "Deleted task"),
    "notes:save": ("Saving note", "Saved note"),
    "notes:search": ("Searching notes", "Searched notes"),
    "notes:delete": ("Deleting note", "Deleted note"),
    "quit_aura": ("Closing", "Closing"),
}


def system_theme() -> str:
    """'dark' or 'light', following GNOME's setting, else the Qt palette."""
    if shutil.which("gsettings"):
        try:
            scheme = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                                    capture_output=True, text=True, timeout=2).stdout
            if scheme.strip():
                return "dark" if "dark" in scheme else "light"
        except (OSError, subprocess.SubprocessError):
            pass
    return "dark" if QGuiApplication.palette().window().color().lightness() < 128 else "light"


class Worker(QThread):
    """Runs one agent turn off the UI thread."""
    token = pyqtSignal(str)
    tool = pyqtSignal(str)
    image = pyqtSignal(str)
    status = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, aura: Aura, text: str):
        super().__init__()
        self.aura, self.text = aura, text
        self.stopped = False

    def run(self):
        try:
            for event in self.aura.stream(self.text):
                if event.kind == "token":
                    self.token.emit(event.text)
                elif event.kind == "tool":
                    self.tool.emit(event.text)
                elif event.kind == "status":
                    self.status.emit(event.text)
                elif event.kind == "image":
                    self.image.emit(event.text)
                elif event.kind == "stopped":
                    self.stopped = True
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class LearnWorker(QThread):
    """Runs the background memory agent over one conversation thread."""
    learned = pyqtSignal(list)

    def __init__(self, aura: Aura, thread_id: str):
        super().__init__()
        self.aura, self.thread_id = aura, thread_id

    def run(self):
        try:
            self.learned.emit(learner.learn(self.aura.graph, self.thread_id))
        except Exception as e:  # memory is best-effort; never disturb the chat
            print(f"memory learning failed: {type(e).__name__}: {e}", file=sys.stderr)
            self.learned.emit([])


class _UiBridge(QObject):
    """Lets tools running on the worker thread act on the UI thread."""
    quit_requested = pyqtSignal()
    _call = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._call.connect(self._run, Qt.BlockingQueuedConnection)

    def _run(self, box: list):
        box[1] = box[0]()

    def call(self, fn):
        """Run fn on the UI thread and return its result (Qt objects like the clipboard require this)."""
        if QThread.currentThread() is self.thread():
            return fn()
        box = [fn, None]
        self._call.emit(box)  # blocks until _run has finished on the UI thread
        return box[1]


class WebBridge(QObject):
    """The object the page sees as `bridge`: signals push to JS, slots are called from JS."""
    init = pyqtSignal(str)
    history = pyqtSignal(str)
    token = pyqtSignal(str)
    tool = pyqtSignal(str, str, str)
    image = pyqtSignal(str, str)     # (file URL for <img>, local path for actions)
    status = pyqtSignal(str)
    turnDone = pyqtSignal(bool)  # True if the user stopped it
    memory = pyqtSignal(str)       # full snapshot for the Memory panel
    memorySaved = pyqtSignal(str)  # list of changes the learner just made
    threads = pyqtSignal(str)        # {"threads": [...], "current": id} for the history sidebar
    searchResults = pyqtSignal(str)
    lists = pyqtSignal(str)          # tasks & notes snapshot (+ count for the header badge)
    failed = pyqtSignal(str)
    note = pyqtSignal(str, str)

    def __init__(self, window: "ChatWindow"):
        super().__init__()
        self.window = window

    @pyqtSlot()
    def ready(self):
        self.window.page_ready()

    @pyqtSlot(str)
    def send(self, text: str):
        self.window.send(text)

    @pyqtSlot()
    def stop(self):
        if self.window.aura and self.window.worker:
            self.window.aura.stop()

    @pyqtSlot()
    def newChat(self):
        if self.window.aura and not self.window.worker:
            self.window.learn_now()  # learn from the conversation being archived
            self.window.aura.new_chat()
            self.window.push_threads()

    # Tasks & notes panel. Every change pushes a fresh snapshot back to the page.
    def _push_lists(self):
        self.lists.emit(json.dumps(lists.snapshot()))

    @pyqtSlot()
    def getLists(self):
        self._push_lists()

    @pyqtSlot(str, str)
    def addTask(self, text: str, due: str):
        try:
            lists.add_task(text, due)
        except ValueError as e:
            self.failed.emit(str(e))
        self._push_lists()

    @pyqtSlot(str, bool)
    def setTaskDone(self, key: str, done: bool):
        lists.set_done(key, done)
        self._push_lists()

    @pyqtSlot(str, str)
    def editTask(self, key: str, text: str):
        lists.edit_task(key, text=text)
        self._push_lists()

    @pyqtSlot(str)
    def deleteTask(self, key: str):
        lists.delete_task(key)
        self._push_lists()

    @pyqtSlot(str)
    def addNote(self, text: str):
        if text.strip():
            lists.add_note(text)
        self._push_lists()

    @pyqtSlot(str, str)
    def editNote(self, key: str, text: str):
        lists.edit_note(key, text)
        self._push_lists()

    @pyqtSlot(str)
    def deleteNote(self, key: str):
        lists.delete_note(key)
        self._push_lists()

    # Chat history sidebar.
    @pyqtSlot()
    def listThreads(self):
        self.window.push_threads()

    @pyqtSlot(str)
    def openThread(self, thread_id: str):
        w = self.window
        if not w.aura or w.worker or thread_id == w.aura.thread_id:
            return
        w.learn_now()
        w.aura.open_thread(thread_id)
        self.history.emit(_history_json(w.aura))
        w.push_threads()

    @pyqtSlot(str, str)
    def renameThread(self, thread_id: str, title: str):
        threads.rename(thread_id, title)
        self.window.push_threads()

    @pyqtSlot(str)
    def deleteThread(self, thread_id: str):
        w = self.window
        if not w.aura or (w.worker and thread_id == w.aura.thread_id):
            return
        if thread_id == w.aura.thread_id:
            w.aura.new_chat()
            self.history.emit("[]")
        threads.delete(w.aura.checkpointer, thread_id)
        w.push_threads()

    @pyqtSlot(str)
    def searchChats(self, query: str):
        if self.window.aura:
            self.searchResults.emit(json.dumps(threads.search(self.window.aura.graph, query)))

    # Memory panel. Every change pushes a fresh snapshot back to the page.
    def _push_memory(self):
        self.memory.emit(json.dumps(memory.snapshot()))

    @pyqtSlot()
    def getMemory(self):
        self._push_memory()

    @pyqtSlot(str)
    def addFact(self, text: str):
        memory.add_fact(text)
        self._push_memory()

    @pyqtSlot(str, str)
    def editFact(self, key: str, text: str):
        memory.edit_fact(key, text)
        self._push_memory()

    @pyqtSlot(str)
    def deleteFact(self, key: str):
        memory.delete_fact(key)
        self._push_memory()

    @pyqtSlot(str)
    def deleteDay(self, key: str):
        memory.delete_day(key)
        self._push_memory()

    @pyqtSlot(bool)
    def setLearning(self, enabled: bool):
        memory.set_learning(enabled)
        self._push_memory()

    @pyqtSlot()
    def forgetAll(self):
        memory.forget_everything()
        self._push_memory()

    @pyqtSlot(str)
    def copyText(self, text: str):
        QApplication.clipboard().setText(text)

    @pyqtSlot(str)
    def openUrl(self, url: str):
        QDesktopServices.openUrl(QUrl(url))

    # Actions on generated images shown in the chat.
    @pyqtSlot(str)
    def openImage(self, path: str):
        if p := _generated_image(path):
            tools.open_path(str(p))

    @pyqtSlot(str)
    def showImageInFolder(self, path: str):
        if p := _generated_image(path):
            tools.open_path(str(p.parent))

    @pyqtSlot(str)
    def copyImage(self, path: str):
        if p := _generated_image(path):
            QApplication.clipboard().setImage(QImage(str(p)))


class _Page(QWebEnginePage):
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        # Only the bundled page may load in the window; any clicked link goes to the system browser.
        if url.isLocalFile():
            return True
        QDesktopServices.openUrl(url)
        return False


class ChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.page_is_ready = False
        self.pending_notes: list[tuple[str, str]] = []
        self.quitting = False
        self.setWindowTitle(config.ASSISTANT_NAME)
        self.resize(900, 820)
        self.setMinimumSize(420, 520)
        self.worker: Worker | None = None
        self.theme = system_theme()

        self.aura, self.startup_error = None, ""
        try:
            self.aura = Aura()
        except Exception as e:
            self.startup_error = f"Can't start: {e}"

        self.view = QWebEngineView(self)
        self.view.setPage(_Page(self.view))
        self.view.page().setBackgroundColor(QColor(BACKGROUND[self.theme]))
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.setStyleSheet(f"QMainWindow {{ background: {BACKGROUND[self.theme]}; }}")
        self.setCentralWidget(self.view)

        self.web = WebBridge(self)
        channel = QWebChannel(self.view.page())
        channel.registerObject("bridge", self.web)
        self.view.page().setWebChannel(channel)
        self.view.setUrl(QUrl.fromLocalFile(str(WEB_DIR / "index.html")))

        self.bridge = _UiBridge()
        self.bridge.quit_requested.connect(lambda: QTimer.singleShot(1200, self.quit))
        tools.on_quit = self.bridge.quit_requested.emit
        tools.ui_call = self.bridge.call

        # Reminders run from startup, even while the window is hidden (e.g. autostarted at login).
        self.reminder_timer = QTimer(self, interval=15_000, timeout=self._fire_reminders)
        self.reminder_timer.start()
        QTimer.singleShot(0, self._fire_reminders)  # anything that came due while AURA was closed

        # Background memory agent: runs after the user goes quiet, and once shortly after startup.
        self.learners: list[LearnWorker] = []
        self.learn_timer = QTimer(self, singleShot=True, interval=LEARN_AFTER_IDLE_MS, timeout=self.learn_now)
        self.learn_timer.start()

        quit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        quit_shortcut.setContext(Qt.ApplicationShortcut)
        quit_shortcut.activated.connect(self.quit)

    def page_ready(self):
        """The page has connected to the bridge: send settings and the saved conversation."""
        self.web.init.emit(json.dumps({
            "assistant": config.ASSISTANT_NAME, "user": config.USERNAME,
            "theme": self.theme, "error": self.startup_error,
        }))
        self.web.history.emit(_history_json(self.aura))
        self.push_threads()
        self.web.lists.emit(json.dumps(lists.snapshot()))
        self.page_is_ready = True
        for note in self.pending_notes:
            self.web.note.emit(*note)
        self.pending_notes.clear()

    def send(self, text: str):
        if not self.aura or self.worker:
            return
        self.worker = Worker(self.aura, text)
        self.worker.token.connect(self.web.token)
        self.worker.tool.connect(lambda name: self.web.tool.emit(name, *TOOL_LABELS.get(name, (name, name))))
        self.worker.status.connect(self.web.status)
        self.worker.image.connect(lambda path: self.web.image.emit(_file_url(path), path))
        self.worker.failed.connect(self.web.failed)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def push_threads(self):
        if self.aura:
            self.web.threads.emit(json.dumps({"threads": threads.list_threads(self.aura.graph),
                                              "current": self.aura.thread_id}))

    def _on_finished(self):
        stopped = self.worker.stopped
        self.worker = None
        self.web.turnDone.emit(stopped)
        self.push_threads()  # a new chat appears / the current one moves to the top
        self.web.lists.emit(json.dumps(lists.snapshot()))  # the agent may have changed tasks or notes
        self.learn_timer.start()  # (re)start the idle countdown

    def learn_now(self):
        if not self.aura:
            return
        if self.worker:  # mid-conversation: try again after the next pause
            self.learn_timer.start()
            return
        thread_id = self.aura.thread_id
        if any(w.thread_id == thread_id and w.isRunning() for w in self.learners):
            return
        worker = LearnWorker(self.aura, thread_id)
        worker.learned.connect(self._on_learned)
        worker.finished.connect(lambda: self.learners.remove(worker))
        self.learners.append(worker)
        worker.start()

    def _on_learned(self, changes: list):
        if changes:
            self.web.memorySaved.emit(json.dumps(changes))
        self.web.memory.emit(json.dumps(memory.snapshot()))

    def _fire_reminders(self):
        self._ticks = getattr(self, "_ticks", 0) + 1
        if self.page_is_ready and self._ticks % 4 == 0:  # once a minute: due/overdue badge stays current
            self.web.lists.emit(json.dumps(lists.snapshot()))
        for _id, message, due_at in reminders.due():
            late = datetime.now() - due_at > timedelta(minutes=2)
            note = (message, f"Missed reminder, was due {due_at:%a %H:%M}" if late else f"Reminder · {due_at:%H:%M}")
            if self.page_is_ready:
                self.web.note.emit(*note)
            else:
                self.pending_notes.append(note)
            if shutil.which("notify-send"):
                subprocess.Popen(["notify-send", "-a", config.ASSISTANT_NAME, "-u", "critical",
                                  "Reminder", message])
            QApplication.alert(self)

    def closeEvent(self, event):
        """Closing the window keeps AURA running in the background (reminders, hotkey); Ctrl+Q quits."""
        if self.quitting:
            event.accept()
            return
        event.ignore()
        self.hide()
        flag = config.DATA_DIR / ".hide_hint_shown"
        if not flag.exists() and shutil.which("notify-send"):
            flag.touch()
            subprocess.Popen(["notify-send", "-a", config.ASSISTANT_NAME, f"{config.ASSISTANT_NAME} is still running",
                              "Press Super+J to bring it back. Ctrl+Q quits."])

    def quit(self):
        self.quitting = True
        if self.worker and self.aura:
            self.aura.stop()
            self.worker.wait(3000)
        for w in self.learners:
            w.wait(5000)
        QApplication.quit()

    def toggle(self, command: str):
        """Handle a message from another `main.py` launch: "toggle" hides/shows, "show" always shows."""
        if command == "ping":  # a --hidden launch checking whether AURA is already running
            return
        if command == "toggle" and self.isVisible() and self.isActiveWindow():
            self.hide()
            return
        self.show()
        self.raise_()
        self.activateWindow()
        self.view.setFocus()
        self.view.page().runJavaScript("window.focusInput && focusInput()")


def run(hidden: bool = False):
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)  # required by QtWebEngine
    app = QApplication(sys.argv)
    app.setApplicationName(config.ASSISTANT_NAME)
    app.setDesktopFileName("aura")
    QLocalServer.removeServer(instance.NAME)  # clear a stale socket left by a crash
    server = QLocalServer()
    server.listen(instance.NAME)

    window = ChatWindow()

    def on_connection():
        conn = server.nextPendingConnection()
        conn.waitForReadyRead(500)
        window.toggle(bytes(conn.readAll()).decode())
        conn.deleteLater()

    server.newConnection.connect(on_connection)
    if not hidden:
        window.show()
    sys.exit(app.exec_())
