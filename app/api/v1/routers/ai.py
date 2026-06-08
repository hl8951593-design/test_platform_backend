from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.schemas.ai import (
    AIChatRequest,
    AITestCaseExpandRequest,
    AITestCaseGenerateRequest,
    AIWebSocketTestCaseExpandRequest,
    AIWebSocketTestCaseGenerateRequest,
)
from app.services.ai_service import AIService
from app.services.ai_test_case_service import AITestCaseService
from app.services.ai_websocket_test_case_service import AIWebSocketTestCaseService

router = APIRouter()


@router.get("/provider", summary="查询 AI 数据源配置")
def get_ai_provider(current_user: User = Depends(get_current_user)):
    provider = AIService().provider_config()
    return success(data=provider)


@router.post("/chat", summary="DeepSeek 对话补全")
def chat_with_ai(
    payload: AIChatRequest,
    current_user: User = Depends(get_current_user),
):
    result = AIService().chat(payload)
    return success(data=result, message="AI 调用成功")


@router.post("/test-cases/generate", summary="AI 生成接口测试用例")
def generate_test_cases(
    project_id: int,
    environment_id: int,
    payload: AITestCaseGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = AITestCaseService(db).generate_test_cases(
        project_id=project_id,
        environment_id=environment_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=result, message="AI 测试用例生成成功")


@router.post("/test-cases/{test_case_id}/expand", summary="AI 扩写接口测试用例")
def expand_test_cases(
    project_id: int,
    test_case_id: int,
    payload: AITestCaseExpandRequest,
    environment_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = AITestCaseService(db).expand_test_cases(
        project_id=project_id,
        test_case_id=test_case_id,
        environment_id=environment_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=result, message="AI 测试用例扩写成功")


@router.post("/websocket-test-cases/generate", summary="AI 生成 WebSocket 测试用例")
def generate_websocket_test_cases(
    project_id: int,
    environment_id: int,
    payload: AIWebSocketTestCaseGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = AIWebSocketTestCaseService(db).generate_test_cases(
        project_id=project_id,
        environment_id=environment_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=result, message="AI WebSocket 测试用例生成成功")


@router.post("/websocket-test-cases/{test_case_id}/expand", summary="AI 扩写 WebSocket 测试用例")
def expand_websocket_test_cases(
    project_id: int,
    test_case_id: int,
    payload: AIWebSocketTestCaseExpandRequest,
    environment_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = AIWebSocketTestCaseService(db).expand_test_cases(
        project_id=project_id,
        test_case_id=test_case_id,
        environment_id=environment_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=result, message="AI WebSocket 测试用例扩写成功")
