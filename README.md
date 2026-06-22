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
| `podscribe record <pod>` (alias `start`) | Live mic → transcript → pod storage. Flags: `--model`, `--vad-aggressiveness`, `--device`, `--keep-audio` |
| `podscribe list` | List all pods and their meetings |
| `podscribe show <pod> [meeting-id-prefix \| latest]` | View transcript |
| `podscribe context {add\|remove\|list}` | Manage the glossary (initial_prompt context) for a pod |
| `podscribe enhance <pod> [meeting]` (alias `summarize`) | LLM cleanup pass via local Ollama |
| `podscribe consolidate <pod> [meeting] [--no-log]` (alias `cons`) | Extract structured fields from enhanced summary; append to `meetings.csv` |
| `podscribe config llm {show\|set}` | Project-level LLM config (model, prompt template) in `podscribe.yaml` |
| `podscribe config consolidate {show\|set}` | Project-level consolidate prompt |

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
pods/<name>/
├── config.yaml
├── transcripts/
│   └── DD-MMM-YYYY/           # e.g. 22-JUN-2026
│       ├── <meeting-id>.md    # e.g. 2026-06-22-143012-sam-chen.md (incremental, one [HH:MM:SS] line per segment)
│       ├── <meeting-id>.json  # meeting metadata sidecar (model, duration, etc.)
│       └── <meeting-id>.raw   # raw audio (deleted by default after finalize)
├── summaries/
│   └── DD-MMM-YYYY/
│       └── <meeting-id>.md    # enhanced transcript (output of `podscribe enhance`)
└── meetings.csv               # consolidated log (output of `podscribe consolidate`)
```

Each pod has its own directory. Cross-pod rollups come in a later phase.

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
- **Raw audio deleted by default** after transcript is saved. Use `--keep-audio` for debugging.
- **Pods are isolated.** Each person's data lives in its own directory. Easy to back up, share, or delete one without touching others.

## Tests

```bash
pytest tests/ -v
```

154 offline unit tests + 1 smoke test requiring network. Run with `pytest tests/ -v`. Skip the smoke test with `-k "not transcriber"` (recommended for CI without network). The offline tests cover data models, validation, storage, config, glossary, CLI parsing, and the LLM client. The smoke test (`tests/test_transcriber.py::test_transcriber_accepts_initial_prompt`) downloads a real Whisper model and requires a working `mlx-whisper` install.

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
