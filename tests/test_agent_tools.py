from __future__ import annotations


def test_list_and_show_kt_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from podscribe.cli import main
    from podscribe.storage import init_pod
    init_pod("fso")
    video = tmp_path / "kt.mp4"
    video.touch()
    (tmp_path / "kt.vtt").write_text("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nkt content here\n")
    assert main(["fso", "ingest", str(video)]) == 0

    from podscribe.agent_tools import list_kt_tool, show_kt
    sessions = list_kt_tool("fso")
    assert len(sessions) == 1
    assert "kt content here" in show_kt("fso", "latest")
