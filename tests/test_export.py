"""Tests for podscribe.export."""
import io
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


# ── Import (Task 10) ─────────────────────────────────────────────


def test_import_refuses_overwrite_without_force(tmp_path, monkeypatch, capsys):
    """Existing pod → import errors out without --force."""
    from podscribe.storage import init_pod
    from podscribe.export import create_export, import_archive

    # Build a tarball in /tmp
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.chdir(src)
    _make_pod_with_content(src, "sam-chen")
    tar = tmp_path / "out.tar.gz"
    create_export(tar)

    # Set up a destination with an existing pod
    dst = tmp_path / "dst"
    dst.mkdir()
    monkeypatch.chdir(dst)
    init_pod("sam-chen")
    rc = import_archive(tar)
    assert rc == 1
    captured = capsys.readouterr()
    assert "Refusing" in captured.err
    assert "sam-chen" in captured.err


def test_import_force_overwrites(tmp_path, monkeypatch):
    """--force replaces the existing pod."""
    from podscribe.storage import init_pod, pod_exists
    from podscribe.export import create_export, import_archive

    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.chdir(src)
    _make_pod_with_content(src, "sam-chen")
    tar = tmp_path / "out.tar.gz"
    create_export(tar)

    dst = tmp_path / "dst"
    dst.mkdir()
    monkeypatch.chdir(dst)
    init_pod("sam-chen")  # Pre-existing

    rc = import_archive(tar, force=True)
    assert rc == 0
    assert pod_exists("sam-chen")


def test_import_dry_run_no_writes(tmp_path, monkeypatch, capsys):
    """--dry-run prints what would happen, no files change."""
    from podscribe.export import create_export, import_archive

    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.chdir(src)
    _make_pod_with_content(src, "sam-chen")
    tar = tmp_path / "out.tar.gz"
    create_export(tar)

    dst = tmp_path / "dst"
    dst.mkdir()
    monkeypatch.chdir(dst)
    pods_before = sorted((dst / "pods").glob("*")) if (dst / "pods").exists() else []
    rc = import_archive(tar, dry_run=True)
    assert rc == 0
    captured = capsys.readouterr()
    assert "Would import" in captured.out
    pods_after = sorted((dst / "pods").glob("*")) if (dst / "pods").exists() else []
    assert pods_before == pods_after


def test_import_rejects_path_traversal(tmp_path, monkeypatch):
    """Tarball with a path-traversal member is rejected outright."""
    import tarfile
    from podscribe.export import import_archive

    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "evil.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo(name="pods/../../etc/passwd")
        data = b"evil"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    with pytest.raises(ValueError, match="Unsafe path"):
        import_archive(bad)


def test_export_import_roundtrip(tmp_path, monkeypatch):
    """Create a tarball, delete the pod, import it back, verify content."""
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting, pod_exists, load_pod
    from podscribe.models import Segment
    from datetime import datetime
    from podscribe.export import create_export, import_archive

    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.chdir(src)
    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "Project Helios is on track"))
    finalize_meeting(meeting)
    tar = tmp_path / "out.tar.gz"
    create_export(tar)

    # Wipe the pod
    import shutil
    shutil.rmtree(src / "pods" / "sam-chen")
    assert not pod_exists("sam-chen")

    # Re-import
    rc = import_archive(tar)
    assert rc == 0
    assert pod_exists("sam-chen")
    reloaded = load_pod("sam-chen")
    assert reloaded.name == "sam-chen"


def test_import_skips_root_level_podscribe_yaml(tmp_path, monkeypatch, capsys):
    """Root-level podscribe.yaml in a tarball is skipped on import."""
    import tarfile
    import io
    from podscribe.export import import_archive

    monkeypatch.chdir(tmp_path)
    tar = tmp_path / "out.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        info = tarfile.TarInfo(name="pods/sam-chen/config.yaml")
        data = b"name: sam-chen\n"
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
        info2 = tarfile.TarInfo(name="podscribe.yaml")
        data2 = b"llm:\n  model: gemma4\n"
        info2.size = len(data2)
        t.addfile(info2, io.BytesIO(data2))

    (tmp_path / "podscribe.yaml").write_text("llm:\n  model: qwen3.6:27b\n")

    rc = import_archive(tar)
    assert rc == 0
    assert (tmp_path / "podscribe.yaml").read_text() == "llm:\n  model: qwen3.6:27b\n"
    captured = capsys.readouterr()
    assert "podscribe.yaml" in captured.err
    assert (tmp_path / "pods" / "sam-chen" / "config.yaml").exists()


def test_import_rejects_symlink_member(tmp_path, monkeypatch):
    """Symlink members are rejected."""
    import tarfile
    from podscribe.export import import_archive

    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "evil.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo(name="pods/sam-chen/escape")
        info.type = tarfile.SYMTYPE
        info.linkname = "../.."
        tar.addfile(info)

    with pytest.raises(ValueError, match="Unsafe"):
        import_archive(bad)


def test_cmd_import_path_traversal_clean_error(tmp_path, monkeypatch, capsys):
    """cmd_import catches ValueError from path traversal and prints clean error."""
    import tarfile
    from podscribe.cli import cmd_import, build_parser

    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "evil.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo(name="pods/../../etc/passwd")
        data = b"evil"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    args = build_parser().parse_args(["import", str(bad)])
    rc = cmd_import(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "Unsafe path" in captured.err
    assert "Traceback" not in captured.err


def test_cmd_import_malformed_tarball_clean_error(tmp_path, monkeypatch, capsys):
    """cmd_import catches tarfile.ReadError and prints clean error."""
    from podscribe.cli import cmd_import, build_parser

    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "not-a-tarball.tar.gz"
    bad.write_bytes(b"this is not a gzip file")

    args = build_parser().parse_args(["import", str(bad)])
    rc = cmd_import(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "Cannot read tarball" in captured.err
    assert "Traceback" not in captured.err

