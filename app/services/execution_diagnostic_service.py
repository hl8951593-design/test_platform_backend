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
from app.services.execution_record_service import ExecutionRecordService
from app.services.execution_payload_store import DatabaseExecutionPayloadStore


class ExecutionDiagnosticService:
    """Permission-checked semantic views over authoritative execution details."""

    def __init__(self, db: Session):
        self.record_service = ExecutionRecordService(db)
        self.projector = ExecutionDiagnosticProjectionService()
        self.payload_store = DatabaseExecutionPayloadStore(db)

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
