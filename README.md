# podscribe

Local-first live transcription for 1:1s and team meetings. Pod-isolated, fully on your machine.

You speak → it transcribes live → saves a markdown transcript per person. No LLM processing yet — that's Phase 2.

## Quick start (macOS, Apple Silicon)

Requires Python 3.10+, Xcode Command Line Tools (`xcode-select --install`), and a working microphone.

```bash
# 1. Set up
cd podscribe
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 1b. Set up config files (gitignored — contain your real names and model prefs)
cp podscribe.yaml.example podscribe.yaml
cp leadership_team.yaml.example leadership_team.yaml
# Edit each file: add your team members to leadership_team.yaml and
# choose your Ollama model in podscribe.yaml

# 2. Create a pod for your first direct report
podscribe init sam-chen --display-name "Sam Chen" --role "Senior Engineer"

# 3. Run a live transcription (do this before / during your next 1:1)
podscribe record sam-chen
# ... talk naturally ...
# Press Ctrl+C to stop and finalize

# 4. See what you got
podscribe list
podscribe show sam-chen latest
```

## Commands

| Command | What it does |
|---|---|
| `podscribe init <name>` | Create a pod (one per person). Flags: `--display-name`, `--role`, `--cadence`, `--notes` |
| `podscribe record <pod>` (alias `start`) | Live mic → transcript → pod storage. Flags: `--model`, `--vad-aggressiveness`, `--device`, `--keep-audio` (default: **on**) / `--no-keep-audio`, `--type` |
| `podscribe list` | List all pods and their meetings. Flags: `--all`, `--since`, `--recent`, `--type` |
| `podscribe show <pod> [meeting-id-prefix \| latest]` | View transcript |
| `podscribe context {add\|remove\|list}` | Manage the glossary (initial_prompt context) for a pod |
| `podscribe search <query>` | Search transcripts across pods. Flags: `--pod`, `--since`, `--type`, `--color` |
| `podscribe enhance <pod> [meeting]` (alias `summarize`) | LLM cleanup pass via local Ollama |
| `podscribe consolidate <pod> [meeting] [--no-log]` (alias `cons`) | Extract structured fields from enhanced summary; append to `meetings.csv` |
| `podscribe export --out <path>` | Bundle `pods/`, `leadership_team.yaml`, and `podscribe.yaml` into a tarball. `--out -` writes to stdout |
| `podscribe import <archive>` | Restore a podscribe export tarball. Flags: `--force`, `--dry-run` |
| `podscribe config llm {show\|set}` | Project-level LLM config (model, prompt template) in `podscribe.yaml` |
| `podscribe config consolidate {show\|set}` | Project-level consolidate prompt |

### Listing & filtering

```
podscribe list                          # all pods, all meetings (existing)
podscribe list <pod>                    # one pod, all meetings
podscribe list --all                    # all pods (uses global meetings.csv)
podscribe list --since 7d               # last 7 days
podscribe list --since 2026-06-15       # since a specific date
podscribe list --recent 5               # limit to N most recent
podscribe list --type 1on1              # filter by meeting type
```

`--since` accepts durations (`Nd`, `Nh`, `Nm`) or ISO dates (`YYYY-MM-DD`).

### Searching

```
podscribe search "Project Helios"               # all pods
podscribe search "auth" --pod sam-chen          # one pod
podscribe search "blocker" --since 7d           # last week
podscribe search "design" --type 1on1           # typed meetings only
podscribe search "x" --color                    # ANSI-highlighted output
```

Output format: `pod-name:DD-MMM-YYYY:<meeting-id>:[HH:MM:SS] <line-text>`.
Matches are fixed-string (no regex). Uses `rg` if installed, falls back to
a Python recursive search otherwise.

### Backup & restore

```
podscribe export --out pods-2026-06-22.tar.gz
podscribe import pods-2026-06-22.tar.gz
podscribe import --dry-run pods-2026-06-22.tar.gz   # show, don't write
podscribe import --force pods-2026-06-22.tar.gz     # overwrite existing pods
podscribe export --out -                             # stdout (for piping)
```

`export` includes `pods/` (transcripts, summaries, per-pod config, per-pod
`meetings.csv`), `leadership_team.yaml`, and `podscribe.yaml`. Excludes
`.raw` audio, `.env`, `__pycache__/`, `.pytest_cache/`, `.venv/`.

`import` refuses to overwrite existing pods by default; pass `--force` to
replace them. The tarball is checked for path-traversal attacks before
extraction.

### Glossary

The glossary is the union of `leadership_team.yaml` (repo root, global) and
`pods/<name>/config.yaml` (pod-specific). It is injected into Whisper as an
`initial_prompt` during `record`, and embedded into the LLM prompt during
`enhance`/`consolidate`.

The effective glossary (leadership + pod-specific) is cached per session
and invalidated automatically when `leadership_team.yaml` changes on disk.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CLI (Python process)                      │
│                                                              │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│   │ Audio    │    │ VAD      │    │ Whisper  │              │
│   │ capture  │ →  │ (webrtc) │ →  │ (mlx-    │              │
│   │ (sd)     │    │ silence  │    │ whisper) │              │
│   └──────────┘    └──────────┘    └──────────┘              │
│        ↑                             ↓                       │
│   16kHz mono                    live text + segments         │
│   PCM chunks                    (buffered in memory)          │
│                                       ↓                       │
│                              ┌──────────────┐                │
│                              │ Pod storage  │                │
│                              │ markdown +   │                │
│                              │ metadata     │                │
│                              └──────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

**Three independent components, clean seams:**
1. **Audio pipeline** (`podscribe/audio.py`) — sounddevice InputStream + WebRTC VAD + chunked Whisper inference
2. **Storage layer** (`podscribe/storage.py`) — pod-aware file management, deterministic meeting IDs, markdown + JSON sidecar
3. **CLI** (`podscribe/cli.py`) — argparse, four commands

## File structure

```
podscribe/
├── pyproject.toml
├── README.md
├── requirements.txt
├── podscribe/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── audio.py
│   ├── transcriber.py
│   ├── storage.py
│   ├── models.py
│   └── config.py
└── tests/
```

Pods are stored under `pods/<name>/`:

```
leadership_team.yaml                       — global glossary (repo root)
podscribe.yaml                             — project LLM config (repo root)
pods/meetings.csv                          — global rollup (all pods)
pods/<name>/
├── config.yaml
├── transcripts/
│   └── DD-MMM-YYYY/                       # e.g. 22-JUN-2026
│       └── [<type>/]                      # optional subdir, e.g. 1on1/, retro/
│           ├── <meeting-id>.md            # e.g. 2026-06-22-143012-sam-chen.md (incremental, one [HH:MM:SS] line per segment)
│           ├── <meeting-id>.json          # meeting metadata sidecar (model, duration, type, etc.)
│           └── <meeting-id>.raw           # raw audio (kept by default; use --no-keep-audio to delete)
├── summaries/
│   └── DD-MMM-YYYY/
│       └── <meeting-id>.md                # enhanced transcript (output of `podscribe enhance`)
└── meetings.csv                           # per-pod rollup (output of `podscribe consolidate`)
```

The optional `<type>/` subdir appears when `--type` is passed to `record`.
A 2-level layout (no type subdir) and a 3-level layout (with type) coexist
on disk and are both discovered by `list` and `search`.

## macOS first-run setup

The first time you run `podscribe record`, **macOS will prompt for microphone access**. Grant it. After that, it remembers.

If prompted, also allow Terminal (or iTerm/etc.) mic access in:
**System Settings → Privacy & Security → Microphone**

`webrtcvad` requires building a small C extension. On macOS:
```bash
xcode-select --install   # if not already installed
pip install webrtcvad
```

## Models

- Default: `large-v3-turbo` (~500MB, downloaded on first use via Apple MLX, then cached)
- mlx-whisper handles download + caching automatically (stored in `~/.cache/huggingface/`). Models download automatically from HuggingFace on first use.
- To use a different model: `podscribe record sam-chen --model base`

Only these short names are resolved by `podscribe` itself:

| Short name | HuggingFace path |
|---|---|
| `base` | `mlx-community/whisper-base-mlx` |
| `turbo` | `mlx-community/whisper-large-v3-turbo` |
| `large-v3-turbo` | `mlx-community/whisper-large-v3-turbo` |

Any other `--model` value is passed through to `mlx-whisper` unchanged, so full HuggingFace paths also work.

## LLM (enhance & consolidate)

- Requires Ollama running locally (`ollama serve`, default `http://localhost:11434`).
- Default model: `qwen3.6:27b` (27B Qwen is preferred over smaller models for output quality).
- The LLM section lives in `podscribe.yaml` (project-level) or per-pod `config.yaml`:

  ```yaml
  llm:
    model: qwen3.6:27b
    prompt_template: |
      You are cleaning up a raw meeting transcript. {{glossary}}
      Fix punctuation, remove filler, and preserve speaker names.
    preserve_speakers: true   # default true; when false, strip speaker names
  ```

- `preserve_speakers: true` (default) keeps speaker names in the enhanced output. Set to `false` to strip them. Resolution order: pod-level `llm.preserve_speakers` > project-level > default `true`.
- `podscribe consolidate` uses a separate, lighter prompt stored under the `consolidate:` key in `podscribe.yaml`. It extracts structured fields (action items, blockers, next steps) and appends them to `pods/<name>/meetings.csv`.

## Privacy

- **All processing local.** Whisper runs via Apple MLX on your machine. No network calls during recording or transcription.
- **Raw audio kept by default** to enable speaker diarization (future). Use `--no-keep-audio` to delete after recording.
- **Pods are isolated.** Each person's data lives in its own directory. Easy to back up, share, or delete one without touching others.
- **Config files are gitignored.** `podscribe.yaml` and `leadership_team.yaml` contain your real team names and personal settings and are excluded from version control. Copy from the `.example` files to get started.

## Tests

```bash
pytest tests/ -v
```

198 offline unit tests + 1 smoke test requiring network. Run with `pytest tests/ -v`. Skip the smoke test with `-k "not transcriber"` (recommended for CI without network). The offline tests cover data models, validation, storage, config, glossary, CLI parsing, search, export/import, and the LLM client. The smoke test (`tests/test_transcriber.py::test_transcriber_accepts_initial_prompt`) downloads a real Whisper model and requires a working `mlx-whisper` install.

## Manual smoke test (on your Mac)

Before using in a real meeting, do this:

```bash
podscribe init smoke-test
podscribe record smoke-test
# Say: "Testing one two three. The quick brown fox jumps over the lazy dog. This is a test of podscribe live transcription."
# Wait a few seconds, then Ctrl+C
podscribe show smoke-test latest
```

Verify:
- Transcript is readable
- Timestamps are roughly right
- No obviously hallucinated phrases ("thanks for watching", "subscribe", etc.)
- If hallucination is bad, try `--vad-aggressiveness 3`

## VAD tuning

`--vad-aggressiveness` controls how strict the silence detector is:
- `0` — very loose, lets everything through (more noise → more false segments)
- `1` — loose
- `2` — default, balanced
- `3` — strict, only clear speech (may clip the start of soft-spoken words)

Start with `2`. If you see lots of "…" or empty segments in transcripts, raise to `3`. If you're losing words at the start of sentences, lower to `1`.

## Troubleshooting

Model download is handled by `mlx-whisper` automatically via Hugging Face Hub.

**"No module named webrtcvad"** — needs C build tools: `xcode-select --install` then `pip install webrtcvad`.

**"No module named sounddevice"** — `pip install sounddevice`. On Linux you may need `portaudio19-dev` first.

**Whisper model download is slow** — first run downloads ~500MB. Subsequent runs use cached model.

**Live transcript is choppy** — try `--vad-aggressiveness 3` (stricter silence detection = cleaner segments).

**Transcript has garbage / hallucinations on pauses** — VAD aggressiveness too low. Raise to 3.

**Audio device issues** — check input device: `python -c "import sounddevice; print(sounddevice.query_devices())"`. Use `--device N` to pick one.

**App crashed mid-meeting** — segments are written to disk incrementally, so you should still have everything up to the crash point. Run `podscribe show <pod> latest`.

## Roadmap

- **Phase 1 (this version):** Live transcription CLI, pod storage, list/show ✓
- **Phase 2:** LLM cleanup pass (Ollama, local) — fix hallucinations, structure, punctuation
- **Phase 3:** Prep generation from past meetings (questions for next 1:1)
- **Phase 4:** Semantic search across transcripts + longitudinal profile
- **Phase 5:** Speaker diarization for multi-speaker meetings

## License

MIT
