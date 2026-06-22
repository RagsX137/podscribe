# Design: Section 4 Architecture Fixes

**Date:** 2026-06-22
**Status:** Approved
**Branch:** `feature/section-4-architecture` (off `main` after `fix/recommended-cleanup` lands)
**Source review:** `Recommended_fixes.md` §4 (root of repo)
**Scope:** All 7 findings (4.1 – 4.7) in a single PR.

## Summary

Seven architecture improvements from the original audit. None are bug fixes;
they pay down technical debt and unlock the team-lead workflows in §5. One
PR, twelve commits, TDD throughout. No new runtime dependencies (`tarfile`
and `Path` are stdlib; `rg` is optional with a Python fallback).

## Decisions locked during brainstorming

| Decision | Choice |
|---|---|
| Scope | All 7 in one PR |
| 4.1 refactor | Narrow: helper returns `(text, err)`; caller picks the path |
| 4.2 list filters | `cmd list` gains `--all`, `--since`, `--recent`, `--type` |
| 4.3 global CSV | Project-root `pods/meetings.csv`, written alongside per-pod CSV |
| 4.4 cache | mtime check on every get; key includes pod.glossary snapshot |
| 4.5 storage layout | Additive optional subdir; unspecified = no subdir |
| 4.5 type values | Fixed enum (7 values) validated at record time |
| 4.6 search output | `pod-name:DD-MMM-YYYY:<meeting-id>:[HH:MM:SS]:<line-text>` |
| 4.7 export scope | Source-only (no `.raw`, no `.env`, no `__pycache__`) |

## Out of scope (deferred)

- §2.6 CSV thread-safety — user confirmed sequential use. 4.3 increases the
  single-file contention but does not change the calculus.
- §3.4 rolling `last_n_text` glossary continuity. (4.4 cache is the
  foundational piece; the rolling-continuity feature is a follow-on.)
- §5 team-lead commands (`prep`, `blockers`, `digest`, `stats`).
- §6 async jobs / `--fast` / `--deep`.
- §3.1 model default change.

## Pre-requisite

`fix/recommended-cleanup` must be merged to `main` first. This design
preserves all behavior from that PR (`_resolve_meeting` helper, empty-
transcript guard, `preserve_speakers` toggle, streaming enhance, etc.).

---

## 1. 4.1 — Extract `_run_enhance`

**File:** `podscribe/cli.py` (new private helper near `_resolve_meeting`)

`cmd_enhance` and `cmd_consolidate` both run the same LLM-call +
reachability-check pattern. Extract it.

**Signature:**

```python
def _run_enhance(
    pod: Pod, meeting: Meeting, prompt: str, model: str,
) -> tuple[Optional[str], Optional[str]]:
    """Run LLM enhance. Returns (text, None) on success, (None, error) on failure.

    The error string is what gets printed to stderr; it owns the Ollama-
    availability message so both call sites stay in sync.
    """
    result = enhance_transcript(model, prompt)
    if result is None:
        return None, "Failed to reach Ollama. Is it running? Start with: ollama serve"
    return result, None
```

**Caller updates:**

`cmd_enhance` after the prompt-build:

```python
text, err = _run_enhance(pod, meeting, prompt, llm_config["model"])
if err is not None:
    print(err, file=sys.stderr)
    return 1
date_str = fmt_date(datetime.fromisoformat(meeting.started_at))
summary_path = pod.summaries_dir_for(date_str) / f"{meeting.id}.md"
summary_path.parent.mkdir(parents=True, exist_ok=True)
summary_path.write_text(text)
print(f"Enhanced transcript saved to {summary_path}")
return 0
```

`cmd_consolidate` after the prompt-build:

```python
text, err = _run_enhance(pod, meeting, prompt, model_name)
if err is not None:
    print(err, file=sys.stderr)
    return 1
# existing parse-YAML-and-update-CSV logic, using `text` instead of `response`
```

Both call sites keep their own meeting lookup, prefix resolution, empty-
guard, prompt construction, and post-processing. The helper owns only the
two lines that were identical: the LLM call and the connectivity error.

---

## 2. 4.4 — Glossary cache with mtime

**File:** `podscribe/config.py`

`get_effective_glossary` (`config.py:106`) re-reads `leadership_team.yaml`
on every call. During a record session this fires once per segment —
cheap, but not free, and not necessary.

**Cache shape** (module-level):

```python
_glossary_cache: dict = {
    "key": None,        # tuple of (leadership_mtime, pod.glossary_id)
    "value": None,      # the resolved list
}


def _leadership_yaml_path() -> Path:
    return Path("leadership_team.yaml")


def get_effective_glossary(pod: Pod) -> list:
    """Return leadership + pod glossary, cached by mtime + pod.glossary id."""
    try:
        mtime = _leadership_yaml_path().stat().st_mtime
    except FileNotFoundError:
        mtime = 0
    key = (mtime, id(pod.glossary), len(pod.glossary))
    if _glossary_cache.get("key") != key:
        _glossary_cache["key"] = key
        _glossary_cache["value"] = _read_effective_glossary(pod)
    return _glossary_cache["value"]


def _read_effective_glossary(pod: Pod) -> list:
    """The actual disk read. Reads leadership_team.yaml + pod.glossary."""
    leadership = load_leadership_glossary() or []
    return leadership + list(pod.glossary or [])
```

**Why `id(pod.glossary)` + `len()`:** `pod.glossary` is a list that may be
mutated in place (e.g. `add_entry` appends). `id()` catches reference
changes (e.g. `pod.glossary = new_list`); `len()` is a cheap sanity check
for in-place mutation. The full correctness invariant is that any
mutation of `pod.glossary` either goes through the same `Pod` object (in
which case `id()` matches and the cache is still valid) or replaces the
list (in which case `id()` differs and the cache invalidates).

**`save_pod_config` is a no-op for invalidation** because the cached value
includes `pod.glossary` directly, not a serialised snapshot. If the caller
mutates the list and writes to disk, the cache is still correct.

**`stat()` is sub-microsecond on macOS.** The per-segment hit during record
is now: 1 stat + 1 dict comparison + 1 list copy instead of a file read.

---

## 3. 4.5 — Meeting type

**Files:** `podscribe/models.py`, `podscribe/cli.py`, `podscribe/storage.py`

**Enum** (in `models.py`):

```python
MEETING_TYPES = (
    "1on1",
    "retro",
    "skip-level",
    "design-review",
    "standup",
    "interview",
    "other",
)


def parse_meeting_type(raw: Optional[str]) -> Optional[str]:
    """Normalize and validate a --type argument. Returns the canonical form or None."""
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized not in MEETING_TYPES:
        valid = ", ".join(MEETING_TYPES)
        raise ValueError(
            f"Unknown meeting type '{raw}'. Valid types: {valid}"
        )
    return normalized
```

**CLI** (record subparser):

```
podscribe <pod> record --type 1on1
podscribe <pod> record --type retro --model large-v3-turbo
```

`cmd_record` calls `parse_meeting_type(args.type)`; on `ValueError`, prints
to stderr and returns 1. The type is then passed to `start_meeting`.

**Storage (additive):**

`Meeting` dataclass gains a field:

```python
@dataclass
class Meeting:
    ...existing fields...
    type: Optional[str] = None
```

`start_meeting` (`storage.py:102`) accepts `meeting_type: Optional[str] = None`:

```python
def start_meeting(
    pod: Pod, when: Optional[datetime] = None,
    meeting_type: Optional[str] = None,
) -> Meeting:
    when = when or datetime.now()
    meeting_id = make_meeting_id(pod.name, when)
    date_str = fmt_date(when)
    base_dir = pod.transcripts_dir_for(date_str)
    transcript_dir = base_dir / meeting_type if meeting_type else base_dir
    transcript_dir.mkdir(parents=True, exist_ok=True)
    ...
    return Meeting(
        ...,
        type=meeting_type,
    )
```

The audio and metadata paths stay in the same subdir as the transcript.

**JSON sidecar** (`finalize_meeting`, `storage.py:137`): add `"type":
meeting.type` to the metadata dict. `list_meetings` reads it back.

**`list_meetings` glob** (`storage.py:167`): the existing glob
`pod.base_path.glob("transcripts/*/*.json")` matches the 2-level layout
(`transcripts/<date>/<id>.json`). To also match the 3-level typed
subdir layout (`transcripts/<date>/<type>/<id>.json`), add a second glob
and dedupe. `Path.glob` is a single-segment matcher, so each `*` is one
path component; we need both the 2- and 3-segment patterns.

```python
json_paths = set()
json_paths.update(pod.base_path.glob("transcripts/*/*.json"))
json_paths.update(pod.base_path.glob("transcripts/*/*/*.json"))
for json_path in sorted(json_paths):
    try:
        with json_path.open() as f:
            data = json.load(f)
        # ...existing Meeting-construction logic, reading data.get("type")
    except (json.JSONDecodeError, KeyError, ValueError):
        continue
```

`list_meetings` already skips files where JSON parsing fails, so a glob
that hits an unrelated `*.json` is harmless. The `set` dedupes if a file
matches both patterns (it won't, but defensive).

**Backward compatibility:** existing meetings (no `type` in JSON sidecar)
appear with `Meeting.type = None`. The `list --type 1on1` filter excludes
them. `cmd_show` doesn't care.

---

## 4. 4.3 — Global `meetings.csv`

**File:** `podscribe/storage.py` (additions)

**Path:** `pods/meetings.csv` (project root, alongside `podscribe.yaml`).
Same schema as the per-pod file (`storage.py:CSV_COLUMNS`).

**Writer additions:**

```python
def global_log_path() -> Path:
    return Path("pods") / "meetings.csv"


def append_global_log_row(fields: dict) -> bool:
    """Append a row to the global CSV. Returns True on success, False on error.

    Errors are NOT raised — the per-pod CSV is the authoritative record.
    A global-write failure is logged to stderr but does not block the caller.
    """
    try:
        path = global_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        new_row = {col: fields.get(col, "") for col in CSV_COLUMNS}
        file_exists = path.exists()
        with path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(new_row)
        return True
    except OSError as e:
        print(f"Warning: failed to write global log: {e}", file=sys.stderr)
        return False


def read_global_log() -> list[dict]:
    """Read all rows from the global meetings.csv."""
    path = global_log_path()
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))
```

**Hook into `append_log_row`:**

```python
def append_log_row(pod: Pod, fields: dict) -> None:
    path = log_path(pod)
    new_row = {col: fields.get(col, "") for col in CSV_COLUMNS}
    file_exists = path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(new_row)
    # Mirror to global CSV. Failure here does not raise.
    append_global_log_row(fields)
```

`update_log_row` is NOT mirrored. Rationale: the global CSV is a derived
view; corrections go through the per-pod path, and the global row is
rebuilt on next consolidate (a separate "rebuild" command is out of
scope). The global row may briefly disagree with the per-pod row until
the next consolidate run for that meeting; this matches the existing
"eventually consistent" posture of the system.

**`list --all` mode** (4.2) reads `read_global_log()` instead of scanning
per-pod CSVs.

---

## 5. 4.2 — `list` filters

**File:** `podscribe/cli.py:cmd_list`

**New flags:**

```
podscribe list [<pod>] [--all] [--since 7d|YYYY-MM-DD] [--recent N] [--type <type>]
```

- `<pod>` (new, optional): if absent, defaults to scanning all pods. With
  `<pod>`, the command shows that pod's meetings only.
- `--all`: explicit "scan all pods" mode (default behavior when `<pod>`
  is absent)
- `--since DURATION` (e.g. `7d`, `24h`, `30m`): filter to meetings started
  within the duration. ISO date (`2026-06-15`) also accepted.
- `--since DATE`: same flag, accepts `YYYY-MM-DD` for absolute dates
- `--recent N`: limit to N most recent
- `--type TYPE`: filter to one meeting type (uses 4.5 enum)

**Output:** markdown table.

```
POD              TYPE       DATE          MEETING ID                          DURATION
sam-chen         1on1       22-JUN-2026   2026-06-22-143012-sam-chen          00:32:14
priya-rao        retro      21-JUN-2026   2026-06-21-094512-priya-rao         00:18:02
```

**Backend:**

```python
def cmd_list(args) -> int:
    if args.all or args.pod is None:
        rows = read_global_log()
    else:
        rows = _read_pod_log(args.pod)
    # Apply filters
    if args.since:
        cutoff = _parse_since(args.since)  # datetime
        rows = [r for r in rows if _csv_date(r["date"]) >= cutoff.date()]
    if args.type:
        try:
            valid_type = parse_meeting_type(args.type)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        rows = [r for r in rows if r.get("type") == valid_type]
    if args.recent:
        rows = rows[:args.recent]
    if not rows:
        print("(no meetings)")
        return 0
    # print markdown table
    ...
```

`_parse_since` accepts:
- `7d`, `24h`, `30m` → duration string parsed by a small helper
- `2026-06-15` → ISO date

**Edge case:** global CSV is empty (no consolidates yet). `list --all`
prints `(no meetings)` and returns 0. The per-pod fallback for
`list <pod>` still works (reads `pods/<pod>/meetings.csv`).

---

## 6. 4.6 — `podscribe search`

**New file:** `podscribe/search.py`
**New command:** `podscribe search <query> [--pod <name>] [--since <duration|date>] [--type <type>] [--color]`

**Signature:**

```python
def search(
    query: str,
    *,
    pod: Optional[str] = None,
    since: Optional[str] = None,
    meeting_type: Optional[str] = None,
    color: bool = False,
) -> Iterator[SearchMatch]:
    """Yield SearchMatch objects for each matching line in any transcript .md."""
    ...


@dataclass
class SearchMatch:
    pod_name: str
    date_str: str       # e.g. "22-JUN-2026"
    meeting_id: str     # e.g. "2026-06-22-143012-sam-chen"
    timestamp: str      # e.g. "[00:01:23]"
    text: str           # the line text (without the timestamp prefix)
```

**Output line** (in `cmd_search`):

```python
print(f"{m.pod_name}:{m.date_str}:{m.meeting_id}:{m.timestamp} {m.text}")
```

With `--color`: ANSI bold the `pod_name` and `timestamp`, yellow the
query match. Uses `sys.stdout.isatty()` to default `color=True` if
attached to a terminal and the user didn't explicitly pass `--color` /
`--no-color`.

**Backend strategy:**

1. Determine the file list:
   - If `--pod`: `Path(f"pods/{pod}/transcripts").rglob("*.md")`
   - Else: `Path("pods").rglob("*.md")` filtered by `"transcripts" in path.parts`

2. Apply `--since` filter: parse the date from the meeting ID prefix
   (the first 10 characters of the filename stem, in `YYYY-MM-DD` form).
   The meeting ID is `YYYY-MM-DD-HHMMSS-<pod>`, so the date is always
   `Path(file).stem[:10]`. Skip files outside the window.

3. Apply `--type` filter: skip files where the path component
   between the date dir and the file is a type dir that doesn't match
   the requested type. Files with 2 levels (no type subdir) are
   excluded by `--type` (a 2-level file has no type to match).

4. For each remaining file:
   - If `rg` on PATH: `subprocess.run(["rg", "-F", "--no-heading", "-n", query, str(file)], capture_output=True, text=True)`. Parse output, yield matches.
   - Else: `file.read_text().splitlines()` and `if query in line:`. Yield matches.

5. Each match's `timestamp` is parsed from the line prefix
   `[HH:MM:SS]`. If the line doesn't have the prefix, timestamp is `""`.

**No new dependencies.** `subprocess`, `pathlib`, `shutil.which` are stdlib.

**Edge cases:**

| Case | Behavior |
|---|---|
| `rg` not installed | Fall back to Python `Path.rglob` + `in` check |
| Query has regex meta-chars | Use `rg -F` (fixed string); Python uses `in`, no regex |
| Query has spaces | Pass as one argv element; both backends handle it |
| File is undecodable | Skip with a warning to stderr; continue |
| Path has 3 levels but `--type` not set | Include the file (typed meetings are still searchable) |
| Path has 2 levels and `--type 1on1` set | Exclude the file (no type set → can't match) |
| `--since 7d` and file has no `started_at` | Use file mtime as a fallback for date filter |
| Empty result | Print `No matches.` and return 0 |

---

## 7. 4.7 — `podscribe export` / `podscribe import`

**New file:** `podscribe/export.py`

**`create_export(out_path: Path) -> Path`:**

If `out_path` is `-` or `None`, write tarball to `sys.stdout.buffer` and
return a sentinel. Otherwise write to `out_path`.

```python
def create_export(out_path: Optional[Path] = None) -> Path:
    """Bundle pods/, leadership_team.yaml, and podscribe.yaml into a tar.gz.

    Excludes: .raw files, .env, __pycache__/, .pytest_cache/, .venv/.
    """
    members = []
    for path in _iter_export_members():
        members.append(path)
    # Use tarfile.open with mode="w:gz"
    if out_path is None or str(out_path) == "-":
        # write to stdout
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w:gz") as tar:
            for m in members:
                tar.add(m, arcname=m.relative_to(Path.cwd()))
        return Path("-")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_path, "w:gz") as tar:
        for m in members:
            tar.add(m, arcname=str(m.relative_to(Path.cwd())))
    return out_path


def _iter_export_members() -> Iterator[Path]:
    """Walk pods/, leadership_team.yaml, podscribe.yaml; yield paths to include."""
    cwd = Path.cwd()
    pods_dir = cwd / "pods"
    if pods_dir.exists():
        for path in pods_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(cwd)
            parts = rel.parts
            # Exclude .raw files
            if path.suffix == ".raw":
                continue
            # Exclude __pycache__ etc.
            if any(p in parts for p in ("__pycache__", ".pytest_cache", ".venv")):
                continue
            yield path
    for fname in ("leadership_team.yaml", "podscribe.yaml"):
        fpath = cwd / fname
        if fpath.exists():
            yield fpath
```

**`import_archive(archive_path: Path, *, force: bool = False, dry_run: bool = False) -> int`:**

```python
def import_archive(
    archive_path: Path, *, force: bool = False, dry_run: bool = False,
) -> int:
    """Extract a podscribe export tarball into the current directory.

    Default: refuse to overwrite existing pods. --force: overwrite.
    --dry-run: print what would happen, do not write.
    """
    pods_in_tar = set()
    other_members = []
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            # Path-traversal check
            target = (Path.cwd() / member.name).resolve()
            if not str(target).startswith(str(Path.cwd().resolve())):
                raise ValueError(f"Unsafe path in tarball: {member.name}")
            # Categorize
            parts = Path(member.name).parts
            if parts and parts[0] == "pods" and len(parts) >= 2:
                pods_in_tar.add(parts[1])
            else:
                other_members.append(member)

    # Check conflicts
    existing = {p.name for p in Path("pods").iterdir()} if Path("pods").exists() else set()
    conflicts = pods_in_tar & existing
    if conflicts and not force:
        print(
            f"Refusing to overwrite existing pods: {sorted(conflicts)}.\n"
            f"Re-run with --force to replace them.",
            file=sys.stderr,
        )
        return 1

    if dry_run:
        print(f"Would import: {sorted(pods_in_tar)}")
        if other_members:
            print(f"Would also import: {[m.name for m in other_members]}")
        return 0

    # Extract
    with tarfile.open(archive_path, "r:gz") as tar:
        _safe_extract(tar, path=Path.cwd())
    print(f"Imported: {sorted(pods_in_tar)}")
    return 0


def _safe_extract(tar: tarfile.TarFile, path: Path = Path(".")) -> None:
    """Extract every member with a path-traversal check.

    Python 3.12 added `tar.extractall(filter="data")` for this purpose,
    but the project supports Python 3.10+. This function is the manual
    equivalent and works on all supported versions.
    """
    cwd_resolved = path.resolve()
    for member in tar.getmembers():
        target = (path / member.name).resolve()
        if not str(target).startswith(str(cwd_resolved) + sep) and target != cwd_resolved:
            raise ValueError(f"Unsafe path in tarball: {member.name}")
    tar.extractall(path=path)
```

The test suite covers both the happy path and the path-traversal
rejection.

**Path-traversal protection** uses `Path.resolve()` and a prefix check
on the cwd. This blocks `pods/../../etc/passwd`-style attacks and any
absolute path.

**Excluded from import:** same exclusions as export (`.raw`, `__pycache__`,
etc.) — `tarfile` will simply not include them in the member list.

**CLI:**

```
podscribe export --out pods-2026-06-22.tar.gz
podscribe export --out -                              # stdout
podscribe import pods-2026-06-22.tar.gz
podscribe import --dry-run pods-2026-06-22.tar.gz
podscribe import --force pods-2026-06-22.tar.gz
```

**Edge cases:**

| Case | Behavior |
|---|---|
| `out` is a directory | Error: "out path is a directory" |
| `out` already exists | Overwrite (tarfile opens in `w:gz` mode, truncates) |
| Tarball contains a pod not in local repo | Import as new (always allowed) |
| Tarball contains root-level `podscribe.yaml` | Imported, but does NOT replace local `podscribe.yaml` (project config is intentionally not migrated; documented in `--help`) |
| Tarball is malformed / not gzip | `tarfile.ReadError`, exit 1 with tar's error message |
| Path traversal in member | Refuse the entire import, exit 1 |
| Local pod exists and `--force` is set | Replace the pod's directory contents (the imported `transcripts/` and `summaries/` overwrite local files) |

---

## Component changes summary

| File | Change |
|---|---|
| `podscribe/cli.py` | New `_run_enhance`; both `cmd_enhance` and `cmd_consolidate` use it; `cmd_record` accepts `--type`; new `cmd_search`, `cmd_export`, `cmd_import`; new flags on `cmd_list` |
| `podscribe/storage.py` | `start_meeting` accepts `meeting_type`; `list_meetings` globs 2- and 3-level; `append_log_row` also writes to global CSV; new `global_log_path()`, `append_global_log_row()`, `read_global_log()` |
| `podscribe/config.py` | `get_effective_glossary` caches with mtime key; new `_leadership_yaml_path()` and `_read_effective_glossary()` helpers |
| `podscribe/models.py` | `MEETING_TYPES` tuple; `parse_meeting_type`; `Meeting.type: Optional[str] = None` field |
| `podscribe/export.py` (new) | `create_export`, `import_archive`, `_iter_export_members`, `_safe_extract` |
| `podscribe/search.py` (new) | `SearchMatch` dataclass; `search` iterator; `_rg_search` and `_python_search` backends |
| `podscribe/__init__.py` | No change |
| `tests/test_cli.py` | New tests: `--type`, `search` invocation, `export`/`import` invocation, list filters |
| `tests/test_storage.py` | New tests: typed subdir start_meeting, 3-level glob, global CSV mirror |
| `tests/test_config.py` | New test: mtime invalidation |
| `tests/test_models.py` | New test: `parse_meeting_type` accepts/rejects |
| `tests/test_export.py` (new) | Round-trip: create + import a tarball; verify path-traversal rejection; verify `--force` and `--dry-run`; verify exclusions |
| `tests/test_search.py` (new) | `rg` and `python` backends, all filters, color flag, empty-result behavior |
| `README.md` | New section: list filters, search, export/import, --type, glossary cache note |

## Data flow

```
record (--type 1on1)
   ↓
start_meeting(pod, when, meeting_type="1on1")
   ↓
transcripts/22-JUN-2026/1on1/<id>.md       ← additive subdir
transcripts/22-JUN-2026/1on1/<id>.json     ← type field stored
transcripts/22-JUN-2026/1on1/<id>.raw      ← deleted by default

enhance → summary in summaries/22-JUN-2026/<id>.md
consolidate → reads summary, calls _run_enhance, updates
              pods/<pod>/meetings.csv AND pods/meetings.csv

list --all → reads pods/meetings.csv (4.2 + 4.3)
list <pod> → reads pods/<pod>/meetings.csv (existing)
list --type 1on1 → filters by type from JSON sidecar OR global CSV

search "Project Helios" --pod sam-chen
  → rg -F "Project Helios" pods/sam-chen/transcripts
  → falls back to Path.rglob if rg not installed
  → prints: sam-chen:22-JUN-2026:<id>:[00:01:23] discussed Project Helios

export --out pods-2026-06-22.tar.gz
  → tar.gz of pods/**/*.md, pods/**/*.yaml, leadership_team.yaml, podscribe.yaml
  → excludes .raw, __pycache__, .venv

import pods-2026-06-22.tar.gz
  → safe extract with path-traversal check
  → refuses to overwrite existing pods (--force to override)
```

## Error handling

| Failure | Behavior |
|---|---|
| 4.1 Ollama unreachable | `_run_enhance` returns `(None, error)`; caller prints and exits 1 |
| 4.4 leadership file missing | Cache key mtime=0; cache holds the empty leadership + pod glossary |
| 4.4 cache stale after manual edit | mtime check picks it up on next `get_effective_glossary` call |
| 4.5 invalid `--type` | `parse_meeting_type` raises `ValueError`; `cmd_record` prints and exits 1 |
| 4.5 existing 2-level data | `list_meetings` glob matches both; no migration needed |
| 4.3 global CSV write fails | Logged to stderr; per-pod write still succeeds |
| 4.2 `--since` parse fails | `cmd_list` prints usage hint and exits 1 |
| 4.6 `rg` not installed | Silent fallback to Python `rglob`; no warning |
| 4.6 file is undecodable | Skip with warning; continue |
| 4.7 export path is a directory | `tarfile` raises `IsADirectoryError`; caught and reported |
| 4.7 path traversal in import | Refuse entire import, exit 1 |
| 4.7 import conflict, no `--force` | Print conflicting pod names; exit 1 |

## Testing strategy

**~34 new tests:**

| Section | Test name | Asserts |
|---|---|---|
| 4.1 | `test_run_enhance_returns_text_on_success` | Mock `enhance_transcript`; helper returns `(text, None)` |
| 4.1 | `test_run_enhance_returns_error_on_failure` | Mock `enhance_transcript` → `None`; helper returns `(None, "Failed to reach Ollama...")` |
| 4.1 | `test_cmd_enhance_uses_helper` | After refactor, `cmd_enhance` calls `_run_enhance` (not `enhance_transcript` directly) |
| 4.1 | `test_cmd_consolidate_uses_helper` | Same for consolidate |
| 4.4 | `test_get_effective_glossary_caches` | Two calls, one disk read (spy on `load_leadership_glossary`) |
| 4.4 | `test_cache_invalidates_on_mtime_change` | Touch the file with a newer mtime; cache resets |
| 4.4 | `test_cache_handles_missing_file` | File deleted between calls; cache holds `mtime=0` value |
| 4.5 | `test_parse_meeting_type_normalizes_case` | `1ON1` → `1on1` |
| 4.5 | `test_parse_meeting_type_rejects_unknown` | `weekly-sync` → raises |
| 4.5 | `test_start_meeting_with_type_uses_subdir` | `transcripts/<date>/1on1/<id>.md` exists |
| 4.5 | `test_start_meeting_without_type_uses_flat` | `transcripts/<date>/<id>.md` (existing layout) |
| 4.5 | `test_list_meetings_finds_typed_and_untyped` | Mix of 2-level and 3-level paths; both found |
| 4.5 | `test_cmd_record_rejects_invalid_type` | `--type weekly` → exit 1, stderr message |
| 4.3 | `test_append_log_row_writes_global` | After call, `pods/meetings.csv` has the row |
| 4.3 | `test_global_log_failure_does_not_break_pod_log` | Mock `OSError` on global write; per-pod file still has the row |
| 4.3 | `test_read_global_log_empty_when_no_file` | Returns `[]` |
| 4.2 | `test_cmd_list_all_reads_global` | `--all` flag invokes `read_global_log` |
| 4.2 | `test_cmd_list_filters_by_since` | `--since 7d` excludes older rows |
| 4.2 | `test_cmd_list_filters_by_type` | `--type 1on1` excludes others |
| 4.2 | `test_cmd_list_limits_by_recent` | `--recent 5` returns at most 5 |
| 4.6 | `test_search_python_backend` | `rg` not on PATH (mocked); uses `rglob`; yields matches |
| 4.6 | `test_search_uses_rg_when_available` | `rg` on PATH; shells out with `-F` |
| 4.6 | `test_search_filters_by_pod` | Only that pod's files scanned |
| 4.6 | `test_search_filters_by_since` | Out-of-window files skipped |
| 4.6 | `test_search_filters_by_type` | 3-level files match only matching type |
| 4.6 | `test_search_empty_result` | Prints "No matches.", returns 0 |
| 4.7 | `test_export_creates_tarball` | File exists; magic bytes `\\x1f\\x8b` (gzip) |
| 4.7 | `test_export_excludes_raw_files` | Tarball member list has no `.raw` |
| 4.7 | `test_export_excludes_pycache` | Tarball member list has no `__pycache__/` |
| 4.7 | `test_import_refuses_overwrite_without_force` | Pre-existing pod → exit 1 |
| 4.7 | `test_import_force_overwrites` | `--force` succeeds; pod replaced |
| 4.7 | `test_import_dry_run_no_writes` | `--dry-run`; no files change |
| 4.7 | `test_import_rejects_path_traversal` | Tarball with `pods/../../etc/passwd` → `ValueError` |
| 4.7 | `test_export_import_roundtrip` | Create tarball, delete pod, import, pod is back |

**Test count:** 127 (current) → ~161 after this PR lands.

## Documentation

`README.md` updates:
- New section: `## Listing & filtering` (covers `list --all`, `--since`, `--recent`, `--type`)
- New section: `## Searching` (covers `search` with all flags)
- New section: `## Backup & restore` (covers `export` / `import`)
- Update: `## Commands` to include `--type` on `record`
- Update: `## Storage layout` to show the optional 3-level `transcripts/<date>/<type>/<id>.md` and the global `pods/meetings.csv`
- Note in glossary section: "Cached per session; reloads on file change."

`KT-HANDOFF.md` left untouched (per user preference for the previous PR).

`AGENTS.md`: add a one-liner about the new layout under the "Storage layout" section.

## Commit order (12 commits)

1. `refactor(cli): extract _run_enhance helper` — 4.1
2. `feat(config): cache effective glossary with mtime invalidation` — 4.4
3. `feat(models): add MEETING_TYPES enum and parse_meeting_type helper` — 4.5 partial (model)
4. `feat(cli): add --type flag to record command` — 4.5 partial (CLI)
5. `feat(storage): support typed meeting subdirs and 3-level list glob` — 4.5 partial (storage)
6. `feat(storage): mirror append_log_row to global meetings.csv` — 4.3
7. `feat(cli): add --all/--since/--recent/--type flags to list` — 4.2
8. `feat(search): add podscribe search command` — 4.6
9. `feat(export): add podscribe export command` — 4.7 partial
10. `feat(export): add podscribe import with --force and --dry-run` — 4.7 partial
11. `docs: README updates for section 4 features` — README
12. `test: section 4 integration smoke (record → search → export → import)` — end-to-end

**Commit rationale:**
- 1-2: refactors with no user-facing change. Smallest blast radius first.
- 3-5: 4.5 broken into 3 commits (model, CLI, storage) so each is bisectable.
- 6: 4.3 is the foundation for 4.2's `--all` mode.
- 7: 4.2 depends on 4.3 and 4.5.
- 8: 4.6 is independent.
- 9-10: 4.7 split into export and import.
- 11-12: docs + smoke test.

## Rollback

One PR, one revert. If any commit regresses, `git revert <merge-sha>` ships
clean. The PR has no data migrations:
- Existing 2-level layouts continue to work (3-level glob matches both).
- Existing per-pod CSVs are unchanged.
- Existing JSON sidecars gain a `"type": null` field; old code reading
  the sidecar without expecting `type` is forward-compatible.
- Glossary cache invalidates correctly via mtime; no stale-cache risk.

## Open questions

None. All 7 strategic questions answered during brainstorming:
- Q1: scope = all 7 in one PR
- Q2: 4.1 helper returns `(text, err)`; caller picks path
- Q3: 4.4 mtime check on every get
- Q4: 4.5 additive optional subdir
- Q5: 4.5 fixed enum of 7 values
- Q6: 4.6 plain line output `pod:date:<id>:[ts]:<text>`
- Q7: 4.7 source-only export
