"""Whisper/Parakeet transcription facade over pluggable, platform-aware backends."""
from __future__ import annotations

from typing import List

import numpy as np

from .backends.registry import REGISTRY
from .backends.select import resolve_backend

DEFAULT_MODEL = "large-v3-turbo"

# Retained for backward-compatible imports; canonical mapping now lives in
# podscribe/backends/select.py.
MODEL_MAP = {
    "base": "mlx-community/whisper-base-mlx",
    "large": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}


def resolve_model(name: str) -> str:
    """Map a short MLX Whisper name to its HF repo (back-compat shim)."""
    if "/" in name:
        return name
    return MODEL_MAP.get(name, name)


def _make_backend(backend_id: str, repo_id: str):
    """Instantiate a backend via its registry spec (lazy-imports the module)."""
    try:
        spec = REGISTRY[backend_id]
    except KeyError:
        raise ValueError(f"unknown backend id '{backend_id}'")
    return spec.load(repo_id)


class Transcriber:
    """Facade: resolves a backend from (model, backend) and delegates transcribe().

    The backend engine is lazy-loaded, so constructing a Transcriber is cheap
    and only the selected engine's dependency must be installed.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        backend: str = "auto",
        n_threads: int = 0,
        print_progress: bool = False,
    ):
        self.backend_id, self.model_name = resolve_backend(model, backend)
        self._backend = None

    def _ensure_backend(self):
        if self._backend is None:
            self._backend = _make_backend(self.backend_id, self.model_name)
        return self._backend

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, **kwargs) -> List[dict]:
        """Transcribe a mono float32 16kHz segment.

        Returns list of {"start", "end", "text"} with segment-relative times.
        """
        return self._ensure_backend().transcribe(audio, sample_rate=sample_rate, **kwargs)
