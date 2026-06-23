import json

from fastapi import APIRouter, BackgroundTasks, Depends, Header
from fastapi.responses import StreamingResponse
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
    AIExecutionDiagnoseRequest,
    AISkillRunRequest,
    AITestCaseExpandRequest,
    AITestCaseGenerateRequest,
    AIWebSocketTestCaseExpandRequest,
    AIWebSocketTestCaseGenerateRequest,
)
from app.services.ai_service import AIService
from app.services.ai_browser_capture_service import AIBrowserCaptureService
from app.services.ai_run_event_service import TERMINAL_RUN_STATUSES, ai_run_event_store
from app.services.ai_skill_service import AISkillService
from app.services.ai_skill_run_service import AISkillRunService
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


@router.post("/executions/diagnose", summary="AI 诊断接口执行结果")
def diagnose_execution(
    project_id: int, payload: AIExecutionDiagnoseRequest,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    result = AIBrowserCaptureService(db).diagnose_execution(
        project_id=project_id, payload=payload, current_user=current_user
    )
    return success(data=result, message="AI 执行诊断完成")


@router.get("/skills", summary="查询可用 AI Skills")
def list_ai_skills(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = AISkillService(db).list_skills()
    return success(data=result)


@router.get("/skills/{skill_id}", summary="查询 AI Skill 详情")
def get_ai_skill_detail(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = AISkillService(db).get_skill(skill_id)
    return success(data=result)


@router.post("/skills/{skill_id}/run", summary="运行 AI Skill")
def run_ai_skill(
    skill_id: str,
    payload: AISkillRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = AISkillService(db).run_skill(
        skill_id=skill_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=result, message="AI Skill 执行成功")


@router.post("/skills/{skill_id}/runs", summary="创建可观测 AI Skill Run")
def create_ai_skill_run(
    skill_id: str,
    payload: AISkillRunRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    queued = AISkillRunService().create_run(
        skill_id=skill_id,
        payload=payload,
        current_user=current_user,
    )
    background_tasks.add_task(
        AISkillRunService.execute_run,
        queued.run_id,
        skill_id,
        payload.model_dump(mode="json"),
        current_user.id,
    )
    return success(data=queued, message="AI Skill Run 已创建")


@router.get("/skill-runs/{run_id}", summary="查询 AI Skill Run")
def get_ai_skill_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
):
    result = AISkillRunService().get_run(run_id, current_user)
    return success(data=result)


@router.get("/skill-runs/{run_id}/events", summary="订阅 AI Skill Run 事件")
def stream_ai_skill_run_events(
    run_id: str,
    last_event_id: int = Header(default=0, alias="Last-Event-ID", ge=0),
    current_user: User = Depends(get_current_user),
):
    AISkillRunService().get_run(run_id, current_user)

    def event_stream():
        sequence = last_event_id
        while True:
            events, run_status = ai_run_event_store.wait_for_events(run_id, sequence)
            if not events:
                if run_status in TERMINAL_RUN_STATUSES:
                    return
                yield "event: heartbeat\ndata: {}\n\n"
            for item in events:
                sequence = item.sequence
                yield (
                    f"id: {item.sequence}\n"
                    f"event: {item.event}\n"
                    f"data: {json.dumps(item.payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
                )
            if run_status in TERMINAL_RUN_STATUSES and not events:
                return
            if run_status in TERMINAL_RUN_STATUSES and events:
                return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
