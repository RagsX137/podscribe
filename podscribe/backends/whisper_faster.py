"""Whisper via faster-whisper (CTranslate2): NVIDIA CUDA with CPU fallback."""
from __future__ import annotations

import glob
import os
import sys
import warnings
from typing import List, Optional

import numpy as np

from .base import normalize_segments, prepare_audio


def _add_cuda_dll_dirs() -> None:
    """On Windows, put the NVIDIA pip-wheel CUDA runtime on the DLL search path.

    CTranslate2 does not bundle the CUDA 12 runtime on Windows, so it fails to
    load cublas64_12.dll / cudnn64_9.dll unless they are reachable. When the
    ``nvidia-cublas-cu12`` / ``nvidia-cudnn-cu12`` wheels are installed their
    DLLs live under ``site-packages/nvidia/*/bin``, which is not on PATH by
    default. Prepend those dirs to PATH (the loader search order CTranslate2's
    native code actually consults) and register them with add_dll_directory.
    Best-effort and silent when not on Windows or the wheels are absent.
    """
    if sys.platform != "win32":
        return
    try:
        import nvidia  # namespace package created by the nvidia-*-cu12 wheels
    except ImportError:
        return
    for base in nvidia.__path__:
        for dll_dir in glob.glob(os.path.join(base, "*", "bin")):
            if not os.path.isdir(dll_dir):
                continue
            os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
            try:
                os.add_dll_directory(dll_dir)
            except OSError:
                pass


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
        _add_cuda_dll_dirs()
        try:
            self._model = WhisperModel(self.model_name, device="cuda", compute_type="float16")
        except Exception as e:
            warnings.warn(
                f"CUDA unavailable for whisper-faster ({type(e).__name__}: {e}); "
                "falling back to slower CPU int8. For GPU on Windows install the "
                "CUDA 12 runtime wheels: pip install nvidia-cublas-cu12 nvidia-cudnn-cu12",
                RuntimeWarning,
                stacklevel=2,
            )
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
