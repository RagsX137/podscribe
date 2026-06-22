# Podscribe KT Handoff

## What it does

CLI tool that records meetings (mic → Whisper → transcript) per person ("pod"). Now with glossary support to fix mangled names/projects.

## Core flow

```
podscribe init <name>          # create a pod for a person
podscribe context <name> add... # add names, projects, terms
podscribe record <name>        # live transcribe (uses glossary as Whisper bias)
podscribe enhance <name> latest # optional LLM cleanup via Ollama
podscribe list                 # list all pods and meetings
podscribe show <name> latest   # view transcript
```

## Glossary (new)

Per-pod list of names/projects stored in `pods/<name>/config.yaml`:

```
podscribe context demo add "Anurag Kaushik" --category person
podscribe context demo add "BEM" --category project
podscribe context demo list
```

During recording, these are injected as Whisper `initial_prompt` — zero latency cost.

## LLM enhance (new, optional)

Needs `llm` section in `config.yaml`:

```yaml
llm:
  model: "qwen3.6"
  prompt_template: |
    Fix names and project terms in this transcript.
    Glossary: {{glossary}}
    Transcript: {{transcript}}
    Return only the corrected transcript.
```

Run: `podscribe enhance demo latest`

Saves to `<meeting-id>.enhanced.md`. You control the prompt — edit it in YAML anytime.

## Files changed

| File | What |
|------|------|
| `podscribe/models.py` | Pod has `glossary` + `llm` fields |
| `podscribe/glossary.py` | Manage entries, format Whisper prompt |
| `podscribe/llm.py` | Ollama HTTP client |
| `podscribe/transcriber.py` | Passes `**kwargs` to pywhispercpp |
| `podscribe/cli.py` | `context` + `enhance` commands |

## Model

Default is `large-v3-turbo` (~500MB, best accuracy). Use `--model base` for speed.
