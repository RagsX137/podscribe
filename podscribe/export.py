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


def create_export(out_path: Optional[Path] = None) -> Path:
    """Bundle pods/, leadership_team.yaml, and podscribe.yaml into a tar.gz.

    Excludes .raw files, .env, __pycache__/, .pytest_cache/, .venv/.
    If out_path is None or "-", write to sys.stdout.buffer.
    """
    members = list(_iter_export_members())

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


def _iter_export_members() -> Iterator[Path]:
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
            if path.suffix in _EXCLUDED_SUFFIXES:
                continue
            yield path
    for fname in ("leadership_team.yaml", "podscribe.yaml"):
        fpath = cwd / fname
        if fpath.exists():
            yield fpath
