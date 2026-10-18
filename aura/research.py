"""Research agent: a small LangGraph pipeline for questions that need several sources.

plan (2-3 search queries) -> search (DuckDuckGo, dedupe) -> read (fetch pages in parallel) -> write
(answer from those sources only, with numbered citations). The page text lives only inside this graph,
so it never floods the main conversation (or Groq's tokens-per-minute budget there).
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable, TypedDict
from urllib.parse import urlparse

import groq
from ddgs import DDGS
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from . import config

MAX_SOURCES = 5
PAGE_CHARS = 2200  # per source: 5 sources stay well inside the free tier's per-minute token budget


class Queries(BaseModel):
    queries: list[str] = Field(description="2-3 different web search queries")


class State(TypedDict, total=False):
    question: str
    queries: list[str]
    results: list[dict]   # {"title", "url", "snippet"}
    sources: list[dict]   # {"title", "url", "text"}
    answer: str


def _llm(model: str, max_tokens: int) -> ChatGroq:
    extra = {"reasoning_effort": "low"} if model.startswith("openai/gpt-oss") else {"reasoning_format": "hidden"}
    return ChatGroq(model=model, api_key=config.GROQ_API_KEY, max_tokens=max_tokens, max_retries=2,
                    request_timeout=60, **extra)


def _with_fallback(call: Callable[[ChatGroq], object], max_tokens: int):
    """Try each chat model in turn on rate limits (each has its own per-minute budget)."""
    last = None
    for model in config.CHAT_MODELS:
        try:
            return call(_llm(model, max_tokens))
        except groq.RateLimitError as e:
            last = e
    raise last


def build(status: Callable[[str], None] = lambda s: None, search=None, read=None):
    """The research graph. `search` / `read` can be swapped out (tests)."""
    from .tools import read_url
    search = search or (lambda q: DDGS().text(q, max_results=5))
    read = read or (lambda url: read_url.invoke({"url": url}))

    def plan(state: State) -> State:
        status("researching · planning searches")
        prompt = (f"Today is {datetime.now():%A %d %B %Y}. Write 2-3 short, different web search queries that "
                  f"together answer this question well:\n\n{state['question']}")
        try:
            out = _llm(config.SUMMARY_MODEL, 300).with_structured_output(Queries, method="json_schema").invoke(prompt)
            queries = [q for q in out.queries if q.strip()][:3]
        except Exception:
            queries = []
        return {"queries": queries or [state["question"]]}

    def do_search(state: State) -> State:
        status(f"researching · searching ({len(state['queries'])} queries)")
        seen_urls, seen_sites, results = set(), {}, []
        for q in state["queries"]:
            try:
                hits = search(q) or []
            except Exception:
                hits = []
            for h in hits:
                url, site = h.get("href", ""), urlparse(h.get("href", "")).netloc
                if not url or url in seen_urls or seen_sites.get(site, 0) >= 2:  # at most 2 pages per site
                    continue
                seen_urls.add(url)
                seen_sites[site] = seen_sites.get(site, 0) + 1
                results.append({"title": h.get("title", url), "url": url, "snippet": h.get("body", "")})
        return {"results": results[:MAX_SOURCES]}

    def do_read(state: State) -> State:
        status(f"researching · reading {len(state['results'])} sources")

        def one(r: dict) -> dict:
            try:
                text = read(r["url"])
            except Exception:
                text = ""
            return {"title": r["title"], "url": r["url"], "text": (text or r["snippet"])[:PAGE_CHARS]}

        with ThreadPoolExecutor(max_workers=MAX_SOURCES) as pool:
            sources = list(pool.map(one, state["results"]))
        return {"sources": [s for s in sources if s["text"].strip()]}

    def write(state: State) -> State:
        if not state["sources"]:
            return {"answer": "I couldn't find usable sources for that. Try rephrasing, or ask me to do a quick web search."}
        status("researching · writing the answer")
        numbered = "\n\n".join(f"[{i}] {s['title']} ({s['url']})\n{s['text']}" for i, s in enumerate(state["sources"], 1))
        prompt = (f"Today is {datetime.now():%A %d %B %Y}. Answer the question using ONLY the sources below. "
                  "Be clear and well organised (short paragraphs or a few bullets, no tables). Cite sources inline as "
                  "[1], [2]... right after the facts they support. If the sources disagree or don't cover something, "
                  "say so. Don't add a source list; it's appended automatically.\n\n"
                  f"Question: {state['question']}\n\nSources:\n{numbered}")
        text = _with_fallback(lambda llm: llm.invoke(prompt).content, max_tokens=config.MAX_TOKENS)
        listing = "\n".join(f"{i}. [{s['title']}]({s['url']})" for i, s in enumerate(state["sources"], 1))
        return {"answer": f"{text.strip()}\n\n**Sources**\n{listing}"}

    graph = StateGraph(State)
    graph.add_node("plan", plan)
    graph.add_node("search", do_search)
    graph.add_node("read", do_read)
    graph.add_node("write", write)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "search")
    graph.add_edge("search", "read")
    graph.add_edge("read", "write")
    graph.add_edge("write", END)
    return graph.compile()


def run(question: str, status: Callable[[str], None] = lambda s: None) -> str:
    return build(status).invoke({"question": question})["answer"]
