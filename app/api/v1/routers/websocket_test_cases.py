from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.async_response import execution_started_payload
from app.core.execution_worker import ExecutionReservation, execution_worker
from app.core.read_response_cache import read_response_cache
from app.core.response import success
from app.models.user import User
from app.schemas.websocket_test_case import (
    UnsavedWebSocketTestCaseExecuteRequest,
    WebSocketBatchExecuteRequest,
    WebSocketDebugSessionCreateRequest,
    WebSocketDebugSessionRead,
    WebSocketDebugSessionSendRequest,
    WebSocketTestCaseCreateRequest,
    WebSocketTestCaseExecutionRead,
    WebSocketTestCaseRead,
    WebSocketTestCaseUpdateRequest,
)
from app.services.websocket_debug_session_service import WebSocketDebugSessionService
from app.services.websocket_test_case_service import WebSocketTestCaseService

router = APIRouter()


def _reserve_websocket_executions(count: int) -> ExecutionReservation:
    reservation = execution_worker.reserve(count)
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="执行队列已满，请稍后重试",
        )
    return reservation


def _submit_websocket_execution(execution_id: int, reservation: ExecutionReservation | None = None):
    future = (
        reservation.submit_future(WebSocketTestCaseService.execute_queued_execution, execution_id)
        if reservation is not None
        else execution_worker.submit_future(
            WebSocketTestCaseService.execute_queued_execution,
            execution_id,
        )
    )
    if future is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="执行队列已满，请稍后重试",
        )
    return future


def _invalidate_websocket_execution_caches(_future=None) -> None:
    read_response_cache.clear_prefix(("websocket_test_cases",))
    read_response_cache.clear_prefix(("projects",))


@router.post("/debug-sessions", status_code=status.HTTP_201_CREATED, summary="创建 WebSocket 长连接调试会话")
def create_debug_session(
    project_id: int,
    payload: WebSocketDebugSessionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = WebSocketDebugSessionService(db).create(project_id=project_id, payload=payload, current_user=current_user)
    return success(data=WebSocketDebugSessionRead.model_validate(session), message="WebSocket 调试连接已建立")


@router.get("/debug-sessions/{session_id}", summary="查询 WebSocket 调试会话和增量消息")
def read_debug_session(
    project_id: int,
    session_id: str,
    after_sequence: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = WebSocketDebugSessionService(db).read(
        project_id=project_id, session_id=session_id, after_sequence=after_sequence, current_user=current_user
    )
    return success(data=WebSocketDebugSessionRead.model_validate(session))


@router.post("/debug-sessions/{session_id}/messages", summary="通过 WebSocket 调试会话发送消息")
def send_debug_session_message(
    project_id: int,
    session_id: str,
    payload: WebSocketDebugSessionSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = WebSocketDebugSessionService(db).send(
        project_id=project_id, session_id=session_id, payload=payload, current_user=current_user
    )
    return success(data=WebSocketDebugSessionRead.model_validate(session), message="WebSocket 消息已发送")


@router.post("/debug-sessions/{session_id}/ping", summary="发送 WebSocket 调试会话心跳")
def ping_debug_session(
    project_id: int,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = WebSocketDebugSessionService(db).ping(project_id=project_id, session_id=session_id, current_user=current_user)
    return success(data=WebSocketDebugSessionRead.model_validate(session), message="WebSocket 心跳已发送")


@router.delete("/debug-sessions/{session_id}/messages", summary="清空 WebSocket 调试会话消息日志")
def clear_debug_session_messages(
    project_id: int,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = WebSocketDebugSessionService(db).clear_messages(
        project_id=project_id, session_id=session_id, current_user=current_user
    )
    return success(data=WebSocketDebugSessionRead.model_validate(session), message="WebSocket 调试消息日志已清空")


@router.delete("/debug-sessions/{session_id}", summary="主动断开 WebSocket 调试会话")
def close_debug_session(
    project_id: int,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = WebSocketDebugSessionService(db).close(project_id=project_id, session_id=session_id, current_user=current_user)
    return success(data=WebSocketDebugSessionRead.model_validate(session), message="WebSocket 调试连接已断开")


@router.get("")
def list_cases(
    project_id: int,
    keyword: str | None = None,
    environment_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = (
        "websocket_test_cases",
        id(db.get_bind()),
        current_user.id,
        bool(current_user.is_admin),
        project_id,
        keyword or "",
        environment_id,
        page,
        page_size,
    )

    def build_response():
        result = WebSocketTestCaseService(db).list_cases(
            project_id=project_id,
            current_user=current_user,
            keyword=keyword,
            environment_id=environment_id,
            page=page,
            page_size=page_size,
        )
        result["items"] = [
            WebSocketTestCaseRead.model_validate(item) for item in result["items"]
        ]
        return success(data=result)

    return read_response_cache.get_or_set(cache_key, build_response)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_case(project_id: int, payload: WebSocketTestCaseCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    case = WebSocketTestCaseService(db).create_case(project_id=project_id, payload=payload, current_user=current_user)
    read_response_cache.clear_prefix(("websocket_test_cases",))
    read_response_cache.clear_prefix(("projects",))
    read_response_cache.clear_prefix(("environment_configs",))
    return success(data=WebSocketTestCaseRead.model_validate(case))


@router.put("/{test_case_id}")
def update_case(project_id: int, test_case_id: int, payload: WebSocketTestCaseUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    case = WebSocketTestCaseService(db).update_case(project_id=project_id, test_case_id=test_case_id, payload=payload, current_user=current_user)
    read_response_cache.clear_prefix(("websocket_test_cases",))
    read_response_cache.clear_prefix(("projects",))
    read_response_cache.clear_prefix(("environment_configs",))
    return success(data=WebSocketTestCaseRead.model_validate(case))


@router.delete("/{test_case_id}", summary="删除 WebSocket 测试用例")
def delete_case(
    project_id: int,
    test_case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    WebSocketTestCaseService(db).delete_case(
        project_id=project_id,
        test_case_id=test_case_id,
        current_user=current_user,
    )
    read_response_cache.clear_prefix(("websocket_test_cases",))
    read_response_cache.clear_prefix(("projects",))
    read_response_cache.clear_prefix(("environment_configs",))
    return success(message="WebSocket 测试用例删除成功")


@router.post(
    "/{test_case_id}/execute",
    status_code=status.HTTP_202_ACCEPTED,
    summary="异步执行已保存 WebSocket 测试用例",
)
def execute_saved_case(project_id: int, test_case_id: int, environment_id: int | None = Query(default=None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    reservation = _reserve_websocket_executions(1)
    try:
        execution = WebSocketTestCaseService(db).enqueue_saved_case(project_id=project_id, test_case_id=test_case_id, environment_id=environment_id, current_user=current_user)
        future = _submit_websocket_execution(execution.id, reservation)
        future.add_done_callback(_invalidate_websocket_execution_caches)
    finally:
        reservation.release_unused()
    _invalidate_websocket_execution_caches()
    return success(
        data=execution_started_payload(
            WebSocketTestCaseExecutionRead.model_validate(execution),
            execution_type="websocket",
            execution_id=execution.id,
            project_id=project_id,
        ),
        message="WebSocket 测试用例执行已受理",
    )


@router.post("/execute-unsaved")
def execute_unsaved_case(project_id: int, payload: UnsavedWebSocketTestCaseExecuteRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    execution = WebSocketTestCaseService(db).execute_unsaved_case(project_id=project_id, payload=payload, current_user=current_user)
    read_response_cache.clear_prefix(("projects",))
    return success(data=WebSocketTestCaseExecutionRead.model_validate(execution))


@router.post("/batch-execute", status_code=status.HTTP_202_ACCEPTED)
def batch_execute(project_id: int, payload: WebSocketBatchExecuteRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    reservation = _reserve_websocket_executions(len(payload.websocket_test_case_ids))
    executions = []
    try:
        service = WebSocketTestCaseService(db)
        service.validate_saved_case_batch(
            project_id=project_id,
            test_case_ids=payload.websocket_test_case_ids,
            environment_id=payload.environment_id,
            current_user=current_user,
        )
        for test_case_id in payload.websocket_test_case_ids:
            execution = service.enqueue_saved_case(
                project_id=project_id,
                test_case_id=test_case_id,
                environment_id=payload.environment_id,
                current_user=current_user,
            )
            executions.append(execution)
            future = _submit_websocket_execution(execution.id, reservation)
            future.add_done_callback(_invalidate_websocket_execution_caches)
    finally:
        reservation.release_unused()
    _invalidate_websocket_execution_caches()
    return success(
        data=[
            execution_started_payload(
                WebSocketTestCaseExecutionRead.model_validate(item),
                execution_type="websocket",
                execution_id=item.id,
                project_id=project_id,
            )
            for item in executions
        ],
        message="批量 WebSocket 测试用例执行已受理",
    )
