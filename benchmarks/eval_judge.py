# benchmarks/eval_judge.py
"""Layer-2 LLM judge: rubric prompt, anonymization, position-swap pairing, verdict parsing."""
from __future__ import annotations

import re
from typing import Optional

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
