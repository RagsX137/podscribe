from __future__ import annotations

import json
from datetime import datetime

import pytest

from podscribe.models import Pod
from podscribe.storage import (
    finalize_kt_session,
    init_pod,
    list_kt_sessions,
    list_meetings,
    start_kt_session,
    write_kt_transcript,
)


def _pod(tmp_path):
    return init_pod("fso")


def test_kt_session_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = _pod(tmp_path)
    when = datetime(2026, 7, 3, 9, 0, 0)
    m = start_kt_session(pod, when=when)
    assert m.type == "kt"
    assert "kt/transcripts" in str(m.transcript_path)

    write_kt_transcript(m, [(1.0, "hello"), (70.5, "world")])
    finalize_kt_session(
        m, source="vtt", original_media="kt.mp4",
        recorded_at="2026-06-01T10:00:00", duration_sec=71, model="",
    )

    body = m.transcript_path.read_text()
    assert "[00:00:01] hello" in body
    assert "[00:01:10] world" in body

    meta = json.loads(m.metadata_path.read_text())
    assert meta["type"] == "kt"
    assert meta["source"] == "vtt"
    assert meta["original_media"] == "kt.mp4"
    assert meta["recorded_at"] == "2026-06-01T10:00:00"


def test_list_kt_sessions_newest_first_and_isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = _pod(tmp_path)
    for hh in (9, 11):
        m = start_kt_session(pod, when=datetime(2026, 7, 3, hh, 0, 0))
        write_kt_transcript(m, [(0.0, "x")])
        finalize_kt_session(
            m, source="vtt", original_media="k.mp4",
            recorded_at=None, duration_sec=1, model="",
        )
    sessions = list_kt_sessions(pod)
    assert len(sessions) == 2
    assert sessions[0].started_at > sessions[1].started_at   # newest first
    # KT sessions must NOT leak into the meeting listing:
    assert list_meetings(pod) == []


def test_kt_same_second_collision_suffix(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = _pod(tmp_path)
    when = datetime(2026, 7, 3, 9, 0, 0)
    m1 = start_kt_session(pod, when=when)
    write_kt_transcript(m1, [(0.0, "a")])
    finalize_kt_session(m1, source="vtt", original_media="k.mp4",
                        recorded_at=None, duration_sec=1, model="")
    m2 = start_kt_session(pod, when=when)   # same second, m1 already finalized
    assert m2.id != m1.id
    assert m2.id.endswith("-0001")
