# Podscribe — Recommended Fixes

**Scope:** Full read of all source + docs + test suite + real E2E runs against
Ollama `qwen3.6:27b` and `gemma4:latest`. Findings ordered by severity.

---

## Applied (branches `fix/recommended-cleanup`, integration PR)

The following findings from the original audit were resolved. Kept here for
history; see `docs/superpowers/specs/2026-06-22-recommended-cleanup-design.md`
for the design and `docs/superpowers/plans/2026-06-22-recommended-cleanup.md`
for the implementation plan.

| # | Finding | Resolution | Commit |
|---|---|---|---|
| 1.1 | `--keep-audio` never wrote audio to disk | `cmd_record` now opens a `wave.Wave_write` handle and appends int16 PCM per segment; resilient to `wave.open` failure | `0f1cbdf` |
| 1.2 | Meeting IDs collided at minute precision | `make_meeting_id` now uses `YYYY-MM-DD-HHMMSS-<pod>` (seconds) | `c134100` |
| 1.3 | LLM stripped names from enhanced output | `preserve_speakers` toggle (default `true`) prepends `SPEAKER_PRESERVATION_PREAMBLE`; resolution order pod > project > default; non-bool values raise | `6fb25ba` |
| 1.4 | `cmd_enhance` print said "Saving transcript" | Now says "Enhanced summary will be saved to" | `4d4dd72` |
| 2.1 | Ambiguous meeting prefix silently picked newest | New `_resolve_meeting` helper lists candidates and returns 1 when ≥2 match; used by `cmd_show`, `cmd_enhance`, `cmd_consolidate` | `3b37b65` |
| 2.2 | Empty transcript wasted a 20-30s LLM call | `cmd_enhance` returns 1 with `Transcript too short to enhance (<N> chars).` when stripped length < 50 | `35f32b8` |
| 2.3 | `consolidate` re-enhanced on missing summary | Now errors out with exact `podscribe enhance <pod> <meeting-id>` command to run | `d0b5fe7` |
| 2.4 | `--latest`/`-l` flag on `enhance` was dead code | Removed from the enhance subparser | `60c2d08` |
| 2.5 | Glossary dedup was case- and whitespace-sensitive | `add_entry`/`remove_entry` dedup case-insensitively; first-seen casing preserved | `3749392` |
| 2.7 | Smoke test used `base.en` (not in `MODEL_MAP`) | Changed to `base` | `1f47725` |
| 3.2 | No progress feedback during LLM call | Addressed by §3.3 streaming (one `tqdm` bar per token, final metrics to stderr) | `3c5368d` |
| 3.3 | No retry on transient Ollama failures | `enhance_transcript` retries up to 3× (1/2/4s) on connection errors and 5xx; 4xx fails immediately; 30-min timeout | `3c5368d` |
| 3.6 | README was stale | README updated: `mlx-whisper`, storage layout, model table, `consolidate`, `preserve_speakers`, test count | `25e3212`, `2c1a032` |

Additional implementation bugs found during code review of the cleanup branch
itself (fixed with regression tests):

| Bug | Fix |
|---|---|
| `tqdm` progress bar was not closed if `iter_lines()` raised mid-stream | Wrapped streaming loop in `try/finally` |
| `enhance_transcript(max_retries=N)` with `N > 4` raised `IndexError` on `delays[attempt]` | Clamped to `delays[min(attempt, len(delays) - 1)]` |
| `wave.open` was outside the `try/finally` in `cmd_record`; on failure the meeting was left without metadata | Wrapped setup in `try/except OSError`; recording continues without audio on failure |
| Empty-transcript guard printed the raw length, not the stripped length | Use `stripped_len` in both the check and the message |

---

## Outstanding — deferred or rejected

### 2.6 `append_log_row` is not thread-safe.

4 threads × 20 writes → all 80 rows survived in test, but the window is small and
there's no `fcntl.flock` or atomic rename. In CI / multi-process contexts (running
consolidate and record concurrently), you can lose rows or corrupt the CSV. **Fix:**
wrap writes with `fcntl.flock(f, fcntl.LOCK_EX)` (POSIX) / `msvcrt` (Windows) or use a
write-temp-and-rename pattern like `update_log_row` already does.

Status: deferred. User confirmed current usage is sequential, theoretical only.

---

## 3. UX/PERFORMANCE — what will hurt adoption

### 3.1 27B model is 3 minutes per short transcript.

Real measurement on `qwen3.6:27b` for a 12-line 1:1 (~850-char prompt):

```
elapsed: 179.7s
```

A 30-minute real meeting would be ~3-5× the prompt length, putting you at **10-25 minutes
per enhance**. With 12 reports meeting weekly, that's 2-5 hours of GPU time. For a
5pm-after-the-1:1 workflow, this is a non-starter.

**Fix options (in order of effort):**
- **Default to gemma4 (8B) for enhance.** It's 13s for the same prompt, ~14× faster, and
  the action item quality is good enough for a 1:1. Keep 27B available via
  `podscribe config llm set --quality <model>`.
- **Stream tokens.** ✅ Addressed in §3.3 — call now streams; UX win realized even though
  total time is unchanged.
- **Chunk long transcripts.** Split on `[HH:MM:SS]` boundaries and enhance N lines at a
  time, concatenating results. Map-reduce.
- **Background-job mode.** `podscribe enhance --async <pod> <meeting>` returns
  immediately, writes result when done. Poll with `podscribe jobs`.

Status: 27B remains the default per user decision ("gemma4 is garbage, Qwen is worth the
wait"). Revisit if the wait becomes blocking in practice.

### 3.4 Glossary `initial_prompt` is rebuilt every segment but never used as continuity fork.

`cli.py:107-109` builds the glossary prompt once, but each segment is transcribed
independently. The previous segment's text is never passed to the next, so fragmented
sentences get re-decoded. AGENTS.md roadmap acknowledges this.

**Fix:** keep a rolling `last_n_text` (last 2 segments, ~30 tokens) and pass it as a
second `initial_prompt` suffix: `f"{glossary_prompt}\n\n{last_n_text}"`. Cheap, high-impact.

Status: deferred.

### 3.5 VAD force-splits at 10s can cut words mid-sentence.

`audio.py:111` — `MAX_SEGMENT_SEC = 10.0` triggers a hard yield with no soft boundary
check. If a speaker's breath falls on the 10s mark, the next segment starts mid-word.
**Fix:** when `MAX_SEGMENT_SEC` triggers, wait one more frame: if it's silence, yield
cleanly; if it's speech, extend the segment to 12s and then yield. Small cost, much
better transcripts.

Status: deferred.

### 3.7 `.env` HF_TOKEN is invalid and not needed.

`.env` has `HF_TOKEN=hf_REDACTED` — returns 401 from HF.
Also: `mlx-whisper` only needs auth for private/gated repos, and the default model
`mlx-community/whisper-large-v3-turbo` is public. The token does nothing useful.
**Recommendation:** delete `.env` (it's already in `.gitignore`) and `unset HF_TOKEN` in
any env. If a gated model is ever used, document the env var in README.

Status: deferred (cosmetic).

---

## 4. ARCHITECTURE — what will hurt as the project grows

### 4.1 `cmd_enhance` and `cmd_consolidate` share 40+ lines of LLM-promotion code.

`cli.py:268-296` and `cli.py:355-393` have nearly identical LLM-call + path-resolution
blocks. **Fix:** extract `_run_enhance(pod, meeting, llm_config) -> Path` and reuse.

### 4.2 Storage layer doesn't have a single "all pods" view.

`cmd_list` (`cli.py:137`) iterates `pods/*` but produces a flat per-pod listing. With 12
reports, scrolling for "what did Sam and Priya talk about this week" requires two
commands. **Fix:** add `podscribe list --since 7d` and `podscribe list --all --recent N`
filters. Backend can scan `pods/*/meetings.csv` (one row per meeting) instead of globbing
every JSON sidecar.

### 4.3 No global `meetings.csv`.

`storage.py:23` puts `meetings.csv` inside each pod. So a team-lead's rollup ("all 12
pods, this week") means reading 12 files. **Fix:** write a parallel
`pods/meetings.csv` (or `~/.podscribe/global.csv`) on every `append_log_row`. Single
source for the "team digest" command.

### 4.4 Glossary is rebuilt from disk on every record/enhance.

`get_effective_glossary` (`config.py:106`) re-reads `leadership_team.yaml` on every call.
Cheap today, but it's a per-segment hit in the record path. **Fix:** cache on the `Pod`
object, invalidate on `save_pod_config` or when `leadership_team.yaml` mtime changes.

### 4.5 Meeting "type" is implicit.

The model assumes one meeting type per pod, but a team lead has 1:1s, retros,
skip-levels, design reviews — all written into the same `sam-chen` pod. The transcripts
look identical; you can't filter "show me only 1:1s" later. **Fix:** add `--type 1on1` to
`record` that goes into a `transcripts/22-JUN-2026/1on1/<id>.md` subdir. Small data-model
change, big queryability win.

### 4.6 No search.

Roadmap #4 (Phase 4) lists semantic search. The pre-requisite is even basic keyword
search: `podscribe search "Project Helios"` should grep across all `.md` files in 10ms.
**Fix:** add a `podscribe search <query>` command that uses `rg` if installed, falls back
to Python `Path.rglob`. 20 lines of code, immediate value.

### 4.7 No backup/export.

For 12 pods of sensitive people-data on a single laptop, there's no `podscribe export`
to make a tarball, and no `podscribe import` to restore. **Fix:** `podscribe export
--out pods-2026-06-22.tar.gz` (just `tar` the `pods/` + `leadership_team.yaml` +
`podscribe.yaml`).

---

## 5. Team-lead POV — managing 4 teams of 2-3 people (10-12 reports)

This is where the product is thin. Today a team lead using podscribe gets 12 isolated
silos. They cannot answer any of the questions a real manager asks weekly:

| Need | Today | Suggested command |
|---|---|---|
| "Prep for Sam's 1:1 tomorrow" | Manual scroll | `podscribe prep sam-chen` — pulls last meeting + open action items + relevant recent transcripts from other pods that mention Sam's projects |
| "All my blockers this week" | Read 12 `meetings.csv` files | `podscribe blockers --since 7d` |
| "How am I spending time?" | No data | `podscribe stats` — total hours per pod, per week, by category |
| "What did we say about Project Helios across teams?" | Impossible without `rg` | `podscribe search "Project Helios" --all` |
| "Quick weekly digest for my skip-level" | Compose by hand | `podscribe digest --week 25` — one markdown, all 12 pods |
| "Sam is rolling off, hand his pod to Alex" | No migration path | `podscribe transfer sam-chen alex-tan` — moves data + ownership |
| "Which meetings slipped the agenda this week?" | Manual scan | `podscribe drift --since 7d` — compare agenda (if any) vs transcript topics |

The cheapest two to ship:

1. **`podscribe prep <pod>`** — concatenate `quick_summary` + `blockers` + `next_steps`
   from the last 2 consolidate runs, with auto-injected cross-references: "Note:
   `Project Helios` was also discussed with Priya (2026-06-21)". No LLM call needed.
2. **`podscribe search`** — 20 lines, immediate value.

The most valuable longer-term: a `digest` command that produces a single-page weekly
report from the global `meetings.csv`. That's the "share with skip-level" artifact
managers actually need.

---

## 6. "Better routing" — workflow simplifications

The current flow forces the user to remember 3 commands in sequence:
`record` → `enhance` → `consolidate`. Each is a separate LLM trip and a separate wait.
Better routing:

- **Chain by default.** Add `--consolidate` to `record` so a finished recording
  auto-enhances + auto-consolidates. Total wait = 1 enhance + 1 extract (skip the
  redundant enhance in consolidate after fixing 2.3). For a team lead running 4 1:1s
  back-to-back, this means "record the last one, walk away, come back to 4 completed
  digests".
- **Watch mode.** `podscribe watch sam-chen` (or `record --watch`) prints a live console
  with the running transcript + last 30s of audio energy + detected topic shifts. No LLM,
  no waiting — gives real-time confidence that the recording is healthy.
- **Two-phase enhance.** `enhance --fast` uses gemma4; `enhance --deep` uses 27B.
  Default: fast. User can opt in to deep for "important" meetings.
- **Streaming response.** ✅ Addressed in §3.3.
- **Async jobs.** `enhance --async` returns a job ID; `podscribe jobs` shows status.
  Lets a team lead queue up Monday's 12 1:1s Friday night.

---

## 7. Quick wins remaining (≤ 1 hour each, in priority order)

1. Glossary rolling `last_n_text` continuity (3.4) — drop-in `initial_prompt` suffix.
2. VAD 10s soft boundary (3.5) — one-frame lookahead in `audio.py`.
3. `.env` HF_TOKEN cleanup (3.7) — delete file, `unset HF_TOKEN`.
4. `append_log_row` `fcntl.flock` (2.6) — 4 lines; only matters under concurrency.

(Quick wins 1, 2, 3, 4, 5, 6, 7, 8, 9 from the original list were applied; new numbering
covers only the leftovers.)

---

## 8. What to plan, not patch

- Team-lead workflow commands (prep, digest, search, blockers, stats) — §5.
- Async job system for the 12-report weekly cycle — §6.
- Backups + pod transfer — §4.7.
- Optional `meeting.type` for queryability — §4.5.