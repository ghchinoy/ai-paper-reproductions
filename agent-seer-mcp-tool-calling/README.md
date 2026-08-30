# Grading the agent, not the pixels: reproducing Agent Seer on a generative-media MCP server

*A spike report on spec-driven tool-calling evaluation, the negative result we hit, and the one change that fixed it.*

## Why we ran this

We ship a set of Model Context Protocol (MCP) servers that let an agent drive Google Cloud's generative-media APIs: text-to-video, image-to-video, text-to-speech, music, and audio/video compositing. Our existing checks confirm that a server starts, answers a `tools/list` handshake, and produces a non-empty artifact. They do not confirm that an *agent* calls those tools correctly: right tool, right order, schema-legal arguments. That orchestration layer is where real bugs reach users. An agent picks a model that cannot do what the prompt asks, passes an aspect ratio the model rejects, or breaks an image-to-video chain by forgetting to pass the upstream frame.

A recent paper offered a way to build that missing layer without hand-authoring a benchmark. We reproduced its method against one of our servers to see whether the signal holds up on real generative-media tool schemas. This post covers what we built, the concrete numbers, an instructive negative finding, and the single adjustment that turned a false pass into clean discrimination.

## The paper: Agent Seer

Agent Seer (Karumuri, Vemula, and Lopes Pegna, arXiv 2608.26133) targets the cold-start evaluation problem: you have a new or fast-changing tool suite and no test data for it. Its claim is that a tool specification already carries enough meaning to synthesize evaluation scenarios, so you can generate an eval harness from the spec alone and never execute a tool.

The method is a four-stage pipeline, with a Pydantic schema validating each stage boundary:

1. **Tool interpretation.** An LLM enriches each raw tool spec into semantic fields (what it does, what it needs, why it is used, enterprise context).
2. **Scenario generation.** The model writes scenarios at two tiers, simple and complex. Each scenario carries a user prompt and an exact ordered workflow of tool calls with arguments. That workflow is the held-out oracle. A coverage instruction pushes the generator to exercise every tool.
3. **Mock output generation.** For each call, the model fabricates a plausible tool response and tags it with a grounding tier (high, medium, low) recording whether real example outputs were available.
4. **Multi-turn expansion.** The model splits a scenario into conversational turns with follow-ups that reference concrete values from the mock outputs.

The scoring half is an LLM-as-judge with a decomposed rubric. Tool-calling correctness spans four dimensions (usage, selection, ordering, arguments) across fourteen sub-dimensions, each scored 0 to 10, normalized, and averaged. The rubric enforces cascading penalties through the judge prompt: a wrong parameter name or a missing required parameter zeros out the value, type, and format scores for that argument, and a wrong value cascades into type, format, and relevancy. One critical error collapses the argument mean rather than costing a fraction of a point. A separate coherence rubric scores five dimensions from 1 to 3.

The paper uses Gemini 2.5 Flash Lite as the generator (temperature 0.7) and Gemini 2.5 Flash as the judge (temperature 0 for determinism). It defends against LLM-as-judge circularity two ways: the judge is a stronger model than the generator, and the authors re-score every record with an out-of-family model (Qwen3.5-122B), reporting a paired Pearson correlation near 0.79 on tool-calling correctness and a Spearman rank correlation of 0.86 across servers. Across seven open-source MCP servers (Illustrator, Selenium, Redis, Git, Elasticsearch, Slack, Filesystem) it produced 337 scenarios and 391 records, with mean tool-calling correctness of 0.911. Its headline result is that argument value-accuracy is the dominant failure mode, and that coarse name-match metrics miss it.

One property of the paper matters for us before we write a line of code: every server it evaluates is a text, data, or control tool. Agent Seer never executes a tool and never inspects a tool's output. It feeds the agent a synthetic output and judges the transcript. So the method says whether an agent *orchestrates* a tool suite correctly. It says nothing about whether a generated video, image, or audio clip is any good. We reproduced the orchestration half, which is the half the paper supports, and the half nothing in our repo does today.

## Systems under test

We ran the reproduction against **`mcp-veo-go`**, our Veo video-generation server. We picked it because it has the most error-prone schema of any server we ship: model selection, aspect ratio, an audio toggle, distinct text-to-video and image-to-video entry points, and GCS output URIs. That is the schema-complexity and argument-accuracy regime where the paper predicts the method earns its keep. A filesystem-simple server would under-exercise it.

The server exposes six tools, all of which the pipeline covered:

| Tool | Job |
|---|---|
| `veo_t2v` | Text-to-video |
| `veo_i2v` | Image-to-video (requires an input image) |
| `veo_first_last_to_video` | Interpolate between a first and last frame |
| `veo_reference_to_video` | Generate guided by reference images |
| `veo_ingredients_to_video` | Compose a video from multiple input assets |
| `veo_extend_video` | Extend an existing clip |

Models under test:

- **Generator:** Gemini 2.5 Flash Lite, temperature 0.7, structured-output mode, matching the paper.
- **Judge:** Gemini 2.5 Flash, temperature 0, matching the paper.
- **Second judge (robustness spot-check):** Gemini 2.5 Pro. This is a same-family check, not the out-of-family check the paper runs. More on that limitation below.

All three run through Vertex AI `generateContent`. The judge and generator hold no state between calls.

## How we reproduced the method

We followed the pipeline stage for stage, using the paper's published prompts where it prints them.

**Stage 0, ingest the real spec.** We built `mcp-veo-go` from source and pulled its actual `tools/list` over a raw JSON-RPC stdio handshake. Every downstream stage runs against the server's real schema, not a hand-summarized version of it.

**Stage 1, tool interpretation.** We used the paper's Appendix D.1 prompt verbatim, once per tool.

**Stage 2, scenario generation.** We used the paper's simple and complex prompts verbatim, including the coverage instruction. The generator produced 15 scenarios (6 simple, 9 complex) with full tool coverage and zero uncovered tools. Each scenario's generated workflow is the held-out oracle.

**Stage 3, mock outputs.** We used the paper's prompt verbatim, with one grounding change we made deliberately. The paper ran entirely at grounding tier `low` because its specs shipped no example outputs. We seeded this stage with the real `mcp-veo-go` success-response shape, a text block plus a `resource_link` per video, taken from the server's own response code and our smoke test. That lifted the grounding tiers to 16 high and 3 medium instead of uniform low. Genmedia responses are simple and stable, so the seed was cheap and raised fidelity for free.

**Judge.** We reconstructed the tool-calling and coherence rubrics from the paper's rubric tables and the cascading-penalty footnote, and implemented the aggregation described in the methodology. The pipeline prompts (stages 1 through 4) are verbatim from the paper. The judge prompts are faithful reconstructions of the published rubric, because the paper describes the rubric in tables rather than printing the judge prompt as a copyable block. We recorded that provenance distinction in the code so a reader can see which text is quoted and which is reconstructed.

We skipped the two stages the paper describes but does not provide as code: the multi-turn expansion (stage 4) and the runner that drives a live agent under test (stage 5). Skipping the runner was the right call for a spike. The runner is a separate integration cost, and leaving it out lets the spike isolate one question: does the judge itself discriminate a good tool call from a broken one on a real generative-media schema? To answer that we hand-authored the transcripts the runner would otherwise produce. A production build swaps in a real agent's emitted calls and leaves the judge unchanged.

## The discrimination test

We wrote 11 transcripts against Veo's real schema: 2 correct and 9 each carrying one distinct, documented failure. Then we scored every transcript with the Flash judge and, for a second opinion, the Pro judge.

| Case | Kind | TC (Flash) | TC (Pro) | Failure named | Injected fault |
|---|---|---|---|---|---|
| A0-correct | correct | 1.000 | 1.000 | – | – |
| A1-wrong-model-value | broken | 1.000 | 0.839 | none (Flash missed it) | Veo-2.0 model called with `generate_audio=true` |
| A2-illegal-enum | broken | 0.956 | 0.867 | argument_value | `aspect_ratio: 21:9`, unsupported |
| A3-hallucinated-model | broken | 0.822 | 0.822 | argument_value | model ID not in the spec |
| A4-missing-required | broken | 0.722 | 0.778 | argument_completeness | omitted required `prompt` |
| A5-wrong-tool | broken | 0.444 | 0.494 | selection, argument_value | `veo_i2v` with no image |
| A6-wrong-param-names | broken | 0.667 | 0.794 | name, value, type, format, relevancy | `ratio` / `gcs_bucket`, not in schema |
| B0-correct | correct | 1.000 | 1.000 | – | – |
| B1-wrong-tool | broken | 0.656 | 0.500 | selection | `veo_t2v` ignoring a provided image |
| B2-missing-required-image | broken | 0.778 | 0.794 | completeness, value, type, format | omitted required `image_uri` |
| B3-malformed-uri | broken | 0.867 | 0.911 | value, type, format | `image_uri: "in.png"`, not a `gs://` URI |

The judge separated correct from broken with a mean tool-calling score of **1.000 for correct calls versus 0.768 for broken ones**, a gap of 0.232, and it named the injected fault in **7 of 9** broken cases. For every structural error the schema can express, a missing required field, wrong parameter names, wrong-tool selection, the score dropped and the taxonomy pointed at the right dimension. The cascading penalty fired as designed on A6, where wrong parameter names collapsed the whole argument mean.

## The negative finding: the judge is blind to what the schema does not say

Read the A1 row again. The Veo-2.0 call requesting `generate_audio=true` is the single most realistic production bug in the set, and the Flash judge gave it a perfect 1.000, the same score it gave a fully correct call. A2, an unsupported aspect ratio, scored 0.956 and nearly passed.

The reason is specific and it generalizes. Veo's most valuable constraints do not live in `tools/list`. Which models support audio, and which aspect ratios a given model accepts, live in the server's Go model registry, not in the tool schema the judge reads. The schema literally says aspect ratios are "model-dependent" and lists no enum. Veo-2.0 does not support audio generation at all; the 3.x models do. The judge cannot penalize a violation of a rule it never sees, so it passed the call that our own smoke-test documentation already flags as a footgun.

This is worse than a low score. A test that lets your highest-value bug pass produces false confidence, which is more dangerous than having no test. The same-family Pro judge caught A1 at 0.839, which told us the miss was an information gap in the judge's context, not random noise. The judge had the reasoning capacity; it lacked the constraint.

## The fix: feed the judge a capability matrix

The constraints the judge was missing are already machine-readable in our codebase, in the Veo model registry. We extracted them into a small capability matrix and added it to the judge's context. For each model it records the audio support, supported aspect ratios and durations, maximum video count, and whether the model supports first-last and reference-image modes. The relevant row for A1:

```
veo-2.0-generate-001:  SupportsGenerateAudio = false
veo-3.0-generate-001:  SupportsGenerateAudio = true
veo-3.1-generate-001:  SupportsGenerateAudio = true
```

With that matrix in context we re-scored the affected cases:

| Case | TC before | TC enriched |
|---|---|---|
| A0-correct | 1.000 | 0.994 |
| A1-wrong-model-value | 1.000 | 0.800 |
| A2-illegal-enum | 0.956 | 0.789 |
| A3-hallucinated-model | 0.822 | 0.800 |

The change did the job. Before enrichment, the Veo-2.0 audio bug and a correct call were indistinguishable, both at 1.000. After enrichment, the correct call held at 0.994 while the broken call fell to 0.800, restoring a clean gap between a pass and a fail. The unsupported aspect ratio fell into the same failing band. Correct calls stayed high. The judge works once it can see the constraints.

## What we take from this

The Agent Seer method transfers cleanly to generative-media orchestration. Spec-driven generation gave us full tool coverage with no hand-curation, and the decomposed rubric surfaced the argument-level errors that coarse name-match metrics miss, which is the exact failure profile Veo's schema invites.

The result is a conditional go. The condition is the whole point: do not ship the judge on the spec alone. On its own it passes the highest-value generative-media bugs, model-and-feature incompatibility and model-dependent enums, because those constraints are absent from `tools/list`. The lever that fixes this is cheap and already sitting in our code. If we build this out, the shape is:

1. Enrich the context given to both generator and judge with the capability matrix from the model registry. Low effort, validated above.
2. Pair the LLM judge with deterministic schema and capability contract checks for the constraints that are machine-checkable, and reserve the judge for selection, ordering, and value-grounding that is not.
3. Then invest in the live agent-under-test runner, the real integration cost, and gate CI on scores only after the runner exists.

## A forward-looking note on the out-of-family judge

The paper's defense against LLM-as-judge circularity rests on re-scoring with an out-of-family model, Qwen3.5-122B. We could not reproduce that check. We had no Qwen access in this environment, so our second judge was Gemini 2.5 Pro, which is a same-family model. Pro agreed with Flash on most cases and, usefully, caught the A1 bug that Flash missed, but same-family agreement cannot rule out a shared blind spot.

A natural next step, suggested by the project owner, is to use a Gemma 24B model available through Model Garden as the out-of-family judge in place of Qwen. Gemma is a distinct model family from the Gemini judge and is reachable in our own environment, which makes it a practical substitute for the paper's circularity check. We have not run this yet. It is the first thing to do before trusting the absolute scores or gating anything on them.

## Reproducing this

The spike code and every artifact live under `spike/`: the pipeline, the reconstructed judge, the real `tools/list` we captured, all stage outputs, the discrimination results, the enriched re-run, and the capability matrix. Running it needs `gcloud` application-default credentials, Python 3, and the Go toolchain (only to re-pull the spec). The pipeline regenerates stages 1 through 3, and the discrimination script runs the correct-versus-broken proof with the optional second judge. Every score in this post is a live model output saved alongside the code, not a hand-entered figure.

## Files in this reproduction

- `README.md` — this write-up.
- `paper-analysis.md` — the closer reading of Agent Seer and how its method maps onto our generative-media MCP servers.
- `spike-result.md` — the go/no-go result, with the full discrimination and enrichment numbers.
- `spike/` — the reproduction code and artifacts:
  - `agent_seer_spike.py` — the four-stage pipeline (ingest spec, interpret, generate scenarios, mock outputs).
  - `discrimination_test.py` — the correct-versus-broken transcript proof.
  - `judge.py`, `scoring.py`, `prompts.py` — the reconstructed tool-calling and coherence judge, aggregation, and prompt provenance.
  - `gemini_client.py` — the Vertex `generateContent` client.
  - `seed_outputs.json` — the real `mcp-veo-go` response shape used to raise Stage-3 grounding.
  - `spike/README.md` — how to run it.
  - `spike/artifacts/` — the captured spec, every stage output, and all scores (`discrimination_results.json`, `discrimination_enriched.json`, `veo_model_capabilities.json`, and more).
