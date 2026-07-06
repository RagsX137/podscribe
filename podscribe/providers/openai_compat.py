"""OpenAI-compatible provider (/v1/chat/completions) with SSE streaming.

Covers OpenAI, Groq, OpenRouter, DeepSeek, GLM, Kimi, Minimax, Qwen, LM Studio,
vLLM, and Ollama's /v1 shim — anything speaking the OpenAI chat schema.
"""
from __future__ import annotations

import json
from typing import Callable, Optional

import requests

from .base import stream_with_retry


class OpenAIProvider:
    def __init__(self, model: str, base_url: str, api_key: Optional[str] = None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post_chat(self, messages: list, tools: Optional[list]):
        payload: dict = {"model": self.model, "messages": messages, "stream": True}
        if tools:
            payload["tools"] = tools
        return requests.post(
            f"{self.base_url}/chat/completions",
            json=payload, headers=self._headers(), stream=True, timeout=1800,
        )

    @staticmethod
    def _consume(resp, on_token, on_message) -> str:
        parts: list = []
        tool_acc: dict = {}
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("data:"):
                data = line[len("data:"):].strip()
            else:
                data = line.strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or [{}]
            delta = choices[0].get("delta", {})
            if delta.get("content"):
                parts.append(delta["content"])
                on_token(delta["content"])
            for tc in delta.get("tool_calls", []) or []:
                idx = tc.get("index", 0)
                slot = tool_acc.setdefault(idx, {"function": {"name": "", "arguments": ""}})
                fn = tc.get("function", {})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                slot.setdefault("type", tc.get("type", "function"))
                if fn.get("name"):
                    slot["function"]["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
        message = {"role": "assistant", "content": "".join(parts)}
        if tool_acc:
            message["tool_calls"] = [tool_acc[i] for i in sorted(tool_acc)]
        on_message(message)
        return "".join(parts)

    def generate(
        self, prompt: str, *, max_retries: int = 3,
        on_token: Callable[[str], None] = lambda t: None,
        on_stats: Callable[[dict], None] = lambda d: None,
        on_retry: Callable[[int, str], None] = lambda a, e: None,
    ) -> Optional[str]:
        # No on_stats: OpenAI-style streaming returns no token-usage numbers,
        # so firing it would emit a misleading all-zero metrics line (and, on
        # failure, a spurious "done" line before the error). Ollama fires
        # on_stats only on the success/done chunk; matched here by staying silent.
        messages = [{"role": "user", "content": prompt}]
        return stream_with_retry(
            lambda: self._post_chat(messages, None),
            lambda r: self._consume(r, on_token, lambda m: None),
            max_retries=max_retries, on_retry=on_retry,
        )

    def chat(
        self, messages: list, tools: Optional[list] = None, *, max_retries: int = 3,
        on_token: Callable[[str], None] = lambda t: None,
        on_message: Callable[[dict], None] = lambda d: None,
        on_retry: Callable[[int, str], None] = lambda a, e: None,
    ) -> Optional[str]:
        return stream_with_retry(
            lambda: self._post_chat(messages, tools),
            lambda r: self._consume(r, on_token, on_message),
            max_retries=max_retries, on_retry=on_retry,
        )

    def model_info(self) -> dict:
        return {}
