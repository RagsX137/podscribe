"""Tests for podscribe.export."""
import tarfile
from pathlib import Path

import pytest

from podscribe.export import create_export, _iter_export_members


def _make_pod_with_content(base: Path, pod_name: str) -> None:
    pod_dir = base / "pods" / pod_name
    pod_dir.mkdir(parents=True, exist_ok=True)
    (pod_dir / "config.yaml").write_text(f"name: {pod_name}\n")
    tdir = pod_dir / "transcripts" / "22-JUN-2026"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "2026-06-22-143000-sam-chen.md").write_text("# Meeting\n[00:00:00] hello\n")
    (tdir / "2026-06-22-143000-sam-chen.json").write_text('{"id": "x"}')
    (tdir / "2026-06-22-143000-sam-chen.raw").write_bytes(b"\x00" * 100)


def test_export_creates_tarball(tmp_path, monkeypatch):
    """create_export writes a gzip tarball at out_path."""
    monkeypatch.chdir(tmp_path)
    _make_pod_with_content(tmp_path, "sam-chen")
    out = tmp_path / "out.tar.gz"
    result = create_export(out)
    assert result == out
    assert out.exists()
    # Magic bytes for gzip: 0x1f 0x8b
    assert out.read_bytes()[:2] == b"\x1f\x8b"


def test_export_excludes_raw_files(tmp_path, monkeypatch):
    """Tarball member list does not include .raw files."""
    monkeypatch.chdir(tmp_path)
    _make_pod_with_content(tmp_path, "sam-chen")
    out = tmp_path / "out.tar.gz"
    create_export(out)
    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    assert not any(n.endswith(".raw") for n in names)
    assert any(n.endswith(".md") for n in names)
    assert any(n.endswith(".json") for n in names)


def test_export_excludes_pycache_and_venv(tmp_path, monkeypatch):
    """Tarball excludes __pycache__, .pytest_cache, .venv."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pods" / "sam-chen").mkdir(parents=True)
    (tmp_path / "pods" / "sam-chen" / "config.yaml").write_text("name: sam-chen\n")
    pycache = tmp_path / "pods" / "sam-chen" / "__pycache__"
    pycache.mkdir()
    (pycache / "foo.pyc").write_bytes(b"\x00")
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("")

    out = tmp_path / "out.tar.gz"
    create_export(out)
    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    assert not any("__pycache__" in n for n in names)
    assert not any(".venv" in n for n in names)
