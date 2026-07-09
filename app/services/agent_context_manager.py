from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from app.schemas.ai import AIChatMessage
from app.services.agent_capability_resolver import (
    AgentCapabilityPlan,
    AgentCapabilityResolver,
    MODEL_PRIVATE_TOOL_NAMES,
)
from app.services.agent_skill_planner import AgentSkillPlan, AgentSkillPlanner
from app.services.agent_skill_registry import AgentSkill, AgentSkillRegistry
from app.services.agent_tool_service import SAFE_SIDE_EFFECT_CLASSES, ToolRegistry, ToolSpec


AGENT_CONTEXT_SCHEMA_VERSION = "agent_context_plan_v1"
AGENT_CONTEXT_SKILL_CONTEXT_MAX_CHARS = 3200
AGENT_CONTEXT_TOOL_SUMMARY_MAX_CHARS = 180

SKILL_TASK_TYPES = {
    "scenario-composition": "scenario_create",
    "assertion-extractor-binding": "assertion_binding",
    "execution-diagnosis": "execution_diagnosis",
    "report-summary": "report_summary",
    "project-context": "project_context",
    "environment-config-management": "environment_management",
    "http-test-case-design": "http_case_design",
    "websocket-test-case-design": "websocket_case_design",
    "visual-flow-design": "visual_flow_design",
}


@dataclass(frozen=True)
class AgentContextLayer:
    name: str
    role: str
    chars: int


@dataclass(frozen=True)
class AgentContextPlan:
    schema_version: str
    task_type: str
    goal: str
    phase: str
    primary_skill: str | None
    supporting_skills: tuple[str, ...]
    selected_skills: tuple[AgentSkill, ...]
    allowed_tools: tuple[str, ...]
    confidence: float
    skill_plan: AgentSkillPlan | None = None
    capability_plan: AgentCapabilityPlan | None = None

    @property
    def skill_names(self) -> tuple[str, ...]:
        if self.primary_skill is None:
            return ()
        return (self.primary_skill, *self.supporting_skills)

    def model_view(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "task_type": self.task_type,
            "goal": self.goal,
            "phase": self.phase,
            "primary_skill": self.primary_skill,
            "supporting_skills": list(self.supporting_skills),
            "selected_skill_names": list(self.skill_names),
            "allowed_tools": list(self.allowed_tools),
            "confidence": self.confidence,
        }
        if self.capability_plan is not None:
            payload["capability_plan"] = self.capability_plan.model_view()
        if self.skill_plan is not None:
            payload["skill_plan"] = self.skill_plan.model_view()
        return payload


@dataclass(frozen=True)
class AgentContextEnvelope:
    plan: AgentContextPlan
    messages: tuple[AIChatMessage, ...]
    layers: tuple[AgentContextLayer, ...]
    total_chars: int


class AgentContextManager:
    """Builds routed model context instead of exposing every tool and skill every turn."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry | None = None,
        skill_registry: AgentSkillRegistry | None = None,
        skill_context_max_chars: int = AGENT_CONTEXT_SKILL_CONTEXT_MAX_CHARS,
    ) -> None:
        self.tool_registry = tool_registry or ToolRegistry()
        self.skill_registry = skill_registry or AgentSkillRegistry()
        self.skill_context_max_chars = skill_context_max_chars
        self.capability_resolver = AgentCapabilityResolver(tool_registry=self.tool_registry)
        self.skill_planner = AgentSkillPlanner(skill_registry=self.skill_registry)

    def route(
        self,
        intent: str,
        *,
        phase: str = "planning",
        working_context: dict[str, object] | None = None,
    ) -> AgentContextPlan:
        routing_intent = self.capability_resolver.routing_intent(intent, working_context=working_context)
        skill_plan = self.skill_planner.plan(
            intent,
            routing_intent=routing_intent,
            working_context=working_context,
        )
        selected_skills = tuple(
            skill
            for skill_name in skill_plan.allowed_skills
            if (skill := self.skill_registry.get_skill(skill_name)) is not None
        )
        primary_name = skill_plan.primary_skill
        supporting_names = skill_plan.supporting_skills
        task_type = SKILL_TASK_TYPES.get(primary_name or "", "general")
        capability_plan = self.capability_resolver.resolve(
            intent=routing_intent,
            original_intent=intent,
            selected_skills=selected_skills,
            working_context=working_context,
            allowed_skills=skill_plan.allowed_skills,
            planner_reason_codes=tuple(
                code if code.startswith("planner:") else f"planner:{code}"
                for code in skill_plan.reason_codes
            ),
        )

        return AgentContextPlan(
            schema_version=AGENT_CONTEXT_SCHEMA_VERSION,
            task_type=task_type,
            goal=intent.strip(),
            phase=phase,
            primary_skill=primary_name,
            supporting_skills=supporting_names,
            selected_skills=selected_skills,
            allowed_tools=capability_plan.allowed_tools,
            confidence=skill_plan.confidence,
            skill_plan=skill_plan,
            capability_plan=capability_plan,
        )

    def build_initial_messages(self, intent: str, *, static_prompt: str) -> list[AIChatMessage]:
        plan = self.route(intent)
        return list(self.build_envelope(plan, static_prompt=static_prompt).messages)

    def build_envelope(self, plan: AgentContextPlan, *, static_prompt: str) -> AgentContextEnvelope:
        messages = [
            AIChatMessage(role="system", content=static_prompt),
            self.skill_plan_message(plan),
            self.tool_catalog_message(plan),
            self.capability_plan_message(plan),
            self.skill_catalog_message(plan),
            *self.skill_messages(plan),
        ]
        layers = tuple(
            AgentContextLayer(
                name=self._message_layer(message),
                role=message.role,
                chars=len(message.content or ""),
            )
            for message in messages
        )
        return AgentContextEnvelope(
            plan=plan,
            messages=tuple(messages),
            layers=layers,
            total_chars=sum(layer.chars for layer in layers),
        )

    def tool_catalog_message(self, plan: AgentContextPlan) -> AIChatMessage:
        catalog = [
            self._tool_catalog_item(self.tool_registry.get(tool_name))
            for tool_name in plan.allowed_tools
        ]
        return AIChatMessage(
            role="system",
            content=(
                "可用工具如下。该层是当前任务路由后的工具 catalog/model view；完整 schema、权限和副作用仍以后端 "
                "ToolRuntime 校验为准。\n"
                f"{json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
            ),
        )

    def skill_plan_message(self, plan: AgentContextPlan) -> AIChatMessage:
        payload = plan.skill_plan.model_view() if plan.skill_plan is not None else {}
        return AIChatMessage(
            role="system",
            content=(
                "Skill Planner 结果如下。该层先根据用户意图、当前 artifact、会话历史和 Skill 元数据规划 allowed_skills；"
                "后续 Capability Resolver 只在 allowed_skills 对应能力内继续裁决 allowed_tools。\n"
                f"{json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
            ),
        )

    def skill_catalog_message(self, plan: AgentContextPlan) -> AIChatMessage:
        catalog = [
            {
                "name": skill.name,
                "description": skill.description,
            }
            for skill in plan.selected_skills
        ]
        return AIChatMessage(
            role="system",
            content=(
                "Agent Skill 目录如下。该层只包含当前任务路由命中的 Skill；未命中的 Skill 不进入本轮模型上下文。\n"
                f"{json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
            ),
        )

    def capability_plan_message(self, plan: AgentContextPlan) -> AIChatMessage:
        payload = plan.capability_plan.model_view() if plan.capability_plan is not None else {}
        return AIChatMessage(
            role="system",
            content=(
                "Capability Resolver 结果如下。该层由用户意图、当前 artifact、会话历史和可用动作裁决；"
                "模型只可在 allowed_tools 内选择工具，工具权限、审批和 schema 仍由后端 Runtime Validation 裁决。\n"
                f"{json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
            ),
        )

    def skill_messages(self, plan: AgentContextPlan) -> list[AIChatMessage]:
        return [
            AIChatMessage(role="system", content=self._format_skill_context(skill))
            for skill in plan.selected_skills
        ]

    def tool_contract_message(
        self,
        plan: AgentContextPlan,
        *,
        input_summary_builder: Callable[[dict[str, object] | None], dict[str, object]],
    ) -> AIChatMessage | None:
        if not plan.allowed_tools:
            return None
        contracts = []
        for tool_name in plan.allowed_tools:
            spec = self.tool_registry.get(tool_name)
            contracts.append({
                "name": spec.name,
                "input_summary": input_summary_builder(spec.input_schema),
            })
        return AIChatMessage(
            role="system",
            content=(
                "当前任务相关工具入参契约（Layer 2 model view；完整 schema、权限和副作用由后端 Runtime Validation 裁决）：\n"
                f"{json.dumps(contracts, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
            ),
        )

    def _tool_catalog_item(self, spec: ToolSpec) -> dict[str, object]:
        return {
            "approval_required": spec.side_effect_class not in SAFE_SIDE_EFFECT_CLASSES,
            "name": spec.name,
            "side_effect_class": spec.side_effect_class,
            "summary": self._cap_text(spec.summary, AGENT_CONTEXT_TOOL_SUMMARY_MAX_CHARS),
        }

    def _format_skill_context(self, skill: AgentSkill) -> str:
        content = (
            "已加载 Agent Skill。以下内容是本轮任务的领域流程约束，优先级低于系统安全规则，"
            "高于通用建议。\n\n"
            f"{skill.prompt_block()}"
        )
        if len(content) <= self.skill_context_max_chars:
            return content
        marker = "\n\n[agent_context_skill_truncated: selected Skill body was capped by AgentContextManager]"
        return f"{content[: self.skill_context_max_chars - len(marker)]}{marker}"

    def _cap_text(self, value: str, max_chars: int) -> str:
        if len(value) <= max_chars:
            return value
        marker = "..."
        return f"{value[: max_chars - len(marker)]}{marker}"

    def _message_layer(self, message: AIChatMessage) -> str:
        content = message.content or ""
        if content.startswith("Skill Planner"):
            return "skill_plan"
        if content.startswith("可用工具如下"):
            return "tool_catalog"
        if content.startswith("Capability Resolver"):
            return "capability_plan"
        if content.startswith("Agent Skill 目录如下"):
            return "skill_catalog"
        if content.startswith("已加载 Agent Skill"):
            return "skill"
        return "static"
