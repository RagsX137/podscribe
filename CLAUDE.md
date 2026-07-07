# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Authoritative reference

**[AGENTS.md](AGENTS.md) is the primary, detailed guide — read it first.** It documents the full architecture, every CLI command/flag, the storage layout, config layering, code style, and gotchas. This file only surfaces the highest-leverage facts and points back to AGENTS.md for depth. Keep the two in sync; prefer extending AGENTS.md over duplicating it here.

## What this is

Local-first live meeting transcription CLI (Python ≥3.10) for Apple Silicon: `mic → WebRTC VAD → mlx-whisper → markdown`, with an optional Ollama-backed LLM `enhance`/`consolidate`/`god` pipeline. Single setuptools package. Entrypoint: `podscribe.cli:main` (also `python -m podscribe`).

The three-stage flow is `record → enhance → consolidate`, each independent.

## Commands

```bash
pip install -e '.[mlx,dev]'               # Apple Silicon engine + pytest/jiwer
pip install -e '.[cuda,dev]'              # NVIDIA/CUDA engine + pytest/jiwer
pytest tests/ -v                          # all tests (600+; count varies with installed engines, 1 network smoke test)
pytest tests/ -k "not transcriber" -v     # skip the one network smoke test (use offline/CI)
pytest tests/test_storage.py -v           # single file
pytest tests/ -k "test_init_pod" -v       # single test by name
```

There is no lint/format tooling configured — match existing style manually.

## Critical conventions (don't violate these)

- **3.10 compatibility**: use `Optional[X]`, never `X | None`. Every module starts with `from __future__ import annotations`.
- **Test filesystem isolation**: every test does `monkeypatch.chdir(tmp_path)` because `pods/` resolves relative to CWD. Omitting it corrupts real pod data. Run all commands from the repo root.
- **CSV is written atomically** via `tempfile.mkstemp` + `os.replace` — never write `meetings.csv` directly. `consolidate` (not `enhance`) is what writes it.
- **LLM core stays headless**: `llm.py` fires `on_token`/`on_stats`/`on_retry` callbacks; the CLI/TUI caller owns all rendering. Never print from the core.
- **Glossary cache**: after changing a pod glossary in a test, reset `podscribe.config._glossary_cache["key"] = None`.
- **TUI output** uses the 256-color synthwave constants in `tui.py` (`C_PEACH`, `C_PINK`, `C_LILAC`, `C_MINT`, `C_DIM`, `C_RED`).

## Non-obvious behaviors

- **Pod-first CLI syntax**: `podscribe <pod> record` is rewritten to `record <pod>` by `rewrite_argv` in [cli.py](podscribe/cli.py). Aliases: `start`→`record`, `summarize`→`enhance`, `cons`→`consolidate`.
- **Audio deps are lazy-imported** in `cmd_record` only — `audio.py`/`transcriber.py` and their heavy deps don't load for other commands.
- **`.raw` audio is kept by default** (`--no-keep-audio` to delete) for future diarization.
- **Two transcript layouts coexist** (2-level without `--type`, 3-level with it); listing/search globs both.
- **`pods/`, `podscribe.yaml`, `leadership_team.yaml` are gitignored** — pod data and configs are never committed. Use the `.example` files to set up.
- **Ollama at `localhost:11434` must be running** for `enhance`, `consolidate`, and `god`.

## LLM Enhance Eval Harness

A staged regression harness for the `enhance` LLM stage. Lives at `benchmarks/eval_enhance.py` with five subcommands sharing a JSON cache under `benchmarks/eval_data/` (gitignored).

- `generate` — runs all (model, meeting, run) combos through the full podscribe pipeline; resumable (skips existing cache).
- `check` — Layer-1 deterministic checks over cached outputs.
- `judge` — Layer-2 champion-anchored pairwise (Claude API for public; local Ollama for fso). Persists both position-swap verdicts separately. Asserts `judged + failed == attempted`.
- `rate` — Layer-3 blind A/B REPL with appended ratings.
- `report` — pure aggregation: per-model Layer-1 pass rates, win/tie/loss vs champion, judge failure rate, cost one-liner.

Cache layout: `benchmarks/eval_data/<suite>__<meeting>__<model>__run<N>.json` (generate/check) and `*.verdict.json` (judge). Manifest at `benchmarks/eval_manifest.yaml` carries 3 public YouTube clips (≤15 min each, pinned time-ranges), 1 private fso ref, and 6 contestants pinned by `{tag, digest}`. `/api/tags` verifies digests on every run.

Privacy: the fso private-suite transcript never reaches a hosted API; it is only judged by the local Ollama model. Documented at `docs/EVALS.md`.

## Working directory rules

Keep throwaway scripts/outputs in `.scratch/` (gitignored). Never write to `/tmp` or paths outside the project, and never commit generated data into the repo root.
