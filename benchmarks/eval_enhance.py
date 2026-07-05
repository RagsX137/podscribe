# benchmarks/eval_enhance.py
"""Staged eval harness: generate/check/judge/rate/report.

Stage scripts share a JSON cache under benchmarks/eval_data/. generate runs
all (model, meeting, run) combos and caches full response text + timing.
check, judge, rate, report are pure aggregation over cached outputs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from benchmarks.bench_enhance import run_once
from benchmarks.eval_cache import cache_path, list_cached, load_artifact, save_artifact
from benchmarks.eval_checks import run_checks
from benchmarks.eval_judge import anonymize_pair, build_rubric_prompt, judge_pair, pair_key, swapped_key


def load_transcript(entry: dict, base_dir: Path) -> str:
    if entry.get("suite") == "public":
        return (base_dir / f"{entry['id']}.transcript.md").read_text()
    from podscribe.storage import list_meetings, load_pod, read_transcript_diarized
    pod = load_pod(entry["pod"])
    meetings = list_meetings(pod)
    for m in meetings:
        if m.id.startswith(entry["meeting_prefix"]):
            return read_transcript_diarized(m)
    sys.exit(f"No meeting matching '{entry['meeting_prefix']}' for pod '{entry['pod']}'.")


def build_prompt_for_transcript(transcript: str) -> str:
    from podscribe.config import get_effective_glossary, load_preserve_speakers, load_project_config
    from podscribe.llm import build_enhance_prompt

    cfg = load_project_config().get("llm") or {}
    template = cfg.get("prompt_template") or ""
    return build_enhance_prompt(template, [], transcript, preserve_speakers=load_preserve_speakers(None) if False else True)


def cmd_generate(*, entries: list, contestants: list, runs: int, base: Path) -> int:
    existing = set(list_cached(base))
    for entry in entries:
        transcript = load_transcript(entry, base)
        prompt = build_prompt_for_transcript(transcript)
        for c in contestants:
            for run in range(runs):
                path_key = cache_path(entry["suite"], entry["id"], c["tag"], run, base=base)
                rel = path_key.name
                if rel in existing:
                    sys.stderr.write(f"  skip cached: {rel}\n")
                    continue
                sys.stderr.write(f"  generate: {rel}\n")
                result = run_once(c["tag"], prompt, label=rel, quiet=True)
                payload = {
                    "suite": entry["suite"], "meeting": entry["id"],
                    "model": c["tag"], "run": run,
                    "response_text": result.get("response_text") or result.get("response_preview"),
                    "response_len": result.get("response_len", 0),
                    "timing": {k: v for k, v in result.items() if k.startswith(("total", "warm", "load", "prompt", "eval", "wall", "in_", "out_"))},
                }
                save_artifact(path_key, payload)
    return 0


def load_transcript_for_check(entry: dict, base_dir: Path) -> str:
    if entry["suite"] == "public":
        return (base_dir / f"{entry['meeting']}.transcript.md").read_text()
    return load_transcript(entry, base_dir)


def cmd_check(*, base: Path) -> int:
    results_by_model = {}
    for name in list_cached(base):
        artifact = load_artifact(base / name)
        entry = {"suite": artifact["suite"], "meeting": artifact["meeting"], "id": artifact["meeting"]}
        transcript = load_transcript_for_check(entry, base)
        runs = [artifact]
        results = run_checks(transcript, artifact["response_text"], [], runs=runs, llm_response_text=artifact["response_text"])
        results_by_model.setdefault(artifact["model"], []).extend([(r.name, r.passed) for r in results])
    for model, flat in results_by_model.items():
        passed = sum(1 for _, p in flat if p)
        total = len(flat)
        print(f"{model}: {passed}/{total} checks passed")
    return 0


def cmd_judge(*, base: Path, backend: str, model: str, judge_runs: str) -> int:
    from benchmarks.eval_manifest import load_manifest
    m = load_manifest()
    champion_tag = next((c.tag for c in m.contestants if c.role == "champion"), m.contestants[0].tag)
    challenger_tags = [c.tag for c in m.contestants if c.role == "challenger"]
    runs_to_judge = [0] if judge_runs == "run0" else [0, 1, 2]
    attempted = judged = failed = 0
    seen_pair_keys = set()
    for meeting_artifact in [a for a in base.iterdir() if "pos_" not in a.name and a.name.endswith(".json")]:
        data = load_artifact(meeting_artifact)
        meeting = data["meeting"]
        for chal in challenger_tags:
            for run in runs_to_judge:
                challenger_path = base / f"public__{meeting}__{chal.replace(':', '_')}__run{run}.json"
                champion_path = base / f"public__{meeting}__{champion_tag.replace(':', '_')}__run{run}.json"
                if not (challenger_path.exists() and champion_path.exists()):
                    continue
                pair = {
                    "challenger": {"model": chal, "text": load_artifact(challenger_path)["response_text"]},
                    "champion": {"model": champion_tag, "text": load_artifact(champion_path)["response_text"]},
                }
                for pos_key in (pair_key(chal, champion_tag, meeting, run), swapped_key(pair_key(chal, champion_tag, meeting, run))):
                    if pos_key in seen_pair_keys:
                        continue
                    seen_pair_keys.add(pos_key)
                    attempted += 1
                    result = judge_pair(pair, backend=backend, model=model)
                    if result["status"] == "judged":
                        judged += 1
                    else:
                        failed += 1
                    out_path = base / f"{pos_key}.verdict.json"
                    save_artifact(out_path, result)
    assert judged + failed == attempted, f"quiet drop: {judged}+{failed}!={attempted}"
    sys.stderr.write(f"judge: attempted={attempted} judged={judged} failed={failed}\n")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="eval_enhance", description="LLM enhance eval harness.")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="Run all models on all suite inputs.")
    g.add_argument("--runs", type=int, default=3)
    g.add_argument("--models", help="Comma-separated override; default reads manifest.")
    c = sub.add_parser("check", help="Layer-1 metrics over cached outputs.")
    j = sub.add_parser("judge", help="Layer-2 pairwise judging over cached outputs.")
    j.add_argument("--backend", choices=["claude", "local"], default="claude")
    j.add_argument("--model", default="claude-sonnet-5")
    j.add_argument("--judge-runs", default="run0", help="run0 or all")
    args = p.parse_args()
    if args.cmd == "generate":
        from benchmarks.eval_manifest import load_manifest, verify_contestants, Contestant
        m = load_manifest()
        contestants = [Contestant(tag=c.tag, digest=c.digest, role=c.role) for c in m.contestants]
        if args.models:
            wanted = set(s.strip() for s in args.models.split(","))
            contestants = [c for c in contestants if c.tag in wanted]
        verify_contestants(contestants)
        entries = [{"id": e.id, "suite": "public"} for e in m.public] + [{"id": e.id, "suite": "private", "pod": e.pod, "meeting_prefix": e.meeting_prefix} for e in m.private]
        return cmd_generate(entries=entries, contestants=[{"tag": c.tag, "digest": c.digest, "role": c.role} for c in contestants], runs=args.runs, base=Path("benchmarks/eval_data"))
    elif args.cmd == "check":
        return cmd_check(base=Path("benchmarks/eval_data"))
    elif args.cmd == "judge":
        return cmd_judge(base=Path("benchmarks/eval_data"), backend=args.backend, model=args.model, judge_runs=args.judge_runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
