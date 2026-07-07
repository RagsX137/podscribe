import sys
import types
import numpy as np
from podscribe.backends.whisper_faster import WhisperFasterBackend


class _FakeSegment:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


def _install_fake_faster(monkeypatch, captured, *, fail_cuda=False):
    fake = types.ModuleType("faster_whisper")

    class WhisperModel:
        def __init__(self, model, device="auto", compute_type="default", **kw):
            if fail_cuda and device == "cuda":
                raise RuntimeError("no cuda")
            captured["init"] = (model, device, compute_type)

        def transcribe(self, audio, **kwargs):
            captured["transcribe_kwargs"] = kwargs
            segs = [_FakeSegment(0.0, 1.0, " hi "), _FakeSegment(1.0, 2.0, "")]
            return iter(segs), types.SimpleNamespace(language="en")

    fake.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)


def test_transcribe_normalizes_and_forwards_prompt(monkeypatch):
    captured = {}
    _install_fake_faster(monkeypatch, captured)
    backend = WhisperFasterBackend("large-v3-turbo")
    out = backend.transcribe(np.zeros(16000, dtype=np.float32), initial_prompt="ctx")
    assert out == [{"start": 0.0, "end": 1.0, "text": "hi"}]
    assert captured["init"][0] == "large-v3-turbo"
    assert captured["transcribe_kwargs"].get("initial_prompt") == "ctx"


def test_falls_back_to_cpu_when_cuda_unavailable(monkeypatch):
    captured = {}
    _install_fake_faster(monkeypatch, captured, fail_cuda=True)
    backend = WhisperFasterBackend("base")
    backend.transcribe(np.zeros(16000, dtype=np.float32))
    assert captured["init"][1] == "cpu"
    assert captured["init"][2] == "int8"


def test_empty_audio_returns_empty(monkeypatch):
    _install_fake_faster(monkeypatch, {})
    backend = WhisperFasterBackend("base")
    assert backend.transcribe(np.array([], dtype=np.float32)) == []
