"""Tool implementations for God mode agent. No argparse — clean function signatures."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Optional

from .config import get_effective_glossary, load_project_config, resolve_llm_config
from .glossary import add_entry, format_glossary_prompt, remove_entry
from .models import Segment, fmt_date
from .storage import (
    append_segment,
    finalize_meeting,
    init_pod,
    list_kt_sessions,
    list_meetings,
    load_pod,
    pod_exists,
    read_transcript,
    save_pod_config,
    start_meeting,
)
from .search import search


MAX_TOOL_RESULT_CHARS = 8000


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + "\n[...truncated, full result on disk]"


def _resolve_meeting(meetings, prefix: str):
    """Resolve a meeting by ID prefix. Returns (meeting, error_str)."""
    if prefix == "latest":
        if not meetings:
            return None, "No meetings found."
        return meetings[0], None
    matches = [m for m in meetings if m.id.startswith(prefix)]
    if not matches:
        return None, f"No meeting matching '{prefix}'."
    if len(matches) > 1:
        listing = "\n".join(f"  • {m.id}" for m in matches)
        return None, f"Multiple meetings match '{prefix}':\n{listing}"
    return matches[0], None


def _list_pod_names() -> list[str]:
    from pathlib import Path
    pods_dir = Path("pods")
    if not pods_dir.exists():
        return []
    return sorted(
        p.name for p in pods_dir.iterdir()
        if p.is_dir() and (p / "config.yaml").exists()
    )


def list_pods() -> list[str]:
    """Return all existing pod names."""
    return _list_pod_names()


def pod_info(name: str) -> dict:
    """Return pod metadata and meeting stats."""
    if not pod_exists(name):
        return {"error": f"Pod '{name}' does not exist."}
    pod = load_pod(name)
    meetings = list_meetings(pod)
    return {
        "name": pod.name,
        "display_name": pod.display_name,
        "role": pod.role,
        "cadence": pod.cadence,
        "notes": pod.notes,
        "created_at": pod.created_at,
        "total_meetings": len(meetings),
        "glossary_entries": len(pod.glossary or []),
    }


def init_pod_tool(
    name: str,
    display_name: str = "",
    role: str = "",
    cadence: str = "weekly",
    notes: str = "",
) -> dict:
    """Create a new pod. Returns result dict."""
    if pod_exists(name):
        return {"error": f"Pod '{name}' already exists."}
    pod = init_pod(name, display_name=display_name, role=role, cadence=cadence, notes=notes)
    return {"name": pod.name, "status": "created", "path": str(pod.base_path)}


def list_meetings_tool(
    pod_name: str,
    since: Optional[str] = None,
    meeting_type: Optional[str] = None,
    recent: Optional[int] = None,
) -> list[dict]:
    """List meetings in a pod, filterable."""
    if not pod_exists(pod_name):
        return [{"error": f"Pod '{pod_name}' does not exist."}]
    pod = load_pod(pod_name)
    meetings = list_meetings(pod)
    filtered = list(meetings)

    if meeting_type:
        from .models import parse_meeting_type
        try:
            t = parse_meeting_type(meeting_type)
            filtered = [m for m in filtered if m.type == t]
        except ValueError:
            return [{"error": f"Invalid meeting type: {meeting_type}"}]

    if since:
        from .storage import _parse_since
        try:
            cutoff = _parse_since(since)
            filtered = [m for m in filtered if datetime.fromisoformat(m.started_at).date() >= cutoff]
        except (ValueError, TypeError):
            return [{"error": f"Invalid --since value: {since}"}]

    if recent is not None:
        filtered = filtered[:recent]

    return [
        {
            "id": m.id,
            "type": m.type,
            "started_at": m.started_at,
            "duration_sec": m.duration_sec,
        }
        for m in filtered
    ]


def show_meeting(pod_name: str, meeting_id: str) -> str:
    """Return the raw transcript text for a meeting."""
    if not pod_exists(pod_name):
        return f"Pod '{pod_name}' does not exist."
    pod = load_pod(pod_name)
    meetings = list_meetings(pod)
    meeting, err = _resolve_meeting(meetings, meeting_id)
    if err:
        return err
    try:
        return read_transcript(meeting)
    except FileNotFoundError as e:
        return str(e)


def list_kt_tool(pod_name: str) -> list:
    """List KT sessions in a pod (id, started_at, type)."""
    if not pod_exists(pod_name):
        return [{"error": f"Pod '{pod_name}' does not exist."}]
    pod = load_pod(pod_name)
    out = []
    for m in list_kt_sessions(pod):
        out.append({"id": m.id, "started_at": m.started_at, "type": m.type})
    return out


def show_kt(pod_name: str, session_id: str) -> str:
    """Return the raw transcript text for a KT session ('latest' allowed)."""
    if not pod_exists(pod_name):
        return f"Pod '{pod_name}' does not exist."
    pod = load_pod(pod_name)
    sessions = list_kt_sessions(pod)
    meeting, err = _resolve_meeting(sessions, session_id)
    if err is not None:
        return err
    try:
        return read_transcript(meeting)
    except FileNotFoundError as e:
        return str(e)


# -- Recording state (module-level, one active recording at a time) --

_recording_session: Optional[dict] = None


def is_recording_active() -> bool:
    """Return True if a god-mode background recording is currently running."""
    return _recording_session is not None


def start_recording(
    pod_name: str,
    model: str = "large-v3-turbo",
    backend: str = "auto",
    vad: int = 2,
    meeting_type: Optional[str] = None,
) -> dict:
    """Launch background recording thread. Returns session info dict."""
    global _recording_session
    if _recording_session is not None:
        return {"error": "Recording already in progress."}
    if not pod_exists(pod_name):
        return {"error": f"Pod '{pod_name}' does not exist."}

    from .audio import AudioCapture
    from .transcriber import Transcriber

    from .models import parse_meeting_type
    try:
        mt = parse_meeting_type(meeting_type)
    except ValueError as e:
        return {"error": str(e)}

    pod = load_pod(pod_name)
    meeting = start_meeting(pod, meeting_type=mt)
    capture = AudioCapture(vad_aggressiveness=vad)
    transcriber = Transcriber(model=model, backend=backend)
    effective_glossary = get_effective_glossary(pod)
    glossary = format_glossary_prompt(effective_glossary) if effective_glossary else None
    lines: list = []

    def _record_thread():
        nonlocal lines
        with meeting.transcript_path.open("w") as f:
            f.write(f"# Meeting: {meeting.id}\n\n")
            f.write(f"- pod: {pod.name} ({pod.display_name})\n")
            f.write(f"- started: {meeting.started_at}\n")
            f.write(f"- model: {transcriber.model_name}\n")
            f.write(f"- vad: webrtcvad (aggressiveness={capture.vad_aggressiveness})\n\n")
            f.write("## Transcript\n\n")
        meeting.model = transcriber.model_name
        meeting.vad_enabled = True
        start_ts = time.monotonic()
        try:
            for audio_segment in capture.segments():
                kwargs = {}
                if glossary:
                    kwargs["initial_prompt"] = glossary
                results = transcriber.transcribe(audio_segment, **kwargs)
                for r in results:
                    elapsed = time.monotonic() - start_ts
                    seg_duration = max(0.0, r["end"] - r["start"])
                    seg_start = max(0.0, elapsed - seg_duration)
                    seg = Segment(start_sec=seg_start, end_sec=elapsed, text=r["text"])
                    append_segment(meeting, seg)
                    lines.append(f"[{_fmt_time(seg.start_sec)}] {seg.text}")
        finally:
            capture.stop()
            meeting.duration_sec = int(time.monotonic() - start_ts)
            meeting.ended_at = datetime.now().isoformat(timespec="seconds")
            finalize_meeting(meeting, keep_audio=True)

    thread = threading.Thread(target=_record_thread, daemon=True)
    thread.start()
    _recording_session = {
        "pod": pod,
        "meeting": meeting,
        "capture": capture,
        "thread": thread,
        "transcript_lines": lines,
    }
    return {"meeting_id": meeting.id, "pod": pod_name, "status": "recording"}


def _fmt_time(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def stop_recording() -> dict:
    """Stop active recording, finalize meeting. Returns result dict."""
    global _recording_session
    session = _recording_session
    if session is None:
        return {"error": "No active recording."}
    session["capture"].stop()
    session["thread"].join(timeout=10)
    if session["thread"].is_alive():
        _recording_session = None
        return {"error": "Recording thread did not stop within timeout."}
    _recording_session = None
    m = session["meeting"]
    return {
        "meeting_id": m.id,
        "segments": len(session["transcript_lines"]),
        "duration_sec": m.duration_sec,
        "status": "finalized",
    }


def get_recording_status() -> dict:
    """Return current recording status for TUI polling."""
    global _recording_session
    session = _recording_session
    if session is None:
        return {"status": "idle"}
    m = session["meeting"]
    lines = session["transcript_lines"]
    return {
        "status": "recording",
        "meeting_id": m.id,
        "pod": m.pod_name,
        "segment_count": len(lines),
        "latest_lines": lines[-20:] if lines else [],
    }


def enhance_meeting(pod_name: str, meeting_id: str = "latest") -> str:
    """Run LLM enhance on a meeting transcript. Returns enhanced text."""
    if not pod_exists(pod_name):
        return f"Pod '{pod_name}' does not exist."
    pod = load_pod(pod_name)
    meetings = list_meetings(pod)
    meeting, err = _resolve_meeting(meetings, meeting_id)
    if err:
        return err

    llm_config = resolve_llm_config(pod)
    if not llm_config or not llm_config.get("model") or not llm_config.get("prompt_template"):
        return "LLM not configured. Set up with `podscribe config llm set`."

    transcript = read_transcript(meeting)
    if len(transcript.strip()) < 50:
        return f"Transcript too short ({len(transcript.strip())} chars)."

    from .config import load_preserve_speakers
    from .llm import build_enhance_prompt
    glossary = get_effective_glossary(pod)
    preserve = load_preserve_speakers(pod)
    prompt = build_enhance_prompt(
        llm_config["prompt_template"], glossary, transcript, preserve_speakers=preserve,
    )

    date_str = fmt_date(datetime.fromisoformat(meeting.started_at))
    summary_dir = pod.summaries_dir_for(date_str)
    enhanced_path = summary_dir / f"{meeting.id}.md"

    text, enhance_err = _run_enhance(prompt, llm_config)
    if enhance_err:
        return enhance_err

    summary_dir.mkdir(parents=True, exist_ok=True)
    enhanced_path.write_text(text)
    return f"Enhanced transcript saved to {enhanced_path}"


def _run_enhance(prompt: str, llm_config: dict) -> tuple[Optional[str], Optional[str]]:
    """Run LLM enhance via a provider, returning (text, None) or (None, error)."""
    from .providers.registry import build_provider
    try:
        provider = build_provider(llm_config)
    except ValueError as e:
        return None, str(e)
    from .llm import enhance_transcript
    result = enhance_transcript(provider.model, prompt, provider=provider)
    if result is None:
        return None, "LLM request failed. Check the provider/base_url and that the server is reachable."
    return result, None


def consolidate_meeting(pod_name: str, meeting_id: str = "latest", no_log: bool = False) -> dict:
    """Extract structured fields from enhanced summary, update CSV."""
    if not pod_exists(pod_name):
        return {"error": f"Pod '{pod_name}' does not exist."}
    pod = load_pod(pod_name)
    meetings = list_meetings(pod)
    meeting, err = _resolve_meeting(meetings, meeting_id)
    if err:
        return {"error": err}

    date_str = fmt_date(datetime.fromisoformat(meeting.started_at))
    enhanced_path = pod.summaries_dir_for(date_str) / f"{meeting.id}.md"
    if not enhanced_path.exists():
        return {"error": f"No enhanced summary for {meeting.id}. Run enhance first."}

    enhanced_text = enhanced_path.read_text()
    from .config import load_consolidate_prompt
    from .llm import build_consolidate_prompt, extract_structured_fields
    prompt_template = load_consolidate_prompt()
    prompt = build_consolidate_prompt(prompt_template, enhanced_text)

    llm_config = resolve_llm_config(pod)
    if not llm_config or not llm_config.get("model"):
        return {"error": "LLM not configured."}
    text, cons_err = _run_enhance(prompt, llm_config)
    if cons_err:
        return {"error": cons_err}

    fields = extract_structured_fields(text)
    if fields is None:
        return {"error": "Failed to parse structured fields from LLM response."}

    if no_log:
        return {
            "meeting_id": meeting.id,
            "summary": fields.get("quick_summary", ""),
            "status": "extracted_only",
        }

    log_fields = _build_log_fields(pod, meeting, enhanced_path, fields)
    from .storage import append_log_row, log_entry_exists, rewrite_log_row

    if log_entry_exists(pod, meeting.id):
        rewrite_log_row(pod, meeting.id, log_fields)
        csv_status = "rewritten"
    else:
        append_log_row(pod, log_fields)
        csv_status = "appended"

    return {
        "meeting_id": meeting.id,
        "summary": fields.get("quick_summary", ""),
        "csv_status": csv_status,
    }


def _build_log_fields(pod, meeting, enhanced_path, fields):
    def _join(v):
        if isinstance(v, list):
            return "|".join(v)
        return str(v or "")
    return {
        "date": fmt_date(datetime.fromisoformat(meeting.started_at)),
        "person": pod.display_name,
        "meeting_id": meeting.id,
        "type": meeting.type or "",
        "quick_summary": _join(fields.get("quick_summary")),
        "key_topics": _join(fields.get("key_topics")),
        "action_items": _join(fields.get("action_items")),
        "blockers": _join(fields.get("blockers")),
        "next_steps": _join(fields.get("next_steps")),
        "summary_file": str(enhanced_path.relative_to(pod.base_path)),
        "transcript_file": str(meeting.transcript_path.relative_to(pod.base_path)) if meeting.transcript_path else "",
        "duration_sec": meeting.duration_sec or "",
    }


def search_transcripts(
    query: str,
    pod: Optional[str] = None,
    since: Optional[str] = None,
    meeting_type: Optional[str] = None,
) -> list[dict]:
    """Full-text search across transcripts."""
    matches = list(search(
        query,
        pod=pod,
        since=since,
        meeting_type=meeting_type,
        color=False,
    ))
    return [
        {
            "pod": m.pod_name,
            "date": m.date_str,
            "meeting_id": m.meeting_id,
            "timestamp": m.timestamp,
            "text": m.text,
        }
        for m in matches
    ]


def glossary_list(pod_name: str) -> list[dict]:
    """Return effective glossary entries for a pod."""
    if not pod_exists(pod_name):
        return [{"error": f"Pod '{pod_name}' does not exist."}]
    pod = load_pod(pod_name)
    return get_effective_glossary(pod)


def glossary_add(pod_name: str, term: str, category: str = "") -> dict:
    """Add a glossary entry. Returns result dict."""
    if not pod_exists(pod_name):
        return {"error": f"Pod '{pod_name}' does not exist."}
    pod = load_pod(pod_name)
    try:
        add_entry(pod, term, category)
        save_pod_config(pod)
        return {"term": term, "category": category, "status": "added"}
    except ValueError as e:
        return {"error": str(e)}


def glossary_remove(pod_name: str, term: str) -> dict:
    """Remove a glossary entry. Returns result dict."""
    if not pod_exists(pod_name):
        return {"error": f"Pod '{pod_name}' does not exist."}
    pod = load_pod(pod_name)
    try:
        remove_entry(pod, term)
        save_pod_config(pod)
        return {"term": term, "status": "removed"}
    except ValueError as e:
        return {"error": str(e)}


def export_data(out_path: Optional[str] = None) -> str:
    """Export pod data to a tarball. Returns path string."""
    from pathlib import Path
    from .export import create_export
    out = Path(out_path) if out_path else None
    try:
        result = create_export(out)
        return str(result)
    except OSError as e:
        return f"Export failed: {e}"
