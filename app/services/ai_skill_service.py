from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai_skills import get_ai_skill
from app.ai_skills.registry import list_ai_skills
from app.models.user import User
from app.schemas.ai import (
    AIGeneratedScenarioResponse,
    AIGeneratedTestCaseResponse,
    AIGeneratedWebSocketTestCaseResponse,
    AIScenarioComposeRequest,
    AISkillOperationRead,
    AISkillRead,
    AISkillRunRequest,
    AITestCaseExpandRequest,
    AITestCaseGenerateRequest,
    AIWebSocketTestCaseExpandRequest,
    AIWebSocketTestCaseGenerateRequest,
)
from app.services.ai_scenario_composer_service import AIScenarioComposerService
from app.services.ai_run_event_service import AIRunTrace
from app.services.ai_test_case_service import AITestCaseService
from app.services.ai_websocket_test_case_service import AIWebSocketTestCaseService


_SCHEMA_TYPES = {
    "AITestCaseGenerateRequest": AITestCaseGenerateRequest,
    "AITestCaseExpandRequest": AITestCaseExpandRequest,
    "AIGeneratedTestCaseResponse": AIGeneratedTestCaseResponse,
    "AIWebSocketTestCaseGenerateRequest": AIWebSocketTestCaseGenerateRequest,
    "AIWebSocketTestCaseExpandRequest": AIWebSocketTestCaseExpandRequest,
    "AIGeneratedWebSocketTestCaseResponse": AIGeneratedWebSocketTestCaseResponse,
    "AIScenarioComposeRequest": AIScenarioComposeRequest,
    "AIGeneratedScenarioResponse": AIGeneratedScenarioResponse,
}


class AISkillService:
    def __init__(self, db: Session):
        self.db = db

    def list_skills(self) -> list[AISkillRead]:
        return [self._skill_read(skill) for skill in list_ai_skills()]

    def get_skill(self, skill_id: str) -> AISkillRead:
        try:
            return self._skill_read(get_ai_skill(skill_id))
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI skill 不存在") from exc

    def run_skill(
        self,
        *,
        skill_id: str,
        payload: AISkillRunRequest,
        current_user: User,
        trace: AIRunTrace | None = None,
    ) -> AIGeneratedTestCaseResponse | AIGeneratedWebSocketTestCaseResponse | AIGeneratedScenarioResponse:
        self._ensure_operation(skill_id, payload.operation)
        if skill_id == "http-test-case":
            return self._run_http_test_case(payload, current_user, trace)
        if skill_id == "websocket-test-case":
            return self._run_websocket_test_case(payload, current_user, trace)
        if skill_id == "scenario-composer":
            return self._run_scenario_composer(payload, current_user, trace)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="AI skill 暂未绑定运行适配器")

    def _run_http_test_case(
        self,
        payload: AISkillRunRequest,
        current_user: User,
        trace: AIRunTrace | None,
    ) -> AIGeneratedTestCaseResponse:
        service = AITestCaseService(self.db)
        if payload.operation == "generate":
            environment_id = self._require_environment_id(payload)
            return service.generate_test_cases(
                project_id=payload.project_id,
                environment_id=environment_id,
                payload=self._validate_input(AITestCaseGenerateRequest, payload.input),
                current_user=current_user,
                trace=trace,
            )
        if payload.operation == "expand":
            source_id = self._require_source_id(payload)
            return service.expand_test_cases(
                project_id=payload.project_id,
                test_case_id=source_id,
                environment_id=payload.environment_id,
                payload=self._validate_input(AITestCaseExpandRequest, payload.input),
                current_user=current_user,
                trace=trace,
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的 skill operation")

    def _run_scenario_composer(
        self,
        payload: AISkillRunRequest,
        current_user: User,
        trace: AIRunTrace | None,
    ) -> AIGeneratedScenarioResponse:
        if payload.operation != "compose":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的 skill operation")
        environment_id = self._require_environment_id(payload)
        return AIScenarioComposerService(self.db).compose(
            project_id=payload.project_id,
            environment_id=environment_id,
            payload=self._validate_input(AIScenarioComposeRequest, payload.input),
            current_user=current_user,
            trace=trace,
        )

    def _run_websocket_test_case(
        self,
        payload: AISkillRunRequest,
        current_user: User,
        trace: AIRunTrace | None,
    ) -> AIGeneratedWebSocketTestCaseResponse:
        service = AIWebSocketTestCaseService(self.db)
        if payload.operation == "generate":
            environment_id = self._require_environment_id(payload)
            return service.generate_test_cases(
                project_id=payload.project_id,
                environment_id=environment_id,
                payload=self._validate_input(AIWebSocketTestCaseGenerateRequest, payload.input),
                current_user=current_user,
                trace=trace,
            )
        if payload.operation == "expand":
            source_id = self._require_source_id(payload)
            return service.expand_test_cases(
                project_id=payload.project_id,
                test_case_id=source_id,
                environment_id=payload.environment_id,
                payload=self._validate_input(AIWebSocketTestCaseExpandRequest, payload.input),
                current_user=current_user,
                trace=trace,
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的 skill operation")

    def _skill_read(self, skill) -> AISkillRead:
        package_info = skill.package.info()
        return AISkillRead(
            id=skill.skill_id,
            name=package_info.metadata.name,
            description=package_info.metadata.description,
            version=package_info.metadata.version,
            domain=package_info.domain,
            protocol=package_info.protocol,
            operations=[
                self._operation_read(operation)
                for operation in package_info.operations
                if isinstance(operation, dict)
            ],
        )

    def _operation_read(self, operation: dict[str, Any]) -> AISkillOperationRead:
        input_schema = str(operation.get("input_schema") or "")
        output_schema = str(operation.get("output_schema") or "")
        return AISkillOperationRead(
            name=str(operation.get("name") or ""),
            summary=str(operation.get("summary") or ""),
            input_schema=input_schema,
            output_schema=output_schema,
            input_json_schema=self._json_schema(input_schema),
            output_json_schema=self._json_schema(output_schema),
            requires_environment=bool(operation.get("requires_environment")),
            requires_source=bool(operation.get("requires_source")),
        )

    def _ensure_operation(self, skill_id: str, operation: str) -> None:
        try:
            skill = get_ai_skill(skill_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI skill 不存在") from exc

        package_info = skill.package.info()
        supported = {
            item.get("name")
            for item in package_info.operations
            if isinstance(item, dict)
        }
        if operation not in supported:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="AI skill operation 不存在")

    def _validate_input(self, schema, data: dict[str, Any]):
        try:
            return schema.model_validate(data)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.errors(),
            ) from exc

    def _require_environment_id(self, payload: AISkillRunRequest) -> int:
        if payload.environment_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="environment_id 必填")
        return payload.environment_id

    def _require_source_id(self, payload: AISkillRunRequest) -> int:
        if payload.source_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="source_id 必填")
        return payload.source_id

    def _json_schema(self, schema_name: str) -> dict[str, Any]:
        schema_type = _SCHEMA_TYPES.get(schema_name)
        if schema_type is None:
            return {}
        return schema_type.model_json_schema()
