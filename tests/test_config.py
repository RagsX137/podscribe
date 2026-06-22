"""Tests for pod config round-trip."""
from pathlib import Path

import pytest
import yaml

from podscribe.config import load_pod_config, save_pod_config
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
