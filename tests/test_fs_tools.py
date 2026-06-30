"""Tests for god mode filesystem tools."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from podscribe.fs_tools import (
    list_directory,
    read_file_tool,
    search_fs,
    find_symbol,
    find_references,
)


# ---------------------------------------------------------------------------
# list_directory
# ---------------------------------------------------------------------------

def test_list_directory_basic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.py").write_text("world")
    result = list_directory(".")
    assert "a.txt" in result
    assert "b.py" in result


def test_list_directory_recursive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("hi")
    result = list_directory(".", recursive=True)
    assert any("c.txt" in r for r in result)


def test_list_directory_skips_hidden(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_text("x")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "y.py").write_text("x")
    (tmp_path / "real.py").write_text("x")
    result = list_directory(".", recursive=True)
    assert not any(".git" in r for r in result)
    assert not any("__pycache__" in r for r in result)
    assert not any(".venv" in r for r in result)
    assert any("real.py" in r for r in result)


def test_list_directory_cap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for i in range(510):
        (tmp_path / f"f{i}.txt").write_text("x")
    result = list_directory(".")
    assert len(result) == 501  # 500 paths + 1 truncation notice
    assert result[-1] == "[...truncated at 500 entries]"


def test_list_directory_path_escape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = list_directory("../../etc")
    assert isinstance(result, dict)
    assert "error" in result


# ---------------------------------------------------------------------------
# read_file_tool
# ---------------------------------------------------------------------------

def test_read_file_full(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "f.txt").write_text("line1\nline2\nline3\n")
    result = read_file_tool("f.txt")
    assert "line1" in result
    assert "line2" in result
    assert "line3" in result


def test_read_file_range(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lines = "\n".join(f"line{i}" for i in range(1, 11))
    (tmp_path / "f.txt").write_text(lines)
    result = read_file_tool("f.txt", start_line=3, end_line=5)
    assert "line3" in result
    assert "line5" in result
    assert "line1" not in result
    assert "line6" not in result


def test_read_file_cap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    content = "\n".join(f"line{i}" for i in range(1, 600))
    (tmp_path / "big.txt").write_text(content)
    result = read_file_tool("big.txt")
    assert "[...truncated" in result


def test_read_file_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = read_file_tool("nonexistent.txt")
    assert isinstance(result, str)
    assert "not found" in result.lower() or "no such file" in result.lower()


def test_read_file_path_escape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = read_file_tool("../../etc/passwd")
    assert isinstance(result, dict)
    assert "error" in result


# ---------------------------------------------------------------------------
# search_fs
# ---------------------------------------------------------------------------

def test_search_fs_finds_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello world\nfoo bar\n")
    result = search_fs("hello", ".")
    assert len(result) >= 1
    assert any(r["file"] == "a.txt" for r in result)
    assert result[0]["line"] == 1
    assert "hello" in result[0]["text"]


def test_search_fs_no_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("no match here\n")
    result = search_fs("zzznomatch", ".")
    assert result == []


def test_search_fs_glob_filter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("TARGET = 1\n")
    (tmp_path / "b.txt").write_text("TARGET = 2\n")
    result = search_fs("TARGET", ".", include_glob="*.py")
    assert all(r["file"].endswith(".py") for r in result)


def test_search_fs_path_escape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = search_fs("x", "../../etc")
    assert isinstance(result, dict)
    assert "error" in result


# ---------------------------------------------------------------------------
# find_symbol
# ---------------------------------------------------------------------------

def test_find_symbol_def(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mod.py").write_text("def my_func(x):\n    pass\n")
    result = find_symbol("my_func", ".")
    assert len(result) >= 1
    assert result[0]["kind"] == "def"
    assert result[0]["name"] == "my_func"
    assert "mod.py" in result[0]["file"]


def test_find_symbol_class(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mod.py").write_text("class MyClass:\n    pass\n")
    result = find_symbol("MyClass", ".")
    assert len(result) >= 1
    assert result[0]["kind"] == "class"
    assert result[0]["name"] == "MyClass"


def test_find_symbol_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mod.py").write_text("x = 1\n")
    result = find_symbol("no_such_symbol", ".")
    assert result == []


# ---------------------------------------------------------------------------
# find_references
# ---------------------------------------------------------------------------

def test_find_references_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("result = my_func()\n")
    (tmp_path / "b.py").write_text("x = my_func(1, 2)\n")
    result = find_references("my_func", ".")
    assert len(result) >= 2
    files = {r["file"] for r in result}
    assert "a.py" in files
    assert "b.py" in files


def test_find_references_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    result = find_references("no_such_identifier", ".")
    assert result == []


def test_read_file_binary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data.bin").write_bytes(bytes(range(256)))
    result = read_file_tool("data.bin")
    assert isinstance(result, dict)
    assert "error" in result
    assert "binary" in result["error"].lower()


def test_find_symbol_path_escape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = find_symbol("foo", "../../etc")
    assert isinstance(result, dict)
    assert "error" in result
