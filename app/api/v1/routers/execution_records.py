from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.schemas.execution_record import ExecutionType
from app.services.execution_record_service import ExecutionRecordService

router = APIRouter()


@router.get("", summary="List unified execution records")
def list_execution_records(
    project_id: int,
    execution_type: ExecutionType | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    environment_id: int | None = None,
    trigger_user_id: int | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = ExecutionRecordService(db).list_records(
        project_id=project_id,
        current_user=current_user,
        execution_type=execution_type,
        status_filter=status_filter,
        environment_id=environment_id,
        trigger_user_id=trigger_user_id,
        started_from=started_from,
        started_to=started_to,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return success(data=result)


@router.get("/{execution_type}/{execution_id}", summary="Get unified execution detail")
def get_execution_record(
    project_id: int,
    execution_type: ExecutionType,
    execution_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = ExecutionRecordService(db).get_detail(
        project_id=project_id,
        execution_type=execution_type,
        execution_id=execution_id,
        current_user=current_user,
    )
    return success(data=result)
