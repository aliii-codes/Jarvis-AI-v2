import os

import pytest

from aura import tools


def save(**kwargs) -> str:
    return tools.save_document.invoke(kwargs)


def test_paths_outside_home_are_refused(home):
    for path in ["/etc/passwd", "~/../../etc/passwd", "../outside"]:
        with pytest.raises(PermissionError):
            tools._in_home(path)


def test_symlink_escape_is_refused(home, tmp_path):
    os.symlink(tmp_path / "data", home / "sneaky")
    with pytest.raises(PermissionError):
        tools._in_home("~/sneaky")


def test_save_document_goes_where_asked(home, side_effects):
    # Regression: "save it in a new folder in Downloads" used to be ignored.
    out = save(title="Sick leave - principal", content="Dear Principal...", folder="Downloads/Sick Leave")
    target = home / "Downloads" / "Sick Leave" / "Sick leave - principal.txt"
    assert target.read_text() == "Dear Principal..." and str(target) in out
    assert side_effects == [("open", str(target))]


def test_save_document_never_overwrites(home):
    save(title="Letter", content="first", folder="Desktop")
    save(title="Letter", content="second", folder="Desktop")
    assert (home / "Desktop" / "Letter.txt").read_text() == "first"
    assert (home / "Desktop" / "Letter (2).txt").read_text() == "second"


def test_save_document_names_and_extensions(home):
    save(title="app.py", content="print(1)", folder="~/Desktop/code")
    save(title='weird/name: "x"?', content="x", folder="Desktop")
    assert (home / "Desktop" / "code" / "app.py").exists()
    assert (home / "Desktop" / "weird name x.txt").exists()


def test_save_document_refuses_outside_home():
    with pytest.raises(PermissionError):
        save(title="x", content="x", folder="/etc")


def test_save_document_default_folder(isolated):
    from aura import config
    save(title="plain", content="x")
    assert (config.DATA_DIR / "documents" / "plain.txt").exists()


def test_files_tool(home, side_effects):
    (home / "Downloads" / "os_notes.txt").write_text("lecture notes")
    (home / "Downloads" / "blob.bin").write_bytes(b"\0\1\2" * 10)
    listing = tools.files.invoke({"action": "list", "path": "Downloads"})
    assert "os_notes.txt  (13 bytes" in listing  # regression: tiny files showed as "0 KB" and read as empty
    assert tools.files.invoke({"action": "read", "path": "Downloads/os_notes.txt"}) == "lecture notes"
    assert "binary" in tools.files.invoke({"action": "read", "path": "Downloads/blob.bin"})
    assert "os_notes.txt" in tools.files.invoke({"action": "find", "name": "notes", "path": "~"})
    tools.files.invoke({"action": "open_folder", "path": "Downloads"})
    assert side_effects[-1] == ("open", str(home / "Downloads"))


def test_task_and_note_tools_hide_ids():
    # Regression: ids like "#52264a" leaked into replies; the model no longer sees them.
    assert "#" not in tools.tasks.invoke({"action": "add", "task": "Buy milk"})
    assert "#" not in tools.tasks.invoke({"action": "list"})
    assert "#" not in tools.notes.invoke({"action": "save", "text": "wifi is Coffee-5G"})
    assert "#" not in tools.notes.invoke({"action": "search", "text": "wifi"})
    assert "Completed" in tools.tasks.invoke({"action": "done", "task": "milk"})


def test_memory_and_reminder_tools_work():
    # Regression: tools named `memory` / `reminders` shadowed their modules and both broke.
    assert tools.memory.invoke({"action": "remember", "text": "Has a cat named Mochi"}).startswith("Remembered")
    assert "Mochi" in tools.memory.invoke({"action": "recall", "text": "cat"})
    assert tools.memory.invoke({"action": "remember", "text": "Has two cats", "replaces": "cat named Mochi"}).startswith("Updated")
    assert "Reminder #1 set" in tools.reminders.invoke({"action": "set", "message": "stretch", "in_minutes": 30})
    assert "stretch" in tools.reminders.invoke({"action": "list"})
    assert "Cancelled" in tools.reminders.invoke({"action": "cancel", "reminder_id": 1})
    assert "past" in tools.reminders.invoke({"action": "set", "message": "x", "at": "2020-01-01 10:00"})


def test_generated_image_guard(isolated):
    from aura import config, ui
    images = config.DATA_DIR / "images"
    images.mkdir()
    (images / "fox.jpg").write_bytes(b"jpg")
    assert ui._generated_image(str(images / "fox.jpg"))
    assert ui._generated_image("/etc/passwd") is None
