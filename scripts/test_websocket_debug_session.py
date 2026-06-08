import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

import uvicorn

from app.schemas.websocket_test_case import WebSocketDebugSessionCreateRequest, WebSocketDebugSessionSendRequest
from app.services.websocket_debug_session_service import WebSocketDebugSessionService
from scripts.websocket_mock_server import app as mock_app


class FakeRepository:
    def __init__(self, base_url: str):
        self.environment = SimpleNamespace(base_url=base_url)

    def get_environment(self, *, project_id, environment_id):
        return self.environment if (project_id, environment_id) == (1, 2) else None

    def get_environment_variables(self, *, environment_id):
        return {"token": "mock-token"}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_mock_server():
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(mock_app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("mock server failed to start")
    return server, thread, f"http://127.0.0.1:{port}"


def _wait_messages(service, session_id, user, expected):
    deadline = time.time() + 5
    while time.time() < deadline:
        result = service.read(project_id=1, session_id=session_id, after_sequence=0, current_user=user)
        received = [item for item in result["messages"] if item["direction"] == "received"]
        if len(received) >= expected:
            return result
        time.sleep(0.05)
    raise AssertionError(f"did not receive {expected} messages")


def main() -> int:
    server, thread, base_url = _start_mock_server()
    try:
        service = object.__new__(WebSocketDebugSessionService)
        service.repository = FakeRepository(base_url)
        service.permission_service = SimpleNamespace(require_project_permission=lambda *args: None)
        user = SimpleNamespace(id=9)
        created = service.create(
            project_id=1,
            current_user=user,
            payload=WebSocketDebugSessionCreateRequest(
                environment_id=2,
                path="/ws/echo",
                subprotocols=["debug"],
                idle_timeout_seconds=60,
            ),
        )
        session_id = created["session_id"]
        assert created["status"] == "connected"
        assert created["negotiated_subprotocol"] == "debug"

        service.send(
            project_id=1, session_id=session_id, current_user=user,
            payload=WebSocketDebugSessionSendRequest(type="text", data="first"),
        )
        first = _wait_messages(service, session_id, user, 1)
        assert first["status"] == "connected"
        assert first["messages"][-1]["data"] == "first"

        last_sequence = first["messages"][-1]["sequence"]
        service.send(
            project_id=1, session_id=session_id, current_user=user,
            payload=WebSocketDebugSessionSendRequest(type="json", data={"event": "second"}),
        )
        second = _wait_messages(service, session_id, user, 2)
        assert second["status"] == "connected"
        incremental = service.read(project_id=1, session_id=session_id, after_sequence=last_sequence, current_user=user)
        assert incremental["messages"]
        assert incremental["messages"][-1]["json"] == {"event": "second"}

        sequence_before_clear = second["latest_sequence"]
        cleared = service.clear_messages(project_id=1, session_id=session_id, current_user=user)
        assert cleared["status"] == "connected"
        assert cleared["latest_sequence"] == sequence_before_clear
        assert cleared["messages"] == []

        service.send(
            project_id=1, session_id=session_id, current_user=user,
            payload=WebSocketDebugSessionSendRequest(type="text", data="after-clear"),
        )
        after_clear = _wait_messages(service, session_id, user, 1)
        assert all(item["sequence"] > sequence_before_clear for item in after_clear["messages"])
        assert after_clear["messages"][-1]["data"] == "after-clear"

        heartbeat = service.ping(project_id=1, session_id=session_id, current_user=user)
        assert heartbeat["status"] == "connected"

        closed = service.close(project_id=1, session_id=session_id, current_user=user)
        assert closed["status"] == "disconnected"
        print("WebSocket long-lived debug session tests passed.")
        return 0
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
