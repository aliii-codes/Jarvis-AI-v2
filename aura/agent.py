"""The AURA agent: a LangGraph tool-calling agent with persistent, self-summarizing memory."""
import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Literal

import groq
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

from . import config, lists, memory
from .tools import TOOLS

SYSTEM_PROMPT = """You are {assistant}, a personal desktop assistant for {user}.
Current date and time: {now}.

- Be concise and direct. Short answers unless the user asks for detail.
- Use tools to act on the computer (open apps, play music, change volume, save documents)
  and to fetch anything current (web_search, get_weather). Never invent live facts.
- Use as few tool calls as possible. One web_search is usually enough; only read_url when the snippets don't answer it.
- For any action, always call the tool and report what it returned; never assume the outcome.
  Never say you did, or are about to do, something unless you call the tool in this same reply.
- You can translate, summarize, rewrite and explain text yourself; no tool is needed for that.
- If the user refers to "this", "what I copied" or "my clipboard", read the clipboard first.
- When asked to write something longer (email, letter, essay, code), write it and save it with save_document.
- After using a tool, briefly confirm what you did. Never promise to do something later or in the background;
  you can only act while replying. If something failed, say so and suggest trying again.
- Light Markdown is fine (bold, lists, code blocks); avoid tables and headings.
- You have long-term memory of {user}. Use it naturally, the way a friend would, without listing it.
  If they ask you to remember or forget something, call remember / forget. For older details
  (past days, things not shown below), call recall. If asked what you know about them, answer from memory.
- Things to do go in the task list (add_task / complete_task); info to keep goes in notes (save_note).
  When the user mentions finishing something on their list, complete it. A task with a time gets a reminder."""

MAX_TOOL_ROUNDS = 4
STATE_FILE = config.DATA_DIR / "state.json"


class Cancelled(Exception):
    """Raised inside the graph when the user presses Stop."""


def _is_summary(msg: BaseMessage) -> bool:
    return msg.additional_kwargs.get("lc_source") == "summarization"


@dynamic_prompt
def _system_prompt(request: ModelRequest) -> str:
    prompt = SYSTEM_PROMPT.format(
        assistant=config.ASSISTANT_NAME,
        user=config.USERNAME,
        now=datetime.now().strftime("%A %d %B %Y, %H:%M"),
    )
    sections = [prompt, memory.prompt_block()]
    urgent = lists.attention()
    if urgent:
        sections.append("Tasks due today or overdue (mention them if it fits naturally):\n"
                        + "\n".join(f"- {t['text']} ({'overdue, ' if t['overdue'] else ''}due {t['due_label']})"
                                     for t in urgent[:6]))
    return "\n\n".join(s for s in sections if s)


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


def _chat_model(name: str) -> ChatGroq:
    # max_retries=0: on a 429 we switch models immediately instead of the client silently waiting.
    extra = {"reasoning_effort": "low"} if name.startswith("openai/gpt-oss") else {"reasoning_format": "hidden"}
    # request_timeout: a stalled connection fails after 30s (then falls back) instead of hanging silently.
    return ChatGroq(model=name, api_key=config.GROQ_API_KEY, max_tokens=config.MAX_TOKENS, max_retries=0,
                    request_timeout=30, **extra)


def _retry_after(err: groq.RateLimitError) -> float:
    header = err.response.headers.get("retry-after") if err.response is not None else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = re.search(r"try again in ([\d.]+)s", str(err))
    return float(match.group(1)) if match else 10.0


# Worth retrying: a network blip or a Groq-side hiccup. (With max_retries=0 the client no longer does this.)
TRANSIENT = (groq.APIConnectionError, groq.APITimeoutError, groq.InternalServerError)


def _rate_limit_fallback(models: list[ChatGroq], cancelled: threading.Event):
    """Each Groq model has its own tokens-per-minute budget: on a 429, try the next model right away.
    Only if every model is limited, wait (visibly, and cancellably) for the soonest one to free up.
    Connection errors and 5xx get the same treatment with a short backoff."""

    @wrap_model_call
    def fallback(request: ModelRequest, handler):
        status = get_stream_writer()
        for attempt in range(4):
            waits, limited = [], False
            for i, model in enumerate(models):
                if cancelled.is_set():
                    raise Cancelled()
                try:
                    if i:
                        status({"status": f"busy · using {model.model_name.split('/')[-1]}"})
                    return handler(request.override(model=model))
                except groq.RateLimitError as err:
                    limited = True
                    waits.append(_retry_after(err))
                except TRANSIENT:
                    waits.append(2.0 * (attempt + 1))  # short backoff: 2s, 4s, 6s...
            wait = min(waits) + 0.5
            reason = "rate limited" if limited else "connection problem"
            status({"status": f"{reason} · retrying in {wait:.0f}s"})
            if cancelled.wait(wait):
                raise Cancelled()
        return handler(request.override(model=models[0]))

    return fallback


@dataclass
class Event:
    kind: Literal["token", "tool", "status", "stopped", "done"]
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

        models = [_chat_model(name) for name in config.CHAT_MODELS]
        summarizer = ChatGroq(model=config.SUMMARY_MODEL, api_key=config.GROQ_API_KEY,
                              reasoning_effort="low", max_tokens=1024, max_retries=6, request_timeout=60)
        self.graph = create_agent(
            models[0],
            tools=TOOLS,
            middleware=[
                _system_prompt,
                # Keeps memory bounded: once history passes ~4k tokens, older turns become a summary.
                SummarizationMiddleware(summarizer, trigger=("tokens", 4000), keep=("messages", 12)),
                # Old tool results (web pages, files, saved documents) are already answered; send them as
                # "[cleared]" so they don't eat Groq's tokens-per-minute budget on every later request.
                ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=2500, keep=1, clear_tool_inputs=True)]),
                # A failing tool (network down, app missing...) is reported to the model instead of crashing the turn.
                ToolErrorMiddleware(on_error=lambda e, req: f"Error: {type(e).__name__}: {e}"),
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
        self.config = {"configurable": {"thread_id": f"chat-{datetime.now():%Y%m%d-%H%M%S}"}}
        if not self._fixed_thread:
            STATE_FILE.write_text(json.dumps({"thread_id": self.thread_id}))

    def reset(self) -> None:
        """Permanently delete the current conversation (used by tests)."""
        self.checkpointer.delete_thread(self.thread_id)

    # ── running a turn ──────────────────────────────────────────────────
    def stop(self) -> None:
        self.cancelled.set()

    def stream(self, text: str) -> Iterator[Event]:
        """Run one user turn, yielding answer tokens, tool calls and status updates as they happen."""
        self.cancelled.clear()
        self._repair()
        had_text = after_tool = False
        partial: list[str] = []
        stream = self.graph.stream({"messages": [HumanMessage(text)]}, self.config,
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
                        yield Event("token", chunk.content)
                elif mode == "updates":
                    for node, update in payload.items():
                        if not isinstance(update, dict):
                            continue
                        for msg in update.get("messages", []):
                            if node == "model":
                                partial.clear()  # this model output is now saved
                                for call in getattr(msg, "tool_calls", []):
                                    after_tool = True
                                    yield Event("tool", call["name"])
                            elif isinstance(msg, AIMessage) and msg.content:
                                # e.g. the call-limit middleware's message; not streamed as tokens
                                yield Event("token", ("\n\n" if had_text else "") + msg.content)
                                had_text = True
        except Cancelled:
            stream.close()
            self._repair(partial_text="".join(partial))
            yield Event("stopped")
            return
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
        """Visible (role, text) pairs from the saved conversation."""
        out = []
        for msg in self.graph.get_state(self.config).values.get("messages", []):
            if isinstance(msg, HumanMessage) and not _is_summary(msg):
                out.append(("user", msg.content))
            elif isinstance(msg, AIMessage) and msg.content:
                out.append(("assistant", msg.content))
        return out
