from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.sensitive_data import request_fingerprint
from app.models.agent import (
    AgentContextBuild,
    AgentEvidenceWatch,
    AgentLoopObservation,
    AgentMemoryContradictionEvent,
    AgentRootCauseRule,
    AgentRun,
)
from app.models.user import User
from app.schemas.agent import AgentContextBuildCreateRequest, AgentLoopObservationCreateRequest
from app.services.permission_service import PermissionService


FROZEN_MUTABILITY_CLASSES = {"immutable", "versioned"}
VOLATILE_MUTABILITY_CLASSES = {"mutable_current", "ephemeral_latest", "external_uncontrolled"}
EVIDENCE_MUTABILITY_CLASSES = FROZEN_MUTABILITY_CLASSES | VOLATILE_MUTABILITY_CLASSES
ACTIVE_POLICY_DEPENDENCY_ROLES = {"decision_dependency", "validation_evidence", "policy_dependency"}
AUDIT_DEPENDENCY_ROLES = {"audit_background", "trace_only", "superseded"}
EVIDENCE_DEPENDENCY_ROLES = ACTIVE_POLICY_DEPENDENCY_ROLES | AUDIT_DEPENDENCY_ROLES
EVIDENCE_FRESHNESS_POLICIES = {"none", "revalidate_on_resume", "revalidate_before_side_effect"}
DEFAULT_EVIDENCE_MUTABILITY_CLASS = "mutable_current"
DEFAULT_EVIDENCE_DEPENDENCY_ROLE = "audit_background"
HIGH_RISK_SIDE_EFFECT_CLASSES = {"business_create", "business_update", "destructive", "external_effect"}
DEGRADATION_RANK = {"none": 0, "light": 1, "medium": 2, "heavy": 3}
ROOT_CAUSE_PRIORITY_BANDS = {
    "safety": (1, 19),
    "evidence_context": (20, 39),
    "recovery": (40, 59),
    "repair_quality": (60, 79),
    "resource_limit": (80, 89),
    "fallback": (900, 999),
}
ROOT_CAUSE_DEFAULT_RULE_CONTRACT = {
    "RC_CONTEXT_OMITTED_HIGH_RISK": {"priority_band": "safety", "priority": 10},
    "RC_PERMISSION_REVOKED": {"priority_band": "safety", "priority": 15},
    "RC_POLICY_LOOP": {"priority_band": "safety", "priority": 18},
    "RC_EVIDENCE_INCOMPLETE": {"priority_band": "evidence_context", "priority": 20},
    "RC_MEMORY_CONTRADICTION": {"priority_band": "evidence_context", "priority": 30},
    "RC_APPROVAL_PENDING": {"priority_band": "recovery", "priority": 40},
    "RC_BACKEND_CAPABILITY_DEGRADED": {"priority_band": "recovery", "priority": 45},
    "RC_NO_PROGRESS_PURE": {"priority_band": "repair_quality", "priority": 60},
    "RC_REPAIR_REGRESSION": {"priority_band": "repair_quality", "priority": 65},
    "RC_MAX_ITERATIONS": {"priority_band": "resource_limit", "priority": 80},
    "RC_RESOURCE_LIMIT": {"priority_band": "resource_limit", "priority": 85},
    "RC_UNKNOWN": {"priority_band": "fallback", "priority": 900},
    "RC_RULE_MISSING": {"priority_band": "fallback", "priority": 999},
}
ROOT_CAUSE_GOVERNANCE_FIELDS = {"priority_bands", "violations", "violation_count", "governance_pass"}
ROOT_CAUSE_NEW_RULE_REQUIRED_FIXTURE_COUNT = 3
ROOT_CAUSE_FALLBACK_RULE_ID = "RC_RULE_MISSING"
ROOT_CAUSE_ACCEPTED_UNKNOWN_RULE_ID = "RC_UNKNOWN"
ROOT_CAUSE_MISSING_RULE_METRIC = "root_cause_rule_missing_total"

CONTEXT_BUILD_FIELDS = (
    "context_build_id",
    "run_id",
    "iteration",
    "step_index",
    "build_seq",
    "build_purpose",
    "model_name",
    "token_budget",
    "estimated_input_tokens",
    "context_degradation_level",
    "compressed_sections_json",
    "omitted_evidence_refs_json",
    "required_evidence_refs_json",
    "required_evidence_complete",
    "decision_quality_risk",
    "prompt_object_key",
    "prompt_hash",
    "build_metadata_json",
    "created_at",
)

LOOP_OBSERVATION_FIELDS = (
    "observation_id",
    "run_id",
    "iteration",
    "step_index",
    "decision_context_build_id",
    "decision_context_degradation_level",
    "iteration_context_degradation_max",
    "required_evidence_complete_for_decision",
    "omitted_required_evidence_refs_json",
    "next_action",
    "next_action_is_high_risk",
    "stop_action_reason",
    "stop_reasons_all_json",
    "root_cause_primary",
    "root_cause_rule_id",
    "causal_chain_json",
    "mitigation_action",
    "observation_json",
    "created_at",
)


@dataclass(frozen=True)
class EvidenceRef:
    evidence_ref_id: str
    ref_type: str
    ref_id: str
    mutability_class: str
    dependency_role: str
    active_for_policy: bool
    version_id: str | None = None
    content_hash: str | None = None
    snapshot_id: str | None = None
    captured_at: str | None = None
    freshness_policy: str | None = None
    superseded_by_ref: str | None = None
    required_for_high_risk: bool = False
    authority: str | None = None
    raw: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        payload = {
            "evidence_ref_id": self.evidence_ref_id,
            "ref_type": self.ref_type,
            "ref_id": self.ref_id,
            "mutability_class": self.mutability_class,
            "dependency_role": self.dependency_role,
            "active_for_policy": self.active_for_policy,
            "version_id": self.version_id,
            "content_hash": self.content_hash,
            "snapshot_id": self.snapshot_id,
            "captured_at": self.captured_at,
            "freshness_policy": self.freshness_policy,
            "superseded_by_ref": self.superseded_by_ref,
            "required_for_high_risk": self.required_for_high_risk,
            "authority": self.authority,
        }
        return {key: value for key, value in payload.items() if value is not None}


class EvidenceRefResolver:
    def parse(self, evidence_refs: list[dict[str, Any]]) -> list[EvidenceRef]:
        parsed: list[EvidenceRef] = []
        for index, raw_ref in enumerate(evidence_refs):
            ref_type = str(raw_ref.get("ref_type") or raw_ref.get("type") or "unknown")
            ref_id = str(raw_ref.get("ref_id") or raw_ref.get("id") or f"inline-{index}")
            evidence_ref_id = str(raw_ref.get("evidence_ref_id") or raw_ref.get("ref_key") or f"{ref_type}:{ref_id}")
            dependency_role = str(
                raw_ref.get("dependency_role")
                or raw_ref.get("usage_role")
                or DEFAULT_EVIDENCE_DEPENDENCY_ROLE
            )
            parsed.append(
                EvidenceRef(
                    evidence_ref_id=evidence_ref_id,
                    ref_type=ref_type,
                    ref_id=ref_id,
                    mutability_class=str(raw_ref.get("mutability_class") or DEFAULT_EVIDENCE_MUTABILITY_CLASS),
                    dependency_role=dependency_role,
                    active_for_policy=bool(raw_ref.get("active_for_policy", False)),
                    version_id=_optional_str(raw_ref.get("version_id")),
                    content_hash=_optional_str(raw_ref.get("content_hash")),
                    snapshot_id=_optional_str(raw_ref.get("snapshot_id")),
                    captured_at=_optional_str(raw_ref.get("captured_at")),
                    freshness_policy=_optional_str(raw_ref.get("freshness_policy")),
                    superseded_by_ref=_optional_str(raw_ref.get("superseded_by_ref")),
                    required_for_high_risk=bool(raw_ref.get("required_for_high_risk", False)),
                    authority=_optional_str(raw_ref.get("authority")),
                    raw=dict(raw_ref),
                )
            )
        return parsed

    def select_policy_refs(self, evidence_refs: list[dict[str, Any]]) -> list[EvidenceRef]:
        return [
            ref for ref in self.parse(evidence_refs)
            if ref.active_for_policy
            and ref.dependency_role in ACTIVE_POLICY_DEPENDENCY_ROLES
            and ref.dependency_role != "superseded"
            and ref.superseded_by_ref is None
        ]

    def split_policy_and_audit_refs(
        self,
        evidence_refs: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        parsed = self.parse(evidence_refs)
        policy_ids = {item.evidence_ref_id for item in self.select_policy_refs(evidence_refs)}
        policy_refs = [item.to_json() for item in parsed if item.evidence_ref_id in policy_ids]
        audit_refs = [item.to_json() for item in parsed if item.evidence_ref_id not in policy_ids]
        summary: dict[str, Any] = {
            "total": len(parsed),
            "policy_ref_count": len(policy_refs),
            "audit_ref_count": len(audit_refs),
            "requires_revalidation": self.evidence_requires_revalidation(policy_refs),
            "fully_frozen": self.evidence_fully_frozen(policy_refs),
            "by_mutability": {},
        }
        for ref in parsed:
            summary["by_mutability"][ref.mutability_class] = summary["by_mutability"].get(ref.mutability_class, 0) + 1
        return policy_refs, audit_refs, summary

    def evidence_requires_revalidation(self, policy_refs: list[dict[str, Any]]) -> bool:
        return any(ref.get("mutability_class") in VOLATILE_MUTABILITY_CLASSES for ref in policy_refs)

    def evidence_fully_frozen(self, policy_refs: list[dict[str, Any]]) -> bool:
        if not policy_refs:
            return True
        return all(
            ref.get("mutability_class") in FROZEN_MUTABILITY_CLASSES
            and (ref.get("content_hash") or ref.get("version_id") or ref.get("snapshot_id"))
            for ref in policy_refs
        )


class EvidenceWatchService:
    def __init__(self, db: Session):
        self.db = db

    def register_watches(
        self,
        *,
        run: AgentRun,
        evidence_refs: list[dict[str, Any]],
        tool_call_id: str | None = None,
        commit: bool = True,
    ) -> list[AgentEvidenceWatch]:
        watches: list[AgentEvidenceWatch] = []
        for ref in EvidenceRefResolver().parse(evidence_refs):
            if not ref.active_for_policy:
                continue
            existing = self.db.scalar(
                select(AgentEvidenceWatch).where(
                    AgentEvidenceWatch.run_id == run.run_id,
                    AgentEvidenceWatch.evidence_ref_id == ref.evidence_ref_id,
                    AgentEvidenceWatch.watch_status == "active",
                )
            )
            if existing is not None:
                watches.append(existing)
                continue
            watch = AgentEvidenceWatch(
                evidence_watch_id=f"agent-watch-{uuid.uuid4().hex}",
                run_id=run.run_id,
                tool_call_id=tool_call_id,
                evidence_ref_id=ref.evidence_ref_id,
                ref_type=ref.ref_type,
                ref_id=ref.ref_id,
                watched_version_id=ref.version_id,
                watched_content_hash=ref.content_hash,
                watch_status="active",
            )
            self.db.add(watch)
            watches.append(watch)
        if commit:
            self.db.commit()
            for watch in watches:
                self.db.refresh(watch)
        else:
            self.db.flush()
        return watches

    def mark_stale_by_ref(
        self,
        *,
        ref_type: str,
        ref_id: str,
        stale_reason: str,
        stale_event_id: str | None = None,
    ) -> int:
        now = _utcnow()
        watches = list(
            self.db.scalars(
                select(AgentEvidenceWatch)
                .where(
                    AgentEvidenceWatch.ref_type == ref_type,
                    AgentEvidenceWatch.ref_id == ref_id,
                    AgentEvidenceWatch.watch_status == "active",
                )
                .with_for_update()
            ).all()
        )
        for watch in watches:
            watch.watch_status = "stale"
            watch.stale_reason = stale_reason
            watch.stale_event_id = stale_event_id
            watch.stale_at = now
        self.db.commit()
        return len(watches)


class ContextBuilder:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def build(
        self,
        *,
        run_id: str,
        payload: AgentContextBuildCreateRequest,
        current_user: User,
        commit: bool = True,
    ) -> AgentContextBuild:
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id).with_for_update())
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
        self.permission_service.require_project_access(current_user, run.project_id)
        max_seq = self.db.scalar(
            select(func.max(AgentContextBuild.build_seq)).where(
                AgentContextBuild.run_id == run.run_id,
                AgentContextBuild.iteration == run.current_iteration,
                AgentContextBuild.step_index == payload.step_index,
            )
        ) or 0
        evidence_refs = EvidenceRefResolver().parse(payload.evidence_refs)
        self._ensure_memory_usage_wrapped(run=run, payload=payload, evidence_refs=evidence_refs)
        estimated_tokens = _estimate_tokens({
            "intent": run.intent,
            "purpose": payload.build_purpose,
            "evidence_refs": [item.to_json() for item in evidence_refs],
        })
        kept_refs, omitted_refs, degradation = _apply_budget(evidence_refs, estimated_tokens, payload.token_budget)
        omitted_ids = {item.evidence_ref_id for item in omitted_refs}
        required_complete = not any(ref_id in omitted_ids for ref_id in payload.required_evidence_ref_ids)
        risk = _decision_quality_risk(degradation=degradation, required_complete=required_complete)
        build = AgentContextBuild(
            context_build_id=f"agent-ctx-{uuid.uuid4().hex}",
            run_id=run.run_id,
            iteration=run.current_iteration,
            step_index=payload.step_index,
            build_seq=max_seq + 1,
            build_purpose=payload.build_purpose,
            model_name=payload.model_name,
            token_budget=payload.token_budget,
            estimated_input_tokens=estimated_tokens,
            context_degradation_level=degradation,
            compressed_sections_json={"kept_evidence_ref_count": len(kept_refs)} if degradation != "none" else None,
            omitted_evidence_refs_json=[item.to_json() for item in omitted_refs] or None,
            required_evidence_refs_json=list(payload.required_evidence_ref_ids),
            required_evidence_complete=required_complete,
            decision_quality_risk=risk,
            prompt_object_key=payload.prompt_object_key,
            prompt_hash=request_fingerprint({
                "run_id": run.run_id,
                "build_seq": max_seq + 1,
                "kept_refs": [item.to_json() for item in kept_refs],
            }),
            build_metadata_json={
                "policy_refs": [
                    item.to_json()
                    for item in EvidenceRefResolver().select_policy_refs([ref.raw or ref.to_json() for ref in evidence_refs])
                ],
            },
        )
        self.db.add(build)
        from app.services.agent_runtime_service import AgentRuntimeService

        runtime = AgentRuntimeService(self.db)
        if degradation != "none":
            runtime.append_event(
                run,
                "context.degraded",
                {"context_build_id": build.context_build_id, "degradation": degradation},
                commit=False,
            )
        if omitted_refs:
            runtime.append_event(
                run,
                "context.evidence_omitted",
                {
                    "context_build_id": build.context_build_id,
                    "omitted_evidence_ref_ids": [item.evidence_ref_id for item in omitted_refs],
                },
                commit=False,
            )
        if not required_complete:
            runtime.append_event(
                run,
                "context.full_evidence_required",
                {"context_build_id": build.context_build_id},
                commit=False,
            )
        runtime.append_event(
            run,
            "context.decision_context_bound",
            {"context_build_id": build.context_build_id, "build_purpose": build.build_purpose},
            commit=False,
        )
        EvidenceWatchService(self.db).register_watches(
            run=run,
            evidence_refs=[item.raw or item.to_json() for item in evidence_refs],
            commit=False,
        )
        if commit:
            self.db.commit()
            self.db.refresh(build)
        else:
            self.db.flush()
        return build

    def _ensure_memory_usage_wrapped(
        self,
        *,
        run: AgentRun,
        payload: AgentContextBuildCreateRequest,
        evidence_refs: list[EvidenceRef],
    ) -> None:
        memory_ids_used = {int(memory_id) for memory_id in payload.memory_ids_used}
        if not memory_ids_used:
            return
        wrapped_memory_ids: set[int] = set()
        for ref in evidence_refs:
            if ref.ref_type != "memory":
                continue
            if not (
                ref.active_for_policy
                and ref.dependency_role in {"decision_dependency", "validation_evidence", "policy_dependency"}
                and ref.superseded_by_ref is None
            ):
                continue
            try:
                wrapped_memory_ids.add(int(ref.ref_id))
            except ValueError:
                continue
        missing = sorted(memory_ids_used - wrapped_memory_ids)
        if not missing:
            return

        from app.services.agent_runtime_service import AgentRuntimeService

        AgentRuntimeService(self.db).append_event(
            run,
            "memory.bypassed_evidence_ref",
            {
                "step_index": payload.step_index,
                "build_purpose": payload.build_purpose,
                "memory_ids": missing,
                "reason": "memory_ids_used_missing_active_policy_memory_evidence_ref",
            },
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "memory_bypassed_evidence_ref", "memory_ids": missing},
        )


class RootCauseRuleEngine:
    def __init__(self, db: Session):
        self.db = db

    PRIORITY_BANDS = ROOT_CAUSE_PRIORITY_BANDS

    def ensure_default_rules(self) -> None:
        existing = set(self.db.scalars(select(AgentRootCauseRule.rule_id)).all())
        for rule in _default_root_cause_rules():
            if rule["rule_id"] in existing:
                continue
            self.db.add(AgentRootCauseRule(**rule))
        self.db.flush()

    def audit_rule_governance(self) -> dict[str, Any]:
        self.ensure_default_rules()
        rules = list(
            self.db.scalars(
                select(AgentRootCauseRule).order_by(AgentRootCauseRule.priority.asc(), AgentRootCauseRule.rule_id.asc())
            ).all()
        )
        violations: list[dict[str, Any]] = []
        for rule in rules:
            band_range = self.PRIORITY_BANDS.get(rule.priority_band)
            if band_range is None:
                violations.append({
                    "rule_id": rule.rule_id,
                    "priority": rule.priority,
                    "priority_band": rule.priority_band,
                    "violation": "unknown_priority_band",
                })
                continue
            lower, upper = band_range
            if not lower <= rule.priority <= upper:
                violations.append({
                    "rule_id": rule.rule_id,
                    "priority": rule.priority,
                    "priority_band": rule.priority_band,
                    "expected_range": [lower, upper],
                    "violation": "priority_outside_band",
                })
        return {
            "rule_count": len(rules),
            "priority_bands": {
                band: {"min": lower, "max": upper}
                for band, (lower, upper) in self.PRIORITY_BANDS.items()
            },
            "violation_count": len(violations),
            "violations": violations,
            "governance_pass": not violations,
        }

    def evaluate(self, *, reasons: list[str], observation: dict[str, Any]) -> AgentRootCauseRule:
        self.ensure_default_rules()
        rules = list(
            self.db.scalars(
                select(AgentRootCauseRule)
                .where(AgentRootCauseRule.status == "active")
                .order_by(AgentRootCauseRule.priority.asc(), AgentRootCauseRule.rule_id.asc())
            ).all()
        )
        for rule in rules:
            if _matches_rule(rule.match_expression_json, reasons=reasons, observation=observation):
                return rule
        missing = self.db.scalar(select(AgentRootCauseRule).where(AgentRootCauseRule.rule_id == "RC_RULE_MISSING"))
        if missing is None:
            raise RuntimeError("default root cause rule RC_RULE_MISSING was not seeded")
        return missing


class LoopController:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def record_observation(
        self,
        *,
        run_id: str,
        payload: AgentLoopObservationCreateRequest,
        current_user: User,
    ) -> AgentLoopObservation:
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id).with_for_update())
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
        self.permission_service.require_project_access(current_user, run.project_id)
        build = self.db.scalar(
            select(AgentContextBuild).where(AgentContextBuild.context_build_id == payload.decision_context_build_id)
        )
        if build is None or build.run_id != run.run_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent context build not found")

        observation_payload = self._memory_observation_from_build(build=build, observation=payload.observation)
        reasons = list(dict.fromkeys(payload.reasons))
        if payload.next_action_is_high_risk and not build.required_evidence_complete:
            reasons.append("evidence_incomplete_for_high_risk_action")
        if build.context_degradation_level == "heavy":
            reasons.append("context_degraded_heavy")
        reasons = list(dict.fromkeys(reasons))
        iteration_max = self._iteration_degradation_max(run=run, build=build)
        rule = RootCauseRuleEngine(self.db).evaluate(
            reasons=reasons,
            observation={
                **observation_payload,
                "decision_context_degradation_level": build.context_degradation_level,
                "required_evidence_complete_for_decision": build.required_evidence_complete,
                "next_action_is_high_risk": payload.next_action_is_high_risk,
            },
        )
        stop_reason = _primary_stop_reason(reasons)
        observation = AgentLoopObservation(
            observation_id=f"agent-obs-{uuid.uuid4().hex}",
            run_id=run.run_id,
            iteration=build.iteration,
            step_index=build.step_index,
            decision_context_build_id=build.context_build_id,
            decision_context_degradation_level=build.context_degradation_level,
            iteration_context_degradation_max=iteration_max,
            required_evidence_complete_for_decision=build.required_evidence_complete,
            omitted_required_evidence_refs_json=build.omitted_evidence_refs_json,
            next_action=payload.next_action,
            next_action_is_high_risk=payload.next_action_is_high_risk,
            stop_action_reason=stop_reason,
            stop_reasons_all_json=reasons,
            root_cause_primary=rule.root_cause_primary,
            root_cause_rule_id=rule.rule_id,
            causal_chain_json=rule.causal_chain_json,
            mitigation_action=rule.mitigation_action,
            observation_json=observation_payload,
        )
        self.db.add(observation)
        from app.services.agent_runtime_service import AgentRuntimeService

        AgentRuntimeService(self.db).append_event(
            run,
            "loop.observed",
            {
                "observation_id": observation.observation_id,
                "decision_context_build_id": build.context_build_id,
                "root_cause_rule_id": rule.rule_id,
            },
            commit=False,
        )
        self.db.commit()
        self.db.refresh(observation)
        return observation

    def _memory_observation_from_build(
        self,
        *,
        build: AgentContextBuild,
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        enriched = dict(observation)
        policy_refs = (build.build_metadata_json or {}).get("policy_refs") or []
        memory_ids: list[int] = []
        for ref in policy_refs:
            if ref.get("ref_type") != "memory":
                continue
            if not (
                ref.get("active_for_policy") is True
                and ref.get("dependency_role") in ACTIVE_POLICY_DEPENDENCY_ROLES
                and ref.get("superseded_by_ref") is None
            ):
                continue
            try:
                memory_ids.append(int(ref.get("ref_id")))
            except (TypeError, ValueError):
                continue
        memory_ids = sorted(set(memory_ids))
        if not memory_ids:
            return enriched

        enriched.setdefault(
            "memory_usage",
            {
                "memory_ids": memory_ids,
                "active_policy_count": len(memory_ids),
            },
        )
        enriched.setdefault("memory_used_count", len(memory_ids))
        if "memory_contradiction_delta" not in enriched:
            contradiction_count = self.db.scalar(
                select(func.count(AgentMemoryContradictionEvent.id)).where(
                    AgentMemoryContradictionEvent.memory_id.in_(memory_ids)
                )
            ) or 0
            enriched["memory_contradiction_delta"] = contradiction_count
        return enriched

    def _iteration_degradation_max(self, *, run: AgentRun, build: AgentContextBuild) -> str:
        builds = list(
            self.db.scalars(
                select(AgentContextBuild).where(
                    AgentContextBuild.run_id == run.run_id,
                    AgentContextBuild.iteration == build.iteration,
                )
            ).all()
        )
        if not builds:
            return build.context_degradation_level
        return max((item.context_degradation_level for item in builds), key=lambda value: DEGRADATION_RANK.get(value, 0))


def _default_root_cause_rules() -> list[dict[str, Any]]:
    now = _utcnow()
    return [
        {
            "rule_id": "RC_CONTEXT_OMITTED_HIGH_RISK",
            "reason_key": "evidence_incomplete_for_high_risk_action",
            "root_cause_primary": "context_degraded_heavy",
            "causal_chain_json": ["context_degraded_heavy", "required_evidence_omitted", "same_failure_no_progress"],
            "mitigation_action": "fetch_full_evidence_and_rebuild_context",
            "priority": 10,
            "priority_band": "safety",
            "match_expression_json": {
                "all_reasons": ["evidence_incomplete_for_high_risk_action"],
                "decision_context_degradation_level": "heavy",
                "required_evidence_complete_for_decision": False,
                "next_action_is_high_risk": True,
            },
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        {
            "rule_id": "RC_PERMISSION_REVOKED",
            "reason_key": "permission_revoked_before_execution",
            "root_cause_primary": "permission_revoked",
            "causal_chain_json": ["permission_changed", "execute_time_check_failed"],
            "mitigation_action": "request_permission_or_replan",
            "priority": 15,
            "priority_band": "safety",
            "match_expression_json": {"any_reasons": ["permission_revoked_before_execution"]},
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        {
            "rule_id": "RC_EVIDENCE_INCOMPLETE",
            "reason_key": "evidence_incomplete_for_high_risk_action",
            "root_cause_primary": "evidence_incomplete_for_high_risk_action",
            "causal_chain_json": ["evidence_incomplete", "unsafe_to_continue"],
            "mitigation_action": "fetch_required_evidence",
            "priority": 20,
            "priority_band": "evidence_context",
            "match_expression_json": {
                "all_reasons": ["evidence_incomplete_for_high_risk_action"],
                "required_evidence_complete_for_decision": False,
                "next_action_is_high_risk": True,
            },
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        {
            "rule_id": "RC_POLICY_LOOP",
            "reason_key": "policy_loop",
            "root_cause_primary": "policy_loop",
            "causal_chain_json": ["same_action", "policy_rejected", "repeated_attempt"],
            "mitigation_action": "change_plan_or_require_human",
            "priority": 18,
            "priority_band": "safety",
            "match_expression_json": {"any_reasons": ["policy_loop"]},
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        {
            "rule_id": "RC_MEMORY_CONTRADICTION",
            "reason_key": "memory_contradiction",
            "root_cause_primary": "memory_contradiction",
            "causal_chain_json": ["memory_used", "contradiction_detected", "repair_failed"],
            "mitigation_action": "demote_memory_and_replan",
            "priority": 30,
            "priority_band": "evidence_context",
            "match_expression_json": {
                "all_reasons": ["same_failure_no_progress"],
                "numeric_gt": {"memory_contradiction_delta": 0},
            },
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        {
            "rule_id": "RC_APPROVAL_PENDING",
            "reason_key": "approval_required_before_execution",
            "root_cause_primary": "approval_pending",
            "causal_chain_json": ["approval_required", "human_decision_pending"],
            "mitigation_action": "wait_for_approval",
            "priority": 40,
            "priority_band": "recovery",
            "match_expression_json": {"any_reasons": ["approval_required_before_execution", "pending_approval"]},
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        {
            "rule_id": "RC_BACKEND_CAPABILITY_DEGRADED",
            "reason_key": "backend_capability_degraded",
            "root_cause_primary": "backend_capability_degraded",
            "causal_chain_json": ["backend_capability_degraded", "reconcile_contract_limited"],
            "mitigation_action": "upgrade_backend_operation_contract_or_require_manual_reapproval",
            "priority": 45,
            "priority_band": "recovery",
            "match_expression_json": {"any_reasons": ["backend_capability_degraded", "backend_contract_unsupported"]},
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        {
            "rule_id": "RC_NO_PROGRESS_PURE",
            "reason_key": "same_failure_no_progress",
            "root_cause_primary": "same_failure_no_progress",
            "causal_chain_json": ["repair_attempt", "same_failure", "no_new_signal"],
            "mitigation_action": "stop_or_escalate_repair_strategy",
            "priority": 60,
            "priority_band": "repair_quality",
            "match_expression_json": {
                "any_reasons": ["same_failure_no_progress"],
                "none_reasons": [
                    "repair_regression",
                    "new_failures_outside_scope",
                    "policy_loop",
                    "evidence_incomplete_for_high_risk_action",
                    "backend_capability_degraded",
                    "backend_contract_unsupported",
                    "cost_budget_exceeded",
                    "context_budget_exhausted",
                    "max_iterations",
                ],
            },
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        {
            "rule_id": "RC_REPAIR_REGRESSION",
            "reason_key": "repair_regression",
            "root_cause_primary": "repair_regression",
            "causal_chain_json": ["patch_applied", "new_failure", "regression"],
            "mitigation_action": "rollback_patch_or_human_review",
            "priority": 65,
            "priority_band": "repair_quality",
            "match_expression_json": {"any_reasons": ["repair_regression", "new_failures_outside_scope"]},
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        {
            "rule_id": "RC_MAX_ITERATIONS",
            "reason_key": "max_iterations",
            "root_cause_primary": "max_iterations",
            "causal_chain_json": ["iteration_limit", "stop"],
            "mitigation_action": "human_review_or_extend_limit",
            "priority": 80,
            "priority_band": "resource_limit",
            "match_expression_json": {"any_reasons": ["max_iterations"]},
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        {
            "rule_id": "RC_RESOURCE_LIMIT",
            "reason_key": "resource_limit",
            "root_cause_primary": "resource_limit",
            "causal_chain_json": ["budget_exhausted", "cannot_continue"],
            "mitigation_action": "pause_or_request_budget",
            "priority": 85,
            "priority_band": "resource_limit",
            "match_expression_json": {"any_reasons": ["cost_budget_exceeded", "context_budget_exhausted"]},
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        {
            "rule_id": "RC_UNKNOWN",
            "reason_key": "accepted_unknown",
            "root_cause_primary": "unknown",
            "causal_chain_json": ["unknown"],
            "mitigation_action": "manual_diagnosis",
            "priority": 900,
            "priority_band": "fallback",
            "match_expression_json": {"any_reasons": ["accepted_unknown"]},
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        {
            "rule_id": "RC_RULE_MISSING",
            "reason_key": "rule_missing",
            "root_cause_primary": "root_cause_rule_missing",
            "causal_chain_json": ["unclassified_reason", "root_cause_rule_missing"],
            "mitigation_action": "add_explicit_root_cause_rule",
            "priority": 999,
            "priority_band": "fallback",
            "match_expression_json": {"always": True},
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
    ]


def _apply_budget(
    evidence_refs: list[EvidenceRef],
    estimated_tokens: int,
    token_budget: int,
) -> tuple[list[EvidenceRef], list[EvidenceRef], str]:
    if estimated_tokens <= token_budget:
        return evidence_refs, [], "none"
    ratio = estimated_tokens / max(token_budget, 1)
    if ratio < 1.5:
        degradation = "light"
        omit_count = max(1, len(evidence_refs) // 4)
    elif ratio < 2.5:
        degradation = "medium"
        omit_count = max(1, len(evidence_refs) // 2)
    else:
        degradation = "heavy"
        omit_count = max(1, len(evidence_refs) - 1)
    omitted = evidence_refs[-omit_count:] if evidence_refs else []
    kept = evidence_refs[:-omit_count] if omitted else evidence_refs
    return kept, omitted, degradation


def _decision_quality_risk(*, degradation: str, required_complete: bool) -> str:
    if not required_complete or degradation == "heavy":
        return "high"
    if degradation == "medium":
        return "medium"
    return "low"


def _estimate_tokens(payload: dict[str, Any]) -> int:
    return max(1, len(json.dumps(payload, ensure_ascii=False, sort_keys=True)) // 4)


def _matches_rule(match: dict[str, Any], *, reasons: list[str], observation: dict[str, Any]) -> bool:
    if match.get("always"):
        return True
    if any(reason not in reasons for reason in match.get("all_reasons", [])):
        return False
    any_reasons = match.get("any_reasons")
    if any_reasons and not any(reason in reasons for reason in any_reasons):
        return False
    if any(reason in reasons for reason in match.get("none_reasons", [])):
        return False
    for key in [
        "decision_context_degradation_level",
        "required_evidence_complete_for_decision",
        "next_action_is_high_risk",
    ]:
        if key in match and observation.get(key) != match[key]:
            return False
    for key, threshold in match.get("numeric_gt", {}).items():
        value = observation.get(key)
        if value is None:
            return False
        try:
            if float(value) <= float(threshold):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _primary_stop_reason(reasons: list[str]) -> str | None:
    for reason in [
        "evidence_incomplete_for_high_risk_action",
        "policy_loop",
        "repair_regression",
        "new_failures_outside_scope",
        "same_failure_no_progress",
        "permission_revoked_before_execution",
        "backend_capability_degraded",
        "backend_contract_unsupported",
        "max_iterations",
        "cost_budget_exceeded",
        "context_budget_exhausted",
        "accepted_unknown",
    ]:
        if reason in reasons:
            return reason
    return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
