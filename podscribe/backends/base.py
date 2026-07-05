"""Shared helpers every ASR backend uses to meet the segment contract."""
from __future__ import annotations

from typing import Iterable, List, Tuple

import numpy as np


def normalize_segments(raw: Iterable[Tuple[float, float, str]]) -> List[dict]:
    """Turn (start, end, text) triples into canonical segment dicts.

    Strips surrounding whitespace and drops segments whose text is empty
    after stripping. Times are passed through unchanged (backends supply
    segment-relative seconds).
    """
    segments: List[dict] = []
    for start, end, text in raw:
        cleaned = (text or "").strip()
        if cleaned:
            segments.append({"start": float(start), "end": float(end), "text": cleaned})
    return segments


def prepare_audio(audio: np.ndarray) -> np.ndarray:
    """Flatten multi-channel/2-D audio to 1-D; return 1-D input unchanged."""
    if audio.ndim > 1:
        return audio.reshape(-1)
    return audio
