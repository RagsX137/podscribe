"""Tests for CLI command structure (no audio, no model)."""
from unittest.mock import patch

import pytest

from podscribe.cli import build_parser, rewrite_argv


def test_parser_has_required_commands():
    parser = build_parser()
    # Should not raise
    args = parser.parse_args(["init", "sam-chen"])
    assert args.command == "init"
    assert args.name == "sam-chen"


def test_init_command_args():
    parser = build_parser()
    args = parser.parse_args([
        "init", "priya-patel",
        "--display-name", "Priya Patel",
        "--role", "Tech Lead",
        "--cadence", "biweekly",
        "--notes", "Strong on backend, learning frontend.",
    ])
    assert args.name == "priya-patel"
    assert args.display_name == "Priya Patel"
    assert args.role == "Tech Lead"
    assert args.cadence == "biweekly"
    assert "backend" in args.notes


def test_record_command_args():
    parser = build_parser()
    args = parser.parse_args([
        "record", "sam-chen",
        "--model", "large-v3",
        "--vad-aggressiveness", "3",
        "--keep-audio",
    ])
    assert args.pod == "sam-chen"
    assert args.model == "large-v3"
    assert args.vad_aggressiveness == 3
    assert args.keep_audio is True


def test_show_command_latest():
    parser = build_parser()
    args = parser.parse_args(["show", "sam-chen", "latest"])
    assert args.pod == "sam-chen"
    assert args.meeting == "latest"


def test_invalid_vaggressiveness_rejected():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["record", "sam", "--vad-aggressiveness", "5"])


def test_no_command_rejected():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_context_add_args():
    parser = build_parser()
    args = parser.parse_args(["context", "sam-chen", "add", "Anurag Kaushik", "--category", "person"])
    assert args.command == "context"
    assert args.pod == "sam-chen"
    assert args.action == "add"
    assert args.term == "Anurag Kaushik"
    assert args.category == "person"


def test_context_remove_args():
    parser = build_parser()
    args = parser.parse_args(["context", "sam-chen", "remove", "Anurag Kaushik"])
    assert args.command == "context"
    assert args.action == "remove"


def test_context_list_args():
    parser = build_parser()
    args = parser.parse_args(["context", "sam-chen", "list"])
    assert args.command == "context"
    assert args.action == "list"


def test_enhance_args():
    parser = build_parser()
    args = parser.parse_args(["enhance", "sam-chen", "latest"])
    assert args.command == "enhance"
    assert args.pod == "sam-chen"
    assert args.meeting == "latest"


def test_record_uses_glossary_prompt():
    """When a pod has glossary entries, cmd_record builds initial_prompt."""
    from podscribe.glossary import format_glossary_prompt
    glossary = [{"term": "Project Helios", "category": "project"}]
    prompt = format_glossary_prompt(glossary)
    assert "Project Helios" in prompt


# ── New syntax: pod-first and aliases ─────────────────────────────

def _parse(argv):
    return build_parser().parse_args(rewrite_argv(argv))


def test_pod_first_syntax_rewrites():
    """`podscribe <pod> <command>` rewrites to `<command> <pod>`."""
    args = _parse(["demo", "record"])
    assert args.command == "record"
    assert args.pod == "demo"


def test_pod_first_syntax_with_flags():
    """`podscribe <pod> <command> [flags]` preserves flags."""
    args = _parse(["demo", "record", "--keep-audio"])
    assert args.command == "record"
    assert args.pod == "demo"
    assert args.keep_audio is True


def test_start_alias_pod_first():
    """`podscribe <pod> start` rewrites to `record <pod>`."""
    args = _parse(["demo", "start"])
    assert args.command == "record"
    assert args.pod == "demo"


def test_start_alias_toplevel():
    """`podscribe start <pod>` rewrites to `record <pod>`."""
    args = _parse(["start", "demo"])
    assert args.command == "record"
    assert args.pod == "demo"


def test_summarize_alias_pod_first():
    """`podscribe <pod> summarize` rewrites to `enhance <pod>`."""
    args = _parse(["demo", "summarize"])
    assert args.command == "enhance"
    assert args.pod == "demo"


def test_summarize_alias_toplevel():
    """`podscribe summarize <pod>` rewrites to `enhance <pod>`."""
    args = _parse(["summarize", "demo"])
    assert args.command == "enhance"
    assert args.pod == "demo"


def test_standard_syntax_still_works():
    """`podscribe record <pod>` still works unchanged."""
    args = _parse(["record", "demo"])
    assert args.command == "record"
    assert args.pod == "demo"


def test_context_pod_first():
    """`podscribe <pod> context add "Term"` rewrites correctly."""
    args = _parse(["demo", "context", "add", "Anurag", "--category", "person"])
    assert args.command == "context"
    assert args.pod == "demo"
    assert args.action == "add"
    assert args.term == "Anurag"
    assert args.category == "person"


def test_show_pod_first():
    """`podscribe <pod> show latest` rewrites correctly."""
    args = _parse(["sam-chen", "show", "latest"])
    assert args.command == "show"
    assert args.pod == "sam-chen"
    assert args.meeting == "latest"


def test_config_llm_show():
    parser = build_parser()
    args = parser.parse_args(["config", "llm", "show"])
    assert args.command == "config"
    assert args.action == "llm"
    assert args.llm_action == "show"


def test_config_llm_set():
    parser = build_parser()
    args = parser.parse_args([
        "config", "llm", "set", "qwen3.6",
        "Fix spelling: {{transcript}}",
    ])
    assert args.command == "config"
    assert args.action == "llm"
    assert args.llm_action == "set"
    assert args.model == "qwen3.6"
    assert args.prompt_template == "Fix spelling: {{transcript}}"


def test_consolidate_args_default_latest():
    parser = build_parser()
    args = parser.parse_args(["consolidate", "sam-chen"])
    assert args.command == "consolidate"
    assert args.pod == "sam-chen"
    assert args.meeting == "latest"
    assert args.no_log is False


def test_consolidate_args_with_meeting():
    parser = build_parser()
    args = parser.parse_args(["consolidate", "sam-chen", "2026-06-22"])
    assert args.command == "consolidate"
    assert args.pod == "sam-chen"
    assert args.meeting == "2026-06-22"


def test_consolidate_no_log_flag():
    parser = build_parser()
    args = parser.parse_args(["consolidate", "sam-chen", "--no-log"])
    assert args.no_log is True


def test_consolidate_no_log_flag_short():
    parser = build_parser()
    args = parser.parse_args(["consolidate", "sam-chen", "-n"])
    assert args.no_log is True


def test_consolidate_alias_pod_first():
    """`podscribe <pod> consolidate` rewrites correctly."""
    args = _parse(["sam-chen", "consolidate"])
    assert args.command == "consolidate"
    assert args.pod == "sam-chen"


def test_consolidate_alias_short():
    """`podscribe cons <pod>` rewrites to `consolidate <pod>`."""
    args = _parse(["cons", "sam-chen"])
    assert args.command == "consolidate"
    assert args.pod == "sam-chen"


def test_consolidate_alias_pod_first_short():
    """`podscribe <pod> cons` rewrites to `consolidate <pod>`."""
    args = _parse(["sam-chen", "cons"])
    assert args.command == "consolidate"
    assert args.pod == "sam-chen"


def test_config_consolidate_show():
    parser = build_parser()
    args = parser.parse_args(["config", "consolidate", "show"])
    assert args.command == "config"
    assert args.action == "consolidate"
    assert args.consolidate_action == "show"


def test_config_consolidate_set():
    parser = build_parser()
    args = parser.parse_args(["config", "consolidate", "set", "Extract {{summary}}"])
    assert args.command == "config"
    assert args.action == "consolidate"
    assert args.consolidate_action == "set"
    assert args.prompt == "Extract {{summary}}"


def test_cmd_consolidate_no_pod(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from podscribe.cli import cmd_consolidate, build_parser
    args = build_parser().parse_args(["consolidate", "nope"])
    rc = cmd_consolidate(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "No pod" in captured.err


def test_cmd_consolidate_no_meetings(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod
    from podscribe.cli import cmd_consolidate, build_parser
    init_pod("sam-chen")
    args = build_parser().parse_args(["consolidate", "sam-chen"])
    rc = cmd_consolidate(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "No meetings" in captured.err


def test_cmd_consolidate_no_enhanced_summary_errors_out(tmp_path, monkeypatch, capsys):
    """Missing summary: hard error with the exact enhance command to run, no prompt."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_consolidate, build_parser

    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello world"))
    finalize_meeting(meeting)

    args = build_parser().parse_args(["consolidate", "sam-chen"])
    rc = cmd_consolidate(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "No enhanced summary" in captured.err
    assert "podscribe enhance sam-chen" in captured.err


def test_cmd_consolidate_with_no_log(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_consolidate, build_parser

    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello world"))
    finalize_meeting(meeting)
    date_str = "22-JUN-2026"
    summary_dir = pod.summaries_dir_for(date_str)
    summary_dir.mkdir(parents=True, exist_ok=True)
    enhanced = summary_dir / f"{meeting.id}.md"
    enhanced.write_text("# Enhanced\nWe talked about Q3 plans.")

    with patch("podscribe.cli.enhance_transcript", return_value="quick_summary: Test summary"):
        with patch("podscribe.cli.load_project_config", return_value={"llm": {"model": "qwen3.6", "prompt_template": "test"}}):
            args = build_parser().parse_args(["consolidate", "sam-chen", "--no-log"])
            rc = cmd_consolidate(args)
            assert rc == 0
    captured = capsys.readouterr()
    assert "Test summary" in captured.out


def test_cmd_show_empty_meeting_defaults_to_latest(tmp_path, monkeypatch, capsys):
    """`podscribe show <pod> ""` should resolve to latest, not crash.

    Regression guard: cmd_show referenced args.latest which the show
    subparser does not define, raising AttributeError on a falsy meeting.
    """
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_show, build_parser

    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello world"))
    finalize_meeting(meeting)

    args = build_parser().parse_args(["show", "sam-chen", ""])
    rc = cmd_show(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "hello world" in captured.out


def test_enhance_parser_has_no_latest_flag():
    """--latest/-l is dead code; args.meeting defaults to 'latest'."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["enhance", "sam-chen", "2026-06-22-1430", "--latest"])


def test_cmd_enhance_prints_summary_path_not_transcript_path(tmp_path, monkeypatch, capsys):
    """Misleading print: 'Saving transcript' but writes the summary."""
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_enhance, build_parser

    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello world this is a sufficiently long transcript segment for testing"))
    finalize_meeting(meeting)

    with patch("podscribe.cli.enhance_transcript", return_value="Enhanced output."):
        with patch("podscribe.cli.load_project_config", return_value={
            "llm": {"model": "qwen3.6", "prompt_template": "test"}
        }):
            args = build_parser().parse_args(["enhance", "sam-chen"])
            rc = cmd_enhance(args)
            assert rc == 0

    captured = capsys.readouterr()
    assert "Enhanced summary will be saved to" in captured.out
    assert "Saving transcript to" not in captured.out


def test_cmd_enhance_rejects_empty_transcript(tmp_path, monkeypatch, capsys):
    """Empty transcript: skip the LLM call entirely."""
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_enhance, build_parser

    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, ""))  # empty segment
    finalize_meeting(meeting)

    llm_called = []
    def fake_enhance(*a, **kw):
        llm_called.append(True)
        return "should not happen"

    with patch("podscribe.cli.enhance_transcript", side_effect=fake_enhance):
        with patch("podscribe.cli.load_project_config", return_value={
            "llm": {"model": "qwen3.6", "prompt_template": "test"}
        }):
            args = build_parser().parse_args(["enhance", "sam-chen"])
            rc = cmd_enhance(args)
            assert rc == 1

    assert llm_called == [], "LLM should not be called for empty transcript"
    captured = capsys.readouterr()
    assert "too short" in captured.err


def test_cmd_enhance_rejects_short_transcript(tmp_path, monkeypatch, capsys):
    """<50 char transcript: skip the LLM call entirely."""
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_enhance, build_parser

    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello"))  # 5 chars
    finalize_meeting(meeting)

    llm_called = []
    with patch("podscribe.cli.enhance_transcript", side_effect=lambda *a, **kw: llm_called.append(True) or "no"):
        with patch("podscribe.cli.load_project_config", return_value={
            "llm": {"model": "qwen3.6", "prompt_template": "test"}
        }):
            args = build_parser().parse_args(["enhance", "sam-chen"])
            rc = cmd_enhance(args)
            assert rc == 1

    assert llm_called == []
    captured = capsys.readouterr()
    assert "too short" in captured.err


def test_cmd_consolidate_no_summary_does_not_prompt(tmp_path, monkeypatch, capsys):
    """Missing summary: must NOT call input() — should be a hard error."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_consolidate, build_parser

    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello world"))
    finalize_meeting(meeting)

    def fail_if_called(*a, **kw):
        raise AssertionError("input() should not be called")

    monkeypatch.setattr("builtins.input", fail_if_called)
    args = build_parser().parse_args(["consolidate", "sam-chen"])
    rc = cmd_consolidate(args)
    assert rc == 1


def test_show_with_ambiguous_prefix_lists_candidates(tmp_path, monkeypatch, capsys):
    """Two meetings with same prefix → list them and return 1."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_show, build_parser

    pod = init_pod("sam-chen")
    for dt in [datetime(2026, 6, 22, 14, 30, 0), datetime(2026, 6, 22, 14, 31, 0)]:
        m = start_meeting(pod, dt)
        append_segment(m, Segment(1.0, 5.0, "hello"))
        finalize_meeting(m)

    args = build_parser().parse_args(["show", "sam-chen", "2026-06-22-14"])
    rc = cmd_show(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "Multiple meetings match" in captured.err
    assert "2026-06-22-143000-sam-chen" in captured.err
    assert "2026-06-22-143100-sam-chen" in captured.err


def test_enhance_with_ambiguous_prefix_lists_candidates(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_enhance, build_parser

    pod = init_pod("sam-chen")
    for dt in [datetime(2026, 6, 22, 14, 30, 0), datetime(2026, 6, 22, 14, 31, 0)]:
        m = start_meeting(pod, dt)
        append_segment(m, Segment(1.0, 5.0, "hello"))
        finalize_meeting(m)

    with patch("podscribe.cli.load_project_config", return_value={
        "llm": {"model": "qwen3.6", "prompt_template": "test"}
    }):
        args = build_parser().parse_args(["enhance", "sam-chen", "2026-06-22-14"])
        rc = cmd_enhance(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "Multiple meetings match" in captured.err


def test_consolidate_with_ambiguous_prefix_lists_candidates(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_consolidate, build_parser

    pod = init_pod("sam-chen")
    for dt in [datetime(2026, 6, 22, 14, 30, 0), datetime(2026, 6, 22, 14, 31, 0)]:
        m = start_meeting(pod, dt)
        append_segment(m, Segment(1.0, 5.0, "hello"))
        finalize_meeting(m)

    args = build_parser().parse_args(["consolidate", "sam-chen", "2026-06-22-14"])
    rc = cmd_consolidate(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "Multiple meetings match" in captured.err


def test_cmd_record_writes_wav_with_keep_audio(tmp_path, monkeypatch):
    """--keep-audio produces a real, replayable WAV file with the right content."""
    import wave
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch, MagicMock
    import numpy as np
    from podscribe.storage import init_pod
    from podscribe.cli import cmd_record, build_parser

    pod = init_pod("sam-chen")

    # Simulate one 0.5s segment of float32 audio at 16kHz
    fake_segment = np.zeros(8000, dtype=np.float32)

    # Mock the Transcriber to return a deterministic result
    mock_transcriber = MagicMock()
    mock_transcriber.model_name = "base"
    mock_transcriber.transcribe.return_value = [{"text": "hello", "start": 0, "end": 0.5}]

    mock_capture = MagicMock()
    mock_capture.vad_aggressiveness = 2
    mock_capture.had_overflow = False
    mock_capture.segments.return_value = iter([fake_segment])
    mock_capture.stop = MagicMock(side_effect=lambda: None)

    with patch("podscribe.audio.AudioCapture", return_value=mock_capture):
        with patch("podscribe.transcriber.Transcriber", return_value=mock_transcriber):
            with patch("podscribe.cli.signal.signal"):
                with patch("podscribe.cli.time.monotonic", side_effect=[0.0, 0.5, 0.5]):
                    args = build_parser().parse_args(["record", "sam-chen", "--keep-audio", "--model", "base"])
                    rc = cmd_record(args)
                    assert rc == 0

    raw_files = list(tmp_path.glob("pods/sam-chen/transcripts/*/*.raw"))
    assert len(raw_files) == 1
    raw_path = raw_files[0]

    with wave.open(str(raw_path), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16000
        frames = w.readframes(w.getnframes())
        assert len(frames) == 8000 * 2


def test_cmd_record_omits_audio_by_default(tmp_path, monkeypatch):
    """Without --keep-audio, no .raw file is created."""
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch, MagicMock
    import numpy as np
    from podscribe.storage import init_pod
    from podscribe.cli import cmd_record, build_parser

    pod = init_pod("sam-chen")

    fake_segment = np.zeros(8000, dtype=np.float32)
    mock_transcriber = MagicMock()
    mock_transcriber.model_name = "base"
    mock_transcriber.transcribe.return_value = [{"text": "hello", "start": 0, "end": 0.5}]
    mock_capture = MagicMock()
    mock_capture.vad_aggressiveness = 2
    mock_capture.had_overflow = False
    mock_capture.segments.return_value = iter([fake_segment])
    mock_capture.stop = MagicMock(side_effect=lambda: None)

    with patch("podscribe.audio.AudioCapture", return_value=mock_capture):
        with patch("podscribe.transcriber.Transcriber", return_value=mock_transcriber):
            with patch("podscribe.cli.signal.signal"):
                with patch("podscribe.cli.time.monotonic", side_effect=[0.0, 0.5, 0.5]):
                    args = build_parser().parse_args(["record", "sam-chen", "--model", "base"])
                    rc = cmd_record(args)
                    assert rc == 0

    raw_files = list(tmp_path.glob("pods/sam-chen/transcripts/*/*.raw"))
    assert raw_files == []

