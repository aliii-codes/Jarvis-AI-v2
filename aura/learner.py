"""Background memory agent: reads new conversation messages and updates long-term memory."""
from datetime import date

from langchain_core.messages import AIMessage, HumanMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field, field_validator

from . import config, memory

LEARN_PROMPT = """You maintain the long-term memory of {assistant}, a personal assistant for {user}.
Today is {today}. Read the new conversation and decide what is worth remembering about {user}.

Remember, as short statements without the user's name (e.g. "Studies CS at FAST, Lahore"):
- identity and life: city, work or study, languages
- preferences and habits: units, tone, apps and tools they use, routines
- people they mention, with who they are ("Sara is their sister")
- ongoing projects and goals
- upcoming events with an absolute date: turn "next Tuesday" into "on Tue 21 Oct 2026"

Do NOT remember:
- one-off requests or questions ("asked about the weather"), general facts, or the assistant's answers
- secrets of any kind: passwords, API keys, codes, card or account numbers
- health, religion, politics or sexuality, unless the user explicitly asks you to remember it
- anything already covered by a known fact; update that fact instead if it changed

Update a fact (by id) when new information changes it. Delete a fact (by id) if the user says it's no longer
true, or it was an event whose date has passed. If the user explicitly asked to remember or forget something,
the assistant has already done it; don't repeat it.

day_note: one short line about what {user} did, planned or felt today that would be useful to recall later
(e.g. "Worked on AURA's memory feature; nervous about the networks exam"), or null if nothing notable.
Only add something not already in today's notes (don't rephrase an existing note).

Most conversations contain nothing worth remembering. Then return empty lists and null.

Known facts (id: text):
{facts}

Today's notes so far:
{today_notes}

New conversation:
{excerpt}"""


class FactUpdate(BaseModel):
    id: str
    text: str


class MemoryOps(BaseModel):
    add: list[str] = Field(default_factory=list, description="New facts about the user")
    update: list[FactUpdate] = Field(default_factory=list, description="Known facts whose text should change")
    delete: list[str] = Field(default_factory=list, description="Ids of known facts that are no longer true")
    day_note: str | None = Field(None, description="One line about the user's day, or null")

    @field_validator("add", "delete", mode="before")
    @classmethod
    def _unwrap(cls, items):
        # The model sometimes wraps strings as {"description": "..."}; accept that instead of failing.
        if not isinstance(items, list):
            return items
        return [next((v for v in i.values() if isinstance(v, str)), "") if isinstance(i, dict) else i for i in items]


def _excerpt(messages: list, limit: int = 8000) -> str:
    lines = []
    for m in messages:
        if isinstance(m, HumanMessage) and not memory_is_summary(m):
            lines.append(f"User: {m.content[:1500]}")
        elif isinstance(m, AIMessage) and m.content:
            lines.append(f"Assistant: {m.content[:1500]}")
    return "\n".join(lines)[-limit:]


def memory_is_summary(m) -> bool:
    return m.additional_kwargs.get("lc_source") == "summarization"


def pending(graph, thread_id: str) -> list:
    """Messages of this thread the learner hasn't read yet."""
    messages = graph.get_state({"configurable": {"thread_id": thread_id}}).values.get("messages", [])
    last = memory.last_learned(thread_id)
    ids = [m.id for m in messages]
    if last in ids:
        return messages[ids.index(last) + 1:]
    return messages[-12:]  # first run, or the marker was summarized away; duplicates are filtered


def learn(graph, thread_id: str) -> list[str]:
    """Update memory from new messages in a thread. Returns human-readable changes for the UI."""
    new = pending(graph, thread_id)
    if not new:
        return []
    mark = lambda: new[-1].id and memory.set_last_learned(thread_id, new[-1].id)
    if not memory.learning_enabled() or not any(isinstance(m, HumanMessage) and not memory_is_summary(m) for m in new):
        mark()
        return []

    known = memory.facts()
    prompt = LEARN_PROMPT.format(
        assistant=config.ASSISTANT_NAME, user=config.USERNAME,
        today=date.today().strftime("%A %d %B %Y"),
        facts="\n".join(f"{f['id']}: {f['text']}" for f in known) or "(none yet)",
        excerpt=_excerpt(new),
        today_notes="\n".join(f"- {n}" for n in next((d["notes"] for d in memory.days(1)
                                                       if d["date"] == date.today().isoformat()), [])) or "(none)",
    )
    llm = ChatGroq(model=config.SUMMARY_MODEL, api_key=config.GROQ_API_KEY,
                   reasoning_effort="low", max_tokens=1200, max_retries=4, request_timeout=60)
    ops: MemoryOps = llm.with_structured_output(MemoryOps, method="json_schema", strict=True).invoke(prompt)

    changes, by_id = [], {f["id"]: f["text"] for f in known}
    for fact in ops.add:
        if memory.add_fact(fact):
            changes.append(f"Remembered: {fact}")
    for upd in ops.update:
        if upd.id in by_id and upd.text.strip() and upd.text != by_id[upd.id] and memory.edit_fact(upd.id, upd.text):
            changes.append(f"Updated: {upd.text}")
    for key in ops.delete:
        if key in by_id and memory.delete_fact(key):
            changes.append(f"Forgot: {by_id[key]}")
    if ops.day_note and memory.add_day_note(ops.day_note):
        changes.append(f"Noted for today: {ops.day_note}")
    mark()
    return changes
