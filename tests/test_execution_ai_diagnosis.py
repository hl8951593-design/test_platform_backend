import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.schemas.ai import AIExecutionDiagnoseRequest
from app.services.agent_tool_service import AgentToolBackend
from app.services.ai_browser_capture_service import AIBrowserCaptureService
from tests.test_execution_diagnostic_projection import run_220_shape


class ExecutionAIDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.user = SimpleNamespace(id=7, username="analyst")
        self.backend = AgentToolBackend(self.db)

    @patch("app.services.ai_browser_capture_service.AIService.chat")
    @patch(
        "app.services.ai_browser_capture_service.PermissionService.require_project_permission"
    )
    @patch("app.services.agent_platform_tool_service.ExecutionRecordService.get_detail")
    def test_execution_diagnosis_sends_bounded_semantic_evidence(
        self, get_detail, _require_permission, chat
    ):
        get_detail.return_value = run_220_shape()
        chat.return_value = SimpleNamespace(
            content=json.dumps(
                {
                    "summary": "auth failed",
                    "probable_causes": [],
                    "evidence": [],
                    "suggestions": [],
                    "risk_level": "high",
                }
            ),
            model="test",
        )

        result = self.backend.execute(
            tool_name="execution.diagnose",
            payload={
                "project_id": 1,
                "execution_type": "scenario",
                "execution_id": 220,
            },
            current_user=self.user,
        )

        request = chat.call_args.args[0]
        prompt = request.messages[1].content
        self.assertLessEqual(len(prompt), 16000)
        self.assertIn("请求未授权", prompt)
        self.assertIn("90001", prompt)
        self.assertNotIn("x" * 1000, prompt)
        self.assertIn('"evidence"', prompt)
        self.assertNotIn('"execution"', prompt)
        self.assertEqual(result["source"], "execution.diagnostic")

    @patch("app.services.ai_browser_capture_service.AIService.chat")
    @patch(
        "app.services.ai_browser_capture_service.PermissionService.require_project_permission"
    )
    def test_ai_diagnosis_rejects_evidence_above_defense_in_depth_limit(
        self, _require_permission, chat
    ):
        request = AIExecutionDiagnoseRequest(
            protocol="scenario",
            draft_data={},
            evidence={"oversized": "z" * 17000},
        )

        with self.assertRaises(HTTPException) as raised:
            AIBrowserCaptureService(self.db).diagnose_execution(
                project_id=1,
                payload=request,
                current_user=self.user,
            )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(
            raised.exception.detail,
            "execution diagnostic evidence exceeds 16000 chars",
        )
        chat.assert_not_called()

    def test_ai_diagnosis_request_accepts_legacy_execution_data_alias(self):
        request = AIExecutionDiagnoseRequest(
            protocol="http",
            draft_data={},
            execution_data={"summary": {"status": "failed"}},
        )

        self.assertEqual(request.evidence["summary"]["status"], "failed")
        self.assertNotIn("execution_data", request.model_dump())

    def test_execution_diagnosis_skill_requires_progressive_evidence_workflow(self):
        skill_path = (
            Path(__file__).parents[1]
            / "app"
            / "agent_skills"
            / "execution-diagnosis"
            / "SKILL.md"
        )
        content = skill_path.read_text(encoding="utf-8")
        required_in_order = [
            "`view=summary`",
            "`view=failures`",
            "`view=step`",
            "`view=artifact`",
            "`execution.diagnose`",
        ]

        positions = [content.index(marker) for marker in required_in_order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("never request full raw output by default", content)


if __name__ == "__main__":
    unittest.main()
