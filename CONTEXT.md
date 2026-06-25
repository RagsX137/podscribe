# Podscribe — Ubiquitous Language

This glossary defines the canonical terms used across the codebase, docs, and
conversations about podscribe. Conflicts with this file take precedence over
informal usage; update this file when a term is resolved, not after the fact.

---

## Core domain

**Pod** — A named, persistent context for a recurring relationship (one person,
one team, one recurring meeting series). Identified by a kebab-case slug
(e.g. `sam-chen`). All meetings, transcripts, and summaries belong to exactly
one pod.

**Meeting** — A single recorded session within a pod. Identified by
`YYYY-MM-DD-HHMMSS-<pod-name>`. Has a type, start time, duration, and at least
one transcript file.

**Transcript** — The raw, timestamped, line-by-line text output of a recording.
Stored as `.md` under `pods/<name>/transcripts/`. Appended incrementally
during recording (crash-safe). Never rewritten after finalization.

**Enhanced transcript / Summary** — The LLM-cleaned version of a transcript,
stored as `.md` under `pods/<name>/summaries/`. Written once by `enhance`.

**Segment** — One unit of transcribed audio: a timestamp + text string, emitted
by the Whisper model for a detected speech chunk.

**Glossary** — The per-pod (+ global) list of named entities (people, projects,
clients) injected as Whisper `initial_prompt` to improve transcription accuracy.
Not the same as this CONTEXT.md file.

**Pod config** — `pods/<name>/config.yaml`. Stores pod metadata, pod-specific
glossary entries, and an optional per-pod `llm` section.

---

## TUI domain

**Normal mode** — The default interactive state of the TUI. The cursor rests on
a meeting in the main pane; `j/k` navigate; single-letter keys (`r`, `e`, `c`,
`/`, `:`) trigger actions. Status bar is purple (`#c9a5f7`).

**Insert mode** — The state during an active recording. The transcript streams
live into the main pane; the waveform bar animates; no navigation keys respond.
Status bar is hot-pink/red (`#ff6b8a`). Exited by Ctrl+C.

**Active mode** — Umbrella term for Insert mode and Stream mode — any state
where an async process (recording or LLM streaming) is in flight. Status bar
is hot-pink/red. Contrast with Normal mode and Command mode.

**Stream mode** — The state during an active `enhance` LLM token stream.
Tokens render live in the main pane. Part of Active mode (red status bar).

**Command mode** — The state when the command palette is open (`:` key).
Status bar is peach (`#ffcba4`). Exited by Escape or Enter.

**Sidebar** — The left pane. Always visible. Lists all pods; `j/k` navigate
when sidebar has focus. `Tab` transfers focus to the main pane.

**Main pane** — The right pane. Context-sensitive: shows the Dashboard by
default, the meeting list when browsing, a live transcript during recording,
or a token stream during enhance.

**Dashboard** — The default view of the main pane when no action is in flight.
Shows pod stats (total meetings, enhancement coverage, last-met date) and a
recent-meetings list for the focused pod.

**Status bar** — The bottom row of the terminal. Always visible. Colour
encodes the current mode (purple = Normal, red = Active, peach = Command).
Carries the mode badge, current pod name, and runtime metrics (elapsed,
segment count, model, context size). All debug noise (VAD level, overflow
flag) lives here, not in the main pane.

**Command palette** — A fuzzy-search overlay opened by `:`. Candidates are pods
(`[pod]` badge) and commands (`[cmd]` badge). Selecting a pod jumps focus;
selecting an argument-bearing command closes the palette and opens a
`Prompt.ask` flow for arguments.

**Waveform bar** — A row of amplitude bars between the transcript area and the
status bar, visible only in Insert mode. Driven by real RMS amplitude from the
audio pipeline (one value per ~100ms chunk). Communicates mic activity vs
silence at a glance.
