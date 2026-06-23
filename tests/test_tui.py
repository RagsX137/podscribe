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


# ── Feature 1: Meeting picker ───────────────────────────────────────

def test_pick_meeting_returns_none_on_quit(tmp_path, monkeypatch):
    """Meeting picker returns None when user quits."""
    import podscribe.tui as tui
    from rich.console import Console
    import unittest.mock as mock

    mock_meetings = [
        mock.MagicMock(id="2026-06-22-143000-sam-chen", started_at="2026-06-22T14:30:00",
                       type="1on1", duration_sec=1934),
    ]
    with mock.patch.object(tui, "list_meetings", return_value=mock_meetings):
        with mock.patch.object(tui, "read_key", return_value="q"):
            result = tui._pick_meeting(Console(), mock.MagicMock(name="sam-chen"))
    assert result is None


def test_pick_meeting_returns_selected_meeting(tmp_path, monkeypatch):
    """Meeting picker returns the selected meeting on Enter."""
    import podscribe.tui as tui
    from rich.console import Console
    import unittest.mock as mock

    mock_meetings = [
        mock.MagicMock(id="2026-06-22-143000-sam-chen", started_at="2026-06-22T14:30:00",
                       type="1on1", duration_sec=1934),
        mock.MagicMock(id="2026-06-21-100000-sam-chen", started_at="2026-06-21T10:00:00",
                       type="retro", duration_sec=600),
    ]
    # Press down arrow then Enter to select the second meeting
    with mock.patch.object(tui, "list_meetings", return_value=mock_meetings):
        with mock.patch.object(tui, "read_key", side_effect=[tui.KEY_DOWN, tui.KEY_ENTER]):
            result = tui._pick_meeting(Console(), mock.MagicMock(name="sam-chen"))
    assert result is not None
    assert result.id == "2026-06-21-100000-sam-chen"


def test_pick_meeting_number_key_selects_directly(tmp_path, monkeypatch):
    """Pressing a number key selects that meeting directly."""
    import podscribe.tui as tui
    from rich.console import Console
    import unittest.mock as mock

    mock_meetings = [
        mock.MagicMock(id="mtg-a", started_at="2026-06-22T14:30:00", type=None, duration_sec=None),
        mock.MagicMock(id="mtg-b", started_at="2026-06-21T10:00:00", type=None, duration_sec=None),
    ]
    with mock.patch.object(tui, "list_meetings", return_value=mock_meetings):
        with mock.patch.object(tui, "read_key", return_value="2"):
            result = tui._pick_meeting(Console(), mock.MagicMock(name="sam-chen"))
    assert result is not None
    assert result.id == "mtg-b"


def test_pick_meeting_no_meetings_returns_none(tmp_path, monkeypatch):
    """No meetings → prints error, returns None."""
    import podscribe.tui as tui
    from rich.console import Console
    import unittest.mock as mock

    with mock.patch.object(tui, "list_meetings", return_value=[]):
        result = tui._pick_meeting(Console(), mock.MagicMock(name="sam-chen"))
    assert result is None


# ── Feature 4: Arrow-key navigation ─────────────────────────────────

def test_select_menu_arrow_down_then_enter():
    """Arrow down moves selection, Enter selects."""
    import podscribe.tui as tui
    from rich.console import Console
    import unittest.mock as mock

    items = [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]
    keys = [tui.KEY_DOWN, tui.KEY_DOWN, tui.KEY_ENTER]
    with mock.patch.object(tui, "read_key", side_effect=keys):
        result = tui._select_menu(Console(), "Test", items)
    assert result == "c"


def test_select_menu_arrow_up_wraps():
    """Arrow up wraps around. From first item → Back → last item."""
    import podscribe.tui as tui
    from rich.console import Console
    import unittest.mock as mock

    items = [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]
    # Up from index 0 → index 3 (Back), up again → index 2 (Gamma), Enter
    keys = [tui.KEY_UP, tui.KEY_UP, tui.KEY_ENTER]
    with mock.patch.object(tui, "read_key", side_effect=keys):
        result = tui._select_menu(Console(), "Test", items)
    assert result == "c"


def test_select_menu_number_key_jumps():
    """Pressing '3' selects the third item directly."""
    import podscribe.tui as tui
    from rich.console import Console
    import unittest.mock as mock

    items = [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]
    with mock.patch.object(tui, "read_key", return_value="3"):
        result = tui._select_menu(Console(), "Test", items)
    assert result == "c"


def test_select_menu_quit_returns_none():
    """Pressing 'q' returns None."""
    import podscribe.tui as tui
    from rich.console import Console
    import unittest.mock as mock

    items = [("a", "Alpha"), ("b", "Beta")]
    with mock.patch.object(tui, "read_key", return_value="q"):
        result = tui._select_menu(Console(), "Test", items)
    assert result is None


def test_select_menu_ctrl_c_returns_none():
    """Ctrl+C returns None."""
    import podscribe.tui as tui
    from rich.console import Console
    import unittest.mock as mock

    items = [("a", "Alpha"), ("b", "Beta")]
    with mock.patch.object(tui, "read_key", return_value="\x03"):
        result = tui._select_menu(Console(), "Test", items)
    assert result is None


def test_select_menu_empty_items_returns_none():
    """Empty items list returns None immediately."""
    import podscribe.tui as tui
    from rich.console import Console
    result = tui._select_menu(Console(), "Test", [])
    assert result is None


# ── Feature 2: Others submenu structure ─────────────────────────────

def test_others_menu_has_write_operations():
    """Others menu should include glossary, llm, and consolidate-cfg keys."""
    import podscribe.tui as tui
    from rich.console import Console
    import unittest.mock as mock

    # Press 'q' to exit immediately
    with mock.patch.object(tui, "read_key", return_value="q"):
        result = tui._others_menu(Console())
    assert result == "q"

    # Verify the menu items include the new write operations
    # by checking that _glossary_menu, _llm_config_menu, _consolidate_cfg_menu exist
    assert hasattr(tui, "_glossary_menu")
    assert hasattr(tui, "_llm_config_menu")
    assert hasattr(tui, "_consolidate_cfg_menu")
    assert hasattr(tui, "_others_glossary")
    assert hasattr(tui, "_others_llm_config")
    assert hasattr(tui, "_others_consolidate_cfg")


def test_glossary_menu_returns_keys():
    """Glossary submenu returns correct keys."""
    import podscribe.tui as tui
    from rich.console import Console
    import unittest.mock as mock

    with mock.patch.object(tui, "read_key", return_value="1"):
        result = tui._glossary_menu(Console())
    assert result == "list"

    with mock.patch.object(tui, "read_key", return_value="2"):
        result = tui._glossary_menu(Console())
    assert result == "add"

    with mock.patch.object(tui, "read_key", return_value="3"):
        result = tui._glossary_menu(Console())
    assert result == "remove"


# ── Feature 3: CLI TTY delegation ───────────────────────────────────

def test_cmd_record_delegates_to_record_view_when_tty(tmp_path, monkeypatch):
    """cmd_record should delegate to record_view when stdout is a TTY."""
    import io
    import unittest.mock as mock
    from podscribe.cli import cmd_record, build_parser
    from podscribe.storage import init_pod

    monkeypatch.chdir(tmp_path)
    init_pod("sam-chen")

    class FakeTty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdout", FakeTty())
    monkeypatch.setattr("sys.stderr", FakeTty())

    called = []
    def fake_record_view(pod, args):
        called.append((pod.name, args))
        return 0

    args = build_parser().parse_args(["record", "sam-chen", "--model", "base"])
    with mock.patch("podscribe.tui.record_view", side_effect=fake_record_view):
        rc = cmd_record(args)
    assert rc == 0
    assert len(called) == 1
    assert called[0][0] == "sam-chen"


def test_cmd_record_uses_plain_path_when_not_tty(tmp_path, monkeypatch):
    """cmd_record should use the plain-text path when stdout is not a TTY."""
    import io
    import unittest.mock as mock
    from podscribe.cli import cmd_record, build_parser
    from podscribe.storage import init_pod

    monkeypatch.chdir(tmp_path)
    init_pod("sam-chen")

    monkeypatch.setattr("sys.stdout", io.StringIO())  # isatty() = False

    mock_capture = mock.MagicMock()
    mock_capture.vad_aggressiveness = 2
    mock_capture.had_overflow = False
    mock_capture.segments.return_value = iter([])
    mock_capture.stop = mock.MagicMock()

    mock_transcriber = mock.MagicMock()
    mock_transcriber.model_name = "base"

    record_view_called = []
    with mock.patch("podscribe.tui.record_view", side_effect=lambda *a: record_view_called.append(True)):
        with mock.patch("podscribe.audio.AudioCapture", return_value=mock_capture):
            with mock.patch("podscribe.transcriber.Transcriber", return_value=mock_transcriber):
                with mock.patch("podscribe.cli.signal.signal"):
                    args = build_parser().parse_args(["record", "sam-chen", "--model", "base"])
                    rc = cmd_record(args)

    assert record_view_called == [], "record_view should not be called in non-TTY mode"
    assert rc == 0


def test_cmd_enhance_delegates_to_enhance_view_when_tty(tmp_path, monkeypatch):
    """cmd_enhance should delegate to enhance_view when stdout is a TTY."""
    import io
    import unittest.mock as mock
    from datetime import datetime
    from podscribe.cli import cmd_enhance, build_parser
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment

    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello world this is a long enough transcript for testing"))
    finalize_meeting(meeting)

    class FakeTty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdout", FakeTty())
    monkeypatch.setattr("sys.stderr", FakeTty())

    called = []
    def fake_enhance_view(pod, meeting):
        called.append((pod.name, meeting.id))
        return 0

    with mock.patch("podscribe.cli.load_project_config", return_value={
        "llm": {"model": "qwen3.6", "prompt_template": "x"}
    }):
        with mock.patch("podscribe.tui.enhance_view", side_effect=fake_enhance_view):
            args = build_parser().parse_args(["enhance", "sam-chen"])
            rc = cmd_enhance(args)
    assert rc == 0
    assert len(called) == 1


def test_cmd_consolidate_delegates_to_consolidate_screen_when_tty(tmp_path, monkeypatch):
    """cmd_consolidate should delegate to consolidate_screen when stdout is a TTY."""
    import io
    import unittest.mock as mock
    from datetime import datetime
    from podscribe.cli import cmd_consolidate, build_parser
    from podscribe.storage import init_pod, start_meeting, append_segment, finalize_meeting
    from podscribe.models import Segment

    monkeypatch.chdir(tmp_path)
    pod = init_pod("sam-chen")
    meeting = start_meeting(pod, datetime(2026, 6, 22, 14, 30, 0))
    append_segment(meeting, Segment(1.0, 5.0, "hello world"))
    finalize_meeting(meeting)
    summary_dir = pod.summaries_dir_for("22-JUN-2026")
    summary_dir.mkdir(parents=True, exist_ok=True)
    (summary_dir / f"{meeting.id}.md").write_text("Summary text.")

    class FakeTty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdout", FakeTty())
    monkeypatch.setattr("sys.stderr", FakeTty())

    called = []
    def fake_consolidate_screen(pod, meeting):
        called.append((pod.name, meeting.id))
        return 0

    with mock.patch("podscribe.tui.consolidate_screen", side_effect=fake_consolidate_screen):
        args = build_parser().parse_args(["consolidate", "sam-chen"])
        rc = cmd_consolidate(args)
    assert rc == 0
    assert len(called) == 1

