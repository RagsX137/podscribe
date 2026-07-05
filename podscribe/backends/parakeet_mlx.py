"""Parakeet via parakeet-mlx (Apple Silicon). No prompt conditioning."""
from __future__ import annotations

import os
import tempfile
import wave
from pathlib import Path
from typing import List

import numpy as np

from .base import normalize_segments, prepare_audio


def _write_temp_wav(audio: np.ndarray, sample_rate: int) -> Path:
    fd, name = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    with wave.open(name, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return Path(name)


class ParakeetMLXBackend:
    """parakeet-mlx wrapper. Model cached on the instance; transcribes via temp WAV."""

    def __init__(self, repo_id: str):
        self.model_name = repo_id
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from parakeet_mlx import from_pretrained
        except ImportError as e:
            raise ImportError(
                "parakeet-mlx is required for the parakeet-mlx backend. "
                "Install with: pip install -e '.[parakeet-mlx]'"
            ) from e
        self._model = from_pretrained(self.model_name)
        return self._model

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, **kwargs) -> List[dict]:
        audio = prepare_audio(audio)
        if audio.size == 0:
            return []
        model = self._load()
        wav = _write_temp_wav(audio, sample_rate)
        try:
            result = model.transcribe(str(wav))
        finally:
            try:
                wav.unlink()
            except OSError:
                pass
        return normalize_segments(
            (s.start, s.end, s.text) for s in getattr(result, "sentences", [])
        )
