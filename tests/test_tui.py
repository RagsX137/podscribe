from podscribe.tui import launch


def test_launch_no_pods_prints_panel_and_exits_0(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = launch()
    assert rc == 0
    out = capsys.readouterr().out
    assert "No pods" in out or "init" in out


def test_launch_with_pod_calls_record_or_enhance_view(tmp_path, monkeypatch):
    """With a pod and a non-interactive key (e.g. 'q'), launch should exit cleanly."""
    monkeypatch.chdir(tmp_path)
    from podscribe.storage import init_pod
    init_pod("sam-chen", display_name="Sam Chen")
    import podscribe.tui as tui
    monkeypatch.setattr(tui, "read_key", lambda: "q")
    monkeypatch.setattr(tui, "probe_ollama", lambda: False)
    rc = launch()
    assert rc == 0
