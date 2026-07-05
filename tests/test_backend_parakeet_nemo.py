import sys
import types

import numpy as np

from podscribe.backends.parakeet_nemo import ParakeetNeMoBackend


def _install_fake_nemo(monkeypatch, captured):
    nemo = types.ModuleType("nemo")
    collections = types.ModuleType("nemo.collections")
    asr = types.ModuleType("nemo.collections.asr")

    class _Hyp:
        timestamp = {"segment": [
            {"start": 0.0, "end": 1.0, "segment": " hi "},
            {"start": 1.0, "end": 2.0, "segment": ""},
        ]}

    class ASRModel:
        @staticmethod
        def from_pretrained(model_name):
            captured["repo"] = model_name
            return ASRModel()

        def transcribe(self, paths, timestamps=False, **kw):
            captured["timestamps"] = timestamps
            return [_Hyp()]

    asr.models = types.SimpleNamespace(ASRModel=ASRModel)
    monkeypatch.setitem(sys.modules, "nemo", nemo)
    monkeypatch.setitem(sys.modules, "nemo.collections", collections)
    monkeypatch.setitem(sys.modules, "nemo.collections.asr", asr)


def test_transcribe_reads_segment_timestamps(monkeypatch):
    captured = {}
    _install_fake_nemo(monkeypatch, captured)
    backend = ParakeetNeMoBackend("nvidia/parakeet-tdt-0.6b-v2")
    out = backend.transcribe(np.zeros(16000, dtype=np.float32), initial_prompt="ignored")
    assert out == [{"start": 0.0, "end": 1.0, "text": "hi"}]
    assert captured["repo"] == "nvidia/parakeet-tdt-0.6b-v2"
    assert captured["timestamps"] is True


def test_empty_audio_returns_empty(monkeypatch):
    _install_fake_nemo(monkeypatch, {})
    backend = ParakeetNeMoBackend("nvidia/parakeet-tdt-0.6b-v2")
    assert backend.transcribe(np.array([], dtype=np.float32)) == []
