# Podscribe roadmap

Ideas for future exploration, split into **priority showcase items** (next up) and **future exploration** (not yet prioritized).

---

## Priority — showcase improvements

Goal: make Podscribe flagship-grade for AI/ML hiring teams. Each item below is sized to be brainstormed + implemented in its own focused session rather than crammed into one. The first two (benchmark, architecture) are being designed now; the rest follow on the roadmap.

### P1. Benchmark table across bundled Whisper models

`benchmark` · in progress

Real, reproducible benchmark comparing `base`, `turbo`, and `large-v3-turbo` on real audio. Metrics: speed (RTF, wall time, tok/s, peak memory) + quality (Word Error Rate vs a small hand-transcribed ground-truth set).

Artifacts:
- `benchmarks/bench_transcribe.py` — harness mirroring `bench_enhance.py` style; streams audio through the real `audio.py` + `transcriber.py` pipeline
- `docs/BENCHMARKS.md` — rendered markdown table linked from README
- `benchmarks/results/*.json` — committed result snapshots
- WER computation against labeled fixtures (see P7)

Decision already made: speed + WER vs a small labeled set (~3-5 short clips, ~30s each, hand-transcribed).

### P2. Architecture diagram

`docs` · in progress

Two diagrams, both Mermaid (renders inline on GitHub, version-controlled):
- **A — high-level pipeline** inline in README.md: mic → VAD → Whisper → store → enhance → consolidate (~7 nodes)
- **B — module-level** in new `docs/ARCHITECTURE.md`: actual files (`audio.py`, `transcriber.py`, `storage.py`, `llm.py`, `agent.py`, `agent_tools.py`, `search.py`, `export.py`, `config.py`, `glossary.py`) with data formats and the god-mode loop

### P3. README polish

`docs`

Tighten the tagline + add a "Why Podscribe" / Highlights section listing privacy-on-device, agentic god-mode, ~208 offline tests, Apple-Silicon-optimized — the 10-second elevator pitch a recruiter scans. Intended to land after P1 + P2 so the benchmark table and architecture diagram can be linked into the refreshed README rather than added twice.

### P4. Demo gif / asciinema

`docs`

Short screen recording (asciinema or gif) of `record → show → enhance → consolidate` embedded in README. The TUI is a visual selling point that prose can't convey. Benefits from P7's fixtures so the demo runs reproducibly without a mic or real meetings.

### P5. Project structure tree in README

`docs`

A trimmed file tree showing the module layout (`podscribe/*.py`, `tests`, `benchmarks`, `docs`) — quick visual orientation for a reviewer opening the repo. Part of the README polish pass (P3) but called out separately so it's not forgotten.

### P6. CI badge + test summary

`docs` · `ci`

Add a GitHub Actions workflow running `pytest -k 'not transcriber'` + lint, with a status badge at the top of README. Hiring teams look for green CI as a maturity signal. Should also surface the test count (208) somewhere scannable.

### P7. Fixture / seed pod dataset

`data` · prerequisite for P1, P4

Ship a tiny `fixtures/` dataset (a few public-domain or synthesized audio clips + expected transcripts) so benchmarks and demos reproduce out-of-the-box without a mic or real meetings. Note: `pods/` is gitignored, so fixtures live elsewhere and must be referenced explicitly by the bench harness.

### P8. Contributing / development docs

`docs`

`CONTRIBUTING.md` codifying setup, test commands, code style notes (much of this already lives in `AGENTS.md` — promote and reframe for human contributors). Signals the repo is set up for collaboration, not just solo use.

---

## Future exploration

Not yet prioritized.

## 1. Glossary improvements

Current glossary injects terms as Whisper `initial_prompt`. This is zero-latency but limited — Whisper may ignore it on short segments.

Ideas to explore:
- hotword/phrase biasing via Whisper detection heuristic
- automatic glossary extraction from past transcripts (extract names/projects mis-transcribed across meetings)
- per-meeting glossary overrides via CLI flags

## 2. VAD tuning & segmentation

Current VAD (webrtcvad, aggressiveness 0-3) is basic. Issues:
- loose VAD (0-1) passes through noise → garbage segments
- strict VAD (3) clips soft-spoken starts
- 5-frame silence threshold is hardcoded

Ideas to explore:
- silence threshold as CLI parameter
- adaptive VAD that learns noise floor per session
- post-VAD merge: rejoin segments that were split by brief pauses (same speaker)
- energy-based pre-filter before VAD

## 3. LLM enhance (Ollama)

Current `enhance` command sends transcript to Ollama for cleanup. It works but is basic:
- single-shot, no streaming
- no progress feedback for long transcripts
- prompt template is hand-edited in config.yaml

Ideas to explore:
- streaming token-by-token display during enhance
- built-in prompt templates (fix-hallucinations, summarize, extract-actions)
- diff view: show original vs enhanced side by side
- auto-run enhance after record completes

## 4. Segment merging & continuity

Current VAD segments speech into 1-3s chunks, each independently transcribed by Whisper. This causes fragmented sentences and filler word bloat (~87% more words than reference).

Ideas to explore:
- increase `MAX_SEGMENT_SEC` from 10s to 30s to yield longer utterances
- lower default `VAD_AGGRESSIVENESS` from 2 to 1 to avoid mid-sentence splits
- pass previous segment text as `initial_prompt` to subsequent segments for continuity
- post-hoc merge: rejoin adjacent segments that form grammatical sentences

## 5. LLM de-fragmentation pass

After recording, run an Ollama pass specifically to merge fragments and fix segmentation artifacts, independent of the existing enhance command.

## 6. Model accuracy tuning

Compare `large-v3-turbo` vs full `large-v3` on the same audio for accuracy-latency trade-off. Consider smaller models (`base.en`) for test/iteration speed.

## 7. Cross-platform / NVIDIA support (not planned — captured for later)

**Status: deferred. Not being implemented.** Captured here so the analysis isn't lost.

Podscribe is *not* truly Apple-Silicon-exclusive — only the ASR layer
([`transcriber.py`](podscribe/transcriber.py)) is, via `mlx-whisper` (Apple MLX/Metal).
Everything else is already portable:

- **Ollama** (`enhance`/`consolidate`/`god`) runs natively on Windows+CUDA — works as-is,
  and *faster* on a 32 GB GPU (the 27B-model latency pain in `Recommended_fixes.md` §3.1
  goes away).
- **Audio + VAD** (`sounddevice`/PortAudio + `webrtcvad`) build and run on Windows.
- **Storage / CLI / TUI / search / export** are pure Python + `pathlib` + `os.replace`.

**The whole port = one pluggable ASR backend.** Refactor `transcriber.py` into a
`TranscriberBackend` protocol with hardware auto-detection:

```
Transcriber (protocol)
├── MLXBackend            # mlx-whisper      — Apple Silicon (existing)
├── FasterWhisperBackend  # CTranslate2/CUDA — NVIDIA
└── CPUBackend            # faster-whisper int8 — universal fallback / CI
```

NVIDIA ASR options (ranked): **faster-whisper (CTranslate2)** — same Whisper families,
INT8/FP16, keeps BENCHMARKS.md apples-to-apples; **HF Transformers + PyTorch/CUDA** —
best bleeding-edge GPU support; **whisperX** — adds diarization (already a roadmap goal,
`.raw` audio is kept for it); **NVIDIA NeMo Parakeet/Canary** — SOTA on NVIDIA, heavier.

⚠️ **RTX 5090 is Blackwell (sm_120) — bleeding edge.** Needs CUDA 12.8+, recent cuDNN,
PyTorch 2.7+/nightly; CTranslate2 may not ship sm_120 wheels yet. **Spike first** to confirm
which engine actually runs on the card before committing. This is the port's only real risk.

Windows edges (all small): `msvcrt.locking` or temp-rename instead of POSIX `fcntl.flock`
(`Recommended_fixes.md` §2.6); `webrtcvad-wheels` or MSVC build tools (or upgrade to
silero-VAD, GPU-based + cross-platform); `colorama`/VT enablement for older consoles.

**Why it's worth capturing:** the port converts a portfolio liability (Apple-only, no
reviewer can run it) into two assets — a broader hiring audience (any NVIDIA box) and a
**cross-accelerator benchmark table** (M-series RTF vs RTX 5090 RTF) that turns the existing
benchmark harness into a strong AI/ML-engineer artifact. See the matching section in
`production_readiness.md`. Effort: ~2–3 focused days of code, gated by the Blackwell spike.
