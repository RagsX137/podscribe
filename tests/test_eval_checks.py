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


def test_speaker_preservation_pass_when_subset():
    from benchmarks.eval_checks import speaker_preservation
    transcript = "[00:00:01] Sam: hi\n[00:00:05] Bob: hello"
    summary = "Sam said hi. Bob greeted."
    r = speaker_preservation(transcript, summary, glossary=[])
    assert r.passed is True
    assert r.violations == []


def test_speaker_preservation_flags_hallucinated_speaker():
    from benchmarks.eval_checks import speaker_preservation
    transcript = "[00:00:01] Sam: hi"
    summary = "Sam spoke. Bob was also present."
    r = speaker_preservation(transcript, summary, glossary=[])
    assert r.passed is False
    assert "Bob" in r.violations


def test_number_date_faithfulness_pass_existing_number():
    from benchmarks.eval_checks import number_date_faithfulness
    transcript = "We saw 2341 requests on July 15 2026."
    summary = "There were 2341 requests on July 15 2026."
    r = number_date_faithfulness(transcript, summary, glossary=[])
    assert r.passed is True
    assert r.violations == []


def test_number_date_faithfulness_word_form_match():
    from benchmarks.eval_checks import number_date_faithfulness
    transcript = "We saw forty-two requests."
    summary = "42 requests were observed."
    r = number_date_faithfulness(transcript, summary, glossary=[])
    assert r.passed is True


def test_number_date_faithfulness_invented_number_flagged():
    from benchmarks.eval_checks import number_date_faithfulness
    transcript = "We saw 100 requests."
    summary = "There were 99999 requests."
    r = number_date_faithfulness(transcript, summary, glossary=[])
    assert r.passed is False
    assert "99999" in r.violations


def test_number_date_faithfulness_rounding_strict_flag():
    from benchmarks.eval_checks import number_date_faithfulness
    transcript = "We saw 1234 requests."
    summary = "About 1200 requests."
    r = number_date_faithfulness(transcript, summary, glossary=[])
    assert r.passed is False  # exact entity rule: 1200 is new


def test_number_date_faithfulness_paraphrase_q2_not_flagged():
    from benchmarks.eval_checks import number_date_faithfulness
    transcript = "Q2 went well."
    summary = "The second quarter went smoothly."
    r = number_date_faithfulness(transcript, summary, glossary=[])
    assert r.passed is True


def test_length_sanity_pass_in_band():
    from benchmarks.eval_checks import length_sanity
    transcript = "x " * 1000
    summary = "y " * 300
    r = length_sanity(transcript, summary, glossary=[], min_ratio=0.05, max_ratio=0.6)
    assert r.passed is True


def test_length_sanity_flags_over_truncation():
    from benchmarks.eval_checks import length_sanity
    transcript = "x " * 1000
    summary = "y "
    r = length_sanity(transcript, summary, glossary=[], min_ratio=0.05, max_ratio=0.6)
    assert r.passed is False
    assert "below" in r.detail.lower() or "short" in r.detail.lower()


def test_length_sanity_flags_parroting():
    from benchmarks.eval_checks import length_sanity
    transcript = "x " * 1000
    summary = transcript
    r = length_sanity(transcript, summary, glossary=[], min_ratio=0.05, max_ratio=0.6)
    assert r.passed is False
    assert "above" in r.detail.lower() or "long" in r.detail.lower()


def test_consistency_low_variance_passes():
    from benchmarks.eval_checks import consistency
    runs = [
        {"text": "Summary of length one.", "action_items": ["a"]},
        {"text": "Summary of length one.", "action_items": ["a"]},
        {"text": "Summary of length one.", "action_items": ["a"]},
    ]
    r = consistency(runs)
    assert r.passed is True
    assert r.detail != ""


def test_consistency_high_variance_flags():
    from benchmarks.eval_checks import consistency
    runs = [
        {"text": "short", "action_items": ["a"]},
        {"text": "short " * 50, "action_items": ["a", "b", "c"]},
        {"text": "xxxx", "action_items": []},
    ]
    r = consistency(runs)
    assert r.passed is False
