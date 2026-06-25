def test_on_level_callback_receives_rms_float():
    """on_level must be called with a float in [0.0, 1.0] for each audio chunk."""
    import numpy as np
    from podscribe.audio import AudioCapture

    levels = []
    capture = AudioCapture(on_level=levels.append)

    # Simulate the callback directly — mimic what sounddevice would call
    # indata shape is (frames, channels) = (480, 1)
    chunk = np.full((480, 1), 0.5, dtype="float32")

    import types
    fake_status = None
    capture._callback(chunk, 480, None, fake_status)

    assert len(levels) == 1
    level = levels[0]
    assert isinstance(level, float)
    assert 0.0 <= level <= 1.0
    # RMS of 0.5 signal = 0.5
    assert abs(level - 0.5) < 0.01
