# tests/test_eval_checks.py
from __future__ import annotations

from benchmarks.eval_checks import glossary_fidelity, CheckResult

GLOSSARY = [
    {"term": "Kubernetes", "category": "project"},
    {"term": "Anurag Kaushik", "category": "person"},
]


def test_glossary_fidelity_pass_canonical():
    summary = "Anurag Kaushik discussed Kubernetes upgrades."
    r = glossary_fidelity("transcript", summary, GLOSSARY)
    assert r.passed is True
    assert r.violations == []


def test_glossary_fidelity_case_insensitive():
    summary = "anurag kaushik discussed kubernetes upgrades."
    r = glossary_fidelity("transcript", summary, GLOSSARY)
    assert r.passed is True


def test_glossary_fidelity_plural_tolerant():
    summary = "Anurag Kaushik discussed multiple Kubernetes clusters."
    r = glossary_fidelity("transcript", summary, GLOSSARY)
    assert r.passed is True


def test_glossary_fidelity_misspelt_term_violation():
    summary = "Anurag Kausik discussed kubernates upgrades."
    r = glossary_fidelity("transcript", summary, GLOSSARY)
    assert r.passed is False
    assert len(r.violations) == 1
    assert "kubernates" in r.violations[0]


def test_glossary_fidelity_no_partial_word_match():
    summary = "The K8sNode count increased."
    r = glossary_fidelity("transcript", summary, [{"term": "K8s", "category": "project"}])
    assert r.passed is True
