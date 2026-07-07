import numpy as np
import podscribe.transcriber as T
from podscribe.transcriber import Transcriber


class _StubBackend:
    def __init__(self, repo_id):
        self.model_name = repo_id
        self.seen = None

    def transcribe(self, audio, sample_rate=16000, **kwargs):
        self.seen = kwargs
        return [{"start": 0.0, "end": 1.0, "text": "ok"}]


def test_facade_resolves_and_delegates(monkeypatch):
    monkeypatch.setattr(T, "resolve_backend", lambda model, backend: ("whisper-faster", "large-v3-turbo"))
    made = {}

    def fake_make(backend_id, repo_id):
        made["args"] = (backend_id, repo_id)
        return _StubBackend(repo_id)

    monkeypatch.setattr(T, "_make_backend", fake_make)
    t = Transcriber(model="large-v3-turbo", backend="auto")
    assert t.backend_id == "whisper-faster"
    assert t.model_name == "large-v3-turbo"
    out = t.transcribe(np.zeros(16000, dtype=np.float32), initial_prompt="ctx")
    assert out == [{"start": 0.0, "end": 1.0, "text": "ok"}]
    assert made["args"] == ("whisper-faster", "large-v3-turbo")


def test_make_backend_unknown_id_raises():
    import pytest
    with pytest.raises(ValueError, match="unknown backend"):
        T._make_backend("nope", "repo")
