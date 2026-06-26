import unittest

from app.schemas.visual_flow import FlowUpdateRequest


class VisualFlowSchemaTests(unittest.TestCase):
    def _payload(self):
        return {
            "name": "visual flow",
            "description": "",
            "definition": {
                "schemaVersion": "1.0",
                "projectId": 1,
                "environmentId": 4,
                "name": "visual flow",
                "description": "",
                "nodes": [
                    {
                        "id": "START",
                        "kind": "start",
                        "name": "Start",
                        "position": {"x": 0, "y": 0},
                    },
                    {
                        "id": "END",
                        "kind": "end",
                        "name": "End",
                        "position": {"x": 240, "y": 0},
                    },
                ],
                "edges": [
                    {
                        "id": "EDGE-1",
                        "source": "START",
                        "target": "END",
                        "route": "always",
                    }
                ],
            },
        }

    def test_flow_update_accepts_missing_expected_version_for_frontend_compatibility(self):
        payload = FlowUpdateRequest.model_validate(self._payload())

        self.assertIsNone(payload.expected_version)

    def test_flow_update_accepts_camel_case_expected_version(self):
        raw = self._payload()
        raw["expectedVersion"] = 3

        payload = FlowUpdateRequest.model_validate(raw)

        self.assertEqual(payload.expected_version, 3)


if __name__ == "__main__":
    unittest.main()
