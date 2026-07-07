"""Platform-aware backend selection, driven entirely by the registry."""
from __future__ import annotations

import platform

from .registry import BACKEND_IDS, REGISTRY


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def _is_parakeet(model: str) -> bool:
    lowered = model.lower()
    return lowered == "parakeet" or "/parakeet-" in lowered or lowered.startswith("parakeet-")


def _auto_pick(family: str, apple: bool) -> str:
    for spec in REGISTRY.values():
        if spec.family == family and spec.apple_silicon == apple:
            return spec.backend_id
    raise ValueError(f"no backend registered for family '{family}' (apple={apple})")


def resolve_backend(model: str, backend: str = "auto") -> tuple[str, str]:
    """Return (backend_id, repo_id). See interface docs for the rules."""
    if backend != "auto" and backend not in REGISTRY:
        raise ValueError(
            f"unknown backend '{backend}'. Choose from: auto, " + ", ".join(BACKEND_IDS)
        )
    family = "parakeet" if _is_parakeet(model) else "whisper"
    backend_id = _auto_pick(family, is_apple_silicon()) if backend == "auto" else backend
    return backend_id, REGISTRY[backend_id].resolve_repo(model)
