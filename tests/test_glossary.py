"""Tests for glossary management."""
import pytest
from podscribe.glossary import add_entry, remove_entry, format_glossary_prompt
from podscribe.models import Pod


class TestAddEntry:
    def test_add_entry(self):
        pod = Pod(name="sam-chen")
        add_entry(pod, "Anurag Kaushik", "person")
        assert len(pod.glossary) == 1
        assert pod.glossary[0] == {"term": "Anurag Kaushik", "category": "person"}

    def test_add_duplicate_raises(self):
        pod = Pod(name="sam-chen", glossary=[{"term": "Anurag Kaushik", "category": "person"}])
        with pytest.raises(ValueError, match="already in glossary"):
            add_entry(pod, "Anurag Kaushik", "person")

    def test_add_empty_raises(self):
        pod = Pod(name="sam-chen")
        with pytest.raises(ValueError, match="cannot be empty"):
            add_entry(pod, "", "person")


class TestRemoveEntry:
    def test_remove_entry(self):
        pod = Pod(name="sam-chen", glossary=[{"term": "Anurag Kaushik", "category": "person"}])
        remove_entry(pod, "Anurag Kaushik")
        assert pod.glossary == []

    def test_remove_nonexistent_raises(self):
        pod = Pod(name="sam-chen")
        with pytest.raises(ValueError, match="not found"):
            remove_entry(pod, "Nobody")


class TestFormatGlossaryPrompt:
    def test_format_empty_glossary(self):
        result = format_glossary_prompt([])
        assert result == ""

    def test_format_with_terms(self):
        glossary = [
            {"term": "Anurag Kaushik", "category": "person"},
            {"term": "Project Helios", "category": "project"},
        ]
        result = format_glossary_prompt(glossary)
        assert "Anurag Kaushik" in result
        assert "Project Helios" in result
        assert result.startswith("Please transcribe")
