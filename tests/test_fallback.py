"""The rate-limit / connection / bad-tool-call fallback, with fake models that fail on cue."""
import threading
from types import SimpleNamespace

import groq
import httpx
import pytest

from aura import agent


def _error(kind: str):
    req = httpx.Request("POST", "https://api.groq.com/x")
    if kind == "rate":
        return groq.RateLimitError("limit", response=httpx.Response(429, headers={"retry-after": "0"}, request=req), body=None)
    if kind == "offline":
        return groq.APIConnectionError(request=req)
    if kind == "bad_tool":
        return groq.APIError("Tool call validation failed: attempted to call tool 'translate'", request=req, body=None)
    return groq.APIError("some other error", request=req, body=None)


class Request(SimpleNamespace):
    def override(self, **kw):
        return Request(**{**self.__dict__, **kw})


def run(script: dict, monkeypatch):
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
    result = middleware.wrap_model_call(Request(model=None), handler)
    return result, tried


def test_invented_tool_is_retried_on_the_same_model(monkeypatch):
    result, tried = run({"big": ["bad_tool", "ok"], "small": []}, monkeypatch)
    assert result == "answer from big" and tried == ["big:bad_tool", "big:ok"]


def test_repeated_bad_tool_moves_to_next_model(monkeypatch):
    result, tried = run({"big": ["bad_tool", "bad_tool"], "small": ["ok"]}, monkeypatch)
    assert result == "answer from small"


def test_rate_limit_and_offline_fall_back(monkeypatch):
    assert run({"big": ["rate"], "small": ["ok"]}, monkeypatch)[0] == "answer from small"
    result, tried = run({"big": ["offline", "ok"], "small": ["offline"]}, monkeypatch)
    assert result == "answer from big"  # after a short backoff, the first model is tried again


def test_other_errors_are_not_swallowed(monkeypatch):
    with pytest.raises(groq.APIError, match="some other error"):
        run({"big": ["other"], "small": ["ok"]}, monkeypatch)
