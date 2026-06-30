"""Unit tests for benchmarks/bench_transcribe.py — no real audio, no real models."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from benchmarks.bench_transcribe import (
    METRIC_NAMES,
    aggregate_results,
    load_manifest,
    normalize_pair,
    normalize_pair_and_compute,
    parse_clip_line,
    render_markdown_table,
)


def test_load_manifest_returns_clips(tmp_path):
    asr = tmp_path / "asr"
    asr.mkdir()
    (asr / "manifest.yaml").write_text(
        yaml.safe_dump({"clips": [
            {"name": "short-clear", "duration_s": 28.0, "source": "test", "notes": "n"},
            {"name": "short-noisy", "duration_s": 31.5, "source": "test", "notes": "n"},
        ]})
    )
    # matching fixture files exist
    (asr / "short-clear.f32").write_bytes(b"")
    (asr / "short-clear.txt").write_text("hello world")
    (asr / "short-noisy.f32").write_bytes(b"")
    (asr / "short-noisy.txt").write_text("hello noisy")

    clips = load_manifest(asr)
    assert [c["name"] for c in clips] == ["short-clear", "short-noisy"]
    assert clips[0]["duration_s"] == 28.0


def test_load_manifest_raises_on_missing_fixture(tmp_path):
    asr = tmp_path / "asr"
    asr.mkdir()
    (asr / "manifest.yaml").write_text(
        yaml.safe_dump({"clips": [{"name": "only-manifest", "duration_s": 10.0,
                                  "source": "x", "notes": "y"}]})
    )
    # no .f32 or .txt present
    with pytest.raises(FileNotFoundError, match="only-manifest"):
        load_manifest(asr)


def test_load_manifest_raises_on_missing_reference_text(tmp_path):
    asr = tmp_path / "asr"
    asr.mkdir()
    (asr / "manifest.yaml").write_text(
        yaml.safe_dump({"clips": [{"name": "half", "duration_s": 10.0,
                                  "source": "x", "notes": "y"}]})
    )
    (asr / "half.f32").write_bytes(b"\x00\x00\x00\x00")
    # .txt missing
    with pytest.raises(FileNotFoundError, match="half\\.txt"):
        load_manifest(asr)


def test_load_manifest_raises_on_missing_manifest(tmp_path):
    asr = tmp_path / "asr"
    asr.mkdir()
    with pytest.raises(FileNotFoundError, match="manifest.yaml"):
        load_manifest(asr)


def test_normalize_pair_lowercases_and_strips_punctuation():
    ref, hyp = normalize_pair("Hello, World!", "hello world")
    assert ref == "hello world"
    assert hyp == "hello world"


def test_normalize_pair_collapses_whitespace():
    ref, hyp = normalize_pair("a   b\tc", "a b c")
    assert ref == "a b c"
    assert hyp == "a b c"


def test_normalize_pair_strips_leading_trailing():
    ref, _ = normalize_pair("  hi  ", "hi")
    assert ref == "hi"


def test_parse_clip_line_decodes_json_metrics():
    line = json.dumps({
        "clip": "short-clear", "model": "base", "duration_s": 28.0,
        "wall_s": 3.42, "rtf": 0.122,
        "wer": 0.051, "cer": 0.028, "mer": 0.040, "wil": 0.073, "wip": 0.927,
        "hypothesis": "hello", "peak_rss_mb": 980,
    })
    rec = parse_clip_line(line)
    assert rec["clip"] == "short-clear"
    assert rec["model"] == "base"
    assert rec["wer"] == pytest.approx(0.051)
    assert rec["wip"] == pytest.approx(0.927)


def test_metrics_on_known_pair():
    """A small hand-checked example: one deletion, zero substitutions/insertions.

    ref  = "the quick brown fox"
    hyp  = "the quick fox"       # 'brown' deleted
    WER  = 1 deletion / 4 words  = 0.25
    CER, MER, WIL, WIP come from jiwer — we sanity-check ranges, not exact values,
    to avoid coupling the test to a specific jiwer version's rounding.
    """
    ref = "the quick brown fox"
    hyp = "the quick fox"
    metrics = normalize_pair_and_compute(ref, hyp)
    assert metrics["wer"] == pytest.approx(0.25, abs=0.01)
    assert 0.0 < metrics["cer"] < 1.0
    assert 0.0 < metrics["mer"] < 1.0
    assert 0.0 < metrics["wil"] < 1.0
    assert 0.0 < metrics["wip"] < 1.0


def _clip_record(model, clip, wer=0.1, cer=0.05, mer=0.08, wil=0.15, wip=0.85,
                 wall_s=3.0, rtf=0.1, duration_s=30.0, peak_rss_mb=900):
    return {
        "model": model, "clip": clip, "duration_s": duration_s,
        "wall_s": wall_s, "rtf": rtf,
        "wer": wer, "cer": cer, "mer": mer, "wil": wil, "wip": wip,
        "hypothesis": "x", "peak_rss_mb": peak_rss_mb,
    }


def test_aggregate_results_groups_by_model():
    records = [
        _clip_record("base", "a", wer=0.1, peak_rss_mb=900),
        _clip_record("base", "b", wer=0.2, peak_rss_mb=900),  # peak is constant per model
        _clip_record("large-v3-turbo", "a", wer=0.05, peak_rss_mb=4200),
        _clip_record("large-v3-turbo", "b", wer=0.07, peak_rss_mb=4200),
    ]
    agg = aggregate_results(records)
    assert set(agg.keys()) == {"base", "large-v3-turbo"}
    assert agg["base"]["clips"] == 2
    assert agg["base"]["mean_wer"] == pytest.approx(0.15)
    assert agg["base"]["peak_rss_mb"] == 900
    assert agg["large-v3-turbo"]["mean_wer"] == pytest.approx(0.06)


def test_aggregate_results_computes_mean_for_all_metrics():
    records = [_clip_record("base", "a", wer=0.1, cer=0.02, mer=0.04, wil=0.08, wip=0.92)]
    agg = aggregate_results(records)
    assert agg["base"]["mean_wer"] == pytest.approx(0.1)
    assert agg["base"]["mean_cer"] == pytest.approx(0.02)
    assert agg["base"]["mean_mer"] == pytest.approx(0.04)
    assert agg["base"]["mean_wil"] == pytest.approx(0.08)
    assert agg["base"]["mean_wip"] == pytest.approx(0.92)
    assert agg["base"]["mean_rtf"] == pytest.approx(0.1)
    assert agg["base"]["mean_wall_s"] == pytest.approx(3.0)


def test_render_markdown_table_has_all_columns_and_rows():
    records = [
        _clip_record("base", "a", wer=0.10, cer=0.06, mer=0.09, wil=0.17, wip=0.83),
        _clip_record("large-v3-turbo", "a", wer=0.05, cer=0.03, mer=0.04, wil=0.07, wip=0.93),
    ]
    agg = aggregate_results(records)
    md = render_markdown_table(agg)
    # header has every column
    for col in ("Model", "Params", "Mean RTF", "Peak RSS (MB)",
                "Mean WER", "Mean CER", "Mean MER", "Mean WIL", "Mean WIP"):
        assert col in md
    # one row per model
    assert "| `base`" in md
    assert "| `large-v3-turbo`" in md


def test_render_markdown_table_orders_models_by_param_count():
    records = [
        _clip_record("large-v3-turbo", "a"),
        _clip_record("base", "a"),
    ]
    agg = aggregate_results(records)
    md = render_markdown_table(agg)
    base_pos = md.find("`base`")
    turbo_pos = md.find("`large-v3-turbo`")
    assert base_pos < turbo_pos, "base should be listed before large-v3-turbo"
