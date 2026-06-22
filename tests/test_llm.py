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


def test_enhance_transcript_success():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"response": "Corrected transcript."}
    with patch("podscribe.llm.requests.post", return_value=mock_resp) as mock_post:
        result = enhance_transcript("llama3.2", "fix this")
        assert result == "Corrected transcript."
        mock_post.assert_called_once()


def test_enhance_transcript_connection_error():
    with patch("podscribe.llm.requests.post", side_effect=requests.ConnectionError):
        result = enhance_transcript("llama3.2", "fix this")
        assert result is None


def test_enhance_transcript_http_error():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 500")
    with patch("podscribe.llm.requests.post", return_value=mock_resp):
        result = enhance_transcript("llama3.2", "fix this")
        assert result is None


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
