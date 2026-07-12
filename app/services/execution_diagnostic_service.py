import copy
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.response import normalize_response_data
from app.models.user import User
from app.schemas.execution_diagnostic import (
    ExecutionDiagnosticEnvelope,
    ExecutionDiagnosticQuery,
    DiagnosticPage,
)
from app.schemas.execution_record import ExecutionType
from app.services.execution_diagnostic_projection import (
    ExecutionDiagnosticProjectionService,
)
from app.services.execution_payload_store import DatabaseExecutionPayloadStore
from app.repositories.execution_diagnostic_repository import (
    ExecutionDiagnosticRepository,
)
from app.services.scenario_step_order import scenario_step_descriptors


class ScenarioStepResultAssembler:
    def __init__(self, db: Session):
        self.repository = ExecutionDiagnosticRepository(db)
        self.payload_store = DatabaseExecutionPayloadStore(db)

    def assemble_scenario_step_results(
        self,
        *,
        project_id: int,
        execution_id: int,
        scenario_snapshot: dict[str, Any],
        include_artifacts: bool,
        legacy_step_results: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.repository.list_all_steps(
            project_id=project_id,
            execution_type="scenario",
            execution_id=execution_id,
        )
        by_step_id = {
            str(item.get("step_id")): copy.deepcopy(item)
            for item in (legacy_step_results or [])
            if isinstance(item, dict) and item.get("step_id")
        }
        for row in rows:
            by_step_id[row.step_id] = self._hydrate_step_detail(
                row,
                include_artifacts=include_artifacts,
            )
        ordered = self._scenario_step_descriptors(scenario_snapshot)
        if not ordered:
            return [
                by_step_id[key]
                for key in sorted(
                    by_step_id,
                    key=lambda item: int(by_step_id[item].get("step_index") or 0),
                )
            ]
        return [
            by_step_id.get(
                descriptor["step_id"],
                self._pending_step_from_descriptor(descriptor),
            )
            for descriptor in ordered
        ]

    def _hydrate_step_detail(
        self, row: Any, *, include_artifacts: bool
    ) -> dict[str, Any]:
        detail = copy.deepcopy(row.detail_json or {})
        if not include_artifacts:
            return detail
        detail = self._hydrate_value(
            detail,
            project_id=row.project_id,
            execution_id=row.execution_id,
        )
        for field, artifact_ref, source_fields in (
            (
                "request_snapshot",
                row.request_artifact_ref,
                ("request_snapshot", "request", "session_snapshot", "session"),
            ),
            (
                "response_snapshot",
                row.response_artifact_ref,
                ("response_snapshot", "response"),
            ),
        ):
            if artifact_ref and not any(key in detail for key in source_fields):
                detail[field] = self._read_execution_artifact(
                    project_id=row.project_id,
                    execution_id=row.execution_id,
                    artifact_ref=artifact_ref,
                )
        return detail

    def _hydrate_value(
        self, value: Any, *, project_id: int, execution_id: int
    ) -> Any:
        if _is_externalized_placeholder(value):
            return self._read_execution_artifact(
                project_id=project_id,
                execution_id=execution_id,
                artifact_ref=str(value["artifact_ref"]),
            )
        if isinstance(value, dict):
            return {
                key: self._hydrate_value(
                    item,
                    project_id=project_id,
                    execution_id=execution_id,
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self._hydrate_value(
                    item,
                    project_id=project_id,
                    execution_id=execution_id,
                )
                for item in value
            ]
        return value

    def _read_execution_artifact(
        self, *, project_id: int, execution_id: int, artifact_ref: str
    ) -> Any:
        metadata = self.payload_store.get_metadata(
            project_id=project_id,
            artifact_ref=artifact_ref,
        )
        if (
            metadata.execution_type != "scenario"
            or metadata.execution_id != execution_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="scenario step artifact identity mismatch",
            )
        return self.payload_store.read_all(
            project_id=project_id,
            artifact_ref=artifact_ref,
        )

    @staticmethod
    def _scenario_step_descriptors(
        scenario_snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return scenario_step_descriptors(scenario_snapshot)

    @staticmethod
    def _pending_step_from_descriptor(
        descriptor: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **descriptor,
            "status": "pending",
            "extracted_variables": [],
            "resolved_bindings": [],
            "attempt_history": [],
        }


class ExecutionDiagnosticService:
    """Permission-checked semantic views over authoritative execution details."""

    def __init__(self, db: Session):
        from app.services.execution_record_service import ExecutionRecordService

        self.record_service = ExecutionRecordService(db)
        self.projector = ExecutionDiagnosticProjectionService()
        self.payload_store = DatabaseExecutionPayloadStore(db)
        self.scenario_assembler = ScenarioStepResultAssembler(db)

    def assemble_scenario_step_results(self, **kwargs) -> list[dict[str, Any]]:
        return self.scenario_assembler.assemble_scenario_step_results(**kwargs)

    def read(
        self,
        *,
        project_id: int,
        execution_type: ExecutionType,
        execution_id: int,
        query: ExecutionDiagnosticQuery,
        current_user: User,
    ) -> ExecutionDiagnosticEnvelope:
        if query.view == "artifact":
            return self._read_artifact(
                project_id=project_id,
                execution_type=execution_type,
                execution_id=execution_id,
                query=query,
                current_user=current_user,
            )
        detail = self.record_service.get_detail(
            project_id=project_id,
            execution_type=execution_type,
            execution_id=execution_id,
            current_user=current_user,
            include_artifacts=False,
        )
        return self.projector.project(
            execution_type=execution_type,
            execution=normalize_response_data(detail),
            query=query,
        )

    def _read_artifact(
        self,
        *,
        project_id: int,
        execution_type: ExecutionType,
        execution_id: int,
        query: ExecutionDiagnosticQuery,
        current_user: User,
    ) -> ExecutionDiagnosticEnvelope:
        self.record_service._require_view(current_user, project_id)
        artifact_ref = str(query.selector.artifact_ref)
        metadata = self.payload_store.get_metadata(
            project_id=project_id,
            artifact_ref=artifact_ref,
        )
        if (
            metadata.execution_type != execution_type
            or metadata.execution_id != execution_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="execution artifact not found",
            )
        chunk = self.payload_store.read_chunk(
            project_id=project_id,
            artifact_ref=artifact_ref,
            offset=query.selector.offset,
            max_bytes=query.selector.max_bytes,
        )
        return ExecutionDiagnosticEnvelope(
            resource_ref=f"{execution_type}:{execution_id}",
            view="artifact",
            data=chunk.model_dump(mode="json"),
            evidence_refs=[
                {
                    "artifact_ref": chunk.artifact_ref,
                    "sha256": chunk.sha256,
                    "raw_size_bytes": chunk.raw_size_bytes,
                }
            ],
            page=DiagnosticPage(
                next_cursor=str(chunk.next_offset) if chunk.has_more else None,
                has_more=chunk.has_more,
            ),
            diagnostic_complete=not chunk.has_more,
            recommended_next_views=["artifact"] if chunk.has_more else [],
        )


def _is_externalized_placeholder(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("externalized") is True
        and isinstance(value.get("artifact_ref"), str)
    )
