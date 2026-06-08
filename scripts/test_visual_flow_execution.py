import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

import app.services.visual_flow_service as flow_module
from fastapi import HTTPException
from app.schemas.visual_flow import FlowDefinition
from app.schemas.visual_flow import FlowNode
from app.services.visual_flow_service import VisualFlowService

EXECUTION_CALLS = []
WEBSOCKET_EXECUTION_CALLS = []


class FakeRepository:
    def __init__(self):
        self.nodes = []
        self.cases = {
            1: SimpleNamespace(
                id=1, project_id=1, environment_id=None, method="POST", path="http://example.test/login",
                headers={}, query_params={}, body_type="json", body={}, assertions=[], extractors=[],
            ),
            2: SimpleNamespace(
                id=2, project_id=1, environment_id=None, method="GET", path="http://example.test/profile",
                headers={}, query_params={}, body_type="none", body=None, assertions=[], extractors=[],
            ),
        }
        self.websocket_cases = {
            3: SimpleNamespace(
                id=3, project_id=1, environment_id=None, path="ws://example.test/original",
                headers={}, subprotocols=[], messages=[], receive_count=1,
                connect_timeout_ms=10000, receive_timeout_ms=10000, assertions=[], extractors=[],
            )
        }
        self.execution = SimpleNamespace(
            id=1, flow_id=None, flow_version_id=None, project_id=1, environment_id=None,
            status="running", started_at=datetime.now(), finished_at=None,
        )

    def get_environment(self, **kwargs):
        return None

    def get_http_case(self, *, project_id, case_id):
        case = self.cases.get(case_id)
        return case if case and case.project_id == project_id else None

    def get_websocket_case(self, **kwargs):
        case = self.websocket_cases.get(kwargs["case_id"])
        return case if case and case.project_id == kwargs["project_id"] else None

    def create_execution(self, **kwargs):
        return self.execution

    def create_node_execution(self, **kwargs):
        item = SimpleNamespace(**kwargs)
        self.nodes.append(item)
        return item

    def finish_execution(self, *, execution, status):
        execution.status = status
        execution.finished_at = datetime.now()
        return execution


class FakeTestCaseService:
    def __init__(self, db):
        pass

    def _execute(self, *, test_case_id, payload, **kwargs):
        EXECUTION_CALLS.append({"test_case_id": test_case_id, "payload": payload})
        assert test_case_id is None
        if test_case_id == 1:
            response = {"status_code": 200, "headers": {}, "body": '{"token":"abc"}', "json": {"token": "abc"}}
        elif payload.path == "http://example.test/profile-in-flow":
            assert payload.headers["Authorization"] == "abc"
            assert payload.headers["X-Node-Only"] == "true"
            response = {"status_code": 200, "headers": {}, "body": '{"role":"admin"}', "json": {"role": "admin"}}
        else:
            response = {"status_code": 200, "headers": {}, "body": '{"token":"abc"}', "json": {"token": "abc"}}
        return SimpleNamespace(
            status="passed", request_snapshot={"headers": payload.headers}, response_snapshot=response,
            assertion_results=[], error_message=None, duration_ms=1, created_at=datetime.now(),
        )


class FakeWebSocketTestCaseService:
    def __init__(self, db):
        pass

    def _execute(self, project_id, test_case_id, payload, current_user):
        WEBSOCKET_EXECUTION_CALLS.append({"test_case_id": test_case_id, "payload": payload})
        assert test_case_id is None
        assert payload.path == "ws://example.test/in-flow"
        return SimpleNamespace(
            status="passed", session_snapshot={"url": payload.path}, response_snapshot={"received_messages": []},
            assertion_results=[], error_message=None, duration_ms=1, created_at=datetime.now(),
        )


def main() -> int:
    original = flow_module.TestCaseService
    original_websocket = flow_module.WebSocketTestCaseService
    flow_module.TestCaseService = FakeTestCaseService
    flow_module.WebSocketTestCaseService = FakeWebSocketTestCaseService
    try:
        service = object.__new__(VisualFlowService)
        service.db = None
        service.repository = FakeRepository()
        definition = FlowDefinition.model_validate(
            {
                "schemaVersion": "1.0", "projectId": 1,
                "nodes": [
                    {"id": "start", "kind": "start", "name": "Start", "position": {"x": 0, "y": 0}, "config": {}},
                    {"id": "login", "kind": "api_case", "name": "Login", "referenceId": 1, "position": {"x": 1, "y": 0}, "config": {"outputPaths": ["response.body.token"]}},
                    {"id": "profile", "kind": "api_case", "name": "Profile", "referenceId": 2, "position": {"x": 2, "y": 0}, "config": {"caseOverrides": {"path": "http://example.test/profile-in-flow", "headers": {"X-Node-Only": "true"}}, "outputPaths": ["response.body.role"], "inputBindings": [{"id": "token", "target": "headers.Authorization", "sourceNodeId": "login", "sourcePath": "response.body.token", "fallback": ""}]}},
                    {"id": "condition", "kind": "condition", "name": "Is admin", "position": {"x": 3, "y": 0}, "config": {"condition": 'outputs["profile"].response.body.role == "admin"'}},
                    {"id": "yes", "kind": "end", "name": "Yes", "position": {"x": 4, "y": 0}, "config": {}},
                    {"id": "no", "kind": "end", "name": "No", "position": {"x": 4, "y": 1}, "config": {}},
                ],
                "edges": [
                    {"id": "e1", "source": "start", "target": "login", "route": "success"},
                    {"id": "e2", "source": "login", "target": "profile", "route": "success"},
                    {"id": "e3", "source": "profile", "target": "condition", "route": "success"},
                    {"id": "e4", "source": "condition", "target": "yes", "route": "true"},
                    {"id": "e5", "source": "condition", "target": "no", "route": "false"},
                ],
                "viewport": {"zoom": 1},
            }
        )
        service._validate(definition, project_id=1, executable=True)
        result = service._execute(
            definition=definition, project_id=1, environment_id=None, flow_id=None,
            flow_version_id=None, idempotency_key=None, current_user=SimpleNamespace(id=1),
        )
        statuses = {item.node_id: item.status for item in service.repository.nodes}
        assert result.status == "passed"
        assert statuses["yes"] == "passed"
        assert statuses["no"] == "skipped"
        original_profile = service.repository.cases[2]
        assert original_profile.path == "http://example.test/profile"
        assert original_profile.headers == {}
        assert all(call["test_case_id"] is None for call in EXECUTION_CALLS)
        websocket_node = FlowNode.model_validate(
            {
                "id": "ws", "kind": "websocket_case", "name": "WS", "referenceId": 3,
                "position": {"x": 0, "y": 0}, "config": {"caseConfig": {"path": "ws://example.test/in-flow"}},
            }
        )
        service._execute_websocket_node(websocket_node, 1, None, {}, SimpleNamespace(id=1))
        assert service.repository.websocket_cases[3].path == "ws://example.test/original"
        assert WEBSOCKET_EXECUTION_CALLS[0]["test_case_id"] is None
        invalid_definition = definition.model_copy(deep=True)
        invalid_definition.nodes[1].config.case_overrides = {"id": 999}
        try:
            service._validate(invalid_definition, project_id=1, executable=True)
        except HTTPException as exc:
            assert exc.status_code == 422
            assert any(item["code"] == "invalid_case_override" for item in exc.detail["issues"])
        else:
            raise AssertionError("Unsupported node-local case field was accepted")
        print("Visual flow execution tests passed")
        return 0
    finally:
        flow_module.TestCaseService = original
        flow_module.WebSocketTestCaseService = original_websocket


if __name__ == "__main__":
    raise SystemExit(main())
