"""Unit tests for benchmarks/bench_meeting.py — no ffmpeg, no real models."""
from __future__ import annotations

import yaml
import pytest

from benchmarks.bench_meeting import (
    available_models,
    discover_media_and_vtt,
    ingest,
    vtt_to_text,
    write_manifest,
)


def test_available_models_dedupes_aliases():
    models = available_models()
    # turbo aliases large-v3-turbo -> only one of them appears, and by insertion
    # order in MODEL_MAP that is 'large-v3-turbo'.
    assert "large-v3-turbo" in models
    assert "turbo" not in models
    assert "base" in models
    assert len(models) == len(set(models))


def test_vtt_to_text_strips_headers_timestamps_and_voice_tags():
    vtt = (
        "WEBVTT\n"
        "\n"
        "2b226284-5cb0-4cc2-b1a9-c286c6ceee39/7-0\n"
        "00:00:03.869 --> 00:00:04.509\n"
        "<v Anurag Kaushik>Okay.</v>\n"
        "\n"
        "2b226284-5cb0-4cc2-b1a9-c286c6ceee39/8-0\n"
        "00:00:08.749 --> 00:00:12.349\n"
        "<v Nahid>Thanks everybody for joining.\n"
        "Hey, go ahead.</v>\n"
    )
    ref = vtt_to_text(vtt)
    assert ref == "Okay. Thanks everybody for joining. Hey, go ahead."
    assert "WEBVTT" not in ref
    assert "-->" not in ref
    assert "<v" not in ref
    # speaker names in tags must not leak into the reference text
    assert "Anurag" not in ref


def test_vtt_to_text_collapses_whitespace():
    assert vtt_to_text("WEBVTT\n\n<v A>foo   bar</v>\n") == "foo bar"


def test_discover_finds_single_pair(tmp_path):
    (tmp_path / "meeting.mp4").write_bytes(b"x")
    (tmp_path / "meeting.vtt").write_text("WEBVTT\n")
    media, vtt = discover_media_and_vtt(tmp_path)
    assert media.name == "meeting.mp4"
    assert vtt.name == "meeting.vtt"


def test_discover_missing_media_raises(tmp_path):
    (tmp_path / "meeting.vtt").write_text("WEBVTT\n")
    with pytest.raises(FileNotFoundError, match="no media file"):
        discover_media_and_vtt(tmp_path)


def test_discover_missing_vtt_raises(tmp_path):
    (tmp_path / "meeting.mp4").write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match="no .vtt"):
        discover_media_and_vtt(tmp_path)


def test_discover_ambiguous_media_raises(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.mov").write_bytes(b"x")
    (tmp_path / "meeting.vtt").write_text("WEBVTT\n")
    with pytest.raises(ValueError, match="multiple media"):
        discover_media_and_vtt(tmp_path)


def test_write_manifest_roundtrips_through_load_manifest(tmp_path):
    from benchmarks.bench_transcribe import load_manifest

    asr = tmp_path / "asr"
    asr.mkdir()
    (asr / "clip.f32").write_bytes(b"\x00\x00\x00\x00")
    (asr / "clip.txt").write_text("hello")
    write_manifest(asr, "clip", 1330.6, "src")
    clips = load_manifest(asr)
    assert clips[0]["name"] == "clip"
    assert clips[0]["duration_s"] == 1330.6


def test_ingest_derives_clip_name_and_writes_fixtures(tmp_path, monkeypatch):
    # stub decode so no ffmpeg is required
    import benchmarks.bench_meeting as bm

    (tmp_path / "Team Sync 2026.mov").write_bytes(b"x")
    (tmp_path / "ref.vtt").write_text("WEBVTT\n\n<v A>Hi there.</v>\n")

    def fake_decode(media, out_f32):
        out_f32.write_bytes(b"\x00\x00\x00\x00")
        return 42.0

    monkeypatch.setattr(bm, "decode_to_f32", fake_decode)
    asr_dir, name, dur = ingest(tmp_path)
    assert name == "team-sync-2026"
    assert dur == 42.0
    assert (asr_dir / "team-sync-2026.txt").read_text() == "Hi there."
    manifest = yaml.safe_load((asr_dir / "manifest.yaml").read_text())
    assert manifest["clips"][0]["name"] == "team-sync-2026"
