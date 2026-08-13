import unittest
import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core.sensitive_data import (
    decrypt_sensitive,
    encrypt_sensitive,
    mask_sensitive,
    protect_secret_text,
    redact_query_string,
    request_fingerprint,
    reveal_secret_text,
    verify_webhook_signature,
)
from app.schemas.retry import RetryPolicyConfig
from app.services.test_case_service import TestCaseService


class SensitiveDataTests(unittest.TestCase):
    def test_sensitive_fields_are_encrypted_and_masked(self):
        source = {
            "headers": {
                "Authorization": "Bearer secret",
                "lingxi-auth": "bearer external-secret",
                "Accept": "application/json",
            },
            "body": {"password": "secret", "name": "tester"},
        }
        encrypted = encrypt_sensitive(source)
        self.assertNotEqual(encrypted["headers"]["Authorization"], source["headers"]["Authorization"])
        self.assertEqual(decrypt_sensitive(encrypted), source)
        self.assertEqual(mask_sensitive(encrypted)["headers"]["Authorization"], "***")
        self.assertEqual(mask_sensitive(encrypted)["headers"]["lingxi-auth"], "***")

    def test_secret_text_round_trip(self):
        encrypted = protect_secret_text("secret-value")
        self.assertNotEqual(encrypted, "secret-value")
        self.assertEqual(reveal_secret_text(encrypted), "secret-value")

    def test_request_fingerprint_is_stable(self):
        self.assertEqual(request_fingerprint({"b": 2, "a": 1}), request_fingerprint({"a": 1, "b": 2}))

    def test_sensitive_query_values_are_masked_for_request_logs(self):
        result = redact_query_string(
            "project_id=1&token=download-secret&X-API-Key=api-secret&keyword=safe"
        )

        self.assertIn("project_id=1", result)
        self.assertIn("keyword=safe", result)
        self.assertNotIn("download-secret", result)
        self.assertNotIn("api-secret", result)
        self.assertIn("token=%2A%2A%2A", result)

    def test_webhook_signature_verification(self):
        timestamp = "1780977600"
        body = b'{"event":"deploy"}'
        signature = hmac.new(
            b"webhook-secret",
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        with patch("app.core.sensitive_data.settings.TEST_PLAN_WEBHOOK_SECRET", "webhook-secret"):
            self.assertTrue(verify_webhook_signature(
                timestamp=timestamp,
                body=body,
                signature=f"sha256={signature}",
            ))
            self.assertFalse(verify_webhook_signature(
                timestamp=timestamp,
                body=b"changed",
                signature=f"sha256={signature}",
            ))

    def test_http_execution_exposes_raw_response_only_to_runtime_sink(self):
        db = MagicMock()
        service = TestCaseService(db)
        payload = SimpleNamespace(
            environment_id=None,
            method="GET",
            assertions=[],
            extractors=[],
            retry_policy=RetryPolicyConfig(),
        )
        raw_response = {
            "status_code": 200,
            "headers": {},
            "body": '{"data":{"access_token":"real-secret"}}',
            "json": {"data": {"access_token": "real-secret"}},
        }
        captured = {}
        execution = SimpleNamespace(id=1)

        def create_execution(**values):
            captured.update(values)
            return execution

        runtime_response_sink = {}
        with (
            patch.object(service, "_load_environment_context", return_value=(None, {})),
            patch.object(
                service,
                "_build_request_snapshot",
                return_value={"method": "GET", "url": "https://api.example.com/login"},
            ),
            patch.object(service, "_send_request", return_value=raw_response),
            patch.object(service, "_create_execution_record", side_effect=create_execution),
            patch.object(service, "_stage_execution_diagnostic"),
        ):
            service._execute(
                project_id=1,
                test_case_id=None,
                payload=payload,
                current_user=SimpleNamespace(id=7),
                runtime_response_sink=runtime_response_sink,
            )

        self.assertEqual(
            runtime_response_sink["response_snapshot"]["json"]["data"]["access_token"],
            "real-secret",
        )
        self.assertEqual(
            captured["response_snapshot"]["json"]["data"]["access_token"],
            "***",
        )


if __name__ == "__main__":
    unittest.main()
