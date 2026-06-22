from unittest.mock import MagicMock, patch

import pytest
import requests
from podscribe.llm import build_enhance_prompt, enhance_transcript


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
