"""Offline tests for diarizer.py. No model, no torch, no pyannote."""
import os

import pytest

from podscribe.diarizer import Utterance, Diarizer


SAMPLE_ORIG_MD = """# Meeting: 2026-07-01-120000-sam-chen

- pod: sam-chen (Sam Chen)
- started: 2026-07-01T12:00:00
- model: mlx-community/whisper-large-v3-turbo
- vad: webrtcvad (aggressiveness=2)

## Transcript

[00:00:03] Hello, welcome.
[00:00:09] How are you doing?
[00:00:14] Good, let's get started.
"""


def test_write_diarized_transcript_preserves_header_and_labels(tmp_path):
    orig = tmp_path / "meeting.md"
    orig.write_text(SAMPLE_ORIG_MD)
    out = tmp_path / "meeting.diarized.md"
    utterances = [
        Utterance(3.0, 7.0, 0, "Hello, welcome."),
        Utterance(9.0, 13.0, 1, "How are you doing?"),
        Utterance(14.0, 18.0, 0, "Good, let's get started."),
    ]
    Diarizer.write_diarized_transcript(orig, utterances, out)
    text = out.read_text()
    header = text.split("## Transcript", 1)[0]
    assert "Meeting: 2026-07-01-120000-sam-chen" in header
    assert "vad: webrtcvad (aggressiveness=2)" in header
    lines = [ln for ln in text.splitlines() if ln.startswith("[")]
    assert lines == [
        "[00:00:03] Speaker 0: Hello, welcome.",
        "[00:00:09] Speaker 1: How are you doing?",
        "[00:00:14] Speaker 0: Good, let's get started.",
    ]


def test_write_diarized_transcript_no_partial_on_error(tmp_path, monkeypatch):
    orig = tmp_path / "meeting.md"
    orig.write_text(SAMPLE_ORIG_MD)
    out = tmp_path / "meeting.diarized.md"
    utterances = [Utterance(3.0, 7.0, 0, "Hi")]
    monkeypatch.setattr(os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        Diarizer.write_diarized_transcript(orig, utterances, out)
    assert not out.exists()


def test_parse_transcript_lines(tmp_path):
    md = tmp_path / "m.md"
    md.write_text(SAMPLE_ORIG_MD)
    assert Diarizer._parse_transcript_lines(md) == [
        (3.0, "Hello, welcome."),
        (9.0, "How are you doing?"),
        (14.0, "Good, let's get started."),
    ]


def test_renumber_speakers_first_appearance():
    assert Diarizer._renumber_speakers([2, 2, 0, 2, 1, 0, 0]) == [0, 0, 1, 0, 2, 1, 1]


def test_renumber_speakers_none_uses_nearest_preceding():
    assert Diarizer._renumber_speakers([None, 2, None, 1, None]) == [0, 0, 0, 1, 1]


def test_snap_turns_to_lines_covers_and_falls_back():
    line_secs = [3.0, 9.0, 14.0, 20.0]
    turns = [(2.0, 7.0, 5), (18.0, 25.0, 7)]
    assert Diarizer._snap_turns_to_lines(turns, line_secs) == [5, None, None, 7]


def test_snap_turns_to_lines_latest_start_wins_on_overlap():
    assert Diarizer._snap_turns_to_lines([(0.0, 10.0, 0), (4.0, 6.0, 1)], [5.0]) == [1]


def test_diarize_end_to_end_with_stubbed_pipeline(tmp_path, monkeypatch):
    md = tmp_path / "m.md"
    md.write_text(SAMPLE_ORIG_MD)
    audio = tmp_path / "m.raw"
    audio.write_bytes(b"\x00" * 100)
    fake_turns = [(2.0, 7.0, 1), (8.0, 13.0, 0), (13.0, 20.0, 1)]
    dia = Diarizer(hf_token="fake")
    monkeypatch.setattr(dia, "_run_pipeline", lambda audio_path: fake_turns)
    utt = dia.diarize(audio, md)
    assert [u.speaker for u in utt] == [0, 1, 0]
    assert [u.text for u in utt] == ["Hello, welcome.", "How are you doing?", "Good, let's get started."]
    assert [u.start_sec for u in utt] == [3.0, 9.0, 14.0]
