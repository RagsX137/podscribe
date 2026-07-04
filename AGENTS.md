# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project

Python CLI (>=3.10) for local-first live transcription using mlx-whisper + WebRTC VAD on Apple Silicon. Setuptools-based, single package.

## Architecture

`podscribe.cli:main` (console_scripts entrypoint; also `python -m podscribe`).

```
podscribe/
├── cli.py          — argparse + rewrite_argv + all cmd handlers
├── tui.py          — interactive TUI: launcher + live views (lazy-imported)
├── audio.py        — sounddevice InputStream + webrtcvad, 16kHz mono float32
├── transcriber.py  — mlx_whisper.transcribe wrapper (Apple MLX)
├── diarizer.py     — pyannote.audio speaker diarization (lazy-imported; [diarize] extra)
├── hf_auth.py      — HuggingFace token resolution (~/.config/podscribe/hf_token, mode 0o600)
├── storage.py      — pods/<name>/ per pod, transcripts .md/.json, raw .raw (kept by default)
├── models.py       — Pod, Meeting, Segment dataclasses + ID/name/type helpers
├── config.py       — load/save pod config.yaml + project podscribe.yaml + leadership_team.yaml
├── glossary.py     — glossary add/remove/format for Whisper initial_prompt
├── llm.py          — requests-based Ollama client (enhance + consolidate + chat_stream); streaming + retries
├── agent.py        — GodSession: agentic loop; uses llm.chat_stream + tool dispatch
├── agent_tools.py  — tool implementations (list_pods, show_meeting, start_recording, etc.)
├── search.py       — cross-pod keyword search (rg backend, Python fallback)
└── export.py       — tar.gz export/import of pods/ + root YAMLs (path-traversal safe)

benchmarks/bench_enhance.py    — Ollama model benchmarking harness (separate script, not installed)
benchmarks/bench_transcribe.py — Whisper model bench on fixtures/asr (--asr-dir selects a clip set)
benchmarks/bench_meeting.py    — bench all models on a real (media + .vtt) pair in a benchmark_data/ folder
```

`.raw` is now CONTINUOUS (all frames, silence included), owned by `AudioCapture`
(`raw_audio_path`) via the `_segments_from_chunks` seam — required for diarization
and for a clock that matches transcript timestamps. `audio_layout: "continuous"`
in the meeting JSON gates `diarize`.

## Commands

| Command | Notes |
|---------|-------|
| `init <name>` | Name must be kebab-case `^[a-z0-9]+(-[a-z0-9]+)*$`; flags: `--display-name`, `--role`, `--cadence`, `--notes` |
| `record` | `--model` (default `large-v3-turbo`), `--vad-aggressiveness` 0-3, `--device`, `--keep-audio` (default **on**; use `--no-keep-audio` to delete), `--type`; Ctrl+C to stop; audio lazy-imported |
| `ingest` | KT video → kt-type session. `podscribe <pod> ingest <video> [--transcript P] [--asr] [--model M]`. Uses a sibling `.vtt`/`.srt` as source of truth; `--asr` forces local mlx-whisper (never overwrites the vtt — creates a separate session). Requires ffmpeg only on the `--asr` path. |
| `list` | `list <pod>` filters to one pod. Flags: `--all` (global CSV), `--since` (e.g. `7d`/`24h`/`2026-06-15`), `--recent N`, `--type`; renders a markdown table |
| `show <pod> <id-prefix\|latest>` | Reads from `.md` transcript file. Flag: `--kt` targets KT sessions only (resolves within the `kt/` subtree). |
| `context` | Subcommands: `add`, `remove`, `list`; glossary merged from `leadership_team.yaml` + per-pod `config.yaml` |
| `enhance` | Requires Ollama at localhost:11434 + `llm` section in pod or project config. Flag: `--kt` summarizes a KT session (from the `kt/` subtree) instead of a meeting. |
| `consolidate` (alias `cons`) | Requires Ollama; extracts structured YAML from enhanced summary and appends/rewrites a row in `meetings.csv`. `--no-log`/`-n` skips the CSV update. Prompts on existing row before rewriting. |
| `ask` | Scoped KT Q&A: `podscribe <pod> ask <id\|latest> [question...]`. Grounded in one KT transcript (kt/ subtree only); REPL when no question. |
| `diarize` | Post-hoc diarization via pyannote.audio (`pip install -e '.[diarize]'` + HF token). Writes `.diarized.md`; `show`/`enhance` prefer it. Refuses non-continuous recordings. Defaults to Apple MPS/Metal when available (CPU fallback). Flags: `--num-speakers`, `--cpu`, `--relogin`. |
| `search <query>` | Fixed-string match across transcripts. Flags: `--pod`, `--since`, `--type`, `--color`, `--kt` (search KT sessions instead of meetings; default excludes kt/). Uses `rg` if on PATH, else Python fallback. |
| `god [prompt]` | Agentic mode: no prompt → TUI REPL; `--model` override stored as `god.model` in `podscribe.yaml` |
| `export` | Bundles `pods/`, `leadership_team.yaml`, `podscribe.yaml` into tar.gz. `--out -` → stdout. Excludes `.raw`, `.env`, `__pycache__/`, `.pytest_cache/`, `.venv/`. |
| `import <archive>` | Restores an export tarball. `--force` overwrites existing pods; `--dry-run` prints only. Refuses path-traversal/symlink members. Skips root-level `podscribe.yaml`. |
| `podscribe` (no args) | TTY-only; opens the remembered-pod launcher menu with Record/Enhance/Consolidate/Others. Falls back to a help message in non-TTY contexts. |
| `config llm {show\|set}` | Project-level LLM config in `podscribe.yaml` (repo root) |
| `config consolidate {show\|set}` | Project-level consolidate prompt (supports `{{summary}}` placeholder) |
| `config god {show\|set}` | god-mode model in `podscribe.yaml` under `god.model`; falls back to `llm.model` if unset |

## CLI quirks

- **Pod-first syntax**: `podscribe <pod> record` → rewritten to `record <pod>` by `rewrite_argv` in [`cli.py`](podscribe/cli.py:966)
- **Aliases**: `start` → `record`, `summarize` → `enhance`, `cons` → `consolidate`
- `rewrite_argv` logic: if `argv[0]` is not a known command and `argv[1]` is, it swaps them. Aliases are also resolved on `argv[0]` before the swap check.
- **`--model` default is `large-v3-turbo`** (maps to `mlx-community/whisper-large-v3-turbo`)
- `cmd_record` and `cmd_enhance`/`cmd_consolidate` both check `sys.stdout.isatty() and sys.stderr.isatty()` and delegate to TUI views if true — plain execution requires non-TTY or redirection.
- README is current; it is a reliable source of command/flag examples.

## Models

- `Pod`, `Meeting`, `Segment` — dataclasses in [`models.py`](podscribe/models.py)
- Pod names validated with kebab-case regex at model construction (`Pod.__post_init__` raises `ValueError`)
- **Meeting ID: `YYYY-MM-DD-HHMMSS-<pod-name>`** (seconds = 6 digits, NOT 4)
- `MEETING_TYPES` — full set: `1on1`, `skip-level`, `interview`, `standup`, `retro`, `planning`, `sprint-review`, `all-hands`, `team-sync`, `design-review`, `incident`, `post-mortem`, `brainstorm`, `customer`, `vendor`, `cross-team`, `other`; validated by `parse_meeting_type` (lowercased)
- mlx-whisper model names: short names resolved by `transcriber.MODEL_MAP` are only `base`, `turbo`, `large-v3-turbo`; any other value (including full HF paths) passes through unchanged
- Glossary: list of `{"term": str, "category": str}` injected as Whisper `initial_prompt`
- LLM config: `{"model": str, "prompt_template": str, "preserve_speakers"?: bool}`; templates support `{{glossary}}`, `{{transcript}}`, and `{{summary}}` placeholders

## Storage layout

```
leadership_team.yaml                       — global glossary (repo root)
podscribe.yaml                             — project LLM + consolidate + god config (repo root)
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
├── summaries/
│   └── <DD-MMM-YYYY>/
│       └── <meeting-id>.md                — enhanced transcript output
└── kt/
    ├── transcripts/<DD-MMM-YYYY>/<id>.md + <id>.json   — KT sessions (type=kt, source=vtt|asr)
    └── summaries/<DD-MMM-YYYY>/<id>.md                 — enhance --kt output
```

Transcript format: `# Meeting: <id>` header, then `[HH:MM:SS] text` lines, appended incrementally (crash-safe).

- 2-level (no type) and 3-level (with type) layouts coexist; `list_meetings` globs both (`transcripts/*/*.json` and `transcripts/*/*/*.json`) and sorts by `started_at` from the JSON sidecar.
- `append_log_row` mirrors every per-pod row to the global `pods/meetings.csv`; global-write failures are logged to stderr but do not block the per-pod write.
- CSV atomic writes use `tempfile.mkstemp` + `os.replace` — never write CSV directly.

## Config

Three config layers:
- **Leadership team**: `leadership_team.yaml` at repo root — global glossary entries (names, projects) that apply across all pods. Plain-string entries (`["Name"]`) are normalised to `{"term": "...", "category": ""}` by `_normalise_entry`.
- **Per-pod**: `pods/<name>/config.yaml` — pod-specific glossary, metadata, optional `llm` section
- **Project-level**: `podscribe.yaml` at repo root — `llm` section (fallback when pod has none) + `consolidate.prompt` + `god.model`

Effective glossary = `leadership_team.yaml` terms + per-pod `config.yaml` terms. Cached per process by `config.get_effective_glossary` (key = leadership mtime + `id(pod.glossary)` + `len(pod.glossary)`).

`preserve_speakers` (bool, default `true`): resolution order pod-level `llm` > project-level `llm` > default. When true, `llm.build_enhance_prompt` prepends anti-hallucination + speaker-preservation preambles before the template.

`podscribe.yaml` currently sets `llm.model: qwen3.6:27b` (Ollama tag). `consolidate` uses the same model by default but a separate `consolidate.prompt`. `god` command uses `god.model` with fallback to `llm.model`.

## Tests

```bash
pytest tests/ -v                              # all tests
pytest tests/test_storage.py -v              # single file
pytest tests/ -k "test_init_pod" -v          # single test by name
pytest tests/ -k "not transcriber" -v        # skip the smoke test (offline)
```

- 208 tests collected (207 offline + 1 smoke). All offline tests need no mic or model.
- **Filesystem isolation**: every test uses `monkeypatch.chdir(tmp_path)` — tests rely on relative `pods/` path resolving inside `tmp_path`. Omitting this will corrupt real pod data.
- `test_transcriber.py::test_transcriber_accepts_initial_prompt` downloads a real Whisper model — skip with `-k "not transcriber"` when offline.
- Invalidate the glossary cache in tests that add/modify pod glossaries: set `podscribe.config._glossary_cache["key"] = None` after saving config changes.
- Use `tmp_path` fixture for temp directories.

## Code style

- All modules begin with `from __future__ import annotations` (deferred evaluation)
- Imports: stdlib first, then third-party, then relative `.module` — all relative imports use dotted form
- Private helpers prefixed with `_` (e.g. `_hms`, `_fmt_time`, `_resolve_meeting`)
- Error returns: CLI command functions return `int` exit code (0 = success, 1 = user error, 2 = bad invocation). Print errors to `sys.stderr`, normal output to `sys.stdout`.
- LLM streaming: headless core (`llm.py`) fires `on_token`/`on_stats`/`on_retry` callbacks; caller (CLI or TUI) owns rendering — never add output directly in the core
- `save_pod_config` uses `yaml.safe_dump(..., sort_keys=False, allow_unicode=True)` — preserve key order
- Type hints: `Optional[X]` style (not `X | None`) to maintain 3.10 compatibility

## Dependencies

Install order matters on macOS:
```
xcode-select --install        # required for webrtcvad C extension
pip install -e .              # installs all deps including pytest under [dev]
```

`mlx-whisper` uses Apple MLX (no separate install). Model downloads cached under `~/.cache/huggingface/`.

## Gotchas

- **Audio modules lazy-imported** in `cmd_record` — `audio.py` and `transcriber.py` (and their heavy deps) are not loaded for non-recording commands.
- **`.raw` audio kept by default** (`keep_audio=True`); use `record --no-keep-audio` to delete after finalize. Required for future diarization support.
- **Ollama must be running** (`ollama serve`) for both `enhance` and `consolidate`. `consolidate` requires an existing enhanced summary (run `enhance` first).
- **`consolidate` is what writes `meetings.csv`**, not `enhance`. `enhance` only writes the enhanced markdown to `summaries/`.
- **`pods/` is gitignored**, so pod data is never committed; run commands from the repo root so the relative `pods/` path resolves.
- **`list_meetings` skips** any meeting whose JSON sidecar is missing or malformed (no error raised).
- **KT sessions live under `pods/<pod>/kt/`** and are excluded from `list`/`search`/`list_meetings` by default; use `--kt` to target them. `search` default explicitly excludes `kt/` (it would otherwise mislabel the pod).
- **`god` command is a full agentic loop** (`agent.py` + `agent_tools.py`): it uses `/api/chat` (not `/api/generate`) via `llm.chat_stream`, supports tool calling, and maintains session history inside `GodSession`.
- **TUI palette** is 256-color synthwave (`C_PEACH`, `C_PINK`, `C_LILAC`, `C_MINT`, `C_DIM`, `C_RED`) defined as constants in `tui.py` — use these for any new TUI output.
- **`export` deliberately skips `podscribe.yaml`** on import to avoid overwriting local LLM config.

## Working directory rules

- **All work files must live inside this project folder.** Do not use `/tmp`, `~/Desktop`, or any other path outside the project. Use `.scratch/` for throwaway scripts and outputs.
- **`.scratch/` IS in `.gitignore`** (along with `.superpowers/`, `.worktrees/`, `pods/`, `.venv/`, `*.raw`, `.env`) — safe to drop files there. Verify with `git check-ignore` before assuming anything is ignored.
- **Never commit generated data into the repo root.** Test outputs, dumps, and reviews go in `.scratch/` or a feature branch.
