"""Test isolation: every test gets its own data folder and fake home, and nothing opens on the desktop.

Run:  pytest            (offline tests, no API calls)
      pytest --live     (also the live regression against Groq; needs GroqAPIKey in .env)
"""
import subprocess
import sys
import webbrowser
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aura import agent, memory, reminders, tools  # noqa: E402
from aura import config as aura_config  # noqa: E402  (pytest hooks need the name `config`)


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="run tests that call the Groq API")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs --live (calls the Groq API)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls the real Groq API (run with --live)")


class SideEffects(list):
    """Records what would have opened on the user's desktop."""


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    data, home = tmp_path / "data", tmp_path / "home"
    data.mkdir()
    for folder in ("Downloads", "Desktop", "Documents"):
        (home / folder).mkdir(parents=True)

    monkeypatch.setattr(aura_config, "DATA_DIR", data)
    monkeypatch.setattr(aura_config, "MEMORY_DB", data / "memory.sqlite")
    monkeypatch.setattr(memory, "DB", data / "memory_store.sqlite")
    monkeypatch.setattr(memory, "_store", None)  # drop any cached connection to another test's store
    monkeypatch.setattr(reminders, "DB", data / "reminders.sqlite")
    monkeypatch.setattr(agent, "STATE_FILE", data / "state.json")
    monkeypatch.setattr(tools, "HOME", home)
    if not aura_config.GROQ_API_KEY:
        monkeypatch.setattr(aura_config, "GROQ_API_KEY", "test-key")  # offline tests never call the API

    real_which = tools.shutil.which
    monkeypatch.setattr(tools.shutil, "which", lambda n: None if n == "xdg-user-dir" else real_which(n))

    effects = SideEffects()
    monkeypatch.setattr(tools, "open_path", lambda p: effects.append(("open", str(p))))
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: effects.append(("browser", url)) or True)

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            effects.append(("launch", cmd))

    monkeypatch.setattr(tools.subprocess, "Popen", FakePopen)
    yield effects
    memory._store = None


@pytest.fixture
def home(isolated) -> Path:
    return tools.HOME


@pytest.fixture
def side_effects(isolated) -> SideEffects:
    return isolated


@pytest.fixture
def aura_agent():
    """An Aura on a fixed test thread. Constructing it makes no API calls."""
    return agent.Aura(thread_id="test")
