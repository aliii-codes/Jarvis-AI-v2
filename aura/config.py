"""Settings loaded from `.env` (environment variables take precedence)."""
import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "Data"
DATA_DIR.mkdir(exist_ok=True)

_env = dotenv_values(ROOT / ".env")


def _get(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key) or _env.get(key) or default


GROQ_API_KEY = _get("GroqAPIKey") or _get("GROQ_API_KEY")
HF_API_KEY = _get("HuggingFaceAPIKey")

USERNAME = _get("Username", "User")
ASSISTANT_NAME = _get("Assistantname", "AURA")

# Main model answers and calls tools; the small one only summarizes old history.
CHAT_MODEL = _get("ChatModel", "openai/gpt-oss-120b")
# Tried in order when the previous model is rate limited (each has its own tokens-per-minute budget).
FALLBACK_MODELS = [m.strip() for m in _get("FallbackModels", "openai/gpt-oss-20b,qwen/qwen3.8-27b").split(",") if m.strip()]
CHAT_MODELS = [CHAT_MODEL] + [m for m in FALLBACK_MODELS if m != CHAT_MODEL]
SUMMARY_MODEL = _get("SummaryModel", "openai/gpt-oss-20b")
# Groq counts input + max_tokens against the tokens-per-minute limit (8k on the free tier),
# so a modest cap keeps requests from waiting on rate limits. Raise it on a paid tier.
MAX_TOKENS = int(_get("MaxTokens", "1024"))

MEMORY_DB = DATA_DIR / "memory.sqlite"
