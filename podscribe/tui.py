"""Interactive terminal UI: launcher + live views. Lazy-imported."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import os
import readchar
import requests
import select
import sys
import termios
import threading
import tty
from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

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
C_RED   = "color(203)"

OLLAMA_URL = "http://localhost:11434"

# readchar key codes
KEY_UP    = "\x1b[A"
KEY_DOWN  = "\x1b[B"
KEY_ENTER = "\r"

WAVEFORM_WIDTH = 40  # number of RMS buckets shown in the waveform bar

_WAVE_CHARS = "▁▂▃▄▅▆▇█"

def _rms_to_bar_char(rms: float) -> str:
    idx = int(min(rms, 0.999) * len(_WAVE_CHARS))
    return _WAVE_CHARS[idx]


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

# ---------------------------------------------------------------------------
# Header and sidebar rendering
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Type badge colours (matches the amber/teal/green palette in mockup)
# ---------------------------------------------------------------------------
_TYPE_COLOURS: dict[str, str] = {
    "1on1":         "color(179)",   # amber
    "skip-level":   "color(179)",
    "interview":    "color(179)",
    "standup":      "color(73)",    # teal
    "retro":        "color(71)",    # green
    "planning":     "color(73)",
    "sprint-review":"color(73)",
    "all-hands":    "color(140)",   # purple
    "team-sync":    "color(73)",
    "design-review":"color(140)",
    "incident":     "color(203)",   # red
    "post-mortem":  "color(203)",
    "brainstorm":   "color(152)",   # mint
    "customer":     "color(215)",   # orange
    "vendor":       "color(215)",
    "cross-team":   "color(215)",
    "other":        "color(244)",
}

def _type_badge(mtype: Optional[str]) -> str:
    """Return a coloured [type] pill string, or a dim dash if no type."""
    if not mtype:
        return f"[{C_DIM}]{'–':14s}[/{C_DIM}]"
    col = _TYPE_COLOURS.get(mtype, C_PEACH)
    return f"[bold {col}][{mtype}][/bold {col}]"


def _key_pill(key: str, label: str) -> str:
    """Return a visually-boxed key hint: [key] label."""
    return f"[reverse {C_LILAC}] {key} [/reverse {C_LILAC}] [{C_DIM}]{label}[/{C_DIM}]"


def _dur_fmt(sec: Optional[float]) -> str:
    """Format duration as  42m  or  1h 12m — compact form for the dashboard."""
    if not sec:
        return ""
    s = int(sec)
    h, rem = divmod(s, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def render_header(pod: Pod, ollama_ok: bool) -> Text:
    """Full-width header: left = breadcrumb, right = ollama + key pills."""
    t = Text(overflow="ellipsis", no_wrap=True)
    # Left side
    t.append("podscribe", style=f"bold {C_PEACH}")
    t.append("  ·  ", style=C_DIM)
    t.append(pod.name, style=f"bold {C_PINK}")
    if pod.role:
        t.append("  ·  ", style=C_DIM)
        t.append(pod.role, style=C_DIM)
    # Right side — pad to fill terminal, then append right-aligned block
    right_parts = []
    if ollama_ok:
        right_parts.append(f"[{C_MINT}]● ollama online[/{C_MINT}]")
    else:
        right_parts.append(f"[{C_DIM}]○ ollama offline[/{C_DIM}]")
    right_parts += [
        f"  [reverse {C_DIM}] ? [/reverse {C_DIM}]",
        f"  [reverse {C_LILAC}] : [/reverse {C_LILAC}]",
        f"  [reverse {C_LILAC}] / [/reverse {C_LILAC}]",
    ]
    t.append("  " + "".join(right_parts))
    return t


def render_sidebar(state: AppState, pods: list) -> Panel:
    """Rich Panel containing the pod list for the sidebar."""
    lines = []
    for i, pod in enumerate(pods):
        if i == state.sidebar_idx:
            cursor = f"[{C_PINK}]▶[/{C_PINK}]"
            name   = f"[bold {C_PINK}]{pod.name}[/bold {C_PINK}]"
            role   = f"\n    [{C_DIM}]{pod.role}[/{C_DIM}]" if pod.role else ""
        else:
            cursor = "  "
            name   = f"[{C_DIM}]{pod.name}[/{C_DIM}]"
            role   = f"\n    [{C_DIM}]{pod.role}[/{C_DIM}]" if pod.role else ""
        lines.append(f" {cursor} {name}{role}")
    border = C_LILAC if state.focused_pane == "sidebar" else C_DIM
    return Panel("\n".join(lines) or " ", title=f"[{C_DIM}]PODS[/{C_DIM}]", border_style=border)


# ---------------------------------------------------------------------------
# Dashboard + status bar rendering
# ---------------------------------------------------------------------------

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
    """Main pane: stat cards + recent meetings table + key hint pills."""
    from datetime import datetime

    total = len(meetings)
    enhanced = sum(1 for m in meetings if _meeting_enhanced(pod, m))
    pct = f"{int(enhanced / total * 100)}% coverage" if total else "0% coverage"
    last_met_abs = "–"
    last_met_rel = ""
    if meetings:
        try:
            dt = datetime.fromisoformat(meetings[0].started_at)
            last_met_abs = dt.strftime("%Y-%m-%d")
            delta = datetime.now() - dt
            days = delta.days
            last_met_rel = f"{days}d ago" if days >= 1 else "today"
        except (ValueError, TypeError):
            pass

    from rich.console import Group

    # ── Stat cards ──────────────────────────────────────────────────────────
    cards = Table.grid(padding=(0, 2))
    cards.add_column(min_width=18)
    cards.add_column(min_width=18)
    cards.add_column(min_width=18)

    def _card(label: str, value: str, sub: str, col: str) -> Text:
        t = Text()
        t.append(f"{label}\n", style=C_DIM)
        t.append(f"{value}\n", style=f"bold {col}")
        t.append(sub, style=C_DIM)
        return t

    since = ""
    if meetings:
        try:
            dt0 = datetime.fromisoformat(meetings[-1].started_at)
            since = f"since {dt0.strftime('%b %Y')}"
        except (ValueError, TypeError):
            pass

    cards.add_row(
        _card("TOTAL MEETINGS", str(total), since, C_PEACH),
        _card("ENHANCED", str(enhanced), pct, C_MINT),
        _card("LAST MET", last_met_rel, last_met_abs, C_PEACH),
    )

    # ── Pod subtitle ────────────────────────────────────────────────────────
    subtitle = Text()
    subtitle.append(pod.display_name or pod.name, style=f"bold {C_PINK}")
    if pod.role or pod.cadence:
        parts = []
        if pod.role:
            parts.append(pod.role)
        if pod.cadence:
            parts.append(f"every {pod.cadence}")
        subtitle.append("  " + " · ".join(parts), style=C_DIM)

    # ── Recent meetings ──────────────────────────────────────────────────────
    tbl = Table.grid(padding=(0, 1))
    tbl.add_column(width=1)             # cursor
    tbl.add_column(width=16)            # date
    tbl.add_column(width=16)            # type badge
    tbl.add_column(width=5)             # duration
    tbl.add_column()                    # enh status (right-aligned via markup)

    for i, m in enumerate(meetings[:12]):
        cursor = Text("▶", style=C_PINK) if i == state.main_idx else Text(" ")
        try:
            dt = datetime.fromisoformat(m.started_at)
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            date_str = m.started_at or m.id
        badge = Text.from_markup(_type_badge(m.type))
        dur   = Text(_dur_fmt(m.duration_sec), style=C_DIM)
        if _meeting_enhanced(pod, m):
            enh_text = Text("✓ enhanced", style=C_MINT)
        else:
            enh_text = Text("→ raw", style=C_DIM)
        tbl.add_row(cursor, Text(date_str, style=C_DIM), badge, dur, enh_text)

    # ── Key hints ────────────────────────────────────────────────────────────
    hints_line1 = Text()
    for key, label in [("r","record"), ("e","enhance"), ("c","consolidate"),
                        ("Enter","view transcript"), ("/","search"), ("Tab","switch pane")]:
        hints_line1.append_text(Text.from_markup(_key_pill(key, label) + "  "))
    hints_line2 = Text.from_markup(_key_pill("q", "quit"))

    from rich.padding import Padding
    body = Group(
        subtitle, Text(""),
        cards, Text(""),
        Text("RECENT MEETINGS", style=C_DIM),
        Text("─" * 60, style=C_DIM),
        tbl, Text(""),
        hints_line1,
        hints_line2,
    )
    border = C_LILAC if state.focused_pane == "main" else C_DIM
    return Panel(body, title="[bold]Dashboard[/bold]", border_style=border)


def render_status_bar(state: "AppState", pod: Pod, meetings: Optional[list] = None,
                      llm_model: Optional[str] = None, llm_ctx: Optional[str] = None) -> Text:
    """Full-width bottom status bar: mode badge left, model/ctx right."""
    from datetime import datetime
    col = mode_colour(state.mode)
    t = Text(no_wrap=True, overflow="ellipsis")
    # Mode badge
    t.append(f" {state.mode} ", style=f"bold reverse {col}")
    t.append("  ")
    t.append(pod.name, style=f"bold {C_DIM}")

    # Meeting count + last met
    if meetings:
        t.append(f"  ·  {len(meetings)} meetings", style=C_DIM)
        try:
            dt = datetime.fromisoformat(meetings[0].started_at)
            delta = datetime.now() - dt
            days = delta.days
            ago = f"{days}d ago" if days >= 1 else "today"
            t.append(f"  ·  last {ago}", style=C_DIM)
        except (ValueError, TypeError):
            pass

    # Right side: model + ctx
    if llm_model:
        right = f"model [bold {C_PEACH}]{llm_model}[/bold {C_PEACH}]"
        if llm_ctx and llm_ctx != "?":
            right += f"  [{C_DIM}]ctx {llm_ctx}[/{C_DIM}]"
        t.append("  " + right)

    return t


# ---------------------------------------------------------------------------
# Fuzzy command palette
# ---------------------------------------------------------------------------

@dataclass
class FuzzyCandidate:
    kind: str   # "pod" | "cmd"
    label: str
    value: str  # pod name or command key

_PALETTE_COMMANDS = [
    FuzzyCandidate("cmd", "init",               "init"),
    FuzzyCandidate("cmd", "export",             "export"),
    FuzzyCandidate("cmd", "import",             "import"),
    FuzzyCandidate("cmd", "search",             "search"),
    FuzzyCandidate("cmd", "config-llm",         "config-llm"),
    FuzzyCandidate("cmd", "config-consolidate", "config-consolidate"),
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


# ---------------------------------------------------------------------------
# Key reading + Ollama probe
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Generic interactive menu (arrow keys + number keys)
# ---------------------------------------------------------------------------

def _select_menu(
    console: Console,
    title: str,
    items: list[tuple[str, str]],
    *,
    quit_label: str = "Back",
) -> Optional[str]:
    """Interactive menu with arrow-key + number-key navigation.

    items: list of (value, label) pairs. The value is returned on selection.
    Returns the selected value, or None for quit (q / Ctrl+C).

    Navigation:
      ↑/↓     — move selection
      Enter   — select highlighted item
      1-9     — jump to item by number
      q/Ctrl+C — quit
    """
    if not items:
        return None

    entries = list(items) + [(None, quit_label)]
    selected = 0

    def _render() -> Panel:
        lines = []
        for i, (val, label) in enumerate(entries):
            if val is None:
                cursor = f"[{C_DIM}]  [/{C_DIM}]"
                text = f"[{C_DIM}]{label}[/{C_DIM}]"
            elif i == selected:
                cursor = f"[{C_PINK}]\u25b6[/{C_PINK}]"
                text = f"[{C_PINK}]{label}[/{C_PINK}]"
            else:
                cursor = "  "
                text = label
            num = f"[{C_LILAC}]{i + 1 if i < len(items) else 'q'}[/{C_LILAC}]" if i < 9 else " "
            lines.append(f"  {cursor} {num}  {text}")
        return Panel("\n".join(lines), title=title, border_style=C_LILAC)

    with Live(_render(), console=console, refresh_per_second=30) as live:
        while True:
            k = read_key()
            if k == KEY_UP:
                selected = (selected - 1) % len(entries)
                live.update(_render())
            elif k == KEY_DOWN:
                selected = (selected + 1) % len(entries)
                live.update(_render())
            elif k in (KEY_ENTER, "\n"):
                return entries[selected][0]
            elif k.isdigit():
                idx = int(k) - 1
                if 0 <= idx < len(entries):
                    return entries[idx][0]
            elif k in ("q", "\x03"):
                return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _list_pod_names() -> list[str]:
    pods_dir = Path("pods")
    if not pods_dir.exists():
        return []
    return sorted(
        p.name for p in pods_dir.iterdir()
        if p.is_dir() and (p / "config.yaml").exists()
    )


def _resolve_pod(name_hint: Optional[str]) -> Optional[Pod]:
    """Return a Pod for the given name, or None if it doesn't exist."""
    if not name_hint:
        return None
    if not pod_exists(name_hint):
        return None
    return load_pod(name_hint)


def _pick_pod(console: Console) -> Optional[Pod]:
    """Show an interactive pod picker. Returns the selected Pod, or None."""
    names = _list_pod_names()
    if not names:
        return None
    items = [(n, n) for n in names]
    choice = _select_menu(console, "Choose a pod", items, quit_label="Cancel")
    if choice is None:
        return None
    return _resolve_pod(choice)


def _fmt_meeting_label(meeting) -> str:
    """Format a meeting as a one-line label for the picker."""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(meeting.started_at)
        date_part = dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        date_part = meeting.started_at or meeting.id

    extras = []
    if meeting.type:
        extras.append(meeting.type)
    if meeting.duration_sec:
        from .cli import _hms
        extras.append(_hms(meeting.duration_sec))
    if extras:
        return f"{date_part}  \u00b7  {'  \u00b7  '.join(extras)}"
    return date_part


def _pick_meeting(console: Console, pod: Pod) -> Optional[object]:
    """Show an interactive meeting picker. Returns the selected Meeting, or None."""
    meetings = list_meetings(pod)
    if not meetings:
        console.print(f"[red]No meetings for pod '{pod.name}'.[/red]")
        return None
    items = [(m.id, _fmt_meeting_label(m)) for m in meetings]
    choice = _select_menu(console, f"Meetings for {pod.name}", items, quit_label="Cancel")
    if choice is None:
        return None
    match = [m for m in meetings if m.id == choice]
    return match[0] if match else None


# ---------------------------------------------------------------------------
# CLI dispatch helper
# ---------------------------------------------------------------------------

def _dispatch_cli(argv: list[str]) -> int:
    """Run a one-shot command by re-invoking main() with the given argv."""
    from .cli import main
    return main(argv)


def _pause(console: Console) -> None:
    """Print 'press any key' and wait."""
    console.print(f"\n[{C_DIM}]Press any key to continue...[/{C_DIM}]")
    read_key()


def _set_input_raw(fd: int) -> list:
    """Put only input processing in raw mode; preserve output flags.

    Clears ICANON (line buffering) and ECHO so each keypress is delivered
    immediately without echoing.  Intentionally preserves ISIG so that
    Ctrl+C still generates SIGINT — the run_record_session SIGINT handler
    depends on this.

    Returns the previous termios attributes for restore.
    """
    old = termios.tcgetattr(fd)
    mode = termios.tcgetattr(fd)
    mode[0] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK | termios.ISTRIP | termios.IXON)
    mode[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN)
    mode[6][termios.VMIN] = 1
    mode[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSADRAIN, mode)
    return old


def _listen_for_stop(
    capture,
    wake_fd: int,
    stop_event: threading.Event,
) -> None:
    """Thread target: read stdin for 's' to stop recording.
    Sets stdin to cbreak mode (no line buffering, no echo) for the lifetime
    of the thread.  ISIG is intentionally preserved so Ctrl+C still delivers
    SIGINT to run_record_session's signal handler.
    Watches *wake_fd* (read-end of a pipe) so the main thread can
    unblock select() and cause a clean exit.
    """
    try:
        fd = sys.stdin.fileno()
    except (OSError, AttributeError):
        return
    old_term = None
    try:
        try:
            old_term = _set_input_raw(fd)
        except termios.error:
            # stdin is not a real tty (redirected, piped) — fall back to
            # raw select only; terminal is already in whatever mode it is.
            pass
        while not stop_event.is_set():
            try:
                r, _, _ = select.select([fd, wake_fd], [], [], 1.0)
            except (ValueError, OSError):
                return
            if wake_fd in r:
                return
            if fd in r:
                ch = os.read(fd, 1).decode("utf-8", errors="replace")
                if ch in ("s", "S"):
                    capture.stop()
                    return
    finally:
        if old_term is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_term)
            except (ValueError, OSError, termios.error):
                pass


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
    from .config import get_effective_glossary
    from .glossary import format_glossary_prompt

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

    effective_glossary = get_effective_glossary(pod)
    glossary_prompt = format_glossary_prompt(effective_glossary) if effective_glossary else None

    BUFFER_LINES = 200
    lines: list[str] = [
        f"[{C_PINK}]Recording meeting {meeting.id}[/{C_PINK}]",
        "  \u2018s\u2019 to stop  \u00b7  Ctrl+C fallback",
    ]
    console = Console()

    waveform: list = [0.0] * WAVEFORM_WIDTH

    def _on_level(rms: float) -> None:
        waveform.append(rms)
        if len(waveform) > WAVEFORM_WIDTH:
            del waveform[: len(waveform) - WAVEFORM_WIDTH]

    transcriber = Transcriber(model=getattr(args, "model", "large-v3-turbo"))
    capture = AudioCapture(
        vad_aggressiveness=getattr(args, "vad_aggressiveness", 2),
        device=getattr(args, "device", None),
        on_level=_on_level,
    )
    keep_audio = bool(getattr(args, "keep_audio", True))
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

    status: dict = {"elapsed": 0, "segment_count": 0, "vad_aggr": capture.vad_aggressiveness, "overflow": False}
    status_line = {"text": ""}

    def _on_segment(seg) -> None:
        from .cli import _hms
        lines.append(f"[{_hms(seg.start_sec)}] {seg.text}")
        if len(lines) > BUFFER_LINES:
            del lines[: len(lines) - BUFFER_LINES]

    def _on_status(d: dict) -> None:
        status.update(d)

    def _on_done(n: int) -> None:
        from .cli import _hms
        status_line["text"] = f"Done. Saved {n} segments ({_hms(meeting.duration_sec or 0)})"

    def _render():
        from rich.console import Group as RGroup
        from rich.rule import Rule

        elapsed_sec = int(status.get("elapsed", 0))
        h, rem = divmod(elapsed_sec, 3600)
        m_, s = divmod(rem, 60)
        elapsed_str = f"{h:02d}:{m_:02d}:{s:02d}"
        segs = status.get("segment_count", 0)
        vad  = status.get("vad_aggr", "?")
        model_name = getattr(transcriber, "model_name", "?")

        # Top header bar
        hdr = Text(no_wrap=True, overflow="ellipsis")
        hdr.append(" ● REC ", style=f"bold reverse {C_RED}")
        hdr.append("  ")
        hdr.append(f"{meeting.id}", style=f"bold {C_PINK}")
        if meeting.type:
            hdr.append(f"  ·  {meeting.type}", style=C_DIM)
        hdr.append(
            f"    elapsed [bold {C_PEACH}]{elapsed_str}[/bold {C_PEACH}]"
            f"  segs [{C_PEACH}]{segs}[/{C_PEACH}]"
            f"  VAD [{C_DIM}]{vad}[/{C_DIM}]"
            f"  model [{C_DIM}]{model_name}[/{C_DIM}]"
        )

        # Transcript body
        body_text = Text(overflow="fold")
        for line in lines[-BUFFER_LINES:]:
            body_text.append_text(Text.from_markup(line + "\n"))

        # Waveform + ctrl-c hint
        wave_str = "".join(_rms_to_bar_char(v) for v in waveform[-WAVEFORM_WIDTH:])
        wave_line = Text()
        wave_line.append(wave_str, style=C_PINK)
        wave_line.append("  \u2018s\u2019 stop  \u00b7  Ctrl+C", style=C_DIM)

        # Bottom status bar
        overflow_ok = not status.get("overflow", False)
        status_bar = Text(no_wrap=True, overflow="ellipsis")
        status_bar.append(" INSERT ", style=f"bold reverse {C_PINK}")
        status_bar.append("  recording", style=f"bold {C_DIM}")
        status_bar.append(f"  ·  {segs} segments captured", style=C_DIM)
        status_bar.append(
            f"  ·  overflow {'ok' if overflow_ok else 'WARN'}",
            style=C_DIM if overflow_ok else f"bold {C_RED}",
        )
        status_bar.append(f"    {model_name}", style=C_DIM)

        if status_line["text"]:
            done = Text(status_line["text"], style=C_MINT)
            return RGroup(hdr, Rule(style=C_DIM), body_text, wave_line, Rule(style=C_DIM), done, status_bar)
        return RGroup(hdr, Rule(style=C_DIM), body_text, wave_line, Rule(style=C_DIM), status_bar)

    # Start background key listener (daemon thread) so 's' stops recording
    r_fd, w_fd = os.pipe()
    _stop_ev = threading.Event()
    _listener = threading.Thread(
        target=_listen_for_stop,
        args=(capture, r_fd, _stop_ev),
        daemon=True,
    )
    _listener.start()

    rc = 0
    try:
        with Live(_render(), console=console, refresh_per_second=8, screen=True) as live:
            def _on_status_live(d: dict) -> None:
                _on_status(d)
                live.update(_render())

            try:
                run_record_session(
                    pod, meeting, capture, transcriber,
                    glossary_prompt=glossary_prompt, wav_writer=wav_writer,
                    on_segment=_on_segment,
                    on_status=_on_status_live,
                    on_done=_on_done,
                )
            except KeyboardInterrupt:
                rc = 130
            live.update(_render())
    finally:
        _stop_ev.set()
        try:
            os.write(w_fd, b"\x00")
        except OSError:
            pass
        try:
            os.close(w_fd)
        except OSError:
            pass
        try:
            os.close(r_fd)
        except OSError:
            pass
        _listener.join(timeout=2.0)
    console.print(f"  [dim]\u2192 {meeting.transcript_path}[/dim]")
    return rc


def enhance_view(pod: Pod, meeting) -> int:
    """rich.live view for enhance. Streams tokens via on_token."""
    from datetime import datetime
    from .config import get_effective_glossary, load_preserve_speakers

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
    footer = {"tokens": 0, "tps": 0.0, "status": "streaming"}

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
        footer["status"] = (
            f"done prompt {stats.get('prompt_eval_count', 0)} + response {ec} "
            f"@ {footer['tps']:.1f} tok/s"
        )

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
        if rc == 130:
            return 130
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
    status = console.status("[bold cyan]Consolidating...")

    def _prompt() -> bool:
        status.stop()
        return Confirm.ask(
            f"Log entry exists for {meeting.id}. Rewrite?", default=False
        )

    status.start()
    try:
        rc = run_consolidate(pod, meeting, prompt_rewrite=_prompt)
    finally:
        status.stop()
    return rc


# ---------------------------------------------------------------------------
# Launcher
# ---------------------------------------------------------------------------

def launch() -> int:
    """Top-level TUI entry: two-pane modal layout with j/k navigation."""
    from argparse import Namespace
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

    with Live(console=console, refresh_per_second=12, screen=True) as live:
        def _refresh():
            from rich.console import Group
            from rich.rule import Rule
            pod      = _current_pod()
            meetings = _current_meetings()
            llm_cfg  = pod.llm or load_project_config().get("llm") or {}
            llm_model = llm_cfg.get("model")
            llm_ctx: Optional[str] = None
            if llm_model:
                try:
                    info = ollama_model_info(llm_model)
                    llm_ctx = str((info.get("model_info") or {}).get("llama.context_length", "?"))
                except Exception:
                    llm_ctx = "?"
            header    = render_header(pod, ollama_ok)
            status    = render_status_bar(state, pod, meetings=meetings,
                                          llm_model=llm_model, llm_ctx=llm_ctx)
            sidebar_panel = render_sidebar(state, pods)
            main_panel    = render_dashboard(pod, meetings, state)
            cols = Columns([sidebar_panel, main_panel], equal=False, expand=True)
            screen_label = Text(
                f"SCREEN 1  —  {state.mode} MODE  ·  DASHBOARD VIEW",
                style=C_DIM, justify="center",
            )
            live.update(Group(header, Rule(style=C_DIM), cols, Rule(style=C_DIM), status, screen_label))

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
                    vad_aggressiveness=2, device=None, keep_audio=True,
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


def god_view(model: Optional[str] = None) -> int:
    """Two-pane God mode TUI: left = agent chat, right = tool ref / live transcript."""
    from .agent import GodSession, _format_tool_result
    from . import agent_tools
    import json

    console = Console()

    try:
        session = GodSession(model=model)
    except Exception as e:
        console.print(f"[red]Failed to initialize God session: {e}[/red]")
        return 1

    # Quick Ollama check
    if not probe_ollama():
        console.print(Panel(
            "Ollama not reachable. Start with: ollama serve",
            title="[red]Error[/red]", border_style="red",
        ))
        return 1

    input_buffer: list = []
    messages: list = []
    recording_active = False

    def _idle_reference() -> list:
        return [
            "[bold color(183)]Slash Commands[/bold color(183)]",
            "[color(244)]/record <pod> [--type][/color(244)]",
            "[color(244)]/stop[/color(244)]",
            "[color(244)]/enhance <pod> [meeting][/color(244)]",
            "[color(244)]/consolidate <pod> [meeting][/color(244)]",
            "[color(244)]/list [pod][/color(244)]",
            "[color(244)]/show <pod> <meeting>[/color(244)]",
            "[color(244)]/search <query>[/color(244)]",
            "[color(244)]/init <name>[/color(244)]",
            "[color(244)]/export[/color(244)]",
            "[color(244)]/help  /exit[/color(244)]",
            "",
            "[bold color(183)]Tips[/bold color(183)]",
            "[color(244)]Type naturally — the agent will call tools[/color(244)]",
            "[color(244)]Type 'stop' or '/stop' to end recording[/color(244)]",
            "[color(244)]'s' alone on a line stops recording too[/color(244)]",
        ]

    right_content: list = _idle_reference()

    def _render():
        left_lines = list(messages)
        if input_buffer:
            left_lines.append(f"\n[bold color(211)]You:[/bold color(211)] {''.join(input_buffer)}")
        elif recording_active:
            left_lines.append(f"\n[color(203)]\u25cf Recording active — type 'stop' when done[/color(203)]")

        left_body = "\n".join(left_lines) if left_lines else "[color(244)]Ask me something...[/color(244)]"
        left_panel = Panel(left_body, title="[bold]God Mode[/bold]", border_style=C_LILAC)

        right_body = "\n".join(right_content)
        right_panel = Panel(right_body, title="[bold]Tools[/bold]", border_style=C_DIM)

        from datetime import datetime
        status = Text(no_wrap=True, overflow="ellipsis")
        status.append(f" {session.model} ", style=f"bold reverse {C_DIM}")
        status.append(f"  {datetime.now().strftime('%H:%M:%S')}", style=C_DIM)

        return Group(
            Text("podscribe god mode", style=f"bold {C_PEACH}"),
            Rule(style=C_DIM),
            Columns([left_panel, right_panel], equal=False, expand=True),
            Rule(style=C_DIM),
            status,
        )

    def _on_token(t: str) -> None:
        nonlocal messages
        if messages and messages[-1].startswith(f"[{C_PEACH}]\u25cf"):
            messages[-1] += t
        else:
            messages.append(f"[{C_PEACH}]\u25cf[/{C_PEACH}] {t}")

    def _on_tool_call(name: str, args_str: str) -> None:
        messages.append(f"[{C_LILAC}]\u25c7[/{C_LILAC}] {name}({args_str})")

    def _on_result(text: str) -> None:
        preview = text[:300] + "..." if len(text) > 300 else text
        messages.append(f"[{C_DIM}]Result:[/{C_DIM}] {preview}")

    def _reset_input() -> str:
        nonlocal input_buffer
        text = "".join(input_buffer).strip()
        input_buffer = []
        return text

    def _handle_slash(command: str) -> None:
        nonlocal recording_active, right_content
        parts = command.split()
        if not parts:
            return
        cmd = parts[0]
        args = parts[1:]

        messages.append(f"[{C_LILAC}]\u25c7 /{command}[/{C_LILAC}]")

        try:
            if cmd == "help":
                right_content = _idle_reference()
                messages.append("[color(244)]Reference shown in right pane.[/color(244)]")
            elif cmd == "exit":
                raise KeyboardInterrupt()
            elif cmd == "stop":
                result = agent_tools.stop_recording()
                if "error" in result:
                    messages.append(f"[red]Error: {result['error']}[/red]")
                else:
                    msg = f"{result.get('meeting_id', '')} finalized ({result.get('segments', 0)} segments, {result.get('duration_sec', 0)}s)"
                    messages.append(f"[{C_DIM}]Result:[/{C_DIM}] {msg}")
                recording_active = False
                right_content = _idle_reference()
            elif cmd == "record":
                pod = args[0] if args else ""
                mt = None
                if "--type" in args:
                    idx = args.index("--type")
                    if idx + 1 < len(args):
                        mt = args[idx + 1]
                result = agent_tools.start_recording(pod, meeting_type=mt)
                if "error" in result:
                    messages.append(f"[red]Error: {result['error']}[/red]")
                else:
                    messages.append(f"[{C_DIM}]Result:[/{C_DIM}] {result.get('meeting_id', '')} recording")
                    recording_active = True
                    right_content = [f"[color(203)]\u25cf Recording {result.get('meeting_id', '')}[/color(203)]"]
            elif cmd == "list":
                if args:
                    result = agent_tools.list_meetings_tool(args[0])
                else:
                    result = agent_tools.list_pods()
                messages.append(f"[{C_DIM}]Result:[/{C_DIM}] {json.dumps(result, indent=2)}")
            elif cmd == "show":
                if len(args) >= 2:
                    result = agent_tools.show_meeting(args[0], args[1])
                else:
                    result = "Usage: /show <pod> <meeting>"
                messages.append(f"[{C_DIM}]Result:[/{C_DIM}] {agent_tools._truncate(result)}")
            elif cmd == "enhance":
                pod = args[0] if args else ""
                mid = args[1] if len(args) > 1 else "latest"
                result = agent_tools.enhance_meeting(pod, mid)
                messages.append(f"[{C_DIM}]Result:[/{C_DIM}] {result}")
            elif cmd == "consolidate":
                pod = args[0] if args else ""
                mid = args[1] if len(args) > 1 else "latest"
                nl = "--no-log" in args or "-n" in args
                result = agent_tools.consolidate_meeting(pod, mid, no_log=nl)
                messages.append(f"[{C_DIM}]Result:[/{C_DIM}] {json.dumps(result, indent=2)}")
            elif cmd == "search":
                query = " ".join(args) if args else ""
                if query:
                    result = agent_tools.search_transcripts(query)
                    messages.append(f"[{C_DIM}]Result:[/{C_DIM}] {json.dumps(result[:5], indent=2)}")
                else:
                    messages.append("[color(244)]Usage: /search <query>[/color(244)]")
            elif cmd == "init":
                if args:
                    result = agent_tools.init_pod_tool(args[0])
                    messages.append(f"[{C_DIM}]Result:[/{C_DIM}] {json.dumps(result, indent=2)}")
                else:
                    messages.append("[color(244)]Usage: /init <name>[/color(244)]")
            elif cmd == "export":
                result = agent_tools.export_data()
                messages.append(f"[{C_DIM}]Result:[/{C_DIM}] Exported to {result}")
            else:
                messages.append(f"[red]Unknown command: /{cmd}[/red]")
        except Exception as e:
            messages.append(f"[red]Error: {e}[/red]")

        # Inject into agent context
        last_msg = messages[-1] if messages else ""
        session.add_system_context(f"/{command} executed \u2192 {last_msg}")

    def _send_to_agent(text: str) -> None:
        messages.append(f"[bold color(211)]You:[/bold color(211)] {text}")
        session.run_prompt(
            text,
            on_token=_on_token,
            on_tool_call=_on_tool_call,
            on_result=_on_result,
        )

    with Live(_render(), console=console, refresh_per_second=8, screen=True) as live:
        while True:
            try:
                k = read_key()
            except KeyboardInterrupt:
                break

            if k in ("\r", "\n"):
                text = _reset_input()
                if not text:
                    continue

                if recording_active and text == "s":
                    result = agent_tools.stop_recording()
                    messages.append(f"[{C_LILAC}]\u25c7 stop_recording()[/{C_LILAC}]")
                    msg = f"finalized ({result.get('segments', 0)} segments, {result.get('duration_sec', 0)}s)"
                    messages.append(f"[{C_DIM}]Result:[/{C_DIM}] {msg}")
                    recording_active = False
                    right_content = _idle_reference()
                    session.add_system_context(f"/stop executed \u2192 meeting {result.get('meeting_id', '')} finalized")
                elif text.startswith("/"):
                    _handle_slash(text[1:])
                else:
                    _send_to_agent(text)

                live.update(_render())
            elif k == "\x7f":
                if input_buffer:
                    input_buffer.pop()
                live.update(_render())
            elif k == "\x03":
                break
            elif k.isprintable() or k in (" ",):
                input_buffer.append(k)
                live.update(_render())

            # Poll recording status for right pane updates
            if recording_active:
                status = agent_tools.get_recording_status()
                if status.get("status") == "recording":
                    latest = status.get("latest_lines", [])
                    right_content = [
                        f"[color(203)]\u25cf Recording {status['meeting_id']}[/color(203)]",
                        f"  segments: {status['segment_count']}",
                    ] + [f"[color(244)]{l}[/color(244)]" for l in latest[-10:]] + [
                        "",
                        "[color(244)]Type 'stop' or '/stop' to end[/color(244)]",
                    ]
                    live.update(_render())

    console.print()
    return 0
