from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.agent_artifact_resolver import (
    ARTIFACT_CLASS_AUTHORITATIVE,
    ARTIFACT_TRUST_SOURCE,
    AgentArtifactResolver,
)
from app.services.agent_skill_registry import AgentSkill
from app.services.agent_tool_service import ToolRegistry


AGENT_CAPABILITY_PLAN_SCHEMA_VERSION = "agent_capability_plan_v1"
AGENT_CAPABILITY_TOOL_NAME_RE = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+\b")

MODEL_PRIVATE_TOOL_NAMES = frozenset({
    "tool_result.read_full",
})

BASE_CONTEXT_TOOL_NAMES = (
    "project.read_context",
)

DEFAULT_SCENARIO_TOOL_NAMES = (
    "project.read_context",
    "testcase.query_project_cases",
    "scenario.compose_draft",
    "scenario.query_project_scenarios",
)

SCENARIO_DRAFT_SAVE_TOOLS = (
    "scenario.create_saved",
    "scenario.update_saved",
)

SCENARIO_FAILURE_REPAIR_TOOLS = (
    "scenario.query_project_scenarios",
    "testcase.query_project_cases",
    "scenario.compose_draft",
    "scenario.update_saved",
    "scenario.execute_dry_run",
)

TEST_CASE_QUERY_SNAPSHOT_COMPOSE_TOOLS = (
    "scenario.compose_draft",
)

TEST_CASE_QUERY_SNAPSHOT_EXECUTE_TOOLS = (
    "testcase.batch_execute",
    "websocket_testcase.batch_execute",
)

TEST_CASE_QUERY_SNAPSHOT_ASSERTION_TOOLS = (
    "testcase.batch_update_assertions",
    "websocket_testcase.batch_update_assertions",
)

HTTP_TEST_CASE_CREATION_TOOLS = (
    "project.read_context",
    "testcase.query_project_cases",
    "ai_skill.run_draft",
    "testcase.validate_schema",
    "testcase.create_saved",
)

ENVIRONMENT_MANAGEMENT_TOOLS = (
    "project.read_context",
    "environment.query_project_configs",
    "environment.create_config",
    "environment.update_config",
    "environment.delete_config",
    "environment.upsert_variable",
    "environment.delete_variable",
)


@dataclass(frozen=True)
class AgentCapabilityAction:
    action: str
    domain: str
    tool_name: str
    source: str
    required_tools: tuple[str, ...] = ()
    tool_input_hint: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def model_view(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": self.action,
            "domain": self.domain,
            "tool_name": self.tool_name,
            "source": self.source,
        }
        if self.required_tools:
            payload["required_tools"] = list(self.required_tools)
        if self.tool_input_hint:
            payload["tool_input_hint"] = self.tool_input_hint
        if self.reason:
            payload["reason"] = self.reason
        return payload


@dataclass(frozen=True)
class AgentCapabilityPlan:
    schema_version: str
    intent: str
    domain: str | None
    intent_action: str | None
    allowed_tools: tuple[str, ...]
    allowed_skills: tuple[str, ...] = ()
    available_actions: tuple[AgentCapabilityAction, ...] = ()
    blocked_actions: tuple[dict[str, Any], ...] = ()
    required_facts: tuple[str, ...] = ()
    tool_input_hints: dict[str, dict[str, Any]] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()

    def model_view(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "intent": self.intent,
            "allowed_tools": list(self.allowed_tools),
            "allowed_skills": list(self.allowed_skills),
        }
        if self.domain:
            payload["domain"] = self.domain
        if self.intent_action:
            payload["intent_action"] = self.intent_action
        if self.available_actions:
            payload["available_actions"] = [action.model_view() for action in self.available_actions]
        if self.blocked_actions:
            payload["blocked_actions"] = list(self.blocked_actions)
        if self.required_facts:
            payload["required_facts"] = list(self.required_facts)
        if self.tool_input_hints:
            payload["tool_input_hints"] = self.tool_input_hints
        if self.reason_codes:
            payload["reason_codes"] = list(self.reason_codes)
        return payload


class AgentCapabilityResolver:
    """Resolves model-visible tools from intent, routed skills, and working artifacts."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry | None = None,
        model_private_tool_names: frozenset[str] = MODEL_PRIVATE_TOOL_NAMES,
    ) -> None:
        self.tool_registry = tool_registry or ToolRegistry()
        self.model_private_tool_names = model_private_tool_names
        self.artifact_resolver = AgentArtifactResolver()

    def routing_intent(self, intent: str, *, working_context: dict[str, Any] | None = None) -> str:
        hint = self._routing_hint_for_working_context(intent, working_context)
        if not hint:
            return intent
        if hint in intent:
            return intent
        return f"{intent}\n{hint}"

    def resolve(
        self,
        *,
        intent: str,
        selected_skills: tuple[AgentSkill, ...],
        working_context: dict[str, Any] | None = None,
        original_intent: str | None = None,
        allowed_skills: tuple[str, ...] = (),
        planner_reason_codes: tuple[str, ...] = (),
    ) -> AgentCapabilityPlan:
        available_names = {spec.name for spec in self.tool_registry.list_specs()}
        names: set[str] = set()
        available_actions: list[AgentCapabilityAction] = []
        blocked_actions: list[dict[str, Any]] = []
        required_facts: set[str] = set()
        reason_codes: set[str] = set()
        tool_input_hints: dict[str, dict[str, Any]] = {}
        reason_codes.update(planner_reason_codes)

        search_text = "\n".join([intent, *(skill.prompt_block() for skill in selected_skills)])
        names.update(tool_name for tool_name in self._tool_names_from_text(search_text) if tool_name in available_names)

        if any(skill.name == "scenario-composition" for skill in selected_skills):
            names.update(DEFAULT_SCENARIO_TOOL_NAMES)
            reason_codes.add("skill:scenario-composition")
        if any(skill.name == "environment-config-management" for skill in selected_skills):
            names.update(ENVIRONMENT_MANAGEMENT_TOOLS)
            required_facts.add("environment_config_context")
            reason_codes.add("skill:environment-config-management")
        if self._intent_requests_case_creation(intent):
            names.update(HTTP_TEST_CASE_CREATION_TOOLS)
            required_facts.add("test_case_source_inventory")
            reason_codes.add("intent:test_case_creation")
        if self._intent_mentions_environment_management(intent):
            names.update(ENVIRONMENT_MANAGEMENT_TOOLS)
            required_facts.add("environment_config_context")
            reason_codes.add("intent:environment_management")
        if selected_skills:
            names.update(BASE_CONTEXT_TOOL_NAMES)
            reason_codes.add("skill_context:base")
        if self._intent_mentions_project_context(intent):
            names.add("project.read_context")
            reason_codes.add("intent:project_context")
        if self._intent_mentions_case_inventory(intent):
            names.add("testcase.query_project_cases")
            reason_codes.add("intent:case_inventory")
        if self._intent_mentions_report(intent) and not self._intent_mentions_scenario_execution(intent):
            names.add("report.read_summary")
            reason_codes.add("intent:report")
        if self._intent_mentions_scenario_execution(intent):
            names.update(("scenario.query_project_scenarios", "scenario.execute_dry_run"))
            reason_codes.add("intent:scenario_execution")

        self._apply_working_context_capabilities(
            intent=intent,
            working_context=working_context,
            names=names,
            available_names=available_names,
            available_actions=available_actions,
            blocked_actions=blocked_actions,
            required_facts=required_facts,
            reason_codes=reason_codes,
            tool_input_hints=tool_input_hints,
        )
        self._prune_context_locked_tools(intent=intent, names=names, available_actions=available_actions)

        allowed_tools = tuple(
            tool_name
            for tool_name in sorted(names)
            if tool_name in available_names and tool_name not in self.model_private_tool_names
        )
        domain = self._infer_domain(intent, selected_skills, available_actions)
        intent_action = self._infer_intent_action(intent, available_actions)
        return AgentCapabilityPlan(
            schema_version=AGENT_CAPABILITY_PLAN_SCHEMA_VERSION,
            intent=(original_intent or intent).strip(),
            domain=domain,
            intent_action=intent_action,
            allowed_tools=allowed_tools,
            allowed_skills=allowed_skills,
            available_actions=tuple(available_actions),
            blocked_actions=tuple(blocked_actions),
            required_facts=tuple(sorted(required_facts)),
            tool_input_hints=tool_input_hints,
            reason_codes=tuple(sorted(reason_codes)),
        )

    def _prune_context_locked_tools(
        self,
        *,
        intent: str,
        names: set[str],
        available_actions: list[AgentCapabilityAction],
    ) -> None:
        unlocked_tools: set[str] = set()
        for action in available_actions:
            unlocked_tools.add(action.tool_name)
            unlocked_tools.update(action.required_tools)
        if not any(tool_name in unlocked_tools for tool_name in SCENARIO_DRAFT_SAVE_TOOLS):
            for tool_name in SCENARIO_DRAFT_SAVE_TOOLS:
                names.discard(tool_name)
        if "scenario.execute_dry_run" not in unlocked_tools and not self._intent_mentions_scenario_execution(intent):
            names.discard("scenario.execute_dry_run")

    def _apply_working_context_capabilities(
        self,
        *,
        intent: str,
        working_context: dict[str, Any] | None,
        names: set[str],
        available_names: set[str],
        available_actions: list[AgentCapabilityAction],
        blocked_actions: list[dict[str, Any]],
        required_facts: set[str],
        reason_codes: set[str],
        tool_input_hints: dict[str, dict[str, Any]],
    ) -> None:
        blocked_actions.extend(self._blocked_artifact_actions(working_context, intent=intent))
        active_action = self._active_artifact_action(working_context)
        if active_action is not None:
            self._add_artifact_action_tools(
                action_context=active_action,
                source="active_artifact_action",
                names=names,
                available_names=available_names,
                available_actions=available_actions,
                required_facts=required_facts,
                reason_codes=reason_codes,
                tool_input_hints=tool_input_hints,
            )
            return

        for candidate in reversed(self._artifact_candidates(working_context)):
            action_context = self._candidate_action_context(candidate, intent=intent)
            if action_context is None:
                continue
            self._add_artifact_action_tools(
                action_context=action_context,
                source="artifact_candidate",
                names=names,
                available_names=available_names,
                available_actions=available_actions,
                required_facts=required_facts,
                reason_codes=reason_codes,
                tool_input_hints=tool_input_hints,
            )
            return

    def _add_artifact_action_tools(
        self,
        *,
        action_context: dict[str, Any],
        source: str,
        names: set[str],
        available_names: set[str],
        available_actions: list[AgentCapabilityAction],
        required_facts: set[str],
        reason_codes: set[str],
        tool_input_hints: dict[str, dict[str, Any]],
    ) -> None:
        artifact_type = str(action_context.get("artifact_type") or "")
        domain = str(action_context.get("domain") or artifact_type.split("_", 1)[0] or "artifact")
        action = str(action_context.get("action") or "use")
        tool_name = str(action_context.get("tool_name") or "")
        required_tools = self._required_tools_for_artifact_action(action_context)

        for name in required_tools:
            if name in available_names:
                names.add(name)
        if artifact_type == "scenario_draft" and action == "save":
            names.update(name for name in SCENARIO_DRAFT_SAVE_TOOLS if name in available_names)
            names.add("project.read_context")
            required_facts.add("scenario_draft_artifact")
        if "scenario.execute_dry_run" in required_tools:
            names.update(name for name in ("scenario.query_project_scenarios", "scenario.execute_dry_run") if name in available_names)
            required_facts.add("saved_scenario_id")
        if artifact_type == "scenario_run_failure" and action == "repair":
            names.update(name for name in SCENARIO_FAILURE_REPAIR_TOOLS if name in available_names)
            required_facts.add("scenario_run_failure_artifact")

        hint = action_context.get("tool_input_hint")
        if isinstance(hint, dict) and tool_name:
            tool_input_hints[tool_name] = hint

        if tool_name and tool_name in available_names:
            available_actions.append(
                AgentCapabilityAction(
                    action=action,
                    domain=domain,
                    tool_name=tool_name,
                    source=source,
                    required_tools=tuple(name for name in required_tools if name in available_names),
                    tool_input_hint=hint if isinstance(hint, dict) else {},
                    reason=f"{artifact_type}.{action}" if artifact_type else action,
                )
            )
        if artifact_type and action:
            reason_codes.add(f"artifact_action:{artifact_type}.{action}")

    def _required_tools_for_artifact_action(self, action_context: dict[str, Any]) -> tuple[str, ...]:
        tools: list[str] = []
        tool_name = action_context.get("tool_name")
        if isinstance(tool_name, str) and tool_name:
            tools.append(tool_name)
        explicit_required_tools = action_context.get("required_tools")
        if isinstance(explicit_required_tools, list):
            tools.extend(item for item in explicit_required_tools if isinstance(item, str) and item)
        after_save_actions = action_context.get("after_save_actions")
        if isinstance(after_save_actions, list):
            tools.extend(item for item in after_save_actions if isinstance(item, str) and item)
        return tuple(dict.fromkeys(tools))

    def _candidate_action_context(self, candidate: dict[str, Any], *, intent: str) -> dict[str, Any] | None:
        artifact_type = str(candidate.get("artifact_type") or "")
        actions = candidate.get("available_followup_actions")
        action_names = {str(action) for action in actions} if isinstance(actions, list) else set()
        artifact_id = str(candidate.get("artifact_id") or "")
        if not artifact_id:
            return None

        if artifact_type == "scenario_draft" and self._intent_requests_save_action(intent):
            if action_names and not {"save", "update_saved"}.intersection(action_names):
                return None
            scenario_source: dict[str, Any] = {"artifact_id": artifact_id}
            if candidate.get("output_hash"):
                scenario_source["output_hash"] = candidate.get("output_hash")
            return {
                "artifact_type": "scenario_draft",
                "domain": "scenario",
                "action": "save",
                "tool_name": "scenario.create_saved",
                "artifact_id": artifact_id,
                "tool_input_hint": {
                    "scenario_source": scenario_source,
                },
            }

        if artifact_type == "saved_scenario" and self._intent_mentions_scenario_execution(intent):
            if action_names and "execute" not in action_names:
                return None
            summary = candidate.get("artifact_summary") if isinstance(candidate.get("artifact_summary"), dict) else {}
            hint: dict[str, Any] = {"source_artifact_id": artifact_id}
            for key in ("scenario_id", "name", "environment_id", "current_version"):
                if summary.get(key) is not None:
                    hint[key] = summary.get(key)
            return {
                "artifact_type": "saved_scenario",
                "domain": "scenario",
                "action": "execute",
                "tool_name": "scenario.execute_dry_run",
                "required_tools": ["scenario.query_project_scenarios", "scenario.execute_dry_run"],
                "artifact_id": artifact_id,
                "tool_input_hint": hint,
            }

        if artifact_type == "scenario_run_failure" and self._intent_mentions_repair_action(intent):
            if action_names and "repair" not in action_names:
                return None
            summary = candidate.get("artifact_summary") if isinstance(candidate.get("artifact_summary"), dict) else {}
            hint: dict[str, Any] = {"source_artifact_id": artifact_id}
            for key in ("scenario_id", "environment_id", "run_ids", "failed_run_ids", "failures", "statuses"):
                if summary.get(key) is not None:
                    hint[key] = summary.get(key)
            return {
                "artifact_type": "scenario_run_failure",
                "domain": "scenario",
                "action": "repair",
                "tool_name": "scenario.compose_draft",
                "required_tools": list(SCENARIO_FAILURE_REPAIR_TOOLS),
                "artifact_id": artifact_id,
                "tool_input_hint": hint,
            }

        if artifact_type != "test_case_query_snapshot":
            return None
        if self._intent_mentions_scenario_composition(intent) and "compose_scenario" in action_names:
            return {
                "artifact_type": artifact_type,
                "domain": "scenario",
                "action": "compose_scenario",
                "tool_name": TEST_CASE_QUERY_SNAPSHOT_COMPOSE_TOOLS[0],
                "artifact_id": artifact_id,
            }
        if self._intent_requests_execute_action(intent) and "execute" in action_names:
            return {
                "artifact_type": artifact_type,
                "domain": "test_case",
                "action": "execute",
                "tool_name": TEST_CASE_QUERY_SNAPSHOT_EXECUTE_TOOLS[0],
                "artifact_id": artifact_id,
            }
        if self._intent_mentions_assertion_update(intent) and {"update_assertions", "batch_update_assertions"}.intersection(action_names):
            return {
                "artifact_type": artifact_type,
                "domain": "test_case",
                "action": "update_assertions",
                "tool_name": TEST_CASE_QUERY_SNAPSHOT_ASSERTION_TOOLS[0],
                "artifact_id": artifact_id,
            }
        return None

    def _routing_hint_for_working_context(self, intent: str, working_context: dict[str, Any] | None) -> str:
        active_action = self._active_artifact_action(working_context)
        if active_action is None:
            for candidate in reversed(self._artifact_candidates(working_context)):
                active_action = self._candidate_action_context(candidate, intent=intent)
                if active_action is not None:
                    break
        if not active_action:
            return ""
        artifact_type = str(active_action.get("artifact_type") or "")
        action = str(active_action.get("action") or "")
        tool_name = str(active_action.get("tool_name") or "")
        if artifact_type == "scenario_draft" and action == "save" and tool_name:
            return (
                "active_artifact_type=scenario_draft; active_artifact_action=save; "
                "route_skill=scenario-composition; enable_tools=scenario.create_saved,scenario.update_saved; "
                "use scenario_source artifact reference instead of reconstructing scenario JSON."
            )
        if artifact_type == "saved_scenario" and action == "execute" and tool_name:
            return (
                "active_artifact_type=saved_scenario; active_artifact_action=execute; "
                "route_skill=scenario-composition; "
                "enable_tools=scenario.query_project_scenarios,scenario.execute_dry_run; "
                "execute the saved scenario from the SOURCE artifact, then summarize dry-run results."
            )
        if artifact_type == "scenario_run_failure" and action == "repair" and tool_name:
            return (
                "active_artifact_type=scenario_run_failure; active_artifact_action=repair; "
                "route_skill=scenario-composition; "
                "enable_tools=scenario.query_project_scenarios,testcase.query_project_cases,"
                "scenario.compose_draft,scenario.update_saved,scenario.execute_dry_run; "
                "repair the failed saved scenario from the SOURCE dry-run artifact, then validate with dry-run."
            )
        return ""

    def _active_artifact_action(self, working_context: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(working_context, dict):
            return None
        active_action = working_context.get("active_artifact_action")
        if not isinstance(active_action, dict):
            return None
        artifact_trust = active_action.get("artifact_trust")
        if artifact_trust and artifact_trust != ARTIFACT_TRUST_SOURCE:
            return None
        artifact_class = active_action.get("artifact_class")
        if artifact_class and artifact_class != ARTIFACT_CLASS_AUTHORITATIVE:
            return None
        return active_action

    def _blocked_artifact_actions(
        self,
        working_context: dict[str, Any] | None,
        *,
        intent: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(working_context, dict):
            return []
        blocked: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        active_action = working_context.get("active_artifact_action")
        if isinstance(active_action, dict):
            items.append(active_action)
        raw_candidates = working_context.get("current_artifact_candidates")
        if isinstance(raw_candidates, list):
            items.extend(item for item in raw_candidates if isinstance(item, dict))
        for item in items:
            artifact_trust = item.get("artifact_trust")
            if not artifact_trust or artifact_trust == ARTIFACT_TRUST_SOURCE:
                continue
            artifact_type = str(item.get("artifact_type") or "")
            action = str(item.get("action") or "")
            if not action and artifact_type == "scenario_draft" and self._intent_requests_save_action(intent):
                action = "save"
            if not action:
                continue
            blocked.append({
                "artifact_id": item.get("artifact_id"),
                "artifact_type": artifact_type,
                "artifact_trust": artifact_trust,
                "action": action,
                "tool_name": item.get("tool_name"),
                "reason": "artifact_trust_not_source",
            })
        return blocked

    def _artifact_candidates(self, working_context: dict[str, Any] | None) -> tuple[dict[str, Any], ...]:
        if not isinstance(working_context, dict):
            return ()
        candidates: list[dict[str, Any]] = []
        raw_handles = working_context.get("active_artifact_handles")
        if isinstance(raw_handles, list):
            candidates.extend(item for item in raw_handles if isinstance(item, dict))
        raw_candidates = working_context.get("current_artifact_candidates")
        if isinstance(raw_candidates, list):
            candidates.extend(item for item in raw_candidates if isinstance(item, dict))
        manifest = working_context.get("conversation_tool_artifact_manifest")
        if isinstance(manifest, dict) and isinstance(manifest.get("items"), list):
            candidates.extend(item for item in manifest["items"] if isinstance(item, dict))

        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in candidates:
            availability = self.artifact_resolver.availability_from_item(item)
            if availability is None or not availability.is_decision_source:
                continue
            item = availability.model_handle()
            key = str(item.get("artifact_id") or item.get("tool_call_id") or id(item))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return tuple(deduped)

    def _tool_names_from_text(self, text: str) -> tuple[str, ...]:
        return tuple(sorted(set(AGENT_CAPABILITY_TOOL_NAME_RE.findall(text))))

    def _infer_domain(
        self,
        intent: str,
        selected_skills: tuple[AgentSkill, ...],
        available_actions: list[AgentCapabilityAction],
    ) -> str | None:
        if available_actions:
            return available_actions[0].domain
        if any(skill.name == "environment-config-management" for skill in selected_skills) or self._intent_mentions_environment_management(intent):
            return "environment"
        if any(skill.name == "scenario-composition" for skill in selected_skills) or self._intent_mentions_scenario_execution(intent):
            return "scenario"
        if any(skill.name == "report-summary" for skill in selected_skills):
            return "report"
        if self._intent_mentions_case_inventory(intent):
            return "test_case"
        return None

    def _infer_intent_action(self, intent: str, available_actions: list[AgentCapabilityAction]) -> str | None:
        if available_actions:
            return available_actions[0].action
        if self._intent_mentions_repair_action(intent):
            return "repair"
        if self._intent_requests_case_creation(intent):
            return "create_cases"
        if self._intent_requests_save_action(intent):
            return "save"
        if self._intent_requests_execute_action(intent):
            return "execute"
        if self._intent_mentions_report(intent):
            return "read_report"
        if self._intent_mentions_case_inventory(intent):
            return "query_cases"
        return None

    def _intent_mentions_project_context(self, intent: str) -> bool:
        lowered = intent.lower()
        return any(term in lowered for term in ("项目", "环境", "context", "environment", "project"))

    def _intent_mentions_environment_management(self, intent: str) -> bool:
        lowered = intent.casefold()
        return any(
            term in lowered
            for term in (
                "environment",
                "env",
                "base_url",
                "variable",
                "variables",
                "token",
                "bearer",
                "auth",
                "cookie",
                "lingxi-auth",
                "环境",
                "环境变量",
                "变量",
                "令牌",
                "鉴权",
                "认证",
                "过期",
            )
        )

    def _intent_mentions_case_inventory(self, intent: str) -> bool:
        lowered = intent.lower()
        return any(term in lowered for term in ("用例", "case", "接口", "api"))

    def _intent_requests_case_creation(self, intent: str) -> bool:
        lowered = intent.lower()
        has_case_subject = any(
            term in lowered
            for term in (
                "用例",
                "测试用例",
                "接口用例",
                "http用例",
                "test case",
                "testcase",
                "case",
            )
        )
        has_creation_action = any(
            term in lowered
            for term in (
                "创建",
                "生成",
                "新增",
                "扩展",
                "扩写",
                "create",
                "generate",
                "add",
                "expand",
            )
        )
        has_design_variant = any(term in lowered for term in ("等价类", "边界值", "equivalence", "boundary"))
        return has_case_subject and (has_creation_action or has_design_variant)

    def _intent_mentions_report(self, intent: str) -> bool:
        lowered = intent.lower()
        return any(term in lowered for term in ("报告", "执行结果", "失败原因", "report", "failure"))

    def _intent_mentions_scenario_execution(self, intent: str) -> bool:
        lowered = intent.lower()
        has_scenario_subject = any(
            term in lowered
            for term in (
                "场景",
                "scenario",
                "dry-run",
                "dryrun",
                "自动化测试流程",
                "测试流程",
                "automation flow",
                "test flow",
                "flow",
            )
        )
        has_execution_action = any(
            term in lowered
            for term in (
                "execute",
                "run",
                "rerun",
                "执行测试",
                "运行测试",
                "执行场景",
                "运行场景",
                "场景执行",
                "场景下执行",
                "运行这个场景",
                "执行这个场景",
                "试运行",
                "dry-run",
                "dryrun",
            )
        )
        if not has_execution_action and any(term in lowered for term in ("执行", "execute", "run")) and any(
            term in lowered for term in ("流程", "flow", "刚创建", "刚才", "just created", "this", "that", "该")
        ):
            has_execution_action = True
        return has_scenario_subject and has_execution_action

    def _intent_mentions_scenario_composition(self, intent: str) -> bool:
        lowered = intent.lower()
        return any(term in lowered for term in ("场景", "流程", "scenario", "compose", "组合", "编排"))

    def _intent_mentions_repair_action(self, intent: str) -> bool:
        lowered = intent.lower()
        return any(
            term in lowered
            for term in (
                "\u4fee\u590d",
                "\u89e3\u51b3",
                "\u4fee\u597d",
                "\u6539\u597d",
                "\u5904\u7406\u95ee\u9898",
                "fix",
                "repair",
                "resolve",
            )
        )

    def _intent_mentions_assertion_update(self, intent: str) -> bool:
        lowered = intent.lower()
        return any(term in lowered for term in ("断言", "assertion", "校验"))

    def _intent_requests_save_action(self, intent: str) -> bool:
        lowered = intent.lower()
        return any(term in lowered for term in ("保存", "持久化", "落库", "发布", "正式场景", "save"))

    def _intent_requests_execute_action(self, intent: str) -> bool:
        lowered = intent.lower()
        return any(
            term in lowered
            for term in ("保存后执行", "保存并执行", "执行", "试运行", "dry-run", "dryrun", "execute", "run", "rerun")
        )
