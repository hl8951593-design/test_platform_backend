import unittest
from unittest.mock import MagicMock

from app.core.variable_renderer import render_variables
from app.schemas.test_case import TestCaseRequestConfig
from app.services.test_case_service import TestCaseService
from app.services.websocket_test_case_service import WebSocketTestCaseService


class VariableRendererTests(unittest.TestCase):
    def test_hyphenated_variable_name_is_rendered(self):
        self.assertEqual(
            render_variables("{{Lingxi-Auth}}", {"Lingxi-Auth": "bearer token"}),
            "bearer token",
        )

    def test_embedded_and_nested_variables_are_rendered(self):
        source = {
            "headers": {"Authorization": "Bearer {{ access-token }}"},
            "body": [{"tenant": "{{租户.ID}}"}],
        }
        self.assertEqual(
            render_variables(
                source,
                {"access-token": "abc", "租户.ID": 42},
            ),
            {
                "headers": {"Authorization": "Bearer abc"},
                "body": [{"tenant": 42}],
            },
        )

    def test_unknown_variable_is_preserved(self):
        self.assertEqual(render_variables("{{missing}}", {}), "{{missing}}")

    def test_http_request_snapshot_renders_hyphenated_header_variable(self):
        service = TestCaseService(MagicMock())
        payload = TestCaseRequestConfig(
            environment_id=4,
            method="GET",
            path="/health",
            headers={"Lingxi-Auth": "{{Lingxi-Auth}}"},
            body_type="none",
        )

        snapshot = service._build_request_snapshot(
            payload=payload,
            base_url="https://example.com",
            variables={"Lingxi-Auth": "bearer token"},
        )

        self.assertEqual(snapshot["headers"]["Lingxi-Auth"], "bearer token")

    def test_websocket_renderer_supports_hyphenated_variable_name(self):
        service = WebSocketTestCaseService(MagicMock())
        self.assertEqual(
            service._render(
                {"Authorization": "Bearer {{access-token}}"},
                {"access-token": "abc"},
            ),
            {"Authorization": "Bearer abc"},
        )


if __name__ == "__main__":
    unittest.main()
