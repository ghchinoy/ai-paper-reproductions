---
name: agent-seer
description: Specification-driven evaluation, deterministic capability linting, and synthetic test harness generation for Model Context Protocol (MCP) tool suites. Validates tool-calling transcripts against schemas and runtime capability matrices in <1ms without LLMs, and scores semantic orchestration using a decomposed 14-subdimension LLM-as-judge rubric. Use when testing agent tool-calling reliability, catching model-capability footguns, linting MCP function calls, or generating synthetic multi-turn eval harnesses from tools/list specs.
license: Apache-2.0
compatibility: Requires Python 3.10+, Vertex AI or OpenAI endpoint for LLM judging.
metadata:
  author: ghchinoy
  version: "1.0.0"
---

# Agent Seer (`agent-seer`)

Spec-driven evaluation and deterministic linting framework for autonomous agents calling Model Context Protocol (MCP) tools. Based on [Agent Seer (arXiv:2608.26133)](https://arxiv.org/abs/2608.26133) and extended with runtime **capability matrix grounding** and **sub-millisecond deterministic pre-pass linting**.

## Canonical Reference Docs

- [`references/rubric-guide.md`](references/rubric-guide.md) — 14-subdimension Tool-Calling (TC) rubric, arithmetic mean equations, and cascading penalty collapse rules.
- [`references/capability-schemas.md`](references/capability-schemas.md) — Capability matrix format and guidelines for bridging JSON schema gaps in model-dependent constraints.

---

## Core Workflows

### 1. Fast Deterministic Linting (<1ms, $0 Tokens)
Run static AST, JSON schema, and capability matrix validation before invoking any LLM:

```bash
# Lint a transcript JSON or Python file against an MCP server
agent-seer lint path/to/transcript.json --server path/to/mcp_server_or_dir --caps path/to/capabilities.json
```

Python API:
```python
from agent_seer import DeterministicLinter, load_tools_and_capabilities

tools, caps = load_tools_and_capabilities("spike/servers/veo")
linter = DeterministicLinter(tools=tools, capabilities=caps)

result = linter.lint(agent_calls)
if not result.is_valid:
    for err in result.errors:
        print(f"Error [{err.category}]: {err.message}")
```

---

### 2. LLM-as-a-Judge Orchestration Evaluation
Score agent tool-calling transcripts across 14 sub-dimensions using Gemini 2.5 Flash, Pro, or Gemma 24B/27B:

```bash
# Evaluate with capability matrix enrichment (default)
agent-seer eval path/to/transcript.json --server path/to/mcp_server --model gemini-2.5-flash

# Evaluate with out-of-family Gemma judge on Model Garden
agent-seer eval path/to/transcript.json --server path/to/mcp_server --model gemma-2-27b-it
```

Python API:
```python
from agent_seer import AgentSeerJudge, load_tools_and_capabilities

tools, caps = load_tools_and_capabilities("spike/servers/veo")
judge = AgentSeerJudge(model="gemini-2.5-flash")

report = judge.evaluate_tool_calling(
    tool_specs=tools,
    user_prompt="Generate a 16:9 cinematic video with audio",
    agent_calls=agent_calls,
    capabilities=caps,
    enriched=True,
)
print(f"Overall TC Score: {report['tc_overall']:.3f}")
```

---

### 3. Inspecting Server Schemas & Capabilities
Examine any live MCP server binary or pre-extracted spec:

```bash
agent-seer inspect /path/to/mcp-server-binary
```

---

### 4. CI & Pytest Test Assertion Helpers
Use built-in assertions to gate Pull Requests in continuous integration:

```python
from agent_seer.testing import assert_valid_tool_calls, evaluate_transcript

def test_agent_video_generation_workflow(my_agent):
    calls = my_agent.run("Create a 16:9 video of sunrise")
    
    # 1. Deterministic pre-pass (instant check)
    assert_valid_tool_calls(calls, server_path="spike/servers/veo")
    
    # 2. Semantic evaluation (assert minimum score threshold)
    evaluate_transcript(
        user_prompt="Create a 16:9 video of sunrise",
        calls=calls,
        server_path="spike/servers/veo",
        min_tc_score=0.90,
    )
```
