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
