"""Tests for glossary management."""
import pytest
from podscribe.glossary import add_entry, remove_entry, format_glossary_prompt
from podscribe.models import Pod


@pytest.fixture
def pod():
    return Pod(name="sam-chen")


def test_add_entry_accepts_new_term(pod):
    add_entry(pod, "Anurag Kaushik", "person")
    assert {"term": "Anurag Kaushik", "category": "person"} in pod.glossary


def test_add_entry_dedups_case_insensitive(pod):
    add_entry(pod, "Anurag Kaushik", "person")
    with pytest.raises(ValueError, match="already in glossary"):
        add_entry(pod, "anurag kaushik", "person")


def test_add_entry_preserves_first_seen_casing(pod):
    add_entry(pod, "Anurag Kaushik", "person")
    with pytest.raises(ValueError):
        add_entry(pod, "ANURAG KAUSHIK", "person")
    # Original casing is what got stored
    assert pod.glossary[0]["term"] == "Anurag Kaushik"


def test_add_entry_strips_whitespace(pod):
    add_entry(pod, "  Anurag  ", "person")
    assert pod.glossary[0]["term"] == "Anurag"


def test_add_entry_rejects_empty(pod):
    with pytest.raises(ValueError, match="cannot be empty"):
        add_entry(pod, "   ", "")


def test_remove_entry_case_insensitive(pod):
    add_entry(pod, "Anurag Kaushik", "person")
    remove_entry(pod, "ANURAG KAUSHIK")
    assert pod.glossary == []


def test_remove_entry_missing_raises(pod):
    with pytest.raises(ValueError, match="not found"):
        remove_entry(pod, "Nobody")
