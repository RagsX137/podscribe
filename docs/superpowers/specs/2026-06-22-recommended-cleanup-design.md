# Design: Recommended Fixes Cleanup

**Date:** 2026-06-22
**Status:** Draft
**Branch:** `fix/recommended-cleanup` (off `main` after the 3 in-flight fixes land)
**Source review:** `Recommended_fixes.md` (root of repo)
**Scope:** §1 critical bugs + §2 real bugs + §7 quick wins from the review doc.

## Summary

A single PR that ships 12 fixes sourced from the `Recommended_fixes.md` review
audit. Each fix is one commit. No new user-facing commands. No new architecture.
The 27B Qwen model stays the LLM default — the user's verbatim feedback was that
gemma4 is "garbage" and Qwen is worth the wait.

## In-scope fixes

| # | Review § | Fix | Files |
|---|---|---|---|
| 1 | §1.1 | `--keep-audio` actually writes int16 PCM to `.raw` (WAV format) | `cli.py` |
| 2 | §1.2 | Meeting ID: `HHMM` → `HHMMSS` | `podscribe/models.py` |
| 3 | §1.3 | `preserve_speakers` toggle in LLM config | `podscribe/llm.py`, `podscribe/config.py`, `podscribe.yaml` |
| 4 | §1.4 | Fix misleading "Saving transcript" print | `podscribe/cli.py` |
| 5 | §2.1 | Ambiguous meeting prefix → list candidates + return 1 | `podscribe/cli.py` |
| 6 | §2.2 | Empty-transcript guard before LLM call | `podscribe/cli.py` |
| 7 | §2.3 | Consolidate errors out cleanly if summary missing | `podscribe/cli.py` |
| 8 | §2.4 | Remove dead `--latest` / `-l` flag from enhance parser | `podscribe/cli.py` |
| 9 | §2.5 | Case-insensitive glossary dedup (preserve first-seen casing) | `podscribe/glossary.py` |
| 10 | §2.7 | Smoke test: `base.en` → `base` | `tests/test_transcriber.py` |
| 11 | §3.3 | Streaming enhance with `tqdm` progress, retry, metrics | `podscribe/llm.py`, `pyproject.toml`, `requirements.txt` |
| 12 | §3.6 | README: `pywhispercpp`→`mlx-whisper`, 45→125, storage layout, model default | `README.md` |

## Out of scope (deferred)

- §1.3 deeper: auto-deriving manager/report from `pod.display_name` for the
  preamble. (Could come later; toggle is enough for v1.)
- §2.6: CSV thread-safety. Theoretical only; user confirmed usage is sequential.
- §3.1: 27B → 8B default. Rejected by user; Qwen is the desired model.
- §3.2: `tqdm` spinner for the LLM wait — addressed inside §3.3 instead.
- §3.4: rolling `last_n_text` glossary continuity.
- §3.5: VAD 10s soft-boundary.
- §3.7: `.env` HF_TOKEN cleanup. Cosmetic.
- §4: all architecture items.
- §5: new team-lead commands (`prep`, `digest`, `search`, `blockers`, `stats`,
  `transfer`).
- §6: streaming-on-the-network-side / async jobs / `--fast`/`--deep`.

## Pre-requisite: land the 3 in-flight fixes first

The branch is based on `main` AFTER these three commits are merged:

1. Declare `requests` in `pyproject.toml` + `requirements.txt`
2. Fix `cmd_show` empty-arg `AttributeError` (with regression test)
3. Fix `list_meetings` chronological sort across month boundaries (with regression test)

## Architecture & data flow

This is a bug-fix PR; no new architecture. The shape of the system does not
change. The flow that runs today — `record` → `enhance` → `consolidate` — is
unchanged. The fixes make that flow more reliable (no data loss, no silent
overwrites) and more correct (real audio files, no dead flags, no confusing
prints).

## Component changes

### 1. Audio write path (§1.1)

The `cmd_record` function already iterates `capture.segments()`, which yields
contiguous `np.float32` arrays at 16kHz mono. Add a `wave.Wave_write` handle at
the top of the recording session when `--keep-audio` is set, and append each
segment (converted to int16 PCM) inside the loop. Close in `finally`. The
existing `finalize_meeting(keep_audio=...)` already does the right thing once
the file is real.

The `.raw` extension is preserved (existing convention). Tools detect WAV from
the magic bytes regardless.

```python
# pseudo-code, exact placement in cli.py
wav_writer = None
if args.keep_audio:
    wav_writer = wave.open(str(meeting.audio_path), "wb")
    wav_writer.setnchannels(1)
    wav_writer.setsampwidth(2)
    wav_writer.setframerate(16000)

for audio_segment in capture.segments():
    if wav_writer is not None:
        pcm = np.clip(audio_segment * 32767, -32768, 32767).astype(np.int16)
        wav_writer.writeframes(pcm.tobytes())
    # ... existing transcribe logic
```

If the write fails (disk full, permission), catch in a try/except, warn to
stderr, and continue. Recording must not be blocked by a write failure.

### 2. Meeting ID format (§1.2)

One-line change in `make_meeting_id` (`podscribe/models.py`):

```python
return f"{dt.strftime('%Y-%m-%d-%H%M%S')}-{pod_name}"
```

Old HHMM meetings stay as-is on disk. New meetings get HHMMSS. The two formats
never collide (HHMMSS is a strict superset of HHMM at the string level). The
chronological sort in `list_meetings` (just fixed) sorts by `started_at`, not
by ID string, so mixed formats are handled correctly.

### 3. `preserve_speakers` toggle (§1.3)

**Config schema** (in `podscribe.yaml` and optionally `pods/<name>/config.yaml`):

```yaml
llm:
  model: qwen3.6:27b
  prompt_template: |
    ...
  preserve_speakers: true   # new key, default true
```

**Resolution order:** pod-level `llm.preserve_speakers` > project-level
`podscribe.yaml` `llm.preserve_speakers` > default `true`.

**Validation:** the config loader must reject non-boolean values (e.g. a string
"yes" or an int 1) with a clear error. Use `isinstance(value, bool)` after
`yaml.safe_load`; if not a bool, raise a `ConfigError` pointing at the
offending key.

**Behavior** (in `llm.py:build_enhance_prompt`): when `preserve_speakers` is
true, prepend this fixed preamble to the template before the existing glossary
+ transcript substitution:

> Preserve all names exactly as they appear in the transcript. For each
> action item, name the responsible person (e.g. "Sam will review the auth
> middleware design"). If the transcript does not name a person, write
> "Unassigned — needs owner" rather than dropping the item.

The preamble lives as a module-level constant in `llm.py` (e.g.
`SPEAKER_PRESERVATION_PREAMBLE`). Custom prompt templates automatically get the
speaker logic when the toggle is on; no need to edit the template itself.

### 4. Misleading print (§1.4)

`podscribe/cli.py:278-281`. Change the second line from "Saving transcript to"
to "Enhanced summary will be saved to". Trivial.

### 5. Ambiguous prefix (§2.1)

Extract a helper, use it in `cmd_show`, `cmd_enhance`, `cmd_consolidate`:

```python
def _resolve_meeting(meetings, prefix, pod_name) -> tuple[Meeting | None, str | None]:
    if prefix == "latest":
        return meetings[0], None
    matches = [m for m in meetings if m.id.startswith(prefix)]
    if not matches:
        return None, f"No meeting matching '{prefix}' for pod '{pod_name}'."
    if len(matches) > 1:
        listing = "\n".join(f"  • {m.id}" for m in matches)
        return None, f"Multiple meetings match '{prefix}':\n{listing}\nUse a longer prefix."
    return matches[0], None
```

On error, print the second tuple element to stderr, return 1.

### 6. Empty-transcript guard (§2.2)

In `cmd_enhance`, immediately after reading the transcript file:

```python
if len(transcript.strip()) < 50:
    print(f"Transcript too short to enhance ({len(transcript)} chars).", file=sys.stderr)
    return 1
```

### 7. Consolidate errors out cleanly (§2.3)

Replace the existing y/N offer block in `cmd_consolidate` with a hard error:

```python
summary_path = meeting.summary_path
if not summary_path.exists():
    print(
        f"No enhanced summary for {meeting.id}. "
        f"Run `podscribe enhance {pod.name} {meeting.id}` first.",
        file=sys.stderr,
    )
    return 1
```

### 8. Remove dead `--latest` flag (§2.4)

Delete `add_argument("--latest", "-l", ...)` from the enhance and consolidate
subparsers. `args.meeting` already defaults to `"latest"`. The show subparser
was already fixed in the in-flight commit (it was reading `args.latest` which
didn't exist on the show parser).

### 9. Case-insensitive glossary dedup (§2.5)

In `podscribe/glossary.py`:

```python
def add_entry(pod, term, category=""):
    term = term.strip()
    if not term:
        raise ValueError("Term cannot be empty")
    key = term.lower()
    if any(e["term"].lower() == key for e in pod.glossary):
        raise ValueError(f"'{term}' is already in glossary")
    pod.glossary.append({"term": term, "category": category})

def remove_entry(pod, term):
    term = term.strip()
    key = term.lower()
    for i, entry in enumerate(pod.glossary):
        if entry["term"].lower() == key:
            pod.glossary.pop(i)
            return
    raise ValueError(f"'{term}' not found in glossary")
```

First-seen casing is preserved (we only append, never overwrite).

### 10. Smoke test fix (§2.7)

`tests/test_transcriber.py:7`. Change `Transcriber(model="base.en")` to
`Transcriber(model="base")`. One line.

### 11. Streaming enhance with progress + metrics (§3.3)

`podscribe/llm.py:enhance_transcript` changes from `stream: false` to
`stream: true`. New dependency: `tqdm>=4.64` (added to `pyproject.toml` and
`requirements.txt`).

**Public signature change:** `enhance_transcript(model, prompt, *, max_retries=3, show_progress=True)`.
The old `timeout` kwarg is removed (now hardcoded to 1800s, but no longer
overridable — we never want a shorter timeout). Returns `Optional[str]`.
Stats are printed internally to stderr. No caller changes required at the
call-site level (all kwargs are new with defaults).

**Behavior:**

1. If `show_progress=True` (production default), fetch model info from
   `/api/show` (5s timeout, best-effort) to read `num_ctx`.
2. Open streaming request with `timeout=1800` (30 min).
3. Wrap each line in JSON; for each `response` chunk, append to a buffer and
   update a `tqdm` bar (1 update per token).
4. On `done: true`, capture `prompt_eval_count`, `eval_count`,
   `total_duration`, `eval_duration`.
5. Print final metrics to stderr.

**Stderr output format:**

```
Calling Model:qwen3.6:27b...
Context window size : 32768 tokens
qwen3.6:27b:  68%|██████████████████▋       | 412/600 [00:27<00:12, 18.0tok/s]
  ✓ done in 47.2s | prompt 1250 + response 423 tokens @ 17.3 tok/s
```

**Retries:** up to 3 attempts. Backoff 1s, 2s, 4s. Retry on connection
errors and 5xx. Do NOT retry on 4xx (bad prompt, model-not-found).

**Edge cases:**

- `/api/show` fails (offline model card): skip the `num_ctx` line.
- `tqdm` import fails (shouldn't — it's a hard dep): fall back to a simple
  carriage-return spinner.
- Stream yields malformed JSON: skip that line, continue.
- First token never arrives (model hangs): the bar shows 0 tokens, but the
  caller can still see the spinner. The 30-min timeout will eventually fire.

### 12. README updates (§3.6)

Only `README.md`. No new sections, no rewrite. Specific edits:

| Location | Change |
|---|---|
| Model section | `pywhispercpp` → `mlx-whisper`. Note: "Models download automatically from HuggingFace on first use." |
| `--model` flag docs | Default `large-v3-turbo` (was `large-v3`). Add short-name → HF-path table. |
| Tests section | "45 unit tests" → "124 unit tests, all offline". Add note that the smoke test requires `mlx-whisper` + network. |
| Storage layout | Replace flat `pods/<name>/transcripts/YYYY-MM-DD-HHMM-<pod>.md` with the actual two-level layout: `pods/<name>/transcripts/DD-MMM-YYYY/<meeting-id>.md` plus `summaries/` and `meetings.csv`. |
| Commands | Add `consolidate`, `cons` alias, `config consolidate show|set`. |
| LLM section | Mention Ollama requirement, default Qwen 27B, document `preserve_speakers` toggle. |

`KT-HANDOFF.md` is left untouched (per user choice).

## Error handling

| Failure mode | Behavior |
|---|---|
| §1.1 audio write fails | `try/except` around `wav_writer.writeframes`, warn to stderr, continue recording. |
| §1.3 unknown `preserve_speakers` value | `bool(value)` coercion in config loader; raise on non-coercible. |
| §2.1 ambiguous prefix | Print candidates + return 1 (no further action). |
| §2.2 short transcript | Return 1, no LLM call (saves 3-10 min). |
| §2.3 missing summary | Return 1 with exact `enhance` command to run. |
| §3.3 /api/show fails | Skip `num_ctx` line, continue. |
| §3.3 streaming connection drops | Retry 3× with 1/2/4s backoff. Return None after exhaustion (callers handle). |
| §3.3 4xx from Ollama | No retry, return None immediately (caller reports). |
| §3.3 malformed JSON chunk | Skip that line, continue. |
| §3.3 30-min timeout fires | `requests.ReadTimeout`, retry on next attempt. |

## Testing strategy

**New tests (~16):**

| Fix | Test name | Asserts |
|---|---|---|
| §1.1 | `test_cmd_record_writes_wav_with_keep_audio` | File exists; magic bytes = "RIFF" + "WAVE"; byte count matches expected sample count. |
| §1.1 | `test_cmd_record_omits_audio_by_default` | No file created when `--keep-audio` is omitted. |
| §1.2 | `test_meeting_id_format` (update) | Returns `YYYY-MM-DD-HHMMSS-<pod>`. |
| §1.3 | `test_prompt_includes_speaker_preamble_when_enabled` | Preamble string present in built prompt. |
| §1.3 | `test_prompt_omits_preamble_when_disabled` | Preamble string absent. |
| §1.3 | `test_preserve_speakers_default_is_true` | When config key absent, behavior is "enabled". |
| §1.3 | `test_preserve_speakers_resolution_pod_overrides_project` | Pod-level wins. |
| §1.4 | `test_cmd_enhance_prints_summary_path_not_transcript_path` | Stderr contains "Enhanced summary will be saved to". |
| §2.1 | `test_show_with_ambiguous_prefix_lists_candidates_and_returns_1` | Two meetings match → list printed, rc=1. |
| §2.1 | `test_enhance_with_ambiguous_prefix_*` | Same for enhance. |
| §2.1 | `test_consolidate_with_ambiguous_prefix_*` | Same for consolidate. |
| §2.2 | `test_cmd_enhance_rejects_empty_transcript` | rc=1, no LLM call (mock counter). |
| §2.2 | `test_cmd_enhance_rejects_short_transcript` | rc=1, no LLM call. |
| §2.3 | `test_cmd_consolidate_errors_when_summary_missing` | rc=1, stderr contains `podscribe enhance <pod> <meeting>`. |
| §2.4 | `test_enhance_parser_has_no_latest_flag` | argparse fails with `--latest`. |
| §2.5 | `test_add_entry_dedups_case_insensitive` | "Anurag" then "anurag" raises on second. |
| §2.5 | `test_add_entry_preserves_first_seen_casing` | First-seen casing is what gets stored. |
| §2.5 | `test_remove_entry_case_insensitive` | `remove("ANURAG")` removes "Anurag". |
| §3.3 | `test_enhance_streams_and_returns_full_text` | Mock streaming response, assert full text. |
| §3.3 | `test_enhance_retries_on_5xx` | 3 attempts on 5xx, succeeds on 3rd. |
| §3.3 | `test_enhance_no_retry_on_4xx` | 1 attempt on 4xx, returns None. |
| §3.3 | `test_enhance_prints_metrics_to_stderr` | capfd shows the final stats line. |
| §3.3 | `test_enhance_uses_30_minute_timeout` | Assert `requests.post` called with `timeout=1800`. |

**Mock pattern for streaming tests:**

```python
def make_streaming_response(chunks, final_stats=None):
    lines = []
    for c in chunks:
        lines.append(json.dumps({"response": c, "done": False}))
    lines.append(json.dumps({"response": "", "done": True, **(final_stats or {})}))
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.iter_lines = MagicMock(return_value=iter(lines))
    return resp
```

**Test count:** 124 passing → ~146 passing. The `base.en` smoke test gets a
trivial one-line fix; the `meeting_id_format` test is updated in place; net
new ≈ 22 tests.

## Documentation

`README.md` updates per §3.6 table above. `KT-HANDOFF.md` left as-is (user
choice). `AGENTS.md` does not need changes — the in-flight commit already
added the `requests` declaration and cleaned up the gotcha section.

## Sequencing (commit order)

1. README (§3.6) — mechanical, doesn't touch code.
2. Tests + low-risk code: §2.4, §2.7.
3. UX: §1.4, §2.2, §2.3, §2.1.
4. Glossary: §2.5.
5. Config: §1.3, §3.3.
6. ID format: §1.2.
7. Audio: §1.1.

Rationale: low-risk first so each commit is independently testable, biggest
blast-radius last. §1.1 is the largest code change and could regress
recording; doing it last makes bisect easy.

## Rollback

One PR, one revert. If anything regresses, `git revert <merge-sha>` and ship.
No data migrations, no format breaks for existing user data:
- HHMM meeting IDs are preserved on disk.
- Case-insensitive glossary dedup doesn't modify existing entries.
- CSV format unchanged.
- `--keep-audio` previously wrote nothing; now writes a real file — net
  improvement, no data loss.
- The `preserve_speakers` toggle defaults to the same effective behavior as
  the user's preferred outcome (names preserved).

## Open questions

None. All 11 strategic questions answered in the brainstorming session:
- Q1: scope = Bugs + Quick wins
- Q2: land 3 in-flight fixes as-is
- Q3: keep 27B Qwen default
- Q4: HHMMSS seconds suffix
- Q5: write in cmd_record segment loop
- Q6: `preserve_speakers` toggle (default true)
- Q7: consolidate errors out cleanly
- Q8: drop §2.6 (theoretical only)
- Q9: change smoke test to `"base"`
- Q10: just README.md, not KT-HANDOFF
- Q11: one feature branch, one PR
