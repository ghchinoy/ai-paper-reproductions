"""Agent Seer Prompts & Prompt Builders (arXiv:2608.26133)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

from .models import ToolDefinition, ToolParameter

# --------------------------------------------------------------------------
# Prompt Templates
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
7. Include complex and multi-turn workflows
8. Tool calls should reflect advanced and creative tool usage

IMPORTANT: Ensure broad coverage across ALL available tools. Every tool listed above should appear in at least one scenario's agent_workflow. There are {N} tools total -- design scenarios that collectively exercise all of them."""
)

STAGE2_BOUNDARY = (
    """I'm building an agentic chatbot for enterprise use cases. Based on the available tool capabilities below, generate rigorous fault-testing scenarios with boundary values, invalid parameters, and edge-case inputs to stress test the agent's validation. Include scenarios with: Missing required parameters, Illegal enum values, Type mismatches, and Unsupported model capabilities.

Available Tool Capabilities:
{tool_summary}

For each scenario, include the exact function calls the agent would make using the available tools.
"""
    + _STAGE2_JSON_FORMAT
    + """
IMPORTANT: Ensure broad coverage across ALL available tools. There are {N} tools total -- design scenarios that collectively exercise all of them."""
)

STAGE3_MOCK_OUTPUT = """I'm evaluating an agentic chatbot. Given a scenario and the agent's workflow, generate realistic mock tool output responses for each step.

Available Tool Capabilities:
{tool_summary}

Example outputs (if available):
{seed_outputs}

Scenario:
Title: {title}
Prompt: {prompt}
Workflow:
{workflow}

Return JSON:
{{
  "mock_workflow": [
    {{
      "function_name": <exact tool name>,
      "parameters": {{...}},
      "quick_explanation": <why this call was made>,
      "mock_output": <realistic output string or JSON object matching real tool responses>,
      "confidence": <"high" if real example was available, "medium" if similar format, "low" if fully synthetic>,
      "expected_response": <expected payload structure>
    }}
  ]
}}
"""

STAGE4_MULTI_TURN = """You are an expert Multi-Turn Conversation Expander for agent tool-calling evaluation.

Scenario: {title}
Initial Prompt: {prompt}
Workflow with Grounded Mock Outputs:
{mock_workflow}
Follow-up Directive: {followup}

Synthesize a coherent multi-turn conversation where turn 1 executes the workflow and turn 2 executes follow-up actions referencing prior turn outputs.

Return JSON:
{{
  "scenario_title": "{title}",
  "turns": [
    {{
      "turn_index": 1,
      "user_message": <initial prompt>,
      "agent_tool_calls": [<turn 1 calls>],
      "tool_responses": [<turn 1 grounded outputs>],
      "agent_response": <natural language summary>
    }},
    {{
      "turn_index": 2,
      "user_message": <follow-up message>,
      "agent_tool_calls": [<follow-up calls>],
      "tool_responses": [<follow-up outputs>],
      "agent_response": <follow-up agent summary>
    }}
  ]
}}
"""

TC_JUDGE_PROMPT = """You are an expert evaluator assessing the correctness of tool calls made by an autonomous AI agent.

Tool Specifications:
```json
{tool_specs}
```

User Prompt:
{user_prompt}

Agent Tool Calls:
```json
{agent_calls}
```

Score the agent's tool calls against the rubric below. Each sub-dimension is scored from 0 to 10 (10 = flawless, 0 = complete failure).

CRITICAL CASCADING PENALTY RULES (MUST ENFORCE):
1. If a parameter NAME is incorrect or a REQUIRED parameter is missing, assign 0 to name_accuracy and CASCADE near-zero scores (0-2) to value_accuracy, type_compliance, and format_compliance for that parameter.
2. If a parameter VALUE is incorrect (e.g. invalid enum, ungrounded value, unsupported model capability), assign near-zero scores (0-2) to value_accuracy and CASCADE near-zero scores to type_compliance, format_compliance, and relevancy.
3. A critical parameter error should collapse the overall arguments score, not cost a fraction of a point.

Return JSON in this EXACT structure:
{{
  "usage": {{
    "necessity": <0-10: Was tool calling necessary for this request? 10=yes, 0=unnecessary tool use>,
    "overuse_detection": <0-10: Did the agent call redundant tools? 0=no overuse, 10=severe overuse>
  }},
  "selection": {{
    "correctness": <0-10: Are the selected tools appropriate for the task?>,
    "specificity": <0-10: Did the agent choose the most specific tool available?>,
    "completeness": <0-10: Were all necessary tools selected to fulfill the prompt?>
  }},
  "ordering": {{
    "not_applicable": <true if only 1 tool was called, false if multiple tools were called>,
    "sequence_logic": <0-10: Logical progression of calls>,
    "dependency_handling": <0-10: Proper passing of outputs to subsequent tool inputs>,
    "execution_efficiency": <0-10: Efficient ordering without redundant steps>
  }},
  "arguments": {{
    "completeness": <0-10: Are all required and necessary parameters provided?>,
    "name_accuracy": <0-10: Do all parameter names exactly match the tool schema?>,
    "value_accuracy": <0-10: Are all parameter values correct and grounded in prompt/context?>,
    "type_compliance": <0-10: Do parameter types match schema types (string, number, array, boolean)?>,
    "format_compliance": <0-10: Do formats (enums, URIs, dates) adhere to constraints?>,
    "relevancy": <0-10: Are provided parameters relevant to the prompt?>
  }},
  "failures": [<list of failure categories identified, e.g. "argument_name", "argument_value", "argument_completeness", "selection", "ordering", "capability_violation">],
  "rationale": "<concise explanation of the score and any detected errors>"
}}"""

COHERENCE_JUDGE_PROMPT = """You are an expert evaluator assessing the conversational coherence of an agentic interaction.

Transcript:
{transcript}

Score the transcript across these 5 dimensions on a 1-3 scale (1=poor, 2=adequate, 3=excellent):
- logical_flow: Natural progression of conversation
- completeness: Fully addresses user needs
- conciseness: Free of unnecessary filler
- topic_relevance: Stays on topic
- context_retention: Retains facts across turns (set not_applicable=true if single-turn)

Return JSON:
{{
  "logical_flow": <1-3>,
  "completeness": <1-3>,
  "conciseness": <1-3>,
  "topic_relevance": <1-3>,
  "context_retention": {{
    "not_applicable": <true/false>,
    "score": <1-3 if applicable>
  }},
  "manifestations": [<list of coherence defects if any>],
  "rationale": "<explanation>"
}}"""


# --------------------------------------------------------------------------
# Prompt Builders
# --------------------------------------------------------------------------

def build_tool_summary(tools_or_interpretations: List[Any]) -> str:
    """Builds formatted markdown tool summary for prompt injection."""
    if not tools_or_interpretations:
        return ""

    lines = []
    for item in tools_or_interpretations:
        if isinstance(item, ToolDefinition) or (isinstance(item, dict) and ("parameters" in item or "inputSchema" in item)):
            t_def = ToolDefinition.from_mcp_tool(item) if isinstance(item, dict) else item
            lines.append(f"### Tool: `{t_def.name}`")
            lines.append(f"- **Description**: {t_def.description or 'No description'}")
            if not t_def.parameters:
                lines.append("- **Parameters**: None")
            else:
                lines.append("- **Parameters**:")
                for p_name, p in t_def.parameters.items():
                    req_str = "REQUIRED" if p.required else "optional"
                    p_type = p.type or "string"
                    desc = f": {p.description}" if p.description else ""
                    enum_str = f" [Enum: {', '.join(str(e) for e in p.enum)}]" if p.enum else ""
                    lines.append(f"  - `{p_name}` ({p_type}, {req_str}){desc}{enum_str}")
            if t_def.capabilities:
                lines.append(f"- **Capabilities**: {json.dumps(t_def.capabilities)}")
            lines.append("")
        elif hasattr(item, "tool_name"):
            # ToolInterpretation object
            lines.append(f"### Tool: `{item.tool_name}`")
            lines.append(f"- **What it does**: {item.what_it_does}")
            lines.append(f"- **What it needs**: {item.what_it_needs}")
            lines.append(f"- **Why it is used**: {item.why_its_used}")
            if item.enterprise_context:
                lines.append(f"- **Context**: {', '.join(item.enterprise_context)}")
            lines.append("")
        elif isinstance(item, dict):
            lines.append(f"### Tool: `{item.get('tool_name', item.get('name', 'unknown'))}`")
            lines.append(f"- **What it does**: {item.get('what_it_does', item.get('description', ''))}")
            lines.append(f"- **What it needs**: {item.get('what_it_needs', '')}")
            lines.append("")

    return "\n".join(lines).strip()


def build_stage1_prompt(
    tool: Union[ToolDefinition, Dict[str, Any]],
    capabilities: Optional[Dict[str, Any]] = None,
) -> str:
    """Builds prompt for Stage 1: Tool Interpretation."""
    t_dict = tool.to_dict() if hasattr(tool, "to_dict") else dict(tool)
    if capabilities:
        t_dict["capabilities"] = capabilities
    return STAGE1_TOOL_INTERPRETATION.format(tool_info=json.dumps(t_dict, indent=2))


def build_stage2_prompt(
    interpretations: List[Any], n_tools: int, tier: str = "simple"
) -> str:
    """Builds prompt for Stage 2: Scenario Generation."""
    summary_str = build_tool_summary(interpretations)
    if tier == "complex":
        tmpl = STAGE2_COMPLEX
    elif tier == "boundary":
        tmpl = STAGE2_BOUNDARY
    else:
        tmpl = STAGE2_SIMPLE
    return tmpl.format(tool_summary=summary_str, N=n_tools)


def build_stage3_prompt(
    scenario: Any,
    example_outputs: Optional[Dict[str, Any]] = None,
    tool_summary: str = "",
) -> str:
    """Builds prompt for Stage 3: Mock Output Generation."""
    if isinstance(scenario, dict):
        title = scenario.get("title", "Untitled")
        prompt_text = scenario.get("prompt", "")
        workflow = scenario.get("agent_workflow", [])
    elif hasattr(scenario, "title"):
        title = scenario.title
        prompt_text = scenario.prompt
        workflow = scenario.agent_workflow
    else:
        title = str(scenario)
        prompt_text = str(scenario)
        workflow = []

    wf_list = [w.to_dict() if hasattr(w, "to_dict") else w for w in workflow]

    if not example_outputs:
        seed_str = "No prior reference outputs provided (Grounding: low/synthetic)"
    else:
        seed_str = json.dumps(example_outputs, indent=2)

    return STAGE3_MOCK_OUTPUT.format(
        tool_summary=tool_summary or "{}",
        seed_outputs=seed_str,
        title=title,
        prompt=prompt_text,
        workflow=json.dumps(wf_list, indent=2),
    )


def build_stage4_prompt(
    scenario: Any, mock_workflow: Optional[List[Dict[str, Any]]] = None
) -> str:
    """Builds prompt for Stage 4: Multi-Turn Conversation Expansion."""
    if isinstance(scenario, str):
        title = scenario
        prompt_text = scenario
        followup = "Continue and expand workflow"
    elif isinstance(scenario, dict):
        title = scenario.get("title", "Untitled")
        prompt_text = scenario.get("prompt", "")
        followup = scenario.get("agent_followup", "Continue and expand workflow")
    else:
        title = getattr(scenario, "title", "Untitled")
        prompt_text = getattr(scenario, "prompt", "")
        followup = getattr(scenario, "agent_followup", "Continue and expand workflow")

    wf = mock_workflow or []
    return STAGE4_MULTI_TURN.format(
        title=title,
        prompt=prompt_text,
        mock_workflow=json.dumps(wf, indent=2),
        followup=followup,
    )
