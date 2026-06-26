# Podscribe KT Handoff

## What it does

Local-first live transcription CLI for Apple Silicon. Records meetings via mic → WebRTC VAD → mlx-whisper → incremental transcripts. Each person/project gets a **pod** — a dedicated folder with transcripts, glossary terms, LLM-enhanced summaries, and a CSV rollup.

Three layers of processing: **record** (raw transcription) → **enhance** (LLM cleanup) → **consolidate** (structured YAML extraction → CSV).

## Core flow

```
podscribe init <name>          # create a pod for a person
podscribe context <name> add... # add names, projects, terms (Whisper bias)
podscribe record <name>        # live transcribe (uses glossary)
podscribe enhance <name>       # LLM cleanup via Ollama (optional)
podscribe consolidate <name>   # extract structured fields → CSV (optional)
podscribe list                 # list pods and meetings
podscribe show <name> latest   # view transcript
```

## Architecture

```
podscribe/
├── cli.py          — argparse + rewrite_argv + all command handlers
├── tui.py          — interactive TUI: launcher + live views (lazy-imported)
├── audio.py        — sounddevice InputStream + webrtcvad, 16kHz mono float32
├── transcriber.py  — mlx_whisper.transcribe wrapper (Apple MLX)
├── storage.py      — pods/<name>/ per pod, transcripts .md/.json, raw .raw
├── models.py       — Pod, Meeting, Segment dataclasses
├── config.py       — load/save pod config.yaml + project podscribe.yaml + leadership_team.yaml
├── glossary.py     — glossary add/remove/format for Whisper initial_prompt
├── llm.py          — requests-based Ollama client (enhance + consolidate + chat_stream)
├── agent.py        — GodSession: agentic loop; uses llm.chat_stream + tool dispatch
├── agent_tools.py  — tool implementations (list_pods, show_meeting, start_recording, etc.)
├── fs_tools.py     — 5 read-only filesystem tools for god mode (list_directory, read_file_tool, search_fs, find_symbol, find_references)
├── search.py       — cross-pod keyword search (rg backend, Python fallback)
└── export.py       — tar.gz export/import of pods/ + root YAMLs
```

### Key design decisions

- **Pod-first syntax**: `podscribe <pod> command` → rewritten to `command <pod>` by `rewrite_argv` in `cli.py`. Aliases resolved at the same stage.
- **Lazy audio imports**: `audio.py` and `transcriber.py` are imported only inside `cmd_record` — non-recording commands stay fast.
- **Crash-safe transcripts**: Every segment is appended to the `.md` file immediately; Ctrl+C just finalizes metadata. A crash mid-meeting loses at most one segment.
- **Headless LLM core**: `llm.py` fires `on_token`/`on_stats`/`on_retry` callbacks; the caller (CLI or TUI) owns all rendering. No tqdm, no print statements in the core.
- **ATOMIC CSV writes**: `storage.py` uses `tempfile.mkstemp` + `os.replace` for `meetings.csv` — never write CSV directly.

## God mode (`podscribe god`)

An agentic loop that gives the LLM (via Ollama `/api/chat`) 20+ tools to inspect the project and take actions:

| Category | Tools |
|----------|-------|
| Pod ops | `list_pods`, `pod_info`, `init_pod_tool`, `list_meetings_tool`, `show_meeting` |
| Recording | `start_recording`, `stop_recording`, `get_recording_status` |
| LLM | `enhance_meeting`, `consolidate_meeting`, `search_transcripts` |
| Glossary | `glossary_list`, `glossary_add`, `glossary_remove` |
| Export | `export_data` |
| Filesystem (read-only) | `list_directory`, `read_file_tool`, `search_fs`, `find_symbol`, `find_references` |

### Filesystem tools (`fs_tools.py`)

All paths are sandboxed to `Path.cwd()` — any escape returns `{"error": "Path outside project root."}`. No `shell=True`. Output capped at 8000 chars / 500 lines / 100 search hits.

| Function | What it does | Safety |
|----------|-------------|--------|
| `list_directory(path, recursive)` | List files and dirs. Skips `.git`, `__pycache__`, `.venv`. Directories get `/` suffix. | Capped at 500 entries |
| `read_file_tool(path, start_line, end_line)` | Read a text file with 1-based line range. Binary files rejected. | Capped at 500 lines |
| `search_fs(query, path, include_glob)` | Fixed-string search across files. Uses `rg` when available, Python `os.walk` fallback. | Capped at 100 hits |
| `find_symbol(name, path)` | Find Python `def`/`class` declarations by name. Uses `rg --type py` or Python regex. | Capped at 100 hits |
| `find_references(name, path)` | Find all occurrences of an identifier. Uses `rg -F -w` or Python word-boundary regex. | Capped at 100 hits |

### God session flow

1. User sends a prompt (REPL or one-shot via `podscribe god <prompt>`)
2. `GodSession._step` calls `chat_stream` with the message history + tool definitions
3. If the LLM responds with `tool_calls`, `_handle_message` dispatches each call, appends tool results as `role: "tool"` messages, and loops
4. When the LLM responds with text only (no tool calls), that's the final answer — returned to the user
5. Loop is capped at 10 turns to prevent infinite agent loops

### TUI integration

In the interactive TUI (`podscribe` with no args at a TTY), god mode opens a two-pane view:
- **Left pane**: message history (user + assistant)
- **Right pane**: tool call/result log for transparency

Type text to chat, `/exit` to quit the god session.

## Storage layout

```
leadership_team.yaml                       — global glossary (repo root)
podscribe.yaml                             — project LLM + consolidate + god config (repo root)
pods/meetings.csv                          — global rollup (all pods)
pods/<name>/
├── config.yaml                            — pod metadata, pod-specific glossary, optional llm
├── meetings.csv                           — per-pod rollup (output of consolidate)
├── transcripts/
│   └── <DD-MMM-YYYY>/                     — e.g. 22-JUN-2026
│       └── [<type>/]                      — optional subdir when record --type is used
│           ├── <meeting-id>.md            — incremental transcript
│           ├── <meeting-id>.json          — metadata sidecar
│           └── <meeting-id>.raw           — raw audio (deleted by default)
└── summaries/
    └── <DD-MMM-YYYY>/
        └── <meeting-id>.md                — enhanced output
```

- **Meeting ID format**: `YYYY-MM-DD-HHMMSS-<pod-name>` (HHMMSS is 6 digits, not 4)
- **2-level and 3-level layouts coexist** — `list_meetings` globs both `transcripts/*/*.json` and `transcripts/*/*/*.json`
- **`append_log_row` mirrors** every per-pod row to the global `pods/meetings.csv`

## Glossary system

Three layers, merged at runtime:

1. **Leadership team** (`leadership_team.yaml`): global entries shared across all pods
2. **Per-pod** (`pods/<name>/config.yaml`): pod-specific terms
3. **Whisper injection**: both layers are formatted as a comma-separated list and passed as `initial_prompt` during recording

Glossary entries are `{"term": str, "category": str}` dicts. Plain strings in YAML are normalised by `_normalise_entry`. The effective glossary is cached per process by `config.get_effective_glossary` (key = leadership mtime + pod glossary identity).

## Config system

Three config layers:

- **Leadership team**: `leadership_team.yaml` — global glossary
- **Per-pod**: `pods/<name>/config.yaml` — metadata, glossary, optional `llm` section
- **Project**: `podscribe.yaml` at repo root — `llm.model`, `llm.prompt_template`, `llm.preserve_speakers`, `consolidate.prompt`, `god.model`

### Model resolution (god mode)

Priority: CLI `--model` flag → `podscribe.yaml` → `god.model` → `llm.model` → error

### `preserve_speakers` resolution

Pod-level `llm.preserve_speakers` → project-level → default `true`. Non-boolean values raise `ValueError`.

## LLM token streaming

`enhance_transcript` uses `/api/generate`, `chat_stream` uses `/api/chat` (for tool calling). Both:

- Stream tokens via `on_token` callback
- Fire `on_stats` with prompt/eval counts + durations on completion
- Fire `on_retry` before each retry sleep
- Retry up to 3× on connection errors and 5xx (1s, 2s, 4s backoff)
- Do NOT retry on 4xx (bad model, bad prompt)
- Use 1800s (30 min) timeout for long transcripts

`chat_stream` also handles `tool_calls` in the streaming response by accumulating them and firing `on_message` once with the complete message dict (including `tool_calls`).

## Tests

```
pytest tests/ -v                       # all tests
pytest tests/ -k "not transcriber"     # skip the smoke test (offline)
```

- 342 tests (341 offline + 1 smoke). All offline tests need no mic or model.
- Filesystem isolation: every test uses `monkeypatch.chdir(tmp_path)` — tests rely on relative `pods/` resolving inside `tmp_path`.
- `test_transcriber.py::test_transcriber_accepts_initial_prompt` downloads a real Whisper model — skip with `-k "not transcriber"` when offline.
- Glossary cache must be invalidated in tests that modify pod glossaries: set `podscribe.config._glossary_cache["key"] = None`.

## Known gotchas

- **Ollama must be running** (`ollama serve`) for enhance, consolidate, and god mode.
- **Consolidate writes `meetings.csv`**, not enhance. Enhance only writes to `summaries/`.
- **`pods/` is gitignored** — all pod data local-only.
- **Audio modules are lazy-imported** — `audio.py` and `transcriber.py` are not loaded until `cmd_record` runs.
- **`list_meetings` silently skips** meetings whose JSON sidecar is missing or malformed.
- **`.raw` audio deleted by default**; use `record --keep-audio` to save it (required for future diarization).
- **Export skips `podscribe.yaml`** on import to avoid overwriting local LLM config.
- **God mode maxes out at 10 tool-calling turns** to prevent runaway agents.
- **`_truncate` duplication** exists in both `fs_tools.py` and `agent_tools.py` — identical functions, separate modules.
