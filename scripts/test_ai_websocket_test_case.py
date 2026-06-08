import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.schemas.ai import AIWebSocketTestCaseExpandRequest, AIWebSocketTestCaseGenerateRequest
from app.services.ai_websocket_test_case_service import AIWebSocketTestCaseService


class FakeAIService:
    def __init__(self):
        self.requests = []

    def chat(self, payload):
        self.requests.append(payload)
        return SimpleNamespace(content=json.dumps({
            "source_summary": "chat websocket",
            "cases": [{
                "name": "join room",
                "method": "POST",
                "path": "wss://example.test/ws/room?client=web",
                "headers": {"Authorization": "Bearer {{token}}"},
                "subprotocols": ["json"],
                "messages": [{"type": "json", "data": {"event": "join"}}],
                "receive_count": 0,
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "message_count", "expected": 3},
                    {"type": "message_json_equals", "message_index": 1, "path": "event", "expected": "joined"},
                ],
                "extractors": [{"name": "connection_id", "message_index": 1, "path": "connection_id"}],
            }],
            "warnings": [],
        }, ensure_ascii=False))


def main() -> int:
    environment = SimpleNamespace(id=2, name="test", base_url="https://example.test", description=None)
    source = SimpleNamespace(
        id=7, name="source", description=None, environment_id=2, environment_ids=[2],
        path="/ws/room", headers={}, subprotocols=["json"], messages=[],
        receive_count=1, connect_timeout_ms=10000, receive_timeout_ms=10000,
        assertions=[], extractors=[],
    )
    service = object.__new__(AIWebSocketTestCaseService)
    service.permission_service = SimpleNamespace(require_project_permission=lambda *args: None)
    service.project_repository = SimpleNamespace(
        get_environment=lambda **kwargs: environment,
        list_environment_variables=lambda **kwargs: [SimpleNamespace(name="token", is_secret=True)],
    )
    service.test_case_repository = SimpleNamespace(get_by_id=lambda **kwargs: source)
    service.ai_service = FakeAIService()
    user = SimpleNamespace(id=1)

    generated = service.generate_test_cases(
        project_id=1, environment_id=2,
        payload=AIWebSocketTestCaseGenerateRequest(websocket_text="connect and join room"),
        current_user=user,
    )
    case = generated.cases[0]
    assert case.path == "/ws/room?client=web"
    assert case.receive_count == 3
    assert [item.type for item in case.assertions] == ["message_count", "message_json_equals"]
    assert not hasattr(case, "method")
    system_prompt = service.ai_service.requests[0].messages[0].content
    assert "WebSocket" in system_prompt and "禁止输出 method" in system_prompt

    expanded = service.expand_test_cases(
        project_id=1, test_case_id=7, environment_id=None,
        payload=AIWebSocketTestCaseExpandRequest(requirement="扩写握手和消息顺序异常"),
        current_user=user,
    )
    assert expanded.cases[0].environment_id == 2
    expand_prompt = service.ai_service.requests[1].messages[0].content
    assert "handshake_auth" in expand_prompt and "message_sequence" in expand_prompt
    print("AI WebSocket test case generation and expansion tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
