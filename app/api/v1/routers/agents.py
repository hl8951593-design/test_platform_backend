import json
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from fastapi.params import Query as QueryParam
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.execution_worker import execution_worker
from app.core.response import success
from app.db.session import SessionLocal
from app.models.agent import (
    AgentBackendContract,
    AgentContextBuild,
    AgentLoopObservation,
    AgentMemoryRetrievalProfile,
    AgentMemorySourceProfile,
    AgentMemoryStalenessEvent,
    AgentMemoryUsageEvent,
    AgentMemoryValidationEvent,
    AgentReconcileAttempt,
    ProjectMemory,
)
from app.models.user import User
from app.schemas.agent import (
    AgentApprovalDecisionRead,
    AgentApprovalDecisionRequest,
    AgentApprovalExpireAuditRead,
    AgentApprovalExpireProcessRead,
    AgentApprovalLineageRead,
    AgentApprovalMutationLogRead,
    AgentApprovalRead,
    AgentAlertSnapshotRead,
    AgentBackendCompletionAuditRead,
    AgentCapabilitiesRead,
    AgentConversationExportRead,
    AgentConversationRead,
    AgentConversationSmokeRead,
    AgentConversationSmokeRequest,
    AgentConversationTranscriptRead,
    AgentContextBuildCreateRequest,
    AgentContextBuildRead,
    AgentEventReplayAuditRead,
    AgentEventReplayStressAuditRead,
    AgentFaultInjectionCaseRead,
    AgentFaultInjectionCoverageRead,
    AgentFaultInjectionRequest,
    AgentFaultInjectionRunRead,
    AgentLaunchAuditRead,
    AgentLoopObservationCreateRequest,
    AgentLoopObservationRead,
    AgentBackendContractRead,
    AgentMemoryCandidateRead,
    AgentMemoryCreateRequest,
    AgentMemoryDecisionRequest,
    AgentMemoryFeedbackProcessRead,
    AgentMemoryFeedbackRequest,
    AgentMemoryRead,
    AgentMemoryRetrievalProfileRead,
    AgentMemoryRetrieveRequest,
    AgentMemorySourceProfileRead,
    AgentMemoryStalenessEventRead,
    AgentMemoryUpdateRequest,
    AgentMemoryUsageEventRead,
    AgentMemoryValidationEventRead,
    AgentMetricsSnapshotRead,
    AgentMigrationBlockRead,
    AgentMigrationBlockResolveRead,
    AgentMigrationBlockResolveRequest,
    AgentModelHealthRead,
    AgentOutboxPublishRead,
    AgentReadinessDashboardRead,
    AgentReleaseGatePromotionRead,
    AgentReleaseGateRead,
    AgentReconcileAttemptRead,
    AgentRunActionStateRead,
    AgentRunCreateRequest,
    AgentRunEventSnapshotRead,
    AgentRunbookDiagnosisRead,
    AgentRunbookRead,
    AgentRunReconcileRead,
    AgentRunRead,
    AgentRunResumeRead,
    AgentRunSummaryRead,
    AgentRootCauseRuleGovernanceAuditRead,
    AgentRuntimeSnapshotRead,
    AgentSkillRead,
    AgentToolCallRead,
    AgentWorkerQueueAuditRead,
)
from app.services.agent_approval_service import ApprovalExpireScanner, ApprovalService
from app.services.agent_fault_injection_service import AgentFaultInjectionService
from app.services.agent_loop_service import ContextBuilder, LoopController, RootCauseRuleEngine
from app.services.agent_memory_service import (
    MemoryFeedbackWorker,
    MemoryManager,
    MemoryRetrievalProfileResolver,
    MemorySourceProfileResolver,
    memory_candidate_to_payload,
)
from app.services.agent_observability_service import (
    AgentAlertService,
    AgentBackendCompletionAuditService,
    AgentEventReplayAuditService,
    AgentFaultInjectionCoverageService,
    AgentLaunchAuditService,
    AgentMetricsService,
    AgentOutboxPublisher,
    AgentReadinessDashboardService,
    AgentWorkerQueueAuditService,
)
from app.services.agent_reconcile_service import MigrationCoordinator, ReconcileWorker
from app.services.agent_release_gate_service import AgentReleaseGateService
from app.services.agent_resume_service import AgentRunResumeService
from app.services.agent_runbook_service import AgentRunbookService
from app.services.agent_runtime_service import (
    AgentConversationRunner,
    AgentModelHealthService,
    AgentRuntimeService,
    ExecutionLedgerService,
    RUN_TERMINAL_STATUSES,
)
from app.services.agent_skill_registry import AgentSkillRegistry
from app.services.permission_service import PermissionService

router = APIRouter()

AGENT_SSE_ACTIVE_POLL_INTERVAL_SECONDS = 0.1
AGENT_SSE_IDLE_POLL_INTERVAL_SECONDS = 0.5
AGENT_SSE_HEARTBEAT_INTERVAL_SECONDS = 15


def _run_agent_conversation(run_id: str, user_id: int) -> None:
    with SessionLocal() as worker_db:
        AgentConversationRunner(worker_db).run(run_id=run_id, user_id=user_id)


def _should_start_agent_conversation_worker(db: Session) -> bool:
    bind = db.get_bind()
    if bind.dialect.name != "sqlite":
        return True
    database = getattr(bind.url, "database", None)
    return database not in {None, "", ":memory:"}


def _query_value(value, default=None):
    return default if isinstance(value, QueryParam) else value


@router.get("/capabilities", summary="鏌ヨ Agent Runtime 鑳藉姏")
def get_agent_capabilities(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = (db, current_user)
    return success(data=AgentCapabilitiesRead.model_validate(AgentRuntimeService(db).capabilities()))


@router.get("/model-health", summary="Check Agent model configuration and optional live stream probe")
def get_agent_model_health(
    live: bool = Query(default=False, description="Run a minimal live DeepSeek stream probe"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if live and not PermissionService(db).is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for live Agent model probe")
    return success(data=AgentModelHealthRead.model_validate(AgentModelHealthService().check(live=live)))


@router.get("/skills", summary="查询 Agent Skill 目录")
def list_agent_skills(
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    return success(data=[AgentSkillRead.model_validate(item) for item in AgentSkillRegistry().catalog()])


@router.post("/conversation-smoke", summary="执行 Agent 对话端到端 smoke 诊断")
def run_agent_conversation_smoke(
    payload: AgentConversationSmokeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not PermissionService(db).is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for Agent conversation smoke")
    smoke = AgentRuntimeService(db).run_conversation_smoke(
        project_id=payload.project_id,
        intent=payload.intent,
        max_iterations=payload.max_iterations,
        current_user=current_user,
    )
    return success(data=AgentConversationSmokeRead.model_validate(smoke), message="Agent conversation smoke completed")


@router.get(
    "/backend-contracts/{backend_name}/operations/{backend_operation}",
    summary="查询 Agent Backend Operation Contract",
)
def get_agent_backend_contract(
    backend_name: str,
    backend_operation: str,
    backend_contract_version: str = "v1",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not PermissionService(db).is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for Agent backend contract")
    AgentRuntimeService(db).ensure_backend_contracts()
    contract = db.scalar(
        select(AgentBackendContract).where(
            AgentBackendContract.backend_name == backend_name,
            AgentBackendContract.backend_operation == backend_operation,
            AgentBackendContract.backend_contract_version == backend_contract_version,
        )
    )
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent backend contract not found")
    return success(data=AgentBackendContractRead.model_validate(contract))


@router.get("/metrics", summary="查询 Agent Runtime 监控指标快照")
def get_agent_metrics(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    if project_id is not None:
        permission_service.require_project_access(current_user, project_id)
    elif not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for global Agent metrics")
    snapshot = AgentMetricsService(db).snapshot(project_id=project_id)
    return success(data=AgentMetricsSnapshotRead.model_validate(snapshot))


@router.get("/dashboard", summary="查询 Agent Runtime 上线门禁 Dashboard")
def get_agent_readiness_dashboard(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    if project_id is not None:
        permission_service.require_project_access(current_user, project_id)
    elif not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for global Agent dashboard")
    AgentRuntimeService(db).ensure_backend_contracts()
    snapshot = AgentReadinessDashboardService(db).snapshot(project_id=project_id)
    return success(data=AgentReadinessDashboardRead.model_validate(snapshot))


@router.get("/launch-audit", summary="审计 Agent 前端联调与上线准备状态")
def get_agent_launch_audit(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    if project_id is not None:
        permission_service.require_project_access(current_user, project_id)
    elif not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for global Agent launch audit")
    AgentRuntimeService(db).ensure_backend_contracts()
    audit = AgentLaunchAuditService(db).audit(project_id=project_id)
    return success(data=AgentLaunchAuditRead.model_validate(audit))


@router.get("/backend-completion-audit", summary="审计 Agent 后端功能完成度")
def get_agent_backend_completion_audit(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    if project_id is not None:
        permission_service.require_project_access(current_user, project_id)
    elif not permission_service.is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin required for global Agent backend completion audit",
        )
    AgentRuntimeService(db).ensure_backend_contracts()
    audit = AgentBackendCompletionAuditService(db).audit(project_id=project_id)
    return success(data=AgentBackendCompletionAuditRead.model_validate(audit))


@router.get("/alerts", summary="查询 Agent Runtime 监控告警快照")
def get_agent_alerts(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    if project_id is not None:
        permission_service.require_project_access(current_user, project_id)
    elif not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for global Agent alerts")
    AgentRuntimeService(db).ensure_backend_contracts()
    snapshot = AgentAlertService(db).snapshot(project_id=project_id)
    return success(data=AgentAlertSnapshotRead.model_validate(snapshot))


@router.get("/root-cause-rules/audit", summary="审计 Agent RootCause 规则治理状态")
def audit_agent_root_cause_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    if not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for Agent root cause rule audit")
    audit = RootCauseRuleEngine(db).audit_rule_governance()
    return success(data=AgentRootCauseRuleGovernanceAuditRead.model_validate(audit))


@router.get("/approvals/expire-audit", summary="审计 Agent Approval 批量过期扫描状态")
def audit_agent_approval_expiration(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    if project_id is not None:
        permission_service.require_project_access(current_user, project_id)
    elif not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for global Agent approval expire audit")
    audit = ApprovalExpireScanner(db).audit(project_id=project_id)
    return success(data=AgentApprovalExpireAuditRead.model_validate(audit))


@router.post("/approvals/expire", summary="执行 Agent Approval 批量过期扫描")
def process_agent_approval_expiration(
    project_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    if project_id is not None:
        permission_service.require_project_access(current_user, project_id)
    elif not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for global Agent approval expiration")
    summary = ApprovalExpireScanner(db).expire_due_summary(limit=limit, project_id=project_id)
    return success(data=AgentApprovalExpireProcessRead.model_validate(summary), message="Agent approval expiration scanned")


@router.get("/worker-queue/audit", summary="审计 Agent WorkerQueue lease 与重复 claim 状态")
def audit_agent_worker_queue(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    if project_id is not None:
        permission_service.require_project_access(current_user, project_id)
    elif not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for global Agent worker queue audit")
    audit = AgentWorkerQueueAuditService(db).audit(project_id=project_id)
    return success(data=AgentWorkerQueueAuditRead.model_validate(audit))


@router.get("/events/replay-stress-audit", summary="审计 Agent EventStore/SSE 高并发重放窗口")
def audit_agent_event_replay_stress(
    project_id: int | None = None,
    sample_limit: int = Query(default=100, ge=1, le=500),
    cursor_count: int = Query(default=3, ge=1, le=10),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    if project_id is not None:
        permission_service.require_project_access(current_user, project_id)
    elif not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for global Agent replay stress audit")
    audit = AgentEventReplayAuditService(db).audit_project(
        project_id=project_id,
        sample_limit=sample_limit,
        cursor_count=cursor_count,
    )
    return success(data=AgentEventReplayStressAuditRead.model_validate(audit))


@router.post("/outbox/publish", summary="发布 Agent Outbox 待发布事件")
def publish_agent_outbox(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not PermissionService(db).is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for Agent outbox publishing")
    summary = AgentOutboxPublisher(db).publish_pending(limit=limit)
    return success(data=AgentOutboxPublishRead.model_validate(summary), message="Agent outbox publish attempted")


@router.get("/release-gates", summary="查询 Agent 灰度发布门禁")
def get_agent_release_gates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not PermissionService(db).is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for Agent release gates")
    AgentRuntimeService(db).ensure_backend_contracts()
    snapshot = AgentReleaseGateService(db).snapshot()
    return success(data=AgentReleaseGateRead.model_validate(snapshot))


@router.get("/release-gates/promotion", summary="评估 Agent 灰度晋级条件")
def assess_agent_release_gate_promotion(
    target_level: str = Query(default="L3", pattern=r"^L[0-5]$"),
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    if project_id is not None:
        permission_service.require_project_access(current_user, project_id)
    elif not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for global Agent release assessment")
    AgentRuntimeService(db).ensure_backend_contracts()
    try:
        assessment = AgentReleaseGateService(db).promotion_assessment(
            target_level=target_level,
            project_id=project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return success(data=AgentReleaseGatePromotionRead.model_validate(assessment))


@router.get("/fault-injections", summary="查询 Agent 生产硬化故障注入清单")
def list_agent_fault_injection_cases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not PermissionService(db).is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for Agent fault injection catalog")
    cases = AgentFaultInjectionService(db).list_cases()
    return success(data=[AgentFaultInjectionCaseRead.model_validate(item) for item in cases])


@router.get("/fault-injections/coverage", summary="审计 Agent 故障注入覆盖率")
def audit_agent_fault_injection_coverage(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not PermissionService(db).is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for Agent fault injection coverage")
    coverage = AgentFaultInjectionCoverageService(db).audit()
    return success(data=AgentFaultInjectionCoverageRead.model_validate(coverage))


@router.post("/fault-injections/run", summary="执行 Agent 生产硬化故障注入")
def run_agent_fault_injections(
    payload: AgentFaultInjectionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    if not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for Agent fault injection")
    permission_service.require_project_access(current_user, payload.project_id)
    summary = AgentFaultInjectionService(db).run_cases(
        project_id=payload.project_id,
        case_ids=payload.case_ids,
        current_user=current_user,
    )
    return success(data=AgentFaultInjectionRunRead.model_validate(summary), message="Agent fault injection completed")


@router.get("/runbooks", summary="查询 Agent Runbook 目录")
def list_agent_runbooks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = (db, current_user)
    runbooks = AgentRunbookService(db).list_runbooks()
    return success(data=[AgentRunbookRead.model_validate(item) for item in runbooks])


@router.post("/runs", summary="鍒涘缓 Agent Run")
def create_agent_run(
    payload: AgentRunCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    runtime = AgentRuntimeService(db)
    run = runtime.create_run(payload=payload, current_user=current_user)
    if run.status not in RUN_TERMINAL_STATUSES and _should_start_agent_conversation_worker(db):
        submitted = execution_worker.submit(_run_agent_conversation, run.run_id, current_user.id)
        if not submitted:
            run = runtime.fail_run(
                run,
                error_code="agent_conversation_worker_queue_full",
                error_message="Agent conversation worker queue is full",
            )
    return success(data=AgentRunRead.model_validate(run), message="Agent run created")


@router.get("/runs", summary="查询 Agent Run 列表")
def list_agent_runs(
    project_id: int = Query(description="项目 ID"),
    conversation_id: str | None = Query(default=None, max_length=64),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation_id = _query_value(conversation_id)
    status_filter = _query_value(status_filter)
    limit = _query_value(limit, 50)
    runs = AgentRuntimeService(db).list_runs(
        project_id=project_id,
        conversation_id=conversation_id,
        status_filter=status_filter,
        limit=limit,
        current_user=current_user,
    )
    return success(data=[AgentRunRead.model_validate(run) for run in runs])


@router.get("/conversations", summary="查询 Agent Conversation 列表")
def list_agent_conversations(
    project_id: int = Query(description="项目 ID"),
    search: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    search = _query_value(search)
    limit = _query_value(limit, 50)
    conversations = AgentRuntimeService(db).list_conversations(
        project_id=project_id,
        search=search,
        limit=limit,
        current_user=current_user,
    )
    return success(data=[AgentConversationRead.model_validate(item) for item in conversations])


@router.get("/conversations/{conversation_id}/runs", summary="查询 Agent Conversation 下的 Run")
def list_agent_conversation_runs(
    conversation_id: str,
    project_id: int = Query(description="项目 ID"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = _query_value(limit, 50)
    runs = AgentRuntimeService(db).list_runs(
        project_id=project_id,
        conversation_id=conversation_id,
        limit=limit,
        current_user=current_user,
    )
    return success(data=[AgentRunRead.model_validate(run) for run in runs])


@router.get("/conversations/{conversation_id}/transcript", summary="查询 Agent Conversation Transcript")
def get_agent_conversation_transcript(
    conversation_id: str,
    project_id: int = Query(description="项目 ID"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = _query_value(limit, 100)
    transcript = AgentRuntimeService(db).get_conversation_transcript(
        project_id=project_id,
        conversation_id=conversation_id,
        limit=limit,
        current_user=current_user,
    )
    return success(data=AgentConversationTranscriptRead.model_validate(transcript))


@router.get("/conversations/{conversation_id}/export", summary="导出 Agent Conversation 调试包")
def export_agent_conversation(
    conversation_id: str,
    project_id: int = Query(description="项目 ID"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = _query_value(limit, 100)
    export_payload = AgentRuntimeService(db).export_conversation(
        project_id=project_id,
        conversation_id=conversation_id,
        limit=limit,
        current_user=current_user,
    )
    return success(data=AgentConversationExportRead.model_validate(export_payload))


@router.get("/runs/{run_id}/summary", summary="查询 Agent Run 聚合摘要")
def get_agent_run_summary(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    summary = AgentRuntimeService(db).get_run_summary(run_id=run_id, current_user=current_user)
    return success(data=AgentRunSummaryRead.model_validate(summary))


@router.get("/runs/{run_id}/actions", summary="查询 Agent Run 可执行操作状态")
def get_agent_run_actions(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    action_state = AgentRuntimeService(db).get_run_action_state(run_id=run_id, current_user=current_user)
    return success(data=AgentRunActionStateRead.model_validate(action_state))


@router.get("/runs/{run_id}", summary="鏌ヨ Agent Run")
def get_agent_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = AgentRuntimeService(db).get_run(run_id=run_id, current_user=current_user)
    return success(data=AgentRunRead.model_validate(run))


@router.get("/runs/{run_id}/runbook", summary="诊断 Agent Run 并返回 Runbook 建议")
def diagnose_agent_runbook(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    diagnosis = AgentRunbookService(db).diagnose_run(run_id=run_id, current_user=current_user)
    return success(data=AgentRunbookDiagnosisRead.model_validate(diagnosis))


@router.post("/runs/{run_id}/cancel", summary="鍙栨秷 Agent Run")
def cancel_agent_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = AgentRuntimeService(db).cancel_run(run_id=run_id, current_user=current_user)
    return success(data=AgentRunRead.model_validate(run), message="Agent run cancelled")


@router.post("/runs/{run_id}/reconcile", summary="瑙﹀彂 Agent Run Reconcile")
def reconcile_agent_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = ReconcileWorker(db).reconcile_run(run_id=run_id, current_user=current_user)
    return success(data=AgentRunReconcileRead.model_validate(result), message="Agent run reconcile completed")


@router.post("/runs/{run_id}/resume", summary="恢复 Agent Run")
def resume_agent_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = AgentRunResumeService(db).resume_run(run_id=run_id, current_user=current_user)
    return success(
        data=AgentRunResumeRead(
            run=AgentRunRead.model_validate(result["run"]),
            resumed=result["resumed"],
            checkpoint_freshness=result["checkpoint_freshness"],
            scheduled_tool_call_ids=result["scheduled_tool_call_ids"],
            executed_tool_call_ids=result.get("executed_tool_call_ids", []),
            observed_tool_call_ids=result.get("observed_tool_call_ids", []),
        ),
        message="Agent run resume checked",
    )


@router.get("/runs/{run_id}/migration-blocks", summary="鏌ヨ Agent Run Migration Blocks")
def list_agent_migration_blocks(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    blocks = MigrationCoordinator(db).list_blocks(run_id=run_id, current_user=current_user)
    return success(data=[AgentMigrationBlockRead.model_validate(item) for item in blocks])


@router.post("/runs/{run_id}/migration-blocks/{block_id}/resolve", summary="瑙ｅ喅 Agent Migration Block")
def resolve_agent_migration_block(
    run_id: str,
    block_id: str,
    payload: AgentMigrationBlockResolveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    block, freshness = MigrationCoordinator(db).resolve_block(
        run_id=run_id,
        block_id=block_id,
        current_user=current_user,
        resolution_note=payload.resolution_note,
    )
    return success(
        data=AgentMigrationBlockResolveRead(
            block=AgentMigrationBlockRead.model_validate(block),
            checkpoint_freshness=freshness,
        ),
        message="Agent migration block resolved",
    )


@router.get("/runs/{run_id}/approvals", summary="查询 Agent Run 审批")
def list_agent_run_approvals(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    approvals = ApprovalService(db).list_run_approvals(run_id=run_id, current_user=current_user)
    return success(data=[AgentApprovalRead.model_validate(item) for item in approvals])


@router.post("/runs/{run_id}/context-builds", summary="鍒涘缓 Agent Context Build")
def create_agent_context_build(
    run_id: str,
    payload: AgentContextBuildCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    build = ContextBuilder(db).build(run_id=run_id, payload=payload, current_user=current_user)
    return success(data=AgentContextBuildRead.model_validate(build), message="Agent context build created")


@router.get("/runs/{run_id}/context-builds", summary="鏌ヨ Agent Context Builds")
def list_agent_context_builds(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    AgentRuntimeService(db).get_run(run_id=run_id, current_user=current_user)
    builds = list(db.scalars(
        select(AgentContextBuild)
        .where(AgentContextBuild.run_id == run_id)
        .order_by(AgentContextBuild.iteration.asc(), AgentContextBuild.step_index.asc(), AgentContextBuild.build_seq.asc())
    ).all())
    return success(data=[AgentContextBuildRead.model_validate(item) for item in builds])


@router.post("/runs/{run_id}/loop-observations", summary="璁板綍 Agent Loop Observation")
def create_agent_loop_observation(
    run_id: str,
    payload: AgentLoopObservationCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    observation = LoopController(db).record_observation(run_id=run_id, payload=payload, current_user=current_user)
    return success(data=AgentLoopObservationRead.model_validate(observation), message="Agent loop observation recorded")


@router.get("/runs/{run_id}/loop-observations", summary="鏌ヨ Agent Loop Observations")
def list_agent_loop_observations(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    AgentRuntimeService(db).get_run(run_id=run_id, current_user=current_user)
    observations = list(db.scalars(
        select(AgentLoopObservation)
        .where(AgentLoopObservation.run_id == run_id)
        .order_by(AgentLoopObservation.iteration.asc(), AgentLoopObservation.step_index.asc(), AgentLoopObservation.created_at.asc())
    ).all())
    return success(data=[AgentLoopObservationRead.model_validate(item) for item in observations])


@router.get("/memories", summary="查询 Agent Memories")
def list_agent_memories(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ApprovalService(db).policy_manager.permission_service.require_project_access(current_user, project_id)
    memories = list(db.scalars(
        select(ProjectMemory)
        .where(ProjectMemory.project_id == project_id)
        .order_by(ProjectMemory.updated_at.desc())
    ).all())
    return success(data=[AgentMemoryRead.model_validate(item) for item in memories])


@router.post("/memories", summary="创建 Agent Memory")
def create_agent_memory(
    payload: AgentMemoryCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    memory = MemoryManager(db).create_memory(
        project_id=payload.project_id,
        memory_type=payload.memory_type,
        title=payload.title,
        content=payload.content,
        source_type=payload.source_type,
        source_ref_json=payload.source_ref_json,
        evidence_refs=payload.evidence_refs,
        current_user=current_user,
    )
    return success(data=AgentMemoryRead.model_validate(memory), message="Agent memory created")


@router.patch("/memories/{memory_id}", summary="更新 Agent Memory")
def update_agent_memory(
    memory_id: int,
    payload: AgentMemoryUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    memory = MemoryManager(db).update_memory(
        memory_id=memory_id,
        memory_type=payload.memory_type,
        title=payload.title,
        content=payload.content,
        source_ref_json=payload.source_ref_json,
        evidence_refs=payload.evidence_refs,
        status_value=payload.status,
        reason=payload.reason,
        current_user=current_user,
    )
    return success(data=AgentMemoryRead.model_validate(memory), message="Agent memory updated")


@router.post("/memories/{memory_id}/validate", summary="验证 Agent Memory")
def validate_agent_memory(
    memory_id: int,
    payload: AgentMemoryDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    memory = MemoryManager(db).validate_memory(
        memory_id=memory_id,
        reason=payload.reason,
        current_user=current_user,
    )
    return success(data=AgentMemoryRead.model_validate(memory), message="Agent memory validated")


@router.post("/memories/{memory_id}/reject", summary="拒绝 Agent Memory")
def reject_agent_memory(
    memory_id: int,
    payload: AgentMemoryDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    memory = MemoryManager(db).reject_memory(
        memory_id=memory_id,
        reason=payload.reason,
        current_user=current_user,
    )
    return success(data=AgentMemoryRead.model_validate(memory), message="Agent memory rejected")


@router.post("/memories/retrieve", summary="检索 Agent Memories")
def retrieve_agent_memories(
    payload: AgentMemoryRetrieveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    candidates = MemoryManager(db).retrieve(
        project_id=payload.project_id,
        query=payload.query,
        profile_name=payload.profile_name,
        task_risk=payload.task_risk,
        usage_role=payload.usage_role,
        current_user=current_user,
        run_id=payload.run_id,
        step_index=payload.step_index,
        limit=payload.limit,
    )
    return success(data=[AgentMemoryCandidateRead(**memory_candidate_to_payload(item)) for item in candidates])


@router.get("/memory-source-profiles", summary="查询 Agent Memory Source Profiles")
def list_agent_memory_source_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    MemorySourceProfileResolver(db).ensure_defaults()
    db.commit()
    profiles = list(db.scalars(select(AgentMemorySourceProfile).order_by(AgentMemorySourceProfile.source_type.asc())).all())
    return success(data=[AgentMemorySourceProfileRead.model_validate(item) for item in profiles])


@router.get("/memory-retrieval-profiles", summary="查询 Agent Memory Retrieval Profiles")
def list_agent_memory_retrieval_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    MemoryRetrievalProfileResolver(db).ensure_defaults()
    db.commit()
    profiles = list(db.scalars(select(AgentMemoryRetrievalProfile).order_by(AgentMemoryRetrievalProfile.profile_name.asc())).all())
    return success(data=[AgentMemoryRetrievalProfileRead.model_validate(item) for item in profiles])


@router.get("/memory-usage-events", summary="查询 Agent Memory Usage Events")
def list_agent_memory_usage_events(
    run_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    statement = select(AgentMemoryUsageEvent).order_by(AgentMemoryUsageEvent.created_at.desc())
    if run_id:
        AgentRuntimeService(db).get_run(run_id=run_id, current_user=current_user)
        statement = statement.where(AgentMemoryUsageEvent.run_id == run_id)
    elif not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for global Agent memory usage events")
    events = list(db.scalars(statement.limit(100)).all())
    return success(data=[AgentMemoryUsageEventRead.model_validate(item) for item in events])


@router.get("/memory-staleness-events", summary="查询 Agent Memory Staleness Events")
def list_agent_memory_staleness_events(
    project_id: int | None = None,
    memory_id: int | None = None,
    evidence_ref_type: str | None = None,
    evidence_ref_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    statement = select(AgentMemoryStalenessEvent).order_by(AgentMemoryStalenessEvent.created_at.desc())
    if memory_id is not None:
        memory = db.get(ProjectMemory, memory_id)
        if memory is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent memory not found")
        permission_service.require_project_access(current_user, memory.project_id)
        statement = statement.where(AgentMemoryStalenessEvent.memory_id == memory_id)
    elif project_id is not None:
        permission_service.require_project_access(current_user, project_id)
        statement = statement.where(AgentMemoryStalenessEvent.project_id == project_id)
    elif not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for global Agent memory staleness events")
    if evidence_ref_type is not None:
        statement = statement.where(AgentMemoryStalenessEvent.evidence_ref_type == evidence_ref_type)
    if evidence_ref_id is not None:
        statement = statement.where(AgentMemoryStalenessEvent.evidence_ref_id == evidence_ref_id)
    events = list(db.scalars(statement.limit(limit)).all())
    return success(data=[AgentMemoryStalenessEventRead.model_validate(item) for item in events])


@router.get("/memory-validation-events", summary="查询 Agent Memory Validation Events")
def list_agent_memory_validation_events(
    project_id: int | None = None,
    memory_id: int | None = None,
    validation_source: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    permission_service = PermissionService(db)
    statement = select(AgentMemoryValidationEvent).order_by(AgentMemoryValidationEvent.created_at.desc())
    if memory_id is not None:
        memory = db.get(ProjectMemory, memory_id)
        if memory is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent memory not found")
        permission_service.require_project_access(current_user, memory.project_id)
        statement = statement.where(AgentMemoryValidationEvent.memory_id == memory_id)
    elif project_id is not None:
        permission_service.require_project_access(current_user, project_id)
        statement = statement.where(AgentMemoryValidationEvent.project_id == project_id)
    elif not permission_service.is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for global Agent memory validation events")
    if validation_source is not None:
        statement = statement.where(AgentMemoryValidationEvent.validation_source == validation_source)
    events = list(db.scalars(statement.limit(limit)).all())
    return success(data=[AgentMemoryValidationEventRead.model_validate(item) for item in events])


@router.post("/memory-usage-events/{usage_event_id}/feedback", summary="提交 Agent Memory 使用反馈")
def record_agent_memory_usage_feedback(
    usage_event_id: int,
    payload: AgentMemoryFeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    summary = MemoryFeedbackWorker(db).record_usage_feedback(
        usage_event_id=usage_event_id,
        outcome=payload.outcome,
        caused_tool_input_change=payload.caused_tool_input_change,
        failure_fingerprint=payload.failure_fingerprint,
        contradiction_type=payload.contradiction_type,
        severity=payload.severity,
        reason=payload.reason,
        current_user=current_user,
    )
    return success(data=AgentMemoryFeedbackProcessRead.model_validate(summary), message="Agent memory feedback processed")


@router.post("/memory-feedback/process", summary="处理待消费 Agent Memory Feedback")
def process_agent_memory_feedback(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not PermissionService(db).is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required for Agent memory feedback processing")
    summary = MemoryFeedbackWorker(db).process_due(limit=limit)
    return success(data=AgentMemoryFeedbackProcessRead.model_validate(summary), message="Agent memory feedback processed")


@router.get("/runs/{run_id}/events", summary="璁㈤槄 Agent Run 浜嬩欢")
def stream_agent_run_events(
    run_id: str,
    last_event_id: int = Header(default=0, alias="Last-Event-ID", ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    AgentRuntimeService(db).get_run(run_id=run_id, current_user=current_user)

    def event_stream():
        sequence = last_event_id
        heartbeat_at = time.monotonic()
        while True:
            with SessionLocal() as event_db:
                events, run = AgentRuntimeService(event_db).list_events(
                    run_id=run_id,
                    after_sequence=sequence,
                )
                run_status = run.status
                last_sequence = run.last_event_sequence

            for item in events:
                sequence = item.event_seq
                event_payload = dict(item.payload_json)
                event_payload["item_id"] = item.item_id
                yield (
                    f"id: {item.event_seq}\n"
                    f"event: {item.event_type}\n"
                    f"data: {json.dumps(event_payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
                )
                heartbeat_at = time.monotonic()

            if run_status in RUN_TERMINAL_STATUSES and sequence >= last_sequence:
                return
            if time.monotonic() - heartbeat_at >= AGENT_SSE_HEARTBEAT_INTERVAL_SECONDS:
                yield "event: heartbeat\ndata: {}\n\n"
                heartbeat_at = time.monotonic()
            if run_status in {"queued", "running"}:
                time.sleep(AGENT_SSE_ACTIVE_POLL_INTERVAL_SECONDS)
            else:
                time.sleep(AGENT_SSE_IDLE_POLL_INTERVAL_SECONDS)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/runs/{run_id}/events/snapshot", summary="查询 Agent Run 事件快照")
def get_agent_run_event_snapshot(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    snapshot = AgentRuntimeService(db).get_event_snapshot(
        run_id=run_id,
        after_sequence=after_sequence,
        limit=limit,
        current_user=current_user,
    )
    return success(data=AgentRunEventSnapshotRead.model_validate(snapshot))


@router.get("/runs/{run_id}/events/replay-audit", summary="审计 Agent Run EventStore/SSE 重放连续性")
def audit_agent_run_event_replay(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    AgentRuntimeService(db).get_run(run_id=run_id, current_user=current_user)
    audit = AgentEventReplayAuditService(db).audit_run(run_id=run_id, after_sequence=after_sequence)
    return success(data=AgentEventReplayAuditRead.model_validate(audit))


@router.get("/runtime-snapshots/{snapshot_id}", summary="鏌ヨ Agent Runtime Snapshot")
def get_agent_runtime_snapshot(
    snapshot_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    snapshot = AgentRuntimeService(db).get_snapshot(snapshot_id=snapshot_id, current_user=current_user)
    return success(data=AgentRuntimeSnapshotRead.model_validate(snapshot))


@router.get("/tool-calls/{tool_call_id}", summary="鏌ヨ Agent ToolCall")
def get_agent_tool_call(
    tool_call_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    call = ExecutionLedgerService(db).get_tool_call(tool_call_id=tool_call_id, current_user=current_user)
    approval_service = ApprovalService(db)
    current_approval = approval_service.get_current_approval(tool_call_id=tool_call_id)
    lineage = approval_service.get_lineage(approval_lineage_id=call.approval_lineage_id)
    attempts = list(db.scalars(
        select(AgentReconcileAttempt)
        .where(AgentReconcileAttempt.tool_call_id == tool_call_id)
        .order_by(AgentReconcileAttempt.attempt_seq.desc())
        .limit(5)
    ).all())
    payload = AgentToolCallRead.model_validate(call).model_copy(
        update={
            "current_approval": AgentApprovalRead.model_validate(current_approval) if current_approval else None,
            "approval_lineage": AgentApprovalLineageRead.model_validate(lineage) if lineage else None,
            "recent_reconcile_attempts": [
                AgentReconcileAttemptRead.model_validate(item)
                for item in attempts
            ]
        }
    )
    return success(data=payload)


@router.post("/tool-calls/{tool_call_id}/approve", summary="瀹℃壒 Agent ToolCall")
def approve_agent_tool_call(
    tool_call_id: str,
    payload: AgentApprovalDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    approval, lineage, call, mutation = ApprovalService(db).approve(
        tool_call_id=tool_call_id,
        payload=payload,
        current_user=current_user,
    )
    data = AgentApprovalDecisionRead(
        approval=AgentApprovalRead.model_validate(approval),
        lineage=AgentApprovalLineageRead.model_validate(lineage),
        tool_call=AgentToolCallRead.model_validate(call),
        mutation_log=AgentApprovalMutationLogRead.model_validate(mutation),
    )
    return success(data=data, message="Agent ToolCall approval approved")


@router.post("/tool-calls/{tool_call_id}/reject", summary="鎷掔粷 Agent ToolCall")
def reject_agent_tool_call(
    tool_call_id: str,
    payload: AgentApprovalDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    approval, lineage, call, mutation = ApprovalService(db).reject(
        tool_call_id=tool_call_id,
        payload=payload,
        current_user=current_user,
    )
    data = AgentApprovalDecisionRead(
        approval=AgentApprovalRead.model_validate(approval),
        lineage=AgentApprovalLineageRead.model_validate(lineage),
        tool_call=AgentToolCallRead.model_validate(call),
        mutation_log=AgentApprovalMutationLogRead.model_validate(mutation),
    )
    return success(data=data, message="Agent ToolCall approval rejected")
