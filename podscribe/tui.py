"""Interactive terminal UI: launcher + live views. Lazy-imported."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import readchar
import requests
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm

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
# Palette (256-color; matches .scratch/mockup-synthwave-pastel.txt)
# ---------------------------------------------------------------------------
C_PEACH = "color(223)"
C_PINK = "color(211)"
C_LILAC = "color(183)"
C_MINT = "color(152)"
C_DIM = "color(244)"

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
    """Show a numbered list and prompt the user to pick a pod."""
    names = _list_pod_names()
    if not names:
        return None
    console.print(Panel(
        "\n".join(f"  [{C_LILAC}][{i+1}][/{C_LILAC}] {n}" for i, n in enumerate(names)),
        title=f"[{C_PINK}]Choose a pod[/{C_PINK}]",
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


def _others_menu(console: Console) -> Optional[list[str]]:
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
        mapping = {
            "1": "list", "2": "show", "3": "search",
            "4": "context", "5": "export", "6": "config",
        }
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
    lines: list[str] = [
        f"[{C_PINK}]Recording meeting {meeting.id}[/{C_PINK}]",
        "  Ctrl+C to stop.",
    ]
    console = Console()

    # Latest status dict populated by on_status; consumed by _render.
    status: dict = {"elapsed": 0, "segment_count": 0, "vad_aggr": 1, "overflow": False}
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
        h, m = divmod(m, 60)
        footer = (
            f"elapsed {h:02d}:{m:02d}:{s:02d}  "
            f"segs={status.get('segment_count', 0)}  "
            f"VAD={status.get('vad_aggr', '?')}  "
            f"overflow={'WARN' if status.get('overflow') else 'ok'}"
        )
        body = "\n".join(lines[-BUFFER_LINES:])
        return Panel(
            body + "\n\n" + footer + "\n" + status_line["text"],
            title=f"[{C_PEACH}]record[/{C_PEACH}]",
            border_style=C_LILAC,
        )

    rc = 0
    with Live(_render(), console=console, refresh_per_second=8) as live:
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

    def _prompt() -> bool:
        return Confirm.ask(
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
    from argparse import Namespace

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
            args = Namespace(
                type=None, model="large-v3-turbo",
                vad_aggressiveness=2, device=None, keep_audio=False,
            )
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
            _dispatch_cli(sub)
