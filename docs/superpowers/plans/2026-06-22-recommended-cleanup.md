# Recommended Fixes Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 12 fixes from `Recommended_fixes.md` in one PR, one commit per fix. No new user-facing commands. No new architecture.

**Architecture:** Strict bug-fix PR. Each fix is independent — each gets its own commit on a single feature branch. TDD throughout: failing test → minimal implementation → passing test → commit. The biggest-blast-radius change (audio write path) lands last; the smallest (smoke test rename) lands first.

**Tech Stack:** Python ≥3.10, pytest, `mlx-whisper`, `webrtcvad`, `sounddevice`, `tqdm` (new), `requests`. macOS Apple Silicon, single-user, sequential CLI invocations.

**Source spec:** `docs/superpowers/specs/2026-06-22-recommended-cleanup-design.md` (commit `a7c568b`).

---

## Pre-requisite: land the 3 in-flight fixes

The 3 changes currently in the working tree (per `git status`) must land on `main` BEFORE this branch is created:

1. Declare `requests` in `pyproject.toml` + `requirements.txt`
2. Fix `cmd_show` empty-arg `AttributeError` (with regression test)
3. Fix `list_meetings` chronological sort across month boundaries (with regression test)

**Steps:**

- [ ] **Step 1: Verify the in-flight changes are exactly as expected**

```bash
git status
```

Expected: 7 modified files (`AGENTS.md`, `podscribe/cli.py`, `podscribe/storage.py`, `pyproject.toml`, `requirements.txt`, `tests/test_cli.py`, `tests/test_storage.py`) + 1 untracked (`Recommended_fixes.md`).

- [ ] **Step 2: Run the full test suite to confirm a clean baseline**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: 126 tests pass (all offline tests; the smoke test is excluded).

- [ ] **Step 3: Commit each fix as its own commit**

```bash
git add pyproject.toml requirements.txt
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "chore: declare requests as a real dependency"

git add podscribe/storage.py tests/test_storage.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "fix(storage): sort list_meetings by started_at, not path string"

git add podscribe/cli.py tests/test_cli.py AGENTS.md
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "fix(cli): default cmd_show meeting to 'latest' when arg is empty"
```

- [ ] **Step 4: Create the feature branch**

```bash
git checkout -b fix/recommended-cleanup
```

Expected: on branch `fix/recommended-cleanup`, clean working tree (except `Recommended_fixes.md` which is untracked noise; ignore).

---

## File structure

**Files modified in this PR (in commit order):**

| File | Tasks | Why |
|---|---|---|
| `README.md` | T1 | Bring docs in sync with code (Task 12 / spec §3.6) |
| `tests/test_transcriber.py` | T2 | Fix smoke test model name (§2.7) |
| `podscribe/cli.py` | T3, T4, T5, T6, T7 | Remove dead flag, fix print, empty-guard, consolidate error, ambiguous-prefix helper |
| `podscribe/glossary.py` | T8 | Case-insensitive dedup (§2.5) |
| `podscribe/llm.py` | T9, T10 | `preserve_speakers` plumbing + streaming + retry + progress + metrics |
| `podscribe/config.py` | T9 | Load `preserve_speakers` config, validation |
| `podscribe.yaml` | T9 | Default `preserve_speakers: true` (optional) |
| `podscribe/models.py` | T11 | `make_meeting_id` HHMMSS (§1.2) |
| `podscribe/cli.py` (audio section) | T12 | `--keep-audio` writes real WAV (§1.1) |
| `pyproject.toml` + `requirements.txt` | T10 | Add `tqdm>=4.64` |
| `tests/test_cli.py` | T3, T4, T5, T6, T7, T12 | New tests for §2.4, §1.4, §2.2, §2.3, §2.1, §1.1 |
| `tests/test_llm.py` | T9, T10 | New tests for §1.3, §3.3 + update existing tests for new mock pattern |
| `tests/test_models.py` | T11 | Update `test_meeting_id_format` |
| `tests/test_glossary.py` (new file) | T8 | Tests for case-insensitive dedup |

**No new files except `tests/test_glossary.py`.** No new commands, no new config sections beyond the `preserve_speakers` key.

---

## Commit order (12 commits)

1. README update (T1)
2. Smoke test fix (T2)
3. Remove `--latest` from enhance (T3)
4. Misleading enhance print (T4)
5. Empty-transcript guard (T5)
6. Consolidate error-out (T6)
7. Ambiguous prefix helper (T7)
8. Glossary case-insensitive dedup (T8)
9. `preserve_speakers` toggle (T9)
10. Streaming enhance with progress + metrics (T10)
11. Meeting ID HHMMSS (T11)
12. Audio write path (T12)

Each commit is one task below. Each task is self-contained.

---

## Task 1: Update README to match current code (§3.6)

**Files:**
- Modify: `README.md`

No test for this task (docs only). Read the spec section §12 (README updates) for the exact edits. Verify the test count line says "126 offline + 1 smoke".

- [ ] **Step 1: Read the current README to find the spots to edit**

```bash
grep -n "pywhispercpp\|45 unit\|45 tests\|podscribe.yaml\|HHMM\|large-v3\b" README.md
```

Expected: multiple matches — those are the lines we need to fix.

- [ ] **Step 2: Update the model section**

Find the line containing `pywhispercpp` and replace it with `mlx-whisper`. Add a sentence: "Models download automatically from HuggingFace on first use."

- [ ] **Step 3: Update the `--model` flag docs**

Find the line documenting `--model`. Change the default from `large-v3` to `large-v3-turbo`. Add a small table:

```
| Short name | HuggingFace path |
|---|---|
| tiny | mlx-community/whisper-tiny-mlx |
| base | mlx-community/whisper-base-mlx |
| small | mlx-community/whisper-small-mlx |
| medium | mlx-community/whisper-medium-mlx |
| large-v3 | mlx-community/whisper-large-v3-mlx |
| large-v3-turbo | mlx-community/whisper-large-v3-turbo |
```

- [ ] **Step 4: Update the test count**

Find "45 unit tests" (or similar) and replace with:

> 126 offline unit tests + 1 smoke test requiring network. Run with `pytest tests/ -v`. Skip the smoke test with `-k "not transcriber"` (recommended for CI without network).

- [ ] **Step 5: Update the storage layout diagram**

Find the flat `pods/<name>/transcripts/YYYY-MM-DD-HHMM-<pod>.md` line and replace with the actual two-level layout:

```
pods/<name>/
├── config.yaml
└── transcripts/
    └── DD-MMM-YYYY/        # e.g. 22-JUN-2026
        ├── <meeting-id>.md # e.g. 2026-06-22-143012-sam-chen.md
        ├── <meeting-id>.json
        └── <meeting-id>.raw   # deleted by default
└── summaries/
    └── DD-MMM-YYYY/
        └── <meeting-id>.md
└── meetings.csv
```

- [ ] **Step 6: Add the `consolidate` command and LLM section**

Add a section documenting `podscribe consolidate <pod> [meeting] [--no-log]`, the `cons` alias, and `podscribe config consolidate show|set`.

In the LLM section, mention:
- Ollama must be running (`ollama serve`)
- Default model is `qwen3.6:27b` (the user prefers Qwen over gemma4 for output quality)
- The `preserve_speakers: true` toggle in the `llm` config (default true; preserves speaker names in enhanced output)

- [ ] **Step 7: Verify the test count claim is correct**

```bash
pytest --collect-only -q 2>&1 | tail -1
```

Expected: `127 tests collected in 0.0Xs`.

- [ ] **Step 8: Commit**

```bash
git add README.md
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "docs: sync README with current storage layout, model, and test count"
```

---

## Task 2: Fix smoke test model name (§2.7)

**Files:**
- Modify: `tests/test_transcriber.py:7`

One-line fix. The smoke test uses `model="base.en"` but only `"base"` is in `MODEL_MAP` (`podscribe/transcriber.py:10`). Change to `"base"`.

- [ ] **Step 1: Read the test**

```bash
sed -n '1,15p' tests/test_transcriber.py
```

Expected: line 7 contains `Transcriber(model="base.en")`.

- [ ] **Step 2: Change the model name**

In `tests/test_transcriber.py`, change `model="base.en"` to `model="base"`.

- [ ] **Step 3: Verify the change**

```bash
grep -n "Transcriber(model" tests/test_transcriber.py
```

Expected: `Transcriber(model="base")`.

- [ ] **Step 4: Run the test to confirm it's still skipped (no network)**

```bash
pytest tests/test_transcriber.py -v 2>&1 | tail -20
```

Expected: 1 test collected, will error if network is unavailable. Per AGENTS.md: skip with `-k "not transcriber"`. Don't fix the network issue here; that's not in scope.

- [ ] **Step 5: Run the rest of the suite to confirm nothing else broke**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: 126 tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_transcriber.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "test(transcriber): use 'base' instead of missing 'base.en' model"
```

---

## Task 3: Remove dead `--latest` flag from enhance parser (§2.4)

**Files:**
- Modify: `podscribe/cli.py:497` (delete the line)
- Modify: `tests/test_cli.py` (add test)

`args.meeting` already defaults to `"latest"` (line 496). The `--latest` / `-l` flag is dead code.

- [ ] **Step 1: Write the failing test**

In `tests/test_cli.py`, add at the end of the file:

```python
def test_enhance_parser_has_no_latest_flag():
    """--latest/-l is dead code; args.meeting defaults to 'latest'."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["enhance", "sam-chen", "2026-06-22-1430", "--latest"])
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_cli.py::test_enhance_parser_has_no_latest_flag -v
```

Expected: FAIL. The current parser accepts `--latest` so argparse doesn't exit.

- [ ] **Step 3: Delete the dead flag**

In `podscribe/cli.py:497`, delete this line:

```python
    p_enh.add_argument("--latest", "-l", action="store_true", help="Use latest meeting")
```

The line above it (`p_enh.add_argument("meeting", nargs="?", default="latest", ...)`) stays.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_cli.py::test_enhance_parser_has_no_latest_flag -v
```

Expected: PASS. argparse now exits on `--latest`.

- [ ] **Step 5: Run the full CLI test suite**

```bash
pytest tests/test_cli.py -v -k "not transcriber"
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add podscribe/cli.py tests/test_cli.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "fix(cli): remove dead --latest flag from enhance subparser"
```

---

## Task 4: Fix misleading enhance print (§1.4)

**Files:**
- Modify: `podscribe/cli.py:279` (change the print)
- Modify: `tests/test_cli.py` (add test)

Line 279 says "Saving transcript to..." but writes the summary. Change to "Enhanced summary will be saved to...".

- [ ] **Step 1: Write the failing test**

In `tests/test_cli.py`, add at the end of the file:

```python
def test_cmd_enhance_prints_summary_path_not_transcript_path(tmp_path, monkeypatch, capsys):
    """Misleading print: 'Saving transcript' but writes the summary."""
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_enhance, build_parser

    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello world"))
    finalize_meeting(meeting)

    with patch("podscribe.cli.enhance_transcript", return_value="Enhanced output."):
        with patch("podscribe.cli.load_project_config", return_value={
            "llm": {"model": "qwen3.6", "prompt_template": "test"}
        }):
            args = build_parser().parse_args(["enhance", "sam-chen"])
            rc = cmd_enhance(args)
            assert rc == 0

    captured = capsys.readouterr()
    assert "Enhanced summary will be saved to" in captured.out
    assert "Saving transcript to" not in captured.out
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_cli.py::test_cmd_enhance_prints_summary_path_not_transcript_path -v
```

Expected: FAIL. Current code prints "Saving transcript to...".

- [ ] **Step 3: Change the print**

In `podscribe/cli.py:279`, change:

```python
    print(f"Saving transcript to {pod.name}/{date_str}/{meeting.id}...")
```

to:

```python
    print(f"Enhanced summary will be saved to {pod.name}/{date_str}/{meeting.id}...")
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_cli.py::test_cmd_enhance_prints_summary_path_not_transcript_path -v
```

Expected: PASS.

- [ ] **Step 5: Run the full CLI test suite**

```bash
pytest tests/test_cli.py -v -k "not transcriber"
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add podscribe/cli.py tests/test_cli.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "fix(cli): correct misleading 'Saving transcript' print in enhance"
```

---

## Task 5: Empty-transcript guard in enhance (§2.2)

**Files:**
- Modify: `podscribe/cli.py` (add guard after reading transcript)
- Modify: `tests/test_cli.py` (add tests)

If the transcript is too short to enhance, skip the LLM call and return 1. Saves 3-10 minutes of GPU time.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, add at the end of the file:

```python
def test_cmd_enhance_rejects_empty_transcript(tmp_path, monkeypatch, capsys):
    """Empty transcript: skip the LLM call entirely."""
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_enhance, build_parser

    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, ""))  # empty segment
    finalize_meeting(meeting)

    llm_called = []
    def fake_enhance(*a, **kw):
        llm_called.append(True)
        return "should not happen"

    with patch("podscribe.cli.enhance_transcript", side_effect=fake_enhance):
        with patch("podscribe.cli.load_project_config", return_value={
            "llm": {"model": "qwen3.6", "prompt_template": "test"}
        }):
            args = build_parser().parse_args(["enhance", "sam-chen"])
            rc = cmd_enhance(args)
            assert rc == 1

    assert llm_called == [], "LLM should not be called for empty transcript"
    captured = capsys.readouterr()
    assert "too short" in captured.err


def test_cmd_enhance_rejects_short_transcript(tmp_path, monkeypatch, capsys):
    """<50 char transcript: skip the LLM call entirely."""
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_enhance, build_parser

    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello"))  # 5 chars
    finalize_meeting(meeting)

    llm_called = []
    with patch("podscribe.cli.enhance_transcript", side_effect=lambda *a, **kw: llm_called.append(True) or "no"):
        with patch("podscribe.cli.load_project_config", return_value={
            "llm": {"model": "qwen3.6", "prompt_template": "test"}
        }):
            args = build_parser().parse_args(["enhance", "sam-chen"])
            rc = cmd_enhance(args)
            assert rc == 1

    assert llm_called == []
    captured = capsys.readouterr()
    assert "too short" in captured.err
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_cli.py::test_cmd_enhance_rejects_empty_transcript tests/test_cli.py::test_cmd_enhance_rejects_short_transcript -v
```

Expected: FAIL. Current code does not check transcript length.

- [ ] **Step 3: Add the guard**

In `podscribe/cli.py`, find the `transcript = read_transcript(meeting)` line (around line 268) and add the guard immediately after:

```python
    transcript = read_transcript(meeting)
    if len(transcript.strip()) < 50:
        print(
            f"Transcript too short to enhance ({len(transcript)} chars).",
            file=sys.stderr,
        )
        return 1
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_cli.py::test_cmd_enhance_rejects_empty_transcript tests/test_cli.py::test_cmd_enhance_rejects_short_transcript -v
```

Expected: PASS.

- [ ] **Step 5: Run the full CLI test suite to confirm no regression**

```bash
pytest tests/test_cli.py -v -k "not transcriber"
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add podscribe/cli.py tests/test_cli.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "fix(cli): skip LLM call when transcript is too short to enhance"
```

---

## Task 6: Consolidate errors out cleanly when summary missing (§2.3)

**Files:**
- Modify: `podscribe/cli.py:354-377` (replace y/N offer with hard error)
- Modify: `tests/test_cli.py` (update existing test + add new one)

The current code offers to enhance first via a y/N prompt. Replace with a hard error that tells the user exactly what to run.

- [ ] **Step 1: Update the existing test**

In `tests/test_cli.py`, find the test `test_cmd_consolidate_no_enhanced_summary` (around line 308). Change it to:

```python
def test_cmd_consolidate_no_enhanced_summary_errors_out(tmp_path, monkeypatch, capsys):
    """Missing summary: hard error with the exact enhance command to run, no prompt."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_consolidate, build_parser

    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello world"))
    finalize_meeting(meeting)

    args = build_parser().parse_args(["consolidate", "sam-chen"])
    rc = cmd_consolidate(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "No enhanced summary" in captured.err
    assert "podscribe enhance sam-chen" in captured.err
```

- [ ] **Step 2: Add a test that verifies no input() is called**

In `tests/test_cli.py`, add at the end of the file:

```python
def test_cmd_consolidate_no_summary_does_not_prompt(tmp_path, monkeypatch, capsys):
    """Missing summary: must NOT call input() — should be a hard error."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_consolidate, build_parser

    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello world"))
    finalize_meeting(meeting)

    def fail_if_called(*a, **kw):
        raise AssertionError("input() should not be called")

    monkeypatch.setattr("builtins.input", fail_if_called)
    args = build_parser().parse_args(["consolidate", "sam-chen"])
    rc = cmd_consolidate(args)
    assert rc == 1
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
pytest tests/test_cli.py::test_cmd_consolidate_no_enhanced_summary_errors_out tests/test_cli.py::test_cmd_consolidate_no_summary_does_not_prompt -v
```

Expected: FAIL. The first fails because old text says "Run enhance first? [y/N]". The second fails because the old code calls `input()`.

- [ ] **Step 4: Replace the y/N offer with a hard error**

In `podscribe/cli.py`, find the block starting at line 354 (`if not enhanced_path.exists():`) and ending at line 377 (the `else:` branch returning 1). Replace the entire block (lines 354-377) with:

```python
    if not enhanced_path.exists():
        print(
            f"No enhanced summary for {meeting.id}. "
            f"Run `podscribe enhance {pod.name} {meeting.id}` first.",
            file=sys.stderr,
        )
        return 1
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pytest tests/test_cli.py::test_cmd_consolidate_no_enhanced_summary_errors_out tests/test_cli.py::test_cmd_consolidate_no_summary_does_not_prompt -v
```

Expected: PASS.

- [ ] **Step 6: Run the full CLI test suite**

```bash
pytest tests/test_cli.py -v -k "not transcriber"
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add podscribe/cli.py tests/test_cli.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "fix(cli): consolidate errors out cleanly when summary missing"
```

---

## Task 7: Ambiguous meeting prefix → list candidates (§2.1)

**Files:**
- Modify: `podscribe/cli.py` (add helper + use in show, enhance, consolidate)
- Modify: `tests/test_cli.py` (add tests for all three commands)

The current code silently picks the first match when multiple meetings share a prefix. Add a helper that lists candidates and returns 1 instead.

- [ ] **Step 1: Add the helper function**

In `podscribe/cli.py`, find the `_hms` helper near the top (around line 33). Add this new helper right after it:

```python
def _resolve_meeting(meetings, prefix, pod_name):
    """Resolve a meeting by ID prefix. Returns (meeting, None) on success, (None, error_message) on failure.

    - "latest" → meetings[0]
    - unique prefix → that meeting
    - 0 matches → error
    - 2+ matches → list candidates, error
    """
    if prefix == "latest":
        if not meetings:
            return None, f"No meetings for pod '{pod_name}'."
        return meetings[0], None
    matches = [m for m in meetings if m.id.startswith(prefix)]
    if not matches:
        return None, f"No meeting matching '{prefix}' for pod '{pod_name}'."
    if len(matches) > 1:
        listing = "\n".join(f"  • {m.id}" for m in matches)
        return None, (
            f"Multiple meetings match '{prefix}':\n{listing}\n"
            f"Use a longer prefix to disambiguate."
        )
    return matches[0], None
```

- [ ] **Step 2: Use the helper in cmd_show**

In `podscribe/cli.py`, find the `cmd_show` function (around line 168). Replace the entire prefix-resolution block (lines 178-186) with:

```python
    meeting_id = args.meeting or "latest"
    meeting, err = _resolve_meeting(meetings, meeting_id, args.pod)
    if err is not None:
        print(err, file=sys.stderr)
        return 1
    print(read_transcript(meeting))
    return 0
```

- [ ] **Step 3: Use the helper in cmd_enhance**

In `podscribe/cli.py`, find the prefix-resolution block in `cmd_enhance` (lines 259-266). Replace it with:

```python
    meeting, err = _resolve_meeting(meetings, args.meeting, args.pod)
    if err is not None:
        print(err, file=sys.stderr)
        return 1
```

(The `if not meetings: print(...); return 1` block right above stays as-is — that's a separate check.)

- [ ] **Step 4: Use the helper in cmd_consolidate**

In `podscribe/cli.py`, find the prefix-resolution block in `cmd_consolidate` (lines 342-349). Replace it with:

```python
    meeting, err = _resolve_meeting(meetings, args.meeting, args.pod)
    if err is not None:
        print(err, file=sys.stderr)
        return 1
```

(The `if not meetings:` block above stays.)

- [ ] **Step 5: Write the tests**

In `tests/test_cli.py`, add at the end of the file:

```python
def test_show_with_ambiguous_prefix_lists_candidates(tmp_path, monkeypatch, capsys):
    """Two meetings with same prefix → list them and return 1."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_show, build_parser

    pod = init_pod("sam-chen")
    for dt in [datetime(2026, 6, 22, 14, 30, 12), datetime(2026, 6, 22, 14, 30, 45)]:
        m = start_meeting(pod, dt)
        append_segment(m, Segment(1.0, 5.0, "hello"))
        finalize_meeting(m)

    args = build_parser().parse_args(["show", "sam-chen", "2026-06-22-1430"])
    rc = cmd_show(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "Multiple meetings match" in captured.err
    assert "2026-06-22-143012-sam-chen" in captured.err
    assert "2026-06-22-143045-sam-chen" in captured.err


def test_enhance_with_ambiguous_prefix_lists_candidates(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_enhance, build_parser

    pod = init_pod("sam-chen")
    for dt in [datetime(2026, 6, 22, 14, 30, 12), datetime(2026, 6, 22, 14, 30, 45)]:
        m = start_meeting(pod, dt)
        append_segment(m, Segment(1.0, 5.0, "hello"))
        finalize_meeting(m)

    args = build_parser().parse_args(["enhance", "sam-chen", "2026-06-22-1430"])
    rc = cmd_enhance(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "Multiple meetings match" in captured.err


def test_consolidate_with_ambiguous_prefix_lists_candidates(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_consolidate, build_parser

    pod = init_pod("sam-chen")
    for dt in [datetime(2026, 6, 22, 14, 30, 12), datetime(2026, 6, 22, 14, 30, 45)]:
        m = start_meeting(pod, dt)
        append_segment(m, Segment(1.0, 5.0, "hello"))
        finalize_meeting(m)

    args = build_parser().parse_args(["consolidate", "sam-chen", "2026-06-22-1430"])
    rc = cmd_consolidate(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "Multiple meetings match" in captured.err
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
pytest tests/test_cli.py::test_show_with_ambiguous_prefix_lists_candidates tests/test_cli.py::test_enhance_with_ambiguous_prefix_lists_candidates tests/test_cli.py::test_consolidate_with_ambiguous_prefix_lists_candidates -v
```

Expected: PASS. The tests verify the new behavior, so they should pass once the helper is in place.

- [ ] **Step 7: Sanity-check: run the full CLI suite to confirm no regression**

```bash
pytest tests/test_cli.py -v -k "not transcriber"
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add podscribe/cli.py tests/test_cli.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "fix(cli): list candidates and return 1 on ambiguous meeting prefix"
```

---

## Task 8: Case-insensitive glossary dedup (§2.5)

**Files:**
- Modify: `podscribe/glossary.py` (update add_entry and remove_entry)
- Create: `tests/test_glossary.py` (new file)

`add_entry` does exact-string matching, so "Anurag" and "anurag" both go in. Make it case-insensitive while preserving first-seen casing.

- [ ] **Step 1: Create the new test file with failing tests**

Create `tests/test_glossary.py`:

```python
"""Tests for glossary management."""
import pytest
from podscribe.glossary import add_entry, remove_entry, format_glossary_prompt
from podscribe.models import Pod


@pytest.fixture
def pod():
    return Pod(name="sam-chen")


def test_add_entry_accepts_new_term(pod):
    add_entry(pod, "Anurag Kaushik", "person")
    assert {"term": "Anurag Kaushik", "category": "person"} in pod.glossary


def test_add_entry_dedups_case_insensitive(pod):
    add_entry(pod, "Anurag Kaushik", "person")
    with pytest.raises(ValueError, match="already in glossary"):
        add_entry(pod, "anurag kaushik", "person")


def test_add_entry_preserves_first_seen_casing(pod):
    add_entry(pod, "Anurag Kaushik", "person")
    with pytest.raises(ValueError):
        add_entry(pod, "ANURAG KAUSHIK", "person")
    # Original casing is what got stored
    assert pod.glossary[0]["term"] == "Anurag Kaushik"


def test_add_entry_strips_whitespace(pod):
    add_entry(pod, "  Anurag  ", "person")
    assert pod.glossary[0]["term"] == "Anurag"


def test_add_entry_rejects_empty(pod):
    with pytest.raises(ValueError, match="cannot be empty"):
        add_entry(pod, "   ", "")


def test_remove_entry_case_insensitive(pod):
    add_entry(pod, "Anurag Kaushik", "person")
    remove_entry(pod, "ANURAG KAUSHIK")
    assert pod.glossary == []


def test_remove_entry_missing_raises(pod):
    with pytest.raises(ValueError, match="not found"):
        remove_entry(pod, "Nobody")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_glossary.py -v
```

Expected: at least 2 fail — `test_add_entry_dedups_case_insensitive` and `test_remove_entry_case_insensitive`. Others should pass.

- [ ] **Step 3: Update `glossary.py`**

In `podscribe/glossary.py`, replace the entire file content with:

```python
"""Glossary management: add, remove, list entries and format for Whisper biasing."""
from __future__ import annotations

from .models import Pod


def add_entry(pod: Pod, term: str, category: str = "") -> None:
    """Add a term to the pod's glossary.

    Dedup is case-insensitive (so "Anurag" and "anurag" are the same entry).
    The first-seen casing is preserved; subsequent attempts raise ValueError.
    Whitespace is stripped from the term before storage and dedup.
    """
    term = term.strip()
    if not term:
        raise ValueError("Term cannot be empty")
    key = term.lower()
    if any(e["term"].lower() == key for e in pod.glossary):
        raise ValueError(f"'{term}' is already in glossary")
    pod.glossary.append({"term": term, "category": category})


def remove_entry(pod: Pod, term: str) -> None:
    """Remove a term from the pod's glossary (case-insensitive)."""
    term = term.strip()
    key = term.lower()
    for i, entry in enumerate(pod.glossary):
        if entry["term"].lower() == key:
            pod.glossary.pop(i)
            return
    raise ValueError(f"'{term}' not found in glossary")


def format_glossary_prompt(glossary: list) -> str:
    if not glossary:
        return ""
    terms = ", ".join(e["term"] for e in glossary)
    return f"Please transcribe the following names and project names correctly: {terms}."
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_glossary.py -v
```

Expected: all 7 pass.

- [ ] **Step 5: Run the full suite**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: 133 tests pass (was 126, +7 new glossary tests).

- [ ] **Step 6: Commit**

```bash
git add podscribe/glossary.py tests/test_glossary.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "fix(glossary): case-insensitive dedup, preserve first-seen casing"
```

---

## Task 9: `preserve_speakers` toggle (§1.3)

**Files:**
- Modify: `podscribe/llm.py` (add preamble constant, add kwarg to `build_enhance_prompt`)
- Modify: `podscribe/config.py` (add `load_preserve_speakers()` helper with validation)
- Modify: `podscribe/cli.py` (plumb the toggle through `cmd_enhance`)
- Modify: `tests/test_llm.py` (add tests for preamble)
- Modify: `tests/test_config.py` (add tests for loader + validation)
- Modify: `podscribe.yaml` (set default `preserve_speakers: true`)

Add a `preserve_speakers: bool` config key (default true) that prepends a fixed preamble to the enhance prompt template, instructing the LLM to preserve speaker names in action items.

- [ ] **Step 1: Write the failing test in test_llm.py**

In `tests/test_llm.py`, add at the end of the file:

```python
SPEAKER_PREAMBLE_FRAGMENT = "Preserve all names exactly as they appear"


def test_build_enhance_prompt_includes_speaker_preamble_by_default():
    """Default behavior: include the speaker-preservation preamble."""
    prompt = build_enhance_prompt(TEMPLATE, GLOSSARY, "hello")
    assert SPEAKER_PREAMBLE_FRAGMENT in prompt


def test_build_enhance_prompt_excludes_preamble_when_disabled():
    prompt = build_enhance_prompt(TEMPLATE, GLOSSARY, "hello", preserve_speakers=False)
    assert SPEAKER_PREAMBLE_FRAGMENT not in prompt


def test_build_enhance_prompt_preamble_appears_before_template():
    """The preamble should come first, before any template content."""
    prompt = build_enhance_prompt(TEMPLATE, GLOSSARY, "hello")
    preamble_pos = prompt.find(SPEAKER_PREAMBLE_FRAGMENT)
    template_marker_pos = prompt.find("Correct these names")
    assert preamble_pos < template_marker_pos
    assert preamble_pos >= 0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_llm.py::test_build_enhance_prompt_includes_speaker_preamble_by_default tests/test_llm.py::test_build_enhance_prompt_excludes_preamble_when_disabled tests/test_llm.py::test_build_enhance_prompt_preamble_appears_before_template -v
```

Expected: 3 failures (the new `preserve_speakers` kwarg doesn't exist yet).

- [ ] **Step 3: Add the preamble constant and update `build_enhance_prompt`**

In `podscribe/llm.py`, add this constant near the top of the file (after the imports, before `OLLAMA_URL`):

```python
SPEAKER_PRESERVATION_PREAMBLE = (
    "Preserve all names exactly as they appear in the transcript. "
    "For each action item, name the responsible person "
    '(e.g. "Sam will review the auth middleware design"). '
    'If the transcript does not name a person, write "Unassigned — needs owner" '
    "rather than dropping the item."
)
```

Then update `build_enhance_prompt` to accept and apply the toggle:

```python
def build_enhance_prompt(
    template: str,
    glossary: list,
    transcript: str,
    *,
    preserve_speakers: bool = True,
) -> str:
    if preserve_speakers:
        template = SPEAKER_PRESERVATION_PREAMBLE + "\n\n" + template
    glossary_text = ", ".join(
        f"{e['term']} ({e.get('category', 'other')})" for e in glossary
    )
    prompt = template.replace("{{glossary}}", glossary_text)
    prompt = prompt.replace("{{transcript}}", transcript)
    if "{{transcript}}" not in template:
        prompt += "\n\n" + transcript
    return prompt
```

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
pytest tests/test_llm.py::test_build_enhance_prompt_includes_speaker_preamble_by_default tests/test_llm.py::test_build_enhance_prompt_excludes_preamble_when_disabled tests/test_llm.py::test_build_enhance_prompt_preamble_appears_before_template -v
```

Expected: 3 passes.

- [ ] **Step 5: Run the existing llm tests to confirm no regression**

```bash
pytest tests/test_llm.py -v
```

Expected: all pass.

- [ ] **Step 6: Add the config loader with validation**

In `podscribe/config.py`, add this function near the end of the file:

```python
def load_preserve_speakers(pod: "Pod") -> bool:
    """Resolve the preserve_speakers setting for a pod.

    Resolution order: pod-level llm.preserve_speakers > project-level
    llm.preserve_speakers > default True.

    Raises ConfigError if either level is set to a non-boolean value.
    """
    for level_name, llm_cfg in [
        ("pod", pod.llm),
        ("project", load_project_config().get("llm")),
    ]:
        if llm_cfg and "preserve_speakers" in llm_cfg:
            value = llm_cfg["preserve_speakers"]
            if not isinstance(value, bool):
                raise ValueError(
                    f"{level_name} llm.preserve_speakers must be a boolean, "
                    f"got {type(value).__name__}: {value!r}"
                )
            return value
    return True
```

(We're using `ValueError` rather than introducing a new `ConfigError` class — keep the change small.)

- [ ] **Step 7: Add tests for the config loader**

Open `tests/test_config.py` and add at the end of the file (if it doesn't exist, create it):

```python
"""Tests for config loading."""
from pathlib import Path
import pytest
from podscribe.config import load_preserve_speakers
from podscribe.models import Pod


@pytest.fixture
def pod():
    return Pod(name="sam-chen", base_path=Path("pods/sam-chen"))


def test_load_preserve_speakers_default_true(tmp_path, monkeypatch, pod):
    monkeypatch.chdir(tmp_path)
    assert load_preserve_speakers(pod) is True


def test_load_preserve_speakers_project_level(tmp_path, monkeypatch, pod):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "podscribe.yaml").write_text(
        "llm:\n  model: qwen3.6\n  prompt_template: x\n  preserve_speakers: false\n"
    )
    assert load_preserve_speakers(pod) is False


def test_load_preserve_speakers_pod_overrides_project(tmp_path, monkeypatch, pod):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "podscribe.yaml").write_text(
        "llm:\n  model: qwen3.6\n  prompt_template: x\n  preserve_speakers: false\n"
    )
    pod.llm = {"model": "qwen3.6", "prompt_template": "x", "preserve_speakers": True}
    assert load_preserve_speakers(pod) is True


def test_load_preserve_speakers_rejects_non_bool_at_pod_level(tmp_path, monkeypatch, pod):
    monkeypatch.chdir(tmp_path)
    pod.llm = {"model": "qwen3.6", "prompt_template": "x", "preserve_speakers": "yes"}
    with pytest.raises(ValueError, match="must be a boolean"):
        load_preserve_speakers(pod)


def test_load_preserve_speakers_rejects_non_bool_at_project_level(tmp_path, monkeypatch, pod):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "podscribe.yaml").write_text(
        "llm:\n  model: qwen3.6\n  prompt_template: x\n  preserve_speakers: 1\n"
    )
    with pytest.raises(ValueError, match="must be a boolean"):
        load_preserve_speakers(pod)
```

- [ ] **Step 8: Run the new config tests**

```bash
pytest tests/test_config.py -v
```

Expected: all 5 pass.

- [ ] **Step 9: Plumb the toggle through `cmd_enhance`**

In `podscribe/cli.py`, find the `build_enhance_prompt` call (around line 270). Add the import for `load_preserve_speakers` at the top of the file (extend the existing `.config` import line on line 12). Then update the call site:

Before (line 269-272):
```python
    effective_glossary = get_effective_glossary(pod)
    prompt = build_enhance_prompt(
        llm_config["prompt_template"], effective_glossary, transcript
    )
```

After:
```python
    effective_glossary = get_effective_glossary(pod)
    preserve_speakers = load_preserve_speakers(pod)
    prompt = build_enhance_prompt(
        llm_config["prompt_template"], effective_glossary, transcript,
        preserve_speakers=preserve_speakers,
    )
```

Also extend the import line on line 12 to add `load_preserve_speakers`:

```python
from .config import get_effective_glossary, load_consolidate_prompt, load_leadership_glossary, load_preserve_speakers, load_project_config, save_consolidate_prompt, save_project_config
```

- [ ] **Step 10: Run the full test suite**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: 146 tests pass (was 133, +8 from this task — 3 preamble tests + 5 config tests).

- [ ] **Step 11: Update `podscribe.yaml` (optional but recommended)**

If `podscribe.yaml` exists in the repo root, add `preserve_speakers: true` to the `llm` section. Check first:

```bash
test -f podscribe.yaml && cat podscribe.yaml
```

If present and has an `llm:` section, add the line. If absent, skip this step (no default file is required).

- [ ] **Step 12: Commit**

```bash
git add podscribe/llm.py podscribe/config.py podscribe/cli.py tests/test_llm.py tests/test_config.py podscribe.yaml 2>/dev/null
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "feat(llm): add preserve_speakers toggle (default true)"
```

(The `podscribe.yaml 2>/dev/null` quietly skips the file if it didn't exist.)

---

## Task 10: Streaming enhance with progress + metrics + retry (§3.3)

**Files:**
- Modify: `podscribe/llm.py` (refactor `enhance_transcript` to streaming + retry + progress + metrics)
- Modify: `pyproject.toml` (add `tqdm>=4.64`)
- Modify: `requirements.txt` (add `tqdm>=4.64`)
- Modify: `tests/test_llm.py` (update existing tests + add 5 new tests)

This is the biggest change in the PR. Replaces the request/response pattern with streaming, adds a `tqdm` progress bar, retries 3× on transient errors, and prints token metrics to stderr.

- [ ] **Step 1: Add the tqdm dependency**

In `pyproject.toml`, find the `dependencies` list and add `"tqdm>=4.64"` to it (alphabetical order: between `sounddevice` and `pyyaml`, or wherever the existing list keeps its sort).

In `requirements.txt`, add `tqdm>=4.64` on its own line.

- [ ] **Step 2: Run the test suite to confirm the dep change didn't break anything**

```bash
pip install -e . 2>&1 | tail -5
pytest tests/ -v -k "not transcriber" 2>&1 | tail -3
```

Expected: install succeeds; 138 tests still pass.

- [ ] **Step 3: Commit the dep change**

```bash
git add pyproject.toml requirements.txt
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "chore: add tqdm dep for streaming enhance progress bar"
```

- [ ] **Step 4: Update the existing tests to use the new mock pattern**

The existing `test_enhance_transcript_*` tests in `tests/test_llm.py` mock `mock_resp.json.return_value` and `mock_resp.raise_for_status`. The new code uses `iter_lines`. Update the existing 3 tests.

In `tests/test_llm.py`, find `test_enhance_transcript_success`, `test_enhance_transcript_connection_error`, and `test_enhance_transcript_http_error`. Replace them with:

```python
import json


def make_streaming_response(chunks, final_stats=None, status_code=200):
    """Build a mock streaming response for enhance_transcript."""
    lines = []
    for c in chunks:
        lines.append(json.dumps({"response": c, "done": False}))
    final = {"response": "", "done": True, **(final_stats or {})}
    lines.append(json.dumps(final))
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.iter_lines = MagicMock(return_value=iter(lines))
    resp.status_code = status_code
    return resp


def test_enhance_transcript_success():
    """Streaming response: chunks accumulate into the final text."""
    resp = make_streaming_response(
        ["Hello", " ", "world"],
        final_stats={"prompt_eval_count": 5, "eval_count": 3,
                     "total_duration": 1_000_000_000, "eval_duration": 500_000_000},
    )
    with patch("podscribe.llm.requests.post", return_value=resp) as mock_post:
        result = enhance_transcript("llama3.2", "fix this", show_progress=False)
        assert result == "Hello world"
        # streamed + no retry
        assert mock_post.call_count == 1
        # timeout=1800 in the call
        assert mock_post.call_args.kwargs["timeout"] == 1800
        assert mock_post.call_args.kwargs["stream"] is True


def test_enhance_transcript_connection_error():
    with patch("podscribe.llm.requests.post", side_effect=requests.ConnectionError):
        result = enhance_transcript("llama3.2", "fix this", show_progress=False)
        assert result is None


def test_enhance_transcript_http_error():
    """Generic HTTP error → retried, returns None after exhaustion."""
    bad_resp = MagicMock()
    bad_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 500")
    bad_resp.status_code = 500
    with patch("podscribe.llm.requests.post", return_value=bad_resp) as mock_post:
        result = enhance_transcript("llama3.2", "fix this", show_progress=False)
        assert result is None
        # 3 attempts
        assert mock_post.call_count == 3
```

- [ ] **Step 5: Run the updated tests to verify the new mock works**

```bash
pytest tests/test_llm.py::test_enhance_transcript_success tests/test_llm.py::test_enhance_transcript_connection_error tests/test_llm.py::test_enhance_transcript_http_error -v
```

Expected: all 3 fail (the new streaming code doesn't exist yet — function still does request/response).

- [ ] **Step 6: Add the new tests**

In `tests/test_llm.py`, add at the end of the file:

```python
def test_enhance_streams_and_returns_full_text():
    """Multiple streaming chunks concatenate into the final text."""
    resp = make_streaming_response(
        ["Sam", " will", " review", " the", " design"],
        final_stats={"prompt_eval_count": 10, "eval_count": 5,
                     "total_duration": 2_000_000_000, "eval_duration": 1_000_000_000},
    )
    with patch("podscribe.llm.requests.post", return_value=resp):
        result = enhance_transcript("qwen3.6:27b", "go", show_progress=False)
        assert result == "Sam will review the design"


def test_enhance_retries_on_5xx(capfd):
    """5xx response: retried 3×, succeeds on 3rd attempt."""
    bad = MagicMock()
    bad.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 503")
    bad.status_code = 503
    bad.iter_lines = MagicMock(return_value=iter([]))
    good = make_streaming_response(["ok"], final_stats={"prompt_eval_count": 1, "eval_count": 1})
    with patch("podscribe.llm.requests.post", side_effect=[bad, bad, good]) as mock_post:
        with patch("podscribe.llm.time.sleep"):  # don't actually wait
            result = enhance_transcript("qwen3.6:27b", "go", show_progress=False)
            assert result == "ok"
            assert mock_post.call_count == 3


def test_enhance_no_retry_on_4xx():
    """4xx response: no retry, return None immediately."""
    bad = MagicMock()
    bad.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 400")
    bad.status_code = 400
    with patch("podscribe.llm.requests.post", return_value=bad) as mock_post:
        result = enhance_transcript("qwen3.6:27b", "go", show_progress=False)
        assert result is None
        assert mock_post.call_count == 1


def test_enhance_prints_metrics_to_stderr(capfd):
    """When show_progress=True, print prompt + response tokens + tok/s to stderr."""
    resp = make_streaming_response(
        ["Hi"],
        final_stats={"prompt_eval_count": 7, "eval_count": 1,
                     "total_duration": 1_000_000_000, "eval_duration": 100_000_000},
    )
    with patch("podscribe.llm.requests.post", return_value=resp):
        with patch("podscribe.llm._ollama_model_info", return_value={
            "model_info": {"llama.context_length": 32768}
        }):
            result = enhance_transcript("qwen3.6:27b", "go", show_progress=True)
            assert result == "Hi"
    captured = capfd.readouterr()
    assert "Calling Model:qwen3.6:27b" in captured.err
    assert "Context window size : 32768 tokens" in captured.err
    assert "prompt 7" in captured.err
    assert "response 1 tokens" in captured.err
    assert "tok/s" in captured.err


def test_enhance_uses_30_minute_timeout():
    resp = make_streaming_response(["x"], final_stats={"prompt_eval_count": 1, "eval_count": 1})
    with patch("podscribe.llm.requests.post", return_value=resp) as mock_post:
        enhance_transcript("qwen3.6:27b", "go", show_progress=False)
    assert mock_post.call_args.kwargs["timeout"] == 1800
```

- [ ] **Step 7: Run the new tests to verify they fail**

```bash
pytest tests/test_llm.py -v -k "streams or retries or no_retry or prints_metrics or 30_minute"
```

Expected: 5 failures.

- [ ] **Step 8: Refactor `enhance_transcript` to streaming + retry + progress + metrics**

In `podscribe/llm.py`, replace the `enhance_transcript` function and the imports at the top.

First, update the imports at the top of the file. Find the current imports:

```python
"""Ollama HTTP client for transcript enhancement."""
from __future__ import annotations

import re
from typing import List, Optional

import requests
import yaml
```

Replace with:

```python
"""Ollama HTTP client for transcript enhancement."""
from __future__ import annotations

import json
import re
import sys
import time
from typing import List, Optional

import requests
import yaml
from tqdm import tqdm
```

Then find and replace the existing `enhance_transcript` function (lines 24-42 in the current file) with the new streaming implementation:

```python
OLLAMA_SHOW_URL = "http://localhost:11434/api/show"


def _ollama_model_info(model: str) -> dict:
    """Fetch model details (num_ctx etc.) from /api/show. Best-effort."""
    try:
        r = requests.post(OLLAMA_SHOW_URL, json={"name": model}, timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return {}


def enhance_transcript(
    model: str,
    prompt: str,
    *,
    max_retries: int = 3,
    show_progress: bool = True,
) -> Optional[str]:
    """Stream from Ollama, show progress + metrics, return full text.

    - Uses stream=True so tokens arrive incrementally (no 10-min wait with
      no feedback).
    - Retries up to max_retries on connection errors and 5xx. Does NOT retry
      on 4xx (bad prompt, model not found).
    - timeout=1800s (30 min) — long enough for heavy Qwen analysis.
    - Returns the accumulated text on success, None on failure.
    """
    info = _ollama_model_info(model) if show_progress else {}
    model_details = info.get("model_info") or {}
    num_ctx = model_details.get("llama.context_length", "?")

    payload = {"model": model, "prompt": prompt, "stream": True}
    delays = [1, 2, 4]

    for attempt in range(max_retries):
        try:
            if show_progress:
                sys.stderr.write(f"Calling Model:{model}...\n")
                sys.stderr.write(f"Context window size : {num_ctx} tokens\n")
                sys.stderr.flush()

            resp = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=1800)
            resp.raise_for_status()

            text_parts: list = []
            stats: dict = {}
            bar = None
            if show_progress:
                bar = tqdm(
                    desc=model, unit="tok", file=sys.stderr,
                    mininterval=0.5, dynamic_ncols=True,
                )

            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "response" in chunk:
                    text_parts.append(chunk["response"])
                    if bar is not None:
                        bar.update(1)
                if chunk.get("done"):
                    stats = {
                        "prompt_eval_count": chunk.get("prompt_eval_count", 0),
                        "eval_count": chunk.get("eval_count", 0),
                        "total_duration_ns": chunk.get("total_duration", 0),
                        "eval_duration_ns": chunk.get("eval_duration", 0),
                    }
                    break

            if bar is not None:
                bar.close()

            if show_progress:
                pe = stats.get("prompt_eval_count", 0)
                ec = stats.get("eval_count", 0)
                ed = (stats.get("eval_duration_ns", 0) or 1) / 1e9
                tps = ec / ed if ed > 0 else 0
                total_s = (stats.get("total_duration_ns", 0) or 1) / 1e9
                sys.stderr.write(
                    f"  ✓ done in {total_s:.1f}s | "
                    f"prompt {pe} + response {ec} tokens @ {tps:.1f} tok/s\n"
                )
                sys.stderr.flush()
            return "".join(text_parts)

        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status is not None and 400 <= status < 500:
                return None  # 4xx: don't retry
        except requests.RequestException:
            pass

        if attempt < max_retries - 1:
            time.sleep(delays[attempt])

    return None
```

- [ ] **Step 9: Run all the LLM tests**

```bash
pytest tests/test_llm.py -v
```

Expected: all pass (8 total — 3 updated + 5 new).

- [ ] **Step 10: Run the full suite to confirm no caller breaks**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: 154 tests pass (was 146, +5 new from this task; the 3 existing `test_enhance_transcript_*` tests were updated in place, not added).

- [ ] **Step 11: Commit**

```bash
git add podscribe/llm.py tests/test_llm.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "feat(llm): streaming enhance with tqdm progress, retry, and metrics"
```

---

## Task 11: Meeting ID format HHMMSS (§1.2)

**Files:**
- Modify: `podscribe/models.py:28` (change strftime format)
- Modify: `tests/test_models.py` (update `test_meeting_id_format`)

One-line format change. Adds seconds precision so two same-minute meetings don't collide.

- [ ] **Step 1: Read the existing test**

```bash
grep -n -A 5 "test_meeting_id_format" tests/test_models.py
```

Expected: existing test asserts the HHMM format. Note its exact assertions.

- [ ] **Step 2: Update the existing test**

In `tests/test_models.py`, find `test_meeting_id_format` and update it to expect HHMMSS. The exact edit depends on the existing assertions, but should look like:

```python
def test_meeting_id_format():
    from datetime import datetime
    when = datetime(2026, 6, 22, 14, 30, 12)
    assert make_meeting_id("sam-chen", when) == "2026-06-22-143012-sam-chen"
```

(If other tests in `test_models.py` assert HHMM, update them too. The existing format is `%Y-%m-%d-%H%M-` so search for any string starting with `2026-` and update accordingly.)

- [ ] **Step 3: Run the test to verify it fails**

```bash
pytest tests/test_models.py -v
```

Expected: the updated test fails because the format is still HHMM.

- [ ] **Step 4: Update `make_meeting_id`**

In `podscribe/models.py:28`, change:

```python
    return when.strftime("%Y-%m-%d-%H%M-") + pod_name
```

to:

```python
    return when.strftime("%Y-%m-%d-%H%M%S-") + pod_name
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
pytest tests/test_models.py -v
```

Expected: pass.

- [ ] **Step 6: Run the full suite**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: 143 tests pass (no count change — just an update).

- [ ] **Step 7: Commit**

```bash
git add podscribe/models.py tests/test_models.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "fix(models): add seconds precision to meeting IDs (HHMMSS)"
```

---

## Task 12: Audio write path for `--keep-audio` (§1.1)

**Files:**
- Modify: `podscribe/cli.py` (add `wave` import + wav_writer in `cmd_record`)
- Modify: `tests/test_cli.py` (add tests)

The biggest-blast-radius change. Open a `wave.Wave_write` handle when `--keep-audio` is set, write each captured segment as int16 PCM, close on stop.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, add at the end of the file:

```python
def test_cmd_record_writes_wav_with_keep_audio(tmp_path, monkeypatch):
    """--keep-audio produces a real, replayable WAV file with the right content."""
    import struct
    import wave
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch, MagicMock
    import numpy as np
    from podscribe.storage import init_pod
    from podscribe.cli import cmd_record, build_parser

    pod = init_pod("sam-chen")

    # Simulate one 0.5s segment of float32 audio at 16kHz
    fake_segment = np.zeros(8000, dtype=np.float32)

    # Mock the Transcriber to return a deterministic result
    mock_transcriber = MagicMock()
    mock_transcriber.model_name = "base"
    mock_transcriber.transcribe.return_value = [{"text": "hello", "start": 0, "end": 0.5}]

    mock_capture = MagicMock()
    mock_capture.vad_aggressiveness = 2
    mock_capture.had_overflow = False
    mock_capture.segments.return_value = iter([fake_segment])
    # Auto-stop after one segment
    type(mock_capture)._running = True
    mock_capture.stop = MagicMock(side_effect=lambda: None)

    with patch("podscribe.cli.AudioCapture", return_value=mock_capture):
        with patch("podscribe.cli.Transcriber", return_value=mock_transcriber):
            with patch("podscribe.cli.signal.signal"):  # don't touch SIGINT
                with patch("podscribe.cli.time.monotonic", side_effect=[0.0, 0.5, 0.5]):
                    args = build_parser().parse_args(["record", "sam-chen", "--keep-audio", "--model", "base"])
                    # Avoid the system-input device probe
                    with patch("podscribe.cli.sd"):
                        rc = cmd_record(args)
                        assert rc == 0

    # Find the .raw file
    raw_files = list(tmp_path.glob("pods/sam-chen/transcripts/*/*.raw"))
    assert len(raw_files) == 1
    raw_path = raw_files[0]

    # Verify it's a valid WAV
    with wave.open(str(raw_path), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16000
        frames = w.readframes(w.getnframes())
        assert len(frames) == 8000 * 2  # 8000 samples × 2 bytes


def test_cmd_record_omits_audio_by_default(tmp_path, monkeypatch):
    """Without --keep-audio, no .raw file is created."""
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch, MagicMock
    import numpy as np
    from podscribe.storage import init_pod
    from podscribe.cli import cmd_record, build_parser

    pod = init_pod("sam-chen")

    fake_segment = np.zeros(8000, dtype=np.float32)
    mock_transcriber = MagicMock()
    mock_transcriber.model_name = "base"
    mock_transcriber.transcribe.return_value = [{"text": "hello", "start": 0, "end": 0.5}]
    mock_capture = MagicMock()
    mock_capture.vad_aggressiveness = 2
    mock_capture.had_overflow = False
    mock_capture.segments.return_value = iter([fake_segment])
    mock_capture.stop = MagicMock(side_effect=lambda: None)

    with patch("podscribe.cli.AudioCapture", return_value=mock_capture):
        with patch("podscribe.cli.Transcriber", return_value=mock_transcriber):
            with patch("podscribe.cli.signal.signal"):
                with patch("podscribe.cli.time.monotonic", side_effect=[0.0, 0.5, 0.5]):
                    with patch("podscribe.cli.sd"):
                        args = build_parser().parse_args(["record", "sam-chen", "--model", "base"])
                        rc = cmd_record(args)
                        assert rc == 0

    raw_files = list(tmp_path.glob("pods/sam-chen/transcripts/*/*.raw"))
    assert raw_files == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_cli.py::test_cmd_record_writes_wav_with_keep_audio tests/test_cli.py::test_cmd_record_omits_audio_by_default -v
```

Expected: both fail. The current code does not write to `audio_path`.

- [ ] **Step 3: Add the `wave` import**

In `podscribe/cli.py`, find the imports block (lines 1-15). Add `import wave` after `import argparse`:

```python
import argparse
import signal
import sys
import time
import wave
```

(Alphabetical order: argparse → signal → sys → time → wave.)

- [ ] **Step 4: Open the WAV writer at the top of `cmd_record`**

In `podscribe/cli.py`, find the `cmd_record` function (around line 60). Find the `start_monotonic = time.monotonic()` line (around line 97). Just before that, add:

```python
    wav_writer = None
    if args.keep_audio:
        wav_writer = wave.open(str(meeting.audio_path), "wb")
        wav_writer.setnchannels(1)
        wav_writer.setsampwidth(2)
        wav_writer.setframerate(16000)
```

- [ ] **Step 5: Write each segment as int16 PCM inside the segment loop**

In the same file, find the `for audio_segment in capture.segments():` loop (line 106). At the top of the loop body (just after `for audio_segment in capture.segments():`), add:

```python
        if wav_writer is not None:
            try:
                pcm = np.clip(audio_segment * 32767, -32768, 32767).astype(np.int16)
                wav_writer.writeframes(pcm.tobytes())
            except OSError as e:
                print(f"  ⚠ audio write failed: {e}", file=sys.stderr)
```

(Add `import numpy as np` at the top of cli.py if it's not already there — it likely is, but check.)

- [ ] **Step 6: Close the writer in the `finally` block**

Find the `finally:` block at the end of the `try:` in `cmd_record` (around line 123). After `capture.stop()`, add:

```python
    finally:
        capture.stop()
        if wav_writer is not None:
            wav_writer.close()
        meeting.duration_sec = int(time.monotonic() - start_monotonic)
        ...
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
pytest tests/test_cli.py::test_cmd_record_writes_wav_with_keep_audio tests/test_cli.py::test_cmd_record_omits_audio_by_default -v
```

Expected: both pass.

- [ ] **Step 8: Run the full suite to confirm no regression**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: 156 tests pass (was 154, +2 new from this task).

- [ ] **Step 9: Commit**

```bash
git add podscribe/cli.py tests/test_cli.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "feat(record): --keep-audio now writes a real, replayable WAV file"
```

---

## Final verification

After all 12 tasks are done and committed on `fix/recommended-cleanup`:

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: 156 tests pass, 0 failures. (Pre-PR: 126 offline + 1 smoke; this PR adds 30 new tests across the 12 tasks.)

- [ ] **Step 2: Run the smoke test to confirm it now uses a valid model**

```bash
pytest tests/test_transcriber.py -v 2>&1 | tail -5
```

Expected: 1 test collected. The test will fail if there's no network — that's expected, and AGENTS.md instructs to skip with `-k "not transcriber"`. The fix is that the model name in the test is now valid, so the only reason it fails is the network, not a 401 from a missing model.

- [ ] **Step 3: Verify commit count and order**

```bash
git log main..fix/recommended-cleanup --oneline
```

Expected: exactly 12 commits (one per task), in the order listed above.

- [ ] **Step 4: Push the branch**

```bash
git push -u origin fix/recommended-cleanup
```

(Only if the user has explicitly asked to push. Otherwise stop here and let the user open the PR.)

---

## Self-review

**1. Spec coverage:**

| Spec section | Covered by |
|---|---|
| §1.1 audio write | Task 12 |
| §1.2 HHMMSS | Task 11 |
| §1.3 preserve_speakers | Task 9 |
| §1.4 misleading print | Task 4 |
| §2.1 ambiguous prefix | Task 7 |
| §2.2 empty-transcript guard | Task 5 |
| §2.3 consolidate error-out | Task 6 |
| §2.4 --latest dead code | Task 3 |
| §2.5 case-insensitive glossary | Task 8 |
| §2.7 smoke test | Task 2 |
| §3.3 streaming + progress + metrics | Task 10 |
| §3.6 README | Task 1 |
| Pre-requisite (3 in-flight fixes) | Pre-requisite section |
| Sequencing order | Commit order matches spec |

**2. Placeholder scan:** No "TBD" / "TODO" / "implement later" / "fill in details". Every code step shows the actual code. Every test has its full body.

**3. Type consistency:** `_resolve_meeting` returns `tuple[Meeting | None, str | None]` everywhere it's used. `build_enhance_prompt`'s new `preserve_speakers` kwarg is used consistently (always keyword, default `True`). `enhance_transcript`'s new signature is consistent in all 3 callers (cli.py:284, cli.py:368, cli.py:389 — none pass kwargs, so they all use the new defaults).

**4. Risk:** Task 12 (audio write) is the highest-risk change because it adds an import and modifies the most-touched code path. If anything fails, the audio write is wrapped in try/except so recording still works. The other 11 tasks are surgical.

**5. Test count after PR lands:** 156 offline tests passing (was 126, +30 new net). One test was updated in place (`test_meeting_id_format`). The spec's rough estimate was 22 net new; the plan is more thorough (extra tests for glossary dedup, config validation, and preamble ordering).
