# Project: Agent Seer Comprehensive Review, Synthesis & Strategic Roadmap

## Architecture
Agent Seer (arXiv:2608.26133) implements an automated, 4-stage specification-driven synthetic scenario generation and multi-turn evaluation framework for emerging and proprietary tool-calling interfaces (such as MCP servers). 

### Pipeline Stages
1. **Stage 1 (Tool Interpretation):** Expands raw JSON tool schemas into 5 semantic dimensions (`tool_name`, `what_it_does`, `what_it_needs`, `why_its_used`, `enterprise_context`).
2. **Stage 2 (Scenario Generation):** Generates single-turn (simple) and multi-turn (complex) enterprise scenarios with user prompts, oracle workflows, and novelty rationales with 100% tool coverage.
3. **Stage 3 (Mock Output Generation):** Generates synthetic tool execution outputs across three grounding tiers (`high`: seeded from real server schemas; `medium`: similar tool schemas; `low`: zero examples).
4. **Stage 4 (Multi-Turn Expansion):** Chains workflows across conversational turns with follow-up prompts referencing prior mock outputs.

### Evaluation & Scoring Engine
- **Tool-Calling Correctness ($TC$):** 4 dimensions, 14 sub-dimensions normalized to $[0, 1]$ on a 10-point scale:
  $$\text{Usage} = \text{norm}_{10}(\text{necessity})$$
  $$\text{Selection} = \frac{1}{3} \sum_{k \in \{\text{correctness}, \text{specificity}, \text{completeness}\}} \text{norm}_{10}(\text{sel}_k)$$
  $$\text{Arguments} = \frac{1}{6} \sum_{k \in \{\text{completeness}, \text{name\_acc}, \text{val\_acc}, \text{type\_comp}, \text{fmt\_comp}, \text{relevancy}\}} \text{norm}_{10}(\text{arg}_k)$$
  $$\text{Ordering} = \frac{1}{M} \sum_{k \in \{\text{seq\_logic}, \text{dep\_handling}, \text{exec\_eff}\}} \text{norm}_{10}(\text{ord}_k) \quad (\text{if called tools } > 1)$$
  $$TC = \frac{1}{D} \sum_{d \in \{\text{Usage}, \text{Selection}, \text{Arguments}, [\text{Ordering}]\}} d \quad (D \in \{3, 4\})$$
- **Cascading Penalty Rules:**
  - Parameter NAME wrong or REQUIRED missing: assign near-zero scores ($0 \le \text{score} \le 2$) to `value_accuracy`, `type_compliance`, and `format_compliance`.
  - Parameter VALUE wrong (illegal enum, ungrounded value, unsupported model): cascade near-zero scores ($0 \le \text{score} \le 3$) to `type_compliance`, `format_compliance`, and `relevancy`.
  - Single critical parameter error collapses argument arithmetic mean.
- **Conversational Coherence ($Coh$):** 5 dimensions on 3-point scale normalized to $[0, 1]$ via $\frac{x - 1}{2}$.
- **LLM-as-Judge Circularity Mitigations:** Temperature $0.0$, separated prompt contexts, out-of-family judging with Gemma 24B/27B or Qwen.

### Evaluated Generative-Media MCP Server Suites
1. `mcp-veo-go` (Google Veo Video Generation: `veo_t2v`, `veo_i2v`, `veo_v2v`, `veo_extend`, `veo_audio`, `veo_status`, `veo_cancel`, `veo_download`)
2. `mcp-nanobanana-go` (Gemini Image Generation: `nanobanana_image_generation`, `gemini-3.1-flash-image`, `gemini-3-pro-image`, `gemini-2.5-flash-image`, `imagen-3.0-generate-002`)
3. `mcp-lyria-go` (Google Lyria Music Generation: `lyria_generate_music`, `lyria-3-clip-001`, `lyria-3-pro-001`, `lyria-3-loop-001`)

## Feature Inventory
| # | Feature / Requirement | Description | Milestone | Status |
|---|-----------------------|-------------|-----------|--------|
| 1 | 4-Stage Pipeline Deconstruction | Spec-driven interpretation, scenario synthesis, mock output grounding, multi-turn expansion | M1 | DONE |
| 2 | 14-Subdimension Rubric & Formulas | Complete mathematical definitions, normalization, arithmetic mean, ordering applicability | M1 | DONE |
| 3 | Cascading Penalty Rules | Exact prompt directives, near-zero assignment rules, failure propagation | M1 | DONE |
| 4 | Schema-Blindness Negative Result | Detailed analysis of JSON schema omissions vs backend Go runtime constraints | M1 | DONE |
| 5 | Empirical Before/After Discrimination | Complete data tables for Veo, Nanobanana, Lyria; exact scores, deltas, taxonomy hits | M1 | DONE |
| 6 | Architectural Boundary Formulation | 3-layer architecture: Plumbing (L0), Orchestration (L1), Perceptual Quality (L2) | M1 | DONE |
| 7 | Judge Circularity Mitigations | Analysis of Gemini Flash/Pro same-family vs Gemma 24B/27B out-of-family evaluation | M1 | DONE |
| 8 | Blog Narrative Framing | "Grading the agent, not the pixels" framing, clear problem statement, enterprise stakes | M2 | DONE |
| 9 | Blog Pipeline Mechanics Walkthrough | Accessible explanation of 4 stages with intuitive visual/text diagrams | M2 | DONE |
| 10| Blog Cautionary Case Studies | Concrete JSON & schema snippets: Veo-2.0 audio request (1.000 -> 0.800), Nanobanana 4K on 2.5 (0.944 -> 0.778) | M2 | DONE |
| 11| Blog Capability Matrix Fix | Mechanism of capability matrix injection and restoration of clean discrimination gap | M2 | DONE |
| 12| Blog Takeaways for Engineers | Actionable design principles for MCP server authors and AI agent builders | M2 | DONE |
| 13| Strategic Roadmap Tier 1 | Deterministic schema & capability linters as non-LLM pre-pass (ast/schema linting, 0-token cost) | M3 | DONE |
| 14| Strategic Roadmap Tier 2 | Multi-server cross-tool orchestration chains (Image -> Video -> Audio -> AV compositing) | M3 | DONE |
| 15| Strategic Roadmap Tier 3 | Live agent runner integration & Model Garden Gemma out-of-family regression CI gating | M3 | DONE |
| 16| Cross-Document Verification & Audit | Strict numeric consistency check across all 3 docs and against raw spike artifacts | M4 | DONE |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Technical Deep-Dive Report | Author `/Users/ghchinoy/projects/ai-paper-reproductions/agent-seer-mcp-tool-calling/technical-report.md` (R1) | Survey | DONE |
| M2 | Engineering Blog Post | Author `/Users/ghchinoy/projects/ai-paper-reproductions/agent-seer-mcp-tool-calling/blog-post.md` (R2) | M1 | DONE |
| M3 | Strategic Recommendations | Author `/Users/ghchinoy/projects/ai-paper-reproductions/agent-seer-mcp-tool-calling/recommendations.md` (R3) | M1 | DONE |
| M4 | Verification, Challenge & Audit | Dual Reviewer verification, Dual Challenger stress testing, and Forensic Integrity Audit across all deliverables | M1, M2, M3 | DONE (PASS) |

## Deliverable Layout & Artifact Inventory
- **Deliverable 1 (R1):** `/Users/ghchinoy/projects/ai-paper-reproductions/agent-seer-mcp-tool-calling/technical-report.md` (699 lines, 62.9 KB)
- **Deliverable 2 (R2):** `/Users/ghchinoy/projects/ai-paper-reproductions/agent-seer-mcp-tool-calling/blog-post.md` (464 lines, 33.8 KB)
- **Deliverable 3 (R3):** `/Users/ghchinoy/projects/ai-paper-reproductions/agent-seer-mcp-tool-calling/recommendations.md` (785 lines, 61.8 KB)
- **Audit Reports:**
  - Forensic Audit: `.agents/teamwork_preview_auditor_1/handoff.md` (CLEAN)
  - Reviewer 1: `.agents/teamwork_preview_reviewer_1_replace/handoff.md` (APPROVE)
  - Reviewer 2: `.agents/teamwork_preview_reviewer_2_replace/handoff.md` (APPROVE)
  - Challenger 1: `.agents/teamwork_preview_challenger_1/handoff.md` (APPROVE)
  - Challenger 2: `.agents/teamwork_preview_challenger_2/handoff.md` (APPROVE)
