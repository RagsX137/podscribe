from __future__ import annotations

import json
from datetime import datetime

import pytest

from podscribe.cli import main
from podscribe.storage import (
    append_segment,
    finalize_kt_session,
    finalize_meeting,
    init_pod,
    list_kt_sessions,
    load_pod,
    start_kt_session,
    start_meeting,
    write_kt_transcript,
)
from podscribe.models import Segment

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


def test_show_kt_reads_kt_subtree(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    init_pod("fso")
    video = tmp_path / "kt.mp4"
    video.touch()
    (tmp_path / "kt.vtt").write_text(VTT)
    assert main(["fso", "ingest", str(video)]) == 0
    assert main(["fso", "show", "--kt", "latest"]) == 0
    assert "hello from the KT" in capsys.readouterr().out


def test_show_latest_merges_meeting_and_kt_by_timestamp(tmp_path, monkeypatch, capsys):
    """Regression: `show latest` (no --kt) must chronologically merge meetings
    and KT sessions, not just concatenate list_meetings() + list_kt_sessions().

    An older meeting plus a newer KT session should resolve to the KT session.
    """
    monkeypatch.chdir(tmp_path)
    init_pod("fso")
    pod = load_pod("fso")

    older = datetime(2026, 1, 1, 9, 0, 0)
    newer = datetime(2026, 6, 1, 9, 0, 0)

    # Older meeting.
    meeting = start_meeting(pod, when=older)
    append_segment(meeting, Segment(start_sec=0.0, end_sec=1.0, text="older meeting content"))
    finalize_meeting(meeting)

    # Newer KT session, ingested later.
    kt = start_kt_session(pod, when=newer)
    write_kt_transcript(kt, [(1.0, "newer kt content")])
    finalize_kt_session(
        kt, source="vtt", original_media="kt.mp4",
        recorded_at=None, duration_sec=3, model="",
    )

    rc = main(["fso", "show", "latest"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "newer kt content" in out
    assert "older meeting content" not in out


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


def test_ingest_asr_missing_mlx_whisper_errors_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    init_pod("fso")
    video = tmp_path / "kt.mp4"
    video.touch()

    # Stub decode so we reach Transcriber() before hitting the missing-dep error.
    monkeypatch.setattr("podscribe.media.decode_to_f32", lambda m, o: 3.0)
    import numpy as np
    monkeypatch.setattr("numpy.fromfile", lambda *a, **k: np.zeros(48000, dtype=np.float32))

    class FakeTranscriber:
        def __init__(self, *a, **k): pass
        def transcribe(self, audio, **k):
            raise ImportError("mlx-whisper is required. Install with: pip install mlx-whisper")

    monkeypatch.setattr("podscribe.transcriber.Transcriber", FakeTranscriber)

    rc = main(["fso", "ingest", str(video), "--asr"])
    assert rc == 1
    assert "mlx-whisper is required" in capsys.readouterr().err


def test_ingest_missing_transcript_path_errors_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    init_pod("fso")
    video = tmp_path / "kt.mp4"
    video.touch()
    missing = tmp_path / "does-not-exist.vtt"

    rc = main(["fso", "ingest", str(video), "--transcript", str(missing)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "No such transcript file" in err
    assert str(missing) in err


def test_enhance_kt_writes_to_kt_summaries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    init_pod("fso")
    video = tmp_path / "kt.mp4"
    video.touch()
    (tmp_path / "kt.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n" + ("blah " * 40) + "\n"
    )
    assert main(["fso", "ingest", str(video)]) == 0

    # Project LLM config + stub the LLM call.
    import yaml
    (tmp_path / "podscribe.yaml").write_text(
        yaml.safe_dump({"llm": {"model": "m", "prompt_template": "T {{transcript}}"}})
    )
    monkeypatch.setattr("podscribe.cli._run_enhance", lambda prompt, model: ("KT SUMMARY", None))

    from podscribe.storage import load_pod, list_kt_sessions
    sid = list_kt_sessions(load_pod("fso"))[0].id
    rc = main(["fso", "enhance", "--kt", sid])
    assert rc == 0

    hits = list((tmp_path / "pods" / "fso" / "kt" / "summaries").rglob(f"{sid}.md"))
    assert hits and hits[0].read_text() == "KT SUMMARY"


def test_ask_one_shot_returns_grounded_answer(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    init_pod("fso")
    video = tmp_path / "kt.mp4"
    video.touch()
    (tmp_path / "kt.vtt").write_text(VTT)
    assert main(["fso", "ingest", str(video)]) == 0

    import yaml
    (tmp_path / "podscribe.yaml").write_text(
        yaml.safe_dump({"llm": {"model": "m", "prompt_template": "x"}})
    )

    captured = {}

    def fake_chat_stream(model, messages, **kwargs):
        captured["messages"] = messages
        on_token = kwargs.get("on_token", lambda t: None)
        on_token("grounded answer")
        return "grounded answer"

    monkeypatch.setattr("podscribe.cli.chat_stream", fake_chat_stream)

    rc = main(["fso", "ask", "latest", "what", "is", "this?"])
    assert rc == 0
    # The transcript text must be in the prompt (grounding), and the user question present.
    joined = " ".join(m["content"] for m in captured["messages"])
    assert "hello from the KT" in joined
    assert "what is this?" in joined
    assert "grounded answer" in capsys.readouterr().out


def test_ask_one_shot_reports_llm_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    init_pod("fso")
    video = tmp_path / "kt.mp4"
    video.touch()
    (tmp_path / "kt.vtt").write_text(VTT)
    assert main(["fso", "ingest", str(video)]) == 0

    import yaml
    (tmp_path / "podscribe.yaml").write_text(
        yaml.safe_dump({"llm": {"model": "m", "prompt_template": "x"}})
    )

    def fake_chat_stream(model, messages, **kwargs):
        # Simulate Ollama-not-running / exhausted retries: on_token never fires.
        return None

    monkeypatch.setattr("podscribe.cli.chat_stream", fake_chat_stream)

    capsys.readouterr()  # discard ingest output
    rc = main(["fso", "ask", "latest", "some", "question"])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "Failed to get a response" in captured.err
