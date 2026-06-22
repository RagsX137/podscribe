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
| `podscribe record <pod>` | Live mic → transcript → pod storage. Flags: `--model`, `--vad-aggressiveness`, `--device`, `--keep-audio` |
| `podscribe list` | List all pods and their meetings |
| `podscribe show <pod> [meeting-id-prefix \| latest]` | View transcript |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CLI (Python process)                      │
│                                                              │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│   │ Audio    │    │ VAD      │    │ Whisper  │              │
│   │ capture  │ →  │ (webrtc) │ →  │ (cpp via │              │
│   │ (sd)     │    │ silence  │    │ pywcpp)  │              │
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
- `config.yaml` — pod metadata
- `transcripts/YYYY-MM-DD-HHMM-<pod>.md` — markdown transcript (one line per segment, with HH:MM:SS timestamp)
- `transcripts/YYYY-MM-DD-HHMM-<pod>.json` — meeting metadata (model, duration, etc.)

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
- mlx-whisper handles download + caching automatically (stored in `~/.cache/huggingface/`)
- To use a different model: `podscribe record sam-chen --model base`

## Privacy

- **All processing local.** Whisper runs via Apple MLX on your machine. No network calls during recording or transcription.
- **Raw audio deleted by default** after transcript is saved. Use `--keep-audio` for debugging.
- **Pods are isolated.** Each person's data lives in its own directory. Easy to back up, share, or delete one without touching others.

## Tests

```bash
pytest tests/
```

45 unit tests cover data models, validation, storage, and CLI. Audio + transcription logic requires real mic + downloaded model — test those manually on your Mac (see below).

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
