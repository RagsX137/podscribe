# Podscribe — agent instructions

## Project

Python CLI (>=3.10) for local-first live transcription using mlx-whisper + WebRTC VAD on Apple Silicon. Setuptools-based, single package.

## Architecture

`podscribe.cli:main` (console_scripts entrypoint; also `python -m podscribe`).

```
podscribe/
├── cli.py          — argparse + rewrite_argv + all cmd handlers
├── tui.py          — interactive TUI: launcher + rich live views (lazy-imported)
├── audio.py        — sounddevice InputStream + webrtcvad, 16kHz mono float32
├── transcriber.py  — mlx_whisper.transcribe wrapper (Apple MLX)
├── storage.py      — pods/<name>/ per pod, transcripts .md/.json, raw .raw (kept by default)
├── models.py       — Pod, Meeting, Segment dataclasses + ID/name/type helpers
├── config.py       — load/save pod config.yaml + project podscribe.yaml + leadership_team.yaml
├── glossary.py     — glossary add/remove/format for Whisper initial_prompt
├── llm.py          — requests-based Ollama client (enhance + consolidate); streaming + retries
├── search.py       — cross-pod keyword search (rg backend, Python fallback)
└── export.py       — tar.gz export/import of pods/ + root YAMLs (path-traversal safe)

benchmarks/bench_enhance.py — Ollama model benchmarking harness (separate script, not installed)
```

## CLI quirks

- **Pod-first syntax**: `podscribe <pod> record` → rewritten to `record <pod>` by `rewrite_argv`
- **Aliases**: `start` → `record`, `summarize` → `enhance`, `cons` → `consolidate`
- See `cli.py:rewrite_argv` for exact rewrite logic
- **`--model` default is `large-v3-turbo`** (maps to `mlx-community/whisper-large-v3-turbo`)
- README is current; it is a reliable source of command/flag examples.

## Commands

| Command | Notes |
|---------|-------|
| `init <name>` | Name must be kebab-case `^[a-z0-9]+(-[a-z0-9]+)*$`; flags: `--display-name`, `--role`, `--cadence`, `--notes` |
| `record` | `--model` (default `large-v3-turbo`), `--vad-aggressiveness` 0-3, `--device`, `--keep-audio` (default **on**; use `--no-keep-audio` to delete), `--type`; Ctrl+C to stop; audio lazy-imported |
| `list` | `list <pod>` filters to one pod. Flags: `--all` (global CSV), `--since` (e.g. `7d`/`24h`/`2026-06-15`), `--recent N`, `--type`; renders a markdown table |
| `show <pod> <id-prefix\|latest>` | Reads from `.md` transcript file |
| `context` | Subcommands: `add`, `remove`, `list`; glossary merged from `leadership_team.yaml` + per-pod `config.yaml` |
| `enhance` | Requires Ollama at localhost:11434 + `llm` section in pod or project config |
| `consolidate` (alias `cons`) | Requires Ollama; extracts structured YAML from enhanced summary and appends/rewrites a row in `meetings.csv`. `--no-log`/`-n` skips the CSV update. Prompts on existing row before rewriting. |
| `search <query>` | Fixed-string match across transcripts. Flags: `--pod`, `--since`, `--type`, `--color`. Uses `rg` if on PATH, else Python fallback. |
| `export` | Bundles `pods/`, `leadership_team.yaml`, `podscribe.yaml` into tar.gz. `--out -` → stdout. Excludes `.raw`, `.env`, `__pycache__/`, `.pytest_cache/`, `.venv/`. |
| `import <archive>` | Restores an export tarball. `--force` overwrites existing pods; `--dry-run` prints only. Refuses path-traversal/symlink members. Skips root-level `podscribe.yaml`. |
| `podscribe` (no args) | TTY-only; opens the remembered-pod launcher menu with Record/Enhance/Consolidate/Others. Falls back to a help message in non-TTY contexts. |
| `config llm {show\|set}` | Project-level LLM config in `podscribe.yaml` (repo root) |
| `config consolidate {show\|set}` | Project-level consolidate prompt (supports `{{summary}}` placeholder) |

## Models

- `Pod`, `Meeting`, `Segment` — dataclasses in `models.py`
- Pod names validated with kebab-case regex at model construction
- **Meeting ID: `YYYY-MM-DD-HHMMSS-<pod-name>`** (note: seconds, 6 digits, not 4)
- `MEETING_TYPES` — full set: `1on1`, `skip-level`, `interview`, `standup`, `retro`, `planning`, `sprint-review`, `all-hands`, `team-sync`, `design-review`, `incident`, `post-mortem`, `brainstorm`, `customer`, `vendor`, `cross-team`, `other`; validated by `parse_meeting_type` (lowercased)
- mlx-whisper model names: short names resolved by `transcriber.MODEL_MAP` are only `base`, `turbo`, `large-v3-turbo`; any other value (including full HF paths like `mlx-community/whisper-large-v3-mlx`) passes through unchanged
- Glossary: list of `{"term": str, "category": str}` injected as Whisper `initial_prompt`
- LLM config: `{"model": str, "prompt_template": str, "preserve_speakers"?: bool}`; templates support `{{glossary}}`, `{{transcript}}`, and `{{summary}}` placeholders

## Storage layout

```
leadership_team.yaml                       — global glossary (repo root)
podscribe.yaml                             — project LLM + consolidate config (repo root)
pods/meetings.csv                          — global rollup (all pods)
pods/<name>/
├── config.yaml                            — pod metadata, pod-specific glossary, optional llm
├── meetings.csv                           — per-pod rollup (output of `consolidate`)
├── transcripts/
│   └── <DD-MMM-YYYY>/                     — e.g. 22-JUN-2026
│       └── [<type>/]                      — optional subdir when `record --type` is used
│           ├── <meeting-id>.md            — incremental transcript (one timestamped line per segment)
│           ├── <meeting-id>.json          — meeting metadata sidecar
│           └── <meeting-id>.raw           — raw audio (kept by default; deleted if --no-keep-audio)
└── summaries/
    └── <DD-MMM-YYYY>/
        └── <meeting-id>.md                — enhanced transcript output
```

Transcript format: `# Meeting: <id>` header, then `[HH:MM:SS] text` lines, appended incrementally (crash-safe).

- 2-level (no type) and 3-level (with type) layouts coexist; `list_meetings` globs both (`transcripts/*/*.json` and `transcripts/*/*/*.json`) and sorts by `started_at` from the JSON sidecar.
- `append_log_row` mirrors every per-pod row to the global `pods/meetings.csv`; global-write failures are logged to stderr but do not block the per-pod write.

## Config

Three config layers:
- **Leadership team**: `leadership_team.yaml` at repo root — global glossary entries (names, projects) that apply across all pods
- **Per-pod**: `pods/<name>/config.yaml` — pod-specific glossary, metadata, optional `llm` section
- **Project-level**: `podscribe.yaml` at repo root — `llm` section (fallback when pod has none) + `consolidate.prompt`

Effective glossary (used during record/enhance) = `leadership_team.yaml` terms + per-pod `config.yaml` terms. Cached per process by `config.get_effective_glossary` (invalidated by `leadership_team.yaml` mtime + pod glossary identity/length).
Glossary `initial_prompt` format: `"Please transcribe the following names and project names correctly: <terms>."`

`preserve_speakers` (bool, default `true`): resolution order pod-level `llm` > project-level `llm` > default. When true, `llm.build_enhance_prompt` prepends an anti-hallucination + speaker-preservation preamble to the template.

`podscribe.yaml` currently sets `llm.model: qwen3.6:27b` (Ollama tag). This must be `ollama pull`-ed before `enhance`/`consolidate` will work. `consolidate` uses the same model by default but a separate `consolidate.prompt` (supports `{{summary}}` placeholder).

## Tests

```
pytest tests/ -v
```

- 208 tests collected (207 offline + 1 smoke). All offline tests need no mic or model.
- **Filesystem isolation**: every test uses `monkeypatch.chdir(tmp_path)` or a separate `base_path` before touching disk; tests share `tmp_path` per function.
- `test_transcriber.py::test_transcriber_accepts_initial_prompt` is the one smoke test that downloads a real Whisper model — skip with `pytest -k "not transcriber"` when offline.
- Use `tmp_path` fixture for temp directories.

## Dependencies

Install order matters on macOS:
```
xcode-select --install        # required for webrtcvad C extension
pip install -e .              # installs all deps
```

Declared in `pyproject.toml`: `mlx-whisper`, `webrtcvad`, `sounddevice`, `rich`, `readchar`, `numpy`, `pyyaml`, `requests`.
`mlx-whisper` uses Apple MLX (no separate install). Model downloads cached automatically under `~/.cache/huggingface/`.

## Gotchas

- **Audio modules lazy-imported** in `cmd_record` — `audio.py` and `transcriber.py` (and their heavy deps: `sounddevice`, `webrtcvad`, `mlx_whisper`) are not loaded for non-recording commands.
- **Model validation is in `Pod.__post_init__`** — constructing a `Pod` with an invalid name raises `ValueError`.
- **`.raw` audio kept by default** (`keep_audio=True`); use `record --no-keep-audio` to delete after finalize. Required for future diarization support.
- **Ollama must be running** (`ollama serve`) for both `enhance` and `consolidate`. `consolidate` requires an existing enhanced summary (run `enhance` first).
- **`consolidate` is what writes `meetings.csv`**, not `enhance`. `enhance` only writes the enhanced markdown to `summaries/`.
- **`pods/` is gitignored**, so pod data is never committed; run commands from the repo root so the relative `pods/` path resolves.
- **`list_meetings` skips** any meeting whose JSON sidecar is missing or malformed (no error raised).

## Working directory rules

- **All work files must live inside this project folder.** Do not use `/tmp`, `~/Desktop`,
  or any other path outside the project. Use `.scratch/` for throwaway scripts and outputs.
- **`.scratch/` IS in `.gitignore`** (along with `.superpowers/`, `.worktrees/`, `pods/`,
  `.venv/`, `*.raw`, `.env`) — it's safe to drop files there, but verify with
  `git check-ignore` before assuming anything is ignored.
- **Never commit generated data into the repo root.** Test outputs, dumps, and reviews
  go in `.scratch/` or a feature branch.
