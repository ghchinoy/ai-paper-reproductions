# Paper Analysis: MCP Server Evaluation Practices — actionability for our Genmedia MCP servers

**Investigator note / provenance.** I fetched the PDF at `https://arxiv.org/pdf/2608.26133`
(HTTP 200, 6.0 MB), extracted the full text with a local pure-Python decoder (`WebFetch`
was unavailable — its backing model errored), and read the abstract, intro, all four
pipeline-stage descriptions, the evaluation methodology (§4), the results (§5), and the
appendices (rubric tables, prompts, schemas). The cleaned extraction is saved alongside
this doc at `agent-seer-extracted-text.txt` for anyone who wants to verify quotes. PDF
kerning inserts stray spaces inside words in the extraction (e.g. "v erification"); that is
an extraction artifact, not the paper.

**The paper is not the one the brief's phrasing implies.** The arXiv ID resolves to:

> **Agent Seer: Synthesizing Scenarios from Specification Understanding**
> Harish Karumuri, Mahesh Vemula, David Lopes Pegna (Apple).

It is a real, concrete, buildable systems paper — not a survey. But its subject is
**generating evaluation scenarios for agent *tool-calling*, from MCP specs, without ever
running the tools.** That distinction is the whole story for us and I develop it below.

---

## Summary (verdict first)

Agent Seer is **directly and immediately actionable for one layer of our stack and silent
on the layer the owner probably cares most about.**

- **What it gives us for free:** a spec-in → eval-harness-out pipeline that reads an MCP
  server's tool schemas and synthesizes graded, multi-turn test scenarios plus a
  multi-dimensional **LLM-as-judge rubric** (Gemini 2.5 Flash) that scores whether an
  *agent* calls our tools correctly — right tool, right order, right arguments — and
  whether the conversation is coherent. Our genmedia tools have exactly the kind of typed,
  enum-heavy, GCS-URI-shaped parameter schemas this method is designed to stress. The
  rubric (§4, Appendix E) and prompts (Appendix D) are reproduced in the paper in enough
  detail to re-implement.
- **The load-bearing gap:** Agent Seer **never executes a tool and never looks at a tool's
  output.** It feeds the agent *synthetic/mock* tool outputs and judges the transcript. It
  therefore says **nothing about the quality of a generated image, video, audio, or music
  clip.** All seven MCPs it evaluates (Illustrator, Selenium, Redis, Git, Elasticsearch,
  Slack, Filesystem) are text/data/control tools. A "Gemini-based autorater for media
  quality" — grading whether Veo's video actually matches the prompt — is a **different
  autorater that this paper does not provide** and that its architecture explicitly routes
  around ("harnesses decoupled from any execution backend", §2.4).

So the honest tradeoff: **Agent Seer is a low-cost, high-fit answer to "does an agent
orchestrate our genmedia tools correctly?" and a non-answer to "is the media any good?"**
Both are worth having; only the first is in this paper. The second is where our existing
`smoke_generate_and_verify.sh` stops (it confirms a non-empty artifact exists, not that it
is correct), so that gap is real — but the paper does not close it.

---

## 1. What the paper actually proposes

### The problem it targets: the "cold-start evaluation problem"
Producing realistic evaluation data for a tool suite that has none — sharpest for "new,
private, or rapidly evolving APIs." Three named sub-problems (§1): the **curation
bottleneck** (hand-authored benchmarks don't scale), the **static benchmark problem**
(fixed benchmarks rot as APIs evolve), and the **multi-turn evaluation gap** (follow-ups
must react to real tool outputs).

### The core claim
Tool specifications — "function names, natural-language descriptions, and typed parameter
schemas — already encode sufficient semantic information to synthesize realistic evaluation
scenarios without manual curation or live tool execution." (Abstract)

### The mechanism: a four-stage pipeline (§3), each boundary validated by Pydantic schemas
1. **Tool Interpretation (§3.1)** — LLM enriches each raw tool spec into 5 semantic fields
   (`what_it_does`, `what_it_needs`, `why_its_used`, `enterprise_context`, name). Connects
   terse API docs to richer scenarios.
2. **Scenario Generation (§3.2)** — LLM produces scenarios at two complexity tiers (simple
   / complex), each with a title, user prompt, an **exact `agent_workflow`** (ordered tool
   calls with parameters — this is the held-out oracle), a `novelty_reason`, and a
   follow-up. A coverage suffix pushes the generator to exercise *every* tool.
3. **Mock Output Generation (§3.3)** — for each call in the workflow, the LLM fabricates a
   realistic synthetic tool response, tagged with a **grounding tier** (high/medium/low)
   recording whether real example outputs were available. In their runs *all* outputs were
   `low` (specs had no examples).
4. **Multi-Turn Expansion (§3.4)** — splits a scenario into conversational turns at natural
   phase boundaries, with follow-ups that reference concrete values from the mock outputs
   (BFCL v3 multi-step and multi-hop patterns).

The output (§3.5, Table 1) is a **self-contained harness**: `prompt`, `expected_tools`
(oracle, held out), `mock_outputs`, `conversation`. "A downstream framework presents the
prompt, feeds mock outputs as tool responses, and scores the agent's emitted calls against
the scenario workflow as the held-out oracle — enabling evaluation on a previously unseen
tool suite **without live access.**"

### The autorater: LLM-as-judge with a decomposed rubric (§4, Appendix E)
Two independent judge prompts, both unsupervised (no reference answer needed):

- **Tool-Calling correctness (TC)** — four dimensions, 14 sub-dimensions, each scored
  0–10, normalized, arithmetic-mean aggregated:
  - **Usage** (was a tool needed? overuse?)
  - **Selection** (correctness, specificity, completeness of chosen tools)
  - **Ordering** (sequence logic, dependency handling, efficiency; N/A for single calls)
  - **Arguments** (completeness, name accuracy, **value accuracy**, type compliance, format
    compliance, relevancy)
  - **Cascading penalties** enforced via judge prompt: a wrong parameter *name* or missing
    required param zeros out value/type/format; a wrong *value* cascades to type/format/
    relevancy. "A single critical error therefore collapses the argument mean."
- **Coherence (Coh)** — five dimensions (logical flow, completeness, conciseness, topic
  relevance, context retention), scored 1–3, normalized, mean-aggregated.

**Models:** generator = Gemini 2.5 Flash Lite (temp 0.7, structured-output mode); judge =
Gemini 2.5 Flash (temp 0 for determinism). They defend against LLM-as-judge circularity two
ways: an evaluator>generator capability gap (judge is the stronger model), and an
**out-of-family replication** re-scoring all 391 records with Qwen3.5-122B (Alibaba),
getting paired Pearson r≈0.79 on TC, MCP-ranking Spearman ρ=0.86, and reproducing the same
dominant failure mode. Coherence was found to be judge-dependent (they report it as such).

### Results worth knowing (§5)
- Evaluated on **seven open-source MCP specs**: Illustrator, Selenium, Redis, Git,
  Elasticsearch, Slack, Filesystem — 337 scenarios → 391 records.
- Mean TC 0.911, mean Coh 0.855; every MCP >0.85 overall, >0.91 on simple scenarios.
- **Finding 1 (their headline):** *parameter-schema complexity* (avg params/tool, optional
  fraction) is the strongest negative correlate of quality (r≈−0.60/−0.66 per-MCP);
  tool-count is a smaller, orthogonal, *positive* effect. Git (11.2 avg params/tool) is
  worst.
- **Finding 2:** **argument value-accuracy is the dominant failure mode** (223 records),
  invisible to coarse name-match metrics — this is the payoff of decomposing the rubric.
- Honest limitations they state: no human-correlation study yet; coherence is
  judge-dependent; there's a pretraining-leak failure (Git tool-name hallucination —
  emitting real CLI commands not in the spec).

---

## 2. Actionable vs. theoretical — how buildable is this?

**Strongly buildable, low-to-moderate effort.** This is the opposite of a survey. The paper
hands you:
- the exact rubric dimensions/sub-dimensions and scoring scales (Tables 18, 19),
- the cascading-penalty rules (Table 18 footnote),
- the pipeline prompts verbatim for all four stages (Appendix D),
- the Pydantic output schemas (Appendix F, Figure 2),
- the harness artifact format (Table 1).

A competent engineer could reconstruct the TC autorater against one of our servers in
**days, not weeks**, because the "hard" artifacts (rubric + prompts + schema) are published.

**What is NOT handed to you / must be supplied:**
- No released code or repo is cited (I found none referenced in the paper). You
  reimplement from the prompts/tables.
- The "downstream framework" that actually *drives an agent* and feeds it the mock outputs
  is described (§3.5) but not provided — you build the runner.
- An **agent under test.** Agent Seer evaluates *an agent's* tool-calling. We need to
  decide what plays that role (Gemini CLI / geminicli, our own agent harness, or a raw
  Gemini function-calling loop given our tool schemas).
- Human-correlation validation is explicitly left as future work; if we want to trust the
  scores we may need to do our own spot-check.

**Buildable-today line:** the spec→scenario→transcript-judge loop for tool-calling
correctness. **Interesting-idea-not-in-this-paper line:** anything that grades the actual
media artifact.

---

## 3. "A Gemini-based autorater" — the multimodal compatibility question (engaged honestly)

This is the crux, and the brief's framing hides a fork. There are **two different
autoraters** and the paper only builds one:

**(A) The Agent Seer autorater (in the paper).** Judges a *text transcript* of tool calls
against a spec-derived oracle, with mock outputs. It is **modality-agnostic about tool
output because it never sees the output** — it fabricates one. Applied to our servers it
would score: "Given the user asked for a 16:9 cinematic clip, did the agent call `veo_t2v`
(not `veo_i2v`), pass a valid `model`, set `aspect_ratio` to a schema-legal enum, format the
output GCS URI correctly, and — for an i2v chain — feed the prior image artifact as input?"
That is **fully compatible** with our servers and arguably *more* valuable for us than for
the paper's text tools, because our schemas are exactly the enum/URI/model-string-heavy
kind where argument-value errors bite (wrong Veo model rejecting `generate_audio=true` is a
real footgun already documented in our own smoke README).

**(B) A media-quality autorater (NOT in the paper).** Grade the actual pixels/audio: does
the video depict "a slow cinematic pan across a calm mountain lake at sunrise"? Is the audio
intelligible TTS? Does the music match "upbeat acoustic"? This requires **Gemini's
multimodal input** (feed the generated MP4/PNG/WAV back to Gemini with a rubric). Agent
Seer's architecture is *deliberately decoupled from execution* (§2.4), so it offers no
rubric, no prompt, and no methodology for this. We would be inventing it, taking only
inspiration (decomposed rubric, cascading penalties, out-of-family judge check) from the
paper.

**Honest conclusion:** the paper's approach handles our servers well *as tool interfaces*
and not at all *as media generators*. If the owner's real goal is "is the generated media
good," Agent Seer is scaffolding and philosophy, not a solution. If the goal is "does an
agent reliably orchestrate our genmedia tools," Agent Seer is close to a drop-in recipe.

---

## 4. Grounding against what already exists in this repo

Checked in `/workspace/vaics-agent-tools` (one of many clones of the genmedia repo;
`SCION_WORKSPACE_MODE=shared-plain`):

| Existing artifact | What it verifies | What it does NOT do |
|---|---|---|
| `experiments/mcp-genmedia/.../<server>/verify.sh` | `go build` + `tools/list` liveness (STDIO handshake) | No tool call, no output |
| `experiments/agent_tools/smoke_generate_and_verify.sh` | Fires ONE real `tools/call` per server, confirms a **non-empty artifact exists** (local file or GCS object, size>0) | No quality/rubric judgment; no multi-turn; no agent-orchestration test; hard-coded single prompt per server |
| `GEMINI.md` End-to-End Test Plan (§ in `mcp-genmedia-go/GEMINI.md`) | Manual, agent-driven multi-step run producing `report.json`/`report.md` with **status = Success/Failed + filepath** | Status/existence only, no scored quality; manual, not automated; no rubric |

**The starting point is: we verify existence and liveness, never *correctness* or
*quality*.** Servers covered by the smoke test: gemini(image), nanobanana(image), veo(t2v
video), lyria(music), chirp3(tts), omni(video), avtool(ffmpeg transform). Imagen is
intentionally excluded (models shut down 2026-08-17, HTTP 404). This matters for planning:
avtool is deterministic transformation (not generative) and is the *one* server where
"correctness" is objectively checkable without a judge.

**Agent Seer would sit above the smoke test, not replace it:** smoke = "the plumbing works
and produces bytes"; Agent Seer (A) = "an agent calls the plumbing correctly"; a future
autorater (B) = "the bytes are good." No existing artifact does (A) or (B). So neither
proposal duplicates existing work.

---

## 5. Analysis deliverables

### 5a. Analysis (paper mapped to our servers)
Agent Seer's spec-driven scenario+rubric pipeline maps cleanly onto our servers' tool
schemas and would give us the currently-missing **orchestration-correctness** layer. Its
argument-correctness decomposition is especially apt: our known failure modes (wrong Veo
model, illegal enum values, GCS-URI formatting, i2v needing an upstream image) are exactly
"argument value/format/type" sub-dimension failures the paper shows coarse metrics miss. It
does **not** map onto media-artifact quality at all.

### 5b. Questions to ask
*(For the owner — I will raise these serially, highest-leverage first.)*
1. **Which autorater do you actually want** — (A) agent-orchestrates-our-tools-correctly, or
   (B) the-generated-media-is-good? They are different builds; the paper only supplies (A).
   *(This is the load-bearing decision; everything else depends on it.)*
2. If (A): **what is the "agent under test"** — Gemini CLI, our own agent, or a raw Gemini
   function-calling loop over our schemas?
3. If (B): what does "good media" mean well enough to rubric it — prompt-adherence only, or
   also aesthetic/technical quality, safety, C2PA/provenance correctness?
4. Do we have (or can we cheaply produce) a small set of **real example outputs** per tool?
   The paper runs entirely at grounding-tier `low`; real examples would raise mock fidelity
   for (A) and are mandatory ground-truth for (B).
5. What's the appetite for **LLM-as-judge cost/nondeterminism** in CI vs. a cheaper
   deterministic check?

*Open research questions the paper leaves:* no human-quality correlation (they flag it);
coherence is judge-dependent; pretraining-leak hallucination (tool names not in spec) —
directly relevant since our tools have common-verb names.

### 5c. Pros and cons of adopting Agent Seer's approach here

**Pros**
- Published rubric + prompts + schemas → fast to reimplement; low novel-research risk.
- Spec-driven → auto-tracks our evolving tool schemas (solves the static-benchmark rot the
  paper names; our tools change often — models get deprecated, params added).
- Decomposed argument scoring surfaces our real footguns that existence-checks can't.
- No live tool execution → cheap, fast, no Vertex quota/cost/GCS spend to run the eval
  itself; deterministic-ish judge (temp 0).
- Multi-turn coverage tests agentic chaining (imagen→veo i2v, chirp→avtool) we only test
  manually today.

**Cons**
- **Says nothing about media quality** — the thing our servers uniquely produce.
- Mock outputs are LLM-fabricated; for media tools a "mock output" is a fake GCS URI /
  fake success blob — realistic enough to test *calling* but inherently fictional.
- LLM-as-judge circularity risk (they mitigate with out-of-family judge; we'd need to too).
- Requires standing up an agent-under-test + runner harness (not provided).
- Coherence scores are judge-dependent → treat as soft signal.
- Pretraining-leak hallucination risk is *higher* for us: our tool names are generic verbs.

### 5d. Counterfactuals (what if we DON'T do this)
- **Status quo cost:** `smoke_generate_and_verify.sh` catches "server broke / produces no
  bytes." It will **not** catch: an agent picking the wrong model, passing a soon-invalid
  enum, mis-formatting a GCS URI, breaking an i2v chain, or a model silently producing
  garbage media. Those failures reach users. The manual GEMINI.md plan catches some but is
  unautomated and effort-bounded — it rots exactly as the paper predicts.
- **Cheaper partial alternatives that get most of the value:**
  1. **Static schema-contract tests** (no LLM): assert enum legality, required-param
     presence, model-string validity, URI shape against the live `tools/list` schema. Kills
     the "static benchmark rot" and most argument-format failures for ~a day of work, no
     judge, no cost. *Captures a large slice of Agent Seer's argument dimension deterministically.*
  2. **Golden-transcript tests**: a handful of hand-written agent conversations with
     expected tool calls, diffed. Cheap, no judge, but doesn't scale/auto-track (the exact
     curation bottleneck the paper attacks).
  3. **Extend the smoke test with a single multimodal Gemini "sanity" pass** (does the
     image roughly match the prompt? yes/no) — a minimal slice of autorater (B) without the
     full rubric. Highest value-per-effort if the owner actually wants media quality.
- **Recommendation on counterfactual:** alternative (1) is worth doing *regardless* — it's
  a deterministic floor. Agent Seer (A) is the scalable ceiling for orchestration. (B) is a
  separate initiative.

### 5e. Potential test implementation plan (SKETCH — for owner review, not a committed design)

> Load-bearing assumption flagged up front: this sketches autorater **(A)**, because it's
> what the paper supports and what nothing in our repo does. If the owner wants **(B)**,
> most of this changes and I'd re-scope.

**Which server first:** start with **`mcp-veo-go`** (or nanobanana as a cheaper proxy).
Rationale: Veo has the richest/most-error-prone schema (model selection, aspect ratio,
`generate_audio`, t2v-vs-i2v, GCS output) — the exact schema-complexity/argument-accuracy
regime the paper shows is where the method earns its keep. Filesystem-like simplicity (e.g.
avtool) would under-exercise it.

**Phased build:**
1. **Ingest spec** — pull the target server's `tools/list` JSON (we already do this in
   `verify.sh`); feed each tool schema into a reimplemented **Stage 1** interpreter prompt.
2. **Generate scenarios (Stage 2)** — simple + complex tiers, with the coverage suffix, over
   the genmedia tool set. Oracle = the generated `agent_workflow`.
3. **Mock outputs (Stage 3)** — synthesize plausible success responses (fake GCS URIs,
   operation-done blobs). *Decision to flag:* seed with 1–2 **real** smoke-test responses
   per tool to lift grounding tier above `low` — cheap, we already produce them.
4. **Multi-turn expansion (Stage 4)** — optional in v1; the highest-value multi-turn case
   for us is the **i2v / avtool chain** (image→video, tts→mp3), so prioritize that pattern.
5. **Runner** — drive an agent-under-test (decision Q2) with the prompt + tool schemas,
   capture emitted calls, feed mock outputs back, produce a transcript. *This is the piece
   the paper describes but doesn't provide.*
6. **Judge (§4 rubric)** — reimplement the TC + Coherence prompts with Gemini 2.5 Flash
   (temp 0), including cascading penalties. Emit per-dimension scores + failure taxonomy.
7. **Robustness check** — periodically re-score with an out-of-family judge (paper uses
   Qwen3.5) to detect judge circularity before trusting numbers.
8. **CI shape** — run offline/cheap (no Vertex generation cost since tools aren't executed);
   gate on TC score thresholds + zero schema-illegal arguments.

**Effort estimate (rough, for owner sizing):** Phases 1–3+6 for one server ≈ a small spike
(single engineer, ~1 week) given the prompts are published; phases 4–5 (agent runner +
multi-turn) add the real integration cost and depend on Q2. Treat as an **architect-worthy
design** only if we commit to it as standing infra across all servers + CI.

---

## Scope recommendation (Sizing)
This investigation itself is done. For the *follow-on* work, if the owner greenlights it:
- **Alternative (1) deterministic schema-contract tests:** small, single-implementer task.
- **Agent Seer (A) proof-of-concept on one server:** a **spike** first (validate the judge
  produces useful, non-degenerate signal on genmedia schemas) before any broad build.
- **Media-quality autorater (B):** this is genuinely new design (no paper recipe) →
  **architect-designed** before implementation if pursued.
I recommend the owner pick the autorater target (Q1) and authorize a one-server **spike**
for (A) rather than committing to full infra sight-unseen.

## Open questions I could not resolve myself
- Whether the owner wants (A) orchestration correctness or (B) media quality — decides scope.
- No public Agent Seer code exists (reimplement from prompts); I could not verify an
  official implementation.
- Whether we have real per-tool example outputs to raise mock grounding above `low`.
- What agent-under-test we'd evaluate (affects the runner design materially).
