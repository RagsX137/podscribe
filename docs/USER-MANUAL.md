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

# 5. If you have Ollama running, get an AI summary
podscribe sam-chen summarize
```

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
├── 2026-06-22-1015-sam-chen.md     ← readable transcript
├── 2026-06-22-1015-sam-chen.json   ← metadata (model, duration, etc.)
└── 2026-06-22-1015-sam-chen.raw    ← raw audio (only with --keep-audio)
```

---

### `podscribe list`
See all pods and their recent meetings, newest first.

```
$ podscribe list
[alex] Alex — Tech Lead
  • 2026-06-22T14:30:00 (48m) → 2026-06-22-1430-alex
[sam-chen] Sam Chen — Senior Engineer
  • 2026-06-21T10:15:00 (32m) → 2026-06-21-1015-sam-chen
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
```

**Prompt template placeholders:**
- `{{transcript}}` — the full meeting transcript
- `{{glossary}}` — all glossary terms formatted inline

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
│   └── 22-JUN-2026/                  # organized by date
│       ├── 2026-06-22-1015-name.md   # transcript (incremental, crash-safe)
│       ├── 2026-06-22-1015-name.json # metadata sidecar
│       └── 2026-06-22-1015-name.raw  # raw audio (deleted by default)
└── summaries/
    └── 22-JUN-2026/
        └── 2026-06-22-1015-name.md   # LLM-enhanced output

podscribe.yaml                         # project-wide LLM config (optional)
leadership_team.yaml                   # global glossary terms (optional)
```

## Quick reference

| Goal | Command |
|------|---------|
| Create a pod | `podscribe init <name> [--display-name "..." --role "..." --cadence ...]` |
| Record a meeting | `podscribe <name> record` (or `record <name>`, or `<name> start`) |
| Add glossary term | `podscribe <name> context add "Term" --category person` |
| List glossary | `podscribe <name> context list` |
| View transcript | `podscribe <name> show latest` |
| LLM summary | `podscribe <name> summarize` |
| Set project LLM | `podscribe config llm set <model> '<template>'` |
| View project LLM | `podscribe config llm show` |
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
| `requests` | Summarize | Only needed for the `enhance` command |
| Ollama | Summarize | Must be running at `localhost:11434` |
