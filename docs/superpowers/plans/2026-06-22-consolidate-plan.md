# Consolidate Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `podscribe consolidate` command that reads an enhanced summary, extracts structured fields via Ollama, and appends to a per-pod CSV log.

**Architecture:** Five independent layers: CSV storage operations in `storage.py`, prompt management in `config.py`, LLM extraction in `llm.py`, consolidate handler + parser + alias in `cli.py`. Each file change is tested first.

**Tech Stack:** Python 3.10+, csv stdlib, pyyaml, requests (already used), pytest with tmp_path isolation

---

### Task 1: CSV log storage operations

**Files:**
- Modify: `podscribe/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing tests for CSV log operations**

```python
# Add to tests/test_storage.py

import csv

from podscribe.storage import (
    append_log_row,
    log_entry_exists,
    log_path,
    rewrite_log_row,
)


def test_log_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod
    pod = init_pod("sam-chen")
    path = log_path(pod)
    assert path == pod.base_path / "meetings.csv"


def test_append_and_read_log_row(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod
    pod = init_pod("sam-chen")
    fields = {
        "date": "2026-06-22",
        "person": "Sam Chen",
        "meeting_id": "2026-06-22-1430-sam-chen",
        "quick_summary": "Synced on Q3 roadmap",
        "key_topics": "Q3 roadmap|API review",
        "action_items": "Unblock API review",
        "blockers": "Stalled on VP sign-off",
        "next_steps": "Check in Friday",
        "summary_file": "summaries/2026-06-22-1430-sam-chen.md",
        "transcript_file": "transcripts/2026-06-22-1430-sam-chen.md",
    }
    append_log_row(pod, fields)
    path = log_path(pod)
    assert path.exists()
    with path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["meeting_id"] == fields["meeting_id"]
    assert rows[0]["quick_summary"] == fields["quick_summary"]


def test_log_entry_exists_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod
    pod = init_pod("sam-chen")
    fields = {"meeting_id": "2026-06-22-1430-sam-chen"}
    append_log_row(pod, fields)
    assert log_entry_exists(pod, "2026-06-22-1430-sam-chen") is True
    assert log_entry_exists(pod, "2026-06-23-1430-sam-chen") is False


def test_log_entry_exists_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod
    pod = init_pod("sam-chen")
    assert log_entry_exists(pod, "anything") is False


def test_rewrite_log_row(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod
    pod = init_pod("sam-chen")
    fields = {
        "meeting_id": "2026-06-22-1430-sam-chen",
        "quick_summary": "Old summary",
        "key_topics": "",
        "action_items": "",
        "blockers": "",
        "next_steps": "",
        "date": "",
        "person": "",
        "summary_file": "",
        "transcript_file": "",
    }
    append_log_row(pod, fields)
    fields["quick_summary"] = "Updated summary"
    rewrite_log_row(pod, "2026-06-22-1430-sam-chen", fields)
    path = log_path(pod)
    with path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["quick_summary"] == "Updated summary"


def test_append_multiple_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod
    pod = init_pod("sam-chen")
    append_log_row(pod, {"meeting_id": "id-1"})
    append_log_row(pod, {"meeting_id": "id-2"})
    path = log_path(pod)
    with path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_storage.py -v -k "log" 2>&1 | head -30`
Expected: ImportError (functions not defined) or test failures

- [ ] **Step 3: Implement CSV log operations in storage.py**

Add to `podscribe/storage.py`:

```python
import csv


CSV_COLUMNS = [
    "date", "person", "meeting_id", "quick_summary",
    "key_topics", "action_items", "blockers", "next_steps",
    "summary_file", "transcript_file",
]


def log_path(pod: Pod) -> Path:
    return pod.base_path / "meetings.csv"


def log_entry_exists(pod: Pod, meeting_id: str) -> bool:
    path = log_path(pod)
    if not path.exists():
        return False
    with path.open() as f:
        for row in csv.DictReader(f):
            if row.get("meeting_id") == meeting_id:
                return True
    return False


def append_log_row(pod: Pod, fields: dict) -> None:
    path = log_path(pod)
    new_row = {col: fields.get(col, "") for col in CSV_COLUMNS}
    file_exists = path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(new_row)


def rewrite_log_row(pod: Pod, meeting_id: str, fields: dict) -> None:
    path = log_path(pod)
    if not path.exists():
        append_log_row(pod, fields)
        return
    with path.open() as f:
        rows = list(csv.DictReader(f))
    updated = {col: fields.get(col, "") for col in CSV_COLUMNS}
    out_rows = []
    for row in rows:
        if row.get("meeting_id") == meeting_id:
            out_rows.append(updated)
        else:
            out_rows.append(row)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(out_rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_storage.py -v -k "log"`
Expected: All 6 new tests pass

- [ ] **Step 5: Commit**

```bash
git add tests/test_storage.py podscribe/storage.py
git commit -m "feat: add CSV log storage operations for consolidate"
```

---

### Task 2: Consolidate prompt config layer

**Files:**
- Modify: `podscribe/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for consolidate config**

Add to `tests/test_config.py`:

```python
from podscribe.config import (
    load_consolidate_prompt,
    save_consolidate_prompt,
)


def test_consolidate_prompt_default_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prompt = load_consolidate_prompt()
    assert "quick_summary" in prompt
    assert "action_items" in prompt


def test_consolidate_prompt_save_and_load(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_consolidate_prompt("Custom prompt {{summary}}")
    loaded = load_consolidate_prompt()
    assert loaded == "Custom prompt {{summary}}"


def test_consolidate_prompt_overwrites(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_consolidate_prompt("First prompt")
    save_consolidate_prompt("Second prompt")
    loaded = load_consolidate_prompt()
    assert loaded == "Second prompt"


def test_consolidate_prompt_loads_from_project_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.config import save_project_config
    save_project_config({"consolidate": {"prompt": "From file {{summary}}"}})
    loaded = load_consolidate_prompt()
    assert loaded == "From file {{summary}}"


def test_consolidate_prompt_save_updates_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_consolidate_prompt("Saved prompt")
    from podscribe.config import load_project_config
    cfg = load_project_config()
    assert cfg["consolidate"]["prompt"] == "Saved prompt"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v -k "consolidate"`
Expected: ImportError (functions not defined)

- [ ] **Step 3: Implement consolidate config in config.py**

Add to `podscribe/config.py`:

```python
CONSOLIDATE_PROMPT_DEFAULT = """Given the following enhanced meeting summary, extract structured information.

Return ONLY valid YAML with these fields:
- quick_summary: One-sentence summary of the meeting
- key_topics: Bullet list of topics discussed
- action_items: List of things the manager needs to follow up on
- blockers: List of any blockers or concerns raised
- next_steps: List of plans for next meeting

Enhanced summary:
{{summary}}"""


def load_consolidate_prompt() -> str:
    """Load consolidate prompt from podscribe.yaml, or return default."""
    cfg = load_project_config()
    prompt = cfg.get("consolidate", {}).get("prompt")
    return prompt if prompt else CONSOLIDATE_PROMPT_DEFAULT


def save_consolidate_prompt(prompt: str) -> None:
    """Save consolidate prompt to podscribe.yaml."""
    cfg = load_project_config()
    if "consolidate" not in cfg:
        cfg["consolidate"] = {}
    cfg["consolidate"]["prompt"] = prompt
    save_project_config(cfg)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v -k "consolidate"`
Expected: All 5 new tests pass

- [ ] **Step 5: Commit**

```bash
git add tests/test_config.py podscribe/config.py
git commit -m "feat: add consolidate prompt config with default"
```

---

### Task 3: LLM extraction for consolidate

**Files:**
- Modify: `podscribe/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write failing tests for consolidate LLM functions**

Add to `tests/test_llm.py`:

```python
from podscribe.llm import (
    build_consolidate_prompt,
    extract_structured_fields,
)


ENHANCED_SUMMARY = "We discussed the Q3 roadmap. Sam is blocked on API review. Next steps: check in Friday."


def test_build_consolidate_prompt_inserts_summary():
    prompt = build_consolidate_prompt("Extract: {{summary}}", ENHANCED_SUMMARY)
    assert ENHANCED_SUMMARY in prompt
    assert "Extract:" in prompt


def test_build_consolidate_prompt_no_var():
    """If template doesn't contain {{summary}}, it's appended."""
    prompt = build_consolidate_prompt("Extract fields", ENHANCED_SUMMARY)
    assert ENHANCED_SUMMARY in prompt


def test_extract_structured_fields_valid_yaml():
    response = """
quick_summary: Synced on Q3 roadmap
key_topics:
  - Q3 roadmap
  - API review
action_items:
  - Unblock API review
blockers:
  - Stalled on VP sign-off
next_steps:
  - Check in Friday
"""
    result = extract_structured_fields(response)
    assert result is not None
    assert result["quick_summary"] == "Synced on Q3 roadmap"
    assert "API review" in result["key_topics"]
    assert "Unblock API review" in result["action_items"]


def test_extract_structured_fields_fenced_yaml():
    response = "Some text\n```yaml\nquick_summary: Synced\nkey_topics: []\n```\nmore text"
    result = extract_structured_fields(response)
    assert result is not None
    assert result["quick_summary"] == "Synced"


def test_extract_structured_fields_invalid():
    result = extract_structured_fields("not yaml at all")
    assert result is None


def test_extract_structured_fields_empty():
    result = extract_structured_fields("")
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm.py -v -k "consolidate or extract"`
Expected: ImportError (functions not defined)

- [ ] **Step 3: Implement LLM extraction in llm.py**

Add to `podscribe/llm.py`:

```python
import yaml


def build_consolidate_prompt(template: str, summary: str) -> str:
    prompt = template.replace("{{summary}}", summary)
    if "{{summary}}" not in template:
        prompt += "\n\n" + summary
    return prompt


def extract_structured_fields(response: str) -> Optional[dict]:
    """Parse YAML structured fields from LLM response.

    Tries full response first, then fenced code blocks.
    Returns dict with known fields or None.
    """
    text = response.strip()
    if not text:
        return None

    # Try parsing the full response as YAML
    for source in [text, _extract_fenced_yaml(text)]:
        if source is None:
            continue
        try:
            data = yaml.safe_load(source)
            if isinstance(data, dict):
                return data
        except yaml.YAMLError:
            continue
    return None


def _extract_fenced_yaml(text: str) -> Optional[str]:
    import re
    match = re.search(r"```(?:yaml)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm.py -v -k "consolidate or extract"`
Expected: All 6 new tests pass

- [ ] **Step 5: Commit**

```bash
git add tests/test_llm.py podscribe/llm.py
git commit -m "feat: add LLM extraction for consolidate command"
```

---

### Task 4: CLI consolidate command handler

**Files:**
- Modify: `podscribe/cli.py`
- Add imports: `cmd_consolidate`, `cmd_config_consolidate_show`, `cmd_config_consolidate_set`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests for consolidate command**

Add to `tests/test_cli.py`:

```python
def test_consolidate_args_default_latest():
    parser = build_parser()
    args = parser.parse_args(["consolidate", "sam-chen"])
    assert args.command == "consolidate"
    assert args.pod == "sam-chen"
    assert args.meeting == "latest"
    assert args.no_log is False


def test_consolidate_args_with_meeting():
    parser = build_parser()
    args = parser.parse_args(["consolidate", "sam-chen", "2026-06-22"])
    assert args.command == "consolidate"
    assert args.pod == "sam-chen"
    assert args.meeting == "2026-06-22"


def test_consolidate_no_log_flag():
    parser = build_parser()
    args = parser.parse_args(["consolidate", "sam-chen", "--no-log"])
    assert args.no_log is True


def test_consolidate_no_log_flag_short():
    parser = build_parser()
    args = parser.parse_args(["consolidate", "sam-chen", "-n"])
    assert args.no_log is True


def test_consolidate_alias_pod_first():
    """`podscribe <pod> consolidate` rewrites correctly."""
    args = _parse(["sam-chen", "consolidate"])
    assert args.command == "consolidate"
    assert args.pod == "sam-chen"


def test_consolidate_alias_short():
    """`podscribe cons <pod>` rewrites to `consolidate <pod>`."""
    args = _parse(["cons", "sam-chen"])
    assert args.command == "consolidate"
    assert args.pod == "sam-chen"


def test_consolidate_alias_pod_first_short():
    """`podscribe <pod> cons` rewrites to `consolidate <pod>`."""
    args = _parse(["sam-chen", "cons"])
    assert args.command == "consolidate"
    assert args.pod == "sam-chen"


def test_config_consolidate_show():
    parser = build_parser()
    args = parser.parse_args(["config", "consolidate", "show"])
    assert args.command == "config"
    assert args.action == "consolidate"
    assert args.consolidate_action == "show"


def test_config_consolidate_set():
    parser = build_parser()
    args = parser.parse_args(["config", "consolidate", "set", "Extract {{summary}}"])
    assert args.command == "config"
    assert args.action == "consolidate"
    assert args.consolidate_action == "set"
    assert args.prompt == "Extract {{summary}}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v -k "consolidate or cons" 2>&1 | head -20`
Expected: Test failures for undefined parser commands

- [ ] **Step 3: Add parser entries and alias to cli.py**

In `build_parser()`, after the `enhance` subparser, add:

```python
    # consolidate
    p_cons = sub.add_parser("consolidate", help="Extract structured fields from enhanced summary and update CSV log.")
    p_cons.add_argument("pod", help="Pod name")
    p_cons.add_argument("meeting", nargs="?", default="latest", help="Meeting ID prefix (default: latest)")
    p_cons.add_argument("--no-log", "-n", action="store_true", help="Skip CSV log update")
    p_cons.set_defaults(func=cmd_consolidate)
```

In `build_parser()`, inside the `config` subparser, after the `llm` block:

```python
    p_cfg_cons = cfg_sub.add_parser("consolidate", help="Manage consolidate prompt.")
    cons_sub = p_cfg_cons.add_subparsers(dest="consolidate_action", required=True)
    p_cons_show = cons_sub.add_parser("show", help="Show consolidate prompt.")
    p_cons_show.set_defaults(func=cmd_config_consolidate_show)
    p_cons_set = cons_sub.add_parser("set", help="Set consolidate prompt.")
    p_cons_set.add_argument("prompt", help="Prompt template with {{summary}} placeholder")
    p_cons_set.set_defaults(func=cmd_config_consolidate_set)
```

In `rewrite_argv()`, update `known_commands` and `aliases`:

```python
    known_commands = {"init", "record", "list", "show", "context", "enhance", "config", "consolidate"}
    aliases = {"start": "record", "summarize": "enhance", "cons": "consolidate"}
```

- [ ] **Step 4: Add command handlers in cli.py**

Add these functions before `build_parser()`:

```python
def cmd_config_consolidate_show(args) -> int:
    from .config import load_consolidate_prompt
    prompt = load_consolidate_prompt()
    print(prompt)
    return 0


def cmd_config_consolidate_set(args) -> int:
    from .config import save_consolidate_prompt
    save_consolidate_prompt(args.prompt)
    print("Consolidate prompt set.")
    return 0
```

- [ ] **Step 5: Run parser tests to verify they pass**

Run: `pytest tests/test_cli.py -v -k "consolidate or cons"`
Expected: All 9 new parser tests pass

- [ ] **Step 6: Commit**

```bash
git add tests/test_cli.py podscribe/cli.py
git commit -m "feat: add consolidate parser, alias, and config subcommands"
```

- [ ] **Step 7: Write integration test for cmd_consolidate flow**

Add to `tests/test_cli.py`:

```python
from unittest.mock import patch, MagicMock

def test_cmd_consolidate_no_pod(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from podscribe.cli import cmd_consolidate, build_parser
    args = build_parser().parse_args(["consolidate", "nope"])
    rc = cmd_consolidate(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "No pod" in captured.err or "No pod" in captured.out


def test_cmd_consolidate_no_enhanced_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: "n")
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
    assert "No enhanced summary" in captured.out


def test_cmd_consolidate_with_no_log(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.cli import cmd_consolidate, build_parser

    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello world"))
    finalize_meeting(meeting)
    # Create fake enhanced summary
    date_str = "22-JUN-2026"
    summary_dir = pod.summaries_dir_for(date_str)
    summary_dir.mkdir(parents=True, exist_ok=True)
    enhanced = summary_dir / f"{meeting.id}.md"
    enhanced.write_text("# Enhanced\nWe talked about Q3 plans.")

    with patch("podscribe.cli.enhance_transcript", return_value="Enhanced summary."):
        with patch("podscribe.cli.extract_structured_fields", return_value={"quick_summary": "Test"}):
            args = build_parser().parse_args(["consolidate", "sam-chen", "--no-log"])
            rc = cmd_consolidate(args)
            assert rc == 0
    captured = capsys.readouterr()
    assert "Extracted" in captured.out or "consolidated" in captured.out or "quick_summary" in captured.out
```

- [ ] **Step 8: Implement cmd_consolidate function**

Add to `podscribe/cli.py`:

```python
def cmd_consolidate(args) -> int:
    """Extract structured fields from enhanced summary and update CSV log."""
    from .config import get_effective_glossary, load_consolidate_prompt
    from .glossary import format_glossary_prompt
    from .llm import build_consolidate_prompt, enhance_transcript, extract_structured_fields
    from .storage import append_log_row, log_entry_exists, log_path, rewrite_log_row

    if not pod_exists(args.pod):
        print(f"No pod '{args.pod}'.", file=sys.stderr)
        return 1

    pod = load_pod(args.pod)
    meetings = list_meetings(pod)
    if not meetings:
        print(f"No meetings for pod '{args.pod}'.", file=sys.stderr)
        return 1

    meeting_id = args.meeting if args.meeting != "latest" else meetings[0].id
    if args.meeting == "latest" or args.meeting is None:
        meeting = meetings[0]
    else:
        matching = [m for m in meetings if m.id.startswith(args.meeting)]
        if not matching:
            print(f"No meeting matching '{args.meeting}'.", file=sys.stderr)
            return 1
        meeting = matching[0]

    # Check if enhanced summary exists
    from datetime import datetime
    from .models import fmt_date
    date_str = fmt_date(datetime.fromisoformat(meeting.started_at))
    enhanced_path = pod.summaries_dir_for(date_str) / f"{meeting.id}.md"

    if not enhanced_path.exists():
        print(f"No enhanced summary for {meeting.id}. Run enhance first? [y/N] ", end="", file=sys.stderr)
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer in ("y", "yes"):
            from .llm import build_enhance_prompt, enhance_transcript
            from .config import load_project_config
            llm_config = pod.llm if pod.llm else load_project_config().get("llm")
            if not llm_config or not llm_config.get("model") or not llm_config.get("prompt_template"):
                print("LLM not configured. Set up LLM config first.", file=sys.stderr)
                return 1
            transcript = read_transcript(meeting)
            effective_glossary = get_effective_glossary(pod)
            prompt = build_enhance_prompt(llm_config["prompt_template"], effective_glossary, transcript)
            result = enhance_transcript(llm_config["model"], prompt)
            if result is None:
                print("Failed to reach Ollama.", file=sys.stderr)
                return 1
            enhanced_path.parent.mkdir(parents=True, exist_ok=True)
            enhanced_path.write_text(result)
            print(f"Enhanced summary saved to {enhanced_path}")
        else:
            print("Aborted.", file=sys.stderr)
            return 1

    # Read enhanced summary
    enhanced_text = enhanced_path.read_text()

    # Call LLM for structured extraction
    prompt_template = load_consolidate_prompt()
    prompt = build_consolidate_prompt(prompt_template, enhanced_text)

    llm_config = pod.llm if pod.llm else load_project_config().get("llm")
    model_name = llm_config.get("model", "qwen3.6") if llm_config else "qwen3.6"
    response = enhance_transcript(model_name, prompt)
    if response is None:
        print("Failed to reach Ollama for extraction.", file=sys.stderr)
        return 1

    fields = extract_structured_fields(response)
    if fields is None:
        print("Failed to parse structured fields from LLM response.", file=sys.stderr)
        print("Raw response:", response, file=sys.stderr)
        return 1

    quick_summary = fields.get("quick_summary", "")
    key_topics = "|".join(fields.get("key_topics", [])) if isinstance(fields.get("key_topics"), list) else str(fields.get("key_topics", ""))
    action_items = "|".join(fields.get("action_items", [])) if isinstance(fields.get("action_items"), list) else str(fields.get("action_items", ""))
    blockers = "|".join(fields.get("blockers", [])) if isinstance(fields.get("blockers"), list) else str(fields.get("blockers", ""))
    next_steps = "|".join(fields.get("next_steps", [])) if isinstance(fields.get("next_steps"), list) else str(fields.get("next_steps", ""))

    print(f"Extracted: {quick_summary}")
    print(f"  Topics: {key_topics}")
    print(f"  Actions: {action_items}")
    print(f"  Blockers: {blockers}")
    print(f"  Next: {next_steps}")

    if not args.no_log:
        log_fields = {
            "date": date_str,
            "person": pod.display_name,
            "meeting_id": meeting.id,
            "quick_summary": quick_summary,
            "key_topics": key_topics,
            "action_items": action_items,
            "blockers": blockers,
            "next_steps": next_steps,
            "summary_file": str(enhanced_path.relative_to(pod.base_path)) if enhanced_path else "",
            "transcript_file": str(meeting.transcript_path.relative_to(pod.base_path)) if meeting.transcript_path else "",
        }
        if log_entry_exists(pod, meeting.id):
            print(f"Log entry exists for {meeting.id}. Rewrite? [y/N] ", end="")
            try:
                answer = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            if answer in ("y", "yes"):
                rewrite_log_row(pod, meeting.id, log_fields)
                print(f"Log entry rewritten for {meeting.id}")
            else:
                print("Skipping log update.")
        else:
            append_log_row(pod, log_fields)
            print(f"Log entry appended to {log_path(pod)}")
    else:
        print("Skipping CSV log (--no-log)")

    return 0
```

- [ ] **Step 9: Run integration tests**

Run: `pytest tests/test_cli.py -v -k "consolidate"`
Expected: Parser and alias tests pass. Integration tests may need the handler to be defined.

- [ ] **Step 10: Commit**

```bash
git add tests/test_cli.py podscribe/cli.py
git commit -m "feat: implement consolidate command handler"
```

---

### Task 5: Run full test suite and verify

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v 2>&1 | tail -30`
Expected: All tests pass (including the 20+ new tests)

- [ ] **Step 2: Verify consolidate works end-to-end (manual)**

```bash
# Create a test pod
podscribe init smoke-consolidate --display-name "Smoke Test"

# Record (will time out quickly, that's fine)
echo "q" | timeout 3 podscribe record smoke-consolidate || true

# Enhance
podscribe enhance smoke-consolidate

# Consolidate
podscribe consolidate smoke-consolidate
```

Expected: CSV created at pods/smoke-consolidate/meetings.csv

- [ ] **Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "chore: finalize consolidate implementation"
```
