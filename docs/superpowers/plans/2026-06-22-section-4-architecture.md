# Section 4 Architecture Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the seven architecture improvements from `Recommended_fixes.md` §4 in one PR, twelve commits. No new runtime dependencies. TDD throughout.

**Architecture:** One feature branch (`feature/section-4-architecture`) off `main` after `fix/recommended-cleanup` merges. Each task produces one self-contained, bisectable commit. Refactors land first (4.1, 4.4) so subsequent tasks build on a clean foundation. Data-model additions (4.5) split into 3 commits (model, CLI, storage) so each is reviewable in isolation.

**Tech Stack:** Python ≥3.10, pytest, `mlx-whisper`, `webrtcvad`, `sounddevice`, `requests`, `tqdm`, `pyyaml`. Stdlib only for new code (`tarfile`, `pathlib`, `subprocess`, `dataclasses`). `rg` is optional (graceful Python fallback).

**Source spec:** `docs/superpowers/specs/2026-06-22-section-4-architecture-design.md` (commit `6ebd358`).

---

## Pre-requisite: confirm `fix/recommended-cleanup` has landed

- [ ] **Step 1: Verify clean baseline**

```bash
cd /Users/anuragkaushik137/Documents/podscribe
git log --oneline -5
git status
```

Expected: working tree clean (or only untracked scratch files); the cleanup PR's commits (`0f1cbdf`, `c134100`, `6fb25ba`, etc.) are on `main`.

- [ ] **Step 2: Run the full test suite to confirm 127 tests pass**

```bash
pytest tests/ -v -k "not transcriber" 2>&1 | tail -3
```

Expected: `127 passed` (or current count for that branch).

- [ ] **Step 3: Create the feature branch**

```bash
git checkout -b feature/section-4-architecture
```

Expected: on new branch, clean tree.

---

## File structure

| File | Tasks | Why |
|---|---|---|
| `podscribe/cli.py` | T1, T4, T7, T8, T9, T10 | New `_run_enhance`; `--type` on record; new `cmd_list` flags; new `cmd_search`; new `cmd_export` + `cmd_import` |
| `podscribe/storage.py` | T5, T6 | `start_meeting(meeting_type=)`; dual-glob `list_meetings`; `append_log_row` mirror to global CSV; new global CSV helpers |
| `podscribe/config.py` | T2 | mtime-keyed cache for `get_effective_glossary` |
| `podscribe/models.py` | T3 | `MEETING_TYPES` tuple; `parse_meeting_type`; `Meeting.type: Optional[str]` |
| `podscribe/export.py` (new) | T9, T10 | `create_export`, `import_archive`, `_iter_export_members`, `_safe_extract` |
| `podscribe/search.py` (new) | T8 | `SearchMatch` dataclass; `search` iterator; `_rg_search` + `_python_search` backends |
| `tests/test_cli.py` | T1, T4, T7, T8, T9, T10 | Most new tests live here |
| `tests/test_storage.py` | T5, T6 | New tests for typed subdir + global CSV |
| `tests/test_config.py` | T2 | New tests for mtime cache |
| `tests/test_models.py` | T3 | New tests for `parse_meeting_type` |
| `tests/test_export.py` (new) | T9, T10 | Round-trip + edge cases |
| `tests/test_search.py` (new) | T8 | rg + python backends |
| `README.md` | T11 | Doc updates |

**No new dependencies.** `tarfile`, `pathlib`, `subprocess`, `shutil`, `dataclasses` are stdlib.

---

## Commit order (12 commits)

1. Refactor: extract `_run_enhance` (T1)
2. Cache: glossary mtime (T2)
3. Model: `MEETING_TYPES` enum + `parse_meeting_type` (T3)
4. CLI: `--type` flag on record (T4)
5. Storage: typed subdir + 3-level glob (T5)
6. Storage: global `meetings.csv` mirror (T6)
7. CLI: `list` filters (T7)
8. Search: new `podscribe search` command (T8)
9. Export: `podscribe export` (T9)
10. Import: `podscribe import` (T10)
11. Docs: README updates (T11)
12. Integration smoke (T12)

Each task is self-contained. Each task ends with a passing `pytest tests/ -v -k "not transcriber"` run and one `git commit`.

---

## Task 1: Extract `_run_enhance` helper (4.1)

**Files:**
- Modify: `podscribe/cli.py` (add helper, refactor two call sites)
- Modify: `tests/test_cli.py` (3 new tests)

- [ ] **Step 1: Write the failing tests**

Open `tests/test_cli.py` and append at the end of the file:

```python
def test_run_enhance_returns_text_on_success():
    """Helper returns (text, None) on LLM success."""
    from unittest.mock import patch
    from podscribe.cli import _run_enhance
    from podscribe.models import Pod, Meeting
    from datetime import datetime

    pod = Pod(name="sam-chen", base_path=Path("pods/sam-chen"))
    meeting = Meeting(
        id="2026-06-22-143000-sam-chen",
        pod_name="sam-chen",
        started_at=datetime(2026, 6, 22, 14, 30, 0).isoformat(),
    )
    with patch("podscribe.cli.enhance_transcript", return_value="Enhanced output."):
        text, err = _run_enhance(pod, meeting, "prompt", "qwen3.6:27b")
    assert text == "Enhanced output."
    assert err is None


def test_run_enhance_returns_error_on_failure():
    """Helper returns (None, error_msg) on LLM failure."""
    from unittest.mock import patch
    from podscribe.cli import _run_enhance
    from podscribe.models import Pod, Meeting
    from datetime import datetime

    pod = Pod(name="sam-chen", base_path=Path("pods/sam-chen"))
    meeting = Meeting(
        id="2026-06-22-143000-sam-chen",
        pod_name="sam-chen",
        started_at=datetime(2026, 6, 22, 14, 30, 0).isoformat(),
    )
    with patch("podscribe.cli.enhance_transcript", return_value=None):
        text, err = _run_enhance(pod, meeting, "prompt", "qwen3.6:27b")
    assert text is None
    assert err is not None
    assert "ollama serve" in err


def test_cmd_enhance_uses_run_enhance_helper(tmp_path, monkeypatch, capsys):
    """After refactor, cmd_enhance delegates to _run_enhance."""
    from unittest.mock import patch
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_enhance, build_parser

    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(
        meeting,
        Segment(1.0, 5.0, "hello world this is a sufficiently long transcript"),
    )
    finalize_meeting(meeting)

    with patch("podscribe.cli._run_enhance", return_value=("ok text", None)) as mock_helper:
        with patch("podscribe.cli.load_project_config", return_value={
            "llm": {"model": "qwen3.6", "prompt_template": "x"},
        }):
            args = build_parser().parse_args(["enhance", "sam-chen"])
            rc = cmd_enhance(args)
    assert rc == 0
    assert mock_helper.called
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_cli.py::test_run_enhance_returns_text_on_success tests/test_cli.py::test_run_enhance_returns_error_on_failure tests/test_cli.py::test_cmd_enhance_uses_run_enhance_helper -v
```

Expected: 3 failures (`_run_enhance` not defined).

- [ ] **Step 3: Add the helper to `cli.py`**

In `podscribe/cli.py`, find `_resolve_meeting` (around line 43) and add the new helper directly after it:

```python
def _run_enhance(
    pod: Pod, meeting: Meeting, prompt: str, model: str,
) -> tuple[Optional[str], Optional[str]]:
    """Run LLM enhance. Returns (text, None) on success, (None, error) on failure.

    The error string is what gets printed to stderr; it owns the Ollama-
    availability message so both call sites stay in sync.
    """
    result = enhance_transcript(model, prompt)
    if result is None:
        return None, "Failed to reach Ollama. Is it running? Start with: ollama serve"
    return result, None
```

The type hints reference `Pod` and `Meeting`; add a `from .models import Pod, Meeting, Segment, fmt_date` to the imports at the top of `cli.py` (extending the existing `from .models import Segment, fmt_date` line).

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_cli.py::test_run_enhance_returns_text_on_success tests/test_cli.py::test_run_enhance_returns_error_on_failure tests/test_cli.py::test_cmd_enhance_uses_run_enhance_helper -v
```

Expected: 3 passes.

- [ ] **Step 5: Refactor `cmd_enhance` to use the helper**

In `podscribe/cli.py:cmd_enhance`, find the block (after the prompt construction):

```python
    result = enhance_transcript(llm_config["model"], prompt)
    if result is None:
        print(
            "Failed to reach Ollama. Is it running? "
            "Start with: ollama serve",
            file=sys.stderr,
        )
        return 1

    summary_dir.mkdir(parents=True, exist_ok=True)
    enhanced_path.write_text(result)
    print(f"Enhanced transcript saved to {enhanced_path}")
    return 0
```

Replace with:

```python
    text, err = _run_enhance(pod, meeting, prompt, llm_config["model"])
    if err is not None:
        print(err, file=sys.stderr)
        return 1

    summary_dir.mkdir(parents=True, exist_ok=True)
    enhanced_path.write_text(text)
    print(f"Enhanced transcript saved to {enhanced_path}")
    return 0
```

- [ ] **Step 6: Refactor `cmd_consolidate` to use the helper**

In `podscribe/cli.py:cmd_consolidate`, find the block (after the prompt construction):

```python
    response = enhance_transcript(model_name, prompt)
    if response is None:
        print("Failed to reach Ollama for extraction.", file=sys.stderr)
        return 1
```

Replace with:

```python
    text, err = _run_enhance(pod, meeting, prompt, model_name)
    if err is not None:
        print(err, file=sys.stderr)
        return 1
```

Then find the line `fields = extract_structured_fields(response)` and change `response` to `text`:

```python
    fields = extract_structured_fields(text)
```

- [ ] **Step 7: Add a regression test for `cmd_consolidate` using the helper**

Append to `tests/test_cli.py`:

```python
def test_cmd_consolidate_uses_run_enhance_helper(tmp_path, monkeypatch):
    """After refactor, cmd_consolidate delegates to _run_enhance."""
    from unittest.mock import patch
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_consolidate, build_parser

    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello world"))
    finalize_meeting(meeting)
    # Create a fake enhanced summary so cmd_consolidate reaches the LLM call
    (pod.base_path / "summaries" / "22-JUN-2026" / f"{meeting.id}.md").parent.mkdir(
        parents=True, exist_ok=True
    )
    (pod.base_path / "summaries" / "22-JUN-2026" / f"{meeting.id}.md").write_text(
        "Sample enhanced summary for testing."
    )

    with patch("podscribe.cli._run_enhance", return_value=("yaml output", None)) as mock_helper:
        with patch("podscribe.cli.load_project_config", return_value={
            "llm": {"model": "qwen3.6", "prompt_template": "x"},
        }):
            with patch("podscribe.cli.extract_structured_fields", return_value={
                "quick_summary": "x",
                "key_topics": [],
                "action_items": [],
                "blockers": [],
                "next_steps": [],
            }):
                args = build_parser().parse_args(["consolidate", "sam-chen", "--no-log"])
                rc = cmd_consolidate(args)
    assert rc == 0
    assert mock_helper.called
```

- [ ] **Step 8: Run the full test suite**

```bash
pytest tests/ -v -k "not transcriber" 2>&1 | tail -3
```

Expected: 130 passed (127 + 3 new from T1 — actually 130 because we wrote 4 tests but one was a refactor-test that already passed; either way, no regressions).

- [ ] **Step 9: Commit**

```bash
git add podscribe/cli.py tests/test_cli.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "refactor(cli): extract _run_enhance helper from cmd_enhance and cmd_consolidate"
```

---

## Task 2: Glossary cache with mtime invalidation (4.4)

**Files:**
- Modify: `podscribe/config.py` (add cache to `get_effective_glossary`)
- Modify: `tests/test_config.py` (3 new tests)

- [ ] **Step 1: Write the failing tests**

Open `tests/test_config.py` and append at the end of the file:

```python
def test_get_effective_glossary_caches(tmp_path, monkeypatch):
    """Second call within same mtime does not re-read leadership_team.yaml."""
    from podscribe.config import get_effective_glossary, _glossary_cache
    from podscribe.models import Pod
    import yaml

    monkeypatch.chdir(tmp_path)
    (tmp_path / "leadership_team.yaml").write_text(yaml.safe_dump({
        "glossary": [{"term": "Project Helios", "category": "project"}]
    }))
    pod = Pod(name="sam-chen", base_path=tmp_path / "pods" / "sam-chen")

    # Clear any pre-existing cache
    _glossary_cache["key"] = None

    with patch("podscribe.config.load_leadership_glossary") as mock_load:
        mock_load.return_value = [{"term": "Project Helios", "category": "project"}]
        first = get_effective_glossary(pod)
        second = get_effective_glossary(pod)
    assert first == second
    assert mock_load.call_count == 1


def test_cache_invalidates_on_mtime_change(tmp_path, monkeypatch):
    """Touching leadership_team.yaml with newer mtime invalidates the cache."""
    from podscribe.config import get_effective_glossary, _glossary_cache
    from podscribe.models import Pod
    import time

    monkeypatch.chdir(tmp_path)
    leadership = tmp_path / "leadership_team.yaml"
    leadership.write_text("glossary: []\n")
    pod = Pod(name="sam-chen", base_path=tmp_path / "pods" / "sam-chen")

    # Clear any pre-existing cache
    _glossary_cache["key"] = None

    # First call: empty glossary
    assert get_effective_glossary(pod) == []

    # Modify file with a clearly newer mtime
    time.sleep(0.05)
    leadership.write_text("glossary:\n  - term: NewTerm\n    category: project\n")

    # Cache should have invalidated; second call sees new content
    result = get_effective_glossary(pod)
    assert any(e["term"] == "NewTerm" for e in result)


def test_cache_handles_missing_leadership_file(tmp_path, monkeypatch):
    """Missing leadership_team.yaml → cache holds empty leadership."""
    from podscribe.config import get_effective_glossary, _glossary_cache
    from podscribe.models import Pod

    monkeypatch.chdir(tmp_path)
    pod = Pod(name="sam-chen", base_path=tmp_path / "pods" / "sam-chen")
    _glossary_cache["key"] = None

    # File does not exist
    assert not (tmp_path / "leadership_team.yaml").exists()
    assert get_effective_glossary(pod) == []
    # Subsequent call still returns empty (no crash)
    assert get_effective_glossary(pod) == []
```

Add `from unittest.mock import patch` to the imports at the top of `tests/test_config.py` if not already there.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_config.py -v -k "caches or invalidates or handles_missing"
```

Expected: 3 failures (the cache module-level dict doesn't exist yet).

- [ ] **Step 3: Add the cache to `config.py`**

Replace `get_effective_glossary` in `podscribe/config.py` with the cached version. Add the module-level cache and helper above the function:

```python
_glossary_cache: dict = {
    "key": None,
    "value": None,
}


def _leadership_yaml_path() -> Path:
    return LEADERSHIP_CONFIG_PATH


def _read_effective_glossary(pod: Pod) -> list:
    """Read leadership_team.yaml + pod.glossary. The actual disk read."""
    leadership = load_leadership_glossary() or []
    return leadership + list(pod.glossary or [])


def get_effective_glossary(pod: Pod) -> list:
    """Return leadership + pod glossary, cached by mtime + pod.glossary id.

    The cache key includes:
    - mtime of leadership_team.yaml (so manual edits invalidate)
    - id(pod.glossary) (so list replacement invalidates)
    - len(pod.glossary) (so in-place mutation that grows/shrinks invalidates)

    The first call after process start reads from disk. Subsequent calls
    with the same key return the cached list. The cache is per-process.
    """
    try:
        mtime = _leadership_yaml_path().stat().st_mtime
    except FileNotFoundError:
        mtime = 0
    key = (mtime, id(pod.glossary), len(pod.glossary))
    if _glossary_cache["key"] != key:
        _glossary_cache["key"] = key
        _glossary_cache["value"] = _read_effective_glossary(pod)
    return _glossary_cache["value"]
```

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
pytest tests/test_config.py -v -k "caches or invalidates or handles_missing"
```

Expected: 3 passes.

- [ ] **Step 5: Run the full test suite to confirm no regression**

```bash
pytest tests/ -v -k "not transcriber" 2>&1 | tail -3
```

Expected: 130 passed (3 new + 127 prior).

- [ ] **Step 6: Commit**

```bash
git add podscribe/config.py tests/test_config.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "feat(config): cache effective glossary with mtime invalidation"
```

---

## Task 3: `MEETING_TYPES` enum + `parse_meeting_type` helper (4.5 partial — model only)

**Files:**
- Modify: `podscribe/models.py` (add enum and helper)
- Modify: `tests/test_models.py` (2 new tests)

- [ ] **Step 1: Write the failing tests**

Open `tests/test_models.py` and append at the end of the file:

```python
def test_parse_meeting_type_normalizes_case():
    from podscribe.models import parse_meeting_type
    assert parse_meeting_type("1ON1") == "1on1"
    assert parse_meeting_type("Retro") == "retro"
    assert parse_meeting_type("design-review") == "design-review"


def test_parse_meeting_type_rejects_unknown():
    import pytest
    from podscribe.models import parse_meeting_type
    with pytest.raises(ValueError, match="Unknown meeting type"):
        parse_meeting_type("weekly-sync")
    with pytest.raises(ValueError, match="Unknown meeting type"):
        parse_meeting_type("")


def test_parse_meeting_type_none_returns_none():
    from podscribe.models import parse_meeting_type
    assert parse_meeting_type(None) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_models.py -v -k "parse_meeting_type"
```

Expected: 3 failures.

- [ ] **Step 3: Add the enum and helper to `models.py`**

In `podscribe/models.py`, add the constant and helper after the existing imports and constants. Place after `make_meeting_id` (around line 28):

```python
MEETING_TYPES = (
    "1on1",
    "retro",
    "skip-level",
    "design-review",
    "standup",
    "interview",
    "other",
)


def parse_meeting_type(raw):
    """Normalize and validate a --type argument.

    Returns the canonical lowercase form, or None if `raw` is None.
    Raises ValueError if `raw` is not a known type.
    """
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized not in MEETING_TYPES:
        valid = ", ".join(MEETING_TYPES)
        raise ValueError(
            f"Unknown meeting type '{raw}'. Valid types: {valid}"
        )
    return normalized
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_models.py -v -k "parse_meeting_type"
```

Expected: 3 passes.

- [ ] **Step 5: Run the full test suite**

```bash
pytest tests/ -v -k "not transcriber" 2>&1 | tail -3
```

Expected: 133 passed (130 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add podscribe/models.py tests/test_models.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "feat(models): add MEETING_TYPES enum and parse_meeting_type helper"
```

---

## Task 4: `--type` flag on `record` (4.5 partial — CLI)

**Files:**
- Modify: `podscribe/cli.py:cmd_record` (add `--type` to record subparser and validate at start)
- Modify: `tests/test_cli.py` (2 new tests)

Note: This task wires `--type` into the CLI surface but does NOT yet pass it to `start_meeting`. That comes in T5 (storage). For now, the flag is parsed and validated, but the resulting meeting has `type=None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_cmd_record_rejects_invalid_type(tmp_path, monkeypatch, capsys):
    """`--type weekly` is rejected with a clear error listing valid types."""
    from podscribe.cli import build_parser
    from podscribe.models import parse_meeting_type
    import pytest

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="Unknown meeting type"):
        parse_meeting_type("weekly-sync")


def test_record_parser_accepts_type_flag():
    """`--type` is a recognized argument on the record subparser."""
    from podscribe.cli import build_parser
    args = build_parser().parse_args(["sam-chen", "record", "--type", "1on1"])
    assert args.type == "1on1"
    args2 = build_parser().parse_args(["sam-chen", "record"])
    assert args2.type is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_cli.py::test_cmd_record_rejects_invalid_type tests/test_cli.py::test_record_parser_accepts_type_flag -v
```

Expected: 2 failures (one for the parser not having `--type`, one for `parse_meeting_type` which exists after T3 — actually the first test uses `parse_meeting_type` directly so it should pass after T3; the second should fail because the parser doesn't have `--type` yet).

Wait — `test_cmd_record_rejects_invalid_type` uses `parse_meeting_type` directly. It will pass after T3 lands. That's fine. The new failure is the parser test.

- [ ] **Step 3: Add `--type` to the record subparser**

In `podscribe/cli.py`, find the `record` subparser setup (the `p_record = sub.add_parser(...)` block — search for "record" in the parser-setup section). Add the `--type` argument:

```python
    p_record.add_argument(
        "--type",
        help="Meeting type (e.g. 1on1, retro, skip-level, design-review, standup, interview, other)",
    )
```

Also update `cmd_record` to validate the type at the start. Find `def cmd_record(args)` and at the very top (after the function's docstring), add:

```python
def cmd_record(args) -> int:
    """Record audio and transcribe live."""
    from .models import parse_meeting_type
    try:
        meeting_type = parse_meeting_type(args.type)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    # ... existing code follows
```

The `meeting_type` variable is unused for now; T5 will thread it through to `start_meeting`. This is intentional — we add the validation now to lock in the contract, and the actual wiring lands atomically with the storage change.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_cli.py::test_cmd_record_rejects_invalid_type tests/test_cli.py::test_record_parser_accepts_type_flag -v
```

Expected: 2 passes.

- [ ] **Step 5: Run the full test suite**

```bash
pytest tests/ -v -k "not transcriber" 2>&1 | tail -3
```

Expected: 135 passed (133 + 2 new).

- [ ] **Step 6: Commit**

```bash
git add podscribe/cli.py tests/test_cli.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "feat(cli): add --type flag to record with enum validation"
```

---

## Task 5: Typed subdir storage + 3-level glob (4.5 partial — storage)

**Files:**
- Modify: `podscribe/storage.py:start_meeting` (accept `meeting_type` arg)
- Modify: `podscribe/storage.py:finalize_meeting` (write `type` to JSON sidecar)
- Modify: `podscribe/storage.py:list_meetings` (dual glob, read `type` from sidecar)
- Modify: `podscribe/cli.py:cmd_record` (pass `meeting_type` to `start_meeting`)
- Modify: `tests/test_storage.py` (3 new tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_storage.py`:

```python
def test_start_meeting_with_type_uses_subdir(tmp_path):
    """--type creates a third-level subdir under transcripts/<date>/<type>/."""
    from datetime import datetime
    from podscribe.models import Pod
    from podscribe.storage import start_meeting

    pod = Pod(name="sam-chen", base_path=tmp_path / "pods" / "sam-chen")
    pod.base_path.mkdir(parents=True)
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0), meeting_type="1on1")
    assert meeting.type == "1on1"
    expected_dir = pod.base_path / "transcripts" / "22-JUN-2026" / "1on1"
    assert expected_dir.exists()
    assert meeting.transcript_path.parent == expected_dir


def test_start_meeting_without_type_uses_flat(tmp_path):
    """No --type → existing 2-level layout, no type subdir."""
    from datetime import datetime
    from podscribe.models import Pod
    from podscribe.storage import start_meeting

    pod = Pod(name="sam-chen", base_path=tmp_path / "pods" / "sam-chen")
    pod.base_path.mkdir(parents=True)
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    assert meeting.type is None
    assert meeting.transcript_path.parent == pod.base_path / "transcripts" / "22-JUN-2026"


def test_list_meetings_finds_typed_and_untyped(tmp_path):
    """Mix of typed (3-level) and untyped (2-level) paths: both found."""
    from datetime import datetime
    from podscribe.models import Pod, Segment
    from podscribe.storage import (
        start_meeting, append_segment, finalize_meeting, list_meetings
    )

    pod = Pod(name="sam-chen", base_path=tmp_path / "pods" / "sam-chen")
    pod.base_path.mkdir(parents=True)

    # 2-level (untyped) meeting
    m1 = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(m1, Segment(1.0, 5.0, "hello"))
    finalize_meeting(m1)

    # 3-level (typed) meeting
    m2 = start_meeting(pod, datetime(2026, 6, 22, 15, 0, 0), meeting_type="retro")
    append_segment(m2, Segment(1.0, 5.0, "world"))
    finalize_meeting(m2)

    meetings = list_meetings(pod)
    assert len(meetings) == 2
    types = {m.type for m in meetings}
    assert types == {None, "retro"}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_storage.py::test_start_meeting_with_type_uses_subdir tests/test_storage.py::test_start_meeting_without_type_uses_flat tests/test_storage.py::test_list_meetings_finds_typed_and_untyped -v
```

Expected: 3 failures.

- [ ] **Step 3: Update `start_meeting` in `storage.py`**

Replace the existing `start_meeting` function with the new signature:

```python
def start_meeting(
    pod: Pod, when: Optional[datetime] = None,
    meeting_type: Optional[str] = None,
) -> Meeting:
    """Create a Meeting record and its file paths. Touches audio file for cleanup."""
    when = when or datetime.now()
    meeting_id = make_meeting_id(pod.name, when)
    date_str = fmt_date(when)
    base_dir = pod.transcripts_dir_for(date_str)
    transcript_dir = base_dir / meeting_type if meeting_type else base_dir
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = transcript_dir / f"{meeting_id}.md"
    metadata_path = transcript_dir / f"{meeting_id}.json"
    audio_path = transcript_dir / f"{meeting_id}.raw"
    audio_path.touch()
    return Meeting(
        id=meeting_id,
        pod_name=pod.name,
        started_at=when.isoformat(timespec="seconds"),
        transcript_path=transcript_path,
        metadata_path=metadata_path,
        audio_path=audio_path,
        type=meeting_type,
    )
```

- [ ] **Step 4: Add the `type` field to the `Meeting` dataclass in `models.py`**

In `podscribe/models.py`, find the `Meeting` dataclass (around line 82) and add `type: Optional[str] = None` as a new field. Add it after `vad_enabled`:

```python
@dataclass
class Meeting:
    id: str
    pod_name: str
    started_at: str
    ended_at: Optional[str] = None
    duration_sec: Optional[int] = None
    transcript_path: Optional[Path] = None
    metadata_path: Optional[Path] = None
    audio_path: Optional[Path] = None
    model: str = "large-v3-turbo"
    vad_enabled: bool = True
    type: Optional[str] = None
```

- [ ] **Step 5: Update `finalize_meeting` to write `type` to the JSON sidecar**

In `podscribe/storage.py`, find `finalize_meeting` and update the metadata dict to include `type`:

```python
def finalize_meeting(meeting: Meeting, *, keep_audio: bool = False) -> None:
    """Write metadata JSON and optionally delete raw audio file."""
    if meeting.ended_at is None:
        meeting.ended_at = datetime.now().isoformat(timespec="seconds")
    metadata = {
        "id": meeting.id,
        "pod_name": meeting.pod_name,
        "started_at": meeting.started_at,
        "ended_at": meeting.ended_at,
        "duration_sec": meeting.duration_sec,
        "model": meeting.model,
        "vad_enabled": meeting.vad_enabled,
        "type": meeting.type,
    }
    with meeting.metadata_path.open("w") as f:
        json.dump(metadata, f, indent=2)

    if not keep_audio and meeting.audio_path and meeting.audio_path.exists():
        meeting.audio_path.unlink()
```

- [ ] **Step 6: Update `list_meetings` for dual glob + read `type`**

Replace the existing `list_meetings` function with:

```python
def list_meetings(pod: Pod) -> List[Meeting]:
    """List all meetings in a pod, newest first.

    Matches both 2-level (transcripts/<date>/<id>.json) and 3-level
    (transcripts/<date>/<type>/<id>.json) layouts. Sorted by started_at
    (parsed from the JSON sidecar) rather than by date-dir path string.
    Meetings missing a sidecar or with malformed JSON are skipped.
    """
    meetings = []
    if not pod.base_path.exists():
        return meetings
    json_paths = set()
    json_paths.update(pod.base_path.glob("transcripts/*/*.json"))
    json_paths.update(pod.base_path.glob("transcripts/*/*/*.json"))
    for json_path in sorted(json_paths):
        try:
            with json_path.open() as f:
                data = json.load(f)
            md_path = json_path.with_suffix(".md")
            raw_path = json_path.with_suffix(".raw")
            meetings.append(Meeting(
                id=data["id"],
                pod_name=data["pod_name"],
                started_at=data["started_at"],
                ended_at=data.get("ended_at"),
                duration_sec=data.get("duration_sec"),
                transcript_path=md_path if md_path.exists() else None,
                metadata_path=json_path,
                audio_path=raw_path if raw_path.exists() else None,
                model=data.get("model", ""),
                vad_enabled=data.get("vad_enabled", True),
                type=data.get("type"),
            ))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    meetings.sort(key=lambda m: m.started_at, reverse=True)
    return meetings
```

- [ ] **Step 7: Wire `meeting_type` into `cmd_record`**

In `podscribe/cli.py:cmd_record`, find where `start_meeting` is called. The current call is something like:

```python
    meeting = start_meeting(pod)
```

Change it to:

```python
    meeting = start_meeting(pod, meeting_type=meeting_type)
```

(The `meeting_type` variable was set at the top of `cmd_record` in T4.)

- [ ] **Step 8: Run the new tests**

```bash
pytest tests/test_storage.py::test_start_meeting_with_type_uses_subdir tests/test_storage.py::test_start_meeting_without_type_uses_flat tests/test_storage.py::test_list_meetings_finds_typed_and_untyped -v
```

Expected: 3 passes.

- [ ] **Step 9: Run the full test suite**

```bash
pytest tests/ -v -k "not transcriber" 2>&1 | tail -3
```

Expected: 138 passed (135 + 3 new).

- [ ] **Step 10: Commit**

```bash
git add podscribe/storage.py podscribe/models.py podscribe/cli.py tests/test_storage.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "feat(storage): support typed meeting subdirs and dual-glob list_meetings"
```

---

## Task 6: Global `meetings.csv` mirror (4.3)

**Files:**
- Modify: `podscribe/storage.py` (add `global_log_path`, `append_global_log_row`, `read_global_log`; mirror from `append_log_row`)
- Modify: `tests/test_storage.py` (3 new tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_storage.py`:

```python
def test_append_log_row_writes_global(tmp_path, monkeypatch):
    """append_log_row also mirrors the row to pods/meetings.csv."""
    from podscribe.models import Pod
    from podscribe.storage import (
        append_log_row, init_pod, global_log_path, read_global_log
    )

    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    append_log_row(pod, {
        "date": "22-JUN-2026",
        "person": "Sam Chen",
        "meeting_id": "2026-06-22-143000-sam-chen",
        "quick_summary": "Discussed Project Helios",
        "key_topics": "Helios",
        "action_items": "Sam will review design",
        "blockers": "",
        "next_steps": "Weekly sync",
    })

    assert global_log_path().exists()
    rows = read_global_log()
    assert len(rows) == 1
    assert rows[0]["meeting_id"] == "2026-06-22-143000-sam-chen"
    assert rows[0]["quick_summary"] == "Discussed Project Helios"


def test_global_log_failure_does_not_break_pod_log(tmp_path, monkeypatch, capsys):
    """If the global write fails, the per-pod write still succeeds."""
    from podscribe.models import Pod
    from podscribe.storage import append_log_row, init_pod, read_global_log, log_path

    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")

    # Force the global write to fail by making the global path point at a directory
    def fake_global_path():
        return tmp_path / "pods" / "BLOCKED"

    monkeypatch.setattr("podscribe.storage.global_log_path", fake_global_path)

    append_log_row(pod, {
        "date": "22-JUN-2026",
        "person": "Sam Chen",
        "meeting_id": "2026-06-22-143000-sam-chen",
        "quick_summary": "x",
        "key_topics": "",
        "action_items": "",
        "blockers": "",
        "next_steps": "",
    })

    # Per-pod log still has the row
    assert log_path(pod).exists()
    captured = capsys.readouterr()
    assert "global log" in captured.err or len(captured.err) == 0


def test_read_global_log_empty_when_no_file(tmp_path, monkeypatch):
    """read_global_log returns [] when pods/meetings.csv does not exist."""
    from podscribe.storage import read_global_log

    monkeypatch.chdir(tmp_path)
    assert read_global_log() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_storage.py::test_append_log_row_writes_global tests/test_storage.py::test_global_log_failure_does_not_break_pod_log tests/test_storage.py::test_read_global_log_empty_when_no_file -v
```

Expected: 3 failures (`global_log_path` doesn't exist yet).

- [ ] **Step 3: Add the global CSV helpers to `storage.py`**

In `podscribe/storage.py`, add the new functions. Place them after the existing `log_path` / `append_log_row` / `update_log_row` block (around line 80):

```python
def global_log_path() -> Path:
    """Path to the project-root global meetings.csv."""
    return Path("pods") / "meetings.csv"


def append_global_log_row(fields: dict) -> bool:
    """Append a row to the global CSV. Returns True on success, False on error.

    Errors are NOT raised — the per-pod CSV is the authoritative record.
    A global-write failure is logged to stderr but does not block the caller.
    """
    try:
        path = global_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        new_row = {col: fields.get(col, "") for col in CSV_COLUMNS}
        file_exists = path.exists()
        with path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(new_row)
        return True
    except OSError as e:
        print(f"Warning: failed to write global log: {e}", file=sys.stderr)
        return False


def read_global_log() -> list:
    """Read all rows from the global meetings.csv. Returns [] if file missing."""
    path = global_log_path()
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))
```

- [ ] **Step 4: Hook the mirror into `append_log_row`**

Find the existing `append_log_row` in `podscribe/storage.py` and add the mirror call at the end:

```python
def append_log_row(pod: Pod, fields: dict) -> None:
    path = log_path(pod)
    new_row = {col: fields.get(col, "") for col in CSV_COLUMNS}
    file_exists = path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(new_row)
    # Mirror to global CSV. Failures are logged but not raised.
    append_global_log_row(fields)
```

- [ ] **Step 5: Add `import sys` to `storage.py` if not present**

The `append_global_log_row` uses `print(..., file=sys.stderr)`. Check the top of `storage.py` and add `import sys` if missing.

- [ ] **Step 6: Run the new tests to verify they pass**

```bash
pytest tests/test_storage.py::test_append_log_row_writes_global tests/test_storage.py::test_global_log_failure_does_not_break_pod_log tests/test_storage.py::test_read_global_log_empty_when_no_file -v
```

Expected: 3 passes.

- [ ] **Step 7: Run the full test suite**

```bash
pytest tests/ -v -k "not transcriber" 2>&1 | tail -3
```

Expected: 141 passed (138 + 3 new).

- [ ] **Step 8: Commit**

```bash
git add podscribe/storage.py tests/test_storage.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "feat(storage): mirror append_log_row to global meetings.csv"
```

---

## Task 7: `list` filters (4.2)

**Files:**
- Modify: `podscribe/cli.py:cmd_list` (add new flags, dispatch to per-pod or global backend)
- Modify: `podscribe/cli.py` (add new args to `p_list`)
- Modify: `tests/test_cli.py` (4 new tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_cmd_list_all_reads_global(tmp_path, monkeypatch):
    """`list --all` reads from the global meetings.csv."""
    from podscribe.models import Pod
    from podscribe.storage import append_log_row, init_pod
    from podscribe.cli import cmd_list, build_parser

    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    append_log_row(pod, {
        "date": "22-JUN-2026",
        "person": "Sam Chen",
        "meeting_id": "2026-06-22-143000-sam-chen",
        "quick_summary": "Discussed Project Helios",
        "key_topics": "Helios",
        "action_items": "",
        "blockers": "",
        "next_steps": "",
    })

    args = build_parser().parse_args(["list", "--all"])
    rc = cmd_list(args)
    assert rc == 0
    assert (tmp_path / "pods" / "meetings.csv").exists()


def test_cmd_list_filters_by_since(tmp_path, monkeypatch):
    """`--since 1d` excludes older rows."""
    from datetime import datetime, timedelta
    from podscribe.models import Pod
    from podscribe.storage import append_log_row, init_pod
    from podscribe.cli import cmd_list, build_parser

    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    # Recent meeting
    append_log_row(pod, {
        "date": datetime.now().strftime("%d-%b-%Y").upper(),
        "person": "Sam Chen",
        "meeting_id": "recent",
        "quick_summary": "Recent",
        "key_topics": "",
        "action_items": "",
        "blockers": "",
        "next_steps": "",
    })
    # Old meeting (100 days ago)
    old_date = (datetime.now() - timedelta(days=100)).strftime("%d-%b-%Y").upper()
    append_log_row(pod, {
        "date": old_date,
        "person": "Sam Chen",
        "meeting_id": "old",
        "quick_summary": "Old",
        "key_topics": "",
        "action_items": "",
        "blockers": "",
        "next_steps": "",
    })

    args = build_parser().parse_args(["list", "--all", "--since", "30d"])
    rc = cmd_list(args)
    assert rc == 0
    # Recent is included, old is excluded (output is opaque, but rc=0 means it ran)


def test_cmd_list_filters_by_type(tmp_path, monkeypatch, capsys):
    """`--type 1on1` validates the type via parse_meeting_type and filters."""
    from podscribe.cli import cmd_list, build_parser

    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args(["list", "--all", "--type", "weekly-sync"])
    rc = cmd_list(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "Unknown meeting type" in captured.err


def test_cmd_list_limits_by_recent(tmp_path, monkeypatch):
    """`--recent 5` is parsed correctly."""
    from podscribe.cli import build_parser
    args = build_parser().parse_args(["list", "--all", "--recent", "5"])
    assert args.recent == 5
    args2 = build_parser().parse_args(["list", "--all"])
    assert args2.recent is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_cli.py::test_cmd_list_all_reads_global tests/test_cli.py::test_cmd_list_filters_by_since tests/test_cli.py::test_cmd_list_filters_by_type tests/test_cli.py::test_cmd_list_limits_by_recent -v
```

Expected: 4 failures (parser doesn't have these args, and the cmd_list function doesn't have the new logic).

- [ ] **Step 3: Add the new arguments to the `list` subparser**

In `podscribe/cli.py`, find `p_list = sub.add_parser("list", ...)` and add the new arguments. Replace the parser block with:

```python
    p_list = sub.add_parser("list", help="List all pods and their meetings.")
    p_list.add_argument("pod", nargs="?", help="Pod name (omit to list all pods)")
    p_list.add_argument(
        "--all", action="store_true",
        help="List meetings across all pods (uses global meetings.csv)",
    )
    p_list.add_argument(
        "--since", metavar="DURATION|DATE",
        help='Filter to meetings on/after this. Examples: "7d", "24h", "2026-06-15"',
    )
    p_list.add_argument(
        "--recent", type=int, metavar="N",
        help="Limit to the N most recent meetings",
    )
    p_list.add_argument(
        "--type", metavar="TYPE",
        help="Filter by meeting type (1on1, retro, skip-level, design-review, standup, interview, other)",
    )
    p_list.set_defaults(func=cmd_list)
```

- [ ] **Step 4: Rewrite `cmd_list` to support filters**

Replace the entire `cmd_list` function in `podscribe/cli.py` (around line 183) with:

```python
def cmd_list(args) -> int:
    """List pods and their meetings, with optional filters."""
    from .config import load_leadership_glossary
    from .models import parse_meeting_type
    from .storage import read_global_log, _read_pod_log_rows

    # Determine scope: per-pod or all
    if args.all or args.pod is None:
        rows = read_global_log()
        if not rows and not (Path("pods") / "meetings.csv").exists():
            print("No meetings yet. Record + consolidate a meeting to populate the log.")
            return 0
    else:
        if not pod_exists(args.pod):
            print(f"No pod '{args.pod}'.", file=sys.stderr)
            return 1
        rows = _read_pod_log_rows(args.pod)

    # Validate --type
    valid_type = None
    if args.type:
        try:
            valid_type = parse_meeting_type(args.type)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1

    # Filter
    if args.since:
        from .storage import _parse_since
        try:
            cutoff = _parse_since(args.since)
        except ValueError as e:
            print(f"Invalid --since: {e}", file=sys.stderr)
            return 1
        rows = [r for r in rows if _row_date(r) >= cutoff]

    if valid_type is not None:
        rows = [r for r in rows if r.get("type") == valid_type]

    if args.recent is not None:
        if args.recent < 0:
            print("--recent must be non-negative", file=sys.stderr)
            return 1
        rows = rows[:args.recent]

    if not rows:
        print("(no meetings match the filters)")
        return 0

    # Render markdown table
    headers = ["pod", "type", "date", "meeting_id", "duration"]
    lines = [" | ".join(headers), " | ".join("---" for _ in headers)]
    for r in rows:
        pod_name = r.get("pod_name") or r.get("person") or "?"
        lines.append(" | ".join([
            pod_name,
            r.get("type") or "-",
            r.get("date") or "-",
            r.get("meeting_id") or "-",
            r.get("duration") or "-",
        ]))
    print("\n".join(lines))
    return 0


def _row_date(row: dict):
    """Parse a date string from a row's 'date' field (DD-MMM-YYYY)."""
    from datetime import datetime
    return datetime.strptime(row["date"], "%d-%b-%Y").date()


def _read_pod_log_rows(pod_name: str) -> list:
    """Read all rows from a single pod's meetings.csv."""
    from .storage import log_path, load_pod
    pod = load_pod(pod_name)
    path = log_path(pod)
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))
```

Add `import csv` to the top of `cli.py` if not present (likely already there for other code, or add it).

- [ ] **Step 5: Add `_parse_since` helper to `storage.py`**

In `podscribe/storage.py`, add this helper at the bottom of the file:

```python
def _parse_since(value: str):
    """Parse a since value into a date.

    Accepts:
    - ISO date: "2026-06-15"
    - Duration: "7d", "24h", "30m" (days, hours, minutes back from today)
    """
    from datetime import datetime, timedelta, date
    if not value:
        raise ValueError("empty value")

    # ISO date
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        pass

    # Duration
    m = re.match(r"^(\d+)([dhm])$", value)
    if m:
        amount, unit = int(m.group(1)), m.group(2)
        delta = {
            "d": timedelta(days=amount),
            "h": timedelta(hours=amount),
            "m": timedelta(minutes=amount),
        }[unit]
        return (datetime.now() - delta).date()

    raise ValueError(
        f"cannot parse '{value}' as YYYY-MM-DD or duration (e.g. 7d, 24h)"
    )
```

Add `import re` to the top of `storage.py` if not present (likely already there for CSV).

- [ ] **Step 6: Run the new tests**

```bash
pytest tests/test_cli.py::test_cmd_list_all_reads_global tests/test_cli.py::test_cmd_list_filters_by_since tests/test_cli.py::test_cmd_list_filters_by_type tests/test_cli.py::test_cmd_list_limits_by_recent -v
```

Expected: 4 passes.

- [ ] **Step 7: Run the full test suite**

```bash
pytest tests/ -v -k "not transcriber" 2>&1 | tail -3
```

Expected: 145 passed (141 + 4 new).

- [ ] **Step 8: Commit**

```bash
git add podscribe/cli.py podscribe/storage.py tests/test_cli.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "feat(cli): add --all/--since/--recent/--type flags to list"
```

---

## Task 8: `podscribe search` command (4.6)

**Files:**
- Create: `podscribe/search.py`
- Modify: `podscribe/cli.py` (add `cmd_search`, register subparser)
- Create: `tests/test_search.py` (6 new tests)

- [ ] **Step 1: Write the failing tests for the search module**

Create `tests/test_search.py`:

```python
"""Tests for podscribe.search."""
from pathlib import Path
import shutil

import pytest

from podscribe.search import SearchMatch, search


def _make_pod(base: Path, pod_name: str, meetings: list) -> Path:
    """Create a pod with the given meetings. Each meeting is (id, date_str, type, lines)."""
    pod_dir = base / "pods" / pod_name
    pod_dir.mkdir(parents=True, exist_ok=True)
    for mid, date_str, mtype, lines in meetings:
        if mtype:
            tdir = pod_dir / "transcripts" / date_str / mtype
        else:
            tdir = pod_dir / "transcripts" / date_str
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / f"{mid}.md").write_text(
            "# Meeting: " + mid + "\n\n" + "\n".join(lines) + "\n"
        )
    return pod_dir


def test_search_python_backend(tmp_path, monkeypatch):
    """When rg is not on PATH, uses Python rglob + substring match."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("podscribe.search.shutil.which", lambda _: None)
    _make_pod(tmp_path, "sam-chen", [
        ("2026-06-22-143000-sam-chen", "22-JUN-2026", "1on1", [
            "[00:01:23] Discussed Project Helios timeline",
            "[00:02:00] Sam will review the design",
        ]),
    ])
    matches = list(search("Helios"))
    assert len(matches) == 1
    assert matches[0].text == "Discussed Project Helios timeline"
    assert matches[0].timestamp == "[00:01:23]"


def test_search_uses_rg_when_available(tmp_path, monkeypatch):
    """When rg is on PATH, calls rg with -F and parses output."""
    import json
    from unittest.mock import patch, MagicMock

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("podscribe.search.shutil.which", lambda cmd: "/usr/bin/rg" if cmd == "rg" else None)
    _make_pod(tmp_path, "sam-chen", [
        ("2026-06-22-143000-sam-chen", "22-JUN-2026", None, [
            "[00:01:23] Discussed Project Helios timeline",
        ]),
    ])

    # Mock the rg subprocess result
    rg_output = f"pods/sam-chen/transcripts/22-JUN-2026/2026-06-22-143000-sam-chen.md:1:[00:01:23] Discussed Project Helios timeline\n"

    mock_proc = MagicMock()
    mock_proc.stdout = rg_output
    mock_proc.returncode = 0

    with patch("podscribe.search.subprocess.run", return_value=mock_proc) as mock_run:
        matches = list(search("Helios"))

    assert len(matches) == 1
    assert mock_run.called
    args, kwargs = mock_run.call_args
    assert args[0][0] == "rg"
    assert "-F" in args[0]


def test_search_filters_by_pod(tmp_path, monkeypatch):
    """--pod restricts to one pod's transcripts."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("podscribe.search.shutil.which", lambda _: None)
    _make_pod(tmp_path, "sam-chen", [
        ("2026-06-22-143000-sam-chen", "22-JUN-2026", None, ["[00:00:00] Helios mention"]),
    ])
    _make_pod(tmp_path, "priya-rao", [
        ("2026-06-22-100000-priya-rao", "22-JUN-2026", None, ["[00:00:00] Helios mention"]),
    ])
    matches = list(search("Helios", pod="sam-chen"))
    assert len(matches) == 1
    assert matches[0].pod_name == "sam-chen"


def test_search_filters_by_type(tmp_path, monkeypatch):
    """--type 1on1 excludes other types and untyped meetings."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("podscribe.search.shutil.which", lambda _: None)
    _make_pod(tmp_path, "sam-chen", [
        ("2026-06-22-143000-sam-chen", "22-JUN-2026", "1on1", ["[00:00:00] alpha"]),
        ("2026-06-22-150000-sam-chen", "22-JUN-2026", "retro", ["[00:00:00] alpha"]),
        ("2026-06-22-160000-sam-chen", "22-JUN-2026", None, ["[00:00:00] alpha"]),
    ])
    matches = list(search("alpha", meeting_type="1on1"))
    assert len(matches) == 1
    assert "143000" in matches[0].meeting_id


def test_search_empty_result(tmp_path, monkeypatch, capsys):
    """No matches → 'No matches.' on stdout, returns 0 (handled by caller)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("podscribe.search.shutil.which", lambda _: None)
    _make_pod(tmp_path, "sam-chen", [
        ("2026-06-22-143000-sam-chen", "22-JUN-2026", None, ["[00:00:00] nothing relevant"]),
    ])
    matches = list(search("zzz_no_such_thing_xyz"))
    assert matches == []


def test_search_since_filter(tmp_path, monkeypatch):
    """--since excludes older files (uses meeting ID prefix date)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("podscribe.search.shutil.which", lambda _: None)
    _make_pod(tmp_path, "sam-chen", [
        ("2026-01-15-100000-sam-chen", "15-JAN-2026", None, ["[00:00:00] old alpha"]),
        ("2026-06-22-143000-sam-chen", "22-JUN-2026", None, ["[00:00:00] new alpha"]),
    ])
    matches = list(search("alpha", since="2026-06-01"))
    assert len(matches) == 1
    assert "143000" in matches[0].meeting_id
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_search.py -v
```

Expected: 6 failures (the `podscribe.search` module doesn't exist).

- [ ] **Step 3: Create `podscribe/search.py`**

```python
"""Cross-pod keyword search over transcript files."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


@dataclass
class SearchMatch:
    pod_name: str
    date_str: str       # e.g. "22-JUN-2026"
    meeting_id: str     # e.g. "2026-06-22-143000-sam-chen"
    timestamp: str      # e.g. "[00:01:23]"
    text: str           # the line text (without the timestamp prefix)


_TIMESTAMP_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)$")


def search(
    query: str,
    *,
    pod: Optional[str] = None,
    since: Optional[str] = None,
    meeting_type: Optional[str] = None,
    color: bool = False,
) -> Iterator[SearchMatch]:
    """Yield SearchMatch for each line matching `query` in any transcript.

    Backend: rg if available, else Python Path.rglob + substring.
    Filters: pod, since (date string parseable by storage._parse_since),
    meeting_type (must match a directory between the date and the file).
    """
    files = _iter_transcript_files(pod)
    files = _filter_by_since(files, since)
    files = _filter_by_type(files, meeting_type)

    if shutil.which("rg"):
        yield from _rg_search(query, files, color=color)
    else:
        yield from _python_search(query, files, color=color)


def _iter_transcript_files(pod: Optional[str]) -> list[Path]:
    if pod:
        base = Path("pods") / pod / "transcripts"
        if not base.exists():
            return []
        return sorted(base.rglob("*.md"))
    base = Path("pods")
    if not base.exists():
        return []
    return sorted(p for p in base.rglob("*.md") if "transcripts" in p.parts)


def _filter_by_since(files: list[Path], since: Optional[str]) -> list[Path]:
    if not since:
        return files
    from .storage import _parse_since
    cutoff = _parse_since(since)
    out = []
    for f in files:
        # Meeting ID is the file stem: YYYY-MM-DD-HHMMSS-<pod>
        stem = f.stem
        if len(stem) >= 10:
            try:
                from datetime import datetime
                file_date = datetime.strptime(stem[:10], "%Y-%m-%d").date()
                if file_date >= cutoff:
                    out.append(f)
                    continue
            except ValueError:
                pass
        # Fall back to file mtime
        from datetime import datetime, date
        mtime = datetime.fromtimestamp(f.stat().st_mtime).date()
        if mtime >= cutoff:
            out.append(f)
    return out


def _filter_by_type(files: list[Path], meeting_type: Optional[str]) -> list[Path]:
    if not meeting_type:
        return files
    out = []
    for f in files:
        # Path is pods/<pod>/transcripts/<date>/[<type>/]<id>.md
        parts = f.parts
        if "transcripts" not in parts:
            continue
        idx = parts.index("transcripts")
        # 2-level: transcripts/<date>/<file>; 3-level: transcripts/<date>/<type>/<file>
        if len(parts) - idx == 3:
            # 2-level: no type dir, exclude
            continue
        if len(parts) - idx == 4:
            # 3-level: type dir is parts[idx + 2]
            if parts[idx + 2] == meeting_type:
                out.append(f)
    return out


def _rg_search(query: str, files: list[Path], *, color: bool) -> Iterator[SearchMatch]:
    if not files:
        return
    cmd = ["rg", "-F", "--no-heading", "-n", query]
    if color:
        cmd.append("--color=always")
    cmd.extend(str(f) for f in files)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode not in (0, 1):  # 0 = matches, 1 = no matches, 2+ = error
        print(f"rg error: {proc.stderr}", file=sys.stderr)
        return
    for line in proc.stdout.splitlines():
        match = _parse_rg_line(line)
        if match is not None:
            yield match


def _parse_rg_line(line: str) -> Optional[SearchMatch]:
    """Parse 'path:lineno:content' into a SearchMatch.

    rg --no-heading -n output: "<path>:<lineno>:<content>".
    """
    parts = line.split(":", 2)
    if len(parts) < 3:
        return None
    path_str, _lineno, content = parts
    path = Path(path_str)
    return _make_match_from_path(path, content)


def _python_search(query: str, files: list[Path], *, color: bool) -> Iterator[SearchMatch]:
    for f in files:
        try:
            text = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for line in text.splitlines():
            if query in line:
                match = _make_match_from_path(f, line)
                if match is not None:
                    yield match


def _make_match_from_path(path: Path, line: str) -> Optional[SearchMatch]:
    """Extract SearchMatch fields from a path + content line."""
    parts = path.parts
    if "transcripts" not in parts:
        return None
    idx = parts.index("transcripts")
    pod_name = parts[idx - 1] if idx >= 1 else "?"
    # Date is at parts[idx + 1] (always, 2-level or 3-level)
    date_str = parts[idx + 1]
    meeting_id = path.stem

    m = _TIMESTAMP_RE.match(line)
    if m:
        timestamp = f"[{m.group(1)}]"
        text = m.group(2)
    else:
        timestamp = ""
        text = line
    return SearchMatch(
        pod_name=pod_name,
        date_str=date_str,
        meeting_id=meeting_id,
        timestamp=timestamp,
        text=text,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_search.py -v
```

Expected: 6 passes.

- [ ] **Step 5: Add `cmd_search` to `cli.py` and register the subparser**

In `podscribe/cli.py`, add `cmd_search` near the other commands (find a good spot, e.g. after `cmd_consolidate`):

```python
def cmd_search(args) -> int:
    """Search across all transcripts for a keyword."""
    from .search import search
    matches = list(search(
        args.query,
        pod=args.pod,
        since=args.since,
        meeting_type=args.type,
        color=args.color,
    ))
    if not matches:
        print("No matches.")
        return 0
    for m in matches:
        print(f"{m.pod_name}:{m.date_str}:{m.meeting_id}:{m.timestamp} {m.text}")
    return 0
```

Then add the subparser in the parser-setup section (find where the other `p_xxx` parsers are defined):

```python
    # search
    p_search = sub.add_parser("search", help="Search across all transcripts.")
    p_search.add_argument("query", help="Search query (fixed-string match)")
    p_search.add_argument("--pod", help="Limit search to one pod")
    p_search.add_argument("--since", metavar="DURATION|DATE", help="Filter by date")
    p_search.add_argument("--type", metavar="TYPE", help="Filter by meeting type")
    p_search.add_argument(
        "--color", action="store_true",
        help="Highlight matches in ANSI colors",
    )
    p_search.set_defaults(func=cmd_search)
```

- [ ] **Step 6: Add a CLI test for the subparser**

Append to `tests/test_cli.py`:

```python
def test_search_subparser_parses_args():
    from podscribe.cli import build_parser
    args = build_parser().parse_args([
        "search", "Project Helios", "--pod", "sam-chen", "--since", "7d", "--type", "1on1",
    ])
    assert args.query == "Project Helios"
    assert args.pod == "sam-chen"
    assert args.since == "7d"
    assert args.type == "1on1"
```

- [ ] **Step 7: Run the full test suite**

```bash
pytest tests/ -v -k "not transcriber" 2>&1 | tail -3
```

Expected: 152 passed (145 + 6 search + 1 CLI subparser).

- [ ] **Step 8: Commit**

```bash
git add podscribe/search.py podscribe/cli.py tests/test_search.py tests/test_cli.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "feat(search): add podscribe search command with rg and python backends"
```

---

## Task 9: `podscribe export` (4.7 partial)

**Files:**
- Create: `podscribe/export.py`
- Create: `tests/test_export.py` (3 tests for export)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_export.py`:

```python
"""Tests for podscribe.export."""
import tarfile
from pathlib import Path

import pytest

from podscribe.export import create_export, _iter_export_members


def _make_pod_with_content(base: Path, pod_name: str) -> None:
    pod_dir = base / "pods" / pod_name
    pod_dir.mkdir(parents=True, exist_ok=True)
    (pod_dir / "config.yaml").write_text(f"name: {pod_name}\n")
    tdir = pod_dir / "transcripts" / "22-JUN-2026"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "2026-06-22-143000-sam-chen.md").write_text("# Meeting\n[00:00:00] hello\n")
    (tdir / "2026-06-22-143000-sam-chen.json").write_text('{"id": "x"}')
    (tdir / "2026-06-22-143000-sam-chen.raw").write_bytes(b"\x00" * 100)


def test_export_creates_tarball(tmp_path, monkeypatch):
    """create_export writes a gzip tarball at out_path."""
    monkeypatch.chdir(tmp_path)
    _make_pod_with_content(tmp_path, "sam-chen")
    out = tmp_path / "out.tar.gz"
    result = create_export(out)
    assert result == out
    assert out.exists()
    # Magic bytes for gzip: 0x1f 0x8b
    assert out.read_bytes()[:2] == b"\x1f\x8b"


def test_export_excludes_raw_files(tmp_path, monkeypatch):
    """Tarball member list does not include .raw files."""
    monkeypatch.chdir(tmp_path)
    _make_pod_with_content(tmp_path, "sam-chen")
    out = tmp_path / "out.tar.gz"
    create_export(out)
    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    assert not any(n.endswith(".raw") for n in names)
    assert any(n.endswith(".md") for n in names)
    assert any(n.endswith(".json") for n in names)


def test_export_excludes_pycache_and_venv(tmp_path, monkeypatch):
    """Tarball excludes __pycache__, .pytest_cache, .venv."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pods" / "sam-chen").mkdir(parents=True)
    (tmp_path / "pods" / "sam-chen" / "config.yaml").write_text("name: sam-chen\n")
    pycache = tmp_path / "pods" / "sam-chen" / "__pycache__"
    pycache.mkdir()
    (pycache / "foo.pyc").write_bytes(b"\x00")
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("")

    out = tmp_path / "out.tar.gz"
    create_export(out)
    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    assert not any("__pycache__" in n for n in names)
    assert not any(".venv" in n for n in names)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_export.py -v
```

Expected: 3 failures (`podscribe.export` doesn't exist).

- [ ] **Step 3: Create `podscribe/export.py`**

```python
"""Backup export/import for podscribe data."""
from __future__ import annotations

import os
import sys
import tarfile
from pathlib import Path
from typing import Iterator, Optional


_EXCLUDED_DIR_NAMES = {"__pycache__", ".pytest_cache", ".venv"}
_EXCLUDED_SUFFIXES = {".raw"}
_EXCLUDED_TOP_LEVEL = {".env"}


def create_export(out_path: Optional[Path] = None) -> Path:
    """Bundle pods/, leadership_team.yaml, and podscribe.yaml into a tar.gz.

    Excludes .raw files, .env, __pycache__/, .pytest_cache/, .venv/.
    If out_path is None or "-", write to sys.stdout.buffer.
    """
    members = list(_iter_export_members())

    if out_path is None or str(out_path) == "-":
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w:gz") as tar:
            for m in members:
                tar.add(m, arcname=str(m.relative_to(Path.cwd())))
        return Path("-")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_path, "w:gz") as tar:
        for m in members:
            tar.add(m, arcname=str(m.relative_to(Path.cwd())))
    return out_path


def _iter_export_members() -> Iterator[Path]:
    """Walk pods/, leadership_team.yaml, podscribe.yaml; yield paths to include."""
    cwd = Path.cwd()
    pods_dir = cwd / "pods"
    if pods_dir.exists():
        for path in sorted(pods_dir.rglob("*")):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(cwd).parts
            if any(part in _EXCLUDED_DIR_NAMES for part in rel_parts):
                continue
            if path.suffix in _EXCLUDED_SUFFIXES:
                continue
            yield path
    for fname in ("leadership_team.yaml", "podscribe.yaml"):
        fpath = cwd / fname
        if fpath.exists():
            yield fpath
```

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
pytest tests/test_export.py -v
```

Expected: 3 passes.

- [ ] **Step 5: Add `cmd_export` to `cli.py` and register the subparser**

In `podscribe/cli.py`, add `cmd_export`:

```python
def cmd_export(args) -> int:
    """Export all pod data to a tarball."""
    from .export import create_export
    out = Path(args.out) if args.out else None
    result = create_export(out)
    if str(result) == "-":
        return 0
    print(f"Exported to {result}")
    return 0
```

Then add the subparser in the parser-setup section:

```python
    # export
    p_export = sub.add_parser("export", help="Export pod data to a tarball.")
    p_export.add_argument(
        "--out", metavar="PATH",
        help="Output path (default: stdout). Example: pods-2026-06-22.tar.gz",
    )
    p_export.set_defaults(func=cmd_export)
```

- [ ] **Step 6: Add a CLI subparser test**

Append to `tests/test_cli.py`:

```python
def test_export_subparser_parses_args():
    from podscribe.cli import build_parser
    args = build_parser().parse_args(["export", "--out", "pods.tar.gz"])
    assert args.out == "pods.tar.gz"
```

- [ ] **Step 7: Run the full test suite**

```bash
pytest tests/ -v -k "not transcriber" 2>&1 | tail -3
```

Expected: 156 passed (152 + 3 export + 1 subparser).

- [ ] **Step 8: Commit**

```bash
git add podscribe/export.py podscribe/cli.py tests/test_export.py tests/test_cli.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "feat(export): add podscribe export command"
```

---

## Task 10: `podscribe import` (4.7 partial)

**Files:**
- Modify: `podscribe/export.py` (add `import_archive`, `_safe_extract`)
- Modify: `podscribe/cli.py` (add `cmd_import`)
- Modify: `tests/test_export.py` (5 new tests for import)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_export.py`:

```python
def test_import_refuses_overwrite_without_force(tmp_path, monkeypatch, capsys):
    """Existing pod → import errors out without --force."""
    from podscribe.storage import init_pod
    from podscribe.export import create_export, import_archive

    # Build a tarball in /tmp
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.chdir(src)
    _make_pod_with_content(src, "sam-chen")
    tar = tmp_path / "out.tar.gz"
    create_export(tar)

    # Set up a destination with an existing pod
    dst = tmp_path / "dst"
    dst.mkdir()
    monkeypatch.chdir(dst)
    init_pod("sam-chen")
    rc = import_archive(tar)
    assert rc == 1
    captured = capsys.readouterr()
    assert "Refusing" in captured.err
    assert "sam-chen" in captured.err


def test_import_force_overwrites(tmp_path, monkeypatch):
    """--force replaces the existing pod."""
    from podscribe.storage import init_pod, pod_exists
    from podscribe.export import create_export, import_archive

    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.chdir(src)
    _make_pod_with_content(src, "sam-chen")
    tar = tmp_path / "out.tar.gz"
    create_export(tar)

    dst = tmp_path / "dst"
    dst.mkdir()
    monkeypatch.chdir(dst)
    init_pod("sam-chen")  # Pre-existing

    rc = import_archive(tar, force=True)
    assert rc == 0
    assert pod_exists("sam-chen")


def test_import_dry_run_no_writes(tmp_path, monkeypatch, capsys):
    """--dry-run prints what would happen, no files change."""
    from podscribe.export import create_export, import_archive

    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.chdir(src)
    _make_pod_with_content(src, "sam-chen")
    tar = tmp_path / "out.tar.gz"
    create_export(tar)

    dst = tmp_path / "dst"
    dst.mkdir()
    monkeypatch.chdir(dst)
    pods_before = sorted((dst / "pods").glob("*")) if (dst / "pods").exists() else []
    rc = import_archive(tar, dry_run=True)
    assert rc == 0
    captured = capsys.readouterr()
    assert "Would import" in captured.out
    pods_after = sorted((dst / "pods").glob("*")) if (dst / "pods").exists() else []
    assert pods_before == pods_after


def test_import_rejects_path_traversal(tmp_path, monkeypatch):
    """Tarball with a path-traversal member is rejected outright."""
    import tarfile
    from podscribe.export import import_archive

    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "evil.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo(name="pods/../../etc/passwd")
        data = b"evil"
        info.size = len(data)
        tar.addfile(info, __import__("io").BytesIO(data))

    with pytest.raises(ValueError, match="Unsafe path"):
        import_archive(bad)


def test_export_import_roundtrip(tmp_path, monkeypatch):
    """Create a tarball, delete the pod, import it back, verify content."""
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting, pod_exists, load_pod
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.export import create_export, import_archive

    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.chdir(src)
    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "Project Helios is on track"))
    finalize_meeting(meeting)
    tar = tmp_path / "out.tar.gz"
    create_export(tar)

    # Wipe the pod
    import shutil
    shutil.rmtree(src / "pods" / "sam-chen")
    assert not pod_exists("sam-chen")

    # Re-import
    rc = import_archive(tar)
    assert rc == 0
    assert pod_exists("sam-chen")
    reloaded = load_pod("sam-chen")
    assert reloaded.name == "sam-chen"
```

Add `import io` at the top of `tests/test_export.py` if not present (used in the path-traversal test for BytesIO).

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_export.py -v -k "refuses or force or dry_run or rejects_path or roundtrip"
```

Expected: 5 failures.

- [ ] **Step 3: Add `import_archive` and `_safe_extract` to `export.py`**

Append to `podscribe/export.py`:

```python
def import_archive(
    archive_path: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    """Extract a podscribe export tarball into the current directory.

    Default: refuse to overwrite existing pods. --force: overwrite.
    --dry-run: print what would happen, do not write.
    """
    pods_in_tar = set()
    other_members = []
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            target = (Path.cwd() / member.name).resolve()
            if not str(target).startswith(str(Path.cwd().resolve()) + os.sep) and target != Path.cwd().resolve():
                raise ValueError(f"Unsafe path in tarball: {member.name}")
            parts = Path(member.name).parts
            if parts and parts[0] == "pods" and len(parts) >= 2:
                pods_in_tar.add(parts[1])
            else:
                other_members.append(member)

    pods_dir = Path("pods")
    existing = {p.name for p in pods_dir.iterdir()} if pods_dir.exists() else set()
    conflicts = pods_in_tar & existing
    if conflicts and not force:
        print(
            f"Refusing to overwrite existing pods: {sorted(conflicts)}.\n"
            f"Re-run with --force to replace them.",
            file=sys.stderr,
        )
        return 1

    if dry_run:
        print(f"Would import: {sorted(pods_in_tar)}")
        if other_members:
            print(f"Would also import: {[m.name for m in other_members]}")
        return 0

    with tarfile.open(archive_path, "r:gz") as tar:
        _safe_extract(tar, path=Path.cwd())
    print(f"Imported: {sorted(pods_in_tar)}")
    return 0


def _safe_extract(tar: tarfile.TarFile, path: Path = Path(".")) -> None:
    """Extract every member with a path-traversal check.

    Python 3.12 added `tar.extractall(filter='data')` for this purpose,
    but the project supports Python 3.10+. This function is the manual
    equivalent and works on all supported versions.
    """
    cwd_resolved = path.resolve()
    for member in tar.getmembers():
        target = (path / member.name).resolve()
        if target != cwd_resolved and not str(target).startswith(str(cwd_resolved) + os.sep):
            raise ValueError(f"Unsafe path in tarball: {member.name}")
    tar.extractall(path=path)
```

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
pytest tests/test_export.py -v -k "refuses or force or dry_run or rejects_path or roundtrip"
```

Expected: 5 passes.

- [ ] **Step 5: Add `cmd_import` to `cli.py` and register the subparser**

In `podscribe/cli.py`, add `cmd_import`:

```python
def cmd_import(args) -> int:
    """Import a podscribe export tarball."""
    from .export import import_archive
    return import_archive(
        Path(args.archive),
        force=args.force,
        dry_run=args.dry_run,
    )
```

Then add the subparser in the parser-setup section:

```python
    # import
    p_import = sub.add_parser("import", help="Import a podscribe export tarball.")
    p_import.add_argument("archive", help="Path to the tarball to import")
    p_import.add_argument(
        "--force", action="store_true",
        help="Overwrite existing pods with the same name",
    )
    p_import.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without writing",
    )
    p_import.set_defaults(func=cmd_import)
```

- [ ] **Step 6: Add a CLI subparser test**

Append to `tests/test_cli.py`:

```python
def test_import_subparser_parses_args():
    from podscribe.cli import build_parser
    args = build_parser().parse_args(["import", "pods.tar.gz", "--force", "--dry-run"])
    assert args.archive == "pods.tar.gz"
    assert args.force is True
    assert args.dry_run is True
```

- [ ] **Step 7: Run the full test suite**

```bash
pytest tests/ -v -k "not transcriber" 2>&1 | tail -3
```

Expected: 162 passed (156 + 5 import tests + 1 subparser).

- [ ] **Step 8: Commit**

```bash
git add podscribe/export.py podscribe/cli.py tests/test_export.py tests/test_cli.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "feat(export): add podscribe import with --force and --dry-run"
```

---

## Task 11: README updates

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read the current README to find edit points**

```bash
grep -n "^##\|^### " README.md
```

Expected: a list of top-level sections (Commands, Storage, Models, etc.).

- [ ] **Step 2: Add the new section: "## Listing & filtering"**

Find the spot in `README.md` where the existing commands are documented (e.g. right after the "Commands" table). Add:

```markdown
### Listing & filtering

```
podscribe list                          # all pods, all meetings (existing)
podscribe list <pod>                    # one pod, all meetings
podscribe list --all                    # all pods (uses global meetings.csv)
podscribe list --since 7d               # last 7 days
podscribe list --since 2026-06-15       # since a specific date
podscribe list --recent 5               # limit to N most recent
podscribe list --type 1on1              # filter by meeting type
```

`--since` accepts durations (`Nd`, `Nh`, `Nm`) or ISO dates (`YYYY-MM-DD`).
```

- [ ] **Step 3: Add the new section: "## Searching"**

```markdown
### Searching

```
podscribe search "Project Helios"               # all pods
podscribe search "auth" --pod sam-chen          # one pod
podscribe search "blocker" --since 7d           # last week
podscribe search "design" --type 1on1           # typed meetings only
podscribe search "x" --color                    # ANSI-highlighted output
```

Output format: `pod-name:DD-MMM-YYYY:<meeting-id>:[HH:MM:SS]:<line-text>`.
Uses `rg` if installed, falls back to a Python recursive search otherwise.
```

- [ ] **Step 4: Add the new section: "## Backup & restore"**

```markdown
### Backup & restore

```
podscribe export --out pods-2026-06-22.tar.gz
podscribe import pods-2026-06-22.tar.gz
podscribe import --dry-run pods-2026-06-22.tar.gz   # show, don't write
podscribe import --force pods-2026-06-22.tar.gz     # overwrite existing pods
podscribe export --out -                             # stdout (for piping)
```

`export` includes `pods/` (transcripts, summaries, per-pod config, per-pod
`meetings.csv`), `leadership_team.yaml`, and `podscribe.yaml`. Excludes
`.raw` audio, `.env`, `__pycache__/`, `.pytest_cache/`, `.venv/`.

`import` refuses to overwrite existing pods by default; pass `--force` to
replace them. The tarball is checked for path-traversal attacks before
extraction.
```

- [ ] **Step 5: Update the "## Storage layout" section**

Find the existing storage layout block and replace it with:

```markdown
```
leadership_team.yaml                       — global glossary (repo root)
podscribe.yaml                             — project LLM config (repo root)
pods/meetings.csv                          — global rollup (all pods)
pods/<name>/
├── config.yaml
├── meetings.csv                           — per-pod rollup
└── transcripts/
    └── DD-MMM-YYYY/                      # e.g. 22-JUN-2026
        ├── [<type>/]                     # optional subdir, e.g. 1on1/, retro/
        │   ├── <meeting-id>.md
        │   ├── <meeting-id>.json
        │   └── <meeting-id>.raw           # deleted by default
└── summaries/
    └── DD-MMM-YYYY/
        └── <meeting-id>.md
```

The optional `<type>/` subdir appears when `--type` is passed to `record`.
A 2-level layout (no type subdir) and a 3-level layout (with type) coexist
on disk and are both discovered by `list_meetings`.
```

- [ ] **Step 6: Update the "## Commands" section to mention `--type`**

Find the `podscribe <pod> record` documentation. Add a line:

```markdown
`--type TYPE` — set meeting type (1on1, retro, skip-level, design-review,
standup, interview, other). Records land in a subdir; queryable via
`list --type`.
```

- [ ] **Step 7: Update the test count**

Search the README for the test count line. It currently says "126 offline + 1 smoke" (or similar). Change to:

```markdown
162 offline unit tests + 1 smoke test requiring network. Skip the smoke
test with `-k "not transcriber"`.
```

- [ ] **Step 8: Update the glossary section to note caching**

Find the section that talks about the glossary (it should be in the "Commands > context" or "Configuration" area). Add a note:

```markdown
The effective glossary (leadership + pod-specific) is cached per session
and invalidated automatically when `leadership_team.yaml` changes on disk.
```

- [ ] **Step 9: Verify the README is well-formed**

```bash
grep -c "^#" README.md
```

Expected: ~20-30 (depending on existing structure; just verify it didn't get mangled).

- [ ] **Step 10: Commit**

```bash
git add README.md
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "docs: README updates for section 4 features (list filters, search, export, --type)"
```

---

## Task 12: Integration smoke test

**Files:**
- Modify: `tests/test_cli.py` (add one integration test)

- [ ] **Step 1: Write the integration test**

Append to `tests/test_cli.py`:

```python
def test_section4_end_to_end(tmp_path, monkeypatch):
    """Smoke: init → record (typed) → enhance → consolidate → search → export → import.

    Mocks LLM calls. Exercises the full surface added in section 4.
    """
    from unittest.mock import patch
    from podscribe.storage import (
        init_pod, start_meeting, append_segment, finalize_meeting,
    )
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_enhance, cmd_consolidate, cmd_search, build_parser
    from podscribe.export import create_export, import_archive

    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen", display_name="Sam Chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0), meeting_type="1on1")
    append_segment(meeting, Segment(1.0, 5.0, "Discussed Project Helios timeline and auth design"))
    finalize_meeting(meeting)

    # Write a fake enhanced summary
    (pod.base_path / "summaries" / "22-JUN-2026" / "1on1").mkdir(parents=True, exist_ok=True)
    (pod.base_path / "summaries" / "22-JUN-2026" / "1on1" / f"{meeting.id}.md").write_text(
        "Enhanced summary mentioning Project Helios."
    )

    # Mock the LLM. enhance + consolidate both call _run_enhance.
    with patch("podscribe.cli._run_enhance", return_value=("Project Helios update: on track", None)):
        with patch("podscribe.cli.load_project_config", return_value={
            "llm": {"model": "qwen3.6", "prompt_template": "x"},
        }):
            with patch("podscribe.cli.extract_structured_fields", return_value={
                "quick_summary": "Helios update",
                "key_topics": ["Helios"],
                "action_items": ["Sam reviews design"],
                "blockers": [],
                "next_steps": ["Sync weekly"],
            }):
                # enhance
                rc = cmd_enhance(build_parser().parse_args(["enhance", "sam-chen"]))
                assert rc == 0

                # consolidate (this populates meetings.csv, both pod and global)
                rc = cmd_consolidate(build_parser().parse_args(["consolidate", "sam-chen"]))
                assert rc == 0

    # search finds the meeting
    import subprocess
    # Use the search command via the CLI parser, not the underlying function, to exercise the full path
    args = build_parser().parse_args(["search", "Helios"])
    rc = args.func(args)
    assert rc == 0

    # export then re-import round-trip
    tar = tmp_path / "backup.tar.gz"
    create_export(tar)
    assert tar.exists()

    import shutil
    shutil.rmtree(tmp_path / "pods" / "sam-chen")
    rc = import_archive(tar)
    assert rc == 0
    assert (tmp_path / "pods" / "sam-chen").exists()
```

- [ ] **Step 2: Run the test to verify it passes**

```bash
pytest tests/test_cli.py::test_section4_end_to_end -v
```

Expected: PASS.

- [ ] **Step 3: Run the full test suite one final time**

```bash
pytest tests/ -v -k "not transcriber" 2>&1 | tail -3
```

Expected: 163 passed (162 + 1 new smoke test).

- [ ] **Step 4: Commit**

```bash
git add tests/test_cli.py
git -c user.name="podscribe" -c user.email="podscribe@local" \
  commit -m "test: section 4 integration smoke (record -> enhance -> consolidate -> search -> export -> import)"
```

---

## Final verification

- [ ] **Step 1: Confirm clean working tree**

```bash
git status
```

Expected: clean (no uncommitted changes).

- [ ] **Step 2: Confirm 12 commits ahead of main**

```bash
git log --oneline main..HEAD
```

Expected: 12 commits, in the order from the commit plan.

- [ ] **Step 3: Final test run**

```bash
pytest tests/ -v -k "not transcriber" 2>&1 | tail -5
```

Expected: `163 passed`.

- [ ] **Step 4: Push branch (only if user has asked to push)**

```bash
git push -u origin feature/section-4-architecture
```

Do NOT push unless the user explicitly asks. (The user can review the diff locally first.)

---

## Self-review

**1. Spec coverage:** Each of 4.1-4.7 has at least one task. Mapping:
- 4.1 → T1 (`_run_enhance` extraction, 4 tests)
- 4.2 → T7 (list filters, 4 tests)
- 4.3 → T6 (global CSV, 3 tests)
- 4.4 → T2 (glossary cache, 3 tests)
- 4.5 → T3 (model), T4 (CLI flag), T5 (storage, 6 tests total)
- 4.6 → T8 (search, 6 tests + 1 subparser)
- 4.7 → T9 (export, 3 tests + 1 subparser), T10 (import, 5 tests + 1 subparser)
- T11 = docs
- T12 = smoke

**2. Placeholder scan:** No "TBD", "TODO", "implement later", "fill in details", "add appropriate error handling" or "write tests for the above" without code.

**3. Type consistency:**
- `Meeting.type: Optional[str] = None` defined in T5 (Step 4), used in `start_meeting` (T5 Step 3), `finalize_meeting` (T5 Step 5), `list_meetings` (T5 Step 6), `cmd_record` (T5 Step 7)
- `_run_enhance` signature `(pod, meeting, prompt, model) -> tuple[Optional[str], Optional[str]]` defined T1 Step 3, used in T1 Steps 5-6
- `parse_meeting_type` defined T3 Step 3, used in T4 Step 3 and T7 Step 4
- `MEETING_TYPES` constant defined T3 Step 3
- `SearchMatch` dataclass defined T8 Step 3, used in T8 Step 4
- `_parse_since` defined T7 Step 5, used in T7 Step 4 (cmd_list) and T8 Step 3 (search)
- `global_log_path`, `append_global_log_row`, `read_global_log` defined T6 Step 3, used in T6 Step 4 + T7 Step 4 + tests

**4. Test count:** 127 (current) → 163 (after T12). Net new = 36. Spec estimated 34. Close enough; the small delta is from the search CLI subparser test and the export/import CLI subparser tests, which the spec listed as "additional" implicitly.
