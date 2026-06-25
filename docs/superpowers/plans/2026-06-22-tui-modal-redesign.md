# TUI Modal Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat `_select_menu` launcher loop with a Lazygit-style modal two-pane TUI — persistent sidebar (pod list) + context-sensitive main pane (Dashboard by default), Vim-style `j/k` navigation, mode-coloured status bar (purple = NORMAL, red = active REC/STREAM, peach = COMMAND), a fuzzy command palette (`:` key), and a real RMS waveform bar during recording.

**Architecture:** The existing `run_record_session` / `enhance_transcript` callback interfaces are preserved untouched. Only the view layer (`tui.py`) is rewritten — the headless cores in `cli.py` and `llm.py` are not changed. `audio.py` gains one new optional `on_level` callback (no-op by default) to emit RMS amplitude per chunk for the waveform bar. All 205 existing tests must stay green.

**Tech Stack:** Python 3.10+, `rich` (already installed: `Console`, `Live`, `Layout`, `Panel`, `Table`, `Prompt`), `readchar` (already installed), `numpy` (already installed for RMS calc).

## Global Constraints

- Python ≥ 3.10; Apple Silicon / macOS only for audio.
- No new runtime dependencies — `rich`, `readchar`, `numpy` are already in `pyproject.toml`.
- `tui.py` is lazy-imported — never loaded by non-interactive commands.
- All existing 205 tests must pass after every task: `pytest tests/ -v -k "not transcriber"`.
- No changes to on-disk formats (transcripts, summaries, CSV, config YAML).
- Kebab-case pod names only (`^[a-z0-9]+(-[a-z0-9]+)*$`).
- Palette constants: `C_PEACH = "color(223)"`, `C_PINK = "color(211)"`, `C_LILAC = "color(183)"`, `C_MINT = "color(152)"`, `C_DIM = "color(244)"`. Two-tier mode colours: active = `"color(211)"` (red/hot-pink), idle-normal = `C_LILAC`, idle-command = `C_PEACH`.
- Status bar mode badges: `NORMAL`, `INSERT`, `STREAM`, `COMMAND`.
- Default launch focus: main pane, most recent meeting of last-used pod.
- Fuzzy palette candidates: pods (`[pod]`) + commands (`[cmd]`) only. Argument-bearing commands open `Prompt.ask` after palette closes.

---

## File Map

| File | Role |
|---|---|
| `podscribe/tui.py` | **Full rewrite.** Two-pane layout, modal state machine, waveform bar, fuzzy palette. |
| `podscribe/audio.py` | **Minimal addition.** Add `on_level: Callable[[float], None]` param to `AudioCapture.__init__`; emit RMS per chunk in `_callback`. |
| `tests/test_tui.py` | **Extend.** New tests for two-pane layout helpers, mode state, fuzzy palette, waveform callback; existing smoke tests updated to match new TUI API. |
| `tests/test_audio.py` | **Extend.** One new test: `on_level` callback receives float in [0, 1] per chunk. |

**Unchanged:** `cli.py`, `llm.py`, `config.py`, `storage.py`, `models.py`, all other test files.

---

## Task 1: Add `on_level` RMS callback to `AudioCapture`

**Files:**
- Modify: `podscribe/audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Produces: `AudioCapture.__init__(self, vad_aggressiveness=2, device=None, on_level=lambda f: None)` — the new param is keyword-only with a no-op default. The callback receives a single `float` in the range `[0.0, 1.0]` representing the RMS of the current chunk, emitted inside `_callback` before the chunk is queued.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audio.py`:

```python
def test_on_level_callback_receives_rms_float():
    """on_level must be called with a float in [0.0, 1.0] for each audio chunk."""
    import numpy as np
    from podscribe.audio import AudioCapture

    levels = []
    capture = AudioCapture(on_level=levels.append)

    # Simulate the callback directly — mimic what sounddevice would call
    # indata shape is (frames, channels) = (480, 1)
    chunk = np.full((480, 1), 0.5, dtype="float32")

    import types
    fake_status = None
    capture._callback(chunk, 480, None, fake_status)

    assert len(levels) == 1
    level = levels[0]
    assert isinstance(level, float)
    assert 0.0 <= level <= 1.0
    # RMS of 0.5 signal = 0.5
    assert abs(level - 0.5) < 0.01
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_audio.py::test_on_level_callback_receives_rms_float -v
```
Expected: `FAILED` — `AudioCapture.__init__() got an unexpected keyword argument 'on_level'`

- [ ] **Step 3: Implement the change in `audio.py`**

In `AudioCapture.__init__`, add `on_level` param and store it:

```python
def __init__(
    self,
    vad_aggressiveness: int = 2,
    device: Optional[int] = None,
    on_level=lambda f: None,
):
    """vad_aggressiveness: 0-3, higher = more aggressive (filters more).
    on_level: called with float RMS in [0.0, 1.0] for each audio chunk.
    """
    self.vad_aggressiveness = vad_aggressiveness
    self.device = device
    self._on_level = on_level
    self._audio_q: "queue.Queue[np.ndarray]" = queue.Queue()
    self._stream: Optional[sd.InputStream] = None
    self._vad = None
    self._running = False
    self._overflow = False
```

In `_callback`, emit RMS before queuing:

```python
def _callback(self, indata, frames, time_info, status):
    if status:
        self._overflow = True
    chunk = indata.copy().reshape(-1)
    rms = float(np.sqrt(np.mean(chunk ** 2)))
    self._on_level(min(1.0, rms))
    self._audio_q.put(chunk)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_audio.py::test_on_level_callback_receives_rms_float -v
```
Expected: `PASSED`

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
pytest tests/ -v -k "not transcriber"
```
Expected: all green (205 tests).

- [ ] **Step 6: Commit**

```bash
git add podscribe/audio.py tests/test_audio.py
git commit -m "feat(audio): add on_level RMS callback per chunk for waveform bar"
```

---

## Task 2: Core TUI state machine and layout skeleton

**Files:**
- Modify: `podscribe/tui.py` (rewrite the module top, palette, and `AppState` class)
- Test: `tests/test_tui.py`

**Interfaces:**
- Produces:
  - `AppState` dataclass with fields: `mode: str` (`"NORMAL"` | `"INSERT"` | `"STREAM"` | `"COMMAND"`), `focused_pane: str` (`"sidebar"` | `"main"`), `sidebar_idx: int`, `main_idx: int`, `pod_names: list[str]`, `waveform: list[float]` (rolling 40-element list of RMS values, all `0.0` initially).
  - `mode_colour(mode: str) -> str` — returns Rich colour string: `"INSERT"` and `"STREAM"` → `C_PINK`; `"COMMAND"` → `C_PEACH`; `"NORMAL"` → `C_LILAC`.
  - `WAVEFORM_WIDTH: int = 40` — module constant.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tui.py`:

```python
def test_mode_colour_active_modes_return_pink():
    from podscribe import tui
    assert tui.mode_colour("INSERT") == tui.C_PINK
    assert tui.mode_colour("STREAM") == tui.C_PINK

def test_mode_colour_command_returns_peach():
    from podscribe import tui
    assert tui.mode_colour("COMMAND") == tui.C_PEACH

def test_mode_colour_normal_returns_lilac():
    from podscribe import tui
    assert tui.mode_colour("NORMAL") == tui.C_LILAC

def test_app_state_defaults():
    from podscribe.tui import AppState
    s = AppState(pod_names=["sam-chen", "alex-wu"])
    assert s.mode == "NORMAL"
    assert s.focused_pane == "main"
    assert s.sidebar_idx == 0
    assert s.main_idx == 0
    assert len(s.waveform) == 40
    assert all(v == 0.0 for v in s.waveform)

def test_app_state_waveform_push():
    from podscribe.tui import AppState
    s = AppState(pod_names=["sam-chen"])
    s.waveform.append(0.7)
    s.waveform = s.waveform[-40:]
    assert s.waveform[-1] == 0.7
    assert len(s.waveform) <= 40
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tui.py::test_mode_colour_active_modes_return_pink tests/test_tui.py::test_app_state_defaults -v
```
Expected: `FAILED` — names not defined yet.

- [ ] **Step 3: Replace the top of `tui.py`** (palette + imports + new symbols, keep all existing functions below for now):

```python
"""Interactive terminal UI: launcher + live views. Lazy-imported."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import readchar
import requests
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from .cli import _resolve_meeting
from .config import load_last_pod, load_project_config, save_last_pod
from .llm import build_enhance_prompt, enhance_transcript, ollama_model_info
from .models import Pod, fmt_date
from .storage import (
    list_meetings,
    load_pod,
    pod_exists,
    read_transcript,
)

# ---------------------------------------------------------------------------
# Palette (256-color; synthwave pastel)
# ---------------------------------------------------------------------------
C_PEACH = "color(223)"
C_PINK  = "color(211)"
C_LILAC = "color(183)"
C_MINT  = "color(152)"
C_DIM   = "color(244)"

OLLAMA_URL = "http://localhost:11434"

# readchar key codes
KEY_UP    = "\x1b[A"
KEY_DOWN  = "\x1b[B"
KEY_ENTER = "\r"

WAVEFORM_WIDTH = 40  # number of RMS buckets shown in the waveform bar


def mode_colour(mode: str) -> str:
    """Return the Rich colour string for the given mode badge."""
    if mode in ("INSERT", "STREAM"):
        return C_PINK
    if mode == "COMMAND":
        return C_PEACH
    return C_LILAC  # NORMAL


@dataclass
class AppState:
    """Mutable state for the two-pane TUI."""
    pod_names: list
    mode: str = "NORMAL"
    focused_pane: str = "main"   # "sidebar" | "main"
    sidebar_idx: int = 0
    main_idx: int = 0
    waveform: list = field(default_factory=lambda: [0.0] * WAVEFORM_WIDTH)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_tui.py::test_mode_colour_active_modes_return_pink tests/test_tui.py::test_mode_colour_command_returns_peach tests/test_tui.py::test_mode_colour_normal_returns_lilac tests/test_tui.py::test_app_state_defaults tests/test_tui.py::test_app_state_waveform_push -v
```
Expected: all `PASSED`.

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -v -k "not transcriber"
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add podscribe/tui.py tests/test_tui.py
git commit -m "feat(tui): add AppState dataclass and mode_colour helper"
```

---

## Task 3: Sidebar and header rendering

**Files:**
- Modify: `podscribe/tui.py`
- Test: `tests/test_tui.py`

**Interfaces:**
- Produces:
  - `render_sidebar(state: AppState, pods: list[Pod]) -> Panel` — returns a Rich `Panel` containing the pod list. Focused pod highlighted in `C_PINK` with `▶` cursor; others in `C_DIM`. Panel border: `C_LILAC` when `state.focused_pane == "sidebar"`, `C_DIM` otherwise. Title: `"Pods"`.
  - `render_header(pod: Pod, ollama_ok: bool) -> str` — returns a single Rich markup string (not a Panel): `podscribe · <pod.name> · <pod.role>   ◉ ollama online` or `○ offline`.

- [ ] **Step 1: Write the failing tests**

```python
def test_render_sidebar_marks_active_pod(tmp_path, monkeypatch):
    from podscribe.tui import AppState, render_sidebar
    from podscribe.models import Pod

    pods = [
        Pod(name="sam-chen", display_name="Sam Chen", role="SE", base_path=tmp_path / "pods" / "sam-chen"),
        Pod(name="alex-wu",  display_name="Alex Wu",  role="Staff", base_path=tmp_path / "pods" / "alex-wu"),
    ]
    state = AppState(pod_names=["sam-chen", "alex-wu"], sidebar_idx=0)
    panel = render_sidebar(state, pods)
    # Render to a string to inspect
    from rich.console import Console
    from io import StringIO
    buf = StringIO()
    c = Console(file=buf, no_color=True, width=40)
    c.print(panel)
    text = buf.getvalue()
    assert "sam-chen" in text
    assert "alex-wu" in text
    # Active item has the cursor character
    assert "▶" in text


def test_render_header_shows_ollama_status():
    from podscribe.tui import render_header
    from podscribe.models import Pod
    from pathlib import Path
    pod = Pod(name="sam-chen", display_name="Sam Chen", role="Senior Eng",
              base_path=Path("/tmp/x"))
    hdr = render_header(pod, ollama_ok=True)
    assert "sam-chen" in hdr
    assert "online" in hdr

    hdr_off = render_header(pod, ollama_ok=False)
    assert "offline" in hdr_off
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_tui.py::test_render_sidebar_marks_active_pod tests/test_tui.py::test_render_header_shows_ollama_status -v
```
Expected: `FAILED`

- [ ] **Step 3: Implement `render_sidebar` and `render_header` in `tui.py`**

Add after the `AppState` dataclass (before existing helper functions):

```python
def render_header(pod: Pod, ollama_ok: bool) -> str:
    """Single-line Rich markup header string."""
    ollama = (
        f"[{C_MINT}]◉ ollama online[/{C_MINT}]"
        if ollama_ok
        else f"[{C_DIM}]○ ollama offline[/{C_DIM}]"
    )
    role = f"[{C_DIM}]{pod.role}[/{C_DIM}]" if pod.role else ""
    sep = f"[{C_DIM}] · [/{C_DIM}]"
    parts = [f"[{C_PEACH}]podscribe[/{C_PEACH}]", sep,
             f"[{C_PINK}]{pod.name}[/{C_PINK}]"]
    if role:
        parts += [sep, role]
    parts += ["  ", ollama]
    return "".join(parts)


def render_sidebar(state: AppState, pods: list) -> Panel:
    """Rich Panel containing the pod list for the sidebar."""
    lines = []
    for i, pod in enumerate(pods):
        if i == state.sidebar_idx:
            cursor = f"[{C_PINK}]▶[/{C_PINK}]"
            name   = f"[{C_PINK}]{pod.name}[/{C_PINK}]"
            role   = f"[{C_DIM}]  {pod.role}[/{C_DIM}]" if pod.role else ""
        else:
            cursor = f"[{C_DIM}] [/{C_DIM}]"
            name   = f"[{C_DIM}]{pod.name}[/{C_DIM}]"
            role   = ""
        lines.append(f" {cursor} {name}{role}")
    border = C_LILAC if state.focused_pane == "sidebar" else C_DIM
    return Panel("\n".join(lines) or " ", title="Pods", border_style=border)
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest tests/test_tui.py::test_render_sidebar_marks_active_pod tests/test_tui.py::test_render_header_shows_ollama_status -v
```
Expected: `PASSED`

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -v -k "not transcriber"
```

- [ ] **Step 6: Commit**

```bash
git add podscribe/tui.py tests/test_tui.py
git commit -m "feat(tui): add render_sidebar and render_header"
```

---

## Task 4: Dashboard and status bar rendering

**Files:**
- Modify: `podscribe/tui.py`
- Test: `tests/test_tui.py`

**Interfaces:**
- Produces:
  - `render_dashboard(pod: Pod, meetings: list, state: AppState) -> Panel` — Rich Panel for the main pane. Shows pod name + role header, a 3-column stats grid (total meetings, enhanced count, last-met), and a recent-meeting list with `▶` cursor on `state.main_idx`. Panel title `"Dashboard"`, border `C_LILAC` when `state.focused_pane == "main"`, `C_DIM` otherwise.
  - `render_status_bar(state: AppState, pod: Pod) -> str` — single Rich markup line: `[MODE] · <pod.name> · <extra>` where `[MODE]` background uses `mode_colour(state.mode)`.
  - `_meeting_enhanced(meeting) -> bool` — returns `True` if `pod.summaries_dir_for(date_str) / f"{meeting.id}.md"` exists. Used by dashboard to compute coverage.

- [ ] **Step 1: Write the failing tests**

```python
def test_render_dashboard_shows_pod_name(tmp_path):
    from podscribe.tui import AppState, render_dashboard
    from podscribe.models import Pod
    from io import StringIO
    from rich.console import Console

    pod = Pod(name="sam-chen", display_name="Sam Chen", role="Senior Eng",
              base_path=tmp_path / "pods" / "sam-chen")
    state = AppState(pod_names=["sam-chen"])
    panel = render_dashboard(pod, meetings=[], state=state)

    buf = StringIO()
    Console(file=buf, no_color=True, width=80).print(panel)
    text = buf.getvalue()
    assert "Sam Chen" in text or "sam-chen" in text


def test_render_status_bar_normal_mode():
    from podscribe.tui import AppState, render_status_bar, C_LILAC
    from podscribe.models import Pod
    from pathlib import Path
    pod = Pod(name="sam-chen", base_path=Path("/tmp/x"))
    state = AppState(pod_names=["sam-chen"], mode="NORMAL")
    bar = render_status_bar(state, pod)
    assert "NORMAL" in bar
    assert "sam-chen" in bar

def test_render_status_bar_insert_mode():
    from podscribe.tui import AppState, render_status_bar, C_PINK
    from podscribe.models import Pod
    from pathlib import Path
    pod = Pod(name="sam-chen", base_path=Path("/tmp/x"))
    state = AppState(pod_names=["sam-chen"], mode="INSERT")
    bar = render_status_bar(state, pod)
    assert "INSERT" in bar
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_tui.py::test_render_dashboard_shows_pod_name tests/test_tui.py::test_render_status_bar_normal_mode -v
```

- [ ] **Step 3: Implement in `tui.py`**

```python
def _meeting_enhanced(pod: Pod, meeting) -> bool:
    """Return True if an enhanced summary exists for this meeting."""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(meeting.started_at)
        date_str = fmt_date(dt)
    except (ValueError, TypeError):
        return False
    summary_path = pod.summaries_dir_for(date_str) / f"{meeting.id}.md"
    return summary_path.exists()


def render_dashboard(pod: Pod, meetings: list, state: "AppState") -> Panel:
    """Main pane default view: pod stats + recent meetings list."""
    from rich.table import Table

    # Stats
    total = len(meetings)
    enhanced = sum(1 for m in meetings if _meeting_enhanced(pod, m))
    pct = f"{int(enhanced / total * 100)}%" if total else "–"
    from datetime import datetime
    last_met = "–"
    if meetings:
        try:
            dt = datetime.fromisoformat(meetings[0].started_at)
            last_met = fmt_date(dt)
        except (ValueError, TypeError):
            pass

    stats = (
        f"[{C_PINK}]{pod.display_name or pod.name}[/{C_PINK}]"
        f"[{C_DIM}]  ·  {pod.role}[/{C_DIM}]\n\n"
        f"[{C_DIM}]meetings [/{C_DIM}][{C_PEACH}]{total}[/{C_PEACH}]"
        f"   [{C_DIM}]enhanced [/{C_DIM}][{C_MINT}]{enhanced} ({pct})[/{C_MINT}]"
        f"   [{C_DIM}]last met [/{C_DIM}][{C_PEACH}]{last_met}[/{C_PEACH}]\n"
    )

    # Recent meetings list
    lines = [stats, f"[{C_DIM}]─── Recent meetings ───────────────────────────────[/{C_DIM}]"]
    for i, m in enumerate(meetings[:12]):
        cursor = f"[{C_PINK}]▶[/{C_PINK}]" if i == state.main_idx else " "
        try:
            dt = datetime.fromisoformat(m.started_at)
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            date_str = m.started_at or m.id
        mtype = f"[{C_PEACH}]{m.type or '–':12s}[/{C_PEACH}]"
        dur = ""
        if m.duration_sec:
            from .cli import _hms
            dur = f"[{C_DIM}]{_hms(m.duration_sec)}[/{C_DIM}]"
        enh = f"[{C_MINT}]✓[/{C_MINT}]" if _meeting_enhanced(pod, m) else f"[{C_DIM}]·[/{C_DIM}]"
        lines.append(f" {cursor} [{C_DIM}]{date_str}[/{C_DIM}]  {mtype}  {dur}  {enh}")

    # Action hints
    hints = (
        f"\n[{C_DIM}]"
        f"[r]ecord  [e]nhance  [c]ons  [Enter]view  [/]search  [Tab]switch  [q]quit"
        f"[/{C_DIM}]"
    )
    lines.append(hints)

    border = C_LILAC if state.focused_pane == "main" else C_DIM
    return Panel("\n".join(lines), title="Dashboard", border_style=border)


def render_status_bar(state: "AppState", pod: Pod) -> str:
    """Single Rich markup line for the status bar."""
    col = mode_colour(state.mode)
    badge = f"[bold {col}] {state.mode} [/bold {col}]"
    return f"{badge}  [{C_DIM}]{pod.name}[/{C_DIM}]"
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest tests/test_tui.py::test_render_dashboard_shows_pod_name tests/test_tui.py::test_render_status_bar_normal_mode tests/test_tui.py::test_render_status_bar_insert_mode -v
```

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -v -k "not transcriber"
```

- [ ] **Step 6: Commit**

```bash
git add podscribe/tui.py tests/test_tui.py
git commit -m "feat(tui): add render_dashboard, render_status_bar, _meeting_enhanced"
```

---

## Task 5: Fuzzy command palette

**Files:**
- Modify: `podscribe/tui.py`
- Test: `tests/test_tui.py`

**Interfaces:**
- Produces:
  - `FuzzyCandidate(kind: str, label: str, value: str)` — plain dataclass. `kind` is `"pod"` or `"cmd"`. `value` is the pod name or command key (e.g. `"init"`, `"export"`, `"search"`).
  - `build_palette_candidates(pod_names: list[str]) -> list[FuzzyCandidate]` — returns pod candidates first, then command candidates. Command candidates (fixed list): `init`, `export`, `import`, `search`, `config-llm`, `config-consolidate`.
  - `fuzzy_filter(candidates: list[FuzzyCandidate], query: str) -> list[FuzzyCandidate]` — returns candidates where `query.lower()` is a substring of `f"{candidate.kind} {candidate.label}".lower()`. Empty query returns all candidates.
  - `command_palette(console: Console, pod_names: list[str]) -> Optional[FuzzyCandidate]` — opens the palette overlay using `rich.live.Live`, reads keys via `read_key()`, returns the selected `FuzzyCandidate` or `None` on Escape/Ctrl+C.

- [ ] **Step 1: Write the failing tests**

```python
def test_build_palette_candidates_includes_pods_and_cmds():
    from podscribe.tui import build_palette_candidates, FuzzyCandidate
    candidates = build_palette_candidates(["sam-chen", "alex-wu"])
    kinds = [c.kind for c in candidates]
    assert "pod" in kinds
    assert "cmd" in kinds
    pod_labels = [c.label for c in candidates if c.kind == "pod"]
    assert "sam-chen" in pod_labels
    assert "alex-wu" in pod_labels

def test_fuzzy_filter_empty_query_returns_all():
    from podscribe.tui import build_palette_candidates, fuzzy_filter
    candidates = build_palette_candidates(["sam-chen"])
    assert fuzzy_filter(candidates, "") == candidates

def test_fuzzy_filter_narrows_by_substring():
    from podscribe.tui import build_palette_candidates, fuzzy_filter
    candidates = build_palette_candidates(["sam-chen", "alex-wu"])
    result = fuzzy_filter(candidates, "sam")
    labels = [c.label for c in result]
    assert "sam-chen" in labels
    assert "alex-wu" not in labels

def test_fuzzy_filter_matches_kind_prefix():
    from podscribe.tui import build_palette_candidates, fuzzy_filter
    candidates = build_palette_candidates(["sam-chen"])
    result = fuzzy_filter(candidates, "cmd")
    assert all(c.kind == "cmd" for c in result)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_tui.py::test_build_palette_candidates_includes_pods_and_cmds tests/test_tui.py::test_fuzzy_filter_empty_query_returns_all -v
```

- [ ] **Step 3: Implement in `tui.py`**

Add after `render_status_bar`:

```python
# ---------------------------------------------------------------------------
# Fuzzy command palette
# ---------------------------------------------------------------------------

from dataclasses import dataclass as _dc

@_dc
class FuzzyCandidate:
    kind: str   # "pod" | "cmd"
    label: str
    value: str  # pod name or command key

_PALETTE_COMMANDS = [
    FuzzyCandidate("cmd", "init",              "init"),
    FuzzyCandidate("cmd", "export",            "export"),
    FuzzyCandidate("cmd", "import",            "import"),
    FuzzyCandidate("cmd", "search",            "search"),
    FuzzyCandidate("cmd", "config-llm",        "config-llm"),
    FuzzyCandidate("cmd", "config-consolidate","config-consolidate"),
]


def build_palette_candidates(pod_names: list) -> list:
    pods = [FuzzyCandidate("pod", n, n) for n in pod_names]
    return pods + list(_PALETTE_COMMANDS)


def fuzzy_filter(candidates: list, query: str) -> list:
    if not query:
        return candidates
    q = query.lower()
    return [c for c in candidates if q in f"{c.kind} {c.label}".lower()]


def command_palette(console: Console, pod_names: list) -> Optional["FuzzyCandidate"]:
    """Fuzzy-search overlay. Returns selected FuzzyCandidate or None."""
    query = ""
    selected = 0

    def _render() -> Panel:
        filtered = fuzzy_filter(build_palette_candidates(pod_names), query)
        lines = [f"[{C_PEACH}]:[/{C_PEACH}] {query}▌\n"]
        for i, c in enumerate(filtered[:16]):
            cursor = f"[{C_PINK}]▶[/{C_PINK}]" if i == selected else " "
            badge = f"[{C_LILAC}][{c.kind}][/{C_LILAC}]"
            label = f"[{C_PINK}]{c.label}[/{C_PINK}]" if i == selected else c.label
            lines.append(f" {cursor} {badge} {label}")
        if not filtered:
            lines.append(f"[{C_DIM}]  no matches[/{C_DIM}]")
        return Panel("\n".join(lines), title="Command Palette", border_style=C_PEACH)

    with Live(_render(), console=console, refresh_per_second=30) as live:
        while True:
            k = read_key()
            filtered = fuzzy_filter(build_palette_candidates(pod_names), query)
            n = min(len(filtered), 16)

            if k in ("\x1b", "\x03"):   # Escape or Ctrl+C
                return None
            elif k in (KEY_ENTER, "\n"):
                if filtered and 0 <= selected < len(filtered):
                    return filtered[selected]
                return None
            elif k == KEY_UP:
                selected = (selected - 1) % max(n, 1)
            elif k == KEY_DOWN:
                selected = (selected + 1) % max(n, 1)
            elif k == "\x7f":           # Backspace
                query = query[:-1]
                selected = 0
            elif k.isprintable():
                query += k
                selected = 0
            live.update(_render())
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest tests/test_tui.py::test_build_palette_candidates_includes_pods_and_cmds tests/test_tui.py::test_fuzzy_filter_empty_query_returns_all tests/test_tui.py::test_fuzzy_filter_narrows_by_substring tests/test_tui.py::test_fuzzy_filter_matches_kind_prefix -v
```

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -v -k "not transcriber"
```

- [ ] **Step 6: Commit**

```bash
git add podscribe/tui.py tests/test_tui.py
git commit -m "feat(tui): add fuzzy command palette (FuzzyCandidate, build_palette_candidates, command_palette)"
```

---

## Task 6: Rewrite `launch()` with the two-pane modal loop

**Files:**
- Modify: `podscribe/tui.py` — replace the existing `launch()` function.
- Test: `tests/test_tui.py` — update the two existing `launch` smoke tests; add one new test.

**Interfaces:**
- Consumes: `AppState`, `render_sidebar`, `render_header`, `render_dashboard`, `render_status_bar`, `command_palette`, `record_view`, `enhance_view`, `consolidate_screen`, `_list_pod_names`, `_resolve_pod`, `_pick_meeting`, `probe_ollama`, `read_key`, `load_last_pod`, `save_last_pod`.
- Produces: `launch() -> int` — same signature as before. Returns 0 on quit, 0 on no-pods. The two existing smoke tests must still pass.

**Key bindings in NORMAL mode:**

| Key | Action |
|-----|--------|
| `j` / `↓` | move cursor down in focused pane |
| `k` / `↑` | move cursor up in focused pane |
| `Tab` | toggle `focused_pane` between `"sidebar"` and `"main"` |
| `r` | `record_view` for focused pod |
| `e` | pick meeting → `enhance_view` |
| `c` | pick meeting → `consolidate_screen` |
| `Enter` | (main pane) view transcript of focused meeting via `_dispatch_cli` |
| `/` | prompt for search query → `_dispatch_cli(["search", query])` |
| `:` | open `command_palette`; dispatch result |
| `q` / Ctrl+C | quit |

- [ ] **Step 1: Write the new smoke test**

```python
def test_launch_tab_switches_focused_pane(tmp_path, monkeypatch):
    """Tab key must switch focus between sidebar and main pane without crashing."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod
    init_pod("sam-chen", display_name="Sam Chen")
    import podscribe.tui as tui

    keys = iter(["Tab", "q"])
    def fake_key():
        k = next(keys)
        return "\t" if k == "Tab" else k
    monkeypatch.setattr(tui, "read_key", fake_key)
    monkeypatch.setattr(tui, "probe_ollama", lambda: False)
    rc = tui.launch()
    assert rc == 0
```

- [ ] **Step 2: Run the existing + new smoke tests to confirm they currently pass (before rewrite)**

```bash
pytest tests/test_tui.py::test_launch_no_pods_prints_panel_and_exits_0 tests/test_tui.py::test_launch_with_pod_and_q_exits_cleanly -v
```
Expected: `PASSED` (baseline).

- [ ] **Step 3: Rewrite `launch()` in `tui.py`**

Replace the entire `launch()` function (from `def launch() -> int:` to end of file):

```python
def launch() -> int:
    """Top-level TUI entry: two-pane modal layout with j/k navigation."""
    from argparse import Namespace
    from rich.layout import Layout
    from rich.columns import Columns

    console = Console()

    pod_names = _list_pod_names()
    if not pod_names:
        console.print(Panel(
            "No pods yet. Run `podscribe init <name>` to create one.",
            title=f"[{C_PINK}]podscribe[/{C_PINK}]",
            border_style=C_LILAC,
        ))
        return 0

    # Load last pod; default to first pod, focus on main (most recent meeting)
    last = load_last_pod()
    if last and last in pod_names:
        sidebar_idx = pod_names.index(last)
    else:
        sidebar_idx = 0

    pods = [_resolve_pod(n) for n in pod_names]
    pods = [p for p in pods if p is not None]
    if not pods:
        return 0

    state = AppState(
        pod_names=pod_names,
        sidebar_idx=sidebar_idx,
        main_idx=0,
        focused_pane="main",
    )
    ollama_ok = probe_ollama()

    def _current_pod() -> Pod:
        return pods[state.sidebar_idx]

    def _current_meetings():
        return list_meetings(_current_pod())

    def _render():
        pod = _current_pod()
        meetings = _current_meetings()
        header   = render_header(pod, ollama_ok)
        sidebar  = render_sidebar(state, pods)
        main     = render_dashboard(pod, meetings, state)
        status   = render_status_bar(state, pod)
        # Two-column layout: sidebar 22 chars wide, main takes rest
        cols = Columns([sidebar, main], equal=False, expand=True)
        return Panel(
            f"{header}\n",
            subtitle=status,
            border_style=C_LILAC,
        )

    def _full_render():
        pod = _current_pod()
        meetings = _current_meetings()
        return Columns(
            [render_sidebar(state, pods), render_dashboard(pod, meetings, state)],
            equal=False, expand=True,
        )

    with Live(console=console, refresh_per_second=12, screen=False) as live:
        def _refresh():
            pod = _current_pod()
            meetings = _current_meetings()
            from rich.console import Group
            header_text = render_header(pod, ollama_ok)
            status_text = render_status_bar(state, pod)
            sidebar_panel = render_sidebar(state, pods)
            main_panel    = render_dashboard(pod, meetings, state)
            cols = Columns([sidebar_panel, main_panel], equal=False, expand=True)
            from rich.text import Text
            live.update(Group(Text.from_markup(header_text), cols, Text.from_markup(status_text)))

        _refresh()

        while True:
            k = read_key()
            pod = _current_pod()
            meetings = _current_meetings()
            n_pods    = len(pods)
            n_meetings = len(meetings)

            # ── Navigation ──────────────────────────────────────────────
            if k in (KEY_DOWN, "j"):
                if state.focused_pane == "sidebar":
                    state.sidebar_idx = (state.sidebar_idx + 1) % max(n_pods, 1)
                    save_last_pod(pods[state.sidebar_idx].name)
                else:
                    state.main_idx = (state.main_idx + 1) % max(n_meetings, 1)
            elif k in (KEY_UP, "k"):
                if state.focused_pane == "sidebar":
                    state.sidebar_idx = (state.sidebar_idx - 1) % max(n_pods, 1)
                    save_last_pod(pods[state.sidebar_idx].name)
                else:
                    state.main_idx = (state.main_idx - 1) % max(n_meetings, 1)
            elif k == "\t":   # Tab
                state.focused_pane = "main" if state.focused_pane == "sidebar" else "sidebar"

            # ── Actions ─────────────────────────────────────────────────
            elif k == "r":
                live.stop()
                args = Namespace(
                    type=None, model="large-v3-turbo",
                    vad_aggressiveness=2, device=None, keep_audio=False,
                )
                state.mode = "INSERT"
                record_view(pod, args)
                state.mode = "NORMAL"
                live.start()
            elif k == "e":
                live.stop()
                meeting = _pick_meeting(console, pod)
                if meeting is not None:
                    state.mode = "STREAM"
                    enhance_view(pod, meeting)
                    state.mode = "NORMAL"
                live.start()
            elif k == "c":
                live.stop()
                meeting = _pick_meeting(console, pod)
                if meeting is not None:
                    consolidate_screen(pod, meeting)
                live.start()
            elif k in (KEY_ENTER, "\n"):
                if state.focused_pane == "main" and meetings:
                    live.stop()
                    m = meetings[state.main_idx] if state.main_idx < len(meetings) else meetings[0]
                    _dispatch_cli(["show", pod.name, m.id])
                    _pause(console)
                    live.start()
            elif k == "/":
                live.stop()
                console.print(f"[{C_DIM}]Search: [/{C_DIM}]", end="")
                try:
                    query = input().strip()
                except (EOFError, KeyboardInterrupt):
                    query = ""
                if query:
                    _dispatch_cli(["search", query])
                    _pause(console)
                live.start()
            elif k == ":":
                live.stop()
                candidate = command_palette(console, pod_names)
                if candidate is not None:
                    _dispatch_palette_candidate(console, candidate, pod)
                live.start()
            elif k in ("q", "\x03"):
                return 0

            _refresh()

    return 0


def _dispatch_palette_candidate(console: Console, candidate: "FuzzyCandidate", pod: Pod) -> None:
    """Execute a selected palette candidate, prompting for args as needed."""
    if candidate.kind == "pod":
        # Focus switches in launch() by sidebar_idx; here just acknowledge
        return
    cmd = candidate.value
    if cmd == "init":
        name = Prompt.ask("Pod name (kebab-case)", console=console)
        if name.strip():
            display = Prompt.ask("Display name", console=console, default="")
            role    = Prompt.ask("Role", console=console, default="")
            _dispatch_cli(["init", name.strip(),
                           *(["--display-name", display] if display else []),
                           *(["--role", role] if role else [])])
            _pause(console)
    elif cmd == "export":
        from datetime import datetime
        default_path = f"podscribe-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz"
        path = Prompt.ask("Export path", console=console, default=default_path)
        _dispatch_cli(["export", "--out", path.strip() or default_path])
        _pause(console)
    elif cmd == "import":
        path = Prompt.ask("Archive path", console=console)
        if path.strip():
            _dispatch_cli(["import", path.strip()])
            _pause(console)
    elif cmd == "search":
        query = Prompt.ask("Search query", console=console)
        if query.strip():
            _dispatch_cli(["search", query.strip()])
            _pause(console)
    elif cmd == "config-llm":
        model = Prompt.ask("Model name (e.g. qwen3.6:27b)", console=console)
        if model.strip():
            template = Prompt.ask("Prompt template (use {{transcript}} placeholder)",
                                  console=console)
            if template.strip():
                _dispatch_cli(["config", "llm", "set", model.strip(), template.strip()])
                _pause(console)
    elif cmd == "config-consolidate":
        prompt = Prompt.ask("Consolidate prompt (use {{summary}} placeholder)",
                            console=console)
        if prompt.strip():
            _dispatch_cli(["config", "consolidate", "set", prompt.strip()])
            _pause(console)
```

- [ ] **Step 4: Run smoke tests**

```bash
pytest tests/test_tui.py::test_launch_no_pods_prints_panel_and_exits_0 tests/test_tui.py::test_launch_with_pod_and_q_exits_cleanly tests/test_tui.py::test_launch_tab_switches_focused_pane -v
```
Expected: all `PASSED`.

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -v -k "not transcriber"
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add podscribe/tui.py tests/test_tui.py
git commit -m "feat(tui): rewrite launch() with two-pane modal layout and j/k navigation"
```

---

## Task 7: Waveform bar in `record_view`

**Files:**
- Modify: `podscribe/tui.py` — update `record_view` to pass `on_level` to `AudioCapture` and render the waveform bar.
- Test: `tests/test_tui.py`

**Interfaces:**
- Consumes: `AudioCapture(on_level=...)` from Task 1; `AppState.waveform` from Task 2.
- The waveform bar is a string of block characters (`▁▂▃▄▅▆▇█`) whose height maps from RMS `[0.0, 1.0]` to 8 levels. `WAVEFORM_WIDTH = 40` buckets. Rendered between the transcript body and the status footer inside the `record_view` `Live` panel.

- [ ] **Step 1: Write the failing test**

```python
def test_record_view_waveform_on_level_passed_to_capture(tmp_path, monkeypatch):
    """record_view must pass an on_level callback to AudioCapture."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, load_pod
    init_pod("sam-chen", display_name="Sam Chen")
    pod = load_pod("sam-chen")

    import unittest.mock as mock
    captured_kwargs = {}

    class FakeCapture:
        vad_aggressiveness = 2
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)
        def segments(self): return iter([])

    mock_transcriber = mock.MagicMock()
    mock_transcriber.model_name = "large-v3-turbo"
    mock_meeting = mock.MagicMock()
    mock_meeting.id = "2026-06-23-120000-sam-chen"
    mock_meeting.audio_path = tmp_path / "audio.raw"
    mock_meeting.transcript_path = tmp_path / "t.md"
    mock_meeting.transcript_path.touch()

    with mock.patch("podscribe.audio.AudioCapture", FakeCapture):
        with mock.patch("podscribe.transcriber.Transcriber", return_value=mock_transcriber):
            with mock.patch("podscribe.storage.start_meeting", return_value=mock_meeting):
                with mock.patch("podscribe.cli.run_record_session"):
                    import podscribe.tui as tui
                    from argparse import Namespace
                    args = Namespace(type=None, model="large-v3-turbo",
                                     vad_aggressiveness=2, device=None, keep_audio=False)
                    tui.record_view(pod, args)

    assert "on_level" in captured_kwargs, "on_level not passed to AudioCapture"
    assert callable(captured_kwargs["on_level"])
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_tui.py::test_record_view_waveform_on_level_passed_to_capture -v
```

- [ ] **Step 3: Update `record_view` in `tui.py`**

Add the `_WAVE_CHARS` constant and helper near the top of `record_view`:

```python
_WAVE_CHARS = "▁▂▃▄▅▆▇█"

def _rms_to_bar_char(rms: float) -> str:
    idx = int(min(rms, 0.999) * len(_WAVE_CHARS))
    return _WAVE_CHARS[idx]
```

In `record_view`, change the `AudioCapture` construction to pass `on_level`:

```python
    waveform: list = [0.0] * WAVEFORM_WIDTH

    def _on_level(rms: float) -> None:
        waveform.append(rms)
        if len(waveform) > WAVEFORM_WIDTH:
            del waveform[: len(waveform) - WAVEFORM_WIDTH]

    capture = AudioCapture(
        vad_aggressiveness=getattr(args, "vad_aggressiveness", 2),
        device=getattr(args, "device", None),
        on_level=_on_level,
    )
```

In `_render()` inside `record_view`, add a waveform line between the transcript body and the footer:

```python
    def _render() -> Panel:
        m, s = divmod(int(status.get("elapsed", 0)), 60)
        h, m_ = divmod(m, 60)
        footer = (
            f"elapsed {h:02d}:{m_:02d}:{s:02d}  "
            f"segs={status.get('segment_count', 0)}  "
            f"VAD={status.get('vad_aggr', '?')}  "
            f"overflow={'WARN' if status.get('overflow') else 'ok'}"
        )
        wave_str = "".join(_rms_to_bar_char(v) for v in waveform[-WAVEFORM_WIDTH:])
        body = "\n".join(lines[-BUFFER_LINES:])
        return Panel(
            body + f"\n\n[{C_PINK}]{wave_str}[/{C_PINK}]\n" + footer + "\n" + status_line["text"],
            title=f"[{C_PEACH}]record[/{C_PEACH}]",
            border_style=C_PINK,  # INSERT mode: pink border
        )
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest tests/test_tui.py::test_record_view_waveform_on_level_passed_to_capture -v
```

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -v -k "not transcriber"
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add podscribe/tui.py tests/test_tui.py
git commit -m "feat(tui): real RMS waveform bar in record_view using on_level callback"
```

---

## Task 8: Clean up dead code and update existing tests

**Files:**
- Modify: `podscribe/tui.py` — remove `_select_menu`, `_action_menu`, `_others_menu`, `_glossary_menu`, `_llm_config_menu`, `_consolidate_cfg_menu`, `_render_banner`, `_others_glossary`, `_others_llm_config`, `_others_consolidate_cfg` (all replaced by the new modal layout + palette).
- Test: `tests/test_tui.py` — remove or update tests that reference the deleted functions.

**Note:** Check which tests reference the old functions before deleting:

- [ ] **Step 1: Identify tests to remove/update**

```bash
grep -n "_action_menu\|_others_menu\|_select_menu\|_render_banner" tests/test_tui.py
```
Any test that only tests the old menu functions can be deleted; tests that test `record_view`, `enhance_view`, `consolidate_screen`, `launch`, `_pick_meeting`, `_pick_pod`, `_fmt_meeting_label` stay unchanged.

- [ ] **Step 2: Remove old menu functions from `tui.py`**

Delete these functions from `tui.py`:
- `_select_menu`
- `_render_banner`
- `_action_menu`
- `_others_menu`
- `_glossary_menu`
- `_llm_config_menu`
- `_consolidate_cfg_menu`
- `_others_glossary`
- `_others_llm_config`
- `_others_consolidate_cfg`

- [ ] **Step 3: Update `tests/test_tui.py`**

Remove tests that reference deleted functions:
- `test_action_menu_ctrl_c_returns_quit` (references `tui._action_menu`)
- `test_others_menu_ctrl_c_returns_quit` (references `tui._others_menu`)

These are replaced by the new navigation tests added in Tasks 2–6.

- [ ] **Step 4: Run full suite**

```bash
pytest tests/ -v -k "not transcriber"
```
Expected: all green (the deleted test count should match the number of tests removed).

- [ ] **Step 5: Commit**

```bash
git add podscribe/tui.py tests/test_tui.py
git commit -m "refactor(tui): remove old flat-menu helpers replaced by two-pane modal layout"
```

---

## Task 9: Manual smoke test + final validation

- [ ] **Step 1: Run the full test suite one final time**

```bash
pytest tests/ -v -k "not transcriber"
```
Expected: all green, no new warnings.

- [ ] **Step 2: Manual terminal smoke test (requires at least one pod)**

If no pod exists, create one first:
```bash
podscribe init test-pod --display-name "Test Pod" --role "Engineer"
```

Then open the TUI:
```bash
podscribe
```

Verify:
- [ ] Header bar shows pod name + ollama status
- [ ] Sidebar shows pod list; focused pod highlighted in pink
- [ ] Main pane shows Dashboard with stats and recent meetings
- [ ] `j`/`k` navigate the meeting list (main pane focused by default)
- [ ] `Tab` switches focus to sidebar; `j`/`k` navigate pods
- [ ] `:` opens the fuzzy palette; typing filters candidates; Escape closes it
- [ ] `q` exits cleanly

- [ ] **Step 3: Commit any final fixes, then tag**

```bash
git add -A
git commit -m "chore: final cleanup after tui-modal-redesign smoke test"
```
