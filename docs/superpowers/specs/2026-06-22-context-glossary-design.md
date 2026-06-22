# Context Glossary — Design Spec

Improve transcription accuracy for people's names, project names, and domain
terms via a per-pod glossary used in two ways: live Whisper biasing and
optional post-meeting LLM cleanup.

## Glossary data model

A list of (term, category) entries stored in the existing `config.yaml` under a
new `glossary` key:

```yaml
name: sam-chen
display_name: Sam Chen
role: Senior Engineer
glossary:
  - term: "Anurag Kaushik"
    category: person
  - term: "Project Helios"
    category: project
llm:
  model: "llama3.2"
  prompt_template: |
    Fix the following transcript. Correct any mis-transcribed names
    and project names using this glossary: {{glossary}}.

    Raw transcript:
    {{transcript}}

    Return only the corrected transcript.
```

The `Pod` dataclass gets a `glossary: list[dict]` field (default `[]`). The
`llm` section is optional — only needed for the enhance command.

Categories: `person`, `project`, `client` — for human organization only.
Whisper doesn't use them; the LLM prompt template can reference them.

## CLI — glossary management

```
podscribe context <pod> add "Anurag Kaushik" --category person
podscribe context <pod> remove "Anurag Kaushik"
podscribe context <pod> list
```

New module `podscribe/glossary.py` handles read/write on `Pod.glossary`.
Validation: reject duplicates, trim whitespace, require non-empty term.

## Live Whisper biasing

During `podscribe record <pod>`, construct an `initial_prompt` string from
the glossary:

> "Please transcribe the following names and project names correctly:
> Anurag Kaushik, Project Helios, Podscribe."

Pass as `initial_prompt=prompt` to `pywhispercpp`'s `transcribe()` via
`**params`. Whisper prepends this to the decoder context — it biases token
selection without appearing in output. Overhead: ~20 tokens per segment,
negligible latency impact.

The `Transcriber` class accepts an optional `initial_prompt` parameter.

## LLM enhance pass (manual, on-demand)

### `podscribe enhance <pod> <meeting>`

1. Read raw transcript from `<meeting-id>.md`
2. Load pod config (glossary + llm prompt template)
3. Send to Ollama at `http://localhost:11434/api/generate`
4. Write enhanced transcript to `<meeting-id>-enhanced.md`

New module `podscribe/llm.py` — thin HTTP client to Ollama. Uses standard
`requests` library. No Ollama SDK dependency.

If `llm.model` or `llm.prompt_template` is missing from config, `enhance`
prints an error telling the user to add them — no silent defaults.

### Prompt template variables

- `{{glossary}}` — formatted list of terms with categories
- `{{transcript}}` — full raw transcript text

Template is stored in YAML so the user can edit it freely without code
changes.

## Files changed / created

| File | Change |
|------|--------|
| `podscribe/models.py` | Add `glossary` and `llm` fields to `Pod` |
| `podscribe/config.py` | Save/load glossary + llm section (already handles unknown keys via YAML) |
| `podscribe/glossary.py` | **New** — add/remove/list glossary entries |
| `podscribe/llm.py` | **New** — Ollama HTTP client |
| `podscribe/transcriber.py` | Accept optional `initial_prompt` |
| `podscribe/cli.py` | Add `context` and `enhance` subcommands |
| `podscribe/audio.py` | No change |
| `podscribe/storage.py` | No change |

## Non-goals

- No auto-run of LLM after recording — enhance is always manual
- No WebUI (deferred to later phase)
- No hotwords API (pywhispercpp doesn't support it; `initial_prompt` suffices)
- No pronunciation dictionaries (overkill for this scope)
