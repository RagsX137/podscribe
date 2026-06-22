"""Tests for CLI command structure (no audio, no model)."""
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
    """`podscribe <pod> summarize --latest` rewrites to `enhance <pod> --latest`."""
    args = _parse(["demo", "summarize", "--latest"])
    assert args.command == "enhance"
    assert args.pod == "demo"
    assert args.latest is True


def test_summarize_alias_toplevel():
    """`podscribe summarize <pod> --latest` rewrites to `enhance <pod> --latest`."""
    args = _parse(["summarize", "demo", "--latest"])
    assert args.command == "enhance"
    assert args.pod == "demo"
    assert args.latest is True


def test_enhance_latest_flag():
    """`podscribe enhance <pod> --latest` sets latest flag."""
    args = _parse(["enhance", "demo", "--latest"])
    assert args.command == "enhance"
    assert args.pod == "demo"
    assert args.latest is True


def test_enhance_latest_flag_short():
    """`podscribe enhance <pod> -l` sets latest flag."""
    args = _parse(["enhance", "demo", "-l"])
    assert args.command == "enhance"
    assert args.pod == "demo"
    assert args.latest is True


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
