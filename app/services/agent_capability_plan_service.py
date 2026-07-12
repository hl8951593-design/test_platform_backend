from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import AgentCapabilityPlanRecord, AgentRun, AgentRuntimeSnapshot
from app.services.agent_skill_registry import AgentSkillRegistry


class CapabilityPlanError(ValueError):
    pass


class CapabilityPlanToolNotAllowed(CapabilityPlanError):
    def __init__(self, *, tool_name: str, capability_plan_id: str) -> None:
        self.tool_name = tool_name
        self.capability_plan_id = capability_plan_id
        super().__init__(f"tool {tool_name} is not allowed by capability plan {capability_plan_id}")


class CapabilityPlanNotActive(CapabilityPlanError):
    pass


@dataclass(frozen=True)
class CapabilityActivationResult:
    accepted: bool
    plan_id: str
    activated_tools: tuple[str, ...] = ()
    rejected_tools: tuple[str, ...] = ()
    rejection_reasons: dict[str, str] | None = None


class AgentCapabilityPlanService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_active_plan(
        self,
        *,
        run: AgentRun,
        iteration: int,
        context_plan: Any,
        intent_decision: Any,
        source: str,
        parent_capability_plan_id: str | None = None,
        revision: int | None = None,
        commit: bool = True,
    ) -> AgentCapabilityPlanRecord:
        if revision is None:
            latest_revision = self.db.scalar(
                select(AgentCapabilityPlanRecord.revision)
                .where(
                    AgentCapabilityPlanRecord.run_id == run.run_id,
                    AgentCapabilityPlanRecord.iteration == iteration,
                )
                .order_by(AgentCapabilityPlanRecord.revision.desc())
                .limit(1)
            )
            revision = 0 if latest_revision is None else int(latest_revision) + 1
        payload = _plan_payload(
            run=run,
            context_plan=context_plan,
            intent_decision=intent_decision,
            source=source,
            iteration=iteration,
            revision=revision,
            parent_capability_plan_id=parent_capability_plan_id,
        )
        record = AgentCapabilityPlanRecord(**payload)
        self.db.add(record)
        self.db.flush()
        run.active_capability_plan_id = record.capability_plan_id
        if commit:
            self.db.commit()
            self.db.refresh(record)
            self.db.refresh(run)
        return record

    def supersede_with_plan(
        self,
        *,
        current: AgentCapabilityPlanRecord,
        context_plan: Any,
        intent_decision: Any,
        source: str,
        commit: bool = True,
    ) -> AgentCapabilityPlanRecord:
        locked = self.db.scalar(
            select(AgentCapabilityPlanRecord)
            .where(AgentCapabilityPlanRecord.id == current.id)
            .with_for_update()
        )
        if locked is None or locked.status != "active":
            raise CapabilityPlanNotActive("capability plan is not active")
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == locked.run_id).with_for_update())
        if run is None:
            raise CapabilityPlanNotActive("capability plan run does not exist")
        locked.status = "superseded"
        replacement = self.create_active_plan(
            run=run,
            iteration=locked.iteration,
            context_plan=context_plan,
            intent_decision=intent_decision,
            source=source,
            parent_capability_plan_id=locked.capability_plan_id,
            revision=locked.revision + 1,
            commit=False,
        )
        if commit:
            self.db.commit()
            self.db.refresh(locked)
            self.db.refresh(replacement)
            self.db.refresh(run)
        return replacement

    def get_active_plan(
        self,
        *,
        run: AgentRun,
        capability_plan_id: str | None = None,
        for_update: bool = False,
    ) -> AgentCapabilityPlanRecord:
        expected_id = capability_plan_id or run.active_capability_plan_id
        if not expected_id:
            raise CapabilityPlanNotActive("run has no active capability plan")
        statement = select(AgentCapabilityPlanRecord).where(
            AgentCapabilityPlanRecord.capability_plan_id == expected_id,
            AgentCapabilityPlanRecord.run_id == run.run_id,
            AgentCapabilityPlanRecord.status == "active",
        )
        if for_update:
            statement = statement.with_for_update()
        plan = self.db.scalar(statement)
        if plan is None or run.active_capability_plan_id != expected_id:
            raise CapabilityPlanNotActive("capability plan is not the run's active plan")
        return plan

    def require_tool_membership(
        self,
        *,
        run: AgentRun,
        capability_plan_id: str,
        tool_name: str,
    ) -> AgentCapabilityPlanRecord:
        plan = self.get_active_plan(
            run=run,
            capability_plan_id=capability_plan_id,
            for_update=True,
        )
        if tool_name not in set(plan.allowed_tools_json or []):
            raise CapabilityPlanToolNotAllowed(
                tool_name=tool_name,
                capability_plan_id=capability_plan_id,
            )
        return plan

    def request_capabilities(
        self,
        *,
        run: AgentRun,
        current: AgentCapabilityPlanRecord,
        tool_names: tuple[str, ...] | list[str],
        reason: str,
        permission_names: tuple[str, ...] | list[str] | None = None,
        commit: bool = True,
    ) -> CapabilityActivationResult:
        requested = tuple(dict.fromkeys(str(name).strip() for name in tool_names if str(name).strip()))
        if not requested:
            return CapabilityActivationResult(
                accepted=False,
                plan_id=current.capability_plan_id,
                rejection_reasons={"request": "tool_names_empty"},
            )

        snapshot = self.db.scalar(
            select(AgentRuntimeSnapshot).where(
                AgentRuntimeSnapshot.snapshot_id == current.runtime_snapshot_id,
                AgentRuntimeSnapshot.project_id == run.project_id,
            )
        )
        runtime_tools = {
            str(item.get("name") or ""): item
            for item in (snapshot.tools_json if snapshot is not None else [])
            if isinstance(item, dict) and item.get("name")
        }
        frozen_skill_manifests = (
            (snapshot.manifests_json or {}).get("skills")
            if snapshot is not None
            else None
        )
        registry_skills = (
            AgentSkillRegistry.from_snapshot_manifests(frozen_skill_manifests).list_skills()
            if isinstance(frozen_skill_manifests, dict) and frozen_skill_manifests
            else AgentSkillRegistry().list_skills()
        )
        declaring_skills: dict[str, tuple[str, ...]] = {
            tool_name: tuple(skill.name for skill in registry_skills if tool_name in skill.tool_names)
            for tool_name in requested
        }
        permission_set = set(permission_names or ())
        rejection_reasons: dict[str, str] = {}
        for tool_name in requested:
            tool = runtime_tools.get(tool_name)
            if tool is None:
                rejection_reasons[tool_name] = "tool_not_in_runtime_snapshot"
                continue
            if not declaring_skills.get(tool_name) and tool_name not in {"project.read_context", "tool_result.read_full"}:
                rejection_reasons[tool_name] = "tool_not_declared_by_registered_skill"
                continue
            if permission_names is not None:
                required = {
                    str(item)
                    for item in (tool.get("required_permissions") or [])
                    if str(item)
                }
                missing = sorted(required - permission_set)
                if missing:
                    rejection_reasons[tool_name] = f"missing_permissions:{','.join(missing)}"
        if rejection_reasons:
            return CapabilityActivationResult(
                accepted=False,
                plan_id=current.capability_plan_id,
                rejected_tools=tuple(name for name in requested if name in rejection_reasons),
                rejection_reasons=rejection_reasons,
            )

        locked = self.db.scalar(
            select(AgentCapabilityPlanRecord)
            .where(AgentCapabilityPlanRecord.id == current.id)
            .with_for_update()
        )
        if locked is None or locked.status != "active" or run.active_capability_plan_id != locked.capability_plan_id:
            raise CapabilityPlanNotActive("capability plan is not active")

        activated_tools = tuple(name for name in requested if name not in set(locked.allowed_tools_json or ()))
        if not activated_tools:
            return CapabilityActivationResult(
                accepted=True,
                plan_id=locked.capability_plan_id,
            )

        locked.status = "superseded"
        allowed_tools = list(dict.fromkeys([*(locked.allowed_tools_json or ()), *activated_tools]))
        tool_aliases = dict(locked.tool_aliases_json or {})
        for tool_name in activated_tools:
            tool_aliases[provider_tool_alias(tool_name)] = tool_name
        skill_plan = dict(locked.skill_plan_json or {})
        selected_skill_names = list(skill_plan.get("selected_skill_names") or skill_plan.get("allowed_skills") or ())
        for tool_name in activated_tools:
            for skill_name in declaring_skills.get(tool_name, ()):
                if skill_name not in selected_skill_names:
                    selected_skill_names.append(skill_name)
        skill_plan["selected_skill_names"] = selected_skill_names
        reason_codes = list(locked.reason_codes_json or ())
        reason_codes.extend(f"capability_activation:{name}" for name in activated_tools)
        revision = locked.revision + 1
        hash_payload = {
            "run_id": run.run_id,
            "iteration": locked.iteration,
            "revision": revision,
            "runtime_snapshot_id": locked.runtime_snapshot_id,
            "intent_decision": locked.intent_decision_json,
            "skill_plan": skill_plan,
            "allowed_tools": allowed_tools,
            "tool_aliases": tool_aliases,
            "required_facts": locked.required_facts_json,
            "reason_codes": reason_codes,
            "activation_reason": reason[:1000],
        }
        replacement = AgentCapabilityPlanRecord(
            capability_plan_id=f"agent-cap-plan-{uuid.uuid4().hex}",
            run_id=run.run_id,
            iteration=locked.iteration,
            revision=revision,
            parent_capability_plan_id=locked.capability_plan_id,
            runtime_snapshot_id=locked.runtime_snapshot_id,
            status="active",
            source="llm_capability_request",
            intent_decision_json=dict(locked.intent_decision_json or {}),
            skill_plan_json=skill_plan,
            allowed_tools_json=allowed_tools,
            tool_aliases_json=tool_aliases,
            required_facts_json=list(locked.required_facts_json or ()),
            reason_codes_json=reason_codes,
            plan_hash=hashlib.sha256(
                json.dumps(hash_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        )
        self.db.add(replacement)
        self.db.flush()
        run.active_capability_plan_id = replacement.capability_plan_id
        if commit:
            self.db.commit()
            self.db.refresh(locked)
            self.db.refresh(replacement)
            self.db.refresh(run)
        return CapabilityActivationResult(
            accepted=True,
            plan_id=replacement.capability_plan_id,
            activated_tools=activated_tools,
        )

    def carry_forward_plan(
        self,
        *,
        run: AgentRun,
        current: AgentCapabilityPlanRecord,
        iteration: int,
        commit: bool = True,
    ) -> AgentCapabilityPlanRecord:
        locked = self.db.scalar(
            select(AgentCapabilityPlanRecord)
            .where(AgentCapabilityPlanRecord.id == current.id)
            .with_for_update()
        )
        if locked is None or locked.status != "active" or run.active_capability_plan_id != locked.capability_plan_id:
            raise CapabilityPlanNotActive("capability plan is not active")
        if iteration <= locked.iteration:
            raise CapabilityPlanError("carry-forward iteration must advance")
        locked.status = "superseded"
        hash_payload = {
            "run_id": run.run_id,
            "iteration": iteration,
            "revision": 0,
            "runtime_snapshot_id": locked.runtime_snapshot_id,
            "intent_decision": locked.intent_decision_json,
            "skill_plan": locked.skill_plan_json,
            "allowed_tools": locked.allowed_tools_json,
            "tool_aliases": locked.tool_aliases_json,
        }
        replacement = AgentCapabilityPlanRecord(
            capability_plan_id=f"agent-cap-plan-{uuid.uuid4().hex}",
            run_id=run.run_id,
            iteration=iteration,
            revision=0,
            parent_capability_plan_id=locked.capability_plan_id,
            runtime_snapshot_id=locked.runtime_snapshot_id,
            status="active",
            source="carry_forward",
            intent_decision_json=dict(locked.intent_decision_json or {}),
            skill_plan_json=dict(locked.skill_plan_json or {}),
            allowed_tools_json=list(locked.allowed_tools_json or ()),
            tool_aliases_json=dict(locked.tool_aliases_json or {}),
            required_facts_json=list(locked.required_facts_json or ()),
            reason_codes_json=list(locked.reason_codes_json or ()),
            plan_hash=hashlib.sha256(
                json.dumps(hash_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        )
        self.db.add(replacement)
        self.db.flush()
        run.active_capability_plan_id = replacement.capability_plan_id
        if commit:
            self.db.commit()
            self.db.refresh(locked)
            self.db.refresh(replacement)
            self.db.refresh(run)
        return replacement


def provider_tool_alias(tool_name: str) -> str:
    readable = re.sub(r"[^a-zA-Z0-9_-]+", "_", tool_name).strip("_") or "tool"
    digest = hashlib.sha256(tool_name.encode("utf-8")).hexdigest()[:8]
    return f"{readable[:48]}_{digest}"


def _plan_payload(
    *,
    run: AgentRun,
    context_plan: Any,
    intent_decision: Any,
    source: str,
    iteration: int,
    revision: int,
    parent_capability_plan_id: str | None,
) -> dict[str, Any]:
    allowed_tools = list(context_plan.allowed_tools)
    intent_view = _model_view(intent_decision)
    skill_view = (
        context_plan.skill_plan.model_view()
        if context_plan.skill_plan is not None
        else {
            "source": "llm_planning",
            "primary_skill": context_plan.primary_skill,
            "supporting_skills": list(context_plan.supporting_skills),
            "selected_skill_names": list(context_plan.skill_names),
            "allowed_skills": list(context_plan.skill_names),
        }
    )
    capability_view = context_plan.capability_plan.model_view() if context_plan.capability_plan is not None else {}
    tool_aliases = {provider_tool_alias(name): name for name in allowed_tools}
    hash_payload = {
        "run_id": run.run_id,
        "iteration": iteration,
        "revision": revision,
        "runtime_snapshot_id": run.runtime_snapshot_id,
        "intent_decision": intent_view,
        "skill_plan": skill_view,
        "allowed_tools": allowed_tools,
        "tool_aliases": tool_aliases,
    }
    plan_hash = hashlib.sha256(
        json.dumps(hash_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "capability_plan_id": f"agent-cap-plan-{uuid.uuid4().hex}",
        "run_id": run.run_id,
        "iteration": iteration,
        "revision": revision,
        "parent_capability_plan_id": parent_capability_plan_id,
        "runtime_snapshot_id": run.runtime_snapshot_id,
        "status": "active",
        "source": source,
        "intent_decision_json": intent_view,
        "skill_plan_json": skill_view,
        "allowed_tools_json": allowed_tools,
        "tool_aliases_json": tool_aliases,
        "required_facts_json": list(capability_view.get("required_facts") or []),
        "reason_codes_json": list(capability_view.get("reason_codes") or []),
        "plan_hash": plan_hash,
    }


def _model_view(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_view"):
        return dict(value.model_view())
    return {
        key: getattr(value, key)
        for key in ("action", "target_domain", "source_domains", "confidence", "source", "reason_codes")
        if hasattr(value, key)
    }


def tool_matches_intent_decision(tool_name: str, decision: dict[str, Any]) -> bool:
    target = str(decision.get("target_domain") or "")
    action = str(decision.get("action") or "")
    if decision.get("write_authorized") is False and action in {"create", "update", "delete", "transition", "execute"}:
        return False
    prefixes = {
        "defect": ("defect.",),
        "test_case": ("testcase.", "websocket_testcase."),
        "scenario": ("scenario.",),
        "test_plan": ("plan.",),
        "visual_flow": ("flow.",),
        "execution": ("execution.",),
        "report": ("report.",),
        "environment": ("environment.",),
        "media": ("media.",),
    }
    if target and not tool_name.startswith(prefixes.get(target, (f"{target}.",))):
        return False
    action_markers = {
        "create": (".create_", ".compose_", ".upsert_"),
        "update": (".update_", ".upsert_"),
        "execute": (".execute_", ".run_"),
        "delete": (".delete_",),
        "transition": (".transition_",),
        "query": (".query_", ".read_"),
        "analyze": (".diagnose", ".analyze", ".read_", ".query_"),
        "export": (".export",),
    }
    markers = action_markers.get(action)
    return markers is None or any(marker in tool_name for marker in markers)
