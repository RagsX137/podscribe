# Podscribe — Recommended Fixes

**Scope:** Historical record of the original audit (full read of all source +
docs + test suite + real E2E runs against Ollama `qwen3.6:27b` and
`gemma4:latest`).

> **Note:** The outstanding items from this audit have been ported to
> [`roadmap.md`](roadmap.md) (Priority section, `F-` prefixed items —
> numeration preserved for traceability). This file now only retains the
> **Applied** history (commit references) for archaeology. See `roadmap.md` for
> active remaining work, ordered by value-for-effort.

---

## Applied (branch `fix/recommended-cleanup`, integration PR)

The following findings from the original audit were resolved. See
`docs/superpowers/specs/2026-06-22-recommended-cleanup-design.md` for the design
and `docs/superpowers/plans/2026-06-22-recommended-cleanup.md` for the
implementation plan.

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

### Also resolved later (tracked in `roadmap.md` completed list)

The audit's architecture items (4.1–4.7), section 3.7 `.env` cleanup, and the
section 5/6/7/8/9 outstanding items have since been either resolved directly
(see `roadmap.md` Completed) or promoted into the active Priority tiers.