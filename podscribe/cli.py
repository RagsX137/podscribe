"""CLI entry point for podscribe."""
from __future__ import annotations

import argparse
import signal
import sys
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from .config import get_effective_glossary, load_consolidate_prompt, load_leadership_glossary, load_preserve_speakers, load_project_config, save_consolidate_prompt, save_project_config
from .glossary import add_entry, format_glossary_prompt, remove_entry
from .llm import build_consolidate_prompt, build_enhance_prompt, enhance_transcript, extract_structured_fields
from .models import Meeting, Pod, Segment, fmt_date
from .storage import (
    append_log_row,
    append_segment,
    finalize_meeting,
    init_pod,
    list_meetings,
    load_pod,
    log_entry_exists,
    log_path,
    pod_exists,
    read_transcript,
    rewrite_log_row,
    save_pod_config,
    start_meeting,
)


def _hms(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _resolve_meeting(meetings, prefix, pod_name):
    """Resolve a meeting by ID prefix. Returns (meeting, None) on success, (None, error_message) on failure.

    - "latest" → meetings[0]
    - unique prefix → that meeting
    - 0 matches → error
    - 2+ matches → list candidates, error
    """
    if prefix == "latest":
        if not meetings:
            return None, f"No meetings for pod '{pod_name}'."
        return meetings[0], None
    matches = [m for m in meetings if m.id.startswith(prefix)]
    if not matches:
        return None, f"No meeting matching '{prefix}' for pod '{pod_name}'."
    if len(matches) > 1:
        listing = "\n".join(f"  • {m.id}" for m in matches)
        return None, (
            f"Multiple meetings match '{prefix}':\n{listing}\n"
            f"Use a longer prefix to disambiguate."
        )
    return matches[0], None


def _run_enhance(
    pod: Pod, meeting: Meeting, prompt: str, model: str,
) -> tuple[Optional[str], Optional[str]]:
    """Run LLM enhance. Returns (text, None) on success, (None, error) on failure.

    The error string is what gets printed to stderr; it owns the Ollama-
    availability message so both call sites stay in sync.
    """
    result = enhance_transcript(model, prompt)
    if result is None:
        return None, "Failed to reach Ollama. Is it running? Start with: ollama serve"
    return result, None


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
    print(f"  config: {pod.config_path}")
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
    effective_glossary = get_effective_glossary(pod)
    glossary_prompt = format_glossary_prompt(effective_glossary) if effective_glossary else None
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

    def handle_sigint(sig, frame):
        capture.stop()

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        for audio_segment in capture.segments():
            if wav_writer is not None:
                try:
                    pcm = np.clip(audio_segment * 32767, -32768, 32767).astype(np.int16)
                    wav_writer.writeframes(pcm.tobytes())
                except OSError as e:
                    print(f"  ⚠ audio write failed: {e}", file=sys.stderr)
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
        if wav_writer is not None:
            wav_writer.close()
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
    meeting_id = args.meeting or "latest"
    meeting, err = _resolve_meeting(meetings, meeting_id, args.pod)
    if err is not None:
        print(err, file=sys.stderr)
        return 1
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
    leadership = load_leadership_glossary()
    effective = get_effective_glossary(pod)
    if not effective:
        print(f"No glossary entries for pod '{args.pod}'.")
        return 0
    print(f"Glossary for {pod.name} ({pod.display_name}):")
    if leadership:
        print("  [leadership team — all pods]")
        for entry in leadership:
            cat = f" ({entry['category']})" if entry.get("category") else ""
            print(f"  • {entry['term']}{cat}")
    if pod.glossary:
        print(f"  [pod-specific — {pod.name}]")
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
    llm_config = pod.llm if pod.llm else load_project_config().get("llm")
    if not llm_config or not llm_config.get("model") or not llm_config.get("prompt_template"):
        print(
            "LLM not configured for this pod. "
            "Add an 'llm' section to config.yaml with 'model' and 'prompt_template', "
            "or set a project-level config with `podscribe config llm set <model> '<template>'`.",
            file=sys.stderr,
        )
        return 1

    meetings = list_meetings(pod)
    if not meetings:
        print(f"No meetings for pod '{args.pod}'.", file=sys.stderr)
        return 1

    meeting, err = _resolve_meeting(meetings, args.meeting, args.pod)
    if err is not None:
        print(err, file=sys.stderr)
        return 1

    transcript = read_transcript(meeting)
    stripped_len = len(transcript.strip())
    if stripped_len < 50:
        print(
            f"Transcript too short to enhance ({stripped_len} chars).",
            file=sys.stderr,
        )
        return 1
    effective_glossary = get_effective_glossary(pod)
    preserve_speakers = load_preserve_speakers(pod)
    prompt = build_enhance_prompt(
        llm_config["prompt_template"], effective_glossary, transcript,
        preserve_speakers=preserve_speakers,
    )

    date_str = fmt_date(datetime.fromisoformat(meeting.started_at))
    summary_dir = pod.summaries_dir_for(date_str)
    enhanced_path = summary_dir / f"{meeting.id}.md"

    print(f"Enhancing transcript for {pod.name}/{date_str}/{meeting.id}...")
    print(f"Enhanced summary will be saved to {pod.name}/{date_str}/{meeting.id}...")
    print(f"  Using Large Language Model: {llm_config['model']}")
    print(f"  Ollama URL: http://localhost:11434")
    print()

    text, err = _run_enhance(pod, meeting, prompt, llm_config["model"])
    if err is not None:
        print(err, file=sys.stderr)
        return 1

    summary_dir.mkdir(parents=True, exist_ok=True)
    enhanced_path.write_text(text)
    print(f"Enhanced transcript saved to {enhanced_path}")
    return 0


def cmd_config_llm_show(args) -> int:
    """Show project-level LLM config."""
    cfg = load_project_config().get("llm")
    if not cfg:
        print("No project-level LLM config set.")
        return 0
    print(f"model: {cfg.get('model', '(none)')}")
    print(f"prompt_template: {cfg.get('prompt_template', '(none)')}")
    return 0


def cmd_config_llm_set(args) -> int:
    """Set project-level LLM config."""
    cfg = load_project_config()
    cfg["llm"] = {"model": args.model, "prompt_template": args.prompt_template}
    save_project_config(cfg)
    print(f"Project LLM config set: {args.model}")
    return 0


def cmd_config_consolidate_show(args) -> int:
    from .config import load_consolidate_prompt
    print(load_consolidate_prompt())
    return 0


def cmd_config_consolidate_set(args) -> int:
    save_consolidate_prompt(args.prompt)
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

    date_str = fmt_date(datetime.fromisoformat(meeting.started_at))
    enhanced_path = pod.summaries_dir_for(date_str) / f"{meeting.id}.md"

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
    text, err = _run_enhance(pod, meeting, prompt, model_name)
    if err is not None:
        print(err, file=sys.stderr)
        return 1

    fields = extract_structured_fields(text)
    if fields is None:
        print("Failed to parse structured fields from LLM response.", file=sys.stderr)
        return 1

    quick_summary = fields.get("quick_summary", "")
    key_topics = "|".join(fields.get("key_topics", [])) if isinstance(fields.get("key_topics"), list) else str(fields.get("key_topics", ""))
    action_items = "|".join(fields.get("action_items", [])) if isinstance(fields.get("action_items"), list) else str(fields.get("action_items", ""))
    blockers = "|".join(fields.get("blockers", [])) if isinstance(fields.get("blockers"), list) else str(fields.get("blockers", ""))
    next_steps = "|".join(fields.get("next_steps", [])) if isinstance(fields.get("next_steps"), list) else str(fields.get("next_steps", ""))

    print(f"Extracted: {quick_summary}")
    print(f"  Topics: {key_topics}")
    print(f"  Actions: {action_items}")
    print(f"  Blockers: {blockers}")
    print(f"  Next: {next_steps}")

    if not args.no_log:
        log_fields = {
            "date": date_str,
            "person": pod.display_name,
            "meeting_id": meeting.id,
            "quick_summary": quick_summary,
            "key_topics": key_topics,
            "action_items": action_items,
            "blockers": blockers,
            "next_steps": next_steps,
            "summary_file": str(enhanced_path.relative_to(pod.base_path)) if enhanced_path else "",
            "transcript_file": str(meeting.transcript_path.relative_to(pod.base_path)) if meeting.transcript_path else "",
        }
        if log_entry_exists(pod, meeting.id):
            print(f"Log entry exists for {meeting.id}. Rewrite? [y/N] ", end="")
            try:
                answer = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            if answer in ("y", "yes"):
                rewrite_log_row(pod, meeting.id, log_fields)
                print(f"Log entry rewritten for {meeting.id}")
            else:
                print("Skipping log update.")
        else:
            append_log_row(pod, log_fields)
            print(f"Log entry appended to {log_path(pod)}")
    else:
        print("Skipping CSV log (--no-log)")

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
    p_rec.add_argument("--model", default="large-v3-turbo", help="Whisper model (default: large-v3-turbo)")
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
    p_enh.add_argument("meeting", nargs="?", default="latest", help="Meeting ID prefix (default: latest)")
    p_enh.set_defaults(func=cmd_enhance)

    # consolidate
    p_cons = sub.add_parser("consolidate", help="Extract structured fields from enhanced summary and update CSV log.")
    p_cons.add_argument("pod", help="Pod name")
    p_cons.add_argument("meeting", nargs="?", default="latest", help="Meeting ID prefix (default: latest)")
    p_cons.add_argument("--no-log", "-n", action="store_true", help="Skip CSV log update")
    p_cons.set_defaults(func=cmd_consolidate)

    # config
    p_cfg = sub.add_parser("config", help="Manage project-level config.")
    cfg_sub = p_cfg.add_subparsers(dest="action", required=True)
    p_cfg_llm = cfg_sub.add_parser("llm", help="Manage LLM config.")
    llm_sub = p_cfg_llm.add_subparsers(dest="llm_action", required=True)
    p_llm_show = llm_sub.add_parser("show", help="Show project LLM config.")
    p_llm_show.set_defaults(func=cmd_config_llm_show)
    p_llm_set = llm_sub.add_parser("set", help="Set project LLM config.")
    p_llm_set.add_argument("model", help="Ollama model name (e.g. qwen3.6)")
    p_llm_set.add_argument("prompt_template", help="Prompt template with {{transcript}} placeholder")
    p_llm_set.set_defaults(func=cmd_config_llm_set)

    p_cfg_cons = cfg_sub.add_parser("consolidate", help="Manage consolidate prompt.")
    cons_sub = p_cfg_cons.add_subparsers(dest="consolidate_action", required=True)
    p_cons_show = cons_sub.add_parser("show", help="Show consolidate prompt.")
    p_cons_show.set_defaults(func=cmd_config_consolidate_show)
    p_cons_set = cons_sub.add_parser("set", help="Set consolidate prompt.")
    p_cons_set.add_argument("prompt", help="Prompt template with {{summary}} placeholder")
    p_cons_set.set_defaults(func=cmd_config_consolidate_set)

    return p


def rewrite_argv(argv: list[str]) -> list[str]:
    """Rewrite pod-first syntax and aliases to standard form.

    `podscribe <pod> <command> [args]` → `<command> <pod> [args]`
    `start` → `record`, `summarize` → `enhance`
    """
    known_commands = {"init", "record", "list", "show", "context", "enhance", "config", "consolidate"}
    aliases = {"start": "record", "summarize": "enhance", "cons": "consolidate"}

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
