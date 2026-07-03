"""Tests for pod config round-trip."""
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from podscribe.config import (
    get_effective_glossary,
    load_consolidate_prompt,
    load_last_pod,
    load_leadership_glossary,
    load_pod_config,
    load_project_config,
    save_consolidate_prompt,
    save_last_pod,
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


@pytest.fixture
def _pod():
    return Pod(name="sam-chen", base_path=Path("pods/sam-chen"))


def test_load_preserve_speakers_default_true(tmp_path, monkeypatch, _pod):
    monkeypatch.chdir(tmp_path)
    from podscribe.config import load_preserve_speakers
    assert load_preserve_speakers(_pod) is True


def test_load_preserve_speakers_project_level(tmp_path, monkeypatch, _pod):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "podscribe.yaml").write_text(
        "llm:\n  model: qwen3.6\n  prompt_template: x\n  preserve_speakers: false\n"
    )
    from podscribe.config import load_preserve_speakers
    assert load_preserve_speakers(_pod) is False


def test_load_preserve_speakers_pod_overrides_project(tmp_path, monkeypatch, _pod):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "podscribe.yaml").write_text(
        "llm:\n  model: qwen3.6\n  prompt_template: x\n  preserve_speakers: false\n"
    )
    _pod.llm = {"model": "qwen3.6", "prompt_template": "x", "preserve_speakers": True}
    from podscribe.config import load_preserve_speakers
    assert load_preserve_speakers(_pod) is True


def test_load_preserve_speakers_rejects_non_bool_at_pod_level(tmp_path, monkeypatch, _pod):
    monkeypatch.chdir(tmp_path)
    _pod.llm = {"model": "qwen3.6", "prompt_template": "x", "preserve_speakers": "yes"}
    from podscribe.config import load_preserve_speakers
    with pytest.raises(ValueError, match="must be a boolean"):
        load_preserve_speakers(_pod)


def test_load_preserve_speakers_rejects_non_bool_at_project_level(tmp_path, monkeypatch, _pod):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "podscribe.yaml").write_text(
        "llm:\n  model: qwen3.6\n  prompt_template: x\n  preserve_speakers: 1\n"
    )
    from podscribe.config import load_preserve_speakers
    with pytest.raises(ValueError, match="must be a boolean"):
        load_preserve_speakers(_pod)


def test_get_effective_glossary_caches(tmp_path, monkeypatch):
    """Second call within same mtime does not re-read leadership_team.yaml."""
    from podscribe.config import get_effective_glossary, _glossary_cache
    from podscribe.models import Pod
    import yaml

    monkeypatch.chdir(tmp_path)
    (tmp_path / "leadership_team.yaml").write_text(yaml.safe_dump({
        "glossary": [{"term": "Project Helios", "category": "project"}]
    }))
    pod = Pod(name="sam-chen", base_path=tmp_path / "pods" / "sam-chen")

    # Clear any pre-existing cache
    _glossary_cache["key"] = None

    with patch("podscribe.config.load_leadership_glossary") as mock_load:
        mock_load.return_value = [{"term": "Project Helios", "category": "project"}]
        first = get_effective_glossary(pod)
        second = get_effective_glossary(pod)
    assert first == second
    assert mock_load.call_count == 1


def test_cache_invalidates_on_mtime_change(tmp_path, monkeypatch):
    """Touching leadership_team.yaml with newer mtime invalidates the cache."""
    from podscribe.config import get_effective_glossary, _glossary_cache
    from podscribe.models import Pod
    import time

    monkeypatch.chdir(tmp_path)
    leadership = tmp_path / "leadership_team.yaml"
    leadership.write_text("glossary: []\n")
    pod = Pod(name="sam-chen", base_path=tmp_path / "pods" / "sam-chen")

    # Clear any pre-existing cache
    _glossary_cache["key"] = None

    # First call: empty glossary
    assert get_effective_glossary(pod) == []

    # Modify file with a clearly newer mtime
    time.sleep(0.05)
    leadership.write_text("glossary:\n  - term: NewTerm\n    category: project\n")

    # Cache should have invalidated; second call sees new content
    result = get_effective_glossary(pod)
    assert any(e["term"] == "NewTerm" for e in result)


def test_cache_handles_missing_leadership_file(tmp_path, monkeypatch):
    """Missing leadership_team.yaml → cache holds empty leadership."""
    from podscribe.config import get_effective_glossary, _glossary_cache
    from podscribe.models import Pod

    monkeypatch.chdir(tmp_path)
    pod = Pod(name="sam-chen", base_path=tmp_path / "pods" / "sam-chen")
    _glossary_cache["key"] = None

    # File does not exist
    assert not (tmp_path / "leadership_team.yaml").exists()
    assert get_effective_glossary(pod) == []
    # Subsequent call still returns empty (no crash)
    assert get_effective_glossary(pod) == []


def test_load_last_pod_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_last_pod() is None


def test_save_then_load_last_pod(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_last_pod("sam-chen")
    assert load_last_pod() == "sam-chen"


def test_last_pod_coexists_with_existing_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.config import save_project_config, load_project_config
    save_project_config({"llm": {"model": "qwen3.6:27b", "prompt_template": "x"}})
    save_last_pod("sam-chen")
    cfg = load_project_config()
    assert cfg["llm"]["model"] == "qwen3.6:27b"
    assert cfg["llm"]["prompt_template"] == "x"
    assert cfg["last_pod"] == "sam-chen"


def test_save_last_pod_rejects_empty_and_non_string(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="non-empty string"):
        save_last_pod("")
    with pytest.raises(ValueError, match="non-empty string"):
        save_last_pod(123)
    assert load_last_pod() is None  # nothing was written


# ── God model config ──────────────────────────────────────────────────────────

def test_load_god_model_from_god_key(tmp_path, monkeypatch):
    """god.model takes priority over llm.model."""
    monkeypatch.chdir(tmp_path)
    from podscribe.config import load_god_model
    (tmp_path / "podscribe.yaml").write_text(
        "god:\n  model: qwen3.6:35b-mlx\nllm:\n  model: qwen3.6:27b\n"
    )
    assert load_god_model() == "qwen3.6:35b-mlx"


def test_load_god_model_falls_back_to_llm(tmp_path, monkeypatch):
    """Falls back to llm.model when god.model is absent."""
    monkeypatch.chdir(tmp_path)
    from podscribe.config import load_god_model
    (tmp_path / "podscribe.yaml").write_text(
        "llm:\n  model: qwen3.6:27b\n"
    )
    assert load_god_model() == "qwen3.6:27b"


def test_load_god_model_returns_none_when_unconfigured(tmp_path, monkeypatch):
    """Returns None when neither god.model nor llm.model is set."""
    monkeypatch.chdir(tmp_path)
    from podscribe.config import load_god_model
    assert load_god_model() is None


def test_save_god_model_persists_under_god_key(tmp_path, monkeypatch):
    """save_god_model writes to god.model and doesn't clobber other keys."""
    monkeypatch.chdir(tmp_path)
    from podscribe.config import save_god_model, load_project_config
    (tmp_path / "podscribe.yaml").write_text(
        "llm:\n  model: qwen3.6:27b\n  prompt_template: x\n"
    )
    save_god_model("qwen3.6:35b-mlx")
    cfg = load_project_config()
    assert cfg["god"]["model"] == "qwen3.6:35b-mlx"
    assert cfg["llm"]["model"] == "qwen3.6:27b"  # unchanged


def test_save_god_model_rejects_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.config import save_god_model
    with pytest.raises(ValueError, match="non-empty string"):
        save_god_model("")


def test_glossary_cache_invalidates_on_pod_config_mtime(tmp_path, monkeypatch):
    """Editing pods/<name>/config.yaml's mtime invalidates the in-process
    glossary cache so _read_effective_glossary is re-invoked on the next call.

    R-11's scope is the cache *key*: it adds the pod-config mtime so a
    long-lived process (god-REPL) re-runs the read when the file is touched
    externally. It does NOT change the read source — `pod.glossary`
    (in-memory) remains the source of truth; callers that want disk-fresh
    glossary content must reload the Pod themselves. This test pins the
    cache-invalidation behaviour by wrapping `_read_effective_glossary`.
    """
    import os
    from unittest.mock import patch
    import podscribe.config as cfg
    from podscribe.storage import init_pod, save_pod_config

    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    pod.glossary = [{"term": "Anurag", "category": "person"}]
    save_pod_config(pod)

    cfg._glossary_cache["key"] = None

    with patch(
        "podscribe.config._read_effective_glossary",
        wraps=cfg._read_effective_glossary,
    ) as m_read:
        cfg.get_effective_glossary(pod)
        assert m_read.call_count == 1

        # Second call, same mtime — served from cache, no re-read
        cfg.get_effective_glossary(pod)
        assert m_read.call_count == 1

        # Bump the pod-config mtime (simulating an external edit)
        st = pod.config_path.stat().st_mtime
        os.utime(pod.config_path, (st + 5.0, st + 5.0))

        cfg.get_effective_glossary(pod)
        assert m_read.call_count == 2, (
            "pod-config mtime change must invalidate the glossary cache"
        )


def test_load_kt_prompt_returns_default_when_unset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.config import KT_PROMPT_DEFAULT, load_kt_prompt
    assert load_kt_prompt() == KT_PROMPT_DEFAULT
    assert "{{transcript}}" in KT_PROMPT_DEFAULT


def test_load_kt_prompt_reads_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import yaml
    from podscribe.config import load_kt_prompt
    (tmp_path / "podscribe.yaml").write_text(
        yaml.safe_dump({"kt": {"prompt": "custom {{transcript}}"}})
    )
    assert load_kt_prompt() == "custom {{transcript}}"
