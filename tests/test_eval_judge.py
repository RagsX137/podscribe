# tests/test_eval_judge.py
from __future__ import annotations

import json
from pathlib import Path

from benchmarks.eval_judge import (
    anonymize_pair,
    build_rubric_prompt,
    pair_key,
    parse_verdict,
    swapped_key,
)


def test_pair_key_includes_challenger_champion_meeting_run():
    k = pair_key("qwen3.6:14b", "qwen3.6:27b", "m1", run=0)
    assert "qwen3.6:14b" in k and "m1" in k and "run0" in k


def test_swapped_key_differs_from_pair_key():
    a = pair_key("qwen3.6:14b", "qwen3.6:27b", "m1", run=0)
    b = swapped_key(a)
    assert a != b
    assert "pos_a_first" in a
    assert "pos_b_first" in b


def test_anonymize_pair_strips_model_names():
    pair = {
        "challenger": {"model": "qwen3.6:14b", "text": "hi from qwen"},
        "champion": {"model": "qwen3.6:27b", "text": "hi from the bigger one"},
    }
    anon = anonymize_pair(pair)
    serialized = json.dumps(anon)
    assert "qwen" not in serialized.lower()
    assert "Summary A" in serialized or "summary_a" in serialized
    assert "Summary B" in serialized or "summary_b" in serialized


def test_build_rubric_prompt_contains_axes():
    prompt = build_rubric_prompt("Summary A text", "Summary B text")
    for axis in ["coverage", "faithfulness", "readability", "action-item quality"]:
        assert axis in prompt.lower()
    assert "Summary A" in prompt
    assert "Summary B" in prompt


def test_parse_verdict_extracts_axis_and_overall():
    raw = (
        "coverage: A\nfaithfulness: B\nreadability: A\n"
        "action-item quality: tie\noverall: A\n"
        "Justification: A is more complete."
    )
    v = parse_verdict(raw)
    assert v["overall"] == "a"
    assert v["coverage"] == "a"
    assert v["faithfulness"] == "b"
    assert v["action-item quality"] == "tie"
    assert v["justification"].startswith("A is more complete")


def test_parse_verdict_returns_none_on_malformed():
    assert parse_verdict("totally random text without structure") is None
