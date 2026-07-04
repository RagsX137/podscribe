"""JSON artifact cache for the eval harness.

All artifacts are JSON keyed by (suite, meeting, model, run). The cache
directory is benchmarks/eval_data/ (gitignored; added in Task 3). A failed
overnight generate resumes where it died because generate skips existing
keys, and save_artifact writes are crash-safe via tempfile + os.replace.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

DEFAULT_BASE = Path("benchmarks/eval_data")


def cache_key(suite: str, meeting: str, model: str, run: int) -> str:
    safe = model.replace(":", "_").replace("/", "_")
    return f"{suite}__{meeting}__{safe}__run{run}"


def cache_path(suite: str, meeting: str, model: str, run: int, base: Path = DEFAULT_BASE) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{cache_key(suite, meeting, model, run)}.json"


def save_artifact(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_artifact(path: Path) -> dict:
    return json.loads(path.read_text())


def list_cached(base: Path = DEFAULT_BASE) -> list:
    if not base.exists():
        return []
    return sorted(p.name for p in base.glob("*.json"))
