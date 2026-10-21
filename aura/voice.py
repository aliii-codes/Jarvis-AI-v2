"""Voice input: the page records the microphone, Groq's Whisper turns it into text, and the text is sent
like a typed message. (Speech in only: AURA doesn't talk back yet.)"""
import re

import groq

from . import config

LANGUAGES = {"auto": None, "en": "en", "ur": "ur"}  # Settings → Voice language
MAX_BYTES = 20 * 1024 * 1024  # Groq's free tier takes up to 25 MB; a minute of speech is well under 1 MB
_EXTENSIONS = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav", "audio/mp4": "m4a", "audio/mpeg": "mp3"}

# Whisper "hears" these in silence, breathing or background noise. A transcript that is only one of them is dropped.
_PHANTOMS = {"", "you", "thank you", "thanks", "thank you very much", "thanks for watching", "thank you for watching",
             "bye", "okay", "uh", "um", "hmm", "so", "subtitles by the amaraorg community", "music"}


def _plain(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def clean(text: str) -> str:
    """The transcript, or "" if it's only noise Whisper made up."""
    text = " ".join((text or "").split())
    return "" if _plain(text) in _PHANTOMS else text


def transcribe(audio: bytes, mime: str = "audio/webm", client=None) -> str:
    """Speech -> text. Raises ValueError with a message for the user when it can't."""
    if not audio:
        raise ValueError("Didn't catch any audio.")
    if len(audio) > MAX_BYTES:
        raise ValueError("That recording is too long. Try a shorter message.")
    if not config.GROQ_API_KEY:
        raise ValueError("Add your Groq API key in Settings to use voice.")
    ext = _EXTENSIONS.get(mime.split(";")[0].strip(), "webm")
    client = client or groq.Groq(api_key=config.GROQ_API_KEY, timeout=30, max_retries=2)
    language = LANGUAGES.get(config.VOICE_LANGUAGE)
    # Names Whisper can't know how to spell; also nudges it towards plain, punctuated text.
    hint = f"{config.USERNAME} talking to {config.ASSISTANT_NAME}."
    try:
        result = client.audio.transcriptions.create(
            model=config.VOICE_MODEL, file=(f"speech.{ext}", audio), temperature=0,
            prompt=hint,
            **({"language": language} if language else {}))
    except groq.RateLimitError:
        raise ValueError("Voice limit reached for now. Try again in a minute, or type it.")
    except groq.APIConnectionError:
        raise ValueError("Couldn't reach Groq for voice. Are you online?")
    except groq.APIStatusError as e:
        raise ValueError(f"Couldn't understand the recording ({e.status_code}).")
    if _plain(result.text) == _plain(hint):  # on silence Whisper may just repeat the hint
        return ""
    return clean(result.text)
