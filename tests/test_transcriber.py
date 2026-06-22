import numpy as np
from podscribe.transcriber import Transcriber


def test_transcriber_accepts_initial_prompt():
    """Verify initial_prompt is accepted as a parameter (no crash)."""
    t = Transcriber(model="base", n_threads=4, print_progress=False)
    audio = np.random.randn(16000).astype(np.float32) * 0.01
    results = t.transcribe(audio, initial_prompt="Test prompt context.")
    assert isinstance(results, list)
