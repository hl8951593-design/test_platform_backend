from sqlalchemy.orm import Session

from app.core.response import normalize_response_data
from app.models.user import User
from app.schemas.execution_diagnostic import (
    ExecutionDiagnosticEnvelope,
    ExecutionDiagnosticQuery,
)
from app.schemas.execution_record import ExecutionType
from app.services.execution_diagnostic_projection import (
    ExecutionDiagnosticProjectionService,
)
from app.services.execution_record_service import ExecutionRecordService


class ExecutionDiagnosticService:
    """Permission-checked semantic views over authoritative execution details."""

    def __init__(self, db: Session):
        self.record_service = ExecutionRecordService(db)
        self.projector = ExecutionDiagnosticProjectionService()

    def read(
        self,
        *,
        project_id: int,
        execution_type: ExecutionType,
        execution_id: int,
        query: ExecutionDiagnosticQuery,
        current_user: User,
    ) -> ExecutionDiagnosticEnvelope:
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
