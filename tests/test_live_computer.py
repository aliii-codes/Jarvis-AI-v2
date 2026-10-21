"""Live: the "computer guy" requests with the real model, against a fake mailbox, fake history and fake projects.
Run with:  pytest --live -s tests/test_live_computer.py
"""
from datetime import datetime, timedelta

import pytest

from aura import memory, modes
from test_computer import FakeSmtp, _firefox, code_folders, gmail  # noqa: F401  (fixtures)


def ask(aura, message):
    called, reply = [], []
    for e in aura.stream(message):
        if e.kind == "tool":
            called.append(e.text)
        elif e.kind == "token":
            reply.append(e.text)
    text = "".join(reply) or (aura.history()[-1][1] if aura.history() else "")
    print(f"> {message}\n  tools={called}\n  {text[:300]!r}\n")
    return called, text


@pytest.mark.live
def test_check_mail_reply_and_send_only_when_approved(aura_agent, gmail):
    called, reply = ask(aura_agent, "hey aura check what's in my email, any new mails?")
    assert "email:unread" in called and "Sara" in reply
    called, reply = ask(aura_agent, "reply to sara that I'll send the notes tonight")
    assert any(c.startswith("email_draft") for c in called) and "Draft" in reply
    assert not FakeSmtp.sent  # drafting never sends
    called, _ = ask(aura_agent, "yes send it")
    assert "email:send" in called and len(FakeSmtp.sent) == 1
    assert FakeSmtp.sent[0]["To"] == "sara@example.com"


@pytest.mark.live
def test_play_the_recent_song_from_history(aura_agent, home, side_effects):
    now = datetime.now()
    _firefox(home, [("https://www.youtube.com/watch?v=BBBBBBBBBBB", "How to center a div - YouTube",
                     now - timedelta(minutes=20)),
                    ("https://www.youtube.com/watch?v=AAAAAAAAAAA", "Imagine Dragons - Believer (Official Video) - YouTube",
                     now - timedelta(hours=2))])
    called, _ = ask(aura_agent, "hey aura check my yt history and play the recent song")
    assert "browser:youtube_history" in called
    assert ("browser", "https://www.youtube.com/watch?v=AAAAAAAAAAA") in side_effects  # the song, not the tutorial


@pytest.mark.live
def test_dev_mode(aura_agent, code_folders, side_effects):
    memory.add_fact("Dev music: https://www.youtube.com/watch?v=jfKfPfyJRdk (lofi hip hop radio)")
    called, _ = ask(aura_agent, "set up dev mode: ask me which project, open it in vs code and play my dev music")
    assert "modes:save" in called and "jfKfPfyJRdk" in modes.prompt_block()
    side_effects.clear()
    called, reply = ask(aura_agent, "yo aura, dev mode")
    if "project:open" not in called:  # it should ask which project first
        assert "project" in reply.lower()
        called, _ = ask(aura_agent, "moodline")
    assert "project:open" in called
    assert ("launch", ["code", str(code_folders / "Documents/Moodline")]) in side_effects
    assert any(e[0] == "browser" and "jfKfPfyJRdk" in e[1] for e in side_effects)

