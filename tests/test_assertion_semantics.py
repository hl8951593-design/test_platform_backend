import unittest
from unittest.mock import MagicMock

from app.runner.assertion_engine import json_values_equal
from app.services.test_case_service import TestCaseService
from app.services.websocket_test_case_service import WebSocketTestCaseService


class JsonEqualityTests(unittest.TestCase):
    def test_boolean_does_not_equal_number(self):
        self.assertFalse(json_values_equal(True, 1))
        self.assertFalse(json_values_equal(False, 0))

    def test_nested_boolean_does_not_equal_number(self):
        self.assertFalse(
            json_values_equal(
                {"items": [{"success": True}]},
                {"items": [{"success": 1}]},
            )
        )

    def test_matching_booleans_and_json_numbers_are_equal(self):
        self.assertTrue(json_values_equal(True, True))
        self.assertTrue(json_values_equal(1, 1.0))

    def test_http_json_assertion_rejects_true_for_expected_one(self):
        service = TestCaseService(MagicMock())

        results = service._run_assertions(
            [{"type": "json_equals", "path": "success", "expected": 1}],
            {"json": {"success": True}},
        )

        self.assertIs(results[0]["actual"], True)
        self.assertFalse(results[0]["passed"])

    def test_websocket_json_assertion_rejects_true_for_expected_one(self):
        service = WebSocketTestCaseService(MagicMock())

        results = service._run_assertions(
            [
                {
                    "type": "message_json_equals",
                    "message_index": 0,
                    "path": "success",
                    "expected": 1,
                }
            ],
            {
                "received_messages": [
                    {"data": '{"success": true}', "json": {"success": True}}
                ]
            },
        )

        self.assertIs(results[0]["actual"], True)
        self.assertFalse(results[0]["passed"])


if __name__ == "__main__":
    unittest.main()
