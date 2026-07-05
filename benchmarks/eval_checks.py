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


def _term_token_canonicals(term: str) -> set:
    """Per-token canonicals for a multi-word term: each token lowercased and
    with optional trailing 's' stripped. Lets us compare each summary token
    against each term token independently, so a misspelling of one token in
    a multi-word term (e.g. "Kausik" within "Anurag Kaushik") is caught.
    """
    tokens = _tokenize(term)
    return {_plural_canonical(t) for t in tokens} | {t.lower() for t in tokens}


def _levenshtein_max(a: str, b: str) -> int:
    """Max allowed Levenshtein for a near-match. Scales with the longer string;
    floor of 2 catches short-token misspellings (e.g. 3-letter tokens).
    """
    return max(2, -(-max(len(a), len(b)) // 3))


def glossary_fidelity(transcript: str, summary: str, glossary: list) -> CheckResult:
    """Every glossary term appearing in summary matches canonical spelling.

    Match is case-insensitive and plural-tolerant; token-boundary required.
    Multi-word terms: each token is compared independently so a misspelling of
    one token within a multi-word term (e.g. "Kausik" in "Anurag Kaushik") is
    caught. The per-token distance threshold scales with token length so we
    permit ~1 typo per ~3 characters.
    """
    summary_tokens = set(_tokenize(summary))
    violations = []
    for entry in glossary:
        term = entry["term"]
        token_canonicals = _term_token_canonicals(term)
        for tok in summary_tokens:
            if tok in token_canonicals:
                continue
            if _plural_canonical(tok) in token_canonicals:
                continue
            for canon in token_canonicals:
                if _levenshtein(tok, canon) <= _levenshtein_max(tok, canon):
                    violations.append(tok)
                    break
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


SPEAKER_LINE_RE = re.compile(r"^\[[\d:]+\]\s+([^:]+):", re.MULTILINE)
_HONORIFICS = {"mr", "mrs", "ms", "dr", "prof"}

_HONORIFIC_AND_FALSE_POSITIVES = {
    "mr", "mrs", "ms", "dr", "prof",
    "the", "a", "an", "i", "we", "they", "he", "she",
    "microsoft", "google", "apple", "amazon", "meta", "facebook", "twitter",
    "tesla", "nvidia", "intel", "ibm", "oracle", "salesforce", "adobe",
    "netflix", "spotify", "uber", "lyft", "airbnb", "github", "gitlab",
    "jira", "confluence", "slack", "kubernetes", "yaml", "json", "cli", "tui",
    "api", "sdk", "ui", "ux", "aws", "gcp", "azure", "sql", "nosql",
    "redis", "kafka", "spark", "hadoop", "docker", "linux", "windows", "macos",
    "ios", "android", "react", "angular", "vue", "node", "python", "java",
    "javascript", "typescript", "rust", "ruby", "swift", "kotlin",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december",
    "q1", "q2", "q3", "q4",
    "american", "european", "asian", "african", "british", "french", "german",
    "japanese", "chinese", "indian", "russian", "australian", "canadian",
    "english", "spanish", "mandarin", "hindi", "arabic",
}


def _speaker_labels_in_transcript(transcript: str) -> set:
    out = set()
    for m in SPEAKER_LINE_RE.finditer(transcript):
        name = m.group(1).strip().rstrip(":")
        name = name.split("—")[0].strip()
        if name.lower() in _HONORIFICS:
            continue
        if name:
            out.add(name)
    return out


def _names_in_summary(summary: str, known: set, glossary: list) -> set:
    candidates = set()
    glossary_terms_lower = {entry["term"].lower() for entry in glossary}
    for line in summary.splitlines():
        for tok in re.findall(r"\b[A-Z][a-zA-Z]+\b", line):
            if tok.lower() in _HONORIFIC_AND_FALSE_POSITIVES:
                continue
            if tok.lower() in glossary_terms_lower:
                continue
            candidates.add(tok)
    return candidates


def speaker_preservation(transcript: str, summary: str, glossary: list) -> CheckResult:
    known = _speaker_labels_in_transcript(transcript)
    candidates = _names_in_summary(summary, known, glossary)
    hallucinated = [n for n in candidates if n not in known and n.lower() not in {k.lower() for k in known}]
    return CheckResult(
        name="speaker_preservation",
        passed=not hallucinated,
        violations=hallucinated,
    )


_NUMBER_RE = re.compile(r"\b\d[\d,]*\.?\d*\b")
_DATE_RE = re.compile(
    r"\b("
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}"
    r")\b",
    re.IGNORECASE,
)
_CURRENCY_RE = re.compile(r"\$\s?\d[\d,]*\.?\d*\b")

_WORD_TO_DIGIT = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
    "million": "1000000",
}


def _word_form_to_digit(token: str) -> Optional[str]:
    if "-" in token:
        parts = token.split("-")
        if len(parts) == 2 and parts[0] in _WORD_TO_DIGIT and parts[1] in _WORD_TO_DIGIT:
            return str(int(_WORD_TO_DIGIT[parts[0]]) + int(_WORD_TO_DIGIT[parts[1]]))
    if token in _WORD_TO_DIGIT:
        return _WORD_TO_DIGIT[token]
    return None


def _normalize_numeric(token: str) -> str:
    return token.replace(",", "").replace("$", "").strip()


def _entities_in(text: str) -> set:
    out = set()
    for m in _NUMBER_RE.finditer(text):
        out.add(_normalize_numeric(m.group(0)))
    for m in _CURRENCY_RE.finditer(text):
        out.add(_normalize_numeric(m.group(0)))
    for m in _DATE_RE.finditer(text):
        out.add(m.group(0).lower())
    for tok in re.findall(r"\b[a-zA-Z\-]+\b", text):
        d = _word_form_to_digit(tok.lower())
        if d is not None:
            out.add(d)
    return out


def number_date_faithfulness(transcript: str, summary: str, glossary: list) -> CheckResult:
    transcript_entities = _entities_in(transcript)
    summary_entities = _entities_in(summary)
    invented = sorted([e for e in summary_entities if e not in transcript_entities])
    return CheckResult(
        name="number_date_faithfulness",
        passed=not invented,
        violations=invented,
    )


def length_sanity(
    transcript: str, summary: str, glossary: list,
    *, min_ratio: float = 0.05, max_ratio: float = 0.6,
) -> CheckResult:
    t_len = max(len(transcript or ""), 1)
    s_len = len(summary or "")
    ratio = s_len / t_len
    if ratio < min_ratio:
        return CheckResult(
            name="length_sanity", passed=False,
            detail=f"summary {s_len} chars vs transcript {t_len}: ratio {ratio:.3f} below {min_ratio}",
        )
    if ratio > max_ratio:
        return CheckResult(
            name="length_sanity", passed=False,
            detail=f"summary {s_len} chars vs transcript {t_len}: ratio {ratio:.3f} above {max_ratio} (parroting)",
        )
    return CheckResult(name="length_sanity", passed=True, detail=f"ratio {ratio:.3f}")


def _count_action_items(run: dict) -> int:
    items = run.get("action_items")
    if isinstance(items, list):
        return len(items)
    return 0


def consistency(runs: list) -> CheckResult:
    if len(runs) < 2:
        return CheckResult(name="consistency", passed=True, detail="single run")
    lengths = [len(r.get("text", "")) for r in runs]
    actions = [_count_action_items(r) for r in runs]
    len_var = max(lengths) - min(lengths)
    act_var = max(actions) - min(actions)
    mean_len = sum(lengths) / len(lengths) or 1
    len_drift = len_var > 0.5 * mean_len
    passed = not (len_drift or act_var > 1)
    return CheckResult(
        name="consistency",
        passed=passed,
        detail=(
            f"lengths={lengths} drift {len_var} (mean {mean_len:.0f}); "
            f"action-item counts={actions} drift {act_var}"
        ),
    )


from podscribe.llm import extract_structured_fields


def consolidate_parse(summary: str, *, llm_response_text: str) -> CheckResult:
    fields = extract_structured_fields(llm_response_text)
    if fields is None:
        return CheckResult(
            name="consolidate_parse", passed=False,
            detail="extract_structured_fields returned None (unparseable)",
        )
    expected = {"quick_summary", "key_topics", "action_items", "blockers", "next_steps"}
    present = expected & set(fields.keys())
    if present == expected:
        return CheckResult(
            name="consolidate_parse", passed=True,
            detail="all expected fields present",
        )
    return CheckResult(
        name="consolidate_parse", passed=False,
        detail=f"missing fields: {sorted(expected - present)}",
    )


def run_checks(
    transcript: str,
    summary: str,
    glossary: list,
    *,
    runs: list,
    llm_response_text: str,
    min_ratio: float = 0.05,
    max_ratio: float = 0.6,
) -> list:
    return [
        glossary_fidelity(transcript, summary, glossary),
        speaker_preservation(transcript, summary, glossary),
        number_date_faithfulness(transcript, summary, glossary),
        length_sanity(transcript, summary, glossary, min_ratio=min_ratio, max_ratio=max_ratio),
        consistency(runs),
        consolidate_parse(summary, llm_response_text=llm_response_text),
    ]
