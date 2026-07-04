from __future__ import annotations

import json
from pathlib import Path

from benchmarks.eval_cache import (
    cache_key,
    cache_path,
    list_cached,
    load_artifact,
    save_artifact,
)


def test_cache_key_distinguishes_runs():
    assert cache_key("public", "m1", "qwen3.6:27b", 0) != cache_key("public", "m1", "qwen3.6:27b", 1)


def test_cache_path_is_under_eval_data(tmp_path):
    p = cache_path("public", "m1", "qwen3.6:27b", 0, base=tmp_path)
    assert p.parent == tmp_path
    assert p.suffix == ".json"


def test_save_and_load_roundtrip(tmp_path):
    key = cache_key("public", "m1", "qwen3.6:27b", 0)
    data = {"text": "hello", "model": "qwen3.6:27b"}
    save_artifact(tmp_path / f"{key}.json", data)
    assert load_artifact(tmp_path / f"{key}.json") == data


def test_list_cached_returns_existing_keys(tmp_path):
    save_artifact(cache_path("public", "m1", "qwen3.6:27b", 0, base=tmp_path), {"text": "a"})
    save_artifact(cache_path("public", "m1", "qwen3.6:14b", 0, base=tmp_path), {"text": "b"})
    keys = list_cached(tmp_path)
    assert len(keys) == 2
    assert all(k.endswith(".json") for k in keys)
