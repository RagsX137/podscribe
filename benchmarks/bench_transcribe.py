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

import json as _json
import sys
from pathlib import Path
from statistics import mean as _mean
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


# --- normalization + metrics ----------------------------------------------- #

def _build_transform():
    """jiwer.Compose of the standard normalization pipeline applied identically
    to reference and hypothesis."""
    import jiwer  # local import — keeps module importable without jiwer installed
    # jiwer 4.x moved individual transform classes from `jiwer.transformations`
    # (a *module* of prebuilt Compositions) to `jiwer.transforms` (the classes).
    # Older jiwer kept them in `jiwer.transformations`; fall back if so.
    try:
        from jiwer.transforms import (  # jiwer >= 4.0
            ToLowerCase, RemovePunctuation, RemoveMultipleSpaces, Strip,
            RemoveWhiteSpace, Compose,
        )
    except ImportError:
        from jiwer.transformations import (  # jiwer < 4.0
            ToLowerCase, RemovePunctuation, StripMultipleSpaces, Strip,
        )
        try:
            from jiwer.transformations import Compose
        except ImportError:
            from jiwer import Compose
        # Older jiwer used StripMultipleSpaces; we still need tab-to-space
        # conversion to make the whitespace-collapse tests pass.
        return Compose([
            ToLowerCase(),
            RemovePunctuation(),
            RemoveWhiteSpace(replace_by_space=True),
            StripMultipleSpaces(),
            Strip(),
        ])
    return Compose([
        ToLowerCase(),
        RemovePunctuation(),
        RemoveWhiteSpace(replace_by_space=True),  # tabs/newlines -> spaces
        RemoveMultipleSpaces(),
        Strip(),
    ])


_TRANSFORM = None  # built lazily so the module imports without jiwer present


def normalize_pair(reference: str, hypothesis: str) -> tuple[str, str]:
    """Apply the standard normalization to (reference, hypothesis)."""
    global _TRANSFORM
    if _TRANSFORM is None:
        _TRANSFORM = _build_transform()
    return _TRANSFORM(reference), _TRANSFORM(hypothesis)


def normalize_pair_and_compute(reference: str, hypothesis: str) -> dict:
    """Compute all 5 jiwer metrics on a normalized (reference, hypothesis) pair."""
    import jiwer
    ref_n, hyp_n = normalize_pair(reference, hypothesis)
    return {
        "wer": float(jiwer.wer(ref_n, hyp_n)),
        "cer": float(jiwer.cer(ref_n, hyp_n)),
        "mer": float(jiwer.mer(ref_n, hyp_n)),
        "wil": float(jiwer.wil(ref_n, hyp_n)),
        "wip": float(jiwer.wip(ref_n, hyp_n)),
    }


def parse_clip_line(line: str) -> dict:
    """Decode one child's JSON stdout line. Raises json.JSONDecodeError on bad input."""
    return _json.loads(line)


# --- aggregation + rendering ----------------------------------------------- #

# Param counts (rough) used only for the table's Params column.
# Source: OpenAI Whisper model card + mlx-community model repos.
_MODEL_PARAMS_M = {
    "base": "~74 M",
    "turbo": "~809 M",
    "large-v3-turbo": "~809 M",
}


def aggregate_results(records: list[dict]) -> dict:
    """Group per-clip records by model and compute per-model means + peak RSS.

    Returns {model: {clips, mean_wall_s, mean_rtf, peak_rss_mb, mean_wer, ...}}.
    """
    by_model: dict[str, list[dict]] = {}
    for r in records:
        by_model.setdefault(r["model"], []).append(r)

    out: dict[str, dict] = {}
    for model, recs in by_model.items():
        peak = max(r["peak_rss_mb"] for r in recs) if recs else 0
        out[model] = {
            "clips": len(recs),
            "mean_wall_s": _mean(r["wall_s"] for r in recs),
            "mean_rtf": _mean(r["rtf"] for r in recs),
            "peak_rss_mb": peak,
            "mean_wer": _mean(r["wer"] for r in recs),
            "mean_cer": _mean(r["cer"] for r in recs),
            "mean_mer": _mean(r["mer"] for r in recs),
            "mean_wil": _mean(r["wil"] for r in recs),
            "mean_wip": _mean(r["wip"] for r in recs),
        }
    return out


def render_markdown_table(aggregated: dict) -> str:
    """Render the per-model summary as a markdown table.

    Models ordered by param count ascending (base first). 'turbo' is omitted
    because it is an alias of 'large-v3-turbo' (see transcriber.MODEL_MAP).
    """
    aliases = {"turbo"}  # not shown as its own row
    order = ["base", "large-v3-turbo"]
    # include any unknown models at the end, alphabetically
    extras = sorted(m for m in aggregated if m not in order and m not in aliases)
    rows = [m for m in order if m in aggregated] + extras

    header = (
        "| Model | Params | Mean RTF (↓) | Peak RSS (MB) | "
        "Mean WER (↓) | Mean CER (↓) | Mean MER (↓) | Mean WIL (↓) | Mean WIP (↑) |\n"
        "|---|---|---|---|---|---|---|---|---|"
    )
    lines = [header]
    for m in rows:
        a = aggregated[m]
        lines.append(
            f"| `{m}` | {_MODEL_PARAMS_M.get(m, '?')} | "
            f"{a['mean_rtf']:.3f} | {int(a['peak_rss_mb'])} | "
            f"{a['mean_wer']:.3f} | {a['mean_cer']:.3f} | {a['mean_mer']:.3f} | "
            f"{a['mean_wil']:.3f} | {a['mean_wip']:.3f} |"
        )
    return "\n".join(lines)
