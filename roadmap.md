# Podscribe roadmap

Split into **priority — active remaining items** (next up, ordered by value-for-effort) and **future exploration** (not yet prioritized).

---

## Priority — active remaining items

Ordered by value-for-effort (highest first). `P-` items are the original showcase
work; `F-` items are ported from `Recommended_fixes.md` (numeration preserved for
traceability), and `R-` items are fixes added after a codebase review (rejected
review claims are noted in the watchlist so they aren't re-flagged). Completed
items are listed at the bottom for reference.

### Tier 1 — Quick wins (high value · low effort)

- **F-3.4 Glossary rolling continuity** — keep the last ~2 segments (~30 tokens)
  and pass as an `initial_prompt` suffix alongside the glossary. Decodes
  fragmented sentences correctly; ~1 hr. (Promoted from Future #4.)
- **F-3.5 VAD 10s soft boundary** — when `MAX_SEGMENT_SEC` triggers, look one
  frame ahead: silence → yield cleanly, speech → extend to 12s then yield. Stops
  mid-word splits; ~1 hr. (Promoted from Future #2.)
- **R-1 Validate `--device` in `AudioCapture.__init__`** (`audio.py:35-51`) —
  probe the device index up front and raise a clear error ("no input device at
  index N; run `podscribe list-devices`") instead of letting
  `sd.InputStream.start()` surface a raw PortAudio traceback. Cheap, removes the
  single most likely first-run failure mode. ~30 min.
- **R-2 Handle `sounddevice.PortAudioError`** around the capture start in
  `AudioCapture.segments()` (`audio.py:83-91`) and around `cmd_record`'s WAV open
  (`cli.py:256-263`). Translate mic-permission / device-busy into a one-line
  stderr message; crash-silently today. ~30 min.
- **R-3 `--include-audio` flag for `export`** (`export.py:12,16-34`) — `.raw`
  files are excluded by default (correct for most backups), but there's no way to
  bundle the diarization source for migration. Add the inverse flag (default off)
  that drops `.raw` from `_EXCLUDED_SUFFIXES` for that run. ~45 min.
- **R-4 `--version`** flag on the top-level parser (`cli.py:798`) — currently
  missing; trivial `action="version"`. ~10 min.
- **R-5 Move `numpy` imports to function scope** (`cli.py:13`, `audio.py:15`) —
  both modules import numpy at top level, slowing `podscribe --help` / `list` /
  `init` (paths that never touch audio). `sounddevice`/`webrtcvad`/`mlx_whisper`
  are already lazy; finish the sweep. ~30 min, mostly mechanical.

### Tier 2 — Core workflow transformations (high value · medium effort)

- **F-6a Chain by default** — `record --consolidate` auto-runs enhance +
  consolidate when recording finishes. Turns "record 4 back-to-back 1:1s, walk
  away, come back to 4 completed digests" from a 12-command ritual into one. The
  biggest workflow win for the core 12-reports-weekly use case.
- **F-5a `podscribe prep <pod>`** — concatenate `quick_summary` + `blockers` +
  `next_steps` from the last 2 consolidate runs, with auto-injected
  cross-references ("Project Helios was also discussed with Priya on
  2026-06-21"). Eliminates the 20-minute pre-1:1 re-read. No LLM call needed.
- **R-6 Rogue-thread cleanup in `stop_recording`** (`agent_tools.py:239-257`) —
  `thread.join(timeout=10)` returns with the thread still alive, the session is
  set to `None`, and the recorder keeps writing silently (orphaned capture
  stream + open `.raw`). On timeout: re-call `capture.stop()`, leave `_recording_session`
  in a `draining` state until the thread actually exits, and surface a "stopping
  lingering recorder" warning. The error path today leaks an audio stream.
  Medium effort — touches the module-global state and needs the god REPL to
  poll for completion. ~half-day.
- **R-7 VAD silence threshold as a CLI flag** (`audio.py:125`) — the
  hardcoded `5` (150 ms) is baked in. Expose `--vad-silence-frames` on
  `record`/god `start_recording`, matching the existing `--vad-aggressiveness`
  pattern. Pairs with the broader VAD-tuning agenda in Future #2; do this one
  first since it's the only knob a lead can *use today* for a noisy room.
  ~1 hr.

### Tier 3 — The manager's real job (high value · medium-high effort)

- **F-5b Agenda generator + open-loops tracker** — mine past meetings for open
  loops and recurring themes, draft the next 1:1 agenda automatically. "The
  biggest gap right now." Open-loops: extract action items assigned to the lead
  across all pods and surface anything never followed up — broken promises
  erode trust faster than anything.
- **F-5c `podscribe digest --week N`** — a single-page markdown digest of all
  pods for one week. The "share with skip-level" artifact managers actually need.
- **F-5d Performance review draft generator** — synthesise ~6 months of
  enhanced summaries into a structured review draft. "Most painful, most
  time-consuming manager task that Podscribe's data is uniquely positioned to
  solve." Highest leverage, highest effort in this tier.
- **F-5e Longitudinal insight** — sentiment trend per pod (3-week decline =
  attrition warning nobody else can give from raw conversation data); topic
  recurrence map ("on-call load in 9 of last 12 meetings"); cross-pod theme
  detection (same topic across 4 of 5 reports same week = escalate). The real
  differentiator.

### Tier 4 — Showcase & collaboration

- **P4. Demo gif / asciinema** — short recording of `record → show → enhance →
  consolidate` embedded in README. The TUI is a visual selling point prose can't
  convey; benefits from the fixtures dataset so the demo runs without a mic.
- **P8. Contributing / development docs** — `CONTRIBUTING.md` codifying setup,
  test commands, code style (much already in `AGENTS.md` — promote and reframe
  for human contributors). Signals the repo is open to collaboration.
- **P6. CI badge + test summary** — GitHub Actions workflow running
  `pytest -k 'not transcriber'` + ruff, with a status badge at the top of
  README. Hiring teams read green CI as a maturity signal. Note:
  `mlx-whisper` is Apple-Silicon-only and `webrtcvad` needs PortAudio on Linux,
  so the CI install step needs a test-only extras group or mocked heavy deps.

### Tier 5 — Quality-of-life & scale

- **F-6 Watch mode** — `record --watch` (or `podscribe watch <pod>`) prints a
  live console: running transcript + last 30s of audio energy + detected topic
  shifts. No LLM, no waiting — real-time confidence the recording is healthy.
- **F-6b Two-phase enhance** — `enhance --fast` (gemma4 8B, 13s) vs `enhance
  --deep` (27B). Default: fast. Opt into deep for "important" meetings.
- **F-6c Async jobs** — `enhance --async` returns a job ID; `podscribe jobs`
  shows status. Lets a lead queue Monday's 12 1:1s Friday night.
- **F-9 TUI pause / resume / markers** — during `record`: `p` pause/resume,
  `m` insert timestamped marker, `a` abort-without-save. Medium-high risk
  (threading + signals + audio hardware); current Ctrl+C-to-stop works and is
  well-tested, so worth doing but not bundled with other TUI work.
- **R-8 TTL cache for `ollama_model_info`** (`llm.py`) — called on every
  `enhance`/`consolidate`/`god` invocation; the `/api/show` round-trip is ~50–150
  ms. 5-min `lru_cache`-style TTL (model metadata rarely changes). Low value
  but trivially safe. ~20 min.
- **R-9 Threaded WAV writer** in `run_record_session` (`cli.py:160-164`) —
  `wav_writer.writeframes(pcm.tobytes())` runs inline with the transcribe loop and
  blocks Whisper on slow disks. Move to a bounded-queue pusher thread (same
  shape as the audio-capture callback); join on finalize. Net win on the long
  meetings where buffer-overflow warnings (R-2's domain) currently show up.
  ~half-day.
- **R-10 `mlx_whisper.transcribe` timeout** (`transcriber.py:61`) — no abort; a
  pathological segment can hang the recorder silently. mlx-whisper exposes no
  cancellation API, so a real fix needs either a subprocess isolate or a
  watchdog that tears down `AudioCapture` on a stalled transcribe. Deferred
  until a real hang is observed; document the absence here so a future reviewer
  doesn't read it as overlooked.

### Tier 6 — Watchlist (deferred decisions)

- **F-2.6 `append_log_row` thread-safety** — no `fcntl.flock` / atomic rename;
  concurrent `consolidate` + `record` could lose or corrupt CSV rows. User
  confirmed current usage is sequential — theoretical only. Revisit if
  multi-process workflows land.
- **F-3.1 Enhance perf on 27B model** — `qwen3.6:27b` is ~3 min for a short
  transcript (10-25 min for a 30-min meeting). Deferred per user decision
  ("gemma4 is garbage, Qwen is worth the wait"). Revisit if the wait becomes
  blocking in practice.
- **R-11 Pod-config mtime in glossary cache key** (`config.py:195`) —
  `get_effective_glossary` keys on leadership-team mtime + `id(pod.glossary)` +
  `len(pod.glossary)`. A long-lived process holding a stale `Pod` object won't see
  external edits to `pods/<name>/config.yaml`. In practice each CLI invocation
  reloads `Pod` from disk, so cross-invocation staleness is impossible — the
  only window is `god` REPL sessions where the `Pod` is held live in the
  `_recording_session` dict. Add `pod.config_path.stat().st_mtime` to the key
  when bridging that; cheap, ~15 min. Defer until god REPL is used against
  externally-edited glossaries in the wild.
- **R-12 `rewrite_argv` nested subcommands** (`cli.py:975-993`) —
  `podscribe sam-chen config llm show` rewrites to `config sam-chen llm show`
  and fails argparse. Note: `config` is project-scoped, not pod-scoped, so the
  pod-first syntax structurally doesn't apply — no realistic caller is hit. Not
  worth fixing until a *pod-scoped* nested command needs the same rewrite.
  Document as a known limitation.
- **R-13 Meeting-ID disambiguation suffix** (`models.py:25-28`) — seconds
  only; two same-second recordings would collide. The review flagged this P0
  but the CLI imposes multi-second recording length by construction (Ctrl+C +
  audio write) and `is_recording_active()` guards against sub-second tear-down.
  Cheap insurance anyway: add a `-(%04d)` counter when a path already exists.
  Low priority; contradicts the review's P0 framing.

### Review claims rejected (do not implement — keep here as a paper trail)

- **"had_overflow never reset"** — `audio.py:81` resets `self._overflow = False`
  at the start of every `segments()`; the review cited the reset line as the fix
  location while asserting the reset didn't exist.
- **"Global `pods/meetings.csv` not re-imported"** — `_safe_extract` in
  `export.py:121-163` extracts every member except `podscribe.yaml`; the
  `pods/meetings.csv` file *is* restored. The review confused the
  conflict-detection loop for the extract list.
- **"Search fails for typed meetings (3-level layout)"** — `search.py:61-81`
  parses `stem[:10]` from the filename (always `YYYY-MM-DD…`), and lines 78-80
  fall back to mtime when date parsing fails. The review's own prose conceded
  "`[:10]` works".
- **"Pipeline enhance + consolidate"** — `run_consolidate` (`cli.py:686-693`)
  hard-errors without the enhanced summary file on disk; consolidate is a strict
  downstream stage of enhance, not an independent parallelizable call. Would
  break the documented flow.
- **"Batch CSV writes"** — `append_log_row` is called once per `consolidate`;
  `import` uses file extraction, not the row API. There is nothing to batch.

---

### Completed (for reference; see git history)

- **F-Diarize-v1** `podscribe diarize`: continuous-audio capture + post-hoc pyannote.audio diarization, `.diarized.md` sidecar, `audio_layout` provenance guard, `~/.config/podscribe/hf_token`, generic `Speaker N`, `show`/`enhance` prefer diarized. Forward-only; TUI progress + name-mapping deferred.
- **P1** Benchmark table across bundled Whisper models
- **P2** Architecture diagram (README + `docs/ARCHITECTURE.md`)
- **P3** README polish — tagline + Why Podscribe highlights
- **P5** Project structure tree in README
- **P7** Fixture / seed pod dataset (`fixtures/asr/`)
- **F-4.1** Shared `_run_enhance` helper extracted (cli.py)
- **F-4.2** `list --since` / `--all` / `--recent N` filters
- **F-4.3** Global `pods/meetings.csv` rollup
- **F-4.4** Glossary cached per process (`config.get_effective_glossary`)
- **F-4.5** Meeting `--type` flag + type/ subdirs
- **F-4.6** `podscribe search` (rg-backed, Python fallback)
- **F-4.7** `podscribe export` / `import` (path-traversal safe)
- **F-2.1-2.5, 2.7** Ambiguous-prefix resolution, empty-transcript guard,
  consolidate-needs-enhance check, dead `--latest` flag removed, glossary
  dedup, smoke-test model fix
- **F-1.1-1.4, 3.2, 3.3, 3.6** Audio-keep fix, second-precision meeting IDs,
  `preserve_speakers`, label fix, streaming + retry, README refreshes
- **F-3.7** `.env` HF_TOKEN removed (token was invalid/unused)

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

Current `enhance` command sends transcript to Ollama for cleanup. Streaming and
retry landed (F-3.2/3.3). Remaining ideas:

- built-in prompt templates (fix-hallucinations, summarize, extract-actions)
- diff view: show original vs enhanced side by side
- auto-run enhance after record completes (see F-6a chain by default)

## 4. Segment merging & continuity

Current VAD segments speech into 1-3s chunks, each independently transcribed by Whisper. This causes fragmented sentences and filler word bloat (~87% more words than reference). Rolling `last_n_text` continuity is in Tier 1 (F-3.4). Remaining ideas:

- increase `MAX_SEGMENT_SEC` from 10s to 30s to yield longer utterances
- lower default `VAD_AGGRESSIVENESS` from 2 to 1 to avoid mid-sentence splits
- post-hoc merge: rejoin adjacent segments that form grammatical sentences

## 5. LLM de-fragmentation pass

After recording, run an Ollama pass specifically to merge fragments and fix segmentation artifacts, independent of the existing enhance command.

## 6. Model accuracy tuning

Compare `large-v3-turbo` vs full `large-v3` on the same audio for accuracy-latency trade-off. Consider smaller models (`base.en`) for test/iteration speed.
