# God Mode — Agentic LLM frontend for Podscribe

**Date:** 2026-06-25
**Status:** Draft design

## Overview

God mode is a new interactive frontend for Podscribe where an Ollama-hosted LLM acts as an agentic "brain" with access to Podscribe's capabilities as callable tools. The user interacts via natural language or slash commands; the agent reasons, calls tools, and reports results.

## Architecture

### New modules

| Module | Responsibility |
|---|---|
| `podscribe/agent_tools.py` | Wraps existing Podscribe internals into ~13 callable functions with clean signatures (no argparse). Each function maps to a tool the agent can invoke. |
| `podscribe/agent.py` | The agent loop: `GodSession` class manages conversation history, Ollama streaming with function calling, tool dispatch, and the REPL/one-shot lifecycle. |

### Modified modules

| Module | Change |
|---|---|
| `podscribe/cli.py` | Add `god` subcommand via argparse. Add `cmd_god` handler. |
| `podscribe/tui.py` | Add `god_view` — a standalone two-pane Rich Live TUI for the interactive session (does NOT compose existing `AppState`/sidebar machinery). |
| `podscribe/llm.py` | Add `chat_stream()` — new function for the `/api/chat` endpoint with `messages` array + `tools` parameter support. Keeps all Ollama HTTP in one module. `agent.py` calls this, not Ollama directly. The existing `/api/generate` path is unchanged. |

### Data flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         god_view (tui.py)                        │
│                                                                  │
│  ┌──────────────────────────────┬──────────────────────────────┐ │
│  │  Left pane (~70%)           │  Right pane (~30%)            │ │
│  │  Agent reasoning + chat     │  Tool reference / live        │ │
│  │                             │  transcript during recording   │ │
│  └──────────┬───────────────────┴──────────┬───────────────────┘ │
│             │                              │                    │
│             │                              │                    │
│     GodSession (agent.py)         Recording thread             │
│     ┌──────────────────┐         (during active recording)     │
│     │ llm.chat_stream()│         ┌──────────────┐              │
│     │ (/api/chat)      │         │ AudioCapture │              │
│     │ messages + tools │◄────────│ + Transcriber│              │
│     └───────┬──────────┘         └──────┬───────┘              │
│             │                           │                       │
│             ▼                           ▼                       │
│     agent_tools.py             transcript_lines Queue           │
│     (tool implementations)     (fed to right pane)             │
└─────────────────────────────────────────────────────────────────┘
```

## Tool inventory (`agent_tools.py`)

Each tool wraps existing Podscribe internals (storage, config, glossary, audio, transcriber). No argparse — clean Python function signatures.

| Tool | Signature | Description |
|---|---|---|
| `list_pods` | `() → list[str]` | All existing pod names |
| `pod_info` | `(name: str) → dict` | Pod metadata + stats |
| `init_pod` | `(name, display_name, role, cadence, notes) → dict` | Create new pod |
| `list_meetings` | `(pod, since, type, recent) → list[dict]` | Filterable meeting list |
| `show_meeting` | `(pod, meeting_id) → str` | Raw transcript text |
| `start_recording` | `(pod, model, vad, meeting_type) → dict` | Launch background recording thread. Returns session info. |
| `stop_recording` | `() → dict` | Stop active recording, finalize meeting |
| `get_recording_status` | `() → dict` | Latest transcript lines + elapsed time for TUI polling |
| `enhance_meeting` | `(pod, meeting_id) → str` | Run LLM enhance, return enhanced text |
| `consolidate_meeting` | `(pod, meeting_id, no_log) → dict` | Extract structured fields, update CSV |
| `search_transcripts` | `(query, pod, since, type) → list[dict]` | Full-text search |
| `glossary_list` | `(pod) → list[dict]` | Effective glossary for pod |
| `glossary_add` | `(pod, term, category) → dict` | Add glossary entry |
| `glossary_remove` | `(pod, term) → dict` | Remove glossary entry |
| `export_data` | `(out_path) → str` | Export tarball path |

**Recording lifecycle:** `start_recording` launches a background thread running `AudioCapture` + `Transcriber` + `append_segment`. The thread writes to a shared `transcript_lines` list (thread-safe) that the TUI reads for the right pane. `stop_recording` sets a stop flag; the thread finalizes the meeting and exits.

**Critical: The background thread uses a stripped-down capture loop** — it does NOT install signal handlers (Python `signal` only works on the main thread). Stop is driven solely by `capture.stop()` which sets `_running = False` on the `AudioCapture` instance. The thread's finally block calls `finalize_meeting` (no signal manipulation).

## Agent Loop (`agent.py`)

### `GodSession` class

```
GodSession:
  model: str            — Ollama model tag (default from config or --model flag)
  messages: list        — Full conversation history [system, user, assistant, tool_results]
  tool_defs: list       — JSON schema for Ollama /api/chat tools parameter
  registry: dict        — tool name → callable from agent_tools
  stop_flag: threading.Event  — signals recording thread to stop
  transcript_lines: list[str] — live transcript buffer (thread-safe append)

  repl()                — Interactive REPL with prompt
  run_prompt(text)      — Single-turn execution for one-shot mode
  _step(messages)       — One LLM call → tool call → result → loop until response
  _execute(tool_call)   — Dispatch to registry, return result
```

### Ollama /api/chat streaming shape

`agent.py` calls `llm.chat_stream()` (not Ollama directly). The `/api/chat` streaming response differs from the existing `/api/generate`:

**Text-only chunk:**
```json
{"message": {"role": "assistant", "content": "Let me "}, "done": false}
```

**Tool call chunk (only in final `done: true` chunk when streaming):**
```json
{
  "message": {
    "role": "assistant",
    "content": "",
    "tool_calls": [
      {"function": {"name": "list_pods", "arguments": "{}"}, "type": "function"}
    ]
  },
  "done": true
}
```

**Accumulation logic:** Content tokens are accumulated from consecutive non-done chunks. When a `done: true` chunk arrives, if it contains `tool_calls`, those are dispatched. If no `tool_calls`, the accumulated content is the final assistant message.

### `_step()` loop

```
1. Call llm.chat_stream(model, messages, tools=tool_defs)
2. Stream chunks:
   - content token → print to left pane, accumulate
   - done:true with tool_calls → break stream
   - done:true without tool_calls → final message, return
3. If tool_calls:
   - Show ◇ tool_name(args) in left pane
   - For each call: _execute(call), append result to messages
   - Go to step 1 (loop back with tool results)
4. If done (no tool_calls → regular assistant message):
   - Append accumulated content to messages
   - Return control to REPL
```

### System prompt

Instructs the model:
- You are the Podscribe assistant — a tool-calling agent for meeting transcription and management
- These tools are available (list with descriptions)
- Be transparent: explain your reasoning as you work
- For recording: tell the user you're starting, call start_recording, explain they can type "stop" or "/stop" when done
- Call tools one at a time. Don't parallelize.
- If a tool returns an error, report it clearly and offer alternatives
- Summarize results concisely

### Model resolution fallback chain

The agent resolves the Ollama model tag (in order):
1. `--model` CLI flag (if provided)
2. Project-level config `podscribe.yaml` → `llm.model` (e.g. `qwen3.6:27b-mlx`)
3. Hardcoded default: `qwen3.6:27b-mlx`

No per-pod `llm.model` resolution — god mode operates across pods, so project-level config is the right level.

### Model caching

- Ollama `keep_alive: -1` keeps model weights in GPU memory between requests
- Conversation history (messages list) grows per turn — future optimization: sliding window or summary compression

### Tool result truncation

Tool results that return large text (transcripts, enhanced summaries, search results) are truncated to `MAX_TOOL_RESULT_CHARS = 8000` before being injected into conversation history. A `[...truncated, full result on disk]` suffix is appended. The agent sees enough to understand the content; the full result lives on the filesystem.

## CLI entry point

```
podscribe god                        → interactive REPL (two-pane TUI)
podscribe god "record sam and enhance" → one-shot, stdout, exit
podscribe god --model qwen3.6:27b-mlx  → custom Ollama model
```

### New argparse subcommand

```python
p_god = sub.add_parser("god", help="Agentic mode: LLM brain with tool access.")
p_god.add_argument("prompt", nargs="?", help="One-shot prompt (omit for REPL)")
p_god.add_argument("--model", default=None, help="Ollama model tag")
```

### `cmd_god` handler

```python
def cmd_god(args) -> int:
    if args.prompt:
        # One-shot: print results to stdout, exit
        session = GodSession(model=args.model)
        return session.run_prompt(args.prompt)
    # REPL: launch two-pane TUI
    if sys.stdout.isatty():
        from .tui import god_view
        return god_view(model=args.model)
    # Non-TTY fallback
    print("god mode requires a TTY.", file=sys.stderr)
    return 2
```

## Two-pane TUI (`tui.py` — `god_view`)

### Layout

Uses Rich `Live` with a `Columns` layout:

```
┌─────────────────────────────────┬──────────────────────┐
│  Left pane (~70%)               │ Right pane (~30%)    │
│                                 │                      │
│  [Header: podscribe god mode]   │ TOOLS (idle) or      │
│                                 │ LIVE TRANSCRIPT      │
│  ● Agent reasoning...           │ (recording)          │
│  ◇ tool_call(args)              │                      │
│  Result: ...                    │ /record <pod>        │
│                                 │ /enhance <pod>       │
│  You: user message              │ /consolidate <pod>   │
│                                 │ /list [pod]          │
│  ● Agent response...            │ /show <pod> <id>     │
│                                 │ /search <query>      │
│                                 │ /init <name>         │
│                                 │ /export              │
│  [Input: _________________]     │ /help /exit          │
│                                 │                      │
│  [Status bar: mode, pod, model] │                      │
└─────────────────────────────────┴──────────────────────┘
```

### Right pane states

| State | Content |
|---|---|
| **Idle** | Reference card with all slash commands and brief tool descriptions |
| **Recording** | Live transcript lines `[HH:MM:SS] text`, elapsed time, segment count, waveform bar, "Press `s` or type 'stop' to end" hint |

### Slash commands

Slash commands execute tools directly (bypass agent reasoning) but inject the result into the agent's conversation history so the agent stays aware:

| Command | Action | Agent history injection |
|---|---|---|
| `/record <pod> [--type]` | `start_recording()` | `System: /record executed → meeting_id=X, status=recording` |
| `s` / `/stop` | `stop_recording()` | `System: /stop executed → meeting_id=X finalized` |
| `/enhance <pod> [meeting]` | `enhance_meeting()` | `System: /enhance executed → result` |
| `/consolidate <pod> [meeting]` | `consolidate_meeting()` | `System: /consolidate executed → result` |
| `/list [pod]` | `list_pods()` / `list_meetings()` | `System: /list executed → result` |
| `/show <pod> <meeting>` | `show_meeting()` | `System: /show executed → result` |
| `/search <query>` | `search_transcripts()` | `System: /search executed → result` |
| `/init <name> [--display-name]` | `init_pod()` | `System: /init executed → result` |
| `/export [--out]` | `export_data()` | `System: /export executed → result` |
| `/help` | Show reference in right pane | None |
| `/exit` | Exit god mode | None |

When a slash command runs, the left pane shows `◇ /command args` followed by the result, and the message is injected into the agent's conversation context.

### Recording thread (`recording` state in right pane)

```python
_recording_session = None  # module-level, one active recording at a time

def start_recording(pod_name, model="large-v3-turbo", vad=2, meeting_type=None):
    """Launch background recording. No signal handlers — stop via stop_recording()."""
    pod = load_pod(pod_name)
    meeting = start_meeting(pod, meeting_type=meeting_type)
    capture = AudioCapture(vad_aggressiveness=vad)
    transcriber = Transcriber(model=model)
    glossary = format_glossary_prompt(get_effective_glossary(pod))
    lines: list = []  # thread-safe: only appended, read by TUI

    def _record_thread():
        """Stripped-down run_record_session — no SIGINT.
        Stop is driven solely by capture.stop() → _running = False.
        """
        with meeting.transcript_path.open("w") as f:
            f.write(f"# Meeting: {meeting.id}\n\n")
        start_ts = time.monotonic()
        try:
            for audio_segment in capture.segments():
                kwargs = {}
                if glossary:
                    kwargs["initial_prompt"] = glossary
                results = transcriber.transcribe(audio_segment, **kwargs)
                for r in results:
                    elapsed = time.monotonic() - start_ts
                    seg = Segment(start_sec=elapsed, end_sec=elapsed, text=r["text"])
                    append_segment(meeting, seg)
                    lines.append(f"[{_hms(seg.start_sec)}] {seg.text}")
        finally:
            capture.stop()
            meeting.duration_sec = int(time.monotonic() - start_ts)
            meeting.ended_at = datetime.now().isoformat(timespec="seconds")
            finalize_meeting(meeting, keep_audio=True)

    thread = threading.Thread(target=_record_thread, daemon=True)
    thread.start()
    _recording_session = {
        "pod": pod, "meeting": meeting,
        "capture": capture, "thread": thread,
        "transcript_lines": lines,
    }
    return {"meeting_id": meeting.id, "pod": pod_name, "status": "recording"}

def stop_recording():
    session = _recording_session
    if session is None:
        return {"error": "no active recording"}
    session["capture"].stop()
    session["thread"].join(timeout=10)
    _recording_session = None
    m = session["meeting"]
    return {"meeting_id": m.id, "segments": len(session["transcript_lines"]),
            "duration_sec": m.duration_sec, "status": "finalized"}
```

The right pane polls `session["transcript_lines"]` (thread-safe — list is only appended, never mutated in place) on each render tick.

During recording, the input handler checks if a recording is active. If the user submits a single `s` (the full input line is just `s\n`), it triggers `stop_recording()` directly — no agent involvement. Longer inputs like `stop` or `stop recording` are sent to the agent as normal messages (the agent will naturally call `stop_recording`). The `/stop` slash command also works at any time, recording or not, for consistency.

## User interaction examples

### Natural language → agent orchestrates

```
You: record a 1on1 with sam and then enhance it

  ● Let me check if Sam's pod exists...
  ◇ list_pods()
  Result: ["sam-chen"]

  ● Pod found. Starting recording — press `s` or type "stop" when you're done.
  ◇ start_recording(pod="sam-chen", type="1on1")
  Result: meeting_id="2026-06-25-143012-sam-chen", status=recording

  [right pane shows live transcript]
  [user speaks, transcript streams]
  [user types: stop]

  You: stop

  ◇ stop_recording()
  Result: meeting finalized, 42 segments, 12m34s

  ● Great, now enhancing...
  ◇ enhance_meeting(pod="sam-chen", meeting="2026-06-25-143012-sam-chen")
  [streaming tokens...]
  Result: enhanced transcript saved to ...

  ● All done! Sam's 1:1 has been transcribed and enhanced.
```

### Slash commands → direct execution

```
You: /list

  ◇ /list
  Result: sam-chen, engineering-standup

You: /record engineering-standup --type standup

  ◇ /record engineering-standup --type standup
  Result: recording started

  [right pane shows live transcript]
```

## Edge cases

| Scenario | Behavior |
|---|---|
| Ollama not running | Graceful error at startup: "Ollama not reachable. Start with `ollama serve`" |
| No pods exist | Right pane shows /init command. Agent suggests creating a pod first. |
| Recording fails (no mic) | Tool returns error message with troubleshooting hint |
| Ambiguous user goal | Agent asks clarifying question before acting |
| `/stop` with no recording | Error displayed: "No active recording" |
| Consecutive `/` commands | Each executes independently; agent history updated each time |
| Model context overflow | Full history sent each turn. Future: sliding window summarization |
| Enhance blocks for long transcripts | `enhance_meeting` is synchronous for v1. TUI shows spinner with elapsed time while agent loop waits. Token streaming during enhance can be added later. |
| Consolidate before enhance | `consolidate_meeting` checks for enhanced summary file first. Returns clear error if missing. |
| Tool result too large | Truncated at 8000 chars with `[...truncated]` suffix. Full content on disk. |
| LLM streaming interrupted | Agent retries (reuse existing retry logic from `llm.py`) |

## Testing strategy

### New test file: `tests/test_agent.py`

**Unit tests (no Ollama needed):**
- Each `agent_tools` function in isolation with mocked dependencies (mock `storage`, `config`, `AudioCapture`, `Transcriber` at the module level — `agent_tools` never touches audio hardware in tests)
- Slash command parsing: `/record sam --type 1on1` → parsed correctly
- Recording thread lifecycle: mock `AudioCapture.segments()` to yield test data, verify `start_recording` thread starts, `stop_recording` joins, meeting finalized, transcript lines populated
- Conversation history accumulation: messages list grows correctly
- Tool result injection: system messages added after tool calls
- Tool result truncation: result > 8000 chars truncated with `[...truncated]`
- `consolidate_meeting` without enhanced summary → returns error, doesn't crash

**Integration test (requires Ollama):**
- `GodSession` with real model, simple query "list pods" (no tool call needed — verifies connection + streaming)

### Existing test modifications

- None — God mode is additive, no changes to existing behavior

## Files to create/modify

| File | Action | Content |
|---|---|---|
| `podscribe/agent_tools.py` | **Create** | ~15 tool functions wrapping storage/config/audio/transcriber |
| `podscribe/agent.py` | **Create** | `GodSession` class, uses `llm.chat_stream()` for /api/chat |
| `podscribe/llm.py` | **Modify** | Add `chat_stream()` — /api/chat endpoint with messages + tools |
| `podscribe/tui.py` | **Modify** | Add `god_view()` function (standalone two-pane Rich Live layout) |
| `podscribe/cli.py` | **Modify** | Add `god` subcommand + `cmd_god` handler |
| `tests/test_agent.py` | **Create** | Tests for agent_tools, agent loop, slash commands |

## Design decisions

1. **Ollama native function calling** over ReAct text-based — cleaner, more reliable, Qwen supports it. The model can natively decide when to call tools.
2. **Background thread for recording** — keeps the agent loop responsive during recording. The user can type messages while recording is active.
3. **Slash commands inject into agent context** — keeps the agent aware of what happened, enabling seamless follow-up ("enhance what we just recorded").
4. **Separate `agent_tools.py` module** — keeps tool implementations independent of the agent loop. CLI commands could also use this module in the future (reducing argparse boilerplate).
5. **Rich TUI for the REPL** — consistent with existing `tui.py` patterns. Two-pane layout is the minimum needed for the live transcript display.
6. **`keep_alive: -1`** — Ollama keeps the model in GPU memory between requests. First call loads the model; subsequent calls reuse cached weights.
