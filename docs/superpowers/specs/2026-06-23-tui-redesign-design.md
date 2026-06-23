# Design: TUI redesign (hybrid) + enhance progress-bar fix

**Date:** 2026-06-23
**Status:** Approved (brainstormed)

## Summary

Two things, one effort:

1. **Bug — the enhance "progress bar" is fictional.** `llm.enhance_transcript` constructs a `tqdm` bar with no `total` (`podscribe/llm.py:112-115`). Ollama's `/api/generate` stream reports no token total until the final `done` chunk, so `bar.total` is `None` and tqdm renders a bare token counter (`qwen3.6:27b: 412tok [00:27, 18.0tok/s]`) — never the `68%|████| 412/600` fill bar shown in `docs/USER-MANUAL.md:172`. The docs lie. Fix: remove tqdm; stream tokens to a caller-supplied callback and let the view render honest feedback.
2. **Redesign — a hybrid terminal UI.** Bare `podscribe` opens a launcher menu (an existing mockup lives at `.scratch/mockup-synthwave-pastel.txt`). The two inherently-interactive flows — `record` and `enhance` — get live `rich.live` views. One-shot commands stay non-interactive, just rendered with `rich` panels/tables. The non-interactive path (`podscribe <pod> <cmd>`) is preserved unchanged in behavior.

## Root cause (evidence)

Diagnostic at `.scratch/diag_progressbar.py` replicates the exact constructor:

```
bar = tqdm(desc=model, unit="tok", file=sys.stderr, mininterval=0.5, dynamic_ncols=True)
```

Output:

```
bar.total = None
rendered last line: 'qwen3.6:27b: 412tok [00:00, 3217976.25tok/s]'
```

`bar.total is None` → no denominator → no `%`, no fill bar, no ETA. The documented `68%|████| 412/600` is unachievable without a `total`, which the Ollama stream never provides pre-completion. `tqdm` auto-disable is **not** the bug (`sys.stderr.isatty()` was `False` in the diagnostic but `bar.disable` stayed `False`).

## Goals

- Honest, live feedback during `enhance` (no fake percentages).
- Live transcript during `record` (matching the existing line-by-line behavior, in a panel).
- A launcher front-door matching the existing mockup, with a remembered pod.
- One home for the record/enhance orchestration logic; 205 existing tests stay green.
- `rich` rendering for one-shot commands, gracefully degrading when piped/non-TTY.
- No new heavy/framework deps — `rich` + a small raw-key reader (`readchar`) for single-key launcher input; drop `tqdm`.

## Non-goals

- No full persistent TUI app (textual/curses), no keyboard nav across many views.
- No pause/resume/marker keys during record (Ctrl+C to stop, as today).
- No async rewrite of the blocking audio capture loop.
- No change to on-disk formats (transcripts, summaries, CSV, config).
- No `play <meeting-id>` command in this spec (separate effort; only relevant if `--keep-audio`).

## Architecture

### New module: `podscribe/tui.py` (lazy-imported)

Holds the launcher and the rich live views. Never imported by one-shot commands. Mirrors the existing lazy-import pattern for `audio`/`transcriber` (AGENTS.md: "Audio modules lazy-imported in `cmd_record`").

### Headless cores + callback renderers

Extract the pure orchestration out of `cmd_record` and `llm.enhance_transcript` so logic has one home and rendering is pluggable. Every callback is a plain `Callable`; no view object is required to run the core.

**Record core** (new function `run_record_session` in `podscribe/cli.py`, next to `cmd_record`):

```python
def run_record_session(
    pod: Pod,
    meeting: Meeting,
    capture,                      # AudioCapture
    transcriber,                  # Transcriber
    *,
    glossary_prompt: Optional[str] = None,
    wav_writer=None,              # wave.Wave_write | None
    on_segment: Callable[[Segment], None] = lambda s: None,
    on_status: Callable[[dict], None] = lambda d: None,
    on_done: Callable[[int], None] = lambda n: None,   # segment_count
) -> None:
    """Drive capture.segments(), append_segment + finalize_meeting, fire callbacks.

    Writes the transcript header before the loop. Sets meeting.model/vad_enabled/duration_sec/ended_at.
    Calls finalize_meeting (keep_audio inferred from wav_writer is not None).
    """
```

`on_status` receives a dict like `{"elapsed": float, "segment_count": int, "vad_aggr": int, "level": float, "overflow": bool}`. The core owns `signal.signal(SIGINT, handle_sigint)` + `capture.stop()` + `try/finally` (wav_writer close, finalize). Disk behavior (`append_segment`, `finalize_meeting`, `.raw` deletion) is unchanged.

**Enhance core** (modify `llm.enhance_transcript`):

```python
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

    No tqdm. No show_progress flag (callbacks replace it). Retries unchanged
    (1/2/4s on connection errors + 5xx; 4xx fails immediately; 30-min timeout).
    on_stats fires once with {"prompt_eval_count","eval_count","total_duration_ns","eval_duration_ns"}.
    """
```

The `_ollama_model_info` call and the "Calling Model:…/Context window size" stderr preface move to the caller (the view prints them as a header); the core just streams.

### Thin wrappers

`cmd_record` / `cmd_enhance` / `cmd_consolidate` pass plain-text callbacks that reproduce today's output (so tests and piped usage stay byte-compatible where it matters):

- `cmd_record`'s `on_segment` → `print(f"[{_hms(s.start_sec)}] {s.text}")`; `on_status` → no-op (or stderr overflow warning only, matching current behavior); `on_done` → `print(f"Done. Saved {n} segments ...")`.
- `cmd_enhance` / `cmd_consolidate` call `enhance_transcript(..., on_token=lambda t: None, on_stats=lambda d: sys.stderr.write(<done line>))` — i.e. silent token stream, final metrics line to stderr, matching current post-stream output. (The fake tqdm line is simply gone.) Because the core no longer prints the "Calling Model:…/Context window size" preface, the **plain wrapper prints those two lines to stderr itself** before calling the core (preserving today's pre-stream output); `enhance_view` prints them as the top panel instead.

When invoked through the launcher, the same cores get rich-live callbacks instead.

### Entry point

`cli.main` runs argparse first so `--help`/`--version` continue to work and unknown subcommands still error. Only when argparse finds no subcommand **and** `sys.stdin.isatty() and sys.stderr.isatty()` does it call `from .tui import launch; launch()`. If stdin/stderr are not TTYs (CI, pipe, subprocess), print to stderr:

```
podscribe: a TTY is required for the interactive menu.
Run 'podscribe --help' for subcommands.
```

…and exit 2 (does not hang on a key read). Everything else (including `podscribe <pod> <cmd>` and aliases) is unchanged.

## Components (`tui.py`)

### Palette

Module-level 256-color constants (pastel pink/purple/peach from the mockup): `C_PEACH`, `C_PINK`, `C_LILAC`, `C_MINT`, `C_DIM`. Reused by all views. Bordered by `rich.box` style matching the mockup's `╭─╮`/`╰─╯`.

### `launch()`

1. Load project config (`podscribe.yaml`); read `last_pod` (new key; default `None`).
2. If no pods exist → print a friendly panel: "No pods yet. Run `podscribe init <name>`." and exit 0.
3. If `last_pod` unset or missing → pod-picker list (numbered) → set `last_pod`, save config.
4. Render the banner + action menu (from `.scratch/mockup-synthwave-pastel.txt`):
   ```
   [1] Record   [2] Enhance   [3] Consolidate   [4] Others   [q] Quit
   pod: <name> · model: <default> · ollama: ◉ online / ○ offline
   ```
   Ollama status probed via a 1s HEAD to `http://localhost:11434`.
5. `[4] Others` → secondary menu: `list / show / search / context / export / import / config / switch pod`. `switch pod` returns to step 3.
6. Key dispatch → `record_view` / `enhance_view` / `consolidate_screen` / etc. After each completes, return to the menu. `q` exits.
7. Save `last_pod` to `podscribe.yaml` on any switch.

### `record_view(pod, ...)`

`rich.live.Live(refresh_per_second=8)` with a `Layout`:
- **Top:** banner line + `Recording meeting <id>` + `Press Ctrl+C to stop.`
- **Body:** transcript panel — timestamped lines appended via `on_segment`. Cap displayed lines to the panel height (keep a tail buffer; full transcript is still on disk via `append_segment`).
- **Footer:** status line from `on_status`: `elapsed · segs=N · VAD=<aggr> · level=<bar> · ⚠ overflow` when set.
- `finally:` closes `Live` cleanly even on `KeyboardInterrupt`. Prints the same `Done. Saved N segments (...)` + `→ <transcript_path>` + overflow warning as today.

### `enhance_view(pod, meeting, llm_config, ...)`

`rich.live.Live` with a `Layout`:
- **Top:** `Enhancing <pod>/<date>/<id>` + `Using LLM: <model>` + `Ollama: http://localhost:11434` + `Context window: <num_ctx> tokens` (from `_ollama_model_info`).
- **Body:** **scrollable token-stream region** — tokens render as they arrive via `on_token`. Tail-buffered like the record panel.
- **Footer:** `elapsed · tokens=N · <tok/s> tok/s · retrying (attempt a)…` when `on_retry` fires.
- On `on_stats`: footer becomes `✓ done in <s>s · prompt <pe> + response <ec> tokens @ <tps> tok/s` (honest, no fake percentage).
- On core returning `None`: red error panel `Failed to reach Ollama. Is it running? Start with: ollama serve` (same text as today's `_run_enhance` error) → return to menu.
- On success: write `summaries/<date>/<id>.md` (unchanged path), print `Enhanced transcript saved to <path>`.

### `consolidate_screen(pod, meeting, llm_config, ...)`

The launcher's `[3] Consolidate` does **not** call the bare `cmd_consolidate` (which uses `input()` for the de-dup rewrite prompt — see `podscribe/cli.py:585`, which would be janky under the TUI). Instead, a dedicated `consolidate_screen`:

- Runs the consolidate flow in a `rich.console.Console.status("Consolidating…")` (no full `rich.live` — consolidate is short and one-shot, so a status spinner is the right level of feedback).
- For the de-dup rewrite prompt, uses `rich.prompt.Confirm.ask("Log entry exists for <id>. Rewrite?", default=False)` (matches today's default-`N` behavior). This keeps the prompt inside the TUI and avoids clobbering the menu with raw stdin.
- On success, writes the same `meetings.csv` row (unchanged path/format) and prints the same outcome messages.
- Returns to the launcher menu.

## Data flow

**Launcher:** `config.load_project_config()` → render menu → key → view → back to menu. `last_pod` persisted to `podscribe.yaml` on switch.

**Record:** `record_view` opens `Live` → builds `AudioCapture`/`Transcriber` (lazy imports stay) → calls `run_record_session(on_segment=update_panel, on_status=update_footer, on_done=close_message)` → core drives capture + disk + finalize → `Live` closes in `finally`.

**Enhance:** `enhance_view` opens `Live` → calls `enhance_transcript(model, prompt, on_token=append, on_stats=footer, on_retry=footer)` → core streams `resp.iter_lines`, accumulates text, fires callbacks → returns text or `None` → view writes file or shows error → `Live` closes.

## CLI interface changes

- **New:** bare `podscribe` → launcher. (Was: argparse error.)
- **Unchanged:** `podscribe <pod> <cmd>`, all aliases, all flags.
- **Behavior of `record`/`enhance` when invoked directly (not via launcher):** still interactive. To avoid two render paths, the direct invocation also uses the rich live view (it's the same screen). Piped/non-TTY → rich degrades to plain line output; callbacks still fire; output stays sensible for `| tee`. The pre-loop `print(...)` header lines are emitted as plain `print` before `Live` starts so they survive piping.
- **No new flags** in this spec.

## Error handling

- Ollama down / 4xx / 5xx → core returns `None`; view shows red error panel; returns to menu. `on_retry` surfaces retry state during the wait.
- Audio buffer overflow → `on_status(overflow=True)` → footer warning (matches current stderr message).
- Ctrl+C during record → existing `SIGINT` handler stops capture; `Live` closes in `finally`; finalize runs.
- Non-TTY / piped → rich auto-degrades; callbacks still fire; no crashes, no control-char soup.
- Bare `podscribe` without a TTY (CI, pipe) → guarded at entry; prints a TTY-required message and exits 2 instead of hanging on a key read.
- Launcher with no pods → friendly panel + exit 0 (no crash on missing `pods/`).
- Missing `last_pod` or stale entry → pod-picker.

## Testing

- **Cores are TTY-free and unit-testable** via capturing callbacks (append to lists). No rich, no Ollama, no mic.
- **Bug regression test** (`tests/test_llm.py`): `enhance_transcript` against a fake `iter_lines` (mock NDJSON chunks via `requests.post` mock) asserts:
  - `on_token` fires once per chunk with a `"response"` key, in order.
  - `on_stats` fires once on the `done` chunk with `eval_count` propagated.
  - Return value is `"".join(responses)`.
  - **No `tqdm` import remains in `llm.py`** (grep assertion in a test or simply assert `tqdm` not in `globals()`).
- **Record core test** (`tests/test_cli.py` or new `tests/test_record.py`): a fake capture yielding 3 segments → assert `on_segment` called 3×, `on_status` called ≥1× with `segment_count`, `append_segment` wrote the right lines to the transcript file, `finalize_meeting` wrote the JSON sidecar with correct `model`/`vad_enabled`/`duration_sec`, and `.raw` was deleted (no `wav_writer`). A second test with `wav_writer` → `.raw` survives.
- **Wrapper compatibility tests:** existing `cmd_enhance`/`cmd_consolidate` tests still pass (plain-text path). Update assertions that looked for the tqdm line to look for the metrics line only.
- **Cleanup-on-error test (rewrite, don't delete):** `tests/test_llm.py:254` ("tqdm bar must still be closed") currently patches `podscribe.llm.tqdm` and asserts the bar is closed on a mid-stream exception. Since tqdm is removed, **rewrite** this test against the callback interface to preserve its intent: when `iter_lines` raises mid-stream, `enhance_transcript` must (a) return cleanly (`None` on failure), (b) not re-raise, and (c) leave no callback/exception state in a bad shape — assert that a `try/finally` cleanup ran (e.g., a `closed` flag set in a mock callback or a recorded "done" event). The *intent* (no resource leak / clean teardown on error) is what must survive, not the tqdm-specific assertion.
- **TUI smoke tests** (`tests/test_tui.py`): `launch()` with ≥1 pod doesn't crash (monkeypatch `rich.live.Live`/key reader); `launch()` with no pods prints the no-pods panel and exits 0. Logic stays in cores — no rich rendering asserted in depth.
- **Docs test / update:** `docs/USER-MANUAL.md:162-176` is rewritten to match the real enhance view (live token stream + footer; no `68%` bar).

## Files to create/modify

| File | Change |
|---|---|
| `podscribe/tui.py` | **NEW.** `launch()`, `record_view`, `enhance_view`, `consolidate_screen`, palette, `readchar`-based key reader. Lazy-imported. |
| `podscribe/llm.py` | Remove `tqdm` import + bar; rewrite `enhance_transcript` with `on_token`/`on_stats`/`on_retry` callbacks; remove `show_progress` arg; move `_ollama_model_info` preface to caller. |
| `podscribe/cli.py` | Extract `run_record_session` from `cmd_record`; thin wrappers for `cmd_record`/`cmd_enhance`/`cmd_consolidate` pass plain-text callbacks; `main()` dispatches bare `podscribe` → `tui.launch()`. |
| `podscribe/config.py` | `load_last_pod()` / `save_last_pod()` reading/writing `last_pod` in `podscribe.yaml`. |
| `pyproject.toml` | Add `rich>=13.7`; remove `tqdm>=4.64`. |
| `requirements.txt` | Same dep changes. |
| `tests/test_llm.py` | Callback regression test; remove tqdm assertions. |
| `tests/test_cli.py` | `run_record_session` test; update `cmd_enhance`/`cmd_consolidate` assertions. |
| `tests/test_tui.py` | **NEW.** `launch()` smoke tests (with/without pods). |
| `docs/USER-MANUAL.md` | Rewrite the "Streaming output" section (lines ~160-176) to match the real enhance view. |
| `AGENTS.md` | Add `tui.py` to the tree + a line on the launcher; remove `tqdm` from deps list; note bare `podscribe` opens launcher. |
| `.scratch/diag_progressbar.py` | Keep as root-cause artifact (already gitignored via `.scratch/`). |

## Dependencies

- **Add:** `rich>=13.7` (pure Python; Apple Silicon fine); `readchar>=4.0` (small pure-Python single-key reader; no framework, no terminal-control boilerplate — chosen over stdlib `termios` for portability and over `input()`-with-Enter to match the mockup's single-key UX).
- **Remove:** `tqdm>=4.64` (only `llm.py` used it; gone after the rewrite).

## Open questions

None — all decisions made during brainstorming:

- Scope: hybrid (menu + live TUI for record/enhance). ✓
- Stack: `rich` + `rich.live`. ✓
- Enhance feedback: live token stream + status footer (no fake %). ✓
- Record feedback: live transcript + footer, Ctrl+C to stop. ✓
- Launcher: remembered pod + action menu; non-interactive path preserved. ✓
- Structure: headless cores + callback renderers. ✓

## Out of scope (future)

- `play <meeting-id>` for spot-checking kept audio (depends on `--keep-audio`).
- Keyboard controls during record (pause/stop/marker).
- Full textual/curses persistent app with many navigable views.
- Auto-enhance / auto-consolidate after record (in `roadmap.md`).
- Estimated-total `%` bar (labeled est.) — rejected in brainstorming in favor of live tokens.
