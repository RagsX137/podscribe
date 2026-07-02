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


def test_segment_frames_yields_at_max_on_silence():
    """Reaching MAX_SEGMENT_SEC where the next frame is silence yields cleanly
    at ~10s (333 frames at 30ms) — no extension.
    """
    from podscribe.audio import _segment_frames, MAX_SEGMENT_SEC
    # 333 speech frames (10s) then 5 silence frames (will trigger boundary)
    seq = [True] * 333 + [False] * 5
    out = list(_segment_frames(seq))
    assert len(out) == 1
    # The yielded segment's frame count is 333 → ~9.99s
    assert len(out[0]) == 333


def test_segment_frames_extends_to_soft_max_on_speech():
    """Reaching MAX_SEGMENT_SEC where the next frame is speech extends to
    SOFT_MAX_SEGMENT_SEC (12s = 400 frames at 30ms), then yields.
    """
    from podscribe.audio import _segment_frames
    seq = [True] * 400  # continuous speech well past both caps
    out = list(_segment_frames(seq))
    assert len(out) == 1
    assert len(out[0]) == 400, "first segment must hit soft cap (12s)"


def test_segment_frames_continuous_speech_yields_exactly_at_soft_max():
    """With speech running well past 12s, the first yield is at exactly 12s
    and a new segment begins afterwards.
    """
    from podscribe.audio import _segment_frames
    seq = [True] * 500
    out = list(_segment_frames(seq))
    assert len(out[0]) == 400, "hard floor at 12s"
    # The remaining 100 frames form a new in-progress segment (yielded on EOF)
    assert len(out) == 2
    assert sum(len(s) for s in out) == 500


def test_segments_from_chunks_writes_all_chunks_but_yields_voiced_only(tmp_path, monkeypatch):
    """The raw file must contain EVERY chunk (silence included); yields are voiced-only.

    This is the v1-catching test: voiced-only .raw would fail the duration assertion.
    """
    import wave
    import numpy as np
    from podscribe.audio import AudioCapture, SAMPLE_RATE, VAD_FRAME_SAMPLES

    # Build a chunk stream: 20 speech frames, 10 silence frames, 20 speech frames.
    # Each chunk is one VAD frame worth of float32 samples (30ms).
    # 20 speech frames = 600ms — exceeds MIN_SEGMENT_SEC (500ms) so the trim/filter
    # in _segments_from_chunks still yields voiced segments. Spec said 10+10+10
    # but 10 frames = 300ms, which is below MIN_SEGMENT_SEC, so the second
    # invariant would always be 0 < 0 → fail. The two invariants we care about
    # only need speech long enough to survive the filter.
    speech = np.full(VAD_FRAME_SAMPLES, 0.5, dtype=np.float32)
    silence = np.zeros(VAD_FRAME_SAMPLES, dtype=np.float32)
    chunks = [speech] * 20 + [silence] * 10 + [speech] * 20
    total_frames = len(chunks) * VAD_FRAME_SAMPLES

    cap = AudioCapture()
    # Stub VAD: our synthetic 0.5 chunk is "speech", 0.0 chunk is "silence".
    monkeypatch.setattr(cap, "_load_vad", lambda: None)
    monkeypatch.setattr(cap, "_is_speech", lambda pcm: bool(np.any(pcm != 0)))
    cap._running = True

    raw_path = tmp_path / "cont.raw"
    voiced = list(cap._segments_from_chunks(iter(chunks), raw_path))

    # Invariant 1: continuous .raw holds every chunk (silence included).
    with wave.open(str(raw_path), "rb") as w:
        assert w.getnframes() == total_frames

    # Invariant 2: yielded audio is voiced-only (strictly less than the total).
    voiced_frames = sum(len(seg) for seg in voiced)
    assert 0 < voiced_frames < total_frames


def test_segments_from_chunks_no_raw_path_still_yields(tmp_path, monkeypatch):
    """raw_path=None: no file written, VAD/yield behaviour unchanged."""
    import numpy as np
    from podscribe.audio import AudioCapture, VAD_FRAME_SAMPLES

    speech = np.full(VAD_FRAME_SAMPLES, 0.5, dtype=np.float32)
    chunks = [speech] * 20
    cap = AudioCapture()
    monkeypatch.setattr(cap, "_load_vad", lambda: None)
    monkeypatch.setattr(cap, "_is_speech", lambda pcm: True)
    cap._running = True
    voiced = list(cap._segments_from_chunks(iter(chunks), None))
    assert sum(len(seg) for seg in voiced) > 0
    assert not (tmp_path / "any.raw").exists()
