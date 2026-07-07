import sys
import types
import numpy as np
import pytest
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
            captured["kwargs"] = kw
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


def test_chunked_decode_by_default(monkeypatch):
    """Long audio must decode in bounded chunks so the Metal allocator doesn't OOM (#10)."""
    captured = {}
    _install_fake_parakeet_mlx(monkeypatch, captured)
    backend = ParakeetMLXBackend("mlx-community/parakeet-tdt-0.6b-v2")
    backend.transcribe(np.zeros(16000, dtype=np.float32))
    assert captured["kwargs"]["chunk_duration"] == 120.0
    assert captured["kwargs"]["overlap_duration"] == 15.0


def test_chunk_params_overridable(monkeypatch):
    captured = {}
    _install_fake_parakeet_mlx(monkeypatch, captured)
    backend = ParakeetMLXBackend("mlx-community/parakeet-tdt-0.6b-v2")
    backend.transcribe(
        np.zeros(16000, dtype=np.float32), chunk_duration=60.0, overlap_duration=5.0
    )
    assert captured["kwargs"]["chunk_duration"] == 60.0
    assert captured["kwargs"]["overlap_duration"] == 5.0


def test_whisper_only_kwargs_not_forwarded(monkeypatch):
    """initial_prompt is a whisper concept; parakeet's transcribe must not receive it."""
    captured = {}
    _install_fake_parakeet_mlx(monkeypatch, captured)
    backend = ParakeetMLXBackend("mlx-community/parakeet-tdt-0.6b-v2")
    with pytest.warns(UserWarning, match="initial_prompt"):
        backend.transcribe(np.zeros(16000, dtype=np.float32), initial_prompt="ignored")
    assert "initial_prompt" not in captured["kwargs"]


def test_chunk_duration_none_does_not_undefault(monkeypatch):
    """An explicit chunk_duration=None must not re-enable parakeet-mlx's single-pass OOM path."""
    captured = {}
    _install_fake_parakeet_mlx(monkeypatch, captured)
    backend = ParakeetMLXBackend("mlx-community/parakeet-tdt-0.6b-v2")
    backend.transcribe(np.zeros(16000, dtype=np.float32), chunk_duration=None)
    assert captured["kwargs"]["chunk_duration"] == 120.0
    assert captured["kwargs"]["overlap_duration"] == 15.0


def test_overlap_duration_none_does_not_undefault(monkeypatch):
    captured = {}
    _install_fake_parakeet_mlx(monkeypatch, captured)
    backend = ParakeetMLXBackend("mlx-community/parakeet-tdt-0.6b-v2")
    backend.transcribe(np.zeros(16000, dtype=np.float32), overlap_duration=None)
    assert captured["kwargs"]["overlap_duration"] == 15.0


def test_unknown_kwarg_warns(monkeypatch):
    _install_fake_parakeet_mlx(monkeypatch, {})
    backend = ParakeetMLXBackend("mlx-community/parakeet-tdt-0.6b-v2")
    with pytest.warns(UserWarning, match="language"):
        backend.transcribe(np.zeros(16000, dtype=np.float32), language="en")


def test_known_kwargs_do_not_warn(monkeypatch, recwarn):
    _install_fake_parakeet_mlx(monkeypatch, {})
    backend = ParakeetMLXBackend("mlx-community/parakeet-tdt-0.6b-v2")
    backend.transcribe(np.zeros(16000, dtype=np.float32), chunk_duration=60.0)
    assert len(recwarn) == 0
