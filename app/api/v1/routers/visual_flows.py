from concurrent.futures import Future, TimeoutError as FutureTimeoutError

from fastapi import APIRouter, Depends, HTTPException, Header, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.async_response import public_execution_status
from app.core.config import settings
from app.core.execution_worker import execution_worker
from app.core.response import success
from app.models.user import User
from app.schemas.visual_flow import FlowCreateRequest, FlowDefinition, FlowExecuteUnsavedRequest, FlowExecutionRead, FlowSummaryRead, FlowUpdateRequest
from app.services.visual_flow_service import VisualFlowService

router = APIRouter()


def _submit_flow_execution(execution_id: int) -> Future[None]:
    future = execution_worker.submit_future(
        VisualFlowService.execute_queued_execution,
        execution_id,
    )
    if future is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="执行队列已满，请稍后重试",
        )
    return future


def _wait_for_flow_execution(db: Session, execution) -> None:
    future = _submit_flow_execution(execution.id)
    try:
        future.result(timeout=settings.EXECUTION_REQUEST_WAIT_TIMEOUT_SECONDS)
    except FutureTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Flow 执行超时，请稍后在执行中心查看结果",
        ) from exc
    db.refresh(execution)


@router.get("")
def list_flows(
    project_id: int,
    keyword: str | None = None,
    flow_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = VisualFlowService(db).list_flows(
        project_id=project_id,
        current_user=current_user,
        keyword=keyword,
        flow_status=flow_status,
        page=page,
        page_size=page_size,
    )
    result["items"] = [
        FlowSummaryRead.model_validate(item) for item in result["items"]
    ]
    return success(data=result)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_flow(project_id: int, payload: FlowCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = VisualFlowService(db).create_flow(project_id=project_id, payload=payload, current_user=current_user)
    return success(data=item, message="Flow created")


@router.get("/{flow_id}")
def get_flow(project_id: int, flow_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = VisualFlowService(db).get_flow(project_id=project_id, flow_id=flow_id, current_user=current_user)
    return success(data=item)


@router.put("/{flow_id}")
def update_flow(project_id: int, flow_id: int, payload: FlowUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = VisualFlowService(db).update_flow(project_id=project_id, flow_id=flow_id, payload=payload, current_user=current_user)
    return success(data=item, message="Flow updated")


@router.delete("/{flow_id}")
def delete_flow(
    project_id: int,
    flow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    VisualFlowService(db).delete_flow(
        project_id=project_id,
        flow_id=flow_id,
        current_user=current_user,
    )
    return success(message="Flow deleted")


def _execution_response(execution, flow_version, node_executions):
    return FlowExecutionRead(
        execution_id=execution.id, flow_id=execution.flow_id, flow_version=flow_version,
        project_id=execution.project_id, environment_id=execution.environment_id,
        status=public_execution_status(execution.status), started_at=execution.started_at, finished_at=execution.finished_at,
        node_executions=node_executions,
    )


@router.post(
    "/{flow_id}/execute",
    status_code=status.HTTP_200_OK,
    summary="异步执行已保存可视化流程",
)
def execute_saved_flow(
    project_id: int, flow_id: int, environment_id: int | None = Query(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    result = VisualFlowService(db).enqueue_saved(
        project_id=project_id, flow_id=flow_id, environment_id=environment_id,
        idempotency_key=idempotency_key, current_user=current_user,
    )
    _wait_for_flow_execution(db, result[0])
    node_executions = VisualFlowService(db).repository.list_node_executions(result[0].id)
    return success(
        data=_execution_response(result[0], result[1], node_executions),
        message="Flow execution completed",
    )


@router.post("/execute-unsaved")
def execute_unsaved_flow(
    project_id: int, payload: FlowExecuteUnsavedRequest | FlowDefinition, environment_id: int | None = Query(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    result = VisualFlowService(db).execute_unsaved(
        project_id=project_id,
        definition=payload.definition if isinstance(payload, FlowExecuteUnsavedRequest) else payload,
        environment_id=environment_id,
        idempotency_key=idempotency_key, current_user=current_user,
    )
    return success(data=_execution_response(*result), message="Unsaved flow execution completed")
