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


def test_launch_tab_switches_focused_pane(tmp_path, monkeypatch):
    """Tab key must switch focus between sidebar and main pane without crashing."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod
    init_pod("sam-chen", display_name="Sam Chen")
    import podscribe.tui as tui

    keys = iter(["Tab", "q"])
    def fake_key():
        k = next(keys)
        return "\t" if k == "Tab" else k
    monkeypatch.setattr(tui, "read_key", fake_key)
    monkeypatch.setattr(tui, "probe_ollama", lambda: False)
    rc = tui.launch()
    assert rc == 0




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


def test_mode_colour_active_modes_return_pink():
    from podscribe import tui
    assert tui.mode_colour("INSERT") == tui.C_PINK
    assert tui.mode_colour("STREAM") == tui.C_PINK

def test_mode_colour_command_returns_peach():
    from podscribe import tui
    assert tui.mode_colour("COMMAND") == tui.C_PEACH

def test_mode_colour_normal_returns_lilac():
    from podscribe import tui
    assert tui.mode_colour("NORMAL") == tui.C_LILAC

def test_app_state_defaults():
    from podscribe.tui import AppState
    s = AppState(pod_names=["sam-chen", "alex-wu"])
    assert s.mode == "NORMAL"
    assert s.focused_pane == "main"
    assert s.sidebar_idx == 0
    assert s.main_idx == 0
    assert len(s.waveform) == 40
    assert all(v == 0.0 for v in s.waveform)

def test_app_state_waveform_push():
    from podscribe.tui import AppState
    s = AppState(pod_names=["sam-chen"])
    s.waveform.append(0.7)
    s.waveform = s.waveform[-40:]
    assert s.waveform[-1] == 0.7
    assert len(s.waveform) <= 40


def test_render_sidebar_marks_active_pod(tmp_path, monkeypatch):
    from podscribe.tui import AppState, render_sidebar
    from podscribe.models import Pod

    pods = [
        Pod(name="sam-chen", display_name="Sam Chen", role="SE", base_path=tmp_path / "pods" / "sam-chen"),
        Pod(name="alex-wu",  display_name="Alex Wu",  role="Staff", base_path=tmp_path / "pods" / "alex-wu"),
    ]
    state = AppState(pod_names=["sam-chen", "alex-wu"], sidebar_idx=0)
    panel = render_sidebar(state, pods)
    # Render to a string to inspect
    from rich.console import Console
    from io import StringIO
    buf = StringIO()
    c = Console(file=buf, no_color=True, width=40)
    c.print(panel)
    text = buf.getvalue()
    assert "sam-chen" in text
    assert "alex-wu" in text
    # Active item has the cursor character
    assert "▶" in text


def test_render_header_shows_ollama_status():
    from podscribe.tui import render_header
    from podscribe.models import Pod
    from pathlib import Path
    pod = Pod(name="sam-chen", display_name="Sam Chen", role="Senior Eng",
              base_path=Path("/tmp/x"))
    hdr = render_header(pod, ollama_ok=True)
    assert "sam-chen" in hdr
    assert "online" in hdr

    hdr_off = render_header(pod, ollama_ok=False)
    assert "offline" in hdr_off


def test_render_dashboard_shows_pod_name(tmp_path):
    from podscribe.tui import AppState, render_dashboard
    from podscribe.models import Pod
    from io import StringIO
    from rich.console import Console

    pod = Pod(name="sam-chen", display_name="Sam Chen", role="Senior Eng",
              base_path=tmp_path / "pods" / "sam-chen")
    state = AppState(pod_names=["sam-chen"])
    panel = render_dashboard(pod, meetings=[], state=state)

    buf = StringIO()
    Console(file=buf, no_color=True, width=80).print(panel)
    text = buf.getvalue()
    assert "Sam Chen" in text or "sam-chen" in text


def test_render_status_bar_normal_mode():
    from podscribe.tui import AppState, render_status_bar, C_LILAC
    from podscribe.models import Pod
    from pathlib import Path
    pod = Pod(name="sam-chen", base_path=Path("/tmp/x"))
    state = AppState(pod_names=["sam-chen"], mode="NORMAL")
    bar = render_status_bar(state, pod)
    assert "NORMAL" in bar
    assert "sam-chen" in bar

def test_render_status_bar_insert_mode():
    from podscribe.tui import AppState, render_status_bar, C_PINK
    from podscribe.models import Pod
    from pathlib import Path
    pod = Pod(name="sam-chen", base_path=Path("/tmp/x"))
    state = AppState(pod_names=["sam-chen"], mode="INSERT")
    bar = render_status_bar(state, pod)
    assert "INSERT" in bar


def test_build_palette_candidates_includes_pods_and_cmds():
    from podscribe.tui import build_palette_candidates, FuzzyCandidate
    candidates = build_palette_candidates(["sam-chen", "alex-wu"])
    kinds = [c.kind for c in candidates]
    assert "pod" in kinds
    assert "cmd" in kinds
    pod_labels = [c.label for c in candidates if c.kind == "pod"]
    assert "sam-chen" in pod_labels
    assert "alex-wu" in pod_labels

def test_fuzzy_filter_empty_query_returns_all():
    from podscribe.tui import build_palette_candidates, fuzzy_filter
    candidates = build_palette_candidates(["sam-chen"])
    assert fuzzy_filter(candidates, "") == candidates

def test_fuzzy_filter_narrows_by_substring():
    from podscribe.tui import build_palette_candidates, fuzzy_filter
    candidates = build_palette_candidates(["sam-chen", "alex-wu"])
    result = fuzzy_filter(candidates, "sam")
    labels = [c.label for c in result]
    assert "sam-chen" in labels
    assert "alex-wu" not in labels

def test_fuzzy_filter_matches_kind_prefix():
    from podscribe.tui import build_palette_candidates, fuzzy_filter
    candidates = build_palette_candidates(["sam-chen"])
    result = fuzzy_filter(candidates, "cmd")
    assert all(c.kind == "cmd" for c in result)


def test_record_view_waveform_on_level_passed_to_capture(tmp_path, monkeypatch):
    """record_view must pass an on_level callback to AudioCapture."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod, load_pod
    init_pod("sam-chen", display_name="Sam Chen")
    pod = load_pod("sam-chen")

    import unittest.mock as mock
    captured_kwargs = {}

    class FakeCapture:
        vad_aggressiveness = 2
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)
        def segments(self): return iter([])

    mock_transcriber = mock.MagicMock()
    mock_transcriber.model_name = "large-v3-turbo"
    mock_meeting = mock.MagicMock()
    mock_meeting.id = "2026-06-23-120000-sam-chen"
    mock_meeting.audio_path = tmp_path / "audio.raw"
    mock_meeting.transcript_path = tmp_path / "t.md"
    mock_meeting.transcript_path.touch()

    with mock.patch("podscribe.audio.AudioCapture", FakeCapture):
        with mock.patch("podscribe.transcriber.Transcriber", return_value=mock_transcriber):
            with mock.patch("podscribe.storage.start_meeting", return_value=mock_meeting):
                with mock.patch("podscribe.cli.run_record_session"):
                    import podscribe.tui as tui
                    from argparse import Namespace
                    args = Namespace(type=None, model="large-v3-turbo",
                                     vad_aggressiveness=2, device=None, keep_audio=False)
                    tui.record_view(pod, args)

    assert "on_level" in captured_kwargs, "on_level not passed to AudioCapture"
    assert callable(captured_kwargs["on_level"])


# ── _listen_for_stop unit tests ─────────────────────────────────────

def test_listen_for_stop_s_key_calls_capture_stop():
    """Pressing 's' in the pipe causes capture.stop() to be called."""
    import os
    import threading
    import unittest.mock as mock
    from podscribe.tui import _listen_for_stop

    r_fd, w_fd = os.pipe()
    stop_ev = threading.Event()
    mock_capture = mock.MagicMock()

    # Write 's' to the read-end via a second pipe pair so the listener
    # sees it as stdin.  We cannot redirect sys.stdin safely in a unit test,
    # so we use a fake fd by passing our pipe read-end as wake_fd and feeding
    # the key through a dedicated stdin-pipe.
    stdin_r, stdin_w = os.pipe()

    import sys, termios
    orig_stdin = sys.stdin

    # Replace sys.stdin.fileno() to point at stdin_r
    class FakeFd:
        def fileno(self):
            return stdin_r

    sys.stdin = FakeFd()
    try:
        t = threading.Thread(target=_listen_for_stop, args=(mock_capture, r_fd, stop_ev))
        t.start()
        # Give the thread time to enter select()
        import time
        time.sleep(0.05)
        os.write(stdin_w, b"s")
        t.join(timeout=2.0)
    finally:
        sys.stdin = orig_stdin
        for fd in (r_fd, w_fd, stdin_r, stdin_w):
            try:
                os.close(fd)
            except OSError:
                pass

    assert not t.is_alive(), "listener thread did not exit after 's'"
    mock_capture.stop.assert_called_once()


def test_listen_for_stop_uppercase_S_calls_capture_stop():
    """Pressing 'S' (uppercase) also stops recording."""
    import os
    import threading
    import unittest.mock as mock
    from podscribe.tui import _listen_for_stop

    r_fd, w_fd = os.pipe()
    stop_ev = threading.Event()
    mock_capture = mock.MagicMock()
    stdin_r, stdin_w = os.pipe()

    import sys
    orig_stdin = sys.stdin

    class FakeFd:
        def fileno(self):
            return stdin_r

    sys.stdin = FakeFd()
    try:
        t = threading.Thread(target=_listen_for_stop, args=(mock_capture, r_fd, stop_ev))
        t.start()
        import time
        time.sleep(0.05)
        os.write(stdin_w, b"S")
        t.join(timeout=2.0)
    finally:
        sys.stdin = orig_stdin
        for fd in (r_fd, w_fd, stdin_r, stdin_w):
            try:
                os.close(fd)
            except OSError:
                pass

    assert not t.is_alive(), "listener thread did not exit after 'S'"
    mock_capture.stop.assert_called_once()


def test_listen_for_stop_non_s_key_ignored():
    """Non-'s' keypresses do not call capture.stop()."""
    import os
    import threading
    import unittest.mock as mock
    from podscribe.tui import _listen_for_stop

    r_fd, w_fd = os.pipe()
    stop_ev = threading.Event()
    mock_capture = mock.MagicMock()
    stdin_r, stdin_w = os.pipe()

    import sys, time
    orig_stdin = sys.stdin

    class FakeFd:
        def fileno(self):
            return stdin_r

    sys.stdin = FakeFd()
    try:
        t = threading.Thread(target=_listen_for_stop, args=(mock_capture, r_fd, stop_ev))
        t.start()
        time.sleep(0.05)
        # Write several non-stop keys
        os.write(stdin_w, b"x")
        os.write(stdin_w, b"q")
        os.write(stdin_w, b"\r")
        time.sleep(0.05)
        # Thread should still be alive (no stop key yet)
        assert t.is_alive(), "thread exited prematurely on non-stop key"
    finally:
        # Wake the thread via wake_fd and let it exit
        try:
            os.write(w_fd, b"\x00")
        except OSError:
            pass
        t.join(timeout=2.0)
        sys.stdin = orig_stdin
        for fd in (r_fd, w_fd, stdin_r, stdin_w):
            try:
                os.close(fd)
            except OSError:
                pass

    mock_capture.stop.assert_not_called()


def test_listen_for_stop_wake_fd_exits_without_stop():
    """Writing to wake_fd causes the thread to exit cleanly without capture.stop()."""
    import os
    import threading
    import unittest.mock as mock
    from podscribe.tui import _listen_for_stop

    r_fd, w_fd = os.pipe()
    stop_ev = threading.Event()
    mock_capture = mock.MagicMock()
    stdin_r, stdin_w = os.pipe()

    import sys, time
    orig_stdin = sys.stdin

    class FakeFd:
        def fileno(self):
            return stdin_r

    sys.stdin = FakeFd()
    try:
        t = threading.Thread(target=_listen_for_stop, args=(mock_capture, r_fd, stop_ev))
        t.start()
        time.sleep(0.05)
        os.write(w_fd, b"\x00")  # Signal via wake_fd
        t.join(timeout=2.0)
    finally:
        sys.stdin = orig_stdin
        for fd in (r_fd, w_fd, stdin_r, stdin_w):
            try:
                os.close(fd)
            except OSError:
                pass

    assert not t.is_alive(), "thread did not exit after wake_fd write"
    mock_capture.stop.assert_not_called()


def test_listen_for_stop_stop_event_exits_thread():
    """Setting stop_event causes the thread to exit within select timeout."""
    import os
    import threading
    import unittest.mock as mock
    from podscribe.tui import _listen_for_stop

    r_fd, w_fd = os.pipe()
    stop_ev = threading.Event()
    mock_capture = mock.MagicMock()
    stdin_r, stdin_w = os.pipe()

    import sys, time
    orig_stdin = sys.stdin

    class FakeFd:
        def fileno(self):
            return stdin_r

    sys.stdin = FakeFd()
    try:
        t = threading.Thread(target=_listen_for_stop, args=(mock_capture, r_fd, stop_ev))
        t.start()
        time.sleep(0.05)
        stop_ev.set()
        t.join(timeout=2.0)
    finally:
        sys.stdin = orig_stdin
        for fd in (r_fd, w_fd, stdin_r, stdin_w):
            try:
                os.close(fd)
            except OSError:
                pass

    assert not t.is_alive(), "thread did not exit after stop_event was set"
    mock_capture.stop.assert_not_called()


def test_listen_for_stop_non_tty_stdin_exits_gracefully():
    """If sys.stdin has no fileno() (e.g. StringIO), thread exits immediately."""
    import io
    import os
    import threading
    import unittest.mock as mock
    from podscribe.tui import _listen_for_stop

    r_fd, w_fd = os.pipe()
    stop_ev = threading.Event()
    mock_capture = mock.MagicMock()

    import sys
    orig_stdin = sys.stdin
    sys.stdin = io.StringIO()  # No fileno() that works

    try:
        t = threading.Thread(target=_listen_for_stop, args=(mock_capture, r_fd, stop_ev))
        t.start()
        t.join(timeout=2.0)
    finally:
        sys.stdin = orig_stdin
        for fd in (r_fd, w_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    assert not t.is_alive(), "thread should exit immediately when stdin has no real fd"
    mock_capture.stop.assert_not_called()


def test_listen_for_stop_closed_fds_exits_without_crash():
    """Closing fds while the thread is running must not crash the thread."""
    import os
    import threading
    import unittest.mock as mock
    from podscribe.tui import _listen_for_stop

    r_fd, w_fd = os.pipe()
    stop_ev = threading.Event()
    mock_capture = mock.MagicMock()
    stdin_r, stdin_w = os.pipe()

    import sys, time
    orig_stdin = sys.stdin

    class FakeFd:
        def fileno(self):
            return stdin_r

    sys.stdin = FakeFd()
    try:
        t = threading.Thread(target=_listen_for_stop, args=(mock_capture, r_fd, stop_ev))
        t.start()
        time.sleep(0.05)
        # Close the fds while the thread is blocked in select
        os.close(r_fd)
        os.close(stdin_r)
        t.join(timeout=2.0)
    finally:
        sys.stdin = orig_stdin
        for fd in (w_fd, stdin_w):
            try:
                os.close(fd)
            except OSError:
                pass

    assert not t.is_alive(), "thread should exit cleanly when fds are closed under it"


def test_set_input_raw_preserves_isig():
    """_set_input_raw must NOT clear ISIG so Ctrl+C still delivers SIGINT."""
    import sys
    import termios
    import unittest.mock as mock
    from podscribe.tui import _set_input_raw

    captured_modes = []

    def fake_tcsetattr(fd, when, mode):
        captured_modes.append(list(mode))

    with mock.patch("podscribe.tui.termios.tcgetattr", return_value=[0, 0, 0, 0b11111111, 0, 0, [0]*20]):
        with mock.patch("podscribe.tui.termios.tcsetattr", side_effect=fake_tcsetattr):
            _set_input_raw(0)

    assert captured_modes, "tcsetattr was never called"
    applied_lflag = captured_modes[0][3]
    assert applied_lflag & termios.ISIG, (
        f"ISIG was cleared in _set_input_raw (lflag={applied_lflag:#010b}); "
        "Ctrl+C would not deliver SIGINT"
    )
