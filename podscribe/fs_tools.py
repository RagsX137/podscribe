"""Read-only filesystem and code-intelligence tools for the god mode agent.

All paths are sandboxed to Path.cwd(). Any path that resolves outside the
project root returns {"error": "Path outside project root."}.
No shell=True. No write operations.
"""
from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .agent_tools import MAX_TOOL_RESULT_CHARS

_SKIP_DIRS = {".git", "__pycache__", ".venv", ".pytest_cache", "node_modules"}
_MAX_DIR_ENTRIES = 500
_MAX_FILE_LINES = 500
_MAX_SEARCH_HITS = 100


def _safe_resolve(path_str: str) -> Path | dict:
    """Resolve path relative to cwd. Returns Path or error dict if outside root."""
    root = Path.cwd().resolve()
    resolved = (root / path_str).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return {"error": "Path outside project root."}
    return resolved


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + "\n[...truncated, full result on disk]"


def list_directory(path: str = ".", recursive: bool = False) -> list[str] | dict:
    """List files and directories under path. Skips .git, __pycache__, .venv."""
    resolved = _safe_resolve(path)
    if isinstance(resolved, dict):
        return resolved
    if not resolved.exists():
        return {"error": f"Path not found: {path}"}
    if not resolved.is_dir():
        return {"error": f"Not a directory: {path}"}

    root = Path.cwd().resolve()
    entries: list[str] = []

    if recursive:
        for dirpath, dirnames, filenames in os.walk(resolved):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for name in sorted(filenames):
                full = Path(dirpath) / name
                try:
                    rel = str(full.relative_to(root))
                except ValueError:
                    rel = str(full)
                entries.append(rel)
                if len(entries) >= _MAX_DIR_ENTRIES:
                    entries.append("[...truncated at 500 entries]")
                    return entries
    else:
        for item in sorted(resolved.iterdir()):
            if item.name in _SKIP_DIRS:
                continue
            try:
                rel = str(item.relative_to(root))
            except ValueError:
                rel = str(item)
            entries.append(rel)
            if len(entries) >= _MAX_DIR_ENTRIES:
                entries.append("[...truncated at 500 entries]")
                return entries

    return entries


def read_file_tool(
    path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> str | dict:
    """Read a text file, optionally between start_line and end_line (1-based)."""
    resolved = _safe_resolve(path)
    if isinstance(resolved, dict):
        return resolved
    if not resolved.exists():
        return f"File not found: {path}"
    if not resolved.is_file():
        return f"Not a file: {path}"

    try:
        raw_bytes = resolved.read_bytes()
        # Reject binary files
        raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return {"error": "Binary file — cannot read as text."}

    lines = raw_bytes.decode("utf-8").splitlines(keepends=True)
    total = len(lines)

    s = (start_line - 1) if start_line is not None else 0
    e = end_line if end_line is not None else total
    s = max(0, s)
    e = min(total, e)

    selected = lines[s:e]
    truncated = False
    if len(selected) > _MAX_FILE_LINES:
        selected = selected[:_MAX_FILE_LINES]
        truncated = True

    result = "".join(selected)
    if truncated:
        result += f"\n[...truncated at {_MAX_FILE_LINES} lines]"
    return _truncate(result)


def _rg_available() -> bool:
    return shutil.which("rg") is not None


def search_fs(
    query: str,
    path: str = ".",
    include_glob: Optional[str] = None,
) -> list[dict] | dict:
    """Fixed-string search across files. Returns [{file, line, text}]."""
    resolved = _safe_resolve(path)
    if isinstance(resolved, dict):
        return resolved
    if not resolved.exists():
        return {"error": f"Path not found: {path}"}

    root = Path.cwd().resolve()

    if _rg_available():
        cmd = ["rg", "--fixed-strings", "--line-number", "--no-heading", "--color=never",
               "--", query, str(resolved)]
        if include_glob:
            cmd = ["rg", "--fixed-strings", "--line-number", "--no-heading", "--color=never",
                   f"--glob={include_glob}", "--", query, str(resolved)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return _parse_rg_output(proc.stdout, root)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # fall through to Python

    # Python fallback
    hits: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(resolved):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in sorted(filenames):
            if include_glob:
                if not fnmatch.fnmatch(fname, include_glob):
                    continue
            fpath = Path(dirpath) / fname
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(content.splitlines(), 1):
                if query in line:
                    try:
                        rel = str(fpath.relative_to(root))
                    except ValueError:
                        rel = str(fpath)
                    hits.append({"file": rel, "line": lineno, "text": line.strip()})
                    if len(hits) >= _MAX_SEARCH_HITS:
                        return hits
    return hits


def _parse_rg_output(output: str, root: Path) -> list[dict]:
    """Parse rg --line-number --no-heading output into [{file, line, text}]."""
    hits: list[dict] = []
    for raw_line in output.splitlines():
        # Format: path:lineno:text
        parts = raw_line.split(":", 2)
        if len(parts) < 3:
            continue
        fpath_str, lineno_str, text = parts
        try:
            lineno = int(lineno_str)
        except ValueError:
            continue
        try:
            rel = str(Path(fpath_str).relative_to(root))
        except ValueError:
            rel = fpath_str
        hits.append({"file": rel, "line": lineno, "text": text.strip()})
        if len(hits) >= _MAX_SEARCH_HITS:
            break
    return hits


def find_symbol(name: str, path: str = ".") -> list[dict] | dict:
    """Find Python def/class declarations by name. Returns [{file, line, kind, name}]."""
    resolved = _safe_resolve(path)
    if isinstance(resolved, dict):
        return resolved
    if not resolved.exists():
        return {"error": f"Path not found: {path}"}

    root = Path.cwd().resolve()
    pattern = re.compile(
        r"^[ \t]*(def|class)\s+" + re.escape(name) + r"\b"
    )
    hits: list[dict] = []

    if _rg_available():
        cmd = ["rg", "--type=py", "--line-number", "--no-heading", "--color=never",
               f"(def|class) {name}\\b", str(resolved)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            for raw_line in proc.stdout.splitlines():
                parts = raw_line.split(":", 2)
                if len(parts) < 3:
                    continue
                fpath_str, lineno_str, text = parts
                m = pattern.search(text)
                if not m:
                    continue
                kind = m.group(1)
                try:
                    lineno = int(lineno_str)
                except ValueError:
                    continue
                try:
                    rel = str(Path(fpath_str).relative_to(root))
                except ValueError:
                    rel = fpath_str
                hits.append({"file": rel, "line": lineno, "kind": kind, "name": name})
            return hits
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # fall through

    # Python fallback
    for dirpath, dirnames, filenames in os.walk(resolved):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in sorted(filenames):
            if not fname.endswith(".py"):
                continue
            fpath = Path(dirpath) / fname
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(content.splitlines(), 1):
                m = pattern.match(line)
                if m:
                    try:
                        rel = str(fpath.relative_to(root))
                    except ValueError:
                        rel = str(fpath)
                    hits.append({"file": rel, "line": lineno, "kind": m.group(1), "name": name})
    return hits


def find_references(name: str, path: str = ".") -> list[dict] | dict:
    """Find all occurrences of an identifier across files. Returns [{file, line, text}]."""
    resolved = _safe_resolve(path)
    if isinstance(resolved, dict):
        return resolved
    if not resolved.exists():
        return {"error": f"Path not found: {path}"}

    root = Path.cwd().resolve()

    if _rg_available():
        cmd = ["rg", "--fixed-strings", "--word-regexp", "--line-number",
               "--no-heading", "--color=never", "--", name, str(resolved)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return _parse_rg_output(proc.stdout, root)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # fall through

    # Python fallback — word-boundary match
    pattern = re.compile(r"\b" + re.escape(name) + r"\b")
    hits: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(resolved):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    try:
                        rel = str(fpath.relative_to(root))
                    except ValueError:
                        rel = str(fpath)
                    hits.append({"file": rel, "line": lineno, "text": line.strip()})
                    if len(hits) >= _MAX_SEARCH_HITS:
                        return hits
    return hits
