"""Tests for God mode agent tools and agent loop."""
from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from podscribe.agent import (
    GodSession,
    _build_tool_defs,
    _resolve_model,
    _format_tool_result,
)
from podscribe.agent_tools import (
    MAX_TOOL_RESULT_CHARS,
    _truncate,
    list_pods,
    pod_info,
    init_pod_tool,
    list_meetings_tool,
    show_meeting,
)


# ── Tool definitions ──────────────────────────────────────────────────────────

def test_build_tool_defs_has_all_tools():
    defs = _build_tool_defs()
    names = {t["function"]["name"] for t in defs}
    expected = {
        "list_pods", "pod_info", "init_pod_tool", "list_meetings_tool",
        "show_meeting", "start_recording", "stop_recording",
        "get_recording_status", "enhance_meeting", "consolidate_meeting",
        "search_transcripts", "glossary_list", "glossary_add", "glossary_remove",
        "export_data",
    }
    assert names == expected


# ── Model resolution ──────────────────────────────────────────────────────────

def test_resolve_model_uses_flag_first():
    with patch("podscribe.agent.load_project_config", return_value={"llm": {"model": "qwen3.6:27b"}}):
        assert _resolve_model("custom-model") == "custom-model"


def test_resolve_model_uses_config():
    with patch("podscribe.agent.load_project_config", return_value={"llm": {"model": "qwen3.6:27b"}}):
        assert _resolve_model(None) == "qwen3.6:27b"


def test_resolve_model_falls_back():
    with patch("podscribe.agent.load_project_config", return_value={}):
        assert _resolve_model(None) == "qwen3.6:27b-mlx"


# ── Truncation ────────────────────────────────────────────────────────────────

def test_truncate_short_text():
    text = "hello world"
    assert _truncate(text) == text


def test_truncate_long_text():
    text = "x" * (MAX_TOOL_RESULT_CHARS + 100)
    result = _truncate(text)
    assert len(result) <= MAX_TOOL_RESULT_CHARS + 100  # truncated + suffix
    assert "[...truncated" in result


def test_truncate_exact_boundary():
    text = "x" * MAX_TOOL_RESULT_CHARS
    assert _truncate(text) == text


# ── Format tool result ────────────────────────────────────────────────────────

def test_format_tool_result_dict():
    result = _format_tool_result("list_pods", ["pod-a", "pod-b"])
    parsed = json.loads(result)
    assert parsed == ["pod-a", "pod-b"]


def test_format_tool_result_string():
    result = _format_tool_result("show_meeting", "# Meeting transcript\nHello")
    assert "Hello" in result


# ── GodSession initialization ─────────────────────────────────────────────────

def test_god_session_system_message():
    session = GodSession(model="test-model")
    assert session.model == "test-model"
    assert len(session.messages) == 1
    assert session.messages[0]["role"] == "system"
    assert "Podscribe assistant" in session.messages[0]["content"]


def test_god_session_add_user_message():
    session = GodSession(model="test-model")
    session.add_user_message("hello")
    assert len(session.messages) == 2
    assert session.messages[1] == {"role": "user", "content": "hello"}


def test_god_session_add_system_context():
    session = GodSession(model="test-model")
    session.add_system_context("/list executed → pods: []")
    assert len(session.messages) == 2
    assert session.messages[1]["role"] == "system"


# ── agent_tools: list_pods ────────────────────────────────────────────────────

def test_list_pods_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = list_pods()
    assert result == []


def test_list_pods_with_pods(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pods" / "sam-chen").mkdir(parents=True)
    (tmp_path / "pods" / "sam-chen" / "config.yaml").write_text("name: sam-chen")
    (tmp_path / "pods" / "priya").mkdir(parents=True)
    (tmp_path / "pods" / "priya" / "config.yaml").write_text("name: priya")
    result = list_pods()
    assert result == ["priya", "sam-chen"]


# ── agent_tools: pod_info ─────────────────────────────────────────────────────

def test_pod_info_nonexistent():
    with patch("podscribe.agent_tools.pod_exists", return_value=False):
        result = pod_info("nonexistent")
        assert "error" in result


def test_pod_info_exists():
    mock_pod = MagicMock()
    mock_pod.name = "sam-chen"
    mock_pod.display_name = "Sam Chen"
    mock_pod.role = "Engineer"
    mock_pod.cadence = "weekly"
    mock_pod.notes = ""
    mock_pod.created_at = "2026-06-01"
    mock_pod.glossary = []

    with patch("podscribe.agent_tools.pod_exists", return_value=True):
        with patch("podscribe.agent_tools.load_pod", return_value=mock_pod):
            with patch("podscribe.agent_tools.list_meetings", return_value=[]):
                result = pod_info("sam-chen")
                assert result["name"] == "sam-chen"
                assert result["total_meetings"] == 0


# ── agent_tools: init_pod_tool ────────────────────────────────────────────────

def test_init_pod_tool_already_exists():
    with patch("podscribe.agent_tools.pod_exists", return_value=True):
        result = init_pod_tool("sam-chen")
        assert "error" in result


def test_init_pod_tool_success():
    with patch("podscribe.agent_tools.pod_exists", return_value=False):
        with patch("podscribe.agent_tools.init_pod") as mock_init:
            mock_pod = MagicMock()
            mock_pod.name = "sam-chen"
            mock_pod.base_path = "pods/sam-chen"
            mock_init.return_value = mock_pod
            result = init_pod_tool("sam-chen", display_name="Sam Chen")
            assert result["status"] == "created"
            assert result["name"] == "sam-chen"


# ── agent_tools: list_meetings_tool ───────────────────────────────────────────

def test_list_meetings_tool_nonexistent_pod():
    with patch("podscribe.agent_tools.pod_exists", return_value=False):
        result = list_meetings_tool("nonexistent")
        assert "error" in result[0]


def test_list_meetings_tool_empty():
    mock_pod = MagicMock()
    mock_pod.name = "sam-chen"
    with patch("podscribe.agent_tools.pod_exists", return_value=True):
        with patch("podscribe.agent_tools.load_pod", return_value=mock_pod):
            with patch("podscribe.agent_tools.list_meetings", return_value=[]):
                result = list_meetings_tool("sam-chen")
                assert result == []


# ── agent_tools: show_meeting ─────────────────────────────────────────────────

def test_show_meeting_nonexistent_pod():
    with patch("podscribe.agent_tools.pod_exists", return_value=False):
        result = show_meeting("nonexistent", "latest")
        assert "not exist" in result


# ── Recording lifecycle ───────────────────────────────────────────────────────

def test_stop_recording_no_active():
    from podscribe.agent_tools import stop_recording
    import podscribe.agent_tools as at
    at._recording_session = None
    result = stop_recording()
    assert "error" in result


# ── Slash command parsing (agent.py internals) ────────────────────────────────

def test_tool_registry_has_all_tools():
    from podscribe.agent import TOOL_REGISTRY
    expected = {
        "list_pods", "pod_info", "init_pod_tool", "list_meetings_tool",
        "show_meeting", "start_recording", "stop_recording",
        "get_recording_status", "enhance_meeting", "consolidate_meeting",
        "search_transcripts", "glossary_list", "glossary_add", "glossary_remove",
        "export_data",
    }
    assert set(TOOL_REGISTRY.keys()) == expected


# ── Conversation history ──────────────────────────────────────────────────────

def test_messages_grows_with_tool_result():
    """Tool results appended as tool-role messages."""
    session = GodSession(model="test-model")
    session.add_user_message("list pods")
    # Simulate tool call + result
    session.messages.append({
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "list_pods", "arguments": "{}"}, "type": "function"}
        ],
    })
    session.messages.append({
        "role": "tool",
        "name": "list_pods",
        "content": '["sam-chen"]',
    })
    assert len(session.messages) == 4  # system + user + assistant + tool
    assert session.messages[-1]["role"] == "tool"
