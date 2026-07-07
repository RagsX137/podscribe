import pytest
from podscribe.providers.registry import build_provider, PROVIDER_NAMES
from podscribe.providers.ollama import OllamaProvider
from podscribe.providers.openai_compat import OpenAIProvider


def test_names():
    assert PROVIDER_NAMES == ("ollama", "openai")


def test_default_is_ollama_localhost():
    p = build_provider({"model": "qwen3.6"})
    assert isinstance(p, OllamaProvider)
    assert p.base_url == "http://localhost:11434"
    assert p.model == "qwen3.6"


def test_none_config_defaults_to_ollama_with_model_arg():
    p = build_provider(None, model="llama3")
    assert isinstance(p, OllamaProvider)
    assert p.model == "llama3"


def test_ollama_custom_base_url():
    p = build_provider({"provider": "ollama", "base_url": "http://box:11434", "model": "m"})
    assert p.base_url == "http://box:11434"


def test_openai_reads_api_key_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_KEY", "sk-abc")
    p = build_provider({
        "provider": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_KEY",
    })
    assert isinstance(p, OpenAIProvider)
    assert p.api_key == "sk-abc"


def test_openai_missing_key_raises(monkeypatch):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    with pytest.raises(ValueError, match="MISSING_KEY"):
        build_provider({"provider": "openai", "base_url": "https://x/v1",
                        "model": "m", "api_key_env": "MISSING_KEY"})


def test_openai_missing_base_url_raises():
    with pytest.raises(ValueError, match="base_url"):
        build_provider({"provider": "openai", "model": "m", "api_key_env": "K"})


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="unknown provider"):
        build_provider({"provider": "anthropic", "model": "m"})
