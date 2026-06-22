"""Tests for pod config round-trip."""
from pathlib import Path

import pytest
import yaml

from podscribe.config import (
    get_effective_glossary,
    load_consolidate_prompt,
    load_leadership_glossary,
    load_pod_config,
    load_project_config,
    save_consolidate_prompt,
    save_pod_config,
    save_project_config,
)
from podscribe.models import Pod


def test_roundtrip(tmp_path):
    pod = Pod(
        name="sam-chen",
        display_name="Sam Chen",
        role="Senior Engineer",
        cadence="weekly",
        notes="Joined March 2026",
        base_path=tmp_path / "pods" / "sam-chen",
    )
    pod.base_path.mkdir(parents=True)
    save_pod_config(pod)
    assert pod.config_path.exists()
    loaded = load_pod_config(pod.base_path)
    assert loaded.name == "sam-chen"
    assert loaded.display_name == "Sam Chen"
    assert loaded.role == "Senior Engineer"
    assert loaded.cadence == "weekly"
    assert loaded.notes == "Joined March 2026"


def test_yaml_format(tmp_path):
    pod = Pod(
        name="sam-chen",
        display_name="Sam Chen",
        base_path=tmp_path / "pods" / "sam-chen",
    )
    pod.base_path.mkdir(parents=True)
    save_pod_config(pod)
    raw = pod.config_path.read_text()
    data = yaml.safe_load(raw)
    assert data["name"] == "sam-chen"
    assert data["display_name"] == "Sam Chen"


def test_special_characters_in_notes(tmp_path):
    pod = Pod(
        name="sam-chen",
        notes='Likes "platform work" — mentioned 3x.',
        base_path=tmp_path / "pods" / "sam-chen",
    )
    pod.base_path.mkdir(parents=True)
    save_pod_config(pod)
    loaded = load_pod_config(pod.base_path)
    assert "platform work" in loaded.notes
    assert "—" in loaded.notes


def test_load_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_pod_config(tmp_path / "nonexistent")


def test_glossary_roundtrip(tmp_path):
    pod = Pod(
        name="sam-chen",
        display_name="Sam Chen",
        glossary=[
            {"term": "Anurag Kaushik", "category": "person"},
            {"term": "Project Helios", "category": "project"},
        ],
        llm={"model": "llama3.2", "prompt_template": "fix {{transcript}}"},
        base_path=tmp_path / "pods" / "sam-chen",
    )
    pod.base_path.mkdir(parents=True)
    save_pod_config(pod)
    loaded = load_pod_config(pod.base_path)
    assert loaded.glossary == pod.glossary
    assert loaded.llm == pod.llm


def test_project_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = {"llm": {"model": "qwen3.6", "prompt_template": "fix {{transcript}}"}}
    save_project_config(data)
    assert (tmp_path / "podscribe.yaml").exists()
    loaded = load_project_config()
    assert loaded["llm"]["model"] == "qwen3.6"
    assert loaded["llm"]["prompt_template"] == "fix {{transcript}}"


def test_project_config_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    loaded = load_project_config()
    assert loaded == {}


def test_load_leadership_glossary_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_leadership_glossary() == []


def test_load_leadership_glossary_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "leadership_team.yaml").write_text("glossary: []\n")
    assert load_leadership_glossary() == []


def test_load_leadership_glossary_with_entries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "leadership_team.yaml").write_text(
        "glossary:\n"
        "  - term: CEO Name\n"
        "    category: person\n"
        "  - term: Big Project\n"
        "    category: project\n"
    )
    glossary = load_leadership_glossary()
    assert len(glossary) == 2
    assert glossary[0]["term"] == "CEO Name"
    assert glossary[1]["category"] == "project"


def test_get_effective_glossary_leadership_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "leadership_team.yaml").write_text(
        "glossary:\n"
        "  - term: CEO Name\n"
        "    category: person\n"
    )
    pod = Pod(name="sam-chen", base_path=tmp_path / "pods" / "sam-chen")
    merged = get_effective_glossary(pod)
    assert len(merged) == 1
    assert merged[0]["term"] == "CEO Name"


def test_get_effective_glossary_both_layers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "leadership_team.yaml").write_text(
        "glossary:\n"
        "  - term: CEO Name\n"
        "    category: person\n"
    )
    pod = Pod(
        name="sam-chen",
        glossary=[{"term": "Sam Chen", "category": "person"}],
        base_path=tmp_path / "pods" / "sam-chen",
    )
    merged = get_effective_glossary(pod)
    assert len(merged) == 2
    # leadership comes first
    assert merged[0]["term"] == "CEO Name"
    assert merged[1]["term"] == "Sam Chen"


def test_get_effective_glossary_no_leadership(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pod = Pod(
        name="sam-chen",
        glossary=[{"term": "Sam Chen", "category": "person"}],
        base_path=tmp_path / "pods" / "sam-chen",
    )
    merged = get_effective_glossary(pod)
    assert len(merged) == 1
    assert merged[0]["term"] == "Sam Chen"


def test_consolidate_prompt_default_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prompt = load_consolidate_prompt()
    assert "quick_summary" in prompt
    assert "action_items" in prompt


def test_consolidate_prompt_save_and_load(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_consolidate_prompt("Custom prompt {{summary}}")
    loaded = load_consolidate_prompt()
    assert loaded == "Custom prompt {{summary}}"


def test_consolidate_prompt_overwrites(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_consolidate_prompt("First prompt")
    save_consolidate_prompt("Second prompt")
    loaded = load_consolidate_prompt()
    assert loaded == "Second prompt"


def test_consolidate_prompt_loads_from_project_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.config import save_project_config
    save_project_config({"consolidate": {"prompt": "From file {{summary}}"}})
    loaded = load_consolidate_prompt()
    assert loaded == "From file {{summary}}"


def test_consolidate_prompt_empty_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import pytest
    with pytest.raises(ValueError, match="cannot be empty"):
        save_consolidate_prompt("")


def test_consolidate_prompt_blank_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import pytest
    with pytest.raises(ValueError, match="cannot be empty"):
        save_consolidate_prompt("   ")


def test_consolidate_prompt_empty_consolidate_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.config import save_project_config
    save_project_config({"consolidate": {}})
    prompt = load_consolidate_prompt()
    assert "quick_summary" in prompt


def test_consolidate_prompt_save_updates_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_consolidate_prompt("Saved prompt")
    from podscribe.config import load_project_config
    cfg = load_project_config()
    assert cfg["consolidate"]["prompt"] == "Saved prompt"
