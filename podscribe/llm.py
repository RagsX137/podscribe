"""Ollama HTTP client for transcript enhancement."""
from __future__ import annotations

import re
from typing import List, Optional

import requests
import yaml

OLLAMA_URL = "http://localhost:11434/api/generate"

SPEAKER_PRESERVATION_PREAMBLE = (
    "Preserve all names exactly as they appear in the transcript. "
    "For each action item, name the responsible person "
    '(e.g. "Sam will review the auth middleware design"). '
    'If the transcript does not name a person, write "Unassigned — needs owner" '
    "rather than dropping the item."
)


def build_enhance_prompt(
    template: str,
    glossary: list,
    transcript: str,
    *,
    preserve_speakers: bool = True,
) -> str:
    if preserve_speakers:
        template = SPEAKER_PRESERVATION_PREAMBLE + "\n\n" + template
    glossary_text = ", ".join(
        f"{e['term']} ({e.get('category', 'other')})" for e in glossary
    )
    prompt = template.replace("{{glossary}}", glossary_text)
    prompt = prompt.replace("{{transcript}}", transcript)
    if "{{transcript}}" not in template:
        prompt += "\n\n" + transcript
    return prompt


def enhance_transcript(
    model: str,
    prompt: str,
    *,
    timeout: int = 600,
) -> Optional[str]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.RequestException:
        return None
    except ValueError:
        return None


def build_consolidate_prompt(template: str, summary: str) -> str:
    prompt = template.replace("{{summary}}", summary)
    if "{{summary}}" not in template:
        prompt += "\n\n" + summary
    return prompt


def extract_structured_fields(response: str) -> Optional[dict]:
    """Parse YAML structured fields from LLM response.

    Tries full response first, then fenced code blocks.
    Returns dict with known fields or None.
    """
    text = response.strip()
    if not text:
        return None

    for source in [text, _extract_fenced_yaml(text)]:
        if source is None:
            continue
        try:
            data = yaml.safe_load(source)
            if isinstance(data, dict):
                return data
        except yaml.YAMLError:
            continue
    return None


def _extract_fenced_yaml(text: str) -> Optional[str]:
    match = re.search(r"```(?:yaml)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None
