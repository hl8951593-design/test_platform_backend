import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.api.v1.routers import defects
from app.core.permissions import ProjectPermission
from app.schemas.defect import DefectCreateRequest, DefectStatusUpdateRequest
from app.services.defect_service import DefectService


def _methods_by_path(router) -> dict[str, set[str]]:
    methods: dict[str, set[str]] = {}
    for route in router.routes:
        if hasattr(route, "methods"):
            methods.setdefault(route.path, set()).update(route.methods or ())
    return methods


class DefectRouteTests(unittest.TestCase):
    def test_defect_routes_are_registered(self):
        methods = _methods_by_path(defects.router)

        self.assertEqual({"GET", "POST"}, methods[""])
        self.assertIn("GET", methods["/{defect_id}"])
        self.assertIn("PUT", methods["/{defect_id}"])
        self.assertIn("DELETE", methods["/{defect_id}"])
        self.assertEqual({"PUT"}, methods["/{defect_id}/status"])


class DefectServiceTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=7)
        self.service = DefectService(MagicMock())
        self.service.permission_service.require_project_permission = MagicMock()
        self.service.repository = MagicMock()

    def test_create_defect_sanitizes_html_and_checks_permission(self):
        payload = DefectCreateRequest(
            title="支付状态未同步",
            assignee="qa_owner",
            bug_type="functional",
            urgency="critical",
            status="new",
            content_html=(
                '<p onclick="alert(1)">复现步骤'
                '<img src="javascript:alert(1)" onerror="alert(1)">'
                '<a href="https://example.com" target="_blank">详情</a>'
                "</p><script>alert(1)</script>"
            ),
        )
        self.service.repository.create.return_value = SimpleNamespace(id=1)

        self.service.create_defect(project_id=10, payload=payload, current_user=self.user)

        self.service.permission_service.require_project_permission.assert_called_once_with(
            self.user,
            10,
            ProjectPermission.CREATE_DEFECT.value,
        )
        content_html = self.service.repository.create.call_args.kwargs["content_html"]
        self.assertIn("<p>复现步骤", content_html)
        self.assertIn('href="https://example.com"', content_html)
        self.assertNotIn("onclick", content_html)
        self.assertNotIn("javascript:", content_html)
        self.assertNotIn("<script", content_html)

    def test_illegal_transition_returns_conflict(self):
        self.service.repository.get_by_id.return_value = SimpleNamespace(
            id=3,
            project_id=10,
            status="new",
        )

        with self.assertRaises(HTTPException) as context:
            self.service.transition_status(
                project_id=10,
                defect_id=3,
                payload=DefectStatusUpdateRequest(status="verified"),
                current_user=self.user,
            )

        self.assertEqual(context.exception.status_code, 409)
        self.service.repository.update_status.assert_not_called()
        self.service.permission_service.require_project_permission.assert_called_once_with(
            self.user,
            10,
            ProjectPermission.TRANSITION_DEFECT.value,
        )


if __name__ == "__main__":
    unittest.main()
