import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

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
        )


if __name__ == "__main__":
    unittest.main()
