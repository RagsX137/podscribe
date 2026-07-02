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
