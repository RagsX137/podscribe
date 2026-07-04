from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from benchmarks.bench_enhance import run_once


def _streaming_response(chunks, final_stats=None):
    lines = [json.dumps({"response": c, "done": False}) for c in chunks]
    final = {"response": "", "done": True, **(final_stats or {})}
    lines.append(json.dumps(final))
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.iter_lines = MagicMock(return_value=iter(lines))
    resp.status_code = 200
    return resp


def test_run_once_keeps_full_response_text():
    chunks = ["alpha ", "bravo ", "charlie"]
    with patch("benchmarks.bench_enhance.requests.post", return_value=_streaming_response(chunks, {"total_duration": 1_000_000_000})):
        result = run_once("qwen3.6:27b", "ignored prompt", label="test", quiet=True)
    assert result["response_text"] == "alpha bravo charlie"
    assert result["response_preview"] == "alpha bravo charlie"[:200]
    assert result["response_len"] == len("alpha bravo charlie")
