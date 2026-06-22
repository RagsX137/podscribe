# Podscribe roadmap

Ideas for future exploration, not yet prioritized.

## 1. Glossary improvements

Current glossary injects terms as Whisper `initial_prompt`. This is zero-latency but limited — Whisper may ignore it on short segments.

Ideas to explore:
- hotword/phrase biasing via Whisper detection heuristic
- automatic glossary extraction from past transcripts (extract names/projects mis-transcribed across meetings)
- per-meeting glossary overrides via CLI flags

## 2. VAD tuning & segmentation

Current VAD (webrtcvad, aggressiveness 0-3) is basic. Issues:
- loose VAD (0-1) passes through noise → garbage segments
- strict VAD (3) clips soft-spoken starts
- 5-frame silence threshold is hardcoded

Ideas to explore:
- silence threshold as CLI parameter
- adaptive VAD that learns noise floor per session
- post-VAD merge: rejoin segments that were split by brief pauses (same speaker)
- energy-based pre-filter before VAD

## 3. LLM enhance (Ollama)

Current `enhance` command sends transcript to Ollama for cleanup. It works but is basic:
- single-shot, no streaming
- no progress feedback for long transcripts
- prompt template is hand-edited in config.yaml

Ideas to explore:
- streaming token-by-token display during enhance
- built-in prompt templates (fix-hallucinations, summarize, extract-actions)
- diff view: show original vs enhanced side by side
- auto-run enhance after record completes

## 4. Segment merging & continuity

Current VAD segments speech into 1-3s chunks, each independently transcribed by Whisper. This causes fragmented sentences and filler word bloat (~87% more words than reference).

Ideas to explore:
- increase `MAX_SEGMENT_SEC` from 10s to 30s to yield longer utterances
- lower default `VAD_AGGRESSIVENESS` from 2 to 1 to avoid mid-sentence splits
- pass previous segment text as `initial_prompt` to subsequent segments for continuity
- post-hoc merge: rejoin adjacent segments that form grammatical sentences

## 5. LLM de-fragmentation pass

After recording, run an Ollama pass specifically to merge fragments and fix segmentation artifacts, independent of the existing enhance command.

## 6. Model accuracy tuning

Compare `large-v3-turbo` vs full `large-v3` on the same audio for accuracy-latency trade-off. Consider smaller models (`base.en`) for test/iteration speed.
