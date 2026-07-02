"""Pod and meeting storage layer."""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .config import load_pod_config, save_pod_config
from .models import Meeting, Pod, Segment, fmt_date, make_meeting_id


CSV_COLUMNS = [
    "date", "person", "meeting_id", "type", "quick_summary",
    "key_topics", "action_items", "blockers", "next_steps",
    "summary_file", "transcript_file", "duration_sec",
]


def log_path(pod: Pod) -> Path:
    return pod.base_path / "meetings.csv"


def log_entry_exists(pod: Pod, meeting_id: str) -> bool:
    path = log_path(pod)
    if not path.exists():
        return False
    with path.open() as f:
        for row in csv.DictReader(f):
            if row.get("meeting_id") == meeting_id:
                return True
    return False


def append_log_row(pod: Pod, fields: dict) -> None:
    path = log_path(pod)
    new_row = {col: fields.get(col, "") for col in CSV_COLUMNS}
    file_exists = path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(new_row)
    # Mirror to global CSV. Failures are logged but not raised.
    append_global_log_row(fields)


def global_log_path() -> Path:
    """Path to the project-root global meetings.csv."""
    return Path("pods") / "meetings.csv"


def append_global_log_row(fields: dict) -> bool:
    """Append a row to the global CSV. Returns True on success, False on error.

    Errors are NOT raised — the per-pod CSV is the authoritative record.
    A global-write failure is logged to stderr but does not block the caller.
    """
    try:
        path = global_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        new_row = {col: fields.get(col, "") for col in CSV_COLUMNS}
        file_exists = path.exists()
        with path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(new_row)
        return True
    except OSError as e:
        print(f"Warning: failed to write global log: {e}", file=sys.stderr)
        return False


def read_global_log() -> list:
    """Read all rows from the global meetings.csv. Returns [] if file missing."""
    path = global_log_path()
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def update_log_row(pod: Pod, meeting_id: str, fields: dict) -> None:
    path = log_path(pod)
    if not path.exists():
        append_log_row(pod, fields)
        return
    with path.open() as f:
        rows = list(csv.DictReader(f))
    updated = {col: fields.get(col, "") for col in CSV_COLUMNS}
    out_rows = []
    found = False
    for row in rows:
        if row.get("meeting_id") == meeting_id:
            out_rows.append(updated)
            found = True
        else:
            out_rows.append(row)
    if not found:
        out_rows.append(updated)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(out_rows)
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise


rewrite_log_row = update_log_row


def init_pod(name: str, **kwargs) -> Pod:
    """Create a new pod with directory structure and config."""
    pod = Pod(name=name, **kwargs)
    pod.base_path.mkdir(parents=True, exist_ok=True)
    save_pod_config(pod)
    return pod


def pod_exists(name: str, base_dir: Path = Path("pods")) -> bool:
    return (base_dir / name / "config.yaml").exists()


def load_pod(name: str, base_dir: Path = Path("pods")) -> Pod:
    if not pod_exists(name, base_dir):
        raise FileNotFoundError(
            f"No pod named '{name}'. Run `podscribe init {name}` first."
        )
    return load_pod_config(base_dir / name)


def start_meeting(
    pod: Pod, when: Optional[datetime] = None,
    meeting_type: Optional[str] = None,
) -> Meeting:
    """Create a Meeting record and its file paths. Touches audio file for cleanup.

    If two recordings start within the same second (same base id), a
    ``-NNNN`` counter is appended so on-disk paths never collide.
    """
    when = when or datetime.now()
    base_id = make_meeting_id(pod.name, when)
    date_str = fmt_date(when)
    base_dir = pod.transcripts_dir_for(date_str)
    transcript_dir = base_dir / meeting_type if meeting_type else base_dir
    transcript_dir.mkdir(parents=True, exist_ok=True)

    # Disambiguate same-second collisions (defensive — Ctrl+C + write latency
    # normally prevents this, but cheap insurance against path collisions).
    # We probe the `.raw` (not `.md`) because start_meeting touches the raw
    # file via audio_path.touch(); the `.md` is only written later by
    # run_record_session, so checking it would never see a collision.
    meeting_id = base_id
    counter = 0
    while (transcript_dir / f"{meeting_id}.raw").exists():
        counter += 1
        meeting_id = f"{base_id}-{counter:04d}"

    transcript_path = transcript_dir / f"{meeting_id}.md"
    metadata_path = transcript_dir / f"{meeting_id}.json"
    audio_path = transcript_dir / f"{meeting_id}.raw"
    audio_path.touch()
    return Meeting(
        id=meeting_id,
        pod_name=pod.name,
        started_at=when.isoformat(timespec="seconds"),
        transcript_path=transcript_path,
        metadata_path=metadata_path,
        audio_path=audio_path,
        type=meeting_type,
    )


def append_segment(meeting: Meeting, segment: Segment) -> None:
    """Append a single segment line to the transcript (crash-safe, incremental)."""
    line = f"[{_fmt_time(segment.start_sec)}] {segment.text.strip()}\n"
    with meeting.transcript_path.open("a") as f:
        f.write(line)


def _fmt_time(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def finalize_meeting(meeting: Meeting, *, keep_audio: bool = False) -> None:
    """Write metadata JSON and optionally delete raw audio file."""
    if meeting.ended_at is None:
        meeting.ended_at = datetime.now().isoformat(timespec="seconds")
    metadata = {
        "id": meeting.id,
        "pod_name": meeting.pod_name,
        "started_at": meeting.started_at,
        "ended_at": meeting.ended_at,
        "duration_sec": meeting.duration_sec,
        "model": meeting.model,
        "vad_enabled": meeting.vad_enabled,
        "type": meeting.type,
        "audio_layout": "continuous" if keep_audio else None,
    }
    with meeting.metadata_path.open("w") as f:
        json.dump(metadata, f, indent=2)

    if not keep_audio and meeting.audio_path and meeting.audio_path.exists():
        meeting.audio_path.unlink()


def list_meetings(pod: Pod) -> List[Meeting]:
    """List all meetings in a pod, newest first.

    Matches both 2-level (transcripts/<date>/<id>.json) and 3-level
    (transcripts/<date>/<type>/<id>.json) layouts. Sorted by started_at
    (parsed from the JSON sidecar) rather than by date-dir path string.
    Meetings missing a sidecar or with malformed JSON are skipped.
    """
    meetings = []
    if not pod.base_path.exists():
        return meetings
    json_paths = set()
    json_paths.update(pod.base_path.glob("transcripts/*/*.json"))
    json_paths.update(pod.base_path.glob("transcripts/*/*/*.json"))
    for json_path in sorted(json_paths):
        try:
            with json_path.open() as f:
                data = json.load(f)
            md_path = json_path.with_suffix(".md")
            raw_path = json_path.with_suffix(".raw")
            meetings.append(Meeting(
                id=data["id"],
                pod_name=data["pod_name"],
                started_at=data["started_at"],
                ended_at=data.get("ended_at"),
                duration_sec=data.get("duration_sec"),
                transcript_path=md_path if md_path.exists() else None,
                metadata_path=json_path,
                audio_path=raw_path if raw_path.exists() else None,
                model=data.get("model", ""),
                vad_enabled=data.get("vad_enabled", True),
                type=data.get("type"),
                audio_layout=data.get("audio_layout"),
            ))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    meetings.sort(key=lambda m: m.started_at, reverse=True)
    return meetings


def read_transcript(meeting: Meeting) -> str:
    """Read a meeting's transcript markdown."""
    if not meeting.transcript_path or not meeting.transcript_path.exists():
        raise FileNotFoundError(f"No transcript at {meeting.transcript_path}")
    return meeting.transcript_path.read_text()


def _parse_since(value: str):
    """Parse a since value into a date.

    Accepts:
    - ISO date: "2026-06-15"
    - Duration: "7d", "24h", "30m" (days, hours, minutes back from today)
    """
    from datetime import datetime, timedelta
    if not value:
        raise ValueError("empty value")

    # ISO date
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        pass

    # Duration
    m = re.match(r"^(\d+)([dhm])$", value)
    if m:
        amount, unit = int(m.group(1)), m.group(2)
        delta = {
            "d": timedelta(days=amount),
            "h": timedelta(hours=amount),
            "m": timedelta(minutes=amount),
        }[unit]
        return (datetime.now() - delta).date()

    raise ValueError(
        f"cannot parse '{value}' as YYYY-MM-DD or duration (e.g. 7d, 24h)"
    )


def _read_pod_log_rows(pod_name: str) -> list:
    """Read all rows from a single pod's meetings.csv."""
    pod = load_pod_config(Path("pods") / pod_name)
    path = log_path(pod)
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))
