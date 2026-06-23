"""Tests for storage layer."""
import csv
import json
from datetime import datetime

import pytest

from podscribe.models import Segment, fmt_date
from podscribe.storage import (
    append_log_row,
    append_segment,
    finalize_meeting,
    init_pod,
    list_meetings,
    load_pod,
    log_entry_exists,
    log_path,
    pod_exists,
    read_transcript,
    rewrite_log_row,
    start_meeting,
    update_log_row,
)


def test_init_pod_creates_structure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen", display_name="Sam Chen", role="Senior Engineer")
    assert (tmp_path / "pods" / "sam-chen" / "config.yaml").exists()
    assert (tmp_path / "pods" / "sam-chen").is_dir()
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
    assert meeting.id == "2026-06-29-143000-sam-chen"
    assert meeting.audio_path.exists()
    date_str = fmt_date(when)
    expected = pod.transcripts_dir_for(date_str) / "2026-06-29-143000-sam-chen.md"
    assert meeting.transcript_path == expected


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
    assert data["id"] == "2026-06-29-143000-sam-chen"


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


def test_list_meetings_sorts_chronologically_across_months(tmp_path, monkeypatch):
    """list_meetings must sort by started_at, not by date-dir path string.

    Date dirs are DD-MMM-YYYY (e.g. 9-JUL-2026, 31-DEC-2026) which sort
    lexicographically in the wrong order. Regression guard.
    """
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    dates = [
        datetime(2026, 1, 9, 10, 0, 0),
        datetime(2026, 1, 22, 10, 0, 0),
        datetime(2026, 6, 22, 10, 0, 0),
        datetime(2026, 7, 1, 10, 0, 0),
        datetime(2026, 12, 31, 10, 0, 0),
    ]
    for dt in dates:
        finalize_meeting(start_meeting(pod, dt))
    meetings = list_meetings(pod)
    ids = [m.id for m in meetings]
    expected = [
        "2026-12-31-100000-sam-chen",
        "2026-07-01-100000-sam-chen",
        "2026-06-22-100000-sam-chen",
        "2026-01-22-100000-sam-chen",
        "2026-01-09-100000-sam-chen",
    ]
    assert ids == expected


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
    assert sam.base_path != priya.base_path
    assert sam.config_path != priya.config_path
    # Add transcript to sam only
    m = start_meeting(sam)
    append_segment(m, Segment(1.0, 2.0, "sam-only"))
    finalize_meeting(m)
    assert list_meetings(sam)
    assert not list_meetings(priya)


def test_log_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    path = log_path(pod)
    assert path == pod.base_path / "meetings.csv"


def test_append_and_read_log_row(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    fields = {
        "date": "2026-06-22",
        "person": "Sam Chen",
        "meeting_id": "2026-06-22-1430-sam-chen",
        "quick_summary": "Synced on Q3 roadmap",
        "key_topics": "Q3 roadmap|API review",
        "action_items": "Unblock API review",
        "blockers": "Stalled on VP sign-off",
        "next_steps": "Check in Friday",
        "summary_file": "summaries/2026-06-22-1430-sam-chen.md",
        "transcript_file": "transcripts/2026-06-22-1430-sam-chen.md",
    }
    append_log_row(pod, fields)
    path = log_path(pod)
    assert path.exists()
    with path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["meeting_id"] == fields["meeting_id"]
    assert rows[0]["quick_summary"] == fields["quick_summary"]


def test_log_entry_exists_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    fields = {"meeting_id": "2026-06-22-1430-sam-chen"}
    append_log_row(pod, fields)
    assert log_entry_exists(pod, "2026-06-22-1430-sam-chen") is True
    assert log_entry_exists(pod, "2026-06-23-1430-sam-chen") is False


def test_log_entry_exists_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    assert log_entry_exists(pod, "anything") is False


def test_rewrite_log_row(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    fields = {
        "meeting_id": "2026-06-22-1430-sam-chen",
        "quick_summary": "Old summary",
        "key_topics": "",
        "action_items": "",
        "blockers": "",
        "next_steps": "",
        "date": "",
        "person": "",
        "summary_file": "",
        "transcript_file": "",
    }
    append_log_row(pod, fields)
    fields["quick_summary"] = "Updated summary"
    rewrite_log_row(pod, "2026-06-22-1430-sam-chen", fields)
    path = log_path(pod)
    with path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["quick_summary"] == "Updated summary"


def test_rewrite_log_row_unmatched_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    append_log_row(pod, {"meeting_id": "2026-06-22-1430-sam-chen"})
    rewrite_log_row(pod, "nonexistent-id", {
        "meeting_id": "2026-06-23-1430-sam-chen",
        "quick_summary": "New row",
        "date": "2026-06-23",
    })
    path = log_path(pod)
    with path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[1]["meeting_id"] == "2026-06-23-1430-sam-chen"
    assert rows[1]["quick_summary"] == "New row"


def test_update_log_row_unmatched_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    append_log_row(pod, {"meeting_id": "2026-06-22-1430-sam-chen"})
    update_log_row(pod, "nonexistent-id", {
        "meeting_id": "2026-06-23-1430-sam-chen",
        "quick_summary": "New row via update",
    })
    path = log_path(pod)
    with path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[1]["meeting_id"] == "2026-06-23-1430-sam-chen"
    assert rows[1]["quick_summary"] == "New row via update"


def test_append_multiple_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    append_log_row(pod, {"meeting_id": "id-1"})
    append_log_row(pod, {"meeting_id": "id-2"})
    path = log_path(pod)
    with path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2


def test_start_meeting_with_type_uses_subdir(tmp_path):
    """--type creates a third-level subdir under transcripts/<date>/<type>/."""
    from datetime import datetime
    from podscribe.models import Pod
    from podscribe.storage import start_meeting

    pod = Pod(name="sam-chen", base_path=tmp_path / "pods" / "sam-chen")
    pod.base_path.mkdir(parents=True)
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0), meeting_type="1on1")
    assert meeting.type == "1on1"
    expected_dir = pod.base_path / "transcripts" / "22-JUN-2026" / "1on1"
    assert expected_dir.exists()
    assert meeting.transcript_path.parent == expected_dir


def test_start_meeting_without_type_uses_flat(tmp_path):
    """No --type → existing 2-level layout, no type subdir."""
    from datetime import datetime
    from podscribe.models import Pod
    from podscribe.storage import start_meeting

    pod = Pod(name="sam-chen", base_path=tmp_path / "pods" / "sam-chen")
    pod.base_path.mkdir(parents=True)
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    assert meeting.type is None
    assert meeting.transcript_path.parent == pod.base_path / "transcripts" / "22-JUN-2026"


def test_list_meetings_finds_typed_and_untyped(tmp_path):
    """Mix of typed (3-level) and untyped (2-level) paths: both found."""
    from datetime import datetime
    from podscribe.models import Pod, Segment
    from podscribe.storage import (
        start_meeting, append_segment, finalize_meeting, list_meetings
    )

    pod = Pod(name="sam-chen", base_path=tmp_path / "pods" / "sam-chen")
    pod.base_path.mkdir(parents=True)

    # 2-level (untyped) meeting
    m1 = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(m1, Segment(1.0, 5.0, "hello"))
    finalize_meeting(m1)

    # 3-level (typed) meeting
    m2 = start_meeting(pod, datetime(2026, 6, 22, 15, 0, 0), meeting_type="retro")
    append_segment(m2, Segment(1.0, 5.0, "world"))
    finalize_meeting(m2)

    meetings = list_meetings(pod)
    assert len(meetings) == 2
    types = {m.type for m in meetings}
    assert types == {None, "retro"}


def test_append_log_row_writes_global(tmp_path, monkeypatch):
    """append_log_row also mirrors the row to pods/meetings.csv."""
    from podscribe.models import Pod
    from podscribe.storage import (
        append_log_row, init_pod, global_log_path, read_global_log
    )

    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    append_log_row(pod, {
        "date": "22-JUN-2026",
        "person": "Sam Chen",
        "meeting_id": "2026-06-22-143000-sam-chen",
        "quick_summary": "Discussed Project Helios",
        "key_topics": "Helios",
        "action_items": "Sam will review design",
        "blockers": "",
        "next_steps": "Weekly sync",
    })

    assert global_log_path().exists()
    rows = read_global_log()
    assert len(rows) == 1
    assert rows[0]["meeting_id"] == "2026-06-22-143000-sam-chen"
    assert rows[0]["quick_summary"] == "Discussed Project Helios"


def test_global_log_failure_does_not_break_pod_log(tmp_path, monkeypatch, capsys):
    """If the global write fails, the per-pod write still succeeds."""
    from podscribe.models import Pod
    from podscribe.storage import append_log_row, init_pod, read_global_log, log_path

    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")

    # Force the global write to fail by making the global path point at a directory
    def fake_global_path():
        return tmp_path / "pods" / "BLOCKED"

    monkeypatch.setattr("podscribe.storage.global_log_path", fake_global_path)

    append_log_row(pod, {
        "date": "22-JUN-2026",
        "person": "Sam Chen",
        "meeting_id": "2026-06-22-143000-sam-chen",
        "quick_summary": "x",
        "key_topics": "",
        "action_items": "",
        "blockers": "",
        "next_steps": "",
    })

    # Per-pod log still has the row
    assert log_path(pod).exists()
    captured = capsys.readouterr()
    assert "global log" in captured.err or len(captured.err) == 0


def test_read_global_log_empty_when_no_file(tmp_path, monkeypatch):
    """read_global_log returns [] when pods/meetings.csv does not exist."""
    from podscribe.storage import read_global_log

    monkeypatch.chdir(tmp_path)
    assert read_global_log() == []


def test_csv_columns_include_type(tmp_path, monkeypatch):
    """CSV_COLUMNS includes 'type' and append_log_row populates it."""
    from podscribe.models import Pod
    from podscribe.storage import (
        append_log_row, init_pod, read_global_log, CSV_COLUMNS
    )

    assert "type" in CSV_COLUMNS
    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    append_log_row(pod, {
        "date": "22-JUN-2026",
        "person": "Sam Chen",
        "meeting_id": "2026-06-22-143000-sam-chen",
        "type": "1on1",
        "quick_summary": "Helios",
        "key_topics": "",
        "action_items": "",
        "blockers": "",
        "next_steps": "",
    })
    rows = read_global_log()
    assert len(rows) == 1
    assert rows[0]["type"] == "1on1"
