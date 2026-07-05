import sys
import types
import numpy as np
from podscribe.backends.parakeet_mlx import ParakeetMLXBackend


def _install_fake_parakeet_mlx(monkeypatch, captured):
    fake = types.ModuleType("parakeet_mlx")

    class _Sentence:
        def __init__(self, start, end, text):
            self.start, self.end, self.text = start, end, text

    class _Result:
        sentences = [_Sentence(0.0, 1.0, " hi "), _Sentence(1.0, 2.0, "")]

    class _Model:
        def transcribe(self, path, **kw):
            captured["path"] = path
            return _Result()

    def from_pretrained(repo, **kw):
        captured["repo"] = repo
        return _Model()

    fake.from_pretrained = from_pretrained
    monkeypatch.setitem(sys.modules, "parakeet_mlx", fake)


def test_transcribe_normalizes_sentences(monkeypatch):
    captured = {}
    _install_fake_parakeet_mlx(monkeypatch, captured)
    backend = ParakeetMLXBackend("mlx-community/parakeet-tdt-0.6b-v2")
    out = backend.transcribe(np.zeros(16000, dtype=np.float32), initial_prompt="ignored")
    assert out == [{"start": 0.0, "end": 1.0, "text": "hi"}]
    assert captured["repo"] == "mlx-community/parakeet-tdt-0.6b-v2"


def test_empty_audio_returns_empty(monkeypatch):
    _install_fake_parakeet_mlx(monkeypatch, {})
    backend = ParakeetMLXBackend("mlx-community/parakeet-tdt-0.6b-v2")
    assert backend.transcribe(np.array([], dtype=np.float32)) == []
