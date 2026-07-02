"""Benchmark all bundled Whisper models on a real meeting recording.

Drop a media file (`.mp4`, `.mov`, `.wav`, ...) and its reference transcript
(`.vtt`) into a folder — e.g. `pods/<pod>/benchmark_data/` — then point this at
that folder. It auto-discovers the pair, decodes the media to 16kHz mono float32,
turns the `.vtt` into a plain-text reference, writes a one-clip manifest under an
`asr/` subdir, and reuses `bench_transcribe`'s parent runner to score every
available model. Aggregate metrics print as a markdown table; a JSON snapshot is
written next to the media (kept out of git when the folder is under `pods/`).

This is DRY over `bench_transcribe`: all metric/aggregation/render/subprocess
logic lives there; this module only handles ingest + model selection.

Usage:
    python benchmarks/bench_meeting.py pods/fso/benchmark_data
    python benchmarks/bench_meeting.py pods/fso/benchmark_data --models base,large-v3-turbo
    python benchmarks/bench_meeting.py pods/fso/benchmark_data --runs 3 --name standup
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

# Allow `python benchmarks/bench_meeting.py ...` (script mode puts benchmarks/ on
# sys.path, not the repo root) to still import the `benchmarks` package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Media containers ffmpeg can decode audio from. Lowercase, leading dot.
MEDIA_EXTS: frozenset[str] = frozenset({
    ".mp4", ".mov", ".m4a", ".mkv", ".webm", ".avi",
    ".wav", ".mp3", ".aac", ".flac", ".ogg", ".opus",
})

_VTT_VOICE_TAG = re.compile(r"</?v[^>]*>")
_VTT_CUE_ID = re.compile(r"^[0-9a-f-]{8,}.*[0-9]+-[0-9]+$")


def available_models() -> list[str]:
    """The distinct canonical model names, aliases deduped.

    Derived from transcriber.MODEL_MAP so new models are picked up automatically.
    When several short names resolve to the same repo (e.g. 'turbo' aliases
    'large-v3-turbo'), the first-seen short name wins and the rest are dropped.
    """
    from podscribe.transcriber import MODEL_MAP

    seen: set[str] = set()
    models: list[str] = []
    for short, repo in MODEL_MAP.items():
        if repo in seen:
            continue
        seen.add(repo)
        models.append(short)
    return models


def vtt_to_text(vtt: str) -> str:
    """Flatten a WebVTT transcript into a single reference string.

    Drops the WEBVTT header, cue-id lines, timestamp lines, and `<v Name>`
    speaker tags (speaker labels aren't spoken, so they must not count as
    reference words); keeps the spoken text in order, whitespace-collapsed.
    """
    out: list[str] = []
    for line in vtt.splitlines():
        s = line.strip()
        if not s or s == "WEBVTT":
            continue
        if "-->" in s:  # timestamp line
            continue
        if _VTT_CUE_ID.match(s):  # "uuid/12-0" style cue identifier
            continue
        text = _VTT_VOICE_TAG.sub("", s).strip()
        if text:
            out.append(text)
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def discover_media_and_vtt(folder: Path) -> tuple[Path, Path]:
    """Find the single media file and single `.vtt` in `folder`.

    Raises FileNotFoundError if either is missing, ValueError if ambiguous.
    """
    if not folder.is_dir():
        raise FileNotFoundError(f"not a directory: {folder}")
    media = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS
    )
    vtts = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == ".vtt"
    )
    if not media:
        raise FileNotFoundError(
            f"no media file ({', '.join(sorted(MEDIA_EXTS))}) in {folder}"
        )
    if len(media) > 1:
        raise ValueError(
            f"multiple media files in {folder}: {[p.name for p in media]}; "
            "keep one per benchmark folder"
        )
    if not vtts:
        raise FileNotFoundError(f"no .vtt reference transcript in {folder}")
    if len(vtts) > 1:
        raise ValueError(
            f"multiple .vtt files in {folder}: {[p.name for p in vtts]}; "
            "keep one per benchmark folder"
        )
    return media[0], vtts[0]


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


def write_manifest(asr_dir: Path, name: str, duration_s: float, source: str) -> Path:
    """Write a one-clip manifest.yaml (the format bench_transcribe.load_manifest reads)."""
    import yaml

    path = asr_dir / "manifest.yaml"
    path.write_text(
        yaml.safe_dump(
            {"clips": [{"name": name, "duration_s": round(duration_s, 1),
                        "source": source}]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def ingest(folder: Path, name: Optional[str] = None) -> tuple[Path, str, float]:
    """Discover media + vtt in `folder`, produce asr/ fixtures, return (asr_dir, clip_name, duration_s)."""
    media, vtt = discover_media_and_vtt(folder)
    clip_name = name or re.sub(r"[^A-Za-z0-9_-]+", "-", media.stem).strip("-").lower() or "meeting"
    asr_dir = folder / "asr"
    asr_dir.mkdir(parents=True, exist_ok=True)

    duration_s = decode_to_f32(media, asr_dir / f"{clip_name}.f32")
    reference = vtt_to_text(vtt.read_text(encoding="utf-8"))
    (asr_dir / f"{clip_name}.txt").write_text(reference, encoding="utf-8")
    write_manifest(
        asr_dir, clip_name, duration_s,
        source=f"real recording {media.name}; reference = {vtt.name}",
    )
    return asr_dir, clip_name, duration_s


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    from datetime import datetime

    from benchmarks.bench_transcribe import _run_parent

    p = argparse.ArgumentParser(
        description="Benchmark all Whisper models on a real meeting (media + .vtt).",
    )
    p.add_argument("folder", type=Path,
                   help="Folder holding one media file and one .vtt reference")
    p.add_argument("--models", default=None,
                   help="Comma-separated model names (default: all available)")
    p.add_argument("--runs", type=int, default=1, help="Repeats per model (default: 1)")
    p.add_argument("--name", default=None,
                   help="Clip name (default: derived from the media filename)")
    args = p.parse_args(argv)

    models = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models else available_models()
    )

    try:
        asr_dir, clip_name, duration_s = ingest(args.folder, args.name)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 1

    sys.stderr.write(
        f"ingested {clip_name} ({duration_s / 60:.1f} min) -> {asr_dir}\n"
        f"models: {', '.join(models)}\n\n"
    )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = args.folder / f"bench-meeting-{stamp}.json"
    return _run_parent(models, None, asr_dir, args.runs, out_path)


if __name__ == "__main__":
    sys.exit(main())
