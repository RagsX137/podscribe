# Podscribe — agent instructions

## Project

Python CLI (>=3.10) for local-first live transcription using mlx-whisper + WebRTC VAD on Apple Silicon. Setuptools-based, single package.

## Architecture

`podscribe.cli:main` (console_scripts entrypoint; also `python -m podscribe`).

```
podscribe/
├── cli.py          — argparse + rewrite_argv + all cmd handlers
├── audio.py        — sounddevice InputStream + webrtcvad, 16kHz mono float32
├── transcriber.py  — mlx_whisper.transcribe wrapper (Apple MLX)
├── storage.py      — pods/<name>/ per pod, transcripts .md/.json, raw .raw (deleted by default)
├── models.py       — Pod, Meeting, Segment dataclasses + ID/name helpers
├── config.py       — load/save pod config.yaml + project podscribe.yaml + leadership_team.yaml
├── glossary.py     — glossary add/remove/format for Whisper initial_prompt
└── llm.py          — requests-based Ollama client (enhance command)
```

## CLI quirks

- **Pod-first syntax**: `podscribe <pod> record` → rewritten to `record <pod>` by `rewrite_argv`
- **Aliases**: `start` → `record`, `summarize` → `enhance`
- See `cli.py:rewrite_argv` for exact rewrite logic
- **`--model` default is `base`** (maps to `mlx-community/whisper-base-mlx`); README incorrectly says `large-v3-turbo`
- README is outdated — mentions `pywhispercpp` but the code uses `mlx-whisper`

## Commands

| Command | Notes |
|---------|-------|
| `init <name>` | Name must be kebab-case `^[a-z0-9]+(-[a-z0-9]+)*$`; flags: `--display-name`, `--role`, `--cadence`, `--notes` |
| `record` | `--model` (default `base`), `--vad-aggressiveness` 0-3, `--device`, `--keep-audio`; Ctrl+C to stop; audio lazy-imported |
| `list` | Lists pods + meetings newest-first |
| `show <pod> <id-prefix\|latest>` | Reads from `.md` transcript file |
| `context` | Subcommands: `add`, `remove`, `list`; glossary merged from `leadership_team.yaml` + per-pod `config.yaml` |
| `enhance` | Requires Ollama at localhost:11434 + `llm` section in pod or project config |
| `config llm {show\|set}` | Project-level LLM config in `podscribe.yaml` (repo root) |

## Models

- `Pod`, `Meeting`, `Segment` — dataclasses in `models.py`
- Pod names validated with kebab-case regex at model construction
- Meeting ID: `YYYY-MM-DD-HHMM-<pod-name>`
- mlx-whisper model names: short names like `base` or full HF paths like `mlx-community/whisper-large-v3-turbo`
- Glossary: list of `{"term": str, "category": str}` injected as Whisper `initial_prompt`
- LLM config: `{"model": str, "prompt_template": str}`; supports `{{glossary}}` and `{{transcript}}` placeholders

## Storage layout

```
leadership_team.yaml                       — global glossary (repo root)
podscribe.yaml                             — project LLM config (repo root)
pods/<name>/
├── config.yaml                            — pod metadata, pod-specific glossary, optional llm
└── <DD-MMM-YYYY>/
    ├── transcripts/
    │   ├── <meeting-id>.md                — incremental transcript (one timestamped line per segment)
    │   ├── <meeting-id>.json              — meeting metadata sidecar
    │   └── <meeting-id>.raw               — raw audio (deleted after finalize unless --keep-audio)
    └── summaries/
        └── <meeting-id>.md                — enhanced transcript output
```

Transcript format: `# Meeting: <id>` header, then `[HH:MM:SS] text` lines, appended incrementally (crash-safe).

## Config

Three config layers:
- **Leadership team**: `leadership_team.yaml` at repo root — global glossary entries (names, projects) that apply across all pods
- **Per-pod**: `pods/<name>/config.yaml` — pod-specific glossary, metadata, optional `llm` section
- **Project-level**: `podscribe.yaml` at repo root — `llm` section used as fallback when pod has none

Effective glossary (used during record/enhance) = `leadership_team.yaml` terms + per-pod `config.yaml` terms.
Glossary `initial_prompt` format: `"Please transcribe the following names and project names correctly: <terms>."`

## Tests

```
pytest tests/ -v
```

- 84 unit tests, all offline (no mic or model needed)
- **Filesystem isolation**: every test uses `monkeypatch.chdir(tmp_path)` or separate `base_path` before touching disk
- `test_transcriber.py` has one smoke test that downloads a real Whisper model (slow) — skip with `-k "not transcriber"` if no network
- Use `tmp_path` fixture for temp directories

## Dependencies

Install order matters on macOS:
```
xcode-select --install        # required for webrtcvad C extension
pip install -e .              # installs all deps
```

Declared in `pyproject.toml`: `mlx-whisper`, `webrtcvad`, `sounddevice`, `numpy`, `pyyaml`.
**`requests`** is used by `llm.py` (enhance command) but **not declared in pyproject.toml**. Install manually if using enhance: `pip install requests`.
`mlx-whisper` uses Apple MLX (no separate install). Model downloads cached automatically.

## Gotchas

- **`requests` is an undeclared dependency** — needed only for `enhance` command, not core recording
- **README is stale**: says `pywhispercpp`/`large-v3-turbo` default; actual code uses `mlx-whisper` with `base` default
- **Audio modules lazy-imported** in `cmd_record` — `audio.py` and `transcriber.py` are not loaded for non-recording commands
- **Test isolation**: must `monkeypatch.chdir(tmp_path)` before any disk ops; tests share `tmp_path` per function
- **Model validation is in `Pod.__post_init__`** — constructing a `Pod` with invalid name raises `ValueError`
- **`.raw` audio deleted by default** on `finalize_meeting` unless `keep_audio=True`
- **Ollama must be running** (`ollama serve`) for `enhance` command
- **`__pycache__` dirs checked in** to source tree but gitignored
