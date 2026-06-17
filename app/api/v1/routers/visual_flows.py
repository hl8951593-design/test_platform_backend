from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.schemas.visual_flow import FlowCreateRequest, FlowDefinition, FlowExecuteUnsavedRequest, FlowExecutionRead, FlowSummaryRead, FlowUpdateRequest
from app.services.visual_flow_service import VisualFlowService

router = APIRouter()


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
        status=execution.status, started_at=execution.started_at, finished_at=execution.finished_at,
        node_executions=node_executions,
    )


@router.post("/{flow_id}/execute")
def execute_saved_flow(
    project_id: int, flow_id: int, environment_id: int | None = Query(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    result = VisualFlowService(db).execute_saved(
        project_id=project_id, flow_id=flow_id, environment_id=environment_id,
        idempotency_key=idempotency_key, current_user=current_user,
    )
    return success(data=_execution_response(*result), message="Flow execution completed")


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
