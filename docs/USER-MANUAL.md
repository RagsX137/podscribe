# Podscribe User Manual

Transcribe your 1:1s and team meetings locally on your Mac. Each person you meet with gets a **pod** — a dedicated folder for their transcripts, glossary terms, and LLM-enhanced summaries.

## Quick start (5 minutes)

```bash
# 1. Install
pip install -e .

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
  [1] Record     [2] Enhance     [3] Consolidate     [4] Others     [q] Quit
```

**What works:**

| Key | Action | Notes |
|-----|--------|-------|
| `1` | Record | Opens a `rich.live` panel showing the live transcript as it streams from Whisper. Ctrl+C to stop. Uses the pod's glossary. |
| `2` | Enhance | Opens a `rich.live` panel showing tokens streaming from Ollama in real time. Uses the latest meeting. |
| `3` | Consolidate | Runs the consolidate flow with a spinner, then a `Confirm` prompt if a log row already exists. Uses the latest meeting. |
| `4` | Others | Submenu: list, show latest, search, context list, export, config show, switch pod. |
| `q` | Quit | Exits to the shell. |
| Ctrl+C | Quit | Treated as `q` at any menu. |

**Others submenu:**

| Key | Action |
|-----|--------|
| `1` | List all meetings across all pods |
| `2` | Show latest transcript for the current pod |
| `3` | Search — prompts for a query, then runs `podscribe search <query>` |
| `4` | List glossary for the current pod |
| `5` | Export — prompts for a path (default: `podscribe-export-<timestamp>.tar.gz`) |
| `6` | Show project LLM config |
| `7` | Switch pod — numbered pod picker |
| `q` | Back to the main menu |

**What doesn't work / limitations:**

- The launcher is **single-key only** (no arrow keys, no mouse). Use number keys and `q`.
- Record has **no pause/resume/marker** keys — Ctrl+C stops and finalizes, same as the CLI.
- Enhance and Consolidate from the launcher always use the **latest meeting** — to target a specific meeting by prefix, use the CLI (`podscribe <pod> enhance <prefix>`).
- The Others submenu covers **read-only operations** only. To add/remove glossary terms, set LLM config, or set the consolidate prompt, use the CLI equivalents.
- Direct CLI commands (`podscribe <pod> enhance`, `podscribe <pod> record`) do **not** use the `rich.live` panels — they produce plain-text output for piping/ scripting. The live panels are only available through the launcher.
- Non-TTY contexts (pipes, CI, `subprocess`) get a `TTY is required` message and exit code 2 instead of hanging on a key read.

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

The enhance call streams tokens from Ollama. When invoked via the launcher (`podscribe` with no args), tokens render live in a `rich.live` panel. When invoked directly (`podscribe <pod> enhance`), the header and final metrics line print to stderr (no live panel). Piped/non-TTY invocations degrade gracefully.

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

## File structure

```
pods/<name>/                          # one directory per person
├── config.yaml                       # pod metadata + glossary + optional LLM config
├── transcripts/
│   └── 22-JUN-2026/                  # organized by date (DD-MMM-YYYY)
│       ├── 2026-06-22-101500-name.md # transcript (incremental, crash-safe)
│       ├── 2026-06-22-101500-name.json # metadata sidecar
│       └── 2026-06-22-101500-name.raw  # raw audio (deleted by default)
├── summaries/
│   └── 22-JUN-2026/
│       └── 2026-06-22-101500-name.md # LLM-enhanced output
└── meetings.csv                      # consolidated log (one row per consolidate run)

podscribe.yaml                         # project-wide LLM + consolidate config
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
