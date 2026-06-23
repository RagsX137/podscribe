"""Cross-pod keyword search over transcript files."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


@dataclass
class SearchMatch:
    pod_name: str
    date_str: str
    meeting_id: str
    timestamp: str
    text: str


_TIMESTAMP_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)$")


def search(
    query: str,
    *,
    pod: Optional[str] = None,
    since: Optional[str] = None,
    meeting_type: Optional[str] = None,
    color: bool = False,
) -> Iterator[SearchMatch]:
    """Yield SearchMatch for each line matching `query` in any transcript.

    Backend: rg if available, else Python Path.rglob + substring.
    Filters: pod, since (date string parseable by storage._parse_since),
    meeting_type (must match a directory between the date and the file).
    """
    files = _iter_transcript_files(pod)
    files = _filter_by_since(files, since)
    files = _filter_by_type(files, meeting_type)

    if shutil.which("rg"):
        yield from _rg_search(query, files, color=color)
    else:
        yield from _python_search(query, files, color=color)


def _iter_transcript_files(pod: Optional[str]) -> list[Path]:
    if pod:
        base = Path("pods") / pod / "transcripts"
        if not base.exists():
            return []
        return sorted(base.rglob("*.md"))
    base = Path("pods")
    if not base.exists():
        return []
    return sorted(p for p in base.rglob("*.md") if "transcripts" in p.parts)


def _filter_by_since(files: list[Path], since: Optional[str]) -> list[Path]:
    if not since:
        return files
    from .storage import _parse_since
    cutoff = _parse_since(since)
    from datetime import datetime
    out = []
    for f in files:
        stem = f.stem
        if len(stem) >= 10:
            try:
                file_date = datetime.strptime(stem[:10], "%Y-%m-%d").date()
                if file_date >= cutoff:
                    out.append(f)
                continue
            except ValueError:
                pass
        mtime = datetime.fromtimestamp(f.stat().st_mtime).date()
        if mtime >= cutoff:
            out.append(f)
    return out


def _filter_by_type(files: list[Path], meeting_type: Optional[str]) -> list[Path]:
    if not meeting_type:
        return files
    out = []
    for f in files:
        parts = f.parts
        if "transcripts" not in parts:
            continue
        idx = parts.index("transcripts")
        if len(parts) - idx == 3:
            continue
        if len(parts) - idx == 4:
            if parts[idx + 2] == meeting_type:
                out.append(f)
    return out


def _rg_search(query: str, files: list[Path], *, color: bool) -> Iterator[SearchMatch]:
    if not files:
        return
    cmd = ["rg", "-F", "--no-heading", "-n", query]
    if color:
        cmd.append("--color=always")
    cmd.extend(str(f) for f in files)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        print(f"rg error: {proc.stderr}", file=sys.stderr)
        return
    for line in proc.stdout.splitlines():
        match = _parse_rg_line(line)
        if match is not None:
            yield match


def _parse_rg_line(line: str) -> Optional[SearchMatch]:
    parts = line.split(":", 2)
    if len(parts) < 3:
        return None
    path_str, _lineno, content = parts
    path = Path(path_str)
    return _make_match_from_path(path, content)


def _python_search(query: str, files: list[Path], *, color: bool) -> Iterator[SearchMatch]:
    for f in files:
        try:
            text = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for line in text.splitlines():
            if query in line:
                match = _make_match_from_path(f, line)
                if match is not None:
                    yield match


def _make_match_from_path(path: Path, line: str) -> Optional[SearchMatch]:
    parts = path.parts
    if "transcripts" not in parts:
        return None
    idx = parts.index("transcripts")
    pod_name = parts[idx - 1] if idx >= 1 else "?"
    date_str = parts[idx + 1]
    meeting_id = path.stem

    m = _TIMESTAMP_RE.match(line)
    if m:
        timestamp = f"[{m.group(1)}]"
        text = m.group(2)
    else:
        timestamp = ""
        text = line
    return SearchMatch(
        pod_name=pod_name,
        date_str=date_str,
        meeting_id=meeting_id,
        timestamp=timestamp,
        text=text,
    )
