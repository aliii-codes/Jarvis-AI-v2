"""The Settings panel's backend: what it shows, and applying a change (validated, saved to .env)."""
import re
import threading

import groq
from dotenv import set_key

from . import config, desktop, hotkey, memory

REPLY_LENGTHS = {"short": 512, "normal": 1024, "long": 2048}
# speech, safety-classifier and tiny-context models (allam: 4k context, no tool calling) would break AURA
_NOT_CHAT = re.compile(r"whisper|guard|orpheus|tts|playai|distil|allam", re.I)
_models_cache: dict[str, list[str]] = {}
_apply_lock = threading.Lock()  # saves run on background threads; .env is rewritten whole, so one at a time


def available_models(api_key: str | None = None) -> list[str]:
    """Chat models this Groq key can use (cached per key)."""
    key = api_key or config.GROQ_API_KEY or ""
    if key not in _models_cache:
        try:
            ids = [m.id for m in groq.Groq(api_key=key, timeout=8, max_retries=1).models.list().data]
            _models_cache[key] = sorted(i for i in ids if not _NOT_CHAT.search(i))
        except groq.APIError:
            return [config.CHAT_MODEL]
    return _models_cache[key]


def _mask(secret: str | None) -> str:
    return f"…{secret[-4:]}" if secret and len(secret) > 8 else ""


def snapshot() -> dict:
    length = next((name for name, n in REPLY_LENGTHS.items() if n == config.MAX_TOKENS), "custom")
    return {
        "username": config.USERNAME,
        "assistant_name": config.ASSISTANT_NAME,
        "theme": config.THEME,
        "chat_model": config.CHAT_MODEL,
        "models": available_models(),
        "reply_length": length,
        "groq_key": _mask(config.GROQ_API_KEY),
        "hf_key": _mask(config.HF_API_KEY),
        "learning": memory.learning_enabled(),
        "followups": config.FOLLOWUPS,
        "autostart": desktop.AUTOSTART.exists(),
        "hotkey": hotkey.status(),
        "data_dir": str(config.DATA_DIR),
    }


def _write(key: str, value: str) -> None:
    config.ENV_FILE.touch(exist_ok=True)
    set_key(str(config.ENV_FILE), key, value, quote_mode="never")


def apply(name: str, value) -> tuple[str, bool]:
    """Apply one change. Returns (confirmation message, whether the agent must be rebuilt).
    Raises ValueError with a user-facing message if the value is rejected."""
    with _apply_lock:
        return _apply(name, value)


def _apply(name: str, value) -> tuple[str, bool]:
    rebuild = False
    if name in ("username", "assistant_name"):
        text = " ".join(str(value).split())[:40]
        if not text:
            raise ValueError("The name can't be empty.")
        _write("Username" if name == "username" else "Assistantname", text)
        message = "Name updated."
    elif name == "theme":
        if value not in ("system", "light", "dark"):
            raise ValueError("Unknown theme.")
        _write("Theme", value)
        message = "Theme updated."
    elif name == "chat_model":
        if value not in available_models():
            raise ValueError(f"{value} isn't available on your Groq account.")
        _write("ChatModel", value)
        message, rebuild = f"Now using {value.split('/')[-1]}.", True
    elif name == "reply_length":
        if value not in REPLY_LENGTHS:
            raise ValueError("Unknown reply length.")
        _write("MaxTokens", str(REPLY_LENGTHS[value]))
        message, rebuild = "Reply length updated.", True
    elif name == "groq_key":
        key = str(value).strip()
        try:  # test it before saving: a typo here would break every reply
            groq.Groq(api_key=key, timeout=8, max_retries=1).models.list()
        except groq.AuthenticationError:
            raise ValueError("Groq rejected that key. Check it and try again.")
        except groq.APIError as e:
            raise ValueError(f"Couldn't check the key ({type(e).__name__}). Are you online?")
        _write("GroqAPIKey", key)
        message, rebuild = "Groq key saved and working.", True
    elif name == "hf_key":
        _write("HuggingFaceAPIKey", str(value).strip())
        message = "Hugging Face key saved." if str(value).strip() else "Hugging Face key removed."
    elif name == "learning":
        memory.set_learning(bool(value))
        message = "Learning from conversations " + ("on." if value else "off.")
    elif name == "followups":
        _write("Followups", "true" if value else "false")
        message = "Check-ins " + ("on." if value else "off.")
    elif name == "autostart":
        (desktop.install if value else desktop.uninstall)()
        message = "Starts at login." if value else "Won't start at login."
    elif name == "hotkey":
        (hotkey.install if value else hotkey.uninstall)()
        message = "Super+J shortcut on." if value else "Shortcut removed."
    else:
        raise ValueError(f"Unknown setting {name!r}.")

    config.reload()
    if name == "assistant_name":  # desktop entries and the shortcut carry the name
        if desktop.AUTOSTART.exists():
            desktop.install()
        if hotkey.status():
            hotkey.install(hotkey.status())
    return message, rebuild
