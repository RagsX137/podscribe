# ADR 0001 — Modal two-pane TUI layout

**Date:** 2026-06-22  
**Status:** Accepted  
**Deciders:** @anuragkaushik137  

---

## Context

The first-generation TUI (`tui.py`, delivered per `docs/superpowers/specs/2026-06-23-tui-redesign-design.md`)
implemented a launcher as a flat numbered-menu loop with `_select_menu` panels
and `rich.live.Live` for recording and enhance views. It works, but each screen
is isolated — no persistent chrome, no spatial context about pods or meetings,
and debug noise (VAD level, overflow flag, segment count) appears inline with
the transcript body.

The user wants a richer, more intentional UX inspired by tools like OpenCode /
Lazygit: a persistent two-pane shell, modal navigation, and a colour-coded
status bar that communicates app state at a glance.

---

## Decision

Replace the flat launcher loop with a **modal, two-pane persistent layout**:

### Layout

```
┌──────────────────────────────────────────────────────────┐
│  podscribe  ·  <pod>  ·  <role>          ◉ ollama  ? : / │  header
├─────────────┬────────────────────────────────────────────┤
│  Pods       │  Dashboard / Meetings / Live transcript     │
│  (sidebar)  │  (main pane — context-sensitive)           │
├─────────────┴────────────────────────────────────────────┤
│  [MODE]  <pod>  ·  <stats>              model  ctx       │  status bar
└──────────────────────────────────────────────────────────┘
```

### Modes

| Mode    | Trigger         | Status bar colour | Key bindings active          |
|---------|-----------------|-------------------|------------------------------|
| NORMAL  | default         | purple `#c9a5f7`  | j/k, Tab, r, e, c, /, :, q  |
| INSERT  | recording live  | red `#ff6b8a`     | Ctrl+C only                  |
| STREAM  | enhance running | red `#ff6b8a`     | Ctrl+C only                  |
| COMMAND | `:` pressed     | peach `#ffcba4`   | type to fuzzy-filter, Esc    |

INSERT and STREAM share a red status bar (they are both "Active mode") — two
colour tiers only: idle (purple/peach) vs active (red).

### Navigation

- Default focus on launch: **main pane**, most recent meeting of last-used pod.
- `j/k` navigate within the focused pane (meetings in main; pods in sidebar).
- `Tab` transfers focus between sidebar and main pane.
- `r/e/c` act on the focused pod (sidebar) + focused meeting (main).

### Main pane default view

The main pane shows a **Dashboard** when no action is in flight:
- Pod stats card: total meetings, enhancement coverage %, last-met date.
- Recent-meetings list: date · type badge · duration · enhanced indicator.
- Action hints row at the bottom.

### Command palette

`:` opens a fuzzy-search overlay. Candidates: all pod names (`[pod]`) and
available commands (`[cmd]`). Selecting a pod jumps sidebar focus. Selecting
an argument-bearing command (`init`, `export`, `config llm set`) closes the
palette and opens a `Prompt.ask` flow for required arguments.

### Waveform bar

Visible only in INSERT mode. A row of amplitude bars driven by real RMS energy
from the audio pipeline (~100ms buckets, one bar per bucket in a rolling window).
Placed between the transcript area and the status bar. Communicates mic
activity vs silence without requiring the user to read numbers.

---

## Alternatives considered

**Keep the flat `_select_menu` loop** — Fast to maintain, but gives no spatial
context. The user must navigate through multiple menus to reach a meeting.
Rejected: does not meet the stated UX goal.

**Full `textual` framework** — Would give reactive widgets and mouse support
out of the box. Rejected: adds a heavy framework dependency and an async
programming model incompatible with the blocking audio capture loop. The
existing `rich.live` + raw `readchar` stack is sufficient.

**Single status bar colour** — Simpler. Rejected: losing the mode colour
removes the most valuable peripheral signal — whether a recording is currently
in flight.

**Four distinct mode colours** — NORMAL (purple), INSERT (red), STREAM (mint),
COMMAND (peach). Rejected in favour of two tiers: both active states (INSERT +
STREAM) share red, because the important distinction is "something is running"
vs "idle", not which kind of something.

---

## Consequences

- `tui.py` is substantially rewritten. The existing `_select_menu` / flat
  launcher loop is replaced by a two-pane render loop.
- `audio.py` gains a lightweight RMS callback (`on_level: Callable[[float], None]`)
  emitted per chunk to drive the waveform bar. The callback is a no-op by
  default; no behaviour change for non-TUI callers.
- The `run_record_session` / `enhance_transcript` callback interfaces introduced
  in the first-generation spec are preserved unchanged — only the view layer
  changes.
- All 205 existing tests continue to pass (the cores are TTY-free).
