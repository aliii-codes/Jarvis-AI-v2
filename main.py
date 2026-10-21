"""AURA: a desktop AI assistant built on LangGraph."""
import argparse
import logging

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AURA desktop assistant")
    parser.add_argument("--toggle", action="store_true", help="show/hide the running window (for a hotkey)")
    parser.add_argument("--voice", action="store_true", help="show the window and start listening (for a hotkey)")
    parser.add_argument("--install-hotkey", nargs="?", const="<Super>j", metavar="KEY",
                        help="add a GNOME shortcut that toggles AURA (default: <Super>j)")
    parser.add_argument("--uninstall-hotkey", action="store_true", help="remove the GNOME shortcut")
    parser.add_argument("--hidden", action="store_true", help="start in the background (used at login)")
    parser.add_argument("--install-autostart", action="store_true",
                        help="start AURA hidden at login and add it to the app menu")
    parser.add_argument("--uninstall-autostart", action="store_true", help="undo --install-autostart")
    args = parser.parse_args()

    if args.install_autostart or args.uninstall_autostart:
        from aura import desktop
        print(desktop.install() if args.install_autostart else desktop.uninstall())
    elif args.install_hotkey or args.uninstall_hotkey:
        from aura import hotkey
        print(hotkey.install(args.install_hotkey) if args.install_hotkey else hotkey.uninstall())
    else:
        # Single instance: if AURA is already running (e.g. hotkey press), just show/toggle it.
        # Checked before importing the UI/agent so the hotkey responds instantly.
        from aura.instance import send_to_running
        # A --hidden launch (login) never pops up an already-running window.
        if args.hidden and send_to_running("ping"):
            pass
        elif not send_to_running("voice" if args.voice else "toggle" if args.toggle else "show"):
            logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
            from aura.ui import run
            run(hidden=args.hidden, listen=args.voice)
