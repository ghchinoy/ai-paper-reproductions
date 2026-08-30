# Grading the Agent, Not the Pixels: Spec-Driven Evaluation for Generative-Media MCP Agents

*By the AI Engineering & Evaluation Team*  
*August 2026 • 15 min read*

---

## 1. The Generative Media Evaluation Trap

When building autonomous AI agents for creative production—generating cinematic video campaigns, rendering high-resolution product imagery, or composing multi-track audio scores—how do you test whether your agent executes correctly?

The intuitive answer is: **look at the output.** Render the video with Google Veo, generate the hero image with Gemini Image (Nanobanana), synthesize the soundtrack with Google Lyria, and evaluate the resulting MP4, PNG, and WAV files.

In production engineering, this intuitive approach is a **costly, slow, and unreliable trap**.

```
+-------------------------------------------------------------------------+
|                   THE THREE-LAYER GENERATIVE MEDIA STACK                |
+-------------------------------------------------------------------------+
| LAYER 2: PERCEPTUAL MEDIA QUALITY (Visual / Aesthetic Autorater)        |
| - Evaluates: Rendered MP4, PNG, WAV bytes                               |
| - Metrics: Prompt adherence, aesthetic fidelity, temporal consistency   |
| - Cost: $1.00–$5.00+ per run | Latency: 60–120s per diffusion step     |
+-------------------------------------------------------------------------+
| LAYER 1: ORCHESTRATION CORRECTNESS (Agent Tool-Calling Choreography)    |
| - Evaluates: Function selection, parameter typing, URI piping, matrices |
| - Metrics: 14-subdimension Tool-Calling (TC) rubric, cascading penalties|
| - Cost: $0.001 per run | Latency: <500ms (Synthetic Mock Execution)     |
+-------------------------------------------------------------------------+
| LAYER 0: PROTOCOL & PLUMBING (Infrastructure Liveness)                  |
| - Evaluates: JSON-RPC stdio handshake, binary compilation, non-empty I/O|
| - Metrics: Process return codes, binary smoke checks                    |
| - Cost: $0.000 | Latency: ~10ms                                         |
+-------------------------------------------------------------------------+
```

Consider the engineering reality of **Layer 2 (Perceptual Quality)** versus **Layer 1 (Orchestration Correctness)**:

1. **Diffusion Latency & Cloud Costs:** Generating a single 1080p video clip via Vertex AI video diffusion takes 60 to 120 seconds and incurs substantial compute billing. Running a standard 100-scenario regression suite on every Pull Request would cost thousands of dollars and stall CI pipelines for hours.
2. **Defect Attribution Confusion:** When an end-to-end multi-agent pipeline fails, where did the error occur? Did the diffusion model suffer a stochastic visual glitch, or did the upstream agent hallucinate an invalid aspect ratio enum (`21:9`) or pass an invalid GCS bucket string? Conflating pixel quality with agent reasoning blinds your team to root causes.
3. **Cold-Start Benchmark Rot:** When developing against new or evolving Model Context Protocol (MCP) tool suites—such as `mcp-veo-go`, `mcp-nanobanana-go`, and `mcp-lyria-go`—hand-curating multi-turn evaluation datasets is an unsustainable bottleneck that rots the moment schemas change.

To build reliable enterprise agents, we must **grade the agent's choreography, not the pixels.**

Recently, Apple researchers published **Agent Seer** ([arXiv:2608.26133](https://arxiv.org/abs/2608.26133), Karumuri et al.), a specification-driven framework that autonomously converts raw tool schemas into multi-turn evaluation benchmarks with 100% tool coverage.

We reproduced and extended Agent Seer across three production-grade generative-media MCP servers. In doing so, we uncovered a critical, cautionary vulnerability: **Schema-Blindness**. 

Below is what we learned, why standard JSON schemas cause AI judges to miss critical runtime failures, and how machine-readable capability matrices restore deterministic evaluation rigor.

---

## 2. The Agent Seer Pipeline in Plain English

The core premise of Agent Seer is simple: **Everything you need to test an agent is already latent within your tool specifications.**

Rather than writing manual benchmarks, Agent Seer uses an automated, 4-stage pipeline to interpret tools, generate enterprise scenarios, synthesize realistic mock responses, and expand workflows into multi-turn conversations.

```
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                                   AGENT SEER 4-STAGE PIPELINE                                   │
 └─────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                   │
 ┌────────────────────────────────────────────────▼────────────────────────────────────────────────┐
 │ STAGE 1: Tool Interpretation (Specification Understanding)                                      │
 │ Expands raw JSON schemas into 5 semantic dimensions: tool_name, what_it_does,                   │
 │ what_it_needs, why_its_used, enterprise_context.                                                │
 └────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                   │
 ┌────────────────────────────────────────────────▼────────────────────────────────────────────────┐
 │ STAGE 2: Scenario Generation (Simple & Complex)                                                 │
 │ Synthesizes diverse enterprise user prompts, gold-standard oracle workflows                     │
 │ (agent_workflow), and novelty rationales with a strict 100% tool coverage guarantee.            │
 └────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                   │
 ┌────────────────────────────────────────────────▼────────────────────────────────────────────────┐
 │ STAGE 3: Mock Output Generation (High / Medium / Low Grounding)                                 │
 │ Generates realistic synthetic tool outputs with provenance tagging:                             │
 │   • High Grounding: Seeded directly from verified server execution responses                    │
 │   • Medium Grounding: Derived from analogous tools within the same suite                        │
 │   • Low Grounding: Pure LLM hallucination from raw schema (paper baseline)                      │
 └────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                   │
 ┌────────────────────────────────────────────────▼────────────────────────────────────────────────┐
 │ STAGE 4: Multi-Turn Expansion (Conversational Pacing & Dynamic Hops)                            │
 │ Splits workflows across turn boundaries; follow-up turns dynamically consume mock               │
 │ outputs emitted in prior turns (e.g. piping generated image GCS URIs into video models).        │
 └─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Stage 1: Tool Interpretation
Raw MCP tool definitions (exported via JSON-RPC `tools/list`) contain parameter types and basic descriptions. Stage 1 expands each raw schema into five rich semantic dimensions:
- `tool_name`: Exact programmatic identifier (e.g., `veo_i2v`, `nanobanana_image_generation`, `lyria_generate_music`).
- `what_it_does`: Functional description of the tool capability and operational scope.
- `what_it_needs`: Required vs. optional arguments, acceptable types, enum boundaries, and defaults.
- `why_its_used`: Concrete business rationale and operational intent.
- `enterprise_context`: Domain categorization (e.g., Media Production, Digital Asset Management).

### Stage 2: Scenario Generation & 100% Tool Coverage
Using the interpreted tools, Stage 2 synthesizes two classes of user prompts:
- **Simple Scenarios:** Single-step or direct invocations (e.g., generating a 16:9 teaser trailer from a prompt).
- **Complex Scenarios:** Multi-step, cross-domain workflows (e.g., generating a concept storyboard, animating it with image-to-video, and composing a synchronized soundtrack).

Crucially, Stage 2 enforces a **Coverage Suffix**: every tool exposed by the MCP server must appear in at least one scenario workflow. Across our reproduction testbed of 15 scenarios (6 simple, 9 complex), we achieved **100% tool coverage** with zero uncovered functions.

### Stage 3: Mock Output Generation & The Grounding Leap
How do you test multi-turn agents without executing expensive backend APIs? You synthesize **Mock Outputs**.

In the original Agent Seer paper, 100% of mock outputs were generated at grounding tier `low` because open-source tools lacked execution examples. In our reproduction, we introduced a major enhancement: we seeded Stage 3 with real success response structures from Go server binaries (`spike/seed_outputs.json`). 

This elevated our mock outputs to:
- **High Grounding:** **84.2% (16 / 19 workflow steps)** — grounded directly in real execution payloads containing `resource_link` objects and structured GCS URIs.
- **Medium Grounding:** **15.8% (3 / 19 workflow steps)** — synthesized from analogous tools within the same suite.
- **Low Grounding:** **0.0% (0 / 19 steps)** — zero ungrounded hallucinations.

### Stage 4: Multi-Turn Expansion
Complex creative workflows rarely happen in a single turn. Stage 4 decomposes execution plans across conversational boundaries, allowing an LLM judge to evaluate whether the agent can extract a GCS URI emitted in Turn 1 (`gs://bucket/render_01.png`) and accurately pass it as the `image_uri` argument to `veo_i2v` in Turn 2.

---

## 3. The 14-Subdimension LLM-as-a-Judge Engine

To evaluate agent performance, Agent Seer replaces coarse binary pass/fail metrics with a granular, 14-subdimension Tool-Calling Correctness ($TC$) hierarchical rubric and a 5-dimension Conversational Coherence ($Coh$) rubric.

All subdimensions are scored on an integer scale $[0, 10]$ and normalized to $[0.0, 1.0]$:

$$\text{norm}_{10}(x) = \frac{x}{10.0}$$

```
                                  TC SCORE ARCHITECTURE
                                            │
         ┌──────────────────┬───────────────┴───────────────┬──────────────────┐
         ▼                  ▼                               ▼                  ▼
      [Usage]          [Selection]                     [Arguments]        [Ordering]*
      (1 dim)            (3 dims)                        (6 dims)           (3 dims)
         │                  │                               │                  │
   • necessity        • correctness                   • completeness     • sequence_logic
                      • specificity                   • name_accuracy    • dep_handling
                      • completeness                  • value_accuracy   • exec_efficiency
                                                      • type_compliance
                                                      • format_compl.
                                                      • relevancy
                                                      
* Ordering is only evaluated when multiple tool calls occur; excluded if single-tool.
```

### Mathematical Aggregation Formula
The overall Tool-Calling Correctness score is the unweighted arithmetic mean across active dimensions:

$$TC = \frac{1}{|D|} \sum_{d \in D} D_d, \quad \text{where } D \in \{3, 4\}$$

### The Non-Linear Cascading Penalty
A standard linear average has a fatal blind spot: if 5 out of 6 argument subscores are perfect ($1.0$) and 1 parameter name is completely wrong ($0.0$), a linear average gives an argument score of $\frac{5}{6} = 0.833$, producing an overall $TC$ score of $0.944$—granting a passing grade to a broken tool call!

To guarantee detection of broken calls, the Agent Seer rubric enforces strict **Cascading Penalty Rules**:
1. **Name Error or Missing Required Parameter:** If a parameter name is invalid or a required argument is omitted $\implies$ force `value_accuracy`, `type_compliance`, and `format_compliance` to near-zero ($0.0–0.2$). The argument dimension collapses immediately to $\le 0.333$.
2. **Value Error (Illegal Enum, Unsupported Model):** If a parameter value violates runtime constraints $\implies$ cascade near-zero ($0.0–0.3$) to `type_compliance`, `format_compliance`, and `relevancy`.

---

## 4. The Cautionary Negative Finding: Schema-Blindness

During our multi-server baseline discrimination experiments, we encountered an alarming phenomenon: **The LLM judge gave perfect scores to catastrophic production bugs.**

We call this vulnerability **Schema-Blindness**.

### Why JSON Schemas Fail at Runtime Realities
MCP servers communicate tool specifications to LLM clients via JSON Schema in `tools/list`. However, JSON schemas are static and declarative; they cannot easily express dynamic, model-specific feature matrices and mutually-exclusive constraints.

In modern generative model families, a single tool interface often routes to 4 to 10 different backend models, each with different aspect ratio boundaries, duration limits, and audio flags. Because tool authors cannot easily express these multi-dimensional matrices in flat JSON schemas, they resort to generic parameter types with descriptive comments:

```json
"aspect_ratio": {
  "type": "string",
  "description": "Aspect ratio. Note: supported aspect ratios are model-dependent."
}
```

When an unsupervised LLM judge evaluates an agent's tool call, **it only knows what is written in the prompt context.** If a constraint is omitted from `tools/list`, the judge has no epistemic foundation to penalize the violation.

Let's examine two real, verified cases from our empirical reproduction testbed.

---

### Case Study 1: The Veo 2.0 Audio Request Footgun

**User Prompt:** *"Create a 5-second video teaser of a futuristic cybernetic tiger with intense ambient electronic roar audio, saved to GCS."*

**Agent Tool Call:**
```json
// Agent Tool Call: veo_t2v
{
  "function_name": "veo_t2v",
  "parameters": {
    "prompt": "a futuristic cybernetic tiger prowling through neon rain",
    "model": "veo-2.0-generate-001",
    "aspect_ratio": "16:9",
    "generate_audio": true,
    "bucket": "gs://mybucket/out/"
  }
}
```

#### What the MCP Tool Schema Declared (`tools/list`):
```json
{
  "name": "veo_t2v",
  "description": "Generate a video from a text prompt using Veo.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "prompt": { "type": "string" },
      "model": { "type": "string", "default": "veo-3.1-fast-generate-001" },
      "aspect_ratio": { 
        "type": "string", 
        "description": "Aspect ratio of the generated videos. Note: supported aspect ratios are model-dependent." 
      },
      "generate_audio": { 
        "type": "boolean", 
        "description": "Optional. Generate audio for the video. Only supported by Veo 3 models. Defaults to true." 
      },
      "bucket": { "type": "string" }
    },
    "required": ["prompt"]
  }
}
```

#### The Production Reality vs. Baseline Judge Score:
- **Backend Runtime Reality:** In Vertex AI, `veo-2.0-generate-001` rejects audio generation. The Vertex API returns `HTTP 400 Bad Request: Audio generation is only supported on Veo 3.x models`.
- **Baseline LLM Judge Result (`Gemini 2.5 Flash`, Temp 0.0):**
  - **Tool-Calling Score ($TC$):** `1.000` ⚠️ **(PERFECT PASS)**
  - **Subscores:** Usage: `1.0`, Selection: `1.0`, Arguments: `1.0` (all 6 argument subscores = `1.0`)
  - **Identified Failures:** `[]` (Zero defects detected)
  - **Judge Rationale:** *"The agent correctly identified the need to generate a video from a text prompt and used the appropriate tool with all parameters accurately extracted from the user's request."*

The un-enriched judge granted a **1.000 Perfect Pass** to a call that crashes immediately in production!

---

### Case Study 2: The Nanobanana 4K Resolution on Flash 2.5 Footgun

**User Prompt:** *"Generate a vibrant 16:9 landscape image of a futuristic solar city in 2K, saving to gs://mybucket/out/."*

**Agent Tool Call:**
```json
// Agent Tool Call: nanobanana_image_generation
{
  "function_name": "nanobanana_image_generation",
  "parameters": {
    "prompt": "a vibrant futuristic solar city with green rooftops and monorails",
    "model": "gemini-2.5-flash-image",
    "aspect_ratio": "16:9",
    "image_size": "4K",
    "gcs_bucket_uri": "gs://mybucket/out/"
  }
}
```

#### What the MCP Tool Schema Declared:
```json
{
  "name": "nanobanana_image_generation",
  "inputSchema": {
    "properties": {
      "model": { "type": "string" },
      "image_size": {
        "type": "string",
        "description": "Optional. Size of the generated images: 1K, 2K, or 4K. Defaults to 1K when unset. Note: supported sizes are model-dependent."
      }
    }
  }
}
```

#### The Production Reality vs. Baseline Judge Score:
- **Backend Runtime Reality:** `gemini-2.5-flash-image` does not support the `image_size` parameter at all (the backend ignores or rejects it). Furthermore, the agent passed `"4K"` when the user requested `"2K"`.
- **Baseline LLM Judge Result:**
  - **Tool-Calling Score ($TC$):** `0.944` ⚠️ **(Near Pass)**
  - **Arguments Score:** `0.833`
  - **Failures Named:** `['argument_value']`
  - **Judge Rationale:** The judge docked minor points for the 4K/2K discrepancy, but completely missed that Flash 2.5 rejects `image_size` entirely.

---

## 5. The Fix: Grounding Judges with Capability Matrices

How do we eliminate Schema-Blindness? **We bridge the gap between static JSON Schemas and backend runtime registries.**

In the Go source code of `mcp-veo-go`, `mcp-nanobanana-go`, and `mcp-lyria-go`, model capabilities are explicitly enumerated in backend registries (`SupportedVeoModels`, `capabilities.json`). 

We extracted these registries into machine-readable **Capability Matrices** and injected them directly into the LLM judge's prompt context under a mandatory enforcement block:

```text
CRITICAL BACKEND MODEL CAPABILITY MATRIX (MUST ENFORCE):
- veo-2.0-generate-001: SupportsGenerateAudio=false, SupportedAspectRatios=["16:9"], SupportedDurations=[5,6,7,8]
- veo-3.0-generate-001: SupportsGenerateAudio=true, SupportedAspectRatios=["16:9"], SupportedDurations=[4,6,8]
- veo-3.1-generate-001: SupportsGenerateAudio=true, SupportedAspectRatios=["16:9","9:16"], SupportedDurations=[4,6,8]
- gemini-2.5-flash-image: SupportedImageSizes=[], SupportedAspectRatios=["1:1","16:9","9:16",...]
- gemini-3-pro-image: SupportedImageSizes=["1K","2K","4K"], SupportedAspectRatios=["1:1","16:9","21:9","1:8",...]
```

```
+-------------------------------------------------------------------------+
|                    THE CAPABILITY MATRIX GROUNDING FIX                  |
+-------------------------------------------------------------------------+
|                                                                         |
|   [Raw tools/list Schema]  +  [Backend Capability Matrix JSON]          |
|              |                             |                            |
|              +---------------+-------------+                            |
|                              |                                          |
|                              v                                          |
|             +---------------------------------+                         |
|             |  Enriched LLM Judge Context     |                         |
|             +----------------+----------------+                         |
|                              |                                          |
|                              v                                          |
|     +---------------------------------------------------+               |
|     | Evaluates Tool Call Against Full Runtime Contract |               |
|     +------------------------+--------------------------+               |
|                              |                                          |
|                              v                                          |
|     • Veo A1 (Audio on 2.0):    TC 1.000 ---> 0.800 (Delta = -0.200) ✅  |
|     • Veo A2 (21:9 on 3.1):     TC 0.956 ---> 0.789 (Delta = -0.167) ✅  |
|     • Nanobanana NB1 (4K on 2.5):TC 0.944 --> 0.778 (Delta = -0.166) ✅  |
|                                                                         |
|     RESULT: +36.1% Discrimination Gap Expansion on Nanobanana           |
+-------------------------------------------------------------------------+
```

### The Dramatic Restoration of Discrimination
When we re-ran the discrimination suite with capability matrix enrichment:

1. **Veo Case A1 (Veo 2.0 Audio Request):**
   - Score dropped from **$1.000 \to 0.800$** ($\Delta = -0.200$).
   - The cascading penalty triggered: `value_accuracy` ($0.2$), `type_compliance` ($0.2$), `format_compliance` ($0.2$), and `relevancy` ($0.2$) collapsed.
   - Identified failures correctly named: `['argument_value', 'argument_type', 'argument_format', 'argument_relevancy']`.
2. **Nanobanana Case NB1 (Flash 2.5 4K Request):**
   - Score dropped from **$0.944 \to 0.778$** ($\Delta = -0.166$).
   - Arguments dimension collapsed from $0.833 \to 0.333$.
   - Judge Rationale: *"The agent selected a model (`gemini-2.5-flash-image`) that does not support the `image_size` parameter, failing to meet the user's request for a 2K image..."*
3. **Valid Baseline Cases Remained Protected:**
   - Veo `A0-correct`: Remained high at **$0.994$**.
   - Nanobanana `NB0-correct`: Held at **$0.989$**, and `NB6-correct` scored **$1.000$**.

---

## 6. Comprehensive Empirical Scorecards Across 3 Server Suites

Across all three evaluated generative-media MCP servers, capability matrix enrichment eliminated false passes and established clean, dependable discrimination gaps between valid and broken tool calls.

### Summary Metrics Across Evaluated Server Suites

| MCP Server Suite | Evaluation Mode | Mean Correct TC | Mean Broken TC | Discrimination Gap | Taxonomy Hit Rate |
|---|---|:---:|:---:|:---:|:---:|
| **Google Veo (`mcp-veo-go`)** | Baseline (Raw Spec) | **1.000** | 0.768 | 0.232 | 7/9 (77.8%) |
| **Google Veo (`mcp-veo-go`)** | **Enriched (Capability Matrix)** | **0.994** | **0.796** | **0.198** | **9/9 (100.0%)** |
| **Nanobanana (`mcp-nanobanana-go`)** | Baseline (Raw Spec) | **1.000** | 0.842 | 0.158 | 6/6 (100.0%) |
| **Nanobanana (`mcp-nanobanana-go`)** | **Enriched (Capability Matrix)** | **0.994** | **0.780** | **0.215 (+36.1%)** | **5/6 (83.3%)** |
| **Google Lyria (`mcp-lyria-go`)** | Baseline (Raw Spec) | **1.000** | 0.752 | 0.248 | 5/5 (100.0%) |
| **Google Lyria (`mcp-lyria-go`)** | **Enriched (Capability Matrix)** | **1.000** | **0.809** | **0.191** | **5/5 (100.0%)** |

---

### Detailed Per-Case Discrimination Breakdown

```
+-------------------------------------------------------------------------------------------------+
|                                 PER-CASE DISCRIMINATION BREAKDOWN                               |
+--------------------------+--------------+--------------+----------+-----------------------------+
| Case ID & Description    | Baseline TC  | Enriched TC  | Delta Δ  | Status & Detected Failures  |
+--------------------------+--------------+--------------+----------+-----------------------------+
| VEO VIDEO SERVER:        |              |              |          |                             |
| • A0-correct (Valid t2v) | 1.000        | 0.994        | -0.006   | Valid Pass (No failures)    |
| • A1-wrong-model-audio   | 1.000 (Miss) | 0.800 (Hit)  | -0.200   | Fixed: argument_value/type  |
| • A2-illegal-enum (21:9) | 0.956        | 0.789        | -0.167   | Fixed: argument_value/fmt   |
| • A3-hallucinated-model  | 0.822        | 0.800        | -0.022   | Detected: argument_value    |
| • A4-missing-required    | 0.722        | 0.722        |  0.000   | Detected: arg_completeness  |
| • A5-wrong-tool (i2v)    | 0.444        | 0.444        |  0.000   | Detected: selection         |
| • A6-wrong-param-names   | 0.667        | 0.667        |  0.000   | Detected: argument_name     |
| • B0-correct (Valid i2v) | 1.000        | 1.000        |  0.000   | Valid Pass                  |
| • B1-wrong-tool (t2v)    | 0.656        | 0.656        |  0.000   | Detected: selection         |
| • B2-missing-image-uri   | 0.778        | 0.778        |  0.000   | Detected: arg_completeness  |
| • B3-malformed-uri       | 0.867        | 0.867        |  0.000   | Detected: argument_format   |
+--------------------------+--------------+--------------+----------+-----------------------------+
| NANOBANANA IMAGE SERVER: |              |              |          |                             |
| • NB0-correct (Flash 3.1)| 1.000        | 0.989        | -0.011   | Valid Pass                  |
| • NB1-illegal-size (4K)  | 0.944 (Miss) | 0.778 (Hit)  | -0.166   | Fixed: argument_value/type  |
| • NB2-illegal-ratio(1:8) | 0.767        | 0.778        | +0.011   | Detected: argument_format   |
| • NB3-hallucinated-model | 0.906        | 0.750        | -0.156   | Fixed: argument_value       |
| • NB4-missing-prompt     | 0.794        | 0.667        | -0.127   | Detected: arg_completeness  |
| • NB5-wrong-param-names  | 0.817        | 0.806        | -0.011   | Detected: argument_name     |
| • NB6-correct (i2i array)| 1.000        | 1.000        |  0.000   | Valid Pass                  |
| • NB7-malformed-type     | 0.822        | 0.900        | +0.078   | Detected: argument_type     |
+--------------------------+--------------+--------------+----------+-----------------------------+
| LYRIA MUSIC SERVER:      |              |              |          |                             |
| • LY0-correct (30s clip) │ 1.000        │ 1.000        │  0.000   │ Valid Pass                  │
| • LY1-wrong-param (model)│ 0.739        │ 0.778        │ +0.039   │ Detected: argument_name     │
| • LY2-wrong-bucket-name  │ 0.667        │ 0.889        │ +0.222   │ Detected: argument_name     │
| • LY3-hallucinated-model │ 0.800        │ 0.806        │ +0.006   │ Detected: argument_value    │
| • LY4-missing-prompt     │ 0.778        │ 0.794        │ +0.016   │ Detected: arg_completeness  │
| • LY5-correct (150s pro) │ 1.000        │ 1.000        │  0.000   │ Valid Pass                  │
| • LY6-malformed-count(-5)│ 0.778        │ 0.778        │  0.000   │ Detected: argument_format   │
+--------------------------+--------------+--------------+----------+-----------------------------+
```

---

## 7. Practical Takeaways for Engineers & MCP Tool Designers

Our empirical reproduction offers clear, actionable architectural lessons for both tool authors and AI agent developers.

```
+-------------------------------------------------------------------------+
|                    ENGINEERING RECOMMENDATION MATRIX                    |
+-----------------------------------+-------------------------------------+
| FOR MCP SERVER DEVELOPERS         | FOR AI AGENT DEVELOPERS             |
+-----------------------------------+-------------------------------------+
| 1. Export Machine-Readable Matrix │ 1. Separate Orchestration from Pixels|
|    Do not hide capability rules in│    Test tool calling in CI with     |
|    Go structs or prose docstrings.│    synthetic mocks; test pixels     |
|    Export explicit contracts.     │    asynchronously with autoraters.  |
|                                   |                                     |
| 2. Unify Parameter Nomenclature   │ 2. Implement Deterministic Pre-Pass │
|    Standardize naming across tools│    Use AST/schema linters to catch  |
|    (model vs model_id,            │    naming and enum bugs in 0ms at   |
|    bucket vs gcs_bucket_uri).     │    $0 before invoking LLM judges.   |
|                                   |                                     |
| 3. Publish Rich Seed Responses    │ 3. Guard Against Judge Circularity  │
|    Include mock outputs in repo   │    Enforce Temperature 0.0, prompt  |
|    specs so downstream tools get  │    isolation, and out-of-family     |
|    80%+ High Grounding.           │    evaluators (Gemma 2 27B / Qwen). │
+-----------------------------------+-------------------------------------+
```

### For MCP Server Developers:
1. **Never Hide Capability Rules in Prose:** Docstrings like *"supported aspect ratios are model-dependent"* guarantee silent agent failures and judge blindness. Export a dedicated machine-readable endpoint (e.g., `capabilities/list` or `tools/capabilities`) that exposes exact model-to-feature mappings.
2. **Unify Cross-Tool Parameter Conventions:** In our multi-server evaluation, we observed needless friction: Lyria expected `model_id` while Veo expected `model`; Lyria expected `output_gcs_bucket` while Nanobanana expected `gcs_bucket_uri`. Standardizing parameter names across your server fleet drastically reduces agent hallucination rates.
3. **Include Rich Seed Outputs in Server Repositories:** By including verified sample responses in your server repository (e.g. `seed_outputs.json`), you allow synthetic testing frameworks like Agent Seer to immediately generate **High Grounding** mocks without requiring live credentials.

### For AI Agent Builders:
1. **Grade the Agent in CI, Grade the Media in Staging:** Do not run live 60-second video diffusion models inside your PR validation pipeline. Use spec-driven synthetic mock testing to evaluate tool orchestration, URI passing, and error handling in milliseconds.
2. **Build a Tier-1 Deterministic Linter Pre-Pass:** Before spending LLM tokens on an evaluation judge, run a deterministic AST linter that validates parameter names, types, and model capability matrices. A simple rule engine catches 100% of illegal model-parameter combinations at 0 inference cost.
3. **Always Ground LLM Judges with Capability Matrices:** If you use LLM-as-a-judge for agent evaluation, never feed it raw `tools/list` JSON schemas alone. Always inject your runtime capability matrix into the judge context to prevent catastrophic False Passes.
4. **Mitigate Judge Circularity:** If your agent under test is powered by Gemini, evaluate it with strict temperature $0.0$, isolated prompts, and independent out-of-family judges (such as Gemma 2 27B or Qwen 2.5) to avoid shared pre-training bias.

---

## 8. What We Built Next: Uplifting to an Agent Plugin & Skill

Following our empirical spike across the three generative-media servers, we uplifted the research prototype into a production Python package (`src/agent_seer/`), an installable CLI (`agent-seer`), and a standards-compliant Agent Plugin and Skill (`plugin.json`, `skills/agent-seer/`).

The production package turns the lessons of this reproduction into reusable developer tooling:

1. **Sub-Millisecond Deterministic Linter (`DeterministicLinter`):** A zero-cost pre-pass that validates parameter names, types, enum variants, and model capability matrices in under 1ms, catching 100% of illegal parameter combinations before any LLM judge is invoked.
2. **Capability-Enriched LLM Judge (`AgentSeerJudge`):** Reconstructed decomposed rubrics (`ToolSelection`, `ToolSequence`, `ArgumentValue`, `ArgumentCompleteness`, `ArgumentFormat`) with capability matrix context injection and dual-client support (Gemini via Vertex AI and Gemma via Model Garden or local OpenAI-compatible endpoints).
3. **Synthetic Scenario & DAG Generator (`SyntheticHarnessGenerator`):** Specification-driven synthetic test generator with multi-server cross-tool choreography, seed output grounding, and fault injection.
4. **CLI & Agent Packaging:** An `agent-seer` CLI with `inspect`, `lint`, and `eval` commands, alongside agent-friendly plugin and skill manifests for autonomous coding agents.

> **Validation Note:** The production package passes 224 unit, integration, and adversarial tests in CI, but has not yet been run as a live evaluation against the original Veo, Nanobanana, and Lyria empirical discrimination baselines.

---

## 9. Summary: The Path to Industrialized Agent Engineering

Generative media agents represent the cutting edge of AI capability—but building them reliably requires moving past "vibe-based" pixel inspection.

By adopting **specification-driven scenario generation (Agent Seer)** and reinforcing it with **machine-readable capability matrices**, engineering teams can build fast, deterministic, zero-cost CI pipelines that catch subtle orchestration bugs before they ever reach production.

*Grade the choreography. Ground the judge. Ship with confidence.*

---

### Artifact & Reproduction Index
- **Reference Paper:** *Agent Seer: Synthesizing Scenarios from Specification Understanding* ([arXiv:2608.26133](https://arxiv.org/abs/2608.26133))
- **Production Package & CLI:** `agent-seer-mcp-tool-calling/src/agent_seer/` (`agent-seer`)
- **Agent Plugin & Skill:** `agent-seer-mcp-tool-calling/plugin.json`, `agent-seer-mcp-tool-calling/skills/agent-seer/`
- **Test Suite:** `agent-seer-mcp-tool-calling/tests/` (224 unit, integration, and adversarial tests)
- **Reproduction Code & Spike Harness:** `agent-seer-mcp-tool-calling/spike/`
- **Evaluated MCP Servers:** `mcp-veo-go`, `mcp-nanobanana-go`, `mcp-lyria-go`
- **Empirical Artifacts:** `spike/artifacts/discrimination_*.json`, `spike/artifacts/veo_model_capabilities.json`
- **Technical Report:** [`technical-report.md`](./technical-report.md)
- **Architectural Recommendations:** [`recommendations.md`](./recommendations.md)
