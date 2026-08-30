<!-- headroom:rtk-instructions -->
# RTK (Rust Token Killer) - Token-Optimized Commands

When running shell commands, **always prefix with `rtk`**. This reduces context
usage by 60-90% with zero behavior change. If rtk has no filter for a command,
it passes through unchanged — so it is always safe to use.

## Key Commands
```bash
# Git (59-80% savings)
rtk git status          rtk git diff            rtk git log

# Files & Search (60-75% savings)
rtk ls <path>           rtk read <file>         rtk grep <pattern>
rtk find <pattern>      rtk diff <file>

# Test (90-99% savings) — shows failures only
rtk pytest tests/       rtk cargo test          rtk test <cmd>

# Build & Lint (80-90% savings) — shows errors only
rtk tsc                 rtk lint                rtk cargo build
rtk prettier --check    rtk mypy                rtk ruff check

# Analysis (70-90% savings)
rtk err <cmd>           rtk log <file>          rtk json <file>
rtk summary <cmd>       rtk deps                rtk env

# GitHub (26-87% savings)
rtk gh pr view <n>      rtk gh run list         rtk gh issue list

# Infrastructure (85% savings)
rtk docker ps           rtk kubectl get         rtk docker logs <c>

# Package managers (70-90% savings)
rtk pip list            rtk pnpm install        rtk npm run <script>
```

## Rules
- In command chains, prefix each segment: `rtk git add . && rtk git commit -m "msg"`
- For debugging, use raw command without rtk prefix
- `rtk proxy <cmd>` runs command without filtering but tracks usage
<!-- /headroom:rtk-instructions -->

# Repository Agent Guidelines & Reproduction Conventions

This repository houses hands-on empirical reproductions of AI and agent research papers. Its core mission is to test whether published methods hold up when implemented against real-world systems, protocols (such as the Model Context Protocol / MCP), and production models.

---

## 1. Prose & Editorial Flow

All narrative deliverables—including blog posts, technical reports, and architectural recommendations—must adhere to strict engineering editorial standards. AI-generated text must be audited for authentic technical voice and stripped of synthetic writing patterns before publication.

### Tooling & Public Specifications

1. **Editorial Quality & Pattern Stripping:**
   - **`agent-skills` repository:** [https://github.com/ghchinoy/agent-skills](https://github.com/ghchinoy/agent-skills)
   - Employs the **`technical-post-editorial`** skill (located under `plugins/repo-authoring/skills/technical-post-editorial/`).
   - Standards reference: [Agent Skills Specification](https://agentskills.io) and [Agent Plugins Specification v1.0.0](https://agent-plugins.org).
   - Use during drafting to remove common AI tropes (e.g. rhetorical drama dashes, throat-clearing openers, false binary framing, non-technical filler adverbs) while preserving human voice and technical rigor.

2. **Acceptance Gate & Readability Metrics:**
   - **`docstats` repository:** [https://github.com/ghchinoy/docstats](https://github.com/ghchinoy/docstats)
   - Multi-protocol readability and house-style linting engine (ships the `readability-analysis` skill and `readability-docstats` MCP tool).
   - Evaluates a **Two-Axis Scorecard**:
     - **Axis A (Readability & Audience Fit):** Consensus grade level (`text_standard`), Flesch-Kincaid Grade Level, Gunning Fog, SMOG index. Target: Grade 10–15 for deep technical post-mortems and architecture papers.
     - **Axis B (House-Style Linting):** Deterministic counts and rates of throat-clearing openers (target: 0), binary contrasts (target: 0), non-technical filler adverbs (target rate: ≤ 1.5/100 words), em dashes (target rate: ≤ 0.5/100 words), and computes `ai_tell_score` (target floor: **≥ 7.0 / 10.0**, ideally 10.0 with 0 diagnostic flags).

### Recommended Editorial Workflow: Post-Hoc Acceptance Gate

`docstats` is designed as an **asynchronous post-hoc acceptance gate**, *not* an in-loop generative dial. Empirical research demonstrates that injecting numeric metrics during generation does not improve prose quality and risks metric gaming.

Follow this sequence:
1. **Draft:** Author narrative prose using qualitative editorial guidelines (`technical-post-editorial`).
2. **Audit:** Run `docstats` against the drafted markdown file (via MCP or `uv run python main.py` in the `docstats` project) to obtain the Axis A / Axis B scorecard.
3. **Refine:** Resolve any diagnostic flags (e.g., offender adverbs like *actually*, *silently*, *fundamentally*, or rhetorical em dashes).
4. **Gate & Publish:** Ensure the document achieves `ai_tell_score >= 7.0` and empty flags before committing.

---

## 2. Reproduction Conventions & Lifecycle

Each research reproduction in this repository lives in its own top-level directory (e.g., `agent-seer-mcp-tool-calling/`) and adheres to a disciplined empirical lifecycle.

### Reproduction Lifecycle Stages

1. **Paper Analysis (`paper-analysis.md`):**
   - Critical reading of the research paper claims, formal definitions, prompt templates, and algorithms.
   - Translation of paper assumptions to the target system under test (e.g., Model Context Protocol tools, Vertex AI / Gemini models).
2. **Reproduction Spike (`spike/` & `spike-result.md`):**
   - Minimal standalone experiment testing core paper claims against live systems.
   - Saves all raw inputs, model completions, and evaluation outputs to `spike/artifacts/`.
   - Produces a crisp go/no-go decision report (`spike-result.md`) based on empirical metrics (e.g., discrimination score, hallucination rate).
3. **Production Uplift (`src/` & `tests/`):**
   - When a reproduction yields actionable engineering value, uplift the spike code into an installable Python package under `src/<package_name>/` with a clean CLI entrypoint (`pyproject.toml`).
   - Implement deterministic pre-passes (AST/schema linters), typed models (Pydantic), and robust client abstractions (supporting cross-family evaluation).
   - Write comprehensive unit, integration, and adversarial tests under `tests/`.
4. **Agent Plugin & Skill Packaging (`plugin.json` & `skills/`):**
   - Package reusable tools and workflows as standards-compliant Agent Plugins (`plugin.json`) and Agent Skills (`skills/<skill_name>/SKILL.md`).
5. **Deliverable Documentation:**
   - **`technical-report.md`:** Comprehensive technical analysis, empirical tables, cross-model circularity checks, and architectural evaluations.
   - **`blog-post.md`:** Narrative engineering post-mortem and publication write-up.
   - **`recommendations.md`:** Actionable design guidelines for server authors and agent developers.
   - **`PROJECT.md`:** Milestone tracking, pipeline stages, scoring formulas, and deliverable paths.

### Empirical Honesty & Verification Standards

- **Negative Findings First:** Document where papers fail in real-world conditions. (e.g., in Agent Seer, raw JSON Schema evaluation missed 100% of model-parameter incompatibility bugs—identifying this led to the capability-matrix fix).
- **Explicit Validation Caveats:** Never overstate validation status. If a production package has been tested via unit tests but not yet run against live empirical baselines, state the caveat explicitly.
- **Accurate Metric Reporting:** Always verify test counts directly via test runner collection (`uv run --with pytest --with pytest-asyncio pytest --collect-only`), never guess or hardcode stale figures.
- **Artifact Grounding:** All empirical claims in reports and posts must link to saved artifacts under `spike/artifacts/`.

### Development & Tooling Standards

- **Environment & Dependency Management:** Use [`uv`](https://docs.astral.sh/uv/) for Python packaging, dependency resolution, and virtual environments.
- **Testing:** Run test suites using `uv run --with pytest --with pytest-asyncio pytest -v`.
- **Shell Commands:** Always prefix shell commands with `rtk` (see RTK block above).
- **Git Hygiene:** Write conventional commit messages matching repo style (`docs(<scope>): ...`, `feat(<scope>): ...`, `fix(<scope>): ...`). Do not commit build artifacts (`*.egg-info/`, `.serena/`, untracked `uv.lock`).
