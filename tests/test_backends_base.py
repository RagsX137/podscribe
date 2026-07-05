import numpy as np
from podscribe.backends.base import normalize_segments, prepare_audio


def test_normalize_segments_builds_contract_dicts():
    raw = [(0.0, 1.5, "  hello  "), (1.5, 2.0, "world")]
    assert normalize_segments(raw) == [
        {"start": 0.0, "end": 1.5, "text": "hello"},
        {"start": 1.5, "end": 2.0, "text": "world"},
    ]


def test_normalize_segments_drops_empty_text():
    raw = [(0.0, 1.0, "   "), (1.0, 2.0, ""), (2.0, 3.0, "kept")]
    assert normalize_segments(raw) == [{"start": 2.0, "end": 3.0, "text": "kept"}]


def test_prepare_audio_reshapes_multidim():
    audio = np.zeros((4, 1), dtype=np.float32)
    assert prepare_audio(audio).ndim == 1


def test_prepare_audio_passes_1d_through():
    audio = np.zeros(4, dtype=np.float32)
    assert prepare_audio(audio) is audio
