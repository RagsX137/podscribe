"""Tests for data models and ID generation."""
from datetime import datetime
from pathlib import Path

import pytest

from podscribe.models import (
    Meeting,
    Pod,
    Segment,
    make_meeting_id,
    validate_pod_name,
)


class TestValidatePodName:
    def test_valid_simple(self):
        validate_pod_name("sam")  # no raise

    def test_valid_kebab(self):
        for name in ["sam-chen", "priya", "alex-tan-wei", "user123", "a-1-b"]:
            validate_pod_name(name)

    def test_invalid_empty(self):
        with pytest.raises(ValueError):
            validate_pod_name("")

    def test_invalid_uppercase(self):
        with pytest.raises(ValueError):
            validate_pod_name("Sam-Chen")

    def test_invalid_underscore(self):
        with pytest.raises(ValueError):
            validate_pod_name("sam_chen")

    def test_invalid_double_hyphen(self):
        with pytest.raises(ValueError):
            validate_pod_name("sam--chen")

    def test_invalid_start_hyphen(self):
        with pytest.raises(ValueError):
            validate_pod_name("-sam")

    def test_invalid_end_hyphen(self):
        with pytest.raises(ValueError):
            validate_pod_name("sam-")

    def test_invalid_space(self):
        with pytest.raises(ValueError):
            validate_pod_name("sam chen")

    def test_invalid_special(self):
        with pytest.raises(ValueError):
            validate_pod_name("sam@chen")


class TestMakeMeetingId:
    def test_format(self):
        when = datetime(2026, 6, 29, 14, 30, 12)
        assert make_meeting_id("sam-chen", when) == "2026-06-29-143012-sam-chen"

    def test_format_single_digit_hour(self):
        when = datetime(2026, 6, 29, 9, 5, 7)
        assert make_meeting_id("alex", when) == "2026-06-29-090507-alex"

    def test_default_time(self):
        mid = make_meeting_id("sam-chen")
        assert mid.endswith("-sam-chen")
        # Date prefix should be 18 chars: YYYY-MM-DD-HHMMSS-
        assert mid.startswith("20")  # year prefix
        assert len(mid) == 18 + len("sam-chen")


class TestPod:
    def test_default_display_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pod = Pod(name="sam-chen")
        assert pod.display_name == "Sam Chen"

    def test_explicit_display_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pod = Pod(name="sam-chen", display_name="Sam the Man")
        assert pod.display_name == "Sam the Man"

    def test_default_cadence(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pod = Pod(name="sam-chen")
        assert pod.cadence == "weekly"

    def test_paths(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pod = Pod(name="sam-chen")
        assert pod.base_path == Path("pods") / "sam-chen"
        assert pod.config_path == Path("pods") / "sam-chen" / "config.yaml"
        assert pod.transcripts_dir_for("22-JUN-2026") == Path("pods") / "sam-chen" / "transcripts" / "22-JUN-2026"
        assert pod.summaries_dir_for("22-JUN-2026") == Path("pods") / "sam-chen" / "summaries" / "22-JUN-2026"

    def test_invalid_name_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError):
            Pod(name="BadName")

    def test_created_at_set(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pod = Pod(name="sam-chen")
        assert pod.created_at  # non-empty
        # Should be ISO format
        datetime.fromisoformat(pod.created_at)


class TestPodGlossary:
    def test_default_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pod = Pod(name="sam-chen")
        assert pod.glossary == []

    def test_with_entries(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pod = Pod(
            name="sam-chen",
            glossary=[
                {"term": "Anurag Kaushik", "category": "person"},
                {"term": "Project Helios", "category": "project"},
            ],
        )
        assert len(pod.glossary) == 2
        assert pod.glossary[0]["term"] == "Anurag Kaushik"
        assert pod.glossary[1]["category"] == "project"

    def test_llm_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pod = Pod(
            name="sam-chen",
            llm={"model": "llama3.2", "prompt_template": "fix {{transcript}}"},
        )
        assert pod.llm["model"] == "llama3.2"


class TestPodLlmDefault:
    def test_default_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pod = Pod(name="sam-chen")
        assert pod.llm is None


class TestSegment:
    def test_basic(self):
        s = Segment(start_sec=1.5, end_sec=3.0, text="hello")
        assert s.start_sec == 1.5
        assert s.text == "hello"
        assert s.confidence is None
        assert s.speaker is None


def test_parse_meeting_type_normalizes_case():
    from podscribe.models import parse_meeting_type
    assert parse_meeting_type("1ON1") == "1on1"
    assert parse_meeting_type("Retro") == "retro"
    assert parse_meeting_type("design-review") == "design-review"


def test_parse_meeting_type_all_new_types_valid():
    """All new meeting types added beyond the original 1:1-focused set are accepted."""
    from podscribe.models import parse_meeting_type
    new_types = [
        "planning", "sprint-review", "all-hands", "team-sync",
        "incident", "post-mortem", "brainstorm",
        "customer", "vendor", "cross-team",
    ]
    for t in new_types:
        assert parse_meeting_type(t) == t, f"{t} should be a valid meeting type"


def test_parse_meeting_type_rejects_unknown():
    import pytest
    from podscribe.models import parse_meeting_type
    with pytest.raises(ValueError, match="Unknown meeting type"):
        parse_meeting_type("weekly-sync")
    with pytest.raises(ValueError, match="Unknown meeting type"):
        parse_meeting_type("")


def test_parse_meeting_type_none_returns_none():
    from podscribe.models import parse_meeting_type
    assert parse_meeting_type(None) is None


def test_kt_is_a_valid_meeting_type():
    from podscribe.models import parse_meeting_type
    assert parse_meeting_type("kt") == "kt"
    assert parse_meeting_type("KT") == "kt"


def test_pod_kt_dir_helpers():
    from pathlib import Path
    from podscribe.models import Pod
    pod = Pod(name="fso", base_path=Path("pods/fso"))
    assert pod.kt_transcripts_dir_for("03-JUL-2026") == Path("pods/fso/kt/transcripts/03-JUL-2026")
    assert pod.kt_summaries_dir_for("03-JUL-2026") == Path("pods/fso/kt/summaries/03-JUL-2026")
