"""The AURA agent: a LangGraph tool-calling agent with persistent, self-summarizing memory."""
import json
import re
import sqlite3
import threading
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterator, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    SummarizationMiddleware,
    ToolErrorMiddleware,
    dynamic_prompt,
    wrap_model_call,
)
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langchain_groq import ChatGroq
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.config import get_stream_writer

from . import attachments as attachment_files
from . import config, documents, lists, memory, threads
from . import models as model_lib
from .tools import TOOLS

SYSTEM_PROMPT = """You are {assistant}, {user}'s desktop assistant. Now: {now}.
Next 7 days: {week} (use these exact dates; don't compute weekdays yourself).
- Be concise. Light Markdown only (no tables or headings). Never show internal ids like #a1b2c3.
- Act through tools, and only claim what a tool actually did in this reply; never promise to do things later.
  If a tool fails, say so. Never invent live facts: use web_search (one search is usually enough).
- Translate, summarize and write yourself. Show code and short texts in chat; use save_document only when asked
  for a file or for long pieces, passing the folder they named and telling them the real path.
- Images only via generate_image (shown in chat automatically): never write image links; a repeat request means a new image.
- Questions about {user}'s own past or life ("what did I...", "when is my...") that the facts below don't answer:
  call memory recall before saying you don't know. Never web_search personal questions.
- Questions about {user}'s own notes, lectures or files: use documents, and name the file in plain words
  ("according to networks.md, ...").
- Questions needing several sources (comparisons, recommendations, in-depth): use research, then present its
  answer keeping the [1]-style citations and the Sources list. Quick facts: web_search.
- "this" / "what I copied" means the clipboard. Things to do go in tasks, info to keep in notes, facts about
  {user} in memory. Use what you know about {user} naturally, without reciting it."""

MAX_TOOL_ROUNDS = 4
DIRECT_TOOLS = {t.name for t in TOOLS if t.return_direct}  # their output is shown as the reply
STATE_FILE = config.DATA_DIR / "state.json"


class Cancelled(Exception):
    """Raised inside the graph when the user presses Stop."""


def _image_of(msg: ToolMessage) -> str | None:
    """Path of a generated image attached to a tool result, if the file still exists."""
    artifact = getattr(msg, "artifact", None)
    path = artifact.get("image") if isinstance(artifact, dict) else None
    if not path and msg.name == "generate_image":
        # Images made before results carried an artifact: the path is only in the result text.
        match = re.search(r"(/\S+/images/\S+\.(?:jpg|png))", str(msg.content))
        path = match.group(1) if match else None
    images = (config.DATA_DIR / "images").resolve()
    return path if path and Path(path).is_file() and Path(path).resolve().is_relative_to(images) else None


# gpt-oss likes typographic look-alikes (non-breaking hyphen U+2011, narrow no-break space U+202F...).
# They look fine but break copy-paste: a copied "Coffee‑5G" wifi password wouldn't work. Use plain ones.
_PLAIN = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u00a0": " ", "\u202f": " ", "\u2007": " "})


def _plain(text: str) -> str:
    return text.translate(_PLAIN)


def _is_summary(msg: BaseMessage) -> bool:
    return msg.additional_kwargs.get("lc_source") == "summarization"


@dynamic_prompt
def _system_prompt(request: ModelRequest) -> str:
    today = datetime.now()
    prompt = SYSTEM_PROMPT.format(
        assistant=config.ASSISTANT_NAME,
        user=config.USERNAME,
        now=today.strftime("%A %d %B %Y, %H:%M"),
        # Models get weekday -> date arithmetic wrong (a "Mon" gym session was saved on Wednesday): spell it out.
        week=", ".join((today + timedelta(days=i)).strftime("%a %Y-%m-%d") for i in range(7)),
    )
    sections = [prompt, memory.prompt_block()]
    urgent = lists.attention()
    if urgent:
        sections.append("Tasks due today or overdue (mention them if it fits naturally):\n"
                        + "\n".join(f"- {t['text']} ({'overdue, ' if t['overdue'] else ''}due {t['due_label']})"
                                     for t in urgent[:6]))
    return "\n\n".join(s for s in sections if s)


# Every tool description is sent with every request, so only send the tools a message plausibly needs.
CORE_TOOLS = {"web_search", "get_weather", "memory"}
TOOL_TRIGGERS = {
    "read_url": r"https?://|www\.|\.(com|org|net|io|pk|pdf)\b|\b(link|article|page|url|website)\b",
    "app": r"\b(open|close|launch|start|quit|kill|run)\b|\bapp\b",
    "browser": r"\b(open|youtube|play|google|website|site|song|music|video|watch|browser)\b",
    "set_volume": r"\b(volume|mute|unmute|louder|quieter|sound)\b",
    "save_document": r"\b(save|file|write|draft|document|letter|email|essay|report|downloads?|desktop|folder)\b",
    "files": r"\b(file|files|folder|dir|directory|downloads?|desktop|documents|read|find|pdf|open)\b|\.(txt|py|md|pdf)\b",
    "generate_image": r"\b(image|picture|pic|photo|draw|drawing|paint|art|wallpaper|logo|illustration|sketch|generate)\b",
    "clipboard": r"\b(clipboard|copied|copy|paste|this)\b",
    "reminders": r"\b(remind|reminder|reminders|alarm|timer|tomorrow|tonight)\b|\bin \d+ ?(min|hour|h)\b|\bat \d",
    "tasks": r"\b(task|tasks|todo|to-do|to do|list|done|finished|complete|need to|have to|deadline|due)\b",
    "notes": r"\b(note|notes|jot|write down|wifi|password|code)\b",
    "quit_aura": r"\b(bye|goodbye|quit|exit|close yourself|good night)\b",
    "documents": r"\b(notes|lecture|lectures|slides|pdf|document|documents|my files|course|syllabus|chapter|according to)\b",
    "research": r"\b(research|compare|comparison|vs|versus|pros and cons|which is better|best \w+ for|in depth|"
                r"deep dive|recommend|look into|worth it|should i (buy|get|use|choose))\b",
}


def _wanted_tools(messages: list) -> set[str]:
    """Core tools, plus groups triggered by the latest user message or used in the last couple of turns
    (so follow-ups like "cancel it" or "do it again" still have their tools)."""
    humans = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage) and not _is_summary(m)]
    if not humans:
        return set(TOOL_TRIGGERS) | CORE_TOOLS
    text = str(messages[humans[-1]].content).lower()
    wanted = set(CORE_TOOLS) | {name for name, pattern in TOOL_TRIGGERS.items() if re.search(pattern, text)}
    if documents.folders():  # questions about their files rarely contain a tell-tale keyword
        wanted.add("documents")
    recent_start = humans[-3] if len(humans) >= 3 else 0
    for m in messages[recent_start:]:
        if isinstance(m, AIMessage):
            wanted |= {call["name"] for call in m.tool_calls}
    return wanted


@wrap_model_call
def _select_tools(request: ModelRequest, handler):
    wanted = _wanted_tools(request.state["messages"])
    return handler(request.override(tools=[t for t in request.tools if getattr(t, "name", None) in wanted]))


@wrap_model_call
def _wrap_up(request: ModelRequest, handler):
    """After a few rounds of tool calls in one turn, take the tools away so the model answers
    with what it has, instead of searching until the hard call limit cuts it off silently."""
    messages = request.state["messages"]
    start = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage) and not _is_summary(m)),
                default=0)
    rounds = sum(1 for m in messages[start:] if isinstance(m, AIMessage) and m.tool_calls)
    if rounds >= MAX_TOOL_ROUNDS:
        request = request.override(tools=[])
    return handler(request)


SHORT_WAIT = 4.0  # if the best model frees up within this many seconds, wait for it rather than answer worse
SMALL_TALK = re.compile(r"^\s*(hi|hey|hello|yo|sup|hiya|thanks|thank you|thx|ty|ok|okay|k|cool|nice|great|lol|haha|"
                        r"good (morning|night|evening|afternoon)|bye|gn|how are you|what'?s up)\b[\s!.?]*$", re.I)


def _small_talk(messages: list) -> bool:
    """A greeting or thanks at the start of a turn: the small model answers that just as well,
    which saves the big model's per-minute budget for real questions."""
    if not messages or not isinstance(messages[-1], HumanMessage) or _is_summary(messages[-1]):
        return False
    text = str(messages[-1].content)
    return len(text.split()) <= 6 and bool(SMALL_TALK.match(text))


def _rate_limit_fallback(models: list, cancelled: threading.Event):
    """Every model (and provider) has its own tokens-per-minute budget. On a 429: wait briefly if the best
    model frees up within seconds, otherwise try the next model right away; only if all are limited, wait
    (visibly, cancellably) for the soonest. Connection errors and 5xx get a short backoff, a model that calls
    a tool it wasn't offered gets one more try, and a provider with a bad key is skipped."""

    @wrap_model_call
    def fallback(request: ModelRequest, handler):
        status = get_stream_writer()
        order = list(models)
        if _small_talk(request.state["messages"]):
            small = [m for m in order if getattr(m, "model_name", "") == config.SUMMARY_MODEL]
            order = small + [m for m in order if m not in small]
        for attempt in range(4):
            waits, limited = [], False
            for i, model in enumerate(order):
                if cancelled.is_set():
                    raise Cancelled()
                if i:
                    status({"status": f"busy · using {model_lib.label(model)}"})
                retried = False
                while True:
                    try:
                        return handler(request.override(model=model))
                    except Cancelled:
                        raise
                    except Exception as err:
                        kind = model_lib.classify(err)
                        if kind is None:
                            raise
                        if kind == "bad_tool" and not retried:  # a model slip: asking again usually works
                            retried = True
                            continue
                        wait = model_lib.retry_after(err) if kind == "rate" else 0
                        if kind == "rate" and i == 0 and attempt == 0 and not retried and wait <= SHORT_WAIT:
                            retried = True
                            status({"status": f"busy · back in {wait:.0f}s"})
                            if cancelled.wait(wait + 0.3):
                                raise Cancelled()
                            continue
                        if kind == "rate":
                            limited = True
                            waits.append(wait)
                        elif kind == "offline":
                            waits.append(2.0 * (attempt + 1))  # short backoff: 2s, 4s, 6s...
                        break  # rate / offline / skip / repeated bad tool call: next model
            if not waits:  # nothing to wait for (bad keys, tool slips): one last try raises the real error
                break
            wait = min(waits) + 0.5
            reason = "rate limited" if limited else "connection problem"
            status({"status": f"{reason} · retrying in {wait:.0f}s"})
            if cancelled.wait(wait):
                raise Cancelled()
        return handler(request.override(model=order[0]))

    return fallback


@dataclass
class Event:
    kind: Literal["token", "tool", "image", "status", "stopped", "done"]
    text: str = ""


class Aura:
    def __init__(self, thread_id: str | None = None):
        if not config.GROQ_API_KEY:
            raise RuntimeError("GroqAPIKey is missing from .env")
        self.cancelled = threading.Event()
        self._fixed_thread = thread_id is not None
        self.config = {"configurable": {"thread_id": thread_id or self._load_thread()}}
        self._conn = sqlite3.connect(config.MEMORY_DB, check_same_thread=False)
        self.checkpointer = SqliteSaver(self._conn)

        models = [model_lib.chat_model(name) for name in config.CHAT_MODELS]
        summarizer = ChatGroq(model=config.SUMMARY_MODEL, api_key=config.GROQ_API_KEY,
                              reasoning_effort="low", max_tokens=1024, max_retries=6, request_timeout=60)
        self.graph = create_agent(
            models[0],
            tools=TOOLS,
            middleware=[
                _system_prompt,
                # Keeps requests small: past ~2k tokens of history, older turns become a summary. History was
                # most of each request, so this roughly doubles how often the big model fits in the free budget.
                SummarizationMiddleware(summarizer, trigger=("tokens", 2000), keep=("messages", 6)),
                # Old tool results (web pages, files, saved documents) are already answered; send them as
                # "[cleared]" so they don't eat Groq's tokens-per-minute budget on every later request.
                ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=1500, keep=1, clear_tool_inputs=True)]),
                # A failing tool (network down, app missing...) is reported to the model instead of crashing the turn.
                ToolErrorMiddleware(on_error=lambda e, req: f"Error: {type(e).__name__}: {e}"),
                _select_tools,
                _wrap_up,
                _rate_limit_fallback(models, self.cancelled),
                ModelCallLimitMiddleware(run_limit=MAX_TOOL_ROUNDS + 4),  # backstop only
            ],
            checkpointer=self.checkpointer,
        )

    # ── conversation threads ────────────────────────────────────────────
    @staticmethod
    def _load_thread() -> str:
        try:
            return json.loads(STATE_FILE.read_text())["thread_id"]
        except (OSError, ValueError, KeyError):
            return "main"  # the conversation from before threads existed

    @property
    def thread_id(self) -> str:
        return self.config["configurable"]["thread_id"]

    def new_chat(self) -> None:
        """Start a fresh conversation; the old one stays saved in the database."""
        self.open_thread(f"chat-{datetime.now():%Y%m%d-%H%M%S}")

    def open_thread(self, thread_id: str) -> None:
        """Switch to another conversation (and make it the one AURA reopens on next launch)."""
        self.config = {"configurable": {"thread_id": thread_id}}
        if not self._fixed_thread:
            STATE_FILE.write_text(json.dumps({"thread_id": thread_id}))

    def reset(self) -> None:
        """Permanently delete the current conversation (used by tests)."""
        self.checkpointer.delete_thread(self.thread_id)

    # ── running a turn ──────────────────────────────────────────────────
    def stop(self) -> None:
        self.cancelled.set()

    def stream(self, text: str, attachments: list[dict] | None = None) -> Iterator[Event]:
        """Run one user turn, yielding answer tokens, tool calls and status updates as they happen.
        `attachments` (from attachments.add_file / add_bytes) are read into text before the model sees them."""
        self.cancelled.clear()
        self._repair()
        message = HumanMessage(text)
        if attachments:
            parts = []
            for meta in attachments:
                yield Event("status", f"reading {meta['name']}")
                parts.append(attachment_files.to_text(meta))
            content = "\n\n".join(([text] if text.strip() else []) + parts)
            message = HumanMessage(content, additional_kwargs={
                "display_text": text,  # what the chat shows; the model also gets the extracted text
                "attachments": [{k: m[k] for k in ("id", "name", "kind", "path")} for m in attachments]})
        had_text = after_tool = used_tool = False
        partial: list[str] = []
        stream = self.graph.stream({"messages": [message]}, self.config,
                                   stream_mode=["messages", "updates", "custom"])
        try:
            for mode, payload in stream:
                if self.cancelled.is_set():
                    raise Cancelled()
                if mode == "custom" and isinstance(payload, dict) and "status" in payload:
                    yield Event("status", payload["status"])
                elif mode == "messages":
                    chunk, meta = payload
                    # Only the agent's own model node; skip the summarizer's tokens.
                    if meta.get("langgraph_node") == "model" and isinstance(chunk, AIMessageChunk) and chunk.content:
                        if had_text and after_tool:
                            yield Event("token", "\n\n")  # text written before and after a tool call
                            partial.clear()
                        had_text, after_tool = True, False
                        partial.append(chunk.content)
                        yield Event("token", _plain(chunk.content))
                elif mode == "updates":
                    for node, update in payload.items():
                        if not isinstance(update, dict):
                            continue
                        for msg in update.get("messages", []):
                            if node == "model":
                                partial.clear()  # this model output is now saved
                                for call in getattr(msg, "tool_calls", []):
                                    after_tool = used_tool = True
                                    action = (call.get("args") or {}).get("action")
                                    yield Event("tool", f"{call['name']}:{action}" if action else call["name"])
                            elif node == "tools" and isinstance(msg, ToolMessage):
                                if image := _image_of(msg):
                                    yield Event("image", image)
                                elif msg.name in DIRECT_TOOLS and msg.content:
                                    # return_direct: the tool's output *is* the reply (e.g. research with citations)
                                    yield Event("token", ("\n\n" if had_text else "") + _plain(str(msg.content)))
                                    had_text = True
                            elif isinstance(msg, AIMessage) and msg.content:
                                # e.g. the call-limit middleware's message; not streamed as tokens
                                yield Event("token", ("\n\n" if had_text else "") + _plain(msg.content))
                                had_text = True
        except Cancelled:
            stream.close()
            self._repair(partial_text="".join(partial))
            threads.touch(self.graph, self.thread_id)
            yield Event("stopped")
            return
        if not had_text and not used_tool:
            # A model (usually a fallback under rate limits) returned nothing: never show a blank reply.
            yield Event("token", "Sorry, I didn't get an answer back. Please try again.")
        threads.touch(self.graph, self.thread_id)
        yield Event("done")

    def _repair(self, partial_text: str = "") -> None:
        """Keep the saved conversation valid after a Stop or a crash: every tool call needs a result
        (Groq rejects the history otherwise), and a half-written reply is kept rather than lost."""
        messages = self.graph.get_state(self.config).values.get("messages", [])
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        fixes: list[BaseMessage] = []
        if last_ai is not None and last_ai.tool_calls:
            answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
            fixes += [ToolMessage("Cancelled by the user.", tool_call_id=call["id"])
                      for call in last_ai.tool_calls if call["id"] not in answered]
        if partial_text.strip():
            fixes.append(AIMessage(partial_text.strip() + " …"))
        if fixes:
            self.graph.update_state(self.config, {"messages": fixes}, as_node="tools")

    def history(self) -> list[tuple[str, str]]:
        """Visible (role, text) pairs from the saved conversation; role "image" carries a file path."""
        out = []
        for msg in self.graph.get_state(self.config).values.get("messages", []):
            if isinstance(msg, HumanMessage) and not _is_summary(msg):
                files = msg.additional_kwargs.get("attachments")
                text = msg.additional_kwargs.get("display_text", msg.content)
                out.append(("user", text, files) if files else ("user", text))
            elif isinstance(msg, AIMessage) and msg.content:
                role = "checkin" if msg.additional_kwargs.get("aura_checkin") else "assistant"
                out.append((role, _plain(msg.content)))
            elif isinstance(msg, ToolMessage) and (image := _image_of(msg)):
                out.append(("image", image))
            elif isinstance(msg, ToolMessage) and msg.name in DIRECT_TOOLS and msg.content:
                out.append(("assistant", _plain(str(msg.content))))  # shown to the user as the reply
        return out
