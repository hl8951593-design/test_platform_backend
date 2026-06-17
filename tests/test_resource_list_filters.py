import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.test_case_service import TestCaseService
from app.services.visual_flow_service import VisualFlowService
from app.services.websocket_test_case_service import WebSocketTestCaseService


class ResourceListFilterTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.user = SimpleNamespace(id=7)

    def test_http_case_list_returns_page_and_forwards_filters(self):
        service = TestCaseService(self.db)
        service.permission_service.require_project_permission = MagicMock()
        service.repository.list_by_project = MagicMock(
            return_value=([SimpleNamespace(id=1)], 23)
        )

        result = service.list_cases(
            project_id=10,
            current_user=self.user,
            keyword="login",
            environment_id=3,
            page=2,
            page_size=5,
        )

        self.assertEqual(result["total"], 23)
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["page_size"], 5)
        self.assertEqual([item.id for item in result["items"]], [1])
        service.repository.list_by_project.assert_called_once_with(
            project_id=10,
            keyword="login",
            environment_id=3,
            page=2,
            page_size=5,
        )

    def test_websocket_case_list_returns_page_and_forwards_filters(self):
        service = WebSocketTestCaseService(self.db)
        service.permission_service.require_project_permission = MagicMock()
        service.repository.list_by_project = MagicMock(
            return_value=([SimpleNamespace(id=2)], 8)
        )

        result = service.list_cases(
            project_id=10,
            current_user=self.user,
            keyword="chat",
            environment_id=4,
            page=1,
            page_size=20,
        )

        self.assertEqual(result["total"], 8)
        self.assertEqual([item.id for item in result["items"]], [2])
        service.repository.list_by_project.assert_called_once_with(
            project_id=10,
            keyword="chat",
            environment_id=4,
            page=1,
            page_size=20,
        )

    def test_flow_list_returns_status_node_count_and_page(self):
        service = VisualFlowService(self.db)
        service.permission_service.require_project_permission = MagicMock()
        flow = SimpleNamespace(
            id=5,
            name="Checkout",
            description="order flow",
            status="draft",
            current_version=3,
            updated_at=datetime(2026, 6, 15),
        )
        service.repository.list_by_project = MagicMock(return_value=([flow], 1))
        service.repository.get_version = MagicMock(
            return_value=SimpleNamespace(
                definition={"nodes": [{"id": "START"}, {"id": "END"}]}
            )
        )

        result = service.list_flows(
            project_id=10,
            current_user=self.user,
            keyword="checkout",
            flow_status="draft",
            page=1,
            page_size=20,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["status"], "draft")
        self.assertEqual(result["items"][0]["node_count"], 2)
        service.repository.list_by_project.assert_called_once_with(
            project_id=10,
            keyword="checkout",
            flow_status="draft",
            page=1,
            page_size=20,
        )


if __name__ == "__main__":
    unittest.main()
