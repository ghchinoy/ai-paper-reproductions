"""Agent Seer prompts (arXiv 2608.26133), reconstructed for the mcp-veo-go spike.

PROVENANCE / fidelity notes:
- Stage 1-4 generation prompts (STAGE1_* .. STAGE4_*) are reproduced VERBATIM
  from the paper's Appendix D (extracted text at
  ../agent-seer-extracted-text.txt), with the PDF's kerning artifacts
  (stray spaces inside words) removed. Placeholders {tool_info}, {tool_summary},
  {N} are the paper's.
- The two judge prompts (TC_JUDGE_PROMPT, COHERENCE_JUDGE_PROMPT) are
  reconstructed from the paper's published rubric — Table 18 (tool-calling
  dimensions/sub-dimensions/definitions/scales + the cascading-penalty
  footnote), Table 19 (coherence dimensions/manifestations/1-3 scale), and the
  aggregation rules in Section 4 / Appendix E. The paper does not print the
  judge prompt as a single verbatim block, so this is a faithful reconstruction
  of the rubric it specifies, not a copy of a printed prompt. The sub-dimension
  wordings and cascading rules are quoted from Table 18.
"""

# --------------------------------------------------------------------------
# Stage 1: Tool Interpretation (Appendix D.1, verbatim)
# --------------------------------------------------------------------------
STAGE1_TOOL_INTERPRETATION = """I have a tool that can be called by an agent, and I could use help understanding what it does and what it is helpful for.

Tool info:
``` json
{tool_info}
```

I need a json in the following format that can help me thoroughly understand what the tool is capable of, especially in an enterprise context. Keep the explanations grounded within the tool info.
{{
  "tool_name": <Tool name here, as given>,
  "what_it_does": <Complete explanation of the tool's functionality and what it aims to do>,
  "what_it_needs": <What parameters the tool needs and how they should be formatted>,
  "why_its_used": <Reasons an agent would call this tool; potential use cases>,
  "enterprise_context": <Tags for what aspect of an enterprise this could help with>
}}"""

# --------------------------------------------------------------------------
# Stage 2: Scenario Generation (Appendix D.2, verbatim)
# The complex prompt mirrors the simple one, swapping "straightforward, and
# commonplace" for "novel, and complex" and adding two "Make sure" items.
# --------------------------------------------------------------------------
_STAGE2_JSON_FORMAT = """
Return JSON in this shape:
{{
  "categories": [
    {{
      "category": <category name>,
      "scenarios": [
        {{
          "title": <short title>,
          "prompt": <the user-facing instruction to the agent>,
          "agent_workflow": [
            {{
              "function_name": <exact tool name>,
              "parameters": {{<param name>: <realistic value>, ...}},
              "quick_explanation": <why this call is made>
            }}
          ],
          "novelty_reason": <why this scenario has evaluation value>,
          "agent_followup": <a natural follow-up question>
        }}
      ]
    }}
  ]
}}
"""

STAGE2_SIMPLE = (
    """I'm building an agentic chatbot for enterprise use cases. Based on the available tool capabilities below, generate realistic, straightforward, and commonplace scenarios organized by category that showcase how employees would use this chatbot for everyday tasks. These examples would not require too many tool calls -- they'll be smaller and more precise.

Available Tool Capabilities:
{tool_summary}

For each scenario, include the exact function calls the agent would make using the available tools.
"""
    + _STAGE2_JSON_FORMAT
    + """
Make sure:
1. Use actual tool names from the available capabilities
2. Function names and parameters are structured separately with realistic values adhering to the parameter schema
3. Workflows show logical progression
4. Scenarios are practical and commonly encountered
5. Agent workflows do the necessary context management & tool calls to identify how parameters are selected
6. Provide meaningful agent_followup content that makes sense within the context of the scenario.

IMPORTANT: Ensure broad coverage across ALL available tools. Every tool listed above should appear in at least one scenario's agent_workflow. There are {N} tools total -- design scenarios that collectively exercise all of them."""
)

STAGE2_COMPLEX = (
    """I'm building an agentic chatbot for enterprise use cases. Based on the available tool capabilities below, generate realistic, novel, and complex scenarios organized by category that showcase advanced and creative tool usage. These examples should demonstrate sophisticated multi-domain workflows.

Available Tool Capabilities:
{tool_summary}

For each scenario, include the exact function calls the agent would make using the available tools.
"""
    + _STAGE2_JSON_FORMAT
    + """
Make sure:
1. Use actual tool names from the available capabilities
2. Function names and parameters are structured separately with realistic values adhering to the parameter schema
3. Workflows show logical progression
4. Scenarios are practical and commonly encountered
5. Agent workflows do the necessary context management & tool calls to identify how parameters are selected
6. Provide meaningful agent_followup content that makes sense within the context of the scenario.
7. Each scenario demonstrates complex, multi-step processes.
8. Each scenario shows creative combinations of tools that unlock new capabilities.

IMPORTANT: Ensure broad coverage across ALL available tools. Every tool listed above should appear in at least one scenario's agent_workflow. There are {N} tools total -- design scenarios that collectively exercise all of them."""
)

# --------------------------------------------------------------------------
# Stage 3: Mock Output Generation (Appendix D.3, verbatim)
# --------------------------------------------------------------------------
STAGE3_MOCK_OUTPUT = """You are a Mock Tool Output Generator for synthetic agent workflow data. Your task is to generate realistic mock tool outputs that complete synthetic scenarios. You will be given an initial prompt (and maybe a description of what the aim of the prompt is & why the scenario is of interest). Then, you will be given an agent workflow. This will detail: (1) A function call w/ parameters and (2) A quick explanation of what the tool does. Finally, you will have some example function calls with their respective outputs OR a JSON schema object describing the output structure. Use this to guide formatting for the final mock tool output.

Return JSON: mock_workflow[] with function_name, parameters, quick_explanation, mock_output, confidence; plus expected_response that references specific mock data.

### CONFIDENCE LEVEL GUIDELINES
"high": concrete example for THIS specific function was provided
"medium": no example for this function, but similar functions have examples
"low": no example output provided for this function

### CRITICAL INSTRUCTIONS
1. Concrete Data: replace placeholders (e.g. "{{user_id}}" or "XYZ") with realistic, specific values.
2. Realism & Diversity: reflect how a real system would respond; incorporate diverse names, global locations, and varied data points.
3. Formatting: strictly adhere to provided reference examples or JSON schema.
4. Expected response references concrete mock data (names, IDs, counts, statuses, dates) and reflects the full workflow, not just the last call.

--- SCENARIO ---
Prompt: {prompt}
Novelty: {novelty_reason}

--- AGENT WORKFLOW ---
{agent_workflow}

--- REFERENCE EXAMPLE OUTPUTS (for grounding) ---
{example_outputs}
"""

# --------------------------------------------------------------------------
# Judge prompt: Tool-Calling correctness (Section 4.1 / Table 18 / Appendix E.1)
# Reconstructed from the published rubric. Sub-dimension wordings and the
# cascading footnote are quoted from Table 18.
# --------------------------------------------------------------------------
TC_JUDGE_PROMPT = """You are a strict, unsupervised evaluator of an AI agent's tool-calling behavior. You are given (a) the tool specifications the agent had available, (b) the user's request, and (c) the exact tool calls the agent emitted. There is NO reference answer; judge purely on the spec and the request.

Score each sub-dimension below on an integer 0-10 scale (10 = perfect, 0 = complete failure). Be discriminating: reserve 9-10 for calls that are fully correct against the schema and request.

## USAGE
- necessity: Was a tool actually needed, or could the assistant answer directly? (0-10)
- overuse_detection: Are there redundant or unnecessary tool calls? (0-10; diagnostic only)

## SELECTION
- correctness: Do the selected tools match the task described by the user? (0-10)
- specificity: Was the most specific tool chosen when alternatives exist? (0-10)
- completeness: Are all tools needed to fully address the query called? (0-10)

## ORDERING (mark not_applicable=true and leave scores null if only ONE tool is called)
- sequence_logic: Is the execution order logical; do later calls build on earlier ones? (0-10)
- dependency_handling: Are inter-tool dependencies respected (output -> input)? (0-10)
- execution_efficiency: Could reordering improve efficiency? (0-10)

## ARGUMENTS
- completeness: Are all required parameters provided? (0-10)
- name_accuracy: Do parameter names match schemas exactly (case-sensitive)? (0-10)
- value_accuracy: Are values correct and grounded in the user query or prior tool outputs? (0-10)
- type_compliance: Do parameter values match expected data types? (0-10)
- format_compliance: Do values follow expected formats (dates, enums, patterns)? (0-10)
- relevancy: Are there any extra or invalid parameters not in the schema? (0-10)

## CASCADING PENALTY RULES (MANDATORY - enforce exactly)
- If a parameter NAME is wrong (does not exist in the schema) OR a REQUIRED parameter is missing: assign near-zero scores (0-2) to value_accuracy, type_compliance, AND format_compliance.
- If a parameter VALUE is wrong (illegal enum, unsupported model, out-of-range, ungrounded): cascade near-zero (0-3) to type_compliance, format_compliance, AND relevancy.
- Values legitimately taken from prior tool outputs in chained calls are NOT penalized.
- A single critical error should therefore collapse the argument mean.

## FAILURE TAXONOMY
Also classify each detected failure into one of: usage, selection, ordering, argument_completeness, argument_name, argument_value, argument_type, argument_format, argument_relevancy. If none, use "none".

Return ONLY JSON in this exact shape:
{{
  "usage": {{"necessity": int, "overuse_detection": int}},
  "selection": {{"correctness": int, "specificity": int, "completeness": int}},
  "ordering": {{"not_applicable": bool, "sequence_logic": int|null, "dependency_handling": int|null, "execution_efficiency": int|null}},
  "arguments": {{"completeness": int, "name_accuracy": int, "value_accuracy": int, "type_compliance": int, "format_compliance": int, "relevancy": int}},
  "failures": [<taxonomy strings>],
  "rationale": <1-3 sentence explanation of the main issues, or "correct" if none>
}}

--- TOOL SPECIFICATIONS ---
{tool_specs}

--- USER REQUEST ---
{user_prompt}

--- AGENT TOOL CALLS (emitted) ---
{agent_calls}
"""

# --------------------------------------------------------------------------
# Judge prompt: Coherence (Section 4.2 / Table 19 / Appendix E.2)
# Reconstructed from Table 19 (dimensions, manifestations, 1-3 scale).
# --------------------------------------------------------------------------
COHERENCE_JUDGE_PROMPT = """You are an unsupervised evaluator of conversational coherence for an enterprise AI agent transcript. Score each dimension on a 1-3 scale:
- 3 (Good): no failure manifestations detected
- 2 (Adequate): 1-2 minor manifestations
- 1 (Poor): 3+ manifestations or critical failures

## DIMENSIONS (with failure manifestations to watch for)
- logical_flow: follows logically from previous turns; coherent progression. Failures: topic_shift, non_sequitur, poor_transitions, breaks_causality, temporal_confusion
- completeness: addresses all parts of the user's query. Failures: cuts_off, partial_answer, too_shallow, ignores_constraints, missing_key_info, no_actionable_advice
- conciseness: communicates without unnecessary repetition. Failures: repeats_directly, rephrases_same_point, too_much_fluff, over_explains, excessive_caution
- topic_relevance: stays focused on the user's query and topic. Failures: complete_topic_shift, misses_main_point, too_generic, hallucination, wrong_question
- context_retention: maintains and uses information from conversation history (set not_applicable=true if there is no prior conversation history). Failures: asks_again, forgets_preferences, pronoun_confusion, contradicts_self, loses_thread, ignores_corrections

Return ONLY JSON:
{{
  "logical_flow": int,
  "completeness": int,
  "conciseness": int,
  "topic_relevance": int,
  "context_retention": {{"not_applicable": bool, "score": int|null}},
  "manifestations": [<detected manifestation strings>],
  "rationale": <1-2 sentence explanation>
}}

--- TRANSCRIPT ---
{transcript}
"""
