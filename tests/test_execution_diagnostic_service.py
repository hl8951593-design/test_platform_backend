import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException
from app.schemas.execution_diagnostic import ExecutionDiagnosticQuery
from app.services.execution_diagnostic_service import ExecutionDiagnosticService
from tests.test_execution_diagnostic_projection import run_220_shape


class ExecutionDiagnosticServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.user = SimpleNamespace(id=7, username="analyst")
        self.service = ExecutionDiagnosticService(self.db)
        self.service.record_service = MagicMock()
        self.service.record_service.get_detail.return_value = run_220_shape()

    def test_read_failure_view_returns_first_failure(self):
        result = self.service.read(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            query=ExecutionDiagnosticQuery(view="failures"),
            current_user=self.user,
        )

        self.assertEqual(result.data["first_failure"]["step_id"], "STEP-2")
        self.assertEqual(result.data["failure_category"], "authorization")
        self.assertNotIn("x" * 1000, result.model_dump_json())

    def test_read_delegates_project_isolation_to_authoritative_detail_service(self):
        self.service.read(
            project_id=17,
            execution_type="scenario",
            execution_id=220,
            query=ExecutionDiagnosticQuery(view="summary"),
            current_user=self.user,
        )

        self.service.record_service.get_detail.assert_called_once_with(
            project_id=17,
            execution_type="scenario",
            execution_id=220,
            current_user=self.user,
            include_artifacts=False,
        )

    def test_artifact_view_returns_bounded_chunk_without_loading_full_detail(self):
        self.service.payload_store = MagicMock()
        self.service.payload_store.get_metadata.return_value = SimpleNamespace(
            execution_type="scenario", execution_id=220
        )
        self.service.payload_store.read_chunk.return_value = SimpleNamespace(
            artifact_ref="execution-artifact://1/scenario/220/abc",
            offset=0,
            next_offset=8192,
            has_more=True,
            raw_size_bytes=100000,
            sha256="a" * 64,
            content="evidence",
            model_dump=lambda mode=None: {
                "artifact_ref": "execution-artifact://1/scenario/220/abc",
                "offset": 0,
                "next_offset": 8192,
                "has_more": True,
                "raw_size_bytes": 100000,
                "sha256": "a" * 64,
                "content": "evidence",
            },
        )

        result = self.service.read(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            query=ExecutionDiagnosticQuery.model_validate({
                "view": "artifact",
                "selector": {
                    "artifact_ref": "execution-artifact://1/scenario/220/abc",
                    "offset": 0,
                    "max_bytes": 8192,
                },
            }),
            current_user=self.user,
        )

        self.assertEqual(result.data["content"], "evidence")
        self.assertTrue(result.page.has_more)
        self.service.record_service.get_detail.assert_not_called()

    def test_artifact_view_rejects_ref_from_another_execution(self):
        self.service.payload_store = MagicMock()
        self.service.payload_store.get_metadata.return_value = SimpleNamespace(
            execution_type="scenario", execution_id=221
        )

        with self.assertRaises(HTTPException) as raised:
            self.service.read(
                project_id=1,
                execution_type="scenario",
                execution_id=220,
                query=ExecutionDiagnosticQuery.model_validate({
                    "view": "artifact",
                    "selector": {
                        "artifact_ref": "execution-artifact://1/scenario/221/abc"
                    },
                }),
                current_user=self.user,
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.service.record_service.get_detail.assert_not_called()


if __name__ == "__main__":
    unittest.main()
