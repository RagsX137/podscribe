"""Pod, project, and leadership configuration: load/save YAML configs."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from .models import Pod

PROJECT_CONFIG_PATH = Path("podscribe.yaml")
LEADERSHIP_CONFIG_PATH = Path("leadership_team.yaml")


def save_pod_config(pod: Pod) -> None:
    """Save pod config to YAML at pod.config_path."""
    data = {
        "name": pod.name,
        "display_name": pod.display_name,
        "role": pod.role,
        "cadence": pod.cadence,
        "notes": pod.notes,
        "created_at": pod.created_at,
    }
    if pod.glossary:
        data["glossary"] = pod.glossary
    if pod.llm:
        data["llm"] = pod.llm
    with pod.config_path.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def load_pod_config(base_path: Path) -> Pod:
    """Load pod config from YAML at base_path/config.yaml."""
    config_path = base_path / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"No pod config found at {config_path}")
    with config_path.open() as f:
        data = yaml.safe_load(f) or {}
    return Pod(
        name=data["name"],
        display_name=data.get("display_name", ""),
        role=data.get("role", ""),
        cadence=data.get("cadence", "weekly"),
        notes=data.get("notes", ""),
        created_at=data.get("created_at", ""),
        glossary=data.get("glossary"),
        llm=data.get("llm"),
        base_path=base_path,
    )


def load_project_config() -> dict:
    """Load project-level config from podscribe.yaml."""
    if PROJECT_CONFIG_PATH.exists():
        with PROJECT_CONFIG_PATH.open() as f:
            return yaml.safe_load(f) or {}
    return {}


def save_project_config(data: dict) -> None:
    """Save project-level config to podscribe.yaml."""
    with PROJECT_CONFIG_PATH.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def load_last_pod() -> Optional[str]:
    """Return the last-used pod name from podscribe.yaml, or None."""
    cfg = load_project_config()
    value = cfg.get("last_pod")
    return value if isinstance(value, str) and value else None


def save_last_pod(name: str) -> None:
    """Persist the last-used pod name in podscribe.yaml (preserves other keys)."""
    if not name or not isinstance(name, str):
        raise ValueError("last_pod must be a non-empty string")
    cfg = load_project_config()
    cfg["last_pod"] = name
    save_project_config(cfg)


def _normalise_entry(e: str | dict) -> dict:
    """Coerce a raw YAML glossary entry — string or dict — to canonical form."""
    if isinstance(e, str):
        return {"term": e, "category": ""}
    return e


def load_leadership_glossary() -> list:
    """Load global glossary from leadership_team.yaml.

    Normalises plain-string entries (e.g. ``["Yassine Parakh"]``) to
    the canonical dict form ``{"term": "...", "category": ""}`` so that
    all consumers can assume dict access.
    """
    if not LEADERSHIP_CONFIG_PATH.exists():
        return []
    with LEADERSHIP_CONFIG_PATH.open() as f:
        data = yaml.safe_load(f) or {}
    raw = data.get("glossary") or []
    return [_normalise_entry(e) for e in raw]


def load_god_model() -> Optional[str]:
    """Return the god-mode agent model from podscribe.yaml.

    Resolution order:
    1. podscribe.yaml → god.model  (agent-specific override)
    2. podscribe.yaml → llm.model  (shared with enhance/consolidate)
    3. None — caller must handle missing config gracefully
    """
    cfg = load_project_config()
    return (
        (cfg.get("god") or {}).get("model")
        or (cfg.get("llm") or {}).get("model")
        or None
    )


def save_god_model(model: str) -> None:
    """Persist the god-mode agent model to podscribe.yaml under god.model."""
    if not model or not isinstance(model, str):
        raise ValueError("god model must be a non-empty string")
    cfg = load_project_config()
    if "god" not in cfg:
        cfg["god"] = {}
    cfg["god"]["model"] = model
    save_project_config(cfg)


CONSOLIDATE_PROMPT_DEFAULT = """Given the following enhanced meeting summary, extract structured information.

Return ONLY valid YAML with these fields:
- quick_summary: One-sentence summary of the meeting
- key_topics: Bullet list of topics discussed
- action_items: List of things the manager needs to follow up on
- blockers: List of any blockers or concerns raised
- next_steps: List of plans for next meeting

Enhanced summary:
{{summary}}"""


def load_consolidate_prompt() -> str:
    """Load consolidate prompt from podscribe.yaml, or return default."""
    cfg = load_project_config()
    prompt = cfg.get("consolidate", {}).get("prompt")
    return prompt if prompt else CONSOLIDATE_PROMPT_DEFAULT


def save_consolidate_prompt(prompt: str) -> None:
    """Save consolidate prompt to podscribe.yaml."""
    if not prompt.strip():
        raise ValueError("Consolidate prompt cannot be empty")
    cfg = load_project_config()
    if "consolidate" not in cfg:
        cfg["consolidate"] = {}
    cfg["consolidate"]["prompt"] = prompt
    save_project_config(cfg)


KT_PROMPT_DEFAULT = """You are reviewing a pre-recorded Knowledge-Transfer (KT) session transcript so a busy team lead can skip watching it and still trust a second pair of eyes.

Glossary (project names/people — spell exactly): {{glossary}}

Produce a markdown briefing with these sections, each grounded only in the transcript:

## Overview
2-3 sentences: what this KT covers and why it matters.

## How it works / architecture
The system, components, and flow as explained.

## Key decisions & rationale
Decisions made and the stated reasons.

## Dependencies & gotchas
External systems, credentials, ordering constraints, and any "be careful" notes.

## Second pair of eyes
- Assumptions the presenter made but did not justify.
- What a reviewer should double-check before relying on this.
- Jargon/acronyms decoded (only those actually used).
- Anything glossed over or left incomplete.

## Open questions / follow-ups
Concrete questions to raise with the presenter or team.

Transcript:
{{transcript}}"""


def load_kt_prompt() -> str:
    """Load the KT summarize prompt from podscribe.yaml (kt.prompt), or default."""
    cfg = load_project_config()
    prompt = (cfg.get("kt") or {}).get("prompt")
    return prompt if prompt else KT_PROMPT_DEFAULT


_glossary_cache: dict = {
    "key": None,
    "value": None,
}


def _leadership_yaml_path() -> Path:
    return LEADERSHIP_CONFIG_PATH


def _read_effective_glossary(pod: Pod) -> list:
    """Read leadership_team.yaml + pod.glossary. The actual disk read."""
    leadership = load_leadership_glossary() or []
    pod_glossary = list(pod.glossary or [])
    return [_normalise_entry(e) for e in leadership + pod_glossary]


def get_effective_glossary(pod: Pod) -> list:
    """Return leadership + pod glossary, cached by mtime + pod.glossary id.

    The cache key includes:
    - mtime of leadership_team.yaml (so manual edits invalidate)
    - mtime of pods/<name>/config.yaml (so external edits invalidate even when
      a long-lived process holds a stale Pod object — god-REPL scenario)
    - id(pod.glossary) (so list replacement invalidates)
    - len(pod.glossary) (so in-place mutation that grows/shrinks invalidates)

    The first call after process start reads from disk. Subsequent calls
    with the same key return the cached list. The cache is per-process.
    """
    try:
        mtime = _leadership_yaml_path().stat().st_mtime
    except FileNotFoundError:
        mtime = 0
    try:
        pod_mtime = pod.config_path.stat().st_mtime
    except (FileNotFoundError, AttributeError, ValueError):
        pod_mtime = 0
    key = (mtime, pod_mtime, id(pod.glossary), len(pod.glossary))
    if _glossary_cache["key"] != key:
        _glossary_cache["key"] = key
        _glossary_cache["value"] = _read_effective_glossary(pod)
    return _glossary_cache["value"]


def load_preserve_speakers(pod: "Pod") -> bool:
    """Resolve the preserve_speakers setting for a pod.

    Resolution order: pod-level llm.preserve_speakers > project-level
    llm.preserve_speakers > default True.

    Raises ValueError if either level is set to a non-boolean value.
    """
    for level_name, llm_cfg in [
        ("pod", pod.llm),
        ("project", load_project_config().get("llm")),
    ]:
        if llm_cfg and "preserve_speakers" in llm_cfg:
            value = llm_cfg["preserve_speakers"]
            if not isinstance(value, bool):
                raise ValueError(
                    f"{level_name} llm.preserve_speakers must be a boolean, "
                    f"got {type(value).__name__}: {value!r}"
                )
            return value
    return True
