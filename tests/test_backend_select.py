"""Tests for platform-aware backend selection."""
import pytest
from podscribe.backends import select
from podscribe.backends.select import resolve_backend


@pytest.fixture
def on_apple(monkeypatch):
    monkeypatch.setattr(select, "is_apple_silicon", lambda: True)


@pytest.fixture
def on_nvidia(monkeypatch):
    monkeypatch.setattr(select, "is_apple_silicon", lambda: False)


def test_auto_apple_whisper_default(on_apple):
    assert resolve_backend("large-v3-turbo") == (
        "whisper-mlx", "mlx-community/whisper-large-v3-turbo")


def test_auto_apple_parakeet(on_apple):
    assert resolve_backend("parakeet") == (
        "parakeet-mlx", "mlx-community/parakeet-tdt-0.6b-v2")


def test_auto_nvidia_whisper_uses_faster(on_nvidia):
    assert resolve_backend("large-v3-turbo") == ("whisper-faster", "large-v3-turbo")


def test_auto_nvidia_parakeet_uses_nemo(on_nvidia):
    assert resolve_backend("parakeet") == (
        "parakeet-nemo", "nvidia/parakeet-tdt-0.6b-v2")


def test_explicit_backend_overrides_platform(on_apple):
    assert resolve_backend("large-v3-turbo", backend="whisper-faster") == (
        "whisper-faster", "large-v3-turbo")


def test_full_hf_path_passes_through(on_nvidia):
    assert resolve_backend("systran/faster-whisper-large-v3", backend="whisper-faster") == (
        "whisper-faster", "systran/faster-whisper-large-v3")


def test_unknown_backend_raises():
    with pytest.raises(ValueError, match="unknown backend"):
        resolve_backend("base", backend="whisper-rocm")
