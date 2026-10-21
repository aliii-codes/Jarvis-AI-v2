"""Gmail over IMAP/SMTP with an app password (Settings → Email).

Reading never changes anything (messages are fetched with PEEK, so they stay unread).
Sending is two-step on purpose: AURA drafts a reply and shows it, and only sends after the user's next
message approves it ("send it", "yes", "looks good"). That rule is enforced here, not left to the model,
so a misheard command or an instruction hidden inside an email can't send anything by itself.
"""
import email
import imaplib
import re
import smtplib
import threading
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, getaddresses, make_msgid, parseaddr, parsedate_to_datetime

from bs4 import BeautifulSoup

from . import config

IMAP_HOST, SMTP_HOST = "imap.gmail.com", "smtp.gmail.com"
TIMEOUT = 20
MAX_BODY = 4000  # characters of an email the model reads

_APPROVE = re.compile(r"\b(send|sent|yes|yeah|yep|yup|ok|okay|sure|go ahead|go for it|do it|looks good|lgtm|"
                      r"perfect|fine|approved?|confirm(ed)?)\b", re.I)
_HOLD = re.compile(r"\b(no|nope|don'?t|do not|not yet|wait|hold|stop|cancel|change|edit|instead|but|rewrite|"
                   r"shorter|longer)\b", re.I)

_lock = threading.Lock()
_drafts: dict[str, dict] = {}   # number ("1", "2"...) -> draft; kept until sent or discarded
_turn = {"n": 0, "text": ""}    # the user's current message, set by the agent at the start of each turn


class MailError(ValueError):
    """A problem to tell the user about (not set up, wrong password, offline...)."""


def configured() -> bool:
    return bool(config.GMAIL_ADDRESS and config.GMAIL_APP_PASSWORD)


def new_turn(user_text: str) -> None:
    """Called by the agent before each user turn."""
    with _lock:
        _turn["n"] += 1
        _turn["text"] = user_text or ""


# ── connections ──────────────────────────────────────────────────────────
def _imap(address: str | None = None, password: str | None = None) -> imaplib.IMAP4_SSL:
    address, password = address or config.GMAIL_ADDRESS, password or config.GMAIL_APP_PASSWORD
    if not (address and password):
        raise MailError("Email isn't set up yet. Add your Gmail address and an app password in Settings → Email.")
    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST, timeout=TIMEOUT)
        conn.login(address, password.replace(" ", ""))
    except imaplib.IMAP4.error:
        raise MailError("Gmail rejected the login. Check the address and app password in Settings → Email.")
    except OSError:
        raise MailError("Couldn't reach Gmail. Are you online?")
    return conn


def check_login(address: str, password: str) -> None:
    """Used by Settings before saving: raises MailError if Gmail won't accept them."""
    _imap(address, password).logout()


# ── reading ──────────────────────────────────────────────────────────────
def _header(msg, name: str) -> str:
    raw = msg.get(name, "")
    try:
        return " ".join(str(make_header(decode_header(raw))).split())
    except (ValueError, LookupError):
        return " ".join(str(raw).split())


def _body(msg) -> str:
    """The readable text of an email: the plain-text part, or the HTML part turned into text."""
    plain = html = None
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        if part.get_content_type() == "text/plain" and plain is None:
            plain = text
        elif part.get_content_type() == "text/html" and html is None:
            html = text
    if plain is None and html is not None:
        plain = BeautifulSoup(html, "html.parser").get_text("\n")
    text = re.sub(r"\n\s*\n+", "\n\n", (plain or "").replace("\r", ""))
    return text.strip()


def _summary(uid: str, msg) -> dict:
    name, addr = parseaddr(_header(msg, "From"))
    try:
        when = parsedate_to_datetime(msg.get("Date")).astimezone().strftime("%a %d %b %H:%M")
    except (TypeError, ValueError):
        when = ""
    return {"id": uid, "from": name or addr, "from_addr": addr, "subject": _header(msg, "Subject") or "(no subject)",
            "date": when, "message_id": msg.get("Message-ID", ""), "references": msg.get("References", ""),
            "reply_to": parseaddr(_header(msg, "Reply-To"))[1] or addr}


def _fetch(conn, uid: str):
    status, data = conn.uid("fetch", uid, "(BODY.PEEK[])")  # PEEK: reading doesn't mark it as read
    if status != "OK" or not data or not isinstance(data[0], tuple):
        raise MailError("That email isn't in the inbox any more.")
    return email.message_from_bytes(data[0][1])


def unread(limit: int = 10) -> list[dict]:
    """Newest unread emails in the inbox, with a short preview."""
    conn = _imap()
    try:
        conn.select("INBOX", readonly=True)
        _, data = conn.uid("search", None, "UNSEEN")
        uids = data[0].split()[-limit:][::-1]
        out = []
        for uid in uids:
            msg = _fetch(conn, uid.decode())
            item = _summary(uid.decode(), msg)
            item["preview"] = " ".join(_body(msg).split())[:200]
            out.append(item)
        return out
    finally:
        conn.logout()


def read(uid: str) -> dict:
    conn = _imap()
    try:
        conn.select("INBOX", readonly=True)
        msg = _fetch(conn, uid)
        item = _summary(uid, msg)
        body = _body(msg)
        item["body"] = body[:MAX_BODY] + ("\n[…cut]" if len(body) > MAX_BODY else "")
        return item
    finally:
        conn.logout()


# ── drafting and sending ─────────────────────────────────────────────────
def draft(body: str, reply_to: str = "", to: str = "", subject: str = "") -> dict:
    """Store a draft (a reply to email `reply_to`, or a new email to `to`). Nothing is sent."""
    body = (body or "").strip()
    if not body:
        raise MailError("The draft is empty.")
    if reply_to:
        original = read(reply_to)
        subject = original["subject"] if original["subject"].lower().startswith("re:") else f"Re: {original['subject']}"
        to = original["reply_to"]
        thread = {"in_reply_to": original["message_id"],
                  "references": f"{original['references']} {original['message_id']}".strip(),
                  "original_id": reply_to, "original_from": original["from"]}
    else:
        addresses = [a for _, a in getaddresses([to]) if "@" in a]
        if not addresses:
            raise MailError(f"'{to}' isn't an email address.")
        to, thread = ", ".join(addresses), {}
        subject = subject.strip() or "(no subject)"
    with _lock:
        number = str(max((int(k) for k in _drafts), default=0) + 1)
        _drafts[number] = d = {"number": number, "to": to, "subject": subject, "body": body,
                               "turn": _turn["n"], **thread}
    return d


def drafts() -> list[dict]:
    with _lock:
        return [dict(d) for d in _drafts.values()]


def discard(which: str = "all") -> int:
    with _lock:
        keys = list(_drafts) if which == "all" else [which] if which in _drafts else []
        for k in keys:
            del _drafts[k]
    return len(keys)


def _approved(d: dict) -> str | None:
    """Why this draft can't be sent yet, or None if the user has seen it and said to send."""
    if d["turn"] >= _turn["n"]:
        return "the user hasn't seen this draft yet. Show it and ask whether to send it"
    text = _turn["text"]
    if not _APPROVE.search(text) or _HOLD.search(text):
        return "the user's latest message doesn't clearly approve sending. Ask them to confirm"
    return None


def send(which: str = "all") -> list[str]:
    """Send approved drafts. Returns one line per draft (sent, or why not)."""
    with _lock:
        targets = list(_drafts.values()) if which == "all" else [_drafts[which]] if which in _drafts else []
    if not targets:
        return ["There's no draft to send. Write one first."]
    results = []
    for d in targets:
        if reason := _approved(d):
            results.append(f"Not sent (draft {d['number']}): {reason}.")
            continue
        _smtp_send(d)
        if d.get("original_id"):
            _mark_answered(d["original_id"])
        with _lock:
            _drafts.pop(d["number"], None)
        results.append(f"Sent to {d['to']}: {d['subject']}")
    return results


def _smtp_send(d: dict) -> None:
    msg = EmailMessage()
    msg["From"] = formataddr((config.USERNAME, config.GMAIL_ADDRESS))
    msg["To"], msg["Subject"] = d["to"], d["subject"]
    msg["Message-ID"] = make_msgid(domain=config.GMAIL_ADDRESS.split("@")[-1])
    if d.get("in_reply_to"):  # keeps the reply in the same Gmail conversation
        msg["In-Reply-To"], msg["References"] = d["in_reply_to"], d["references"]
    msg.set_content(d["body"])
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=TIMEOUT) as smtp:
            smtp.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD.replace(" ", ""))
            smtp.send_message(msg)  # Gmail files it under Sent by itself
    except smtplib.SMTPAuthenticationError:
        raise MailError("Gmail rejected the login. Check the app password in Settings → Email.")
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"Couldn't send the email ({type(e).__name__}).")


def _mark_answered(uid: str) -> None:
    """The original email: read and answered, as if replied to in Gmail. Best-effort."""
    try:
        conn = _imap()
        try:
            conn.select("INBOX")
            conn.uid("store", uid, "+FLAGS", "(\\Seen \\Answered)")
        finally:
            conn.logout()
    except (MailError, imaplib.IMAP4.error, OSError):
        pass


def format_draft(d: dict) -> str:
    """How a draft is shown to the user: exactly what will be sent."""
    head = f"**Draft {d['number']}** · reply to {d['original_from']}" if d.get("original_from") else f"**Draft {d['number']}**"
    quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in d["body"].splitlines())
    return f"{head}\n**To:** {d['to']}  \n**Subject:** {d['subject']}\n\n{quoted}"
