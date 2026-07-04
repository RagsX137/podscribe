from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.eval_manifest import Contestant, Manifest, SuiteEntry, load_manifest, verify_contestants


MANIFEST_YAML = """\
public:
  - id: yt-sig-k8s-001
    source: youtube
    video_id: dQw4w9WgXcQ
    title: "Kubernetes SIG: Working Session 1"
    license: "CC-BY"
    duration_sec: 900
    start: "00:05:00"
    end: "00:20:00"
    expected_speakers: 4
private:
  - id: fso-2026-06-22
    pod: fso
    meeting_prefix: "2026-06-22-1438"
contestants:
  - tag: qwen3.6:27b
    digest: sha256:abc123
    role: champion
  - tag: qwen3.6:14b
    digest: sha256:def456
    role: challenger
"""


def test_load_manifest_parses_public_and_private(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (Path("benchmarks") / "eval_manifest.yaml").parent.mkdir(parents=True)
    (Path("benchmarks") / "eval_manifest.yaml").write_text(MANIFEST_YAML)
    m = load_manifest()
    assert isinstance(m, Manifest)
    assert len(m.public) == 1
    assert m.public[0].video_id == "dQw4w9WgXcQ"
    assert m.public[0].start == "00:05:00"
    assert len(m.private) == 1
    assert m.private[0].pod == "fso"
    assert len(m.contestants) == 2
    champ = [c for c in m.contestants if c.role == "champion"]
    assert champ and champ[0].tag == "qwen3.6:27b"


def test_verify_contestants_digest_mismatch_fails_fast(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    import benchmarks.eval_manifest as em

    def fake_tags():
        return {"qwen3.6:27b": "sha256:DIFFERENT", "qwen3.6:14b": "sha256:def456"}

    monkeypatch.setattr(em, "_fetch_installed_digests", fake_tags)
    contestants = [
        Contestant(tag="qwen3.6:27b", digest="sha256:abc123", role="champion"),
        Contestant(tag="qwen3.6:14b", digest="sha256:def456", role="challenger"),
    ]
    with pytest.raises(SystemExit) as exc:
        verify_contestants(contestants)
    assert "qwen3.6:27b" in str(exc.value)
    assert "pull" in str(exc.value).lower()
