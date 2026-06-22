# Design: `consolidate` command + CSV log

**Date:** 2026-06-22
**Status:** Draft

## Summary

A new `consolidate` command that reads the enhanced summary (output of `enhance`), runs a lightweight LLM extraction for structured fields (action items, blockers, etc.), and maintains a per-pod CSV rollup.

## CLI interface

```
podscribe consolidate <pod> [meeting] [--no-log]
```

- `meeting` — optional meeting ID prefix, defaults to `latest`
- `--no-log` / `-n` — skip CSV logic entirely (for testing / quick one-off)
- Alias: `podscribe cons <pod>` via `rewrite_argv`

## What it does

1. **Check enhanced summary exists** — looks for `summaries/<meeting-id>.md`
   - If missing → `"No enhanced summary for <id>. Run enhance first? [y/N]"`
   - On `y`/`yes` → run `enhance` inline, then proceed
   - On anything else → exit with error
2. **Load enhanced summary** — reads the enhanced `.md` summary for the specified meeting
3. **Call Ollama** — sends a lightweight prompt (from config) that extracts structured fields from the enhanced summary
4. **CSV log** — unless `--no-log`:
   - Check `pods/<name>/meetings.csv` for existing `meeting_id`
   - If found → `"Log entry exists for <id>. Rewrite? [y/N]"`, rewrite on confirm
   - If not found → append new row

## Flow

```
record  →  raw transcript (transcripts/<id>.md)
enhance →  enhanced summary (summaries/<id>.md)
consolidate → reads enhanced summary, extracts structured fields, updates CSV
```

## Prompt management

Prompt lives in `podscribe.yaml` under the `consolidate` key:

```yaml
consolidate:
  prompt: |
    You are a meeting note-taking assistant...
```

- Code has a built-in default constant as fallback (so `consolidate` works without config)
- New subcommands: `podscribe config consolidate show` and `podscribe config consolidate set <prompt>`

## LLM extraction output

`consolidate` calls Ollama with a lightweight prompt asking it to extract structured fields from the enhanced summary. The LLM returns YAML:

```yaml
quick_summary: "One-sentence summary"
key_topics:
  - Topic A
  - Topic B
action_items:
  - "Action 1"
  - "Action 2"
blockers:
  - "Blocker 1"
next_steps:
  - "Next step 1"
```

## CSV schema

**File:** `pods/<name>/meetings.csv`

| Column | Content |
|---|---|
| `date` | Meeting date (YYYY-MM-DD) |
| `person` | Pod display name |
| `meeting_id` | Unique meeting ID (de-dup key) |
| `quick_summary` | 1-sentence summary |
| `key_topics` | Pipe-delimited list |
| `action_items` | Pipe-delimited list |
| `blockers` | Pipe-delimited list |
| `next_steps` | Pipe-delimited list |
| `summary_file` | Relative path to enhanced summary file (from `enhance`) |
| `transcript_file` | Relative path to raw transcript (from `record`) |

## Files to create/modify

| File | Change |
|---|---|
| `podscribe/cli.py` | Add `cmd_consolidate()`, parser entry, `cons` alias in `rewrite_argv`, `config consolidate` subparser |
| `podscribe/llm.py` | Add `CONSOLIDATE_PROMPT_DEFAULT` constant, `build_consolidate_prompt()`, `extract_structured_fields()` |
| `podscribe/storage.py` | Add `log_path()`, `log_entry_exists()`, `append_log_row()`, `rewrite_log_row()` |
| `podscribe/config.py` | Add `load_consolidate_prompt()`, `save_consolidate_prompt()` |
| `podscribe.yaml` | Optional: may get `consolidate.prompt` on first run |
| `tests/test_cli.py` | Test `cmd_consolidate` with/without `--no-log`, rewrite prompt, alias |
| `tests/test_storage.py` | Test CSV log operations |
| `tests/test_llm.py` | Test prompt building and output parsing |

## De-dup logic

- De-dup key: `meeting_id` column
- If meeting ID exists in CSV → prompt user "Log exists for <id>. Rewrite? [y/N]"
- On `y`/`yes` → overwrite row in place (read CSV, replace matching row, write back)
- On anything else → skip, print "Skipping log update."
- Multiple meetings on same day → different `meeting_id`s → separate rows
