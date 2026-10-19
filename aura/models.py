"""Chat models by name, across providers, and a provider-neutral way to classify their errors.

Names are Groq model ids ("openai/gpt-oss-120b"), or "cerebras:<model>" for Cerebras, which hosts the same
gpt-oss-120b with its own (larger) free budget. Cerebras is OpenAI-compatible, so it goes through
langchain-openai.
"""
import re

from langchain_groq import ChatGroq

from . import config

CEREBRAS_URL = "https://api.cerebras.ai/v1"


def chat_model(name: str, max_tokens: int | None = None, timeout: float = 30, max_retries: int = 0):
    """max_retries=0 by default: on a 429 the caller switches models immediately instead of the client
    silently waiting; timeout: a stalled connection fails (then falls back) instead of hanging."""
    max_tokens = max_tokens or config.MAX_TOKENS
    if name.startswith("cerebras:"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=name.split(":", 1)[1], base_url=CEREBRAS_URL, api_key=config.CEREBRAS_API_KEY,
                          max_tokens=max_tokens, max_retries=max_retries, timeout=timeout, reasoning_effort="low")
    extra = {"reasoning_effort": "low"} if name.startswith("openai/gpt-oss") else {"reasoning_format": "hidden"}
    return ChatGroq(model=name, api_key=config.GROQ_API_KEY, max_tokens=max_tokens, max_retries=max_retries,
                    request_timeout=timeout, **extra)


def label(model) -> str:
    """Short name for the status line: "gpt-oss-20b", "gpt-oss-120b (Cerebras)"."""
    name = getattr(model, "model_name", "") or ""
    short = name.split("/")[-1]
    return f"{short} (Cerebras)" if CEREBRAS_URL in str(getattr(model, "openai_api_base", "") or "") else short


def _status(err: Exception) -> int | None:
    code = getattr(err, "status_code", None)
    if code is None:
        code = getattr(getattr(err, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


def classify(err: Exception) -> str | None:
    """'rate' (429), 'offline' (network, timeout, 5xx), 'bad_tool' (model called a tool that wasn't offered),
    'skip' (bad key / model not available on this provider), or None (a real error: don't swallow it)."""
    text = str(err).lower()
    code = _status(err)
    if code == 429 or "rate limit" in text:
        return "rate"
    if "tool call validation failed" in text:
        return "bad_tool"
    if code in (401, 403, 404):
        return "skip"
    name = type(err).__name__
    if (code is not None and code >= 500) or "Connection" in name or "Timeout" in name:
        return "offline"
    return None


def retry_after(err: Exception) -> float:
    response = getattr(err, "response", None)
    header = response.headers.get("retry-after") if response is not None and hasattr(response, "headers") else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = re.search(r"try again in ([\d.]+)s", str(err))
    return float(match.group(1)) if match else 10.0
