# LLM Enhance Evaluations

This document describes how podscribe's LLM `enhance` stage is evaluated for quality on public multi-speaker meetings end-to-end (audio → transcript → summary).

## Methodology

Three layers:

1. **Deterministic checks (Layer 1)** — pure functions over (transcript, summary, glossary). Report pass/fail for speaker preservation, glossary fidelity, number/date faithfulness, length sanity, consistency (N=3 run variance), and consolidate-parse.
2. **LLM judge (Layer 2)** — champion-anchored pairwise (`qwen3.6:27b` is the champion) with position-swap. Claude API (`claude-sonnet-5` default) judges the public suite; the local champion model (`--backend local`) judges the private `fso` suite, where data privacy forbids sending the transcripts to a hosted API. The private suite is **local-only by hard rule**: `judge --suite private --backend claude` fails fast with a refusal — it is never silently downgraded, so a forgotten flag stops the run rather than leaking the transcript. Reported as win/tie/loss rates vs champion, per axis and overall.
3. **Blind human A/B (Layer 3)** — `benchmarks/eval_enhance.py rate` shows two anonymized summaries side-by-side in randomized order; rater picks A/B/tie. Model identities stay hidden until the session ends. The headline output is the human–judge agreement rate.

## Suites

- **Public (3 commitments)**: 3 YouTube engineering meeting clips (≤15 min each), committed pointers and time-ranges in `benchmarks/eval_manifest.yaml`. Downloaded audio, transcripts, and cached outputs live under `benchmarks/eval_data/` (gitignored).
- **Private (confirmation)**: the existing `fso` 2026-06-22-1438 meeting transcript. Read-only; no derivatives committed except aggregate metrics. Has never been and will never be sent to a hosted API.

## Contestants

6 models pinned by `{tag, digest}` in the manifest. Per default: Qwen ladder (27b/14b/8b) + one llama, gemma, and mistral. `/api/tags` verifies each digest before each run. This is a regression harness — a quiet model refresh that changes the digest fails fast with a "pull the pinned version" message.

## Reproduce

```
python benchmarks/eval_enhance.py generate --runs 3
python benchmarks/eval_enhance.py check
ANTHROPIC_API_KEY=sk-... python benchmarks/eval_enhance.py judge          # public, Claude
python benchmarks/eval_enhance.py rate
python benchmarks/eval_enhance.py report

# Private (fso) suite — never leaves the machine; the cloud backend is refused.
python benchmarks/eval_enhance.py judge --suite private --backend local
python benchmarks/eval_enhance.py rate --suite private
python benchmarks/eval_enhance.py report --suite private
```

## Caveats

(Style mirrors `docs/BENCHMARKS.md`.)

- Judge preference is not ground truth.
- n=1 human rater.
- The private-suite local judge shares a family with a contestant; this bias is disclosed and quantified by the Layer-3 agreement rate rather than hand-waved.
- Public-suite transcripts inherit ASR/diarization noise by design — that's the product being measured.
- YouTube sources may rot — the manifest pins IDs + time-ranges, and the fetch script fails loudly.

## Cost

Default matrix · `run0` judging · public suite: 5 challengers × 3 meetings × 2 swaps = 30 Claude calls. At Sonnet pricing the cost one-liner is printed by `report`. Use `--judge-runs all` for 90 calls.
