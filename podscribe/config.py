"""Pod, project, and leadership configuration: load/save YAML configs."""
from __future__ import annotations

from pathlib import Path

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


def load_leadership_glossary() -> list:
    """Load global glossary from leadership_team.yaml."""
    if not LEADERSHIP_CONFIG_PATH.exists():
        return []
    with LEADERSHIP_CONFIG_PATH.open() as f:
        data = yaml.safe_load(f) or {}
    return data.get("glossary") or []


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


def get_effective_glossary(pod: Pod) -> list:
    """Merge leadership-team glossary with pod-specific glossary.

    Leadership terms come first, then pod-specific terms.
    """
    leadership = load_leadership_glossary()
    pod_terms = pod.glossary or []
    return leadership + pod_terms


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
