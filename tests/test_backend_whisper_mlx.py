import sys
import types
import numpy as np
from podscribe.backends.whisper_mlx import WhisperMLXBackend


def _install_fake_mlx(monkeypatch, captured):
    fake = types.ModuleType("mlx_whisper")

    def transcribe(audio, path_or_hf_repo=None, **kwargs):
        captured["repo"] = path_or_hf_repo
        captured["kwargs"] = kwargs
        return {"segments": [
            {"start": 0.0, "end": 1.0, "text": " hi "},
            {"start": 1.0, "end": 2.0, "text": ""},
        ]}

    fake.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake)


def test_transcribe_normalizes_and_passes_repo_and_prompt(monkeypatch):
    captured = {}
    _install_fake_mlx(monkeypatch, captured)
    backend = WhisperMLXBackend("mlx-community/whisper-base-mlx")
    out = backend.transcribe(np.zeros(16000, dtype=np.float32), initial_prompt="ctx")
    assert out == [{"start": 0.0, "end": 1.0, "text": "hi"}]
    assert captured["repo"] == "mlx-community/whisper-base-mlx"
    assert captured["kwargs"].get("initial_prompt") == "ctx"


def test_empty_audio_returns_empty(monkeypatch):
    _install_fake_mlx(monkeypatch, {})
    backend = WhisperMLXBackend("mlx-community/whisper-base-mlx")
    assert backend.transcribe(np.array([], dtype=np.float32)) == []
