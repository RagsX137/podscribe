# Podscribe — Production Readiness & Showcase Plan

**Goal:** make Podscribe a flagship repo that reads convincingly to an **AI/ML Engineer**
hiring audience (applied AI, LLM/agent systems, ML pipelines, evaluation rigor).

**Guiding insight:** the gap between where this repo is and an "ideal" flagship is *not*
more features — the engineering is already strong (~5,400 LOC code vs ~5,200 LOC tests,
144 clean conventional commits, ADR + architecture docs, a documented audit→design→plan
workflow). The gap is **legibility**: making that quality visible in 60 seconds to a
reviewer who will *never install* an Apple-Silicon + Ollama + microphone stack.

Reviewer signals to maximize for the AI/ML-Engineer persona:
1. Builds reliably with LLMs/agents (✅ god-mode agent loop).
2. Measures model output quality (⚠️ seed exists in the ASR benchmark; needs an LLM eval).
3. Productionizes an ML pipeline (⚠️ needs CI, reproducibility, packaging polish).

---

## Phase 0 — Legibility & credibility (½–1 day) · **IN PROGRESS**

Zero intellectual cost, high signal. Removes the dead-ends in the 60-second scan.

| Item | Status |
|---|---|
| `LICENSE` (MIT, matches README) | ✅ done |
| GitHub Actions CI (`.github/workflows/ci.yml`) | ✅ done |
| README badges (CI · license · python · platform) | ✅ done |
| README "Highlights" band (elevator pitch above the fold) | ✅ done |
| `ruff` + `mypy` added to `[dev]` extras + configured in `pyproject.toml` | ✅ done |
| Fix real Python-3.10 f-string syntax bug (`tui.py`) | ✅ done |
| Fix `F821` undefined-name forward-refs (`cli.py`) | ✅ done |
| Lint burn-down (13 style findings) → then make ruff gate broader | ⬜ pending |
| Wire `mypy` as a blocking CI gate | ⬜ pending |
| Verify CI is green on first push (webrtcvad build on runner) | ⬜ pending |

### CI design (why it's built this way)

- **`test` job runs on `macos-latest` (Apple Silicon).** `mlx-whisper` only installs on
  Apple hardware, so ubuntu is not an option for the runtime tests. macOS runners are
  free for public repos. Runs `pytest -k "not transcriber"` to skip the one smoke test
  that downloads a real Whisper model.
- **`lint` job runs on `ubuntu-latest`** (ruff needs no ML deps → fast). `pyproject.toml`
  pins `target-version = "py310"`, so ruff *statically* rejects 3.10-incompatible syntax
  without needing a 3.10 runtime — this is how we prove the `requires-python >= 3.10`
  claim cheaply. (It already caught a real bug: a backslash inside an f-string expression,
  invalid before 3.12, latent because the dev interpreter is 3.14.)
- **Blocking ruff ruleset is the *correctness* subset** `E9, F63, F7, F82` — real bugs,
  not style. Verified clean. The broader style set is a tracked burn-down (below) so the
  badge is green today rather than red-on-arrival.

### Lint burn-down (13 advisory findings — safe, deferred)

All are `F401` (unused import) or `F541` (f-string without placeholder). Deferred from the
blocking gate because some "unused" imports may be re-export / test-monkeypatch seams that
need the full test suite (which requires Apple-Silicon deps) to remove safely. Triage each,
then widen `[tool.ruff.lint] select` to `["E", "F", "W", "I"]` and flip the gate.

```
agent.py:5            F401  shlex
agent_tools.py:296    F401  .llm.enhance_transcript   (verify not a patch seam)
agent_tools.py:342    F401  .llm.enhance_transcript   (verify not a patch seam)
audio.py:9,11,12      F401  collections / threading / time
cli.py:511            F541  empty f-string
cli.py:646            F401  .agent_tools.MAX_TOOL_RESULT_CHARS
tui.py:15             F401  tty
tui.py:27             F401  .cli._resolve_meeting      (verify not a patch seam)
tui.py:286            F401  rich.padding.Padding
tui.py:1172           F401  .agent._format_tool_result (verify not a patch seam)
tui.py:1233           F541  empty f-string
```

---

## Phase 1 — Proof it works without installing (1 day) · conversion

A reviewer won't run the stack; give them the result.

- **Asciinema/gif** of `record → show → enhance → consolidate`, driven off the committed
  `fixtures/asr/` clips so it reproduces without a mic. Embed at the top of README.
- **One-command demo path** (`make demo` or a script) that runs the *benchmark* on the
  committed fixtures and prints the table — lets a Linux/Windows reviewer watch the ML
  evaluation execute even though the live-mic path won't run for them.

---

## Phase 2 — The headline AI/ML contribution (2–4 days) · **depth** ⭐

The differentiator. Build an **evaluation of the LLM `enhance`/`consolidate` pipeline** —
not just ASR WER, but *generation quality*. This is the daily job of an AI/ML engineer
working with LLMs in production, and the raw materials already exist.

- **Hallucination / grounding rate.** `llm.py` already ships `ANTI_HALLUCINATION_PREAMBLE`
  and `SPEAKER_PRESERVATION_PREAMBLE` — now *measure whether they work*. Small labeled set
  of transcripts with known facts/names; run enhance with the preambles on vs off; report
  name-preservation accuracy, invented-fact rate, action-item-attribution accuracy.
- **Structured-extraction accuracy.** `consolidate` extracts YAML fields — measure
  field-level precision/recall against a gold set.
- **Quality-vs-latency Pareto.** Turn the documented "27B vs 8B" gut call
  (`Recommended_fixes.md` §3.1) into a measured table across 2–3 Ollama models.
- Write up as `docs/EVALS.md`, linked from README next to `BENCHMARKS.md`.

**Own the known weakness.** `docs/BENCHMARKS.md` shows the pipeline emits ~87% more words
than reference (VAD fragmentation). State it plainly and discuss mitigation — a candidate
who measures and openly reasons about a flaw in their own system reads as *more* senior,
not less.

---

## Phase 3 — Systems / production signal (1–2 days) · polish

- **`CONTRIBUTING.md`** promoted from `AGENTS.md` (roadmap P8) — signals collaboration-ready.
- **Model-card-style writeup** (`docs/MODEL_CARD.md`): which models, why, known failure
  modes, intended use. Standard artifact AI/ML reviewers look for.
- Widen CI: matrix `[3.10, 3.12]` on the test job once wheel availability is confirmed;
  flip ruff to the full ruleset and add the mypy gate (see Phase 0 burn-down).

---

## Explicitly NOT doing (for this goal)

The Tier-3 product features from `Recommended_fixes.md` §5 (`prep`, `digest`, cross-pod
sentiment, perf-review draft) are great *product* ideas but read as "more app," not "more
AI/ML engineer." Ship at most **one** as a demo of the agent loop; a whole suite of them
distracts from the eval story (Phase 2) that actually differentiates the repo.

---

## Sequencing rationale

Phase 0 removes disqualifiers → Phase 1 gets the repo read → Phase 2 is the thing worth
remembering → Phase 3 is finish. **Phase 0 + Phase 2 alone** already put this ahead of most
candidate repos.
