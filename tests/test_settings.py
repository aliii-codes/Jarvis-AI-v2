"""Settings are validated, written to .env and reloaded, without touching the real .env, login items or shortcuts."""
from unittest import mock

import groq
import pytest
from dotenv import dotenv_values

from aura import config, settings


@pytest.fixture(autouse=True)
def fake_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("GroqAPIKey=gsk_old_key_123456\nUsername=Ali\nAssistantname=AURA\n")
    monkeypatch.setattr(config, "ENV_FILE", env)
    monkeypatch.setattr(settings, "available_models", lambda api_key=None: ["openai/gpt-oss-120b", "openai/gpt-oss-20b"])
    installs = []
    for module, name in [(settings.desktop, "desktop"), (settings.hotkey, "hotkey")]:
        monkeypatch.setattr(module, "install", lambda *a, n=name: installs.append(f"{n} on"))
        monkeypatch.setattr(module, "uninstall", lambda n=name: installs.append(f"{n} off"))
    monkeypatch.setattr(settings.hotkey, "status", lambda: None)
    monkeypatch.setattr(settings.desktop, "AUTOSTART", tmp_path / "aura.desktop")
    config.reload()
    yield env, installs
    monkeypatch.undo()
    config.reload()  # back to the real .env for other tests


def test_name_and_theme_are_saved_and_applied(fake_env):
    env, _ = fake_env
    assert settings.apply("username", "  Ali   Khan ") == ("Name updated.", False)
    settings.apply("theme", "dark")
    assert dotenv_values(env)["Username"] == "Ali Khan" and config.USERNAME == "Ali Khan"
    assert config.THEME == "dark"


def test_invalid_values_are_rejected(fake_env):
    for name, value in [("username", "   "), ("theme", "neon"), ("reply_length", "huge"),
                        ("chat_model", "allam-2-7b"), ("nonsense", 1)]:
        with pytest.raises(ValueError):
            settings.apply(name, value)


def test_model_and_reply_length_need_agent_rebuild(fake_env):
    assert settings.apply("chat_model", "openai/gpt-oss-20b")[1] is True
    assert settings.apply("reply_length", "long")[1] is True
    assert config.CHAT_MODEL == "openai/gpt-oss-20b" and config.MAX_TOKENS == 2048
    assert settings.snapshot()["reply_length"] == "long"


def test_groq_key_is_checked_before_saving(fake_env):
    env, _ = fake_env
    bad = mock.Mock()
    bad.return_value.models.list.side_effect = groq.AuthenticationError("bad key", response=mock.Mock(status_code=401), body=None)
    with mock.patch.object(settings.groq, "Groq", bad), pytest.raises(ValueError, match="rejected"):
        settings.apply("groq_key", "gsk_typo")
    assert dotenv_values(env)["GroqAPIKey"] == "gsk_old_key_123456"  # untouched

    with mock.patch.object(settings.groq, "Groq"):
        assert settings.apply("groq_key", "gsk_new_key_987654") == ("Groq key saved and working.", True)
    assert config.GROQ_API_KEY == "gsk_new_key_987654"
    assert settings.snapshot()["groq_key"] == "…7654"  # only the last 4 characters are ever shown


def test_switches_call_installers(fake_env):
    _, installs = fake_env
    settings.apply("autostart", True)
    settings.apply("hotkey", False)
    settings.apply("followups", False)
    assert installs == ["desktop on", "hotkey off"] and config.FOLLOWUPS is False


def test_concurrent_saves_dont_lose_changes(fake_env):
    # Regression: three quick changes ran on parallel threads and one overwrote another in .env.
    from concurrent.futures import ThreadPoolExecutor
    env, _ = fake_env
    changes = [("username", "Ali K"), ("theme", "dark"), ("reply_length", "short"), ("followups", False)]
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda c: settings.apply(*c), changes))
    saved = dotenv_values(env)
    assert (saved["Username"], saved["Theme"], saved["MaxTokens"], saved["Followups"]) == ("Ali K", "dark", "512", "false")


def test_cerebras_key_is_checked_and_adds_the_backup_model(fake_env):
    import openai
    env, _ = fake_env
    bad = mock.Mock()
    bad.return_value.models.list.side_effect = openai.AuthenticationError(
        "bad", response=mock.Mock(status_code=401, headers={}, request=mock.Mock()), body=None)
    with mock.patch.object(openai, "OpenAI", bad), pytest.raises(ValueError, match="Cerebras rejected"):
        settings.apply("cerebras_key", "csk-typo")
    assert "cerebras:gpt-oss-120b" not in config.CHAT_MODELS

    with mock.patch.object(openai, "OpenAI"):
        assert settings.apply("cerebras_key", "csk-good-key-1234")[1] is True
    assert config.CHAT_MODELS[:2] == ["openai/gpt-oss-120b", "cerebras:gpt-oss-120b"]  # right after the main model
    settings.apply("cerebras_key", "")
    assert not any(m.startswith("cerebras:") for m in config.CHAT_MODELS)
