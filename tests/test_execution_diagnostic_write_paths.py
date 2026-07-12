import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.visual_flow_repository import VisualFlowRepository
from app.repositories.websocket_test_case_repository import WebSocketTestCaseRepository
from app.schemas.test_case import TestCaseRequestConfig
from app.schemas.visual_flow import FlowDefinition
from app.schemas.websocket_test_case import WebSocketTestCaseConfig
from app.services.scenario_service import ScenarioService
from app.services.test_case_service import TestCaseService
from app.services.visual_flow_service import VisualFlowService
from app.services.websocket_test_case_service import WebSocketTestCaseService


def _run(**overrides):
    values = {
        "id": 220,
        "project_id": 1,
        "scenario_id": 45,
        "scenario_version_id": 3,
        "environment_id": 4,
        "dataset_id": None,
        "record_id": None,
        "status": "running",
        "trigger_type": "agent_dry_run",
        "triggered_by_id": 7,
        "started_at": datetime(2026, 7, 12, 10, 0, 0),
        "finished_at": None,
        "duration_ms": None,
        "step_results": [],
        "variables_snapshot": {},
        "last_event_sequence": 0,
        "current_step_id": None,
        "current_step_index": None,
        "execution_id": 99,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _failed_step():
    return {
        "step_id": "STEP-2",
        "step_index": 1,
        "name": "CT image count",
        "kind": "api_case",
        "status": "failed",
        "error_code": "ASSERTION_FAILED",
    }


class ExecutionDiagnosticWritePathTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.scalar.return_value = None
        self.service = ScenarioService(self.db)
        self.service.diagnostic_persistence = MagicMock()

    def test_scenario_step_projection_reuses_event_commit(self):
        run = _run()
        result = _failed_step()

        self.service._persist_step_result(run, [result], {}, {}, [], 1)

        self.service.diagnostic_persistence.stage_step.assert_called_once_with(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            step=result,
            fallback_index=0,
        )
        self.db.commit.assert_not_called()

        self.service._append_event(
            run,
            3,
            "step_failed",
            {"step_id": "STEP-2", "status": "failed"},
        )
        self.assertEqual(self.db.commit.call_count, 1)

    def test_diagnostic_execution_view_requires_no_database_query(self):
        run = _run(status="failed", duration_ms=4282)

        result = self.service._diagnostic_execution_view(run, [_failed_step()])

        self.assertEqual(result["summary"]["id"], "scenario:220")
        self.assertEqual(result["summary"]["status"], "failed")
        self.assertEqual(result["detail"]["step_results"][0]["step_id"], "STEP-2")
        self.db.scalar.assert_not_called()

    def test_queued_context_failure_stages_index_before_existing_commit(self):
        execution = SimpleNamespace(
            id=99,
            status="running",
            finished_at=None,
        )
        run = _run()
        self.db.scalars.return_value = SimpleNamespace(all=lambda: [run])
        self.db.get.return_value = SimpleNamespace(version=3)
        timeline = []
        self.service.diagnostic_persistence.stage_execution.side_effect = (
            lambda **_: timeline.append("diagnostic")
        )
        self.service._append_event = MagicMock(
            side_effect=lambda *_, **__: timeline.append("event")
        )
        self.db.commit.side_effect = lambda: timeline.append("commit")

        self.service._fail_queued_execution(execution, "missing environment")

        self.assertEqual(timeline, ["diagnostic", "event", "commit"])
        self.service.diagnostic_persistence.stage_execution.assert_called_once()

    def test_protocol_repositories_support_flush_without_commit(self):
        db = MagicMock()
        TestCaseRepository(db).create_execution(
            project_id=1,
            test_case_id=None,
            environment_id=None,
            scenario_run_id=None,
            executed_by_id=7,
            status="passed",
            request_snapshot={},
            response_snapshot={},
            assertion_results=[],
            attempt_history=[],
            error_message=None,
            duration_ms=1,
            commit=False,
        )
        WebSocketTestCaseRepository(db).create_execution(
            project_id=1,
            websocket_test_case_id=None,
            environment_id=None,
            scenario_run_id=None,
            executed_by_id=7,
            status="passed",
            session_snapshot={},
            response_snapshot={},
            assertion_results=[],
            attempt_history=[],
            error_message=None,
            duration_ms=1,
            commit=False,
        )
        VisualFlowRepository(db).create_execution(
            flow_id=None,
            flow_version_id=None,
            project_id=1,
            environment_id=None,
            user_id=7,
            idempotency_key=None,
            context_snapshot={},
            commit=False,
        )

        db.commit.assert_not_called()
        self.assertEqual(db.flush.call_count, 3)

    def test_http_terminal_projection_adds_no_commit(self):
        db = MagicMock()
        service = TestCaseService(db)
        service.diagnostic_persistence = MagicMock()
        service._load_environment_context = MagicMock(return_value=(None, {}))
        service._send_request = MagicMock(
            return_value={
                "status_code": 200,
                "headers": {},
                "body": '{"code":200}',
                "json": {"code": 200},
            }
        )

        def create_execution(*, commit=True, **values):
            execution = SimpleNamespace(id=31, created_at=datetime.utcnow(), **values)
            if commit:
                db.commit()
                db.refresh(execution)
            else:
                db.flush()
            return execution

        service.repository.create_execution = MagicMock(side_effect=create_execution)
        payload = TestCaseRequestConfig.model_validate(
            {
                "method": "GET",
                "path": "https://example.test/ping",
                "assertions": [],
                "extractors": [],
            }
        )

        execution = service._execute(
            project_id=1,
            test_case_id=None,
            payload=payload,
            current_user=SimpleNamespace(id=7),
        )

        self.assertEqual(execution.status, "passed")
        self.assertEqual(db.commit.call_count, 1)
        self.assertFalse(service.repository.create_execution.call_args.kwargs["commit"])
        service.diagnostic_persistence.stage_execution.assert_called_once()

    def test_websocket_terminal_projection_adds_no_commit(self):
        db = MagicMock()
        service = WebSocketTestCaseService(db)
        service.diagnostic_persistence = MagicMock()
        service._load_environment_context = MagicMock(return_value=(None, {}))
        service._run_session = MagicMock(
            return_value={"sent_messages": [], "received_messages": []}
        )

        def create_execution(*, commit=True, **values):
            execution = SimpleNamespace(id=32, created_at=datetime.utcnow(), **values)
            if commit:
                db.commit()
                db.refresh(execution)
            else:
                db.flush()
            return execution

        service.repository.create_execution = MagicMock(side_effect=create_execution)
        payload = WebSocketTestCaseConfig.model_validate(
            {"path": "wss://example.test/events", "assertions": [], "extractors": []}
        )

        execution = service._execute(1, None, payload, SimpleNamespace(id=7))

        self.assertEqual(execution.status, "passed")
        self.assertEqual(db.commit.call_count, 1)
        self.assertFalse(service.repository.create_execution.call_args.kwargs["commit"])
        service.diagnostic_persistence.stage_execution.assert_called_once()

    def test_flow_node_projection_reuses_every_existing_commit_boundary(self):
        db = MagicMock()
        service = VisualFlowService(db)
        service.diagnostic_persistence = MagicMock()
        service._validate = MagicMock()
        service._case_snapshots = MagicMock(return_value={})
        next_node_id = 0

        def create_execution(*, commit=True, **values):
            execution = SimpleNamespace(
                id=41,
                status=values.get("status", "running"),
                started_at=datetime.utcnow(),
                finished_at=None,
                trigger_type="manual",
                trigger_user_id=values["user_id"],
                created_at=datetime.utcnow(),
                **{key: value for key, value in values.items() if key not in {"status", "user_id"}},
            )
            (db.commit if commit else db.flush)()
            return execution

        def create_node_execution(*, commit=True, **values):
            nonlocal next_node_id
            next_node_id += 1
            node = SimpleNamespace(id=next_node_id, **values)
            (db.commit if commit else db.flush)()
            return node

        def finish_execution(*, execution, status, commit=True):
            execution.status = status
            execution.finished_at = datetime.utcnow()
            (db.commit if commit else db.flush)()
            return execution

        service.repository.create_execution = MagicMock(side_effect=create_execution)
        service.repository.create_node_execution = MagicMock(
            side_effect=create_node_execution
        )
        service.repository.finish_execution = MagicMock(side_effect=finish_execution)
        definition = FlowDefinition.model_validate(
            {
                "schemaVersion": "1.0",
                "nodes": [
                    {
                        "id": "start",
                        "kind": "start",
                        "name": "Start",
                        "position": {"x": 0, "y": 0},
                    },
                    {
                        "id": "end",
                        "kind": "end",
                        "name": "End",
                        "position": {"x": 200, "y": 0},
                    },
                ],
                "edges": [
                    {
                        "id": "edge-1",
                        "source": "start",
                        "target": "end",
                        "route": "success",
                    }
                ],
            }
        )

        execution = service._execute(
            definition=definition,
            project_id=1,
            environment_id=None,
            flow_id=None,
            flow_version_id=None,
            idempotency_key=None,
            current_user=SimpleNamespace(id=7),
        )

        self.assertEqual(execution.status, "passed")
        self.assertEqual(db.commit.call_count, 4)
        self.assertEqual(service.diagnostic_persistence.stage_step.call_count, 2)
        self.assertGreaterEqual(
            service.diagnostic_persistence.stage_execution.call_count, 2
        )
        self.assertTrue(
            all(
                call.kwargs["commit"] is False
                for call in service.repository.create_node_execution.call_args_list
            )
        )


if __name__ == "__main__":
    unittest.main()
