import json
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
import requests
from podscribe.llm import (
    build_consolidate_prompt,
    build_enhance_prompt,
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
        result = enhance_transcript("llama3.2", "fix this", show_progress=False)
        assert result == "Hello world"
        # streamed + no retry
        assert mock_post.call_count == 1
        # timeout=1800 in the call
        assert mock_post.call_args.kwargs["timeout"] == 1800
        assert mock_post.call_args.kwargs["stream"] is True


def test_enhance_transcript_connection_error():
    with patch("podscribe.llm.requests.post", side_effect=requests.ConnectionError):
        result = enhance_transcript("llama3.2", "fix this", show_progress=False)
        assert result is None


def test_enhance_transcript_http_error():
    """Generic HTTP error → retried, returns None after exhaustion."""
    bad_resp = MagicMock()
    bad_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 500")
    bad_resp.status_code = 500
    with patch("podscribe.llm.requests.post", return_value=bad_resp) as mock_post:
        result = enhance_transcript("llama3.2", "fix this", show_progress=False)
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
        result = enhance_transcript("qwen3.6:27b", "go", show_progress=False)
        assert result == "Sam will review the design"


def test_enhance_retries_on_5xx(capfd):
    """5xx response: retried 3×, succeeds on 3rd attempt."""
    bad = MagicMock()
    bad.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 503")
    bad.status_code = 503
    bad.iter_lines = MagicMock(return_value=iter([]))
    good = make_streaming_response(["ok"], final_stats={"prompt_eval_count": 1, "eval_count": 1})
    with patch("podscribe.llm.requests.post", side_effect=[bad, bad, good]) as mock_post:
        with patch("podscribe.llm.time.sleep"):  # don't actually wait
            result = enhance_transcript("qwen3.6:27b", "go", show_progress=False)
            assert result == "ok"
            assert mock_post.call_count == 3


def test_enhance_no_retry_on_4xx():
    """4xx response: no retry, return None immediately."""
    bad = MagicMock()
    bad.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 400")
    bad.status_code = 400
    with patch("podscribe.llm.requests.post", return_value=bad) as mock_post:
        result = enhance_transcript("qwen3.6:27b", "go", show_progress=False)
        assert result is None
        assert mock_post.call_count == 1


def test_enhance_prints_metrics_to_stderr(capfd):
    """When show_progress=True, print prompt + response tokens + tok/s to stderr."""
    resp = make_streaming_response(
        ["Hi"],
        final_stats={"prompt_eval_count": 7, "eval_count": 1,
                     "total_duration": 1_000_000_000, "eval_duration": 100_000_000},
    )
    with patch("podscribe.llm.requests.post", return_value=resp):
        with patch("podscribe.llm._ollama_model_info", return_value={
            "model_info": {"llama.context_length": 32768}
        }):
            result = enhance_transcript("qwen3.6:27b", "go", show_progress=True)
            assert result == "Hi"
    captured = capfd.readouterr()
    assert "Calling Model:qwen3.6:27b" in captured.err
    assert "Context window size : 32768 tokens" in captured.err
    assert "prompt 7" in captured.err
    assert "response 1 tokens" in captured.err
    assert "tok/s" in captured.err


def test_enhance_uses_30_minute_timeout():
    resp = make_streaming_response(["x"], final_stats={"prompt_eval_count": 1, "eval_count": 1})
    with patch("podscribe.llm.requests.post", return_value=resp) as mock_post:
        enhance_transcript("qwen3.6:27b", "go", show_progress=False)
    assert mock_post.call_args.kwargs["timeout"] == 1800


def test_enhance_closes_progress_bar_on_stream_error():
    """If iter_lines raises mid-stream, the tqdm bar must still be closed."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.iter_lines = MagicMock(side_effect=requests.ConnectionError("stream dropped"))
    bar_mock = MagicMock()
    with patch("podscribe.llm.requests.post", return_value=resp):
        with patch("podscribe.llm.tqdm", return_value=bar_mock):
            with patch("podscribe.llm.time.sleep"):
                with patch("podscribe.llm._ollama_model_info", return_value={}):
                    result = enhance_transcript(
                        "qwen3.6:27b", "go", show_progress=True, max_retries=1
                    )
    assert result is None
    bar_mock.close.assert_called()


def test_enhance_high_max_retries_doesnt_crash():
    """max_retries > len(delays) should not cause IndexError on the backoff."""
    with patch("podscribe.llm.requests.post", side_effect=requests.ConnectionError):
        with patch("podscribe.llm.time.sleep"):
            result = enhance_transcript(
                "qwen3.6:27b", "go", max_retries=6, show_progress=False
            )
    assert result is None
