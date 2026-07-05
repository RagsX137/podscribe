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
