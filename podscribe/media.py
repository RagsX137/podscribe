"""Media ingest helpers: decode video/audio to Whisper input, parse cue transcripts.

Shared by the KT `ingest` command and the benchmark harness. Heavy deps
(numpy) are imported inside functions so importing this module stays light.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

# Containers ffmpeg can decode audio from. Lowercase, leading dot.
MEDIA_EXTS: frozenset = frozenset({
    ".mp4", ".mov", ".m4a", ".mkv", ".webm", ".avi",
    ".wav", ".mp3", ".aac", ".flac", ".ogg", ".opus",
})

TRANSCRIPT_EXTS: Tuple[str, ...] = (".vtt", ".srt")

_VOICE_TAG = re.compile(r"</?v[^>]*>")
# HH:MM:SS or MM:SS with . or , millis, before the "-->" arrow.
_CUE_START = re.compile(
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->"
)


def _cue_start_seconds(line: str) -> Optional[float]:
    """Parse the start time (seconds) from a VTT/SRT timestamp line, else None."""
    m = _CUE_START.search(line)
    if not m:
        return None
    hh = int(m.group(1)) if m.group(1) else 0
    mm = int(m.group(2))
    ss = int(m.group(3))
    ms = int(m.group(4).ljust(3, "0"))
    return hh * 3600 + mm * 60 + ss + ms / 1000.0


def parse_transcript_cues(text: str) -> List[Tuple[float, str]]:
    """Return [(start_sec, text)] per cue for WebVTT or SRT.

    Skips the WEBVTT header, blank lines, numeric/uuid cue-id lines, and
    timestamp lines (kept only for their start time). Joins multi-line cue
    bodies with a space and strips `<v Name>` voice tags.
    """
    lines = text.splitlines()
    out: List[Tuple[float, str]] = []
    i = 0
    n = len(lines)
    while i < n:
        start = _cue_start_seconds(lines[i])
        if start is None:
            i += 1
            continue
        i += 1
        body: List[str] = []
        while i < n and lines[i].strip():
            body.append(_VOICE_TAG.sub("", lines[i]).strip())
            i += 1
        joined = re.sub(r"\s+", " ", " ".join(body)).strip()
        if joined:
            out.append((start, joined))
    return out


def discover_transcript(video: Path) -> Optional[Path]:
    """Return a sibling .vtt/.srt (same stem) next to `video`, preferring .vtt."""
    for ext in TRANSCRIPT_EXTS:
        candidate = video.with_suffix(ext)
        if candidate.is_file():
            return candidate
    return None


def decode_to_f32(media: Path, out_f32: Path) -> float:
    """Decode media audio to 16kHz mono float32 raw via ffmpeg; return duration_s.

    Raises RuntimeError if ffmpeg is missing or the decode fails.
    """
    import shutil
    import subprocess

    import numpy as np

    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found — install it (`brew install ffmpeg`) to decode media"
        )
    out_f32.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(media),
        "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", str(out_f32),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed decoding {media.name}:\n{proc.stderr[-2000:]}"
        )
    samples = np.fromfile(out_f32, dtype=np.float32)
    if samples.size == 0:
        raise RuntimeError(f"decoded 0 samples from {media.name} (no audio stream?)")
    return samples.size / 16000.0
