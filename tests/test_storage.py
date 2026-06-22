"""Tests for storage layer."""
import json
from datetime import datetime

import pytest

from podscribe.models import Segment
from podscribe.storage import (
    append_segment,
    finalize_meeting,
    init_pod,
    list_meetings,
    load_pod,
    pod_exists,
    read_transcript,
    start_meeting,
)


def test_init_pod_creates_structure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen", display_name="Sam Chen", role="Senior Engineer")
    assert (tmp_path / "pods" / "sam-chen" / "config.yaml").exists()
    assert (tmp_path / "pods" / "sam-chen" / "transcripts").is_dir()
    assert (tmp_path / "pods" / "sam-chen" / "prep").is_dir()
    config = (tmp_path / "pods" / "sam-chen" / "config.yaml").read_text()
    assert "name: sam-chen" in config
    assert "display_name: Sam Chen" in config
    assert "role: Senior Engineer" in config


def test_pod_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert not pod_exists("sam-chen")
    init_pod("sam-chen")
    assert pod_exists("sam-chen")
    assert not pod_exists("nonexistent")


def test_load_pod(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    init_pod("sam-chen", display_name="Sam Chen", role="Eng")
    pod = load_pod("sam-chen")
    assert pod.name == "sam-chen"
    assert pod.display_name == "Sam Chen"
    assert pod.role == "Eng"


def test_load_pod_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        load_pod("nope")


def test_start_meeting_creates_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    when = datetime(2026, 6, 29, 14, 30, 0)
    meeting = start_meeting(pod, when)
    assert meeting.id == "2026-06-29-1430-sam-chen"
    assert meeting.audio_path.exists()
    assert meeting.transcript_path == pod.transcripts_dir / "2026-06-29-1430-sam-chen.md"


def test_append_segment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 29, 14, 30, 0))
    seg = Segment(start_sec=10.0, end_sec=15.0, text="hello world")
    append_segment(meeting, seg)
    content = meeting.transcript_path.read_text()
    assert "hello world" in content
    assert "[00:00:10]" in content


def test_append_multiple_segments(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    meeting = start_meeting(pod)
    append_segment(meeting, Segment(1.0, 2.0, "first"))
    append_segment(meeting, Segment(5.0, 7.0, "second"))
    content = meeting.transcript_path.read_text()
    assert "first" in content
    assert "second" in content


def test_finalize_writes_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 29, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 2.0, "hello"))
    meeting.duration_sec = 600
    finalize_meeting(meeting)
    assert meeting.metadata_path.exists()
    data = json.loads(meeting.metadata_path.read_text())
    assert data["pod_name"] == "sam-chen"
    assert data["duration_sec"] == 600
    assert data["id"] == "2026-06-29-1430-sam-chen"


def test_finalize_deletes_audio_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    meeting = start_meeting(pod)
    assert meeting.audio_path.exists()
    finalize_meeting(meeting)
    assert not meeting.audio_path.exists()


def test_finalize_keeps_audio_with_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    meeting = start_meeting(pod)
    finalize_meeting(meeting, keep_audio=True)
    assert meeting.audio_path.exists()


def test_list_meetings_newest_first(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    m1 = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    finalize_meeting(m1)
    m2 = start_meeting(pod, datetime(2026, 6, 29, 14, 30, 0))
    finalize_meeting(m2)
    meetings = list_meetings(pod)
    assert len(meetings) == 2
    assert meetings[0].id.startswith("2026-06-29")
    assert meetings[1].id.startswith("2026-06-22")


def test_list_meetings_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    assert list_meetings(pod) == []


def test_read_transcript(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    meeting = start_meeting(pod)
    append_segment(meeting, Segment(1.0, 2.0, "hello"))
    append_segment(meeting, Segment(3.0, 5.0, "world"))
    text = read_transcript(meeting)
    assert "hello" in text
    assert "world" in text


def test_read_transcript_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    meeting = start_meeting(pod)
    meeting.transcript_path = None
    with pytest.raises(FileNotFoundError):
        read_transcript(meeting)


def test_pods_isolated(tmp_path, monkeypatch):
    """Critical: pods do not share data."""
    monkeypatch.chdir(tmp_path)
    sam = init_pod("sam-chen", display_name="Sam Chen")
    priya = init_pod("priya-patel", display_name="Priya Patel")
    assert sam.transcripts_dir != priya.transcripts_dir
    assert sam.config_path != priya.config_path
    # Add transcript to sam only
    m = start_meeting(sam)
    append_segment(m, Segment(1.0, 2.0, "sam-only"))
    finalize_meeting(m)
    assert list_meetings(sam)
    assert not list_meetings(priya)
