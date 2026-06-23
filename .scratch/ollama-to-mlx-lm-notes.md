# Notes: Replacing Ollama with mlx_lm for `enhance`

Date: 2026-06-22
Status: Discussion only — no code changes yet.

## Context

- `podscribe/llm.py` is Ollama-specific: uses `/api/generate` (streaming) and `/api/show` (context window probe).
- mlx-whisper already runs in-process via `mlx-whisper` (HuggingFace), no server needed for STT.
- Question: can we drop Ollama and use `mlx_lm` for the LLM side too, for speed?

## Key takeaways from discussion

### "mlx_lm reloads weights every call" is a process-lifetime issue, not a framework flaw

- A 27B model is ~16-27 GB of weights on disk. To generate *any* token, weights must be in RAM. No framework can skip this.
- Ollama keeps weights resident by being a long-running daemon (`ollama serve`). First call loads; subsequent calls are hot.
- `python -m mlx_lm generate` is one-shot: load → generate → exit → RAM reclaimed. Next invocation pays full load (~10-30s for 27B) again.
- This is **not** lazy MLX design — it's just that short-lived processes can't keep RAM across invocations. Ollama avoids it only by being a server, not by loading faster.

### Options to keep weights in RAM with mlx_lm

1. **`mlx_lm.server`** — Apple-shipped Ollama-equivalent.
   `python -m mlx_lm.server --model mlx-community/... --port 8080`
   OpenAI-compatible `/v1/chat/completions` endpoint. Long-lived, weights resident.
   → Closest to current architecture; basically swapping Ollama HTTP for MLX HTTP. Doesn't actually escape the "localhost server" pattern.

2. **`mlx_lm.chat`** — built-in REPL, loads once, stays alive for conversation turns. Good for ad-hoc Q&A.

3. **Python API in a loop** — `mlx_lm.load()` once, then call `mlx_lm.stream_generate()` per prompt in the same process. Second prompt onward reuses resident weights.
   Example:
   ```python
   import mlx_lm
   model, tokenizer = mlx_lm.load("mlx-community/Qwen3-32B-4bit")
   for prompt in my_prompts:
       for token in mlx_lm.stream_generate(model, tokenizer, prompt=prompt):
           print(token.text, end="", flush=True)
   ```

### Expected performance impact (switching Ollama → mlx_lm)

- Raw tok/s on MLX is modestly better than llama.cpp/Ollama on Apple Silicon — maybe 15-40%, varies by model and Mac.
- For one-shot `enhance` per meeting (~30-60s total), generation savings are ~2-5s. Startup-load cost is on the same order.
- Real wins from switching: **simpler install** (one framework: mlx for STT + LLM), **no `ollama serve` process to manage** (already a documented gotcha in AGENTS.md).
- Speed is **secondary**; install/UX simplification is primary.
- Slow generation is usually the model size + `num_ctx`, not the framework. A 27B at large context is slow under either.

## TODO / Options for podscribe

- **Option A — `mlx_lm.server` path**: minimal change to `llm.py`. Keep HTTP-client shape, swap URL + payload format (Ollama streaming → OpenAI chat-completions streaming). Removes Ollama dependency, still needs a server process running.
- **Option B — in-process `mlx_lm.generate`**: rewrite `enhance_transcript` to use `mlx_lm.load` + `stream_generate` directly. No server process at all, but pays full weight-load on every `podscribe enhance` invocation. Fine if `enhance` is run rarely (once per meeting).
- **Unanswered**: which exact Qwen model? "Qwen3.6:27b" was not verifiable — need user to specify the `mlx-community/...` HF repo path. Likely candidates: `mlx-community/Qwen3-32B-4bit` or similar.

## References in repo

- `podscribe/llm.py:14` — `OLLAMA_URL` constant (HTTP endpoint)
- `podscribe/llm.py:65` — `_ollama_model_info` (uses `/api/show`)
- `podscribe/llm.py:75` — `enhance_transcript` (streaming HTTP client)
- `podscribe/cli.py:17` — imports from `.llm`
- `podscribe/cli.py:368` — `cmd_enhance` (loads llm config, calls enhance)
- `podscribe/cli.py:510` — `cmd_consolidate` (also uses `_run_enhance`)
- `podscribe/cli.py:728` — `config llm set` help text explicitly mentions "Ollama model name" — would need updating.

## Decision

Deferred — revisit when ready to prototype. No code touched.