# benchmarks/eval_judge.py
"""Layer-2 LLM judge: rubric prompt, anonymization, position-swap pairing, verdict parsing."""
from __future__ import annotations

import os
import re
import sys
from typing import Optional

import requests

POS_A_FIRST = "pos_a_first"
POS_B_FIRST = "pos_b_first"


def pair_key(challenger: str, champion: str, meeting: str, run: int) -> str:
    return f"{challenger}__vs__{champion}__{meeting}__run{run}__{POS_A_FIRST}"


def swapped_key(key: str) -> str:
    return key.replace(POS_A_FIRST, POS_B_FIRST)


def anonymize_pair(pair: dict) -> dict:
    def _scrub(text: str, model: str) -> str:
        if not model:
            return text
        tokens = {model}
        for part in re.split(r"[:\-./\s]", model):
            part = part.strip()
            if len(part) >= 2:
                tokens.add(part)
        for run in re.findall(r"[A-Za-z]{3,}", model):
            tokens.add(run)
        for run in re.findall(r"[0-9]{2,}", model):
            tokens.add(run)
        out = text
        for tok in tokens:
            out = re.sub(rf"\b{re.escape(tok)}\b", "[MODEL]", out, flags=re.IGNORECASE)
        return out

    return {
        "summary_a": _scrub(pair["challenger"]["text"], pair["challenger"].get("model", "")),
        "summary_b": _scrub(pair["champion"]["text"], pair["champion"].get("model", "")),
    }


RUBRIC_PROMPT = """You are a careful judge comparing two meeting summaries, A and B.

Compare them on these axes:
1. coverage
2. faithfulness
3. readability
4. action-item quality

Output EXACTLY this format (no other text before or after):

coverage: <A|B|tie>
faithfulness: <A|B|tie>
readability: <A|B|tie>
action-item quality: <A|B|tie>
overall: <A|B|tie>
Justification: <one sentence>

Summary A:
{a}

Summary B:
{b}
"""


def build_rubric_prompt(a_text: str, b_text: str) -> str:
    return RUBRIC_PROMPT.format(a=a_text, b=b_text)


_AXIS_RE = re.compile(r"(coverage|faithfulness|readability|action-item quality|overall)\s*:\s*(\w+)", re.IGNORECASE)
_JUST_RE = re.compile(r"Justification:\s*(.+)", re.IGNORECASE | re.DOTALL)


def parse_verdict(raw: str) -> Optional[dict]:
    matches = _AXIS_RE.findall(raw)
    if not matches or not any(a.lower() == "overall" for a, _ in matches):
        return None
    out = {a.lower(): v.lower() for a, v in matches}
    j = _JUST_RE.search(raw)
    out["justification"] = j.group(1).strip() if j else ""
    return out


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"


def _call_claude(prompt: str, model: str) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY not set — required for the Claude judge backend.")
    r = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    parts = []
    for block in data.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


def _call_local(prompt: str, model: str) -> str:
    r = requests.post(
        OLLAMA_GENERATE_URL,
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=600,
    )
    r.raise_for_status()
    return r.json().get("response", "")


def judge_pair(pair: dict, *, backend: str, model: str) -> dict:
    anon = anonymize_pair(pair)
    prompt = build_rubric_prompt(anon["summary_a"], anon["summary_b"])
    call = _call_claude if backend == "claude" else _call_local
    for attempt in (1, 2):
        try:
            raw = call(prompt, model)
        except Exception as e:
            if attempt == 2:
                return {"status": "failed", "raw": f"exception: {e}", "attempt": attempt}
            continue
        v = parse_verdict(raw)
        if v is not None:
            return {"status": "judged", "verdict": v, "raw": raw, "attempt": attempt}
        if attempt == 2:
            return {"status": "failed", "raw": raw, "attempt": attempt}
    return {"status": "failed", "raw": "", "attempt": 2}
