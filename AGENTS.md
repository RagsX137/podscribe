# Podscribe — agent instructions

## Project

Python CLI (>=3.10) for local-first live transcription using Whisper + WebRTC VAD. Setuptools-based, no monorepo.

## Architecture

`podscribe.cli:main` (console_scripts entrypoint; also `python -m podscribe`). Three layers:
- **CLI** (`cli.py`) — argparse + custom argv preprocessor (`rewrite_argv`) before parser
- **Audio** (`audio.py`) — sounddevice InputStream + webrtcvad, 16kHz mono float32
- **Storage** (`storage.py`) — `pods/<name>/` per pod, transcripts as `.md` (segments appended incrementally), metadata `.json`, raw `.raw` (deleted by default)

## CLI quirks

- **Pod-first syntax**: `podscribe <pod> record` → rewritten to `record <pod>` by `rewrite_argv`
- **Aliases**: `start` → `record`, `summarize` → `enhance`
- See `cli.py:rewrite_argv` for the exact rewrite logic

## Commands

| Command | Notes |
|---------|-------|
| `init` | Name must be kebab-case |
| `record` | Default model: `base.en`; `--vad-aggressiveness` 0-3; Ctrl+C to stop |
| `list` | Lists pods + meetings |
| `show` | Accepts meeting ID prefix or `latest` |
| `context` | Subcommands: `add`, `remove`, `list`; stored in per-pod `config.yaml` glossary |
| `enhance` | Requires Ollama at localhost:11434 + `llm` section in pod `config.yaml` |

## Models

- `Pod`, `Meeting`, `Segment` — all dataclasses in `models.py`
- Pod names validated with kebab-case regex (`^[a-z0-9]+(-[a-z0-9]+)*$`)
- Meeting ID: `YYYY-MM-DD-HHMM-<pod-name>`
- Glossary: list of `{"term": str, "category": str}` injected as Whisper `initial_prompt`
- LLM config: `{"model": str, "prompt_template": str}`; supports `{{glossary}}` and `{{transcript}}` placeholders

## Tests

```bash
pytest tests/ -v
```

- 45+ unit tests, all offline (no mic or model needed)
- **Filesystem isolation**: every test uses `monkeypatch.chdir(tmp_path)` before touching disk
- `test_transcriber.py` has one smoke test that downloads a real Whisper model (slow) — skip with `-k "not transcriber"` if no network
- Use `tmp_path` fixture for temp directories

## Dependencies

Install order matters on macOS:
```bash
xcode-select --install        # required for webrtcvad C extension
pip install -e .              # installs pywhispercpp, webrtcvad, sounddevice, numpy, pyyaml
```

`requests` is used only by `llm.py` (enhance command). Not required for core recording path.

## Config

Per-pod `pods/<name>/config.yaml` is hand-editable. Glossary and LLM sections live here:
```yaml
glossary:
  - term: Some Name
    category: person
llm:
  model: qwen3.6
  prompt_template: "Fix: {{transcript}}"
```

## Docs

- `docs/KT-HANDOFF.md` — knowledge transfer summary
- `docs/USER-MANUAL.md` — user-facing quick reference
- `docs/superpowers/` — specs and plans from brainstorming workflow

## Gen

- No `opencode.json` or existing instruction files
- Not a git repo
- `.gitignore` covers `__pycache__/`, `.venv/`, `venv/`, `pods/`, `*.egg-info/`, `.pytest_cache/`, `.DS_Store`, `*.raw`
