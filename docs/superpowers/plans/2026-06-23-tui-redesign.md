# TUI Redesign (Hybrid) + Enhance Progress-Bar Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the fictional enhance "progress bar" and add a hybrid TUI (remembered-pod launcher + `rich.live` views for record/enhance) without duplicating record/enhance orchestration or breaking the 205 existing tests.

**Architecture:** Extract `enhance_transcript` and the record loop into headless cores that take plain-callable render callbacks. The existing CLI handlers become thin wrappers using plain-text callbacks (so piped/legacy output and tests are byte-compatible). A new lazy-imported `podscribe/tui.py` hosts the launcher, the `rich.live` live views, and a `Console.status`/`Confirm.ask` consolidate screen. Bare `podscribe` (TTY only) opens the launcher; everything else (`podscribe <pod> <cmd>`, aliases, `--help`, non-TTY) is unchanged or guarded.

**Tech Stack:** Python ≥3.10, `rich>=13.7`, `readchar>=4.0`. Removes `tqdm>=4.64` (only `llm.py` used it).

**Spec:** `docs/superpowers/specs/2026-06-23-tui-redesign-design.md`

**Worktree:** Execute inside a worktree (`superpowers:using-git-worktrees`) to isolate from the pending uncommitted `.gitignore`/`AGENTS.md` edits.

---

## File structure (locked)

| File | Role | Change |
|---|---|---|
| `pyproject.toml` | deps | Add `rich`, `readchar`; remove `tqdm` |
| `requirements.txt` | deps mirror | Same as above |
| `podscribe/config.py` | project config | Add `load_last_pod` / `save_last_pod` |
| `podscribe/llm.py` | enhance core | Remove tqdm + `show_progress`; callback-based `enhance_transcript`; remove header preface |
| `podscribe/cli.py` | CLI handlers + entry | Extract `run_record_session`; thin wrappers; extract `run_consolidate`; TTY-guarded entry point dispatching bare `podscribe` → `tui.launch()` |
| `podscribe/tui.py` | **NEW** interactive surface | `launch`, `record_view`, `enhance_view`, `consolidate_screen`, palette, `readchar` key reader, Ollama status probe |
| `tests/test_llm.py` | core tests | Update all call sites (drop `show_progress`); rewrite cleanup test; add on_token/on_stats regression |
| `tests/test_cli.py` | CLI tests | Add `run_record_session`, `run_consolidate`, entry-point guard tests; update header/metrics assertions to target the wrapper |
| `tests/test_tui.py` | **NEW** TUI smoke | `launch()` no-pods, with-pods, non-TTY guard |
| `docs/USER-MANUAL.md` | user docs | Rewrite "Streaming output" section (lines 160-176) |
| `AGENTS.md` | agent docs | Tree + launcher note + drop `tqdm` |

---

## Task 1: Update dependencies

**Files:**
- Modify: `pyproject.toml:14-22`
- Modify: `requirements.txt:4`

- [ ] **Step 1: Update `pyproject.toml` dependencies**

Replace the dependencies block (lines 14-22) with:

```toml
dependencies = [
    "mlx-whisper>=0.4.0",
    "webrtcvad>=2.0.10",
    "sounddevice>=0.4.6",
    "rich>=13.7",
    "readchar>=4.0",
    "numpy>=1.24",
    "pyyaml>=6.0",
    "requests>=2.28",
]
```

- [ ] **Step 2: Update `requirements.txt`**

Replace line 4 (`tqdm>=4.64`) with:

```
rich>=13.7
readchar>=4.0
```

- [ ] **Step 3: Install**

Run:

```bash
pip install -e .
```

Expected: installs `rich` and `readchar`; uninstalls `tqdm` if present. No errors.

- [ ] **Step 4: Verify import**

Run:

```bash
python -c "import rich, readchar; print(rich.__version__, readchar.__version__)"
```

Expected: prints two version strings, no `ModuleNotFoundError`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements.txt
git commit -m "chore(deps): add rich + readchar, drop tqdm"
```

---

## Task 2: `last_pod` round-trip in project config

**Files:**
- Modify: `podscribe/config.py` (add functions after `save_project_config`, before `load_leadership_glossary`)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
from podscribe.config import load_last_pod, save_last_pod


def test_load_last_pod_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_last_pod() is None


def test_save_then_load_last_pod(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_last_pod("sam-chen")
    assert load_last_pod() == "sam-chen"


def test_last_pod_coexists_with_existing_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.config import save_project_config, load_project_config
    save_project_config({"llm": {"model": "qwen3.6:27b", "prompt_template": "x"}})
    save_last_pod("sam-chen")
    cfg = load_project_config()
    assert cfg["llm"]["model"] == "qwen3.6:27b"
    assert cfg["last_pod"] == "sam-chen"
```

- [ ] **Step 2: Run tests, verify failure**

```bash
pytest tests/test_config.py -k "last_pod" -v
```

Expected: 3 failures with `ImportError: cannot import name 'load_last_pod'`.

- [ ] **Step 3: Implement `load_last_pod` / `save_last_pod`**

In `podscribe/config.py`, insert after `save_project_config` (after line 63) and before `load_leadership_glossary`:

```python
def load_last_pod() -> Optional[str]:
    """Return the last-used pod name from podscribe.yaml, or None."""
    cfg = load_project_config()
    value = cfg.get("last_pod")
    return value if isinstance(value, str) and value else None


def save_last_pod(name: str) -> None:
    """Persist the last-used pod name in podscribe.yaml (preserves other keys)."""
    if not name or not isinstance(name, str):
        raise ValueError("last_pod must be a non-empty string")
    cfg = load_project_config()
    cfg["last_pod"] = name
    save_project_config(cfg)
```

Add `from typing import Optional` to the imports at the top of `config.py` (insert after line 2 `from __future__ import annotations`).

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_config.py -k "last_pod" -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add podscribe/config.py tests/test_config.py
git commit -m "feat(config): round-trip last_pod in podscribe.yaml"
```

---

## Task 3: Make `enhance_transcript` a headless core (the bug fix)

**Files:**
- Modify: `podscribe/llm.py` (rewrite `enhance_transcript`; drop tqdm; drop header preface)
- Modify: `tests/test_llm.py` (update all 10 call sites; rewrite cleanup test; add callback regression)

- [ ] **Step 1: Write the callback regression test (the bug-fix test)**

Add to `tests/test_llm.py`:

```python
def test_enhance_transcript_fires_on_token_and_on_stats():
    """Regression: tokens stream via on_token; stats via on_stats on done."""
    resp = make_streaming_response(
        ["Sam", " will", " review"],
        final_stats={"prompt_eval_count": 10, "eval_count": 3,
                     "total_duration": 2_000_000_000, "eval_duration": 1_000_000_000},
    )
    tokens: list = []
    stats: list = []
    with patch("podscribe.llm.requests.post", return_value=resp):
        result = enhance_transcript(
            "qwen3.6:27b", "go",
            on_token=tokens.append, on_stats=stats.append,
        )
    assert result == "Sam will review"
    assert tokens == ["Sam", " will", " review"]
    assert len(stats) == 1
    assert stats[0]["eval_count"] == 3
    assert stats[0]["prompt_eval_count"] == 10


def test_enhance_transcript_does_not_import_tqdm():
    """The core must not depend on tqdm; the fictional progress bar is gone."""
    import podscribe.llm as llm_mod
    assert not hasattr(llm_mod, "tqdm"), "llm.py must not import tqdm"
```

- [ ] **Step 2: Run the new tests, verify failure**

```bash
pytest tests/test_llm.py::test_enhance_transcript_fires_on_token_and_on_stats tests/test_llm.py::test_enhance_transcript_does_not_import_tqdm -v
```

Expected: both FAIL — first because `on_token`/`on_stats` are not yet accepted; second will pass once tqdm is removed (temporarily still imported). The first failure is what matters.

- [ ] **Step 3: Rewrite `podscribe/llm.py`**

Replace the entire `podscribe/llm.py` with:

```python
"""Ollama HTTP client for transcript enhancement."""
from __future__ import annotations

import json
import re
import sys
import time
from typing import Callable, List, Optional

import requests
import yaml

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_SHOW_URL = "http://localhost:11434/api/show"

ANTI_HALLUCINATION_PREAMBLE = (
    "Strict grounding rules — read carefully:\n"
    "1. Every claim must come from the transcript. Do NOT use outside "
    "knowledge, training data, or assumptions about the people or projects "
    "mentioned.\n"
    "2. If something is unclear, missing, or you do not understand it, "
    "say so explicitly — e.g. 'Not mentioned in the transcript', "
    "'I don't know', or 'Unclear from the transcript'. Do NOT guess.\n"
    "3. Never invent names, dates, action items, decisions, or other facts. "
    "If the transcript does not say it, do not write it."
)

SPEAKER_PRESERVATION_PREAMBLE = (
    "Preserve all names exactly as they appear in the transcript. "
    "For each action item, name the responsible person "
    '(e.g. "Sam will review the auth middleware design"). '
    'If the transcript does not name a person, write "Unassigned — needs owner" '
    "rather than dropping the item."
)


def build_enhance_prompt(
    template: str,
    glossary: list,
    transcript: str,
    *,
    preserve_speakers: bool = True,
) -> str:
    if preserve_speakers:
        template = (
            ANTI_HALLUCINATION_PREAMBLE
            + "\n\n"
            + SPEAKER_PRESERVATION_PREAMBLE
            + "\n\n"
            + template
        )
    glossary_text = ", ".join(
        f"{e['term']} ({e.get('category', 'other')})" for e in glossary
    )
    prompt = template.replace("{{glossary}}", glossary_text)
    prompt = prompt.replace("{{transcript}}", transcript)
    if "{{transcript}}" not in template:
        prompt += "\n\n" + transcript
    return prompt


def ollama_model_info(model: str) -> dict:
    """Fetch model details (num_ctx etc.) from /api/show. Best-effort.

    Public (no underscore) so the TUI/CLI can call it for header rendering.
    """
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
    on_token: Callable[[str], None] = lambda t: None,
    on_stats: Callable[[dict], None] = lambda d: None,
    on_retry: Callable[[int, str], None] = lambda a, e: None,
) -> Optional[str]:
    """Stream from Ollama, fire callbacks, return full text (None on failure).

    Headless core: no tqdm, no header preface, no show_progress flag. The
    caller (plain wrapper or rich view) decides how to render tokens/stats.

    Retries up to max_retries on connection errors and 5xx. Does NOT retry
    on 4xx (bad prompt, model not found). timeout=1800s (30 min).

    on_token(str): fires once per streamed chunk with a "response" key.
    on_stats(dict): fires once on the done chunk with
        {"prompt_eval_count","eval_count","total_duration_ns","eval_duration_ns"}.
    on_retry(attempt:int, error:str): fires before each retry sleep
        (so views can show "retrying…").
    """
    payload = {"model": model, "prompt": prompt, "stream": True}
    delays = [1, 2, 4]

    for attempt in range(max_retries):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=1800)
            resp.raise_for_status()

            text_parts: list = []
            stats: dict = {}
            try:
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "response" in chunk:
                        text_parts.append(chunk["response"])
                        on_token(chunk["response"])
                    if chunk.get("done"):
                        stats = {
                            "prompt_eval_count": chunk.get("prompt_eval_count", 0),
                            "eval_count": chunk.get("eval_count", 0),
                            "total_duration_ns": chunk.get("total_duration", 0),
                            "eval_duration_ns": chunk.get("eval_duration", 0),
                        }
                        break
            except requests.RequestException as e:
                if attempt < max_retries - 1:
                    on_retry(attempt + 1, str(e))
                    time.sleep(delays[min(attempt, len(delays) - 1)])
                    continue
                return None

            on_stats(stats)
            return "".join(text_parts)

        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status is not None and 400 <= status < 500:
                return None  # 4xx: don't retry
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                on_retry(attempt + 1, str(e))
                time.sleep(delays[min(attempt, len(delays) - 1)])
                continue
            return None

    return None


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
    match = re.search(r"```(?:yaml)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None
```

Key changes vs. the old file: `tqdm` import removed; `enhance_transcript` takes `on_token`/`on_stats`/`on_retry` callbacks (defaults no-op); `show_progress` removed; the "Calling Model…/Context window size…" header preface removed from the core; `_ollama_model_info` renamed to public `ollama_model_info` (caller uses it). Retry loop fires `on_retry` before sleeps.

- [ ] **Step 4: Update the 10 call sites in `tests/test_llm.py`**

For every call of the form:

```python
enhance_transcript("...", "...", show_progress=False)
enhance_transcript("...", "...", show_progress=True)
enhance_transcript("...", "...", show_progress=False, max_retries=...)
enhance_transcript("...", "...", max_retries=..., show_progress=...)
```

change to:

```python
enhance_transcript("...", "...")
enhance_transcript("...", "...", max_retries=...)
```

(just drop the `show_progress=...` kwarg). Update all 10 sites: `test_enhance_transcript_success` (line 65), `test_enhance_transcript_connection_error` (76), `test_enhance_transcript_http_error` (86), `test_enhance_streams_and_returns_full_text` (196), `test_enhance_retries_on_5xx` (209), `test_enhance_no_retry_on_4xx` (220), `test_enhance_uses_30_minute_timeout` (249), `test_enhance_high_max_retries_doesnt_crash` (275). Also drop the `with patch("podscribe.llm.tqdm", return_value=bar_mock):` line in `test_enhance_closes_progress_bar_on_stream_error` — see Step 5.

- [ ] **Step 5: Rewrite the cleanup test (preserve intent, drop tqdm)**

Replace `test_enhance_closes_progress_bar_on_stream_error` (line 253) with:

```python
def test_enhance_transcript_cleans_up_on_stream_error():
    """If iter_lines raises mid-stream, the core returns None and does not re-raise.

    Preserves the intent of the old tqdm-cleanup test (no resource leak / clean
    teardown on error) without the tqdm-specific assertion: assert the function
    returns None, no exception escapes, and on_token/on_stats are not called
    after the error.
    """
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.iter_lines = MagicMock(side_effect=requests.ConnectionError("stream dropped"))

    tokens: list = []
    stats: list = []

    with patch("podscribe.llm.requests.post", return_value=resp):
        with patch("podscribe.llm.time.sleep"):
            result = enhance_transcript(
                "qwen3.6:27b", "go", max_retries=1,
                on_token=tokens.append, on_stats=stats.append,
            )
    assert result is None
    assert tokens == []
    assert stats == []
```

- [ ] **Step 6: Update the header/metrics test (`test_enhance_prints_metrics_to_stderr`)**

The header lines ("Calling Model:…", "Context window size:…") now live in the wrapper, and the metrics line is produced by the wrapper's `on_stats` callback. The core itself prints nothing. Split the test: keep the *core* portion (asserts no header from the core) and add a wrapper-level test in Task 4. Replace the test (line 225) with:

```python
def test_enhance_core_prints_nothing_to_stderr(capfd):
    """The headless core emits no header/metrics — callers handle rendering."""
    resp = make_streaming_response(
        ["Hi"],
        final_stats={"prompt_eval_count": 7, "eval_count": 1,
                     "total_duration": 1_000_000_000, "eval_duration": 100_000_000},
    )
    with patch("podscribe.llm.requests.post", return_value=resp):
        enhance_transcript("qwen3.6:27b", "go")
    captured = capfd.readouterr()
    assert "Calling Model" not in captured.err
    assert "Context window size" not in captured.err
```

- [ ] **Step 7: Run all llm tests, verify pass**

```bash
pytest tests/test_llm.py -v
```

Expected: all pass (including the new regression tests and the rewritten cleanup test). The 4xx-no-retry and high-max-retries tests should still pass (retry loop logic is preserved, just with `on_retry` firing).

- [ ] **Step 8: Commit**

```bash
git add podscribe/llm.py tests/test_llm.py
git commit -m "feat(llm): headless enhance_transcript with on_token/on_stats/on_retry; remove tqdm"
```

---

## Task 4: `_run_enhance` wrapper — header + plain callbacks + metrics line

**Files:**
- Modify: `podscribe/cli.py:69-80` (`_run_enhance`)
- Modify: `tests/test_cli.py` (add wrapper-level test for header + metrics)

- [ ] **Step 1: Write the failing test for the wrapper**

Add to `tests/test_cli.py`:

```python
from podscribe.cli import _run_enhance
from podscribe.llm import ollama_model_info  # imported for monkeypatch


def test_run_enhance_prints_header_and_metrics(capfd, monkeypatch):
    """The CLI wrapper prints the Calling/Context header and the metrics line."""
    resp = make_streaming_response(
        ["Hi"],
        final_stats={"prompt_eval_count": 7, "eval_count": 1,
                     "total_duration": 1_000_000_000, "eval_duration": 100_000_000},
    )
    monkeypatch.setattr("podscribe.cli.ollama_model_info",
                        lambda model: {"model_info": {"llama.context_length": 32768}})
    with patch("podscribe.cli.requests.post", return_value=resp):
        text, err = _run_enhance("the prompt", "qwen3.6:27b")
    captured = capfd.readouterr()
    assert err is None
    assert text == "Hi"
    assert "Calling Model:qwen3.6:27b" in captured.err
    assert "Context window size : 32768 tokens" in captured.err
    assert "prompt 7" in captured.err
    assert "response 1 tokens" in captured.err
    assert "tok/s" in captured.err
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/test_cli.py::test_run_enhance_prints_header_and_metrics -v
```

Expected: FAIL — current `_run_enhance` returns the text but prints nothing (the header was inside the old core).

- [ ] **Step 3: Rewrite `_run_enhance`**

Replace `podscribe/cli.py:69-80` with:

```python
def _run_enhance(
    prompt: str, model: str,
) -> tuple[Optional[str], Optional[str]]:
    """Run LLM enhance. Returns (text, None) on success, (None, error) on failure.

    The wrapper owns the 'Calling Model:…/Context window size:…' header and the
    final '✓ done in Ns | prompt X + response Y tokens @ Z tok/s' metrics line
    (both to stderr). The core just streams and fires on_token/on_stats.
    """
    info = ollama_model_info(model)
    num_ctx = (info.get("model_info") or {}).get("llama.context_length", "?")
    sys.stderr.write(f"Calling Model:{model}...\n")
    sys.stderr.write(f"Context window size : {num_ctx} tokens\n")
    sys.stderr.flush()

    def _on_stats(stats: dict) -> None:
        pe = stats.get("prompt_eval_count", 0)
        ec = stats.get("eval_count", 0)
        ed = (stats.get("eval_duration_ns", 0) or 1) / 1e9
        tps = ec / ed if ed > 0 else 0
        total_s = (stats.get("total_duration_ns", 0) or 1) / 1e9
        sys.stderr.write(
            f"  \u2713 done in {total_s:.1f}s | "
            f"prompt {pe} + response {ec} tokens @ {tps:.1f} tok/s\n"
        )
        sys.stderr.flush()

    result = enhance_transcript(model, prompt, on_stats=_on_stats)
    if result is None:
        return None, "Failed to reach Ollama. Is it running? Start with: ollama serve"
    return result, None
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_cli.py::test_run_enhance_prints_header_and_metrics -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite to confirm no regressions**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: all offline tests pass (the `transcriber` smoke test downloads a model; skip offline).

- [ ] **Step 6: Commit**

```bash
git add podscribe/cli.py tests/test_cli.py
git commit -m "feat(cli): _run_enhance wrapper prints header + metrics via on_stats"
```

---

## Task 5: Extract `run_record_session` headless core

**Files:**
- Modify: `podscribe/cli.py` (extract `run_record_session` from `cmd_record`; convert `cmd_record` to a thin wrapper)
- Modify: `tests/test_cli.py` (add `run_record_session` test)

- [ ] **Step 1: Write the failing test for `run_record_session`**

Add to `tests/test_cli.py`:

```python
import numpy as np
from podscribe.cli import run_record_session
from podscribe.models import Meeting, Pod
from podscribe.storage import start_meeting


class FakeCapture:
    def __init__(self, segments):
        self._segments = iter(segments)
        self.stopped = False
    def segments(self):
        return self._segments
    def stop(self):
        self.stopped = True


class FakeTranscriber:
    def __init__(self):
        self.model_name = "large-v3-turbo"
    def transcribe(self, audio, **kwargs):
        # Return one fake result per audio chunk.
        return [{"start": 0.0, "end": 1.0, "text": f"seg-{id(audio)}"}]


def test_run_record_session_drives_callbacks_and_writes_transcript(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = Pod(
        name="sam-chen", display_name="Sam", role="", cadence="weekly",
        notes="", created_at="2026-06-23", glossary=None, llm=None,
        base_path=tmp_path / "pods" / "sam-chen",
    )
    (pod.base_path / "transcripts").mkdir(parents=True)
    meeting = start_meeting(pod)

    segs = [np.zeros(16000, dtype=np.float32), np.zeros(8000, dtype=np.float32)]
    capture = FakeCapture(segs)
    transcriber = FakeTranscriber()

    segments_seen: list = []
    statuses: list = []
    done_counts: list = []

    run_record_session(
        pod, meeting, capture, transcriber,
        on_segment=segments_seen.append,
        on_status=statuses.append,
        on_done=done_counts.append,
    )

    assert len(segments_seen) == 2
    assert capture.stopped is True
    assert done_counts == [2]
    # Transcript was written
    md = meeting.transcript_path.read_text()
    assert "# Meeting:" in md
    assert len(statuses) >= 1
    assert statuses[0]["segment_count"] == 2
    # .raw was deleted (no wav_writer)
    assert not meeting.audio_path.exists()
    # JSON sidecar written
    assert meeting.metadata_path.exists()


def test_run_record_session_keeps_audio_when_wav_writer_provided(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import wave
    pod = Pod(
        name="sam-chen", display_name="Sam", role="", cadence="weekly",
        notes="", created_at="2026-06-23", glossary=None, llm=None,
        base_path=tmp_path / "pods" / "sam-chen",
    )
    (pod.base_path / "transcripts").mkdir(parents=True)
    meeting = start_meeting(pod)

    capture = FakeCapture([np.zeros(16000, dtype=np.float32)])
    transcriber = FakeTranscriber()
    wav = wave.open(str(meeting.audio_path), "wb")
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(16000)

    run_record_session(
        pod, meeting, capture, transcriber, wav_writer=wav,
        on_segment=lambda s: None, on_status=lambda d: None, on_done=lambda n: None,
    )
    assert meeting.audio_path.exists()
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/test_cli.py::test_run_record_session_drives_callbacks_and_writes_transcript tests/test_cli.py::test_run_record_session_keeps_audio_when_wav_writer_provided -v
```

Expected: both FAIL with `ImportError: cannot import name 'run_record_session'`.

- [ ] **Step 3: Implement `run_record_session` and convert `cmd_record`**

Replace the entire `cmd_record` function and add `run_record_session` in `podscribe/cli.py` (replace the current `def cmd_record(args) -> int:` block, which spans roughly lines 100-203). New content:

```python
def _hms(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def run_record_session(
    pod: "Pod",
    meeting: "Meeting",
    capture,
    transcriber,
    *,
    glossary_prompt: Optional[str] = None,
    wav_writer=None,
    on_segment=lambda s: None,
    on_status=lambda d: None,
    on_done=lambda n: None,
) -> None:
    """Drive capture.segments(), append to transcript, finalize. Fire callbacks.

    Headless: callers (plain wrapper or rich view) decide what to render.
    Owns SIGINT (stop capture), the .raw cleanup, and finalize_meeting.
    """
    from .audio import AudioCapture  # noqa: F401  (type-check only)
    from .transcriber import Transcriber  # noqa: F401

    # Write transcript header
    with meeting.transcript_path.open("w") as f:
        f.write(f"# Meeting: {meeting.id}\n\n")
        f.write(f"- pod: {pod.name} ({pod.display_name})\n")
        f.write(f"- started: {meeting.started_at}\n")
        f.write(f"- model: {transcriber.model_name}\n")
        f.write(f"- vad: webrtcvad (aggressiveness={capture.vad_aggressiveness})\n\n")
        f.write("## Transcript\n\n")

    meeting.model = transcriber.model_name
    meeting.vad_enabled = True
    start_monotonic = time.monotonic()
    segment_count = 0

    def handle_sigint(sig, frame):
        capture.stop()

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        for audio_segment in capture.segments():
            if wav_writer is not None:
                try:
                    pcm = np.clip(audio_segment * 32767, -32768, 32767).astype(np.int16)
                    wav_writer.writeframes(pcm.tobytes())
                except OSError:
                    pass
            kwargs = {}
            if glossary_prompt:
                kwargs["initial_prompt"] = glossary_prompt
            results = transcriber.transcribe(audio_segment, **kwargs)
            for r in results:
                elapsed = time.monotonic() - start_monotonic
                seg_duration = max(0.0, r["end"] - r["start"])
                seg_start = max(0.0, elapsed - seg_duration)
                seg = Segment(
                    start_sec=seg_start,
                    end_sec=elapsed,
                    text=r["text"],
                )
                append_segment(meeting, seg)
                on_segment(seg)
                segment_count += 1
            on_status({
                "elapsed": time.monotonic() - start_monotonic,
                "segment_count": segment_count,
                "vad_aggr": capture.vad_aggressiveness,
                "level": 0.0,
                "overflow": getattr(capture, "had_overflow", False),
            })
    finally:
        capture.stop()
        if wav_writer is not None:
            try:
                wav_writer.close()
            except Exception:
                pass
        meeting.duration_sec = int(time.monotonic() - start_monotonic)
        meeting.ended_at = datetime.now().isoformat(timespec="seconds")
        finalize_meeting(meeting, keep_audio=(wav_writer is not None))
        on_done(segment_count)


def cmd_record(args) -> int:
    """Live record + transcribe a meeting (thin wrapper around run_record_session)."""
    from .models import parse_meeting_type
    try:
        meeting_type = parse_meeting_type(args.type)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    from .audio import AudioCapture
    from .transcriber import Transcriber

    if not pod_exists(args.pod):
        print(f"No pod '{args.pod}'. Run `podscribe init {args.pod}` first.", file=sys.stderr)
        return 1

    pod = load_pod(args.pod)
    effective_glossary = get_effective_glossary(pod)
    glossary_prompt = format_glossary_prompt(effective_glossary) if effective_glossary else None
    meeting = start_meeting(pod, meeting_type=meeting_type)
    transcriber = Transcriber(model=args.model)
    capture = AudioCapture(
        vad_aggressiveness=args.vad_aggressiveness,
        device=args.device,
    )

    print(f"Recording meeting {meeting.id}")
    print(f"  pod: {pod.name} ({pod.display_name})")
    print(f"  transcript: {meeting.transcript_path}")
    print(f"  model: {transcriber.model_name}")
    print(f"  VAD aggressiveness: {capture.vad_aggressiveness} (0=loose, 3=strict)")
    print()
    print("  Press Ctrl+C to stop and finalize.")
    print()

    wav_writer = None
    if args.keep_audio:
        try:
            wav_writer = wave.open(str(meeting.audio_path), "wb")
            wav_writer.setnchannels(1)
            wav_writer.setsampwidth(2)
            wav_writer.setframerate(16000)
        except OSError as e:
            print(f"  ⚠ audio write failed: {e}", file=sys.stderr)
            wav_writer = None

    def _on_segment(seg: Segment) -> None:
        print(f"[{_hms(seg.start_sec)}] {seg.text}")

    def _on_done(n: int) -> None:
        print()
        print(f"Done. Saved {n} segments ({_hms(meeting.duration_sec or 0)})")
        print(f"  → {meeting.transcript_path}")
        if capture.had_overflow:
            print("  ⚠ audio buffer overflowed — some audio may have been dropped.", file=sys.stderr)

    run_record_session(
        pod, meeting, capture, transcriber,
        glossary_prompt=glossary_prompt, wav_writer=wav_writer,
        on_segment=_on_segment, on_status=lambda d: None, on_done=_on_done,
    )
    return 0
```

- [ ] **Step 4: Run the new tests, verify pass**

```bash
pytest tests/test_cli.py::test_run_record_session_drives_callbacks_and_writes_transcript tests/test_cli.py::test_run_record_session_keeps_audio_when_wav_writer_provided -v
```

Expected: both PASS.

- [ ] **Step 5: Run the full offline suite, confirm no regressions**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add podscribe/cli.py tests/test_cli.py
git commit -m "refactor(cli): extract run_record_session; cmd_record becomes thin wrapper"
```

---

## Task 6: Extract `run_consolidate` core (DRY for the rewrite prompt)

**Files:**
- Modify: `podscribe/cli.py:509-599` (extract `run_consolidate`; `cmd_consolidate` becomes thin wrapper)
- Modify: `tests/test_cli.py` (add `run_consolidate` test for the prompt callback)

- [ ] **Step 1: Write the failing test for `run_consolidate`**

Add to `tests/test_cli.py`:

```python
from podscribe.cli import run_consolidate


def test_run_consolidate_calls_prompt_rewrite_and_appends(tmp_path, monkeypatch):
    """run_consolidate with prompt_rewrite=True appends a log row."""
    from podscribe.config import save_project_config
    from podscribe.models import Pod
    from podscribe.storage import start_meeting, read_transcript, log_path
    monkeypatch.chdir(tmp_path)
    pod = Pod(
        name="sam-chen", display_name="Sam Chen", role="", cadence="weekly",
        notes="", created_at="2026-06-23", glossary=None,
        llm={"model": "qwen3.6:27b", "prompt_template": "x"},
        base_path=tmp_path / "pods" / "sam-chen",
    )
    (pod.base_path / "transcripts").mkdir(parents=True)
    meeting = start_meeting(pod)
    # Minimal transcript and enhanced summary
    meeting.transcript_path.parent.mkdir(parents=True, exist_ok=True)
    meeting.transcript_path.write_text("# Meeting: x\n[00:00:00] hi\n")
    summary_dir = pod.summaries_dir_for("23-JUN-2026")
    summary_dir.mkdir(parents=True, exist_ok=True)
    (summary_dir / f"{meeting.id}.md").write_text("Summary: stuff happened.")

    yaml_text = (
        "quick_summary: stuff\n"
        "key_topics: [a, b]\n"
        "action_items: [do thing]\n"
        "blockers: []\n"
        "next_steps: [follow up]\n"
    )
    monkeypatch.setattr("podscribe.cli._run_enhance", lambda p, m: (yaml_text, None))
    prompts = []
    def fake_prompt():
        prompts.append(1)
        return True
    rc = run_consolidate(pod, meeting, prompt_rewrite=fake_prompt)
    assert rc == 0
    assert prompts == [1]
    assert log_path(pod).exists()
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/test_cli.py::test_run_consolidate_calls_prompt_rewrite_and_appends -v
```

Expected: FAIL — `ImportError: cannot import name 'run_consolidate'`.

- [ ] **Step 3: Extract `run_consolidate` and convert `cmd_consolidate`**

Replace the body of `cmd_consolidate` (lines 509-599) and add `run_consolidate` above it:

```python
def run_consolidate(
    pod: "Pod",
    meeting: "Meeting",
    *,
    prompt_rewrite,
    no_log: bool = False,
) -> int:
    """Consolidate flow: extract structured fields from enhanced summary, update CSV.

    prompt_rewrite: callable returning bool — True to overwrite an existing log row.
    no_log: if True, skip CSV entirely.
    """
    from .llm import build_consolidate_prompt, enhance_transcript, extract_structured_fields

    enhanced_path = pod.summaries_dir_for(fmt_date(datetime.fromisoformat(meeting.started_at))) / f"{meeting.id}.md"
    if not enhanced_path.exists():
        print(
            f"No enhanced summary for {meeting.id}. "
            f"Run `podscribe enhance {pod.name} {meeting.id}` first.",
            file=sys.stderr,
        )
        return 1

    enhanced_text = enhanced_path.read_text()
    prompt_template = load_consolidate_prompt()
    prompt = build_consolidate_prompt(prompt_template, enhanced_text)

    llm_config = pod.llm if pod.llm else load_project_config().get("llm")
    if not llm_config or not llm_config.get("model"):
        print("LLM not configured for this pod. Set up LLM config first.", file=sys.stderr)
        return 1
    model_name = llm_config["model"]
    text, err = _run_enhance(prompt, model_name)
    if err is not None:
        print(err, file=sys.stderr)
        return 1

    fields = extract_structured_fields(text)
    if fields is None:
        print("Failed to parse structured fields from LLM response.", file=sys.stderr)
        return 1

    quick_summary = fields.get("quick_summary", "")
    def _join(v):
        if isinstance(v, list):
            return "|".join(v)
        return str(v or "")
    key_topics = _join(fields.get("key_topics"))
    action_items = _join(fields.get("action_items"))
    blockers = _join(fields.get("blockers"))
    next_steps = _join(fields.get("next_steps"))

    print(f"Extracted: {quick_summary}")
    print(f"  Topics: {key_topics}")
    print(f"  Actions: {action_items}")
    print(f"  Blockers: {blockers}")
    print(f"  Next: {next_steps}")

    if no_log:
        print("Skipping CSV log (--no-log)")
        return 0

    date_str = fmt_date(datetime.fromisoformat(meeting.started_at))
    log_fields = {
        "date": date_str,
        "person": pod.display_name,
        "meeting_id": meeting.id,
        "type": meeting.type or "",
        "quick_summary": quick_summary,
        "key_topics": key_topics,
        "action_items": action_items,
        "blockers": blockers,
        "next_steps": next_steps,
        "summary_file": str(enhanced_path.relative_to(pod.base_path)) if enhanced_path else "",
        "transcript_file": str(meeting.transcript_path.relative_to(pod.base_path)) if meeting.transcript_path else "",
        "duration_sec": meeting.duration_sec or "",
    }
    if log_entry_exists(pod, meeting.id):
        if prompt_rewrite():
            rewrite_log_row(pod, meeting.id, log_fields)
            print(f"Log entry rewritten for {meeting.id}")
        else:
            print("Skipping log update.")
    else:
        append_log_row(pod, log_fields)
        print(f"Log entry appended to {log_path(pod)}")
    return 0


def cmd_consolidate(args) -> int:
    """Extract structured fields from enhanced summary and update CSV log."""
    if not pod_exists(args.pod):
        print(f"No pod '{args.pod}'.", file=sys.stderr)
        return 1

    pod = load_pod(args.pod)
    meetings = list_meetings(pod)
    if not meetings:
        print(f"No meetings for pod '{args.pod}'.", file=sys.stderr)
        return 1

    meeting, err = _resolve_meeting(meetings, args.meeting, args.pod)
    if err is not None:
        print(err, file=sys.stderr)
        return 1

    def _prompt_plain() -> bool:
        print(f"Log entry exists for {meeting.id}. Rewrite? [y/N] ", end="")
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        return answer in ("y", "yes")

    return run_consolidate(
        pod, meeting,
        prompt_rewrite=_prompt_plain,
        no_log=args.no_log,
    )
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_cli.py::test_run_consolidate_calls_prompt_rewrite_and_appends -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add podscribe/cli.py tests/test_cli.py
git commit -m "refactor(cli): extract run_consolidate; cmd_consolidate is a thin wrapper"
```

---

## Task 7: Entry point — TTY guard, bare-`podscribe` → `tui.launch()`

**Files:**
- Modify: `podscribe/cli.py:764-775` (`main`)
- Create: `podscribe/tui.py` (minimal stub with `launch()` for this task; full views come in Task 8)
- Modify: `tests/test_cli.py` (add entry-point guard tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
import io
from podscribe.cli import main


def test_main_no_args_non_tty_prints_help_and_exits_2(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr("sys.stderr", io.StringIO())
    # Force isatty to False
    class NotATty:
        def isatty(self): return False
    monkeypatch.setattr("sys.stdin", NotATty())
    monkeypatch.setattr("sys.stderr", NotATty())
    rc = main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "TTY is required" in err


def test_main_help_still_works(capsys):
    rc = main(["--help"])
    # argparse exits with code 0 after printing help
    assert rc == 0
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/test_cli.py::test_main_no_args_non_tty_prints_help_and_exits_2 tests/test_cli.py::test_main_help_still_works -v
```

Expected: first FAILS (no guard yet — argparse errors out, code != 2 or message differs); second passes (argparse handles `--help`).

- [ ] **Step 3: Create a minimal `podscribe/tui.py` stub**

Create `podscribe/tui.py`:

```python
"""Interactive terminal UI: launcher + live views. Lazy-imported."""
from __future__ import annotations


def launch() -> int:
    """Entry point for bare `podscribe` (TTY only). Full implementation in Task 8."""
    print("podscribe: TUI not yet implemented.")
    return 0
```

- [ ] **Step 4: Update `main` with the TTY guard**

Replace `podscribe/cli.py:764-779` with:

```python
def main(argv: Optional[list] = None) -> int:
    if argv is None:
        argv = sys.argv[1:] if len(sys.argv) > 1 else []

    # Bare invocation (no args) → TUI launcher if a TTY is attached, else help.
    if not argv:
        if sys.stdin.isatty() and sys.stderr.isatty():
            from .tui import launch
            return launch()
        sys.stderr.write(
            "podscribe: a TTY is required for the interactive menu.\n"
            "Run 'podscribe --help' for subcommands.\n"
        )
        return 2

    argv = rewrite_argv(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the new tests, verify pass**

```bash
pytest tests/test_cli.py::test_main_no_args_non_tty_prints_help_and_exits_2 tests/test_cli.py::test_main_help_still_works -v
```

Expected: both PASS.

- [ ] **Step 6: Sanity check: full suite still green**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add podscribe/tui.py podscribe/cli.py tests/test_cli.py
git commit -m "feat(cli): TTY-guarded entry; bare 'podscribe' opens TUI launcher"
```

---

## Task 8: `tui.py` — palette, key reader, launcher, `record_view`, `enhance_view`, `consolidate_screen`

**Files:**
- Modify: `podscribe/tui.py` (replace the stub with the full implementation)
- Create: `tests/test_tui.py` (smoke tests)

- [ ] **Step 1: Write the smoke tests**

Create `tests/test_tui.py`:

```python
from podscribe.tui import launch


def test_launch_no_pods_prints_panel_and_exits_0(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = launch()
    assert rc == 0
    out = capsys.readouterr().out
    assert "No pods" in out or "init" in out


def test_launch_with_pod_calls_record_or_enhance_view(tmp_path, monkeypatch):
    """With a pod and a non-interactive key (e.g. 'q'), launch should exit cleanly."""
    monkeypatch.chdir(tmp_path)
    # Create a pod
    from podscribe.storage import init_pod
    init_pod("sam-chen", display_name="Sam Chen")
    # Patch readchar.readkey to return 'q' immediately
    import podscribe.tui as tui
    monkeypatch.setattr(tui, "read_key", lambda: "q")
    # Also patch Ollama status probe so it doesn't try a real request
    monkeypatch.setattr(tui, "probe_ollama", lambda: False)
    rc = launch()
    assert rc == 0
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/test_tui.py -v
```

Expected: FAIL — `launch()` is the stub returning "TUI not yet implemented"; `read_key` and `probe_ollama` don't exist yet.

- [ ] **Step 3: Write the full `podscribe/tui.py`**

Replace `podscribe/tui.py` with:

```python
"""Interactive terminal UI: launcher + live views. Lazy-imported."""
from __future__ import annotations

import sys
from typing import Callable, Optional

import readchar
import requests
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from .config import load_last_pod, load_project_config, save_last_pod
from .llm import build_enhance_prompt, enhance_transcript, ollama_model_info
from .models import Pod, fmt_date
from .storage import (
    _resolve_meeting,
    init_pod,
    list_meetings,
    load_pod,
    pod_exists,
    read_transcript,
)

# ---------------------------------------------------------------------------
# Palette (256-color; matches .scratch/mockup-synthwave-pastel.txt)
# ---------------------------------------------------------------------------
C_PEACH = "38;5;223"
C_PINK = "38;5;211"
C_LILAC = "38;5;183"
C_MINT = "38;5;152"
C_DIM = "38;5;244"

OLLAMA_URL = "http://localhost:11434"


def read_key() -> str:
    """Read a single key. Wrapper so tests can monkeypatch."""
    return readchar.readkey()


def probe_ollama() -> bool:
    """Return True if Ollama is reachable. 1s timeout. Wrapper for tests."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=1)
        return r.ok
    except requests.RequestException:
        return False


def _list_pod_names() -> list[str]:
    pods_dir = __import__("pathlib").Path("pods")
    if not pods_dir.exists():
        return []
    return sorted(p.name for p in pods_dir.iterdir() if p.is_dir() and (p / "config.yaml").exists())


def _resolve_pod(name_hint: Optional[str]) -> Optional[Pod]:
    """Return a Pod for the given name, or None if it doesn't exist."""
    if not name_hint:
        return None
    if not pod_exists(name_hint):
        return None
    return load_pod(name_hint)


def _pick_pod(console: Console) -> Optional[Pod]:
    """Show a numbered list and prompt the user to pick a pod."""
    names = _list_pod_names()
    if not names:
        return None
    console.print(Panel(
        "\n".join(f"  [{C_LILAC}][{i+1}][/{C_LILAC}] {n}" for i, n in enumerate(names)),
        title="[{C_PINK}]Choose a pod[/{C_PINK}]",
        border_style=C_LILAC,
    ))
    while True:
        k = read_key()
        if k.isdigit():
            idx = int(k) - 1
            if 0 <= idx < len(names):
                return _resolve_pod(names[idx])
        if k in ("q", "\x03"):
            return None


def _render_banner(console: Console, pod: Pod, ollama_ok: bool) -> None:
    ollama = f"[{C_MINT}]\u25c9 online[/{C_MINT}]" if ollama_ok else f"[{C_DIM}]\u25cb offline[/{C_DIM}]"
    console.print(Panel(
        f"[{C_PEACH}]podscribe[/{C_PEACH}]  "
        f"[{C_DIM}]\u00b7[/{C_DIM}]  pod: [{C_PINK}]{pod.name}[/{C_PINK}]  "
        f"[{C_DIM}]\u00b7[/{C_DIM}]  ollama: {ollama}",
        border_style=C_LILAC,
    ))


def _action_menu(console: Console) -> str:
    """Render the action menu and return the chosen key."""
    console.print(
        f"  [{C_LILAC}][1][/{C_LILAC}] Record     "
        f"[{C_LILAC}][2][/{C_LILAC}] Enhance     "
        f"[{C_LILAC}][3][/{C_LILAC}] Consolidate     "
        f"[{C_LILAC}][4][/{C_LILAC}] Others     "
        f"[{C_LILAC}][q][/{C_LILAC}] Quit"
    )
    while True:
        k = read_key()
        if k in ("1", "2", "3", "4", "q"):
            return k


def _others_menu(console: Console) -> Optional[str]:
    """Submenu for one-shot commands. Returns a CLI argv list to execute, or None."""
    items = [
        ("1", "list"),
        ("2", "show"),
        ("3", "search"),
        ("4", "context"),
        ("5", "export"),
        ("6", "config"),
        ("7", "switch pod"),
        ("q", "back"),
    ]
    console.print(
        "  " + "    ".join(f"[{C_LILAC}][{k}][/{C_LILAC}] {name}" for k, name in items)
    )
    while True:
        k = read_key()
        if k == "q":
            return None
        if k == "7":
            return ["__SWITCH_POD__"]
        mapping = {"1": "list", "2": "show", "3": "search", "4": "context", "5": "export", "6": "config"}
        if k in mapping:
            return [mapping[k]]


def _dispatch_cli(argv: list[str]) -> int:
    """Run a one-shot command by re-invoking main() with the given argv."""
    from .cli import main
    return main(argv)


# ---------------------------------------------------------------------------
# Live views
# ---------------------------------------------------------------------------

def record_view(pod: Pod, args) -> int:
    """rich.live view for recording. Uses run_record_session with rich callbacks."""
    from .cli import run_record_session
    from .audio import AudioCapture
    from .transcriber import Transcriber
    from .models import parse_meeting_type
    from .storage import start_meeting

    try:
        meeting_type = parse_meeting_type(getattr(args, "type", None))
    except ValueError as e:
        Console().print(f"[red]{e}[/red]")
        return 1

    try:
        meeting = start_meeting(pod, meeting_type=meeting_type)
    except Exception as e:
        Console().print(f"[red]Failed to start meeting: {e}[/red]")
        return 1

    transcriber = Transcriber(model=getattr(args, "model", "large-v3-turbo"))
    capture = AudioCapture(
        vad_aggressiveness=getattr(args, "vad_aggressiveness", 1),
        device=getattr(args, "device", None),
    )
    keep_audio = bool(getattr(args, "keep_audio", False))
    wav_writer = None
    if keep_audio:
        import wave
        try:
            wav_writer = wave.open(str(meeting.audio_path), "wb")
            wav_writer.setnchannels(1)
            wav_writer.setsampwidth(2)
            wav_writer.setframerate(16000)
        except OSError:
            wav_writer = None

    # Bounded line buffer for the live panel (full transcript still on disk).
    BUFFER_LINES = 200
    lines: list[str] = [f"[{C_PINK}]Recording meeting {meeting.id}[/{C_PINK}]", f"  Ctrl+C to stop."]
    console = Console()

    def _fmt_status(d: dict) -> str:
        m, s = divmod(int(d.get("elapsed", 0)), 60)
        h, m = divmod(m, 60)
        return (
            f"elapsed {h:02d}:{m:02d}:{s:02d}  segs={d.get('segment_count', 0)}  "
            f"VAD={d.get('vad_aggr', '?')}  overflow={'WARN' if d.get('overflow') else 'ok'}"
        )

    def _on_segment(seg) -> None:
        from .cli import _hms
        lines.append(f"[{_hms(seg.start_sec)}] {seg.text}")
        if len(lines) > BUFFER_LINES:
            del lines[: len(lines) - BUFFER_LINES]

    def _on_status(d: dict) -> None:
        # Live reads the tail of `lines` and the status; nothing else to do.
        pass

    status_line = {"text": ""}

    def _on_done(n: int) -> None:
        from .cli import _hms
        status_line["text"] = f"Done. Saved {n} segments ({_hms(meeting.duration_sec or 0)})"

    def _render() -> Panel:
        body = "\n".join(lines[-BUFFER_LINES:])
        return Panel(
            body + "\n\n" + _fmt_status({"elapsed": 0, "segment_count": len(lines) - 2, "vad_aggr": 1, "overflow": False}) + "\n" + status_line["text"],
            title=f"[{C_PEACH}]record[/{C_PEACH}]",
            border_style=C_LILAC,
        )

    rc = 0
    with Live(_render(), console=console, refresh_per_second=8) as live:
        # We can't easily update live.update from inside run_record_session
        # (sync loop), so we update on each status tick via a wrapper.
        def _on_status_live(d: dict) -> None:
            _on_status(d)
            live.update(_render())

        try:
            run_record_session(
                pod, meeting, capture, transcriber,
                wav_writer=wav_writer,
                on_segment=_on_segment,
                on_status=_on_status_live,
                on_done=_on_done,
            )
        except KeyboardInterrupt:
            rc = 130
        live.update(_render())
    console.print(f"  [dim]\u2192 {meeting.transcript_path}[/dim]")
    return rc


def enhance_view(pod: Pod, meeting) -> int:
    """rich.live view for enhance. Streams tokens via on_token."""
    from .cli import _run_enhance
    from .config import get_effective_glossary, load_preserve_speakers
    from .storage import pod as _pod_module  # noqa: F401  (for clarity)
    from datetime import datetime

    console = Console()
    llm_config = pod.llm if pod.llm else load_project_config().get("llm")
    if not llm_config or not llm_config.get("model") or not llm_config.get("prompt_template"):
        console.print(Panel(
            "LLM not configured for this pod. Add an 'llm' section to config.yaml "
            "with 'model' and 'prompt_template'.",
            title="[red]enhance[/red]",
            border_style="red",
        ))
        return 1

    transcript = read_transcript(meeting)
    if len(transcript.strip()) < 50:
        console.print(Panel(
            f"Transcript too short to enhance ({len(transcript.strip())} chars).",
            title="[red]enhance[/red]", border_style="red",
        ))
        return 1

    glossary = get_effective_glossary(pod)
    preserve = load_preserve_speakers(pod)
    prompt = build_enhance_prompt(
        llm_config["prompt_template"], glossary, transcript, preserve_speakers=preserve,
    )

    date_str = fmt_date(datetime.fromisoformat(meeting.started_at))
    summary_dir = pod.summaries_dir_for(date_str)
    enhanced_path = summary_dir / f"{meeting.id}.md"

    BUFFER_TOKENS = 200
    tokens: list[str] = ["(waiting for first token)"]
    footer = {"elapsed": 0.0, "tokens": 0, "tps": 0.0, "status": "streaming"}

    info = ollama_model_info(llm_config["model"])
    num_ctx = (info.get("model_info") or {}).get("llama.context_length", "?")

    def _on_token(t: str) -> None:
        if tokens == ["(waiting for first token)"]:
            tokens.clear()
        tokens.append(t)
        if len(tokens) > BUFFER_TOKENS:
            del tokens[: len(tokens) - BUFFER_TOKENS]
        footer["tokens"] += 1

    def _on_stats(stats: dict) -> None:
        ed = (stats.get("eval_duration_ns", 0) or 1) / 1e9
        ec = stats.get("eval_count", 0)
        footer["tps"] = ec / ed if ed > 0 else 0
        footer["status"] = f"done prompt {stats.get('prompt_eval_count', 0)} + response {ec} @ {footer['tps']:.1f} tok/s"

    def _on_retry(attempt: int, err: str) -> None:
        footer["status"] = f"retrying (attempt {attempt})..."

    def _render() -> Panel:
        body = "".join(tokens[-BUFFER_TOKENS:])
        return Panel(
            body + f"\n\n[{C_DIM}]{footer['status']}[/{C_DIM}]",
            title=f"[{C_PEACH}]enhance {pod.name}/{date_str}/{meeting.id}[/{C_PEACH}]  "
                  f"model={llm_config['model']}  ctx={num_ctx}",
            border_style=C_LILAC,
        )

    rc = 0
    with Live(_render(), console=console, refresh_per_second=10) as live:
        def _tick() -> None:
            live.update(_render())
        # Run the core; update live between chunks via a token wrapper.
        def _on_token_live(t: str) -> None:
            _on_token(t)
            _tick()
        try:
            result = enhance_transcript(
                llm_config["model"], prompt,
                on_token=_on_token_live, on_stats=_on_stats, on_retry=_on_retry,
            )
        except KeyboardInterrupt:
            rc = 130
            result = None
        if result is None:
            console.print(Panel(
                "Failed to reach Ollama. Is it running? Start with: ollama serve",
                title="[red]enhance[/red]", border_style="red",
            ))
            return 1
        _tick()
        summary_dir.mkdir(parents=True, exist_ok=True)
        enhanced_path.write_text(result)
    console.print(f"[green]Enhanced transcript saved to {enhanced_path}[/green]")
    return rc


def consolidate_screen(pod: Pod, meeting) -> int:
    """rich.console.status spinner + rich.prompt.Confirm for the de-dup prompt."""
    from .cli import run_consolidate

    console = Console()
    from rich.prompt import Confirm as _Confirm

    def _prompt() -> bool:
        return _Confirm.ask(
            f"Log entry exists for {meeting.id}. Rewrite?", default=False
        )

    with console.status("[bold cyan]Consolidating..."):
        rc = run_consolidate(pod, meeting, prompt_rewrite=_prompt)
    return rc


# ---------------------------------------------------------------------------
# Launcher
# ---------------------------------------------------------------------------

def launch() -> int:
    """Top-level TUI entry: pod context + action menu + dispatch."""
    console = Console()

    if not _list_pod_names():
        console.print(Panel(
            "No pods yet. Run `podscribe init <name>` to create one.",
            title=f"[{C_PINK}]podscribe[/{C_PINK}]",
            border_style=C_LILAC,
        ))
        return 0

    last = load_last_pod()
    pod = _resolve_pod(last)
    if pod is None:
        pod = _pick_pod(console)
        if pod is None:
            return 0
        save_last_pod(pod.name)

    ollama_ok = probe_ollama()

    while True:
        console.clear()
        _render_banner(console, pod, ollama_ok)
        key = _action_menu(console)
        if key == "q":
            return 0
        if key == "1":
            from argparse import Namespace
            args = Namespace(type=None, model="large-v3-turbo",
                             vad_aggressiveness=1, device=None, keep_audio=False)
            record_view(pod, args)
        elif key == "2":
            meetings = list_meetings(pod)
            if not meetings:
                console.print(f"[red]No meetings for pod '{pod.name}'.[/red]")
            else:
                meeting, err = _resolve_meeting(meetings, "latest", pod.name)
                if err:
                    console.print(f"[red]{err}[/red]")
                else:
                    enhance_view(pod, meeting)
        elif key == "3":
            meetings = list_meetings(pod)
            if not meetings:
                console.print(f"[red]No meetings for pod '{pod.name}'.[/red]")
            else:
                meeting, err = _resolve_meeting(meetings, "latest", pod.name)
                if err:
                    console.print(f"[red]{err}[/red]")
                else:
                    consolidate_screen(pod, meeting)
        elif key == "4":
            sub = _others_menu(console)
            if sub is None:
                continue
            if sub == ["__SWITCH_POD__"]:
                new_pod = _pick_pod(console)
                if new_pod is not None:
                    pod = new_pod
                    save_last_pod(pod.name)
                continue
            # Dispatch as a plain CLI command (e.g. ["list"]) for one-shots.
            _dispatch_cli(sub)
```

- [ ] **Step 4: Run smoke tests, verify pass**

```bash
pytest tests/test_tui.py -v
```

Expected: both PASS.

- [ ] **Step 5: Run the full suite**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: all pass. If any test fails because `tui.py` imports pulled in `rich`/`readchar` into a path that shouldn't have them, fix the import; `tui.py` should never be imported by one-shot command paths (it's only imported inside `main()` when the bare-`podscribe` TTY branch fires, and inside `record_view`/`enhance_view`/`consolidate_screen` which are themselves only reached via the TUI).

- [ ] **Step 6: Commit**

```bash
git add podscribe/tui.py tests/test_tui.py
git commit -m "feat(tui): launcher + record/enhance live views + consolidate screen"
```

---

## Task 9: Docs — rewrite USER-MANUAL streaming section, update AGENTS.md

**Files:**
- Modify: `docs/USER-MANUAL.md:160-176` (rewrite the "Streaming output" example)
- Modify: `AGENTS.md` (tree + launcher note + drop tqdm)

- [ ] **Step 1: Rewrite the USER-MANUAL streaming section**

In `docs/USER-MANUAL.md`, replace the block from line 160 (`#### Streaming output`) through line 176 (the closing ```) with:

```markdown
#### Streaming output

The enhance call streams tokens from Ollama and renders them live in a `rich.live` panel. When invoked directly (`podscribe <pod> enhance`) you see the same live view; piped/non-TTY invocations degrade to plain lines.

```
Enhancing transcript for sam-chen/22-JUN-2026/2026-06-22-101500-sam-chen...
Enhanced summary will be saved to sam-chen/22-JUN-2026/2026-06-22-101500-sam-chen...
  Using Large Language Model: qwen3.6:27b
  Ollama URL: http://localhost:11434

Calling Model:qwen3.6:27b...
Context window size : 32768 tokens
[live token panel fills as Ollama generates]
  ✓ done in 47.2s | prompt 1250 + response 423 tokens @ 17.3 tok/s

Enhanced transcript saved to pods/sam-chen/summaries/22-JUN-2026/2026-06-22-101500-sam-chen.md
```

There is no fake percentage bar — Ollama's streaming API does not report a total token count until completion, so the view shows an honest token stream + final metrics instead.
```

- [ ] **Step 2: Update AGENTS.md**

In `AGENTS.md`:

1. In the `podscribe/` tree block, add a line for `tui.py` after `cli.py`:

```
├── tui.py          — interactive TUI: launcher + rich live views (lazy-imported)
```

2. In the "Commands" table, add a new row after the `enhance` row:

```
| `podscribe` (no args) | TTY-only; opens the remembered-pod launcher menu with Record/Enhance/Consolidate/Others. Falls back to a help message in non-TTY contexts. |
```

3. In the "Declared in `pyproject.toml`" block, replace `tqdm` with `rich`, and add `readchar`. The line should read:

```
Declared in `pyproject.toml`: `mlx-whisper`, `webrtcvad`, `sounddevice`, `rich`, `readchar`, `numpy`, `pyyaml`, `requests`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/USER-MANUAL.md AGENTS.md
git commit -m "docs: rewrite enhance streaming section; update AGENTS.md (TUI, deps)"
```

---

## Task 10: Final verification

- [ ] **Step 1: Run the full offline test suite**

```bash
pytest tests/ -v -k "not transcriber"
```

Expected: all pass. Confirm the test count is `≥ 205` (the 204 baseline + the new tests added in Tasks 2, 3, 5, 6, 7, 8).

- [ ] **Step 2: Manual smoke checks**

```bash
# 1. --help still works
podscribe --help

# 2. argparse error for unknown subcommand still works
podscribe bogus-cmd
echo "exit=$?"

# 3. Bare podscribe in non-TTY exits 2 with a helpful message
podscribe < /dev/null 2>&1 | head -5
echo "exit=${PIPESTATUS[0]}"
```

Expected: 1 prints help, 2 prints argparse error, 3 prints the TTY-required message and `exit=2`.

- [ ] **Step 3: Confirm `tqdm` is gone from `podscribe/`**

```bash
grep -rn "tqdm" podscribe/ || echo "OK: no tqdm in podscribe/"
```

Expected: prints `OK: no tqdm in podscribe/`.

- [ ] **Step 4: Final summary commit (no code changes)**

```bash
git log --oneline -10
```

Verify the chain of commits reads coherently:

```
chore(deps): add rich + readchar, drop tqdm
feat(config): round-trip last_pod in podscribe.yaml
feat(llm): headless enhance_transcript with on_token/on_stats/on_retry; remove tqdm
feat(cli): _run_enhance wrapper prints header + metrics via on_stats
refactor(cli): extract run_record_session; cmd_record becomes thin wrapper
refactor(cli): extract run_consolidate; cmd_consolidate is a thin wrapper
feat(cli): TTY-guarded entry; bare 'podscribe' opens TUI launcher
feat(tui): launcher + record/enhance live views + consolidate screen
docs: rewrite enhance streaming section; update AGENTS.md (TUI, deps)
```

---

## Out of scope (deferred)

- Rich-rendered panels/tables for one-shot commands (`list`/`show`/`search`/`export`/`import`/`config`/`context`). Spec lists these as polish; current markdown table output is fine. A follow-up can add `rich`-rendered tables when stdout is a TTY.
- `play <meeting-id>` for spot-checking kept audio (separate effort; depends on `--keep-audio`).
- Keyboard controls during record (pause/stop/marker) — brainstormed out.
- Full textual/curses persistent app — brainstormed out.
- Auto-enhance / auto-consolidate after record (`roadmap.md`).

## Self-review notes (post-write)

- **Spec coverage:** every section of the spec maps to a task: deps (1), config last_pod (2), enhance core refactor (3), wrapper (4), record core (5), consolidate core (6), entry point (7), tui.py (8), docs (9), verification (10). Bug regression test is Task 3. Cleanup-test rewrite is Task 3. Non-TTY guard is Task 7. `consolidate_screen` uses `Confirm.ask` (Task 8). `readchar` is the key reader (Task 8). All covered.
- **Placeholder scan:** no `TBD`/`TODO`/`fill in`/`similar to`. Every code block is complete.
- **Type consistency:** `run_record_session(on_segment, on_status, on_done)` is defined in Task 5 and used by `record_view` (Task 8) and `cmd_record` (Task 5). `enhance_transcript(on_token, on_stats, on_retry)` defined in Task 3 and used by `_run_enhance` (Task 4), `enhance_view` (Task 8), and tests. `run_consolidate(prompt_rewrite, no_log)` defined in Task 6 and used by `cmd_consolidate` (Task 6) and `consolidate_screen` (Task 8). `load_last_pod`/`save_last_pod` defined Task 2, used Task 8. Consistent.
