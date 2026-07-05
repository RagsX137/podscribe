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
from benchmarks.eval_rate import append_rating, randomize_pair, session_state


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
    from podscribe.config import load_project_config
    from podscribe.llm import build_enhance_prompt

    cfg = load_project_config().get("llm") or {}
    template = cfg.get("prompt_template") or ""
    return build_enhance_prompt(template, [], transcript, preserve_speakers=True)


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
    from podscribe.config import get_effective_glossary
    from podscribe.models import Pod

    stub_pod = Pod(name="eval-stub", base_path=Path("/nonexistent/eval-stub"))
    glossary = get_effective_glossary(stub_pod)

    by_key: dict = {}
    for name in list_cached(base):
        if "verdict" in name:
            continue
        artifact = load_artifact(base / name)
        key = (artifact["suite"], artifact["meeting"], artifact["model"])
        by_key.setdefault(key, []).append(artifact)

    results_by_model = {}
    for (suite, meeting, model), artifacts in by_key.items():
        artifacts.sort(key=lambda a: a.get("run", 0))
        artifact = artifacts[0]
        entry = {"suite": suite, "meeting": meeting, "id": meeting}
        transcript = load_transcript_for_check(entry, base)
        runs = [
            {"text": a.get("response_text", ""), "action_items": a.get("action_items", [])}
            for a in artifacts
        ]
        results = run_checks(
            transcript, artifact["response_text"], glossary,
            runs=runs, llm_response_text=artifact["response_text"],
        )
        results_by_model.setdefault(model, []).extend([(r.name, r.passed) for r in results])
    for model, flat in results_by_model.items():
        passed = sum(1 for _, p in flat if p)
        total = len(flat)
        print(f"{model}: {passed}/{total} checks passed")
    return 0


def _load_judgeable_pairs(base: Path, suite: str, champion_tag: str, challenger_tags: list, run: int = 0) -> list:
    pairs = []
    seen_meetings = set()
    cache_files = sorted(
        (a for a in base.iterdir() if "pos_" not in a.name and a.name.endswith(".json") and a.name != "ratings.json"),
        key=lambda a: a.name,
    )
    for meeting_artifact in cache_files:
        data = load_artifact(meeting_artifact)
        if not isinstance(data, dict) or data.get("suite") != suite:
            continue
        meeting = data["meeting"]
        if meeting in seen_meetings:
            continue
        seen_meetings.add(meeting)
        for chal in challenger_tags:
            challenger_path = base / f"{suite}__{meeting}__{chal.replace(':', '_')}__run{run}.json"
            champion_path = base / f"{suite}__{meeting}__{champion_tag.replace(':', '_')}__run{run}.json"
            if not (challenger_path.exists() and champion_path.exists()):
                continue
            pairs.append({
                "challenger": {"model": chal, "text": load_artifact(challenger_path)["response_text"]},
                "champion": {"model": champion_tag, "text": load_artifact(champion_path)["response_text"]},
                "meeting": meeting, "run": run,
            })
    return pairs


def cmd_judge(*, base: Path, backend: str, model: Optional[str], judge_runs: str, suite: str) -> int:
    if suite == "private" and backend == "claude":
        sys.exit("Refusing to send private suite to a cloud API. Use --backend local.")
    from benchmarks.eval_manifest import load_manifest
    m = load_manifest()
    champion_tag = next((c.tag for c in m.contestants if c.role == "champion"), m.contestants[0].tag)
    challenger_tags = [c.tag for c in m.contestants if c.role == "challenger"]
    if model is None:
        if backend == "claude":
            model = "claude-sonnet-5"
        else:
            model = champion_tag
    runs_to_judge = [0] if judge_runs == "run0" else [0, 1, 2]
    attempted = judged = failed = 0
    seen_pair_keys = set()
    for run in runs_to_judge:
        for p in _load_judgeable_pairs(base, suite, champion_tag, challenger_tags, run=run):
            chal = p["challenger"]["model"]
            meeting = p["meeting"]
            base_key = pair_key(chal, champion_tag, meeting, run)
            for pos, swapped in (("a_first", False), ("b_first", True)):
                pos_key = base_key if not swapped else swapped_key(base_key)
                if pos_key in seen_pair_keys:
                    continue
                seen_pair_keys.add(pos_key)
                judged_pair = p if not swapped else {"challenger": p["champion"], "champion": p["challenger"]}
                attempted += 1
                result = judge_pair(judged_pair, backend=backend, model=model)
                result["position"] = pos
                result["challenger"] = chal
                result["champion"] = champion_tag
                result["meeting"] = meeting
                result["run"] = run
                result["suite"] = suite
                if result["status"] == "judged":
                    judged += 1
                else:
                    failed += 1
                save_artifact(base / f"{pos_key}.verdict.json", result)
    assert judged + failed == attempted, f"quiet drop: {judged}+{failed}!={attempted}"
    sys.stderr.write(f"judge: attempted={attempted} judged={judged} failed={failed}\n")
    return 0


def cmd_rate(*, base: Path, suite: str, ratings_path: Path) -> int:
    from benchmarks.eval_manifest import load_manifest
    m = load_manifest()
    champion_tag = next((c.tag for c in m.contestants if c.role == "champion"), m.contestants[0].tag)
    challenger_tags = [c.tag for c in m.contestants if c.role == "challenger"]
    pairs = _load_judgeable_pairs(base, suite, champion_tag, challenger_tags, run=0)
    state = session_state(pairs=pairs)
    for i, pair in enumerate(pairs):
        randomized = randomize_pair(pair, seed=i)
        print(f"\n=== Pair {i + 1}/{len(pairs)} ===")
        print(f"Left:\n{randomized['left']['text']}\n")
        print(f"Right:\n{randomized['right']['text']}\n")
        print("Type 'left', 'right', 'tie', or Ctrl+C to quit.")
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if choice not in ("left", "right", "tie"):
            print("Skipping unrecognized choice.")
            continue
        append_rating(ratings_path, {
            "pair_id": f"pair-{i}", "choice": choice, "run": 0,
            "meeting": pair["meeting"], "challenger": pair["challenger"]["model"],
        })
    state.reveal()
    print("\n=== Reveal ===")
    for i, pair in enumerate(pairs):
        print(f"pair-{i}: challenger={pair['challenger']['model']} champion={pair['champion']['model']}")
    return 0


_AXES = ["coverage", "faithfulness", "readability", "action-item quality", "overall"]
_SONNET_PER_CALL_USD = 0.02


def _challenger_from_verdict(vpath: Path, v: dict) -> Optional[str]:
    chal = v.get("challenger")
    if chal:
        return chal
    stem = vpath.name[: -len(".verdict.json")]
    head = stem.split("__vs__", 1)[0]
    parts = head.rsplit("__", 1)
    return parts[-1] if parts else head


def _position_from_verdict(vpath: Path, v: dict) -> str:
    pos = v.get("position")
    if pos:
        return pos
    return "b_first" if "pos_b_first" in vpath.name else "a_first"


def _challenger_outcome(value: str, position: str) -> Optional[str]:
    if value not in ("a", "b", "tie") or not position:
        return None
    if value == "tie":
        return "tie"
    if position == "a_first":
        return "challenger" if value == "a" else "champion"
    return "champion" if value == "a" else "challenger"


def _human_judge_agreement(base: Path, suite: str, champion_tag: str, challenger_tags: list, ratings_path: Path) -> Optional[tuple]:
    if not ratings_path or not ratings_path.exists():
        return None
    from benchmarks.eval_rate import load_ratings
    ratings = load_ratings(ratings_path)
    if not ratings:
        return None
    judge_votes: dict = {}
    for vpath in base.glob("*.verdict.json"):
        v = load_artifact(vpath)
        if v.get("status") != "judged":
            continue
        chal = v.get("challenger") or _challenger_from_verdict(vpath, v)
        meeting = v.get("meeting")
        if not chal or not meeting:
            continue
        val = ((v.get("verdict") or {}).get("overall") or "").lower()
        outcome = _challenger_outcome(val, _position_from_verdict(vpath, v))
        if outcome:
            judge_votes.setdefault((chal, meeting), []).append(outcome)
    judge_outlook: dict = {}
    for key, votes in judge_votes.items():
        counts = {o: votes.count(o) for o in ("challenger", "champion", "tie")}
        winner = max(counts, key=counts.get)
        judge_outlook[key] = winner if counts[winner] * 2 > len(votes) else "tie"
    agreed = total = 0
    for r in ratings:
        chal = r.get("challenger")
        meeting = r.get("meeting")
        choice = r.get("choice")
        pid = r.get("pair_id", "")
        if not (chal and meeting and choice) or not pid.startswith("pair-"):
            continue
        try:
            seed = int(pid.split("-", 1)[1])
        except (ValueError, IndexError):
            continue
        human_pick = _human_pick(choice, chal, champion_tag, seed)
        if human_pick is None:
            continue
        j = judge_outlook.get((chal, meeting))
        if j is None:
            continue
        total += 1
        if human_pick == j:
            agreed += 1
    if total == 0:
        return None
    return agreed, total


def _human_pick(choice: str, challenger: str, champion_tag: str, seed: int) -> Optional[str]:
    """Map a rater's left/right/tie choice back to challenger/champion/tie.

    The A/B side assignment is reproduced from the seed the rate stage used
    (encoded in pair_id) and the challenger/champion identities stored in the
    rating itself — never from the current directory-listing order — so the
    metric is stable across separate rate and report invocations.
    """
    if choice == "tie":
        return "tie"
    if choice not in ("left", "right"):
        return None
    randomized = randomize_pair(
        {"challenger": {"model": challenger}, "champion": {"model": champion_tag}},
        seed=seed,
    )
    return "challenger" if randomized[choice]["model"] == challenger else "champion"


def cmd_report(*, base: Path, suite: str, ratings_path: Optional[Path] = None) -> int:
    attempted = judged = failed = 0
    axis_counts = {a: {"challenger": 0, "champion": 0, "tie": 0} for a in _AXES}
    per_model: dict = {}
    for vpath in base.glob("*.verdict.json"):
        v = load_artifact(vpath)
        attempted += 1
        if v.get("status") != "judged":
            failed += 1
            continue
        judged += 1
        chal = _challenger_from_verdict(vpath, v)
        pos = _position_from_verdict(vpath, v)
        verdict = v.get("verdict") or {}
        per_model.setdefault(chal, {"wins": 0, "ties": 0, "losses": 0})
        for axis in _AXES:
            val = (verdict.get(axis) or "").lower()
            outcome = _challenger_outcome(val, pos)
            if outcome is None:
                continue
            axis_counts[axis][outcome] += 1
            if axis == "overall":
                if outcome == "challenger":
                    per_model[chal]["wins"] += 1
                elif outcome == "champion":
                    per_model[chal]["losses"] += 1
                else:
                    per_model[chal]["ties"] += 1
    assert judged + failed == attempted, f"quiet drop: {judged}+{failed}!={attempted}"
    print(f"# Eval report ({suite})")
    fail_rate = (failed / attempted) if attempted else 0.0
    print(f"Judge: attempted={attempted} judged={judged} failed={failed} (failure rate {fail_rate:.1%})")
    print(f"  Judgment invariant: judged + failed == attempted  ->  {judged} + {failed} == {attempted}")
    print("## Per-axis outcome (challenger / champion / tie)")
    for axis in _AXES:
        c = axis_counts[axis]
        print(f"  {axis}: challenger={c['challenger']} champion={c['champion']} tie={c['tie']}")
    print("## Per-model overall (vs champion)")
    for chal in sorted(per_model):
        d = per_model[chal]
        print(f"  {chal}: wins={d['wins']} ties={d['ties']} losses={d['losses']}")
    calls = judged + failed
    print(f"# Cost: ~{calls} judge call(s) @ Sonnet pricing (~${calls * _SONNET_PER_CALL_USD:.2f} est.)")
    agreement = None
    if ratings_path is not None:
        from benchmarks.eval_manifest import load_manifest
        m = load_manifest()
        champion_tag = next((c.tag for c in m.contestants if c.role == "champion"), m.contestants[0].tag)
        challenger_tags = [c.tag for c in m.contestants if c.role == "challenger"]
        agreement = _human_judge_agreement(base, suite, champion_tag, challenger_tags, ratings_path)
    if agreement is not None:
        agreed, total = agreement
        rate = agreed / total if total else 0.0
        print(f"# Human–judge agreement (headline): {agreed}/{total} = {rate:.0%}")
    else:
        print("# Human–judge agreement (headline): no ratings available (run `rate`)")
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
    j.add_argument("--model", default=None, help="Judge model; default claude-sonnet-5 for Claude, manifest champion for local.")
    j.add_argument("--judge-runs", default="run0", help="run0 or all")
    j.add_argument("--suite", choices=["public", "private"], default="public")
    r = sub.add_parser("rate", help="Layer-3 blind A/B REPL.")
    r.add_argument("--suite", choices=["public", "private"], default="public")
    r.add_argument("--ratings", default="benchmarks/eval_data/ratings.json")
    rep = sub.add_parser("report", help="Pure aggregation over cached outputs.")
    rep.add_argument("--suite", default="public")
    rep.add_argument("--ratings", default="benchmarks/eval_data/ratings.json")
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
        return cmd_judge(base=Path("benchmarks/eval_data"), backend=args.backend, model=args.model, judge_runs=args.judge_runs, suite=args.suite)
    elif args.cmd == "rate":
        return cmd_rate(base=Path("benchmarks/eval_data"), suite=args.suite, ratings_path=Path(args.ratings))
    elif args.cmd == "report":
        return cmd_report(base=Path("benchmarks/eval_data"), suite=args.suite, ratings_path=Path(args.ratings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
