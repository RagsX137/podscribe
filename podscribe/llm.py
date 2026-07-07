"""Ollama HTTP client for transcript enhancement."""
from __future__ import annotations

import re
from typing import Callable, Optional

import yaml

from .providers.base import Provider
from .providers.ollama import OllamaProvider

ANTI_HALLUCINATION_PREAMBLE = (
    "Strict grounding rules — read carefully:\n"
    "1. Every claim must come from the transcript. Do NOT use outside "
    "knowledge, training data, or assumptions about the people or projects "
    "mentioned.\n"
    "2. If something is unclear, missing, or you do not understand it, "
    "say so explicitly — e.g. 'Not mentioned in the transcript', "
    "'I don't know', or 'Unclear from the transcript'. Do NOT guess.\n"
    "3. Never invent names, dates, action items, decisions, or other facts. "
    "If the transcript does not say it, do not write it."
)

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
        template = (
            ANTI_HALLUCINATION_PREAMBLE
            + "\n\n"
            + SPEAKER_PRESERVATION_PREAMBLE
            + "\n\n"
            + template
        )
    glossary_text = ", ".join(
        f"{e['term']} ({e.get('category', 'other')})" for e in glossary
    )
    prompt = template.replace("{{glossary}}", glossary_text)
    prompt = prompt.replace("{{transcript}}", transcript)
    if "{{transcript}}" not in template:
        prompt += "\n\n" + transcript
    return prompt


def ollama_model_info(model: str, *, provider: Optional[Provider] = None) -> dict:
    """Fetch model details (context window etc.). Best-effort; {} on failure.

    Kept named `ollama_model_info` for caller compatibility; delegates to the
    given provider (default: localhost Ollama).
    """
    provider = provider or OllamaProvider(model)
    return provider.model_info()


def enhance_transcript(
    model: str,
    prompt: str,
    *,
    max_retries: int = 3,
    on_token: Callable[[str], None] = lambda t: None,
    on_stats: Callable[[dict], None] = lambda d: None,
    on_retry: Callable[[int, str], None] = lambda a, e: None,
    provider: Optional[Provider] = None,
) -> Optional[str]:
    """Stream from Ollama, fire callbacks, return full text (None on failure).

    Headless core: no tqdm, no header preface, no show_progress flag. The
    caller (plain wrapper or rich view) decides how to render tokens/stats.

    Retries up to max_retries on connection errors and 5xx. Does NOT retry
    on 4xx (bad prompt, model not found). timeout=1800s (30 min).

    on_token(str): fires once per streamed chunk with a "response" key.
    on_stats(dict): fires once on the done chunk with
        {"prompt_eval_count","eval_count","total_duration_ns","eval_duration_ns"}.
    on_retry(attempt:int, error:str): fires before each retry sleep
        (so views can show "retrying…").
    """
    provider = provider or OllamaProvider(model)
    text = provider.generate(
        prompt, max_retries=max_retries,
        on_token=on_token, on_stats=on_stats, on_retry=on_retry,
    )
    return text or None  # empty string → failure, not "got text"


def build_consolidate_prompt(template: str, summary: str) -> str:
    prompt = template.replace("{{summary}}", summary)
    if "{{summary}}" not in template:
        prompt += "\n\n" + summary
    return prompt


def _strip_think_blocks(text: str) -> str:
    """Remove extended-thinking <think>...</think> blocks from LLM output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def extract_structured_fields(response: str) -> Optional[dict]:
    """Parse YAML structured fields from LLM response.

    Strips extended-thinking <think>...</think> blocks, then tries
    full response and fenced code blocks.
    Returns dict with known fields or None.
    """
    text = _strip_think_blocks(response.strip())
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


def chat_stream(
    model: str,
    messages: list,
    tools: Optional[list] = None,
    *,
    max_retries: int = 3,
    on_token: Callable[[str], None] = lambda t: None,
    on_message: Callable[[dict], None] = lambda d: None,
    on_retry: Callable[[int, str], None] = lambda a, e: None,
    provider: Optional[Provider] = None,
) -> Optional[str]:
    """Stream from Ollama /api/chat with optional tools support.

    messages: list of dicts with 'role' and 'content' keys.
    tools: optional list of tool definitions (JSON schema for Ollama).
    on_token: called with each content token string.
    on_message: called once with the final message dict
        (may contain 'tool_calls' key for function calling).

    Returns the full accumulated text on success, or None on failure.
    """
    provider = provider or OllamaProvider(model)
    return provider.chat(
        messages, tools=tools, max_retries=max_retries,
        on_token=on_token, on_message=on_message, on_retry=on_retry,
    )
