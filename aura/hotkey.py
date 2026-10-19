"""Global hotkey via a GNOME custom keyboard shortcut.

Wayland doesn't let apps grab keys globally, so instead the desktop runs
`main.py --toggle` on the key press; the running instance shows or hides itself.
"""
import ast
import shlex
import shutil
import subprocess
import sys

from . import config

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/aura/"
ENTRY = f"{SCHEMA}.custom-keybinding:{PATH}"
# Entries from before the project was renamed; removed on install so the key isn't bound twice.
LEGACY_PATHS = ["/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/jarvis/"]


def _gsettings(*args: str) -> str:
    return subprocess.run(["gsettings", *args], check=True, capture_output=True, text=True).stdout.strip()


def _bindings() -> list[str]:
    raw = _gsettings("get", SCHEMA, "custom-keybindings")
    return [] if raw.startswith("@as") else ast.literal_eval(raw)  # "@as []" when empty


def _gvariant_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def toggle_command() -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(config.ROOT / 'main.py'))} --toggle"


def install(binding: str = "<Super>j") -> str:
    if not shutil.which("gsettings"):
        return ("gsettings not found (not GNOME?). Bind this command to a key in your desktop's "
                f"keyboard settings instead:\n  {toggle_command()}")
    for old in LEGACY_PATHS:
        subprocess.run(["gsettings", "reset-recursively", f"{SCHEMA}.custom-keybinding:{old}"], capture_output=True)
    bindings = [b for b in _bindings() if b not in LEGACY_PATHS]
    if PATH not in bindings:
        bindings.append(PATH)
    _gsettings("set", SCHEMA, "custom-keybindings", str(bindings))
    _gsettings("set", ENTRY, "name", _gvariant_str(config.ASSISTANT_NAME))
    _gsettings("set", ENTRY, "command", _gvariant_str(toggle_command()))
    _gsettings("set", ENTRY, "binding", _gvariant_str(binding))
    return f"Installed: {binding} now shows/hides {config.ASSISTANT_NAME} (starts it if it isn't running)."


def uninstall() -> str:
    bindings = _bindings()
    if PATH in bindings:
        _gsettings("set", SCHEMA, "custom-keybindings", str([b for b in bindings if b != PATH]))
    subprocess.run(["gsettings", "reset-recursively", ENTRY], capture_output=True)
    return "Hotkey removed."


def status() -> str | None:
    """The installed key binding (e.g. "<Super>j"), or None if the shortcut isn't installed."""
    if not shutil.which("gsettings"):
        return None
    try:
        if PATH not in _bindings():
            return None
        return _gsettings("get", ENTRY, "binding").strip("'\"") or None
    except subprocess.CalledProcessError:
        return None
