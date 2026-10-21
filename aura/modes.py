"""Modes: named routines the user sets up once and starts by saying the name ("dev mode", "study mode").

A mode is a short list of steps in plain words ("ask which project, open it in VS Code, play <url> on YouTube").
They're in the system prompt, so AURA carries them out with its normal tools when the user says the name.
"""
from .lists import _now
from .memory import _all, _db, _lock, _norm

MODES = ("modes",)


def _key(name: str) -> str:
    return _norm(name).replace(" mode", "").strip().replace(" ", "-") or "mode"


def modes() -> list[dict]:
    with _lock:
        return sorted(({"id": i.key, **i.value} for i in _all(MODES)), key=lambda m: m["name"])


def save(name: str, steps: str) -> dict:
    """Add a mode, or replace the steps of the one with this name."""
    name, steps = " ".join(name.split()), steps.strip()
    if not name or not steps:
        raise ValueError("A mode needs a name and its steps.")
    if not name.lower().endswith("mode"):
        name += " mode"
    m = {"name": name, "steps": steps, "updated": _now()}
    with _lock:
        _db().put(MODES, _key(name), m)
    return m


def delete(name: str) -> bool:
    with _lock:
        if not _db().get(MODES, _key(name)):
            return False
        _db().delete(MODES, _key(name))
        return True


def prompt_block() -> str:
    rows = modes()
    if not rows:
        return ""
    return ("Modes (when the user says one, carry out its steps with your tools; ask only what the steps say to ask):\n"
            + "\n".join(f"- {m['name']}: {m['steps']}" for m in rows))
