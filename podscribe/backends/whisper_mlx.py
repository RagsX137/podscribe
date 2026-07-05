"""Whisper via mlx-whisper (Apple Silicon MLX). The original transcriber path."""
from __future__ import annotations

from typing import List

import numpy as np

from .base import normalize_segments, prepare_audio


class WhisperMLXBackend:
    """Lazy-loaded Whisper model via mlx-whisper. Weights cached by mlx-whisper."""

    def __init__(self, repo_id: str):
        self.model_name = repo_id

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, **kwargs) -> List[dict]:
        try:
            import mlx_whisper
        except ImportError as e:
            raise ImportError(
                "mlx-whisper is required for the whisper-mlx backend. "
                "Install with: pip install mlx-whisper"
            ) from e

        audio = prepare_audio(audio)
        if audio.size == 0:
            return []
        result = mlx_whisper.transcribe(audio, path_or_hf_repo=self.model_name, **kwargs)
        return normalize_segments(
            (s["start"], s["end"], s.get("text", ""))
            for s in result.get("segments", [])
        )
