import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

import uvicorn

from app.schemas.websocket_test_case import UnsavedWebSocketTestCaseExecuteRequest
from app.services.websocket_test_case_service import WebSocketTestCaseService
from scripts.websocket_mock_server import app as mock_app


class FakeRepository:
    def __init__(self, base_url: str):
        self.environment = SimpleNamespace(base_url=base_url)
        self.variables = {"token": "abc", "user_id": "42"}

    def get_environment(self, *, project_id, environment_id):
        return self.environment if (project_id, environment_id) == (1, 2) else None

    def get_environment_variables(self, *, environment_id):
        return self.variables

    def create_execution(self, **values):
        return SimpleNamespace(**values)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_mock_server() -> tuple[uvicorn.Server, threading.Thread, str]:
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(mock_app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("WebSocket mock server failed to start")
    return server, thread, f"http://127.0.0.1:{port}"


def _service(base_url: str) -> WebSocketTestCaseService:
    service = object.__new__(WebSocketTestCaseService)
    service.repository = FakeRepository(base_url)
    service.permission_service = SimpleNamespace(require_project_permission=lambda *args: None)
    service._environment_context_cache = {}
    return service


def main() -> int:
    server, thread, base_url = _start_mock_server()
    try:
        service = _service(base_url)
        session_result = service.execute_unsaved_case(
            project_id=1,
            current_user=SimpleNamespace(id=9),
            payload=UnsavedWebSocketTestCaseExecuteRequest(
                environment_id=2,
                path="/ws/session/{{user_id}}",
                headers={"Authorization": "Bearer {{token}}"},
                subprotocols=["json"],
                messages=[{"type": "json", "data": {"action": "join", "user_id": "{{user_id}}"}}],
                receive_count=2,
                assertions=[
                    {"type": "message_count", "expected": 2},
                    {"type": "message_json_equals", "message_index": 0, "path": "event", "expected": "welcome"},
                    {"type": "message_json_equals", "message_index": 0, "path": "authorization", "expected": "Bearer abc"},
                    {"type": "message_contains", "message_index": 1, "expected": "done"},
                ],
                extractors=[{"name": "received_user_id", "message_index": 0, "path": "user_id"}],
            ),
        )
        assert session_result.status == "passed", session_result
        assert session_result.response_snapshot["negotiated_subprotocol"] == "json"
        assert service.repository.variables["received_user_id"] == "42"

        echo_result = service.execute_unsaved_case(
            project_id=1,
            current_user=SimpleNamespace(id=9),
            payload=UnsavedWebSocketTestCaseExecuteRequest(
                path=f"ws://127.0.0.1:{base_url.rsplit(':', 1)[1]}/ws/echo",
                subprotocols=["text"],
                messages=[{"type": "text", "data": "hello mock"}],
                receive_count=1,
                assertions=[{"type": "message_contains", "message_index": 0, "expected": "hello mock"}],
            ),
        )
        assert echo_result.status == "passed", echo_result

        sequence_result = service.execute_unsaved_case(
            project_id=1,
            current_user=SimpleNamespace(id=9),
            payload=UnsavedWebSocketTestCaseExecuteRequest(
                path=f"ws://127.0.0.1:{base_url.rsplit(':', 1)[1]}/ws/sequence/3",
                receive_count=3,
                assertions=[
                    {"type": "message_count", "expected": 3},
                    {"type": "message_json_equals", "message_index": 2, "path": "index", "expected": 2},
                ],
            ),
        )
        assert sequence_result.status == "passed", sequence_result

        auth_success = service.execute_unsaved_case(
            project_id=1,
            current_user=SimpleNamespace(id=9),
            payload=UnsavedWebSocketTestCaseExecuteRequest(
                path=f"ws://127.0.0.1:{base_url.rsplit(':', 1)[1]}/ws/auth",
                headers={"Authorization": "Bearer mock-token"},
                receive_count=1,
                assertions=[{"type": "message_json_equals", "message_index": 0, "path": "authenticated", "expected": True}],
            ),
        )
        assert auth_success.status == "passed", auth_success

        auth_error = service.execute_unsaved_case(
            project_id=1,
            current_user=SimpleNamespace(id=9),
            payload=UnsavedWebSocketTestCaseExecuteRequest(
                path=f"ws://127.0.0.1:{base_url.rsplit(':', 1)[1]}/ws/auth",
                receive_count=1,
            ),
        )
        assert auth_error.status == "error", auth_error
        print(f"WebSocket mock integration tests passed: {base_url}")
        return 0
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
