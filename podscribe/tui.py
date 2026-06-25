"""Interactive terminal UI: launcher + live views. Lazy-imported."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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
    """Main pane default view: pod stats + recent meetings list."""
    from datetime import datetime

    # Stats
    total = len(meetings)
    enhanced = sum(1 for m in meetings if _meeting_enhanced(pod, m))
    pct = f"{int(enhanced / total * 100)}%" if total else "–"
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
# Banner + menus
# ---------------------------------------------------------------------------

def _render_banner(console: Console, pod: Pod, ollama_ok: bool) -> None:
    ollama = (
        f"[{C_MINT}]\u25c9 online[/{C_MINT}]"
        if ollama_ok
        else f"[{C_DIM}]\u25cb offline[/{C_DIM}]"
    )
    console.print(Panel(
        f"[{C_PEACH}]podscribe[/{C_PEACH}]  "
        f"[{C_DIM}]\u00b7[/{C_DIM}]  pod: [{C_PINK}]{pod.name}[/{C_PINK}]  "
        f"[{C_DIM}]\u00b7[/{C_DIM}]  ollama: {ollama}",
        border_style=C_LILAC,
    ))


def _action_menu(console: Console) -> str:
    """Main action menu. Returns the chosen key ('1'-'4' or 'q')."""
    items = [
        ("1", "Record"),
        ("2", "Enhance"),
        ("3", "Consolidate"),
        ("4", "Others"),
    ]
    choice = _select_menu(console, "Action", items, quit_label="Quit")
    return choice if choice is not None else "q"


def _others_menu(console: Console) -> str:
    """Others submenu. Returns the chosen key, or 'q' for back."""
    items = [
        ("list", "List all meetings"),
        ("show", "Show latest transcript"),
        ("search", "Search transcripts"),
        ("glossary", "Glossary management"),
        ("export", "Export data"),
        ("llm", "LLM config"),
        ("consolidate-cfg", "Consolidate prompt"),
        ("switch", "Switch pod"),
    ]
    choice = _select_menu(console, "Others", items, quit_label="Back")
    return choice if choice is not None else "q"


def _glossary_menu(console: Console) -> str:
    """Glossary submenu. Returns the chosen key, or 'q' for back."""
    items = [
        ("list", "List glossary terms"),
        ("add", "Add term"),
        ("remove", "Remove term"),
    ]
    choice = _select_menu(console, "Glossary", items, quit_label="Back")
    return choice if choice is not None else "q"


def _llm_config_menu(console: Console) -> str:
    """LLM config submenu. Returns the chosen key, or 'q' for back."""
    items = [
        ("show", "Show current config"),
        ("set", "Set model + template"),
    ]
    choice = _select_menu(console, "LLM Config", items, quit_label="Back")
    return choice if choice is not None else "q"


def _consolidate_cfg_menu(console: Console) -> str:
    """Consolidate prompt submenu. Returns the chosen key, or 'q' for back."""
    items = [
        ("show", "Show current prompt"),
        ("set", "Set prompt"),
    ]
    choice = _select_menu(console, "Consolidate Prompt", items, quit_label="Back")
    return choice if choice is not None else "q"


# ---------------------------------------------------------------------------
# Others submenu handlers
# ---------------------------------------------------------------------------

def _dispatch_cli(argv: list[str]) -> int:
    """Run a one-shot command by re-invoking main() with the given argv."""
    from .cli import main
    return main(argv)


def _pause(console: Console) -> None:
    """Print 'press any key' and wait."""
    console.print(f"\n[{C_DIM}]Press any key to continue...[/{C_DIM}]")
    read_key()


def _others_glossary(console: Console, pod: Pod) -> None:
    """Glossary management submenu."""
    while True:
        sub = _glossary_menu(console)
        if sub == "q":
            return
        if sub == "list":
            _dispatch_cli(["context", pod.name, "list"])
            _pause(console)
        elif sub == "add":
            term = Prompt.ask("Term to add", console=console)
            if not term.strip():
                continue
            category = Prompt.ask(
                "Category (person/project/client/other)",
                console=console, default="other",
            )
            _dispatch_cli(["context", pod.name, "add", term, "--category", category])
            _pause(console)
        elif sub == "remove":
            term = Prompt.ask("Term to remove", console=console)
            if not term.strip():
                continue
            _dispatch_cli(["context", pod.name, "remove", term])
            _pause(console)


def _others_llm_config(console: Console) -> None:
    """LLM config submenu."""
    while True:
        sub = _llm_config_menu(console)
        if sub == "q":
            return
        if sub == "show":
            _dispatch_cli(["config", "llm", "show"])
            _pause(console)
        elif sub == "set":
            model = Prompt.ask("Model name (e.g. qwen3.6:27b)", console=console)
            if not model.strip():
                continue
            template = Prompt.ask(
                "Prompt template (use {{transcript}} placeholder)",
                console=console,
            )
            if not template.strip():
                continue
            _dispatch_cli(["config", "llm", "set", model, template])
            _pause(console)


def _others_consolidate_cfg(console: Console) -> None:
    """Consolidate prompt submenu."""
    while True:
        sub = _consolidate_cfg_menu(console)
        if sub == "q":
            return
        if sub == "show":
            _dispatch_cli(["config", "consolidate", "show"])
            _pause(console)
        elif sub == "set":
            prompt = Prompt.ask(
                "Consolidate prompt (use {{summary}} placeholder)",
                console=console,
            )
            if not prompt.strip():
                continue
            _dispatch_cli(["config", "consolidate", "set", prompt])
            _pause(console)


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
        "  Ctrl+C to stop.",
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
            border_style=C_PINK,
        )

    rc = 0
    with Live(_render(), console=console, refresh_per_second=8) as live:
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
