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


def test_audio_capture_rejects_bad_device_with_actionable_message():
    """AudioCapture(device=N) with an invalid index raises ValueError whose
    message points the user at `podscribe list-devices`.
    """
    import sounddevice as sd
    from unittest.mock import patch
    from podscribe.audio import AudioCapture

    def fake_query(idx, kind=None):
        raise sd.PortAudioError(f"Invalid device index {idx}")

    with patch("sounddevice.query_devices", side_effect=fake_query):
        try:
            AudioCapture(device=99999)
            assert False, "expected ValueError for bad device index"
        except ValueError as e:
            assert "99999" in str(e)
            assert "list-devices" in str(e)


def test_segments_translates_portaudio_error_to_stderr(capsys, monkeypatch):
    """If sd.InputStream.start() raises PortAudioError (mic permission / busy),
    segments() prints a one-line stderr message and yields nothing instead of
    surfacing a raw traceback.
    """
    import sounddevice as sd
    from unittest.mock import patch
    from podscribe.audio import AudioCapture

    capture = AudioCapture()

    class _BoomStream:
        def __init__(self, *a, **kw):
            raise sd.PortAudioError("Device unavailable")
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    capture._load_vad = lambda: None  # no webrtcvad needed
    with patch("sounddevice.InputStream", _BoomStream):
        segments = list(capture.segments())
    assert segments == []
    err = capsys.readouterr().err
    assert "audio input failed" in err
