# tests/test_eval_enhance.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.eval_enhance import cmd_generate


def test_generate_skips_existing_cache(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    base = Path("benchmarks/eval_data")
    base.mkdir(parents=True, exist_ok=True)
    existing_text = "cached-response"
    key = "public__meeting2__qwen3.6_14b__run0.json"
    (base / key).write_text(json.dumps({"response_text": existing_text, "model": "qwen3.6:14b", "meeting": "meeting2", "run": 0}))

    call_count = {"n": 0}

    def fake_run_once(model, prompt, **kw):
        call_count["n"] += 1
        return {"response_text": "should-not-be-called", "response_preview": "", "response_len": 0, "total_s": 0}

    monkeypatch.setattr("benchmarks.eval_enhance.run_once", fake_run_once)

    def fake_load_transcript(entry, base_dir):
        return "fake transcript text"

    monkeypatch.setattr("benchmarks.eval_enhance.load_transcript", fake_load_transcript)

    entries = [{"id": "meeting2", "suite": "public"}]
    contestants = [{"tag": "qwen3.6:14b", "digest": "x", "role": "challenger"}]
    rc = cmd_generate(entries=entries, contestants=contestants, runs=1, base=base)
    assert rc == 0
    assert call_count["n"] == 0


def test_check_stage_reads_cache_and_reports(monkeypatch, tmp_path, capsys):
    from benchmarks.eval_enhance import cmd_check
    monkeypatch.chdir(tmp_path)
    base = Path("benchmarks/eval_data")
    base.mkdir(parents=True, exist_ok=True)
    transcript_text = "[00:00:01] Sam: We saw 100 requests."
    (base / "public__m1__qwen3.6_27b__run0.json").write_text(json.dumps({
        "suite": "public", "meeting": "m1", "model": "qwen3.6_27b", "run": 0,
        "response_text": "Sam reported 100 requests.",
        "response_len": 22,
    }))
    monkeypatch.setattr("benchmarks.eval_enhance.load_transcript_for_check", lambda entry, base_dir: transcript_text)

    rc = cmd_check(base=base)
    assert rc == 0
    captured = capsys.readouterr()
    assert "qwen3.6_27b" in captured.out or "passed" in captured.out.lower()


def test_judge_stage_writes_persisted_verdicts(monkeypatch, tmp_path):
    from benchmarks.eval_enhance import cmd_judge
    monkeypatch.chdir(tmp_path)
    base = Path("benchmarks/eval_data")
    base.mkdir(parents=True, exist_ok=True)
    (Path("benchmarks") / "eval_manifest.yaml").write_text(
        "contestants:\n"
        "  - tag: qwen3.6:27b\n"
        "    digest: d27\n"
        "    role: champion\n"
        "  - tag: qwen3.6:14b\n"
        "    digest: d14\n"
        "    role: challenger\n"
    )
    for model in ("qwen3.6_27b", "qwen3.6_14b"):
        (base / f"public__m1__{model}__run0.json").write_text(json.dumps({
            "suite": "public", "meeting": "m1", "model": model, "run": 0,
            "response_text": f"Summary by {model}.", "response_len": 10,
        }))
    verdict = {"coverage": "a", "faithfulness": "a", "readability": "b", "action-item quality": "tie", "overall": "a", "justification": "A is better."}
    monkeypatch.setattr("benchmarks.eval_enhance.judge_pair", lambda pair, **kw: {"status": "judged", "verdict": verdict, "raw": "", "attempt": 1})
    rc = cmd_judge(base=base, backend="claude", model="claude-sonnet-5", judge_runs="run0")
    assert rc == 0
    judged = [p for p in base.iterdir() if "pos_" in p.name]
    assert len(judged) == 2


def test_judge_stage_asserts_judged_plus_failed_eq_attempted(monkeypatch, tmp_path):
    from benchmarks.eval_enhance import cmd_judge
    monkeypatch.chdir(tmp_path)
    base = Path("benchmarks/eval_data")
    base.mkdir(parents=True, exist_ok=True)
    (Path("benchmarks") / "eval_manifest.yaml").write_text(
        "contestants:\n"
        "  - tag: qwen3.6:27b\n"
        "    digest: d27\n"
        "    role: champion\n"
        "  - tag: qwen3.6:14b\n"
        "    digest: d14\n"
        "    role: challenger\n"
    )
    for model in ("qwen3.6_27b", "qwen3.6_14b"):
        (base / f"public__m1__{model}__run0.json").write_text(json.dumps({
            "suite": "public", "meeting": "m1", "model": model, "run": 0,
            "response_text": "x", "response_len": 1,
        }))
    from itertools import count
    calls = count()
    def fake(pair, **kw):
        return {"status": "judged", "verdict": {"overall": "a"}, "raw": "", "attempt": 1} if next(calls) == 0 else {"status": "failed", "raw": "bad", "attempt": 2}
    monkeypatch.setattr("benchmarks.eval_enhance.judge_pair", fake)
    rc = cmd_judge(base=base, backend="claude", model="claude-sonnet-5", judge_runs="run0")
    assert rc == 0


def test_rate_stage_logs_rating_to_file(monkeypatch, tmp_path, capsys):
    from benchmarks.eval_enhance import cmd_rate
    monkeypatch.chdir(tmp_path)
    base = Path("benchmarks/eval_data")
    base.mkdir(parents=True, exist_ok=True)
    (Path("benchmarks") / "eval_manifest.yaml").write_text(
        "contestants:\n"
        "  - tag: qwen3.6:27b\n"
        "    digest: d27\n"
        "    role: champion\n"
        "  - tag: qwen3.6:14b\n"
        "    digest: d14\n"
        "    role: challenger\n"
    )
    for model in ("qwen3.6_27b", "qwen3.6_14b"):
        (base / f"public__m1__{model}__run0.json").write_text(json.dumps({
            "suite": "public", "meeting": "m1", "model": model, "run": 0,
            "response_text": f"Summary by {model}.", "response_len": 10,
        }))
    monkeypatch.setattr("builtins.input", lambda *a, **kw: "left")
    rc = cmd_rate(base=base, ratings_path=base / "ratings.json")
    assert rc == 0
    assert (base / "ratings.json").exists()


def test_report_stage_prints_summary_and_respects_invariant(monkeypatch, tmp_path, capsys):
    from benchmarks.eval_enhance import cmd_report
    monkeypatch.chdir(tmp_path)
    base = Path("benchmarks/eval_data")
    base.mkdir(parents=True, exist_ok=True)
    (base / "public__m1__qwen3.6_27b__run0.json").write_text(json.dumps({"suite": "public", "meeting": "m1", "model": "qwen3.6_27b", "run": 0, "response_text": "a", "response_len": 1}))
    (base / "public__m1__qwen3.6_14b__run0.json").write_text(json.dumps({"suite": "public", "meeting": "m1", "model": "qwen3.6_14b", "run": 0, "response_text": "b", "response_len": 1}))
    (base / "public__m1__qwen3.6_14b__vs__qwen3.6_27b__m1__run0__pos_a_first.verdict.json").write_text(json.dumps({"status": "judged", "verdict": {"overall": "a"}, "raw": "", "attempt": 1}))
    (base / "public__m1__qwen3.6_14b__vs__qwen3.6_27b__m1__run0__pos_b_first.verdict.json").write_text(json.dumps({"status": "failed", "raw": "x", "attempt": 2}))
    rc = cmd_report(base=base, suite="public")
    assert rc == 0
    captured = capsys.readouterr()
    assert "judged" in captured.out.lower() or "attempted" in captured.out.lower()
