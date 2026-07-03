from __future__ import annotations

import json

import pytest

from podscribe.cli import main
from podscribe.storage import init_pod, list_kt_sessions

VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhello from the KT\n"


def test_ingest_vtt_creates_kt_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    init_pod("fso")
    video = tmp_path / "kt.mp4"
    video.touch()
    (tmp_path / "kt.vtt").write_text(VTT)

    rc = main(["fso", "ingest", str(video)])
    assert rc == 0

    pod = __import__("podscribe.storage", fromlist=["load_pod"]).load_pod("fso")
    sessions = list_kt_sessions(pod)
    assert len(sessions) == 1
    meta = json.loads(sessions[0].metadata_path.read_text())
    assert meta["source"] == "vtt"
    assert "hello from the KT" in sessions[0].transcript_path.read_text()


def test_ingest_no_transcript_no_asr_errors_with_hint(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    init_pod("fso")
    video = tmp_path / "kt.mp4"
    video.touch()

    rc = main(["fso", "ingest", str(video)])
    assert rc == 1
    assert "--asr" in capsys.readouterr().err


def test_ingest_asr_forces_transcription_even_with_vtt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    init_pod("fso")
    video = tmp_path / "kt.mp4"
    video.touch()
    (tmp_path / "kt.vtt").write_text(VTT)

    # Stub decode + transcriber so no ffmpeg/model is needed.
    import numpy as np
    monkeypatch.setattr("podscribe.media.decode_to_f32", lambda m, o: 3.0)
    monkeypatch.setattr("numpy.fromfile", lambda *a, **k: np.zeros(48000, dtype=np.float32))

    class FakeTranscriber:
        def __init__(self, *a, **k): pass
        def transcribe(self, audio, **k):
            return [{"start": 0.0, "end": 2.0, "text": "asr said this"}]

    monkeypatch.setattr("podscribe.transcriber.Transcriber", FakeTranscriber)

    rc = main(["fso", "ingest", str(video), "--asr"])
    assert rc == 0

    from podscribe.storage import load_pod
    sessions = list_kt_sessions(load_pod("fso"))
    assert len(sessions) == 1
    meta = json.loads(sessions[0].metadata_path.read_text())
    assert meta["source"] == "asr"
    assert "asr said this" in sessions[0].transcript_path.read_text()
