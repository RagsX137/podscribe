"""Glossary management: add, remove, list entries and format for Whisper biasing."""
from __future__ import annotations

from .models import Pod


def add_entry(pod: Pod, term: str, category: str = "") -> None:
    """Add a term to the pod's glossary.

    Dedup is case-insensitive (so "Anurag" and "anurag" are the same entry).
    The first-seen casing is preserved; subsequent attempts raise ValueError.
    Whitespace is stripped from the term before storage and dedup.
    """
    term = term.strip()
    if not term:
        raise ValueError("Term cannot be empty")
    key = term.lower()
    if any(e["term"].lower() == key for e in pod.glossary):
        raise ValueError(f"'{term}' is already in glossary")
    pod.glossary.append({"term": term, "category": category})


def remove_entry(pod: Pod, term: str) -> None:
    """Remove a term from the pod's glossary (case-insensitive)."""
    term = term.strip()
    key = term.lower()
    for i, entry in enumerate(pod.glossary):
        if entry["term"].lower() == key:
            pod.glossary.pop(i)
            return
    raise ValueError(f"'{term}' not found in glossary")


def format_glossary_prompt(glossary: list) -> str:
    if not glossary:
        return ""
    terms = ", ".join(e["term"] for e in glossary)
    return f"Please transcribe the following names and project names correctly: {terms}."
