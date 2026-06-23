import json
from typing import Any

from fastapi import HTTPException, status

from app.core.response import normalize_response_data
from app.db.session import SessionLocal
from app.models.user import User
from app.schemas.ai import AISkillRunQueuedRead, AISkillRunRead, AISkillRunRequest
from app.services.ai_run_event_service import AIRunTrace, ai_run_event_store
from app.services.ai_skill_service import AISkillService


class AISkillRunService:
    def create_run(
        self,
        *,
        skill_id: str,
        payload: AISkillRunRequest,
        current_user: User,
    ) -> AISkillRunQueuedRead:
        run = ai_run_event_store.create_run(
            skill_id=skill_id,
            payload=payload,
            user_id=current_user.id,
        )
        return AISkillRunQueuedRead(
            run_id=run.run_id,
            skill_id=skill_id,
            operation=payload.operation,
            status=run.status,
        )

    def get_run(self, run_id: str, current_user: User) -> AISkillRunRead:
        try:
            run = ai_run_event_store.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI run 不存在") from exc
        owner_id = ai_run_event_store.get_run_user_id(run_id)
        if owner_id != current_user.id and not bool(getattr(current_user, "is_admin", False)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无 AI run 访问权限")
        return run

    @staticmethod
    def execute_run(run_id: str, skill_id: str, payload_data: dict[str, Any], user_id: int) -> None:
        ai_run_event_store.start_run(run_id)
        trace = AIRunTrace(ai_run_event_store, run_id)
        try:
            payload = AISkillRunRequest.model_validate(payload_data)
            with SessionLocal() as db:
                user = db.get(User, user_id)
                if user is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
                trace.step_started("运行 AI Skill", skill_id=skill_id, operation=payload.operation)
                result = AISkillService(db).run_skill(
                    skill_id=skill_id,
                    payload=payload,
                    current_user=user,
                    trace=trace,
                )
                trace.step_completed("运行 AI Skill")
            ai_run_event_store.complete_run(run_id, normalize_response_data(result))
        except Exception as exc:  # noqa: BLE001
            error_message = AISkillRunService._error_message(exc)
            ai_run_event_store.fail_run(run_id, error_message)

    @staticmethod
    def _error_message(exc: Exception) -> str:
        if isinstance(exc, HTTPException):
            detail = exc.detail
            if isinstance(detail, (dict, list)):
                return json.dumps(detail, ensure_ascii=False)
            return str(detail)
        return str(exc)
