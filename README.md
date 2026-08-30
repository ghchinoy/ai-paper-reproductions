# AI paper reproductions

Hands-on reproductions of AI and agent research papers: enough code, data, and
write-up to see whether a paper's method holds up when you build it against a
real system. Each reproduction lives in its own directory with the paper
analysis, the spike code, the saved artifacts, and a narrative write-up.

## Reproductions

| Directory | Paper | What it reproduces |
|---|---|---|
| [`agent-seer-mcp-tool-calling/`](./agent-seer-mcp-tool-calling/) | Agent Seer: Synthesizing Scenarios from Specification Understanding ([arXiv:2608.26133](https://arxiv.org/abs/2608.26133)) | Spec-driven, execution-free evaluation of agent tool-calling, applied to a generative-media MCP server (`mcp-veo-go`). Includes the negative finding on schema-blind judging and the capability-matrix fix. |

## Layout of a reproduction

Each reproduction directory follows a consistent shape:

- `README.md` — the narrative write-up (what the paper claims, how we reproduced it, the results).
- `paper-analysis.md` — the closer reading of the paper and how it maps to the system under test.
- `spike-result.md` — the go/no-go result of the spike, with the raw numbers.
- `spike/` — the standalone reproduction spike code and every saved empirical artifact.
- `src/` & `pyproject.toml` — the production Python package and CLI (`agent-seer`).
- `tests/` — unit, integration, and adversarial test suites.
- `plugin.json` & `skills/` — Agent Plugin and Agent Skill definitions for agentic workflows.
- `technical-report.md` — in-depth technical analysis, architecture, and empirical findings.
- `blog-post.md` — narrative publication write-up and engineering post-mortem.
- `recommendations.md` — actionable design guidelines and architectural recommendations.
