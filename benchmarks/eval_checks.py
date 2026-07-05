"""Layer-1 deterministic checks for the eval harness.

Each check is a pure function (transcript, summary, glossary) -> CheckResult.
All offline, no network. Fabricated inputs in tests pin behavior.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CheckResult:
    name: str
    passed: bool
    violations: list = field(default_factory=list)
    detail: str = ""


def _tokenize(text: str) -> list:
    return re.findall(r"[A-Za-z0-9]+", text.lower())


def _plural_canonical(term: str) -> str:
    return term.lower().rstrip("s")


def glossary_fidelity(transcript: str, summary: str, glossary: list) -> CheckResult:
    """Every glossary term appearing in summary matches canonical spelling.

    Match is case-insensitive and plural-tolerant; token-boundary required.
    Partial-word matches (e.g. K8s inside K8sNode) do NOT count.
    """
    summary_tokens = set(_tokenize(summary))
    violations = []
    for entry in glossary:
        term = entry["term"]
        canonical_forms = {_plural_canonical(term), term.lower()}
        for tok in summary_tokens:
            if tok in canonical_forms:
                continue
            if _plural_canonical(tok) in canonical_forms:
                continue
            if _levenshtein(tok, term.lower()) <= 2:
                violations.append(tok)
    return CheckResult(
        name="glossary_fidelity",
        passed=not violations,
        violations=violations,
    )


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
