"""Tests for podscribe.search."""
from pathlib import Path
import shutil

import pytest

from podscribe.search import SearchMatch, search


def _make_pod(base: Path, pod_name: str, meetings: list) -> Path:
    """Create a pod with the given meetings. Each meeting is (id, date_str, type, lines)."""
    pod_dir = base / "pods" / pod_name
    pod_dir.mkdir(parents=True, exist_ok=True)
    for mid, date_str, mtype, lines in meetings:
        if mtype:
            tdir = pod_dir / "transcripts" / date_str / mtype
        else:
            tdir = pod_dir / "transcripts" / date_str
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / f"{mid}.md").write_text(
            "# Meeting: " + mid + "\n\n" + "\n".join(lines) + "\n"
        )
    return pod_dir


def test_search_python_backend(tmp_path, monkeypatch):
    """When rg is not on PATH, uses Python rglob + substring match."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("podscribe.search.shutil.which", lambda _: None)
    _make_pod(tmp_path, "sam-chen", [
        ("2026-06-22-143000-sam-chen", "22-JUN-2026", "1on1", [
            "[00:01:23] Discussed Project Helios timeline",
            "[00:02:00] Sam will review the design",
        ]),
    ])
    matches = list(search("Helios"))
    assert len(matches) == 1
    assert matches[0].text == "Discussed Project Helios timeline"
    assert matches[0].timestamp == "[00:01:23]"


def test_search_uses_rg_when_available(tmp_path, monkeypatch):
    """When rg is on PATH, calls rg with -F and parses output."""
    from unittest.mock import patch, MagicMock

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("podscribe.search.shutil.which", lambda cmd: "/usr/bin/rg" if cmd == "rg" else None)
    _make_pod(tmp_path, "sam-chen", [
        ("2026-06-22-143000-sam-chen", "22-JUN-2026", None, [
            "[00:01:23] Discussed Project Helios timeline",
        ]),
    ])

    rg_output = f"pods/sam-chen/transcripts/22-JUN-2026/2026-06-22-143000-sam-chen.md:1:[00:01:23] Discussed Project Helios timeline\n"

    mock_proc = MagicMock()
    mock_proc.stdout = rg_output
    mock_proc.returncode = 0

    with patch("podscribe.search.subprocess.run", return_value=mock_proc) as mock_run:
        matches = list(search("Helios"))

    assert len(matches) == 1
    assert mock_run.called
    args, kwargs = mock_run.call_args
    assert args[0][0] == "rg"
    assert "-F" in args[0]


def test_search_filters_by_pod(tmp_path, monkeypatch):
    """--pod restricts to one pod's transcripts."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("podscribe.search.shutil.which", lambda _: None)
    _make_pod(tmp_path, "sam-chen", [
        ("2026-06-22-143000-sam-chen", "22-JUN-2026", None, ["[00:00:00] Helios mention"]),
    ])
    _make_pod(tmp_path, "priya-rao", [
        ("2026-06-22-100000-priya-rao", "22-JUN-2026", None, ["[00:00:00] Helios mention"]),
    ])
    matches = list(search("Helios", pod="sam-chen"))
    assert len(matches) == 1
    assert matches[0].pod_name == "sam-chen"


def test_search_filters_by_type(tmp_path, monkeypatch):
    """--type 1on1 excludes other types and untyped meetings."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("podscribe.search.shutil.which", lambda _: None)
    _make_pod(tmp_path, "sam-chen", [
        ("2026-06-22-143000-sam-chen", "22-JUN-2026", "1on1", ["[00:00:00] alpha"]),
        ("2026-06-22-150000-sam-chen", "22-JUN-2026", "retro", ["[00:00:00] alpha"]),
        ("2026-06-22-160000-sam-chen", "22-JUN-2026", None, ["[00:00:00] alpha"]),
    ])
    matches = list(search("alpha", meeting_type="1on1"))
    assert len(matches) == 1
    assert "143000" in matches[0].meeting_id


def test_search_empty_result(tmp_path, monkeypatch, capsys):
    """No matches → empty list (caller prints 'No matches.')."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("podscribe.search.shutil.which", lambda _: None)
    _make_pod(tmp_path, "sam-chen", [
        ("2026-06-22-143000-sam-chen", "22-JUN-2026", None, ["[00:00:00] nothing relevant"]),
    ])
    matches = list(search("zzz_no_such_thing_xyz"))
    assert matches == []


def test_search_since_filter(tmp_path, monkeypatch):
    """--since excludes older files (uses meeting ID prefix date)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("podscribe.search.shutil.which", lambda _: None)
    _make_pod(tmp_path, "sam-chen", [
        ("2026-01-15-100000-sam-chen", "15-JAN-2026", None, ["[00:00:00] old alpha"]),
        ("2026-06-22-143000-sam-chen", "22-JUN-2026", None, ["[00:00:00] new alpha"]),
    ])
    matches = list(search("alpha", since="2026-06-01"))
    assert len(matches) == 1
    assert "143000" in matches[0].meeting_id


def test_search_excludes_kt_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.cli import main as cli_main
    from podscribe.storage import init_pod
    init_pod("fso")
    video = tmp_path / "kt.mp4"
    video.touch()
    (tmp_path / "kt.vtt").write_text("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nzebra term\n")
    assert cli_main(["fso", "ingest", str(video)]) == 0

    from podscribe.search import search
    assert list(search("zebra term")) == []                       # excluded by default
    hits = list(search("zebra term", include_kt=True))
    assert hits and hits[0].pod_name == "fso"                      # correct pod, not "kt"
