"""Data models for pods, meetings, and segments."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


KEBAB_CASE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def validate_pod_name(name: str) -> None:
    """Validate pod name is kebab-case. Raises ValueError if not."""
    if not name:
        raise ValueError("Pod name cannot be empty")
    if not KEBAB_CASE_RE.match(name):
        raise ValueError(
            f"Invalid pod name '{name}'. Must be kebab-case "
            f"(lowercase letters, digits, single hyphens, e.g. 'sam-chen')."
        )


def make_meeting_id(pod_name: str, when: Optional[datetime] = None) -> str:
    """Generate a deterministic meeting ID: YYYY-MM-DD-HHMM-<pod-name>."""
    when = when or datetime.now()
    return when.strftime("%Y-%m-%d-%H%M-") + pod_name


def fmt_date(when: datetime) -> str:
    """Format a datetime as DD-MMM-YYYY (e.g. 22-JUN-2026)."""
    return when.strftime("%d-%b-%Y").upper()


@dataclass
class Pod:
    name: str
    display_name: str = ""
    role: str = ""
    cadence: str = "weekly"
    notes: str = ""
    created_at: str = ""
    glossary: Optional[list] = None
    llm: Optional[dict] = None
    base_path: Optional[Path] = None

    def __post_init__(self):
        validate_pod_name(self.name)
        if not self.display_name:
            self.display_name = self.name.replace("-", " ").title()
        if not self.created_at:
            self.created_at = datetime.now().isoformat(timespec="seconds")
        if self.glossary is None:
            self.glossary = []
        if self.base_path is None:
            self.base_path = Path("pods") / self.name

    @property
    def config_path(self) -> Path:
        return self.base_path / "config.yaml"

    def date_dir(self, date_str: str) -> Path:
        return self.base_path / date_str

    def transcripts_dir_for(self, date_str: str) -> Path:
        return self.base_path / "transcripts" / date_str

    def summaries_dir_for(self, date_str: str) -> Path:
        return self.base_path / "summaries" / date_str


@dataclass
class Segment:
    start_sec: float
    end_sec: float
    text: str
    confidence: Optional[float] = None
    speaker: Optional[str] = None


@dataclass
class Meeting:
    id: str
    pod_name: str
    started_at: str
    ended_at: Optional[str] = None
    duration_sec: Optional[int] = None
    transcript_path: Optional[Path] = None
    metadata_path: Optional[Path] = None
    audio_path: Optional[Path] = None
    model: str = "large-v3-turbo"
    vad_enabled: bool = True
