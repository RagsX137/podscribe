"""Parakeet via parakeet-mlx (Apple Silicon). No prompt conditioning."""
from __future__ import annotations

import os
import tempfile
import wave
import warnings
from pathlib import Path
from typing import List

import numpy as np

from .base import normalize_segments, prepare_audio

# parakeet-mlx decodes a clip in a single pass when chunk_duration is None, which
# OOMs the Metal allocator on full-length meetings (#10). Chunked decode bounds
# peak memory; 120s/15s matches the tuned values used for the benchmark run.
_CHUNK_DURATION = 120.0
_OVERLAP_DURATION = 15.0

# Only these kwargs are meaningful to parakeet-mlx's transcribe(); anything
# else (e.g. whisper's initial_prompt) is silently dropped below, so we warn
# instead of letting a typo or a future caller vanish without a trace.
_KNOWN_KWARGS = {"chunk_duration", "overlap_duration"}


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
        # Only forward parakeet-mlx's own chunking knobs; whisper-only kwargs
        # (e.g. initial_prompt) would raise a TypeError here.
        unknown = set(kwargs) - _KNOWN_KWARGS
        if unknown:
            warnings.warn(
                f"parakeet-mlx backend ignores kwargs: {sorted(unknown)}",
                stacklevel=2,
            )
        # dict.get(key, default) only applies the default when the key is
        # absent, so an explicit chunk_duration=None would pass None straight
        # through to model.transcribe() and re-introduce the single-pass OOM.
        chunk_duration = kwargs.get("chunk_duration")
        if chunk_duration is None:
            chunk_duration = _CHUNK_DURATION
        overlap_duration = kwargs.get("overlap_duration")
        if overlap_duration is None:
            overlap_duration = _OVERLAP_DURATION
        wav = _write_temp_wav(audio, sample_rate)
        try:
            result = model.transcribe(
                str(wav),
                chunk_duration=chunk_duration,
                overlap_duration=overlap_duration,
            )
        finally:
            try:
                wav.unlink()
            except OSError:
                pass
        return normalize_segments(
            (s.start, s.end, s.text) for s in getattr(result, "sentences", [])
        )
