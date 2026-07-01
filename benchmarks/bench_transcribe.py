"""Benchmark the bundled Whisper models on real audio.

Two-process harness: a parent spawns one child Python subprocess per model.
Each child loads one model, transcribes all requested fixtures, and prints
one JSON line per clip to stdout (its ONLY stdout output). The parent
aggregates, renders a markdown table, and writes a timestamped JSON
snapshot to benchmarks/results/.

Usage:
    python benchmarks/bench_transcribe.py                       # default: all 3 models, all fixtures
    python benchmarks/bench_transcribe.py --models base,large,large-v3-turbo
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
    "large": "~1550 M",
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
    order = ["base", "large-v3-turbo", "large"]
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


# --- child worker + parent orchestrator ------------------------------------ #

def _run_child(model: str, clip_names: Optional[list[str]], asr_dir: Path,
               runs: int) -> None:
    """Child process body: load one model and print one JSON line per (clip, run).

    Stdout is reserved strictly for JSON output; all progress goes to stderr.
    Exits 0 on success; on error prints {"error": ...} and exits 1.
    """
    try:
        import resource
        import time

        import numpy as np

        from podscribe.transcriber import Transcriber

        clips = load_manifest(asr_dir)
        if clip_names:
            wanted = set(clip_names)
            clips = [c for c in clips if c["name"] in wanted]
            if not clips:
                raise ValueError(
                    f"no clips in manifest match --clips {clip_names!r}"
                )

        t = Transcriber(model=model)
        # warm the model on the first clip so subsequent runs are post-load
        if clips and runs >= 1:
            warm_audio = np.fromfile(clips[0]["f32_path"], dtype=np.float32)
            t.transcribe(warm_audio, sample_rate=16000)

        for clip in clips:
            audio = np.fromfile(clip["f32_path"], dtype=np.float32)
            reference = Path(clip["txt_path"]).read_text(encoding="utf-8").strip()
            duration = float(clip.get("duration_s", len(audio) / 16000.0))
            for run_idx in range(runs):
                sys.stderr.write(
                    f"  [{model}] {clip['name']} run {run_idx + 1}/{runs}...\n"
                )
                sys.stderr.flush()
                t0 = time.perf_counter()
                segments = t.transcribe(audio, sample_rate=16000)
                wall_s = time.perf_counter() - t0
                hypothesis = " ".join(s["text"] for s in segments).strip()
                metrics = normalize_pair_and_compute(reference, hypothesis)
                # macOS ru_maxrss is in bytes; Linux is in KB. Convert to MB.
                _rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                peak_rss_mb = _rss / (1024.0 * 1024.0) if sys.platform == "darwin" else _rss / 1024.0
                record = {
                    "model": model,
                    "clip": clip["name"],
                    "run": run_idx,
                    "duration_s": duration,
                    "wall_s": wall_s,
                    "rtf": wall_s / duration if duration else 0.0,
                    "hypothesis": hypothesis,
                    "peak_rss_mb": peak_rss_mb,
                    **metrics,
                }
                sys.stdout.write(_json.dumps(record) + "\n")
                sys.stdout.flush()
        sys.exit(0)
    except Exception as e:  # surface to parent as a structured line
        sys.stdout.write(_json.dumps({"error": str(e), "model": model}) + "\n")
        sys.stdout.flush()
        sys.exit(1)


def _run_parent(models: list[str], clip_names: Optional[list[str]],
                asr_dir: Path, runs: int, out_path: Optional[Path]) -> int:
    """Spawn one child per model, aggregate JSON lines, render, optionally save."""
    import subprocess

    records: list[dict] = []
    errors: list[dict] = []

    for model in models:
        cmd = [
            sys.executable, "-m", "benchmarks.bench_transcribe",
            "--child", "--model", model,
            "--runs", str(runs),
        ]
        if clip_names:
            cmd += ["--clips", ",".join(clip_names)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            rec = parse_clip_line(line)
            if "error" in rec:
                errors.append(rec)
            else:
                records.append(rec)
        if proc.returncode != 0 and proc.stderr:
            sys.stderr.write(proc.stderr)

    if errors:
        for e in errors:
            sys.stderr.write(f"ERROR ({e.get('model', '?')}): {e['error']}\n")
        return 1

    if not records:
        sys.stderr.write("no records produced (no matching clips?)\n")
        return 1

    aggregated = aggregate_results(records)
    md = render_markdown_table(aggregated)
    sys.stdout.write("\n" + md + "\n\n")

    snapshot = {
        "meta": {
            "models": models,
            "clips": sorted({r["clip"] for r in records}),
            "runs": runs,
            "timestamp": _results_timestamp(),
        },
        "records": records,
        "aggregated": aggregated,
        "markdown": md,
    }
    if out_path is not None:
        out_path.write_text(_json.dumps(snapshot, indent=2), encoding="utf-8")
        sys.stderr.write(f"\nwrote results: {out_path}\n")
    return 0


def _results_timestamp() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    # repo root = parent of benchmarks/
    repo_root = Path(__file__).resolve().parent.parent
    default_asr = repo_root / "fixtures" / "asr"
    default_results = repo_root / "benchmarks" / "results"

    p = argparse.ArgumentParser(
        description="Benchmark bundled Whisper models on fixture audio.",
    )
    p.add_argument("--models", default="base,large,large-v3-turbo",
                   help="Comma-separated model names (default: base,large,large-v3-turbo)")
    p.add_argument("--clips", default=None,
                   help="Comma-separated clip names from manifest (default: all)")
    p.add_argument("--runs", type=int, default=1,
                   help="Repeats per clip (default: 1)")
    p.add_argument("--asr-dir", type=Path, default=default_asr,
                   help=f"Fixtures dir (default: {default_asr})")
    p.add_argument("--regen", action="store_true",
                   help="Write a results JSON snapshot to benchmarks/results/")
    p.add_argument("--list-clips", action="store_true",
                   help="Print manifest contents and exit")
    # internal: child mode
    p.add_argument("--child", action="store_true",
                   help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    if args.list_clips:
        try:
            clips = load_manifest(args.asr_dir)
        except FileNotFoundError as e:
            sys.stderr.write(str(e) + "\n")
            return 1
        for c in clips:
            print(f"{c['name']:20s} {c.get('duration_s', 0):6.1f}s  "
                  f"{c.get('source', '')}")
        return 0

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    clip_names = None
    if args.clips:
        clip_names = [c.strip() for c in args.clips.split(",") if c.strip()]

    if args.child:
        _run_child(args.models, clip_names, args.asr_dir, args.runs)
        return 0  # _run_child exits, but be defensive

    out_path = None
    if args.regen:
        default_results.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = default_results / f"bench-transcribe-{stamp}.json"

    return _run_parent(models, clip_names, args.asr_dir, args.runs, out_path)


if __name__ == "__main__":
    sys.exit(main())
