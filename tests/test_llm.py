import json
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
import requests
from podscribe.llm import (
    build_consolidate_prompt,
    build_enhance_prompt,
    chat_stream,
    enhance_transcript,
    extract_structured_fields,
)


GLOSSARY = [
    {"term": "Anurag Kaushik", "category": "person"},
    {"term": "Project Helios", "category": "project"},
]
TEMPLATE = "Correct these names: {{glossary}}\n\nTranscript:\n{{transcript}}"


def test_build_enhance_prompt_inserts_glossary():
    transcript = "Anuraj spoke about project helios"
    prompt = build_enhance_prompt(TEMPLATE, GLOSSARY, transcript)
    assert "Anurag Kaushik" in prompt
    assert "Project Helios" in prompt
    assert transcript in prompt


def test_build_enhance_prompt_empty_glossary():
    transcript = "hello world"
    prompt = build_enhance_prompt(TEMPLATE, [], transcript)
    assert transcript in prompt


def test_build_enhance_prompt_no_transcript_var():
    """If template doesn't contain {{transcript}}, it's appended."""
    template = "Just fix this."
    prompt = build_enhance_prompt(template, GLOSSARY, "some text")
    assert "some text" in prompt


def make_streaming_response(chunks, final_stats=None, status_code=200):
    """Build a mock streaming response for enhance_transcript."""
    lines = []
    for c in chunks:
        lines.append(json.dumps({"response": c, "done": False}))
    final = {"response": "", "done": True, **(final_stats or {})}
    lines.append(json.dumps(final))
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.iter_lines = MagicMock(return_value=iter(lines))
    resp.status_code = status_code
    return resp


def test_enhance_transcript_success():
    """Streaming response: chunks accumulate into the final text."""
    resp = make_streaming_response(
        ["Hello", " ", "world"],
        final_stats={"prompt_eval_count": 5, "eval_count": 3,
                     "total_duration": 1_000_000_000, "eval_duration": 500_000_000},
    )
    with patch("podscribe.llm.requests.post", return_value=resp) as mock_post:
        result = enhance_transcript("llama3.2", "fix this")
        assert result == "Hello world"
        # streamed + no retry
        assert mock_post.call_count == 1
        # timeout=1800 in the call
        assert mock_post.call_args.kwargs["timeout"] == 1800
        assert mock_post.call_args.kwargs["stream"] is True


def test_enhance_transcript_connection_error():
    with patch("podscribe.llm.requests.post", side_effect=requests.ConnectionError):
        result = enhance_transcript("llama3.2", "fix this")
        assert result is None


def test_enhance_transcript_http_error():
    """Generic HTTP error → retried, returns None after exhaustion."""
    bad_resp = MagicMock()
    bad_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 500")
    bad_resp.status_code = 500
    with patch("podscribe.llm.requests.post", return_value=bad_resp) as mock_post:
        result = enhance_transcript("llama3.2", "fix this")
        assert result is None
        # 3 attempts
        assert mock_post.call_count == 3


ENHANCED_SUMMARY = "We discussed the Q3 roadmap. Sam is blocked on API review. Next steps: check in Friday."


def test_build_consolidate_prompt_inserts_summary():
    prompt = build_consolidate_prompt("Extract: {{summary}}", ENHANCED_SUMMARY)
    assert ENHANCED_SUMMARY in prompt
    assert "Extract:" in prompt


def test_build_consolidate_prompt_no_var():
    """If template doesn't contain {{summary}}, it's appended."""
    prompt = build_consolidate_prompt("Extract fields", ENHANCED_SUMMARY)
    assert ENHANCED_SUMMARY in prompt


def test_extract_structured_fields_valid_yaml():
    response = """
quick_summary: Synced on Q3 roadmap
key_topics:
  - Q3 roadmap
  - API review
action_items:
  - Unblock API review
blockers:
  - Stalled on VP sign-off
next_steps:
  - Check in Friday
"""
    result = extract_structured_fields(response)
    assert result is not None
    assert result["quick_summary"] == "Synced on Q3 roadmap"
    assert "API review" in result["key_topics"]
    assert "Unblock API review" in result["action_items"]


def test_extract_structured_fields_fenced_yaml():
    response = "Some text\n```yaml\nquick_summary: Synced\nkey_topics: []\n```\nmore text"
    result = extract_structured_fields(response)
    assert result is not None
    assert result["quick_summary"] == "Synced"


def test_extract_structured_fields_invalid():
    result = extract_structured_fields("not yaml at all")
    assert result is None


def test_extract_structured_fields_empty():
    result = extract_structured_fields("")
    assert result is None


SPEAKER_PREAMBLE_FRAGMENT = "Preserve all names exactly as they appear"
ANTI_HALLUCINATION_FRAGMENT = "Strict grounding rules"


def test_build_enhance_prompt_includes_speaker_preamble_by_default():
    """Default behavior: include the speaker-preservation preamble."""
    prompt = build_enhance_prompt(TEMPLATE, GLOSSARY, "hello")
    assert SPEAKER_PREAMBLE_FRAGMENT in prompt


def test_build_enhance_prompt_excludes_preamble_when_disabled():
    prompt = build_enhance_prompt(TEMPLATE, GLOSSARY, "hello", preserve_speakers=False)
    assert SPEAKER_PREAMBLE_FRAGMENT not in prompt


def test_build_enhance_prompt_preamble_appears_before_template():
    """The preamble should come first, before any template content."""
    prompt = build_enhance_prompt(TEMPLATE, GLOSSARY, "hello")
    preamble_pos = prompt.find(SPEAKER_PREAMBLE_FRAGMENT)
    template_marker_pos = prompt.find("Correct these names")
    assert preamble_pos < template_marker_pos
    assert preamble_pos >= 0


def test_build_enhance_prompt_includes_anti_hallucination_preamble_by_default():
    """Default behavior: include the anti-hallucination preamble."""
    prompt = build_enhance_prompt(TEMPLATE, GLOSSARY, "hello")
    assert ANTI_HALLUCINATION_FRAGMENT in prompt


def test_build_enhance_prompt_excludes_anti_hallucination_when_disabled():
    prompt = build_enhance_prompt(TEMPLATE, GLOSSARY, "hello", preserve_speakers=False)
    assert ANTI_HALLUCINATION_FRAGMENT not in prompt


def test_build_enhance_prompt_anti_hallucination_comes_before_speaker():
    """Anti-hallucination rule should come first — it's the most important."""
    prompt = build_enhance_prompt(TEMPLATE, GLOSSARY, "hello")
    ah_pos = prompt.find(ANTI_HALLUCINATION_FRAGMENT)
    sp_pos = prompt.find(SPEAKER_PREAMBLE_FRAGMENT)
    assert ah_pos < sp_pos
    assert ah_pos >= 0


def test_enhance_streams_and_returns_full_text():
    """Multiple streaming chunks concatenate into the final text."""
    resp = make_streaming_response(
        ["Sam", " will", " review", " the", " design"],
        final_stats={"prompt_eval_count": 10, "eval_count": 5,
                     "total_duration": 2_000_000_000, "eval_duration": 1_000_000_000},
    )
    with patch("podscribe.llm.requests.post", return_value=resp):
        result = enhance_transcript("qwen3.6:27b", "go")
        assert result == "Sam will review the design"


def test_enhance_retries_on_5xx(capfd):
    """5xx response: retried 3×, succeeds on 3rd attempt; on_retry fires before each sleep."""
    bad = MagicMock()
    bad.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 503")
    bad.status_code = 503
    bad.iter_lines = MagicMock(return_value=iter([]))
    good = make_streaming_response(["ok"], final_stats={"prompt_eval_count": 1, "eval_count": 1})
    retries: list = []

    def track_retry(attempt, err):
        retries.append(attempt)

    with patch("podscribe.llm.requests.post", side_effect=[bad, bad, good]) as mock_post:
        with patch("podscribe.llm.time.sleep"):  # don't actually wait
            result = enhance_transcript("qwen3.6:27b", "go", on_retry=track_retry)
            assert result == "ok"
            assert mock_post.call_count == 3
            # Two retries (after attempts 1 and 2) before the 3rd attempt succeeds.
            assert retries == [1, 2]


def test_enhance_no_retry_on_4xx():
    """4xx response: no retry, return None immediately."""
    bad = MagicMock()
    bad.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 400")
    bad.status_code = 400
    with patch("podscribe.llm.requests.post", return_value=bad) as mock_post:
        result = enhance_transcript("qwen3.6:27b", "go")
        assert result is None
        assert mock_post.call_count == 1


def test_enhance_core_prints_nothing_to_stderr(capfd):
    """The headless core emits no header/metrics — callers handle rendering."""
    resp = make_streaming_response(
        ["Hi"],
        final_stats={"prompt_eval_count": 7, "eval_count": 1,
                     "total_duration": 1_000_000_000, "eval_duration": 100_000_000},
    )
    with patch("podscribe.llm.requests.post", return_value=resp):
        enhance_transcript("qwen3.6:27b", "go")
    captured = capfd.readouterr()
    assert "Calling Model" not in captured.err
    assert "Context window size" not in captured.err


def test_enhance_uses_30_minute_timeout():
    resp = make_streaming_response(["x"], final_stats={"prompt_eval_count": 1, "eval_count": 1})
    with patch("podscribe.llm.requests.post", return_value=resp) as mock_post:
        enhance_transcript("qwen3.6:27b", "go")
    assert mock_post.call_args.kwargs["timeout"] == 1800


def test_enhance_transcript_cleans_up_on_stream_error():
    """If iter_lines raises mid-stream, the core returns None and does not re-raise.

    Preserves the intent of the old tqdm-cleanup test (no resource leak / clean
    teardown on error) without the tqdm-specific assertion: assert the function
    returns None, no exception escapes, and on_token/on_stats are not called
    after the error.
    """
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.iter_lines = MagicMock(side_effect=requests.ConnectionError("stream dropped"))

    tokens: list = []
    stats: list = []

    with patch("podscribe.llm.requests.post", return_value=resp):
        with patch("podscribe.llm.time.sleep"):
            result = enhance_transcript(
                "qwen3.6:27b", "go", max_retries=1,
                on_token=tokens.append, on_stats=stats.append,
            )
    assert result is None
    assert tokens == []
    assert stats == []


def test_enhance_high_max_retries_doesnt_crash():
    """max_retries > len(delays) should not cause IndexError on the backoff."""
    with patch("podscribe.llm.requests.post", side_effect=requests.ConnectionError):
        with patch("podscribe.llm.time.sleep"):
            result = enhance_transcript(
                "qwen3.6:27b", "go", max_retries=6
            )
    assert result is None


def test_enhance_transcript_fires_on_token_and_on_stats():
    """Regression: tokens stream via on_token; stats via on_stats on done."""
    resp = make_streaming_response(
        ["Sam", " will", " review"],
        final_stats={"prompt_eval_count": 10, "eval_count": 3,
                     "total_duration": 2_000_000_000, "eval_duration": 1_000_000_000},
    )
    tokens: list = []
    stats: list = []
    with patch("podscribe.llm.requests.post", return_value=resp):
        result = enhance_transcript(
            "qwen3.6:27b", "go",
            on_token=tokens.append, on_stats=stats.append,
        )
    assert result == "Sam will review"
    assert tokens == ["Sam", " will", " review"]
    assert len(stats) == 1
    assert stats[0]["eval_count"] == 3
    assert stats[0]["prompt_eval_count"] == 10


def test_enhance_transcript_does_not_import_tqdm():
    """The core must not depend on tqdm; the fictional progress bar is gone."""
    import podscribe.llm as llm_mod
    assert not hasattr(llm_mod, "tqdm"), "llm.py must not import tqdm"


def make_chat_stream_response(chunks, tool_call_msg=None, final_extra=None):
    """Build a mock streaming response for /api/chat."""
    lines = []
    for c in chunks:
        lines.append(json.dumps({
            "model": "qwen3.6:27b",
            "message": {"role": "assistant", "content": c},
            "done": False,
        }))
    final_msg = tool_call_msg or {"role": "assistant", "content": ""}
    final = {
        "model": "qwen3.6:27b",
        "message": final_msg,
        "done": True,
        **(final_extra or {}),
    }
    lines.append(json.dumps(final))
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.iter_lines = MagicMock(return_value=iter(lines))
    resp.status_code = 200
    return resp


def test_chat_stream_text_response():
    """Text-only response: tokens stream via on_token, full text returned."""
    resp = make_chat_stream_response(["Hello", " ", "World"])
    tokens: list = []
    msgs: list = []

    with patch("podscribe.llm.requests.post", return_value=resp) as mock_post:
        result = chat_stream(
            "qwen3.6:27b",
            [{"role": "user", "content": "say hi"}],
            on_token=tokens.append,
            on_message=msgs.append,
        )

    assert result == "Hello World"
    assert tokens == ["Hello", " ", "World"]
    assert len(msgs) == 1
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["content"] == ""
    assert mock_post.call_args.kwargs["stream"] is True
    assert mock_post.call_args.kwargs["timeout"] == 1800


def test_chat_stream_tool_call():
    """Tool call response: on_message receives tool_calls, text is empty."""
    tool_call = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "list_pods", "arguments": "{}"}, "type": "function"}
        ],
    }
    resp = make_chat_stream_response([], tool_call_msg=tool_call)
    tokens: list = []
    msgs: list = []

    with patch("podscribe.llm.requests.post", return_value=resp):
        result = chat_stream(
            "qwen3.6:27b",
            [{"role": "user", "content": "list pods"}],
            on_token=tokens.append,
            on_message=msgs.append,
        )

    assert result == ""
    assert tokens == []
    assert len(msgs) == 1
    assert "tool_calls" in msgs[0]
    assert msgs[0]["tool_calls"][0]["function"]["name"] == "list_pods"


def test_chat_stream_passes_tools():
    """Tools list is included in the request payload."""
    resp = make_chat_stream_response(["ok"])
    tools = [{"type": "function", "function": {"name": "list_pods"}}]
    with patch("podscribe.llm.requests.post", return_value=resp) as mock_post:
        chat_stream("qwen3.6:27b", [{"role": "user", "content": "hi"}], tools=tools)
    assert mock_post.call_args.kwargs["json"]["tools"] == tools


def test_chat_stream_connection_error():
    with patch("podscribe.llm.requests.post", side_effect=requests.ConnectionError):
        result = chat_stream("qwen3.6:27b", [{"role": "user", "content": "hi"}])
    assert result is None


def test_chat_stream_retries_on_5xx():
    bad = MagicMock()
    bad.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 503")
    bad.status_code = 503
    bad.iter_lines = MagicMock(return_value=iter([]))
    good = make_chat_stream_response(["ok"])

    with patch("podscribe.llm.requests.post", side_effect=[bad, bad, good]) as mock_post:
        with patch("podscribe.llm.time.sleep"):
            result = chat_stream("qwen3.6:27b", [{"role": "user", "content": "hi"}])
    assert result == "ok"
    assert mock_post.call_count == 3


def test_chat_stream_5xx_all_attempts_fail():
    """All 5xx attempts fail: retried 3 times, returns None."""
    bad = MagicMock()
    bad.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 503")
    bad.status_code = 503
    bad.iter_lines = MagicMock(return_value=iter([]))

    with patch("podscribe.llm.requests.post", return_value=bad) as mock_post:
        with patch("podscribe.llm.time.sleep"):
            result = chat_stream("qwen3.6:27b", [{"role": "user", "content": "hi"}])
    assert result is None
    assert mock_post.call_count == 3


def test_chat_stream_no_retry_on_4xx():
    bad = MagicMock()
    bad.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 400")
    bad.status_code = 400

    with patch("podscribe.llm.requests.post", return_value=bad) as mock_post:
        result = chat_stream("qwen3.6:27b", [{"role": "user", "content": "hi"}])
    assert result is None
    assert mock_post.call_count == 1


def test_chat_stream_cleans_up_on_stream_error():
    """If iter_lines raises mid-stream, returns None and does not re-raise."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.iter_lines = MagicMock(side_effect=requests.ConnectionError("stream dropped"))

    tokens: list = []
    msgs: list = []

    with patch("podscribe.llm.requests.post", return_value=resp):
        with patch("podscribe.llm.time.sleep"):
            result = chat_stream(
                "qwen3.6:27b", [{"role": "user", "content": "hi"}], max_retries=1,
                on_token=tokens.append, on_message=msgs.append,
            )
    assert result is None
    assert tokens == []
    assert msgs == []
