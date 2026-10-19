"""The rate-limit / connection / bad-tool-call fallback, with fake models that fail on cue."""
import threading
from types import SimpleNamespace

import groq
import httpx
import pytest
from langchain_core.messages import HumanMessage

from aura import agent


def _error(kind: str):
    req = httpx.Request("POST", "https://api.groq.com/x")
    if kind in ("rate", "rate_long"):
        seconds = "30" if kind == "rate_long" else "1"
        return groq.RateLimitError("limit", response=httpx.Response(429, headers={"retry-after": seconds}, request=req), body=None)
    if kind == "bad_key":
        return groq.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)
    if kind == "offline":
        return groq.APIConnectionError(request=req)
    if kind == "bad_tool":
        return groq.APIError("Tool call validation failed: attempted to call tool 'translate'", request=req, body=None)
    return groq.APIError("some other error", request=req, body=None)


class Request(SimpleNamespace):
    def override(self, **kw):
        return Request(**{**self.__dict__, **kw})


def run(script: dict, monkeypatch, said="what's the weather?"):
    """script: model name -> list of outcomes ("ok" or an error kind), consumed in order."""
    monkeypatch.setattr(agent, "get_stream_writer", lambda: (lambda payload: None))
    models = [SimpleNamespace(model_name=name) for name in script]
    tried = []

    def handler(request):
        name = request.model.model_name
        outcome = script[name].pop(0)
        tried.append(f"{name}:{outcome}")
        if outcome != "ok":
            raise _error(outcome)
        return f"answer from {name}"

    middleware = agent._rate_limit_fallback(models, threading.Event())
    result = middleware.wrap_model_call(Request(model=None, state={"messages": [HumanMessage(said)]}), handler)
    return result, tried


def test_invented_tool_is_retried_on_the_same_model(monkeypatch):
    result, tried = run({"big": ["bad_tool", "ok"], "small": []}, monkeypatch)
    assert result == "answer from big" and tried == ["big:bad_tool", "big:ok"]


def test_repeated_bad_tool_moves_to_next_model(monkeypatch):
    result, tried = run({"big": ["bad_tool", "bad_tool"], "small": ["ok"]}, monkeypatch)
    assert result == "answer from small"


def test_short_rate_limit_waits_for_the_best_model(monkeypatch):
    # Back in ~1s: worth waiting rather than answering with a weaker model.
    result, tried = run({"big": ["rate", "ok"], "small": ["ok"]}, monkeypatch)
    assert result == "answer from big" and tried == ["big:rate", "big:ok"]


def test_rate_limit_and_offline_fall_back(monkeypatch):
    assert run({"big": ["rate_long"], "small": ["ok"]}, monkeypatch)[0] == "answer from small"
    assert run({"big": ["rate", "rate"], "small": ["ok"]}, monkeypatch)[0] == "answer from small"  # still busy after the wait
    result, tried = run({"big": ["offline", "ok"], "small": ["offline"]}, monkeypatch)
    assert result == "answer from big"  # after a short backoff, the first model is tried again


def test_other_errors_are_not_swallowed(monkeypatch):
    with pytest.raises(groq.APIError, match="some other error"):
        run({"big": ["other"], "small": ["ok"]}, monkeypatch)


def test_small_talk_goes_to_the_small_model_first(monkeypatch):
    from aura import config
    monkeypatch.setattr(config, "SUMMARY_MODEL", "small")
    result, tried = run({"big": [], "small": ["ok"]}, monkeypatch, said="thanks!")
    assert result == "answer from small" and tried == ["small:ok"]
    result, _ = run({"big": ["ok"], "small": []}, monkeypatch, said="thanks, now what's the capital of Peru?")
    assert result == "answer from big"  # a real question still gets the big model


def test_provider_with_bad_key_is_skipped(monkeypatch):
    # e.g. an expired Cerebras key: move on instead of failing the reply.
    result, _ = run({"big": ["rate_long"], "cerebras": ["bad_key"], "small": ["ok"]}, monkeypatch)
    assert result == "answer from small"
