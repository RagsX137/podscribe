from podscribe import llm


class _FakeProvider:
    model = "m"

    def __init__(self):
        self.generate_called = self.chat_called = False

    def generate(self, prompt, *, max_retries=3, on_token=lambda t: None,
                 on_stats=lambda d: None, on_retry=lambda a, e: None):
        self.generate_called = True
        on_token("tok"); on_stats({"eval_count": 1})
        return "generated"

    def chat(self, messages, tools=None, *, max_retries=3, on_token=lambda t: None,
             on_message=lambda d: None, on_retry=lambda a, e: None):
        self.chat_called = True
        on_message({"role": "assistant", "content": "chatted"})
        return "chatted"

    def model_info(self):
        return {"model_info": {"llama.context_length": 8192}}


def test_enhance_transcript_uses_given_provider():
    fp = _FakeProvider()
    stats = {}
    out = llm.enhance_transcript("m", "prompt", provider=fp, on_stats=lambda s: stats.update(s))
    assert out == "generated"
    assert fp.generate_called
    assert stats["eval_count"] == 1


def test_chat_stream_uses_given_provider():
    fp = _FakeProvider()
    out = llm.chat_stream("m", [{"role": "user", "content": "x"}], provider=fp)
    assert out == "chatted"
    assert fp.chat_called


def test_model_info_uses_given_provider():
    fp = _FakeProvider()
    assert llm.ollama_model_info("m", provider=fp)["model_info"]["llama.context_length"] == 8192


def test_default_provider_is_localhost_ollama(monkeypatch):
    from podscribe.providers import ollama as ollama_mod

    built = {}
    from podscribe.providers.ollama import OllamaProvider

    def spy(model):
        built["model"] = model
        p = OllamaProvider(model)
        return p

    monkeypatch.setattr(llm, "OllamaProvider", spy)
    monkeypatch.setattr(ollama_mod, "_info_cache", {})
    import requests

    class _R:
        def raise_for_status(self): pass
        def json(self): return {}
    monkeypatch.setattr(requests, "post", lambda *a, **k: _R())
    llm.ollama_model_info("qwen3.6")
    assert built["model"] == "qwen3.6"
