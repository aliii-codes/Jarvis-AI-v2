"""Settings loaded from `.env` (environment variables take precedence). `reload()` re-reads them at runtime."""
import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
DATA_DIR = ROOT / "Data"
DATA_DIR.mkdir(exist_ok=True)
MEMORY_DB = DATA_DIR / "memory.sqlite"

# Filled in by reload(); listed here so editors and readers know what exists.
GROQ_API_KEY: str | None = None
CEREBRAS_API_KEY: str | None = None
HF_API_KEY: str | None = None
IMAGE_MODEL = USERNAME = ASSISTANT_NAME = CHAT_MODEL = SUMMARY_MODEL = THEME = VISION_MODEL = ""
FALLBACK_MODELS: list[str] = []
CHAT_MODELS: list[str] = []
MAX_TOKENS = 1024
FOLLOWUPS = True


def reload() -> None:
    global GROQ_API_KEY, CEREBRAS_API_KEY, HF_API_KEY, IMAGE_MODEL, USERNAME, ASSISTANT_NAME, CHAT_MODEL, FALLBACK_MODELS
    global CHAT_MODELS, SUMMARY_MODEL, MAX_TOKENS, THEME, FOLLOWUPS, VISION_MODEL
    env = dotenv_values(ENV_FILE)

    def get(key: str, default: str | None = None) -> str | None:
        return os.environ.get(key) or env.get(key) or default

    GROQ_API_KEY = get("GroqAPIKey") or get("GROQ_API_KEY")
    # Optional: Cerebras hosts the same gpt-oss-120b with a separate, larger free budget.
    CEREBRAS_API_KEY = get("CerebrasAPIKey")
    HF_API_KEY = get("HuggingFaceAPIKey")
    # Hugging Face text-to-image model (served by its partner providers; falls back to Pollinations when unavailable).
    IMAGE_MODEL = get("ImageModel", "black-forest-labs/FLUX.1-schnell")

    USERNAME = get("Username", "User")
    ASSISTANT_NAME = get("Assistantname", "AURA")
    THEME = get("Theme", "system")  # system | light | dark
    FOLLOWUPS = get("Followups", "true").lower() != "false"  # gentle check-ins

    # Main model answers and calls tools; the small one only summarizes old history.
    CHAT_MODEL = get("ChatModel", "openai/gpt-oss-120b")
    # Tried in order when the previous model is rate limited (each has its own tokens-per-minute budget).
    FALLBACK_MODELS = [m.strip() for m in get("FallbackModels", "openai/gpt-oss-20b,qwen/qwen3.8-27b").split(",") if m.strip()]
    # Order tried: the main model, the same model on Cerebras (if a key is set), then the smaller fallbacks.
    cerebras = [f"cerebras:{get('CerebrasModel', 'gpt-oss-120b')}"] if CEREBRAS_API_KEY else []
    CHAT_MODELS = [CHAT_MODEL] + cerebras + [m for m in FALLBACK_MODELS if m != CHAT_MODEL]
    SUMMARY_MODEL = get("SummaryModel", "openai/gpt-oss-20b")
    # Reads attached images (the chat models are text-only); qwen3.8-27b accepts images on Groq.
    VISION_MODEL = get("VisionModel", "qwen/qwen3.8-27b")
    # Groq counts input + max_tokens against the tokens-per-minute limit (8k on the free tier),
    # so a modest cap keeps requests from waiting on rate limits. Raise it on a paid tier.
    MAX_TOKENS = int(get("MaxTokens", "1024"))


reload()
