import json
import unittest
from pathlib import Path

from app.schemas.desktop_device import DesktopDeviceRegisterRead


FIXTURE_PATH = Path(__file__).with_name("testauto_desktop_contract_v1.json")


class DesktopContractFixtureTests(unittest.TestCase):
    def test_authoritative_fixture_matches_backend_contract(self):
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            fixture["schema_version"],
            "testauto-desktop-contract-fixture-v1",
        )
        DesktopDeviceRegisterRead.model_validate(
            fixture["device_register_response"]
        )
        claim = fixture["claim_response"]
        available = fixture["available_executions_response"]
        self.assertEqual(available["total"], 1)
        self.assertEqual(available["items"][0]["expected_status"], "queued")
        self.assertEqual(
            available["items"][0]["execution_id"],
            claim["execution_id"],
        )
        self.assertEqual(claim["status"], "claimed")
        self.assertGreaterEqual(claim["last_client_sequence"], 0)
        self.assertEqual(
            claim["snapshot"]["dsl"]["schema_version"],
            "ui-case-v1",
        )
        self.assertNotIn("secret_values", claim["snapshot"])
        self.assertEqual(
            [message["type"] for message in fixture["control_messages"]],
            ["execution.available", "command.available"],
        )
        patch_command = fixture["patch_command"]
        self.assertEqual(patch_command["command_type"], "patch")
        self.assertEqual(
            patch_command["payload"]["schema_version"],
            "ui-runtime-patch-request-v1",
        )
        self.assertEqual(
            fixture["runtime_patch_response"]["command_id"],
            patch_command["command_id"],
        )
        presign = fixture["artifact_presign_response"]
        self.assertEqual(presign["method"], "PUT")
        self.assertNotIn("/", presign["artifact_ref"])
        self.assertEqual(
            fixture["artifact_finalize_response"]["artifact_ref"],
            presign["artifact_ref"],
        )


if __name__ == "__main__":
    unittest.main()
