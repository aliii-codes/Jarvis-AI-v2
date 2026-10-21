"""The Settings panel's backend: what it shows, and applying a change (validated, saved to .env)."""
import re
import threading

import groq
from dotenv import set_key

from . import config, desktop, documents, hotkey, mail, memory, voice

REPLY_LENGTHS = {"short": 512, "normal": 1024, "long": 2048}
ROUTINE_REMINDERS = ("0", "5", "10", "15", "30")  # minutes before a routine; 0 = off
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
        "cerebras_key": _mask(config.CEREBRAS_API_KEY),
        "hf_key": _mask(config.HF_API_KEY),
        "learning": memory.learning_enabled(),
        "followups": config.FOLLOWUPS,
        "routine_reminder": str(config.ROUTINE_REMINDER),
        "voice_language": config.VOICE_LANGUAGE,
        "gmail_address": config.GMAIL_ADDRESS or "",
        "gmail_password": _mask(config.GMAIL_APP_PASSWORD),
        "autostart": desktop.AUTOSTART.exists(),
        "hotkey": hotkey.status(),
        "data_dir": str(config.DATA_DIR),
        "documents": documents.status(),
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
    elif name == "cerebras_key":
        key = str(value).strip()
        if key:
            import openai
            from .models import CEREBRAS_URL
            try:  # same check as the Groq key: a typo here would silently disable the backup
                openai.OpenAI(base_url=CEREBRAS_URL, api_key=key, timeout=10, max_retries=1).models.list()
            except openai.AuthenticationError:
                raise ValueError("Cerebras rejected that key. Check it and try again.")
            except openai.APIError as e:
                raise ValueError(f"Couldn't check the key ({type(e).__name__}). Are you online?")
        _write("CerebrasAPIKey", key)
        message, rebuild = ("Cerebras key saved: the big model now has a backup." if key else "Cerebras key removed."), True
    elif name == "hf_key":
        _write("HuggingFaceAPIKey", str(value).strip())
        message = "Hugging Face key saved." if str(value).strip() else "Hugging Face key removed."
    elif name == "learning":
        memory.set_learning(bool(value))
        message = "Learning from conversations " + ("on." if value else "off.")
    elif name == "followups":
        _write("Followups", "true" if value else "false")
        message = "Check-ins " + ("on." if value else "off.")
    elif name == "routine_reminder":
        if str(value) not in ROUTINE_REMINDERS:
            raise ValueError("Unknown reminder time.")
        _write("RoutineReminder", str(value))
        message = f"Routine reminders {value} min before." if str(value) != "0" else "Routine reminders off."
    elif name == "gmail_address":
        address = str(value).strip()
        if address and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address):
            raise ValueError("That doesn't look like an email address.")
        _write("GmailAddress", address)
        message = "Email address saved." if address else "Email address removed."
    elif name == "gmail_password":
        password = str(value).replace(" ", "")
        if password:
            if not config.GMAIL_ADDRESS:
                raise ValueError("Enter your Gmail address first.")
            mail.check_login(config.GMAIL_ADDRESS, password)  # MailError is a ValueError: shown as-is
        _write("GmailAppPassword", password)
        message = "Gmail connected." if password else "Gmail disconnected."
    elif name == "voice_language":
        if value not in voice.LANGUAGES:
            raise ValueError("Unknown language.")
        _write("VoiceLanguage", value)
        message = "Voice language updated."
    elif name == "autostart":
        (desktop.install if value else desktop.uninstall)()
        message = "Starts at login." if value else "Won't start at login."
    elif name == "doc_add":
        folder = documents.add_folder(str(value))
        message = f"Added {folder}. Indexing in the background…"
    elif name == "doc_remove":
        documents.remove_folder(str(value))
        message = "Folder removed."
    elif name == "doc_reindex":
        message = "Re-indexing in the background…"
    elif name == "hotkey":
        (hotkey.install if value else hotkey.uninstall)()
        message = "Super+J (and Super+Shift+J to talk) on." if value else "Shortcuts removed."
    else:
        raise ValueError(f"Unknown setting {name!r}.")

    config.reload()
    if name == "assistant_name":  # desktop entries and the shortcut carry the name
        if desktop.AUTOSTART.exists():
            desktop.install()
        if hotkey.status():
            hotkey.install(hotkey.status())
    return message, rebuild
