from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.ai_skills import get_ai_skill
from app.ai_skills.base import AISkillRunner
from app.core.permissions import ProjectPermission
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.schemas.ai import (
    AIGeneratedTestCaseResponse,
    AITestCaseExpandRequest,
    AITestCaseGenerateRequest,
)
from app.services.ai_service import AIService
from app.services.ai_run_event_service import AIRunTrace
from app.services.permission_service import PermissionService


class AITestCaseService:
    skill_id = "http-test-case"

    def __init__(self, db: Session):
        self.db = db
        self.project_repository = ProjectRepository(db)
        self.test_case_repository = TestCaseRepository(db)
        self.permission_service = PermissionService(db)
        self.ai_service = AIService()

    def generate_test_cases(
        self,
        *,
        project_id: int,
        environment_id: int,
        payload: AITestCaseGenerateRequest,
        current_user: User,
        trace: AIRunTrace | None = None,
    ) -> AIGeneratedTestCaseResponse:
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
        payload: AITestCaseExpandRequest,
        current_user: User,
        trace: AIRunTrace | None = None,
    ) -> AIGeneratedTestCaseResponse:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        source_case = self.test_case_repository.get_by_id(
            project_id=project_id,
            test_case_id=test_case_id,
        )
        if source_case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试用例不存在")

        selected_environment_id = (
            environment_id
            or source_case.environment_id
            or (source_case.environment_ids[0] if source_case.environment_ids else None)
        )
        if selected_environment_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="测试用例未绑定环境")

        environment, variables = self._context(project_id, selected_environment_id, current_user)
        source_case_data = self._source_case_to_dict(source_case)
        context = {
            "mode": "expand",
            "project_id": project_id,
            "environment_id": selected_environment_id,
            "environment": environment,
            "variables": variables,
            "payload": payload,
            "include_assertions": payload.include_assertions,
            "source_test_case": source_case_data,
        }
        skill = get_ai_skill(self.skill_id)
        return self._runner().run_traced(skill, context, trace) if trace else self._runner().run(skill, context)

    def _context(self, project_id: int, environment_id: int, current_user: User):
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        environment = self.project_repository.get_environment(
            project_id=project_id,
            environment_id=environment_id,
        )
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")
        return environment, self.project_repository.list_environment_variables(environment_id=environment_id)

    def _runner(self) -> AISkillRunner:
        return AISkillRunner(self.ai_service)

    def _source_case_to_dict(self, source_case: Any) -> dict[str, Any]:
        return {
            "id": source_case.id,
            "name": source_case.name,
            "description": source_case.description,
            "environment_id": source_case.environment_id,
            "environment_ids": source_case.environment_ids,
            "method": source_case.method,
            "path": source_case.path,
            "headers": source_case.headers or {},
            "query_params": source_case.query_params or {},
            "body_type": source_case.body_type,
            "body": source_case.body,
            "assertions": source_case.assertions or [],
            "extractors": source_case.extractors or [],
        }
