import json
import requests
from podscribe.providers.ollama import OllamaProvider
from podscribe.providers import ollama as ollama_mod


class _StreamResp:
    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(str(self.status_code)); err.response = self
            raise err

    def iter_lines(self, decode_unicode=False):
        for ln in self._lines:
            yield ln


def test_generate_streams_tokens_and_stats(monkeypatch):
    lines = [
        json.dumps({"response": "Hel"}),
        json.dumps({"response": "lo"}),
        json.dumps({"done": True, "prompt_eval_count": 3, "eval_count": 2,
                    "total_duration": 10, "eval_duration": 5}),
    ]
    captured = {}

    def fake_post(url, json=None, stream=False, timeout=None):
        captured["url"] = url
        captured["body"] = json
        return _StreamResp(lines)

    monkeypatch.setattr(requests, "post", fake_post)
    tokens, stats = [], {}
    p = OllamaProvider("qwen3.6", base_url="http://box:11434")
    out = p.generate("hi", on_token=tokens.append, on_stats=lambda s: stats.update(s))
    assert out == "Hello"
    assert tokens == ["Hel", "lo"]
    assert stats["eval_count"] == 2
    assert captured["url"] == "http://box:11434/api/generate"
    assert captured["body"]["model"] == "qwen3.6"


def test_generate_raises_and_retries_on_error_frame(monkeypatch):
    """A mid-stream {"error": ...} frame must trigger a retry, not a silent empty result."""
    monkeypatch.setattr("time.sleep", lambda s: None)
    error_line = json.dumps({"error": "model runner has unexpectedly stopped"})
    calls = []

    def fake_post(url, json=None, stream=False, timeout=None):
        calls.append(1)
        return _StreamResp([error_line])

    monkeypatch.setattr(requests, "post", fake_post)
    retries = []
    p = OllamaProvider("qwen3.6")
    out = p.generate("hi", max_retries=2, on_retry=lambda a, e: retries.append(e))
    assert out is None
    assert len(calls) == 2  # retried once before giving up
    assert "unexpectedly stopped" in retries[0]


def test_chat_raises_and_retries_on_error_frame(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    error_line = json.dumps({"error": "model runner has unexpectedly stopped"})
    calls = []

    def fake_post(url, json=None, stream=False, timeout=None):
        calls.append(1)
        return _StreamResp([error_line])

    monkeypatch.setattr(requests, "post", fake_post)
    p = OllamaProvider("qwen3.6")
    out = p.chat([{"role": "user", "content": "hi"}], max_retries=2)
    assert out is None
    assert len(calls) == 2


def test_reachable_hits_configured_base_url(monkeypatch):
    """reachable() must probe the provider's own base_url, not localhost."""
    captured = {}

    class _OK:
        ok = True

    def fake_get(url, timeout=None):
        captured["url"] = url
        return _OK()

    monkeypatch.setattr(requests, "get", fake_get)
    p = OllamaProvider("qwen3.6", base_url="http://box:11434")
    assert p.reachable() is True
    assert captured["url"] == "http://box:11434/api/tags"


def test_reachable_false_on_connection_error(monkeypatch):
    def fake_get(url, timeout=None):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "get", fake_get)
    assert OllamaProvider("m", base_url="http://box:11434").reachable() is False


def test_reachable_detail_surfaces_connection_error_reason(monkeypatch):
    def fake_get(url, timeout=None):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "get", fake_get)
    ok, reason = OllamaProvider("m", base_url="http://box:11434").reachable_detail()
    assert ok is False
    assert "unreachable" in reason


def test_chat_accumulates_tool_calls(monkeypatch):
    lines = [
        json.dumps({"message": {"content": "thinking"}}),
        json.dumps({"message": {"tool_calls": [{"function": {"name": "f", "arguments": "{}"}}]},
                    "done": True}),
    ]

    def fake_post(url, json=None, stream=False, timeout=None):
        return _StreamResp(lines)

    monkeypatch.setattr(requests, "post", fake_post)
    got = {}
    p = OllamaProvider("qwen3.6")
    out = p.chat([{"role": "user", "content": "x"}], tools=[{"type": "function"}],
                 on_message=lambda m: got.update(m))
    assert out == "thinking"
    assert got["tool_calls"][0]["function"]["name"] == "f"


def test_model_info_hits_show_endpoint(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        assert url == "http://localhost:11434/api/show"
        class R:
            def raise_for_status(self): pass
            def json(self): return {"model_info": {"llama.context_length": 4096}}
        return R()

    monkeypatch.setattr(ollama_mod, "_info_cache", {})
    monkeypatch.setattr(requests, "post", fake_post)
    p = OllamaProvider("qwen3.6")
    assert p.model_info()["model_info"]["llama.context_length"] == 4096
