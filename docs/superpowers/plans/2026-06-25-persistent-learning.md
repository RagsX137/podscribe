# Persistent Learning — Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` or
> `superpowers:subagent-driven-development` to work through this task-by-task.
> Each task has a checkbox. Mark it done before moving to the next.

**Goal:** Add a feedback loop so podscribe gets measurably better after every
`record → enhance → consolidate` cycle. Five layered features, all local-only,
all plain YAML/text, none requiring new runtime dependencies.

**Guiding constraint:** every existing test must stay green after every task.
Run `pytest tests/ -v -k "not transcriber"` before marking any task done.

---

## Background — what signals exist today

After a full cycle, podscribe has produced:

| Signal | Location | Currently used? |
|---|---|---|
| Raw timestamped transcript | `pods/<pod>/transcripts/…/<id>.md` | Once, as enhance input |
| Enhanced summary | `pods/<pod>/summaries/…/<id>.md` | Once, as consolidate input |
| Structured fields | `pods/<pod>/meetings.csv` (`key_topics`, `action_items`, `blockers`, `next_steps`) | Never read back |
| Per-pod glossary | `pods/<pod>/config.yaml` `glossary[]` | Injected into Whisper + enhance prompt |
| Global glossary | `leadership_team.yaml` | Same |
| Preserve-speakers flag | `podscribe.yaml` / pod `config.yaml` | Read at enhance time |

None of these are ever *written back to* after creation. This plan closes every
loop.

---

## Architecture overview — new files

```
pods/<pod>/
├── config.yaml            ← glossary[] gains source/auto_added_at fields
├── memory.yaml            ← NEW: rolling per-pod knowledge base
└── prompt_feedback.yaml   ← NEW: per-meeting LLM output observations

pods/
└── team_patterns.yaml     ← NEW: cross-pod aggregated signals
```

No changes to transcript `.md`, `.json`, `.raw`, `meetings.csv`, or
`summaries/` formats. No new runtime dependencies beyond what is already
installed (`pyyaml`, `requests`).

---

## File map

| File | Change |
|---|---|
| `podscribe/memory.py` | **New module.** All memory read/write logic. |
| `podscribe/patterns.py` | **New module.** Cross-pod aggregation (pure Python, no LLM). |
| `podscribe/config.py` | Add `load_pod_memory`, `save_pod_memory`, `load_team_patterns`, `save_team_patterns`. |
| `podscribe/llm.py` | Add `build_memory_merge_prompt`, `build_glossary_extract_prompt`, `build_feedback_observation`. |
| `podscribe/cli.py` | Extend `run_consolidate` to trigger memory merge + glossary growth + feedback collection. Add `cmd_memory_show`, `cmd_patterns`, `cmd_context_prune`. Wire new subcommands into `build_parser` and `rewrite_argv`. |
| `podscribe/tui.py` | Add `memory show` + `patterns` entries to the Others menu. |
| `podscribe/export.py` | Include `memory.yaml`, `prompt_feedback.yaml`, `team_patterns.yaml` in export bundle. |
| `tests/test_memory.py` | **New.** Unit tests for all memory.py functions. |
| `tests/test_patterns.py` | **New.** Unit tests for all patterns.py functions. |
| `tests/test_cli.py` | Extend with tests for new CLI commands. |
| `AGENTS.md` | Update Models, Commands, Storage layout, Gotchas sections. |

**Unchanged:** `audio.py`, `transcriber.py`, `storage.py`, `models.py`,
`glossary.py`, `search.py`, all on-disk formats.

---

## Feature 1 — Auto-Glossary Growth

**What:** After each `consolidate`, a small second LLM call extracts any new
proper nouns from the enhanced summary that are not already in the effective
glossary. Candidates are appended to `config.yaml` with `source: "auto"` and
`auto_added_at: "<date>"`. Stale auto entries can be pruned with
`podscribe context prune <pod>`.

**Why first:** zero new files, plugs directly into the existing consolidate
flow, immediate benefit to Whisper transcription quality.

### Task 1a — `build_glossary_extract_prompt` in `llm.py`

Add a new function to `podscribe/llm.py`:

```python
def build_glossary_extract_prompt(summary: str, existing_terms: list[str]) -> str:
    """Build a prompt that asks the LLM to extract new proper nouns from a summary.

    existing_terms: list of term strings already in the effective glossary.
    The LLM is instructed to return ONLY valid YAML — a list of
    {term: str, category: str} dicts, or an empty list [].
    """
```

Prompt contract with the LLM:
- Input: enhanced summary text + bullet list of already-known terms
- Output: YAML list `[{term: "X", category: "person|project|team|acronym|other"}]`
  or `[]` if nothing new
- Strict instruction: only proper nouns with clear capitalisation signals;
  never common words; never terms already in the existing list

- [ ] **Step 1: Write the failing test** in `tests/test_llm.py`

  ```python
  def test_build_glossary_extract_prompt_contains_summary():
      from podscribe.llm import build_glossary_extract_prompt
      prompt = build_glossary_extract_prompt("Sam reviewed Argo Rollouts.", ["Sam"])
      assert "Argo Rollouts" in prompt
      assert "Sam" in prompt   # existing terms listed so LLM won't re-add them
      assert "{{" not in prompt  # no unresolved placeholders

  def test_build_glossary_extract_prompt_empty_existing():
      from podscribe.llm import build_glossary_extract_prompt
      prompt = build_glossary_extract_prompt("Project Helios.", [])
      assert "Project Helios" in prompt
  ```

- [ ] **Step 2: Implement** `build_glossary_extract_prompt` in `llm.py`

- [ ] **Step 3: Run tests** — `pytest tests/test_llm.py -v`

### Task 1b — Auto-grow in `run_consolidate`

Extend `run_consolidate` in `podscribe/cli.py`:

After the structured fields are successfully extracted (line ~618), add:

```python
# --- Auto-glossary growth (best-effort: never blocks consolidate) ---
try:
    _auto_grow_glossary(pod, enhanced_text, llm_config["model"])
except Exception:
    pass  # never let this block the main flow
```

Implement `_auto_grow_glossary(pod, enhanced_text, model)` as a private function
in `cli.py`:
1. Build effective glossary term strings
2. Call `build_glossary_extract_prompt`
3. Call `enhance_transcript` (same Ollama call, no streaming needed — use `on_token=lambda t: None`)
4. Parse YAML response with `extract_structured_fields` (already exists)
5. For each candidate: call `glossary.add_entry(pod, term, category)` with `source="auto"`,
   `auto_added_at=today`
6. If any new entries were added: call `save_pod_config(pod)` and print
   `"  + auto-added N glossary term(s): ..."` to stderr

**Important:** `glossary.add_entry` already deduplicates case-insensitively and
raises `ValueError` on duplicates — wrap each add in a try/except to skip
existing terms silently.

**`glossary.py` change:** `add_entry` needs two optional kwargs:
`source: str = ""` and `auto_added_at: str = ""`, stored in the entry dict.

### Task 1c — `context prune` command

New command: `podscribe context <pod> prune [--older-than N]`

- Removes all entries where `source == "auto"` and `auto_added_at` is older
  than N meetings ago (default: remove auto entries not seen in any transcript
  in the last 30 days)
- Simpler version acceptable: just remove all `source: auto` entries with no
  recency check — user can re-grow them on next consolidate

Add to `build_parser` under the `context` subparser. Add
`cmd_context_prune(args)` handler in `cli.py`.

- [ ] **Write tests** in `tests/test_cli.py` and `tests/test_glossary.py`
- [ ] **Implement** `add_entry` kwargs in `glossary.py`
- [ ] **Implement** `_auto_grow_glossary` + `cmd_context_prune` in `cli.py`
- [ ] **Wire** `context prune` into `build_parser`
- [ ] **Run all tests:** `pytest tests/ -v -k "not transcriber"`
- [ ] **Commit:** `feat(memory): auto-grow glossary after consolidate + context prune`

---

## Feature 2 — Pod Memory File

**What:** A `pods/<pod>/memory.yaml` that accumulates structured knowledge about
a person across all their meetings. Merged after each `consolidate`. Injected
into the `enhance` prompt via a new `{{memory}}` placeholder.

### Task 2a — `memory.py` module

Create `podscribe/memory.py`:

```python
"""Per-pod memory: rolling knowledge base merged after each consolidate."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional
import yaml

MEMORY_VERSION = 1

def memory_path(pod_base: Path) -> Path:
    return pod_base / "memory.yaml"

def load_memory(pod_base: Path) -> dict:
    """Load memory.yaml, or return a fresh empty memory dict."""

def save_memory(pod_base: Path, memory: dict) -> None:
    """Atomically write memory.yaml (via tempfile + os.replace)."""

def empty_memory(pod_name: str, display_name: str) -> dict:
    """Return a fresh memory structure."""
```

**Memory schema** (what `empty_memory` returns):

```yaml
version: 1
pod_name: sam-chen
display_name: Sam Chen
last_updated: "2026-06-25"

working_style: []          # list of string observations, max 10 (oldest dropped)

recurring_themes:
  # - topic: "Auth service tech debt"
  #   first_seen: "2026-05-12"
  #   last_seen: "2026-06-22"
  #   count: 4
  #   status: "ongoing"   # ongoing | resolved | monitoring

open_actions:
  # - text: "Review auth PR"
  #   owner: "Sam"
  #   since: "2026-06-15"
  #   meeting_id: "2026-06-15-143012-sam-chen"

resolved_actions:
  # - text: "Write Argo Rollouts runbook"
  #   resolved: "2026-06-22"

blockers_history:
  # - text: "Waiting on platform team K8s quota"
  #   raised: "2026-06-08"
  #   resolved: null   # or "2026-06-22"
```

Rules:
- `working_style`: capped at 10 entries. When 10 is reached, the oldest is
  dropped to make room.
- `recurring_themes`: keyed by `topic` (string). If a theme appears in a new
  meeting, `last_seen` and `count` are updated, not duplicated.
- `open_actions`→`resolved_actions`: actions mentioned as "done" or "completed"
  in a new summary are moved from `open` to `resolved`.
- `blockers_history`: new blockers appended; existing ones updated with
  `resolved` date if mentioned as resolved.

- [ ] **Write tests** in `tests/test_memory.py`:
  - `test_empty_memory_structure` — verify all keys present
  - `test_load_memory_missing_file_returns_empty`
  - `test_save_and_load_roundtrip`
  - `test_save_is_atomic` — verify tempfile+replace pattern

- [ ] **Implement** `memory.py`
- [ ] **Run tests:** `pytest tests/test_memory.py -v`

### Task 2b — `build_memory_merge_prompt` in `llm.py`

```python
def build_memory_merge_prompt(current_memory_yaml: str, consolidated_fields: dict) -> str:
    """Build a prompt to merge new meeting signals into the existing memory.

    consolidated_fields: the dict from extract_structured_fields — contains
    quick_summary, key_topics, action_items, blockers, next_steps.

    LLM instruction:
    - Given the current memory YAML and the new meeting fields, return
      an updated memory YAML.
    - Merge recurring_themes by topic (case-insensitive).
    - Move actions from open_actions to resolved_actions if the new
      summary mentions they are done.
    - Add new blockers; mark existing ones resolved if mentioned as resolved.
    - Add working_style observations only if genuinely new and specific.
    - Do NOT invent anything. Return ONLY valid YAML, no prose.
    - Preserve the version, pod_name, display_name fields exactly.
    """
```

- [ ] **Write tests** in `tests/test_llm.py`:
  - `test_build_memory_merge_prompt_contains_current_memory`
  - `test_build_memory_merge_prompt_contains_consolidated_fields`
  - `test_build_memory_merge_prompt_no_unresolved_placeholders`

- [ ] **Implement** in `llm.py`
- [ ] **Run tests**

### Task 2c — Memory merge in `run_consolidate`

After auto-glossary growth (Task 1b), add to `run_consolidate`:

```python
# --- Memory merge (best-effort) ---
try:
    _merge_pod_memory(pod, fields, llm_config["model"])
except Exception:
    pass
```

`_merge_pod_memory(pod, fields, model)` in `cli.py`:
1. Load current memory (`memory.load_memory(pod.base_path)`)
2. If memory is empty (first time), create with `memory.empty_memory(pod.name, pod.display_name)`
3. Serialise current memory to YAML string
4. Call `build_memory_merge_prompt(current_yaml, fields)`
5. Call `enhance_transcript` (Ollama, no streaming)
6. Parse response as YAML with `extract_structured_fields`
7. Validate: must have `pod_name`, `version` keys — if invalid, skip silently
8. `memory.save_memory(pod.base_path, merged)`
9. Print `"  ✓ memory updated"` to stderr

- [ ] **Write tests** in `tests/test_cli.py`:
  - `test_run_consolidate_writes_memory_file`
  - `test_run_consolidate_memory_merge_failure_does_not_block`

- [ ] **Implement** `_merge_pod_memory` in `cli.py`
- [ ] **Run all tests**

### Task 2d — `{{memory}}` in enhance prompt

Extend `build_enhance_prompt` in `llm.py` to accept an optional `memory: dict = None`
parameter:

```python
def build_enhance_prompt(
    template: str,
    glossary: list,
    transcript: str,
    *,
    preserve_speakers: bool = True,
    memory: Optional[dict] = None,
) -> str:
```

If `memory` is provided and non-empty:
- Serialise the relevant subset (working_style, recurring_themes, open_actions)
  as a compact YAML block
- Replace `{{memory}}` in the template, OR prepend a `## Context from previous
  meetings` block before the template if `{{memory}}` is not present
- This is purely additive: if `memory.yaml` does not exist, behaviour is
  identical to today

Extend `cmd_enhance` in `cli.py` to load memory and pass it to
`build_enhance_prompt`.

- [ ] **Write tests** in `tests/test_llm.py`:
  - `test_build_enhance_prompt_with_memory_injects_context`
  - `test_build_enhance_prompt_without_memory_unchanged`

- [ ] **Write tests** in `tests/test_cli.py`:
  - `test_cmd_enhance_passes_memory_to_prompt_when_present`
  - `test_cmd_enhance_works_without_memory_file`

- [ ] **Implement** in `llm.py` and `cli.py`
- [ ] **Run all tests**

### Task 2e — `memory show` command

New command: `podscribe memory show <pod>`

Prints `memory.yaml` as formatted YAML to stdout. If no memory exists, prints
`"No memory yet for pod '<pod>'. Run consolidate first."`.

New command: `podscribe memory reset <pod>`

Deletes `memory.yaml` for the pod. Prompts for confirmation unless `--force`.

- [ ] **Implement** `cmd_memory_show`, `cmd_memory_reset` in `cli.py`
- [ ] **Wire** `memory {show,reset}` into `build_parser` and `rewrite_argv`
- [ ] **Write tests** in `tests/test_cli.py`
- [ ] **Run all tests**
- [ ] **Commit:** `feat(memory): pod memory file — merge after consolidate, inject into enhance`

---

## Feature 3 — Team Patterns

**What:** A project-level `pods/team_patterns.yaml` that aggregates signals
across all pods. No LLM call — pure Python reduce over `meetings.csv`. Surfaced
with `podscribe patterns`.

### Task 3a — `patterns.py` module

Create `podscribe/patterns.py`:

```python
"""Cross-pod signal aggregation. Pure Python — no LLM call required."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import yaml

PATTERNS_PATH = Path("pods") / "team_patterns.yaml"

def compute_patterns(base_dir: Path = Path("pods")) -> dict:
    """Read all pods' meetings.csv and memory.yaml files, aggregate signals.

    Returns a dict matching the team_patterns schema.
    Never raises — returns {} on any read error.
    """

def load_team_patterns() -> dict:
    """Load pods/team_patterns.yaml. Returns {} if missing."""

def save_team_patterns(data: dict) -> None:
    """Atomically write pods/team_patterns.yaml."""
```

**Team patterns schema:**

```yaml
last_updated: "2026-06-25"

recurring_blockers:
  # Blockers that appear in 2+ pods' memory.yaml or meetings.csv
  # - text: "Platform team K8s quota"
  #   pods: [sam-chen, priya-nair]
  #   count: 3
  #   last_seen: "2026-06-22"

shared_themes:
  # Key topics appearing in 2+ pods in the same rolling 30-day window
  # - text: "On-call rotation"
  #   pods: [sam-chen, alex-tan]
  #   first_seen: "2026-06-08"

team_vocabulary:
  # Terms appearing in 2+ pods' enhanced summaries but not yet in
  # leadership_team.yaml — candidates for promotion to the global glossary
  # - term: "Argo Rollouts"
  #   pods: [sam-chen, priya-nair]
  #   category: project
```

**Aggregation logic** (no LLM):
- `recurring_blockers`: scan `blockers` column of each pod's `meetings.csv`,
  tokenise by `|` separator (the existing join format). Group by normalised
  text (lowercase, strip). If count ≥ 2 across any pods → add to list.
- `shared_themes`: same approach for `key_topics` column.
- `team_vocabulary`: scan auto-added glossary entries across all
  `config.yaml` files. If a term appears in 2+ pods → candidate for
  `leadership_team.yaml`.

- [ ] **Write tests** in `tests/test_patterns.py`:
  - `test_compute_patterns_empty_dir`
  - `test_compute_patterns_single_pod_no_crossover`
  - `test_compute_patterns_detects_shared_blocker`
  - `test_compute_patterns_detects_shared_theme`
  - `test_load_patterns_missing_returns_empty`
  - `test_save_and_load_roundtrip`

- [ ] **Implement** `patterns.py`
- [ ] **Run tests:** `pytest tests/test_patterns.py -v`

### Task 3b — Update patterns after consolidate

At the end of `run_consolidate` (after memory merge), add:

```python
# --- Refresh team patterns (best-effort) ---
try:
    from .patterns import compute_patterns, save_team_patterns
    save_team_patterns(compute_patterns())
except Exception:
    pass
```

### Task 3c — `patterns` command

New command: `podscribe patterns`

Prints `pods/team_patterns.yaml` as a formatted table using `rich` (or plain
text if not a TTY). Columns: signal type, text, pods affected, count, last seen.

Options: `--json` (raw YAML/JSON output), `--promote` (interactively move
`team_vocabulary` candidates to `leadership_team.yaml`).

- [ ] **Implement** `cmd_patterns` in `cli.py`
- [ ] **Wire** into `build_parser` and `rewrite_argv`
- [ ] **Write tests** in `tests/test_cli.py`
- [ ] **Run all tests**
- [ ] **Commit:** `feat(memory): team patterns — cross-pod aggregation after consolidate`

---

## Feature 4 — Prompt Feedback Observations

**What:** After each `enhance`, record lightweight observations about the LLM
output into `pods/<pod>/prompt_feedback.yaml`. After N meetings, `podscribe tune
<pod>` reads the observations and asks the LLM to suggest targeted edits to the
prompt template. User reviews a diff before anything is written.

### Task 4a — Collect observations

After `enhance_transcript` returns in `cmd_enhance`, add a call to:

```python
_record_prompt_feedback(pod, meeting, enhanced_text)
```

`_record_prompt_feedback` in `cli.py`:
- Checks which expected section headers from the prompt template are present
  in the output vs. absent/empty ("None.")
- Records `word_count`, `action_items_count`, `sections_empty` list
- Appends one entry to `pods/<pod>/prompt_feedback.yaml`
- Caps the file at 20 entries (oldest dropped)
- Best-effort: never raises, never blocks enhance

**`prompt_feedback.yaml` schema:**

```yaml
observations:
  - meeting_id: "2026-06-22-143012-sam-chen"
    date: "2026-06-22"
    word_count: 847
    action_items_count: 3
    sections_empty: ["blockers", "open_questions"]
    sections_none_literal: ["next_1on1"]
```

- [ ] **Write tests** in `tests/test_cli.py`:
  - `test_record_prompt_feedback_writes_file`
  - `test_record_prompt_feedback_caps_at_20`
  - `test_record_prompt_feedback_failure_does_not_block_enhance`

- [ ] **Implement** `_record_prompt_feedback` in `cli.py`
- [ ] **Run all tests**

### Task 4b — `tune` command

New command: `podscribe tune <pod>`

1. Reads `pods/<pod>/prompt_feedback.yaml`
2. If fewer than 5 observations: prints `"Not enough data yet (need 5+
   meetings). Run more enhance cycles first."` and exits 0
3. Builds a prompt: current `prompt_template` + observations summary +
   instruction to suggest 2–3 targeted edits
4. Calls Ollama, streams the suggestions to stdout
5. Prompts: `"Apply these suggestions to podscribe.yaml? [y/N]"`
6. If yes: calls the LLM a second time with instruction to return the full
   revised prompt template only (no prose), validates it contains
   `{{transcript}}` and `{{glossary}}`, writes to `podscribe.yaml`
7. Backs up original prompt to `podscribe.yaml.bak` before writing

- [ ] **Implement** `cmd_tune` in `cli.py`
- [ ] **Wire** into `build_parser` and `rewrite_argv`
- [ ] **Write tests** (mock LLM responses)
- [ ] **Run all tests**
- [ ] **Commit:** `feat(memory): prompt feedback collection + tune command`

---

## Feature 5 — Whisper Calibration via Transcript Diffing

**What:** After `consolidate`, compare the raw transcript against the enhanced
summary to detect proper nouns that Whisper misspelled but the LLM corrected.
Add the corrected spellings to the pod glossary automatically (same auto-grow
mechanism as Feature 1).

This is the simplest feature — it reuses everything from Feature 1 and requires
no LLM call of its own.

### Task 5a — `_extract_whisper_corrections` in `cli.py`

```python
def _extract_whisper_corrections(transcript: str, summary: str, existing_terms: list[str]) -> list[str]:
    """Find capitalised tokens in summary not present in transcript or glossary.

    Heuristic: a token is a candidate if:
    - It appears capitalised (Title Case or ALL CAPS) in the summary
    - It does not appear in the transcript (case-insensitive)
    - It is not already in the existing glossary

    Returns a list of candidate term strings.
    """
```

Call this from `run_consolidate` after the enhanced summary is read, before
the glossary extraction LLM call. Merge the candidates into the glossary-growth
candidates list so they are written together in a single `save_pod_config` call.

- [ ] **Write tests** in `tests/test_cli.py`:
  - `test_extract_whisper_corrections_finds_missing_proper_noun`
  - `test_extract_whisper_corrections_skips_existing_glossary_terms`
  - `test_extract_whisper_corrections_empty_when_no_new_terms`

- [ ] **Implement** `_extract_whisper_corrections`
- [ ] **Integrate** into `run_consolidate`
- [ ] **Run all tests**
- [ ] **Commit:** `feat(memory): Whisper calibration — auto-correct proper nouns from summary diff`

---

## Feature 6 — Export / Import updates

**What:** Include the new files in `export` and handle them safely in `import`.

Files to include in export bundle:
- `pods/<pod>/memory.yaml`
- `pods/<pod>/prompt_feedback.yaml`
- `pods/team_patterns.yaml`

Files to exclude from export (sensitive / machine-specific):
- None of the above are sensitive by default

### Task 6 — Update `export.py`

Currently `export.py` excludes `.raw` files but includes everything else under
`pods/`. Since the new files live under `pods/`, they are automatically included
— no change needed to the export include logic.

However, add an `--no-memory` flag to `podscribe export` that excludes
`memory.yaml` and `prompt_feedback.yaml` for users who want a leaner export.

Also update `_EXCLUDED_SUFFIXES` in `export.py` to add no new entries (`.raw`
is already excluded; `.yaml` must NOT be added globally).

- [ ] **Write tests** for `--no-memory` flag in `tests/test_export.py`
- [ ] **Implement** `--no-memory` export flag
- [ ] **Run all tests**
- [ ] **Commit:** `feat(memory): export --no-memory flag`

---

## TUI surface

After all features are implemented, add entries to the TUI's Others menu:

```python
# In tui.py _others_menu():
("memory", "Memory — show pod knowledge"),
("patterns", "Team patterns"),
("tune", "Tune prompt (N obs. required)"),
```

Wire each to `_dispatch_cli(["memory", "show", pod.name])` etc.

- [ ] **Implement** TUI menu additions in `tui.py`
- [ ] **Write/extend tests** in `tests/test_tui.py`
- [ ] **Commit:** `feat(tui): add memory/patterns/tune to Others menu`

---

## AGENTS.md updates (do last)

After all features are committed, update `AGENTS.md`:

- **Commands table:** add `memory {show,reset}`, `patterns`, `tune`, `context prune`
- **Models section:** note `memory.yaml` and `prompt_feedback.yaml` schemas
- **Storage layout:** add the new files to the diagram
- **Gotchas:** add note that `run_consolidate` now triggers up to 2 extra LLM
  calls (glossary growth + memory merge), both best-effort and non-blocking
- **Test count:** update from 208 to reflect new test count

---

## Execution order

```
Task 1a → 1b → 1c   (auto-glossary: ~2h, no new files)
Task 2a → 2b → 2c → 2d → 2e   (pod memory: ~4h, memory.py new file)
Task 3a → 3b → 3c   (team patterns: ~3h, patterns.py new file)
Task 4a → 4b         (prompt feedback + tune: ~3h)
Task 5a              (Whisper calibration: ~1h, reuses Feature 1)
Feature 6            (export: ~1h)
TUI surface          (~30min)
AGENTS.md            (~15min)
```

**Total estimated effort: ~15h across a focused session.**

Each task is independently committable. If the session is interrupted, the
partial work is always in a shippable state because every feature degrades
gracefully (all new calls are best-effort, wrapped in try/except, never block
the main consolidate/enhance flow).

---

## Privacy checklist

- [ ] All new files live under `pods/` — already gitignored
- [ ] No outbound network calls; Ollama remains the only inference endpoint
- [ ] `memory reset <pod>` deletes `memory.yaml` cleanly
- [ ] `--no-memory` export flag for users who want lean exports
- [ ] Auto-added glossary entries are flagged `source: auto` — auditable and prunable
- [ ] `prompt_feedback.yaml` contains only structural observations, no transcript text
- [ ] `team_patterns.yaml` contains aggregated signals only, no raw text
