"""4-Stage Spec-Driven Synthetic Evaluation Pipeline (arXiv:2608.26133)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
import os
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union

from .clients import BaseLLMClient, GeminiClient, MockClient, create_client
from .models import ServerSpec, ToolCall, ToolDefinition, ToolParameter
from .prompts import (
    build_stage1_prompt,
    build_stage2_prompt,
    build_stage3_prompt,
    build_stage4_prompt,
    build_tool_summary,
)

logger = logging.getLogger("agent_seer.pipeline")


# --------------------------------------------------------------------------
# Pipeline Data Models
# --------------------------------------------------------------------------

@dataclass
class ToolInterpretation:
    tool_name: str
    what_it_does: str
    what_it_needs: str
    why_its_used: str
    enterprise_context: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "what_it_does": self.what_it_does,
            "what_it_needs": self.what_it_needs,
            "why_its_used": self.why_its_used,
            "enterprise_context": list(self.enterprise_context),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolInterpretation:
        ctx = data.get("enterprise_context", [])
        if isinstance(ctx, str):
            ctx = [ctx] if ctx else []
        elif not isinstance(ctx, list):
            ctx = [str(ctx)]
        return cls(
            tool_name=data.get("tool_name", ""),
            what_it_does=data.get("what_it_does", ""),
            what_it_needs=data.get("what_it_needs", ""),
            why_its_used=data.get("why_its_used", ""),
            enterprise_context=ctx,
        )

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class AgentWorkflowStep:
    function_name: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    quick_explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "function_name": self.function_name,
            "parameters": dict(self.parameters),
            "quick_explanation": self.quick_explanation,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentWorkflowStep:
        fname = data.get("function_name", data.get("name", ""))
        params = data.get("parameters", data.get("arguments", {}))
        return cls(
            function_name=fname,
            parameters=dict(params) if isinstance(params, dict) else {},
            quick_explanation=data.get("quick_explanation", ""),
        )

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


@dataclass
class Scenario:
    title: str
    prompt: str
    agent_workflow: List[AgentWorkflowStep] = field(default_factory=list)
    novelty_reason: str = ""
    agent_followup: str = ""
    tier: str = "simple"
    category: str = "General"
    expected_tools: Optional[List[str]] = None
    injected_fault: Optional[str] = None
    expected_taxonomy: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "title": self.title,
            "prompt": self.prompt,
            "agent_workflow": [w.to_dict() for w in self.agent_workflow],
            "novelty_reason": self.novelty_reason,
            "agent_followup": self.agent_followup,
            "tier": self.tier,
            "category": self.category,
        }
        if self.expected_tools is not None:
            d["expected_tools"] = self.expected_tools
        if self.injected_fault is not None:
            d["injected_fault"] = self.injected_fault
        if self.expected_taxonomy is not None:
            d["expected_taxonomy"] = self.expected_taxonomy
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Scenario:
        wf = [
            w if isinstance(w, AgentWorkflowStep) else AgentWorkflowStep.from_dict(w)
            for w in data.get("agent_workflow", [])
        ]
        return cls(
            title=data.get("title", ""),
            prompt=data.get("prompt", ""),
            agent_workflow=wf,
            novelty_reason=data.get("novelty_reason", ""),
            agent_followup=data.get("agent_followup", ""),
            tier=data.get("tier", "simple"),
            category=data.get("category", "General"),
            expected_tools=data.get("expected_tools"),
            injected_fault=data.get("injected_fault"),
            expected_taxonomy=data.get("expected_taxonomy"),
        )

    def __getitem__(self, item: str) -> Any:
        if item == "agent_workflow":
            return [w.to_dict() for w in self.agent_workflow]
        return getattr(self, item)


class ScenarioCollection:
    """Collection of scenarios supporting indexing, iteration, and dual category access."""

    def __init__(
        self,
        scenarios_or_categories: Optional[Union[List[Scenario], List[Dict[str, Any]], Dict[str, Any]]] = None,
        categories: Optional[List[Dict[str, Any]]] = None,
        scenarios: Optional[List[Scenario]] = None,
    ):
        self.scenarios: List[Scenario] = []
        self._categories: Optional[List[Dict[str, Any]]] = categories

        if scenarios is not None:
            self.scenarios = list(scenarios)
        elif scenarios_or_categories:
            if isinstance(scenarios_or_categories, dict) and "categories" in scenarios_or_categories:
                self._categories = scenarios_or_categories["categories"]
                for cat in self._categories:
                    cat_name = cat.get("category", "General")
                    for sc in cat.get("scenarios", []):
                        sc_obj = sc if isinstance(sc, Scenario) else Scenario.from_dict(sc)
                        sc_obj.category = cat_name
                        self.scenarios.append(sc_obj)
            elif isinstance(scenarios_or_categories, list):
                for item in scenarios_or_categories:
                    if isinstance(item, Scenario):
                        self.scenarios.append(item)
                    elif isinstance(item, dict):
                        self.scenarios.append(Scenario.from_dict(item))

    @property
    def categories(self) -> List[Dict[str, Any]]:
        if self._categories is not None:
            return self._categories
        # Group by category dynamically
        cat_map: Dict[str, List[Dict[str, Any]]] = {}
        for s in self.scenarios:
            cat_map.setdefault(s.category, []).append(s.to_dict())
        return [{"category": k, "scenarios": v} for k, v in cat_map.items()]

    def __len__(self) -> int:
        return len(self.scenarios)

    def __getitem__(self, index_or_key: Union[int, str]) -> Any:
        if isinstance(index_or_key, int):
            return self.scenarios[index_or_key]
        if index_or_key == "categories":
            return self.categories
        if index_or_key == "scenarios":
            return self.scenarios
        raise KeyError(index_or_key)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "categories":
            return self.categories
        if key == "scenarios":
            return self.scenarios
        return default

    def __iter__(self) -> Iterator[Scenario]:
        return iter(self.scenarios)

    def __contains__(self, item: str) -> bool:
        return item in ("categories", "scenarios")

    def to_dict(self) -> Dict[str, Any]:
        return {"categories": self.categories, "scenarios": [s.to_dict() for s in self.scenarios]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScenarioCollection:
        return cls(data)


@dataclass
class GroundedMockCall:
    function_name: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    quick_explanation: str = ""
    mock_output: Any = None
    confidence: str = "medium"
    expected_response: Any = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "function_name": self.function_name,
            "parameters": dict(self.parameters),
            "quick_explanation": self.quick_explanation,
            "mock_output": self.mock_output,
            "confidence": self.confidence,
        }
        if self.expected_response is not None:
            d["expected_response"] = self.expected_response
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GroundedMockCall:
        return cls(
            function_name=data.get("function_name", data.get("name", "")),
            parameters=dict(data.get("parameters", data.get("arguments", {}))),
            quick_explanation=data.get("quick_explanation", ""),
            mock_output=data.get("mock_output"),
            confidence=data.get("confidence", "medium"),
            expected_response=data.get("expected_response"),
        )

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


@dataclass
class GroundedMockScenario:
    scenario_title: str
    tier: str
    scenario: Scenario
    mock_workflow: List[GroundedMockCall] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_title": self.scenario_title,
            "tier": self.tier,
            "scenario": self.scenario.to_dict(),
            "mock_workflow": [m.to_dict() for m in self.mock_workflow],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GroundedMockScenario:
        sc_data = data.get("scenario", {})
        sc_obj = sc_data if isinstance(sc_data, Scenario) else Scenario.from_dict(sc_data)
        mocks = [
            m if isinstance(m, GroundedMockCall) else GroundedMockCall.from_dict(m)
            for m in data.get("mock_workflow", [])
        ]
        return cls(
            scenario_title=data.get("scenario_title", sc_obj.title),
            tier=data.get("tier", "simple"),
            scenario=sc_obj,
            mock_workflow=mocks,
        )

    def __getitem__(self, item: str) -> Any:
        if item == "mock_workflow":
            return [m.to_dict() for m in self.mock_workflow]
        return getattr(self, item)


@dataclass
class ConversationTurn:
    turn_index: int
    user_message: str
    agent_tool_calls: List[Any] = field(default_factory=list)
    tool_responses: List[Dict[str, Any]] = field(default_factory=list)
    agent_response: str = ""

    def to_dict(self) -> Dict[str, Any]:
        calls = []
        for c in self.agent_tool_calls:
            if hasattr(c, "to_dict"):
                calls.append(c.to_dict())
            elif isinstance(c, dict):
                calls.append(c)
        return {
            "turn_index": self.turn_index,
            "user_message": self.user_message,
            "agent_tool_calls": calls,
            "tool_responses": self.tool_responses,
            "agent_response": self.agent_response,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ConversationTurn:
        raw_calls = data.get("agent_tool_calls", [])
        calls = []
        for c in raw_calls:
            if isinstance(c, ToolCall):
                calls.append(c)
            elif isinstance(c, dict):
                calls.append(ToolCall.from_dict(c))
        return cls(
            turn_index=data.get("turn_index", 1),
            user_message=data.get("user_message", ""),
            agent_tool_calls=calls,
            tool_responses=data.get("tool_responses", []),
            agent_response=data.get("agent_response", ""),
        )


@dataclass
class MultiTurnTranscript:
    scenario_title: str
    tier: str = "simple"
    turns: List[ConversationTurn] = field(default_factory=list)
    held_out_workflow: Optional[List[AgentWorkflowStep]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "scenario_title": self.scenario_title,
            "tier": self.tier,
            "turns": [t.to_dict() for t in self.turns],
        }
        if self.held_out_workflow is not None:
            d["held_out_workflow"] = [w.to_dict() for w in self.held_out_workflow]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MultiTurnTranscript:
        raw_turns = data.get("turns", [])
        turns = [t if isinstance(t, ConversationTurn) else ConversationTurn.from_dict(t) for t in raw_turns]
        raw_hw = data.get("held_out_workflow")
        hw = None
        if raw_hw is not None:
            hw = [w if isinstance(w, AgentWorkflowStep) else AgentWorkflowStep.from_dict(w) for w in raw_hw]
        return cls(
            scenario_title=data.get("scenario_title", ""),
            tier=data.get("tier", "simple"),
            turns=turns,
            held_out_workflow=hw,
        )

    def to_text(self) -> str:
        """Formats multi-turn transcript into human-readable text."""
        lines = [f"=== Transcript: {self.scenario_title} ==="]
        for turn in self.turns:
            lines.append(f"\nTurn {turn.turn_index}:")
            lines.append(f"USER: {turn.user_message}")
            if turn.agent_tool_calls:
                call_strs = []
                for c in turn.agent_tool_calls:
                    c_name = getattr(c, "name", c.get("name", c.get("function_name", ""))) if isinstance(c, dict) else getattr(c, "name", "")
                    c_args = getattr(c, "arguments", c.get("arguments", c.get("parameters", {}))) if isinstance(c, dict) else getattr(c, "arguments", {})
                    arg_pairs = ", ".join(f"{k}={repr(v)}" for k, v in c_args.items())
                    call_strs.append(f"{c_name}({arg_pairs})")
                lines.append(f"AGENT TOOL CALLS: {', '.join(call_strs)}")
            if turn.agent_response:
                lines.append(f"ASSISTANT: {turn.agent_response}")
        return "\n".join(lines).strip()


@dataclass
class SyntheticHarness:
    server_name: str = ""
    interpretations: List[ToolInterpretation] = field(default_factory=list)
    scenarios: List[Scenario] = field(default_factory=list)
    mock_scenarios: List[GroundedMockScenario] = field(default_factory=list)
    transcripts: List[MultiTurnTranscript] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def grounded_mocks(self) -> List[GroundedMockScenario]:
        return self.mock_scenarios

    @property
    def multi_turn_transcripts(self) -> List[MultiTurnTranscript]:
        return self.transcripts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "server_name": self.server_name,
            "interpretations": [i.to_dict() for i in self.interpretations],
            "scenarios": [s.to_dict() for s in self.scenarios],
            "mock_scenarios": [g.to_dict() for g in self.mock_scenarios],
            "transcripts": [m.to_dict() for m in self.transcripts],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SyntheticHarness:
        interps = [i if isinstance(i, ToolInterpretation) else ToolInterpretation.from_dict(i) for i in data.get("interpretations", [])]
        scenarios = [s if isinstance(s, Scenario) else Scenario.from_dict(s) for s in data.get("scenarios", [])]
        mocks = [m if isinstance(m, GroundedMockScenario) else GroundedMockScenario.from_dict(m) for m in data.get("mock_scenarios", [])]
        transcripts = [t if isinstance(t, MultiTurnTranscript) else MultiTurnTranscript.from_dict(t) for t in data.get("transcripts", [])]
        return cls(
            server_name=data.get("server_name", ""),
            interpretations=interps,
            scenarios=scenarios,
            mock_scenarios=mocks,
            transcripts=transcripts,
            metadata=data.get("metadata", {}),
        )

    def export_json(self, output_dir: str) -> Dict[str, str]:
        """Exports all harness artifacts to JSON files in the specified directory."""
        os.makedirs(output_dir, exist_ok=True)
        paths = {
            "interpretations": os.path.join(output_dir, "interpretations.json"),
            "scenarios": os.path.join(output_dir, "scenarios.json"),
            "mock_scenarios": os.path.join(output_dir, "mock_scenarios.json"),
            "transcripts": os.path.join(output_dir, "transcripts.json"),
            "metadata": os.path.join(output_dir, "metadata.json"),
            "stage1": os.path.join(output_dir, "stage1_interpretations.json"),
            "stage2": os.path.join(output_dir, "stage2_scenarios.json"),
            "stage3": os.path.join(output_dir, "stage3_mock_outputs.json"),
            "stage4": os.path.join(output_dir, "stage4_transcripts.json"),
            "harness": os.path.join(output_dir, "synthetic_harness.json"),
        }
        interps_data = [i.to_dict() for i in self.interpretations]
        scenarios_data = [s.to_dict() for s in self.scenarios]
        mocks_data = [m.to_dict() for m in self.mock_scenarios]
        transcripts_data = [t.to_dict() for t in self.transcripts]

        for p in (paths["interpretations"], paths["stage1"]):
            with open(p, "w", encoding="utf-8") as f:
                json.dump(interps_data, f, indent=2)
        for p in (paths["scenarios"], paths["stage2"]):
            with open(p, "w", encoding="utf-8") as f:
                json.dump(scenarios_data, f, indent=2)
        for p in (paths["mock_scenarios"], paths["stage3"]):
            with open(p, "w", encoding="utf-8") as f:
                json.dump(mocks_data, f, indent=2)
        for p in (paths["transcripts"], paths["stage4"]):
            with open(p, "w", encoding="utf-8") as f:
                json.dump(transcripts_data, f, indent=2)
        with open(paths["metadata"], "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2)
        with open(paths["harness"], "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

        return paths


# --------------------------------------------------------------------------
# Pipeline Implementation
# --------------------------------------------------------------------------

class SyntheticEvalPipeline:
    """Executes the 4-stage synthetic eval generation pipeline."""

    def __init__(
        self,
        client: Optional[Any] = None,
        offline: bool = False,
        model_name: str = "gemini-2.5-flash-lite",
    ):
        self.offline = offline
        self.model_name = model_name
        self.client = client or (MockClient() if offline else GeminiClient())

    def interpret_spec(
        self, tools: Union[List[ToolDefinition], List[Dict[str, Any]]]
    ) -> List[ToolInterpretation]:
        """Stage 1: Tool Interpretation."""
        results = []
        for t in tools:
            t_def = ToolDefinition.from_mcp_tool(t) if isinstance(t, dict) else t
            if not t_def.parameters:
                req_desc = "No parameters required."
            else:
                req_names = [pname for pname, p in t_def.parameters.items() if p.required]
                opt_names = [pname for pname, p in t_def.parameters.items() if not p.required]
                parts = []
                if req_names:
                    parts.append(f"Required parameters: {', '.join(req_names)}")
                if opt_names:
                    parts.append(f"Optional parameters: {', '.join(opt_names)}")
                req_desc = "; ".join(parts) or f"Parameters: {list(t_def.parameters.keys())}"

            if self.offline:
                results.append(
                    ToolInterpretation(
                        tool_name=t_def.name,
                        what_it_does=t_def.description or f"Executes {t_def.name}",
                        what_it_needs=req_desc,
                        why_its_used=f"Automated tool calling for {t_def.name}",
                        enterprise_context=["Media Production", "Enterprise Automation"],
                    )
                )
                continue

            try:
                prompt = build_stage1_prompt(t_def)
                res = self.client.generate_json(prompt, model=self.model_name, temperature=0.7)
                if not isinstance(res, dict) or "what_it_does" not in res:
                    raise ValueError("Malformed Stage 1 response")
                ctx = res.get("enterprise_context", [])
                if isinstance(ctx, str):
                    ctx = [ctx]
                results.append(
                    ToolInterpretation(
                        tool_name=res.get("tool_name", t_def.name),
                        what_it_does=res.get("what_it_does", t_def.description or ""),
                        what_it_needs=res.get("what_it_needs", req_desc),
                        why_its_used=res.get("why_its_used", ""),
                        enterprise_context=ctx or ["Enterprise"],
                    )
                )
            except Exception as e:
                logger.warning(f"Stage 1 fallback on tool {t_def.name}: {e}")
                results.append(
                    ToolInterpretation(
                        tool_name=t_def.name,
                        what_it_does=t_def.description or f"Executes {t_def.name}",
                        what_it_needs=req_desc,
                        why_its_used=f"Automated tool calling for {t_def.name}",
                        enterprise_context=["Enterprise"],
                    )
                )
        return results

    def generate_scenarios(
        self,
        interpretations: List[ToolInterpretation],
        tools: Optional[List[ToolDefinition]] = None,
        tiers: Optional[List[str]] = None,
    ) -> ScenarioCollection:
        """Stage 2: Scenario Generation with 100% tool coverage."""
        selected_tiers = tiers or ["simple", "complex"]
        all_scenarios: List[Scenario] = []
        all_categories: List[Dict[str, Any]] = []

        all_tool_defs = tools or []
        if not all_tool_defs and interpretations:
            all_tool_defs = [
                ToolDefinition(name=i.tool_name, description=i.what_it_does)
                for i in interpretations
            ]

        if self.offline:
            if not all_tool_defs:
                return ScenarioCollection(categories=[], scenarios=[])

            for tier in selected_tiers:
                if tier == "complex" and len(all_tool_defs) >= 2:
                    steps = []
                    for idx, t in enumerate(all_tool_defs):
                        in_uri = "gs://mock-bucket/assets/initial.png" if idx == 0 else f"gs://mock-bucket/step_{idx}_out.mp4"
                        p_vals = {}
                        for pname, p in t.parameters.items():
                            if p.required:
                                if "uri" in pname or "bucket" in pname:
                                    p_vals[pname] = in_uri
                                elif p.enum:
                                    p_vals[pname] = p.enum[0]
                                else:
                                    p_vals[pname] = "composite test prompt"
                        steps.append(
                            AgentWorkflowStep(
                                function_name=t.name,
                                parameters=p_vals,
                                quick_explanation=f"Chained execution step {idx+1}",
                            )
                        )
                    sc = Scenario(
                        title="Composite Multi-Tool Chained Pipeline",
                        prompt="Execute multi-step pipeline with inter-tool dependency passing",
                        agent_workflow=steps,
                        novelty_reason="Chained multi-tool DAG workflow",
                        agent_followup="Extend pipeline execution",
                        tier=tier,
                        category="Chained Pipelines",
                    )
                    all_scenarios.append(sc)
                    all_categories.append({"category": "Chained Pipelines", "scenarios": [sc.to_dict()]})
                else:
                    for t in all_tool_defs:
                        params = {}
                        for pname, p in t.parameters.items():
                            if p.required:
                                if "uri" in pname or "bucket" in pname:
                                    params[pname] = "gs://mock-bucket/assets/image.png"
                                elif p.enum:
                                    params[pname] = p.enum[0]
                                elif p.type == "string":
                                    params[pname] = "test prompt for evaluation"
                                elif p.type in ("integer", "number"):
                                    params[pname] = 1
                                elif p.type == "boolean":
                                    params[pname] = True
                                else:
                                    params[pname] = "val"
                        sc = Scenario(
                            title=f"Execute {t.name}",
                            prompt=f"Please call {t.name} with standard parameters",
                            agent_workflow=[
                                AgentWorkflowStep(
                                    function_name=t.name,
                                    parameters=params,
                                    quick_explanation=f"Calls {t.name}",
                                )
                            ],
                            novelty_reason=f"Exercises {t.name}",
                            agent_followup="Would you like any modifications?",
                            tier=tier,
                            category=f"Single Tool {tier}",
                        )
                        all_scenarios.append(sc)
                        all_categories.append({"category": f"Single Tool {tier}", "scenarios": [sc.to_dict()]})

            return ScenarioCollection(categories=all_categories, scenarios=all_scenarios)

        n_tools = len(interpretations) or len(all_tool_defs)
        for tier in selected_tiers:
            try:
                prompt = build_stage2_prompt(interpretations or all_tool_defs, n_tools=n_tools, tier=tier)
                res = self.client.generate_json(prompt, model=self.model_name, temperature=0.7)
                if not isinstance(res, dict) or "categories" not in res or not isinstance(res["categories"], list):
                    raise ValueError("Malformed Stage 2 JSON response")
                cats = res.get("categories", [])
                all_categories.extend(cats)
                for cat in cats:
                    cat_name = cat.get("category", "General")
                    for sc_data in cat.get("scenarios", []):
                        steps = [
                            AgentWorkflowStep(
                                function_name=s.get("function_name", s.get("name", "")),
                                parameters=s.get("parameters", s.get("arguments", {})),
                                quick_explanation=s.get("quick_explanation", ""),
                            )
                            for s in sc_data.get("agent_workflow", [])
                        ]
                        all_scenarios.append(
                            Scenario(
                                title=sc_data.get("title", "Untitled Scenario"),
                                prompt=sc_data.get("prompt", ""),
                                agent_workflow=steps,
                                novelty_reason=sc_data.get("novelty_reason", ""),
                                agent_followup=sc_data.get("agent_followup", ""),
                                tier=tier,
                                category=cat_name,
                            )
                        )
            except Exception as e:
                logger.warning(f"Stage 2 fallback for tier {tier}: {e}")
                for t in all_tool_defs:
                    sc = Scenario(
                        title=f"Fallback {t.name}",
                        prompt=f"Execute {t.name}",
                        agent_workflow=[AgentWorkflowStep(function_name=t.name, parameters={})],
                        tier=tier,
                        category="Fallback",
                    )
                    all_scenarios.append(sc)
                    all_categories.append({"category": "Fallback", "scenarios": [sc.to_dict()]})

        # Ensure 100% coverage
        covered = {step.function_name for sc in all_scenarios for step in sc.agent_workflow}
        for t in all_tool_defs:
            if t.name not in covered:
                sc = Scenario(
                    title=f"Coverage Guarantee for {t.name}",
                    prompt=f"Run {t.name} to fulfill coverage requirement",
                    agent_workflow=[AgentWorkflowStep(function_name=t.name, parameters={})],
                    tier="simple",
                    category="Coverage Fallback",
                )
                all_scenarios.append(sc)
                all_categories.append({"category": "Coverage Fallback", "scenarios": [sc.to_dict()]})

        return ScenarioCollection(categories=all_categories, scenarios=all_scenarios)

    def generate_mock_outputs(
        self,
        scenarios: List[Scenario],
        seed_outputs: Optional[Dict[str, Any]] = None,
        tool_summary: str = "",
    ) -> List[GroundedMockScenario]:
        """Stage 3: Mock Output Generation with Grounding Tiers."""
        grounded_scenarios = []

        for sc in scenarios:
            if self.offline:
                calls = []
                for step in sc.agent_workflow:
                    seed = (seed_outputs or {}).get(step.function_name)
                    if seed:
                        output = seed
                        conf = "high"
                    else:
                        output = {"status": "success", "function": step.function_name}
                        conf = "medium"
                    calls.append(
                        GroundedMockCall(
                            function_name=step.function_name,
                            parameters=step.parameters,
                            quick_explanation=step.quick_explanation,
                            mock_output=output,
                            confidence=conf,
                        )
                    )
                grounded_scenarios.append(
                    GroundedMockScenario(
                        scenario_title=sc.title,
                        tier=sc.tier,
                        scenario=sc,
                        mock_workflow=calls,
                    )
                )
                continue

            try:
                prompt = build_stage3_prompt(sc, example_outputs=seed_outputs, tool_summary=tool_summary)
                res = self.client.generate_json(prompt, model=self.model_name, temperature=0.0)
                raw_wf = res.get("mock_workflow", []) if isinstance(res, dict) else []
                if not raw_wf:
                    raise ValueError("Empty mock workflow in Stage 3 response")

                mock_list = []
                for item in raw_wf:
                    mock_list.append(
                        GroundedMockCall(
                            function_name=item.get("function_name", ""),
                            parameters=item.get("parameters", {}),
                            quick_explanation=item.get("quick_explanation", ""),
                            mock_output=item.get("mock_output"),
                            confidence=item.get("confidence", "medium"),
                            expected_response=item.get("expected_response"),
                        )
                    )
                grounded_scenarios.append(
                    GroundedMockScenario(
                        scenario_title=sc.title,
                        tier=sc.tier,
                        scenario=sc,
                        mock_workflow=mock_list,
                    )
                )
            except Exception as e:
                logger.warning(f"Stage 3 fallback on scenario '{sc.title}': {e}")
                calls = [
                    GroundedMockCall(
                        function_name=step.function_name,
                        parameters=step.parameters,
                        quick_explanation=step.quick_explanation,
                        mock_output={"status": "success", "function": step.function_name},
                        confidence="medium",
                    )
                    for step in sc.agent_workflow
                ]
                grounded_scenarios.append(
                    GroundedMockScenario(
                        scenario_title=sc.title,
                        tier=sc.tier,
                        scenario=sc,
                        mock_workflow=calls,
                    )
                )

        return grounded_scenarios

    def expand_multi_turn(
        self, grounded_scenarios: List[GroundedMockScenario]
    ) -> List[MultiTurnTranscript]:
        """Stage 4: Multi-Turn Conversation Expansion."""
        transcripts = []

        for gsc in grounded_scenarios:
            if self.offline:
                turn1_calls = [ToolCall(name=m.function_name, arguments=m.parameters) for m in gsc.mock_workflow]
                turn1_resps = [{"tool_name": m.function_name, "output": m.mock_output} for m in gsc.mock_workflow]
                turns = [
                    ConversationTurn(
                        turn_index=1,
                        user_message=gsc.scenario.prompt,
                        agent_tool_calls=turn1_calls,
                        tool_responses=turn1_resps,
                        agent_response=f"Executed {len(gsc.mock_workflow)} tool call(s).",
                    )
                ]
                if gsc.scenario.agent_followup:
                    turns.append(
                        ConversationTurn(
                            turn_index=2,
                            user_message=gsc.scenario.agent_followup,
                            agent_tool_calls=[],
                            tool_responses=[],
                            agent_response="Follow-up complete.",
                        )
                    )
                transcripts.append(MultiTurnTranscript(scenario_title=gsc.scenario_title, tier=gsc.tier, turns=turns))
                continue

            try:
                prompt = build_stage4_prompt(gsc.scenario, [m.to_dict() for m in gsc.mock_workflow])
                res = self.client.generate_json(prompt, model=self.model_name, temperature=0.0)
                raw_turns = res.get("turns", []) if isinstance(res, dict) else []
                if not isinstance(raw_turns, list) or not raw_turns:
                    raise ValueError("Invalid turns structure in Stage 4 response")

                turns = []
                for t in raw_turns:
                    turns.append(
                        ConversationTurn(
                            turn_index=t.get("turn_index", len(turns) + 1),
                            user_message=t.get("user_message", ""),
                            agent_tool_calls=t.get("agent_tool_calls", []),
                            tool_responses=t.get("tool_responses", []),
                            agent_response=t.get("agent_response", ""),
                        )
                    )
                transcripts.append(MultiTurnTranscript(scenario_title=gsc.scenario_title, tier=gsc.tier, turns=turns))
            except Exception as e:
                logger.warning(f"Stage 4 fallback on scenario '{gsc.scenario_title}': {e}")
                turn1_calls = [ToolCall(name=m.function_name, arguments=m.parameters) for m in gsc.mock_workflow]
                turn1_resps = [{"tool_name": m.function_name, "output": m.mock_output} for m in gsc.mock_workflow]
                turns = [
                    ConversationTurn(
                        turn_index=1,
                        user_message=gsc.scenario.prompt,
                        agent_tool_calls=turn1_calls,
                        tool_responses=turn1_resps,
                        agent_response=f"Executed {len(gsc.mock_workflow)} tool call(s).",
                    ),
                    ConversationTurn(
                        turn_index=2,
                        user_message=gsc.scenario.agent_followup or "Follow up",
                        agent_tool_calls=[],
                        tool_responses=[],
                        agent_response="Completed follow-up turn.",
                    ),
                ]
                transcripts.append(MultiTurnTranscript(scenario_title=gsc.scenario_title, tier=gsc.tier, turns=turns))

        return transcripts

    def generate_pipeline(
        self,
        spec: ServerSpec,
        tiers: Optional[List[str]] = None,
        seed_outputs: Optional[Dict[str, Any]] = None,
    ) -> SyntheticHarness:
        """Generates a complete SyntheticHarness from a ServerSpec."""
        if not spec.tools:
            return SyntheticHarness(
                server_name=spec.name,
                interpretations=[],
                scenarios=[],
                mock_scenarios=[],
                transcripts=[],
                metadata={"total_tools": 0},
            )

        interps = self.interpret_spec(spec.tools)
        scenarios_coll = self.generate_scenarios(interps, tools=spec.tools, tiers=tiers)
        grounded = self.generate_mock_outputs(scenarios_coll.scenarios, seed_outputs=seed_outputs)
        transcripts = self.expand_multi_turn(grounded)

        return SyntheticHarness(
            server_name=spec.name,
            interpretations=interps,
            scenarios=scenarios_coll.scenarios,
            mock_scenarios=grounded,
            transcripts=transcripts,
            metadata={"total_tools": len(spec.tools), "tiers": tiers or ["simple", "complex"]},
        )

    def run(
        self,
        spec: Union[ServerSpec, Dict[str, Any]],
        output_dir: Optional[str] = None,
        tiers: Optional[List[str]] = None,
        seed_outputs: Optional[Dict[str, Any]] = None,
    ) -> SyntheticHarness:
        """Executes full evaluation pipeline on ServerSpec and optionally exports to output_dir."""
        if isinstance(spec, dict):
            tools = [t if isinstance(t, ToolDefinition) else ToolDefinition.from_mcp_tool(t) for t in spec.get("tools", [])]
            s_spec = ServerSpec(
                server_name=spec.get("server_name", spec.get("name", "")),
                tools=tools,
                capabilities=spec.get("capabilities", {}),
            )
        else:
            s_spec = spec

        harness = self.generate_pipeline(s_spec, tiers=tiers, seed_outputs=seed_outputs)
        if output_dir:
            harness.export_json(output_dir)
        return harness

    def run_full_pipeline(
        self,
        tools: List[ToolDefinition],
        seed_outputs: Optional[Dict[str, Any]] = None,
    ) -> SyntheticHarness:
        """Executes Stages 1 through 4 sequentially."""
        spec = ServerSpec(name="dynamic_server", tools=tools)
        return self.generate_pipeline(spec, seed_outputs=seed_outputs)


# Class alias
SyntheticHarnessGenerator = SyntheticEvalPipeline
