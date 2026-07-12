from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Literal, Sequence

from pydantic import BaseModel, Field, ValidationError

from app.schemas.ai import AIChatMessage, AIChatRequest
from app.services.ai_service import AIService


AgentEffectScope = Literal["observe", "derive", "draft", "execute", "persist"]

EFFECT_SCOPE_ORDER: dict[str, int] = {
    "observe": 0,
    "derive": 1,
    "draft": 2,
    "execute": 3,
    "persist": 4,
}

SIDE_EFFECT_SCOPE: dict[str, str] = {
    "read_only": "observe",
    "deterministic_compute": "derive",
    "draft_only": "draft",
    "execution_record": "execute",
    "business_update": "persist",
}

CORE_CONTEXT_TOOLS = frozenset({"project.read_context", "tool_result.read_full"})


class AgentPlanningDecision(BaseModel):
    goal: str = Field(min_length=1, max_length=1000)
    action: str = Field(min_length=1, max_length=64)
    target_domain: str | None = Field(default=None, max_length=128)
    source_domains: list[str] = Field(default_factory=list)
    selected_skills: list[str] = Field(min_length=1)
    selected_tools: list[str] = Field(default_factory=list)
    selected_artifact_ids: list[str] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    requested_effect_scope: AgentEffectScope
    confidence: float = Field(ge=0, le=1)
    reason_summary: str = Field(min_length=1, max_length=1000)


@dataclass(frozen=True)
class ValidatedAgentPlanningDecision:
    goal: str
    action: str
    target_domain: str | None
    source_domains: tuple[str, ...]
    selected_skills: tuple[str, ...]
    selected_tools: tuple[str, ...]
    selected_artifact_ids: tuple[str, ...]
    required_facts: tuple[str, ...]
    requested_effect_scope: str
    confidence: float
    reason_summary: str
    source: str = "llm_planning"
    model_requested_effect_scope: str | None = None
    required_effect_scope: str | None = None
    effect_scope_normalized: bool = False

    def model_view(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "action": self.action,
            "target_domain": self.target_domain,
            "source_domains": list(self.source_domains),
            "selected_skills": list(self.selected_skills),
            "selected_tools": list(self.selected_tools),
            "selected_artifact_ids": list(self.selected_artifact_ids),
            "required_facts": list(self.required_facts),
            "requested_effect_scope": self.requested_effect_scope,
            "model_requested_effect_scope": self.model_requested_effect_scope or self.requested_effect_scope,
            "required_effect_scope": self.required_effect_scope or self.requested_effect_scope,
            "effect_scope_normalized": self.effect_scope_normalized,
            "confidence": self.confidence,
            "reason_summary": self.reason_summary,
            "source": self.source,
        }


class AgentPlanningError(ValueError):
    def __init__(self, message: str, *, code: str, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = dict(details or {})
        super().__init__(message)

    def model_view(self) -> dict[str, Any]:
        return {"code": self.code, **self.details}


class AgentPlanningFailed(AgentPlanningError):
    def __init__(self, *, last_error: AgentPlanningError) -> None:
        super().__init__(
            "agent planning failed after one bounded repair attempt",
            code="agent_planning_failed",
            details={"last_error": last_error.model_view()},
        )


class AgentPlanningDecisionService:
    def __init__(self, *, ai_service: AIService | None = None, minimum_confidence: float = 0.55) -> None:
        self.ai_service = ai_service or AIService()
        self.minimum_confidence = minimum_confidence

    def decide(
        self,
        *,
        intent: str,
        conversation_context: dict[str, Any] | None,
        skill_index: Sequence[dict[str, Any]],
        tool_index: Sequence[dict[str, Any]],
        artifact_index: Sequence[dict[str, Any]],
        project_id: int,
        permissions: Sequence[str],
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> ValidatedAgentPlanningDecision:
        last_error: AgentPlanningError | None = None
        for attempt in (1, 2):
            request = self._request(
                intent=intent,
                conversation_context=conversation_context,
                skill_index=skill_index,
                tool_index=tool_index,
                artifact_index=artifact_index,
                project_id=project_id,
                permissions=permissions,
                attempt=attempt,
                validation_error=last_error.model_view() if last_error is not None else None,
            )
            response = self.ai_service.chat(request)
            try:
                content = str(getattr(response, "content", "") or "").strip()
                finish_reason = getattr(response, "finish_reason", None)
                if not content or finish_reason != "stop":
                    raise AgentPlanningError(
                        "planner response is empty or incomplete",
                        code="planner_response_incomplete",
                        details={"finish_reason": finish_reason, "content_present": bool(content)},
                    )
                try:
                    parsed = AgentPlanningDecision.model_validate_json(content)
                except (ValidationError, ValueError) as exc:
                    raise AgentPlanningError(
                        "planner response is not valid structured JSON",
                        code="planner_response_invalid",
                        details={"validation": _bounded_error_text(exc)},
                    ) from exc
                return self._validate(
                    parsed,
                    skill_index=skill_index,
                    tool_index=tool_index,
                    artifact_index=artifact_index,
                    permissions=permissions,
                )
            except AgentPlanningError as exc:
                last_error = exc
                if on_event is not None:
                    on_event("invalid", exc.model_view())
                    if attempt == 1:
                        on_event("retrying", {"next_attempt": 2, "reason_code": exc.code})
        assert last_error is not None
        raise AgentPlanningFailed(last_error=last_error)

    def _validate(
        self,
        decision: AgentPlanningDecision,
        *,
        skill_index: Sequence[dict[str, Any]],
        tool_index: Sequence[dict[str, Any]],
        artifact_index: Sequence[dict[str, Any]],
        permissions: Sequence[str],
    ) -> ValidatedAgentPlanningDecision:
        skills = _index_by(skill_index, "name")
        tools = _index_by(tool_index, "name")
        artifacts = _index_by(artifact_index, "artifact_id")

        selected_skills = _unique_non_empty(decision.selected_skills)
        selected_tools = _unique_non_empty(decision.selected_tools)
        selected_artifacts = _unique_non_empty(decision.selected_artifact_ids)
        source_domains = _unique_non_empty(decision.source_domains)
        required_facts = _unique_non_empty(decision.required_facts)

        unknown_skills = sorted(set(selected_skills) - set(skills))
        unknown_tools = sorted(set(selected_tools) - set(tools))
        unknown_artifacts = sorted(set(selected_artifacts) - set(artifacts))
        if unknown_skills or unknown_tools or unknown_artifacts:
            raise AgentPlanningError(
                "planner selected unregistered references",
                code="planner_unknown_reference",
                details={
                    "unknown_skills": unknown_skills,
                    "unknown_tools": unknown_tools,
                    "unknown_artifact_ids": unknown_artifacts,
                },
            )

        declared_tools = set(CORE_CONTEXT_TOOLS)
        owned_domains: set[str] = set()
        consumed_domains: set[str] = set()
        produced_domains: set[str] = set()
        for skill_name in selected_skills:
            skill = skills[skill_name]
            declared_tools.update(_strings(skill.get("tool_names") or skill.get("tools")))
            owned_domains.update(_strings(skill.get("owns")))
            consumed_domains.update(_strings(skill.get("consumes")))
            produced_domains.update(_strings(skill.get("produces")))

        undeclared_tools = sorted(set(selected_tools) - declared_tools)
        if undeclared_tools:
            raise AgentPlanningError(
                "planner selected Tools not declared by the selected Skills",
                code="planner_tool_not_declared_by_skill",
                details={"undeclared_tools": undeclared_tools},
            )

        if decision.target_domain and decision.target_domain not in owned_domains | produced_domains:
            raise AgentPlanningError(
                "planner target domain is incompatible with selected Skills",
                code="planner_target_domain_incompatible",
                details={"target_domain": decision.target_domain},
            )
        incompatible_sources = sorted(set(source_domains) - consumed_domains - owned_domains)
        if incompatible_sources:
            raise AgentPlanningError(
                "planner source domains are incompatible with selected Skills",
                code="planner_source_domain_incompatible",
                details={"source_domains": incompatible_sources},
            )
        if decision.confidence < self.minimum_confidence:
            raise AgentPlanningError(
                "planner confidence is below the configured threshold",
                code="planner_confidence_too_low",
                details={"confidence": decision.confidence, "minimum": self.minimum_confidence},
            )

        tool_scopes: dict[str, str] = {}
        missing_permissions: dict[str, list[str]] = {}
        permission_set = set(_strings(permissions))
        for tool_name in selected_tools:
            tool = tools[tool_name]
            side_effect_class = str(tool.get("side_effect_class") or "")
            scope = SIDE_EFFECT_SCOPE.get(side_effect_class)
            if scope is None:
                raise AgentPlanningError(
                    "registered Tool has an unknown side-effect class",
                    code="planner_tool_effect_unknown",
                    details={"tool_name": tool_name, "side_effect_class": side_effect_class},
                )
            tool_scopes[tool_name] = scope
            missing = sorted(set(_strings(tool.get("required_permissions"))) - permission_set)
            if missing:
                missing_permissions[tool_name] = missing
        if missing_permissions:
            raise AgentPlanningError(
                "planner selected Tools without required permissions",
                code="planner_permission_missing",
                details={"missing_permissions": missing_permissions},
            )

        model_requested_effect_scope = decision.requested_effect_scope
        required_effect_scope = required_effect_scope_for_tools(tool_scopes)
        effective_effect_scope = max(
            (model_requested_effect_scope, required_effect_scope),
            key=EFFECT_SCOPE_ORDER.__getitem__,
        )

        return ValidatedAgentPlanningDecision(
            goal=decision.goal.strip(),
            action=decision.action.strip(),
            target_domain=decision.target_domain,
            source_domains=source_domains,
            selected_skills=selected_skills,
            selected_tools=selected_tools,
            selected_artifact_ids=selected_artifacts,
            required_facts=required_facts,
            requested_effect_scope=effective_effect_scope,
            confidence=decision.confidence,
            reason_summary=decision.reason_summary.strip(),
            model_requested_effect_scope=model_requested_effect_scope,
            required_effect_scope=required_effect_scope,
            effect_scope_normalized=effective_effect_scope != model_requested_effect_scope,
        )

    def _request(
        self,
        *,
        intent: str,
        conversation_context: dict[str, Any] | None,
        skill_index: Sequence[dict[str, Any]],
        tool_index: Sequence[dict[str, Any]],
        artifact_index: Sequence[dict[str, Any]],
        project_id: int,
        permissions: Sequence[str],
        attempt: int,
        validation_error: dict[str, Any] | None,
    ) -> AIChatRequest:
        payload = {
            "attempt": attempt,
            "output_contract": AgentPlanningDecision.model_json_schema(),
            "intent": intent,
            "project_id": project_id,
            "permissions": list(_strings(permissions)),
            "conversation_context": _safe_conversation_context(conversation_context),
            "skill_index": [_compact_skill(item) for item in skill_index],
            "tool_index": [_compact_tool(item) for item in tool_index],
            "artifact_index": [_compact_artifact(item) for item in artifact_index],
        }
        if validation_error is not None:
            payload["validation_error"] = validation_error
        return AIChatRequest(
            messages=[
                AIChatMessage(
                    role="system",
                    content=(
                        "You are the semantic planning control plane for TestAuto Agent. Return exactly one top-level "
                        "JSON object that conforms to output_contract; do not wrap it in plan, result, data, or any "
                        "other key. Copy every required field name exactly. selected_skills must contain at least one "
                        "registered Skill. requested_effect_scope must be one of observe, derive, draft, execute, or "
                        "persist; use observe for read_only, derive for deterministic_compute, draft for draft_only, "
                        "execute for execution_record, and persist for business_update. Never return none. The backend "
                        "derives the effective scope from frozen ToolSpecs and may safely normalize this advisory value. "
                        "Select only registered "
                        "Skills, Tools, and artifact ids from the supplied frozen indexes. selected_tools may be empty "
                        "only when the selected Skill can answer without a Tool. The backend validates and executes "
                        "the plan. Do not include chain-of-thought; reason_summary must be a short decision explanation."
                    ),
                ),
                AIChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            ],
            thinking="disabled",
            temperature=0,
            max_tokens=2048,
            response_format="json",
        )


def _index_by(items: Sequence[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {
        str(item.get(key)): dict(item)
        for item in items
        if isinstance(item, dict) and isinstance(item.get(key), str) and str(item.get(key)).strip()
    }


def _strings(values: Any) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return ()
    return tuple(str(value).strip() for value in values if str(value).strip())


def _unique_non_empty(values: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_strings(values)))


def _bounded_error_text(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:1000]


def _safe_conversation_context(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, Any] = {}
    for key in ("active_artifact_action", "active_artifact_handles", "current_artifact_candidates"):
        if key in value:
            safe[key] = value[key]
    return safe


def _compact_skill(item: dict[str, Any]) -> dict[str, Any]:
    fields = ("name", "description", "owns", "consumes", "produces", "tool_names", "tools")
    return {field: item.get(field) for field in fields if item.get(field) not in (None, [], {})}


def _compact_tool(item: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "name",
        "summary",
        "side_effect_class",
        "replay_policy",
        "required_permissions",
        "schema_hash",
    )
    compact = {field: item.get(field) for field in fields if item.get(field) not in (None, [], {})}
    side_effect_class = str(item.get("side_effect_class") or "")
    required_effect_scope = SIDE_EFFECT_SCOPE.get(side_effect_class)
    if required_effect_scope is not None:
        compact["required_effect_scope"] = required_effect_scope
    return compact


def required_effect_scope_for_tools(tool_scopes: dict[str, str]) -> str:
    return max(tool_scopes.values(), key=EFFECT_SCOPE_ORDER.__getitem__, default="observe")


def _compact_artifact(item: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "artifact_id",
        "artifact_type",
        "artifact_class",
        "artifact_trust",
        "available_followup_actions",
        "object_references",
        "output_hash",
        "created_at",
    )
    return {field: item.get(field) for field in fields if item.get(field) not in (None, [], {})}
