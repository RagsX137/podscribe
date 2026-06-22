"""Glossary management: add, remove, list entries and format for Whisper biasing."""
from __future__ import annotations

from .models import Pod


def add_entry(pod: Pod, term: str, category: str = "") -> None:
    term = term.strip()
    if not term:
        raise ValueError("Term cannot be empty")
    if any(e["term"] == term for e in pod.glossary):
        raise ValueError(f"'{term}' is already in glossary")
    pod.glossary.append({"term": term, "category": category})


def remove_entry(pod: Pod, term: str) -> None:
    term = term.strip()
    for i, entry in enumerate(pod.glossary):
        if entry["term"] == term:
            pod.glossary.pop(i)
            return
    raise ValueError(f"'{term}' not found in glossary")


def format_glossary_prompt(glossary: list) -> str:
    if not glossary:
        return ""
    terms = ", ".join(e["term"] for e in glossary)
    return f"Please transcribe the following names and project names correctly: {terms}."
