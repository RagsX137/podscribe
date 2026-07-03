from __future__ import annotations

from pathlib import Path

import pytest

from podscribe.media import (
    MEDIA_EXTS,
    discover_transcript,
    parse_transcript_cues,
)

VTT = """WEBVTT

00:00:01.000 --> 00:00:04.000
<v Alice>Welcome to the auth service KT.

00:01:10.500 --> 00:01:13.000
Then we rotate the token.
"""

SRT = """1
00:00:01,000 --> 00:00:04,000
Welcome to the auth service KT.

2
00:01:10,500 --> 00:01:13,000
Then we rotate the token.
"""


def test_parse_vtt_preserves_start_and_strips_voice_tags():
    cues = parse_transcript_cues(VTT)
    assert cues == [
        (1.0, "Welcome to the auth service KT."),
        (70.5, "Then we rotate the token."),
    ]


def test_parse_srt_comma_millis():
    cues = parse_transcript_cues(SRT)
    assert cues[0] == (1.0, "Welcome to the auth service KT.")
    assert cues[1][0] == 70.5


def test_parse_multiline_cue_joins_text():
    vtt = "WEBVTT\n\n00:00:02.000 --> 00:00:05.000\nline one\nline two\n"
    assert parse_transcript_cues(vtt) == [(2.0, "line one line two")]


def test_parse_empty_returns_empty():
    assert parse_transcript_cues("WEBVTT\n") == []


def test_discover_transcript_prefers_vtt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    video = tmp_path / "kt.mp4"
    video.touch()
    (tmp_path / "kt.vtt").write_text(VTT)
    assert discover_transcript(video) == tmp_path / "kt.vtt"


def test_discover_transcript_finds_srt_when_no_vtt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    video = tmp_path / "kt.mp4"
    video.touch()
    (tmp_path / "kt.srt").write_text(SRT)
    assert discover_transcript(video) == tmp_path / "kt.srt"


def test_discover_transcript_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    video = tmp_path / "kt.mp4"
    video.touch()
    assert discover_transcript(video) is None


def test_media_exts_contains_common_containers():
    assert {".mp4", ".mov", ".m4a", ".wav"} <= MEDIA_EXTS
