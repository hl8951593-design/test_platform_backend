import unittest
import hashlib
import hmac
from unittest.mock import patch

from app.core.sensitive_data import (
    decrypt_sensitive,
    encrypt_sensitive,
    mask_sensitive,
    protect_secret_text,
    request_fingerprint,
    reveal_secret_text,
    verify_webhook_signature,
)


class SensitiveDataTests(unittest.TestCase):
    def test_sensitive_fields_are_encrypted_and_masked(self):
        source = {
            "headers": {"Authorization": "Bearer secret", "Accept": "application/json"},
            "body": {"password": "secret", "name": "tester"},
        }
        encrypted = encrypt_sensitive(source)
        self.assertNotEqual(encrypted["headers"]["Authorization"], source["headers"]["Authorization"])
        self.assertEqual(decrypt_sensitive(encrypted), source)
        self.assertEqual(mask_sensitive(encrypted)["headers"]["Authorization"], "***")

    def test_secret_text_round_trip(self):
        encrypted = protect_secret_text("secret-value")
        self.assertNotEqual(encrypted, "secret-value")
        self.assertEqual(reveal_secret_text(encrypted), "secret-value")

    def test_request_fingerprint_is_stable(self):
        self.assertEqual(request_fingerprint({"b": 2, "a": 1}), request_fingerprint({"a": 1, "b": 2}))

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


if __name__ == "__main__":
    unittest.main()
