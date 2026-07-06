"""Ollama provider: native /api/generate, /api/chat, /api/show."""
from __future__ import annotations

import json
import time
from typing import Callable, Optional

import requests

from .base import stream_with_retry

_INFO_TTL_SEC = 300
_info_cache: dict = {}  # {(base_url, model): (fetched_at, info)}


class OllamaProvider:
    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def generate(
        self, prompt: str, *, max_retries: int = 3,
        on_token: Callable[[str], None] = lambda t: None,
        on_stats: Callable[[dict], None] = lambda d: None,
        on_retry: Callable[[int, str], None] = lambda a, e: None,
    ) -> Optional[str]:
        payload = {"model": self.model, "prompt": prompt, "stream": True}

        def make():
            return requests.post(f"{self.base_url}/api/generate", json=payload,
                                 stream=True, timeout=1800)

        def consume(resp) -> str:
            parts, stats = [], {}
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if chunk.get("done"):
                    stats = {
                        "prompt_eval_count": chunk.get("prompt_eval_count", 0),
                        "eval_count": chunk.get("eval_count", 0),
                        "total_duration_ns": chunk.get("total_duration", 0),
                        "eval_duration_ns": chunk.get("eval_duration", 0),
                    }
                    break
                if "response" in chunk:
                    parts.append(chunk["response"])
                    on_token(chunk["response"])
            on_stats(stats)
            return "".join(parts)

        return stream_with_retry(make, consume, max_retries=max_retries, on_retry=on_retry)

    def chat(
        self, messages: list, tools: Optional[list] = None, *, max_retries: int = 3,
        on_token: Callable[[str], None] = lambda t: None,
        on_message: Callable[[dict], None] = lambda d: None,
        on_retry: Callable[[int, str], None] = lambda a, e: None,
    ) -> Optional[str]:
        payload: dict = {"model": self.model, "messages": messages,
                         "stream": True, "keep_alive": -1}
        if tools:
            payload["tools"] = tools

        def make():
            return requests.post(f"{self.base_url}/api/chat", json=payload,
                                 stream=True, timeout=1800)

        def consume(resp) -> str:
            parts, done_data, tool_calls = [], {}, []
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = chunk.get("message", {})
                if msg.get("content"):
                    parts.append(msg["content"])
                    on_token(msg["content"])
                if msg.get("tool_calls"):
                    tool_calls.extend(msg["tool_calls"])
                if chunk.get("done"):
                    done_data = dict(msg)
                    if tool_calls:
                        done_data["tool_calls"] = tool_calls
                    break
            if done_data:
                on_message(done_data)
            return "".join(parts)

        return stream_with_retry(make, consume, max_retries=max_retries, on_retry=on_retry)

    def reachable(self) -> bool:
        """True if the Ollama server answers /api/tags within 1s."""
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=1)
            return r.ok
        except requests.RequestException:
            return False

    def model_info(self) -> dict:
        key = (self.base_url, self.model)
        now = time.time()
        cached = _info_cache.get(key)
        if cached is not None and (now - cached[0]) < _INFO_TTL_SEC:
            return cached[1]
        try:
            r = requests.post(f"{self.base_url}/api/show", json={"name": self.model}, timeout=5)
            r.raise_for_status()
            info = r.json()
        except requests.RequestException:
            info = {}
        _info_cache[key] = (now, info)
        return info
