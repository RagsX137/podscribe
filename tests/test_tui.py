from podscribe.tui import launch


def test_launch_no_pods_prints_panel_and_exits_0(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = launch()
    assert rc == 0
    out = capsys.readouterr().out
    assert "No pods" in out or "init" in out


def test_launch_with_pod_and_q_exits_cleanly(tmp_path, monkeypatch):
    """With a pod and a non-interactive key (e.g. 'q'), launch should exit cleanly."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod
    init_pod("sam-chen", display_name="Sam Chen")
    import podscribe.tui as tui
    monkeypatch.setattr(tui, "read_key", lambda: "q")
    monkeypatch.setattr(tui, "probe_ollama", lambda: False)
    rc = launch()
    assert rc == 0


def test_action_menu_ctrl_c_returns_quit(tmp_path):
    """Ctrl+C (\\x03) in the action menu should be treated as 'q' (quit), not crash."""
    import podscribe.tui as tui
    from rich.console import Console
    monkeypatch_keys = ["\x03"]
    def fake_read_key():
        return monkeypatch_keys.pop(0)
    import unittest.mock as mock
    with mock.patch.object(tui, "read_key", side_effect=fake_read_key):
        result = tui._action_menu(Console())
    assert result == "q"


def test_others_menu_ctrl_c_returns_quit():
    """Ctrl+C (\\x03) in the others menu should be treated as 'q' (back)."""
    import podscribe.tui as tui
    from rich.console import Console
    import unittest.mock as mock
    with mock.patch.object(tui, "read_key", return_value="\x03"):
        result = tui._others_menu(Console())
    assert result == "q"


def test_record_view_passes_glossary_prompt_to_run_record_session(tmp_path, monkeypatch):
    """record_view must build and pass glossary_prompt — regression for the
    bug where TUI recording silently ignored the glossary."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, load_pod
    init_pod("sam-chen", display_name="Sam Chen")
    # Add a glossary entry so the prompt is non-empty
    from podscribe.config import save_pod_config
    pod = load_pod("sam-chen")
    pod.glossary = [{"term": "Project Helios", "category": "project"}]
    save_pod_config(pod)

    # Clear the glossary cache so the new entry is picked up
    from podscribe.config import _glossary_cache
    _glossary_cache["key"] = None

    pod = load_pod("sam-chen")

    import unittest.mock as mock

    # Capture the kwargs passed to run_record_session
    captured_kwargs = {}
    def fake_run_record_session(*args, **kwargs):
        captured_kwargs.update(kwargs)

    # Mock the heavy deps that record_view lazy-imports
    mock_capture = mock.MagicMock()
    mock_capture.vad_aggressiveness = 2
    mock_transcriber = mock.MagicMock()
    mock_transcriber.model_name = "large-v3-turbo"

    mock_meeting = mock.MagicMock()
    mock_meeting.id = "2026-06-23-120000-sam-chen"
    mock_meeting.audio_path = tmp_path / "audio.raw"

    with mock.patch("podscribe.cli.run_record_session", side_effect=fake_run_record_session):
        with mock.patch("podscribe.audio.AudioCapture", return_value=mock_capture):
            with mock.patch("podscribe.transcriber.Transcriber", return_value=mock_transcriber):
                with mock.patch("podscribe.storage.start_meeting", return_value=mock_meeting):
                    import podscribe.tui as tui
                    from argparse import Namespace
                    args = Namespace(
                        type=None, model="large-v3-turbo",
                        vad_aggressiveness=2, device=None, keep_audio=False,
                    )
                    tui.record_view(pod, args)

    assert "glossary_prompt" in captured_kwargs, "glossary_prompt was not passed to run_record_session"
    assert captured_kwargs["glossary_prompt"] is not None, "glossary_prompt was None despite pod having a glossary"
    assert "Project Helios" in captured_kwargs["glossary_prompt"]


def test_run_record_session_restores_sigint_handler(tmp_path, monkeypatch):
    """run_record_session must restore the original SIGINT handler on exit,
    so Ctrl+C works correctly after returning to the launcher."""
    import signal
    import numpy as np
    from podscribe.cli import run_record_session
    from podscribe.models import Pod
    from podscribe.storage import start_meeting

    monkeypatch.chdir(tmp_path)
    pod = Pod(
        name="sam-chen", display_name="Sam", role="", cadence="weekly",
        notes="", created_at="2026-06-23", glossary=None, llm=None,
        base_path=tmp_path / "pods" / "sam-chen",
    )
    (pod.base_path / "transcripts").mkdir(parents=True)
    meeting = start_meeting(pod)

    class FakeCapture:
        def __init__(self):
            self.vad_aggressiveness = 2
            self.had_overflow = False
        def segments(self):
            return iter([np.zeros(16000, dtype=np.float32)])
        def stop(self):
            pass

    class FakeTranscriber:
        model_name = "large-v3-turbo"
        def transcribe(self, audio, **kwargs):
            return [{"start": 0.0, "end": 1.0, "text": "hi"}]

    original_handler = signal.getsignal(signal.SIGINT)
    run_record_session(
        pod, meeting, FakeCapture(), FakeTranscriber(),
        on_segment=lambda s: None, on_status=lambda d: None, on_done=lambda n: None,
    )
    restored_handler = signal.getsignal(signal.SIGINT)
    assert restored_handler == original_handler, (
        f"SIGINT handler was not restored after run_record_session. "
        f"Expected {original_handler}, got {restored_handler}"
    )


def test_main_bare_tty_ctrl_c_returns_130(monkeypatch):
    """Ctrl+C at the launcher (bare podscribe in a TTY) should return 130,
    not crash with a traceback."""
    import io
    import podscribe.cli as cli

    class FakeTty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdin", FakeTty())
    monkeypatch.setattr("sys.stderr", FakeTty())

    with __import__("unittest.mock").mock.patch("podscribe.tui.launch", side_effect=KeyboardInterrupt):
        rc = cli.main([])
    assert rc == 130
