from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.ai_skills import get_ai_skill
from app.ai_skills.base import AISkillRunner
from app.core.permissions import ProjectPermission
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.websocket_test_case_repository import WebSocketTestCaseRepository
from app.schemas.ai import (
    AIGeneratedWebSocketTestCaseResponse,
    AIWebSocketTestCaseExpandRequest,
    AIWebSocketTestCaseGenerateRequest,
)
from app.services.ai_service import AIService
from app.services.ai_run_event_service import AIRunTrace
from app.services.permission_service import PermissionService


class AIWebSocketTestCaseService:
    skill_id = "websocket-test-case"

    def __init__(self, db: Session):
        self.project_repository = ProjectRepository(db)
        self.test_case_repository = WebSocketTestCaseRepository(db)
        self.permission_service = PermissionService(db)
        self.ai_service = AIService()

    def generate_test_cases(
        self,
        *,
        project_id: int,
        environment_id: int,
        payload: AIWebSocketTestCaseGenerateRequest,
        current_user: User,
        trace: AIRunTrace | None = None,
    ) -> AIGeneratedWebSocketTestCaseResponse:
        environment, variables = self._context(project_id, environment_id, current_user)
        context = {
            "mode": "generate",
            "project_id": project_id,
            "environment_id": environment_id,
            "environment": environment,
            "variables": variables,
            "payload": payload,
            "include_assertions": payload.include_assertions,
        }
        skill = get_ai_skill(self.skill_id)
        return self._runner().run_traced(skill, context, trace) if trace else self._runner().run(skill, context)

    def expand_test_cases(
        self,
        *,
        project_id: int,
        test_case_id: int,
        environment_id: int | None,
        payload: AIWebSocketTestCaseExpandRequest,
        current_user: User,
        trace: AIRunTrace | None = None,
    ) -> AIGeneratedWebSocketTestCaseResponse:
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.MANAGE_CASE.value)
        source = self.test_case_repository.get_by_id(project_id=project_id, test_case_id=test_case_id)
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WebSocket 测试用例不存在")
        selected_environment_id = environment_id or source.environment_id or (source.environment_ids[0] if source.environment_ids else None)
        if selected_environment_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="WebSocket 测试用例未绑定环境")

        environment, variables = self._context(project_id, selected_environment_id, current_user)
        context = {
            "mode": "expand",
            "project_id": project_id,
            "environment_id": selected_environment_id,
            "environment": environment,
            "variables": variables,
            "payload": payload,
            "include_assertions": payload.include_assertions,
            "source_websocket_test_case": self._source_case(source),
        }
        skill = get_ai_skill(self.skill_id)
        return self._runner().run_traced(skill, context, trace) if trace else self._runner().run(skill, context)

    def _context(self, project_id: int, environment_id: int, current_user: User):
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.MANAGE_CASE.value)
        environment = self.project_repository.get_environment(project_id=project_id, environment_id=environment_id)
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")
        return environment, self.project_repository.list_environment_variables(environment_id=environment_id)

    def _runner(self) -> AISkillRunner:
        return AISkillRunner(self.ai_service)

    def _source_case(self, source):
        return {
            "id": source.id,
            "name": source.name,
            "description": source.description,
            "environment_id": source.environment_id,
            "environment_ids": source.environment_ids,
            "path": source.path,
            "headers": source.headers or {},
            "subprotocols": source.subprotocols or [],
            "messages": source.messages or [],
            "receive_count": source.receive_count,
            "connect_timeout_ms": source.connect_timeout_ms,
            "receive_timeout_ms": source.receive_timeout_ms,
            "assertions": source.assertions or [],
            "extractors": source.extractors or [],
        }
