"""Live regression against Groq: everyday requests in one conversation, including follow-ups.

Checks which tool the model chose and what actually happened, not exact wording.
Run with:  pytest --live -s   (takes a minute or two; uses your Groq quota)
"""
import re
from unittest import mock

import pytest

from aura import lists, memory, reminders, tools

SCENARIO = [
    # (message, expected tool event or None for no tool, check(state) or None)
    ("hey", None, None),
    ("what's the weather in Lahore?", "get_weather", None),
    ("add buy milk to my list", "tasks:add", lambda _: [t["text"].lower() for t in lists.tasks()] == ["buy milk"]),
    ("what's on my list?", "tasks:list", None),
    ("done with the milk", "tasks:done", lambda _: lists.tasks() == []),
    ("remind me in 30 minutes to stretch", "reminders:set", lambda _: len(reminders.pending()) == 1),
    ("cancel it", "reminders:cancel", lambda _: reminders.pending() == []),
    ("note: cafe wifi is Coffee-5G", "notes:save", lambda _: any("Coffee-5G" in n["text"] for n in lists.notes())),
    ("what was the cafe wifi?", "notes:search", lambda s: "Coffee-5G" in s["reply"]),
    ("remember my sister is Sara", "memory:remember", lambda _: any("Sara" in f["text"] for f in memory.facts())),
    ("what's my sister's name?", None, lambda s: "Sara" in s["reply"]),
    ("open firefox", "app:open", lambda s: any(e[0] == "launch" for e in s["effects"])),
    ("play believer by imagine dragons", "browser:play_youtube", lambda s: any("youtube.com" in str(e) for e in s["effects"])),
    ("save a short haiku about rain in Desktop/poems", "save_document",
     lambda _: any((tools.HOME / "Desktop" / "poems").glob("*"))),
    ("open that folder", "files:open_folder", lambda s: ("open", str(tools.HOME / "Desktop" / "poems")) in s["effects"]),
    ("translate what I copied to english", "clipboard:read", lambda s: "later" in s["reply"].lower()),
    ("what's in my Downloads folder?", "files:list", lambda s: "os_notes" in s["reply"]),
]


@pytest.mark.live
def test_everyday_conversation(aura_agent, home, side_effects, monkeypatch):
    (home / "Downloads" / "os_notes.txt").write_text("lecture notes")
    copied = "Ich komme morgen später."

    def fake_ui_call(fn):
        board = mock.Mock(text=mock.Mock(return_value=copied))
        with mock.patch("PyQt5.QtWidgets.QApplication.clipboard", return_value=board):
            return fn()

    monkeypatch.setattr(tools, "ui_call", fake_ui_call)
    failures = []
    for message, expected_tool, check in SCENARIO:
        side_effects.clear()
        called, reply = [], []
        for event in aura_agent.stream(message):
            if event.kind == "tool":
                called.append(event.text)
            elif event.kind == "token":
                reply.append(event.text)
        state = {"reply": "".join(reply), "effects": list(side_effects)}
        print(f"> {message}\n  tools={called} reply={state['reply'][:90]!r}")
        if expected_tool and expected_tool not in called:
            failures.append(f"{message!r}: expected {expected_tool}, got {called}")
        if expected_tool is None and message == "hey" and called:
            failures.append(f"{message!r}: expected no tool, got {called}")
        if check and not check(state):
            failures.append(f"{message!r}: outcome check failed (reply: {state['reply'][:80]!r})")
        if re.search(r"#[0-9a-f]{6}\b", state["reply"]):
            failures.append(f"{message!r}: leaked an internal id")
    assert not failures, "\n".join(failures)


@pytest.mark.live
def test_replying_to_a_check_in(aura_agent):
    # The check-in is the first message of today's chat; the reply must read as a natural continuation.
    from aura import checkins
    memory.add_fact("Networks exam on Sat 17 Oct 2026")
    checkins.deliver(aura_agent, "How did the networks exam go?")
    reply = "".join(e.text for e in aura_agent.stream("it went really well actually, I think I aced it!") if e.kind == "token")
    print("reply:", reply)
    assert any(w in reply.lower() for w in ("great", "awesome", "congrat", "nice", "glad", "amazing", "well done", "fantastic"))
