import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.v1.api import api_router
from app.api.v1.deps import get_current_user
from app.api.v1.routers import test_cases, test_plans
from app.core.config import settings
from app.core.execution_worker import ExecutionWorker
from app.core.sensitive_data import redact_sensitive_data
from app.core.outbound_http import validate_outbound_http_url
from app.db.base import Base
from app.models.project import Project, ProjectEnvironment
from app.models.scenario import TestScenario, TestScenarioVersion
from app.models.test_case import TestCaseExecution
from app.models.user import User
from app.repositories.execution_record_repository import ExecutionRecordRepository
from app.schemas.test_case import BatchExecuteRequest
from app.schemas.test_plan import TestPlanExecuteRequest
from app.services.test_case_service import TestCaseService
from app.services.scenario_service import ScenarioService
from app.services.project_service import ProjectService


class QueueAdmissionTests(unittest.TestCase):
    def test_saved_execution_routes_publish_202_contracts(self):
        expected_paths = {
            "/test-cases/{test_case_id}/execute",
            "/test-cases/batch-execute",
            "/websocket-test-cases/{test_case_id}/execute",
            "/websocket-test-cases/batch-execute",
            "/flows/{flow_id}/execute",
            "/scenarios/{scenario_id}/execute",
            "/test-plans/{plan_id}/execute",
        }
        status_by_path = {
            route.path: route.status_code
            for route in api_router.routes
            if "POST" in getattr(route, "methods", set())
        }
        self.assertEqual(
            {path: status_by_path.get(path) for path in expected_paths},
            {path: 202 for path in expected_paths},
        )

    @patch("app.api.v1.routers.test_plans.TestPlanService")
    @patch("app.api.v1.routers.test_plans.execution_worker.reserve", return_value=None)
    def test_plan_queue_full_is_rejected_before_run_creation(self, reserve, service_class):
        with self.assertRaises(HTTPException) as context:
            test_plans.execute_plan(
                project_id=1,
                plan_id=2,
                payload=TestPlanExecuteRequest(environment_id=3),
                db=MagicMock(),
                current_user=User(id=4, username="user", password_hash="hash"),
            )

        self.assertEqual(context.exception.status_code, 503)
        service_class.assert_not_called()

    @patch("app.api.v1.routers.test_cases.TestCaseService")
    @patch("app.api.v1.routers.test_cases.execution_worker.reserve", return_value=None)
    def test_queue_full_is_rejected_before_execution_record_is_created(self, reserve, service_class):
        with self.assertRaises(HTTPException) as context:
            test_cases.execute_saved_test_case(
                project_id=1,
                test_case_id=2,
                environment_id=None,
                db=MagicMock(),
                current_user=User(id=3, username="user", password_hash="hash"),
            )

        self.assertEqual(context.exception.status_code, 503)
        reserve.assert_called_once_with(1)
        service_class.assert_not_called()

    @patch("app.api.v1.routers.test_cases.TestCaseService")
    @patch("app.api.v1.routers.test_cases.execution_worker.reserve", return_value=None)
    def test_batch_reserves_the_whole_batch_before_writing(self, reserve, service_class):
        with self.assertRaises(HTTPException):
            test_cases.batch_execute_test_cases(
                project_id=1,
                payload=BatchExecuteRequest(test_case_ids=[1, 2, 3]),
                db=MagicMock(),
                current_user=User(id=3, username="user", password_hash="hash"),
            )

        reserve.assert_called_once_with(3)
        service_class.assert_not_called()

    def test_reservation_is_all_or_nothing_and_releases_unused_capacity(self):
        worker = ExecutionWorker(max_workers=1, queue_size=0)
        reservation = worker.reserve(1)
        self.assertIsNotNone(reservation)
        self.assertIsNone(worker.reserve(1))
        reservation.release_unused()
        second = worker.reserve(1)
        self.assertIsNotNone(second)
        second.release_unused()

    @patch("app.api.v1.routers.test_cases.TestCaseService")
    @patch("app.api.v1.routers.test_cases.execution_worker.reserve")
    def test_batch_validation_finishes_before_the_first_record_is_enqueued(self, reserve, service_class):
        reservation = MagicMock()
        reserve.return_value = reservation
        service = service_class.return_value
        service.validate_saved_case_batch.side_effect = HTTPException(status_code=404, detail="missing")

        with self.assertRaises(HTTPException):
            test_cases.batch_execute_test_cases(
                project_id=1,
                payload=BatchExecuteRequest(test_case_ids=[1, 999]),
                db=MagicMock(),
                current_user=User(id=3, username="user", password_hash="hash"),
            )

        service.enqueue_saved_case.assert_not_called()
        reservation.release_unused.assert_called_once()


class PayloadSafetyTests(unittest.TestCase):
    def test_capture_redaction_handles_headers_json_body_and_url_query(self):
        result = redact_sensitive_data({
            "source_url": "https://example.test/items?token=secret&page=1",
            "headers": {"Authorization": "Bearer secret"},
            "body": '{"password":"secret","name":"demo"}',
        })

        self.assertEqual(result["headers"]["Authorization"], "***")
        self.assertIn("token=%2A%2A%2A", result["source_url"])
        self.assertNotIn("secret", result["body"])

    def test_http_response_is_capped_and_redirects_are_not_followed(self):
        old_hosts = settings.EXECUTION_OUTBOUND_ALLOWED_HOSTS
        old_max = settings.EXECUTION_RESPONSE_MAX_BYTES
        settings.EXECUTION_OUTBOUND_ALLOWED_HOSTS = ["example.test"]
        settings.EXECUTION_RESPONSE_MAX_BYTES = 5
        response = MagicMock()
        response.iter_bytes.return_value = [b"abcdefgh"]
        response.encoding = "utf-8"
        response.status_code = 200
        response.headers.items.return_value = []
        context = MagicMock()
        context.__enter__.return_value = response
        try:
            with patch("app.services.test_case_service.httpx.stream", return_value=context) as stream:
                result = TestCaseService(MagicMock())._send_request({
                    "method": "GET",
                    "url": "https://example.test/data",
                    "headers": {},
                    "body_type": "none",
                    "body": None,
                })
        finally:
            settings.EXECUTION_OUTBOUND_ALLOWED_HOSTS = old_hosts
            settings.EXECUTION_RESPONSE_MAX_BYTES = old_max

        self.assertEqual(result["body"], "abcde")
        self.assertTrue(result["body_truncated"])
        self.assertFalse(stream.call_args.kwargs["follow_redirects"])

    def test_private_network_target_is_blocked_without_an_allowlist(self):
        old_hosts = settings.EXECUTION_OUTBOUND_ALLOWED_HOSTS
        old_private = settings.EXECUTION_OUTBOUND_ALLOW_PRIVATE_NETWORKS
        settings.EXECUTION_OUTBOUND_ALLOWED_HOSTS = []
        settings.EXECUTION_OUTBOUND_ALLOW_PRIVATE_NETWORKS = False
        try:
            with patch("app.core.outbound_http.socket.getaddrinfo", return_value=[
                (2, 1, 6, "", ("127.0.0.1", 80)),
            ]):
                with self.assertRaisesRegex(ValueError, "受保护网络地址"):
                    validate_outbound_http_url("http://internal.test/health")
        finally:
            settings.EXECUTION_OUTBOUND_ALLOWED_HOSTS = old_hosts
            settings.EXECUTION_OUTBOUND_ALLOW_PRIVATE_NETWORKS = old_private


class ProjectDeletionOrderingTests(unittest.TestCase):
    def test_database_deletion_precedes_best_effort_object_cleanup(self):
        events = []
        service = ProjectService.__new__(ProjectService)
        service.permission_service = MagicMock()
        service.permission_service.require_project_creator_or_admin.return_value = SimpleNamespace(id=7)
        service.media_repository = MagicMock()
        service.media_repository.list_by_project.return_value = [
            SimpleNamespace(bucket="media", object_key="project/7/image.png")
        ]
        service.project_repository = MagicMock()
        service.project_repository.delete_project.side_effect = lambda project: events.append("database")
        service.object_storage = MagicMock()

        def fail_cleanup(**kwargs):
            events.append("object")
            raise RuntimeError("storage unavailable")

        service.object_storage.delete.side_effect = fail_cleanup
        with patch("app.services.project_service.logger.exception") as log_exception:
            service.delete(7, SimpleNamespace(id=1))

        self.assertEqual(events, ["database", "object"])
        log_exception.assert_called_once()


class AuthenticationAndStatusTests(unittest.TestCase):
    @patch("app.api.v1.deps.decode_access_token", return_value={"sub": "1"})
    @patch("app.api.v1.deps.UserRepository.get_by_id")
    def test_inactive_user_cannot_reuse_an_existing_access_token(self, get_by_id, decode):
        get_by_id.return_value = User(id=1, username="disabled", password_hash="hash", is_active=False)
        with self.assertRaises(HTTPException) as context:
            get_current_user(token="token", db=MagicMock())
        self.assertEqual(context.exception.status_code, 401)

    @patch("app.api.v1.deps.decode_access_token", return_value={"sub": "not-an-id"})
    def test_malformed_subject_is_an_authentication_error(self, decode):
        with self.assertRaises(HTTPException) as context:
            get_current_user(token="token", db=MagicMock())
        self.assertEqual(context.exception.status_code, 401)

    def test_public_running_filter_includes_internal_queued_and_running_rows(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            user = User(
                username="owner",
                account="owner",
                password_hash="hash",
                phone="10000000000",
                email="owner@example.com",
            )
            db.add(user)
            db.flush()
            project = Project(name="Project", created_by_id=user.id)
            db.add(project)
            db.flush()
            db.add_all([
                TestCaseExecution(
                    project_id=project.id,
                    executed_by_id=user.id,
                    status="queued",
                    request_snapshot={},
                ),
                TestCaseExecution(
                    project_id=project.id,
                    executed_by_id=user.id,
                    status="running",
                    request_snapshot={},
                ),
            ])
            db.commit()

            rows, total = ExecutionRecordRepository(db).list_records(
                project_id=project.id,
                execution_type=None,
                status="running",
                environment_id=None,
                trigger_user_id=None,
                started_from=None,
                started_to=None,
                keyword=None,
                page=1,
                page_size=20,
            )
        finally:
            db.close()

        self.assertEqual(total, 2)
        self.assertEqual({row["status"] for row in rows}, {"queued", "running"})


class ScenarioAdmissionTests(unittest.TestCase):
    def test_enabled_dataset_without_enabled_records_is_skipped_not_passed(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            user = User(
                username="owner",
                account="owner",
                password_hash="hash",
                phone="10000000001",
                email="scenario@example.com",
            )
            db.add(user)
            db.flush()
            project = Project(name="Project", created_by_id=user.id)
            db.add(project)
            db.flush()
            environment = ProjectEnvironment(
                project_id=project.id,
                name="test",
                base_url="https://example.test",
                created_by_id=user.id,
            )
            db.add(environment)
            db.flush()
            scenario = TestScenario(
                project_id=project.id,
                environment_id=environment.id,
                name="No runnable record",
                tags=[],
                created_by_id=user.id,
                updated_by_id=user.id,
            )
            db.add(scenario)
            db.flush()
            version = TestScenarioVersion(
                scenario_id=scenario.id,
                version=1,
                definition={
                    "nodes": [],
                    "datasets": [{
                        "id": "DATA-1",
                        "name": "Disabled records",
                        "enabled": True,
                        "variables": {},
                        "records": [{"id": "R-1", "name": "disabled", "enabled": False}],
                    }],
                },
                created_by_id=user.id,
            )
            db.add(version)
            scenario.current_version = 1
            db.commit()

            result = ScenarioService(db).enqueue_scenario(
                project_id=project.id,
                scenario_id=scenario.id,
                environment_id=environment.id,
                dataset_ids=None,
                idempotency_key=None,
                current_user=user,
            )
        finally:
            db.close()

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["runs"], [])


if __name__ == "__main__":
    unittest.main()
