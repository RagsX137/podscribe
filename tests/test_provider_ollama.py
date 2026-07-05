import json
import requests
from podscribe.providers.ollama import OllamaProvider


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

    monkeypatch.setattr(requests, "post", fake_post)
    p = OllamaProvider("qwen3.6")
    assert p.model_info()["model_info"]["llama.context_length"] == 4096
