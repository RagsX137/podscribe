"""Parakeet via NVIDIA NeMo (CUDA). No prompt conditioning."""
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


def _segments_from_hyp(hyp) -> list:
    """Extract (start, end, text) triples from a NeMo hypothesis' segment timestamps."""
    stamp = getattr(hyp, "timestamp", None) or {}
    out = []
    for seg in stamp.get("segment", []):
        out.append((seg.get("start", 0.0), seg.get("end", 0.0), seg.get("segment", "")))
    return out


class ParakeetNeMoBackend:
    """NeMo ASRModel wrapper. Model cached; transcribes a temp WAV with timestamps."""

    def __init__(self, repo_id: str):
        self.model_name = repo_id
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            import nemo.collections.asr as nemo_asr
        except ImportError as e:
            raise ImportError(
                "nemo_toolkit[asr] is required for the parakeet-nemo backend. "
                "Install with: pip install -e '.[parakeet-cuda]'"
            ) from e
        self._model = nemo_asr.models.ASRModel.from_pretrained(self.model_name)
        return self._model

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, **kwargs) -> List[dict]:
        audio = prepare_audio(audio)
        if audio.size == 0:
            return []
        model = self._load()
        wav = _write_temp_wav(audio, sample_rate)
        try:
            hyps = model.transcribe([str(wav)], timestamps=True)
        finally:
            try:
                wav.unlink()
            except OSError:
                pass
        if not hyps:
            return []
        return normalize_segments(_segments_from_hyp(hyps[0]))
