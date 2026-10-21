import shutil
import subprocess
from types import SimpleNamespace

import groq
import httpx
import pytest

from aura import config, settings, voice


class FakeClient:
    """Stands in for groq.Groq: returns a fixed transcript (or raises) and records the request."""

    def __init__(self, text="", error=None):
        self.text, self.error, self.calls = text, error, []
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text)


def _status_error(cls, code):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/audio/transcriptions")
    return cls("error", response=httpx.Response(code, request=request), body=None)


@pytest.fixture(autouse=True)
def defaults(monkeypatch):
    monkeypatch.setattr(config, "VOICE_MODEL", "whisper-large-v3-turbo")
    monkeypatch.setattr(config, "VOICE_LANGUAGE", "auto")


def test_transcript_is_returned_and_request_is_sane():
    client = FakeClient("  Remind me in 20 minutes   to call mom. ")
    assert voice.transcribe(b"audio", "audio/webm;codecs=opus", client) == "Remind me in 20 minutes to call mom."
    call = client.calls[0]
    assert call["file"][0] == "speech.webm" and call["model"] == "whisper-large-v3-turbo"
    assert "language" not in call  # auto: Whisper detects it


def test_language_setting_is_passed(monkeypatch):
    monkeypatch.setattr(config, "VOICE_LANGUAGE", "ur")
    client = FakeClient("ٹھیک ہے")
    voice.transcribe(b"audio", "audio/webm", client)
    assert client.calls[0]["language"] == "ur"


@pytest.mark.parametrize("phantom", ["Thank you.", "you", " Thanks for watching! ", "..."])
def test_whisper_noise_phantoms_are_dropped(phantom):
    assert voice.transcribe(b"audio", "audio/webm", FakeClient(phantom)) == ""


def test_echoed_hint_is_dropped():
    hint = f"{config.USERNAME} talking to {config.ASSISTANT_NAME}."
    assert voice.transcribe(b"audio", "audio/webm", FakeClient(hint)) == ""
    assert voice.transcribe(b"audio", "audio/webm", FakeClient("Thank you, open YouTube")) == "Thank you, open YouTube"


def test_errors_become_friendly_messages(monkeypatch):
    with pytest.raises(ValueError, match="limit"):
        voice.transcribe(b"audio", "audio/webm", FakeClient(error=_status_error(groq.RateLimitError, 429)))
    with pytest.raises(ValueError, match="understand"):
        voice.transcribe(b"audio", "audio/webm", FakeClient(error=_status_error(groq.BadRequestError, 400)))
    with pytest.raises(ValueError, match="any audio"):
        voice.transcribe(b"", "audio/webm", FakeClient("hi"))
    with pytest.raises(ValueError, match="too long"):
        voice.transcribe(b"x" * (voice.MAX_BYTES + 1), "audio/webm", FakeClient("hi"))
    monkeypatch.setattr(config, "GROQ_API_KEY", None)
    with pytest.raises(ValueError, match="API key"):
        voice.transcribe(b"audio", "audio/webm", FakeClient("hi"))


def test_voice_language_setting(monkeypatch):
    monkeypatch.setattr(settings, "_write", lambda k, v: None)
    monkeypatch.setattr(config, "reload", lambda: None)  # keep the real key for later live tests
    assert settings.apply("voice_language", "en")[0] == "Voice language updated."
    with pytest.raises(ValueError):
        settings.apply("voice_language", "klingon")


def _has_flite() -> bool:
    if not shutil.which("ffmpeg"):
        return False
    return "flite" in subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout


@pytest.fixture(scope="module")
def speech_clip(tmp_path_factory):
    # Module scope: made before the per-test isolation fakes out subprocess.
    clip = tmp_path_factory.mktemp("voice") / "speech.webm"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "flite=text='remind me in twenty minutes to call my mom':voice=slt",
                    "-c:a", "libopus", str(clip)], check=True)
    return clip


@pytest.mark.live
@pytest.mark.skipif(not _has_flite(), reason="needs ffmpeg with flite to synthesize speech")
def test_live_transcription(speech_clip):
    text = voice.transcribe(speech_clip.read_bytes(), "audio/webm;codecs=opus").lower()
    assert "remind me" in text and "mom" in text
