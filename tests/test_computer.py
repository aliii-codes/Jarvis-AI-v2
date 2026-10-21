"""The "computer guy" features: Gmail (read, draft, send only when approved), YouTube watch history,
code projects and modes. Uses a fake mailbox, fake browser history files and a fake home folder."""
import sqlite3
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from aura import agent, config, mail, modes, projects, settings, tools, watch_history


# ── a fake Gmail ─────────────────────────────────────────────────────────
def _raw(uid, sender, subject, body, html=False):
    m = EmailMessage()
    m["From"], m["Subject"], m["Message-ID"] = sender, subject, f"<msg{uid}@example.com>"
    m["Date"] = "Tue, 20 Oct 2026 09:15:00 +0500"
    if html:
        m.set_content("<html><body><p>Hi Ali,</p><p>Are we still on for <b>Friday</b>?</p></body></html>",
                      subtype="html")
    else:
        m.set_content(body)
    return m.as_bytes()


class FakeImap:
    def __init__(self, box):
        self.box, self.commands = box, []

    def select(self, folder, readonly=False):
        self.commands.append(("select", folder, readonly))
        return "OK", [b"1"]

    def uid(self, command, *args):
        self.commands.append((command, *args))
        if command == "search":
            return "OK", [b" ".join(k.encode() for k in self.box)]
        if command == "fetch":
            return "OK", [(b"1 (BODY[] {1})", self.box[args[0]])] if args[0] in self.box else [None]
        return "OK", [None]

    def logout(self):
        pass


class FakeSmtp:
    sent: list = []

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        pass

    def send_message(self, msg):
        FakeSmtp.sent.append(msg)


@pytest.fixture
def gmail(monkeypatch):
    monkeypatch.setattr(config, "GMAIL_ADDRESS", "ali@gmail.com")
    monkeypatch.setattr(config, "GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setattr(config, "USERNAME", "Ali")
    box = {"41": _raw(41, "Sara Khan <sara@example.com>", "Notes for Friday", "Can you send me the OS notes?"),
           "42": _raw(42, "Prof. Malik <malik@uni.edu>", "Meeting", "", html=True)}
    imap = FakeImap(box)
    monkeypatch.setattr(mail, "_imap", lambda *a: imap)
    FakeSmtp.sent = []
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSmtp)
    return imap


def test_unread_lists_newest_first_and_leaves_them_unread(gmail):
    items = mail.unread()
    assert [m["subject"] for m in items] == ["Meeting", "Notes for Friday"]
    assert items[1]["from"] == "Sara Khan" and "OS notes" in items[1]["preview"]
    assert ("select", "INBOX", True) in gmail.commands  # read-only mailbox
    assert all(c[2] == "(BODY.PEEK[])" for c in gmail.commands if c[0] == "fetch")  # PEEK: stays unread


def test_html_only_email_is_readable(gmail):
    body = mail.read("42")["body"]
    assert "Are we still on for" in body and "<b>" not in body


def test_reply_draft_threads_correctly(gmail):
    d = mail.draft("Sure, sending them tonight.\n\nAli", reply_to="41")
    assert d["to"] == "sara@example.com" and d["subject"] == "Re: Notes for Friday"
    assert d["in_reply_to"] == "<msg41@example.com>"
    assert "Draft 1" in mail.format_draft(d) and "> Sure, sending them tonight." in mail.format_draft(d)


def test_nothing_is_sent_without_the_user_approving_the_shown_draft(gmail):
    mail.new_turn("reply to Sara's email")
    mail.draft("Sure!\n\nAli", reply_to="41")
    assert "hasn't seen" in mail.send()[0] and not FakeSmtp.sent      # same turn as drafting
    mail.new_turn("no wait, make it longer")
    assert "doesn't clearly approve" in mail.send()[0] and not FakeSmtp.sent
    mail.new_turn("yes but add that I'll be late")
    assert not any("Sent" in r for r in mail.send()) and not FakeSmtp.sent
    mail.new_turn("looks good, send it")
    assert mail.send() == ["Sent to sara@example.com: Re: Notes for Friday"]
    msg = FakeSmtp.sent[0]
    assert msg["In-Reply-To"] == "<msg41@example.com>" and msg["From"] == "Ali <ali@gmail.com>"
    assert ("store", "41", "+FLAGS", "(\\Seen \\Answered)") in gmail.commands
    assert mail.drafts() == []                                          # sent drafts are gone


def test_new_email_needs_a_real_address(gmail):
    with pytest.raises(ValueError):
        mail.draft("hi", to="sara")
    assert mail.draft("hi", to="Sara <sara@example.com>", subject="Hey")["to"] == "sara@example.com"


def test_email_tools(gmail):
    out = tools.email.invoke({"action": "unread"})
    assert "[id 41]" in out and "Sara Khan <sara@example.com>" in out
    shown = tools.email_draft.invoke({"drafts": [{"body": "On my way.\n\nAli", "reply_to_id": "42"},
                                                 {"body": "Thanks!\n\nAli", "reply_to_id": "41"}]})
    assert "Draft 1" in shown and "Draft 2" in shown and shown.endswith("tell me what to change.")
    assert tools.email_draft.return_direct  # the user sees exactly what would be sent
    mail.new_turn("send them all")
    assert tools.email.invoke({"action": "send"}).count("Sent to") == 2


def test_email_not_set_up_says_how(monkeypatch):
    monkeypatch.setattr(config, "GMAIL_ADDRESS", None)
    with pytest.raises(mail.MailError, match="Settings"):
        mail.unread()


def test_gmail_settings_check_the_login(monkeypatch):
    monkeypatch.setattr(settings, "_write", lambda k, v: None)
    monkeypatch.setattr(config, "reload", lambda: None)
    with pytest.raises(ValueError, match="address first"):
        settings.apply("gmail_password", "abcd efgh ijkl mnop")
    monkeypatch.setattr(config, "GMAIL_ADDRESS", "ali@gmail.com")
    checked = []
    monkeypatch.setattr(mail, "check_login", lambda a, p: checked.append((a, p)))
    assert settings.apply("gmail_password", "abcd efgh ijkl mnop")[0] == "Gmail connected."
    assert checked == [("ali@gmail.com", "abcdefghijklmnop")]
    with pytest.raises(ValueError):
        settings.apply("gmail_address", "not an address")


# ── YouTube watch history ────────────────────────────────────────────────
def _firefox(home, visits):
    profile = home / ".mozilla/firefox/abc.default-esr"
    profile.mkdir(parents=True)
    db = sqlite3.connect(profile / "places.sqlite")
    db.executescript("CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT);"
                     "CREATE TABLE moz_historyvisits (id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER);")
    for i, (url, title, when) in enumerate(visits, 1):
        db.execute("INSERT INTO moz_places VALUES (?, ?, ?)", (i, url, title))
        db.execute("INSERT INTO moz_historyvisits (place_id, visit_date) VALUES (?, ?)", (i, int(when.timestamp() * 1e6)))
    db.commit()
    db.close()


def _chromium(home, visits):
    profile = home / ".config/chromium/Default"
    profile.mkdir(parents=True)
    db = sqlite3.connect(profile / "History")
    db.executescript("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT);"
                     "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER);")
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    for i, (url, title, when) in enumerate(visits, 1):
        db.execute("INSERT INTO urls VALUES (?, ?, ?)", (i, url, title))
        micros = int((when.astimezone(timezone.utc) - epoch).total_seconds() * 1e6)
        db.execute("INSERT INTO visits (url, visit_time) VALUES (?, ?)", (i, micros))
    db.commit()
    db.close()


def test_recent_youtube_across_browsers(home):
    now = datetime.now().replace(microsecond=0)
    _firefox(home, [("https://www.youtube.com/watch?v=AAAAAAAAAAA&t=30", "(3) Believer - Imagine Dragons - YouTube",
                     now - timedelta(hours=3)),
                    ("https://www.youtube.com/watch?v=BBBBBBBBBBB", "Lofi beats to code to - YouTube",
                     now - timedelta(hours=1)),
                    ("https://www.youtube.com/results?search_query=x", "x - YouTube", now),
                    ("https://www.youtube.com/watch?v=AAAAAAAAAAA", "Believer - Imagine Dragons - YouTube",
                     now - timedelta(hours=5))])
    _chromium(home, [("https://www.youtube.com/watch?v=CCCCCCCCCCC", "Playdate - Lindsey Stirling - YouTube",
                      (now - timedelta(minutes=10)).astimezone())])
    videos = watch_history.recent()
    assert [v["title"] for v in videos] == ["Playdate - Lindsey Stirling", "Lofi beats to code to",
                                           "Believer - Imagine Dragons"]  # newest first, once each, no searches
    assert videos[0]["browser"] == "Chromium" and videos[2]["url"] == "https://www.youtube.com/watch?v=AAAAAAAAAAA"
    assert "Playdate" in tools.browser.invoke({"action": "youtube_history"})


def test_no_history_is_said_plainly(home):
    assert "No YouTube videos" in tools.browser.invoke({"action": "youtube_history"})


# ── projects and modes ───────────────────────────────────────────────────
@pytest.fixture
def code_folders(home, monkeypatch):
    for path in ["Documents/Moodline/.git", "Documents/Jarvis-AI-v2/pyproject.toml", "Documents/data_agent/main.py",
                 "Documents/GIT CLONES/Osintgram/requirements.txt", "Documents/GIT CLONES/Osintgram-old/.git",
                 "Osintgram-fork/.git", "Documents/Moodline/node_modules/x/package.json"]:
        p = home / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.mkdir() if path.endswith(".git") else p.write_text("")
    monkeypatch.setattr(projects, "editor", lambda: "code")
    return home


def test_find_projects_by_spoken_name(code_folders):
    assert projects.find("moodline")[0].name == "Moodline"
    assert projects.find("mood line")[0].name == "Moodline"
    assert projects.find("jarvis")[0].name == "Jarvis-AI-v2"
    assert projects.find("data agent")[0].name == "data_agent"
    assert projects.find("osintgram")[0].name == "Osintgram"   # inside a plain "GIT CLONES" folder
    assert projects.find("spaceship") == []
    assert all(p.name != "x" for p in projects.candidates())   # node_modules isn't a project


def test_project_tool_opens_vs_code_or_asks(code_folders, side_effects):
    assert tools.project.invoke({"action": "open", "name": "Moodline"}) == "Opened ~/Documents/Moodline in VS Code."
    assert side_effects[-1] == ("launch", ["code", str(code_folders / "Documents/Moodline")])
    assert "No project folder" in tools.project.invoke({"action": "open", "name": "spaceship"})
    listed = tools.project.invoke({"action": "find", "name": "osintgram"})
    assert "Osintgram-fork" in listed and "GIT CLONES/Osintgram" in listed


def test_modes_are_saved_and_in_the_prompt():
    m = tools.modes.invoke({"action": "save", "name": "dev",
                            "steps": "Ask which project, open it in VS Code, play https://youtu.be/abc on YouTube"})
    assert m.startswith("Saved dev mode")
    tools.modes.invoke({"action": "save", "name": "Dev Mode", "steps": "Open the project, play https://youtu.be/xyz"})
    assert len(modes.modes()) == 1 and "youtu.be/xyz" in modes.prompt_block()  # same mode, updated
    assert tools.modes.invoke({"action": "delete", "name": "dev mode"}) == "Deleted dev mode."
    assert modes.prompt_block() == ""


def test_tool_selection_follows_the_conversation():
    wanted = agent._wanted_tools
    assert {"email", "email_draft"} <= wanted([HumanMessage("any new mails?")])
    assert "browser" in wanted([HumanMessage("check my yt history and play the recent song")])
    # "dev mode" -> "Which project?" -> "Moodline": the answer still gets the project tools
    convo = [HumanMessage("yo aura, dev mode"), AIMessage("Which project?"), HumanMessage("Moodline")]
    assert {"project", "browser"} <= wanted(convo)
    # "yes" after a draft still has the email tool to send it
    drafted = [HumanMessage("reply to sara"), AIMessage("", tool_calls=[
        {"name": "email_draft", "args": {}, "id": "1", "type": "tool_call"}]), HumanMessage("yes")]
    assert "email" in wanted(drafted)
