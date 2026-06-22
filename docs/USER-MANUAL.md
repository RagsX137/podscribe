# Podscribe User Manual

Quick reference for local-first live transcription with per-pod glossary and optional LLM enhancement via Ollama.

## Commands

### `podscribe init <pod>`
Create a new pod (a person or project you meet with).

```
podscribe init sam-chen
podscribe init priya-patel --display-name "Priya Patel" --role "Tech Lead" --cadence biweekly --notes "Strong on backend"
```

### `podscribe record <pod>` or `podscribe <pod> record` or `podscribe <pod> start`
Live transcribe a meeting. Glossary terms are injected as Whisper hints.

```
podscribe record demo
podscribe demo record
podscribe demo start
```

Options:
- `--model small` — Whisper model (default: `large-v3-turbo`)
- `--vad-aggressiveness 0-3` — VAD strictness (default `2`, `0`=loose, `3`=strict)
- `--keep-audio` — keep raw audio file after recording
- `--device <N>` — input device index

Press `Ctrl+C` to stop and finalize.

### `podscribe list`
List all pods and their meetings.

```
podscribe list
```

### `podscribe show <pod> latest` or `podscribe <pod> show latest`
Print the latest (or a specific) transcript.

```
podscribe show demo latest
podscribe demo show latest
podscribe demo show 2026-06-22-10  # any prefix works
```

### `podscribe context`
Manage per-pod glossary (names, projects, technical terms).

```
podscribe context demo add "Anurag Kaushik" --category person
podscribe context demo add "Batch Endpoints" --category project
podscribe demo context add "BEM" --category project
podscribe demo context remove "Foo"
podscribe demo context list
```

### `podscribe enhance <pod> [meeting]` or `podscribe <pod> summarize [--latest]`
Send transcript + glossary to Ollama for analysis. The prompt template is in the pod's `config.yaml` — edit it directly.

```
podscribe enhance demo latest       # old syntax
podscribe enhance demo --latest     # old syntax + flag
podscribe demo enhance              # pod-first syntax (defaults to latest)
podscribe demo summarize            # same, via summarize alias
podscribe demo summarize --latest   # explicit flag
podscribe summarize demo --latest   # alias at top level
```

## Config

Each pod lives in `pods/<name>/config.yaml`. You can edit it directly:

```yaml
glossary:
  - term: Anurag Kaushik
    category: person
  - term: Batch Endpoints
    category: project
llm:
  model: qwen3.6:27b
  prompt_template: |
    Analyze this transcript of a team meeting.
    ...
```

The `prompt_template` supports `{{glossary}}` and `{{transcript}}` placeholders. If `{{transcript}}` is omitted, the full transcript is appended at the end.

## Quick Reference

| Goal | Command |
|------|---------|
| New pod | `podscribe init <name>` |
| Record meeting | `podscribe <name> record` or `<name> start` |
| Add glossary term | `podscribe <name> context add "Term" --category person` |
| List terms | `podscribe <name> context list` |
| View transcript | `podscribe <name> show latest` |
| LLM summary | `podscribe <name> summarize` |
| All pods | `podscribe list` |

## Dependencies

- **Ollama** running at `localhost:11434` (for `enhance` only)
- **Whisper** model downloaded on first `record`
