"""CLI entry point for podscribe."""
from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .glossary import add_entry, format_glossary_prompt, remove_entry
from .llm import build_enhance_prompt, enhance_transcript
from .models import Segment
from .storage import (
    append_segment,
    finalize_meeting,
    init_pod,
    list_meetings,
    load_pod,
    pod_exists,
    read_transcript,
    save_pod_config,
    start_meeting,
)


def _hms(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def cmd_init(args) -> int:
    """Initialize a new pod."""
    if pod_exists(args.name):
        print(f"Pod '{args.name}' already exists at pods/{args.name}/", file=sys.stderr)
        return 1
    pod = init_pod(
        args.name,
        display_name=args.display_name or "",
        role=args.role or "",
        cadence=args.cadence or "weekly",
        notes=args.notes or "",
    )
    print(f"Created pod '{pod.name}' at {pod.base_path}/")
    print(f"  config:      {pod.config_path}")
    print(f"  transcripts: {pod.transcripts_dir}/")
    print(f"  prep:        {pod.prep_dir}/")
    return 0


def cmd_record(args) -> int:
    """Live record + transcribe a meeting."""
    # Lazy imports: audio + transcriber libs are heavy
    from .audio import AudioCapture
    from .transcriber import Transcriber

    if not pod_exists(args.pod):
        print(f"No pod '{args.pod}'. Run `podscribe init {args.pod}` first.", file=sys.stderr)
        return 1

    pod = load_pod(args.pod)
    glossary_prompt = format_glossary_prompt(pod.glossary) if pod.glossary else None
    meeting = start_meeting(pod)
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
                print(f"[{_hms(seg.start_sec)}] {seg.text}")
                segment_count += 1
    finally:
        capture.stop()
        meeting.duration_sec = int(time.monotonic() - start_monotonic)
        meeting.ended_at = datetime.now().isoformat(timespec="seconds")
        finalize_meeting(meeting, keep_audio=args.keep_audio)

    print()
    print(f"Done. Saved {segment_count} segments ({_hms(meeting.duration_sec or 0)})")
    print(f"  → {meeting.transcript_path}")
    if capture.had_overflow:
        print("  ⚠ audio buffer overflowed — some audio may have been dropped.", file=sys.stderr)
    return 0


def cmd_list(args) -> int:
    """List all pods and their meetings."""
    pods_dir = Path("pods")
    if not pods_dir.exists():
        print("No pods yet. Run `podscribe init <name>` to create one.")
        return 0
    found_any = False
    for pod_dir in sorted(pods_dir.iterdir()):
        if not pod_dir.is_dir():
            continue
        try:
            pod = load_pod(pod_dir.name)
        except Exception as e:
            print(f"  [{pod_dir.name}] (error loading: {e})")
            continue
        found_any = True
        meetings = list_meetings(pod)
        header = f"[{pod.name}] {pod.display_name}"
        if pod.role:
            header += f" — {pod.role}"
        print(header)
        if not meetings:
            print("  (no meetings yet)")
        for m in meetings:
            dur = f"{m.duration_sec // 60}m{m.duration_sec % 60:02d}s" if m.duration_sec else "?"
            print(f"  • {m.started_at} ({dur}) → {m.id}")
    if not found_any:
        print("No pods yet. Run `podscribe init <name>` to create one.")
    return 0


def cmd_show(args) -> int:
    """Show a meeting transcript."""
    if not pod_exists(args.pod):
        print(f"No pod '{args.pod}'.", file=sys.stderr)
        return 1
    pod = load_pod(args.pod)
    meetings = list_meetings(pod)
    if not meetings:
        print(f"No meetings for pod '{args.pod}'.")
        return 1
    meeting_id = args.meeting if args.meeting else ("latest" if args.latest else "latest")
    if meeting_id == "latest":
        meeting = meetings[0]
    else:
        matching = [m for m in meetings if m.id.startswith(meeting_id)]
        if not matching:
            print(f"No meeting matching '{meeting_id}'. Try `podscribe list`.", file=sys.stderr)
            return 1
        meeting = matching[0]
    print(read_transcript(meeting))
    return 0


def cmd_context_add(args) -> int:
    if not pod_exists(args.pod):
        print(f"No pod '{args.pod}'.", file=sys.stderr)
        return 1
    pod = load_pod(args.pod)
    add_entry(pod, args.term, args.category or "")
    save_pod_config(pod)
    print(f"Added '{args.term}' to glossary for pod '{args.pod}'")
    return 0


def cmd_context_remove(args) -> int:
    if not pod_exists(args.pod):
        print(f"No pod '{args.pod}'.", file=sys.stderr)
        return 1
    pod = load_pod(args.pod)
    remove_entry(pod, args.term)
    save_pod_config(pod)
    print(f"Removed '{args.term}' from glossary for pod '{args.pod}'")
    return 0


def cmd_context_list(args) -> int:
    if not pod_exists(args.pod):
        print(f"No pod '{args.pod}'.", file=sys.stderr)
        return 1
    pod = load_pod(args.pod)
    if not pod.glossary:
        print(f"No glossary entries for pod '{args.pod}'.")
        return 0
    print(f"Glossary for {pod.name} ({pod.display_name}):")
    for entry in pod.glossary:
        cat = f" ({entry['category']})" if entry.get("category") else ""
        print(f"  • {entry['term']}{cat}")
    return 0


def cmd_enhance(args) -> int:
    """Enhance transcript via local LLM (Ollama)."""
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="podscribe",
        description="Local-first live transcription for 1:1s and team meetings.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Initialize a new pod for a person.")
    p_init.add_argument("name", help="Pod name (kebab-case, e.g. sam-chen)")
    p_init.add_argument("--display-name", help="Human-readable name (e.g. 'Sam Chen')")
    p_init.add_argument("--role", help="Role (e.g. 'Senior Engineer')")
    p_init.add_argument("--cadence", help="Meeting cadence (weekly, biweekly, monthly, adhoc)")
    p_init.add_argument("--notes", help="Private notes about this person")
    p_init.set_defaults(func=cmd_init)

    # record
    p_rec = sub.add_parser("record", help="Live record and transcribe a meeting.")
    p_rec.add_argument("pod", help="Pod name")
    p_rec.add_argument("--model", default="base.en", help="Whisper model (default: base.en)")
    p_rec.add_argument("--vad-aggressiveness", type=int, default=2, choices=[0, 1, 2, 3], help="VAD strictness (0=loose, 3=strict; default 2)")
    p_rec.add_argument("--device", type=int, default=None, help="Input device index (default: system default)")
    p_rec.add_argument("--keep-audio", action="store_true", help="Keep raw audio file (for debugging)")
    p_rec.set_defaults(func=cmd_record)

    # list
    p_list = sub.add_parser("list", help="List all pods and their meetings.")
    p_list.set_defaults(func=cmd_list)

    # show
    p_show = sub.add_parser("show", help="Show a meeting transcript.")
    p_show.add_argument("pod", help="Pod name")
    p_show.add_argument("meeting", help="Meeting ID prefix or 'latest'")
    p_show.set_defaults(func=cmd_show)

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

    # enhance
    p_enh = sub.add_parser("enhance", help="Enhance transcript via local LLM (Ollama).")
    p_enh.add_argument("pod", help="Pod name")
    p_enh.add_argument("meeting", nargs="?", help="Meeting ID prefix (default: latest)")
    p_enh.add_argument("--latest", "-l", action="store_true", help="Use latest meeting")
    p_enh.set_defaults(func=cmd_enhance)

    return p


def rewrite_argv(argv: list[str]) -> list[str]:
    """Rewrite pod-first syntax and aliases to standard form.

    `podscribe <pod> <command> [args]` → `<command> <pod> [args]`
    `start` → `record`, `summarize` → `enhance`
    """
    known_commands = {"init", "record", "list", "show", "context", "enhance"}
    aliases = {"start": "record", "summarize": "enhance"}

    if not argv:
        return argv

    arg0 = aliases.get(argv[0], argv[0])
    if arg0 not in known_commands and len(argv) >= 2:
        cmd = aliases.get(argv[1], argv[1])
        if cmd in known_commands:
            return [cmd, argv[0]] + argv[2:]
        return [arg0] + argv[1:]
    return [arg0] + argv[1:]


def main(argv: Optional[list] = None) -> int:
    if argv is None:
        argv = sys.argv[1:] if len(sys.argv) > 1 else []
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
