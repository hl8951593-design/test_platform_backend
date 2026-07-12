from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.agent_artifact_resolver import AgentArtifactResolver
from app.services.agent_intent_action import parse_agent_intent_action
from app.services.agent_skill_registry import AgentSkill, AgentSkillRegistry


AGENT_SKILL_PLAN_SCHEMA_VERSION = "agent_skill_plan_v1"

SCENARIO_SKILL_NAME = "scenario-composition"
REPORT_SKILL_NAME = "report-summary"
HTTP_CASE_SKILL_NAME = "http-test-case-design"
WEBSOCKET_CASE_SKILL_NAME = "websocket-test-case-design"
ENVIRONMENT_SKILL_NAME = "environment-config-management"
GENERAL_TESTING_SKILL_NAME = "general-testing-answer"
EXECUTION_DIAGNOSIS_SKILL_NAME = "execution-diagnosis"
TEST_PLAN_SKILL_NAME = "test-plan-management"
VISUAL_FLOW_SKILL_NAME = "visual-flow-design"
DEFECT_SKILL_NAME = "defect-triage"

EXECUTE_TERMS = (
    "execute",
    "run",
    "rerun",
    "dry-run",
    "dryrun",
    "执行",
    "运行",
    "试运行",
)
SAVE_TERMS = ("save", "persist", "publish", "保存", "持久化", "落库", "发布")
REPAIR_TERMS = ("fix", "repair", "resolve", "修复", "解决", "处理问题")
REPORT_TERMS = ("report", "result", "results", "summary", "summarize", "报告", "执行结果", "结果", "总结")
DEICTIC_TERMS = (
    "this",
    "that",
    "current",
    "previous",
    "just created",
    "刚才",
    "刚创建",
    "这个",
    "该",
    "当前",
)
CASE_CREATION_TERMS = (
    "create test case",
    "generate test case",
    "equivalence",
    "boundary",
    "创建用例",
    "生成用例",
    "等价类",
    "边界值",
)
ENVIRONMENT_MANAGEMENT_TERMS = (
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
EXECUTION_RECORD_TERMS = ("execution", "run record", "执行", "执行记录", "运行记录")
EXECUTION_DIAGNOSIS_TERMS = (
    "diagnose",
    "diagnosis",
    "failed",
    "failure",
    "cause",
    "失败",
    "诊断",
    "原因",
    "超时",
    "断言",
)
TEST_PLAN_TERMS = (
    "test plan",
    "test suite",
    "plan run",
    "smoke suite",
    "regression suite",
    "测试计划",
    "测试套件",
    "计划执行",
    "冒烟计划",
    "回归计划",
)
VISUAL_FLOW_TERMS = ("visual flow", "flow dag", "可视化流程", "流程 dag", "流程节点", "节点连线")
DEFECT_TERMS = ("defect", "bug", "缺陷", "故障单", "关闭缺陷", "重新激活")
CONCEPTUAL_TESTING_TERMS = ("是什么", "什么是", "有啥区别", "有什么区别", "区别是什么", "概念", "原理", "解释")


@dataclass(frozen=True)
class AgentSkillPlanCandidate:
    name: str
    score: int
    reasons: tuple[str, ...]

    def model_view(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class AgentSkillPlan:
    schema_version: str
    intent: str
    routing_intent: str
    primary_skill: str | None
    supporting_skills: tuple[str, ...]
    allowed_skills: tuple[str, ...]
    confidence: float
    selection_strategy: str
    ranker_mode: str
    candidates: tuple[AgentSkillPlanCandidate, ...]
    reason_codes: tuple[str, ...]

    def model_view(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "intent": self.intent,
            "routing_intent": self.routing_intent,
            "primary_skill": self.primary_skill,
            "supporting_skills": list(self.supporting_skills),
            "allowed_skills": list(self.allowed_skills),
            "confidence": self.confidence,
            "selection_strategy": self.selection_strategy,
            "ranker_mode": self.ranker_mode,
            "candidate_skills": [candidate.model_view() for candidate in self.candidates],
        }
        if self.reason_codes:
            payload["reason_codes"] = list(self.reason_codes)
        return payload


class AgentSkillPlanner:
    """Plans model-visible skills before the context and capability layers are built."""

    def __init__(
        self,
        *,
        skill_registry: AgentSkillRegistry | None = None,
        artifact_resolver: AgentArtifactResolver | None = None,
        max_candidates: int = 5,
    ) -> None:
        self.skill_registry = skill_registry or AgentSkillRegistry()
        self.artifact_resolver = artifact_resolver or AgentArtifactResolver()
        self.max_candidates = max(1, max_candidates)

    def plan(
        self,
        intent: str,
        *,
        routing_intent: str | None = None,
        working_context: dict[str, Any] | None = None,
        intent_action: Any | None = None,
    ) -> AgentSkillPlan:
        original_intent = (intent or "").strip()
        effective_intent = (routing_intent or intent or "").strip()
        scores: dict[str, int] = {}
        reasons: dict[str, set[str]] = {}
        global_reasons: set[str] = {"planner:registry_retrieval"}

        for score, skill in self.skill_registry.rank_for_intent(effective_intent, limit=self.max_candidates):
            self._add_candidate(
                scores=scores,
                reasons=reasons,
                skill_name=skill.name,
                score=score,
                reason=f"registry_score:{score}",
            )
            metadata_score = self._metadata_score(skill, effective_intent)
            if metadata_score:
                self._add_candidate(
                    scores=scores,
                    reasons=reasons,
                    skill_name=skill.name,
                    score=metadata_score,
                    reason=f"metadata_score:{metadata_score}",
                )

        for skill in self.skill_registry.list_skills():
            if skill.name in scores:
                continue
            metadata_score = self._metadata_score(skill, effective_intent)
            if metadata_score:
                self._add_candidate(
                    scores=scores,
                    reasons=reasons,
                    skill_name=skill.name,
                    score=metadata_score,
                    reason=f"metadata_score:{metadata_score}",
                )

        self._apply_intent_overrides(
            intent=effective_intent,
            intent_action=intent_action,
            scores=scores,
            reasons=reasons,
            global_reasons=global_reasons,
        )
        self._apply_artifact_context(
            intent=effective_intent,
            working_context=working_context,
            scores=scores,
            reasons=reasons,
            global_reasons=global_reasons,
        )

        intent_action = intent_action or parse_agent_intent_action(effective_intent, working_context=working_context)
        candidates = self._ranked_candidates(scores=scores, reasons=reasons)
        primary = self._primary_skill_for_target(
            intent_action=intent_action,
            candidates=candidates,
        )
        supporting, supporting_reasons = self._supporting_skills_for_action(intent_action, primary=primary)
        global_reasons.update(supporting_reasons)
        allowed = tuple(name for name in (primary, *supporting) if name)
        confidence = _planner_confidence(candidates[0].score if candidates else 0)
        return AgentSkillPlan(
            schema_version=AGENT_SKILL_PLAN_SCHEMA_VERSION,
            intent=original_intent,
            routing_intent=effective_intent,
            primary_skill=primary,
            supporting_skills=supporting,
            allowed_skills=allowed,
            confidence=confidence,
            selection_strategy="hybrid_skill_planner_v1",
            ranker_mode="deterministic_hybrid",
            candidates=candidates,
            reason_codes=tuple(sorted(global_reasons)),
        )

    def _primary_skill_for_target(
        self,
        *,
        intent_action: Any,
        candidates: tuple[AgentSkillPlanCandidate, ...],
    ) -> str | None:
        target_domain = getattr(intent_action, "target_domain", None)
        decision_source = getattr(intent_action, "source", "deterministic_fallback")
        if target_domain and decision_source == "llm_intent":
            owner_names = {
                skill.name
                for skill in self.skill_registry.list_skills()
                if target_domain in getattr(skill, "owns", ())
            }
            for candidate in candidates:
                if candidate.name in owner_names:
                    return candidate.name
            if owner_names:
                return sorted(owner_names)[0]
        return candidates[0].name if candidates else None

    def _supporting_skills_for_action(
        self,
        intent_action: Any,
        *,
        primary: str | None,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        supporting: list[str] = []
        reasons: list[str] = []
        for source_domain in getattr(intent_action, "source_domains", ()):
            owner_skills = [
                skill
                for skill in self.skill_registry.list_skills()
                if source_domain in getattr(skill, "owns", ())
            ]
            owner_skills.sort(key=lambda skill: (0 if source_domain in getattr(skill, "produces", ()) else 1, skill.name))
            for skill in owner_skills:
                if skill.name == primary or skill.name in supporting:
                    continue
                supporting.append(skill.name)
                reasons.append(f"planner:supporting_skill:{skill.name}:evidence:{source_domain}")
                break
        return tuple(supporting), tuple(reasons)

    def _metadata_score(self, skill: AgentSkill, intent: str) -> int:
        if not intent:
            return 0
        normalized = intent.casefold()
        score = 0
        for value in (
            *skill.capabilities,
            *skill.required_context,
            *skill.artifact_types,
            *skill.examples,
        ):
            if value and _contains_phrase(normalized, value):
                score += 2
        for tool_name in skill.tool_names:
            if tool_name and tool_name.casefold() in normalized:
                score += 3
        return score

    def _apply_intent_overrides(
        self,
        *,
        intent: str,
        intent_action: Any | None,
        scores: dict[str, int],
        reasons: dict[str, set[str]],
        global_reasons: set[str],
    ) -> None:
        lowered = intent.casefold()
        intent_action = intent_action or parse_agent_intent_action(intent)
        if any(term in lowered for term in CONCEPTUAL_TESTING_TERMS) and not any(
            term in lowered for term in (*SAVE_TERMS, *EXECUTE_TERMS, "创建", "生成", "更新", "删除")
        ):
            self._add_candidate(
                scores=scores,
                reasons=reasons,
                skill_name=GENERAL_TESTING_SKILL_NAME,
                score=12,
                reason="intent:conceptual_testing_answer",
            )
            global_reasons.add("planner:intent_conceptual_testing_answer")
        if any(term in lowered for term in CASE_CREATION_TERMS):
            self._add_candidate(
                scores=scores,
                reasons=reasons,
                skill_name=HTTP_CASE_SKILL_NAME,
                score=8,
                reason="intent:test_case_creation",
            )
            global_reasons.add("planner:intent_test_case_creation")
        if any(term in lowered for term in ENVIRONMENT_MANAGEMENT_TERMS):
            self._add_candidate(
                scores=scores,
                reasons=reasons,
                skill_name=ENVIRONMENT_SKILL_NAME,
                score=9,
                reason="intent:environment_management",
            )
            global_reasons.add("planner:intent_environment_management")
        if any(term in lowered for term in ("scenario", "场景", "自动化测试流程", "测试流程")):
            self._add_candidate(
                scores=scores,
                reasons=reasons,
                skill_name=SCENARIO_SKILL_NAME,
                score=5,
                reason="intent:scenario_domain",
            )
            global_reasons.add("planner:intent_scenario_domain")
        if any(term in lowered for term in REPORT_TERMS):
            report_score = 10 if any(term in lowered for term in ("report", "报告")) else 4
            self._add_candidate(
                scores=scores,
                reasons=reasons,
                skill_name=REPORT_SKILL_NAME,
                score=report_score,
                reason="intent:report_terms",
            )
        if any(term in lowered for term in EXECUTION_RECORD_TERMS) and any(
            term in lowered for term in EXECUTION_DIAGNOSIS_TERMS
        ):
            self._add_candidate(
                scores=scores,
                reasons=reasons,
                skill_name=EXECUTION_DIAGNOSIS_SKILL_NAME,
                score=12,
                reason="intent:execution_diagnosis",
            )
            global_reasons.add("planner:intent_execution_diagnosis")
        if any(term in lowered for term in TEST_PLAN_TERMS):
            self._add_candidate(
                scores=scores,
                reasons=reasons,
                skill_name=TEST_PLAN_SKILL_NAME,
                score=12,
                reason="intent:test_plan_management",
            )
            global_reasons.add("planner:intent_test_plan_management")
        if any(term in lowered for term in VISUAL_FLOW_TERMS):
            self._add_candidate(
                scores=scores,
                reasons=reasons,
                skill_name=VISUAL_FLOW_SKILL_NAME,
                score=11,
                reason="intent:visual_flow",
            )
            global_reasons.add("planner:intent_visual_flow")
        if any(term in lowered for term in DEFECT_TERMS):
            self._add_candidate(
                scores=scores,
                reasons=reasons,
                skill_name=DEFECT_SKILL_NAME,
                score=11,
                reason="intent:defect_triage",
            )
            global_reasons.add("planner:intent_defect_triage")
        if intent_action.target_domain == "defect":
            self._add_candidate(
                scores=scores,
                reasons=reasons,
                skill_name=DEFECT_SKILL_NAME,
                score=18,
                reason="intent_action:target_domain:defect",
            )
            global_reasons.add("planner:intent_defect_triage")
        if intent_action.target_domain == "test_case" and intent_action.action == "create":
            self._add_candidate(
                scores=scores,
                reasons=reasons,
                skill_name=HTTP_CASE_SKILL_NAME,
                score=18,
                reason="intent_action:target_domain:test_case",
            )
            global_reasons.add("planner:intent_test_case_creation")

    def _apply_artifact_context(
        self,
        *,
        intent: str,
        working_context: dict[str, Any] | None,
        scores: dict[str, int],
        reasons: dict[str, set[str]],
        global_reasons: set[str],
    ) -> None:
        if not isinstance(working_context, dict):
            return
        for action in self._artifact_actions(working_context, intent=intent):
            artifact_type = action.get("artifact_type")
            action_name = action.get("action")
            reason = f"artifact_action:{artifact_type}.{action_name}"
            if artifact_type in {"scenario_draft", "saved_scenario", "scenario_run_failure"}:
                self._add_candidate(
                    scores=scores,
                    reasons=reasons,
                    skill_name=SCENARIO_SKILL_NAME,
                    score=12,
                    reason=reason,
                )
                global_reasons.add("planner:artifact_context")
                global_reasons.add(reason)
            if artifact_type == "test_case_query_snapshot" and action_name in {"execute", "update_assertions"}:
                self._add_candidate(
                    scores=scores,
                    reasons=reasons,
                    skill_name=HTTP_CASE_SKILL_NAME,
                    score=8,
                    reason=reason,
                )
                global_reasons.add("planner:artifact_context")
                global_reasons.add(reason)

    def _artifact_actions(self, working_context: dict[str, Any], *, intent: str) -> tuple[dict[str, str], ...]:
        explicit = working_context.get("active_artifact_action")
        if isinstance(explicit, dict):
            action = self._action_from_item(
                explicit,
                intent=intent,
                explicit_action=str(explicit.get("action") or ""),
            )
            if action is not None:
                return (action,)

        actions: list[dict[str, str]] = []
        for item in self._artifact_items(working_context):
            action = self._action_from_item(item, intent=intent)
            if action is not None:
                actions.append(action)
        return tuple(actions)

    def _artifact_items(self, working_context: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        items: list[dict[str, Any]] = []
        for key in ("active_artifact_handles", "current_artifact_candidates"):
            value = working_context.get(key)
            if isinstance(value, list):
                items.extend(item for item in value if isinstance(item, dict))
        manifest = working_context.get("conversation_tool_artifact_manifest")
        if isinstance(manifest, dict) and isinstance(manifest.get("items"), list):
            items.extend(item for item in manifest["items"] if isinstance(item, dict))
        return tuple(items)

    def _action_from_item(
        self,
        item: dict[str, Any],
        *,
        intent: str,
        explicit_action: str = "",
    ) -> dict[str, str] | None:
        availability = self.artifact_resolver.availability_from_item(item)
        if availability is None or not availability.is_decision_source:
            return None
        actions = set(availability.available_followup_actions)
        artifact_type = availability.artifact_type
        action = explicit_action
        if not action and artifact_type == "scenario_draft" and "save" in actions:
            action = "save"
        if not action and artifact_type == "saved_scenario" and "execute" in actions:
            action = "execute"
        if not action and artifact_type == "scenario_run_failure" and "repair" in actions:
            action = "repair"
        if not action and artifact_type == "test_case_query_snapshot":
            if "update_assertions" in actions or "batch_update_assertions" in actions:
                action = "update_assertions"
            elif "execute" in actions:
                action = "execute"
        if not action:
            return None
        if not self._intent_accepts_artifact_action(artifact_type=artifact_type, action=action, intent=intent):
            return None
        return {"artifact_type": artifact_type, "action": action}

    def _intent_accepts_artifact_action(self, *, artifact_type: str, action: str, intent: str) -> bool:
        lowered = intent.casefold()
        if not lowered:
            return True
        intent_action = parse_agent_intent_action(intent)
        if artifact_type == "test_case_query_snapshot" and action == "update_assertions":
            if intent_action.target_domain and intent_action.target_domain != "test_case":
                return intent_action.is_deictic_followup
        if artifact_type == "scenario_draft" and action == "save":
            return any(term in lowered for term in SAVE_TERMS)
        if artifact_type == "saved_scenario" and action == "execute":
            return any(term in lowered for term in (*EXECUTE_TERMS, *DEICTIC_TERMS, "flow", "流程", "result", "结果"))
        if artifact_type == "scenario_run_failure" and action == "repair":
            return any(term in lowered for term in REPAIR_TERMS)
        return True

    def _ranked_candidates(
        self,
        *,
        scores: dict[str, int],
        reasons: dict[str, set[str]],
    ) -> tuple[AgentSkillPlanCandidate, ...]:
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[: self.max_candidates]
        return tuple(
            AgentSkillPlanCandidate(
                name=name,
                score=score,
                reasons=tuple(sorted(reasons.get(name, ()))),
            )
            for name, score in ranked
            if self.skill_registry.get_skill(name) is not None
        )

    def _add_candidate(
        self,
        *,
        scores: dict[str, int],
        reasons: dict[str, set[str]],
        skill_name: str,
        score: int,
        reason: str,
    ) -> None:
        if self.skill_registry.get_skill(skill_name) is None:
            return
        scores[skill_name] = scores.get(skill_name, 0) + max(0, score)
        reasons.setdefault(skill_name, set()).add(reason)


def _contains_phrase(normalized_intent: str, phrase: str) -> bool:
    value = phrase.casefold().strip()
    return bool(value and value in normalized_intent)


def _planner_confidence(score: int) -> float:
    if score <= 0:
        return 0.0
    return round(min(0.99, score / (score + 3)), 4)
