# Agent Seer (Option A) spike — result & go/no-go

**Server:** `mcp-veo-go` (Option A: orchestration-correctness, not media quality)
**Paper:** Agent Seer, arXiv 2608.26133 (spec→scenario→mock-output→judge)
**Judge/generator:** Gemini 2.5 Flash (judge, temp 0) + Gemini 2.5 Flash Lite (generator, temp 0.7), via Vertex `generateContent`. Out-of-family spot-check: Gemini 2.5 Pro (see caveat).
**Code + artifacts:** `spike/` (pipeline, prompts, judge) and `spike/artifacts/` (every intermediate + all scores). This is throwaway validation work, not wired to CI, no app-repo PR.

---

## TL;DR — recommendation: **GO, but conditional**

The reimplemented judge produces **real, discriminating, non-degenerate signal** on veo's actual schema. It correctly separates good tool calls from broken ones (mean TC **1.000 correct vs 0.768 broken**, gap 0.232) and its failure taxonomy names the injected fault in **7/9** broken cases.

**But the load-bearing finding is a caveat, not a green light on its own:** the judge is **blind to any constraint that is not expressed in `tools/list`.** veo's highest-value footguns — a model that silently rejects `generate_audio`, model-dependent aspect-ratio enums — live in the Go model registry (`SupportedVeoModels`), **not** in the tool schema the judge sees. So the primary judge gave a *perfect 1.000* to the single most realistic production bug in the set (a Veo-2.0 call requesting audio).

When I re-ran with veo's capability matrix added to the judge's context, that same bug dropped to **0.800** and the correct call stayed at **0.994** — clean discrimination restored. **The judge works; it just needs the constraints. Build it out only together with spec-enrichment / capability grounding (or pair it with the investigation's deterministic schema-contract tests, Alternative 1).**

---

## What I built (per §5e phases 1–3 + 6; 4–5 skipped as instructed)

1. **Ingest spec (phase 1).** Built `mcp-veo-go` and pulled real `tools/list` via a raw JSON-RPC stdio handshake → `artifacts/veo_tools_list.json`. 6 tools: `veo_t2v, veo_i2v, veo_first_last_to_video, veo_reference_to_video, veo_ingredients_to_video, veo_extend_video`.
2. **Stage 1 — Tool Interpretation.** Paper's Appendix D.1 prompt verbatim, per tool → `artifacts/stage1_interpretations.json`.
3. **Stage 2 — Scenario Generation.** Paper's D.2 simple + complex prompts verbatim, incl. the coverage suffix → **15 scenarios (6 simple, 9 complex), full tool coverage (0 uncovered)** → `artifacts/stage2_scenarios.json`.
4. **Stage 3 — Mock Outputs.** Paper's D.3 prompt verbatim, **seeded with the real `mcp-veo-go` success-response shape** (text block + `resource_link` per video, derived from `video_logic.go` + `smoke_generate_and_verify.sh`) → grounding tiers came back **high×16 / medium×3** rather than the paper's all-`low`. `artifacts/stage3_mock_outputs.json`, seed in `spike/seed_outputs.json`.
5. **Judge (phase 6).** Reimplemented the TC (4 dims / 14 sub-dims, 0–10) and Coherence (5 dims, 1–3) rubrics from Tables 18/19, **including the cascading-penalty footnote** (wrong name / missing required → zero value+type+format; wrong value → cascade to type+format+relevancy). Aggregation per §4/App. E (`spike/scoring.py`). Prompt provenance is documented in `spike/prompts.py`: stages 1–4 are verbatim; the judge prompts are faithful reconstructions of the published rubric (the paper does not print the judge prompt as a verbatim block).
6. **Robustness spot-check (phase 6, optional).** Re-scored every case with Gemini 2.5 Pro.

## The actual validation — does the judge discriminate good vs broken? (phase 5)

11 hand-authored transcripts on veo's real schema: 2 correct + 9 deliberately broken, each injecting a distinct, documented failure class. Full data: `artifacts/discrimination_results.json`.

| case | kind | TC (Flash) | TC (Pro) | failures named | injected fault |
|---|---|---|---|---|---|
| A0-correct | correct | **1.000** | 1.000 | – | – |
| A1-wrong-model-value | broken | **1.000** ⚠️ | 0.839 | – (missed by Flash) | Veo-2.0 rejects `generate_audio=true` |
| A2-illegal-enum | broken | 0.956 | 0.867 | argument_value | `aspect_ratio: 21:9` unsupported |
| A3-hallucinated-model | broken | 0.822 | 0.822 | argument_value | model ID not in spec |
| A4-missing-required | broken | 0.722 | 0.778 | argument_completeness | omit required `prompt` |
| A5-wrong-tool | broken | 0.444 | 0.494 | selection, argument_value | `veo_i2v` with no image |
| A6-wrong-param-names | broken | 0.667 | 0.794 | name+value+type+format+relevancy | `ratio`/`gcs_bucket` not in schema |
| B0-correct | correct | **1.000** | 1.000 | – | – |
| B1-wrong-tool | broken | 0.656 | 0.500 | selection | `veo_t2v` ignoring provided image |
| B2-missing-required-image | broken | 0.778 | 0.794 | completeness+value+type+format | omit required `image_uri` |
| B3-malformed-uri | broken | 0.867 | 0.911 | value+type+format | `image_uri: "in.png"` (not gs://) |

- **mean TC: correct 1.000 vs broken 0.768 (gap 0.232); taxonomy hits 7/9.**
- **Strong, correct signal** for structural errors the schema *can* express: missing required field, wrong parameter names (full cascade fired), wrong-tool selection — all scored low with the right taxonomy.
- **The two misses (A1, A2)** are exactly the cases whose violated constraint is **absent from `tools/list`**: model↔audio compatibility, and model-dependent aspect-ratio (the schema literally says "supported aspect ratios are model-dependent" and lists no enum). The judge cannot penalize what it cannot see. The out-of-family judge (Pro) caught A1 (0.839), confirming this is an information/prompt gap, not noise.

### Enrichment re-run (the fix, `artifacts/discrimination_enriched.json`)

Adding veo's capability matrix (from `SupportedVeoModels`) to the judge context:

| case | TC before | TC enriched |
|---|---|---|
| A0-correct | 1.000 | 0.994 |
| A1-wrong-model-value | **1.000** | **0.800** ✅ |
| A2-illegal-enum | 0.956 | **0.789** ✅ |
| A3-hallucinated-model | 0.822 | 0.800 |

Clean separation restored. This is the concrete lever for a real build.

## Judgment calls on the investigation's unresolved questions

- **Agent-under-test (Q2, unresolved).** I did **not** stand up a live agent-under-test (Gemini CLI / function-calling loop) — that runner is the piece the paper *describes but does not provide* (§3.5) and is phase-5 work explicitly out of this spike. I authored the transcripts directly so the spike isolates the **judge's** discriminating power from runner-integration risk. A full build swaps in a real agent's emitted calls; the judge is unchanged. This is the right spike-level choice; the runner is the main *additional* cost of productionizing.
- **Mock-output grounding (unresolved).** I seeded Stage 3 with the **real** veo success-response shape (resource_link + GCS text), lifting grounding to **high/medium** vs the paper's uniform `low`. Cheap and worth it; genmedia responses are simple and stable.
- **Judge circularity.** Only a same-family second judge (Gemini 2.5 Pro) was available — **not** a true out-of-family check (the paper uses Qwen3.5, which I have no access to here). Pro largely agreed and, notably, *caught* the A1 case Flash missed, but same-family agreement does not rule out shared blind spots. A real build should include a genuinely out-of-family judge before trusting absolute numbers.

## Is it worth building out further? (go/no-go)

**Yes, conditionally — and the condition is the whole point.**

- The Agent Seer method **transfers cleanly** to genmedia orchestration: spec-driven scenario generation gave full tool coverage with no curation, and the decomposed rubric surfaces the argument-level errors coarse name-match metrics miss — exactly the veo footgun profile.
- **Do not ship the judge spec-only.** On its own it silently passes the highest-value genmedia bugs (model/feature incompatibility, model-dependent enums) because those constraints aren't in `tools/list`. That is a false-confidence failure worse than no test.
- **Recommended shape if pursued:**
  1. **Enrich the spec fed to generator+judge** with the capability matrix already in `mcp-common/models.go` (validated above to fix the misses). Low effort, high leverage.
  2. **Pair with deterministic schema-/capability-contract checks** (investigation's Alternative 1) as a cheap, non-LLM floor for the constraints that *are* machine-checkable; reserve the LLM judge for selection/ordering/value-grounding that isn't.
  3. **Then** invest in the phase-5 agent-under-test runner (the real integration cost) and a true out-of-family judge before trusting scores or gating CI.
- **Sizing:** this remains architect-worthy standing infra *only if* committing across servers + CI. As-is it's a validated one-server spike. The signal justifies the next step; it does not justify skipping enrichment.

## Verification / gates run

- Built `mcp-veo-go` (`go build`, clean) to obtain the real spec; ran it to capture `tools/list`.
- Ran the full pipeline end-to-end (stages 1–3, 15 scenarios) — completed rc=0.
- Ran the discrimination test (11 cases × 2 judges) + enrichment re-run — completed rc=0; all scores are live Gemini outputs saved under `artifacts/`.
- Not run: app-repo unit tests / CI (out of scope — spike is standalone scratchpad code, deliberately not wired to the repo). No out-of-family (non-Google) judge available in this environment.
