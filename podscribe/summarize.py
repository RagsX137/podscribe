"""Long-form summarization: map-reduce chunking over the enhance path.

Orchestration only — it consumes llm.build_enhance_prompt and an injected
run_llm callable. Kept out of llm.py (which stays a headless HTTP core).
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from .llm import build_enhance_prompt
from .providers.registry import build_provider

CONTEXT_FALLBACK_TOKENS = 8192
CONTEXT_MARGIN = 0.5      # reserve half the window for prompt scaffolding + output
CHARS_PER_TOKEN = 4       # rough English estimate
OVERLAP_CHARS = 400       # carried between chunks to preserve cross-boundary context

_MAP_TEMPLATE = (
    "This is ONE part of a longer KT transcript. Summarize just this part into "
    "dense notes (decisions, architecture, dependencies, gotchas, open questions). "
    "Do not add anything not present.\n\nGlossary: {{glossary}}\n\nPart:\n{{transcript}}"
)


def context_limit_chars(llm_config: dict) -> int:
    """Approx transcript char budget for a single LLM pass."""
    provider = build_provider(llm_config)
    info = provider.model_info()
    ctx = (info.get("model_info") or {}).get("llama.context_length")
    if not isinstance(ctx, int) or ctx <= 0:
        ctx = CONTEXT_FALLBACK_TOKENS
    return int(ctx * CONTEXT_MARGIN * CHARS_PER_TOKEN)


def chunk_text(text: str, max_chars: int, overlap_chars: int) -> List[str]:
    """Split text into line-boundary chunks <= max_chars, carrying overlap."""
    lines = text.splitlines(keepends=True)
    chunks: List[str] = []
    cur = ""
    for line in lines:
        if cur and len(cur) + len(line) > max_chars:
            chunks.append(cur)
            cur = cur[-overlap_chars:] if overlap_chars else ""
        cur += line
    if cur.strip():
        chunks.append(cur)
    return chunks


def summarize_transcript(
    transcript: str,
    *,
    llm_config: dict,
    prompt_template: str,
    glossary: list,
    preserve_speakers: bool,
    run_llm: Callable[[str, dict], Tuple[Optional[str], Optional[str]]],
) -> Tuple[Optional[str], Optional[str]]:
    """Summarize `transcript`. Single pass if it fits, else map-reduce.

    run_llm(prompt, llm_config) -> (text, err). On the first map/reduce error
    the partials are abandoned and (None, err) is returned.
    """
    budget = context_limit_chars(llm_config)
    if len(transcript) <= budget:
        prompt = build_enhance_prompt(
            prompt_template, glossary, transcript,
            preserve_speakers=preserve_speakers,
        )
        return run_llm(prompt, llm_config)

    chunks = chunk_text(transcript, budget, OVERLAP_CHARS)
    partials: List[str] = []
    for chunk in chunks:
        prompt = build_enhance_prompt(
            _MAP_TEMPLATE, glossary, chunk, preserve_speakers=preserve_speakers,
        )
        text, err = run_llm(prompt, llm_config)
        if err is not None:
            return None, err
        partials.append(text or "")

    combined = "\n\n".join(partials)
    reduce_prompt = build_enhance_prompt(
        prompt_template, glossary, combined, preserve_speakers=preserve_speakers,
    )
    return run_llm(reduce_prompt, llm_config)
