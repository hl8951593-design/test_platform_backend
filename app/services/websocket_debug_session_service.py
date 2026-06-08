import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import websocket
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.models.user import User
from app.repositories.websocket_test_case_repository import WebSocketTestCaseRepository
from app.schemas.websocket_test_case import (
    WebSocketDebugSessionCreateRequest,
    WebSocketDebugSessionSendRequest,
    WebSocketTestCaseConfig,
)
from app.services.permission_service import PermissionService
from app.services.websocket_test_case_service import WebSocketTestCaseService


def _now() -> datetime:
    return datetime.now()


@dataclass
class DebugSession:
    session_id: str
    project_id: int
    user_id: int
    url: str
    connection: websocket.WebSocket
    negotiated_subprotocol: str | None
    idle_timeout_seconds: int
    created_at: datetime = field(default_factory=_now)
    last_active_at: datetime = field(default_factory=_now)
    status: str = "connected"
    error_message: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    next_sequence: int = 1
    lock: threading.RLock = field(default_factory=threading.RLock)

    def append_message(self, *, direction: str, message_type: str, data: Any, json_value: Any = None) -> None:
        with self.lock:
            self.messages.append({
                "sequence": self.next_sequence,
                "direction": direction,
                "type": message_type,
                "data": data,
                "json": json_value,
                "created_at": _now(),
            })
            self.next_sequence += 1
            if len(self.messages) > 5000:
                self.messages = self.messages[-5000:]
            self.last_active_at = _now()

    def read(self, after_sequence: int = 0) -> dict[str, Any]:
        with self.lock:
            self.last_active_at = _now()
            return {
                "session_id": self.session_id,
                "project_id": self.project_id,
                "status": self.status,
                "url": self.url,
                "negotiated_subprotocol": self.negotiated_subprotocol,
                "created_at": self.created_at,
                "last_active_at": self.last_active_at,
                "idle_timeout_seconds": self.idle_timeout_seconds,
                "error_message": self.error_message,
                "latest_sequence": self.next_sequence - 1,
                "messages": [item.copy() for item in self.messages if item["sequence"] > after_sequence],
            }


class WebSocketDebugSessionManager:
    def __init__(self):
        self._sessions: dict[str, DebugSession] = {}
        self._lock = threading.RLock()
        threading.Thread(target=self._cleanup_loop, daemon=True).start()

    def create(self, *, project_id: int, user_id: int, snapshot: dict[str, Any], idle_timeout_seconds: int) -> DebugSession:
        self.cleanup_expired()
        headers = [f"{key}: {value}" for key, value in snapshot["headers"].items()]
        connection = websocket.create_connection(
            snapshot["url"],
            header=headers,
            subprotocols=snapshot["subprotocols"] or None,
            timeout=snapshot["connect_timeout_ms"] / 1000,
        )
        connection.settimeout(1)
        session = DebugSession(
            session_id=uuid.uuid4().hex,
            project_id=project_id,
            user_id=user_id,
            url=snapshot["url"],
            connection=connection,
            negotiated_subprotocol=connection.subprotocol,
            idle_timeout_seconds=idle_timeout_seconds,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        threading.Thread(target=self._receive_loop, args=(session,), daemon=True).start()
        return session

    def get(self, *, session_id: str, project_id: int, user_id: int) -> DebugSession:
        self.cleanup_expired()
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None or session.project_id != project_id or session.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WebSocket 调试会话不存在")
        return session

    def send(self, *, session: DebugSession, message: WebSocketDebugSessionSendRequest) -> None:
        if session.status != "connected":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="WebSocket 调试会话未连接")
        raw = json.dumps(message.data, ensure_ascii=False) if message.type == "json" else str(message.data)
        try:
            with session.lock:
                session.connection.send(raw)
            session.append_message(direction="sent", message_type=message.type, data=message.data, json_value=message.data if message.type == "json" else None)
        except Exception as exc:  # noqa: BLE001
            self._mark_error(session, exc)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"WebSocket 消息发送失败: {exc}") from exc

    def ping(self, session: DebugSession) -> None:
        if session.status != "connected":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="WebSocket 调试会话未连接")
        try:
            with session.lock:
                session.connection.ping("devtest-heartbeat")
                session.last_active_at = _now()
        except Exception as exc:  # noqa: BLE001
            self._mark_error(session, exc)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"WebSocket 心跳发送失败: {exc}") from exc

    def clear_messages(self, session: DebugSession) -> None:
        with session.lock:
            session.messages.clear()
            session.last_active_at = _now()

    def close(self, session: DebugSession) -> None:
        with session.lock:
            if session.status == "connected":
                session.status = "disconnected"
            session.last_active_at = _now()
        try:
            session.connection.close()
        except Exception:  # noqa: BLE001
            pass

    def cleanup_expired(self) -> None:
        now = _now()
        with self._lock:
            expired = [
                session for session in self._sessions.values()
                if now - session.last_active_at > timedelta(seconds=session.idle_timeout_seconds)
            ]
        for session in expired:
            self.close(session)
            with self._lock:
                self._sessions.pop(session.session_id, None)

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            self.close(session)

    def _receive_loop(self, session: DebugSession) -> None:
        while session.status == "connected":
            try:
                raw = session.connection.recv()
                if raw == "":
                    self.close(session)
                    break
                if isinstance(raw, bytes):
                    session.append_message(direction="received", message_type="binary", data=raw.hex())
                else:
                    try:
                        json_value = json.loads(raw)
                    except json.JSONDecodeError:
                        json_value = None
                    session.append_message(direction="received", message_type="text", data=raw, json_value=json_value)
            except websocket.WebSocketTimeoutException:
                continue
            except websocket.WebSocketConnectionClosedException:
                self.close(session)
                break
            except Exception as exc:  # noqa: BLE001
                if session.status != "connected":
                    break
                self._mark_error(session, exc)
                break

    def _cleanup_loop(self) -> None:
        while True:
            time.sleep(30)
            self.cleanup_expired()

    def _mark_error(self, session: DebugSession, exc: Exception) -> None:
        with session.lock:
            session.status = "error"
            session.error_message = str(exc)
            session.last_active_at = _now()
        try:
            session.connection.close()
        except Exception:  # noqa: BLE001
            pass


debug_session_manager = WebSocketDebugSessionManager()


class WebSocketDebugSessionService:
    def __init__(self, db: Session):
        self.repository = WebSocketTestCaseRepository(db)
        self.permission_service = PermissionService(db)

    def create(self, *, project_id: int, payload: WebSocketDebugSessionCreateRequest, current_user: User) -> dict[str, Any]:
        self._require(current_user, project_id)
        execution_service = WebSocketTestCaseService.__new__(WebSocketTestCaseService)
        execution_service.repository = self.repository
        execution_service._environment_context_cache = {}
        environment, variables = execution_service._load_environment_context(project_id, payload.environment_id)
        config = WebSocketTestCaseConfig(
            environment_id=payload.environment_id,
            path=payload.path,
            headers=payload.headers,
            subprotocols=payload.subprotocols,
            receive_count=0,
            connect_timeout_ms=payload.connect_timeout_ms,
        )
        snapshot = execution_service._build_session_snapshot(config, environment.base_url if environment else None, variables)
        try:
            session = debug_session_manager.create(
                project_id=project_id,
                user_id=current_user.id,
                snapshot=snapshot,
                idle_timeout_seconds=payload.idle_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"WebSocket 调试连接失败: {exc}") from exc
        return session.read()

    def read(self, *, project_id: int, session_id: str, after_sequence: int, current_user: User) -> dict[str, Any]:
        self._require(current_user, project_id)
        return debug_session_manager.get(session_id=session_id, project_id=project_id, user_id=current_user.id).read(after_sequence)

    def send(self, *, project_id: int, session_id: str, payload: WebSocketDebugSessionSendRequest, current_user: User) -> dict[str, Any]:
        self._require(current_user, project_id)
        session = debug_session_manager.get(session_id=session_id, project_id=project_id, user_id=current_user.id)
        debug_session_manager.send(session=session, message=payload)
        return session.read()

    def close(self, *, project_id: int, session_id: str, current_user: User) -> dict[str, Any]:
        self._require(current_user, project_id)
        session = debug_session_manager.get(session_id=session_id, project_id=project_id, user_id=current_user.id)
        debug_session_manager.close(session)
        return session.read()

    def ping(self, *, project_id: int, session_id: str, current_user: User) -> dict[str, Any]:
        self._require(current_user, project_id)
        session = debug_session_manager.get(session_id=session_id, project_id=project_id, user_id=current_user.id)
        debug_session_manager.ping(session)
        return session.read()

    def clear_messages(self, *, project_id: int, session_id: str, current_user: User) -> dict[str, Any]:
        self._require(current_user, project_id)
        session = debug_session_manager.get(session_id=session_id, project_id=project_id, user_id=current_user.id)
        debug_session_manager.clear_messages(session)
        return session.read()

    def _require(self, current_user: User, project_id: int) -> None:
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.EXECUTE_TEST.value)
