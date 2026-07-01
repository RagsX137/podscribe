# Podscribe roadmap

Split into **priority — active remaining items** (next up, ordered by value-for-effort) and **future exploration** (not yet prioritized).

---

## Priority — active remaining items

Ordered by value-for-effort (highest first). `P-` items are the original showcase
work; `F-` items are ported from `Recommended_fixes.md` (numeration preserved for
traceability). Completed items are listed at the bottom for reference.

### Tier 1 — Quick wins (high value · low effort)

- **F-3.4 Glossary rolling continuity** — keep the last ~2 segments (~30 tokens)
  and pass as an `initial_prompt` suffix alongside the glossary. Decodes
  fragmented sentences correctly; ~1 hr. (Promoted from Future #4.)
- **F-3.5 VAD 10s soft boundary** — when `MAX_SEGMENT_SEC` triggers, look one
  frame ahead: silence → yield cleanly, speech → extend to 12s then yield. Stops
  mid-word splits; ~1 hr. (Promoted from Future #2.)

### Tier 2 — Core workflow transformations (high value · medium effort)

- **F-6a Chain by default** — `record --consolidate` auto-runs enhance +
  consolidate when recording finishes. Turns "record 4 back-to-back 1:1s, walk
  away, come back to 4 completed digests" from a 12-command ritual into one. The
  biggest workflow win for the core 12-reports-weekly use case.
- **F-5a `podscribe prep <pod>`** — concatenate `quick_summary` + `blockers` +
  `next_steps` from the last 2 consolidate runs, with auto-injected
  cross-references ("Project Helios was also discussed with Priya on
  2026-06-21"). Eliminates the 20-minute pre-1:1 re-read. No LLM call needed.

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

### Tier 6 — Watchlist (deferred decisions)

- **F-2.6 `append_log_row` thread-safety** — no `fcntl.flock` / atomic rename;
  concurrent `consolidate` + `record` could lose or corrupt CSV rows. User
  confirmed current usage is sequential — theoretical only. Revisit if
  multi-process workflows land.
- **F-3.1 Enhance perf on 27B model** — `qwen3.6:27b` is ~3 min for a short
  transcript (10-25 min for a 30-min meeting). Deferred per user decision
  ("gemma4 is garbage, Qwen is worth the wait"). Revisit if the wait becomes
  blocking in practice.

---

### Completed (for reference; see git history)

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
