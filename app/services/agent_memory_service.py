from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.sensitive_data import mask_sensitive, request_fingerprint
from app.models.agent import (
    AgentMemoryContradictionEvent,
    AgentMemoryEvidenceLink,
    AgentMemoryRetrievalProfile,
    AgentMemorySourceProfile,
    AgentMemoryUsageEvent,
    AgentRun,
    ProjectMemory,
)
from app.models.user import User
from app.services.agent_loop_service import EvidenceRef, EvidenceRefResolver
from app.services.permission_service import PermissionService


SEVERITY_MULTIPLIER = {
    "low": 0.75,
    "medium": 1.0,
    "high": 1.5,
    "critical": 2.0,
}


@dataclass(frozen=True)
class MemoryCandidate:
    memory_id: int
    memory_version: int
    title: str
    content: str
    source_type: str
    confidence: float
    stale_score: float
    retrieval_score: float
    retrieval_profile: str
    evidence_ref: dict[str, Any]
    allowed_usage: str


class MemorySourceProfileResolver:
    def __init__(self, db: Session):
        self.db = db

    def ensure_defaults(self) -> None:
        existing = {
            item.source_type
            for item in self.db.scalars(select(AgentMemorySourceProfile)).all()
        }
        for profile in _default_source_profiles():
            if profile["source_type"] in existing:
                continue
            self.db.add(AgentMemorySourceProfile(**profile))
        self.db.flush()

    def get(self, *, source_type: str) -> AgentMemorySourceProfile:
        self.ensure_defaults()
        profile = self.db.scalar(
            select(AgentMemorySourceProfile).where(
                AgentMemorySourceProfile.source_type == source_type,
                AgentMemorySourceProfile.status == "active",
            )
        )
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "memory_source_profile_missing"},
            )
        return profile


class MemoryRetrievalProfileResolver:
    def __init__(self, db: Session):
        self.db = db

    def ensure_defaults(self) -> None:
        existing = {
            item.profile_name
            for item in self.db.scalars(select(AgentMemoryRetrievalProfile)).all()
        }
        for profile in _default_retrieval_profiles():
            if profile["profile_name"] in existing:
                continue
            self.db.add(AgentMemoryRetrievalProfile(**profile))
        self.db.flush()

    def get(self, *, profile_name: str) -> AgentMemoryRetrievalProfile:
        self.ensure_defaults()
        profile = self.db.scalar(
            select(AgentMemoryRetrievalProfile).where(
                AgentMemoryRetrievalProfile.profile_name == profile_name,
                AgentMemoryRetrievalProfile.status == "active",
            )
        )
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "memory_retrieval_profile_missing"},
            )
        return profile


class MemoryEvidenceAdapter:
    def to_evidence_ref(self, *, memory: ProjectMemory, usage_role: str) -> dict[str, Any]:
        active_for_policy = usage_role == "policy_dependency"
        dependency_role = "policy_dependency" if active_for_policy else usage_role
        return EvidenceRef(
            evidence_ref_id=f"memory:{memory.id}:v{memory.memory_version}",
            ref_type="memory",
            ref_id=str(memory.id),
            version_id=str(memory.memory_version),
            content_hash=memory.content_hash,
            captured_at=(memory.last_validated_at or memory.updated_at or memory.created_at).isoformat(),
            mutability_class="mutable_current",
            freshness_policy="revalidate_before_side_effect",
            dependency_role=dependency_role,
            active_for_policy=active_for_policy,
            superseded_by_ref=None,
            required_for_high_risk=False,
            authority=f"memory:{memory.source_type}",
        ).to_json()


class MemoryManager:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)
        self.source_profiles = MemorySourceProfileResolver(db)
        self.retrieval_profiles = MemoryRetrievalProfileResolver(db)
        self.evidence_adapter = MemoryEvidenceAdapter()

    def create_memory(
        self,
        *,
        project_id: int,
        memory_type: str,
        title: str,
        content: str,
        source_type: str,
        source_ref_json: dict[str, Any] | None,
        evidence_refs: list[dict[str, Any]],
        current_user: User,
    ) -> ProjectMemory:
        self.permission_service.require_project_access(current_user, project_id)
        profile = self.source_profiles.get(source_type=source_type)
        if profile.requires_source_ref and not source_ref_json:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "memory_source_ref_required"},
            )
        content_hash = request_fingerprint({"content": content})
        now = _utcnow()
        expires_at = None
        if profile.default_ttl_days:
            expires_at = now + timedelta(days=profile.default_ttl_days)
        memory = ProjectMemory(
            project_id=project_id,
            memory_type=memory_type,
            title=title,
            content=content,
            content_hash=content_hash,
            memory_version=1,
            source_type=source_type,
            source_ref_json=mask_sensitive(source_ref_json) if source_ref_json else None,
            authority=profile.authority,
            confidence=profile.initial_confidence,
            initial_confidence=profile.initial_confidence,
            confidence_reason_json={
                "source_type": source_type,
                "profile": "source_profile",
                "initial_confidence": profile.initial_confidence,
            },
            stale_score=0.0,
            status="active" if source_type in {"user_confirmed", "document_imported"} else "needs_review",
            expires_at=expires_at,
            evidence_refs_json=[mask_sensitive(dict(item)) for item in evidence_refs],
            watched_refs_json=[
                {
                    "evidence_ref_id": ref.evidence_ref_id,
                    "ref_type": ref.ref_type,
                    "ref_id": ref.ref_id,
                }
                for ref in EvidenceRefResolver().parse(evidence_refs)
            ],
            created_by=current_user.id,
        )
        self.db.add(memory)
        self.db.flush()
        for ref in EvidenceRefResolver().parse(evidence_refs):
            self.db.add(
                AgentMemoryEvidenceLink(
                    memory_id=memory.id,
                    evidence_ref_type=ref.ref_type,
                    evidence_ref_id=ref.ref_id,
                    evidence_version_id=ref.version_id,
                    evidence_content_hash=ref.content_hash,
                    link_role="source_basis",
                )
            )
        self.db.commit()
        self.db.refresh(memory)
        return memory

    def update_memory(
        self,
        *,
        memory_id: int,
        current_user: User,
        memory_type: str | None = None,
        title: str | None = None,
        content: str | None = None,
        source_ref_json: dict[str, Any] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        status_value: str | None = None,
        reason: str | None = None,
    ) -> ProjectMemory:
        memory = self._get_memory_for_update(memory_id=memory_id, current_user=current_user)
        changed = False
        if memory_type is not None and memory.memory_type != memory_type:
            memory.memory_type = memory_type
            changed = True
        if title is not None and memory.title != title:
            memory.title = title
            changed = True
        if content is not None and memory.content != content:
            memory.content = content
            memory.content_hash = request_fingerprint({"content": content})
            changed = True
        if source_ref_json is not None:
            redacted = mask_sensitive(source_ref_json)
            if memory.source_ref_json != redacted:
                memory.source_ref_json = redacted
                changed = True
        if evidence_refs is not None:
            memory.evidence_refs_json = [mask_sensitive(dict(item)) for item in evidence_refs]
            self._replace_evidence_links(memory=memory, evidence_refs=evidence_refs)
            changed = True
        if status_value is not None:
            self._validate_memory_status_transition(memory=memory, status_value=status_value)
            if memory.status != status_value:
                memory.status = status_value
                changed = True
        if changed:
            memory.memory_version += 1
            memory.confidence_reason_json = {
                **(memory.confidence_reason_json or {}),
                "last_update_reason": reason,
                "updated_by": current_user.id,
                "updated_at": _utcnow().isoformat(),
            }
        self.db.commit()
        self.db.refresh(memory)
        return memory

    def validate_memory(
        self,
        *,
        memory_id: int,
        current_user: User,
        reason: str | None = None,
    ) -> ProjectMemory:
        memory = self._get_memory_for_update(memory_id=memory_id, current_user=current_user)
        now = _utcnow()
        memory.status = "active"
        memory.validation_count += 1
        memory.recent_validation_count += 1
        memory.last_validated_at = now
        memory.confidence = _clamp(memory.confidence + 0.1, memory.initial_confidence, 0.95)
        memory.stale_score = _clamp(memory.stale_score - 0.25, 0.0, 1.0)
        memory.memory_version += 1
        memory.confidence_reason_json = {
            **(memory.confidence_reason_json or {}),
            "last_validation_reason": reason,
            "validated_by": current_user.id,
            "validated_at": now.isoformat(),
        }
        self.db.commit()
        self.db.refresh(memory)
        return memory

    def reject_memory(
        self,
        *,
        memory_id: int,
        current_user: User,
        reason: str | None = None,
    ) -> ProjectMemory:
        memory = self._get_memory_for_update(memory_id=memory_id, current_user=current_user)
        memory.status = "rejected"
        memory.confidence = 0.0
        memory.stale_score = 1.0
        memory.memory_version += 1
        memory.confidence_reason_json = {
            **(memory.confidence_reason_json or {}),
            "rejected_by": current_user.id,
            "rejected_at": _utcnow().isoformat(),
            "rejection_reason": reason,
        }
        self.db.commit()
        self.db.refresh(memory)
        return memory

    def retrieve(
        self,
        *,
        project_id: int,
        query: str,
        profile_name: str,
        task_risk: str,
        usage_role: str,
        current_user: User,
        run_id: str | None = None,
        step_index: int | None = None,
        limit: int = 5,
    ) -> list[MemoryCandidate]:
        self.permission_service.require_project_access(current_user, project_id)
        profile = self.retrieval_profiles.get(profile_name=profile_name)
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id)) if run_id else None
        memories = list(
            self.db.scalars(
                select(ProjectMemory)
                .where(ProjectMemory.project_id == project_id)
                .order_by(ProjectMemory.updated_at.desc())
            ).all()
        )
        candidates: list[MemoryCandidate] = []
        for memory in memories:
            if not self._passes_hard_gate(memory=memory, profile=profile, task_risk=task_risk):
                continue
            semantic = _semantic_score(query=query, memory=memory)
            penalty = compute_contradiction_penalty(memory=memory, profile=profile)
            score = _retrieval_score(memory=memory, profile=profile, semantic_score=semantic, contradiction_penalty=penalty)
            evidence_ref = self.evidence_adapter.to_evidence_ref(memory=memory, usage_role=usage_role)
            candidates.append(
                MemoryCandidate(
                    memory_id=memory.id,
                    memory_version=memory.memory_version,
                    title=memory.title,
                    content=memory.content,
                    source_type=memory.source_type,
                    confidence=memory.confidence,
                    stale_score=memory.stale_score,
                    retrieval_score=score,
                    retrieval_profile=profile.profile_name,
                    evidence_ref=evidence_ref,
                    allowed_usage=usage_role,
                )
            )
        candidates.sort(key=lambda item: item.retrieval_score, reverse=True)
        selected = candidates[:limit]
        now = _utcnow()
        for candidate in selected:
            memory = self.db.get(ProjectMemory, candidate.memory_id)
            if memory is None:
                continue
            memory.last_used_at = now
            self.db.add(
                AgentMemoryUsageEvent(
                    memory_id=candidate.memory_id,
                    run_id=run_id,
                    iteration=run.current_iteration if run else None,
                    step_index=step_index,
                    retrieval_profile=profile.profile_name,
                    retrieval_score=candidate.retrieval_score,
                    usage_role=usage_role,
                    active_for_policy=usage_role == "policy_dependency",
                    evidence_ref_json=candidate.evidence_ref,
                )
            )
        self.db.commit()
        return selected

    def _get_memory_for_update(self, *, memory_id: int, current_user: User) -> ProjectMemory:
        memory = self.db.scalar(select(ProjectMemory).where(ProjectMemory.id == memory_id).with_for_update())
        if memory is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
        self.permission_service.require_project_access(current_user, memory.project_id)
        return memory

    def _replace_evidence_links(self, *, memory: ProjectMemory, evidence_refs: list[dict[str, Any]]) -> None:
        self.db.execute(delete(AgentMemoryEvidenceLink).where(AgentMemoryEvidenceLink.memory_id == memory.id))
        parsed_refs = EvidenceRefResolver().parse(evidence_refs)
        memory.watched_refs_json = [
            {
                "evidence_ref_id": ref.evidence_ref_id,
                "ref_type": ref.ref_type,
                "ref_id": ref.ref_id,
            }
            for ref in parsed_refs
        ]
        for ref in parsed_refs:
            self.db.add(
                AgentMemoryEvidenceLink(
                    memory_id=memory.id,
                    evidence_ref_type=ref.ref_type,
                    evidence_ref_id=ref.ref_id,
                    evidence_version_id=ref.version_id,
                    evidence_content_hash=ref.content_hash,
                    link_role="source_basis",
                )
            )

    def _validate_memory_status_transition(self, *, memory: ProjectMemory, status_value: str) -> None:
        allowed = {"active", "needs_review", "needs_revalidation", "suspect", "rejected", "archived"}
        if status_value not in allowed:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "invalid_memory_status"})
        if status_value == "active" and memory.source_type not in {"user_confirmed", "document_imported"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "memory_requires_explicit_validation"},
            )

    def _passes_hard_gate(
        self,
        *,
        memory: ProjectMemory,
        profile: AgentMemoryRetrievalProfile,
        task_risk: str,
    ) -> bool:
        if memory.status not in {"active", "needs_revalidation"}:
            return False
        if memory.expires_at and memory.expires_at < _utcnow():
            return False
        if memory.confidence < profile.min_confidence:
            return False
        if memory.stale_score > profile.max_stale_score:
            return False
        if task_risk == "high" and not profile.allow_memory_for_high_risk:
            return False
        if task_risk == "high" and memory.authority == "agent":
            return False
        return True

    def record_contradiction(
        self,
        *,
        memory_id: int,
        contradiction_type: str,
        severity: str,
        current_user: User,
        run_id: str | None = None,
        failure_fingerprint: str | None = None,
        evidence_ref_json: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> AgentMemoryContradictionEvent:
        memory = self.db.get(ProjectMemory, memory_id)
        if memory is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
        self.permission_service.require_project_access(current_user, memory.project_id)
        if severity not in SEVERITY_MULTIPLIER:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "invalid_memory_contradiction_severity"})
        now = _utcnow()
        event = AgentMemoryContradictionEvent(
            memory_id=memory.id,
            run_id=run_id,
            contradiction_type=contradiction_type,
            severity=severity,
            failure_fingerprint=failure_fingerprint,
            evidence_ref_json=evidence_ref_json,
            reason=reason,
            occurred_at=now,
        )
        self.db.add(event)
        memory.contradiction_count += 1
        memory.recent_contradiction_count += 1
        memory.last_contradicted_at = now
        memory.last_failure_fingerprint = failure_fingerprint
        memory.max_recent_severity = _max_severity(memory.max_recent_severity, severity)
        memory.confidence = _clamp(memory.confidence - 0.15, 0.0, 0.95)
        memory.stale_score = _clamp(memory.stale_score + 0.25, 0.0, 1.0)
        if severity == "critical":
            memory.status = "needs_revalidation"
        elif severity == "high":
            memory.status = "suspect"
        self.db.commit()
        self.db.refresh(event)
        return event


class MemoryStalenessWorker:
    def __init__(self, db: Session):
        self.db = db

    def mark_memories_stale_for_ref(
        self,
        *,
        evidence_ref_type: str,
        evidence_ref_id: str,
        stale_reason: str,
    ) -> int:
        links = list(
            self.db.scalars(
                select(AgentMemoryEvidenceLink).where(
                    AgentMemoryEvidenceLink.evidence_ref_type == evidence_ref_type,
                    AgentMemoryEvidenceLink.evidence_ref_id == evidence_ref_id,
                )
            ).all()
        )
        touched = 0
        for link in links:
            memory = self.db.get(ProjectMemory, link.memory_id)
            if memory is None or memory.status == "rejected":
                continue
            memory.stale_score = _clamp(memory.stale_score + _stale_delta(stale_reason), 0.0, 1.0)
            memory.stale_reason_json = {"reason": stale_reason, "evidence_ref_type": evidence_ref_type, "evidence_ref_id": evidence_ref_id}
            if stale_reason in {"manifest.changed", "environment.updated"} or memory.stale_score >= 0.8:
                memory.status = "needs_revalidation"
            touched += 1
        self.db.commit()
        return touched


class MemoryFeedbackWorker:
    POSITIVE_OUTCOMES = {"confirmed", "succeeded", "helped", "accepted", "useful", "validated"}
    NEUTRAL_OUTCOMES = {"unused", "no_effect", "ignored", "not_used", "neutral"}
    STALE_OUTCOMES = {"stale", "superseded", "outdated", "needs_revalidation"}
    CONTRADICTION_OUTCOMES = {"contradicted", "misleading", "caused_failure", "failed_due_to_memory", "incorrect"}

    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def record_usage_feedback(
        self,
        *,
        usage_event_id: int,
        outcome: str,
        current_user: User,
        caused_tool_input_change: bool | None = None,
        failure_fingerprint: str | None = None,
        contradiction_type: str | None = None,
        severity: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        usage = self.db.scalar(
            select(AgentMemoryUsageEvent).where(AgentMemoryUsageEvent.id == usage_event_id).with_for_update()
        )
        if usage is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory usage event not found")
        memory = self.db.get(ProjectMemory, usage.memory_id)
        if memory is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
        self.permission_service.require_project_access(current_user, memory.project_id)
        if usage.feedback_state == "processed":
            return {
                "attempted": 1,
                "processed": 0,
                "skipped": 1,
                "contradictions_recorded": 0,
                "results": [usage.feedback_result_json or {"usage_event_id": usage.id, "decision": "already_processed"}],
            }
        usage.outcome = outcome
        if caused_tool_input_change is not None:
            usage.caused_tool_input_change = caused_tool_input_change
        usage.feedback_state = "pending"
        usage.feedback_result_json = {
            "failure_fingerprint": failure_fingerprint,
            "contradiction_type": contradiction_type,
            "severity": severity,
            "reason": reason,
        }
        self.db.flush()
        return self.process_due(limit=1, usage_event_id=usage.id)

    def process_due(self, *, limit: int = 100, usage_event_id: int | None = None) -> dict[str, Any]:
        conditions = [
            AgentMemoryUsageEvent.outcome.is_not(None),
            AgentMemoryUsageEvent.feedback_state.in_(["pending", "retry"]),
        ]
        if usage_event_id is not None:
            conditions.append(AgentMemoryUsageEvent.id == usage_event_id)
        events = list(
            self.db.scalars(
                select(AgentMemoryUsageEvent)
                .where(*conditions)
                .order_by(AgentMemoryUsageEvent.created_at.asc(), AgentMemoryUsageEvent.id.asc())
                .limit(limit)
                .with_for_update()
            ).all()
        )
        results: list[dict[str, Any]] = []
        contradictions = 0
        for usage in events:
            result = self._process_usage_event(usage)
            results.append(result)
            if result["decision"] == "contradiction_recorded":
                contradictions += 1
        self.db.commit()
        return {
            "attempted": len(events),
            "processed": sum(1 for item in results if item.get("processed")),
            "skipped": sum(1 for item in results if not item.get("processed")),
            "contradictions_recorded": contradictions,
            "results": results,
        }

    def _process_usage_event(self, usage: AgentMemoryUsageEvent) -> dict[str, Any]:
        now = _utcnow()
        metadata = dict(usage.feedback_result_json or {})
        outcome = (usage.outcome or "").strip().lower()
        memory = self.db.scalar(select(ProjectMemory).where(ProjectMemory.id == usage.memory_id).with_for_update())
        if memory is None or memory.status == "rejected":
            result = {"usage_event_id": usage.id, "processed": False, "decision": "memory_missing_or_rejected"}
            self._mark_processed(usage, now=now, result=result)
            return result

        if outcome in self.POSITIVE_OUTCOMES:
            delta = 0.05 if usage.active_for_policy or usage.caused_tool_input_change else 0.03
            before_confidence = memory.confidence
            before_stale = memory.stale_score
            memory.confidence = _clamp(memory.confidence + delta, 0.0, 0.95)
            memory.stale_score = _clamp(memory.stale_score - 0.08, 0.0, 1.0)
            if memory.status == "needs_revalidation" and memory.stale_score <= 0.5 and memory.confidence >= memory.initial_confidence:
                memory.status = "active"
            memory.confidence_reason_json = {
                **(memory.confidence_reason_json or {}),
                "last_feedback_outcome": outcome,
                "last_feedback_at": now.isoformat(),
                "last_feedback_usage_event_id": usage.id,
            }
            result = {
                "usage_event_id": usage.id,
                "processed": True,
                "decision": "confidence_adjusted",
                "confidence_delta": round(memory.confidence - before_confidence, 6),
                "stale_delta": round(memory.stale_score - before_stale, 6),
                "memory_status": memory.status,
            }
            self._mark_processed(usage, now=now, result={**metadata, **result})
            return result

        if outcome in self.STALE_OUTCOMES:
            before_stale = memory.stale_score
            memory.stale_score = _clamp(memory.stale_score + (0.30 if usage.active_for_policy else 0.20), 0.0, 1.0)
            memory.stale_reason_json = {
                "reason": f"memory_feedback.{outcome}",
                "usage_event_id": usage.id,
                "run_id": usage.run_id,
            }
            if usage.active_for_policy or memory.stale_score >= 0.8:
                memory.status = "needs_revalidation"
            result = {
                "usage_event_id": usage.id,
                "processed": True,
                "decision": "marked_stale",
                "stale_delta": round(memory.stale_score - before_stale, 6),
                "memory_status": memory.status,
            }
            self._mark_processed(usage, now=now, result={**metadata, **result})
            return result

        if outcome in self.CONTRADICTION_OUTCOMES:
            severity = str(metadata.get("severity") or ("high" if usage.caused_tool_input_change else "medium"))
            if severity not in SEVERITY_MULTIPLIER:
                severity = "medium"
            contradiction_type = str(metadata.get("contradiction_type") or "memory_feedback")
            failure_fingerprint = metadata.get("failure_fingerprint")
            event = AgentMemoryContradictionEvent(
                memory_id=memory.id,
                run_id=usage.run_id,
                tool_call_id=usage.tool_call_id,
                contradiction_type=contradiction_type,
                severity=severity,
                failure_fingerprint=str(failure_fingerprint) if failure_fingerprint else None,
                evidence_ref_json=usage.evidence_ref_json,
                reason=metadata.get("reason") or f"memory usage outcome={outcome}",
                occurred_at=now,
            )
            self.db.add(event)
            before_confidence = memory.confidence
            memory.contradiction_count += 1
            memory.recent_contradiction_count += 1
            memory.last_contradicted_at = now
            memory.last_failure_fingerprint = event.failure_fingerprint
            memory.max_recent_severity = _max_severity(memory.max_recent_severity, severity)
            memory.confidence = _clamp(memory.confidence - _feedback_confidence_delta(severity), 0.0, 0.95)
            memory.stale_score = _clamp(memory.stale_score + 0.25, 0.0, 1.0)
            if severity == "critical" or usage.active_for_policy:
                memory.status = "needs_revalidation"
            elif severity == "high":
                memory.status = "suspect"
            result = {
                "usage_event_id": usage.id,
                "processed": True,
                "decision": "contradiction_recorded",
                "confidence_delta": round(memory.confidence - before_confidence, 6),
                "memory_status": memory.status,
                "contradiction_type": contradiction_type,
                "severity": severity,
            }
            self._mark_processed(usage, now=now, result={**metadata, **result})
            return result

        decision = "neutral_outcome" if outcome in self.NEUTRAL_OUTCOMES else "unknown_outcome_ignored"
        result = {"usage_event_id": usage.id, "processed": outcome in self.NEUTRAL_OUTCOMES, "decision": decision}
        self._mark_processed(usage, now=now, result={**metadata, **result})
        return result

    def _mark_processed(self, usage: AgentMemoryUsageEvent, *, now: datetime, result: dict[str, Any]) -> None:
        usage.feedback_state = "processed"
        usage.feedback_processed_at = now
        usage.feedback_result_json = result


def compute_contradiction_penalty(
    *,
    memory: ProjectMemory,
    profile: AgentMemoryRetrievalProfile,
    same_failure_repeated: bool | None = None,
) -> float:
    base = math.log1p(memory.contradiction_count) * 0.12
    recent = min(memory.recent_contradiction_count * 0.08, 0.24)
    same_failure = 0.15 if (same_failure_repeated or memory.last_failure_fingerprint) else 0.0
    severity = SEVERITY_MULTIPLIER.get(memory.max_recent_severity or "medium", 1.0)
    validation_offset = min(memory.recent_validation_count * 0.04, 0.16)
    raw = (base + recent + same_failure) * severity - validation_offset
    return _clamp(raw, 0.0, profile.max_contradiction_penalty)


def _default_source_profiles() -> list[dict[str, Any]]:
    return [
        {"source_type": "user_confirmed", "initial_confidence": 0.85, "authority": "user", "requires_source_ref": False, "allowed_for_high_risk": True},
        {"source_type": "execution_learned", "initial_confidence": 0.70, "authority": "system_record", "requires_source_ref": True, "allowed_for_high_risk": True},
        {"source_type": "document_imported", "initial_confidence": 0.75, "authority": "document", "requires_source_ref": True, "allowed_for_high_risk": True},
        {"source_type": "agent_summarized", "initial_confidence": 0.45, "authority": "agent", "requires_source_ref": False, "allowed_for_high_risk": False},
        {"source_type": "repair_inferred", "initial_confidence": 0.40, "authority": "agent", "requires_source_ref": False, "allowed_for_high_risk": False},
        {"source_type": "external_imported", "initial_confidence": 0.55, "authority": "external", "requires_source_ref": True, "allowed_for_high_risk": False},
    ]


def _default_retrieval_profiles() -> list[dict[str, Any]]:
    base = {
        "semantic_weight": 0.35,
        "confidence_weight": 0.25,
        "recency_weight": 0.05,
        "authority_weight": 0.10,
        "validation_weight": 0.10,
        "stale_weight": 0.20,
        "contradiction_weight": 0.25,
        "status": "active",
        "change_reason": "default agent memory governance profile",
    }
    return [
        {**base, "profile_name": "normal_plan_v1", "task_scope": "plan", "risk_level": "normal", "min_confidence": 0.45, "max_stale_score": 0.70, "allow_memory_for_high_risk": False, "max_contradiction_penalty": 0.60},
        {**base, "profile_name": "repair_v1", "task_scope": "repair", "risk_level": "normal", "min_confidence": 0.55, "max_stale_score": 0.60, "allow_memory_for_high_risk": False, "max_contradiction_penalty": 0.75},
        {**base, "profile_name": "high_risk_action_v1", "task_scope": "action", "risk_level": "high", "min_confidence": 0.75, "max_stale_score": 0.30, "allow_memory_for_high_risk": True, "max_contradiction_penalty": 1.00},
        {**base, "profile_name": "audit_explain_v1", "task_scope": "audit", "risk_level": "audit", "min_confidence": 0.20, "max_stale_score": 0.90, "allow_memory_for_high_risk": False, "max_contradiction_penalty": 0.40},
    ]


def _retrieval_score(
    *,
    memory: ProjectMemory,
    profile: AgentMemoryRetrievalProfile,
    semantic_score: float,
    contradiction_penalty: float,
) -> float:
    authority_score = 1.0 if memory.authority in {"user", "system_record", "document"} else 0.5
    validation_score = min(memory.validation_count * 0.1, 1.0)
    recency_score = 1.0
    return (
        semantic_score * profile.semantic_weight
        + memory.confidence * profile.confidence_weight
        + recency_score * profile.recency_weight
        + authority_score * profile.authority_weight
        + validation_score * profile.validation_weight
        - memory.stale_score * profile.stale_weight
        - contradiction_penalty * profile.contradiction_weight
    )


def _semantic_score(*, query: str, memory: ProjectMemory) -> float:
    query_tokens = {token.lower() for token in query.split() if token.strip()}
    if not query_tokens:
        return 0.5
    content = f"{memory.title} {memory.content}".lower()
    hits = sum(1 for token in query_tokens if token in content)
    return min(1.0, hits / len(query_tokens))


def _max_severity(current: str | None, new: str) -> str:
    order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    if current is None or order[new] > order.get(current, 0):
        return new
    return current


def _stale_delta(reason: str) -> float:
    if reason == "environment.updated":
        return 0.30
    if reason in {"document.updated", "manifest.changed"}:
        return 0.25
    return 0.20


def _feedback_confidence_delta(severity: str) -> float:
    if severity == "critical":
        return 0.25
    if severity == "high":
        return 0.18
    if severity == "low":
        return 0.06
    return 0.12


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
