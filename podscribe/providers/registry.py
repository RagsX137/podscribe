"""Provider registry + config resolution.

To add a provider: implement its module and add one entry to _FACTORIES.
"""
from __future__ import annotations

import os
from typing import Optional

from .base import Provider
from .ollama import OllamaProvider
from .openai_compat import OpenAIProvider


def _build_ollama(cfg: dict, model: str) -> Provider:
    return OllamaProvider(model, base_url=cfg.get("base_url") or "http://localhost:11434")


def _build_openai(cfg: dict, model: str) -> Provider:
    base_url = cfg.get("base_url")
    if not base_url:
        raise ValueError("openai provider requires 'base_url' (e.g. https://api.deepseek.com/v1)")
    api_key = None
    key_env = cfg.get("api_key_env")
    if key_env:
        api_key = os.environ.get(key_env)
        if not api_key:
            raise ValueError(
                f"API key env var '{key_env}' is unset or empty. "
                f"Export it, e.g. export {key_env}=sk-..."
            )
    return OpenAIProvider(model, base_url=base_url, api_key=api_key)


_FACTORIES = {
    "ollama": _build_ollama,
    "openai": _build_openai,
}
PROVIDER_NAMES = tuple(_FACTORIES)


def build_provider(llm_config: Optional[dict], model: Optional[str] = None) -> Provider:
    """Resolve an llm config dict into a ready Provider (see interface docs)."""
    cfg = dict(llm_config or {})
    name = cfg.get("provider") or "ollama"
    if name not in _FACTORIES:
        raise ValueError(
            f"unknown provider '{name}'. Choose from: " + ", ".join(PROVIDER_NAMES)
        )
    resolved_model = model or cfg.get("model")
    if not resolved_model:
        raise ValueError("no model configured for the LLM provider")
    return _FACTORIES[name](cfg, resolved_model)
