# Context Glossary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-pod glossary (names, projects, technical terms), inject as Whisper `initial_prompt` during live recording, and provide optional Ollama post-processing.

**Architecture:** Glossary entries stored in existing `config.yaml` as a new `glossary` key. `initial_prompt` string built from glossary and passed to pywhispercpp via `**params`. LLM enhance uses a thin HTTP client to Ollama with a user-editable prompt template. All new functionality behind CLI subcommands `context` and `enhance`.

**Tech Stack:** Python 3.10+, pywhispercpp, Ollama (for enhance only), yaml, requests

---

### Task 1: Add glossary and llm fields to Pod model

**Files:**
- Modify: `podscribe/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write tests for new fields**

```python
# tests/test_models.py — add to bottom

class TestPodGlossary:
    def test_default_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pod = Pod(name="sam-chen")
        assert pod.glossary == []

    def test_with_entries(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pod = Pod(
            name="sam-chen",
            glossary=[
                {"term": "Anurag Kaushik", "category": "person"},
                {"term": "Project Helios", "category": "project"},
            ],
        )
        assert len(pod.glossary) == 2
        assert pod.glossary[0]["term"] == "Anurag Kaushik"
        assert pod.glossary[1]["category"] == "project"

    def test_llm_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pod = Pod(
            name="sam-chen",
            llm={"model": "llama3.2", "prompt_template": "fix {{transcript}}"},
        )
        assert pod.llm["model"] == "llama3.2"


class TestPodLlmDefault:
    def test_default_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pod = Pod(name="sam-chen")
        assert pod.llm is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_models.py::TestPodGlossary tests/test_models.py::TestPodLlmDefault -v`

Expected: FAIL — Pod has no `glossary` or `llm` field

- [ ] **Step 3: Add glossary and llm fields to Pod dataclass**

```python
@dataclass
class Pod:
    name: str
    display_name: str = ""
    role: str = ""
    cadence: str = "weekly"
    notes: str = ""
    created_at: str = ""
    glossary: Optional[list] = None
    llm: Optional[dict] = None
    base_path: Optional[Path] = None
```

- [ ] **Step 4: Initialize defaults in __post_init__**

Add after the `if not self.created_at:` block:

```python
if self.glossary is None:
    self.glossary = []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_models.py::TestPodGlossary tests/test_models.py::TestPodLlmDefault -v`

Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`

Expected: all tests pass

---

### Task 2: Update config save/load for glossary and llm

**Files:**
- Modify: `podscribe/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write tests for glossary round-trip**

```python
# tests/test_config.py — add to bottom

def test_glossary_roundtrip(tmp_path):
    pod = Pod(
        name="sam-chen",
        display_name="Sam Chen",
        glossary=[
            {"term": "Anurag Kaushik", "category": "person"},
            {"term": "Project Helios", "category": "project"},
        ],
        llm={"model": "llama3.2", "prompt_template": "fix {{transcript}}"},
        base_path=tmp_path / "pods" / "sam-chen",
    )
    pod.base_path.mkdir(parents=True)
    save_pod_config(pod)
    loaded = load_pod_config(pod.base_path)
    assert loaded.glossary == pod.glossary
    assert loaded.llm == pod.llm
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_config.py::test_glossary_roundtrip -v`

Expected: FAIL — `save_pod_config` doesn't include glossary/llm

- [ ] **Step 3: Update save_pod_config to include glossary and llm**

```python
def save_pod_config(pod: Pod) -> None:
    data = {
        "name": pod.name,
        "display_name": pod.display_name,
        "role": pod.role,
        "cadence": pod.cadence,
        "notes": pod.notes,
        "created_at": pod.created_at,
    }
    if pod.glossary:
        data["glossary"] = pod.glossary
    if pod.llm:
        data["llm"] = pod.llm
    with pod.config_path.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_config.py::test_glossary_roundtrip -v`

Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`

Expected: all tests pass

---

### Task 3: Create glossary module

**Files:**
- Create: `podscribe/glossary.py`
- Test: `tests/test_glossary.py`

- [ ] **Step 1: Write tests for glossary operations**

```python
# tests/test_glossary.py
import pytest
from podscribe.glossary import add_entry, remove_entry, format_glossary_prompt
from podscribe.models import Pod


def test_add_entry():
    pod = Pod(name="sam-chen")
    add_entry(pod, "Anurag Kaushik", "person")
    assert len(pod.glossary) == 1
    assert pod.glossary[0] == {"term": "Anurag Kaushik", "category": "person"}


def test_add_duplicate_raises():
    pod = Pod(name="sam-chen", glossary=[{"term": "Anurag Kaushik", "category": "person"}])
    with pytest.raises(ValueError, match="already in glossary"):
        add_entry(pod, "Anurag Kaushik", "person")


def test_add_empty_raises():
    pod = Pod(name="sam-chen")
    with pytest.raises(ValueError, match="cannot be empty"):
        add_entry(pod, "", "person")


def test_remove_entry():
    pod = Pod(name="sam-chen", glossary=[{"term": "Anurag Kaushik", "category": "person"}])
    remove_entry(pod, "Anurag Kaushik")
    assert pod.glossary == []


def test_remove_nonexistent_raises():
    pod = Pod(name="sam-chen")
    with pytest.raises(ValueError, match="not found"):
        remove_entry(pod, "Nobody")


def test_format_empty_glossary():
    result = format_glossary_prompt([])
    assert result == ""


def test_format_with_terms():
    glossary = [
        {"term": "Anurag Kaushik", "category": "person"},
        {"term": "Project Helios", "category": "project"},
    ]
    result = format_glossary_prompt(glossary)
    assert "Anurag Kaushik" in result
    assert "Project Helios" in result
    assert result.startswith("Please transcribe")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_glossary.py -v`

Expected: FAIL — module not found

- [ ] **Step 3: Create glossary module**

```python
"""Glossary management: add, remove, list entries and format for Whisper biasing."""
from __future__ import annotations

from .models import Pod


def add_entry(pod: Pod, term: str, category: str = "") -> None:
    term = term.strip()
    if not term:
        raise ValueError("Term cannot be empty")
    if any(e["term"] == term for e in pod.glossary):
        raise ValueError(f"'{term}' is already in glossary")
    pod.glossary.append({"term": term, "category": category})


def remove_entry(pod: Pod, term: str) -> None:
    term = term.strip()
    for i, entry in enumerate(pod.glossary):
        if entry["term"] == term:
            pod.glossary.pop(i)
            return
    raise ValueError(f"'{term}' not found in glossary")


def format_glossary_prompt(glossary: list) -> str:
    if not glossary:
        return ""
    terms = ", ".join(e["term"] for e in glossary)
    return f"Please transcribe the following names and project names correctly: {terms}."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_glossary.py -v`

Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`

Expected: all tests pass

---

### Task 4: Add context subcommand to CLI

**Files:**
- Modify: `podscribe/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write tests for context subcommand**

```python
# tests/test_cli.py — add to bottom

def test_context_add_args():
    parser = build_parser()
    args = parser.parse_args(["context", "sam-chen", "add", "Anurag Kaushik", "--category", "person"])
    assert args.command == "context"
    assert args.pod == "sam-chen"
    assert args.action == "add"
    assert args.term == "Anurag Kaushik"
    assert args.category == "person"


def test_context_remove_args():
    parser = build_parser()
    args = parser.parse_args(["context", "sam-chen", "remove", "Anurag Kaushik"])
    assert args.command == "context"
    assert args.action == "remove"


def test_context_list_args():
    parser = build_parser()
    args = parser.parse_args(["context", "sam-chen", "list"])
    assert args.command == "context"
    assert args.action == "list"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::test_context_add_args tests/test_cli.py::test_context_remove_args tests/test_cli.py::test_context_list_args -v`

Expected: FAIL — no context subcommand

- [ ] **Step 3: Add context subparser and handler**

Add import at top:
```python
from .glossary import add_entry, format_glossary_prompt, remove_entry
```

Add command handlers before `build_parser`:

```python
def cmd_context_add(args) -> int:
    from .storage import load_pod, save_pod_config
    pod = load_pod(args.pod)
    add_entry(pod, args.term, args.category or "")
    save_pod_config(pod)
    print(f"Added '{args.term}' to glossary for pod '{args.pod}'")
    return 0


def cmd_context_remove(args) -> int:
    from .storage import load_pod, save_pod_config
    pod = load_pod(args.pod)
    remove_entry(pod, args.term)
    save_pod_config(pod)
    print(f"Removed '{args.term}' from glossary for pod '{args.pod}'")
    return 0


def cmd_context_list(args) -> int:
    from .storage import load_pod
    pod = load_pod(args.pod)
    if not pod.glossary:
        print(f"No glossary entries for pod '{args.pod}'.")
        return 0
    print(f"Glossary for {pod.name} ({pod.display_name}):")
    for entry in pod.glossary:
        cat = f" ({entry['category']})" if entry.get("category") else ""
        print(f"  • {entry['term']}{cat}")
    return 0
```

Add context subparser in `build_parser` after the show subparser:

```python
    # context
    p_ctx = sub.add_parser("context", help="Manage glossary (names, projects, terms).")
    p_ctx.add_argument("pod", help="Pod name")
    ctx_sub = p_ctx.add_subparsers(dest="action", required=True)
    p_ctx_add = ctx_sub.add_parser("add", help="Add a term to the glossary")
    p_ctx_add.add_argument("term", help="Term to add (e.g. 'Anurag Kaushik')")
    p_ctx_add.add_argument("--category", help="Category (person, project, client)")
    p_ctx_add.set_defaults(func=cmd_context_add)
    p_ctx_rm = ctx_sub.add_parser("remove", help="Remove a term from the glossary")
    p_ctx_rm.add_argument("term", help="Term to remove")
    p_ctx_rm.set_defaults(func=cmd_context_remove)
    p_ctx_ls = ctx_sub.add_parser("list", help="List glossary entries")
    p_ctx_ls.set_defaults(func=cmd_context_list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::test_context_add_args tests/test_cli.py::test_context_remove_args tests/test_cli.py::test_context_list_args -v`

Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`

Expected: all tests pass

---

### Task 5: Update Transcriber to accept initial_prompt

**Files:**
- Modify: `podscribe/transcriber.py`
- Test: `tests/test_transcriber.py` (create)

- [ ] **Step 1: Write test for initial_prompt passthrough**

```python
# tests/test_transcriber.py
import numpy as np
import pytest
from podscribe.transcriber import Transcriber


def test_transcriber_accepts_initial_prompt():
    """Verify initial_prompt is accepted as a parameter (no crash)."""
    t = Transcriber(model="base.en", n_threads=4, print_progress=False)
    audio = np.random.randn(16000).astype(np.float32) * 0.01
    # Should not raise
    results = t.transcribe(audio, initial_prompt="Test prompt context.")
    assert isinstance(results, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_transcriber.py -v`

Expected: FAIL — transcribe doesn't accept initial_prompt

- [ ] **Step 3: Update Transcriber.transcribe to pass **kwargs to pywhispercpp**

```python
def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, **kwargs) -> List[dict]:
    self._load()
    if audio.ndim > 1:
        audio = audio.reshape(-1)
    if audio.size == 0:
        return []
    audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name
        with wave.open(tmp_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())

        segments = self._model.transcribe(tmp_path, **kwargs)
        results = []
        for s in segments:
            t0 = float(getattr(s, "t0", 0) or 0)
            t1 = float(getattr(s, "t1", 0) or 0)
            text = (getattr(s, "text", "") or "").strip()
            t0 /= 1000.0
            t1 /= 1000.0
            if text:
                results.append({"start": t0, "end": t1, "text": text})
        return results
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_transcriber.py -v`

Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`

Expected: all tests pass

---

### Task 6: Wire glossary into live recording flow

**Files:**
- Modify: `podscribe/cli.py` (cmd_record)

- [ ] **Step 1: Write test verifying initial_prompt construction in record**

```python
# tests/test_cli.py — add

def test_record_uses_glossary_prompt():
    """When a pod has glossary entries, cmd_record builds initial_prompt."""
    from podscribe.glossary import format_glossary_prompt
    glossary = [{"term": "Project Helios", "category": "project"}]
    prompt = format_glossary_prompt(glossary)
    assert "Project Helios" in prompt
```

- [ ] **Step 2: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::test_record_uses_glossary_prompt -v`

Expected: PASS (uses existing format_glossary_prompt)

- [ ] **Step 3: Update cmd_record to pass initial_prompt**

In `cmd_record`, after loading the pod and before the transcription loop, add:

```python
    # Build glossary prompt if pod has glossary entries
    glossary_prompt = format_glossary_prompt(pod.glossary) if pod.glossary else None
```

Then in the transcription loop, change the transcribe call:

```python
    for audio_segment in capture.segments():
        kwargs = {}
        if glossary_prompt:
            kwargs["initial_prompt"] = glossary_prompt
        results = transcriber.transcribe(audio_segment, **kwargs)
```

Add import at top:
```python
from .glossary import add_entry, format_glossary_prompt, remove_entry
```

(If `format_glossary_prompt` and `remove_entry` are already imported from Task 4's additions, just add `format_glossary_prompt`.)

- [ ] **Step 4: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`

Expected: all tests pass

---

### Task 7: Create LLM client module

**Files:**
- Create: `podscribe/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write tests for LLM module**

```python
# tests/test_llm.py
import pytest
from podscribe.llm import build_enhance_prompt


GLOSSARY = [
    {"term": "Anurag Kaushik", "category": "person"},
    {"term": "Project Helios", "category": "project"},
]
TEMPLATE = "Correct these names: {{glossary}}\n\nTranscript:\n{{transcript}}"


def test_build_enhance_prompt_inserts_glossary():
    transcript = "Anuraj spoke about project helios"
    prompt = build_enhance_prompt(TEMPLATE, GLOSSARY, transcript)
    assert "Anurag Kaushik" in prompt
    assert "Project Helios" in prompt
    assert transcript in prompt


def test_build_enhance_prompt_empty_glossary():
    transcript = "hello world"
    prompt = build_enhance_prompt(TEMPLATE, [], transcript)
    assert transcript in prompt


def test_build_enhance_prompt_no_transcript_var():
    """If template doesn't contain {{transcript}}, it's appended."""
    template = "Just fix this."
    prompt = build_enhance_prompt(template, GLOSSARY, "some text")
    assert "some text" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_llm.py -v`

Expected: FAIL — module not found

- [ ] **Step 3: Create LLM module**

```python
"""Ollama HTTP client for transcript enhancement."""
from __future__ import annotations

import json
from typing import List, Optional

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"


def build_enhance_prompt(template: str, glossary: list, transcript: str) -> str:
    glossary_text = ", ".join(
        f"{e['term']} ({e.get('category', 'other')})" for e in glossary
    )
    prompt = template.replace("{{glossary}}", glossary_text)
    prompt = prompt.replace("{{transcript}}", transcript)
    if "{{transcript}}" not in template:
        prompt += "\n\n" + transcript
    return prompt


def enhance_transcript(
    model: str,
    prompt: str,
    *,
    timeout: int = 120,
) -> Optional[str]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.ConnectionError:
        return None
    except requests.Timeout:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_llm.py -v`

Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`

Expected: all tests pass

---

### Task 8: Add enhance subcommand to CLI

**Files:**
- Modify: `podscribe/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write tests for enhance subcommand args**

```python
# tests/test_cli.py — add

def test_enhance_args():
    parser = build_parser()
    args = parser.parse_args(["enhance", "sam-chen", "latest"])
    assert args.command == "enhance"
    assert args.pod == "sam-chen"
    assert args.meeting == "latest"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::test_enhance_args -v`

Expected: FAIL — no enhance subcommand

- [ ] **Step 3: Add enhance subparser and handler**

Add import at top:
```python
from .glossary import add_entry, remove_entry
```

Add handler before `build_parser`:

```python
def cmd_enhance(args) -> int:
    from .storage import list_meetings, load_pod, read_transcript

    if not pod_exists(args.pod):
        print(f"No pod '{args.pod}'.", file=sys.stderr)
        return 1

    pod = load_pod(args.pod)
    if not pod.llm or not pod.llm.get("model") or not pod.llm.get("prompt_template"):
        print(
            "LLM not configured for this pod. "
            "Add an 'llm' section to config.yaml with 'model' and 'prompt_template'.",
            file=sys.stderr,
        )
        return 1

    meetings = list_meetings(pod)
    if not meetings:
        print(f"No meetings for pod '{args.pod}'.", file=sys.stderr)
        return 1

    if args.meeting == "latest":
        meeting = meetings[0]
    else:
        matching = [m for m in meetings if m.id.startswith(args.meeting)]
        if not matching:
            print(f"No meeting matching '{args.meeting}'.", file=sys.stderr)
            return 1
        meeting = matching[0]

    transcript = read_transcript(meeting)
    prompt = build_enhance_prompt(
        pod.llm["prompt_template"], pod.glossary, transcript
    )

    print(f"Enhancing transcript for {meeting.id}...")
    print(f"  model: {pod.llm['model']}")
    print(f"  Ollama URL: http://localhost:11434")
    print()

    result = enhance_transcript(pod.llm["model"], prompt)
    if result is None:
        print(
            "Failed to reach Ollama. Is it running? "
            "Start with: ollama serve",
            file=sys.stderr,
        )
        return 1

    enhanced_path = meeting.transcript_path.with_suffix(".enhanced.md")
    enhanced_path.write_text(result)
    print(f"Enhanced transcript saved to {enhanced_path}")
    return 0
```

Add subparser in `build_parser` after the context subparser:

```python
    # enhance
    p_enh = sub.add_parser("enhance", help="Enhance transcript via local LLM (Ollama).")
    p_enh.add_argument("pod", help="Pod name")
    p_enh.add_argument("meeting", help="Meeting ID prefix or 'latest'")
    p_enh.set_defaults(func=cmd_enhance)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::test_enhance_args -v`

Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`

Expected: all tests pass
