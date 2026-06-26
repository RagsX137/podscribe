# God Mode — Filesystem & Code-Intelligence Tools

**Date:** 2026-06-27
**Status:** Approved design
**Branch:** main

## Overview

Extend god mode's agent tool set with 5 read-only filesystem and code-intelligence tools so the Ollama agent can inspect the project's source code, transcripts, and any other files on disk during a session. No write access is granted.

## New module: `podscribe/fs_tools.py`

All 5 tools live here. `agent_tools.py` imports and re-exports them. The separation keeps pod-domain logic distinct from filesystem concerns.

### Safety model

- Every `path` argument is resolved with `Path(path).resolve()` relative to `Path.cwd()`.
- If the resolved path does not share the `Path.cwd()` prefix the call returns `{"error": "Path outside project root."}`.
- `search_fs`, `find_symbol`, and `find_references` use `subprocess.run([...], shell=False)` with `rg` when available; fall back to a pure-Python `re` walk otherwise.
- No `shell=True` anywhere in `fs_tools.py`.
- Output is always capped and passed through `_truncate` (8000 chars, inherited from `agent_tools.MAX_TOOL_RESULT_CHARS`).

## Tool inventory

### `list_directory(path=".", recursive=False) → list[str]`

Returns sorted relative paths under `path`. Skips `.git/`, `__pycache__/`, `.venv/` directories. Capped at 500 entries; appends `"[...truncated at 500 entries]"` if hit.

### `read_file_tool(path, start_line=None, end_line=None) → str`

Reads a text file. Lines are 1-based (matching the AGENTS.md convention). Returns up to 500 lines per call with a `[...truncated]` notice if the range exceeds that. Binary files return `{"error": "Binary file — cannot read as text."}`.

### `search_fs(query, path=".", include_glob=None) → list[dict]`

Fixed-string (not regex) search across files. Returns up to 100 matches as `[{file, line, text}]`. `include_glob` maps to `rg --glob`. Python fallback: `os.walk` + `str.find`. Skips `.git/`, `__pycache__/`, `.venv/`.

### `find_symbol(name, path=".") → list[dict]`

Searches `.py` files for `def <name>` and `class <name>` declarations. Returns `[{file, line, kind, name}]` where `kind` is `"def"` or `"class"`. Uses `rg --type py` when available. Python fallback: `re` over `.py` files.

### `find_references(name, path=".") → list[dict]`

Fixed-string search for the identifier `name` across all files under `path`. Returns `[{file, line, text}]`, up to 100 matches. Uses `rg -F` (fixed-string). Python fallback: `str.find` walk.

## Changes to `agent.py`

### New tool defs (5 entries appended to `_build_tool_defs()`)

```python
{"type": "function", "function": {
    "name": "list_directory",
    "description": "List files and directories under a path",
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Directory path (default '.')"},
        "recursive": {"type": "boolean", "description": "Recurse into subdirectories"},
    }},
}},
{"type": "function", "function": {
    "name": "read_file_tool",
    "description": "Read a file, optionally between start_line and end_line (1-based)",
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "File path"},
        "start_line": {"type": "integer", "description": "First line to return (1-based)"},
        "end_line": {"type": "integer", "description": "Last line to return (1-based, inclusive)"},
    }, "required": ["path"]},
}},
{"type": "function", "function": {
    "name": "search_fs",
    "description": "Fixed-string search across files; returns [{file, line, text}]",
    "parameters": {"type": "object", "properties": {
        "query": {"type": "string", "description": "Search string"},
        "path": {"type": "string", "description": "Root path to search (default '.')"},
        "include_glob": {"type": "string", "description": "Glob filter, e.g. '*.py'"},
    }, "required": ["query"]},
}},
{"type": "function", "function": {
    "name": "find_symbol",
    "description": "Find Python def/class declarations by name",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string", "description": "Symbol name"},
        "path": {"type": "string", "description": "Root path to search (default '.')"},
    }, "required": ["name"]},
}},
{"type": "function", "function": {
    "name": "find_references",
    "description": "Find all occurrences of an identifier across files",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string", "description": "Identifier to find"},
        "path": {"type": "string", "description": "Root path to search (default '.')"},
    }, "required": ["name"]},
}},
```

### `TOOL_REGISTRY` additions

```python
"list_directory":   fs_tools.list_directory,
"read_file_tool":   fs_tools.read_file_tool,
"search_fs":        fs_tools.search_fs,
"find_symbol":      fs_tools.find_symbol,
"find_references":  fs_tools.find_references,
```

### Import

```python
from . import fs_tools
```

## Changes to `tests/test_agent.py`

`test_build_tool_defs_has_all_tools` expected set gains the 5 new names.

## New test file: `tests/test_fs_tools.py`

Unit tests (no ripgrep required — all tests use the Python fallback path or real `tmp_path` files):

| Test | What it checks |
|---|---|
| `test_list_directory_basic` | Returns relative paths, skips hidden dirs |
| `test_list_directory_recursive` | Recurse flag works |
| `test_list_directory_cap` | >500 files → truncation notice |
| `test_list_directory_path_escape` | `../..` → error |
| `test_read_file_full` | Returns all lines |
| `test_read_file_range` | `start_line`/`end_line` slices correctly |
| `test_read_file_cap` | >500 lines → truncation notice |
| `test_read_file_missing` | Missing file → error string |
| `test_read_file_path_escape` | `../..` → error |
| `test_search_fs_finds_match` | Returns `{file, line, text}` dicts |
| `test_search_fs_no_match` | Returns empty list |
| `test_search_fs_glob_filter` | `include_glob="*.py"` limits results |
| `test_find_symbol_def` | Finds `def foo` |
| `test_find_symbol_class` | Finds `class Bar` |
| `test_find_symbol_none` | Unknown name → empty list |
| `test_find_references_found` | Returns occurrences |
| `test_find_references_empty` | No hits → empty list |

## Files to create/modify

| File | Action |
|---|---|
| `podscribe/fs_tools.py` | **Create** — 5 tool functions + safety helpers |
| `podscribe/agent.py` | **Modify** — 5 new tool defs + registry entries + `from . import fs_tools` |
| `podscribe/agent_tools.py` | **Modify** — re-export 5 fs_tools functions (optional convenience) |
| `tests/test_fs_tools.py` | **Create** — 17 unit tests |
| `tests/test_agent.py` | **Modify** — update `test_build_tool_defs_has_all_tools` expected set |
