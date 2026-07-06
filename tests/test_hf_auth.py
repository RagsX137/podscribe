"""Tests for HF token resolution. Stdlib only; no network, no pyannote."""
import getpass
import sys

import pytest

from podscribe import hf_auth


def test_get_hf_token_prefers_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "env-token-abc")
    monkeypatch.setattr(hf_auth, "HF_TOKEN_PATH", tmp_path / "hf_token")
    assert hf_auth.get_hf_token(interactive=False) == "env-token-abc"


def test_get_hf_token_reads_cached_file(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    token_path = tmp_path / "hf_token"
    token_path.write_text("file-token-xyz")
    monkeypatch.setattr(hf_auth, "HF_TOKEN_PATH", token_path)
    assert hf_auth.get_hf_token(interactive=False) == "file-token-xyz"


def test_get_hf_token_none_when_nothing_and_not_interactive(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(hf_auth, "HF_TOKEN_PATH", tmp_path / "nonexistent")
    assert hf_auth.get_hf_token(interactive=False) is None


def test_get_hf_token_whitespace_stripped(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "  spaced-token  \n")
    monkeypatch.setattr(hf_auth, "HF_TOKEN_PATH", tmp_path / "hf_token")
    assert hf_auth.get_hf_token(interactive=False) == "spaced-token"


def test_save_hf_token_mode_0600_and_parent_dir(tmp_path, monkeypatch):
    token_path = tmp_path / "nested" / "podscribe" / "hf_token"
    monkeypatch.setattr(hf_auth, "HF_TOKEN_PATH", token_path)
    hf_auth.save_hf_token("secret-token")
    assert token_path.read_text() == "secret-token"
    if sys.platform != "win32":
        # POSIX file-mode bits are meaningless on Windows.
        assert (token_path.stat().st_mode & 0o077) == 0


def test_prompt_saves_and_returns_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(hf_auth, "HF_TOKEN_PATH", tmp_path / "hf_token")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "new-token-123\n")
    assert hf_auth.prompt_for_hf_token() == "new-token-123"
    assert (tmp_path / "hf_token").read_text() == "new-token-123"


def test_prompt_none_on_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(hf_auth, "HF_TOKEN_PATH", tmp_path / "hf_token")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "")
    assert hf_auth.prompt_for_hf_token() is None
    assert not (tmp_path / "hf_token").exists()


def test_prompt_none_when_not_tty(tmp_path, monkeypatch):
    monkeypatch.setattr(hf_auth, "HF_TOKEN_PATH", tmp_path / "hf_token")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert hf_auth.prompt_for_hf_token() is None
    assert not (tmp_path / "hf_token").exists()
