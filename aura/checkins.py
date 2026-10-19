"""Gentle check-ins: at most once a day, a short, specific question based on what AURA knows
("How did the networks exam go?"). Most days there's nothing worth asking, and nothing is shown."""
from datetime import date, datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from . import config, memory
from .memory import META, _db, _lock

FLAG = "aura_checkin"  # marks check-in messages in the conversation
EARLIEST_HOUR, LATEST_HOUR = 8, 22

PROMPT = """You write the optional daily check-in that {assistant} may send {user}. It is now {today}.

Using what you know below, is there ONE specific thing worth gently asking about today?
Good reasons: an event that just happened or happens today (an exam, interview, trip, appointment),
something {user} was stressed, sick or excited about in the last few days, or a plan they mentioned.

If yes, write one short, warm, casual line (under 20 words), like a friend texting, e.g.
"How did the networks exam go?" or "Feeling any better today?"
Mind the time: for something still ahead today, wish them well ("Good luck at the dentist later!");
for something that already happened, ask how it went.
If nothing specific and recent fits, return null. Most days should be null.

Never: a generic "how are you", reminders or nagging about tasks and deadlines (they get reminders),
anything already asked in a recent check-in, saying that you remember things, or sensitive topics.

What you know about {user}:
{facts}

Recent days:
{days}

Recent check-ins (don't repeat these):
{recent}"""


class CheckIn(BaseModel):
    message: str | None = Field(None, description="The check-in line, or null if nothing fits today")
    about: str = Field("", description="A few words on what it's about, to avoid repeats")


def _state() -> dict:
    with _lock:
        item = _db().get(META, "checkins")
    return item.value if item else {"last_checked": None, "sent": []}


def _save(state: dict) -> None:
    with _lock:
        _db().put(META, "checkins", state)


def due(now: datetime | None = None) -> bool:
    """Check-ins are on, it's daytime, and today hasn't been considered yet."""
    now = now or datetime.now()
    return (config.FOLLOWUPS and EARLIEST_HOUR <= now.hour < LATEST_HOUR
            and _state().get("last_checked") != now.date().isoformat())


def generate(llm=None) -> str | None:
    """Decide today's check-in (or None). Marks today as considered either way, so it runs once a day."""
    state = _state()
    state["last_checked"] = date.today().isoformat()
    _save(state)

    facts = memory.facts()
    days = [d for d in memory.days(7) if d["date"] >= (date.today() - timedelta(days=7)).isoformat()]
    if not facts and not days:
        return None  # nothing known yet: nothing to ask about
    recent = [s for s in state.get("sent", []) if s["date"] >= (date.today() - timedelta(days=14)).isoformat()]
    prompt = PROMPT.format(
        assistant=config.ASSISTANT_NAME, user=config.USERNAME, today=datetime.now().strftime("%A %d %B %Y, %H:%M"),
        facts="\n".join(f"- {f['text']}" for f in facts) or "(nothing yet)",
        days="\n".join(f"- {d['date']}: " + "; ".join(d["notes"]) for d in days) or "(no notes)",
        recent="\n".join(f"- {s['date']}: {s['message']}" for s in recent) or "(none)",
    )
    llm = llm or ChatGroq(model=config.SUMMARY_MODEL, api_key=config.GROQ_API_KEY,
                          reasoning_effort="low", max_tokens=400, max_retries=3, request_timeout=60)
    result: CheckIn = llm.with_structured_output(CheckIn, method="json_schema").invoke(prompt)
    message = (result.message or "").strip()
    if not message or message.lower() in ("null", "none"):
        return None
    state["sent"] = (state.get("sent", []) + [{"date": date.today().isoformat(), "about": result.about,
                                               "message": message}])[-30:]
    _save(state)
    return message


def deliver(aura, message: str) -> bool:
    """Put the check-in in today's conversation, starting a new chat if the current one isn't from today.
    Returns True if a new chat was started."""
    snapshot = aura.graph.get_state(aura.config)
    last = snapshot.created_at
    today = date.today()
    started_new = not last or datetime.fromisoformat(last).astimezone().date() != today
    if started_new:
        aura.new_chat()
    aura.graph.update_state(aura.config, {"messages": [AIMessage(message, additional_kwargs={FLAG: True})]},
                            as_node="model")
    return started_new
