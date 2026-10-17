"""Desktop integration: start hidden at login, and appear in the app menu (freedesktop .desktop files)."""
import os
import shlex
import sys
from pathlib import Path

from . import config

_XDG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
_DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
AUTOSTART = _XDG / "autostart" / "aura.desktop"
LAUNCHER = _DATA / "applications" / "aura.desktop"  # name matches app.setDesktopFileName("aura")


def _entry(extra_args: str, autostart: bool) -> str:
    cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(config.ROOT / 'main.py'))}{extra_args}"
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={config.ASSISTANT_NAME}",
        "Comment=Your desktop AI companion",
        f"Exec={cmd}",
        "Icon=user-available-symbolic",
        "Terminal=false",
        "Categories=Utility;",
        "StartupWMClass=aura",
    ]
    if autostart:
        lines += ["X-GNOME-Autostart-enabled=true", "X-GNOME-Autostart-Delay=5", "NoDisplay=true"]
    return "\n".join(lines) + "\n"


def install() -> str:
    for path, args, auto in [(AUTOSTART, " --hidden", True), (LAUNCHER, "", False)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_entry(args, auto))
    return (f"{config.ASSISTANT_NAME} will start in the background when you log in "
            f"({AUTOSTART}),\nand is now in your app menu ({LAUNCHER}).")


def uninstall() -> str:
    for path in (AUTOSTART, LAUNCHER):
        path.unlink(missing_ok=True)
    return "Removed autostart and app menu entries."
