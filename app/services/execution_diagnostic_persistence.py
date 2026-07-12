from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.response import normalize_response_data
from app.schemas.execution_diagnostic import (
    CanonicalExecutionDiagnostic,
    CanonicalStepDiagnostic,
)
from app.schemas.execution_record import ExecutionType
from app.repositories.execution_diagnostic_repository import (
    ExecutionDiagnosticRepository,
)
from app.services.execution_diagnostic_projection import (
    ExecutionDiagnosticProjectionService,
)


PROJECTION_VERSION = "execution_diagnostic_projection_v1"


class ExecutionDiagnosticPersistence:
    """Stage diagnostic read models inside the caller-owned transaction."""

    def __init__(self, db: Session):
        self.repository = ExecutionDiagnosticRepository(db)
        self.projector = ExecutionDiagnosticProjectionService()

    def stage_execution(
        self,
        *,
        project_id: int,
        execution_type: ExecutionType,
        execution_id: int,
        execution: dict[str, Any],
    ) -> None:
        normalized = normalize_response_data(execution)
        canonical = self.projector.canonicalize(
            execution_type=execution_type,
            execution=normalized,
        )
        self.repository.upsert_execution_index(
            self._index_values(
                project_id=project_id,
                execution_id=execution_id,
                canonical=canonical,
                execution=normalized,
            )
        )
        for step in canonical.steps:
            self.repository.upsert_step(
                self._step_values(
                    project_id=project_id,
                    execution_id=execution_id,
                    canonical=canonical,
                    step=step,
                )
            )

    def stage_step(
        self,
        *,
        project_id: int,
        execution_type: ExecutionType,
        execution_id: int,
        step: dict[str, Any],
        fallback_index: int,
    ) -> None:
        canonical_step = self.projector.canonicalize_step(
            execution_type=execution_type,
            step=normalize_response_data(step),
            fallback_index=fallback_index,
        )
        self.repository.upsert_step(
            self._single_step_values(
                project_id=project_id,
                execution_type=execution_type,
                execution_id=execution_id,
                step=canonical_step,
            )
        )

    @staticmethod
    def _index_values(
        *,
        project_id: int,
        execution_id: int,
        canonical: CanonicalExecutionDiagnostic,
        execution: dict[str, Any],
    ) -> dict[str, Any]:
        summary = execution.get("summary")
        summary = summary if isinstance(summary, dict) else {}
        counts = canonical.counts
        started_at = _datetime_value(summary.get("started_at"))
        finished_at = _datetime_value(summary.get("finished_at"))
        source_updated_at = _datetime_value(
            summary.get("updated_at")
            or summary.get("finished_at")
            or summary.get("created_at")
        )
        return {
            "project_id": project_id,
            "execution_type": canonical.execution_type,
            "execution_id": execution_id,
            "object_ref": str(summary.get("object_ref") or canonical.resource_ref),
            "resource_id": _optional_int(summary.get("resource_id")),
            "resource_name": _bounded(summary.get("resource_name"), 255),
            "environment_id": _optional_int(summary.get("environment_id")),
            "status": _bounded(summary.get("status") or "unknown", 32),
            "trigger_type": _bounded(summary.get("trigger_type") or "unknown", 32),
            "trigger_user_id": _optional_int(summary.get("trigger_user_id")) or 0,
            "duration_ms": _optional_int(summary.get("duration_ms")),
            "total_steps": counts.get("total", 0),
            "passed_steps": counts.get("passed", 0),
            "failed_steps": counts.get("failed", 0),
            "timeout_steps": counts.get("timeout", 0),
            "skipped_steps": counts.get("skipped", 0),
            "first_failed_step_id": canonical.first_failure_step_id,
            "failure_category": canonical.failure_category,
            "failure_signature": canonical.failure_signature,
            "started_at": started_at,
            "finished_at": finished_at,
            "source_updated_at": source_updated_at,
            "projection_version": PROJECTION_VERSION,
        }

    @classmethod
    def _step_values(
        cls,
        *,
        project_id: int,
        execution_id: int,
        canonical: CanonicalExecutionDiagnostic,
        step: CanonicalStepDiagnostic,
    ) -> dict[str, Any]:
        return cls._single_step_values(
            project_id=project_id,
            execution_type=canonical.execution_type,
            execution_id=execution_id,
            step=step,
        )

    @staticmethod
    def _single_step_values(
        *,
        project_id: int,
        execution_type: ExecutionType,
        execution_id: int,
        step: CanonicalStepDiagnostic,
    ) -> dict[str, Any]:
        return {
            "project_id": project_id,
            "execution_type": execution_type,
            "execution_id": execution_id,
            "step_id": step.step_id,
            "step_index": step.step_index,
            "node_id": step.node_id,
            "node_phase": step.node_phase,
            "name": _bounded(step.name, 255) or step.step_id,
            "kind": _bounded(step.kind, 32) or str(execution_type),
            "status": _bounded(step.status, 32) or "unknown",
            "duration_ms": step.duration_ms,
            "error_code": _bounded(step.error_code, 128),
            "error_message": _bounded(step.error_message, 512),
            "assertion_summary_json": step.assertions,
            "response_summary_json": step.response,
            "binding_summary_json": step.bindings,
            "extraction_summary_json": step.extractors,
            "retry_summary_json": step.retries,
            "detail_json": step.normalized_detail,
            "request_artifact_ref": None,
            "response_artifact_ref": None,
            "detail_artifact_ref": None,
            "projection_version": PROJECTION_VERSION,
        }


def _bounded(value: Any, max_chars: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= max_chars else text[:max_chars]


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    for parser in (
        datetime.fromisoformat,
        lambda item: datetime.strptime(item, "%Y-%m-%d %H:%M:%S"),
    ):
        try:
            parsed = parser(normalized)
            if parsed.tzinfo:
                parsed = parsed.astimezone(UTC).replace(tzinfo=None)
            return parsed
        except ValueError:
            continue
    return None
