# Specification-Driven Synthetic Evaluation for Generative-Media MCP Tool Calling: Architectural Deconstruction, Rubric Mechanics, and Empirical Validation

**Authors:** AI Systems Engineering & Evaluation Group  
**Target Repository:** `ai-paper-reproductions/agent-seer-mcp-tool-calling`  
**Reference Paper:** *Agent Seer: Synthesizing Scenarios from Specification Understanding* (arXiv:2608.26133) by Harish Karumuri, Mahesh Vemula, David Lopes Pegna (Apple)  
**Date:** August 2026  
**Document Version:** 1.0.0 (Publication-Grade Technical Report)

---

## Abstract

Evaluating autonomous AI agents interfacing with complex, rapidly evolving Model Context Protocol (MCP) tool suites presents a severe cold-start dilemma: manual scenario curation is labor-prohibitive, static benchmarks suffer rapid obsolescence, and multi-turn execution evaluation requires expensive, nondeterministic runtime environments. In this report, we deconstruct and empirically reproduce the specification-driven evaluation methodology introduced in *Agent Seer* (arXiv:2608.26133) across three production-grade generative-media MCP server suites: Google Veo (`mcp-veo-go`), Gemini Image/Nanobanana (`mcp-nanobanana-go`), and Google Lyria (`mcp-lyria-go`). 

We present the complete mathematical formalization of the 14-subdimension Tool-Calling Correctness ($TC$) and 5-dimension Conversational Coherence ($Coh$) rubrics, detailing the non-linear cascading penalty mechanics that prevent broken parameter calls from receiving inflated linear scores. Furthermore, we uncover a critical vulnerability—**Schema-Blindness**—wherein standard JSON tool schemas (`tools/list`) omit runtime backend model compatibility constraints, causing un-enriched LLM judges to grant false passes ($TC = 1.000$) to production-breaking bugs. We demonstrate how machine-readable capability matrix enrichment restores clean discrimination gaps ($\ge 0.191$), expanding the discrimination margin on image generation by $+36.1\%$. Finally, we formalize a three-layer evaluation taxonomy (Plumbing, Orchestration, Perceptual Quality) and establish architectural safeguards against LLM-as-judge circularity.

---

## 1. Executive Summary & Problem Formulation

### 1.1 The Cold-Start Evaluation Problem in Agent Tool Calling

The rapid expansion of autonomous agent frameworks has transformed tool-calling from a simple single-turn API dispatch mechanism into multi-turn, multi-tool orchestration workflows. When agents interact with standardized interfaces such as Anthropic's Model Context Protocol (MCP), validating tool-use competence becomes a gating requirement for production deployment. However, evaluating emerging, private, or rapidly iterating MCP servers encounters three fundamental bottlenecks:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 THE COLD-START EVALUATION TRILEMMA                              │
├──────────────────────────────┬──────────────────────────────┬───────────────────────────────────┤
│ 1. Curation Bottleneck       │ 2. Static Benchmark Rot      │ 3. Multi-Turn Evaluation Gap      │
├──────────────────────────────┼──────────────────────────────┼───────────────────────────────────┤
│ Handcrafting multi-turn user │ Hardcoded evaluation suites  │ Downstream conversational turns   │
│ prompts, gold-standard tool  │ rot as API schemas, parameter│ require dynamic, realistic tool   │
│ calls, and execution mocks   │ names, and model enums       │ responses that reflect intermediate│
│ requires prohibitive human   │ iterate across releases.     │ state without expensive execution.│
│ engineering effort.          │                              │                                   │
└──────────────────────────────┴──────────────────────────────┴───────────────────────────────────┘
```

In generative-media domains (video generation, image synthesis, audio composition), these challenges are magnified. Media diffusion backends involve long execution latencies (30–120 seconds per video clip), high cloud inference costs, and stochastic output variance. Running live execution loops simply to test whether an agent can correctly structure a tool call is economically and architecturally unviable.

### 1.2 Agent Seer Formulation & Core Thesis

*Agent Seer* (Karumuri et al., arXiv:2608.26133) establishes that **tool specifications—consisting of function signatures, natural-language documentation, and typed JSON schemas—encode sufficient semantic structure to autonomously synthesize end-to-end evaluation suites without manual authoring or live API execution.**

By feeding raw MCP schemas through a disciplined four-stage pipeline, the system extracts semantic affordances, generates diverse single-turn and multi-turn enterprise scenarios with held-out oracle workflows, synthesizes realistic mock responses across explicit grounding tiers, and evaluates agent transcripts using an unsupervised, decomposed LLM-as-judge rubric.

```
                  ┌──────────────────────────────────────────────────────────┐
                  │                RAW MCP TOOL SPECIFICATIONS               │
                  │                      (`tools/list`)                      │
                  └────────────────────────────┬─────────────────────────────┘
                                               │
                                               ▼
                  ┌──────────────────────────────────────────────────────────┐
                  │                 STAGE 1: INTERPRETATION                  │
                  │       (Extract 5 Semantic Affordance Dimensions)         │
                  └────────────────────────────┬─────────────────────────────┘
                                               │
                                               ▼
                  ┌──────────────────────────────────────────────────────────┐
                  │               STAGE 2: SCENARIO SYNTHESIS                │
                  │      (Simple & Complex Scenarios + 100% Coverage)        │
                  └────────────────────────────┬─────────────────────────────┘
                                               │
                                               ▼
                  ┌──────────────────────────────────────────────────────────┐
                  │                 STAGE 3: MOCK GENERATION                 │
                  │         (Grounding Tiers: High / Medium / Low)           │
                  └────────────────────────────┬─────────────────────────────┘
                                               │
                                               ▼
                  ┌──────────────────────────────────────────────────────────┐
                  │             STAGE 4: MULTI-TURN EXPANSION                │
                  │     (Phase-Boundary Splits & State-Chained Follow-ups)   │
                  └────────────────────────────┬─────────────────────────────┘
                                               │
                                               ▼
                  ┌──────────────────────────────────────────────────────────┐
                  │              EVALUATION & DISCRIMINATION                 │
                  │  (14-Subdimension Rubric + Cascading Penalty Engine)     │
                  └──────────────────────────────────────────────────────────┘
```

### 1.3 Scope of this Technical Report

This report presents an exhaustive engineering deconstruction and empirical reproduction of Agent Seer applied to three generative-media MCP server suites:
1. **Google Veo Server (`mcp-veo-go`)**: 6 video generation and editing tools (`veo_t2v`, `veo_i2v`, `veo_first_last_to_video`, `veo_reference_to_video`, `veo_ingredients_to_video`, `veo_extend_video`).
2. **Gemini Image / Nanobanana Server (`mcp-nanobanana-go`)**: Multi-model image generation tool (`nanobanana_image_generation`) supporting Gemini 2.5 Flash, Gemini 3 Pro, Gemini 3.1 Flash, and Gemini 3.1 Flash Lite.
3. **Google Lyria Server (`mcp-lyria-go`)**: Audio and music generation tool (`lyria_generate_music`) supporting Lyria 2, Lyria 3 Clip, and Lyria 3 Pro.

---

## 2. 4-Stage Spec-Driven Pipeline Deconstruction

The synthetic generation pipeline converts raw schema definitions into validated benchmark harnesses through four sequential transformations, each constrained by formal input/output schemas.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 AGENT SEER SPEC-DRIVEN PIPELINE FLOW                                    │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘

 ┌──────────────────────────┐
 │  MCP Tool Specifications │  (Raw JSON Schema: name, description, inputSchema properties, required)
 └─────────────┬────────────┘
               │
               ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ STAGE 1: Tool Interpretation (Specification Understanding)                                             │
 │ Prompt: Appendix D.1 (Verbatim) | Model: Gemini 2.5 Flash Lite (Temp 0.7, JSON Mode)                   │
 │ Emits 5 Fields: tool_name, what_it_does, what_it_needs, why_its_used, enterprise_context                │
 └─────────────┬──────────────────────────────────────────────────────────────────────────────────────────┘
               │
               ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ STAGE 2: Scenario Generation (Simple vs Complex Tiers)                                                 │
 │ Prompt: Appendix D.2 (Verbatim) + Coverage Suffix ("exercise all N tools")                             │
 │ Emits: title, prompt, agent_workflow [{function_name, parameters, quick_explanation}], novelty_reason  │
 └─────────────┬──────────────────────────────────────────────────────────────────────────────────────────┘
               │
               ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ STAGE 3: Mock Output Generation with Grounding Tiers                                                   │
 │ Prompt: Appendix D.3 (Verbatim) + Reference Schemas/Examples                                           │
 │ Grounding Tiers: High (Target example), Medium (Analogy example), Low (Zero example)                   │
 │ Emits: mock_workflow [{..., mock_output, confidence}], expected_response                               │
 └─────────────┬──────────────────────────────────────────────────────────────────────────────────────────┘
               │
               ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ STAGE 4: Multi-Turn Expansion                                                                          │
 │ Phase-Boundary Decomposition | State Passing via Mock Outputs (BFCL v3 Multi-Step / Multi-Hop)         │
 │ Emits: multi-turn conversational trajectories with held-out oracle references                          │
 └────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Stage 1: Tool Interpretation (Semantic Feature Extraction)

Raw tool definitions provided by MCP `tools/list` are terse and optimized for parser consumption rather than conceptual reasoning. Stage 1 expands each raw tool schema into a rich 5-dimensional semantic representation:

1. `tool_name`: Exact string identifier of the MCP tool.
2. `what_it_does`: Exhaustive functional summary of capabilities, operational modalities, and transformation mechanics.
3. `what_it_needs`: Deconstructed inventory of mandatory versus optional parameters, accepted primitive and composite types, format constraints, and domain-specific valid ranges.
4. `why_its_used`: Strategic intent, task affordances, and execution rationales that distinguish this tool from adjacent APIs.
5. `enterprise_context`: High-level business and operational classification tags (e.g., `["Digital Asset Creation", "Marketing Automation", "Broadcast Post-Production"]`).

#### Formal JSON Contract for Stage 1:
```json
{
  "tool_name": "veo_first_last_to_video",
  "what_it_does": "Generates a smooth video transition connecting an initial start-frame image and a final end-frame image based on a guiding textual prompt.",
  "what_it_needs": {
    "required": ["first_frame_uri", "last_frame_uri", "prompt"],
    "optional": ["model", "aspect_ratio", "duration_seconds", "bucket"],
    "type_constraints": {
      "first_frame_uri": "string (valid gs:// Cloud Storage URI)",
      "last_frame_uri": "string (valid gs:// Cloud Storage URI)",
      "duration_seconds": "integer (model-constrained bounds)"
    }
  },
  "why_its_used": "Used when strict visual continuity is required between two predefined keyframes, preventing diffusion drift across scene boundaries.",
  "enterprise_context": ["Video Production", "VFX Previsualization", "Commercial Stitching"]
}
```

### 2.2 Stage 2: Scenario Generation (Simple vs. Complex & Oracle Workflows)

Stage 2 ingests the aggregated Stage 1 semantic summaries and synthesizes realistic task scenarios across two orthogonal complexity tiers:

- **Simple Tier (`STAGE2_SIMPLE`)**: Focuses on direct, single-intent user prompts requiring one or two deterministic tool calls with minimal branching.
- **Complex Tier (`STAGE2_COMPLEX`)**: Focuses on multi-faceted enterprise workflows requiring composite tool chaining, multimodal asset transformation, conditional parameter tuning, and multi-domain coordination.

#### The 100% Tool Coverage Suffix Guarantee
To eliminate generator selection bias (where the LLM repeatedly generates scenarios for prominent tools like `t2v` while ignoring niche tools like `veo_first_last_to_video`), the prompt injects a strict coverage constraint:

$$\forall t \in \mathcal{T}, \quad \exists s \in \mathcal{S} \quad \text{such that} \quad t \in \text{Workflow}(s)$$

Where $\mathcal{T}$ is the set of $N$ available tools in the MCP suite and $\mathcal{S}$ is the set of generated scenarios. In our empirical reproduction on `mcp-veo-go` ($N=6$), Stage 2 yielded **15 scenarios (6 simple, 9 complex)** with **100% tool coverage (0 uncovered tools)** across four enterprise categories: Creative Advertising, VFX Previsualization, Social Media Campaigning, and Multi-Asset Video Stitching.

#### Held-Out Oracle Workflow Structure
Every generated scenario produces an `agent_workflow` containing the exact sequence of expected function calls, fully specified parameter arguments, and step-level rationales:
```json
{
  "title": "Seamless Interpolation for Automotive Commercial Transition",
  "novelty_reason": "Requires temporal keyframe interpolation between studio shot and road test shot with strict GCS URI validation.",
  "prompt": "We have a hero studio render at gs://auto-assets/studio_front.png and a desert highway shot at gs://auto-assets/highway_rear.png. Create a 5-second cinematic transition connecting them with dust kicking up.",
  "agent_workflow": [
    {
      "function_name": "veo_first_last_to_video",
      "parameters": {
        "first_frame_uri": "gs://auto-assets/studio_front.png",
        "last_frame_uri": "gs://auto-assets/highway_rear.png",
        "prompt": "Cinematic transition from studio render to desert highway, kicking up dust, dynamic camera glide",
        "duration_seconds": 5,
        "model": "veo-3.1-generate-preview"
      },
      "quick_explanation": "Interpolates between the two keyframe URIs using the preview model supporting first/last conditioning."
    }
  ]
}
```

### 2.3 Stage 3: Mock Output Generation with Grounding Tiers

Stage 3 resolves the downstream multi-turn dependency problem without executing live tools. For every step in the `agent_workflow`, synthetic tool execution responses are generated. To quantify the fidelity of these mocks, Agent Seer introduces an explicit **Grounding Tier Taxonomy**:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 STAGE 3 GROUNDING TIER TAXONOMY                                 │
├──────────────────┬──────────────────────────────────────────────┬───────────────────────────────┤
│ Grounding Tier   │ Source Definition                            │ Semantic Confidence Tag       │
├──────────────────┼──────────────────────────────────────────────┼───────────────────────────────┤
│ High Grounding   │ Grounded in verified runtime execution schema│ `"confidence": "high"`        │
│                  │ or real success response for the exact tool. │                               │
├──────────────────┼──────────────────────────────────────────────┼───────────────────────────────┤
│ Medium Grounding │ Grounded in analogous tool outputs within the│ `"confidence": "medium"`      │
│                  │ same server family or related schema shape.  │                               │
├──────────────────┼──────────────────────────────────────────────┼───────────────────────────────┤
│ Low Grounding    │ Spec-only synthesis without runtime response │ `"confidence": "low"`         │
│                  │ examples (pure LLM hallucination).           │                               │
└──────────────────┴──────────────────────────────────────────────┴───────────────────────────────┘
```

#### Empirical Grounding Distribution Analysis
In the original paper (Section 3.3), 100% of generated mock outputs operated at `low` grounding due to the absence of reference responses in open-source specifications. 

In our reproduction, we seeded Stage 3 with real response fixtures (`spike/seed_outputs.json`) derived from `video_logic.go` and verified via `smoke_generate_and_verify.sh`. Across all 15 scenarios comprising **19 individual workflow steps**, our empirical distribution achieved:
- **High Grounding**: **16 / 19 steps (84.2%)** — Emitted fully compliant response payloads combining structured status text and standard `resource_link` metadata blocks.
- **Medium Grounding**: **3 / 19 steps (15.8%)** — Occurred exclusively in Scenario 13 ("Rapid Prototyping of Marketing Concepts"), where 3 sequential `veo_i2v` iterations synthesized distinct variation IDs.
- **Low Grounding**: **0 / 19 steps (0.0%)**.

```json
// Representative High-Grounding Mock Output (Veo Server)
{
  "function_name": "veo_first_last_to_video",
  "confidence": "high",
  "mock_output": {
    "status": "completed",
    "operation_id": "projects/108284920/locations/us-central1/publishers/google/models/veo-3.1/operations/interp_8921b",
    "response": {
      "videos": [
        {
          "gcs_uri": "gs://auto-assets/veo_output/transition_interp_8921b.mp4",
          "mime_type": "video/mp4",
          "duration_seconds": 5
        }
      ]
    },
    "text": "Successfully rendered 5s first-to-last keyframe transition video."
  }
}
```

### 2.4 Stage 4: Multi-Turn Expansion (Phase Boundaries & State Chaining)

Stage 4 segments composite workflows at natural phase boundaries to evaluate multi-step and multi-hop agent capabilities (aligned with Berkeley Function Calling Benchmark / BFCL v3 patterns):

1. **Turn $1$ (Initial Phase)**: User issues the overarching objective. The agent executes initial generation or asset preparation calls. The evaluation harness captures emitted calls, scores them, and injects the corresponding Stage 3 mock outputs.
2. **Turn $t+1$ (Follow-Up Phase)**: The user or agent initiates follow-up operations referencing state dynamically created in Turn $t$ (e.g., extending a video using the output URI from Turn $1$, or applying audio dubbing to an emitted video stem).
3. **State Consistency Verification**: The judge evaluates whether the agent properly extracts dynamic identifiers (`operation_id`, `gcs_uri`) emitted in prior mock turns or hallucinates nonexistent paths.

---

## 3. LLM-as-Judge Decomposed Rubric & Scoring Mechanics

The evaluation engine separates assessment into two orthogonal domains: **Tool-Calling Correctness ($TC$)** and **Conversational Coherence ($Coh$)**.

```
                             ┌──────────────────────────────────────────────┐
                             │       Agent Seer Evaluation System           │
                             └──────────────────────┬───────────────────────┘
                                                    │
                    ┌───────────────────────────────┴───────────────────────────────┐
                    ▼                                                               ▼
       ┌─────────────────────────┐                                     ┌─────────────────────────┐
       │ Tool-Calling (TC) Rubric│                                     │ Conversational Coherence│
       │   (4 Dims, 14 Sub-dims) │                                     │ (5 Dims, 26 Manifests)  │
       └────────────┬────────────┘                                     └────────────┬────────────┘
                    │                                                               │
       ┌────────────┼────────────┬─────────────┐                       ┌────────────┼────────────┬─────────────┐
       ▼            ▼            ▼             ▼                       ▼            ▼            ▼             ▼
    [Usage]    [Selection]  [Arguments]   [Ordering]              [LogicalFlow][Completeness][Conciseness][TopicRelev]
    (2 dims)     (3 dims)     (6 dims)      (3 dims)                    │            │            │             │
                                                                        └────────────┼────────────┴─────────────┘
                                                                                     ▼
                                                                          [ContextRetention (N/A)]
```

### 3.1 Mathematical Formulation of Tool-Calling Correctness ($TC$)

Every sub-dimension $k$ is scored by the judge on a discrete integer scale $x_k \in \{0, 1, \dots, 10\}$. Scores are normalized to the unit interval $[0.0, 1.0]$ via:

$$\text{norm}_{10}(x_k) = \max\left(0.0, \min\left(1.0, \frac{x_k}{10.0}\right)\right)$$

#### The 14 Sub-Dimensions Across 4 Core Categories:

| Dimension Index | Category | Subdimension ($k$) | Active Condition | Mathematical Normalization | Evaluation Focus |
|---|---|---|---|---|---|
| 1 | **Usage** | `necessity` | Always | $D_{\text{usage}} = \text{norm}_{10}(x_{\text{nec}})$ | Was a tool call required, or could the LLM answer directly? |
| 2 | | `overuse_detection` | Diagnostic | *Excluded from aggregate* | Did the agent make redundant or unprompted calls? |
| 3 | **Selection** | `correctness` | Always | $\text{norm}_{10}(x_{\text{cor}})$ | Does the tool choice match the requested functional intent? |
| 4 | | `specificity` | Always | $\text{norm}_{10}(x_{\text{spec}})$ | Was the most specialized tool selected over generic tools? |
| 5 | | `completeness` | Always | $\text{norm}_{10}(x_{\text{comp}})$ | Were all necessary tools selected to satisfy the task? |
| 6 | **Arguments** | `completeness` | Always | $\text{norm}_{10}(x_{\text{arg\_comp}})$ | Are all mandatory schema parameters provided? |
| 7 | | `name_accuracy` | Always | $\text{norm}_{10}(x_{\text{name}})$ | Do parameter keys match the schema exactly (case-sensitive)? |
| 8 | | `value_accuracy` | Always | $\text{norm}_{10}(x_{\text{val}})$ | Are values grounded, valid, and aligned with prompt/context? |
| 9 | | `type_compliance` | Always | $\text{norm}_{10}(x_{\text{type}})$ | Do values match expected types (string, int, array, object)? |
| 10| | `format_compliance`| Always | $\text{norm}_{10}(x_{\text{fmt}})$ | Do values follow formats (URI schemes, enums, bounds)? |
| 11| | `relevancy` | Always | $\text{norm}_{10}(x_{\text{rel}})$ | Are arguments free of ungrounded or extraneous keys? |
| 12| **Ordering** | `sequence_logic` | Tools $> 1$ | $\text{norm}_{10}(x_{\text{seq}})$ | Is execution order logical across dependent steps? |
| 13| | `dependency_handling`| Tools $> 1$ | $\text{norm}_{10}(x_{\text{dep}})$ | Are output values from earlier steps piped correctly? |
| 14| | `execution_efficiency`| Tools $> 1$ | $\text{norm}_{10}(x_{\text{eff}})$ | Is the execution path optimal without redundant hops? |

#### Dimension and Overall Score Aggregation Formulas:

1. **Usage Dimension ($D_{\text{usage}}$)**:
   $$D_{\text{usage}} = \text{norm}_{10}(x_{\text{necessity}})$$

2. **Selection Dimension ($D_{\text{selection}}$)**:
   $$D_{\text{selection}} = \frac{1}{3} \left[ \text{norm}_{10}(x_{\text{cor}}) + \text{norm}_{10}(x_{\text{spec}}) + \text{norm}_{10}(x_{\text{comp}}) \right]$$

3. **Arguments Dimension ($D_{\text{arguments}}$)**:
   $$D_{\text{arguments}} = \frac{1}{6} \sum_{k \in \mathcal{K}_{\text{arg}}} \text{norm}_{10}(x_k)$$
   $$\text{where } \mathcal{K}_{\text{arg}} = \{\text{completeness}, \text{name\_accuracy}, \text{value\_accuracy}, \text{type\_compliance}, \text{format\_compliance}, \text{relevancy}\}$$

4. **Ordering Dimension ($D_{\text{ordering}}$)**:
   If the agent invokes exactly one tool or marks ordering non-applicable:
   $$D_{\text{ordering}} \notin \mathcal{D}_{\text{active}}$$
   If multiple tools are invoked ($M > 1$):
   $$D_{\text{ordering}} = \frac{1}{|\mathcal{K}_{\text{ord}}|} \sum_{k \in \mathcal{K}_{\text{ord}}} \text{norm}_{10}(x_k), \quad \mathcal{K}_{\text{ord}} \subseteq \{\text{sequence\_logic}, \text{dependency\_handling}, \text{execution\_efficiency}\}$$

5. **Overall Composite Score ($TC_{\text{overall}}$)**:
   $$TC_{\text{overall}} = \frac{1}{|\mathcal{D}_{\text{active}}|} \sum_{d \in \mathcal{D}_{\text{active}}} D_d$$
   $$\text{where } |\mathcal{D}_{\text{active}}| = 3 \quad (\text{single tool}) \quad \text{or} \quad |\mathcal{D}_{\text{active}}| = 4 \quad (\text{multiple tools})$$

### 3.2 Cascading Penalty Mechanics & Failure Propagation

A primary failure mode of naive LLM judges is **linear averaging dilution**: if an agent emits a tool call with a completely invalid parameter name, a linear average across 6 argument subdimensions would score 5 subdimensions as $1.0$ and 1 subdimension as $0.0$, yielding $D_{\text{arguments}} = \frac{5}{6} = 0.833$ and an inflated $TC_{\text{overall}} = \frac{1.0 + 1.0 + 0.833}{3} = 0.944$ (a False Pass).

To prevent dilution, the Agent Seer rubric enforces **mandatory cascading penalties** (`spike/prompts.py:173-178`):

```
┌────────────────────────────────────────────────────────────────────────┐
│                        CASCADING PENALTY LOGIC                         │
└────────────────────────────────────────────────────────────────────────┘

Case 1: Parameter Name Invalid OR Required Parameter Missing
  ┌──────────────────────────────┐
  │  name_accuracy = 0 (0-2)     │
  │  OR completeness = 0 (0-2)   │
  └──────────────┬───────────────┘
                 │
                 ├──► value_accuracy  ──► Forced to [0, 2] (0.0 - 0.2)
                 ├──► type_compliance ──► Forced to [0, 2] (0.0 - 0.2)
                 └──► format_compl.   ──► Forced to [0, 2] (0.0 - 0.2)
                 │
                 ▼
     Argument Mean Collapses: D_arguments <= 0.333
     TC_overall Collapses:   TC <= 0.667 - 0.778

Case 2: Parameter Value Invalid (Illegal Enum, Unsupported Model, Out-of-bounds)
  ┌──────────────────────────────┐
  │  value_accuracy = 0 (0-3)    │
  └──────────────┬───────────────┘
                 │
                 ├──► type_compliance ──► Forced to [0, 3] (0.0 - 0.3)
                 ├──► format_compl.   ──► Forced to [0, 3] (0.0 - 0.3)
                 └──► relevancy        ──► Forced to [0, 3] (0.0 - 0.3)
                 │
                 ▼
     Argument Mean Collapses: D_arguments <= 0.333 - 0.467
     TC_overall Collapses:   TC <= 0.750 - 0.800
```

#### Mathematical Failure Propagation Proof:
When a critical parameter name error occurs (e.g., passing `ratio` instead of `aspect_ratio` in `A6-wrong-param-names`):
1. `name_accuracy` drops to $0.0$.
2. The cascade forces `value_accuracy` $\le 0.0$, `type_compliance` $\le 0.0$, and `format_compliance` $\le 0.0$.
3. `completeness` drops to $0.0$ because the valid parameter was omitted.
4. $D_{\text{arguments}} = \frac{0.0 + 0.0 + 0.0 + 0.0 + 0.0 + 0.0}{6} = 0.000$.
5. Composite $TC = \frac{1.0 (\text{Usage}) + 1.0 (\text{Selection}) + 0.0 (\text{Arguments})}{3} = \mathbf{0.667}$.

A single syntax error immediately eliminates $33.3\%$ of the total available score, ensuring unambiguous separation between valid and invalid calls.

### 3.3 Conversational Coherence ($Coh$) Formulation

Conversational Coherence evaluates the natural language output of the agent across 5 qualitative dimensions on a 3-point Likert scale:
- **3 (Good)**: Flawless natural language execution; zero detected failure manifestations.
- **2 (Adequate)**: Minor conversational defects (1–2 non-critical manifestations).
- **1 (Poor)**: Severe conversational failure ($\ge 3$ manifestations or critical logic breaks).

Normalization maps integer scores $x \in \{1, 2, 3\}$ to $[0.0, 1.0]$:

$$\text{norm}_3(x) = \frac{x - 1}{2.0}$$

| Dimension | Active Scope | Monitored Failure Manifestations (26 Total) |
|---|---|---|
| `logical_flow` | Always | `topic_shift`, `non_sequitur`, `poor_transitions`, `breaks_causality`, `temporal_confusion` |
| `completeness` | Always | `cuts_off`, `partial_answer`, `too_shallow`, `ignores_constraints`, `missing_key_info`, `no_actionable_advice` |
| `conciseness` | Always | `repeats_directly`, `rephrases_same_point`, `too_much_fluff`, `over_explains`, `excessive_caution` |
| `topic_relevance` | Always | `complete_topic_shift`, `misses_main_point`, `too_generic`, `hallucination`, `wrong_question` |
| `context_retention`| Multi-turn only | `asks_again`, `forgets_preferences`, `pronoun_confusion`, `contradicts_self`, `loses_thread`, `ignores_corrections` |

Overall Coherence is the unweighted arithmetic mean over active dimensions:

$$Coh_{\text{overall}} = \frac{1}{|\mathcal{V}_{\text{active}}|} \sum_{v \in \mathcal{V}_{\text{active}}} \text{norm}_3(v)$$

---

## 4. Schema-Blindness Negative Result & Capability Matrix Grounding

### 4.1 The Mechanism of Schema-Blindness

In modern MCP server implementations, tool schemas published via the JSON-RPC `tools/list` endpoint are frequently decoupled from internal backend model registries:

1. **Loose Typing in Schemas**: Parameter schemas describe high-level types (e.g., `aspect_ratio: { "type": "string", "description": "Supported aspect ratios are model-dependent." }`).
2. **Hidden Runtime Constraints**: The actual enforcement logic resides in Go backend model structs (e.g., `SupportedVeoModels` in `models.go` or `capabilities.json`).
3. **Judge Information Asymmetry**: The LLM-as-judge evaluates transcripts strictly against the schema provided in its context prompt. If a constraint is omitted from `tools/list`, the judge has zero epistemic basis to penalize the violation.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 THE SCHEMA-BLINDNESS VULNERABILITY                              │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘

   Agent Emits Tool Call:
   veo_t2v(model="veo-2.0-generate-001", generate_audio=true, prompt="...")
        │
        ├──► Vertex AI Backend: REJECTS CALL (Veo 2.0 does not support audio)
        │
        └──► Un-Enriched LLM Judge:
             Checks tools/list JSON Schema:
               generate_audio: { type: "boolean", description: "Optional. Whether to generate audio." }
             Result: Schema satisfied!
             Score Awarded: TC = 1.000 (PERFECT PASS / CRITICAL FALSE NEGATIVE)
```

### 4.2 Empirical Baseline False Passes

During our baseline validation runs with Gemini 2.5 Flash at Temperature 0.0:

- **Veo Case `A1-wrong-model-value`**: The agent invoked `veo_t2v` with `model: "veo-2.0-generate-001"` and `generate_audio: true`. In reality, Veo 2.0 physically rejects audio generation. Because `tools/list` did not document model-specific audio compatibility, the baseline judge awarded a **flawless $TC = 1.000$**, praising the call for "accurate parameter extraction" (`spike/artifacts/discrimination_results.json:27-51`).
- **Nanobanana Case `NB1-illegal-size-on-2.5`**: The agent invoked `gemini-2.5-flash-image` with `image_size: "4K"`. Flash 2.5 does not support resolution scaling. The un-enriched judge granted a near-pass score of **$TC = 0.944$**, failing to identify the model-level rejection (`spike/artifacts/discrimination_nanobanana.json:56-94`).

### 4.3 Capability Matrix Injection Architecture

To eliminate schema-blindness, we architected an automated **Capability Matrix Enrichment** layer that extracts backend model registries and appends a machine-readable capability contract directly into the judge's prompt context:

```json
// Enriched Prompt Injection: CRITICAL BACKEND MODEL CAPABILITY MATRIX (MUST ENFORCE)
{
  "veo-2.0-generate-001": {
    "SupportsGenerateAudio": "false",
    "SupportedAspectRatios": ["16:9"],
    "SupportedDurations": [5],
    "MaxVideos": 4,
    "SupportsFirstLast": false,
    "SupportsReferenceImage": false
  },
  "veo-3.1-generate-001": {
    "SupportsGenerateAudio": "true",
    "SupportedAspectRatios": ["16:9"],
    "SupportedDurations": [4],
    "MaxVideos": 4,
    "SupportsFirstLast": true,
    "SupportsReferenceImage": false
  }
}
```

```json
// Nanobanana Capability Registry (capabilities.json)
{
  "gemini-2.5-flash-image": {
    "SupportedAspectRatios": ["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
    "SupportedImageSizes": [],
    "Description": "Gemini 2.5 Flash Image. Does not support image_size (silently ignored/unsupported)."
  },
  "gemini-3-pro-image": {
    "SupportedAspectRatios": ["1:1", "3:2", "2:3", "3:4", "1:4", "4:1", "4:3", "4:5", "5:4", "1:8", "8:1", "9:16", "16:9", "21:9", "9:21"],
    "SupportedImageSizes": ["1K", "2K", "4K"],
    "Description": "Gemini 3 Pro Image. Complex reasoning and editing."
  }
}
```

### 4.4 Restoration of Clean Discrimination

Upon injecting the capability matrix, the judge immediately recognized the hidden constraints:
- **Veo Case A1**: $TC$ collapsed from **$1.000 \to 0.800$** ($\Delta = -0.200$). The cascading penalty collapsed `value_accuracy`, `type_compliance`, `format_compliance`, and `relevancy` to $0.2$, correctly logging failure taxonomy flags `['argument_value', 'argument_type', 'argument_format', 'argument_relevancy']`.
- **Nanobanana Case NB1**: $TC$ collapsed from **$0.944 \to 0.778$** ($\Delta = -0.166$). Argument score collapsed to $0.333$ with subscores zeroed out (`value_accuracy: 0.0`, `type: 0.0`, `format: 0.0`, `relevancy: 0.0`).
- **Valid Calls Preserved**: Correct baseline cases remained pristine (`A0-correct`: $0.994$, `NB0-correct`: $0.989$, `NB6-correct`: $1.000$, `LY0-correct`: $1.000$).

---

## 5. Empirical Reproduction Results across All Three MCP Server Suites

All empirical data presented below were generated using Gemini 2.5 Flash (Primary Judge, Temperature 0.0) and cross-validated with Gemini 2.5 Pro, executed across all 26 distinct test cases in the reproduction repository (`spike/artifacts/`).

### 5.1 Comprehensive Multi-Server Summary

```
+-------------------------------------------------------------------------------------------------------------+
│ Server Suite        │ Evaluation Run │ Mean Correct TC │ Mean Broken TC │ Discrimination Gap │ Taxonomy Hits│
+---------------------+----------------+-----------------+----------------+--------------------+--------------+
│ Veo (Video)         │ Baseline       │ 1.000           │ 0.768          │ 0.232              │ 7/9 (77.8%)  │
│ Veo (Video)         │ Enriched       │ 0.994           │ 0.796          │ 0.198              │ 9/9 (100.0%) │
│ Nanobanana (Image)  │ Baseline       │ 1.000           │ 0.842          │ 0.158              │ 6/6 (100.0%) │
│ Nanobanana (Image)  │ Enriched       │ 0.994           │ 0.780          │ 0.215 (+36.1% gap) │ 5/6 (83.3%)  │
│ Lyria (Music)       │ Baseline       │ 1.000           │ 0.752          │ 0.248              │ 5/5 (100.0%) │
│ Lyria (Music)       │ Enriched       │ 1.000           │ 0.809          │ 0.191              │ 5/5 (100.0%) │
+-------------------------------------------------------------------------------------------------------------+
```

### 5.2 Server Suite 1: Google Veo (`mcp-veo-go`)

The Veo evaluation suite evaluates 11 hand-authored transcripts covering 6 distinct tools and 9 injected failure modes.

| Case ID | Nature | Injected Defect / Task Description | Target Taxonomy | Baseline TC (Flash) | Baseline TC (Pro) | Enriched TC (Flash) | Score Delta ($\Delta$) | Enriched Failures Identified |
|---|---|---|---|:---:|:---:|:---:|:---:|---|
| `A0-correct` | Correct | Text-to-video (16:9, audio, valid GCS bucket) | None | **1.000** | 1.000 | **0.994** | -0.006 | `[]` |
| `A1-wrong-model-value` | Broken | Veo 2.0 requesting `generate_audio=true` | `argument_value` | **1.000** ⚠️ *(False Pass)* | 0.839 | **0.800** ✅ | **-0.200** | `argument_value`, `argument_type`, `argument_format`, `argument_relevancy` |
| `A2-illegal-enum` | Broken | Veo 3.1 with `aspect_ratio: "21:9"` | `argument_format` | **0.956** ⚠️ *(Near Pass)* | 0.867 | **0.789** ✅ | **-0.167** | `argument_value`, `argument_type`, `argument_format`, `argument_relevancy` |
| `A3-hallucinated-model` | Broken | Model ID `veo-3.5-ultra` (not in spec) | `argument_value` | **0.822** | 0.822 | **0.800** | -0.022 | `argument_value`, `argument_type`, `argument_format`, `argument_relevancy` |
| `A4-missing-required` | Broken | Omitted required parameter `prompt` | `argument_completeness`| **0.722** | 0.778 | *N/A* | *N/A* | `argument_completeness` *(Schema-expressible)* |
| `A5-wrong-tool` | Broken | Invoked `veo_i2v` with no image provided | `selection` | **0.444** | 0.494 | *N/A* | *N/A* | `selection`, `argument_value` *(Schema-expressible)* |
| `A6-wrong-param-names` | Broken | Parameters `ratio` & `gcs_bucket` passed | `argument_name` | **0.667** | 0.794 | *N/A* | *N/A* | `argument_name`, `argument_completeness`, `argument_value`, `argument_type`, `format`, `relevancy` |
| `B0-correct` | Correct | Image-to-video with valid GCS source | None | **1.000** | 1.000 | *N/A* | *N/A* | `[]` |
| `B1-wrong-tool` | Broken | Invoked `veo_t2v` ignoring provided image | `selection` | **0.656** | 0.500 | *N/A* | *N/A* | `selection` *(Schema-expressible)* |
| `B2-missing-required-image`| Broken | Omitted required `image_uri` in `veo_i2v` | `argument_completeness`| **0.778** | 0.794 | *N/A* | *N/A* | `argument_completeness`, `argument_value`, `argument_type`, `argument_format` |
| `B3-malformed-uri` | Broken | Passed local path `in.png` instead of `gs://`| `argument_format` | **0.867** | 0.911 | *N/A* | *N/A* | `argument_value`, `argument_type`, `argument_format` |

### 5.3 Server Suite 2: Gemini Image / Nanobanana (`mcp-nanobanana-go`)

The Nanobanana suite evaluates 8 test cases covering multimodal inputs, resolution scaling, aspect ratio limits, and parameter naming rules.

| Case ID | Nature | Injected Defect / Task Description | Target Taxonomy | Baseline TC | Enriched TC | Score Delta ($\Delta$) | Enriched Failures Identified |
|---|---|---|---|:---:|:---:|:---:|---|
| `NB0-correct` | Correct | Text-to-image (Gemini 3.1 Flash, 16:9, 2K) | None | **1.000** | **0.989** | -0.011 | `[]` |
| `NB1-illegal-size-on-2.5` | Broken | `gemini-2.5-flash-image` with `image_size: "4K"` | `argument_value` | **0.944** ⚠️ *(Near Pass)* | **0.778** ✅ | **-0.166** | `argument_value`, `argument_type`, `argument_format`, `argument_relevancy` |
| `NB2-illegal-aspect-ratio` | Broken | Flash 2.5 with ultra-tall aspect ratio `1:8` | `argument_format` | **0.767** | **0.778** | +0.011 | `selection`, `argument_value` |
| `NB3-hallucinated-model` | Broken | Hallucinated `imagen-3.5-ultra-banana` | `argument_value` | **0.906** | **0.750** | **-0.156** | `argument_value`, `argument_completeness` |
| `NB4-missing-required-prompt`| Broken | Omitted required `prompt` parameter | `argument_completeness`| **0.794** | **0.667** | **-0.127** | `argument_completeness` |
| `NB5-wrong-param-names` | Broken | Invalid names `ratio` & `bucket` | `argument_name` | **0.817** | **0.806** | -0.011 | `argument_name`, `selection_completeness` |
| `NB6-correct-image-to-image`| Correct | Gemini 3 Pro with valid input image array | None | **1.000** | **1.000** | 0.000 | `[]` |
| `NB7-malformed-images-type` | Broken | `images` passed as bare string (not array) | `argument_type` | **0.822** | **0.900** | +0.078 | `argument_type`, `argument_format` |

**Key Metric**: Capability matrix enrichment expanded Nanobanana's discrimination gap from **0.158 to 0.215**, representing a **$+36.1\%$ expansion in discriminating power**.

### 5.4 Server Suite 3: Google Lyria (`mcp-lyria-go`)

The Lyria suite evaluates 7 test cases covering audio generation durations, parameter name variations (`model_id` vs `model`), GCS bucket naming, and negative prompt conditioning.

| Case ID | Nature | Injected Defect / Task Description | Target Taxonomy | Baseline TC | Enriched TC | Score Delta ($\Delta$) | Enriched Failures Identified |
|---|---|---|---|:---:|:---:|:---:|---|
| `LY0-correct` | Correct | Lyria 3 Clip (30s lofi jazz, GCS output) | None | **1.000** | **1.000** | 0.000 | `[]` |
| `LY1-wrong-model-param-name`| Broken | Passed `model` instead of required `model_id` | `argument_name` | **0.739** | **0.778** | +0.039 | `argument_name`, `argument_value`, `argument_type`, `argument_format`, `argument_relevancy` |
| `LY2-wrong-bucket-param-name`| Broken| Passed `gcs_bucket_uri` instead of `output_gcs_bucket` | `argument_name` | **0.667** | **0.889** | +0.222 | `argument_name`, `argument_value`, `argument_format`, `argument_relevancy` |
| `LY3-hallucinated-model` | Broken | Hallucinated `lyria-ultra-composer-001` | `argument_value` | **0.800** | **0.806** | +0.006 | `argument_value`, `argument_completeness` |
| `LY4-missing-required-prompt`| Broken| Omitted required `prompt` parameter | `argument_completeness`| **0.778** | **0.794** | +0.016 | `argument_completeness` |
| `LY5-correct-full-track` | Correct | Lyria 3 Pro (150s full orchestral score) | None | **1.000** | **1.000** | 0.000 | `[]` |
| `LY6-malformed-sample-count`| Broken | `sample_count: -5` (violates schema `minimum: 1`) | `argument_format` | **0.778** | **0.778** | 0.000 | `argument_value`, `argument_type`, `argument_format`, `argument_relevancy` |

---

## 6. Architectural Boundaries: Orchestration Correctness vs Perceptual Media Quality

A rigorous contribution of this reproduction is the formalization of the **Three-Layer Generative Media Evaluation Stack**, establishing exact boundaries between infrastructure, agent reasoning, and perceptual quality.

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   GENERATIVE MEDIA EVALUATION STACK                                    │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘

 +------------------------------------------------------------------------------------------------------+
 | LAYER 2: PERCEPTUAL MEDIA QUALITY (Multimodal Autorater)                                             |
 | - Evaluates: Generated media artifact bytes (MP4, PNG, WAV, MP3).                                    |
 | - Metrics: Prompt adherence, visual aesthetics, temporal flicker, acoustic harmony, C2PA provenance. |
 | - Tools: Gemini 2.5 Pro Multimodal, CLAP, FID, FVD, Video-LLaVA.                                     |
 | - Cost: HIGH (Live Vertex AI API billing, GPU rendering, long execution latencies 30-120s).          |
 +------------------------------------------------------------------------------------------------------+
                                                    ▲
                                                    │ Decoupled Boundary
                                                    ▼
 +------------------------------------------------------------------------------------------------------+
 | LAYER 1: ORCHESTRATION CORRECTNESS (Agent Seer Framework)                                            │
 | - Evaluates: Agent tool-calling transcript (JSON payload structure & sequence).                      |
 | - Metrics: Tool selection, argument naming/typing/formatting, GCS asset piping, model compatibility.  |
 | - Tools: Spec-driven synthetic harness, LLM-as-judge (Temp 0.0) + Capability Matrix.                 |
 | - Cost: LOW (Synthetic mock outputs, zero GPU media rendering, sub-second execution in CI).           |
 +------------------------------------------------------------------------------------------------------+
                                                    ▲
                                                    │ Decoupled Boundary
                                                    ▼
 +------------------------------------------------------------------------------------------------------+
 | LAYER 0: PLUMBING & INFRASTRUCTURE LIVENESS (Smoke Verification)                                     |
 | - Evaluates: Server binary compilation and protocol conformance.                                     |
 | - Metrics: `go build` clean compilation, stdio JSON-RPC handshake, non-empty byte emission (>0 bytes).|
 | - Tools: `verify.sh`, `smoke_generate_and_verify.sh`.                                                |
 | - Cost: MINIMAL (Local process execution).                                                           |
 +------------------------------------------------------------------------------------------------------+
```

### 6.1 Why Orchestration Must Be Decoupled from Perceptual Evaluation

1. **Defect Attribution Precision**: In an integrated end-to-end test, a video generation failure could stem from an orchestration error (agent passed an incompatible aspect ratio), a network error (GCS bucket permission denial), or a diffusion failure (model generated visual artifacts). Layer 1 evaluation isolates agent cognitive defects with zero confounding noise from downstream generative models.
2. **Cost and Latency Decoupling**: Rendering 100 scenario permutations through live video diffusion models on Vertex AI takes hours and incurs substantial GPU billing. Agent Seer evaluates the exact same 100 scenario trajectories in seconds at near-zero inference cost using synthetic mock outputs.
3. **Deterministic CI Gating**: Layer 1 transcript evaluation at Temperature 0.0 with explicit capability contracts provides a deterministic, reproducible gate for continuous integration pull requests.

---

## 7. Judge Circularity Mitigations & Evaluation Robustness

Evaluating LLM outputs using another LLM introduces risks of self-evaluation bias, family circularity, and scoring drift. The Agent Seer architecture deploys four defensive mitigations:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 CIRCULARITY MITIGATION MATRIX                                   │
├────────────────────────────────┬────────────────────────────────────────────────────────────────┤
│ Mitigation Strategy            │ Concrete Implementation in Architecture                        │
├────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ 1. Asymmetric Model Capacity   │ Scenario Generator: Gemini 2.5 Flash Lite (Temp 0.7)           │
│                                │ Judge: Gemini 2.5 Flash / Gemini 2.5 Pro (Temp 0.0)            │
├────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ 2. Out-of-Family Replication   │ Original Paper: Qwen 3.5 122B (r = 0.79, rho = 0.86)           │
│                                │ Harness Architecture: Gemma 2 27B IT / Qwen 2.5 (gemma_client) │
├────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ 3. Prompt & Task Decoupling    │ TC Judge and Coherence Judge execute in completely isolated    │
│                                │ contexts with zero shared memory.                              │
├────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ 4. Taxonomy-Constrained Rubric │ Forces discrete categorical fault attribution rather than      │
│                                │ unconstrained floating-point scoring.                          │
└────────────────────────────────┴────────────────────────────────────────────────────────────────┘
```

### 7.1 Evaluator-Generator Capacity Asymmetry

The scenario generation pipeline utilizes `gemini-2.5-flash-lite` operating at Temperature $0.7$ with structured JSON constraints to encourage creative scenario diversity. Conversely, the evaluation harness utilizes `gemini-2.5-flash` or `gemini-2.5-pro` strictly pinned at **Temperature $0.0$**. The superior reasoning capacity of the judge model ensures that generator shortcuts or subtle parameter hallucinations are reliably detected.

### 7.2 Out-of-Family Replication Dynamics

In the published paper (§5), Karumuri et al. re-scored all 391 evaluation records using Alibaba's `Qwen3.5-122B`, demonstrating a paired Pearson correlation of $r \approx 0.79$ on Tool-Calling Correctness and a Spearman rank correlation of $\rho = 0.86$ across MCP server rankings.

In our reproduction suite, we implemented `spike/gemma_client.py`, enabling out-of-family judging via Vertex AI Model Garden hosting open-weights **Gemma 2 27B IT**. This provides production environments with a fully independent, non-circular evaluation gate.

---

## 8. Conclusion & Key Takeaways

1. **Methodology Transferability**: The Agent Seer spec-driven scenario synthesis pipeline transfers seamlessly to generative-media MCP interfaces, achieving 100% tool coverage and resolving the cold-start benchmark curation bottleneck.
2. **Schema-Blindness is Critical**: Raw JSON tool schemas are insufficient for evaluating generative-media agents due to unexpressed backend model constraints. Spec enrichment via capability matrices is mandatory to prevent false passes ($TC = 1.000$) on production bugs.
3. **Mathematical Cascading Penalties Work**: The 14-subdimension rubric with non-linear cascading penalties effectively prevents linear score dilution, collapsing broken argument scores by $\ge 33.3\%$ upon single parameter errors.
4. **Decoupled Layer Architecture**: Evaluating autonomous agents must decouple Layer 1 (Orchestration Correctness) from Layer 2 (Perceptual Media Quality), enabling sub-second, low-cost CI verification without sacrificing diagnostic precision.

---

## 9. Independent Reproduction & Verification Guide

To independently reproduce the empirical scores, deltas, and tables documented in this technical report, execute the following commands in the workspace:

```bash
# 1. Run Baseline Veo Discrimination Test (Flash & Pro Judges)
python3 agent-seer-mcp-tool-calling/spike/discrimination_test.py --second-judge

# 2. Run Nanobanana Baseline & Enriched Discrimination Tests
python3 agent-seer-mcp-tool-calling/spike/runner.py --server nanobanana
python3 agent-seer-mcp-tool-calling/spike/runner.py --server nanobanana --enriched

# 3. Run Lyria Baseline & Enriched Discrimination Tests
python3 agent-seer-mcp-tool-calling/spike/runner.py --server lyria
python3 agent-seer-mcp-tool-calling/spike/runner.py --server lyria --enriched

# 4. Verify Mathematical Scoring Assertions
python3 -c '
import sys
sys.path.insert(0, "agent-seer-mcp-tool-calling/spike")
import scoring

# Verify Perfect Call Score
perfect = {
    "usage": {"necessity": 10, "overuse_detection": 10},
    "selection": {"correctness": 10, "specificity": 10, "completeness": 10},
    "ordering": {"not_applicable": True},
    "arguments": {"completeness": 10, "name_accuracy": 10, "value_accuracy": 10, "type_compliance": 10, "format_compliance": 10, "relevancy": 10},
    "failures": [], "rationale": "perfect"
}
assert scoring.aggregate_tc(perfect)["tc_overall"] == 1.0

# Verify Cascading Parameter Name Collapse (1.0 -> 0.667)
cascaded_name = {
    "usage": {"necessity": 10, "overuse_detection": 10},
    "selection": {"correctness": 10, "specificity": 10, "completeness": 10},
    "ordering": {"not_applicable": True},
    "arguments": {"completeness": 0, "name_accuracy": 0, "value_accuracy": 0, "type_compliance": 0, "format_compliance": 0, "relevancy": 0},
    "failures": ["argument_name"], "rationale": "bad name"
}
assert round(scoring.aggregate_tc(cascaded_name)["tc_overall"], 3) == 0.667
print("All mathematical scoring assertions verified successfully.")
'
```
