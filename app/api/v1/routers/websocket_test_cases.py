from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
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
def list_cases(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cases = WebSocketTestCaseService(db).list_cases(project_id=project_id, current_user=current_user)
    return success(data=[WebSocketTestCaseRead.model_validate(item) for item in cases])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_case(project_id: int, payload: WebSocketTestCaseCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    case = WebSocketTestCaseService(db).create_case(project_id=project_id, payload=payload, current_user=current_user)
    return success(data=WebSocketTestCaseRead.model_validate(case))


@router.put("/{test_case_id}")
def update_case(project_id: int, test_case_id: int, payload: WebSocketTestCaseUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    case = WebSocketTestCaseService(db).update_case(project_id=project_id, test_case_id=test_case_id, payload=payload, current_user=current_user)
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
    return success(message="WebSocket 测试用例删除成功")


@router.post("/{test_case_id}/execute")
def execute_saved_case(project_id: int, test_case_id: int, environment_id: int | None = Query(default=None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    execution = WebSocketTestCaseService(db).execute_saved_case(project_id=project_id, test_case_id=test_case_id, environment_id=environment_id, current_user=current_user)
    return success(data=WebSocketTestCaseExecutionRead.model_validate(execution))


@router.post("/execute-unsaved")
def execute_unsaved_case(project_id: int, payload: UnsavedWebSocketTestCaseExecuteRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    execution = WebSocketTestCaseService(db).execute_unsaved_case(project_id=project_id, payload=payload, current_user=current_user)
    return success(data=WebSocketTestCaseExecutionRead.model_validate(execution))


@router.post("/batch-execute")
def batch_execute(project_id: int, payload: WebSocketBatchExecuteRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    executions = WebSocketTestCaseService(db).batch_execute(project_id=project_id, payload=payload, current_user=current_user)
    return success(data=[WebSocketTestCaseExecutionRead.model_validate(item) for item in executions])
