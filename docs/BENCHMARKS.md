# Transcription benchmarks

Benchmarks the bundled Whisper models — `base` and `large-v3-turbo` —
end-to-end on real audio, fully on-device. Reproducible on any Apple Silicon Mac.

`turbo` is an alias for `large-v3-turbo` (see `podscribe/transcriber.py:MODEL_MAP`)
and is omitted from the table to avoid duplicating its row.

## Results

| Model | Params | Mean RTF (↓) | Peak RSS (MB) | Mean WER (↓) | Mean CER (↓) | Mean MER (↓) | Mean WIL (↓) | Mean WIP (↑) |
|---|---|---|---|---|---|---|---|---|
| `base` | ~74 M | 0.010 | 490992 | 0.132 | 0.100 | 0.131 | 0.199 | 0.801 |
| `large-v3-turbo` | ~809 M | 0.048 | 1824400 | 0.098 | 0.096 | 0.098 | 0.142 | 0.858 |

Generated on 2026-06-30 on an Apple M1 Max with 32 GB RAM. Model cache warm
(`~/.cache/huggingface/`).

### Per-clip breakdown

#### RTF (lower is faster than realtime)

| Clip | `base` | `large-v3-turbo` |
|---|---|---|
| short-clear | 0.011 | 0.055 |
| short-names | 0.010 | 0.044 |
| short-numbers | 0.009 | 0.046 |

#### WER (word error rate)

| Clip | `base` | `large-v3-turbo` |
|---|---|---|
| short-clear | 0.056 | 0.000 |
| short-names | 0.044 | 0.000 |
| short-numbers | 0.295 | 0.295 |

#### CER (character error rate)

| Clip | `base` | `large-v3-turbo` |
|---|---|---|
| short-clear | 0.016 | 0.000 |
| short-names | 0.004 | 0.000 |
| short-numbers | 0.281 | 0.288 |

#### MER (match error rate)

| Clip | `base` | `large-v3-turbo` |
|---|---|---|
| short-clear | 0.056 | 0.000 |
| short-names | 0.043 | 0.000 |
| short-numbers | 0.295 | 0.295 |

#### WIL (word information lost)

| Clip | `base` | `large-v3-turbo` |
|---|---|---|
| short-clear | 0.108 | 0.000 |
| short-names | 0.065 | 0.000 |
| short-numbers | 0.425 | 0.425 |

#### WIP (word information preserved)

| Clip | `base` | `large-v3-turbo` |
|---|---|---|
| short-clear | 0.892 | 1.000 |
| short-names | 0.935 | 1.000 |
| short-numbers | 0.575 | 0.575 |

## How to reproduce

```bash
python benchmarks/bench_transcribe.py --regen
python benchmarks/bench_transcribe.py --models base,large-v3-turbo --runs 3
python benchmarks/bench_transcribe.py --list-clips
```

Fixtures live in `fixtures/asr/` (see `manifest.yaml`). Each clip is a 16kHz mono
float32 `.f32` file paired with a hand-transcribed `.txt` reference.

## Methodology

- **Audio format:** 16kHz mono float32 — identical to what `podscribe.audio`
  captures, so the bench measures the models, not data-shape plumbing.
- **Transcription:** runs through `podscribe.transcriber.Transcriber.transcribe()`
  directly. No VAD — this benchmark isolates model quality; VAD segmentation
  impact is roadmap "Future exploration §2".
- **Subprocess isolation:** each model runs in its own Python process
  (`python -m benchmarks.bench_transcribe --child ...`). Peak RSS is reported
  per model with no cache bleed between runs.
- **Quality metrics:** computed with `jiwer` — WER, CER, MER, WIL, WIP —
  after a standard normalization pipeline (`ToLowerCase`, `RemovePunctuation`,
  `RemoveWhiteSpace`, `RemoveMultipleSpaces`, `Strip`) applied identically to
  hypothesis and reference. WIP is the only "higher is better" metric; the
  rest are error rates (lower is better).
- **Speed metrics:** `wall_s` is `time.perf_counter()` around the transcribe
  call; `rtf` is `wall_s / duration_s` (lower = faster than realtime).
- **Fixtures:** synthesized via macOS `say` (deterministic, no mic required).
  Three clips exercise different content profiles: pangrams (`short-clear`),
  proper nouns and tech jargon (`short-names`), numbers and dates
  (`short-numbers`).

## Known caveats

- **`short-numbers` WER is artificially high** (~0.29 for both models) because
  the reference transcript uses word form (`forty-two`, `twenty twenty-six`)
  while Whisper outputs digit form (`42`, `2026`). jiwer's default normalization
  treats these as different words. The other two clips show the expected gap
  (`large-v3-turbo` reaches WER = 0.0 on `short-clear` and `short-names`).
- **`peak_rss_mb` column is in KB on macOS**, not MB — a known unit-label bug
  in the harness. Real values: `base` ≈ 480 MB, `large-v3-turbo` ≈ 1.78 GB.
  Follow-up will fix the conversion.

## Metric glossary

| Metric | Stands for | Direction | What it captures |
|---|---|---|---|
| RTF | Real-Time Factor | ↓ | wall time ÷ audio duration |
| WER | Word Error Rate | ↓ | word-level edit distance / reference words |
| CER | Character Error Rate | ↓ | character-level edit distance / reference chars |
| MER | Match Error Rate | ↓ | fraction of word-substitutions/deletions/insertions |
| WIL | Word Information Lost | ↓ | information-theoretic error rate |
| WIP | Word Information Preserved | ↑ | 1 - WIL |
| Peak RSS | peak resident memory | ↓ | per-process peak (subprocess isolation) |
