import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.websocket_test_case_repository import WebSocketTestCaseRepository
from app.services.test_case_service import TestCaseService
from app.services.websocket_test_case_service import WebSocketTestCaseService


class FlowReferenceDetectionTests(unittest.TestCase):
    def test_http_case_reference_query_excludes_archived_flows(self):
        db = MagicMock()
        db.execute.return_value.all.return_value = []

        TestCaseRepository(db).referencing_flow_names(project_id=7, test_case_id=12)

        statement = db.execute.call_args.args[0]
        self.assertIn("archived", statement.compile().params.values())

    def test_websocket_case_reference_query_excludes_archived_flows(self):
        db = MagicMock()
        db.execute.return_value.all.return_value = []

        WebSocketTestCaseRepository(db).referencing_flow_names(
            project_id=7,
            test_case_id=12,
        )

        statement = db.execute.call_args.args[0]
        self.assertIn("archived", statement.compile().params.values())

    def test_http_case_supports_snake_and_camel_case_reference_ids(self):
        for key in ("reference_id", "referenceId"):
            definition = {"nodes": [{"kind": "api_case", key: 12}]}
            self.assertTrue(
                TestCaseRepository._definition_references_case(
                    definition, kind="api_case", test_case_id=12
                )
            )

    def test_case_kind_must_match(self):
        definition = {"nodes": [{"kind": "websocket_case", "reference_id": 12}]}
        self.assertFalse(
            TestCaseRepository._definition_references_case(
                definition, kind="api_case", test_case_id=12
            )
        )

    def test_invalid_definition_is_ignored(self):
        self.assertFalse(
            WebSocketTestCaseRepository._definition_references_case(
                None, kind="websocket_case", test_case_id=12
            )
        )


class DeleteCaseServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.user = SimpleNamespace(id=5)

    def test_http_case_is_deleted_when_unreferenced(self):
        service = TestCaseService(self.db)
        service.permission_service.require_project_permission = MagicMock()
        service.repository = MagicMock()
        case = SimpleNamespace(id=12, project_id=7)
        service.repository.get_by_id.return_value = case
        service.repository.referencing_flow_names.return_value = []

        service.delete_case(project_id=7, test_case_id=12, current_user=self.user)

        service.repository.delete.assert_called_once_with(case)

    def test_http_case_referenced_by_flow_returns_conflict(self):
        service = TestCaseService(self.db)
        service.permission_service.require_project_permission = MagicMock()
        service.repository = MagicMock()
        service.repository.get_by_id.return_value = SimpleNamespace(id=12, project_id=7)
        service.repository.referencing_flow_names.return_value = ["Checkout"]

        with self.assertRaises(HTTPException) as context:
            service.delete_case(project_id=7, test_case_id=12, current_user=self.user)

        self.assertEqual(context.exception.status_code, 409)
        service.repository.delete.assert_not_called()

    def test_websocket_case_is_deleted_when_unreferenced(self):
        service = WebSocketTestCaseService(self.db)
        service.permission_service.require_project_permission = MagicMock()
        service.repository = MagicMock()
        case = SimpleNamespace(id=18, project_id=7)
        service.repository.get_by_id.return_value = case
        service.repository.referencing_flow_names.return_value = []

        service.delete_case(project_id=7, test_case_id=18, current_user=self.user)

        service.repository.delete.assert_called_once_with(case)


if __name__ == "__main__":
    unittest.main()
