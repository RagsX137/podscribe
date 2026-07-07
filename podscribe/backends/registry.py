"""Single source of truth for ASR backends.

To add a backend: implement `podscribe/backends/<name>.py` with a class exposing
`model_name` and `transcribe(audio, sample_rate=16000, **kwargs)`, then add ONE
`BackendSpec` entry to `REGISTRY` below. The selector and the Transcriber facade
are data-driven from this table and need no changes.

Loaders lazy-import their engine inside the function body, so this module stays
import-light and never pulls a heavy dependency until a backend is instantiated.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict


@dataclass(frozen=True)
class BackendSpec:
    backend_id: str
    family: str
    apple_silicon: bool
    load: Callable[[str], object]
    resolve_repo: Callable[[str], str]


_WHISPER_MLX_MAP = {
    "base": "mlx-community/whisper-base-mlx",
    "large": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}
_WHISPER_FASTER_MAP = {
    "base": "base",
    "large": "large-v3",
    "large-v3-turbo": "large-v3-turbo",
    "turbo": "large-v3-turbo",
}


def _mapped(model: str, table: Dict[str, str]) -> str:
    if "/" in model:
        return model
    return table.get(model, model)


def _repo_whisper_mlx(model: str) -> str:
    return _mapped(model, _WHISPER_MLX_MAP)


def _repo_whisper_faster(model: str) -> str:
    return _mapped(model, _WHISPER_FASTER_MAP)


def _repo_parakeet_mlx(model: str) -> str:
    return model if "/" in model else "mlx-community/parakeet-tdt-0.6b-v2"


def _repo_parakeet_nemo(model: str) -> str:
    return model if "/" in model else "nvidia/parakeet-tdt-0.6b-v2"


def _load_whisper_mlx(repo_id: str):
    from .whisper_mlx import WhisperMLXBackend
    return WhisperMLXBackend(repo_id)


def _load_whisper_faster(repo_id: str):
    from .whisper_faster import WhisperFasterBackend
    return WhisperFasterBackend(repo_id)


def _load_parakeet_mlx(repo_id: str):
    from .parakeet_mlx import ParakeetMLXBackend
    return ParakeetMLXBackend(repo_id)


def _load_parakeet_nemo(repo_id: str):
    from .parakeet_nemo import ParakeetNeMoBackend
    return ParakeetNeMoBackend(repo_id)


REGISTRY: Dict[str, BackendSpec] = {
    "whisper-mlx": BackendSpec(
        "whisper-mlx", "whisper", True, _load_whisper_mlx, _repo_whisper_mlx),
    "whisper-faster": BackendSpec(
        "whisper-faster", "whisper", False, _load_whisper_faster, _repo_whisper_faster),
    "parakeet-mlx": BackendSpec(
        "parakeet-mlx", "parakeet", True, _load_parakeet_mlx, _repo_parakeet_mlx),
    "parakeet-nemo": BackendSpec(
        "parakeet-nemo", "parakeet", False, _load_parakeet_nemo, _repo_parakeet_nemo),
}

BACKEND_IDS = tuple(REGISTRY)
