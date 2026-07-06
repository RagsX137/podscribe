import json
import requests
from podscribe.providers.openai_compat import OpenAIProvider


class _SSEResp:
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


def _delta(content=None, tool_calls=None):
    d = {}
    if content is not None:
        d["content"] = content
    if tool_calls is not None:
        d["tool_calls"] = tool_calls
    return "data: " + json.dumps({"choices": [{"delta": d}]})


def test_generate_maps_prompt_to_single_user_message(monkeypatch):
    lines = [_delta("He"), _delta("llo"), "data: [DONE]"]
    captured = {}

    def fake_post(url, json=None, headers=None, stream=False, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        return _SSEResp(lines)

    monkeypatch.setattr(requests, "post", fake_post)
    tokens = []
    p = OpenAIProvider("deepseek-chat", base_url="https://api.deepseek.com/v1", api_key="sk-x")
    out = p.generate("hi", on_token=tokens.append)
    assert out == "Hello"
    assert tokens == ["He", "llo"]
    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-x"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["body"]["stream"] is True


def test_chat_emits_tool_calls_on_message(monkeypatch):
    tc = [{"index": 0, "id": "c1", "type": "function",
           "function": {"name": "f", "arguments": "{}"}}]
    lines = [_delta("ok"), _delta(tool_calls=tc), "data: [DONE]"]

    def fake_post(url, json=None, headers=None, stream=False, timeout=None):
        return _SSEResp(lines)

    monkeypatch.setattr(requests, "post", fake_post)
    got = {}
    p = OpenAIProvider("gpt-4o", base_url="https://api.openai.com/v1", api_key="k")
    out = p.chat([{"role": "user", "content": "x"}], tools=[{"type": "function"}],
                 on_message=lambda m: got.update(m))
    assert out == "ok"
    assert got["tool_calls"][0]["function"]["name"] == "f"


def test_chat_keeps_indexless_tool_calls_separate(monkeypatch):
    """Servers that omit `index` must not collapse distinct calls into slot 0."""
    tc1 = [{"id": "c1", "type": "function",
            "function": {"name": "search", "arguments": "{}"}}]
    tc2 = [{"id": "c2", "type": "function",
            "function": {"name": "glossary", "arguments": "{}"}}]
    lines = [_delta(tool_calls=tc1), _delta(tool_calls=tc2), "data: [DONE]"]

    def fake_post(url, json=None, headers=None, stream=False, timeout=None):
        return _SSEResp(lines)

    monkeypatch.setattr(requests, "post", fake_post)
    got = {}
    p = OpenAIProvider("m", base_url="http://x/v1")
    p.chat([{"role": "user", "content": "x"}], tools=[{"type": "function"}],
           on_message=lambda m: got.update(m))
    names = [t["function"]["name"] for t in got["tool_calls"]]
    assert names == ["search", "glossary"]


def test_reachable_true_on_any_http_response(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return _SSEResp([], status=401)  # server up but unauthorized

    monkeypatch.setattr(requests, "get", fake_get)
    p = OpenAIProvider("m", base_url="https://api.example.com/v1", api_key="k")
    assert p.reachable() is True


def test_reachable_false_on_connection_error(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "get", fake_get)
    p = OpenAIProvider("m", base_url="https://api.example.com/v1")
    assert p.reachable() is False


def test_no_api_key_omits_auth_header(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, stream=False, timeout=None):
        captured["headers"] = headers
        return _SSEResp(["data: [DONE]"])

    monkeypatch.setattr(requests, "post", fake_post)
    p = OpenAIProvider("local-model", base_url="http://localhost:1234/v1")
    p.generate("hi")
    assert "Authorization" not in captured["headers"]
