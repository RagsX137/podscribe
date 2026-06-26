"""Ollama HTTP client for transcript enhancement."""
from __future__ import annotations

import json
import re
import time
from typing import Callable, Optional

import requests
import yaml

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_SHOW_URL = "http://localhost:11434/api/show"

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


def ollama_model_info(model: str) -> dict:
    """Fetch model details (num_ctx etc.) from /api/show. Best-effort.

    Public (no underscore) so the TUI/CLI can call it for header rendering.
    """
    try:
        r = requests.post(OLLAMA_SHOW_URL, json={"name": model}, timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return {}


def enhance_transcript(
    model: str,
    prompt: str,
    *,
    max_retries: int = 3,
    on_token: Callable[[str], None] = lambda t: None,
    on_stats: Callable[[dict], None] = lambda d: None,
    on_retry: Callable[[int, str], None] = lambda a, e: None,
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
    payload = {"model": model, "prompt": prompt, "stream": True}
    delays = [1, 2, 4]

    for attempt in range(max_retries):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=1800)
            resp.raise_for_status()

            text_parts: list = []
            stats: dict = {}
            try:
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("done"):
                        # Ollama's done chunk has response=""; check done first to avoid emitting a spurious on_token("").
                        stats = {
                            "prompt_eval_count": chunk.get("prompt_eval_count", 0),
                            "eval_count": chunk.get("eval_count", 0),
                            "total_duration_ns": chunk.get("total_duration", 0),
                            "eval_duration_ns": chunk.get("eval_duration", 0),
                        }
                        break
                    if "response" in chunk:
                        text_parts.append(chunk["response"])
                        on_token(chunk["response"])
            except requests.RequestException as e:
                if attempt < max_retries - 1:
                    on_retry(attempt + 1, str(e))
                    time.sleep(delays[min(attempt, len(delays) - 1)])
                    continue
                return None

            on_stats(stats)
            return "".join(text_parts)

        except requests.HTTPError as e:
            # HTTPError may lack .response (e.g. test mocks); fall back to the response mock's status_code.
            status = e.response.status_code if e.response is not None else getattr(resp, "status_code", None)
            if status is not None and 400 <= status < 500:
                return None  # 4xx: don't retry
            # 5xx (or unknown status): mirror the RequestException arm
            if attempt < max_retries - 1:
                on_retry(attempt + 1, str(e))
                time.sleep(delays[min(attempt, len(delays) - 1)])
                continue
            return None
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                on_retry(attempt + 1, str(e))
                time.sleep(delays[min(attempt, len(delays) - 1)])
                continue
            return None

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


OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"


def chat_stream(
    model: str,
    messages: list,
    tools: Optional[list] = None,
    *,
    max_retries: int = 3,
    on_token: Callable[[str], None] = lambda t: None,
    on_message: Callable[[dict], None] = lambda d: None,
) -> Optional[str]:
    """Stream from Ollama /api/chat with optional tools support.

    messages: list of dicts with 'role' and 'content' keys.
    tools: optional list of tool definitions (JSON schema for Ollama).
    on_token: called with each content token string.
    on_message: called once with the final message dict
        (may contain 'tool_calls' key for function calling).

    Returns the full accumulated text on success, or None on failure.
    """
    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "keep_alive": "-1",
    }
    if tools:
        payload["tools"] = tools

    delays = [1, 2, 4]

    for attempt in range(max_retries):
        try:
            resp = requests.post(OLLAMA_CHAT_URL, json=payload, stream=True, timeout=1800)
            resp.raise_for_status()

            text_parts: list = []
            done_data: dict = {}

            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = chunk.get("message", {})
                if msg.get("content"):
                    text_parts.append(msg["content"])
                    on_token(msg["content"])

                if chunk.get("done"):
                    done_data = msg
                    break

            if done_data:
                on_message(done_data)
            return "".join(text_parts)

        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else getattr(resp, "status_code", None)
            if status is not None and 400 <= status < 500:
                return None
            if attempt < max_retries - 1:
                time.sleep(delays[min(attempt, len(delays) - 1)])
                continue
            return None
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(delays[min(attempt, len(delays) - 1)])
                continue
            return None

    return None
