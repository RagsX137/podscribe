"""Whisper transcription wrapper around pywhispercpp."""
from __future__ import annotations

import os
import tempfile
import wave
from typing import List

import numpy as np

DEFAULT_MODEL = "base.en"
DEFAULT_N_THREADS = 4


class Transcriber:
    """Lazy-loaded Whisper model via pywhispercpp (whisper.cpp Python bindings)."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        n_threads: int = DEFAULT_N_THREADS,
        print_progress: bool = False,
    ):
        self.model_name = model
        self.n_threads = n_threads
        self.print_progress = print_progress
        self._model = None

    def _load(self):
        if self._model is not None:
            return
        try:
            from pywhispercpp.model import Model
        except ImportError as e:
            raise ImportError(
                "pywhispercpp is required. Install with: pip install pywhispercpp"
            ) from e
        self._model = Model(
            self.model_name,
            n_threads=self.n_threads,
            print_progress=self.print_progress,
        )

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, **kwargs) -> List[dict]:
        """Transcribe a mono float32 audio segment (16kHz).

        Returns list of {"start": float_sec, "end": float_sec, "text": str}.
        Times are relative to the start of the input segment.
        """
        self._load()
        if audio.ndim > 1:
            audio = audio.reshape(-1)
        if audio.size == 0:
            return []
        # Convert float32 [-1, 1] → int16 PCM
        audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_int16.tobytes())

            segments = self._model.transcribe(tmp_path, **kwargs)
            results = []
            for s in segments:
                t0 = float(getattr(s, "t0", 0) or 0)
                t1 = float(getattr(s, "t1", 0) or 0)
                text = (getattr(s, "text", "") or "").strip()
                t0 /= 1000.0
                t1 /= 1000.0
                if text:
                    results.append({"start": t0, "end": t1, "text": text})
            return results
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
