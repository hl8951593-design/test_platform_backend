from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.services.execution_center_service import ExecutionCenterService

router = APIRouter()


@router.get("/overview", summary="执行中心总览")
def get_execution_center_overview(
    project_id: int,
    environment_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = ExecutionCenterService(db).overview(
        project_id=project_id,
        environment_id=environment_id,
        current_user=current_user,
    )
    return success(data=result)


@router.get("/queue", summary="实时执行队列")
def list_execution_center_queue(
    project_id: int,
    environment_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = ExecutionCenterService(db).queue(
        project_id=project_id,
        environment_id=environment_id,
        page=page,
        page_size=page_size,
        current_user=current_user,
    )
    return success(data=result)


@router.get("/workers", summary="执行 Worker 状态")
def list_execution_center_workers(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = ExecutionCenterService(db).workers(project_id=project_id, current_user=current_user)
    return success(data=result)


@router.get("/logs", summary="执行中心实时日志")
def list_execution_center_logs(
    project_id: int,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = ExecutionCenterService(db).logs(
        project_id=project_id,
        after_sequence=after_sequence,
        limit=limit,
        current_user=current_user,
    )
    return success(data=result)


@router.get("/failure-diagnosis", summary="执行失败诊断")
def list_execution_center_failure_diagnosis(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = ExecutionCenterService(db).failure_diagnosis(
        project_id=project_id,
        current_user=current_user,
    )
    return success(data=result)


@router.get("/retries", summary="执行重试池")
def list_execution_center_retries(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = ExecutionCenterService(db).retries(project_id=project_id, current_user=current_user)
    return success(data=result)
