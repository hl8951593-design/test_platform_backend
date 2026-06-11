from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.base import Base
from app.models.project import Project, ProjectEnvironment
from app.models.user import User
from app.schemas.ai import (
    AIBrowserCaptureBatchGenerateRequest,
    AIBrowserCaptureGenerateRequest,
    AIBrowserCaptureRelationsRequest,
    AIBrowserCaptureScenarioRequest,
    AIExecutionDiagnoseRequest,
)
from app.schemas.browser_capture import BrowserCaptureCreateRequest, BrowserCaptureEntryBatchRequest, BrowserCaptureEntryPayload, BrowserCaptureEntryUpdateRequest
from app.services.ai_browser_capture_service import AIBrowserCaptureService
from app.services.browser_capture_service import BrowserCaptureService


def main() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="capture-admin", account="capture-admin", password_hash="x", phone="10086",
                    email="capture@example.com", is_admin=True)
        db.add(user)
        db.flush()
        project = Project(name="capture-project", description=None, created_by_id=user.id)
        db.add(project)
        db.flush()
        environment = ProjectEnvironment(project_id=project.id, name="test", base_url="https://test.example.com",
                                         description=None, is_default=True, created_by_id=user.id)
        db.add(environment)
        db.commit()

        service = BrowserCaptureService(db)
        capture = service.create_capture(project_id=project.id, payload=BrowserCaptureCreateRequest(
            environment_id=environment.id, name="订单流程采集"), current_user=user)
        payload = BrowserCaptureEntryBatchRequest(entries=[BrowserCaptureEntryPayload(
            client_entry_id="entry-1", protocol="http", fingerprint="GET:/orders", name="查询订单",
            method="GET", path="/orders", source_url="https://test.example.com/orders",
            request_data={"headers": {}}, response_data={"status_code": 200, "body": {"data": {"token": "token-123456"}}},
            draft_data={"protocol": "http", "method": "GET", "path": "/orders"}, captured_at=datetime.now(),
        ), BrowserCaptureEntryPayload(
            client_entry_id="entry-2", protocol="http", fingerprint="POST:/orders", name="创建订单",
            method="POST", path="/orders", source_url="https://test.example.com/orders",
            request_data={"headers": {"Authorization": "token-123456"}}, response_data={"status_code": 201},
            draft_data={"protocol": "http", "method": "POST", "path": "/orders"}, captured_at=datetime.now(),
        )])
        first = service.upsert_entries(project_id=project.id, capture_id=capture.id, payload=payload, current_user=user)
        second = service.upsert_entries(project_id=project.id, capture_id=capture.id, payload=payload, current_user=user)
        assert first[0].id == second[0].id
        assert service.update_entry(project_id=project.id, capture_id=capture.id, entry_id=first[0].id,
                                    payload=BrowserCaptureEntryUpdateRequest(status="approved"),
                                    current_user=user).status == "approved"
        generated = SimpleNamespace(model_dump=lambda mode=None: {"cases": [], "source_summary": "mock"})
        with patch("app.services.ai_browser_capture_service.AITestCaseService.generate_test_cases", return_value=generated):
            assert AIBrowserCaptureService(db).generate_cases(
                project_id=project.id, capture_id=capture.id, entry_id=first[0].id,
                payload=AIBrowserCaptureGenerateRequest(), current_user=user,
            ) is generated
            batch = AIBrowserCaptureService(db).generate_batch(
                project_id=project.id, capture_id=capture.id,
                payload=AIBrowserCaptureBatchGenerateRequest(entry_ids=[first[0].id, first[1].id]),
                current_user=user,
            )
            assert batch["success_count"] == 2
        assert service.get_entry(project_id=project.id, capture_id=capture.id, entry_id=first[0].id,
                                 current_user=user).status == "review_required"
        analysis = AIBrowserCaptureService(db).analyze_relations(
            project_id=project.id, capture_id=capture.id,
            payload=AIBrowserCaptureRelationsRequest(entry_ids=[first[0].id, first[1].id]), current_user=user,
        )
        assert analysis["relations"][0]["variable"] == "token"
        scenario = AIBrowserCaptureService(db).generate_scenario(
            project_id=project.id, capture_id=capture.id,
            payload=AIBrowserCaptureScenarioRequest(entry_ids=[first[0].id, first[1].id]), current_user=user,
        )
        assert len(scenario["steps"]) == 2
        assert len(scenario["relations"]) == 1
        diagnosis_response = SimpleNamespace(content='{"summary":"鉴权失败","probable_causes":["token 失效"],"evidence":[],"suggestions":[],"risk_level":"medium"}', model="mock-ai")
        with patch("app.services.ai_browser_capture_service.AIService.chat", return_value=diagnosis_response):
            diagnosis = AIBrowserCaptureService(db).diagnose_execution(
                project_id=project.id,
                payload=AIExecutionDiagnoseRequest(protocol="http", draft_data={"path": "/orders"},
                                                   execution_data={"status": "failed"}),
                current_user=user,
            )
        assert diagnosis["summary"] == "鉴权失败"
        assert diagnosis["model"] == "mock-ai"
        print("browser-capture-service-ok")


if __name__ == "__main__":
    main()
