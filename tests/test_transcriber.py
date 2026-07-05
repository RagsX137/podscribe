import numpy as np
import pytest
from podscribe.transcriber import Transcriber

mlx = pytest.importorskip("mlx_whisper")  # skip on non-Apple machines


def test_transcriber_accepts_initial_prompt():
    """Real mlx smoke test: initial_prompt is accepted and output is well-formed."""
    t = Transcriber(model="base", backend="whisper-mlx")
    audio = np.random.randn(16000).astype(np.float32) * 0.01
    results = t.transcribe(audio, initial_prompt="Test prompt context.")
    assert isinstance(results, list)
