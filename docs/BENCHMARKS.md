# Transcription benchmarks

Benchmarks the bundled Whisper models — `base` and `large-v3-turbo` —
end-to-end, fully on-device. Two complementary suites:

1. **Real-meeting** — a single ~22-minute real recording, scored against an
   independent commercial reference (Microsoft Teams' built-in ASR). Measures
   how the models behave on messy, multi-speaker, real-world audio.
2. **Synthetic-fixture** — three short `say`-generated clips with hand-written
   references. Fully deterministic and reproducible on any Apple Silicon Mac,
   with no private data.

`turbo` is an alias for `large-v3-turbo` (see `podscribe/transcriber.py:MODEL_MAP`)
and is omitted from the tables to avoid duplicating its row.

## Real-meeting results (vs. Microsoft Teams ASR)

A ~22-minute, 4-speaker meeting recording (`.mp4`, 16 kHz mono), transcribed by
each model and compared against the meeting's Microsoft Teams `.vtt` transcript
as the reference.

| Model | Params | Mean RTF (↓) | Peak RSS (MB) | Mean WER (↓) | Mean CER (↓) | Mean MER (↓) | Mean WIL (↓) | Mean WIP (↑) |
|---|---|---|---|---|---|---|---|---|
| `base` | ~74 M | 0.006 | 725 | 0.139 | 0.091 | 0.132 | 0.176 | 0.824 |
| `large-v3-turbo` | ~809 M | 0.028 | 2035 | 0.103 | 0.071 | 0.100 | 0.125 | 0.875 |
| `large` | ~1550 M | 0.063 | 2845 | 0.132 | 0.097 | 0.126 | 0.151 | 0.849 |

`large-v3-turbo` is the clear winner: best accuracy (WER 0.103, ~26% below
`base`) *and* ~2.3× faster and ~800 MB lighter than full `large`. Notably the
1.5 B-param `large` is barely better than tiny `base` here (WER 0.132 vs 0.139)
while costing the most time and memory — `large-v3-turbo` is a distilled decoder
of `large-v3` tuned for exactly this, so on real conversational audio it beats
its parent at a fraction of the cost. All three run far faster than realtime
(RTF ≪ 1). On this meeting there is no reason to run `large`.

Generated on 2026-07-02 on an Apple M1 Max with 32 GB RAM. Model cache warm.
1 run per model.

> **What "WER" means here.** The reference is itself a commercial ASR output,
> not a human transcript, so these figures measure *divergence from Microsoft
> Teams' ASR*, not ground-truth accuracy — the reference can mishear too
> (proper nouns especially). Read them as a *relative* model-quality signal.
> The benchmark also runs **without VAD** (by design — it isolates model
> quality), so the models hallucinate somewhat on silent stretches, which
> inflates error versus a VAD-gated live session.

The recording, decoded audio, and reference transcript are private and live
under a gitignored path (`pods/…/benchmark_data/`); only the aggregate metrics
above are committed. To reproduce with your own media + reference, see
[Adding a real-meeting clip](#adding-a-real-meeting-clip).

## Synthetic-fixture results

| Model | Params | Mean RTF (↓) | Peak RSS (MB) | Mean WER (↓) | Mean CER (↓) | Mean MER (↓) | Mean WIL (↓) | Mean WIP (↑) |
|---|---|---|---|---|---|---|---|---|
| `base` | ~74 M | 0.009 | 480 | 0.132 | 0.100 | 0.131 | 0.199 | 0.801 |
| `large-v3-turbo` | ~809 M | 0.047 | 1783 | 0.098 | 0.096 | 0.098 | 0.142 | 0.858 |

Generated on 2026-06-30 on an Apple M1 Max with 32 GB RAM. Model cache warm
(`~/.cache/huggingface/`).

### Per-clip breakdown

#### RTF (lower is faster than realtime)

| Clip | `base` | `large-v3-turbo` |
|---|---|---|
| short-clear | 0.010 | 0.053 |
| short-names | 0.009 | 0.043 |
| short-numbers | 0.009 | 0.045 |

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

### Adding a real-meeting clip

One command. Requires `ffmpeg` (`brew install ffmpeg`).

1. Drop **one** media file (`.mp4`, `.mov`, `.wav`, ...) and **one** `.vtt`
   reference transcript into a folder under any pod's `benchmark_data/`, e.g.
   `pods/fso/benchmark_data/`. (Anything under `pods/` is gitignored, so private
   recordings stay out of git.)
2. Run:

```bash
python benchmarks/bench_meeting.py pods/fso/benchmark_data
python benchmarks/bench_meeting.py pods/fso/benchmark_data --models base,large-v3-turbo
python benchmarks/bench_meeting.py pods/fso/benchmark_data --runs 3 --name standup
```

`bench_meeting.py` auto-discovers the media + `.vtt`, decodes the audio to 16kHz
mono float32, strips the `.vtt` down to plain reference text (cue ids,
timestamps, and `<v Name>` speaker tags removed), writes an `asr/` manifest, and
reuses `bench_transcribe`'s runner to score every model. With no `--models` it
runs **all available models** (derived from `transcriber.MODEL_MAP`, aliases
deduped). Aggregate metrics print as a table; a `bench-meeting-*.json` snapshot
(with transcript text) is written next to the media — inside the gitignored pod,
so it never lands in git.

### Robustness / adding more real clips

The suite scales to more real recordings today: drop another `(media, .vtt)`
pair into its own `benchmark_data/` folder and run `bench_meeting.py`. The
manifest is list-based, `--asr-dir` isolates each run, and subprocess-per-model
keeps RSS honest. Remaining sharp edge:

- **`.vtt` cleanup does not normalize numbers/dates**, so WER is inflated
  whenever the reference and Whisper disagree on `42` vs `forty-two` (see the
  digit-form caveat below). This affects both models roughly equally.

Note: plain `bench_transcribe.py --regen` writes transcript text to
`benchmarks/results/` (now gitignored) — `bench_meeting.py` sidesteps this by
writing its snapshot into the gitignored pod folder instead.

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
