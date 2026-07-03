from __future__ import annotations

import pytest

from podscribe.summarize import chunk_text, summarize_transcript


def test_chunk_text_respects_max_and_overlap():
    text = "\n".join(f"line {i}" for i in range(100))
    chunks = chunk_text(text, max_chars=120, overlap_chars=20)
    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)
    # reconstructed content covers everything
    assert "line 0" in chunks[0]
    assert "line 99" in chunks[-1]


def test_single_pass_when_fits(monkeypatch):
    monkeypatch.setattr("podscribe.summarize.context_limit_chars", lambda model: 10_000)
    calls = []

    def run_llm(prompt, model):
        calls.append(prompt)
        return "SUMMARY", None

    text, err = summarize_transcript(
        "short transcript", model="m", prompt_template="T {{transcript}}",
        glossary=[], preserve_speakers=False, run_llm=run_llm,
    )
    assert (text, err) == ("SUMMARY", None)
    assert len(calls) == 1          # no map-reduce
    assert "short transcript" in calls[0]


def test_map_reduce_when_too_long(monkeypatch):
    # Force a tiny budget so any real transcript triggers chunking.
    monkeypatch.setattr("podscribe.summarize.context_limit_chars", lambda model: 60)
    prompts = []

    def run_llm(prompt, model):
        prompts.append(prompt)
        return f"partial-{len(prompts)}", None

    long_text = "\n".join(f"sentence number {i} here" for i in range(40))
    text, err = summarize_transcript(
        long_text, model="m", prompt_template="FINAL {{transcript}}",
        glossary=[], preserve_speakers=False, run_llm=run_llm,
    )
    assert err is None
    assert len(prompts) >= 3        # >=2 map calls + 1 reduce
    assert "FINAL" in prompts[-1]   # reduce uses the caller's template


def test_map_reduce_propagates_error(monkeypatch):
    monkeypatch.setattr("podscribe.summarize.context_limit_chars", lambda model: 60)

    def run_llm(prompt, model):
        return None, "ollama down"

    long_text = "\n".join(f"sentence number {i} here" for i in range(40))
    text, err = summarize_transcript(
        long_text, model="m", prompt_template="FINAL {{transcript}}",
        glossary=[], preserve_speakers=False, run_llm=run_llm,
    )
    assert text is None
    assert err == "ollama down"
