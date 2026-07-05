"""Whisper via faster-whisper (CTranslate2): NVIDIA CUDA with CPU fallback."""
from __future__ import annotations

from typing import List, Optional

import numpy as np

from .base import normalize_segments, prepare_audio


class WhisperFasterBackend:
    """CTranslate2-backed Whisper. Prefers CUDA float16, falls back to CPU int8."""

    def __init__(self, repo_id: str):
        self.model_name = repo_id
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise ImportError(
                "faster-whisper is required for the whisper-faster backend. "
                "Install with: pip install -e '.[cuda]'"
            ) from e
        try:
            self._model = WhisperModel(self.model_name, device="cuda", compute_type="float16")
        except Exception:
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, **kwargs) -> List[dict]:
        audio = prepare_audio(audio)
        if audio.size == 0:
            return []
        initial_prompt: Optional[str] = kwargs.get("initial_prompt")
        model = self._load()
        segments, _info = model.transcribe(
            audio.astype(np.float32),
            initial_prompt=initial_prompt,
            word_timestamps=False,
        )
        return normalize_segments((s.start, s.end, s.text) for s in segments)
