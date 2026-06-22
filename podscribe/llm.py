"""Ollama HTTP client for transcript enhancement."""
from __future__ import annotations

from typing import List, Optional

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"


def build_enhance_prompt(template: str, glossary: list, transcript: str) -> str:
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
