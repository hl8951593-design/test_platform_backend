import json
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.response import success
from app.db.session import SessionLocal
from app.models.agent import (
    AgentBackendContract,
    AgentContextBuild,
    AgentLoopObservation,
    AgentMemoryRetrievalProfile,
    AgentMemorySourceProfile,
    AgentMemoryUsageEvent,
    AgentReconcileAttempt,
    ProjectMemory,
)
from app.models.user import User
from app.schemas.agent import (
    AgentApprovalDecisionRead,
    AgentApprovalDecisionRequest,
    AgentApprovalLineageRead,
    AgentApprovalMutationLogRead,
    AgentApprovalRead,
    AgentCapabilitiesRead,
    AgentContextBuildCreateRequest,
    AgentContextBuildRead,
    AgentFaultInjectionCaseRead,
    AgentFaultInjectionRequest,
    AgentFaultInjectionRunRead,
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
    AgentMemoryUpdateRequest,
    AgentMemoryUsageEventRead,
    AgentMetricsSnapshotRead,
    AgentMigrationBlockRead,
    AgentMigrationBlockResolveRead,
    AgentMigrationBlockResolveRequest,
    AgentOutboxPublishRead,
    AgentReleaseGateRead,
    AgentReconcileAttemptRead,
    AgentRunCreateRequest,
    AgentRunbookDiagnosisRead,
    AgentRunbookRead,
    AgentRunReconcileRead,
    AgentRunRead,
    AgentRunResumeRead,
    AgentRuntimeSnapshotRead,
    AgentToolCallRead,
)
from app.services.agent_approval_service import ApprovalService
from app.services.agent_fault_injection_service import AgentFaultInjectionService
from app.services.agent_loop_service import ContextBuilder, LoopController
from app.services.agent_memory_service import (
    MemoryFeedbackWorker,
    MemoryManager,
    MemoryRetrievalProfileResolver,
    MemorySourceProfileResolver,
)
from app.services.agent_observability_service import AgentMetricsService, AgentOutboxPublisher
from app.services.agent_reconcile_service import MigrationCoordinator, ReconcileWorker
from app.services.agent_release_gate_service import AgentReleaseGateService
from app.services.agent_resume_service import AgentRunResumeService
from app.services.agent_runbook_service import AgentRunbookService
from app.services.agent_runtime_service import AgentRuntimeService, ExecutionLedgerService, RUN_TERMINAL_STATUSES
from app.services.permission_service import PermissionService

router = APIRouter()


@router.get("/capabilities", summary="鏌ヨ Agent Runtime 鑳藉姏")
def get_agent_capabilities(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = (db, current_user)
    return success(data=AgentCapabilitiesRead.model_validate(AgentRuntimeService(db).capabilities()))


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
    _ = current_user
    AgentRuntimeService(db).ensure_backend_contracts()
    contract = db.scalar(
        select(AgentBackendContract).where(
            AgentBackendContract.backend_name == backend_name,
            AgentBackendContract.backend_operation == backend_operation,
            AgentBackendContract.backend_contract_version == backend_contract_version,
        )
    )
    if contract is None:
        from fastapi import HTTPException, status

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
    _ = current_user
    AgentRuntimeService(db).ensure_backend_contracts()
    snapshot = AgentReleaseGateService(db).snapshot()
    return success(data=AgentReleaseGateRead.model_validate(snapshot))


@router.get("/fault-injections", summary="查询 Agent P0 故障注入清单")
def list_agent_fault_injection_cases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = (db, current_user)
    cases = AgentFaultInjectionService(db).list_cases()
    return success(data=[AgentFaultInjectionCaseRead.model_validate(item) for item in cases])


@router.post("/fault-injections/run", summary="执行 Agent P0 故障注入")
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
    run = AgentRuntimeService(db).create_run(payload=payload, current_user=current_user)
    return success(data=AgentRunRead.model_validate(run), message="Agent run created")


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
    return success(data=[AgentMemoryCandidateRead(**item.__dict__) for item in candidates])


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
    statement = select(AgentMemoryUsageEvent).order_by(AgentMemoryUsageEvent.created_at.desc())
    if run_id:
        AgentRuntimeService(db).get_run(run_id=run_id, current_user=current_user)
        statement = statement.where(AgentMemoryUsageEvent.run_id == run_id)
    events = list(db.scalars(statement.limit(100)).all())
    return success(data=[AgentMemoryUsageEventRead.model_validate(item) for item in events])


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
                yield (
                    f"id: {item.event_seq}\n"
                    f"event: {item.event_type}\n"
                    f"data: {json.dumps(item.payload_json, ensure_ascii=False, separators=(',', ':'))}\n\n"
                )
                heartbeat_at = time.monotonic()

            if run_status in RUN_TERMINAL_STATUSES and sequence >= last_sequence:
                return
            if time.monotonic() - heartbeat_at >= 15:
                yield "event: heartbeat\ndata: {}\n\n"
                heartbeat_at = time.monotonic()
            time.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
