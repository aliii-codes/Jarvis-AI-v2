"""Single-instance handoff. Kept import-light so the hotkey responds instantly."""
import getpass

from PyQt5.QtNetwork import QLocalSocket

NAME = f"aura-{getpass.getuser()}"


def send_to_running(command: str) -> bool:
    """If AURA is already running, pass it the command ("show" or "toggle") and return True."""
    sock = QLocalSocket()
    sock.connectToServer(NAME)
    if not sock.waitForConnected(500):
        return False
    sock.write(command.encode())
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True
