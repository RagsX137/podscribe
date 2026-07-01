"""Backup export/import for podscribe data."""
from __future__ import annotations

import os
import sys
import tarfile
from pathlib import Path
from typing import Iterator, Optional


_EXCLUDED_DIR_NAMES = {"__pycache__", ".pytest_cache", ".venv"}
_EXCLUDED_SUFFIXES = {".raw"}
_EXCLUDED_TOP_LEVEL = {".env"}


def create_export(out_path: Optional[Path] = None, *, include_audio: bool = False) -> Path:
    """Bundle pods/, leadership_team.yaml, and podscribe.yaml into a tar.gz.

    Excludes .raw files, .env, __pycache__/, .pytest_cache/, .venv/ by default.
    Set include_audio=True to bundle .raw (diarization source) for migration.
    If out_path is None or "-", write to sys.stdout.buffer.
    """
    members = list(_iter_export_members(include_audio=include_audio))

    if out_path is None or str(out_path) == "-":
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w:gz") as tar:
            for m in members:
                tar.add(m, arcname=str(m.relative_to(Path.cwd())))
        return Path("-")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_path, "w:gz") as tar:
        for m in members:
            tar.add(m, arcname=str(m.relative_to(Path.cwd())))
    return out_path


def _iter_export_members(*, include_audio: bool = False) -> Iterator[Path]:
    """Walk pods/, leadership_team.yaml, podscribe.yaml; yield paths to include."""
    cwd = Path.cwd()
    pods_dir = cwd / "pods"
    if pods_dir.exists():
        for path in sorted(pods_dir.rglob("*")):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(cwd).parts
            if any(part in _EXCLUDED_DIR_NAMES for part in rel_parts):
                continue
            if path.suffix in _EXCLUDED_SUFFIXES and not include_audio:
                continue
            yield path
    for fname in ("leadership_team.yaml", "podscribe.yaml"):
        fpath = cwd / fname
        if fpath.exists():
            yield fpath


def import_archive(
    archive_path: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    """Extract a podscribe export tarball into the current directory.

    Default: refuse to overwrite existing pods. --force: overwrite.
    --dry-run: print what would happen, do not write.

    Skips root-level podscribe.yaml: project LLM config is intentionally
    not migrated on import (use `podscribe config llm set` instead).
    """
    pods_in_tar = set()
    other_members = []
    project_yaml_in_tar = False

    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            # Reject path-traversal up front
            target = (Path.cwd() / member.name).resolve()
            if (
                target != Path.cwd().resolve()
                and not str(target).startswith(str(Path.cwd().resolve()) + os.sep)
            ):
                raise ValueError(f"Unsafe path in tarball: {member.name}")
            # Reject non-regular entries
            if not member.isreg() and not member.isdir():
                raise ValueError(
                    f"Unsafe entry type in tarball: {member.name!r} (type={member.type})"
                )

            parts = Path(member.name).parts
            if parts and parts[0] == "pods":
                if len(parts) >= 3:
                    # Real pod: pods/<name>/<something>
                    pods_in_tar.add(parts[1])
                # else: top-level file in pods/ (e.g. global meetings.csv) — not a pod
            elif member.name == "podscribe.yaml":
                project_yaml_in_tar = True
            else:
                other_members.append(member)

    pods_dir = Path("pods")
    existing = {p.name for p in pods_dir.iterdir()} if pods_dir.exists() else set()
    conflicts = pods_in_tar & existing
    if conflicts and not force:
        print(
            f"Refusing to overwrite existing pods: {sorted(conflicts)}.\n"
            f"Re-run with --force to replace them.",
            file=sys.stderr,
        )
        return 1

    if dry_run:
        print(f"Would import: {sorted(pods_in_tar)}")
        if other_members:
            print(f"Would also import: {[m.name for m in other_members]}")
        if project_yaml_in_tar:
            print("Would skip root-level podscribe.yaml (project config not migrated)")
        return 0

    with tarfile.open(archive_path, "r:gz") as tar:
        _safe_extract(tar, path=Path.cwd(), skip_names={"podscribe.yaml"})
    print(f"Imported: {sorted(pods_in_tar)}")
    if project_yaml_in_tar:
        print(
            "Note: skipped root-level podscribe.yaml "
            "(use `podscribe config llm set` to update).",
            file=sys.stderr,
        )
    return 0


def _safe_extract(
    tar: tarfile.TarFile,
    path: Path = Path("."),
    skip_names: set | None = None,
) -> None:
    """Extract every member with safety checks.

    Rejects:
    - path traversal (resolved path outside extract root)
    - symlinks, hardlinks, devices, fifos (defense in depth)

    Optionally skips named members (e.g. root-level `podscribe.yaml` is
    not migrated on import — project LLM config is host-specific).

    Python 3.12 added `tar.extractall(filter='data')` for this purpose,
    but the project supports Python 3.10+. This function is the manual
    equivalent.
    """
    cwd_resolved = path.resolve()
    safe_members = []
    for member in tar.getmembers():
        if skip_names and member.name in skip_names:
            continue
        if not member.isreg() and not member.isdir():
            raise ValueError(
                f"Unsafe entry type in tarball: {member.name!r} (type={member.type})"
            )
        target = (path / member.name).resolve()
        if target != cwd_resolved and not str(target).startswith(str(cwd_resolved) + os.sep):
            raise ValueError(f"Unsafe path in tarball: {member.name}")
        safe_members.append(member)
    tar.extractall(members=safe_members, path=path)
