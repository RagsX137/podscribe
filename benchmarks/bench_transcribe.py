"""Benchmark the bundled Whisper models on real audio.

Two-process harness: a parent spawns one child Python subprocess per model.
Each child loads one model, transcribes all requested fixtures, and prints
one JSON line per clip to stdout (its ONLY stdout output). The parent
aggregates, renders a markdown table, and writes a timestamped JSON
snapshot to benchmarks/results/.

Usage:
    python benchmarks/bench_transcribe.py                       # default: all 3 models, all fixtures
    python benchmarks/bench_transcribe.py --models base,large-v3-turbo
    python benchmarks/bench_transcribe.py --clips short-clear,short-noisy
    python benchmarks/bench_transcribe.py --runs 3
    python benchmarks/bench_transcribe.py --regen               # write results JSON + render table
    python benchmarks/bench_transcribe.py --list-clips          # show manifest contents
    python benchmarks/bench_transcribe.py --child --model base --clips short-clear   # internal
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import yaml

# Quality metrics produced per clip × model. All five are jiwer built-ins
# operating on one normalized (reference, hypothesis) pair.
METRIC_NAMES: tuple[str, ...] = ("wer", "cer", "mer", "wil", "wip")

# --- manifest --------------------------------------------------------------- #

def load_manifest(asr_dir: Path) -> list[dict]:
    """Read fixtures/asr/manifest.yaml and return its clips list.

    Raises FileNotFoundError if manifest.yaml or a clip's .f32/.txt is missing.
    """
    manifest_path = asr_dir / "manifest.yaml"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"manifest not found: {manifest_path} (expected under fixtures/asr/)"
        )
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    clips = data.get("clips") or []
    if not clips:
        raise ValueError(f"{manifest_path} contains no clips")

    for clip in clips:
        name = clip["name"]
        f32 = asr_dir / f"{name}.f32"
        txt = asr_dir / f"{name}.txt"
        if not f32.is_file():
            raise FileNotFoundError(
                f"manifest references {name!r} but {f32.name} is missing"
            )
        if not txt.is_file():
            raise FileNotFoundError(
                f"manifest references {name!r} but {txt.name} is missing"
            )
        clip["f32_path"] = str(f32)
        clip["txt_path"] = str(txt)
    return clips
