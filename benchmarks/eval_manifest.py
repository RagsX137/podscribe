"""Load and verify benchmarks/eval_manifest.yaml."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
import yaml

MANIFEST_PATH = Path("benchmarks/eval_manifest.yaml")
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
_last_ollama_error: Optional[Exception] = None


@dataclass
class SuiteEntry:
    id: str
    source: str
    video_id: Optional[str]
    title: Optional[str]
    license: Optional[str]
    duration_sec: Optional[int]
    start: Optional[str]
    end: Optional[str]
    expected_speakers: Optional[int]
    pod: Optional[str]
    meeting_prefix: Optional[str]


@dataclass
class Contestant:
    tag: str
    digest: str
    role: str


@dataclass
class Manifest:
    public: list[SuiteEntry]
    private: list[SuiteEntry]
    contestants: list[Contestant]


def load_manifest(path: Path = MANIFEST_PATH) -> Manifest:
    if not path.exists():
        sys.exit(f"Manifest not found at {path}.")
    data = yaml.safe_load(path.read_text()) or {}
    public = [
        SuiteEntry(
            id=e["id"], source="youtube",
            video_id=e.get("video_id"), title=e.get("title"),
            license=e.get("license"), duration_sec=e.get("duration_sec"),
            start=e.get("start"), end=e.get("end"),
            expected_speakers=e.get("expected_speakers"),
            pod=None, meeting_prefix=None,
        )
        for e in (data.get("public") or [])
    ]
    private = [
        SuiteEntry(
            id=e["id"], source="pod",
            video_id=None, title=None, license=None,
            duration_sec=None, start=None, end=None, expected_speakers=None,
            pod=e.get("pod"), meeting_prefix=e.get("meeting_prefix"),
        )
        for e in (data.get("private") or [])
    ]
    contestants = [
        Contestant(tag=c["tag"], digest=c["digest"], role=c.get("role", "challenger"))
        for c in (data.get("contestants") or [])
    ]
    return Manifest(public=public, private=private, contestants=contestants)


def _fetch_installed_digests() -> Optional[dict]:
    global _last_ollama_error
    try:
        r = requests.get(OLLAMA_TAGS_URL, timeout=5)
        r.raise_for_status()
    except requests.RequestException as e:
        _last_ollama_error = e
        return None
    _last_ollama_error = None
    out = {}
    for m in r.json().get("models", []):
        tag = m.get("name") or ""
        digest = m.get("digest") or ""
        if tag and digest:
            out[tag] = digest
    return out


def verify_contestants(contestants: list) -> None:
    installed = _fetch_installed_digests()
    if installed is None:
        e = _last_ollama_error
        sys.exit(
            f"Ollama not reachable at localhost:11434 ({e}). "
            f"Start it with `ollama serve`."
        )
    if not installed:
        sys.exit("Ollama reachable but no models installed.")
    for c in contestants:
        actual = installed.get(c.tag)
        if actual is None:
            sys.exit(
                f"Model '{c.tag}' not installed. Run: ollama pull {c.tag}"
            )
        if actual != c.digest:
            sys.exit(
                f"Digest mismatch for '{c.tag}':\n"
                f"  manifest pins {c.digest}\n"
                f"  installed is   {actual}\n"
                f"Pull the pinned version with `ollama pull {c.tag}@{c.digest}` "
                f"or update the manifest."
            )


def _first_or_champion(contestants: list) -> Contestant:
    for c in contestants:
        if c.role == "champion":
            return c
    return contestants[0]


def champion(contestants: list) -> Contestant:
    for c in contestants:
        if c.role == "champion":
            return c
    raise ValueError("no champion in manifest")
