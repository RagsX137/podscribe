# Podscribe User Manual

Transcribe your 1:1s and team meetings locally on your Mac. Each person you meet with gets a **pod** — a dedicated folder for their transcripts, glossary terms, and LLM-enhanced summaries.

## Quick start (5 minutes)

```bash
# 1. Install (pick the ASR engine for your hardware)
pip install -e '.[mlx]'     # Apple Silicon
pip install -e '.[cuda]'    # NVIDIA / CUDA

# 2. Create a pod for someone you meet with
podscribe init sam-chen --display-name "Sam Chen" --role "Senior Engineer"

# 3. Record a live meeting (Ctrl+C to stop)
podscribe sam-chen record

# 4. View what was captured
podscribe sam-chen show latest

# 5. If you have Ollama running, get an AI summary + CSV log entry
podscribe sam-chen summarize
podscribe sam-chen consolidate
```

The three-step flow is **record → enhance → consolidate**. Enhance writes the LLM-cleaned summary; consolidate extracts structured fields (action items, blockers) from that summary and appends a row to `pods/sam-chen/meetings.csv`.

---

## Interactive launcher (`podscribe` with no args)

Running `podscribe` with no arguments opens an interactive menu (requires a TTY). It remembers the last pod you used, so you can quickly record / enhance / consolidate without typing the pod name each time.

```
$ podscribe
╭─ podscribe ───────────────────────────────────────────────╮
│ podscribe  ·  pod: sam-chen  ·  ollama: ◉ online          │
╰───────────────────────────────────────────────────────────╯
  ▶ 1  Record
    2  Enhance
    3  Consolidate
    4  Others
    q  Quit
```

**Navigation:** Use ↑/↓ arrow keys to move the selection (▶), Enter to confirm, or press a number key (1-9) to jump directly to an item. Press `q` or Ctrl+C to quit.

### Main menu

| Item | Action | Notes |
|------|--------|-------|
| Record | Opens a `rich.live` panel showing the live transcript as it streams from Whisper. Ctrl+C to stop. Uses the pod's glossary. |
| Enhance | **Meeting picker** → opens a `rich.live` panel showing tokens streaming from Ollama in real time. |
| Consolidate | **Meeting picker** → runs the consolidate flow with a spinner, then a `Confirm` prompt if a log row already exists. |
| Others | Submenu for one-shot commands and configuration. |
| Quit | Exits to the shell. |

### Meeting picker

### God mode

The `Others → God mode` option or `g` key opens the god mode chat interface — an agentic loop where an LLM can inspect your project files, manage pods, run recordings, search transcripts, and more using 20+ tools.

**Input:** Type a message at the `>` prompt. The assistant shows tool calls in the right pane and responses in the left.

**Navigation:** `Esc` to toggle pane focus, `/exit` to leave god mode, arrow keys to scroll, `/list` to see all slash commands.

When you select Enhance or Consolidate, a meeting picker appears showing all meetings for the current pod, newest first:

```
╭─ Meetings for sam-chen ─────────────────────────────────────╮
│ ▶ 1  2026-06-22 14:30  ·  1on1  ·  00:32:14                │
│   2  2026-06-21 10:00  ·  retro  ·  00:10:00               │
│   3  2026-06-15 15:00                                       │
│   q  Cancel                                                 │
╰─────────────────────────────────────────────────────────────╯
```

Each entry shows the date, time, type (if set), and duration (if finalized). Navigate with ↑/↓ or number keys, Enter to select, `q` to cancel back to the main menu.

### Others submenu

| Item | Action |
|------|--------|
| List all meetings | Runs `podscribe list --all` |
| Show latest transcript | Runs `podscribe show <pod> latest` |
| Search transcripts | Prompts for a query, then runs `podscribe search <query>` |
| God mode | Opens the agentic chat view — LLM can use 20+ tools |
| Glossary management | Submenu: list, **add**, **remove** terms |
| Export data | Prompts for a path (default: `podscribe-export-<timestamp>.tar.gz`) |
| LLM config | Submenu: show, **set** model + template |
| Consolidate prompt | Submenu: show, **set** prompt |
| Switch pod | Pod picker — numbered list, select to switch |
| Back | Returns to the main menu |

The Glossary, LLM config, and Consolidate prompt submenus are **read-write** — you can add/remove glossary terms, set the LLM model and prompt template, and set the consolidate prompt directly from the launcher without dropping to the CLI.

### What doesn't work / limitations

- Record has **no pause/resume/marker** keys — Ctrl+C stops and finalizes, same as the CLI. (See `Recommended_fixes.md` §9 for the planned approach.)
- Non-TTY contexts (pipes, CI, `subprocess`) get a `TTY is required` message and exit code 2 instead of hanging on a key read.

### CLI vs launcher rendering

When invoked directly (`podscribe <pod> record/enhance/consolidate`) in a **TTY**, the CLI now delegates to the same `rich.live` panels as the launcher — you get the live transcript / token stream view. When piped or non-TTY, the CLI falls back to plain-text output for scripting. This means `podscribe sam-chen record` and the launcher's Record produce the same visual experience.

**Remembered pod:** the launcher saves the last-used pod to `podscribe.yaml` (`last_pod` key) on every switch. Delete that key or the whole file to reset.

---

## Commands

### `podscribe init <name>`
Create a new pod — one per person or project you meet with.

```
podscribe init alex                  # name becomes "Alex"
podscribe init priya-patel \
    --display-name "Priya Patel" \
    --role "Tech Lead" \
    --cadence biweekly \
    --notes "Likes async communication"
```

**Naming rules:** lowercase letters, numbers, and hyphens only (`kebab-case`). Examples: `sam-chen`, `alex-tan`, `project-helios`.

---

### `podscribe <pod> record`
Record and transcribe a live meeting. You can also use: `podscribe record <pod>` or `<pod> start`.

```
podscribe sam-chen record            # pod-first — most natural
podscribe record sam-chen            # standard syntax
podscribe sam-chen start             # 'start' is an alias for 'record'
```

**What happens:**
1. Your microphone starts capturing audio
2. WebRTC VAD detects speech segments
3. Each segment is sent to Whisper (via Apple MLX) for transcription
4. Every transcribed line is written immediately — **crash-safe**
5. Press `Ctrl+C` when the meeting ends
6. Raw audio is deleted automatically (use `--keep-audio` to save it)

**Options:**

| Flag | Default | What it does |
|------|---------|-------------|
| `--model` | `large-v3-turbo` | Whisper model size (`base`, `small`, `large-v3-turbo`, or full HF path) |
| `--vad-aggressiveness` | `2` | 0=loose (captures more), 3=strict (cleaner segments) |
| `--device <N>` | system default | Pick a specific microphone |
| `--keep-audio` | off | Keep the raw `.raw` audio file (for debugging) |

**Tip:** If transcripts look choppy or hallucinated, try `--vad-aggressiveness 3`.

**Where does it save?**
```
pods/sam-chen/transcripts/22-JUN-2026/
├── 2026-06-22-101500-sam-chen.md   ← readable transcript
├── 2026-06-22-101500-sam-chen.json ← metadata (model, duration, etc.)
└── 2026-06-22-101500-sam-chen.raw  ← raw audio (only with --keep-audio)
```

Meeting IDs use `YYYY-MM-DD-HHMMSS-<pod>` (seconds precision) so two meetings started in the same minute never collide.

**If `--keep-audio` can't open the file** (disk full, permission denied), recording continues without the audio file — a warning is printed to stderr and the transcript is still produced.

---

### `podscribe list`
See all pods and their recent meetings, newest first.

```
$ podscribe list
[alex] Alex — Tech Lead
  • 2026-06-22T14:30:00 (48m) → 2026-06-22-143000-alex
[sam-chen] Sam Chen — Senior Engineer
  • 2026-06-21T10:15:00 (32m) → 2026-06-21-101500-sam-chen
```

---

### `podscribe <pod> show <id>`
Read a meeting transcript.

```
podscribe sam-chen show latest                       # most recent meeting
podscribe sam-chen show 2026-06-22                    # any prefix works
podscribe sam-chen show 2026-06-22-10                 # even more specific
podscribe show sam-chen latest                        # standard syntax
```

**Ambiguous prefix:** if your prefix matches more than one meeting, `podscribe` lists the candidates and exits 1. Use a longer prefix to disambiguate.

```
$ podscribe sam-chen show 2026-06-22
Multiple meetings match '2026-06-22':
  • 2026-06-22-101500-sam-chen
  • 2026-06-22-143000-sam-chen
Use a longer prefix to disambiguate.
```

---

### `podscribe context`
Teach Whisper to recognize names and project terms specific to this person.

Glossary entries are injected into the Whisper prompt, improving accuracy on names, acronyms, and jargon.

```
podscribe sam-chen context add "Anurag Kaushik" --category person
podscribe sam-chen context add "Batch Endpoints" --category project
podscribe sam-chen context list
podscribe sam-chen context remove "Old Term"
```

**Dedup is case-insensitive:** adding `Anurag Kaushik` then `anurag kaushik` raises an error. The first-seen casing is what gets stored. `remove` is also case-insensitive, so `remove "ANURAG"` removes `Anurag`.

**Where terms come from (merged together):**
- **Global:** `leadership_team.yaml` in the project root — shared across all pods
- **Per-pod:** `pods/<name>/config.yaml` — specific to this person

---

### `podscribe <pod> summarize`
Send the latest transcript to Ollama for analysis (summary, action items, decisions).

```
podscribe sam-chen summarize          # easiest — defaults to latest meeting
podscribe sam-chen enhance            # 'enhance' is the official command name
podscribe sam-chen summarize 2026-06  # specific meeting prefix
```

**Output:** saved to `pods/sam-chen/summaries/22-JUN-2026/<meeting-id>.md`

**Requirements:**
1. [Ollama](https://ollama.com) running (`ollama serve &`)
2. A model pulled (e.g. `ollama pull qwen3.6:27b`)
3. LLM config set (either per-pod or project-wide)

#### Streaming output

The enhance call streams tokens from Ollama. In a TTY (whether via the launcher or direct CLI), tokens render live in a `rich.live` panel with a footer showing token count and tok/s. When piped or non-TTY, the header and final metrics line print to stderr as plain text.

**TTY output (launcher or `podscribe <pod> enhance`):**
```
╭─ enhance sam-chen/22-JUN-2026/2026-06-22-101500-sam-chen  model=qwen3.6:27b  ctx=32768 ─╮
│ Sam will review the auth middleware design by Friday. The key concern is               │
│ backward compatibility with the existing API consumers...                              │
│                                                                                        │
│ done prompt 1250 + response 423 @ 17.3 tok/s                                           │
╰────────────────────────────────────────────────────────────────────────────────────────╯
Enhanced transcript saved to pods/sam-chen/summaries/22-JUN-2026/2026-06-22-101500-sam-chen.md
```

**Non-TTY output (pipes, CI, scripting):**
```
Enhancing transcript for sam-chen/22-JUN-2026/2026-06-22-101500-sam-chen...
Enhanced summary will be saved to sam-chen/22-JUN-2026/2026-06-22-101500-sam-chen...
  Using Large Language Model: qwen3.6:27b
  Ollama URL: http://localhost:11434

Calling Model:qwen3.6:27b...
Context window size : 32768 tokens
  ✓ done in 47.2s | prompt 1250 + response 423 tokens @ 17.3 tok/s

Enhanced transcript saved to pods/sam-chen/summaries/22-JUN-2026/2026-06-22-101500-sam-chen.md
```

There is no fake percentage bar — Ollama's streaming API does not report a total token count until completion, so the view shows an honest token stream + final metrics instead.

Connection drops and 5xx responses are retried up to 3× (1s, 2s, 4s backoff). 4xx errors (bad model, bad prompt) fail immediately — no retry.

#### Short-transcript guard

If the transcript file's stripped content is under 50 characters, enhance exits 1 with `Transcript too short to enhance (<N> chars).` and never calls Ollama. Saves GPU time on stray recordings.

#### `preserve_speakers` toggle

By default, a speaker-preservation preamble is prepended to the prompt telling the LLM to keep names exactly as they appear and to attribute every action item ("Sam will review…", never just "Escalate…"). Set `preserve_speakers: false` to strip names.

**Resolution order:** pod-level `llm.preserve_speakers` → project-level → default `true`. Non-boolean values (`"yes"`, `1`) raise a `ValueError` with a clear message.

#### Setting up the LLM

**Option A — Project-wide (recommended):** One config for all pods.
```bash
podscribe config llm set qwen3.6:27b "Analyze this transcript...

{{transcript}}"
```

**Option B — Per-pod:** Edit `pods/<name>/config.yaml` and add:
```yaml
llm:
  model: qwen3.6:27b
  prompt_template: |
    Analyze this transcript...
    {{transcript}}
  preserve_speakers: true   # default; set false to strip names
```

**Prompt template placeholders:**
- `{{transcript}}` — the full meeting transcript
- `{{glossary}}` — all glossary terms formatted inline

---

### `podscribe <pod> consolidate`
Extract structured fields (summary, action items, blockers, next steps) from an enhanced summary and append them as a row to `pods/<pod>/meetings.csv` — your longitudinal log per direct report.

```
podscribe sam-chen consolidate        # uses latest meeting
podscribe sam-chen cons 2026-06        # 'cons' is an alias; prefix matching
podscribe sam-chen consolidate --no-log # extract only, don't touch the CSV
```

**Requirements:**
1. An enhanced summary must exist for the meeting. If it doesn't, consolidate tells you to run `podscribe enhance <pod> <meeting-id>` first — it does not silently re-enhance.
2. Ollama running; the model used for consolidate comes from the same `llm` config as enhance.

**CSV columns:** `meeting_id,started_at,pod_name,quick_summary,key_topics,action_items,blockers,next_steps,summary_file,transcript_file`. List-valued fields are stored as JSON arrays.

**Re-consolidating:** if a row already exists for the meeting, you'll be asked whether to rewrite it (`y/N`).

---

### `podscribe diarize`

Post-hoc speaker diarization. Requires a meeting recorded with continuous audio
(this version onward) — older meetings are refused with a clear message.

**Prerequisites:** `pip install -e ".[diarize]"`; a HuggingFace token (first TTY run
prompts and caches to `~/.config/podscribe/hf_token`, or set `$HF_TOKEN`).

**Usage:**
- `podscribe diarize <pod>` — latest meeting
- `podscribe diarize <pod> <meeting-id-prefix>` — a specific meeting
- `--num-speakers N` — pin count (default: auto)
- `--cpu` — force CPU (default: Apple MPS/Metal when available, else CPU; falls back to CPU on error)
- `--relogin` — re-prompt for the token

**Output:** `<meeting-id>.diarized.md`; `show`/`enhance` prefer it. Labels: generic
`Speaker 0..N-1` by first appearance. Name mapping is a future feature.

---

### Knowledge-Transfer videos: `ingest`, `enhance --kt`, `ask`

Ingest external video tutorials, demos, and knowledge-transfer (KT) sessions into your pod. The workflow mirrors live meetings but operates independently on video files.

#### `podscribe <pod> ingest <video>`

Ingest a KT video into a pod. The command automatically looks for a sibling `.vtt` or `.srt` file (the transcript you downloaded alongside the video), which is the **source of truth**.

```bash
podscribe fso ingest ~/Downloads/auth-design-kt.mp4
# Automatically finds ~/Downloads/auth-design-kt.vtt (or .srt)

podscribe fso ingest ~/Downloads/some-video.mp4 --transcript ~/path/to/custom.vtt
# Use a custom transcript path

podscribe fso ingest ~/Downloads/unlabeled-video.mp4 --asr --model large-v3-turbo
# Force local mlx-whisper ASR (requires ffmpeg on PATH)
# Creates a separate KT session; never overwrites a .vtt-derived one
```

**What happens:**
1. If `--transcript` is given or a sibling `.vtt`/`.srt` is found, that file is parsed and a KT session is created
2. With `--asr`, ffmpeg extracts audio, mlx-whisper transcribes it, and a **separate** KT session is created (coexisting with any vtt-derived session)
3. The video file itself is not copied — only the transcript is stored
4. Metadata (original media path, source type, timestamp) is saved in a JSON sidecar

**Output:** stored under `pods/<pod>/kt/transcripts/<DD-MMM-YYYY>/` as `.md` + `.json` files.

**Requirements:**
- Sibling `.vtt`/`.srt` file (default) — no extra requirements
- OR: `--asr` flag + ffmpeg on PATH (for local transcription)

---

#### `podscribe <pod> enhance --kt <id|latest>`

Generate an LLM summary of a KT session (just like `enhance` for meetings, but scoped to KT only).

```bash
podscribe fso enhance --kt latest
podscribe fso enhance --kt 2026-06
# Uses the pod's llm config; generates a summary file
```

**Output:** saved to `pods/<pod>/kt/summaries/<DD-MMM-YYYY>/<id>.md`

**Requirements:** Ollama running + `llm` config set (same as meeting `enhance`).

---

#### `podscribe <pod> ask <id|latest> [question...]`

Ask questions about a **single** KT session. Scoped to that session only — never cross-references meetings or other KT sessions.

```bash
podscribe fso ask latest                           # Opens REPL
podscribe fso ask latest "what are the key takeaways?"
podscribe fso ask 2026-06 "list all action items"
```

**Behavior:**
- If a question is given, it runs once and exits (one-shot).
- Omit the question to open an interactive REPL (`>` prompt, `/exit` to quit).
- Each answer is grounded **only** in that KT transcript — no cross-session search.

**Output:** printed to stdout (not logged).

**Requirements:** none (text-only, no LLM call required if you have the transcript).

---

### `podscribe config consolidate`
Manage the consolidate prompt template (stored under the `consolidate:` key in `podscribe.yaml`).

```
podscribe config consolidate show      # view current consolidate prompt
podscribe config consolidate set '<prompt>'
```

The default prompt asks for `quick_summary`, `key_topics`, `action_items`, `blockers`, `next_steps` as YAML. The prompt must contain the `{{summary}}` placeholder.

---

### `podscribe config llm`
Manage the project-wide LLM config (stored in `podscribe.yaml`).

```
podscribe config llm show                  # view current config
podscribe config llm set <model> '<tpl>'   # set model + prompt template
```

Example prompt template:
```
podscribe config llm set qwen3.6:27b 'Fix spelling and grammar in this transcript.
Preserve all technical terms and names.

{{transcript}}'
```

---

### `podscribe config god`
Manage the god mode model (stored under `god.model` in `podscribe.yaml`). Falls back to `llm.model` if unset.

```
podscribe config god show                  # view current god model
podscribe config god set qwen3.6:35b-mlx   # set a model
```

---

### `podscribe god [prompt]`
Enter god mode — an agentic loop where an LLM can use tools to inspect your project, manage pods, run recordings, search transcripts, and more.

```
podscribe god                              # opens interactive REPL (requires TTY)
podscribe god "list all meetings"          # one-shot: runs the prompt, prints result, exits
```

**What it can do:** list pods, get pod info, create pods, list/show meetings, start/stop recordings, enhance/consolidate meetings, search transcripts, manage glossary, export data, list directories, read files, search files for strings/symbols/references — all through natural language.

**Model priority:** CLI `--model` flag → `podscribe.yaml` → `god.model` → `llm.model` → error telling you to configure one.

---

### `podscribe search <query>`
Full-text search across transcripts. Uses ripgrep if available, falls back to Python.

```
podscribe search "deploy pipeline"              # all pods
podscribe search "deploy pipeline" --pod sam-chen # one pod
podscribe search "deploy pipeline" --since 7d    # last 7 days
podscribe search "deploy pipeline" --type 1on1   # specific meeting type
```

---

### `podscribe export`
Bundle all pod data into a portable `.tar.gz` archive.

```
podscribe export                           # saves to podscribe-export-<timestamp>.tar.gz
podscribe export --out my-backup.tar.gz    # custom filename
podscribe export --out -                   # writes to stdout (for piping)
```

**What's included:** `pods/` (all transcripts, summaries, configs, CSVs), `leadership_team.yaml`, `podscribe.yaml`.
**Excluded:** `.raw` audio files, `.env`, `__pycache__/`, `.pytest_cache/`, `.venv/`.

---

### `podscribe import <archive>`
Restore from an export tarball.

```
podscribe import podscribe-export-20260626.tar.gz       # safe import
podscribe import podscribe-export-20260626.tar.gz --force  # overwrite existing pods
podscribe import podscribe-export-20260626.tar.gz --dry-run # preview only
```

**Safety:** Refuses path-traversal and symlink members. Skips `podscribe.yaml` root-level file to avoid overwriting local LLM config. `--dry-run` prints what would be restored without writing anything.

---

## File structure

```
pods/<name>/                          # one directory per person or project
├── config.yaml                       # pod metadata + glossary + optional LLM config
├── meetings.csv                      # consolidated log (one row per consolidate run)
├── transcripts/
│   └── 22-JUN-2026/                  # organized by date (DD-MMM-YYYY)
│       ├── [type/]                   # optional subdir when record --type is used
│       │   ├── 2026-06-22-101500-name.md # transcript (incremental, crash-safe)
│       │   ├── 2026-06-22-101500-name.json # metadata sidecar
│       │   └── 2026-06-22-101500-name.raw  # raw audio (deleted by default)
│       └── (or flat, without type subdir)
├── summaries/
│   └── 22-JUN-2026/
│       └── 2026-06-22-101500-name.md # LLM-enhanced output (mirrors transcript layout)

podscribe.yaml                         # project-wide LLM + consolidate + god config
leadership_team.yaml                   # global glossary terms (optional)
```

## Quick reference

| Goal | Command |
|------|---------|
| Interactive launcher | `podscribe` (no args; TTY only) |
| Create a pod | `podscribe init <name> [--display-name "..." --role "..." --cadence ...]` |
| Record a meeting | `podscribe <name> record` (or `record <name>`, or `<name> start`) |
| Add glossary term | `podscribe <name> context add "Term" --category person` |
| List glossary | `podscribe <name> context list` |
| View transcript | `podscribe <name> show latest` |
| LLM summary | `podscribe <name> summarize` |
| Extract → CSV | `podscribe <name> consolidate` (alias `cons`) |
| Set project LLM | `podscribe config llm set <model> '<template>'` |
| View project LLM | `podscribe config llm show` |
| Set consolidate prompt | `podscribe config consolidate set '<prompt>'` |
| Set/view god model | `podscribe config god set/show` |
| God mode (agentic) | `podscribe god [prompt]` |
| Search transcripts | `podscribe search <query> [--pod <name> --since <n>d]` |
| Export all pods | `podscribe export [--out <path>]` |
| Import pods | `podscribe import <archive> [--force --dry-run]` |
| List all pods | `podscribe list` |

## Tips & troubleshooting

**Transcript is garbage or hallucinated:** Raise VAD to 3 with `--vad-aggressiveness 3`. Or try a larger model.

**Missing words at the start of sentences:** VAD is too aggressive — lower to 1.

**No microphone detected:** List devices with `python -c "import sounddevice; print(sounddevice.query_devices())"` and use `--device <N>`.

**Crashed mid-meeting:** Transcript is written line-by-line, so everything up to the crash is saved. Just `podscribe <name> show latest`.

**LLM summary fails:** Make sure Ollama is running (`ollama serve &`) and the model is pulled (`ollama list`).

**Glossary not helping:** Add more terms! The glossary is injected into Whisper's `initial_prompt` — more relevant terms = better accuracy.

## Dependencies

| Dependency | Required for | Notes |
|-----------|-------------|-------|
| `mlx-whisper` | Recording | Downloaded automatically; model cached in `~/.cache/huggingface/` |
| `webrtcvad` | Recording | Needs Xcode CLI tools (`xcode-select --install`) |
| `sounddevice` | Recording | Default mic used unless `--device` specified |
| `numpy` | Recording | PCM conversion for Whisper input |
| `requests` | Summarize | HTTP client for the Ollama streaming API |
| `rich` | TUI launcher | Live panels for record/enhance, panels, spinner, prompts |
| `readchar` | TUI launcher | Single-key input for the launcher menu |
| Ollama | Summarize | Must be running at `localhost:11434` |
