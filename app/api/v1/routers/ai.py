from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.schemas.ai import (
    AIChatRequest,
    AIBrowserCaptureBatchGenerateRequest,
    AIBrowserCaptureGenerateRequest,
    AIBrowserCaptureRelationsRequest,
    AIBrowserCaptureScenarioRequest,
    AITestCaseExpandRequest,
    AITestCaseGenerateRequest,
    AIWebSocketTestCaseExpandRequest,
    AIWebSocketTestCaseGenerateRequest,
)
from app.services.ai_service import AIService
from app.services.ai_browser_capture_service import AIBrowserCaptureService
from app.services.ai_test_case_service import AITestCaseService
from app.services.ai_websocket_test_case_service import AIWebSocketTestCaseService

router = APIRouter()


@router.post("/browser-captures/{capture_id}/entries/{entry_id}/generate-cases", summary="AI 根据浏览器采集草稿生成用例")
def generate_cases_from_browser_capture(project_id: int, capture_id: int, entry_id: int, payload: AIBrowserCaptureGenerateRequest,
                                        db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = AIBrowserCaptureService(db).generate_cases(project_id=project_id, capture_id=capture_id, entry_id=entry_id,
                                                        payload=payload, current_user=current_user)
    return success(data=result, message="AI 采集草稿用例生成成功")


@router.post("/browser-captures/{capture_id}/generate-cases", summary="AI 批量生成浏览器采集用例")
def generate_cases_from_browser_capture_batch(
    project_id: int, capture_id: int, payload: AIBrowserCaptureBatchGenerateRequest,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    result = AIBrowserCaptureService(db).generate_batch(
        project_id=project_id, capture_id=capture_id, payload=payload, current_user=current_user
    )
    return success(data=result, message="AI 批量用例生成完成")


@router.post("/browser-captures/{capture_id}/analyze-relations", summary="分析浏览器采集接口依赖")
def analyze_browser_capture_relations(
    project_id: int, capture_id: int, payload: AIBrowserCaptureRelationsRequest,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    result = AIBrowserCaptureService(db).analyze_relations(
        project_id=project_id, capture_id=capture_id, payload=payload, current_user=current_user
    )
    return success(data=result, message="接口依赖分析完成")


@router.post("/browser-captures/{capture_id}/generate-scenario", summary="生成浏览器采集场景草稿")
def generate_browser_capture_scenario(
    project_id: int, capture_id: int, payload: AIBrowserCaptureScenarioRequest,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    result = AIBrowserCaptureService(db).generate_scenario(
        project_id=project_id, capture_id=capture_id, payload=payload, current_user=current_user
    )
    return success(data=result, message="场景草稿生成完成")


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
