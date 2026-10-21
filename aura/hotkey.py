"""Global hotkeys via GNOME custom keyboard shortcuts.

Wayland doesn't let apps grab keys globally, so instead the desktop runs
`main.py --toggle` on the key press; the running instance shows or hides itself.
A second shortcut (Super+Shift+J) runs `main.py --voice`: AURA comes up already listening.
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
VOICE_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/aura-voice/"
VOICE_ENTRY = f"{SCHEMA}.custom-keybinding:{VOICE_PATH}"
VOICE_BINDING = "<Super><Shift>j"
# Entries from before the project was renamed; removed on install so the key isn't bound twice.
LEGACY_PATHS = ["/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/jarvis/"]


def _gsettings(*args: str) -> str:
    return subprocess.run(["gsettings", *args], check=True, capture_output=True, text=True).stdout.strip()


def _bindings() -> list[str]:
    raw = _gsettings("get", SCHEMA, "custom-keybindings")
    return [] if raw.startswith("@as") else ast.literal_eval(raw)  # "@as []" when empty


def _gvariant_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def toggle_command(flag: str = "--toggle") -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(config.ROOT / 'main.py'))} {flag}"


def _set_entry(entry: str, name: str, command: str, binding: str) -> None:
    _gsettings("set", entry, "name", _gvariant_str(name))
    _gsettings("set", entry, "command", _gvariant_str(command))
    _gsettings("set", entry, "binding", _gvariant_str(binding))


def install(binding: str = "<Super>j") -> str:
    if not shutil.which("gsettings"):
        return ("gsettings not found (not GNOME?). Bind this command to a key in your desktop's "
                f"keyboard settings instead:\n  {toggle_command()}")
    for old in LEGACY_PATHS:
        subprocess.run(["gsettings", "reset-recursively", f"{SCHEMA}.custom-keybinding:{old}"], capture_output=True)
    bindings = [b for b in _bindings() if b not in LEGACY_PATHS]
    bindings += [p for p in (PATH, VOICE_PATH) if p not in bindings]
    _gsettings("set", SCHEMA, "custom-keybindings", str(bindings))
    _set_entry(ENTRY, config.ASSISTANT_NAME, toggle_command(), binding)
    _set_entry(VOICE_ENTRY, f"{config.ASSISTANT_NAME} (talk)", toggle_command("--voice"), VOICE_BINDING)
    return (f"Installed: {binding} now shows/hides {config.ASSISTANT_NAME} (starts it if it isn't running), "
            f"and {VOICE_BINDING} opens it listening.")


def ensure_voice() -> None:
    """Shortcuts installed before voice existed get the talk shortcut too."""
    try:
        if (binding := status()) and VOICE_PATH not in _bindings():
            install(binding)
    except (OSError, subprocess.CalledProcessError, ValueError, SyntaxError):
        pass  # best-effort: the main shortcut keeps working


def uninstall() -> str:
    bindings = _bindings()
    if PATH in bindings or VOICE_PATH in bindings:
        _gsettings("set", SCHEMA, "custom-keybindings", str([b for b in bindings if b not in (PATH, VOICE_PATH)]))
    for entry in (ENTRY, VOICE_ENTRY):
        subprocess.run(["gsettings", "reset-recursively", entry], capture_output=True)
    return "Hotkeys removed."


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
