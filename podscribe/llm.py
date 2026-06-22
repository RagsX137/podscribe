"""Ollama HTTP client for transcript enhancement."""
from __future__ import annotations

import json
import re
import sys
import time
from typing import List, Optional

import requests
import yaml
from tqdm import tqdm

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


OLLAMA_SHOW_URL = "http://localhost:11434/api/show"


def _ollama_model_info(model: str) -> dict:
    """Fetch model details (num_ctx etc.) from /api/show. Best-effort."""
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
    show_progress: bool = True,
) -> Optional[str]:
    """Stream from Ollama, show progress + metrics, return full text.

    - Uses stream=True so tokens arrive incrementally (no 10-min wait with
      no feedback).
    - Retries up to max_retries on connection errors and 5xx. Does NOT retry
      on 4xx (bad prompt, model not found).
    - timeout=1800s (30 min) — long enough for heavy Qwen analysis.
    - Returns the accumulated text on success, None on failure.
    """
    info = _ollama_model_info(model) if show_progress else {}
    model_details = info.get("model_info") or {}
    num_ctx = model_details.get("llama.context_length", "?")

    payload = {"model": model, "prompt": prompt, "stream": True}
    delays = [1, 2, 4]

    for attempt in range(max_retries):
        try:
            if show_progress:
                sys.stderr.write(f"Calling Model:{model}...\n")
                sys.stderr.write(f"Context window size : {num_ctx} tokens\n")
                sys.stderr.flush()

            resp = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=1800)
            resp.raise_for_status()

            text_parts: list = []
            stats: dict = {}
            bar = None
            if show_progress:
                bar = tqdm(
                    desc=model, unit="tok", file=sys.stderr,
                    mininterval=0.5, dynamic_ncols=True,
                )

            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "response" in chunk:
                    text_parts.append(chunk["response"])
                    if bar is not None:
                        bar.update(1)
                if chunk.get("done"):
                    stats = {
                        "prompt_eval_count": chunk.get("prompt_eval_count", 0),
                        "eval_count": chunk.get("eval_count", 0),
                        "total_duration_ns": chunk.get("total_duration", 0),
                        "eval_duration_ns": chunk.get("eval_duration", 0),
                    }
                    break

            if bar is not None:
                bar.close()

            if show_progress:
                pe = stats.get("prompt_eval_count", 0)
                ec = stats.get("eval_count", 0)
                ed = (stats.get("eval_duration_ns", 0) or 1) / 1e9
                tps = ec / ed if ed > 0 else 0
                total_s = (stats.get("total_duration_ns", 0) or 1) / 1e9
                sys.stderr.write(
                    f"  \u2713 done in {total_s:.1f}s | "
                    f"prompt {pe} + response {ec} tokens @ {tps:.1f} tok/s\n"
                )
                sys.stderr.flush()
            return "".join(text_parts)

        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else getattr(resp, "status_code", None)
            if status is not None and 400 <= status < 500:
                return None  # 4xx: don't retry
        except requests.RequestException:
            pass

        if attempt < max_retries - 1:
            time.sleep(delays[attempt])

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
