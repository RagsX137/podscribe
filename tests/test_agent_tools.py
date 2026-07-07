from __future__ import annotations

import numpy as np


def test_list_and_show_kt_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.cli import main
    from podscribe.storage import init_pod
    init_pod("fso")
    video = tmp_path / "kt.mp4"
    video.touch()
    (tmp_path / "kt.vtt").write_text("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nkt content here\n")
    assert main(["fso", "ingest", str(video)]) == 0

    from podscribe.agent_tools import list_kt_tool, show_kt
    sessions = list_kt_tool("fso")
    assert len(sessions) == 1
    assert "kt content here" in show_kt("fso", "latest")


class _FakeCapture:
    def __init__(self, segments, vad_aggressiveness=2):
        self._segments = iter(segments)
        self.vad_aggressiveness = vad_aggressiveness
        self.stopped = False

    def segments(self):
        return self._segments

    def stop(self):
        self.stopped = True


class _FakeTranscriber:
    def __init__(self, model="large-v3-turbo", backend="auto"):
        self.model_name = model
        self.backend = backend

    def transcribe(self, audio, **kwargs):
        return [{"start": 0.0, "end": 1.0, "text": "hello"}]


def test_start_recording_writes_full_header_and_forwards_backend(tmp_path, monkeypatch):
    """#11: god-mode header should match run_record_session's; #18: backend must reach Transcriber."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod
    import podscribe.agent_tools as at

    at._recording_session = None
    init_pod("sam-chen", display_name="Sam")

    captured = {}

    def _fake_capture_ctor(vad_aggressiveness=2):
        return _FakeCapture([np.zeros(16000, dtype=np.float32)], vad_aggressiveness)

    def _fake_transcriber_ctor(model="large-v3-turbo", backend="auto"):
        captured["backend"] = backend
        return _FakeTranscriber(model, backend)

    monkeypatch.setattr("podscribe.audio.AudioCapture", _fake_capture_ctor)
    monkeypatch.setattr("podscribe.transcriber.Transcriber", _fake_transcriber_ctor)

    result = at.start_recording("sam-chen", model="large-v3-turbo", backend="whisper-faster")
    assert result["status"] == "recording"
    session = at._recording_session
    session["thread"].join(timeout=5)
    assert not session["thread"].is_alive()

    assert captured["backend"] == "whisper-faster"
    header = session["meeting"].transcript_path.read_text()
    assert "- pod: sam-chen (Sam)" in header
    assert "- started:" in header
    assert "- model: large-v3-turbo" in header
    assert "- vad: webrtcvad (aggressiveness=2)" in header
    assert "## Transcript" in header

    at._recording_session = None
