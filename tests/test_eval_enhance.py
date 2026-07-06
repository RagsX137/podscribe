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
    (base / key).write_text(json.dumps({"response_text": existing_text, "model": "qwen3.6:14b", "digest": "x", "meeting": "meeting2", "run": 0}))

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


def test_generate_regenerates_when_pinned_digest_changes(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    base = Path("benchmarks/eval_data")
    base.mkdir(parents=True, exist_ok=True)
    key = "public__meeting2__qwen3.6_14b__run0.json"
    (base / key).write_text(json.dumps({
        "response_text": "stale", "model": "qwen3.6:14b", "digest": "old-digest",
        "meeting": "meeting2", "run": 0,
    }))

    call_count = {"n": 0}

    def fake_run_once(model, prompt, **kw):
        call_count["n"] += 1
        return {"response_text": "fresh", "response_preview": "", "response_len": 5, "total_s": 0}

    monkeypatch.setattr("benchmarks.eval_enhance.run_once", fake_run_once)
    monkeypatch.setattr("benchmarks.eval_enhance.load_transcript", lambda entry, base_dir: "fake transcript text")

    entries = [{"id": "meeting2", "suite": "public"}]
    contestants = [{"tag": "qwen3.6:14b", "digest": "new-digest", "role": "challenger"}]
    rc = cmd_generate(entries=entries, contestants=contestants, runs=1, base=base)
    assert rc == 0
    assert call_count["n"] == 1
    written = json.loads((base / key).read_text())
    assert written["response_text"] == "fresh"
    assert written["digest"] == "new-digest"


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
    seen_pairs = []

    def fake_judge(pair, **kw):
        seen_pairs.append((pair["challenger"]["text"], pair["champion"]["text"]))
        return {"status": "judged", "verdict": verdict, "raw": "", "attempt": 1}

    monkeypatch.setattr("benchmarks.eval_enhance.judge_pair", fake_judge)
    rc = cmd_judge(base=base, backend="claude", model="claude-sonnet-5", judge_runs="run0", suite="public")
    assert rc == 0
    judged = [p for p in base.iterdir() if "pos_" in p.name]
    assert len(judged) == 2
    assert ("Summary by qwen3.6_14b.", "Summary by qwen3.6_27b.") in seen_pairs
    assert ("Summary by qwen3.6_27b.", "Summary by qwen3.6_14b.") in seen_pairs
    positions = {p.name.split("__")[-1].replace(".verdict.json", "") for p in judged}
    assert positions == {"pos_a_first", "pos_b_first"}


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
    rc = cmd_judge(base=base, backend="claude", model="claude-sonnet-5", judge_runs="run0", suite="public")
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
    rc = cmd_rate(base=base, suite="public", ratings_path=base / "ratings.json")
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


def test_judge_refuses_private_with_claude_backend(monkeypatch, tmp_path, capsys):
    from benchmarks.eval_enhance import cmd_judge
    monkeypatch.chdir(tmp_path)
    base = Path("benchmarks/eval_data")
    base.mkdir(parents=True, exist_ok=True)
    for model in ("qwen3.6_27b", "qwen3.6_14b"):
        (base / f"public__m1__{model}__run0.json").write_text(json.dumps({
            "suite": "public", "meeting": "m1", "model": model, "run": 0,
            "response_text": "x", "response_len": 1,
        }))
    with pytest.raises(SystemExit) as exc:
        cmd_judge(base=base, backend="claude", model="claude-sonnet-5", judge_runs="run0", suite="private")
    assert "cloud" in str(exc.value).lower() or "private" in str(exc.value).lower()


def test_check_stage_groups_runs_by_model_and_meeting(monkeypatch, tmp_path, capsys):
    from benchmarks.eval_enhance import cmd_check
    monkeypatch.chdir(tmp_path)
    base = Path("benchmarks/eval_data")
    base.mkdir(parents=True, exist_ok=True)
    transcript_text = "[00:00:01] Sam: We saw 100 requests."
    for run in range(3):
        (base / f"public__m1__qwen3.6_27b__run{run}.json").write_text(json.dumps({
            "suite": "public", "meeting": "m1", "model": "qwen3.6_27b", "run": run,
            "response_text": "Sam reported 100 requests.",
            "response_len": 22,
        }))
    monkeypatch.setattr("benchmarks.eval_enhance.load_transcript_for_check", lambda entry, base_dir: transcript_text)
    rc = cmd_check(base=base)
    assert rc == 0
    captured = capsys.readouterr()
    assert "qwen3.6_27b" in captured.out


def test_report_computes_human_judge_agreement(monkeypatch, tmp_path, capsys):
    from benchmarks.eval_enhance import cmd_judge, cmd_rate, cmd_report
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
    for model, txt in (("qwen3.6_27b", "champ"), ("qwen3.6_14b", "chal")):
        (base / f"public__m1__{model}__run0.json").write_text(json.dumps({
            "suite": "public", "meeting": "m1", "model": model, "run": 0,
            "response_text": txt, "response_len": 4,
        }))

    def consistent_judge(pair, **kw):
        overall = "a" if pair["challenger"]["text"] == "chal" else "b"
        return {"status": "judged", "verdict": {"overall": overall}, "raw": "", "attempt": 1}

    monkeypatch.setattr("benchmarks.eval_enhance.judge_pair", consistent_judge)
    assert cmd_judge(base=base, backend="claude", model="claude-sonnet-5", judge_runs="run0", suite="public") == 0

    ratings = base / "ratings.json"
    monkeypatch.setattr("builtins.input", lambda *a, **kw: "right")
    assert cmd_rate(base=base, suite="public", ratings_path=ratings) == 0

    assert cmd_report(base=base, suite="public", ratings_path=ratings) == 0
    out = capsys.readouterr().out
    assert "Human" in out and "1/1" in out


def test_action_items_for_extracts_list_from_yaml_response():
    from benchmarks.eval_enhance import _action_items_for
    response = (
        "quick_summary: shipped it\n"
        "action_items:\n"
        "  - fix the flaky test\n"
        "  - email the vendor\n"
    )
    assert _action_items_for(response) == ["fix the flaky test", "email the vendor"]


def test_action_items_for_returns_empty_on_unparseable():
    from benchmarks.eval_enhance import _action_items_for
    assert _action_items_for("just some freeform prose, no yaml here") == []
    assert _action_items_for("") == []


def test_report_cost_line_is_free_for_local_backend(monkeypatch, tmp_path, capsys):
    from benchmarks.eval_enhance import cmd_report
    monkeypatch.chdir(tmp_path)
    base = Path("benchmarks/eval_data")
    base.mkdir(parents=True, exist_ok=True)
    (base / "v_a.verdict.json").write_text(json.dumps({
        "status": "judged", "verdict": {"overall": "a"}, "raw": "", "attempt": 1,
        "backend": "local", "challenger": "qwen3.6:14b", "meeting": "m1", "position": "a_first",
    }))
    rc = cmd_report(base=base, suite="private")
    assert rc == 0
    out = capsys.readouterr().out
    assert "$0.00" in out and "local" in out.lower()
    assert "Sonnet" not in out


def test_report_cost_line_uses_sonnet_for_claude_backend(monkeypatch, tmp_path, capsys):
    from benchmarks.eval_enhance import cmd_report
    monkeypatch.chdir(tmp_path)
    base = Path("benchmarks/eval_data")
    base.mkdir(parents=True, exist_ok=True)
    (base / "v_a.verdict.json").write_text(json.dumps({
        "status": "judged", "verdict": {"overall": "a"}, "raw": "", "attempt": 1,
        "backend": "claude", "challenger": "qwen3.6:14b", "meeting": "m1", "position": "a_first",
    }))
    rc = cmd_report(base=base, suite="public")
    assert rc == 0
    assert "Sonnet" in capsys.readouterr().out


def test_human_judge_agreement_uses_stored_fields_not_listing_order(monkeypatch, tmp_path):
    """Agreement must come from the challenger/meeting/seed stored in the rating
    plus the verdicts — never from re-listing the cache dir. Here there are no
    cached response artifacts at all, so any positional re-derivation would find
    nothing; the metric must still compute from ratings + verdicts alone."""
    from benchmarks.eval_enhance import _human_judge_agreement
    monkeypatch.chdir(tmp_path)
    base = Path("benchmarks/eval_data")
    base.mkdir(parents=True, exist_ok=True)
    for pos, overall in (("a_first", "a"), ("b_first", "b")):
        (base / f"v_{pos}.verdict.json").write_text(json.dumps({
            "status": "judged", "verdict": {"overall": overall},
            "position": pos, "challenger": "qwen3.6:14b", "meeting": "m1",
        }))
    ratings = base / "ratings.json"
    ratings.write_text(json.dumps([
        {"pair_id": "pair-0", "choice": "right", "run": 0,
         "meeting": "m1", "challenger": "qwen3.6:14b"},
    ]))
    result = _human_judge_agreement(base, "public", "qwen3.6:27b", ["qwen3.6:14b"], ratings)
    assert result == (1, 1)
