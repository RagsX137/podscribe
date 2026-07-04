#!/usr/bin/env python3
"""Benchmark Ollama models on the podscribe `enhance` workload.

Builds the exact prompt that `podscribe <pod> enhance <meeting>` would send
(same template, glossary, speaker-preservation preamble) and streams it to
each named model via /api/generate, capturing the full Ollama timing
breakdown that the CLI's own logger discards (load_duration,
prompt_eval_duration, etc.).

Runs one warmup + N measured runs per model, all of model A then all of
model B, so each model stays warm between its measured runs.

Usage (run from repo root, like the CLI):

    python benchmarks/bench_enhance.py
    python benchmarks/bench_enhance.py --models qwen3.6:27b,qwen3.6:27b-mlx
    python benchmarks/bench_enhance.py --pod fso --meeting 2026-06-22-1438 --runs 5
    python benchmarks/bench_enhance.py --list-meetings fso

Results are printed to stdout and a timestamped JSON is written to
benchmarks/results/.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# Reuse the podscribe pipeline so the prompt is byte-identical to the CLI.
from podscribe.config import (
    get_effective_glossary,
    load_preserve_speakers,
    load_project_config,
)
from podscribe.llm import build_enhance_prompt
from podscribe.storage import list_meetings, load_pod, read_transcript

OLLAMA_GENERATE = "http://localhost:11434/api/generate"
OLLAMA_TAGS = "http://localhost:11434/api/tags"

# Fields pulled from the final `done` chunk, in nanoseconds unless noted.
STAT_FIELDS = (
    "total_duration",
    "load_duration",
    "prompt_eval_count",      # tokens
    "prompt_eval_duration",
    "eval_count",             # tokens
    "eval_duration",
)


# --------------------------------------------------------------------------- #
# Prompt construction (mirrors cli.cmd_enhance)
# --------------------------------------------------------------------------- #
def build_prompt(pod_name: str, meeting_prefix: str) -> tuple[str, str, int]:
    """Return (prompt, meeting_id, transcript_chars) for the given pod/meeting.

    Uses pod-level llm config if present, else project-level config from
    podscribe.yaml — same resolution order as cmd_enhance.
    """
    pod = load_pod(pod_name)
    llm_config = pod.llm if pod.llm else load_project_config().get("llm")
    if not llm_config or not llm_config.get("prompt_template"):
        sys.exit(
            f"No llm config for pod '{pod_name}' and no project-level config "
            f"in podscribe.yaml."
        )

    meetings = list_meetings(pod)
    if not meetings:
        sys.exit(f"No meetings for pod '{pod_name}'.")

    if meeting_prefix == "latest":
        meeting = meetings[0]
    else:
        matches = [m for m in meetings if m.id.startswith(meeting_prefix)]
        if not matches:
            sys.exit(f"No meeting matching '{meeting_prefix}' for pod '{pod_name}'.")
        if len(matches) > 1:
            sys.exit(
                f"Multiple meetings match '{meeting_prefix}':\n"
                + "\n".join(f"  {m.id}" for m in matches)
            )
        meeting = matches[0]

    transcript = read_transcript(meeting)
    glossary = get_effective_glossary(pod)
    preserve = load_preserve_speakers(pod)
    prompt = build_enhance_prompt(
        llm_config["prompt_template"], glossary, transcript,
        preserve_speakers=preserve,
    )
    return prompt, meeting.id, len(transcript)


# --------------------------------------------------------------------------- #
# Ollama calls
# --------------------------------------------------------------------------- #
def check_ollama(models: list[str]) -> None:
    """Verify Ollama is up and every requested model is installed."""
    try:
        r = requests.get(OLLAMA_TAGS, timeout=5)
        r.raise_for_status()
    except requests.RequestException as e:
        sys.exit(f"Ollama not reachable at localhost:11434 ({e}). Start it with `ollama serve`.")

    installed = {m["name"] for m in r.json().get("models", [])}
    missing = [m for m in models if m not in installed]
    if missing:
        sys.exit(
            f"Missing models: {', '.join(missing)}.\n"
            f"Installed: {', '.join(sorted(installed)) or '(none)'}"
        )


def run_once(model: str, prompt: str, *, label: str, quiet: bool = False) -> dict:
    """One streaming /api/generate call. Returns dict with stats + response text.

    label is shown on the progress line (e.g. "warmup" or "run 2/3").
    """
    payload = {"model": model, "prompt": prompt, "stream": True}
    t0 = time.perf_counter()
    resp = requests.post(OLLAMA_GENERATE, json=payload, stream=True, timeout=3600)
    resp.raise_for_status()

    text_parts: list[str] = []
    stats: dict = {}
    n_chunks = 0
    try:
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "response" in chunk:
                text_parts.append(chunk["response"])
                n_chunks += 1
                if not quiet and n_chunks % 50 == 0:
                    sys.stderr.write(f"    [{label}] {n_chunks} tokens...\r")
                    sys.stderr.flush()
            if chunk.get("done"):
                stats = {k: chunk.get(k, 0) for k in STAT_FIELDS}
                break
    finally:
        resp.close()

    wall = time.perf_counter() - t0
    if not quiet:
        sys.stderr.write(" " * 60 + "\r")
        sys.stderr.flush()

    out_tokens = stats.get("eval_count", 0)
    return {
        "label": label,
        "wall_s": wall,
        "out_tokens": out_tokens,
        "in_tokens": stats.get("prompt_eval_count", 0),
        "total_s": (stats.get("total_duration", 0) or 0) / 1e9,
        "load_s": (stats.get("load_duration", 0) or 0) / 1e9,
        "prompt_eval_s": (stats.get("prompt_eval_duration", 0) or 0) / 1e9,
        "eval_s": (stats.get("eval_duration", 0) or 0) / 1e9,
        "warm_total_s": ((stats.get("total_duration", 0) or 0)
                         - (stats.get("load_duration", 0) or 0)) / 1e9,
        "prompt_tok_s": (
            (stats.get("prompt_eval_count", 0) or 0)
            / ((stats.get("prompt_eval_duration", 0) or 1) / 1e9)
        ),
        "gen_tok_s": (
            (stats.get("eval_count", 0) or 0)
            / ((stats.get("eval_duration", 0) or 1) / 1e9)
        ),
        "response_text": "".join(text_parts),
        "response_preview": "".join(text_parts)[:200],
        "response_len": len("".join(text_parts)),
    }


def benchmark_model(model: str, prompt: str, runs: int, warmup: int) -> dict:
    """Warmup + N measured runs for one model. Returns dict of results."""
    results = {"model": model, "warmup": [], "measured": []}

    for i in range(warmup):
        sys.stderr.write(f"  [{model}] warmup {i + 1}/{warmup}...\n")
        sys.stderr.flush()
        r = run_once(model, prompt, label=f"warmup {i + 1}", quiet=False)
        results["warmup"].append(r)
        sys.stderr.write(
            f"    warmup {i + 1}: {r['total_s']:.1f}s total "
            f"({r['load_s']:.1f}s load), {r['out_tokens']} out tok\n"
        )
        sys.stderr.flush()

    for i in range(runs):
        sys.stderr.write(f"  [{model}] run {i + 1}/{runs}...\n")
        sys.stderr.flush()
        r = run_once(model, prompt, label=f"run {i + 1}", quiet=False)
        results["measured"].append(r)
        sys.stderr.write(
            f"    run {i + 1}: {r['total_s']:.1f}s total, "
            f"warm {r['warm_total_s']:.1f}s, "
            f"prompt-eval {r['prompt_eval_s']:.1f}s @ {r['prompt_tok_s']:.0f} tok/s, "
            f"gen {r['eval_s']:.1f}s @ {r['gen_tok_s']:.1f} tok/s, "
            f"{r['out_tokens']} out tok\n"
        )
        sys.stderr.flush()

    return results


# --------------------------------------------------------------------------- #
# Aggregation + reporting
# --------------------------------------------------------------------------- #
def aggregate(measured: list[dict]) -> dict:
    """Mean/min/max over the measured runs for the key metrics."""
    keys = (
        "total_s", "warm_total_s", "load_s",
        "prompt_eval_s", "prompt_tok_s",
        "eval_s", "gen_tok_s", "out_tokens", "in_tokens", "wall_s",
    )
    agg = {}
    for k in keys:
        vals = [r[k] for r in measured]
        agg[k] = {"mean": statistics.mean(vals), "min": min(vals), "max": max(vals)}
    return agg


def fmt_agg(agg: dict, key: str, unit: str = "s") -> str:
    a = agg[key]
    if unit == "tok":
        return f"{a['mean']:.0f} [{a['min']:.0f}-{a['max']:.0f}]"
    if unit == "tps":
        return f"{a['mean']:.1f} [{a['min']:.1f}-{a['max']:.1f}]"
    return f"{a['mean']:.2f} [{a['min']:.2f}-{a['max']:.2f}]"


def print_report(all_results: list[dict], prompt_len: int, meeting_id: str) -> None:
    print("\n" + "=" * 78)
    print("ENHANCE BENCHMARK")
    print("=" * 78)
    print(f"Meeting : {meeting_id}")
    print(f"Prompt  : {prompt_len:,} chars sent to each model")
    print(f"Runs    : warmup discarded, measured runs averaged below")
    print()

    # Per-run detail table
    print("-" * 78)
    print(f"{'Model':<20} {'Run':<6} {'Total':>8} {'Warm':>8} "
          f"{'PromptEv':>9} {'Gen':>8} {'GenTok/s':>9}")
    print("-" * 78)
    for res in all_results:
        m = res["model"]
        for i, r in enumerate(res["measured"], 1):
            print(f"{m:<20} {i:<6} {r['total_s']:>7.1f}s {r['warm_total_s']:>7.1f}s "
                  f"{r['prompt_eval_s']:>8.1f}s {r['eval_s']:>7.1f}s "
                  f"{r['gen_tok_s']:>8.1f}")
    print()

    # Aggregates
    aggs = [(res["model"], aggregate(res["measured"])) for res in all_results]

    print("-" * 78)
    print(f"{'Metric (mean [min-max])':<28} " + "  ".join(
        f"{m:>22}" for m, _ in aggs))
    print("-" * 78)
    rows = [
        ("Input tokens", "in_tokens", "tok"),
        ("Output tokens", "out_tokens", "tok"),
        ("Total time (incl load)", "total_s", "s"),
        ("Warm total (excl load)", "warm_total_s", "s"),
        ("Model load time", "load_s", "s"),
        ("Prompt eval time", "prompt_eval_s", "s"),
        ("Prompt eval speed", "prompt_tok_s", "tps"),
        ("Generation time", "eval_s", "s"),
        ("Generation speed", "gen_tok_s", "tps"),
        ("Wall clock (our timer)", "wall_s", "s"),
    ]
    for label, key, unit in rows:
        print(f"{label:<28} " + "  ".join(
            f"{fmt_agg(a, key, unit):>22}" for _, a in aggs))
    print()

    # Side-by-side delta (only if exactly 2 models)
    if len(aggs) == 2:
        m1, a1 = aggs[0]
        m2, a2 = aggs[1]
        print("-" * 78)
        print(f"DELTA  ({m2}  minus  {m1})   [negative = {m2} is faster]")
        print("-" * 78)
        for label, key, unit in rows:
            d = a2[key]["mean"] - a1[key]["mean"]
            pct = (d / a1[key]["mean"] * 100) if a1[key]["mean"] else 0
            if unit == "tok":
                ds = f"{d:+.0f} tok"
            elif unit == "tps":
                ds = f"{d:+.1f} tok/s"
            else:
                ds = f"{d:+.2f}s"
            print(f"  {label:<26} {ds:>14}  ({pct:+.1f}%)")
        print()

    # Output quality check
    print("-" * 78)
    print("OUTPUT QUALITY (first 120 chars of each model's last run)")
    print("-" * 78)
    for res in all_results:
        last = res["measured"][-1]
        preview = last["response_preview"].replace("\n", " ")[:120]
        print(f"  {res['model']}: {preview!r}")
    print("=" * 78)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def list_meetings_cmd(pod_name: str) -> None:
    pod = load_pod(pod_name)
    meetings = list_meetings(pod)
    if not meetings:
        print(f"No meetings for pod '{pod_name}'.")
        return
    for m in meetings:
        print(f"  {m.id}")


def save_results(all_results: list[dict], meta: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    # Aggregate per model and attach to each result block.
    payload = {"meta": meta, "models": []}
    for res in all_results:
        block = {
            "model": res["model"],
            "warmup": res["warmup"],
            "measured": res["measured"],
            "aggregate": aggregate(res["measured"]),
        }
        payload["models"].append(block)
    path = out_dir / f"bench-{ts}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def main() -> int:
    p = argparse.ArgumentParser(
        description="Benchmark Ollama models on the podscribe enhance workload.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--models", default="qwen3.6:27b,qwen3.6:27b-mlx",
        help="Comma-separated model names (default: the two qwen3.6:27b variants).",
    )
    p.add_argument("--pod", default="fso", help="Pod name (default: fso).")
    p.add_argument(
        "--meeting", default="2026-06-22-1438",
        help="Meeting id prefix or 'latest' (default: 2026-06-22-1438, the 21KB fso transcript).",
    )
    p.add_argument("--runs", type=int, default=3, help="Measured runs per model (default 3).")
    p.add_argument("--warmup", type=int, default=1, help="Warmup runs, discarded (default 1).")
    p.add_argument(
        "--list-meetings", action="store_true",
        help="List available meetings for --pod and exit.",
    )
    p.add_argument(
        "--out-dir", default=str(Path(__file__).parent / "results"),
        help="Where to write the timestamped results JSON.",
    )
    args = p.parse_args()

    if args.list_meetings:
        list_meetings_cmd(args.pod)
        return 0

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        sys.exit("No models given.")

    check_ollama(models)

    print(f"Building prompt from pod '{args.pod}' meeting '{args.meeting}'...")
    prompt, meeting_id, transcript_chars = build_prompt(args.pod, args.meeting)
    print(f"  meeting      : {meeting_id}")
    print(f"  transcript   : {transcript_chars:,} chars")
    print(f"  full prompt  : {len(prompt):,} chars")
    print(f"  models       : {', '.join(models)}")
    print(f"  warmup/runs  : {args.warmup}/{args.runs}")
    print()

    all_results: list[dict] = []
    for model in models:
        print(f"=== {model} ===")
        res = benchmark_model(model, prompt, args.runs, args.warmup)
        all_results.append(res)
        print()

    print_report(all_results, len(prompt), meeting_id)

    out_dir = Path(args.out_dir)
    meta = {
        "timestamp": datetime.now().isoformat(),
        "pod": args.pod,
        "meeting": meeting_id,
        "transcript_chars": transcript_chars,
        "prompt_chars": len(prompt),
        "runs": args.runs,
        "warmup": args.warmup,
    }
    path = save_results(all_results, meta, out_dir)
    print(f"\nRaw results saved to: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
