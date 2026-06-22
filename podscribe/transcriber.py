"""Whisper transcription wrapper around mlx-whisper (Apple Silicon MLX)."""
from __future__ import annotations

from typing import List

import numpy as np

DEFAULT_MODEL = "base"

MODEL_MAP = {
    "base": "mlx-community/whisper-base-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}


def resolve_model(name: str) -> str:
    """Map short Whisper model names to HF MLX repo IDs.

    Full HF paths (e.g. 'mlx-community/whisper-large-v3-mlx') pass through.
    """
    if "/" in name:
        return name
    return MODEL_MAP.get(name, name)


class Transcriber:
    """Lazy-loaded Whisper model via mlx-whisper (Apple Silicon MLX).

    Model is cached by mlx-whisper internally, so repeated transcribe()
    calls with the same model name reuse the loaded weights.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        n_threads: int = 0,
        print_progress: bool = False,
    ):
        self.model_name = resolve_model(model)

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, **kwargs) -> List[dict]:
        """Transcribe a mono float32 audio segment (16kHz).

        Returns list of {"start": float_sec, "end": float_sec, "text": str}.
        Times are relative to the start of the input segment.
        """
        try:
            import mlx_whisper
        except ImportError as e:
            raise ImportError(
                "mlx-whisper is required. Install with: pip install mlx-whisper"
            ) from e

        if audio.ndim > 1:
            audio = audio.reshape(-1)
        if audio.size == 0:
            return []

        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self.model_name,
            **kwargs,
        )
        segments = []
        for s in result.get("segments", []):
            text = (s.get("text", "") or "").strip()
            if text:
                segments.append({"start": s["start"], "end": s["end"], "text": text})
        return segments
