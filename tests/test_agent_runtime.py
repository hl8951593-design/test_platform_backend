import unittest
import tempfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db.base import Base
from app.models.agent import (
    AgentApproval,
    AgentApprovalLineage,
    AgentApprovalMutationLog,
    AgentBackendContract,
    AgentCheckpoint,
    AgentContextBuild,
    AgentEvidenceWatch,
    AgentEvent,
    AgentLoopObservation,
    AgentMemoryRetrievalProfile,
    AgentMemorySourceProfile,
    AgentMemoryContradictionEvent,
    AgentMemoryStalenessEvent,
    AgentMemoryUsageEvent,
    AgentMemoryValidationEvent,
    AgentMemoryEvidenceLink,
    AgentMigrationBlock,
    AgentOutbox,
    AgentReconcileAttempt,
    AgentRootCauseRule,
    AgentRun,
    AgentRuntimeSnapshot,
    AgentToolCall,
    AgentWorkerQueue,
    ProjectMemory,
)
from app.models.project import Project, ProjectMember, ProjectMemberPermission
from app.models.user import User
from app.schemas.agent import (
    AgentAlertRead,
    AgentAlertSnapshotRead,
    AgentApprovalRead,
    AgentApprovalDecisionRequest,
    AgentApprovalExpireAuditRead,
    AgentContextBuildCreateRequest,
    AgentContextBuildRead,
    AgentConversationExportRead,
    AgentConversationRead,
    AgentConversationSmokeRead,
    AgentConversationSmokeRequest,
    AgentConversationTranscriptRead,
    AgentDashboardCheckRead,
    AgentEventRead,
    AgentEventReplayAuditRead,
    AgentEventReplayStressAuditRead,
    AgentFaultInjectionCaseRead,
    AgentFaultInjectionCoverageRead,
    AgentFaultInjectionResultRead,
    AgentFaultInjectionRunRead,
    AgentBackendCompletionAuditRead,
    AgentLaunchAuditRead,
    AgentLoopObservationCreateRequest,
    AgentLoopObservationRead,
    AgentMemoryCandidateRead,
    AgentMemoryCreateRequest,
    AgentMemoryDecisionRequest,
    AgentMemoryFeedbackProcessRead,
    AgentMemoryRead,
    AgentMemoryRetrievalProfileRead,
    AgentMemoryRetrieveRequest,
    AgentMemorySourceProfileRead,
    AgentMemoryStalenessEventRead,
    AgentMemoryUpdateRequest,
    AgentMemoryUsageEventRead,
    AgentMemoryValidationEventRead,
    AgentMigrationBlockResolveRequest,
    AgentMetricsSnapshotRead,
    AgentModelHealthRead,
    AgentOutboxPublishRead,
    AgentReadinessDashboardRead,
    AgentRunActionRead,
    AgentRunActionStateRead,
    AgentRunCreateRequest,
    AgentRunEventSnapshotRead,
    AgentRunRead,
    AgentRunSummaryRead,
    AgentRuntimeSnapshotRead,
    AgentToolCallCreateRequest,
    AgentToolCallRead,
    ReconcileResult,
    AgentApprovalExpireProcessRead,
    AgentReleaseGateLevelRead,
    AgentReleaseGateRead,
    AgentReleaseGatePromotionRead,
    AgentReleaseGateToolRead,
    AgentReleaseGateViolationRead,
    AgentRunbookRead,
    AgentRunbookDiagnosisRead,
    AgentRunbookRecommendationRead,
    AgentWorkerQueueAuditRead,
)
from app.schemas.ai import AIChatResponse
from app.services.agent_approval_service import (
    APPROVAL_CONFLICT_ERROR_CODES,
    APPROVAL_EVENT_TYPES,
    APPROVAL_EXPIRE_AUDIT_FIELDS,
    APPROVAL_EXPIRE_DERIVED_FROM_FIELDS,
    APPROVAL_EXPIRE_PROCESS_FIELDS,
    APPROVAL_FINAL_STATUSES,
    APPROVAL_IMMUTABLE_FIELDS,
    APPROVAL_MUTATION_TYPES,
    APPROVABLE_TOOL_CALL_STATUSES,
    SUPERSEDE_BLOCKED_TOOL_CALL_STATUSES,
    ApprovalExpireScanner,
    ApprovalService,
    PolicyManager,
)
from app.services.agent_fault_injection_service import (
    AgentFaultInjectionService,
    FAULT_INJECTION_CASE_FIELDS,
    FAULT_INJECTION_RESULT_FIELDS,
    FAULT_INJECTION_RUN_FIELDS,
)
from app.services.agent_loop_service import (
    ACTIVE_POLICY_DEPENDENCY_ROLES,
    AUDIT_DEPENDENCY_ROLES,
    CONTEXT_BUILD_FIELDS,
    ContextBuilder,
    DEFAULT_EVIDENCE_DEPENDENCY_ROLE,
    DEFAULT_EVIDENCE_MUTABILITY_CLASS,
    EVIDENCE_DEPENDENCY_ROLES,
    EVIDENCE_FRESHNESS_POLICIES,
    EVIDENCE_MUTABILITY_CLASSES,
    EvidenceRefResolver,
    EvidenceWatchService,
    FROZEN_MUTABILITY_CLASSES,
    LOOP_OBSERVATION_FIELDS,
    LoopController,
    ROOT_CAUSE_ACCEPTED_UNKNOWN_RULE_ID,
    ROOT_CAUSE_DEFAULT_RULE_CONTRACT,
    ROOT_CAUSE_FALLBACK_RULE_ID,
    ROOT_CAUSE_GOVERNANCE_FIELDS,
    ROOT_CAUSE_MISSING_RULE_METRIC,
    ROOT_CAUSE_NEW_RULE_REQUIRED_FIXTURE_COUNT,
    ROOT_CAUSE_PRIORITY_BANDS,
    RootCauseRuleEngine,
    VOLATILE_MUTABILITY_CLASSES,
)
from app.services.agent_memory_service import (
    MEMORY_CANDIDATE_EVIDENCE_REF_FIELDS,
    MEMORY_CANDIDATE_FIELDS,
    MEMORY_ENTITY_FIELDS,
    MEMORY_FEEDBACK_PROCESS_FIELDS,
    MEMORY_FEEDBACK_RESULT_BASE_FIELDS,
    MEMORY_RETRIEVAL_PROFILE_FIELDS,
    MEMORY_SOURCE_PROFILE_FIELDS,
    MEMORY_STALENESS_EVENT_FIELDS,
    MEMORY_USAGE_EVENT_EVIDENCE_REF_FIELDS,
    MEMORY_USAGE_EVENT_FIELDS,
    MEMORY_VALIDATION_EVENT_FIELDS,
    MemoryEvidenceAdapter,
    MemoryFeedbackWorker,
    MemoryMaintenanceWorker,
    MemoryManager,
    MemoryRetrievalProfileResolver,
    MemorySourceProfileResolver,
    MemoryStalenessWorker,
    SEVERITY_MULTIPLIER,
    compute_contradiction_penalty,
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
    ALERT_ITEM_FIELDS,
    ALERT_SNAPSHOT_FIELDS,
    ALERT_STATUS_VALUES,
    ALERT_SUMMARY_FIELDS,
    AGENT_BACKEND_COMPLETION_AUDIT_CHECK_NAMES,
    AGENT_BACKEND_COMPLETION_AUDIT_FIELDS,
    AGENT_LAUNCH_AUDIT_CHECK_NAMES,
    AGENT_LAUNCH_AUDIT_FIELDS,
    DASHBOARD_CHECK_FIELDS,
    DASHBOARD_CHECK_NAMES,
    EVENT_REPLAY_AUDIT_FIELDS,
    EVENT_REPLAY_CURSOR_AUDIT_FIELDS,
    EVENT_REPLAY_DERIVED_FROM_FIELDS,
    EVENT_REPLAY_STRESS_AUDIT_FIELDS,
    EVENT_REPLAY_STRESS_RUN_FIELDS,
    FAULT_INJECTION_COVERAGE_FIELDS,
    METRICS_DERIVED_FROM_FIELDS,
    METRICS_SNAPSHOT_FIELDS,
    MONITORING_ALERT_BLOCKING_SEVERITIES,
    MONITORING_ALERTS_CLEAR_DETAIL_FIELDS,
    OUTBOX_PUBLISH_FIELDS,
    PROMOTION_DASHBOARD_SUMMARY_FIELDS,
    READINESS_DASHBOARD_FIELDS,
    READINESS_STATUS_VALUES,
    WORKER_QUEUE_AUDIT_FIELDS,
    WORKER_QUEUE_DERIVED_FROM_FIELDS,
    WORKER_QUEUE_DUPLICATE_ACTIVE_FIELDS,
    WORKER_QUEUE_EXPIRED_LEASE_FIELDS,
)
from app.services.agent_reconcile_service import (
    CheckpointFreshnessGate,
    ACTIVE_EVIDENCE_REVALIDATION_ACTIONS,
    ACTIVE_EVIDENCE_REVALIDATION_DETAIL_FIELDS,
    ACTIVE_EVIDENCE_REVALIDATION_FIELDS,
    ACTIVE_EVIDENCE_REVALIDATION_REASONS,
    ACTIVE_EVIDENCE_REVALIDATION_RESULT,
    ENVIRONMENT_FRESHNESS_ACTION,
    ENVIRONMENT_FRESHNESS_FIELDS,
    ENVIRONMENT_FRESHNESS_REASON,
    ENVIRONMENT_FRESHNESS_RESULT,
    PENDING_APPROVAL_DETAIL_FIELDS,
    PENDING_APPROVAL_DETAIL_STALE_REASONS,
    PENDING_APPROVAL_FRESHNESS_ACTION,
    PENDING_APPROVAL_FRESHNESS_FIELDS,
    PENDING_APPROVAL_FRESHNESS_REASONS,
    PENDING_APPROVAL_FRESHNESS_RESULT,
    MigrationCoordinator,
    PERMISSION_FRESHNESS_ACTION,
    PERMISSION_FRESHNESS_DETAIL_FIELDS,
    PERMISSION_FRESHNESS_FIELDS,
    PERMISSION_FRESHNESS_REASON,
    PERMISSION_FRESHNESS_RESULT,
    PERMISSION_FRESHNESS_TOOL_STATUSES,
    RECONCILE_BACKOFF_CAPABILITIES,
    RECONCILE_BACKOFF_EFFECT_STATES,
    RECONCILE_BACKOFF_RESULT_STATUSES,
    RECONCILE_DIRECT_MANUAL_RESULT_STATUSES,
    RECONCILE_ELIGIBLE_STATUSES,
    RECONCILE_MIGRATION_RESULT_STATUSES,
    RECONCILE_RESULT_ENVELOPE_FIELDS,
    RECONCILE_RESULT_STATUSES,
    RECONCILE_SCHEMA_SUPPORT_VALUES,
    RECONCILE_SKIPPED_BACKOFF_FIELDS,
    RECONCILE_STATE_DEPENDENT_RESULT_STATUSES,
    RECONCILE_SUCCESS_RESULT_STATUSES,
    RECONCILE_SUMMARY_FIELDS,
    RECONCILE_TERMINAL_FAILURE_RESULT_STATUSES,
    ReconcileWorker,
    RUNTIME_SNAPSHOT_FRESHNESS_ACTION,
    RUNTIME_SNAPSHOT_FRESHNESS_ERROR_CODE,
    RUNTIME_SNAPSHOT_FRESHNESS_FIELDS,
    RUNTIME_SNAPSHOT_FRESHNESS_REASONS,
    RUNTIME_SNAPSHOT_FRESHNESS_RESULT,
    STALE_EVIDENCE_WATCH_DETAIL_FIELDS,
)
from app.services.agent_release_gate_service import (
    AgentReleaseGateService,
    FINAL_DELIVERY_ARTIFACTS,
    FINAL_DELIVERY_CATEGORY_FIELDS,
    FINAL_DELIVERY_CHECK_FIELDS,
    FINAL_DELIVERY_EXTERNAL_SCOPE_CATEGORIES,
    FINAL_DELIVERY_FIELDS,
    GO_LIVE_GATE_CHECK_FIELDS,
    GO_LIVE_GATE_FIELDS,
    GO_LIVE_GATE_REQUIREMENTS,
    GO_LIVE_GATE_TIER_FIELDS,
    MINIMUM_GO_LIVE_CHECK_FIELDS,
    MINIMUM_GO_LIVE_FIELDS,
    MINIMUM_GO_LIVE_REQUIREMENTS,
    PROMOTION_ASSESSMENT_CHECKS,
    PROMOTION_ASSESSMENT_FIELDS,
    PROMOTION_ALREADY_UNLOCKED_CHECK_STATUS,
    PROMOTION_BLOCKER_FIELDS,
    PROMOTION_BLOCKER_SOURCES,
    PROMOTION_DECISION_VALUES,
    PROMOTION_RELEASE_GATE_FIELDS,
    RELEASE_GATE_FIELDS,
    RELEASE_GATE_LEVEL_FIELDS,
    RELEASE_GATE_ROLLOUT_DECISION_VALUES,
    RELEASE_GATE_TOOL_FIELDS,
    RELEASE_GATE_VIOLATION_FIELDS,
    RELEASE_GATE_VIOLATION_REASON,
)
from app.services.agent_resume_service import AgentRunResumeService
from app.services.agent_runbook_service import (
    CHECKPOINT_FRESHNESS_SAFE_ACTIONS,
    RUNBOOK_EXECUTION_CONTEXT_SUMMARY_FIELDS,
    RUNBOOK_DIAGNOSIS_FIELDS,
    RUNBOOK_DIAGNOSIS_RECOMMENDATION_RUNBOOK_IDS,
    RUNBOOK_FIELDS,
    RUNBOOK_RECOMMENDATION_FIELDS,
    RUNBOOK_RECOMMENDATION_OPTIONAL_FIELDS,
    RUNBOOK_RECOMMENDATION_REQUIRED_FIELDS,
    AgentRunbookService,
)
from app.services.agent_tool_result_policy import (
    DEFAULT_TOOL_RESULT_REPAIR_GUIDANCE,
    FINAL_RESPONSE_BUDGET_INSTRUCTION,
    ToolResultPolicy,
)
from app.services.agent_runtime_service import (
    AGENT_CONVERSATION_EXPORT_FIELDS,
    AGENT_CONVERSATION_FIELDS,
    AGENT_CONVERSATION_SMOKE_FIELDS,
    AGENT_CONVERSATION_TRANSCRIPT_FIELDS,
    AGENT_EVENT_FIELDS,
    AGENT_MODEL_HEALTH_FIELDS,
    AGENT_RUN_ACTION_FIELDS,
    AGENT_RUN_ACTION_STATE_FIELDS,
    AGENT_RUN_EVENT_SNAPSHOT_FIELDS,
    AGENT_RUN_FIELDS,
    AGENT_RUN_SUMMARY_FIELDS,
    RUNTIME_SNAPSHOT_FIELDS,
    TOOL_CALL_FIELDS,
    AgentConversationRunner,
    AgentModelHealthService,
    AgentRuntimeService,
    AgentWorkerQueueService,
    ExecutionLedgerService,
    ToolExecutor,
    _conversation_system_prompt,
    _intent_likely_requires_agent_tool,
    _required_tool_followup_rules_for_intent,
    _unsupported_capability_classifier_prompt,
    _unsupported_capability_guards_for_intent,
    _unsupported_capability_message,
)


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.owner = User(
            id=1,
            username="owner",
            account="owner",
            password_hash="x",
            phone="10000000001",
            email="owner@example.test",
            is_admin=False,
        )
        self.member = User(
            id=2,
            username="member",
            account="member",
            password_hash="x",
            phone="10000000002",
            email="member@example.test",
            is_admin=False,
        )
        self.admin = User(
            id=3,
            username="admin",
            account="admin",
            password_hash="x",
            phone="10000000003",
            email="admin@example.test",
            is_admin=True,
        )
        self.project = Project(id=10, name="Agent Project", description="demo", created_by_id=1)
        self.db.add_all([self.owner, self.member, self.admin, self.project])
        self.db.flush()
        member = ProjectMember(project_id=10, user_id=2, added_by_id=1, is_active=True)
        self.db.add(member)
        self.db.flush()
        self.db.add(ProjectMemberPermission(member_id=member.id, permission_code="project:view"))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_agent_migration_tables_are_declared(self):
        tables = set(inspect(self.db.bind).get_table_names())

        self.assertIn("ai_agent_runtime_snapshots", tables)
        self.assertIn("ai_agent_runs", tables)
        self.assertIn("ai_agent_events", tables)
        self.assertIn("ai_agent_tool_calls", tables)
        self.assertIn("ai_agent_worker_queue", tables)
        self.assertIn("ai_agent_migration_blocks", tables)
        self.assertIn("ai_agent_approval_lineages", tables)
        self.assertIn("ai_agent_approvals", tables)
        self.assertIn("ai_agent_approval_mutation_logs", tables)
        self.assertIn("ai_agent_context_builds", tables)
        self.assertIn("ai_agent_loop_observations", tables)
        self.assertIn("ai_agent_evidence_watches", tables)
        self.assertIn("ai_agent_root_cause_rules", tables)
        self.assertIn("ai_project_memories", tables)
        self.assertIn("ai_agent_memory_source_profiles", tables)
        self.assertIn("ai_agent_memory_retrieval_profiles", tables)
        self.assertIn("ai_agent_memory_usage_events", tables)
        self.assertIn("ai_agent_memory_contradiction_events", tables)
        self.assertIn("ai_agent_memory_staleness_events", tables)
        self.assertIn("ai_agent_memory_validation_events", tables)
        self.assertIn("ai_agent_memory_evidence_links", tables)
        usage_columns = {item["name"] for item in inspect(self.db.bind).get_columns("ai_agent_memory_usage_events")}
        self.assertIn("feedback_state", usage_columns)
        self.assertIn("feedback_processed_at", usage_columns)
        self.assertIn("feedback_result_json", usage_columns)

    def test_create_run_freezes_snapshot_and_persists_events(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="组合登录后查询用户详情",
                auto_complete=True,
            ),
            current_user=self.owner,
        )

        events = list(self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all())
        self.assertEqual(run.status, "completed")
        self.assertTrue(run.runtime_snapshot_id.startswith("agent-snap-"))
        self.assertEqual(run.result_json["completion_source"], "smoke_auto_complete")
        self.assertFalse(run.result_json["model_invoked"])
        self.assertFalse(run.result_json["assistant_visible"])
        self.assertEqual([item.event_type for item in events], ["run.queued", "run.started", "run.completed"])
        self.assertEqual([item.event_seq for item in events], [1, 2, 3])

    def test_get_run_marks_stale_active_run_failed(self):
        runtime = AgentRuntimeService(self.db)
        run = runtime.create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="stale agent run"),
            current_user=self.owner,
        )
        stale_at = datetime.now().replace(tzinfo=None) - timedelta(hours=1)
        for event in self.db.scalars(select(AgentEvent).where(AgentEvent.run_id == run.run_id)).all():
            event.created_at = stale_at
        run.updated_at = stale_at
        self.db.commit()

        healed = AgentRuntimeService(self.db).get_run(run_id=run.run_id, current_user=self.member)
        events = list(
            self.db.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == run.run_id)
                .order_by(AgentEvent.event_seq.asc())
            ).all()
        )

        self.assertEqual(healed.status, "failed")
        self.assertEqual(healed.error_code, "agent_run_stale_worker_lost")
        self.assertEqual(events[-1].event_type, "run.failed")
        self.assertEqual(events[-1].event_seq, healed.last_event_sequence)
        self.assertEqual(events[-1].payload_json["error_code"], "agent_run_stale_worker_lost")

    def test_event_replay_resets_cursor_from_another_run(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="cursor reset", auto_complete=True),
            current_user=self.owner,
        )

        events, listed_run = AgentRuntimeService(self.db).list_events(
            run_id=run.run_id,
            after_sequence=9999,
        )
        snapshot = AgentRuntimeService(self.db).get_event_snapshot(
            run_id=run.run_id,
            after_sequence=9999,
            limit=10,
            current_user=self.member,
        )

        self.assertEqual(listed_run.run_id, run.run_id)
        self.assertEqual([item.event_seq for item in events], [1, 2, 3])
        self.assertEqual([item.event_type for item in events], ["run.queued", "run.started", "run.completed"])
        self.assertEqual(snapshot["after_sequence"], 0)
        self.assertEqual(snapshot["next_after_sequence"], 3)
        self.assertEqual([item.event_seq for item in snapshot["events"]], [1, 2, 3])
        self.assertTrue(snapshot["terminal"])

    def test_conversation_runner_streams_model_events_and_completes_run(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="你可以帮我做什么"),
            current_user=self.owner,
        )

        stream_events = [
            {"type": "delta", "content": "我可以"},
            {"type": "delta", "content": "帮你编排测试。"},
            {
                "type": "done",
                "finish_reason": "stop",
                "model": "deepseek-test",
                "usage": {"total_tokens": 12},
            },
        ]
        with patch("app.services.agent_runtime_service.AIService.chat_stream", return_value=iter(stream_events)):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        events = list(self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all())
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.result_json["message"], "我可以帮你编排测试。")
        self.assertEqual(
            [item.event_type for item in events],
            [
                "run.queued",
                "run.started",
                "model.started",
                "model.delta",
                "model.delta",
                "model.completed",
                "run.completed",
            ],
        )
        self.assertEqual(events[3].payload_json["content"], "我可以")
        self.assertEqual(events[5].payload_json["content"], "我可以帮你编排测试。")
        self.assertEqual(events[6].payload_json["result"]["model"], "deepseek-test")

    def test_conversation_runner_records_model_stream_retrying_event(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="retry before first token"),
            current_user=self.owner,
        )

        stream_events = [
            {
                "type": "retry",
                "attempt": 1,
                "max_retries": 2,
                "delay_seconds": 0.25,
                "error_message": "temporary EOF",
            },
            {"type": "delta", "content": "ok"},
            {"type": "done", "finish_reason": "stop", "model": "deepseek-test"},
        ]
        with patch("app.services.agent_runtime_service.AIService.chat_stream", return_value=iter(stream_events)):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        events = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )
        event_types = [item.event_type for item in events]

        self.assertEqual(completed.status, "completed")
        self.assertIn("model.stream_retrying", event_types)
        retry_event = next(item for item in events if item.event_type == "model.stream_retrying")
        self.assertEqual(retry_event.payload_json["attempt"], 1)
        self.assertEqual(retry_event.payload_json["max_retries"], 2)
        self.assertEqual(retry_event.payload_json["delay_seconds"], 0.25)
        self.assertEqual(retry_event.payload_json["error_message"], "temporary EOF")
        self.assertEqual(retry_event.payload_json["loop_step"], "assistant_response")

    def test_conversation_runner_allows_software_testing_general_answers_without_tools(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="边界值分析和等价类划分有什么区别？"),
            current_user=self.owner,
        )
        captured_messages = []

        def fake_stream(self, payload):
            captured_messages.extend(payload.messages)
            yield {"type": "delta", "content": "边界值分析关注输入边界附近，"}
            yield {"type": "delta", "content": "等价类划分关注把输入集合分组。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        system_prompt = "\n\n".join(message.content for message in captured_messages if message.role == "system")
        tool_calls = list(
            self.db.scalars(
                select(AgentToolCall).where(AgentToolCall.run_id == run.run_id)
            ).all()
        )
        events = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )
        started_event = next(item for item in events if item.event_type == "model.started")
        delta_event = next(item for item in events if item.event_type == "model.delta")
        completed_event = next(item for item in events if item.event_type == "model.completed")
        model_call_id = started_event.payload_json["model_call_id"]

        self.assertEqual(completed.status, "completed")
        self.assertEqual(
            completed.result_json["message"],
            "边界值分析关注输入边界附近，等价类划分关注把输入集合分组。",
        )
        self.assertEqual(tool_calls, [])
        self.assertEqual(started_event.payload_json["iteration_id"], f"{run.run_id}:iter-0")
        self.assertEqual(started_event.payload_json["loop_step"], "assistant_response")
        expected_loop_state = {
            "iteration": 0,
            "iteration_id": f"{run.run_id}:iter-0",
            "phase": "model",
            "step": "assistant_response",
            "model_call_id": model_call_id,
        }
        self.assertEqual(started_event.payload_json["loop_state"], expected_loop_state)
        self.assertEqual(delta_event.payload_json["loop_state"], expected_loop_state)
        self.assertEqual(completed_event.payload_json["loop_state"], expected_loop_state)
        self.assertEqual(delta_event.payload_json["model_call_id"], model_call_id)
        self.assertEqual(completed_event.payload_json["model_call_id"], model_call_id)
        self.assertEqual(completed.result_json["model_call_id"], model_call_id)
        self.assertIn('"name":"general-testing-answer"', system_prompt)
        self.assertIn("Agent Skill: general-testing-answer", system_prompt)
        self.assertIn("Answer software testing, test automation", system_prompt)
        self.assertIn("Do not call tools for conceptual explanations", system_prompt)
        self.assertIn("软件测试相关的通用问答、解释和建议可以直接回答", system_prompt)

    def test_conversation_runner_compacts_long_conversation_history_before_model_call(self):
        runtime = AgentRuntimeService(self.db)
        conversation_id = "agent-conv-long-history"
        for index in range(7):
            previous = runtime.create_run(
                payload=AgentRunCreateRequest(
                    project_id=10,
                    conversation_id=conversation_id,
                    intent=f"historical intent {index} " + ("input detail " * 220),
                ),
                current_user=self.owner,
            )
            runtime.complete_run(
                previous,
                {
                    "message": f"historical assistant {index} " + ("assistant detail " * 260),
                    "assistant_visible": True,
                },
                commit=True,
            )
        current = runtime.create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                conversation_id=conversation_id,
                intent="current compacted history question",
            ),
            current_user=self.owner,
        )
        captured_messages = []

        def fake_stream(service_self, payload):
            captured_messages.extend(payload.messages)
            yield {"type": "delta", "content": "ok"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream):
            AgentConversationRunner(self.db).run(run_id=current.run_id, user_id=self.owner.id)

        events = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == current.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )
        compaction_event = next(item for item in events if item.event_type == "context.history_compacted")
        system_contents = [message.content for message in captured_messages if message.role == "system"]

        self.assertTrue(any("Conversation history compacted for prompt budget." in item for item in system_contents))
        self.assertEqual(compaction_event.payload_json["strategy"], "summarize_older_keep_recent")
        self.assertIn("compacted_run_count", compaction_event.payload_json)
        self.assertIn("estimated_tokens_after", compaction_event.payload_json)
        self.assertIn("current compacted history question", captured_messages[-1].content)

    def test_conversation_runner_normalizes_user_visible_markdown_tables(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="生成场景组合说明"),
            current_user=self.owner,
        )
        malformed_markdown = (
            "- 环境：test\n\n"
            "| 步骤 | 名称 | 依赖关系 ||------|------|----------| "
            "| NODE-1 | 获取企业列表 | 起点 | "
            "| NODE-2 | 获取企业 CT 图像 | 依赖 NODE-1 |"
        )
        expected_markdown = (
            "- 环境：test\n\n"
            "| 步骤 | 名称 | 依赖关系 |\n"
            "| --- | --- | --- |\n"
            "| NODE-1 | 获取企业列表 | 起点 |\n"
            "| NODE-2 | 获取企业 CT 图像 | 依赖 NODE-1 |"
        )
        captured_messages = []

        def fake_stream(service_self, payload):
            captured_messages.extend(payload.messages)
            yield {"type": "delta", "content": malformed_markdown}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        events = list(self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all())
        completed_event = next(item for item in events if item.event_type == "model.completed")
        normalized_event = next(item for item in events if item.event_type == "model.markdown_normalized")
        system_prompt = "\n\n".join(item.content for item in captured_messages if item.role == "system")

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.result_json["message"], expected_markdown)
        self.assertEqual(completed_event.payload_json["content"], expected_markdown)
        self.assertEqual(normalized_event.payload_json["content"], expected_markdown)
        self.assertEqual(normalized_event.payload_json["model_call_id"], completed_event.payload_json["model_call_id"])
        self.assertTrue(normalized_event.payload_json["replace_content"])
        self.assertIn("GitHub Flavored Markdown", system_prompt)
        self.assertIn("表头、分隔行和每一条数据行都必须独占一行", system_prompt)

    def test_run_summary_aggregates_completed_conversation_for_inspector(self):
        from app.api.v1.routers.agents import get_agent_run_summary

        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="summary route"),
            current_user=self.owner,
        )
        stream_events = [
            {"type": "delta", "content": "summary "},
            {"type": "delta", "content": "ready"},
            {
                "type": "done",
                "finish_reason": "stop",
                "model": "deepseek-test",
                "usage": {"total_tokens": 9},
            },
        ]
        with patch("app.services.agent_runtime_service.AIService.chat_stream", return_value=iter(stream_events)):
            AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        payload = get_agent_run_summary(run_id=run.run_id, db=self.db, current_user=self.member)["data"]

        self.assertEqual(list(AgentRunSummaryRead.model_fields), list(AGENT_RUN_SUMMARY_FIELDS))
        self.assertEqual(list(payload), list(AGENT_RUN_SUMMARY_FIELDS))
        self.assertEqual(payload["run"]["run_id"], run.run_id)
        self.assertEqual(payload["assistant_message"], "summary ready")
        self.assertTrue(payload["assistant_visible"])
        self.assertIsNone(payload["completion_source"])
        self.assertTrue(payload["model_invoked"])
        self.assertEqual(payload["model"], "deepseek-test")
        self.assertEqual(payload["finish_reason"], "stop")
        self.assertEqual(payload["usage"], {"total_tokens": "***"})
        self.assertEqual(payload["event_count"], 7)
        self.assertEqual(payload["latest_event_sequence"], 7)
        self.assertEqual(payload["latest_event_types"][-2:], ["model.completed", "run.completed"])
        self.assertEqual(payload["tool_call_count"], 0)
        self.assertEqual(payload["pending_tool_call_count"], 0)
        self.assertEqual(payload["approval_count"], 0)
        self.assertEqual(payload["pending_approval_count"], 0)
        self.assertEqual(payload["migration_block_count"], 0)
        self.assertEqual(payload["open_migration_block_count"], 0)
        self.assertEqual(payload["memory_usage_count"], 0)
        self.assertEqual(payload["blocking_tool_call_ids"], [])
        self.assertTrue(payload["terminal"])
        self.assertFalse(payload["can_cancel"])
        self.assertFalse(payload["can_resume"])

    def test_run_summary_hides_smoke_auto_complete_as_assistant_reply(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="summary smoke", auto_complete=True),
            current_user=self.owner,
        )

        payload = AgentRunSummaryRead.model_validate(
            AgentRuntimeService(self.db).get_run_summary(run_id=run.run_id, current_user=self.member)
        ).model_dump()

        self.assertIsNone(payload["assistant_message"])
        self.assertFalse(payload["assistant_visible"])
        self.assertEqual(payload["completion_source"], "smoke_auto_complete")
        self.assertFalse(payload["model_invoked"])
        self.assertTrue(payload["terminal"])
        self.assertFalse(payload["can_cancel"])

    def test_run_summary_requires_project_access(self):
        outsider = User(
            id=4,
            username="outsider",
            account="outsider",
            password_hash="x",
            phone="10000000004",
            email="outsider@example.test",
            is_admin=False,
        )
        self.db.add(outsider)
        self.db.commit()
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="summary scope"),
            current_user=self.owner,
        )

        with self.assertRaises(HTTPException) as ctx:
            AgentRuntimeService(self.db).get_run_summary(run_id=run.run_id, current_user=outsider)

        self.assertEqual(ctx.exception.status_code, 403)

    def test_run_action_state_exposes_codex_controls_for_pending_approval(self):
        from app.api.v1.routers.agents import get_agent_run_actions

        run, call, approval = self._create_pending_approval()

        payload = get_agent_run_actions(run_id=run.run_id, db=self.db, current_user=self.member)["data"]
        actions = {item["action_id"]: item for item in payload["actions"]}

        self.assertEqual(list(AgentRunActionStateRead.model_fields), list(AGENT_RUN_ACTION_STATE_FIELDS))
        self.assertEqual(list(AgentRunActionRead.model_fields), list(AGENT_RUN_ACTION_FIELDS))
        self.assertEqual(list(payload), list(AGENT_RUN_ACTION_STATE_FIELDS))
        self.assertEqual(list(payload["actions"][0]), list(AGENT_RUN_ACTION_FIELDS))
        self.assertEqual(payload["run_summary"]["run"]["run_id"], run.run_id)
        self.assertIn("pending_approvals", payload["blocked_reasons"])
        self.assertIn("review_approvals", payload["primary_action_ids"])
        self.assertTrue(actions["review_approvals"]["enabled"])
        self.assertEqual(actions["review_approvals"]["resource_ids"], [approval.approval_id])
        self.assertFalse(actions["resume_run"]["enabled"])
        self.assertEqual(actions["resume_run"]["reason"], "pending_approvals_need_review")
        self.assertTrue(actions["cancel_run"]["enabled"])
        self.assertEqual(actions["review_approvals"]["details"]["pending_approval_count"], 1)
        self.assertEqual(actions["resume_run"]["details"]["blocking_tool_call_ids"], [call.tool_call_id])

    def test_run_action_state_exposes_reconcile_for_uncertain_tool_call(self):
        run = self._create_run("action state uncertain")
        call = self._create_uncertain_call(run.run_id, step_index=0)

        payload = AgentRunActionStateRead.model_validate(
            AgentRuntimeService(self.db).get_run_action_state(run_id=run.run_id, current_user=self.member)
        ).model_dump(mode="python")
        actions = {item["action_id"]: item for item in payload["actions"]}

        self.assertIn("uncertain_tool_calls", payload["blocked_reasons"])
        self.assertIn("reconcile_run", payload["primary_action_ids"])
        self.assertTrue(actions["reconcile_run"]["enabled"])
        self.assertEqual(actions["reconcile_run"]["resource_ids"], [call.tool_call_id])
        self.assertEqual(actions["reconcile_run"]["details"]["uncertain_tool_call_count"], 1)
        self.assertFalse(actions["resume_run"]["enabled"])
        self.assertEqual(actions["resume_run"]["reason"], "no_resume_candidate")

    def test_conversation_runner_writes_model_delta_before_stream_done(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="实时返回一段普通回复"),
            current_user=self.owner,
        )
        observed_mid_stream = {"delta_seen": False}

        def fake_stream(service_self, payload):
            yield {"type": "delta", "content": "第一段"}
            observed_mid_stream["delta_seen"] = self_db.scalar(
                select(AgentEvent).where(
                    AgentEvent.run_id == run.run_id,
                    AgentEvent.event_type == "model.delta",
                )
            ) is not None
            yield {"type": "delta", "content": "第二段"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        self_db = self.db
        with patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        events = list(self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all())

        self.assertEqual(completed.status, "completed")
        self.assertTrue(observed_mid_stream["delta_seen"])
        self.assertEqual(
            [item.event_type for item in events],
            [
                "run.queued",
                "run.started",
                "model.started",
                "model.delta",
                "model.delta",
                "model.completed",
                "run.completed",
            ],
        )
        self.assertEqual(events[3].payload_json["content"], "第一段")
        self.assertEqual(completed.result_json["message"], "第一段第二段")

    def test_conversation_runner_batches_small_model_deltas_after_first_visible_delta(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="实时返回很多小片段"),
            current_user=self.owner,
        )
        observed_mid_stream = {"delta_count_after_first": 0}
        tiny_chunks = [str(index % 10) for index in range(30)]

        def fake_stream(service_self, payload):
            _ = (service_self, payload)
            yield {"type": "delta", "content": "首段"}
            observed_mid_stream["delta_count_after_first"] = self_db.scalar(
                select(func.count())
                .select_from(AgentEvent)
                .where(
                    AgentEvent.run_id == run.run_id,
                    AgentEvent.event_type == "model.delta",
                )
            )
            for chunk in tiny_chunks:
                yield {"type": "delta", "content": chunk}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        self_db = self.db
        with patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        delta_events = list(
            self.db.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == run.run_id, AgentEvent.event_type == "model.delta")
                .order_by(AgentEvent.event_seq)
            ).all()
        )

        self.assertEqual(completed.status, "completed")
        self.assertEqual(observed_mid_stream["delta_count_after_first"], 1)
        self.assertLess(len(delta_events), 1 + len(tiny_chunks))
        self.assertEqual(delta_events[0].payload_json["content"], "首段")
        self.assertEqual(
            "".join(item.payload_json["content"] for item in delta_events),
            "首段" + "".join(tiny_chunks),
        )
        self.assertEqual(completed.result_json["message"], "首段" + "".join(tiny_chunks))

    def test_conversation_runner_compacts_suppressed_plain_text_stream_to_one_delta(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="读取当前项目后直接返回总结"),
            current_user=self.owner,
        )
        observed_mid_stream = {"delta_count": 0}
        chunks = ["这是", "一个", "较长", "总结", "片段", "。"]

        def fake_stream(service_self, payload):
            _ = (service_self, payload)
            for index, chunk in enumerate(chunks):
                yield {"type": "delta", "content": chunk}
                if index == 3:
                    observed_mid_stream["delta_count"] = self_db.scalar(
                        select(func.count())
                        .select_from(AgentEvent)
                        .where(
                            AgentEvent.run_id == run.run_id,
                            AgentEvent.event_type == "model.delta",
                        )
                    )
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        self_db = self.db
        with patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        delta_events = list(
            self.db.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == run.run_id, AgentEvent.event_type == "model.delta")
                .order_by(AgentEvent.event_seq)
            ).all()
        )

        expected = "".join(chunks)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(observed_mid_stream["delta_count"], 0)
        self.assertEqual(len(delta_events), 1)
        self.assertEqual(delta_events[0].payload_json["content"], expected)
        self.assertEqual(delta_events[0].payload_json["loop_step"], "tool_planning")
        self.assertIn("model_call_id", delta_events[0].payload_json)
        self.assertEqual(completed.result_json["message"], expected)

    def test_tool_result_policy_classifies_repairable_and_blocking_issues(self):
        call = SimpleNamespace(
            tool_call_id="tool-1",
            tool_name="scenario.compose_draft",
            status="succeeded",
            approval_required=False,
            output_json_redacted={
                "draft": {"warnings": ["companyName 未动态绑定"]},
                "diagnostics": ["Lingxi-Auth 未授权，需要有效 token"],
            },
            error_code=None,
            error_message=None,
        )

        policy = ToolResultPolicy()
        decision = policy.evaluate(call)
        message = policy.build_message(call)
        from app.services.agent_tool_service import ToolRegistry

        self.assertIn("companyName", [item.display() for item in decision.auto_fixable][0])
        self.assertTrue(any("Lingxi-Auth" in item.display() for item in decision.blocked))
        self.assertEqual(
            decision.repair_guidance,
            ToolRegistry().get("scenario.compose_draft").tool_result_repair_guidance,
        )
        self.assertIn("通用工具结果质量闭环", decision.followup_instruction)
        self.assertIn(FINAL_RESPONSE_BUDGET_INSTRUCTION, message)

    def test_tool_result_policy_retries_fixable_failed_tool_inputs(self):
        call = SimpleNamespace(
            tool_call_id="tool-2",
            tool_name="scenario.compose_draft",
            status="failed",
            approval_required=False,
            output_json_redacted=None,
            error_code="tool_execution_failed",
            error_message="validation error: datasets.0.id missing",
        )

        decision = ToolResultPolicy().evaluate(call)

        self.assertTrue(decision.should_continue_reasoning)
        self.assertTrue(any("datasets.0.id" in item.display() for item in decision.auto_fixable))
        self.assertIn("工具失败修复闭环", decision.followup_instruction)

    def test_tool_result_policy_repair_guidance_falls_back_for_unknown_tools(self):
        self.assertEqual(
            ToolResultPolicy().repair_guidance("unknown.tool"),
            DEFAULT_TOOL_RESULT_REPAIR_GUIDANCE,
        )

    def test_agent_model_health_reports_config_without_live_probe(self):
        provider = SimpleNamespace(
            provider="deepseek",
            base_url="https://api.deepseek.test",
            default_model="deepseek-test",
            configured=True,
        )

        with (
            patch("app.services.agent_runtime_service.AIService.provider_config", return_value=provider),
            patch("app.services.agent_runtime_service.AIService.chat_stream") as chat_stream,
        ):
            health = AgentModelHealthService().check(live=False)

        payload = AgentModelHealthRead.model_validate(health).model_dump(mode="python")
        self.assertEqual(list(AgentModelHealthRead.model_fields), list(AGENT_MODEL_HEALTH_FIELDS))
        self.assertEqual(list(payload), list(AGENT_MODEL_HEALTH_FIELDS))
        self.assertEqual(payload["provider"], "deepseek")
        self.assertTrue(payload["configured"])
        self.assertFalse(payload["live"])
        self.assertIsNone(payload["reachable"])
        chat_stream.assert_not_called()

    def test_agent_model_health_live_probe_uses_ai_service_stream(self):
        provider = SimpleNamespace(
            provider="deepseek",
            base_url="https://api.deepseek.test",
            default_model="deepseek-test",
            configured=True,
        )
        captured = {}

        def fake_stream(self, payload):
            captured["payload"] = payload
            yield {"type": "delta", "content": "ok"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_runtime_service.AIService.provider_config", return_value=provider),
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
        ):
            health = AgentModelHealthService().check(live=True)

        self.assertTrue(health["live"])
        self.assertTrue(health["reachable"])
        self.assertTrue(health["first_delta_received"])
        self.assertTrue(health["completed"])
        self.assertEqual(health["model"], "deepseek-test")
        self.assertEqual(health["finish_reason"], "stop")
        self.assertEqual(captured["payload"].max_tokens, 32)
        self.assertEqual(captured["payload"].temperature, 0)

    def test_agent_model_health_live_probe_reports_missing_key_without_stream_call(self):
        provider = SimpleNamespace(
            provider="deepseek",
            base_url="https://api.deepseek.test",
            default_model="deepseek-test",
            configured=False,
        )

        with (
            patch("app.services.agent_runtime_service.AIService.provider_config", return_value=provider),
            patch("app.services.agent_runtime_service.AIService.chat_stream") as chat_stream,
        ):
            health = AgentModelHealthService().check(live=True)

        self.assertFalse(health["configured"])
        self.assertFalse(health["reachable"])
        self.assertEqual(health["error_code"], "deepseek_api_key_missing")
        chat_stream.assert_not_called()

    def test_agent_model_health_route_allows_config_check_but_admin_only_live_probe(self):
        from app.api.v1.routers.agents import get_agent_model_health

        health = {
            "provider": "deepseek",
            "configured": True,
            "base_url": "https://api.deepseek.test",
            "default_model": "deepseek-test",
            "live": False,
            "reachable": None,
            "latency_ms": None,
            "first_delta_received": None,
            "completed": None,
            "model": None,
            "finish_reason": None,
            "error_code": None,
            "error_message": None,
            "checked_at": datetime.now(UTC).replace(tzinfo=None),
        }

        with patch("app.api.v1.routers.agents.AgentModelHealthService.check", return_value=health) as check:
            response = get_agent_model_health(live=False, db=self.db, current_user=self.owner)

        self.assertEqual(response["data"]["provider"], "deepseek")
        check.assert_called_once_with(live=False)
        with self.assertRaises(HTTPException) as ctx:
            get_agent_model_health(live=True, db=self.db, current_user=self.owner)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_agent_skill_catalog_route_returns_metadata_only(self):
        from app.api.v1.routers.agents import list_agent_skills

        payload = list_agent_skills(current_user=self.owner)["data"]

        names = [item["name"] for item in payload]
        self.assertEqual(names, sorted(names))
        self.assertIn("general-testing-answer", names)
        self.assertIn("scenario-composition", names)
        self.assertIn("report-summary", names)
        self.assertTrue(all(set(item) == {"name", "description"} for item in payload))
        self.assertFalse(any("Workflow" in str(item) for item in payload))

    def test_agent_conversation_smoke_route_runs_full_agent_loop_admin_only(self):
        from app.api.v1.routers.agents import run_agent_conversation_smoke

        def fake_stream(self, payload):
            yield {"type": "delta", "content": "Agent smoke ok"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream):
            response = run_agent_conversation_smoke(
                payload=AgentConversationSmokeRequest(project_id=10, intent="smoke test", max_iterations=1),
                db=self.db,
                current_user=self.admin,
            )

        payload = response["data"]
        self.assertEqual(list(AgentConversationSmokeRead.model_fields), list(AGENT_CONVERSATION_SMOKE_FIELDS))
        self.assertEqual(list(payload), list(AGENT_CONVERSATION_SMOKE_FIELDS))
        self.assertEqual(payload["project_id"], 10)
        self.assertEqual(payload["status"], "completed")
        self.assertTrue(payload["completed"])
        self.assertTrue(payload["first_delta_received"])
        self.assertEqual(payload["assistant_message"], "Agent smoke ok")
        self.assertEqual(payload["run_summary"]["run"]["run_id"], payload["run_id"])
        self.assertEqual(payload["run_summary"]["model"], "deepseek-test")
        self.assertIn("model.delta", payload["event_types"])
        self.assertIn("run.completed", payload["event_types"])

        with self.assertRaises(HTTPException) as ctx:
            run_agent_conversation_smoke(
                payload=AgentConversationSmokeRequest(project_id=10),
                db=self.db,
                current_user=self.owner,
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_conversation_runner_records_model_failure_as_run_failed(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="触发模型异常"),
            current_user=self.owner,
        )

        with patch(
            "app.services.agent_runtime_service.AIService.chat_stream",
            side_effect=HTTPException(status_code=503, detail="model unavailable"),
        ):
            failed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        events = list(self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all())
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error_code, "agent_conversation_model_error")
        self.assertEqual(events[-1].event_type, "run.failed")
        self.assertEqual(events[-1].payload_json["error_message"], "model unavailable")

    def test_create_run_generates_conversation_id_and_lists_history(self):
        runtime = AgentRuntimeService(self.db)
        first = runtime.create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="第一轮问题"),
            current_user=self.owner,
        )
        second = runtime.create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                conversation_id=first.conversation_id,
                intent="第二轮追问",
            ),
            current_user=self.owner,
        )

        conversations = runtime.list_conversations(project_id=10, current_user=self.member)
        runs = runtime.list_runs(project_id=10, conversation_id=first.conversation_id, current_user=self.member)
        payload = AgentConversationRead.model_validate(conversations[0]).model_dump(mode="python")

        self.assertTrue(first.conversation_id.startswith("agent-conv-"))
        self.assertEqual(second.conversation_id, first.conversation_id)
        self.assertEqual(list(AgentConversationRead.model_fields), list(AGENT_CONVERSATION_FIELDS))
        self.assertEqual(list(payload), list(AGENT_CONVERSATION_FIELDS))
        self.assertEqual(payload["conversation_id"], first.conversation_id)
        self.assertEqual(payload["run_count"], 2)
        self.assertEqual(payload["latest_run_id"], second.run_id)
        self.assertEqual([run.run_id for run in runs], [second.run_id, first.run_id])

    def test_conversation_runner_includes_previous_completed_runs_as_context(self):
        runtime = AgentRuntimeService(self.db)
        first = runtime.create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="第一轮：我想做登录接口测试"),
            current_user=self.owner,
        )
        runtime.complete_run(first, {"message": "可以先准备登录接口的正向和异常用例。"})
        second = runtime.create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                conversation_id=first.conversation_id,
                intent="继续补充边界情况",
            ),
            current_user=self.owner,
        )

        captured_messages = []

        def fake_stream(self, payload):
            captured_messages.extend(payload.messages)
            yield {"type": "delta", "content": "继续补充 token 过期。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream):
            AgentConversationRunner(self.db).run(run_id=second.run_id, user_id=self.owner.id)

        roles_and_content = [(message.role, message.content) for message in captured_messages]
        self.assertEqual(roles_and_content[0][0], "system")
        self.assertIn(("user", "第一轮：我想做登录接口测试"), roles_and_content)
        self.assertIn(("assistant", "可以先准备登录接口的正向和异常用例。"), roles_and_content)
        self.assertEqual(roles_and_content[-1], ("user", "继续补充边界情况"))

    def test_conversation_runner_injects_run_context_with_project_id(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="help me compose an enterprise scenario"),
            current_user=self.owner,
        )
        captured_messages = []

        def fake_stream(self, payload):
            captured_messages.extend(payload.messages)
            yield {"type": "delta", "content": "ok"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream):
            AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        run_context_messages = [
            message.content
            for message in captured_messages
            if "当前 Agent Run 上下文" in message.content
        ]
        self.assertEqual(len(run_context_messages), 1)
        self.assertIn(f"run_id={run.run_id}", run_context_messages[0])
        self.assertIn("project_id=10", run_context_messages[0])
        self.assertIn("不要向用户反问 project_id", run_context_messages[0])

    def test_conversation_runner_injects_project_memory_context_before_model_call(self):
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="登录接口测试偏好",
            content="登录接口测试必须覆盖 token 过期、重复提交和弱密码拦截。",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="请继续设计登录接口测试"),
            current_user=self.owner,
        )
        captured_messages = []

        def fake_stream(self, payload):
            captured_messages.extend(payload.messages)
            yield {"type": "delta", "content": "我会优先覆盖 token 过期。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        usage = self.db.scalar(
            select(AgentMemoryUsageEvent).where(
                AgentMemoryUsageEvent.run_id == run.run_id,
                AgentMemoryUsageEvent.memory_id == memory.id,
            )
        )
        event_rows = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )
        events = [item.event_type for item in event_rows]
        memory_messages = [
            message.content
            for message in captured_messages
            if "项目记忆上下文" in message.content
        ]

        self.assertEqual(completed.status, "completed")
        self.assertEqual(usage.usage_role, "conversation_context")
        self.assertFalse(usage.active_for_policy)
        self.assertIn("memory.context_injected", events)
        self.assertIn("登录接口测试偏好", memory_messages[0])
        self.assertIn("token 过期", memory_messages[0])
        self.assertEqual(captured_messages[-1].content, "请继续设计登录接口测试")

    def test_parse_tool_request_returns_structured_envelope(self):
        request = AgentConversationRunner(self.db)._parse_tool_request(
            (
                "```agent_tool_request\n"
                '{"tool_name":"project.read_context","input":{"project_id":10},'
                '"reason":"Need project context","evidence_refs":{"kind":"run","id":"evidence-1"},'
                '"unknown_field":"must not leak"}'
                "\n```"
            ),
            normalize_evidence_refs=True,
        )

        self.assertIsNotNone(request)
        self.assertNotIsInstance(request, dict)
        self.assertEqual(request.tool_name, "project.read_context")
        self.assertEqual(request.tool_input, {"project_id": 10})
        self.assertEqual(request.reason, "Need project context")
        self.assertEqual(request.evidence_refs_for_ledger(), [{"kind": "run", "id": "evidence-1"}])
        self.assertEqual(
            request.detected_event_payload(iteration=2),
            {
                "iteration": 2,
                "tool_name": "project.read_context",
                "reason": "Need project context",
                "decision_reason": "Need project context",
            },
        )
        self.assertNotIn("unknown_field", request.detected_event_payload(iteration=2))

    def test_conversation_runner_executes_model_requested_tool_and_feeds_result_back(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="先读取项目上下文再告诉我能做什么"),
            current_user=self.owner,
        )
        captured_messages = []

        def fake_stream(service_self, payload):
            captured_messages.append(payload.messages)
            if len(captured_messages) == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"project.read_context","input":{},"reason":"需要项目上下文","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "我已读取项目 TestAuto，可以继续生成接口测试方案。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch(
                "app.services.agent_runtime_service.AgentToolBackend.execute",
                return_value={"project": {"id": 10, "name": "TestAuto"}},
            ),
        ):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.run_id == run.run_id))
        event_rows = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )
        events = [item.event_type for item in event_rows]
        tool_request_event = next(item for item in event_rows if item.event_type == "model.tool_request_detected")
        tool_result_event = next(item for item in event_rows if item.event_type == "tool.result_observed")

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.result_json["message"], "我已读取项目 TestAuto，可以继续生成接口测试方案。")
        self.assertEqual(call.status, "succeeded")
        self.assertEqual(call.tool_name, "project.read_context")
        self.assertEqual(call.input_json_redacted["project_id"], 10)
        self.assertIn("model.tool_request_detected", events)
        self.assertIn("tool.completed", events)
        self.assertIn("tool.result_observed", events)
        self.assertIn("run.completed", events)
        model_loop_state = tool_request_event.payload_json["loop_state"]
        self.assertEqual(model_loop_state["iteration"], 0)
        self.assertEqual(model_loop_state["iteration_id"], f"{run.run_id}:iter-0")
        self.assertEqual(model_loop_state["phase"], "model")
        self.assertEqual(model_loop_state["step"], "tool_planning")
        self.assertEqual(model_loop_state["model_call_id"], tool_request_event.payload_json["model_call_id"])
        self.assertEqual(
            tool_result_event.payload_json["loop_state"],
            {
                "iteration": 0,
                "iteration_id": f"{run.run_id}:iter-0",
                "phase": "tool",
                "step": "tool_execution",
                "tool_call_id": call.tool_call_id,
                "decision_reason": tool_result_event.payload_json["decision_reason"],
            },
        )
        self.assertEqual(len(captured_messages), 2)
        self.assertIn("工具执行结果如下", captured_messages[1][-1].content)
        self.assertIn("TestAuto", captured_messages[1][-1].content)

    def test_scenario_compose_tool_uses_default_environment_when_omitted(self):
        from app.models.project import ProjectEnvironment
        from app.models.test_case import TestCase
        from app.services.agent_tool_service import AgentToolBackend

        environment = ProjectEnvironment(
            id=100,
            project_id=10,
            name="default",
            base_url="https://api.example.test",
            description="default env",
            is_default=True,
            is_deleted=False,
            created_by_id=self.owner.id,
        )
        test_case = TestCase(
            id=200,
            project_id=10,
            environment_id=100,
            name="Enterprise Login",
            description="login case",
            method="POST",
            path="/login",
            headers={},
            query_params={},
            body_type="json",
            body={"username": "demo", "password": "secret"},
            assertions=[],
            extractors=[],
            retry_policy=None,
            created_by_id=self.owner.id,
        )
        self.db.add_all([environment, test_case])
        self.db.commit()
        captured_payload = {}

        def fake_run_skill(self, *, skill_id, payload, current_user):
            captured_payload["skill_id"] = skill_id
            captured_payload["payload"] = payload
            captured_payload["current_user_id"] = current_user.id
            return {"scenario": {"name": "Enterprise Scenario"}}

        with patch("app.services.agent_tool_service.AISkillService.run_skill", new=fake_run_skill):
            result = AgentToolBackend(self.db).execute(
                tool_name="scenario.compose_draft",
                payload={
                    "project_id": 10,
                    "input": {
                        "requirement": "compose an enterprise login and order workflow",
                        "self_validate": False,
                    },
                },
                current_user=self.owner,
            )

        self.assertEqual(captured_payload["skill_id"], "scenario-composer")
        self.assertEqual(captured_payload["payload"].project_id, 10)
        self.assertEqual(captured_payload["payload"].environment_id, 100)
        self.assertEqual(captured_payload["payload"].input["requirement"], "compose an enterprise login and order workflow")
        self.assertEqual(captured_payload["payload"].input["http_test_case_ids"], [200])
        self.assertEqual(captured_payload["payload"].input["websocket_test_case_ids"], [])
        self.assertEqual(result["draft"]["scenario"]["name"], "Enterprise Scenario")

    def test_report_read_summary_tool_returns_recent_report_context(self):
        from app.models.test_plan import TestPlanRun
        from app.models.visual_flow import VisualFlowExecution, VisualFlowNodeExecution
        from app.services.agent_tool_service import AgentToolBackend

        now = datetime.now().replace(microsecond=0)
        plan_run = TestPlanRun(
            id=301,
            plan_id=None,
            project_id=10,
            plan_name="Nightly Regression",
            plan_version=3,
            environment_id=None,
            environment_name=None,
            status="passed",
            trigger="schedule",
            plan_snapshot={"targets": []},
            target_results=[],
            target_count=3,
            passed_count=3,
            failed_count=0,
            operator_id=self.owner.id,
            started_at=now - timedelta(minutes=20),
            finished_at=now - timedelta(minutes=18),
            duration_ms=120000,
            created_at=now - timedelta(minutes=20),
            is_deleted=False,
        )
        flow_execution = VisualFlowExecution(
            id=401,
            flow_id=None,
            flow_version_id=None,
            project_id=10,
            environment_id=None,
            status="failed",
            trigger_type="manual",
            trigger_user_id=self.owner.id,
            context_snapshot={"variables": {}},
            started_at=now - timedelta(minutes=10),
            finished_at=now - timedelta(minutes=9),
            created_at=now - timedelta(minutes=10),
        )
        nodes = [
            VisualFlowNodeExecution(
                id=501,
                execution_id=401,
                node_id="login",
                status="passed",
                attempt=1,
            ),
            VisualFlowNodeExecution(
                id=502,
                execution_id=401,
                node_id="checkout",
                status="failed",
                attempt=1,
                error={"message": "assertion failed"},
            ),
        ]
        self.db.add_all([plan_run, flow_execution, *nodes])
        self.db.commit()

        result = AgentToolBackend(self.db).execute(
            tool_name="report.read_summary",
            payload={"project_id": 10, "page_size": 10},
            current_user=self.owner,
        )

        self.assertEqual(result["project_id"], 10)
        self.assertEqual(result["report_count"], 2)
        self.assertEqual(result["returned_report_count"], 2)
        self.assertEqual(result["status_counts"], {"failed": 1, "passed": 1})
        self.assertEqual(result["returned_case_totals"]["total"], 5)
        self.assertEqual(result["returned_case_totals"]["passed"], 4)
        self.assertEqual(result["returned_case_totals"]["failed"], 1)
        self.assertEqual(result["returned_case_totals"]["pass_rate"], 80.0)
        self.assertEqual(result["latest_reports"][0]["source_type"], "flow")
        self.assertEqual(result["failure_reports"][0]["source_id"], 401)

    def test_conversation_runner_queries_cases_before_composing_scenario(self):
        from app.models.project import ProjectEnvironment
        from app.models.test_case import TestCase

        environment = ProjectEnvironment(
            id=101,
            project_id=10,
            name="default",
            base_url="https://api.example.test",
            description="default env",
            is_default=True,
            is_deleted=False,
            created_by_id=self.owner.id,
        )
        case = TestCase(
            id=201,
            project_id=10,
            environment_id=101,
            name="Enterprise Company List",
            description="query companies",
            method="GET",
            path="/companies",
            headers={},
            query_params={},
            body_type="json",
            body=None,
            assertions=[],
            extractors=[],
            retry_policy=None,
            created_by_id=self.owner.id,
        )
        self.db.add_all([environment, case])
        self.db.commit()
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="Create an enterprise scenario composition from existing test cases.",
                max_iterations=3,
            ),
            current_user=self.owner,
        )
        captured_skill_payload = {}
        captured_messages = []

        def fake_stream(service_self, payload):
            captured_messages.append(payload.messages)
            if len(captured_messages) == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"testcase.query_project_cases","input":{"project_id":10},'
                        '"reason":"Need project test cases before composing scenario","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            if len(captured_messages) == 2:
                self.assertIn("Enterprise Company List", captured_messages[-1][-1].content)
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"scenario.compose_draft","input":{"project_id":10,'
                        '"environment_id":101,"input":{"requirement":"enterprise company workflow",'
                        '"http_test_case_ids":[201],"self_validate":false,"max_nodes":3}},'
                        '"reason":"Compose scenario from queried case ids","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "Scenario draft created from queried test cases."}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        def fake_run_skill(self, *, skill_id, payload, current_user):
            captured_skill_payload["skill_id"] = skill_id
            captured_skill_payload["payload"] = payload
            return {"scenario": {"name": "Enterprise Company Workflow"}}

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch("app.services.agent_tool_service.AISkillService.run_skill", new=fake_run_skill),
        ):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        calls = list(
            self.db.scalars(
                select(AgentToolCall).where(AgentToolCall.run_id == run.run_id).order_by(AgentToolCall.id.asc())
            ).all()
        )
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.result_json["message"], "Scenario draft created from queried test cases.")
        self.assertEqual([call.tool_name for call in calls], ["testcase.query_project_cases", "scenario.compose_draft"])
        self.assertEqual(calls[0].status, "succeeded")
        self.assertEqual(calls[0].output_json_redacted["http_test_cases"][0]["id"], 201)
        self.assertEqual(calls[1].status, "succeeded")
        self.assertEqual(captured_skill_payload["skill_id"], "scenario-composer")
        self.assertEqual(captured_skill_payload["payload"].input["http_test_case_ids"], [201])

    def test_conversation_runner_project_context_query_does_not_force_scenario_compose(self):
        from app.models.project import ProjectEnvironment
        from app.models.test_case import TestCase

        environment = ProjectEnvironment(
            id=108,
            project_id=10,
            name="test",
            base_url="https://api.example.test",
            description="default env",
            is_default=True,
            is_deleted=False,
            created_by_id=self.owner.id,
        )
        case = TestCase(
            id=208,
            project_id=10,
            environment_id=108,
            name="Enterprise Company List",
            description="query companies",
            method="GET",
            path="/companies",
            headers={},
            query_params={},
            body_type="json",
            body=None,
            assertions=[],
            extractors=[],
            retry_policy=None,
            created_by_id=self.owner.id,
        )
        self.db.add_all([environment, case])
        self.db.commit()
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent=(
                    "Please read current project context, test resources, default environment, "
                    "and whether existing scenario exists."
                ),
                max_iterations=3,
            ),
            current_user=self.owner,
        )
        captured_messages = []

        def fake_stream(service_self, payload):
            captured_messages.append(payload.messages)
            if len(captured_messages) == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"project.read_context","input":{"project_id":10},'
                        '"reason":"Read project context first","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            if len(captured_messages) == 2:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"testcase.query_project_cases","input":{"project_id":10},'
                        '"reason":"Summarize available test resources","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            yield {
                "type": "delta",
                "content": "Project has one HTTP test case, default environment test, and no confirmed saved scenario.",
            }
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        calls = list(
            self.db.scalars(
                select(AgentToolCall).where(AgentToolCall.run_id == run.run_id).order_by(AgentToolCall.id.asc())
            ).all()
        )
        event_types = [
            event.event_type
            for event in self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq.asc())
            ).all()
        ]
        self.assertEqual(completed.status, "completed")
        self.assertEqual([call.tool_name for call in calls], ["project.read_context", "testcase.query_project_cases"])
        self.assertNotIn("model.required_tool_missing", event_types)
        self.assertNotIn("model.required_tool_repaired", event_types)
        self.assertIn("default environment test", completed.result_json["message"])

    def test_conversation_runner_prompts_repair_for_fixable_scenario_warnings(self):
        from app.models.project import ProjectEnvironment
        from app.models.test_case import TestCase

        environment = ProjectEnvironment(
            id=105,
            project_id=10,
            name="default",
            base_url="https://api.example.test",
            description="default env",
            is_default=True,
            is_deleted=False,
            created_by_id=self.owner.id,
        )
        case = TestCase(
            id=205,
            project_id=10,
            environment_id=105,
            name="Enterprise Company List",
            description="query companies",
            method="GET",
            path="/companies",
            headers={},
            query_params={},
            body_type="json",
            body=None,
            assertions=[],
            extractors=[],
            retry_policy=None,
            created_by_id=self.owner.id,
        )
        self.db.add_all([environment, case])
        self.db.commit()
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="Create an enterprise scenario and repair fixable validation warnings.",
                max_iterations=4,
            ),
            current_user=self.owner,
        )
        captured_messages = []
        captured_skill_inputs = []

        def fake_stream(service_self, payload):
            captured_messages.append(payload.messages)
            if len(captured_messages) == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"testcase.query_project_cases","input":{"project_id":10},'
                        '"reason":"Need cases before composing scenario","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            if len(captured_messages) == 2:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"scenario.compose_draft","input":{"project_id":10,'
                        '"environment_id":105,"input":{"requirement":"enterprise workflow",'
                        '"http_test_case_ids":[205],"include_latest_execution":true,'
                        '"self_validate":true,"max_nodes":3}},'
                        '"reason":"Compose initial scenario","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            if len(captured_messages) == 3:
                repair_prompt = captured_messages[-1][-1].content
                self.assertIn("通用工具结果质量闭环", repair_prompt)
                self.assertIn("scenario.compose_draft", repair_prompt)
                self.assertIn("可自动修复项", repair_prompt)
                self.assertIn("companyName 未动态绑定", repair_prompt)
                self.assertIn("需要用户输入或外部配置的阻断项", repair_prompt)
                self.assertIn("鉴权令牌问题", repair_prompt)
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"scenario.compose_draft","input":{"project_id":10,'
                        '"environment_id":105,"input":{"requirement":"enterprise workflow",'
                        '"http_test_case_ids":[205],"include_latest_execution":true,'
                        '"self_validate":true,"max_nodes":3,'
                        '"extra_requirements":"修复 companyName 未动态绑定：从企业列表响应提取 companyName 并绑定关注接口 body.companyName；保留鉴权令牌为用户配置项。"}},'
                        '"reason":"Repair fixable scenario warnings before final answer","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "Scenario draft repaired; only auth token remains for user configuration."}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        def fake_run_skill(service_self, *, skill_id, payload, current_user):
            captured_skill_inputs.append(payload.input)
            if len(captured_skill_inputs) == 1:
                return {
                    "scenario": {"name": "Enterprise Workflow"},
                    "warnings": [
                        "鉴权令牌问题：需要用户配置 Lingxi-Auth。",
                        "companyName 未动态绑定：关注接口 body.companyName 被硬编码。",
                    ],
                }
            return {
                "scenario": {"name": "Enterprise Workflow Repaired"},
                "warnings": ["鉴权令牌问题：需要用户配置 Lingxi-Auth。"],
            }

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch("app.services.agent_tool_service.AISkillService.run_skill", new=fake_run_skill),
        ):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        calls = list(
            self.db.scalars(
                select(AgentToolCall).where(AgentToolCall.run_id == run.run_id).order_by(AgentToolCall.id.asc())
            ).all()
        )
        self.assertEqual(completed.status, "completed")
        self.assertEqual(
            completed.result_json["message"],
            "Scenario draft repaired; only auth token remains for user configuration.",
        )
        self.assertEqual(
            [call.tool_name for call in calls],
            ["testcase.query_project_cases", "scenario.compose_draft", "scenario.compose_draft"],
        )
        self.assertIn("companyName 未动态绑定", captured_skill_inputs[1]["extra_requirements"])

    def test_conversation_runner_applies_generic_repair_loop_to_ai_skill_warnings(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="Generate HTTP test cases and repair fixable draft warnings.",
                max_iterations=3,
            ),
            current_user=self.owner,
        )
        captured_messages = []
        captured_skill_inputs = []

        def fake_stream(service_self, payload):
            captured_messages.append(payload.messages)
            if len(captured_messages) == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"ai_skill.run_draft","input":{"project_id":10,'
                        '"skill_id":"http-test-case","operation":"generate",'
                        '"input":{"interface_text":"GET /companies returns company list",'
                        '"generate_count":1,"include_assertions":true}},'
                        '"reason":"Generate draft HTTP cases","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            if len(captured_messages) == 2:
                repair_prompt = captured_messages[-1][-1].content
                self.assertIn("通用工具结果质量闭环", repair_prompt)
                self.assertIn("ai_skill.run_draft", repair_prompt)
                self.assertIn("推荐修复路径", repair_prompt)
                self.assertIn("json_equals 缺少 expected", repair_prompt)
                self.assertIn("需要用户输入或外部配置的阻断项", repair_prompt)
                self.assertIn("鉴权 token 需要用户配置", repair_prompt)
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"ai_skill.run_draft","input":{"project_id":10,'
                        '"skill_id":"http-test-case","operation":"generate",'
                        '"input":{"interface_text":"GET /companies returns company list",'
                        '"generate_count":1,"include_assertions":true,'
                        '"extra_requirements":"修复 json_equals 缺少 expected：根据接口响应样本或字段语义补充稳定 expected；鉴权 token 保持为用户配置项。"}},'
                        '"reason":"Repair fixable AI draft warnings","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "HTTP test case draft repaired; only auth token remains for user configuration."}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        def fake_run_skill(service_self, *, skill_id, payload, current_user):
            captured_skill_inputs.append(payload.input)
            if len(captured_skill_inputs) == 1:
                return {
                    "source_summary": "company list",
                    "cases": [],
                    "warnings": [
                        "第 1 条 json_equals 缺少 expected，已忽略。",
                        "鉴权 token 需要用户配置。",
                    ],
                }
            return {
                "source_summary": "company list repaired",
                "cases": [],
                "warnings": ["鉴权 token 需要用户配置。"],
            }

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch("app.services.agent_tool_service.AISkillService.run_skill", new=fake_run_skill),
        ):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        calls = list(
            self.db.scalars(
                select(AgentToolCall).where(AgentToolCall.run_id == run.run_id).order_by(AgentToolCall.id.asc())
            ).all()
        )
        self.assertEqual(completed.status, "completed")
        self.assertEqual(
            completed.result_json["message"],
            "HTTP test case draft repaired; only auth token remains for user configuration.",
        )
        self.assertEqual([call.tool_name for call in calls], ["ai_skill.run_draft", "ai_skill.run_draft"])
        self.assertIn("json_equals 缺少 expected", captured_skill_inputs[1]["extra_requirements"])

    def test_conversation_runner_blocks_scenario_compose_until_cases_are_queried(self):
        from app.models.project import ProjectEnvironment
        from app.models.test_case import TestCase

        environment = ProjectEnvironment(
            id=102,
            project_id=10,
            name="default",
            base_url="https://api.example.test",
            description="default env",
            is_default=True,
            is_deleted=False,
            created_by_id=self.owner.id,
        )
        case = TestCase(
            id=202,
            project_id=10,
            environment_id=102,
            name="Enterprise Contract Detail",
            description="query contract detail",
            method="GET",
            path="/contracts/202",
            headers={},
            query_params={},
            body_type="json",
            body=None,
            assertions=[],
            extractors=[],
            retry_policy=None,
            created_by_id=self.owner.id,
        )
        self.db.add_all([environment, case])
        self.db.commit()
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="Create an enterprise scenario composition from existing test cases.",
                max_iterations=4,
            ),
            current_user=self.owner,
        )
        captured_messages = []
        captured_skill_payload = {}

        def fake_stream(service_self, payload):
            captured_messages.append(payload.messages)
            if len(captured_messages) == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"scenario.compose_draft","input":{"project_id":10,'
                        '"environment_id":102,"input":{"requirement":"enterprise contract workflow",'
                        '"http_test_case_ids":[202],"self_validate":false,"max_nodes":3}},'
                        '"reason":"Compose scenario directly","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            if len(captured_messages) == 2:
                self.assertIn("scenario_compose_requires_case_query", captured_messages[-1][-1].content)
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"testcase.query_project_cases","input":{"project_id":10},'
                        '"reason":"Need project cases before composing scenario","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            if len(captured_messages) == 3:
                self.assertIn("Enterprise Contract Detail", captured_messages[-1][-1].content)
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"scenario.compose_draft","input":{"project_id":10,'
                        '"environment_id":102,"input":{"requirement":"enterprise contract workflow",'
                        '"http_test_case_ids":[202],"self_validate":false,"max_nodes":3}},'
                        '"reason":"Compose from queried case ids","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "Scenario draft created after querying project cases."}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        def fake_run_skill(service_self, *, skill_id, payload, current_user):
            captured_skill_payload["skill_id"] = skill_id
            captured_skill_payload["payload"] = payload
            return {"scenario": {"name": "Enterprise Contract Workflow"}}

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch("app.services.agent_tool_service.AISkillService.run_skill", new=fake_run_skill),
        ):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        calls = list(
            self.db.scalars(
                select(AgentToolCall).where(AgentToolCall.run_id == run.run_id).order_by(AgentToolCall.id.asc())
            ).all()
        )

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.result_json["message"], "Scenario draft created after querying project cases.")
        self.assertEqual(
            [call.tool_name for call in calls],
            ["scenario.compose_draft", "testcase.query_project_cases", "scenario.compose_draft"],
        )
        self.assertEqual(calls[0].status, "failed")
        self.assertEqual(calls[0].error_code, "scenario_compose_requires_case_query")
        observations = list(
            self.db.scalars(
                select(AgentLoopObservation)
                .where(AgentLoopObservation.run_id == run.run_id)
                .order_by(AgentLoopObservation.id.asc())
            ).all()
        )
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].iteration, calls[0].attempt_index)
        self.assertEqual(observations[0].step_index, calls[0].step_index)
        self.assertEqual(observations[0].next_action, "repair")
        self.assertEqual(observations[0].stop_action_reason, "tool_prerequisite_missing")
        self.assertEqual(observations[0].root_cause_rule_id, "RC_TOOL_PREREQUISITE_MISSING")
        self.assertEqual(observations[0].root_cause_primary, "tool_prerequisite_missing")
        self.assertEqual(observations[0].mitigation_action, "call_required_prerequisite_tool")
        self.assertEqual(
            observations[0].observation_json,
            {
                "source": "tool_prerequisite_guard",
                "tool_call_id": calls[0].tool_call_id,
                "blocked_tool": "scenario.compose_draft",
                "required_tool": "testcase.query_project_cases",
                "error_code": "scenario_compose_requires_case_query",
            },
        )
        self.assertEqual(calls[1].status, "succeeded")
        self.assertEqual(calls[1].output_json_redacted["http_test_cases"][0]["id"], 202)
        self.assertEqual(calls[2].status, "succeeded")
        self.assertEqual(captured_skill_payload["skill_id"], "scenario-composer")
        self.assertEqual(captured_skill_payload["payload"].input["http_test_case_ids"], [202])

    def test_conversation_runner_honors_cancel_during_final_summary_after_tool_loop(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="工具后总结时取消",
                max_iterations=1,
            ),
            current_user=self.owner,
        )
        call_count = {"value": 0}
        session_factory = self.Session
        owner = self.owner

        def fake_stream(self, payload):
            call_count["value"] += 1
            if call_count["value"] == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"project.read_context","input":{"project_id":10},"reason":"读取项目","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "tool_calls", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "最终总结第一段"}
            cancel_db = session_factory()
            try:
                AgentRuntimeService(cancel_db).cancel_run(run_id=run.run_id, current_user=owner)
            finally:
                cancel_db.close()
            yield {"type": "delta", "content": "不应继续写入"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch(
                "app.services.agent_runtime_service.AgentToolBackend.execute",
                return_value={"project": {"id": 10, "name": "TestAuto"}},
            ),
        ):
            cancelled = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        events = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )
        event_types = [item.event_type for item in events]
        cancelled_index = event_types.index("run.cancelled")
        events_after_cancel = events[cancelled_index + 1:]

        self.assertEqual(cancelled.status, "cancelled")
        self.assertIn("tool.result_observed", event_types)
        self.assertIn("run.cancelled", event_types)
        self.assertNotIn("run.completed", [item.event_type for item in events_after_cancel])
        self.assertFalse(any(
            item.event_type == "model.completed" and item.payload_json.get("final_summary")
            for item in events_after_cancel
        ))

    def test_conversation_runner_records_max_iteration_observation_before_final_summary(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="读取项目上下文后总结",
                max_iterations=1,
            ),
            current_user=self.owner,
        )
        call_count = {"value": 0}

        def fake_stream(self, payload):
            call_count["value"] += 1
            if call_count["value"] == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"project.read_context","input":{"project_id":10},'
                        '"reason":"读取项目","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "tool_calls", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "这是基于工具结果的最终总结。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch(
                "app.services.agent_runtime_service.AgentToolBackend.execute",
                return_value={"project": {"id": 10, "name": "TestAuto"}},
            ),
        ):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        observations = list(
            self.db.scalars(
                select(AgentLoopObservation)
                .where(AgentLoopObservation.run_id == run.run_id)
                .order_by(AgentLoopObservation.id.asc())
            ).all()
        )
        events = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.result_json["message"], "这是基于工具结果的最终总结。")
        self.assertEqual(call_count["value"], 2)
        self.assertEqual(len(observations), 1)
        loop_observed_index = next(
            index for index, item in enumerate(events) if item.event_type == "loop.observed"
        )
        final_summary_started_index = next(
            index
            for index, item in enumerate(events)
            if item.event_type == "model.started" and item.payload_json.get("final_summary")
        )
        self.assertEqual(observations[0].iteration, 1)
        self.assertEqual(observations[0].step_index, 1)
        self.assertEqual(observations[0].next_action, "stop")
        self.assertEqual(observations[0].stop_action_reason, "max_iterations")
        self.assertEqual(observations[0].root_cause_rule_id, "RC_MAX_ITERATIONS")
        self.assertEqual(observations[0].root_cause_primary, "max_iterations")
        self.assertEqual(observations[0].mitigation_action, "human_review_or_extend_limit")
        self.assertEqual(observations[0].observation_json["source"], "max_iteration_guard")
        self.assertEqual(observations[0].observation_json["max_iterations"], 1)
        self.assertEqual(observations[0].observation_json["tool_call_count"], 1)
        self.assertLess(loop_observed_index, final_summary_started_index)

    def test_conversation_runner_stops_on_repeated_failed_tool_no_progress(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="连续修复同一个工具失败时停止",
                max_iterations=4,
            ),
            current_user=self.owner,
        )
        model_call_count = {"value": 0}
        backend_call_count = {"value": 0}

        def fake_stream(self, payload):
            model_call_count["value"] += 1
            if model_call_count["value"] <= 2:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"project.read_context","input":{"project_id":10},'
                        '"reason":"读取项目","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "tool_calls", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "不应在重复失败后继续生成最终回复。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        def fake_execute(self, *, tool_name, payload, current_user):
            backend_call_count["value"] += 1
            raise ValueError("schema invalid: missing required field base_url")

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch("app.services.agent_tool_service.AgentToolBackend.execute", new=fake_execute),
        ):
            failed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        calls = list(
            self.db.scalars(
                select(AgentToolCall)
                .where(AgentToolCall.run_id == run.run_id)
                .order_by(AgentToolCall.id.asc())
            ).all()
        )
        observations = list(
            self.db.scalars(
                select(AgentLoopObservation)
                .where(AgentLoopObservation.run_id == run.run_id)
                .order_by(AgentLoopObservation.id.asc())
            ).all()
        )
        events = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )
        event_types = [item.event_type for item in events]

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error_code, "agent_repair_no_progress")
        self.assertEqual(model_call_count["value"], 2)
        self.assertEqual(backend_call_count["value"], 2)
        self.assertEqual([call.status for call in calls], ["failed", "failed"])
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].iteration, 2)
        self.assertEqual(observations[0].step_index, 2)
        self.assertEqual(observations[0].next_action, "stop")
        self.assertEqual(observations[0].stop_action_reason, "same_failure_no_progress")
        self.assertEqual(observations[0].root_cause_rule_id, "RC_NO_PROGRESS_PURE")
        self.assertEqual(observations[0].root_cause_primary, "same_failure_no_progress")
        self.assertEqual(observations[0].mitigation_action, "stop_or_escalate_repair_strategy")
        self.assertEqual(observations[0].observation_json["source"], "tool_result_no_progress_guard")
        self.assertEqual(observations[0].observation_json["tool_name"], "project.read_context")
        self.assertEqual(observations[0].observation_json["error_code"], "tool_execution_failed")
        self.assertEqual(
            observations[0].observation_json["tool_call_ids"],
            [calls[0].tool_call_id, calls[1].tool_call_id],
        )
        self.assertLess(event_types.index("loop.observed"), event_types.index("run.failed"))
        self.assertFalse(any(
            item.event_type == "model.started" and item.payload_json.get("iteration") == 2
            for item in events
        ))

    def test_conversation_runner_repairs_invalid_model_tool_request_once(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="读取项目上下文后再回答"),
            current_user=self.owner,
        )
        captured_messages = []

        def fake_stream(self, payload):
            captured_messages.append(payload.messages)
            if len(captured_messages) == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"project.read_context","input":{},"reason":"需要项目上下文","evidence_refs":{}}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            if len(captured_messages) == 2:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"project.read_context","input":{},"reason":"需要项目上下文","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "已读取项目上下文，可以继续规划测试。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch(
                "app.services.agent_runtime_service.AgentToolBackend.execute",
                return_value={"project": {"id": 10, "name": "TestAuto"}},
            ),
        ):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        events = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )
        event_types = [item.event_type for item in events]
        invalid_event = next(item for item in events if item.event_type == "model.tool_request_invalid")
        repair_started = [
            item for item in events
            if item.event_type == "model.started" and item.payload_json.get("repair_attempt")
        ]
        observations = list(
            self.db.scalars(
                select(AgentLoopObservation)
                .where(AgentLoopObservation.run_id == run.run_id)
                .order_by(AgentLoopObservation.id.asc())
            ).all()
        )

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.result_json["message"], "已读取项目上下文，可以继续规划测试。")
        self.assertIn("model.tool_request_invalid", event_types)
        self.assertIn("model.tool_request_repaired", event_types)
        self.assertIn("model.tool_request_detected", event_types)
        self.assertIn("tool.result_observed", event_types)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].iteration, 0)
        self.assertEqual(observations[0].step_index, 0)
        self.assertEqual(observations[0].next_action, "repair")
        self.assertEqual(observations[0].stop_action_reason, "tool_request_format_invalid")
        self.assertEqual(observations[0].root_cause_rule_id, "RC_TOOL_REQUEST_FORMAT_INVALID")
        self.assertEqual(observations[0].root_cause_primary, "tool_request_format_invalid")
        self.assertEqual(observations[0].mitigation_action, "repair_tool_request_format")
        self.assertEqual(observations[0].observation_json["source"], "tool_request_parse_guard")
        self.assertEqual(observations[0].observation_json["error_message"], invalid_event.payload_json["error_message"])
        self.assertEqual(observations[0].observation_json["model_call_id"], invalid_event.payload_json["model_call_id"])
        self.assertEqual(len(repair_started), 1)
        self.assertIn("格式无效", captured_messages[1][-1].content)
        self.assertIn("工具执行结果如下", captured_messages[2][-1].content)

    def test_conversation_runner_salvages_mixed_tool_block_without_extra_repair_call(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="读取项目上下文并继续回答"),
            current_user=self.owner,
        )
        captured_messages = []

        def fake_stream(self, payload):
            captured_messages.append(payload.messages)
            if len(captured_messages) == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "我先读取项目上下文。\n\n"
                        "```agent_tool_request\n"
                        '{"tool_name":"project.read_context","input":{},'
                        '"reason":"需要项目上下文","evidence_refs":["latest-project"]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "已读取项目上下文。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch(
                "app.services.agent_runtime_service.AgentToolBackend.execute",
                return_value={"project": {"id": 10, "name": "TestAuto"}},
            ),
        ):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        events = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )
        calls = list(self.db.scalars(select(AgentToolCall).where(AgentToolCall.run_id == run.run_id)).all())
        event_types = [item.event_type for item in events]
        repaired_event = next(item for item in events if item.event_type == "model.tool_request_repaired")
        visible_content = "".join(
            (item.payload_json or {}).get("content", "")
            for item in events
            if item.event_type == "model.delta"
        )

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.result_json["message"], "已读取项目上下文。")
        self.assertEqual(len(captured_messages), 2)
        self.assertIn("model.tool_request_invalid", event_types)
        self.assertEqual(repaired_event.payload_json["repair_strategy"], "salvaged_fenced_tool_request")
        self.assertFalse(any(item.payload_json.get("repair_attempt") for item in events if item.event_type == "model.started"))
        self.assertEqual([call.tool_name for call in calls], ["project.read_context"])
        self.assertEqual(calls[0].policy_evidence_refs_json, [])
        self.assertNotIn("agent_tool_request", visible_content)

    def test_conversation_runner_short_circuits_unsupported_scenario_save(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="把刚才的场景直接保存成正式场景，不要问我。",
            ),
            current_user=self.owner,
        )

        classifier_response = AIChatResponse(
            provider="deepseek",
            model="deepseek-test",
            content='{"requires_scenario_persistence": true, "confidence": 0.98, "reason": "用户要求保存为正式场景"}',
            finish_reason="stop",
        )
        with (
            patch("app.services.agent_runtime_service.AIService.chat", return_value=classifier_response) as chat,
            patch("app.services.agent_runtime_service.AIService.chat_stream") as chat_stream,
        ):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        calls = list(self.db.scalars(select(AgentToolCall).where(AgentToolCall.run_id == run.run_id)).all())
        events = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )

        self.assertEqual(completed.status, "completed")
        self.assertIn("没有“保存正式场景”的后端工具", completed.result_json["message"])
        self.assertEqual(completed.result_json["completion_source"], "unsupported_scenario_save_guard")
        self.assertEqual(calls, [])
        self.assertIn("model.delta", [item.event_type for item in events])
        chat.assert_called_once()
        chat_stream.assert_not_called()

    def test_conversation_runner_does_not_short_circuit_negated_scenario_save_intent(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="请基于当前项目已有用例组合一个企业相关场景草稿，不要保存。",
            ),
            current_user=self.owner,
        )
        classifier_response = AIChatResponse(
            provider="deepseek",
            model="deepseek-test",
            content='{"requires_scenario_persistence": false, "confidence": 0.99, "reason": "用户明确要求不要保存，只生成草稿"}',
            finish_reason="stop",
        )

        def fake_stream(self, payload):
            yield {"type": "delta", "content": "我会继续生成场景草稿，但不会保存正式场景。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_runtime_service.AIService.chat", return_value=classifier_response) as chat,
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
        ):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        self.assertEqual(completed.status, "completed")
        self.assertNotEqual(completed.result_json.get("completion_source"), "unsupported_scenario_save_guard")
        self.assertEqual(completed.result_json["message"], "我会继续生成场景草稿，但不会保存正式场景。")
        chat.assert_called_once()

    def test_conversation_runner_suppresses_mixed_tool_request_stream_and_repairs(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="请读取当前项目上下文，然后总结。"),
            current_user=self.owner,
        )
        captured_messages = []

        def fake_stream(self, payload):
            captured_messages.append(payload.messages)
            if len(captured_messages) == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "我先读取项目。\n"
                        "```agent_tool_request\n"
                        '{"tool_name":"project.read_context","input":{"project_id":10},'
                        '"reason":"读取项目","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            if len(captured_messages) == 2:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"project.read_context","input":{"project_id":10},'
                        '"reason":"读取项目","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "已读取项目上下文。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch(
                "app.services.agent_runtime_service.AgentToolBackend.execute",
                return_value={"project": {"id": 10, "name": "TestAuto"}},
            ),
        ):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        events = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )
        event_types = [item.event_type for item in events]
        visible_content = "".join(
            item.payload_json.get("content", "")
            for item in events
            if item.event_type == "model.delta"
        )

        self.assertEqual(completed.status, "completed")
        self.assertIn("model.tool_request_invalid", event_types)
        self.assertIn("model.tool_request_repaired", event_types)
        self.assertNotIn("agent_tool_request", visible_content)
        self.assertNotIn("我先读取项目", visible_content)
        self.assertEqual(completed.result_json["message"], "已读取项目上下文。")

    def test_conversation_runner_repairs_missing_compose_after_case_query(self):
        from app.models.project import ProjectEnvironment
        from app.models.test_case import TestCase

        environment = ProjectEnvironment(
            id=106,
            project_id=10,
            name="default",
            base_url="https://api.example.test",
            description="default env",
            is_default=True,
            is_deleted=False,
            created_by_id=self.owner.id,
        )
        case = TestCase(
            id=206,
            project_id=10,
            environment_id=106,
            name="Enterprise Company List",
            description="query companies",
            method="GET",
            path="/companies",
            headers={},
            query_params={},
            body_type="json",
            body=None,
            assertions=[],
            extractors=[],
            retry_policy=None,
            created_by_id=self.owner.id,
        )
        self.db.add_all([environment, case])
        self.db.commit()
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="请基于当前项目已有用例组合一个企业相关场景草稿。",
                max_iterations=3,
            ),
            current_user=self.owner,
        )
        captured_messages = []
        test_case = self

        def fake_stream(self, payload):
            captured_messages.append(payload.messages)
            if len(captured_messages) == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"testcase.query_project_cases","input":{"project_id":10},'
                        '"reason":"查询用例","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            if len(captured_messages) == 2:
                yield {"type": "delta", "content": "我已经分析完候选用例，企业列表可作为第一步。"}
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            if len(captured_messages) == 3:
                test_case.assertIn("要求继续调用", captured_messages[-1][-1].content)
                test_case.assertIn("scenario.compose_draft", captured_messages[-1][-1].content)
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"scenario.compose_draft","input":{"project_id":10,'
                        '"environment_id":106,"input":{"requirement":"enterprise workflow",'
                        '"http_test_case_ids":[206],"self_validate":false,"max_nodes":3}},'
                        '"reason":"组合场景","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "已生成企业场景草稿。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch(
                "app.services.agent_tool_service.AISkillService.run_skill",
                return_value={"scenario": {"name": "Enterprise Workflow"}},
            ),
        ):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        calls = list(
            self.db.scalars(
                select(AgentToolCall).where(AgentToolCall.run_id == run.run_id).order_by(AgentToolCall.id.asc())
            ).all()
        )
        event_types = [
            item.event_type
            for item in self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        ]

        self.assertEqual(completed.status, "completed")
        self.assertEqual([call.tool_name for call in calls], ["testcase.query_project_cases", "scenario.compose_draft"])
        self.assertIn("model.required_tool_missing", event_types)
        self.assertIn("model.required_tool_repaired", event_types)
        self.assertEqual(completed.result_json["message"], "已生成企业场景草稿。")
        missing_event = next(
            item
            for item in self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
            if item.event_type == "model.required_tool_missing"
        )
        observations = list(
            self.db.scalars(
                select(AgentLoopObservation)
                .where(AgentLoopObservation.run_id == run.run_id)
                .order_by(AgentLoopObservation.id.asc())
            ).all()
        )
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].iteration, 1)
        self.assertEqual(observations[0].step_index, 1)
        self.assertEqual(observations[0].next_action, "repair")
        self.assertEqual(observations[0].stop_action_reason, "required_tool_followup_missing")
        self.assertEqual(observations[0].root_cause_rule_id, "RC_REQUIRED_TOOL_FOLLOWUP_MISSING")
        self.assertEqual(observations[0].root_cause_primary, "required_tool_followup_missing")
        self.assertEqual(observations[0].mitigation_action, "repair_required_tool_followup")
        self.assertEqual(observations[0].observation_json["source"], "required_tool_followup_guard")
        self.assertEqual(observations[0].observation_json["after_tool"], missing_event.payload_json["after_tool"])
        self.assertEqual(observations[0].observation_json["required_tool"], missing_event.payload_json["required_tool"])
        repair_context = self.db.scalar(
            select(AgentContextBuild).where(
                AgentContextBuild.context_build_id == observations[0].decision_context_build_id
            )
        )
        self.assertIsNotNone(repair_context)
        metadata = repair_context.build_metadata_json or {}
        self.assertIn(
            {"name": "scenario-composition"},
            [{"name": item["name"]} for item in metadata["selected_agent_skills"]],
        )
        self.assertIn(
            {
                "skill_name": "scenario-composition",
                "routing_key": "routing_required_tool_after_success",
                "after_tool": "testcase.query_project_cases",
                "required_tool": "scenario.compose_draft",
            },
            [
                {
                    "skill_name": item["skill_name"],
                    "routing_key": item["routing_key"],
                    "after_tool": item["after_tool"],
                    "required_tool": item["required_tool"],
                }
                for item in metadata["matched_agent_skill_routing_rules"]
            ],
        )

    def test_conversation_runner_retries_fixable_failed_compose_tool(self):
        from app.models.project import ProjectEnvironment
        from app.models.test_case import TestCase

        environment = ProjectEnvironment(
            id=107,
            project_id=10,
            name="default",
            base_url="https://api.example.test",
            description="default env",
            is_default=True,
            is_deleted=False,
            created_by_id=self.owner.id,
        )
        case = TestCase(
            id=207,
            project_id=10,
            environment_id=107,
            name="Enterprise Company List",
            description="query companies",
            method="GET",
            path="/companies",
            headers={},
            query_params={},
            body_type="json",
            body=None,
            assertions=[],
            extractors=[],
            retry_policy=None,
            created_by_id=self.owner.id,
        )
        self.db.add_all([environment, case])
        self.db.commit()
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="请生成一个支持多个 companyId 数据集的企业场景草稿。",
                max_iterations=4,
            ),
            current_user=self.owner,
        )
        captured_messages = []
        skill_call_count = {"value": 0}
        test_case = self

        def fake_stream(self, payload):
            captured_messages.append(payload.messages)
            if len(captured_messages) == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"testcase.query_project_cases","input":{"project_id":10},'
                        '"reason":"查询用例","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            if len(captured_messages) == 2:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"scenario.compose_draft","input":{"project_id":10,'
                        '"environment_id":107,"input":{"requirement":"dataset workflow",'
                        '"http_test_case_ids":[207],"include_datasets":true,"self_validate":true,"max_nodes":3}},'
                        '"reason":"生成数据集场景","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            if len(captured_messages) == 3:
                repair_prompt = captured_messages[-1][-1].content
                test_case.assertIn("工具失败修复闭环", repair_prompt)
                test_case.assertIn("datasets", repair_prompt)
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"scenario.compose_draft","input":{"project_id":10,'
                        '"environment_id":107,"input":{"requirement":"dataset workflow with fixed schema",'
                        '"http_test_case_ids":[207],"include_datasets":true,"self_validate":true,'
                        '"extra_requirements":"修复 datasets schema：补充 dataset id，variables 使用 {name,type} 对象数组。",'
                        '"max_nodes":3}},'
                        '"reason":"修复数据集 schema 后重试","evidence_refs":[]}'
                        "\n```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "数据集场景草稿已修复。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        def fake_run_skill(self, *, skill_id, payload, current_user):
            skill_call_count["value"] += 1
            if skill_call_count["value"] == 1:
                raise HTTPException(
                    status_code=502,
                    detail="AI 返回场景结构校验失败: datasets.0.id missing; variables dict_type",
                )
            return {"scenario": {"name": "Dataset Workflow"}}

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch("app.services.agent_tool_service.AISkillService.run_skill", new=fake_run_skill),
        ):
            completed = AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=self.owner.id)

        calls = list(
            self.db.scalars(
                select(AgentToolCall).where(AgentToolCall.run_id == run.run_id).order_by(AgentToolCall.id.asc())
            ).all()
        )

        self.assertEqual(completed.status, "completed")
        self.assertEqual(
            [call.tool_name for call in calls],
            ["testcase.query_project_cases", "scenario.compose_draft", "scenario.compose_draft"],
        )
        self.assertEqual(calls[1].status, "failed")
        self.assertEqual(calls[2].status, "succeeded")
        self.assertEqual(completed.result_json["message"], "数据集场景草稿已修复。")

    def test_create_run_route_does_not_start_real_worker_in_sqlite_tests(self):
        from app.api.v1.routers.agents import create_agent_run

        with patch("app.api.v1.routers.agents.execution_worker.submit") as submit:
            payload = create_agent_run(
                payload=AgentRunCreateRequest(project_id=10, intent="route worker boundary"),
                db=self.db,
                current_user=self.owner,
            )["data"]

        submit.assert_not_called()
        self.assertEqual(payload["status"], "running")

    def test_agent_conversation_worker_starts_for_file_sqlite_and_non_sqlite_binds(self):
        from types import SimpleNamespace

        from app.api.v1.routers.agents import _should_start_agent_conversation_worker

        class FakeDb:
            def __init__(self, dialect_name: str, database: str | None):
                self.bind = SimpleNamespace(
                    dialect=SimpleNamespace(name=dialect_name),
                    url=SimpleNamespace(database=database),
                )

            def get_bind(self):
                return self.bind

        self.assertFalse(_should_start_agent_conversation_worker(FakeDb("sqlite", ":memory:")))
        self.assertFalse(_should_start_agent_conversation_worker(FakeDb("sqlite", "")))
        self.assertTrue(_should_start_agent_conversation_worker(FakeDb("sqlite", "devtestbackend.db")))
        self.assertTrue(_should_start_agent_conversation_worker(FakeDb("mysql", "devtestbackend")))

    def test_conversation_history_routes_return_server_side_history(self):
        from app.api.v1.routers.agents import (
            export_agent_conversation,
            get_agent_conversation_transcript,
            list_agent_conversation_runs,
            list_agent_conversations,
            list_agent_runs,
        )

        first = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="服务端历史第一轮"),
            current_user=self.owner,
        )
        second = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                conversation_id=first.conversation_id,
                intent="服务端历史第二轮",
            ),
            current_user=self.owner,
        )

        conversations = list_agent_conversations(project_id=10, db=self.db, current_user=self.member)["data"]
        runs = list_agent_conversation_runs(
            conversation_id=first.conversation_id,
            project_id=10,
            db=self.db,
            current_user=self.member,
        )["data"]
        all_runs = list_agent_runs(project_id=10, db=self.db, current_user=self.member)["data"]

        self.assertEqual(conversations[0]["conversation_id"], first.conversation_id)
        self.assertEqual(conversations[0]["run_count"], 2)
        self.assertEqual([run["run_id"] for run in runs], [second.run_id, first.run_id])
        self.assertIn(second.run_id, [run["run_id"] for run in all_runs])

        AgentRuntimeService(self.db).complete_run(first, {"message": "first answer", "model_invoked": False})
        transcript = get_agent_conversation_transcript(
            conversation_id=first.conversation_id,
            project_id=10,
            db=self.db,
            current_user=self.member,
        )["data"]
        self.assertEqual(list(AgentConversationTranscriptRead.model_fields), list(AGENT_CONVERSATION_TRANSCRIPT_FIELDS))
        self.assertEqual(list(transcript), list(AGENT_CONVERSATION_TRANSCRIPT_FIELDS))
        self.assertEqual(list(transcript["conversation"]), list(AGENT_CONVERSATION_FIELDS))
        self.assertEqual(transcript["conversation"]["conversation_id"], first.conversation_id)
        self.assertEqual(transcript["conversation"]["run_count"], 2)
        self.assertEqual([turn["run"]["run_id"] for turn in transcript["turns"]], [first.run_id, second.run_id])
        self.assertEqual(transcript["turns"][0]["assistant_message"], "first answer")
        self.assertTrue(transcript["turns"][0]["assistant_visible"])
        self.assertIsNone(transcript["turns"][1]["assistant_message"])
        self.assertFalse(transcript["turns"][1]["terminal"])

        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=first.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=self.owner,
            enqueue=False,
        )
        call.approval_required = True
        approval = ApprovalService(self.db).create_pending_approval(
            call=call,
            run=first,
            current_user=self.owner,
        )
        call.output_json_redacted = {"project": {"id": 10, "name": "TestAuto"}}
        block = AgentMigrationBlock(
            block_id="agent-migration-export-test",
            run_id=first.run_id,
            tool_call_id=call.tool_call_id,
            status="open",
            block_type="backend_contract",
            reason="export test migration block",
            backend_name="project",
            backend_operation="read_context",
            backend_contract_version="v1",
            required_migration_type="contract_refresh",
            details_json={"source": "conversation_export_test"},
        )
        self.db.add(block)
        self.db.commit()

        export_payload = export_agent_conversation(
            conversation_id=first.conversation_id,
            project_id=10,
            db=self.db,
            current_user=self.member,
        )["data"]

        self.assertEqual(list(AgentConversationExportRead.model_fields), list(AGENT_CONVERSATION_EXPORT_FIELDS))
        self.assertEqual(list(export_payload), list(AGENT_CONVERSATION_EXPORT_FIELDS))
        self.assertEqual(export_payload["export_format"], "agent_conversation_export_v1")
        self.assertEqual([turn["run"]["run_id"] for turn in export_payload["turns"]], [first.run_id, second.run_id])
        self.assertGreaterEqual(len(export_payload["events_by_run_id"][first.run_id]), 2)
        self.assertEqual(export_payload["tool_calls_by_run_id"][first.run_id][0]["tool_call_id"], call.tool_call_id)
        self.assertEqual(export_payload["tool_calls_by_run_id"][first.run_id][0]["output_json_redacted"], call.output_json_redacted)
        self.assertEqual(export_payload["approvals_by_run_id"][first.run_id][0]["approval_id"], approval.approval_id)
        self.assertEqual(export_payload["migration_blocks_by_run_id"][first.run_id][0]["block_id"], block.block_id)
        self.assertEqual(export_payload["derived_from"]["run_ids"], [first.run_id, second.run_id])

    def test_conversation_transcript_requires_project_access(self):
        outsider = User(
            id=4,
            username="outsider",
            account="outsider",
            password_hash="x",
            phone="10000000004",
            email="outsider@example.test",
            is_admin=False,
        )
        self.db.add(outsider)
        self.db.commit()
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="transcript scope"),
            current_user=self.owner,
        )

        with self.assertRaises(HTTPException) as ctx:
            AgentRuntimeService(self.db).get_conversation_transcript(
                project_id=10,
                conversation_id=run.conversation_id,
                current_user=outsider,
            )

        self.assertEqual(ctx.exception.status_code, 403)

    def test_harness_agent_run_payload_contract_matches_routes(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import cancel_agent_run, create_agent_run, get_agent_run

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Agent Run entity payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Agent Run entity payload contract:" in path.read_text(encoding="utf-8")
        ]
        created_payload = create_agent_run(
            payload=AgentRunCreateRequest(project_id=10, intent="run payload contract"),
            db=self.db,
            current_user=self.owner,
        )["data"]
        get_payload = get_agent_run(run_id=created_payload["run_id"], db=self.db, current_user=self.member)["data"]
        cancel_payload = cancel_agent_run(run_id=created_payload["run_id"], db=self.db, current_user=self.owner)["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(AGENT_RUN_FIELDS))
            self.assertEqual(contract["source"], "AgentRunRead")
        self.assertEqual(list(AgentRunRead.model_fields), list(AGENT_RUN_FIELDS))
        for payload in (created_payload, get_payload, cancel_payload):
            self.assertEqual(list(payload), list(AGENT_RUN_FIELDS))
            self.assertEqual(payload["project_id"], 10)
            self.assertEqual(payload["intent"], "run payload contract")
            self.assertTrue(payload["runtime_snapshot_id"].startswith("agent-snap-"))
        self.assertEqual(created_payload["status"], "running")
        self.assertEqual(get_payload["run_id"], created_payload["run_id"])
        self.assertEqual(cancel_payload["status"], "cancelled")

    def test_harness_agent_run_summary_payload_contract_matches_route(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import get_agent_run_summary

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Agent Run summary payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Agent Run summary payload contract:" in path.read_text(encoding="utf-8")
        ]
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="run summary payload contract"),
            current_user=self.owner,
        )

        payload = get_agent_run_summary(run_id=run.run_id, db=self.db, current_user=self.member)["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(AGENT_RUN_SUMMARY_FIELDS))
            self.assertEqual(contract["source"], "AgentRunSummaryRead")
        self.assertEqual(list(AgentRunSummaryRead.model_fields), list(AGENT_RUN_SUMMARY_FIELDS))
        self.assertEqual(list(payload), list(AGENT_RUN_SUMMARY_FIELDS))
        self.assertEqual(payload["run"]["run_id"], run.run_id)
        self.assertEqual(payload["event_count"], 2)
        self.assertEqual(payload["latest_event_types"], ["run.queued", "run.started"])
        self.assertFalse(payload["terminal"])
        self.assertTrue(payload["can_cancel"])

    def test_harness_agent_run_action_state_payload_contract_matches_route(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import get_agent_run_actions

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Agent Run action state payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Agent Run action state payload contract:" in path.read_text(encoding="utf-8")
        ]
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="run action payload contract"),
            current_user=self.owner,
        )
        payload = get_agent_run_actions(run_id=run.run_id, db=self.db, current_user=self.member)["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(AGENT_RUN_ACTION_STATE_FIELDS))
            self.assertEqual(contract["action_fields"], list(AGENT_RUN_ACTION_FIELDS))
            self.assertEqual(contract["action_ids"], [item["action_id"] for item in payload["actions"]])
            self.assertEqual(contract["source"], "AgentRunActionStateRead")
        self.assertEqual(list(AgentRunActionStateRead.model_fields), list(AGENT_RUN_ACTION_STATE_FIELDS))
        self.assertEqual(list(AgentRunActionRead.model_fields), list(AGENT_RUN_ACTION_FIELDS))
        self.assertEqual(list(payload), list(AGENT_RUN_ACTION_STATE_FIELDS))
        self.assertEqual(list(payload["actions"][0]), list(AGENT_RUN_ACTION_FIELDS))
        self.assertEqual(payload["actions"][0]["action_id"], "view_summary")

    def test_harness_agent_conversation_transcript_payload_contract_matches_route(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import get_agent_conversation_transcript

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Agent Conversation transcript payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Agent Conversation transcript payload contract:" in path.read_text(encoding="utf-8")
        ]
        first = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="transcript payload contract"),
            current_user=self.owner,
        )
        second = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                conversation_id=first.conversation_id,
                intent="transcript second turn",
            ),
            current_user=self.owner,
        )
        payload = get_agent_conversation_transcript(
            conversation_id=first.conversation_id,
            project_id=10,
            db=self.db,
            current_user=self.member,
        )["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(AGENT_CONVERSATION_TRANSCRIPT_FIELDS))
            self.assertEqual(contract["conversation_fields"], list(AGENT_CONVERSATION_FIELDS))
            self.assertEqual(contract["turn_fields"], list(AGENT_RUN_SUMMARY_FIELDS))
            self.assertEqual(contract["source"], "AgentConversationTranscriptRead")
        self.assertEqual(list(AgentConversationTranscriptRead.model_fields), list(AGENT_CONVERSATION_TRANSCRIPT_FIELDS))
        self.assertEqual(list(payload), list(AGENT_CONVERSATION_TRANSCRIPT_FIELDS))
        self.assertEqual(list(payload["conversation"]), list(AGENT_CONVERSATION_FIELDS))
        self.assertEqual(list(payload["turns"][0]), list(AGENT_RUN_SUMMARY_FIELDS))
        self.assertEqual([turn["run"]["run_id"] for turn in payload["turns"]], [first.run_id, second.run_id])

    def test_harness_agent_conversation_export_payload_contract_matches_route(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import export_agent_conversation

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Agent Conversation export payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Agent Conversation export payload contract:" in path.read_text(encoding="utf-8")
        ]
        first = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="export payload contract"),
            current_user=self.owner,
        )
        second = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                conversation_id=first.conversation_id,
                intent="export second turn",
            ),
            current_user=self.owner,
        )
        payload = export_agent_conversation(
            conversation_id=first.conversation_id,
            project_id=10,
            db=self.db,
            current_user=self.member,
        )["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(AGENT_CONVERSATION_EXPORT_FIELDS))
            self.assertEqual(contract["conversation_fields"], list(AGENT_CONVERSATION_FIELDS))
            self.assertEqual(contract["turn_fields"], list(AGENT_RUN_SUMMARY_FIELDS))
            self.assertEqual(contract["event_fields"], list(AGENT_EVENT_FIELDS))
            self.assertEqual(contract["tool_call_fields"], list(TOOL_CALL_FIELDS))
            self.assertEqual(contract["source"], "AgentConversationExportRead")
        self.assertEqual(list(AgentConversationExportRead.model_fields), list(AGENT_CONVERSATION_EXPORT_FIELDS))
        self.assertEqual(list(payload), list(AGENT_CONVERSATION_EXPORT_FIELDS))
        self.assertEqual(list(payload["conversation"]), list(AGENT_CONVERSATION_FIELDS))
        self.assertEqual(list(payload["turns"][0]), list(AGENT_RUN_SUMMARY_FIELDS))
        self.assertEqual(list(payload["events_by_run_id"][first.run_id][0]), list(AGENT_EVENT_FIELDS))
        self.assertEqual(payload["export_format"], "agent_conversation_export_v1")
        self.assertEqual(payload["derived_from"]["run_ids"], [first.run_id, second.run_id])

    def test_harness_agent_conversation_smoke_payload_contract_matches_route(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import run_agent_conversation_smoke

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Agent Conversation smoke payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Agent Conversation smoke payload contract:" in path.read_text(encoding="utf-8")
        ]

        def fake_stream(self, payload):
            yield {"type": "delta", "content": "Agent smoke ok"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream):
            payload = run_agent_conversation_smoke(
                payload=AgentConversationSmokeRequest(project_id=10, intent="contract smoke", max_iterations=1),
                db=self.db,
                current_user=self.admin,
            )["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(AGENT_CONVERSATION_SMOKE_FIELDS))
            self.assertEqual(contract["run_summary_fields"], list(AGENT_RUN_SUMMARY_FIELDS))
            self.assertEqual(contract["source"], "AgentConversationSmokeRead")
        self.assertEqual(list(AgentConversationSmokeRead.model_fields), list(AGENT_CONVERSATION_SMOKE_FIELDS))
        self.assertEqual(list(payload), list(AGENT_CONVERSATION_SMOKE_FIELDS))
        self.assertEqual(list(payload["run_summary"]), list(AGENT_RUN_SUMMARY_FIELDS))
        self.assertTrue(payload["first_delta_received"])
        self.assertTrue(payload["completed"])

    def test_harness_runtime_snapshot_payload_contract_matches_route(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import create_agent_run, get_agent_runtime_snapshot

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required RuntimeSnapshot entity payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required RuntimeSnapshot entity payload contract:" in path.read_text(encoding="utf-8")
        ]
        run_payload = create_agent_run(
            payload=AgentRunCreateRequest(project_id=10, intent="snapshot payload contract"),
            db=self.db,
            current_user=self.owner,
        )["data"]
        snapshot_payload = get_agent_runtime_snapshot(
            snapshot_id=run_payload["runtime_snapshot_id"],
            db=self.db,
            current_user=self.member,
        )["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(RUNTIME_SNAPSHOT_FIELDS))
            self.assertEqual(contract["source"], "AgentRuntimeSnapshotRead")
        self.assertEqual(list(AgentRuntimeSnapshotRead.model_fields), list(RUNTIME_SNAPSHOT_FIELDS))
        self.assertEqual(list(snapshot_payload), list(RUNTIME_SNAPSHOT_FIELDS))
        self.assertEqual(snapshot_payload["snapshot_id"], run_payload["runtime_snapshot_id"])
        self.assertEqual(snapshot_payload["project_id"], 10)
        self.assertEqual(snapshot_payload["created_by"], self.owner.id)
        self.assertTrue(snapshot_payload["runtime_hash"])
        self.assertGreaterEqual(len(snapshot_payload["tools_json"]), 1)
        self.assertIn("tools", snapshot_payload["manifests_json"])

    def test_harness_agent_event_payload_contract_matches_event_store(self):
        from pathlib import Path
        import re

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Agent Event entity payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Agent Event entity payload contract:" in path.read_text(encoding="utf-8")
        ]
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="event payload contract", auto_complete=True),
            current_user=self.owner,
        )
        events, listed_run = AgentRuntimeService(self.db).list_events(run_id=run.run_id, after_sequence=0)
        payloads = [AgentEventRead.model_validate(item).model_dump(mode="python") for item in events]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(AGENT_EVENT_FIELDS))
            self.assertEqual(contract["source"], "AgentEventRead")
        self.assertEqual(list(AgentEventRead.model_fields), list(AGENT_EVENT_FIELDS))
        self.assertEqual(listed_run.run_id, run.run_id)
        self.assertEqual([payload["event_seq"] for payload in payloads], [1, 2, 3])
        self.assertEqual([payload["event_type"] for payload in payloads], ["run.queued", "run.started", "run.completed"])
        for payload in payloads:
            self.assertEqual(list(payload), list(AGENT_EVENT_FIELDS))
            self.assertEqual(payload["payload_json"]["schema_version"], 1)
            self.assertEqual(payload["payload_json"]["run_id"], run.run_id)
            self.assertEqual(payload["payload_json"]["project_id"], 10)
            self.assertEqual(payload["payload_json"]["event_seq"], payload["event_seq"])
            self.assertEqual(payload["payload_json"]["event_type"], payload["event_type"])

    def test_harness_run_event_snapshot_payload_contract_matches_route(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import get_agent_run_event_snapshot

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Agent Run event snapshot payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Agent Run event snapshot payload contract:" in path.read_text(encoding="utf-8")
        ]
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="event snapshot payload contract", auto_complete=True),
            current_user=self.owner,
        )
        payload = get_agent_run_event_snapshot(
            run_id=run.run_id,
            after_sequence=0,
            limit=10,
            db=self.db,
            current_user=self.member,
        )["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(AGENT_RUN_EVENT_SNAPSHOT_FIELDS))
            self.assertEqual(contract["event_fields"], list(AGENT_EVENT_FIELDS))
            self.assertEqual(contract["source"], "AgentRunEventSnapshotRead")
        self.assertEqual(list(AgentRunEventSnapshotRead.model_fields), list(AGENT_RUN_EVENT_SNAPSHOT_FIELDS))
        self.assertEqual(list(payload), list(AGENT_RUN_EVENT_SNAPSHOT_FIELDS))
        self.assertEqual(list(payload["events"][0]), list(AGENT_EVENT_FIELDS))
        self.assertEqual(payload["latest_event_sequence"], run.last_event_sequence)
        self.assertEqual(payload["next_after_sequence"], run.last_event_sequence)
        self.assertTrue(payload["terminal"])

    def test_harness_context_build_payload_contract_matches_routes(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import create_agent_context_build, list_agent_context_builds

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required ContextBuild entity payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required ContextBuild entity payload contract:" in path.read_text(encoding="utf-8")
        ]
        run = self._create_run("context build payload contract")
        create_payload = create_agent_context_build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=512,
                model_name="contract-model",
                required_evidence_ref_ids=["case-required"],
                prompt_object_key="prompts/agent/context-contract.json",
            ),
            db=self.db,
            current_user=self.owner,
        )["data"]
        list_payload = list_agent_context_builds(run_id=run.run_id, db=self.db, current_user=self.member)["data"][0]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(CONTEXT_BUILD_FIELDS))
            self.assertEqual(contract["source"], "AgentContextBuildRead")
        self.assertEqual(list(AgentContextBuildRead.model_fields), list(CONTEXT_BUILD_FIELDS))
        for payload in (create_payload, list_payload):
            self.assertEqual(list(payload), list(CONTEXT_BUILD_FIELDS))
            self.assertEqual(payload["run_id"], run.run_id)
            self.assertEqual(payload["build_purpose"], "repair")
            self.assertEqual(payload["model_name"], "contract-model")
            self.assertEqual(payload["token_budget"], 512)
            self.assertEqual(payload["required_evidence_refs_json"], ["case-required"])
            self.assertTrue(payload["required_evidence_complete"])
            self.assertEqual(payload["decision_quality_risk"], "low")
            self.assertEqual(payload["prompt_object_key"], "prompts/agent/context-contract.json")
            self.assertTrue(payload["prompt_hash"])
        self.assertEqual(list_payload["context_build_id"], create_payload["context_build_id"])

    def test_harness_loop_observation_payload_contract_matches_routes(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import (
            create_agent_context_build,
            create_agent_loop_observation,
            list_agent_loop_observations,
        )

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required LoopObservation entity payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required LoopObservation entity payload contract:" in path.read_text(encoding="utf-8")
        ]
        run = self._create_run("loop observation payload contract")
        context_payload = create_agent_context_build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(build_purpose="repair", step_index=0),
            db=self.db,
            current_user=self.owner,
        )["data"]
        create_payload = create_agent_loop_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=context_payload["context_build_id"],
                next_action="repair",
                next_action_is_high_risk=False,
                reasons=["same_failure_no_progress"],
                observation={"retry_count": 2},
            ),
            db=self.db,
            current_user=self.owner,
        )["data"]
        list_payload = list_agent_loop_observations(run_id=run.run_id, db=self.db, current_user=self.member)["data"][0]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(LOOP_OBSERVATION_FIELDS))
            self.assertEqual(contract["source"], "AgentLoopObservationRead")
        self.assertEqual(list(AgentLoopObservationRead.model_fields), list(LOOP_OBSERVATION_FIELDS))
        for payload in (create_payload, list_payload):
            self.assertEqual(list(payload), list(LOOP_OBSERVATION_FIELDS))
            self.assertEqual(payload["run_id"], run.run_id)
            self.assertEqual(payload["decision_context_build_id"], context_payload["context_build_id"])
            self.assertEqual(payload["decision_context_degradation_level"], context_payload["context_degradation_level"])
            self.assertTrue(payload["required_evidence_complete_for_decision"])
            self.assertEqual(payload["next_action"], "repair")
            self.assertFalse(payload["next_action_is_high_risk"])
            self.assertEqual(payload["stop_action_reason"], "same_failure_no_progress")
            self.assertEqual(payload["stop_reasons_all_json"], ["same_failure_no_progress"])
            self.assertEqual(payload["root_cause_rule_id"], "RC_NO_PROGRESS_PURE")
            self.assertEqual(payload["root_cause_primary"], "same_failure_no_progress")
            self.assertEqual(payload["observation_json"]["retry_count"], 2)
        self.assertEqual(list_payload["observation_id"], create_payload["observation_id"])

    def test_cancelled_run_rejects_new_tool_call_with_obsolete_error_code(self):
        run = self._create_run("cancel before planning")
        AgentRuntimeService(self.db).cancel_run(run_id=run.run_id, current_user=self.owner)
        before_tool_call_count = self.db.query(AgentToolCall).count()

        with self.assertRaises(HTTPException) as ctx:
            ExecutionLedgerService(self.db).create_tool_call(
                payload=AgentToolCallCreateRequest(
                    run_id=run.run_id,
                    tool_name="project.read_context",
                    input={"project_id": 10},
                    step_index=0,
                ),
                current_user=self.owner,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "tool_call_obsolete")
        self.assertEqual(self.db.query(AgentToolCall).count(), before_tool_call_count)

    def test_harness_tool_call_entity_payload_contract_matches_routes(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import approve_agent_tool_call, get_agent_tool_call, reject_agent_tool_call

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required ToolCall entity payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required ToolCall entity payload contract:" in path.read_text(encoding="utf-8")
        ]
        _, approved_call, approval = self._create_pending_approval()
        get_payload = get_agent_tool_call(
            tool_call_id=approved_call.tool_call_id,
            db=self.db,
            current_user=self.member,
        )["data"]
        approve_payload = approve_agent_tool_call(
            tool_call_id=approved_call.tool_call_id,
            payload=self._approval_decision(approval),
            db=self.db,
            current_user=self.owner,
        )["data"]
        _, rejected_call, rejected_approval = self._create_pending_approval()
        reject_payload = reject_agent_tool_call(
            tool_call_id=rejected_call.tool_call_id,
            payload=self._approval_decision(rejected_approval, reason="contract reject"),
            db=self.db,
            current_user=self.owner,
        )["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(TOOL_CALL_FIELDS))
            self.assertEqual(contract["source"], "AgentToolCallRead")
        self.assertEqual(list(AgentToolCallRead.model_fields), list(TOOL_CALL_FIELDS))
        for payload in (get_payload, approve_payload["tool_call"], reject_payload["tool_call"]):
            self.assertEqual(list(payload), list(TOOL_CALL_FIELDS))
            self.assertEqual(payload["tool_name"], "project.read_context")
        self.assertEqual(get_payload["current_approval"]["approval_id"], approval.approval_id)
        self.assertEqual(get_payload["approval_lineage"]["approval_lineage_id"], approval.approval_lineage_id)
        self.assertEqual(get_payload["recent_reconcile_attempts"], [])
        self.assertEqual(approve_payload["tool_call"]["runtime_snapshot_id"], get_payload["runtime_snapshot_id"])
        self.assertEqual(reject_payload["tool_call"]["runtime_snapshot_id"], reject_payload["approval"]["runtime_snapshot_id"])
        self.assertEqual(approve_payload["tool_call"]["status"], "planned")
        self.assertEqual(reject_payload["tool_call"]["status"], "manual_intervention")

    def test_append_event_outbox_write_failure_returns_frozen_error_code_and_rolls_back(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="outbox write failure"),
            current_user=self.owner,
        )
        run_id = run.run_id
        run_db_id = run.id
        before_sequence = run.last_event_sequence
        before_event_count = self.db.query(AgentEvent).filter(AgentEvent.run_id == run_id).count()
        before_outbox_count = self.db.query(AgentOutbox).count()

        def broken_outbox(**kwargs):
            return AgentOutbox(event_id=None, status=kwargs["status"])

        with patch("app.services.agent_runtime_service.AgentOutbox", side_effect=broken_outbox):
            with self.assertRaises(HTTPException) as ctx:
                AgentRuntimeService(self.db).append_event(run, "run.test_failed_outbox", {}, commit=True)

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(ctx.exception.detail["code"], "event_outbox_write_failed")
        self.db.expire_all()
        refreshed = self.db.get(AgentRun, run_db_id)
        self.assertEqual(refreshed.last_event_sequence, before_sequence)
        self.assertEqual(self.db.query(AgentEvent).filter(AgentEvent.run_id == run_id).count(), before_event_count)
        self.assertEqual(self.db.query(AgentOutbox).count(), before_outbox_count)

    def test_event_replay_audit_verifies_last_event_id_replay_window(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="replay audit", auto_complete=True),
            current_user=self.owner,
        )

        audit = AgentEventReplayAuditService(self.db).audit_run(run_id=run.run_id, after_sequence=1)

        self.assertTrue(audit["replayable"])
        self.assertTrue(audit["replay_cursor_valid"])
        self.assertEqual(audit["last_event_sequence"], 3)
        self.assertEqual(audit["event_count"], 3)
        self.assertEqual(audit["replay_event_count"], 2)
        self.assertEqual(audit["first_replay_event_seq"], 2)
        self.assertEqual(audit["last_replay_event_seq"], 3)
        self.assertEqual(audit["missing_sequences"], [])

    def test_harness_event_replay_audit_payload_contract_matches_service(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import (
            audit_agent_event_replay_stress,
            audit_agent_run_event_replay,
        )

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Event Replay audit payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Event Replay audit payload contract:" in path.read_text(encoding="utf-8")
        ]
        runs = [
            AgentRuntimeService(self.db).create_run(
                payload=AgentRunCreateRequest(project_id=10, intent=f"replay contract {index}", auto_complete=True),
                current_user=self.owner,
            )
            for index in range(2)
        ]

        run_audit = AgentEventReplayAuditService(self.db).audit_run(run_id=runs[0].run_id, after_sequence=1)
        run_route_payload = audit_agent_run_event_replay(
            run_id=runs[0].run_id,
            after_sequence=1,
            db=self.db,
            current_user=self.owner,
        )["data"]
        stress_audit = AgentEventReplayAuditService(self.db).audit_project(
            project_id=10,
            sample_limit=2,
            cursor_count=3,
        )
        stress_route_payload = audit_agent_event_replay_stress(
            project_id=10,
            sample_limit=2,
            cursor_count=3,
            db=self.db,
            current_user=self.owner,
        )["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["run_fields"], list(EVENT_REPLAY_AUDIT_FIELDS))
            self.assertEqual(contract["stress_fields"], list(EVENT_REPLAY_STRESS_AUDIT_FIELDS))
            self.assertEqual(contract["stress_run_fields"], list(EVENT_REPLAY_STRESS_RUN_FIELDS))
            self.assertEqual(contract["cursor_fields"], list(EVENT_REPLAY_CURSOR_AUDIT_FIELDS))
            self.assertEqual(contract["derived_from_fields"], list(EVENT_REPLAY_DERIVED_FROM_FIELDS))
            self.assertEqual(contract["source"], "AgentEventReplayAuditService")
        self.assertEqual(list(AgentEventReplayAuditRead.model_fields), list(EVENT_REPLAY_AUDIT_FIELDS))
        self.assertEqual(list(AgentEventReplayStressAuditRead.model_fields), list(EVENT_REPLAY_STRESS_AUDIT_FIELDS))
        self.assertEqual(list(run_audit), list(EVENT_REPLAY_AUDIT_FIELDS))
        self.assertEqual(list(run_route_payload), list(EVENT_REPLAY_AUDIT_FIELDS))
        self.assertEqual(list(stress_audit), list(EVENT_REPLAY_STRESS_AUDIT_FIELDS))
        self.assertEqual(list(stress_route_payload), list(EVENT_REPLAY_STRESS_AUDIT_FIELDS))
        self.assertTrue(all(list(item) == list(EVENT_REPLAY_STRESS_RUN_FIELDS) for item in stress_audit["run_audits"]))
        self.assertTrue(
            all(list(item) == list(EVENT_REPLAY_STRESS_RUN_FIELDS) for item in stress_route_payload["run_audits"])
        )
        self.assertTrue(
            all(
                list(cursor) == list(EVENT_REPLAY_CURSOR_AUDIT_FIELDS)
                for item in stress_audit["run_audits"]
                for cursor in item["cursor_audits"]
            )
        )
        self.assertEqual(list(stress_audit["derived_from"]), list(EVENT_REPLAY_DERIVED_FROM_FIELDS))
        self.assertEqual(list(stress_route_payload["derived_from"]), list(EVENT_REPLAY_DERIVED_FROM_FIELDS))

    def test_event_replay_gap_is_reported_in_metrics_and_alerts(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="replay gap", auto_complete=True),
            current_user=self.owner,
        )
        missing = self.db.scalar(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id, AgentEvent.event_seq == 2)
        )
        self.db.delete(missing)
        self.db.commit()

        audit = AgentEventReplayAuditService(self.db).audit_run(run_id=run.run_id)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        alerts = {item["alert_id"]: item for item in alert_snapshot["alerts"]}
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertFalse(audit["replayable"])
        self.assertEqual(audit["missing_sequences"], [2])
        self.assertEqual(metrics["event_replay_gap_total"], 1)
        self.assertIn("agent_event_replay_gap", alerts)
        self.assertEqual(alerts["agent_event_replay_gap"]["severity"], "P1")
        self.assertEqual(alerts["agent_event_replay_gap"]["runbook_id"], "event_replay_recovery")
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P1")
        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "attention")

    def test_event_replay_stress_audit_samples_multiple_runs_and_cursors(self):
        for index in range(5):
            AgentRuntimeService(self.db).create_run(
                payload=AgentRunCreateRequest(project_id=10, intent=f"replay stress {index}", auto_complete=True),
                current_user=self.owner,
            )

        audit = AgentEventReplayAuditService(self.db).audit_project(project_id=10, sample_limit=5, cursor_count=3)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertTrue(audit["high_concurrency_replayable"])
        self.assertEqual(audit["audited_run_count"], 5)
        self.assertEqual(audit["cursor_window_count"], 15)
        self.assertEqual(audit["failed_run_count"], 0)
        self.assertEqual(audit["invalid_cursor_count"], 0)
        self.assertEqual(audit["max_replay_window_events"], 3)
        self.assertEqual(metrics["event_replay_stress_failed_total"], 0)
        self.assertEqual(metrics["event_replay_stress_cursor_window_total"], 15)
        self.assertEqual(metrics["event_replay_stress_max_window_events"], 3)

    def test_event_replay_stress_audit_reports_failed_run_and_alert(self):
        ok_run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="replay stress ok", auto_complete=True),
            current_user=self.owner,
        )
        broken_run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="replay stress broken", auto_complete=True),
            current_user=self.owner,
        )
        missing = self.db.scalar(
            select(AgentEvent).where(AgentEvent.run_id == broken_run.run_id, AgentEvent.event_seq == 2)
        )
        self.db.delete(missing)
        self.db.commit()

        audit = AgentEventReplayAuditService(self.db).audit_project(project_id=10, sample_limit=10, cursor_count=3)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        alerts = {
            item["alert_id"]: item
            for item in alert_snapshot["alerts"]
        }
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertFalse(audit["high_concurrency_replayable"])
        self.assertEqual(audit["failed_run_count"], 1)
        self.assertIn(broken_run.run_id, audit["failed_run_ids"])
        self.assertNotIn(ok_run.run_id, audit["failed_run_ids"])
        self.assertEqual(metrics["event_replay_stress_failed_total"], 1)
        self.assertIn("agent_event_replay_stress_failed", alerts)
        self.assertEqual(alerts["agent_event_replay_stress_failed"]["severity"], "P1")
        self.assertEqual(alerts["agent_event_replay_stress_failed"]["runbook_id"], "event_replay_recovery")
        self.assertEqual(
            alerts["agent_event_replay_stress_failed"]["details"]["related_metrics"]["event_replay_stress_cursor_window_total"],
            metrics["event_replay_stress_cursor_window_total"],
        )
        self.assertEqual(
            alerts["agent_event_replay_stress_failed"]["details"]["related_metrics"]["event_replay_stress_max_window_events"],
            metrics["event_replay_stress_max_window_events"],
        )
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P1")
        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "attention")

    def test_create_run_reuses_snapshot_for_same_runtime_hash(self):
        first = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="first"),
            current_user=self.owner,
        )
        second = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="second"),
            current_user=self.owner,
        )

        self.assertEqual(first.runtime_snapshot_id, second.runtime_snapshot_id)

    def test_conversation_system_prompt_keeps_tool_registry_stable_for_prompt_cache(self):
        from app.services.agent_skill_registry import AgentSkillRegistry
        from app.services.agent_tool_service import ToolRegistry

        registry = ToolRegistry()
        skill_registry = AgentSkillRegistry()
        tool_names = [spec.name for spec in registry.list_specs()]
        skill_names = [skill.name for skill in skill_registry.list_skills()]
        first_prompt = _conversation_system_prompt()
        second_prompt = _conversation_system_prompt()

        self.assertEqual(tool_names, sorted(tool_names))
        self.assertEqual(skill_names, sorted(skill_names))
        self.assertEqual(first_prompt, second_prompt)
        self.assertIn('[{"approval_required":', first_prompt)
        self.assertLess(first_prompt.index('"approval_required"'), first_prompt.index('"input_schema"'))
        self.assertLess(first_prompt.index('"input_schema"'), first_prompt.index('"name"'))
        self.assertIn('"name":"scenario-composition"', first_prompt)
        self.assertIn("Codex 式渐进加载", first_prompt)

    def test_tool_registry_builtin_specs_declare_executable_backend_handlers(self):
        from app.services.agent_tool_service import AgentToolBackend, ToolRegistry

        backend = AgentToolBackend(self.db)

        for spec in ToolRegistry().list_specs():
            self.assertIsNotNone(spec.backend_handler, spec.name)
            self.assertTrue(callable(getattr(backend, spec.backend_handler or "", None)), spec.name)
            self.assertNotIn("backend_handler", spec.to_json())
            self.assertNotIn("required_successful_tool_before", spec.to_json())
            self.assertNotIn("missing_prerequisite_error_code", spec.to_json())
            self.assertNotIn("tool_result_repair_guidance", spec.to_json())

        scenario_spec = ToolRegistry().get("scenario.compose_draft")
        self.assertEqual(scenario_spec.required_successful_tool_before, "testcase.query_project_cases")
        self.assertEqual(scenario_spec.missing_prerequisite_error_code, "scenario_compose_requires_case_query")
        self.assertIn("scenario.compose_draft", scenario_spec.tool_result_repair_guidance or "")

    def test_agent_tool_backend_delegates_handler_resolution_to_router(self):
        from app.services.agent_tool_service import AgentToolBackend, RoutedTool, ToolRegistry

        registry = ToolRegistry()
        calls = []

        def fake_handler(payload, current_user):
            return {
                "handled_by": "fake-router",
                "project_id": payload["project_id"],
                "user_id": current_user.id,
            }

        class FakeRouter:
            def resolve(self, *, tool_name, backend):
                calls.append({"tool_name": tool_name, "backend": backend})
                return RoutedTool(
                    spec=registry.get("project.read_context"),
                    handler=fake_handler,
                )

        backend = AgentToolBackend(self.db, router=FakeRouter())

        result = backend.execute(
            tool_name="custom.external_tool",
            payload={"project_id": 10},
            current_user=self.owner,
        )

        self.assertEqual(result["handled_by"], "fake-router")
        self.assertEqual(result["project_id"], 10)
        self.assertEqual(result["user_id"], self.owner.id)
        self.assertEqual(calls, [{"tool_name": "custom.external_tool", "backend": backend}])

    def test_agent_skill_registry_selects_relevant_skills_by_intent(self):
        from app.services.agent_skill_registry import AgentSkillRegistry

        registry = AgentSkillRegistry()

        general = registry.select_for_intent("边界值分析和等价类划分有什么区别？")
        scenario = registry.select_for_intent("请基于当前项目已有用例组合企业场景草稿，不要保存")
        report = registry.select_for_intent("请读取当前项目测试报告摘要并分析失败原因")
        project = registry.select_for_intent("请读取当前项目上下文和真实用例")
        http_case = registry.select_for_intent("generate HTTP API test case and validate assertions")
        websocket_case = registry.select_for_intent("design WebSocket handshake message sequence and receive assertions")
        execution = registry.select_for_intent("diagnose recent execution failure and SSE stuck state")
        defect = registry.select_for_intent("draft a defect from failed result and classify severity")
        capture = registry.select_for_intent("clean browser capture traffic and convert to API test cases")
        environment = registry.select_for_intent("inspect current project default environment variables and base_url")
        flow = registry.select_for_intent("review visual flow DAG nodes conditions and delay strategy")
        test_plan = registry.select_for_intent("design regression test plan coverage and release readiness")
        permission = registry.select_for_intent("troubleshoot project member permission 403 access")
        api_definition = registry.select_for_intent("review OpenAPI import API definition endpoint catalog")
        dataset = registry.select_for_intent("design dataset records parameterization for data-driven scenario")
        media = registry.select_for_intent("review MinIO screenshot attachment evidence redaction")
        agent_ops = registry.select_for_intent("diagnose agent runtime readiness runbook SSE model.delta stuck")
        security = registry.select_for_intent("design JWT token auth permission and rate limit tests")
        mock = registry.select_for_intent("design mock service virtualization stubs for unstable dependency")
        ci = registry.select_for_intent("integrate CI pipeline webhook release gate promotion checks")
        archive = registry.select_for_intent("plan PDF report archive export trend retention")
        batch = registry.select_for_intent("optimize batch execution queue retry timeout worker scheduling")
        binding = registry.select_for_intent("repair extractor path assertion variable binding from upstream response")
        error_contract = registry.select_for_intent("debug 422 validation failed ErrorResponse request_id frontend display")
        ai_skill_runtime = registry.select_for_intent("diagnose AI Skill Run generated draft JSON schema validation failure")
        asset_lifecycle = registry.select_for_intent("organize test asset tags folders copy delete dependency version history")
        notification = registry.select_for_intent("configure SMTP webhook notification alert for failed test plan run")
        privacy = registry.select_for_intent("redact token PII signed URL secrets from report logs and AI prompt")
        migration = registry.select_for_intent("plan Alembic migration rollback backward compatibility legacy data repair")

        self.assertEqual(general[0].name, "general-testing-answer")
        self.assertIn("scenario-composition", [skill.name for skill in scenario])
        self.assertIn("report-summary", [skill.name for skill in report])
        self.assertIn("project-context", [skill.name for skill in project])
        self.assertEqual(http_case[0].name, "http-test-case-design")
        self.assertEqual(websocket_case[0].name, "websocket-test-case-design")
        self.assertEqual(execution[0].name, "execution-diagnosis")
        self.assertEqual(defect[0].name, "defect-triage")
        self.assertEqual(capture[0].name, "browser-capture-analysis")
        self.assertEqual(environment[0].name, "environment-config-management")
        self.assertEqual(flow[0].name, "visual-flow-design")
        self.assertEqual(test_plan[0].name, "test-plan-management")
        self.assertEqual(permission[0].name, "project-permission-admin")
        self.assertEqual(api_definition[0].name, "api-definition-import")
        self.assertEqual(dataset[0].name, "dataset-parameterization")
        self.assertEqual(media[0].name, "media-evidence-management")
        self.assertEqual(agent_ops[0].name, "agent-runtime-operations")
        self.assertEqual(security[0].name, "security-auth-testing")
        self.assertEqual(mock[0].name, "mock-service-virtualization")
        self.assertEqual(ci[0].name, "ci-release-integration")
        self.assertEqual(archive[0].name, "report-archive-export")
        self.assertEqual(batch[0].name, "batch-execution-scheduling")
        self.assertEqual(binding[0].name, "assertion-extractor-binding")
        self.assertEqual(error_contract[0].name, "api-error-contract-debugging")
        self.assertEqual(ai_skill_runtime[0].name, "ai-skill-runtime-governance")
        self.assertEqual(asset_lifecycle[0].name, "test-asset-lifecycle")
        self.assertEqual(notification[0].name, "notification-alerting-config")
        self.assertEqual(privacy[0].name, "data-privacy-redaction")
        self.assertEqual(migration[0].name, "migration-compatibility-planning")
        self.assertIn("generate HTTP test case", registry.private_list("http-test-case-design", "routing_requires_tool"))
        self.assertIn("generate WebSocket test case", registry.private_list("websocket-test-case-design", "routing_requires_tool"))
        self.assertIn("real execution result", registry.private_list("execution-diagnosis", "routing_requires_tool"))
        self.assertIn("default environment", registry.private_list("environment-config-management", "routing_requires_tool"))
        self.assertIn("real flow execution", registry.private_list("visual-flow-design", "routing_requires_tool"))
        self.assertIn("plan report", registry.private_list("test-plan-management", "routing_requires_tool"))
        self.assertIn("project access", registry.private_list("project-permission-admin", "routing_requires_tool"))
        self.assertIn("current API definition", registry.private_list("api-definition-import", "routing_requires_tool"))
        self.assertIn("dataset records", registry.private_list("dataset-parameterization", "routing_requires_tool"))
        self.assertIn("real attachment", registry.private_list("media-evidence-management", "routing_requires_tool"))
        self.assertIn("real agent event", registry.private_list("agent-runtime-operations", "routing_requires_tool"))
        self.assertIn("real auth failure", registry.private_list("security-auth-testing", "routing_requires_tool"))
        self.assertIn("real mock service", registry.private_list("mock-service-virtualization", "routing_requires_tool"))
        self.assertIn("real release gate", registry.private_list("ci-release-integration", "routing_requires_tool"))
        self.assertIn("real report archive", registry.private_list("report-archive-export", "routing_requires_tool"))
        self.assertIn("real batch execution", registry.private_list("batch-execution-scheduling", "routing_requires_tool"))
        self.assertIn("real extractor failure", registry.private_list("assertion-extractor-binding", "routing_requires_tool"))
        self.assertIn("real API error", registry.private_list("api-error-contract-debugging", "routing_requires_tool"))
        self.assertIn("real AI skill run", registry.private_list("ai-skill-runtime-governance", "routing_requires_tool"))
        self.assertIn("real asset dependency", registry.private_list("test-asset-lifecycle", "routing_requires_tool"))
        self.assertIn("real notification config", registry.private_list("notification-alerting-config", "routing_requires_tool"))
        self.assertIn("real sensitive leak", registry.private_list("data-privacy-redaction", "routing_requires_tool"))
        self.assertIn("real migration state", registry.private_list("migration-compatibility-planning", "routing_requires_tool"))
        self.assertIn("边界值", general[0].triggers)
        self.assertIn("当前项目", registry.private_list("project-context", "routing_requires_tool"))
        self.assertIn("报告摘要", registry.private_list("report-summary", "routing_requires_tool"))
        self.assertIn("场景草稿", registry.private_list("scenario-composition", "routing_requires_tool"))
        self.assertTrue(any(
            rule.startswith(
                "after=testcase.query_project_cases; require=scenario.compose_draft; "
                "min_total_fields=http_total,websocket_total; intent_markers="
            )
            for rule in registry.private_list("scenario-composition", "routing_required_tool_after_success")
        ))
        self.assertTrue(registry.private_list("scenario-composition", "guard_unsupported_capability"))
        self.assertIn("保存", registry.private_list("scenario-composition", "guard_scenario_save_intent"))
        self.assertIn("场景", registry.private_list("scenario-composition", "guard_scenario_save_subject"))
        self.assertEqual(
            registry.private_value("scenario-composition", "guard_scenario_save_classifier_prompt"),
            "save-intent-classifier.md",
        )
        self.assertIn(
            "意图分类器",
            registry.private_resource_text("scenario-composition", "guard_scenario_save_classifier_prompt") or "",
        )
        self.assertNotIn("triggers", general[0].metadata())
        self.assertNotIn("routing_hints", general[0].metadata())
        self.assertNotIn("routing_requires_tool", http_case[0].metadata())
        self.assertNotIn("routing_requires_tool", http_case[0].prompt_block())

    def test_required_tool_routing_uses_skill_private_hints(self):
        self.assertTrue(_intent_likely_requires_agent_tool("请读取当前项目上下文和真实用例"))
        self.assertTrue(_intent_likely_requires_agent_tool("请总结当前项目最近报告摘要"))
        self.assertTrue(_intent_likely_requires_agent_tool("请基于已有用例生成场景草稿"))
        self.assertTrue(_intent_likely_requires_agent_tool("generate HTTP test case"))
        self.assertTrue(_intent_likely_requires_agent_tool("generate WebSocket test case"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real execution result"))
        self.assertTrue(_intent_likely_requires_agent_tool("read default environment"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real flow execution"))
        self.assertTrue(_intent_likely_requires_agent_tool("read plan report"))
        self.assertTrue(_intent_likely_requires_agent_tool("check project access"))
        self.assertTrue(_intent_likely_requires_agent_tool("read current API definition"))
        self.assertTrue(_intent_likely_requires_agent_tool("read dataset records"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real attachment"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real agent event"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real auth failure"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real mock service"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real release gate"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real report archive"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real batch execution"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real extractor failure"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real API error"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real AI skill run"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real asset dependency"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real notification config"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real sensitive leak"))
        self.assertTrue(_intent_likely_requires_agent_tool("read real migration state"))
        self.assertFalse(_intent_likely_requires_agent_tool("边界值分析和等价类划分有什么区别？"))
        self.assertFalse(_intent_likely_requires_agent_tool("场景测试和普通接口用例有什么区别？"))
        self.assertFalse(_intent_likely_requires_agent_tool("draft a defect template without reading project data"))

        rules = _required_tool_followup_rules_for_intent("请基于已有用例生成场景草稿")
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].after_tool, "testcase.query_project_cases")
        self.assertEqual(rules[0].required_tool, "scenario.compose_draft")
        self.assertEqual(rules[0].min_total_fields, ("http_total", "websocket_total"))
        self.assertTrue(rules[0].intent_markers)
        self.assertEqual(
            _required_tool_followup_rules_for_intent(
                "Please read current project context, test resources, default environment, and whether existing scenario exists."
            ),
            (),
        )

    def test_unsupported_capability_guard_uses_skill_private_routing_hints(self):
        guards = _unsupported_capability_guards_for_intent("请把刚才的草稿保存为正式场景")

        self.assertEqual(len(guards), 1)
        self.assertEqual(guards[0].skill_name, "scenario-composition")
        self.assertEqual(guards[0].name, "scenario_save")
        self.assertEqual(guards[0].unavailable_tools, ("scenario.save", "scenario.create", "scenario.persist"))
        self.assertEqual(guards[0].requires_field, "requires_scenario_persistence")
        self.assertEqual(guards[0].completion_source, "unsupported_scenario_save_guard")
        self.assertEqual(_unsupported_capability_guards_for_intent("请保存这份报告摘要"), ())
        self.assertIn("requires_scenario_persistence", _unsupported_capability_classifier_prompt(guards[0]) or "")
        self.assertIn("没有“保存正式场景”的后端工具", _unsupported_capability_message(guards[0]) or "")

    def test_agent_skill_registry_loads_custom_skill_triggers_from_frontmatter(self):
        from app.services.agent_skill_registry import AgentSkillRegistry

        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / "custom-dataset-helper"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "\n".join([
                    "---",
                    "name: custom-dataset-helper",
                    "description: Use when the user asks for custom dataset helper behavior.",
                    "triggers:",
                    "  - 数据样板",
                    "  - custom-dataset",
                    "guard_custom_route:",
                    "  - 私有路由词",
                    "routing_requires_tool:",
                    "  - 数据样板",
                    "routing_required_tool_after_success:",
                    "  - after=dataset.query; require=dataset.compose; min_total_fields=total",
                    "guard_custom_prompt: classifier.md",
                    "guard_custom_message: message.md",
                    "guard_unsupported_capability:",
                    "  - name=dataset_publish; intent=guard_custom_route; subject=routing_requires_tool; unavailable_tools=dataset.publish; classifier_prompt=guard_custom_prompt; requires_field=requires_dataset_publish; completion_source=unsupported_dataset_publish_guard; message=guard_custom_message",
                    "---",
                    "",
                    "# Custom Dataset Helper",
                    "",
                    "Answer with a dataset helper workflow.",
                ]),
                encoding="utf-8",
            )
            (skill_dir / "classifier.md").write_text("私有分类提示词", encoding="utf-8")
            (skill_dir / "message.md").write_text("私有完成消息", encoding="utf-8")

            registry = AgentSkillRegistry(root=Path(temp_dir))
            selected = registry.select_for_intent("请生成一份数据样板")
            private_values = registry.private_list("custom-dataset-helper", "guard_custom_route")
            tool_values = registry.private_list("custom-dataset-helper", "routing_requires_tool")
            followup_values = registry.private_list(
                "custom-dataset-helper",
                "routing_required_tool_after_success",
            )
            prompt_resource = registry.private_resource_text("custom-dataset-helper", "guard_custom_prompt")
            unsupported_values = registry.private_list("custom-dataset-helper", "guard_unsupported_capability")
            message_resource = registry.private_resource_text("custom-dataset-helper", "guard_custom_message")

        self.assertEqual([skill.name for skill in selected], ["custom-dataset-helper"])
        self.assertEqual(private_values, ("私有路由词",))
        self.assertEqual(tool_values, ("数据样板",))
        self.assertEqual(followup_values, ("after=dataset.query; require=dataset.compose; min_total_fields=total",))
        self.assertEqual(prompt_resource, "私有分类提示词")
        self.assertEqual(len(unsupported_values), 1)
        self.assertIn("name=dataset_publish", unsupported_values[0])
        self.assertEqual(message_resource, "私有完成消息")
        self.assertNotIn("私有路由词", selected[0].prompt_block())
        self.assertNotIn("routing_requires_tool", selected[0].prompt_block())
        self.assertNotIn("routing_required_tool_after_success", selected[0].prompt_block())
        self.assertNotIn("guard_unsupported_capability", selected[0].prompt_block())
        self.assertNotIn("私有分类提示词", selected[0].prompt_block())
        self.assertNotIn("私有完成消息", selected[0].prompt_block())

    def test_tool_call_idempotency_reuses_existing_call(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="读取项目上下文"),
            current_user=self.owner,
        )
        payload = AgentToolCallCreateRequest(
            run_id=run.run_id,
            tool_name="project.read_context",
            input={"project_id": 10},
            step_index=0,
            idempotency_key="same-key",
        )

        first = ExecutionLedgerService(self.db).create_tool_call(payload=payload, current_user=self.owner)
        second = ExecutionLedgerService(self.db).create_tool_call(payload=payload, current_user=self.owner)

        self.assertEqual(first.tool_call_id, second.tool_call_id)
        self.assertEqual(self.db.query(AgentToolCall).count(), 1)
        duplicate_events = list(self.db.scalars(
            select(AgentEvent).where(
                AgentEvent.run_id == run.run_id,
                AgentEvent.event_type == "tool.duplicate_blocked",
            )
        ).all())
        self.assertEqual(len(duplicate_events), 1)

    def test_outbox_publisher_retries_and_dead_letters_failures(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="outbox", auto_complete=True),
            current_user=self.owner,
        )
        self.assertGreater(self.db.query(AgentOutbox).filter(AgentOutbox.status == "pending").count(), 0)
        now = datetime.now(UTC).replace(tzinfo=None)

        def fail_publish(event):
            raise RuntimeError(f"publish failed: {event.event_type}")

        publisher = AgentOutboxPublisher(
            self.db,
            publisher=fail_publish,
            max_attempts=2,
            base_retry_seconds=1,
        )
        first = publisher.publish_pending(limit=1, now=now)
        failed_item = self.db.scalar(select(AgentOutbox).where(AgentOutbox.status == "failed"))
        failed_item.next_retry_at = now - timedelta(seconds=1)
        self.db.commit()
        second = publisher.publish_pending(limit=1, now=now)

        self.assertEqual(first["attempted"], 1)
        self.assertEqual(first["failed"], 1)
        self.assertEqual(second["attempted"], 1)
        self.assertEqual(second["dead_letter"], 1)
        self.assertEqual(
            self.db.query(AgentOutbox).filter(AgentOutbox.status == "dead_letter").count(),
            1,
        )
        self.assertEqual(run.run_id, self.db.scalar(select(AgentEvent.run_id).limit(1)))

    def test_outbox_publish_lag_alert_affects_dashboard_readiness(self):
        AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="outbox lag", auto_complete=True),
            current_user=self.owner,
        )
        for item in self.db.scalars(select(AgentOutbox).where(AgentOutbox.status == "pending")).all():
            item.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=2)
        self.db.commit()

        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        alerts = {item["alert_id"]: item for item in alert_snapshot["alerts"]}
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertGreater(metrics["outbox_publish_lag_ms"], 0)
        self.assertIn("agent_outbox_publish_lag", alerts)
        self.assertEqual(alerts["agent_outbox_publish_lag"]["severity"], "P1")
        self.assertEqual(alerts["agent_outbox_publish_lag"]["runbook_id"], "outbox_publish_lag")
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P1")
        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["live_recovery_attention"]["status"], "attention")
        self.assertGreater(checks["live_recovery_attention"]["details"]["outbox_publish_lag_ms"], 0)
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "attention")

    def test_harness_outbox_publish_payload_contract_matches_service(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import publish_agent_outbox

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Outbox publish payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Outbox publish payload contract:" in path.read_text(encoding="utf-8")
        ]
        AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="outbox contract service", auto_complete=True),
            current_user=self.owner,
        )
        service_summary = AgentOutboxPublisher(
            self.db,
            publisher=lambda event: None,
        ).publish_pending(limit=10)
        AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="outbox contract route", auto_complete=True),
            current_user=self.owner,
        )
        route_payload = publish_agent_outbox(limit=10, db=self.db, current_user=self.admin)["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(OUTBOX_PUBLISH_FIELDS))
            self.assertEqual(contract["source"], "AgentOutboxPublisher.publish_pending")
        self.assertEqual(list(AgentOutboxPublishRead.model_fields), list(OUTBOX_PUBLISH_FIELDS))
        self.assertEqual(list(service_summary), list(OUTBOX_PUBLISH_FIELDS))
        self.assertEqual(list(route_payload), list(OUTBOX_PUBLISH_FIELDS))

    def test_outbox_publisher_marks_successfully_published_events(self):
        AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="outbox success", auto_complete=True),
            current_user=self.owner,
        )
        published = []

        summary = AgentOutboxPublisher(
            self.db,
            publisher=lambda event: published.append(event.event_type),
        ).publish_pending(limit=10)

        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["dead_letter"], 0)
        self.assertEqual(summary["published"], len(published))
        self.assertGreater(summary["published"], 0)
        self.assertEqual(self.db.query(AgentOutbox).filter(AgentOutbox.status == "pending").count(), 0)

    def test_agent_metrics_snapshot_reads_agent_fact_tables(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="metrics"),
            current_user=self.owner,
        )
        payload = AgentToolCallCreateRequest(
            run_id=run.run_id,
            tool_name="project.read_context",
            input={"project_id": 10},
            step_index=0,
            idempotency_key="metrics-key",
        )
        call = ExecutionLedgerService(self.db).create_tool_call(payload=payload, current_user=self.owner)
        ExecutionLedgerService(self.db).create_tool_call(payload=payload, current_user=self.owner)
        call.status = "uncertain"
        self.db.add(AgentReconcileAttempt(
            tool_call_id=call.tool_call_id,
            attempt_seq=1,
            backend_name="project-service",
            backend_operation="read_context",
            backend_contract_version="v1",
            result_status="succeeded",
        ))
        self.db.commit()

        snapshot = AgentMetricsService(self.db).snapshot(project_id=10)
        metrics = snapshot["metrics"]

        self.assertEqual(metrics["tool_call_uncertain_total"], 1)
        self.assertEqual(metrics["tool_call_duplicate_blocked_total"], 1)
        self.assertEqual(metrics["tool_call_reconcile_success_total"], 1)
        self.assertIn("outbox_publish_lag_ms", metrics)

    def test_release_gate_snapshot_keeps_current_rollout_at_l2(self):
        AgentRuntimeService(self.db).ensure_backend_contracts()

        snapshot = AgentReleaseGateService(self.db).snapshot()
        tool_names = {item["tool_name"] for item in snapshot["tool_matrix"]}
        business_gate = next(item for item in snapshot["expansion_gates"] if item["level"] == "L3")

        self.assertEqual(snapshot["current_level"], "L2")
        self.assertIn("execution_record", snapshot["allowed_side_effect_classes"])
        self.assertIn("business_create", snapshot["blocked_side_effect_classes"])
        self.assertEqual(snapshot["violations"], [])
        self.assertIn("scenario.execute_dry_run", tool_names)
        self.assertIn("ai_skill.run_draft", tool_names)
        self.assertFalse(business_gate["unlocked"])
        self.assertGreaterEqual(len(business_gate["blocked_reasons"]), 1)

    def test_harness_rollout_matrix_matches_docs_contract(self):
        from pathlib import Path

        from app.api.v1.routers.agents import get_agent_release_gates
        from app.services.agent_release_gate_service import (
            CURRENT_AGENT_ROLLOUT_LEVEL,
            ROLLOUT_LEVELS,
        )
        from app.services.agent_tool_service import ToolRegistry, ToolSpec

        def _split_csv(value: str) -> set[str]:
            if value == "none":
                return set()
            return {item.strip() for item in value.split(",") if item.strip()}

        def _parse_matrix(text: str) -> dict[str, dict]:
            section = text[text.index("Required rollout matrix:"):]
            rows = [
                line
                for line in section.splitlines()
                if line.startswith("|") and not line.startswith("|---")
            ]
            matrix: dict[str, dict] = {}
            for row in rows[1:]:
                cells = [cell.strip() for cell in row.strip("|").split("|")]
                if len(cells) != 5:
                    continue
                level, summary, allowed, blocked, gates = cells
                matrix[level] = {
                    "summary": summary,
                    "allowed_side_effect_classes": _split_csv(allowed),
                    "blocked_side_effect_classes": _split_csv(blocked),
                    "required_gates": [item.strip() for item in gates.split(";") if item.strip()],
                }
            return matrix

        def _parse_release_gate_payload_contract(text: str) -> dict[str, str | list[str]]:
            section = text[text.index("Required release gate snapshot payload contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            parsed: dict[str, str | list[str]] = {}
            for line in block.splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                parsed[key] = (
                    [item.strip() for item in value.split(",") if item.strip()]
                    if key.endswith("_fields") or key == "fields" or key == "rollout_decision_values"
                    else value
                )
            return parsed

        expected = {
            level: {
                "summary": spec["summary"],
                "allowed_side_effect_classes": spec["allowed_side_effect_classes"],
                "blocked_side_effect_classes": spec["blocked_side_effect_classes"],
                "required_gates": spec["required_gates"],
            }
            for level, spec in ROLLOUT_LEVELS.items()
        }
        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_matrices = [
            _parse_matrix(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required rollout matrix:" in path.read_text(encoding="utf-8")
        ]
        documented_payload_contracts = [
            _parse_release_gate_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required release gate snapshot payload contract:" in path.read_text(encoding="utf-8")
        ]
        snapshot = AgentReleaseGateService(self.db).snapshot()
        route_payload = get_agent_release_gates(db=self.db, current_user=self.admin)["data"]
        expansion_gates = {
            gate["level"]: gate
            for gate in snapshot["expansion_gates"]
        }
        levels = list(ROLLOUT_LEVELS)
        current_index = levels.index(CURRENT_AGENT_ROLLOUT_LEVEL)

        self.assertEqual(len(documented_matrices), 2)
        for matrix in documented_matrices:
            self.assertEqual(list(matrix), levels)
            self.assertEqual(matrix, expected)
        self.assertEqual(len(documented_payload_contracts), 2)
        for documented in documented_payload_contracts:
            self.assertEqual(documented["fields"], list(RELEASE_GATE_FIELDS))
            self.assertEqual(documented["tool_fields"], list(RELEASE_GATE_TOOL_FIELDS))
            self.assertEqual(documented["level_fields"], list(RELEASE_GATE_LEVEL_FIELDS))
            self.assertEqual(documented["violation_fields"], list(RELEASE_GATE_VIOLATION_FIELDS))
            self.assertEqual(documented["rollout_decision_values"], list(RELEASE_GATE_ROLLOUT_DECISION_VALUES))
            self.assertEqual(
                documented["rollout_allowed_rule"],
                "current_side_effect_allowed_and_backend_contract_active_or_missing",
            )
            self.assertEqual(documented["violation_reason"], RELEASE_GATE_VIOLATION_REASON)
        self.assertEqual(list(AgentReleaseGateRead.model_fields), list(RELEASE_GATE_FIELDS))
        self.assertEqual(list(AgentReleaseGateToolRead.model_fields), list(RELEASE_GATE_TOOL_FIELDS))
        self.assertEqual(list(AgentReleaseGateLevelRead.model_fields), list(RELEASE_GATE_LEVEL_FIELDS))
        self.assertEqual(list(AgentReleaseGateViolationRead.model_fields), list(RELEASE_GATE_VIOLATION_FIELDS))
        self.assertEqual(list(snapshot), list(RELEASE_GATE_FIELDS))
        self.assertEqual(list(route_payload), list(RELEASE_GATE_FIELDS))
        self.assertTrue(snapshot["tool_matrix"])
        self.assertTrue(snapshot["expansion_gates"])
        self.assertTrue(all(list(item) == list(RELEASE_GATE_TOOL_FIELDS) for item in snapshot["tool_matrix"]))
        self.assertTrue(all(list(item) == list(RELEASE_GATE_TOOL_FIELDS) for item in route_payload["tool_matrix"]))
        self.assertTrue({item["rollout_decision"] for item in snapshot["tool_matrix"]}.issubset(RELEASE_GATE_ROLLOUT_DECISION_VALUES))
        self.assertTrue(all(list(item) == list(RELEASE_GATE_LEVEL_FIELDS) for item in snapshot["expansion_gates"]))
        self.assertTrue(all(list(item) == list(RELEASE_GATE_LEVEL_FIELDS) for item in route_payload["expansion_gates"]))
        self.assertEqual(snapshot["current_level"], CURRENT_AGENT_ROLLOUT_LEVEL)
        self.assertEqual(snapshot["allowed_side_effect_classes"], sorted(expected[CURRENT_AGENT_ROLLOUT_LEVEL]["allowed_side_effect_classes"]))
        self.assertEqual(snapshot["blocked_side_effect_classes"], sorted(expected[CURRENT_AGENT_ROLLOUT_LEVEL]["blocked_side_effect_classes"]))
        for index, level in enumerate(levels):
            with self.subTest(level=level):
                self.assertEqual(expansion_gates[level]["summary"], expected[level]["summary"])
                self.assertEqual(expansion_gates[level]["required_gates"], expected[level]["required_gates"])
                self.assertEqual(expansion_gates[level]["unlocked"], index <= current_index)
        blocked_spec = ToolSpec(
            name="project.create_business_record",
            version="v1",
            summary="business create remains blocked at L2",
            side_effect_class="business_create",
            replay_policy="no_replay",
            required_permissions=(),
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        )
        with patch.object(ToolRegistry, "list_specs", return_value=ToolRegistry().list_specs() + [blocked_spec]):
            blocked_snapshot = AgentReleaseGateService(self.db).snapshot()
        self.assertEqual(list(blocked_snapshot["violations"][0]), list(RELEASE_GATE_VIOLATION_FIELDS))
        self.assertEqual(blocked_snapshot["violations"][0]["tool_name"], "project.create_business_record")
        self.assertEqual(blocked_snapshot["violations"][0]["reason"], RELEASE_GATE_VIOLATION_REASON)
        blocked_tool = next(item for item in blocked_snapshot["tool_matrix"] if item["tool_name"] == blocked_spec.name)
        self.assertFalse(blocked_tool["rollout_allowed"])
        self.assertEqual(blocked_tool["rollout_decision"], RELEASE_GATE_ROLLOUT_DECISION_VALUES[1])

    def test_backend_adapter_contract_defaults_match_docs_and_seeded_tool_specs(self):
        from pathlib import Path

        from app.core.sensitive_data import request_fingerprint
        from app.services.agent_tool_service import SAFE_SIDE_EFFECT_CLASSES, ToolRegistry

        expected_defaults = {
            "reconcile_contract_version": "reconcile-v1",
            "result_adapter_version": "v1",
            "compatibility_status": "active",
            "owner_team": "test-platform",
            "unsafe_side_effect_requires_backend_contract": "true",
            "seed_contracts_from_tool_registry": "true",
        }

        def _parse_defaults(text: str) -> dict[str, str]:
            section = text[text.index("Required backend adapter contract defaults:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            return {
                key.strip(): value.strip()
                for line in block.splitlines()
                if "=" in line
                for key, value in [line.split("=", 1)]
            }

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_defaults = [
            _parse_defaults(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required backend adapter contract defaults:" in path.read_text(encoding="utf-8")
        ]
        specs = ToolRegistry().list_specs()
        expected_contracts = {}

        self.assertEqual(len(documented_defaults), 2)
        for defaults in documented_defaults:
            self.assertEqual(defaults, expected_defaults)
        for spec in specs:
            with self.subTest(tool=spec.name):
                self.assertTrue(spec.name)
                self.assertTrue(spec.version)
                self.assertTrue(spec.summary)
                self.assertTrue(spec.replay_policy)
                self.assertTrue(spec.input_schema)
                self.assertTrue(spec.output_schema)
                self.assertEqual(
                    spec.schema_hash,
                    request_fingerprint({"input_schema": spec.input_schema, "output_schema": spec.output_schema}),
                )
                self.assertTrue(spec.manifest_hash)
                if spec.side_effect_class not in SAFE_SIDE_EFFECT_CLASSES:
                    self.assertIsNotNone(spec.backend_contract)

                contract = spec.backend_contract
                self.assertIsNotNone(contract)
                self.assertEqual(contract.request_schema_hash, request_fingerprint(spec.input_schema))
                self.assertEqual(contract.output_schema_hash, request_fingerprint(spec.output_schema))
                self.assertEqual(contract.reconcile_contract_version, expected_defaults["reconcile_contract_version"])
                self.assertEqual(contract.result_adapter_version, expected_defaults["result_adapter_version"])
                self.assertEqual(contract.compatibility_status, expected_defaults["compatibility_status"])
                self.assertEqual(contract.owner_team, expected_defaults["owner_team"])
                expected_contracts[
                    (
                        contract.backend_name,
                        contract.backend_operation,
                        contract.backend_contract_version,
                    )
                ] = contract

        AgentRuntimeService(self.db).ensure_backend_contracts()
        seeded_contracts = {
            (
                contract.backend_name,
                contract.backend_operation,
                contract.backend_contract_version,
            ): contract
            for contract in self.db.scalars(select(AgentBackendContract)).all()
        }
        release_gate_rows = {
            item["tool_name"]: item
            for item in AgentReleaseGateService(self.db).snapshot()["tool_matrix"]
        }

        self.assertEqual(set(seeded_contracts), set(expected_contracts))
        for key, expected in expected_contracts.items():
            with self.subTest(contract=key):
                seeded = seeded_contracts[key]
                self.assertEqual(seeded.request_schema_hash, expected.request_schema_hash)
                self.assertEqual(seeded.output_schema_hash, expected.output_schema_hash)
                self.assertEqual(seeded.reconcile_contract_version, expected.reconcile_contract_version)
                self.assertEqual(seeded.result_adapter_version, expected.result_adapter_version)
                self.assertEqual(seeded.effect_capability, expected.effect_capability)
                self.assertEqual(seeded.compatibility_status, expected.compatibility_status)
                self.assertEqual(seeded.owner_team, expected.owner_team)
        for spec in specs:
            contract = spec.backend_contract
            row = release_gate_rows[spec.name]
            with self.subTest(tool_matrix=spec.name):
                self.assertEqual(row["backend_name"], contract.backend_name)
                self.assertEqual(row["backend_operation"], contract.backend_operation)
                self.assertEqual(row["backend_contract_version"], contract.backend_contract_version)
                self.assertEqual(row["backend_effect_capability"], contract.effect_capability)
                self.assertEqual(row["backend_contract_status"], expected_defaults["compatibility_status"])

    def test_harness_evidence_ref_authoring_contract_matches_resolver(self):
        from pathlib import Path

        def _split_csv(value: str) -> set[str]:
            return {item.strip() for item in value.split(",") if item.strip()}

        def _parse_contract(text: str) -> dict[str, str | set[str]]:
            section = text[text.index("Required EvidenceRef authoring contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            parsed: dict[str, str | set[str]] = {}
            for line in block.splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                parsed[key] = _split_csv(value) if "," in value else value
            return parsed

        expected_contract = {
            "mutability_classes": EVIDENCE_MUTABILITY_CLASSES,
            "frozen_mutability_classes": FROZEN_MUTABILITY_CLASSES,
            "volatile_mutability_classes": VOLATILE_MUTABILITY_CLASSES,
            "active_policy_dependency_roles": ACTIVE_POLICY_DEPENDENCY_ROLES,
            "audit_dependency_roles": AUDIT_DEPENDENCY_ROLES,
            "dependency_roles": EVIDENCE_DEPENDENCY_ROLES,
            "freshness_policies": EVIDENCE_FRESHNESS_POLICIES,
            "default_mutability_class": DEFAULT_EVIDENCE_MUTABILITY_CLASS,
            "default_dependency_role": DEFAULT_EVIDENCE_DEPENDENCY_ROLE,
            "policy_filter": "active_for_policy=true;dependency_role=in_active_policy_dependency_roles;superseded_by_ref=null",
        }
        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            _parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required EvidenceRef authoring contract:" in path.read_text(encoding="utf-8")
        ]

        self.assertEqual(len(documented_contracts), 2)
        for contract in documented_contracts:
            self.assertEqual(contract, expected_contract)

        refs = [
            {
                "evidence_ref_id": "decision-ref",
                "ref_type": "testcase",
                "ref_id": "case-1",
                "mutability_class": "immutable",
                "content_hash": "hash-case-1",
                "dependency_role": "decision_dependency",
                "active_for_policy": True,
            },
            {
                "evidence_ref_id": "validation-ref",
                "ref_type": "execution_record",
                "ref_id": "execution-1",
                "mutability_class": "versioned",
                "version_id": "v1",
                "dependency_role": "validation_evidence",
                "active_for_policy": True,
            },
            {
                "evidence_ref_id": "policy-ref",
                "ref_type": "memory",
                "ref_id": "1",
                "mutability_class": "mutable_current",
                "dependency_role": "policy_dependency",
                "active_for_policy": True,
                "freshness_policy": "revalidate_before_side_effect",
            },
            {
                "evidence_ref_id": "audit-ref",
                "ref_type": "report",
                "ref_id": "report-1",
                "mutability_class": "ephemeral_latest",
                "dependency_role": "audit_background",
                "active_for_policy": True,
            },
            {
                "evidence_ref_id": "superseded-ref",
                "ref_type": "scenario",
                "ref_id": "scenario-1",
                "mutability_class": "versioned",
                "version_id": "v2",
                "dependency_role": "decision_dependency",
                "active_for_policy": True,
                "superseded_by_ref": "decision-ref",
            },
            {
                "evidence_ref_id": "inactive-ref",
                "ref_type": "external_doc",
                "ref_id": "doc-1",
                "mutability_class": "external_uncontrolled",
                "dependency_role": "policy_dependency",
                "active_for_policy": False,
                "freshness_policy": "revalidate_on_resume",
            },
            {
                "evidence_ref_id": "defaulted-ref",
                "ref_type": "project",
                "ref_id": "10",
            },
        ]

        parsed = EvidenceRefResolver().parse(refs)
        policy_refs, audit_refs, summary = EvidenceRefResolver().split_policy_and_audit_refs(refs)
        frozen_refs = [refs[0], refs[1]]

        self.assertEqual(parsed[-1].mutability_class, DEFAULT_EVIDENCE_MUTABILITY_CLASS)
        self.assertEqual(parsed[-1].dependency_role, DEFAULT_EVIDENCE_DEPENDENCY_ROLE)
        self.assertEqual(
            [item["evidence_ref_id"] for item in policy_refs],
            ["decision-ref", "validation-ref", "policy-ref"],
        )
        self.assertEqual(
            [item["evidence_ref_id"] for item in audit_refs],
            ["audit-ref", "superseded-ref", "inactive-ref", "defaulted-ref"],
        )
        self.assertTrue(summary["requires_revalidation"])
        self.assertFalse(summary["fully_frozen"])
        self.assertFalse(EvidenceRefResolver().evidence_requires_revalidation(frozen_refs))
        self.assertTrue(EvidenceRefResolver().evidence_fully_frozen(frozen_refs))

    def test_release_gate_snapshot_route_requires_admin(self):
        from app.api.v1.routers.agents import get_agent_release_gates

        with self.assertRaises(HTTPException) as owner_ctx:
            get_agent_release_gates(db=self.db, current_user=self.owner)

        admin_response = get_agent_release_gates(db=self.db, current_user=self.admin)

        self.assertEqual(owner_ctx.exception.status_code, 403)
        self.assertEqual(admin_response["data"]["current_level"], "L2")

    def test_release_gate_promotion_route_scopes_global_and_project_access(self):
        from app.api.v1.routers.agents import assess_agent_release_gate_promotion

        outsider = User(
            id=4,
            username="outsider",
            account="outsider",
            password_hash="x",
            phone="10000000004",
            email="outsider@example.test",
            is_admin=False,
        )
        self.db.add(outsider)
        self.db.commit()

        with self.assertRaises(HTTPException) as owner_global_ctx:
            assess_agent_release_gate_promotion(
                target_level="L3",
                db=self.db,
                current_user=self.owner,
            )
        with self.assertRaises(HTTPException) as outsider_project_ctx:
            assess_agent_release_gate_promotion(
                target_level="L3",
                project_id=10,
                db=self.db,
                current_user=outsider,
            )

        member_project = assess_agent_release_gate_promotion(
            target_level="L3",
            project_id=10,
            db=self.db,
            current_user=self.member,
        )
        admin_global = assess_agent_release_gate_promotion(
            target_level="L3",
            db=self.db,
            current_user=self.admin,
        )

        self.assertEqual(owner_global_ctx.exception.status_code, 403)
        self.assertEqual(outsider_project_ctx.exception.status_code, 403)
        self.assertEqual(member_project["data"]["project_id"], 10)
        self.assertEqual(member_project["data"]["target_level"], "L3")
        self.assertIsNone(admin_global["data"]["project_id"])
        self.assertEqual(admin_global["data"]["target_level"], "L3")

    def test_release_gate_promotion_assessment_blocks_l3_until_readiness_and_static_gates_clear(self):
        AgentRuntimeService(self.db).ensure_backend_contracts()

        assessment = AgentReleaseGateService(self.db).promotion_assessment(target_level="L3", project_id=10)
        blockers = {item["source"] for item in assessment["blockers"]}
        checks = {item["name"]: item for item in assessment["checks"]}

        self.assertEqual(assessment["current_level"], "L2")
        self.assertEqual(assessment["target_level"], "L3")
        self.assertFalse(assessment["can_promote"])
        self.assertEqual(assessment["decision"], "blocked")
        self.assertIn("release_gate", blockers)
        self.assertEqual(checks["readiness_dashboard_pass"]["status"], "pass")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "pass")
        self.assertEqual(checks["monitoring_alerts_clear"]["details"]["by_severity"]["P0"], 0)
        self.assertEqual(checks["monitoring_alerts_clear"]["details"]["by_severity"]["P1"], 0)
        self.assertEqual(checks["release_gate_static_reasons_clear"]["status"], "blocked")
        self.assertEqual(assessment["dashboard_checks"], assessment["readiness"]["checks"])
        self.assertEqual(assessment["fault_injection"], assessment["readiness"]["fault_injection"])
        self.assertEqual(assessment["alert_summary"], assessment["readiness"]["alert_summary"])
        payload = AgentReleaseGatePromotionRead.model_validate(assessment).model_dump()
        for key in ("dashboard_checks", "fault_injection", "alert_summary"):
            self.assertEqual(payload[key], assessment[key])

    def test_harness_promotion_assessment_contract_matches_release_gate(self):
        from pathlib import Path
        import re

        def _parse_contract(text: str) -> dict[str, list[str]]:
            section = text[text.index("Required promotion assessment contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            parsed: dict[str, list[str]] = {}
            for line in block.splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                parsed[key] = [item.strip() for item in value.split(",") if item.strip()]
            return parsed

        def _parse_blocker_payload_contract(text: str) -> dict[str, str | list[str]]:
            section = text[text.index("Required promotion blocker payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, str | list[str]] = {}
            for line in block.group(1).splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                if key == "fields" or key.endswith("_details"):
                    parsed[key] = [item.strip() for item in value.split(",") if item.strip()]
                else:
                    parsed[key] = value
            return parsed

        def _parse_decision_contract(text: str) -> dict[str, str | list[str]]:
            section = text[text.index("Required promotion decision contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, str | list[str]] = {}
            for line in block.group(1).splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                parsed[key] = [item.strip() for item in value.split(",") if item.strip()] if key == "decision_values" else value
            return parsed

        def _parse_payload_contract(text: str) -> dict[str, list[str]]:
            section = text[text.index("Required promotion assessment payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str]] = {}
            for line in block.group(1).splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                parsed[key] = [item.strip() for item in value.split(",") if item.strip()]
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = []
        documented_payload_contracts = []
        documented_blocker_payload_contracts = []
        documented_decision_contracts = []
        for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md"):
            text = path.read_text(encoding="utf-8")
            if "Required promotion assessment contract:" in text:
                documented_contracts.append(_parse_contract(text))
            if "Required promotion assessment payload contract:" in text:
                documented_payload_contracts.append(_parse_payload_contract(text))
            if "Required promotion blocker payload contract:" in text:
                documented_blocker_payload_contracts.append(_parse_blocker_payload_contract(text))
            if "Required promotion decision contract:" in text:
                documented_decision_contracts.append(_parse_decision_contract(text))
        expected_contract = {
            "checks": list(PROMOTION_ASSESSMENT_CHECKS),
            "blocker_sources": list(PROMOTION_BLOCKER_SOURCES),
            "release_gate_fields": list(PROMOTION_RELEASE_GATE_FIELDS),
        }
        expected_details_by_source = {
            "release_gate": ["target_level", "blocked_reason", "blocked_reasons"],
            "tool_matrix": ["target_level", "violation_count", "violations"],
            "minimum_go_live": ["target_level", "missing_requirement_ids"],
            "go_live_gates": ["target_level", "missing_by_priority"],
            "final_delivery": ["target_level", "missing_by_category"],
            "monitoring_alerts": ["target_level", "alert_summary"],
            "readiness_dashboard": ["target_level", "readiness", "alert_summary"],
        }
        expected_decision_contract = {
            "decision_values": list(PROMOTION_DECISION_VALUES),
            "already_unlocked_rule": "target_index<=current_index",
            "already_unlocked_can_promote": "false",
            "already_unlocked_blockers": "empty",
            "target_above_current_status": PROMOTION_ALREADY_UNLOCKED_CHECK_STATUS,
        }
        AgentRuntimeService(self.db).ensure_backend_contracts()

        assessment = AgentReleaseGateService(self.db).promotion_assessment(target_level="L3", project_id=10)
        payload = AgentReleaseGatePromotionRead.model_validate(assessment).model_dump()
        already_unlocked = AgentReleaseGateService(self.db).promotion_assessment(target_level="L2", project_id=10)
        already_unlocked_checks = {item["name"]: item for item in already_unlocked["checks"]}

        self.assertEqual(len(documented_contracts), 2)
        for documented in documented_contracts:
            self.assertEqual(documented, expected_contract)
        self.assertEqual(len(documented_payload_contracts), 2)
        for documented in documented_payload_contracts:
            self.assertEqual(documented["fields"], list(PROMOTION_ASSESSMENT_FIELDS))
        self.assertEqual(len(documented_blocker_payload_contracts), 2)
        for documented in documented_blocker_payload_contracts:
            self.assertEqual(documented["fields"], list(PROMOTION_BLOCKER_FIELDS))
            self.assertEqual(documented["details_required_field"], "target_level")
            for source, fields in expected_details_by_source.items():
                self.assertEqual(documented[f"{source}_details"], fields)
        self.assertEqual(len(documented_decision_contracts), 2)
        for documented in documented_decision_contracts:
            self.assertEqual(documented, expected_decision_contract)
        self.assertEqual(list(AgentReleaseGatePromotionRead.model_fields), list(PROMOTION_ASSESSMENT_FIELDS))
        self.assertEqual(list(assessment), list(PROMOTION_ASSESSMENT_FIELDS))
        self.assertEqual([item["name"] for item in assessment["checks"]], list(PROMOTION_ASSESSMENT_CHECKS))
        self.assertEqual(list(assessment["release_gate"]), list(PROMOTION_RELEASE_GATE_FIELDS))
        self.assertTrue(assessment["blockers"])
        for blocker in assessment["blockers"]:
            self.assertEqual(list(blocker), list(PROMOTION_BLOCKER_FIELDS))
            self.assertIn(blocker["source"], PROMOTION_BLOCKER_SOURCES)
            self.assertEqual(blocker["details"]["target_level"], "L3")
            self.assertTrue(set(expected_details_by_source[blocker["source"]]).issubset(blocker["details"]))
        self.assertEqual([item["name"] for item in payload["checks"]], list(PROMOTION_ASSESSMENT_CHECKS))
        self.assertEqual(list(payload), list(PROMOTION_ASSESSMENT_FIELDS))
        self.assertEqual(list(payload["release_gate"]), list(PROMOTION_RELEASE_GATE_FIELDS))
        for blocker in payload["blockers"]:
            self.assertEqual(list(blocker), list(PROMOTION_BLOCKER_FIELDS))
        self.assertEqual(already_unlocked["decision"], "already_unlocked")
        self.assertFalse(already_unlocked["can_promote"])
        self.assertEqual(already_unlocked["blockers"], [])
        self.assertEqual(
            already_unlocked_checks["target_above_current"]["status"],
            PROMOTION_ALREADY_UNLOCKED_CHECK_STATUS,
        )
        self.assertIn(already_unlocked["decision"], PROMOTION_DECISION_VALUES)

        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="promotion blocker contract"),
            current_user=self.owner,
        )
        AgentRuntimeService(self.db).append_event(
            run,
            "memory.bypassed_evidence_ref",
            {"error_code": "memory_bypassed_evidence_ref"},
        )
        blocked_assessment = AgentReleaseGateService(self.db).promotion_assessment(target_level="L3", project_id=10)
        blocked_by_source = {item["source"]: item for item in blocked_assessment["blockers"]}
        self.assertTrue({"monitoring_alerts", "readiness_dashboard"}.issubset(blocked_by_source))
        for source in ("monitoring_alerts", "readiness_dashboard"):
            self.assertEqual(list(blocked_by_source[source]), list(PROMOTION_BLOCKER_FIELDS))
            self.assertTrue(set(expected_details_by_source[source]).issubset(blocked_by_source[source]["details"]))

    def test_harness_minimum_go_live_contract_matches_release_gate(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import get_agent_release_gates

        def _parse_ids(text: str) -> list[str]:
            section = text[text.index("Required minimum go-live contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            return [line.strip() for line in block.splitlines() if line.strip()]

        def _parse_payload_contract(text: str) -> dict[str, str | list[str]]:
            section = text[text.index("Required minimum go-live payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, str | list[str]] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                parsed[key] = value.split(",") if key.endswith("fields") else value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            _parse_ids(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required minimum go-live contract:" in path.read_text(encoding="utf-8")
        ]
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required minimum go-live payload contract:" in path.read_text(encoding="utf-8")
        ]
        AgentRuntimeService(self.db).ensure_backend_contracts()

        release_gate = AgentReleaseGateService(self.db).snapshot()
        minimum = release_gate["minimum_go_live"]
        promotion = AgentReleaseGateService(self.db).promotion_assessment(target_level="L3", project_id=10)
        promotion_checks = {item["name"]: item for item in promotion["checks"]}
        route_payload = get_agent_release_gates(db=self.db, current_user=self.admin)["data"]

        self.assertEqual(len(documented_contracts), 2)
        for documented in documented_contracts:
            self.assertEqual(documented, list(MINIMUM_GO_LIVE_REQUIREMENTS))
        self.assertEqual(len(documented_payload_contracts), 2)
        for documented in documented_payload_contracts:
            self.assertEqual(documented["fields"], list(MINIMUM_GO_LIVE_FIELDS))
            self.assertEqual(documented["check_fields"], list(MINIMUM_GO_LIVE_CHECK_FIELDS))
            self.assertEqual(documented["expansion_prerequisite"], "business_create")
        self.assertIn("minimum_go_live", AgentReleaseGateRead.model_fields)
        self.assertEqual(list(minimum), list(MINIMUM_GO_LIVE_FIELDS))
        self.assertTrue(all(list(item) == list(MINIMUM_GO_LIVE_CHECK_FIELDS) for item in minimum["checks"]))
        self.assertEqual(route_payload["minimum_go_live"]["required_requirement_ids"], list(MINIMUM_GO_LIVE_REQUIREMENTS))
        self.assertEqual(minimum["required_requirement_ids"], list(MINIMUM_GO_LIVE_REQUIREMENTS))
        self.assertEqual(set(minimum["passed_requirement_ids"]), set(MINIMUM_GO_LIVE_REQUIREMENTS))
        self.assertEqual(minimum["missing_requirement_ids"], [])
        self.assertTrue(minimum["pass"])
        self.assertTrue(minimum["business_create_expansion_prerequisite"])
        self.assertEqual(
            {item["requirement_id"]: item["label"] for item in minimum["checks"]},
            MINIMUM_GO_LIVE_REQUIREMENTS,
        )
        backend_capability_check = next(
            item for item in minimum["checks"] if item["requirement_id"] == "backend_effect_capability_declared"
        )
        fault_injection_check = next(
            item for item in minimum["checks"] if item["requirement_id"] == "p0_fault_injection_passed"
        )
        self.assertEqual(backend_capability_check["details"]["missing_backend_capability_tool_names"], [])
        self.assertEqual(fault_injection_check["details"]["missing_required_case_ids"], [])
        self.assertEqual(fault_injection_check["details"]["coverage_ratio"], 1.0)
        self.assertEqual(promotion_checks["minimum_go_live_contract_pass"]["status"], "pass")
        self.assertEqual(promotion["release_gate"]["minimum_go_live"], minimum)
        self.assertNotIn("minimum_go_live", {item["source"] for item in promotion["blockers"]})
        self.assertFalse(promotion["can_promote"])
        self.assertIn("release_gate", {item["source"] for item in promotion["blockers"]})

    def test_harness_go_live_gate_contract_matches_release_gate(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import get_agent_release_gates

        def _parse_contract(text: str) -> dict[str, list[str]]:
            section = text[text.index("Required go-live gate contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            parsed: dict[str, list[str]] = {}
            for line in block.splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                parsed[key] = [item.strip() for item in value.split(",") if item.strip()]
            return parsed

        def _parse_payload_contract(text: str) -> dict[str, str | list[str]]:
            section = text[text.index("Required go-live gate payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, str | list[str]] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                parsed[key] = value.split(",") if key.endswith("fields") else value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            _parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required go-live gate contract:" in path.read_text(encoding="utf-8")
        ]
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required go-live gate payload contract:" in path.read_text(encoding="utf-8")
        ]
        expected_contract = {
            priority: list(gates)
            for priority, gates in GO_LIVE_GATE_REQUIREMENTS.items()
        }
        AgentRuntimeService(self.db).ensure_backend_contracts()

        release_gate = AgentReleaseGateService(self.db).snapshot()
        go_live_gates = release_gate["go_live_gates"]
        promotion = AgentReleaseGateService(self.db).promotion_assessment(target_level="L3", project_id=10)
        promotion_checks = {item["name"]: item for item in promotion["checks"]}
        route_payload = get_agent_release_gates(db=self.db, current_user=self.admin)["data"]

        self.assertEqual(len(documented_contracts), 2)
        for documented in documented_contracts:
            self.assertEqual(documented, expected_contract)
        self.assertEqual(len(documented_payload_contracts), 2)
        for documented in documented_payload_contracts:
            self.assertEqual(documented["fields"], list(GO_LIVE_GATE_FIELDS))
            self.assertEqual(documented["tier_fields"], list(GO_LIVE_GATE_TIER_FIELDS))
            self.assertEqual(documented["check_fields"], list(GO_LIVE_GATE_CHECK_FIELDS))
            self.assertEqual(documented["evidence"], "covered_by_agent_runtime_regression_suite")
        self.assertIn("go_live_gates", AgentReleaseGateRead.model_fields)
        self.assertEqual(list(go_live_gates), list(GO_LIVE_GATE_FIELDS))
        self.assertEqual(route_payload["go_live_gates"]["priorities"], list(GO_LIVE_GATE_REQUIREMENTS))
        self.assertEqual(go_live_gates["priorities"], list(GO_LIVE_GATE_REQUIREMENTS))
        self.assertTrue(go_live_gates["pass"])
        self.assertEqual(go_live_gates["missing_by_priority"], {})
        for tier in go_live_gates["tiers"]:
            self.assertEqual(list(tier), list(GO_LIVE_GATE_TIER_FIELDS))
            expected_gates = GO_LIVE_GATE_REQUIREMENTS[tier["priority"]]
            self.assertEqual(tier["required_gate_ids"], list(expected_gates))
            self.assertEqual(tier["passed_gate_ids"], list(expected_gates))
            self.assertEqual(tier["missing_gate_ids"], [])
            self.assertTrue(tier["pass"])
            self.assertTrue(all(list(item) == list(GO_LIVE_GATE_CHECK_FIELDS) for item in tier["checks"]))
            self.assertEqual(
                {item["gate_id"]: item["label"] for item in tier["checks"]},
                expected_gates,
            )
            self.assertEqual(
                {item["evidence"] for item in tier["checks"]},
                {"covered_by_agent_runtime_regression_suite"},
            )
        self.assertEqual(promotion_checks["go_live_gate_contract_pass"]["status"], "pass")
        self.assertEqual(promotion["release_gate"]["go_live_gates"], go_live_gates)
        self.assertNotIn("go_live_gates", {item["source"] for item in promotion["blockers"]})

    def test_harness_final_delivery_contract_matches_release_gate(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import get_agent_release_gates

        def _parse_contract(text: str) -> dict[str, list[str]]:
            section = text[text.index("Required final delivery contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            parsed: dict[str, list[str]] = {}
            for line in block.splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                parsed[key] = [item.strip() for item in value.split(",") if item.strip()]
            return parsed

        def _parse_payload_contract(text: str) -> dict[str, str | list[str]]:
            section = text[text.index("Required final delivery payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, str | list[str]] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                parsed[key] = value.split(",") if key.endswith("fields") else value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            _parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required final delivery contract:" in path.read_text(encoding="utf-8")
        ]
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required final delivery payload contract:" in path.read_text(encoding="utf-8")
        ]
        expected_contract = {
            category: list(artifacts)
            for category, artifacts in FINAL_DELIVERY_ARTIFACTS.items()
        }
        AgentRuntimeService(self.db).ensure_backend_contracts()
        release_gate = AgentReleaseGateService(self.db).snapshot()
        final_delivery = release_gate["final_delivery"]
        promotion = AgentReleaseGateService(self.db).promotion_assessment(target_level="L3", project_id=10)
        promotion_checks = {item["name"]: item for item in promotion["checks"]}
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        route_payload = get_agent_release_gates(db=self.db, current_user=self.admin)["data"]

        self.assertEqual(len(documented_contracts), 2)
        for documented in documented_contracts:
            self.assertEqual(documented, expected_contract)
        self.assertEqual(len(documented_payload_contracts), 2)
        for documented in documented_payload_contracts:
            self.assertEqual(documented["fields"], list(FINAL_DELIVERY_FIELDS))
            self.assertEqual(documented["category_fields"], list(FINAL_DELIVERY_CATEGORY_FIELDS))
            self.assertEqual(documented["check_fields"], list(FINAL_DELIVERY_CHECK_FIELDS))
            self.assertEqual(documented["external_scope_status"], "external_scope")
            self.assertEqual(documented["backend_owned_status"], "pass")
        self.assertIn("final_delivery", AgentReleaseGateRead.model_fields)
        self.assertEqual(list(final_delivery), list(FINAL_DELIVERY_FIELDS))
        self.assertEqual(route_payload["final_delivery"]["external_scope_categories"], ["frontend"])
        self.assertEqual(final_delivery["external_scope_categories"], sorted(FINAL_DELIVERY_EXTERNAL_SCOPE_CATEGORIES))
        self.assertTrue(final_delivery["pass"])
        self.assertTrue(final_delivery["backend_repository_scope_pass"])
        self.assertEqual(final_delivery["missing_by_category"], {})
        self.assertEqual(promotion_checks["final_delivery_contract_pass"]["status"], "pass")
        self.assertEqual(promotion["release_gate"]["final_delivery"], final_delivery)
        self.assertNotIn("final_delivery", {item["source"] for item in promotion["blockers"]})
        self.assertTrue(dashboard["promotion_assessment"]["final_delivery_contract_pass"])
        self.assertTrue(dashboard["promotion_assessment"]["final_delivery_backend_repository_scope_pass"])
        self.assertEqual(dashboard["promotion_assessment"]["final_delivery_missing_by_category"], {})
        self.assertEqual(dashboard["promotion_assessment"]["final_delivery_external_scope_categories"], ["frontend"])
        categories = {item["category"]: item for item in final_delivery["categories"]}
        self.assertEqual(set(categories), set(FINAL_DELIVERY_ARTIFACTS))
        for category, artifacts in FINAL_DELIVERY_ARTIFACTS.items():
            item = categories[category]
            self.assertEqual(list(item), list(FINAL_DELIVERY_CATEGORY_FIELDS))
            self.assertEqual(item["required_artifact_ids"], list(artifacts))
            self.assertEqual(item["missing_artifact_ids"], [])
            self.assertTrue(all(list(check) == list(FINAL_DELIVERY_CHECK_FIELDS) for check in item["checks"]))
            self.assertEqual(
                {check["artifact_id"]: check["label"] for check in item["checks"]},
                artifacts,
            )
            if category in FINAL_DELIVERY_EXTERNAL_SCOPE_CATEGORIES:
                self.assertTrue(item["external_scope"])
                self.assertEqual(item["delivered_artifact_ids"], [])
                self.assertEqual(item["external_scope_artifact_ids"], list(artifacts))
                self.assertEqual({check["status"] for check in item["checks"]}, {"external_scope"})
                self.assertEqual({check["evidence"] for check in item["checks"]}, {"owned_by_frontend_delivery"})
            else:
                self.assertFalse(item["external_scope"])
                self.assertEqual(item["delivered_artifact_ids"], list(artifacts))
                self.assertEqual(item["external_scope_artifact_ids"], [])
                self.assertEqual({check["status"] for check in item["checks"]}, {"pass"})
                self.assertEqual({check["evidence"] for check in item["checks"]}, {"covered_by_backend_agent_contracts"})

    def test_release_gate_promotion_assessment_includes_dashboard_alert_blockers(self):
        AgentRuntimeService(self.db).ensure_backend_contracts()
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="promotion alert blocker"),
            current_user=self.owner,
        )
        AgentRuntimeService(self.db).append_event(
            run,
            "memory.bypassed_evidence_ref",
            {"error_code": "memory_bypassed_evidence_ref"},
        )

        assessment = AgentReleaseGateService(self.db).promotion_assessment(target_level="L3", project_id=10)
        blockers = {item["source"] for item in assessment["blockers"]}
        checks = {item["name"]: item for item in assessment["checks"]}

        self.assertFalse(assessment["can_promote"])
        self.assertIn("readiness_dashboard", blockers)
        self.assertIn("monitoring_alerts", blockers)
        self.assertEqual(checks["readiness_dashboard_pass"]["status"], "blocked")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "blocked")
        alert_counts = checks["monitoring_alerts_clear"]["details"]["by_severity"]
        self.assertGreater(alert_counts["P0"] + alert_counts["P1"], 0)
        self.assertEqual(assessment["readiness"]["status"], "blocked")

    def test_observability_routes_scope_global_and_project_access(self):
        from app.api.v1.routers.agents import (
            get_agent_alerts,
            get_agent_backend_completion_audit,
            get_agent_launch_audit,
            get_agent_metrics,
            get_agent_readiness_dashboard,
        )

        outsider = User(
            id=4,
            username="outsider",
            account="outsider",
            password_hash="x",
            phone="10000000004",
            email="outsider@example.test",
            is_admin=False,
        )
        self.db.add(outsider)
        self.db.commit()

        for route in (
            get_agent_metrics,
            get_agent_readiness_dashboard,
            get_agent_launch_audit,
            get_agent_backend_completion_audit,
            get_agent_alerts,
        ):
            with self.assertRaises(HTTPException) as owner_global_ctx:
                route(db=self.db, current_user=self.owner)
            with self.assertRaises(HTTPException) as outsider_project_ctx:
                route(project_id=10, db=self.db, current_user=outsider)

            member_project = route(project_id=10, db=self.db, current_user=self.member)
            admin_global = route(db=self.db, current_user=self.admin)

            self.assertEqual(owner_global_ctx.exception.status_code, 403)
            self.assertEqual(outsider_project_ctx.exception.status_code, 403)
            self.assertEqual(member_project["data"]["project_id"], 10)
            self.assertIsNone(admin_global["data"]["project_id"])

    def test_operational_audit_routes_scope_global_and_project_access(self):
        from app.api.v1.routers.agents import (
            audit_agent_event_replay_stress,
            audit_agent_worker_queue,
        )

        outsider = User(
            id=4,
            username="outsider",
            account="outsider",
            password_hash="x",
            phone="10000000004",
            email="outsider@example.test",
            is_admin=False,
        )
        self.db.add(outsider)
        self.db.commit()

        route_calls = (
            (audit_agent_worker_queue, {}),
            (audit_agent_event_replay_stress, {"sample_limit": 100, "cursor_count": 3}),
        )
        for route, kwargs in route_calls:
            with self.assertRaises(HTTPException) as owner_global_ctx:
                route(db=self.db, current_user=self.owner, **kwargs)
            with self.assertRaises(HTTPException) as outsider_project_ctx:
                route(project_id=10, db=self.db, current_user=outsider, **kwargs)

            member_project = route(project_id=10, db=self.db, current_user=self.member, **kwargs)
            admin_global = route(db=self.db, current_user=self.admin, **kwargs)

            self.assertEqual(owner_global_ctx.exception.status_code, 403)
            self.assertEqual(outsider_project_ctx.exception.status_code, 403)
            self.assertEqual(member_project["data"]["project_id"], 10)
            self.assertIsNone(admin_global["data"]["project_id"])

    def test_run_scoped_governance_routes_require_run_project_access(self):
        from app.api.v1.routers.agents import (
            audit_agent_run_event_replay,
            diagnose_agent_runbook,
        )

        outsider = User(
            id=4,
            username="outsider",
            account="outsider",
            password_hash="x",
            phone="10000000004",
            email="outsider@example.test",
            is_admin=False,
        )
        self.db.add(outsider)
        self.db.commit()
        run = self._create_run("run scoped route permission")

        route_calls = (
            (diagnose_agent_runbook, {}),
            (audit_agent_run_event_replay, {"after_sequence": 0}),
        )
        for route, kwargs in route_calls:
            member_response = route(run_id=run.run_id, db=self.db, current_user=self.member, **kwargs)
            admin_response = route(run_id=run.run_id, db=self.db, current_user=self.admin, **kwargs)
            with self.assertRaises(HTTPException) as outsider_ctx:
                route(run_id=run.run_id, db=self.db, current_user=outsider, **kwargs)

            self.assertEqual(member_response["data"]["run_id"], run.run_id)
            self.assertEqual(admin_response["data"]["run_id"], run.run_id)
            self.assertEqual(outsider_ctx.exception.status_code, 403)

    def test_run_event_stream_route_requires_run_project_access(self):
        from app.api.v1.routers.agents import stream_agent_run_events

        outsider = User(
            id=4,
            username="outsider",
            account="outsider",
            password_hash="x",
            phone="10000000004",
            email="outsider@example.test",
            is_admin=False,
        )
        self.db.add(outsider)
        self.db.commit()
        run = self._create_run("run event stream route permission")

        member_response = stream_agent_run_events(
            run_id=run.run_id,
            last_event_id=0,
            db=self.db,
            current_user=self.member,
        )
        admin_response = stream_agent_run_events(
            run_id=run.run_id,
            last_event_id=0,
            db=self.db,
            current_user=self.admin,
        )
        with self.assertRaises(HTTPException) as outsider_ctx:
            stream_agent_run_events(
                run_id=run.run_id,
                last_event_id=0,
                db=self.db,
                current_user=outsider,
            )

        self.assertEqual(member_response.media_type, "text/event-stream")
        self.assertEqual(admin_response.media_type, "text/event-stream")
        self.assertEqual(outsider_ctx.exception.status_code, 403)

    def test_run_event_stream_resets_cross_run_last_event_id(self):
        import asyncio

        from app.api.v1.routers.agents import stream_agent_run_events

        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="sse cursor reset", auto_complete=True),
            current_user=self.owner,
        )

        async def read_stream(response) -> str:
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
            return "".join(chunks)

        with patch("app.api.v1.routers.agents.SessionLocal", self.Session):
            response = stream_agent_run_events(
                run_id=run.run_id,
                last_event_id=9999,
                db=self.db,
                current_user=self.member,
            )
            body = asyncio.run(read_stream(response))

        self.assertIn("event: run.queued", body)
        self.assertIn("event: run.started", body)
        self.assertIn("event: run.completed", body)
        self.assertNotIn("event: heartbeat", body)

    def test_run_event_snapshot_route_returns_cursor_state_and_requires_project_access(self):
        from app.api.v1.routers.agents import get_agent_run_event_snapshot

        outsider = User(
            id=4,
            username="outsider",
            account="outsider",
            email="outsider@example.com",
            phone="13900000004",
            password_hash="x",
            is_active=True,
            is_admin=False,
        )
        self.db.add(outsider)
        self.db.commit()
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="event snapshot", auto_complete=True),
            current_user=self.owner,
        )

        response = get_agent_run_event_snapshot(
            run_id=run.run_id,
            after_sequence=1,
            limit=10,
            db=self.db,
            current_user=self.member,
        )
        payload = response["data"]

        self.assertEqual(list(AgentRunEventSnapshotRead.model_fields), list(AGENT_RUN_EVENT_SNAPSHOT_FIELDS))
        self.assertEqual(list(payload), list(AGENT_RUN_EVENT_SNAPSHOT_FIELDS))
        self.assertEqual(payload["run"]["run_id"], run.run_id)
        self.assertEqual([item["event_seq"] for item in payload["events"]], [2, 3])
        self.assertEqual([item["event_type"] for item in payload["events"]], ["run.started", "run.completed"])
        self.assertEqual(payload["after_sequence"], 1)
        self.assertEqual(payload["event_count"], 2)
        self.assertEqual(payload["latest_event_sequence"], 3)
        self.assertEqual(payload["next_after_sequence"], 3)
        self.assertTrue(payload["terminal"])
        for event_payload in payload["events"]:
            self.assertEqual(list(event_payload), list(AGENT_EVENT_FIELDS))

        with self.assertRaises(HTTPException) as outsider_ctx:
            get_agent_run_event_snapshot(
                run_id=run.run_id,
                after_sequence=0,
                limit=10,
                db=self.db,
                current_user=outsider,
            )
        self.assertEqual(outsider_ctx.exception.status_code, 403)

    def test_object_scoped_read_routes_require_project_access(self):
        from app.api.v1.routers.agents import (
            get_agent_runtime_snapshot,
            get_agent_tool_call,
        )

        outsider = User(
            id=4,
            username="outsider",
            account="outsider",
            password_hash="x",
            phone="10000000004",
            email="outsider@example.test",
            is_admin=False,
        )
        self.db.add(outsider)
        self.db.commit()
        run = self._create_run("object scoped route permission")
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=self.owner,
            enqueue=False,
        )

        snapshot_member = get_agent_runtime_snapshot(
            snapshot_id=run.runtime_snapshot_id,
            db=self.db,
            current_user=self.member,
        )
        snapshot_admin = get_agent_runtime_snapshot(
            snapshot_id=run.runtime_snapshot_id,
            db=self.db,
            current_user=self.admin,
        )
        tool_call_member = get_agent_tool_call(
            tool_call_id=call.tool_call_id,
            db=self.db,
            current_user=self.member,
        )
        tool_call_admin = get_agent_tool_call(
            tool_call_id=call.tool_call_id,
            db=self.db,
            current_user=self.admin,
        )
        with self.assertRaises(HTTPException) as outsider_snapshot_ctx:
            get_agent_runtime_snapshot(
                snapshot_id=run.runtime_snapshot_id,
                db=self.db,
                current_user=outsider,
            )
        with self.assertRaises(HTTPException) as outsider_tool_call_ctx:
            get_agent_tool_call(
                tool_call_id=call.tool_call_id,
                db=self.db,
                current_user=outsider,
            )

        self.assertEqual(snapshot_member["data"]["snapshot_id"], run.runtime_snapshot_id)
        self.assertEqual(snapshot_admin["data"]["snapshot_id"], run.runtime_snapshot_id)
        self.assertEqual(tool_call_member["data"]["tool_call_id"], call.tool_call_id)
        self.assertEqual(tool_call_admin["data"]["tool_call_id"], call.tool_call_id)
        self.assertEqual(outsider_snapshot_ctx.exception.status_code, 403)
        self.assertEqual(outsider_tool_call_ctx.exception.status_code, 403)

    def test_run_derived_resource_routes_require_run_project_access(self):
        from app.api.v1.routers.agents import (
            create_agent_context_build,
            create_agent_loop_observation,
            list_agent_context_builds,
            list_agent_loop_observations,
            list_agent_migration_blocks,
            list_agent_run_approvals,
            resolve_agent_migration_block,
        )

        outsider = User(
            id=4,
            username="outsider",
            account="outsider",
            password_hash="x",
            phone="10000000004",
            email="outsider@example.test",
            is_admin=False,
        )
        self.db.add(outsider)
        self.db.commit()

        run = self._create_run("run derived route permission")
        context_payload = AgentContextBuildCreateRequest(
            build_purpose="plan",
            step_index=0,
            token_budget=128,
            evidence_refs=[],
        )
        with self.assertRaises(HTTPException) as outsider_create_context_ctx:
            create_agent_context_build(
                run_id=run.run_id,
                payload=context_payload,
                db=self.db,
                current_user=outsider,
            )
        context_response = create_agent_context_build(
            run_id=run.run_id,
            payload=context_payload,
            db=self.db,
            current_user=self.member,
        )
        with self.assertRaises(HTTPException) as outsider_list_context_ctx:
            list_agent_context_builds(run_id=run.run_id, db=self.db, current_user=outsider)
        context_list_response = list_agent_context_builds(run_id=run.run_id, db=self.db, current_user=self.member)

        context_build_id = context_response["data"]["context_build_id"]
        loop_payload = AgentLoopObservationCreateRequest(
            decision_context_build_id=context_build_id,
            next_action="repair",
            next_action_is_high_risk=False,
            reasons=["same_failure_no_progress"],
        )
        with self.assertRaises(HTTPException) as outsider_create_loop_ctx:
            create_agent_loop_observation(
                run_id=run.run_id,
                payload=loop_payload,
                db=self.db,
                current_user=outsider,
            )
        loop_response = create_agent_loop_observation(
            run_id=run.run_id,
            payload=loop_payload,
            db=self.db,
            current_user=self.member,
        )
        with self.assertRaises(HTTPException) as outsider_list_loop_ctx:
            list_agent_loop_observations(run_id=run.run_id, db=self.db, current_user=outsider)
        loop_list_response = list_agent_loop_observations(run_id=run.run_id, db=self.db, current_user=self.member)

        approval_run, _, approval = self._create_pending_approval()
        with self.assertRaises(HTTPException) as outsider_approvals_ctx:
            list_agent_run_approvals(run_id=approval_run.run_id, db=self.db, current_user=outsider)
        approvals_response = list_agent_run_approvals(
            run_id=approval_run.run_id,
            db=self.db,
            current_user=self.member,
        )

        migration_run, _, block = self._create_migration_block()
        with self.assertRaises(HTTPException) as outsider_blocks_ctx:
            list_agent_migration_blocks(run_id=migration_run.run_id, db=self.db, current_user=outsider)
        blocks_response = list_agent_migration_blocks(
            run_id=migration_run.run_id,
            db=self.db,
            current_user=self.member,
        )
        with self.assertRaises(HTTPException) as outsider_resolve_ctx:
            resolve_agent_migration_block(
                run_id=migration_run.run_id,
                block_id=block.block_id,
                payload=AgentMigrationBlockResolveRequest(resolution_note="outsider"),
                db=self.db,
                current_user=outsider,
            )
        resolve_response = resolve_agent_migration_block(
            run_id=migration_run.run_id,
            block_id=block.block_id,
            payload=AgentMigrationBlockResolveRequest(resolution_note="member verified"),
            db=self.db,
            current_user=self.member,
        )

        self.assertEqual(outsider_create_context_ctx.exception.status_code, 403)
        self.assertEqual(outsider_list_context_ctx.exception.status_code, 403)
        self.assertEqual(outsider_create_loop_ctx.exception.status_code, 403)
        self.assertEqual(outsider_list_loop_ctx.exception.status_code, 403)
        self.assertEqual(outsider_approvals_ctx.exception.status_code, 403)
        self.assertEqual(outsider_blocks_ctx.exception.status_code, 403)
        self.assertEqual(outsider_resolve_ctx.exception.status_code, 403)
        self.assertEqual(context_response["data"]["run_id"], run.run_id)
        self.assertEqual(context_list_response["data"][0]["context_build_id"], context_build_id)
        self.assertEqual(loop_response["data"]["run_id"], run.run_id)
        self.assertEqual(loop_list_response["data"][0]["observation_id"], loop_response["data"]["observation_id"])
        self.assertEqual(approvals_response["data"][0]["approval_id"], approval.approval_id)
        self.assertEqual(blocks_response["data"][0]["block_id"], block.block_id)
        self.assertEqual(resolve_response["data"]["block"]["block_id"], block.block_id)

    def test_approval_expiration_routes_scope_global_and_project_access(self):
        from app.api.v1.routers.agents import (
            audit_agent_approval_expiration,
            process_agent_approval_expiration,
        )

        outsider = User(
            id=4,
            username="outsider",
            account="outsider",
            password_hash="x",
            phone="10000000004",
            email="outsider@example.test",
            is_admin=False,
        )
        self.db.add(outsider)
        self.db.commit()

        route_calls = (
            (audit_agent_approval_expiration, {}),
            (process_agent_approval_expiration, {"limit": 100}),
        )
        for route, kwargs in route_calls:
            with self.assertRaises(HTTPException) as owner_global_ctx:
                route(db=self.db, current_user=self.owner, **kwargs)
            with self.assertRaises(HTTPException) as outsider_project_ctx:
                route(project_id=10, db=self.db, current_user=outsider, **kwargs)

            member_project = route(project_id=10, db=self.db, current_user=self.member, **kwargs)
            admin_global = route(db=self.db, current_user=self.admin, **kwargs)

            self.assertEqual(owner_global_ctx.exception.status_code, 403)
            self.assertEqual(outsider_project_ctx.exception.status_code, 403)
            self.assertEqual(member_project["data"]["project_id"], 10)
            self.assertIsNone(admin_global["data"]["project_id"])

    def test_readiness_dashboard_combines_metrics_gates_faults_and_runbooks(self):
        AgentRuntimeService(self.db).ensure_backend_contracts()

        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertEqual(dashboard["readiness"], "pass")
        self.assertEqual(checks["metrics_catalog_complete"]["status"], "pass")
        self.assertEqual(checks["release_gate_current_level_clean"]["status"], "pass")
        self.assertEqual(checks["fault_injection_catalog_complete"]["status"], "pass")
        self.assertEqual(checks["runbook_catalog_complete"]["status"], "pass")
        self.assertEqual(checks["alert_metric_catalog_complete"]["status"], "pass")
        self.assertEqual(
            checks["alert_metric_catalog_complete"]["details"]["missing_alert_metric_keys"],
            [],
        )
        self.assertIn(
            "event_replay_stress_cursor_window_total",
            checks["alert_metric_catalog_complete"]["details"]["related_metric_keys"],
        )
        self.assertIn(
            "release_gate_violation_count",
            checks["alert_metric_catalog_complete"]["details"]["dynamic_metric_keys"],
        )
        self.assertIn(
            "checkpoint_freshness_failed_total",
            checks["alert_metric_catalog_complete"]["details"]["trigger_metric_keys"],
        )
        self.assertEqual(
            checks["fault_injection_catalog_complete"]["details"]["missing_required_case_ids"],
            [],
        )
        self.assertEqual(
            len(checks["fault_injection_catalog_complete"]["details"]["covered_required_case_ids"]),
            26,
        )
        self.assertEqual(
            checks["runbook_catalog_complete"]["details"]["missing_required_runbook_ids"],
            [],
        )
        self.assertIn(
            "checkpoint_stale",
            checks["runbook_catalog_complete"]["details"]["covered_required_runbook_ids"],
        )
        self.assertEqual(checks["root_cause_rule_governance"]["status"], "pass")
        self.assertTrue(dashboard["root_cause_governance"]["governance_pass"])
        self.assertEqual(dashboard["root_cause_governance"]["violation_count"], 0)
        self.assertEqual(checks["release_gate_promotion_assessment"]["status"], "pass")
        self.assertEqual(
            checks["release_gate_promotion_assessment"]["details"]["endpoint"],
            "/api/v1/agents/release-gates/promotion",
        )
        self.assertEqual(dashboard["fault_injection"]["required_case_count"], 26)
        self.assertEqual(dashboard["fault_injection"]["registered_case_count"], 26)
        self.assertTrue(dashboard["fault_injection"]["coverage_pass"])
        self.assertEqual(dashboard["fault_injection"]["missing_required_case_ids"], [])
        self.assertEqual(dashboard["runbooks"]["missing_required_runbook_ids"], [])
        self.assertIn("worker_queue_recovery", dashboard["runbooks"]["covered_required_runbook_ids"])
        self.assertIn("memory_evidence_ref_violation", dashboard["runbooks"]["covered_required_runbook_ids"])
        self.assertIn("release_gate_violation", dashboard["runbooks"]["covered_required_runbook_ids"])
        self.assertIn("backend_capability_degraded", dashboard["runbooks"]["covered_required_runbook_ids"])
        self.assertEqual(dashboard["release_gate"]["current_level"], "L2")
        self.assertEqual(
            dashboard["metrics"]["release_gate_violation_count"],
            len(dashboard["release_gate"]["violations"]),
        )
        self.assertTrue(dashboard["promotion_assessment"]["assessment_available"])
        self.assertEqual(dashboard["promotion_assessment"]["target_level"], "L3")
        self.assertIn(
            "business_create tools remain intentionally unregistered",
            dashboard["promotion_assessment"]["target_gate_static_blocked_reasons"],
        )
        self.assertEqual(dashboard["alerts"], [])
        self.assertEqual(dashboard["alert_summary"]["total"], 0)
        required_metrics = set(checks["metrics_catalog_complete"]["details"]["required_metric_keys"])
        for metric_key in [
            "tool_call_orphan_recovered_total",
            "tool_call_send_intent_orphan_total",
            "tool_call_safe_retry_after_send_intent_not_found_total",
            "tool_call_transport_sent_uncertain_total",
            "tool_call_backend_accepted_uncertain_total",
            "backend_effect_capability_receipt_first_total",
            "backend_effect_capability_legacy_no_receipt_total",
            "tool_call_legacy_no_receipt_manual_total",
            "tool_call_backend_contract_unsupported_total",
            "approval_superseded_total",
            "approval_approve_conflict_total",
            "approval_lineage_lock_wait_ms",
            "approval_lineage_lock_skip_total",
            "context_degraded_total",
            "runtime_snapshot_migration_block_total",
            "backend_contract_migration_block_total",
            "run_migration_blocked_total",
            "context_decision_build_missing_total",
            "loop_root_cause_context_degraded_total",
            "loop_root_cause_unknown_total",
            "invalid_repair_scope_total",
            "same_failure_no_progress_total",
            "memory_contradiction_penalty_applied_total",
            "memory_retrieved_total",
            "memory_used_active_policy_total",
            "memory_retrieval_profile_missing_total",
            "memory_low_confidence_filtered_total",
            "memory_evidence_watch_stale_total",
            "release_gate_violation_count",
            "backend_capability_degraded_total",
        ]:
            self.assertIn(metric_key, required_metrics)
            self.assertIn(metric_key, dashboard["metrics"])
        self.assertIn("memory_bypassed_evidence_ref_total", dashboard["metrics"])
        self.assertEqual(dashboard["metrics"]["fault_injection_required_case_total"], 26)
        self.assertEqual(dashboard["metrics"]["fault_injection_missing_required_total"], 0)

    def test_launch_audit_combines_model_dashboard_and_frontend_contracts(self):
        from app.api.v1.routers.agents import get_agent_launch_audit

        provider = SimpleNamespace(
            provider="deepseek",
            base_url="https://api.deepseek.test",
            default_model="deepseek-test",
            configured=True,
        )
        AgentRuntimeService(self.db).ensure_backend_contracts()
        with (
            patch("app.services.agent_runtime_service.AIService.provider_config", return_value=provider),
            patch("app.services.agent_runtime_service.AIService.chat_stream") as chat_stream,
        ):
            audit = AgentLaunchAuditService(self.db).audit(project_id=10)
            route_payload = get_agent_launch_audit(project_id=10, db=self.db, current_user=self.owner)["data"]

        checks = {item["name"]: item for item in audit["checks"]}
        self.assertEqual(list(AgentLaunchAuditRead.model_fields), list(AGENT_LAUNCH_AUDIT_FIELDS))
        self.assertEqual(list(audit), list(AGENT_LAUNCH_AUDIT_FIELDS))
        self.assertEqual(list(route_payload), list(AGENT_LAUNCH_AUDIT_FIELDS))
        self.assertEqual([item["name"] for item in audit["checks"]], list(AGENT_LAUNCH_AUDIT_CHECK_NAMES))
        self.assertTrue(all(list(item) == list(DASHBOARD_CHECK_FIELDS) for item in audit["checks"]))
        self.assertTrue(audit["ready"])
        self.assertEqual(audit["status"], "pass")
        self.assertTrue(audit["model_health"]["configured"])
        self.assertFalse(audit["model_health"]["live"])
        self.assertEqual(audit["dashboard"]["readiness"], "pass")
        self.assertEqual(audit["promotion"]["decision"], "blocked")
        self.assertEqual(checks["frontend_event_contract_available"]["details"]["summary_path"], "GET /api/v1/agents/runs/{run_id}/summary")
        self.assertTrue(checks["backend_repository_delivery_complete"]["details"]["backend_repository_scope_pass"])
        self.assertEqual(checks["frontend_external_scope_declared"]["status"], "pass")
        chat_stream.assert_not_called()

    def test_launch_audit_blocks_when_model_provider_is_unconfigured(self):
        provider = SimpleNamespace(
            provider="deepseek",
            base_url="https://api.deepseek.test",
            default_model="deepseek-test",
            configured=False,
        )

        with patch("app.services.agent_runtime_service.AIService.provider_config", return_value=provider):
            audit = AgentLaunchAuditService(self.db).audit(project_id=10)

        checks = {item["name"]: item for item in audit["checks"]}
        self.assertFalse(audit["ready"])
        self.assertEqual(audit["status"], "blocked")
        self.assertEqual(checks["model_provider_configured"]["status"], "blocked")

    def test_backend_completion_audit_summarizes_agent_backend_delivery(self):
        from app.api.v1.routers.agents import get_agent_backend_completion_audit
        from scripts.agent_behavior_evaluation import CASES as AGENT_BEHAVIOR_EVALUATION_CASES

        provider = SimpleNamespace(
            provider="deepseek",
            base_url="https://api.deepseek.test",
            default_model="deepseek-test",
            configured=True,
        )
        AgentRuntimeService(self.db).ensure_backend_contracts()
        with (
            patch("app.services.agent_runtime_service.AIService.provider_config", return_value=provider),
            patch("app.services.agent_runtime_service.AIService.chat_stream") as chat_stream,
        ):
            audit = AgentBackendCompletionAuditService(self.db).audit(project_id=10)
            route_payload = get_agent_backend_completion_audit(project_id=10, db=self.db, current_user=self.owner)[
                "data"
            ]

        checks = {item["name"]: item for item in audit["checks"]}
        self.assertEqual(list(AgentBackendCompletionAuditRead.model_fields), list(AGENT_BACKEND_COMPLETION_AUDIT_FIELDS))
        self.assertEqual(list(audit), list(AGENT_BACKEND_COMPLETION_AUDIT_FIELDS))
        self.assertEqual(list(route_payload), list(AGENT_BACKEND_COMPLETION_AUDIT_FIELDS))
        self.assertEqual(
            [item["name"] for item in audit["checks"]],
            list(AGENT_BACKEND_COMPLETION_AUDIT_CHECK_NAMES),
        )
        self.assertTrue(all(list(item) == list(DASHBOARD_CHECK_FIELDS) for item in audit["checks"]))
        self.assertTrue(audit["complete"])
        self.assertEqual(audit["status"], "pass")
        self.assertTrue(audit["launch_audit"]["ready"])
        self.assertTrue(audit["launch_audit"]["model_configured"])
        self.assertEqual(audit["backend_scope"]["frontend_delivery"], "external repository")
        self.assertEqual(audit["runtime_contracts"]["summary"], "GET /api/v1/agents/runs/{run_id}/summary")
        self.assertEqual(
            audit["runtime_contracts"]["tool_execution_context"],
            "AgentToolCall.policy_reason_json.execution_context",
        )
        self.assertEqual(
            audit["runtime_contracts"]["runbook_execution_context_summary"],
            "AgentRunbookRecommendation.details.execution_context",
        )
        self.assertEqual(
            audit["runtime_contracts"]["runbook_execution_context_summary_fields"],
            list(RUNBOOK_EXECUTION_CONTEXT_SUMMARY_FIELDS),
        )
        self.assertEqual(audit["diagnostics"]["completion_audit"], "GET /api/v1/agents/backend-completion-audit")
        self.assertEqual(audit["diagnostics"]["tool_call_detail"], "GET /api/v1/agents/tool-calls/{tool_call_id}")
        self.assertEqual(audit["diagnostics"]["runbook_diagnosis"], "GET /api/v1/agents/runs/{run_id}/runbook")
        self.assertEqual(
            checks["observability_and_release_gate"]["details"]["tool_execution_context_source"],
            "AgentToolCall.policy_reason_json.execution_context",
        )
        self.assertEqual(
            checks["observability_and_release_gate"]["details"]["runbook_execution_context_summary_fields"],
            list(RUNBOOK_EXECUTION_CONTEXT_SUMMARY_FIELDS),
        )
        self.assertIn("model.delta", checks["conversation_runner_streaming"]["details"]["required_event_types"])
        self.assertIn(
                "scripts/agent_conversation_e2e_check.py",
            checks["live_e2e_diagnostic_available"]["details"]["normal_user_script"],
        )
        behavior_case_ids = [case.case_id for case in AGENT_BEHAVIOR_EVALUATION_CASES]
        self.assertEqual(
            checks["behavior_evaluation_suite_available"]["details"]["script"],
            "scripts/agent_behavior_evaluation.py",
        )
        self.assertEqual(
            checks["behavior_evaluation_suite_available"]["details"]["case_ids"],
            behavior_case_ids,
        )
        self.assertEqual(
            checks["behavior_evaluation_suite_available"]["details"]["case_count"],
            len(behavior_case_ids),
        )
        self.assertIn(
            "query_first_tool_order",
            checks["behavior_evaluation_suite_available"]["details"]["assertions"],
        )
        self.assertEqual(
            audit["diagnostics"]["behavior_evaluation_script"],
            "scripts/agent_behavior_evaluation.py",
        )
        self.assertEqual(
            audit["diagnostics"]["behavior_evaluation_reports"],
            "reports/woagent_behavior_eval_*.json|md",
        )
        chat_stream.assert_not_called()

    def test_backend_completion_audit_blocks_when_model_provider_is_unconfigured(self):
        provider = SimpleNamespace(
            provider="deepseek",
            base_url="https://api.deepseek.test",
            default_model="deepseek-test",
            configured=False,
        )

        with patch("app.services.agent_runtime_service.AIService.provider_config", return_value=provider):
            audit = AgentBackendCompletionAuditService(self.db).audit(project_id=10)

        checks = {item["name"]: item for item in audit["checks"]}
        self.assertFalse(audit["complete"])
        self.assertEqual(audit["status"], "blocked")
        self.assertEqual(checks["model_provider_configured"]["status"], "blocked")

    def test_harness_launch_audit_payload_contract_matches_service(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import get_agent_launch_audit

        def parse_contract(text: str) -> dict[str, str | list[str]]:
            section = text[text.index("Required launch audit payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, str | list[str]] = {}
            for line in block.group(1).splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                parsed[key] = (
                    [item.strip() for item in value.split(",") if item.strip()]
                    if key
                    in {
                        "fields",
                        "check_fields",
                        "checks",
                        "status_values",
                        "runtime_contract_keys",
                        "diagnostic_keys",
                        "runbook_execution_context_summary_fields",
                        "behavior_evaluation_case_ids",
                        "behavior_evaluation_assertions",
                    }
                    else value
                )
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required launch audit payload contract:" in path.read_text(encoding="utf-8")
        ]
        provider = SimpleNamespace(
            provider="deepseek",
            base_url="https://api.deepseek.test",
            default_model="deepseek-test",
            configured=True,
        )
        with patch("app.services.agent_runtime_service.AIService.provider_config", return_value=provider):
            snapshot = AgentLaunchAuditService(self.db).audit(project_id=10)
            route_payload = get_agent_launch_audit(project_id=10, db=self.db, current_user=self.owner)["data"]

        self.assertEqual(len(documented_contracts), 2)
        for contract in documented_contracts:
            self.assertEqual(contract["fields"], list(AGENT_LAUNCH_AUDIT_FIELDS))
            self.assertEqual(contract["check_fields"], list(DASHBOARD_CHECK_FIELDS))
            self.assertEqual(contract["checks"], list(AGENT_LAUNCH_AUDIT_CHECK_NAMES))
            self.assertEqual(contract["status_values"], list(READINESS_STATUS_VALUES))
            self.assertEqual(contract["source"], "AgentLaunchAuditService.audit")
        self.assertEqual(list(AgentLaunchAuditRead.model_fields), list(AGENT_LAUNCH_AUDIT_FIELDS))
        self.assertEqual(list(snapshot), list(AGENT_LAUNCH_AUDIT_FIELDS))
        self.assertEqual(list(route_payload), list(AGENT_LAUNCH_AUDIT_FIELDS))
        self.assertEqual([item["name"] for item in snapshot["checks"]], list(AGENT_LAUNCH_AUDIT_CHECK_NAMES))
        self.assertEqual([item["name"] for item in route_payload["checks"]], list(AGENT_LAUNCH_AUDIT_CHECK_NAMES))

    def test_harness_backend_completion_audit_payload_contract_matches_service(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import get_agent_backend_completion_audit

        def parse_contract(text: str) -> dict[str, str | list[str]]:
            section = text[text.index("Required backend completion audit payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, str | list[str]] = {}
            for line in block.group(1).splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                parsed[key] = (
                    [item.strip() for item in value.split(",") if item.strip()]
                    if key
                    in {
                        "fields",
                        "check_fields",
                        "checks",
                        "status_values",
                        "runtime_contract_keys",
                        "diagnostic_keys",
                        "runbook_execution_context_summary_fields",
                    }
                    else value
                )
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required backend completion audit payload contract:" in path.read_text(encoding="utf-8")
        ]
        provider = SimpleNamespace(
            provider="deepseek",
            base_url="https://api.deepseek.test",
            default_model="deepseek-test",
            configured=True,
        )
        with patch("app.services.agent_runtime_service.AIService.provider_config", return_value=provider):
            snapshot = AgentBackendCompletionAuditService(self.db).audit(project_id=10)
            route_payload = get_agent_backend_completion_audit(project_id=10, db=self.db, current_user=self.owner)[
                "data"
            ]

        self.assertEqual(len(documented_contracts), 2)
        for contract in documented_contracts:
            self.assertEqual(contract["fields"], list(AGENT_BACKEND_COMPLETION_AUDIT_FIELDS))
            self.assertEqual(contract["check_fields"], list(DASHBOARD_CHECK_FIELDS))
            self.assertEqual(contract["checks"], list(AGENT_BACKEND_COMPLETION_AUDIT_CHECK_NAMES))
            self.assertEqual(contract["status_values"], list(READINESS_STATUS_VALUES))
            self.assertEqual(contract["runtime_contract_keys"], list(snapshot["runtime_contracts"]))
            self.assertEqual(contract["diagnostic_keys"], list(snapshot["diagnostics"]))
            self.assertEqual(
                contract["runbook_execution_context_summary_fields"],
                list(RUNBOOK_EXECUTION_CONTEXT_SUMMARY_FIELDS),
            )
            behavior_check = {
                item["name"]: item for item in snapshot["checks"]
            }["behavior_evaluation_suite_available"]
            self.assertEqual(
                contract["behavior_evaluation_case_ids"],
                behavior_check["details"]["case_ids"],
            )
            self.assertEqual(
                contract["behavior_evaluation_assertions"],
                behavior_check["details"]["assertions"],
            )
            self.assertEqual(contract["source"], "AgentBackendCompletionAuditService.audit")
        self.assertEqual(list(AgentBackendCompletionAuditRead.model_fields), list(AGENT_BACKEND_COMPLETION_AUDIT_FIELDS))
        self.assertEqual(list(snapshot), list(AGENT_BACKEND_COMPLETION_AUDIT_FIELDS))
        self.assertEqual(list(route_payload), list(AGENT_BACKEND_COMPLETION_AUDIT_FIELDS))
        self.assertEqual(
            [item["name"] for item in snapshot["checks"]],
            list(AGENT_BACKEND_COMPLETION_AUDIT_CHECK_NAMES),
        )
        self.assertEqual(
            [item["name"] for item in route_payload["checks"]],
            list(AGENT_BACKEND_COMPLETION_AUDIT_CHECK_NAMES),
        )

    def test_harness_dashboard_promotion_summary_contract_matches_dashboard(self):
        from pathlib import Path
        import re

        def parse_contract(text: str) -> dict[str, str | list[str]]:
            section = text[text.index("Required dashboard promotion summary contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, str | list[str]] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                parsed[key] = value.split(",") if key == "summary_fields" else value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        contracts = [
            parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required dashboard promotion summary contract:" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(len(contracts), 2)

        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks = {item["name"]: item for item in dashboard["checks"]}
        summary = dashboard["promotion_assessment"]
        check = checks["release_gate_promotion_assessment"]

        for contract in contracts:
            self.assertEqual(contract["summary_fields"], list(PROMOTION_DASHBOARD_SUMMARY_FIELDS))
            self.assertEqual(contract["dashboard_check"], "release_gate_promotion_assessment")
            self.assertEqual(contract["endpoint"], "/api/v1/agents/release-gates/promotion")
            self.assertEqual(contract["dashboard_dependency"], "summary_only_no_recursive_promotion_call")

        self.assertEqual(list(summary), list(PROMOTION_DASHBOARD_SUMMARY_FIELDS))
        self.assertEqual(check["details"], summary)
        self.assertEqual(check["details"]["endpoint"], "/api/v1/agents/release-gates/promotion")
        self.assertEqual(check["details"]["target_level"], "L3")
        self.assertTrue(check["details"]["assessment_available"])
        self.assertIn("without invoking the endpoint", check["details"]["dashboard_dependency"])
        self.assertEqual(
            check["details"]["current_tool_violation_count"],
            len(check["details"]["current_tool_violations"]),
        )
        self.assertEqual(check["details"]["final_delivery_external_scope_categories"], ["frontend"])

    def test_harness_metrics_catalog_matches_architecture_contract(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import get_agent_metrics
        from app.services.agent_observability_service import REQUIRED_DASHBOARD_METRICS

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required metrics snapshot payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        docs = [
            path.read_text(encoding="utf-8")
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
        ]
        architecture_text = next(
            text
            for text in docs
            if "Required dashboard metrics:" in text
        )
        metric_section = architecture_text[
            architecture_text.index("Required dashboard metrics:"):
            architecture_text.index("`runbook_catalog_complete` 必须输出")
        ]
        metric_block = re.search(r"```text\n(.*?)\n```", metric_section, re.S)
        self.assertIsNotNone(metric_block)
        documented_metrics = {
            line.strip()
            for line in metric_block.group(1).splitlines()
            if line.strip()
        }
        documented_payload_contracts = [
            _parse_payload_contract(text)
            for text in docs
            if "Required metrics snapshot payload contract:" in text
        ]
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        snapshot = AgentMetricsService(self.db).snapshot(project_id=10)
        route_payload = get_agent_metrics(project_id=10, db=self.db, current_user=self.owner)["data"]
        metrics_check = {
            item["name"]: item
            for item in dashboard["checks"]
        }["metrics_catalog_complete"]
        details = metrics_check["details"]

        self.assertEqual(documented_metrics, REQUIRED_DASHBOARD_METRICS)
        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(METRICS_SNAPSHOT_FIELDS))
            self.assertEqual(contract["derived_from_fields"], list(METRICS_DERIVED_FROM_FIELDS))
            self.assertEqual(contract["metrics_key_source"], "REQUIRED_DASHBOARD_METRICS")
            self.assertEqual(contract["source"], "AgentMetricsService.snapshot")
        self.assertEqual(list(AgentMetricsSnapshotRead.model_fields), list(METRICS_SNAPSHOT_FIELDS))
        self.assertEqual(list(snapshot), list(METRICS_SNAPSHOT_FIELDS))
        self.assertEqual(list(route_payload), list(METRICS_SNAPSHOT_FIELDS))
        self.assertEqual(list(snapshot["derived_from"]), list(METRICS_DERIVED_FROM_FIELDS))
        self.assertEqual(list(route_payload["derived_from"]), list(METRICS_DERIVED_FROM_FIELDS))
        self.assertEqual(set(details["required_metric_keys"]), REQUIRED_DASHBOARD_METRICS)
        self.assertEqual(details["required_metric_count"], len(REQUIRED_DASHBOARD_METRICS))
        self.assertEqual(details["missing_metric_keys"], [])
        self.assertEqual(REQUIRED_DASHBOARD_METRICS - set(snapshot["metrics"]), set())
        self.assertEqual(REQUIRED_DASHBOARD_METRICS - set(route_payload["metrics"]), set())
        self.assertEqual(REQUIRED_DASHBOARD_METRICS - set(dashboard["metrics"]), set())

    def test_harness_alert_metric_catalog_matches_architecture_contract(self):
        from pathlib import Path
        import re

        from app.services.agent_observability_service import (
            ALERT_FACT_METRICS,
            ALERT_DYNAMIC_RUNBOOKS,
            ALERT_RUNBOOK_REQUIRED_SEVERITIES,
            ALERT_RULES,
            DYNAMIC_ALERT_METRICS,
        )

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        architecture_text = next(
            path.read_text(encoding="utf-8")
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "AgentAlertService 当前按以下事实表指标触发 firing alerts" in path.read_text(encoding="utf-8")
        )
        metric_section = architecture_text[
            architecture_text.index("AgentAlertService 当前按以下事实表指标触发 firing alerts："):
            architecture_text.index("报警建议：")
        ]
        metric_block = re.search(r"```text\n(.*?)\n```", metric_section, re.S)
        self.assertIsNotNone(metric_block)
        documented_metrics = {
            line.strip()
            for line in metric_block.group(1).splitlines()
            if line.strip()
        }
        trigger_metrics = {rule["metric_key"] for rule in ALERT_RULES}
        related_metrics = {
            metric_key
            for rule in ALERT_RULES
            for metric_key in rule.get("related_metric_keys", [])
        }
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        alert_check = {
            item["name"]: item
            for item in dashboard["checks"]
        }["alert_metric_catalog_complete"]
        details = alert_check["details"]

        self.assertEqual(documented_metrics, ALERT_FACT_METRICS)
        self.assertEqual(set(details["required_alert_metric_keys"]), ALERT_FACT_METRICS)
        self.assertEqual(set(details["covered_alert_metric_keys"]), ALERT_FACT_METRICS)
        self.assertEqual(details["missing_alert_metric_keys"], [])
        self.assertEqual(set(details["trigger_metric_keys"]), trigger_metrics)
        self.assertEqual(set(details["related_metric_keys"]), related_metrics)
        self.assertEqual(set(details["dynamic_metric_keys"]), DYNAMIC_ALERT_METRICS)
        self.assertEqual(
            ALERT_FACT_METRICS - (trigger_metrics | related_metrics | DYNAMIC_ALERT_METRICS),
            set(),
        )
        for metric_key in (
            "backend_effect_capability_receipt_first_total",
            "backend_effect_capability_legacy_no_receipt_total",
            "event_replay_stress_cursor_window_total",
            "event_replay_stress_max_window_events",
            "fault_injection_required_case_total",
            "fault_injection_registered_case_total",
            "fault_injection_missing_required_total",
            "fault_injection_coverage_ratio",
        ):
            self.assertIn(metric_key, related_metrics)
        self.assertEqual(DYNAMIC_ALERT_METRICS, {"release_gate_violation_count"})

        def parse_alert_runbook_contract(text: str) -> dict[str, object]:
            section = text[text.index("Required alert runbook binding contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, object] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if key == "dynamic_alert_runbooks":
                    parsed[key] = dict(item.split(":", 1) for item in value.split(","))
                else:
                    parsed[key] = value.split(",")
            return parsed

        contracts = [
            parse_alert_runbook_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required alert runbook binding contract:" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(len(contracts), 2)
        for contract in contracts:
            self.assertEqual(contract["runbook_required_severities"], list(ALERT_RUNBOOK_REQUIRED_SEVERITIES))
            self.assertEqual(contract["static_alert_rule_source"], ["ALERT_RULES"])
            self.assertEqual(contract["dynamic_alert_runbooks"], ALERT_DYNAMIC_RUNBOOKS)
            self.assertEqual(contract["dashboard_check"], ["alert_metric_catalog_complete"])
            for field in contract["dashboard_details"]:
                self.assertIn(field, details)

        runbook_ids = {item["runbook_id"] for item in AgentRunbookService(self.db).list_runbooks()}
        required_runbook_rules = [
            rule for rule in ALERT_RULES if rule["severity"] in ALERT_RUNBOOK_REQUIRED_SEVERITIES
        ]
        self.assertTrue(required_runbook_rules)
        self.assertEqual(details["runbook_required_severities"], list(ALERT_RUNBOOK_REQUIRED_SEVERITIES))
        self.assertEqual(details["dynamic_alert_runbooks"], ALERT_DYNAMIC_RUNBOOKS)
        self.assertEqual(details["missing_required_runbook_alert_ids"], [])
        self.assertEqual(details["missing_dynamic_runbook_alert_ids"], [])
        self.assertEqual(
            set(details["covered_required_runbook_alert_ids"]),
            {rule["alert_id"] for rule in required_runbook_rules},
        )
        self.assertEqual(
            set(details["covered_dynamic_runbook_alert_ids"]),
            set(ALERT_DYNAMIC_RUNBOOKS),
        )
        self.assertEqual(
            {rule["runbook_id"] for rule in required_runbook_rules}.union(ALERT_DYNAMIC_RUNBOOKS.values()),
            set(details["alert_runbook_ids"]),
        )
        self.assertTrue(set(details["alert_runbook_ids"]).issubset(runbook_ids))

    def test_harness_alert_snapshot_payload_contract_matches_service(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import get_agent_alerts

        def parse_alert_snapshot_contract(text: str) -> dict[str, str | list[str]]:
            section = text[text.index("Required alert snapshot payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, str | list[str]] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            parse_alert_snapshot_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required alert snapshot payload contract:" in path.read_text(encoding="utf-8")
        ]
        clean_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        clean_payload = AgentAlertSnapshotRead.model_validate(clean_snapshot).model_dump()

        self.assertEqual(len(documented_contracts), 2)
        for contract in documented_contracts:
            self.assertEqual(contract["fields"], list(ALERT_SNAPSHOT_FIELDS))
            self.assertEqual(contract["alert_fields"], list(ALERT_ITEM_FIELDS))
            self.assertEqual(contract["summary_fields"], list(ALERT_SUMMARY_FIELDS))
            self.assertEqual(contract["status_values"], list(ALERT_STATUS_VALUES))
            self.assertEqual(contract["source"], "AgentAlertService.snapshot")
        self.assertEqual(list(AgentAlertSnapshotRead.model_fields), list(ALERT_SNAPSHOT_FIELDS))
        self.assertEqual(list(AgentAlertRead.model_fields), list(ALERT_ITEM_FIELDS))
        self.assertEqual(list(clean_snapshot), list(ALERT_SNAPSHOT_FIELDS))
        self.assertEqual(list(clean_snapshot["summary"]), list(ALERT_SUMMARY_FIELDS))
        self.assertEqual(clean_snapshot["status"], "ok")
        self.assertEqual(clean_snapshot["alerts"], [])
        self.assertEqual(clean_payload["status"], "ok")

        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="alert snapshot contract"),
            current_user=self.owner,
        )
        AgentRuntimeService(self.db).append_event(
            run,
            "memory.bypassed_evidence_ref",
            {"error_code": "memory_bypassed_evidence_ref"},
        )

        firing_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        route_payload = get_agent_alerts(project_id=10, db=self.db, current_user=self.owner)["data"]
        firing_payload = AgentAlertSnapshotRead.model_validate(firing_snapshot).model_dump()
        alerts = {item["alert_id"]: item for item in firing_snapshot["alerts"]}
        route_alerts = {item["alert_id"]: item for item in route_payload["alerts"]}
        memory_alert = alerts["agent_memory_bypassed_evidence_ref"]
        route_memory_alert = route_alerts["agent_memory_bypassed_evidence_ref"]

        self.assertEqual(list(firing_snapshot), list(ALERT_SNAPSHOT_FIELDS))
        self.assertEqual(list(route_payload), list(ALERT_SNAPSHOT_FIELDS))
        self.assertEqual(list(firing_payload), list(ALERT_SNAPSHOT_FIELDS))
        self.assertTrue(all(list(item) == list(ALERT_ITEM_FIELDS) for item in firing_snapshot["alerts"]))
        self.assertTrue(all(list(item) == list(ALERT_ITEM_FIELDS) for item in route_payload["alerts"]))
        self.assertTrue(all(item["status"] == "firing" for item in firing_snapshot["alerts"]))
        self.assertIn(firing_snapshot["status"], ALERT_STATUS_VALUES)
        self.assertEqual(firing_snapshot["status"], "firing")
        self.assertEqual(list(firing_snapshot["summary"]), list(ALERT_SUMMARY_FIELDS))
        self.assertEqual(firing_snapshot["summary"]["highest_severity"], "P0")
        self.assertEqual(memory_alert["severity"], "P0")
        self.assertEqual(memory_alert["metric_key"], "memory_bypassed_evidence_ref_total")
        self.assertEqual(memory_alert["runbook_id"], "memory_evidence_ref_violation")
        self.assertTrue(memory_alert["action"])
        self.assertEqual(memory_alert["details"]["condition"], "memory_bypassed_evidence_ref_total > 0")
        self.assertEqual(route_memory_alert["severity"], memory_alert["severity"])
        self.assertEqual(route_memory_alert["runbook_id"], memory_alert["runbook_id"])
        self.assertEqual(route_memory_alert["details"]["condition"], memory_alert["details"]["condition"])
        self.assertEqual(
            {item["alert_id"] for item in firing_payload["alerts"]},
            set(alerts),
        )

    def test_harness_readiness_dashboard_payload_contract_matches_service(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import get_agent_readiness_dashboard

        def parse_dashboard_payload_contract(text: str) -> dict[str, str | list[str]]:
            section = text[text.index("Required readiness dashboard payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, str | list[str]] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            parse_dashboard_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required readiness dashboard payload contract:" in path.read_text(encoding="utf-8")
        ]
        AgentRuntimeService(self.db).ensure_backend_contracts()
        snapshot = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        route_payload = get_agent_readiness_dashboard(project_id=10, db=self.db, current_user=self.owner)["data"]
        schema_payload = AgentReadinessDashboardRead.model_validate(snapshot).model_dump()

        self.assertEqual(len(documented_contracts), 2)
        for contract in documented_contracts:
            self.assertEqual(contract["fields"], list(READINESS_DASHBOARD_FIELDS))
            self.assertEqual(contract["check_fields"], list(DASHBOARD_CHECK_FIELDS))
            self.assertEqual(contract["checks"], list(DASHBOARD_CHECK_NAMES))
            self.assertEqual(contract["readiness_values"], list(READINESS_STATUS_VALUES))
            self.assertEqual(contract["source"], "AgentReadinessDashboardService.snapshot")
        self.assertEqual(list(AgentReadinessDashboardRead.model_fields), list(READINESS_DASHBOARD_FIELDS))
        self.assertEqual(list(AgentDashboardCheckRead.model_fields), list(DASHBOARD_CHECK_FIELDS))
        self.assertEqual(list(snapshot), list(READINESS_DASHBOARD_FIELDS))
        self.assertEqual(list(route_payload), list(READINESS_DASHBOARD_FIELDS))
        self.assertEqual(list(schema_payload), list(READINESS_DASHBOARD_FIELDS))
        self.assertEqual([item["name"] for item in snapshot["checks"]], list(DASHBOARD_CHECK_NAMES))
        self.assertEqual([item["name"] for item in route_payload["checks"]], list(DASHBOARD_CHECK_NAMES))
        self.assertTrue(all(list(item) == list(DASHBOARD_CHECK_FIELDS) for item in snapshot["checks"]))
        self.assertTrue(all(list(item) == list(DASHBOARD_CHECK_FIELDS) for item in route_payload["checks"]))
        self.assertIn(snapshot["readiness"], READINESS_STATUS_VALUES)
        self.assertIn(route_payload["readiness"], READINESS_STATUS_VALUES)
        self.assertEqual(list(snapshot["alert_summary"]), list(ALERT_SUMMARY_FIELDS))
        self.assertEqual(list(route_payload["alert_summary"]), list(ALERT_SUMMARY_FIELDS))
        self.assertEqual(list(snapshot["promotion_assessment"]), list(PROMOTION_DASHBOARD_SUMMARY_FIELDS))
        self.assertEqual(list(route_payload["promotion_assessment"]), list(PROMOTION_DASHBOARD_SUMMARY_FIELDS))
        self.assertEqual(set(snapshot["derived_from"]), set(route_payload["derived_from"]))

    def test_readiness_dashboard_flags_root_cause_rule_governance_violations(self):
        RootCauseRuleEngine(self.db).ensure_default_rules()
        self.db.add(
            AgentRootCauseRule(
                rule_id="RC_DASHBOARD_BAD_BAND",
                reason_key="dashboard_bad_band",
                root_cause_primary="dashboard_bad_band",
                causal_chain_json=["dashboard_bad_band"],
                mitigation_action="fix_rule_priority",
                priority=88,
                priority_band="safety",
                match_expression_json={"any_reasons": ["dashboard_bad_band"]},
                status="active",
            )
        )
        self.db.commit()

        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["root_cause_rule_governance"]["status"], "attention")
        self.assertEqual(checks["root_cause_rule_governance"]["details"]["violation_count"], 1)
        self.assertEqual(
            checks["root_cause_rule_governance"]["details"]["violations"][0]["rule_id"],
            "RC_DASHBOARD_BAD_BAND",
        )
        self.assertFalse(dashboard["root_cause_governance"]["governance_pass"])

    def test_fault_injection_coverage_audit_tracks_all_required_cases(self):
        coverage = AgentFaultInjectionCoverageService(self.db).audit()
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertTrue(coverage["coverage_pass"])
        self.assertEqual(coverage["registered_case_count"], 26)
        self.assertEqual(coverage["required_case_count"], 26)
        self.assertEqual(coverage["missing_required_case_ids"], [])
        self.assertEqual(coverage["coverage_ratio"], 1.0)
        self.assertEqual(metrics["fault_injection_registered_case_total"], 26)
        self.assertEqual(metrics["fault_injection_required_case_total"], 26)
        self.assertEqual(metrics["fault_injection_missing_required_total"], 0)
        self.assertEqual(metrics["fault_injection_coverage_ratio"], 1.0)

    def test_harness_required_fault_injection_cases_match_docs_contract(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import (
            audit_agent_fault_injection_coverage,
            list_agent_fault_injection_cases,
            run_agent_fault_injections,
        )
        from app.schemas.agent import AgentFaultInjectionRequest
        from app.services.agent_observability_service import REQUIRED_FAULT_CASES

        def _extract_cases(text: str, marker: str) -> set[str]:
            section = text[text.index(marker):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            return {
                line.strip()
                for line in block.group(1).splitlines()
                if line.strip()
            }

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required fault injection payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        docs = {
            path.name: path.read_text(encoding="utf-8")
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
        }
        architecture_text = next(
            text for text in docs.values()
            if "Required fault injection cases:" in text
        )
        plan_text = next(
            text for text in docs.values()
            if "当前后端故障注入服务 `AgentFaultInjectionService` 已可枚举并执行以下 26 个生产硬化用例" in text
        )
        documented_architecture_cases = _extract_cases(architecture_text, "Required fault injection cases:")
        documented_plan_cases = _extract_cases(plan_text, "当前后端故障注入服务")
        documented_payload_contracts = [
            _parse_payload_contract(text)
            for text in docs.values()
            if "Required fault injection payload contract:" in text
        ]
        catalog = AgentFaultInjectionService(self.db).list_cases()
        registered_cases = {
            case["case_id"]
            for case in catalog
        }
        coverage = AgentFaultInjectionCoverageService(self.db).audit()
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        fault_check = {
            item["name"]: item
            for item in dashboard["checks"]
        }["fault_injection_catalog_complete"]
        catalog_route_payload = list_agent_fault_injection_cases(db=self.db, current_user=self.admin)["data"]
        coverage_route_payload = audit_agent_fault_injection_coverage(db=self.db, current_user=self.admin)["data"]
        run_route_payload = run_agent_fault_injections(
            payload=AgentFaultInjectionRequest(project_id=10, case_ids=["root_cause_rule_missing"]),
            db=self.db,
            current_user=self.admin,
        )["data"]

        self.assertEqual(documented_architecture_cases, REQUIRED_FAULT_CASES)
        self.assertEqual(documented_plan_cases, REQUIRED_FAULT_CASES)
        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["case_fields"], list(FAULT_INJECTION_CASE_FIELDS))
            self.assertEqual(contract["coverage_fields"], list(FAULT_INJECTION_COVERAGE_FIELDS))
            self.assertEqual(contract["run_fields"], list(FAULT_INJECTION_RUN_FIELDS))
            self.assertEqual(contract["result_fields"], list(FAULT_INJECTION_RESULT_FIELDS))
            self.assertEqual(contract["source"], "AgentFaultInjectionService_and_AgentFaultInjectionCoverageService")
        self.assertEqual(list(AgentFaultInjectionCaseRead.model_fields), list(FAULT_INJECTION_CASE_FIELDS))
        self.assertEqual(list(AgentFaultInjectionCoverageRead.model_fields), list(FAULT_INJECTION_COVERAGE_FIELDS))
        self.assertEqual(list(AgentFaultInjectionRunRead.model_fields), list(FAULT_INJECTION_RUN_FIELDS))
        self.assertEqual(list(AgentFaultInjectionResultRead.model_fields), list(FAULT_INJECTION_RESULT_FIELDS))
        self.assertTrue(all(list(item) == list(FAULT_INJECTION_CASE_FIELDS) for item in catalog))
        self.assertTrue(all(list(item) == list(FAULT_INJECTION_CASE_FIELDS) for item in catalog_route_payload))
        self.assertEqual(list(coverage), list(FAULT_INJECTION_COVERAGE_FIELDS))
        self.assertEqual(list(coverage_route_payload), list(FAULT_INJECTION_COVERAGE_FIELDS))
        self.assertEqual(list(run_route_payload), list(FAULT_INJECTION_RUN_FIELDS))
        self.assertTrue(all(list(item) == list(FAULT_INJECTION_RESULT_FIELDS) for item in run_route_payload["results"]))
        self.assertEqual(registered_cases, REQUIRED_FAULT_CASES)
        self.assertEqual(set(coverage["covered_required_case_ids"]), REQUIRED_FAULT_CASES)
        self.assertEqual(coverage["missing_required_case_ids"], [])
        self.assertEqual(set(dashboard["fault_injection"]["covered_required_case_ids"]), REQUIRED_FAULT_CASES)
        self.assertEqual(dashboard["fault_injection"]["missing_required_case_ids"], [])
        self.assertEqual(set(fault_check["details"]["covered_required_case_ids"]), REQUIRED_FAULT_CASES)
        self.assertEqual(fault_check["details"]["missing_required_case_ids"], [])

    def test_fault_injection_catalog_and_coverage_routes_require_admin(self):
        from app.api.v1.routers.agents import (
            audit_agent_fault_injection_coverage,
            list_agent_fault_injection_cases,
        )

        with self.assertRaises(HTTPException) as list_ctx:
            list_agent_fault_injection_cases(db=self.db, current_user=self.owner)
        with self.assertRaises(HTTPException) as coverage_ctx:
            audit_agent_fault_injection_coverage(db=self.db, current_user=self.owner)

        list_response = list_agent_fault_injection_cases(db=self.db, current_user=self.admin)
        coverage_response = audit_agent_fault_injection_coverage(db=self.db, current_user=self.admin)

        self.assertEqual(list_ctx.exception.status_code, 403)
        self.assertEqual(coverage_ctx.exception.status_code, 403)
        self.assertGreaterEqual(len(list_response["data"]), 26)
        self.assertTrue(coverage_response["data"]["coverage_pass"])

    def test_fault_injection_run_route_requires_admin(self):
        from app.api.v1.routers.agents import run_agent_fault_injections
        from app.schemas.agent import AgentFaultInjectionRequest

        payload = AgentFaultInjectionRequest(
            project_id=10,
            case_ids=["root_cause_rule_missing"],
        )

        with self.assertRaises(HTTPException) as owner_ctx:
            run_agent_fault_injections(payload=payload, db=self.db, current_user=self.owner)

        admin_response = run_agent_fault_injections(payload=payload, db=self.db, current_user=self.admin)

        self.assertEqual(owner_ctx.exception.status_code, 403)
        self.assertEqual(admin_response["data"]["project_id"], 10)
        self.assertEqual(admin_response["data"]["requested"], 1)
        self.assertEqual(admin_response["data"]["failed"], 0)
        self.assertEqual(admin_response["data"]["results"][0]["case_id"], "root_cause_rule_missing")
        self.assertTrue(admin_response["data"]["results"][0]["passed"])

    def test_background_processing_routes_require_admin(self):
        from app.api.v1.routers.agents import (
            process_agent_memory_feedback,
            publish_agent_outbox,
        )

        with self.assertRaises(HTTPException) as outbox_ctx:
            publish_agent_outbox(db=self.db, current_user=self.owner)
        with self.assertRaises(HTTPException) as feedback_ctx:
            process_agent_memory_feedback(db=self.db, current_user=self.owner)

        outbox_response = publish_agent_outbox(limit=100, db=self.db, current_user=self.admin)
        feedback_response = process_agent_memory_feedback(limit=100, db=self.db, current_user=self.admin)

        self.assertEqual(outbox_ctx.exception.status_code, 403)
        self.assertEqual(feedback_ctx.exception.status_code, 403)
        self.assertEqual(outbox_response["data"]["attempted"], 0)
        self.assertEqual(feedback_response["data"]["attempted"], 0)

    def test_memory_usage_events_global_route_requires_admin(self):
        from app.api.v1.routers.agents import list_agent_memory_usage_events

        run = self._create_run("memory usage event route permission")
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Usage event permission",
            content="Usage event queries must stay scoped.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        self.db.add(AgentMemoryUsageEvent(
            memory_id=memory.id,
            run_id=run.run_id,
            retrieval_profile="repair_v1",
            retrieval_score=1.0,
            usage_role="repair_hint",
            active_for_policy=False,
            caused_tool_input_change=False,
        ))
        self.db.commit()

        with self.assertRaises(HTTPException) as global_ctx:
            list_agent_memory_usage_events(db=self.db, current_user=self.owner)

        run_scoped_response = list_agent_memory_usage_events(
            run_id=run.run_id,
            db=self.db,
            current_user=self.owner,
        )
        admin_global_response = list_agent_memory_usage_events(db=self.db, current_user=self.admin)

        self.assertEqual(global_ctx.exception.status_code, 403)
        self.assertEqual(len(run_scoped_response["data"]), 1)
        self.assertEqual(run_scoped_response["data"][0]["run_id"], run.run_id)
        self.assertEqual(len(admin_global_response["data"]), 1)

    def test_harness_memory_usage_event_payload_contract_matches_route(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import list_agent_memory_usage_events

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Memory usage event payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        run = self._create_run("memory usage event payload contract")
        MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Usage event payload",
            content="Usage event payload should expose stable audit fields.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        MemoryManager(self.db).retrieve(
            project_id=10,
            query="Usage event payload",
            profile_name="normal_plan_v1",
            task_risk="normal",
            usage_role="policy_dependency",
            current_user=self.owner,
            run_id=run.run_id,
            step_index=2,
            limit=1,
        )
        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Memory usage event payload contract:" in path.read_text(encoding="utf-8")
        ]
        usage_event = self.db.scalar(select(AgentMemoryUsageEvent).where(AgentMemoryUsageEvent.run_id == run.run_id))
        run_scoped_payload = list_agent_memory_usage_events(
            run_id=run.run_id,
            db=self.db,
            current_user=self.owner,
        )["data"][0]
        admin_global_payload = list_agent_memory_usage_events(db=self.db, current_user=self.admin)["data"][0]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(MEMORY_USAGE_EVENT_FIELDS))
            self.assertEqual(contract["evidence_ref_fields"], list(MEMORY_USAGE_EVENT_EVIDENCE_REF_FIELDS))
            self.assertEqual(contract["source"], "GET /api/v1/agents/memory-usage-events")
        self.assertEqual(list(AgentMemoryUsageEventRead.model_fields), list(MEMORY_USAGE_EVENT_FIELDS))
        self.assertEqual(list(run_scoped_payload), list(MEMORY_USAGE_EVENT_FIELDS))
        self.assertEqual(list(admin_global_payload), list(MEMORY_USAGE_EVENT_FIELDS))
        self.assertEqual(list(run_scoped_payload["evidence_ref_json"]), list(MEMORY_USAGE_EVENT_EVIDENCE_REF_FIELDS))
        self.assertEqual(run_scoped_payload["id"], usage_event.id)
        self.assertEqual(run_scoped_payload["run_id"], run.run_id)
        self.assertEqual(run_scoped_payload["usage_role"], "policy_dependency")
        self.assertTrue(run_scoped_payload["active_for_policy"])
        self.assertEqual(run_scoped_payload["step_index"], 2)

    def test_memory_active_policy_metric_excludes_audit_only_usage(self):
        run = self._create_run("memory active policy metric boundary")
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Metric boundary memory",
            content="Only active policy usage should count in the active policy metric.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        self.db.add_all([
            AgentMemoryUsageEvent(
                memory_id=memory.id,
                run_id=run.run_id,
                retrieval_profile="normal_plan_v1",
                retrieval_score=0.96,
                usage_role="policy_dependency",
                active_for_policy=True,
                caused_tool_input_change=True,
            ),
            AgentMemoryUsageEvent(
                memory_id=memory.id,
                run_id=run.run_id,
                retrieval_profile="audit_trace_v1",
                retrieval_score=0.81,
                usage_role="audit_trace",
                active_for_policy=False,
                caused_tool_input_change=False,
            ),
        ])
        self.db.commit()

        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertEqual(metrics["memory_retrieved_total"], 2)
        self.assertEqual(metrics["memory_used_active_policy_total"], 1)

    def test_fault_injection_coverage_ratio_alerts_when_below_full(self):
        from app.services import agent_observability_service as observability

        missing_case_id = "temporarily_missing_required_case"
        observability.REQUIRED_FAULT_CASES.add(missing_case_id)
        try:
            coverage = AgentFaultInjectionCoverageService(self.db).audit()
            AgentOutboxPublisher(self.db, publisher=lambda event: None).publish_pending(limit=100)
            metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
            alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
            alerts = {
                item["alert_id"]: item
                for item in alert_snapshot["alerts"]
            }
            dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
            checks = {item["name"]: item for item in dashboard["checks"]}
        finally:
            observability.REQUIRED_FAULT_CASES.remove(missing_case_id)

        self.assertFalse(coverage["coverage_pass"])
        self.assertIn(missing_case_id, coverage["missing_required_case_ids"])
        self.assertEqual(metrics["fault_injection_missing_required_total"], 1)
        self.assertLess(metrics["fault_injection_coverage_ratio"], 1.0)
        self.assertIn("agent_fault_injection_coverage_incomplete", alerts)
        self.assertIn("agent_fault_injection_coverage_ratio_low", alerts)
        for alert_id in (
            "agent_fault_injection_coverage_incomplete",
            "agent_fault_injection_coverage_ratio_low",
        ):
            self.assertEqual(alerts[alert_id]["severity"], "P1")
            self.assertEqual(alerts[alert_id]["runbook_id"], "fault_injection_coverage")
            related_metrics = alerts[alert_id]["details"]["related_metrics"]
            for metric_key in (
                "fault_injection_required_case_total",
                "fault_injection_registered_case_total",
                "fault_injection_missing_required_total",
                "fault_injection_coverage_ratio",
            ):
                self.assertEqual(related_metrics[metric_key], metrics[metric_key])
        self.assertEqual(alerts["agent_fault_injection_coverage_ratio_low"]["threshold"], 1.0)
        self.assertEqual(
            alerts["agent_fault_injection_coverage_ratio_low"]["details"]["condition"],
            "fault_injection_coverage_ratio < 1.0",
        )
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P1")
        self.assertEqual(dashboard["readiness"], "blocked")
        self.assertEqual(checks["fault_injection_catalog_complete"]["status"], "blocked")
        self.assertEqual(
            checks["fault_injection_catalog_complete"]["details"]["missing_required_case_ids"],
            [missing_case_id],
        )
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "attention")

    def test_release_gate_violation_alert_includes_runbook(self):
        release_alerts = AgentAlertService._release_gate_alerts({
            "current_level": "L2",
            "violations": [
                {
                    "tool_name": "project.create_business_record",
                    "reason": "tool_side_effect_exceeds_current_rollout_level",
                }
            ],
        })

        self.assertEqual(len(release_alerts), 1)
        self.assertEqual(release_alerts[0]["runbook_id"], "release_gate_violation")
        self.assertEqual(release_alerts[0]["metric_key"], "release_gate_violation_count")

    def test_release_gate_violation_blocks_dashboard_and_promotion(self):
        from app.services.agent_tool_service import ToolRegistry, ToolSpec

        AgentRuntimeService(self.db).ensure_backend_contracts()
        base_specs = ToolRegistry().list_specs()
        blocked_spec = ToolSpec(
            name="project.create_business_record",
            version="v1",
            summary="business create should stay blocked at L2",
            side_effect_class="business_create",
            replay_policy="never_replay",
            required_permissions=("project:write",),
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            backend_contract=None,
        )

        with patch.object(ToolRegistry, "list_specs", return_value=[*base_specs, blocked_spec]):
            release_gate = AgentReleaseGateService(self.db).snapshot()
            metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
            alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
            alerts = {item["alert_id"]: item for item in alert_snapshot["alerts"]}
            dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
            checks = {item["name"]: item for item in dashboard["checks"]}
            assessment = AgentReleaseGateService(self.db).promotion_assessment(target_level="L3", project_id=10)
            blockers = {item["source"] for item in assessment["blockers"]}
            assessment_checks = {item["name"]: item for item in assessment["checks"]}

        self.assertEqual(len(release_gate["violations"]), 1)
        self.assertEqual(release_gate["violations"][0]["tool_name"], "project.create_business_record")
        self.assertEqual(release_gate["violations"][0]["side_effect_class"], "business_create")
        self.assertEqual(metrics["release_gate_violation_count"], 1)
        self.assertIn("agent_release_gate_violation", alerts)
        self.assertEqual(alerts["agent_release_gate_violation"]["severity"], "P0")
        self.assertEqual(alerts["agent_release_gate_violation"]["metric_key"], "release_gate_violation_count")
        self.assertEqual(alerts["agent_release_gate_violation"]["runbook_id"], "release_gate_violation")
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P0")
        self.assertEqual(dashboard["readiness"], "blocked")
        self.assertEqual(checks["release_gate_current_level_clean"]["status"], "blocked")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "blocked")
        self.assertFalse(assessment["can_promote"])
        self.assertEqual(assessment["decision"], "blocked")
        self.assertIn("tool_matrix", blockers)
        self.assertIn("readiness_dashboard", blockers)
        self.assertIn("monitoring_alerts", blockers)
        self.assertEqual(assessment_checks["current_tool_matrix_clean"]["status"], "blocked")
        self.assertEqual(assessment_checks["readiness_dashboard_pass"]["status"], "blocked")
        self.assertEqual(assessment_checks["monitoring_alerts_clear"]["status"], "blocked")

    def test_monitoring_alerts_fire_and_affect_dashboard_readiness(self):
        AgentRuntimeService(self.db).ensure_backend_contracts()
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="alert p0"),
            current_user=self.owner,
        )
        AgentRuntimeService(self.db).append_event(
            run,
            "memory.bypassed_evidence_ref",
            {"error_code": "memory_bypassed_evidence_ref"},
        )

        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        alert_ids = {item["alert_id"] for item in alert_snapshot["alerts"]}
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertEqual(alert_snapshot["status"], "firing")
        self.assertIn("agent_memory_bypassed_evidence_ref", alert_ids)
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P0")
        self.assertEqual(dashboard["readiness"], "blocked")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "blocked")

    def test_harness_monitoring_alerts_clear_contract_matches_dashboard(self):
        from pathlib import Path
        import re

        def parse_contract(text: str) -> dict[str, object]:
            section = text[text.index("Required monitoring alerts clear contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, object] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if key == "status_rules":
                    parsed[key] = dict(item.split(":", 1) for item in value.split(","))
                else:
                    parsed[key] = value.split(",")
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        contracts = [
            parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required monitoring alerts clear contract:" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(len(contracts), 2)
        for contract in contracts:
            self.assertEqual(contract["dashboard_check"], ["monitoring_alerts_clear"])
            self.assertEqual(contract["blocking_severities"], list(MONITORING_ALERT_BLOCKING_SEVERITIES))
            self.assertEqual(contract["status_rules"], {"P0": "blocked", "P1": "attention", "none": "pass"})
            self.assertEqual(contract["detail_fields"], list(MONITORING_ALERTS_CLEAR_DETAIL_FIELDS))

        clean_dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        clean_check = {item["name"]: item for item in clean_dashboard["checks"]}["monitoring_alerts_clear"]
        self.assertEqual(clean_check["status"], "pass")
        self.assertEqual(set(clean_check["details"]), set(MONITORING_ALERTS_CLEAR_DETAIL_FIELDS))
        self.assertEqual(clean_check["details"]["blocking_severities"], list(MONITORING_ALERT_BLOCKING_SEVERITIES))
        self.assertEqual(clean_check["details"]["blocking_alert_count"], 0)
        self.assertEqual(clean_check["details"]["blocking_alert_ids"], [])
        self.assertEqual(clean_check["details"]["blocking_runbook_ids"], [])

        p1_run = self._create_run("monitoring alerts clear p1")
        p1_call = self._create_uncertain_call(p1_run.run_id, step_index=0)
        p1_call.backend_effect_capability = "legacy_reconcile_only"
        self.db.commit()
        p1_dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        p1_check = {item["name"]: item for item in p1_dashboard["checks"]}["monitoring_alerts_clear"]
        self.assertEqual(p1_check["status"], "attention")
        self.assertIn("agent_backend_capability_degraded", p1_check["details"]["blocking_alert_ids"])
        self.assertIn("agent_backend_capability_degraded", p1_check["details"]["p1_alert_ids"])
        self.assertEqual(p1_check["details"]["p0_alert_ids"], [])
        self.assertIn("backend_capability_degraded", p1_check["details"]["blocking_runbook_ids"])

        p0_run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="monitoring alerts clear p0"),
            current_user=self.owner,
        )
        AgentRuntimeService(self.db).append_event(
            p0_run,
            "memory.bypassed_evidence_ref",
            {"error_code": "memory_bypassed_evidence_ref"},
        )
        p0_dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        p0_check = {item["name"]: item for item in p0_dashboard["checks"]}["monitoring_alerts_clear"]
        self.assertEqual(p0_check["status"], "blocked")
        self.assertIn("agent_memory_bypassed_evidence_ref", p0_check["details"]["blocking_alert_ids"])
        self.assertIn("agent_memory_bypassed_evidence_ref", p0_check["details"]["p0_alert_ids"])
        self.assertIn("memory_evidence_ref_violation", p0_check["details"]["blocking_runbook_ids"])

    def test_backend_capability_degraded_alert_affects_dashboard_readiness(self):
        run = self._create_run("backend capability degraded")
        call = self._create_uncertain_call(run.run_id, step_index=0)
        call.backend_effect_capability = "legacy_reconcile_only"
        legacy_call = self._create_uncertain_call(run.run_id, step_index=1)
        legacy_call.status = "planned"
        legacy_call.effect_submission_state = "unknown"
        legacy_call.backend_effect_capability = "legacy_no_receipt"
        receipt_call = self._create_uncertain_call(run.run_id, step_index=2)
        receipt_call.status = "planned"
        receipt_call.effect_submission_state = "unknown"
        receipt_call.backend_effect_capability = "receipt_first"
        self.db.commit()

        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        alerts = {item["alert_id"]: item for item in alert_snapshot["alerts"]}
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertEqual(metrics["backend_capability_degraded_total"], 2)
        self.assertEqual(metrics["backend_effect_capability_receipt_first_total"], 1)
        self.assertEqual(metrics["backend_effect_capability_legacy_no_receipt_total"], 1)
        self.assertIn("agent_backend_capability_degraded", alerts)
        self.assertEqual(alerts["agent_backend_capability_degraded"]["runbook_id"], "backend_capability_degraded")
        related_metrics = alerts["agent_backend_capability_degraded"]["details"]["related_metrics"]
        for metric_key in (
            "backend_effect_capability_receipt_first_total",
            "backend_effect_capability_legacy_no_receipt_total",
        ):
            self.assertEqual(related_metrics[metric_key], metrics[metric_key])
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P1")
        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "attention")

    def test_context_decision_build_missing_metric_alerts_and_affects_dashboard(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="missing decision context"),
            current_user=self.owner,
        )
        self.db.add(
            AgentLoopObservation(
                observation_id="agent-obs-missing-context",
                run_id=run.run_id,
                iteration=1,
                step_index=0,
                decision_context_build_id="agent-context-missing",
                decision_context_degradation_level="none",
                iteration_context_degradation_max="none",
                required_evidence_complete_for_decision=True,
                omitted_required_evidence_refs_json=[],
                next_action="stop",
                next_action_is_high_risk=False,
                stop_action_reason="same_failure_no_progress",
                stop_reasons_all_json=["same_failure_no_progress"],
                root_cause_primary="same_failure_no_progress",
                root_cause_rule_id="RC_NO_PROGRESS_PURE",
                causal_chain_json=["repair_attempt", "same_failure"],
                mitigation_action="stop_or_escalate_repair_strategy",
                observation_json={"source": "test_missing_context_build"},
            )
        )
        self.db.commit()

        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        alert_ids = {item["alert_id"] for item in alert_snapshot["alerts"]}
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertEqual(metrics["context_decision_build_missing_total"], 1)
        self.assertIn("agent_context_decision_build_missing", alert_ids)
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P1")
        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "attention")

    def test_memory_needs_revalidation_alert_affects_dashboard_readiness(self):
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Needs revalidation",
            content="Memory must be refreshed before reuse.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        memory.status = "needs_revalidation"
        memory.stale_score = 0.85
        self.db.commit()

        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        alerts = {item["alert_id"]: item for item in alert_snapshot["alerts"]}
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertEqual(metrics["memory_needs_revalidation_total"], 1)
        self.assertIn("agent_memory_needs_revalidation", alerts)
        self.assertEqual(alerts["agent_memory_needs_revalidation"]["severity"], "P1")
        self.assertEqual(alerts["agent_memory_needs_revalidation"]["runbook_id"], "checkpoint_stale")
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P1")
        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "attention")

    def test_root_cause_metrics_track_context_degraded_and_unknown(self):
        run = self._create_run("root cause metrics")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=128,
                evidence_refs=self._large_evidence_refs(count=10),
                required_evidence_ref_ids=["evidence-9"],
            ),
            current_user=self.owner,
        )
        LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="execute_tool",
                next_action_is_high_risk=True,
                reasons=["same_failure_no_progress"],
            ),
            current_user=self.owner,
        )
        self.db.add(
            AgentLoopObservation(
                observation_id="agent-obs-unknown-root-cause",
                run_id=run.run_id,
                iteration=2,
                step_index=0,
                decision_context_build_id=build.context_build_id,
                decision_context_degradation_level="none",
                iteration_context_degradation_max="none",
                required_evidence_complete_for_decision=True,
                omitted_required_evidence_refs_json=[],
                next_action="stop",
                next_action_is_high_risk=False,
                stop_action_reason="unknown",
                stop_reasons_all_json=["unknown"],
                root_cause_primary="unknown",
                root_cause_rule_id="RC_UNKNOWN",
                causal_chain_json=["unknown"],
                mitigation_action="manual_diagnosis",
                observation_json={"source": "test_unknown_root_cause"},
            )
        )
        self.db.commit()

        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertEqual(metrics["loop_root_cause_context_degraded_total"], 1)
        self.assertEqual(metrics["loop_root_cause_unknown_total"], 1)

    def test_root_cause_metrics_track_runtime_repair_and_limit_reasons(self):
        run = self._create_run("runtime repair root cause metrics")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": "evidence-runtime-repair",
                        "ref_type": "execution_record",
                        "ref_id": "execution-runtime-repair-1",
                        "mutability_class": "immutable",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
                required_evidence_ref_ids=["evidence-runtime-repair"],
            ),
            current_user=self.owner,
        )

        for reason in [
            "tool_prerequisite_missing",
            "tool_request_format_invalid",
            "required_tool_followup_missing",
            "max_iterations",
        ]:
            LoopController(self.db).record_observation(
                run_id=run.run_id,
                payload=AgentLoopObservationCreateRequest(
                    decision_context_build_id=build.context_build_id,
                    next_action="repair" if reason != "max_iterations" else "stop",
                    next_action_is_high_risk=False,
                    reasons=[reason],
                    observation={"source": "runtime_repair_metric_test", "reason": reason},
                ),
                current_user=self.owner,
            )

        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks = {item["name"]: item for item in dashboard["checks"]}
        required_metrics = set(checks["metrics_catalog_complete"]["details"]["required_metric_keys"])

        expected_metrics = {
            "tool_prerequisite_missing_total": 1,
            "tool_request_format_invalid_total": 1,
            "required_tool_followup_missing_total": 1,
            "max_iterations_total": 1,
        }
        for metric_key, expected_count in expected_metrics.items():
            self.assertEqual(metrics[metric_key], expected_count)
            self.assertIn(metric_key, required_metrics)

    def test_invalid_repair_scope_metric_counts_loop_reasons(self):
        run = self._create_run("invalid repair scope metric")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=512,
                evidence_refs=[],
            ),
            current_user=self.owner,
        )
        self.db.add(
            AgentLoopObservation(
                observation_id="agent-obs-invalid-repair-scope",
                run_id=run.run_id,
                iteration=1,
                step_index=0,
                decision_context_build_id=build.context_build_id,
                decision_context_degradation_level="none",
                iteration_context_degradation_max="none",
                required_evidence_complete_for_decision=True,
                omitted_required_evidence_refs_json=[],
                next_action="stop",
                next_action_is_high_risk=False,
                stop_action_reason="invalid_repair_scope",
                stop_reasons_all_json=["invalid_repair_scope", "policy_loop"],
                root_cause_primary="invalid_repair_scope",
                root_cause_rule_id="RC_INVALID_REPAIR_SCOPE",
                causal_chain_json=["patch_touched_immutable_paths", "invalid_repair_scope"],
                mitigation_action="rollback_patch_or_human_review",
                observation_json={"patch_touched_immutable_paths": True},
            )
        )
        self.db.commit()

        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertEqual(metrics["invalid_repair_scope_total"], 1)

    def test_fault_injection_service_runs_p0_recovery_cases(self):
        summary = AgentFaultInjectionService(self.db).run_cases(
            project_id=10,
            case_ids=None,
            current_user=self.owner,
        )
        by_case = {item["case_id"]: item for item in summary["results"]}

        self.assertEqual(summary["requested"], 26)
        self.assertEqual(summary["failed"], 0)
        self.assertTrue(all(item["passed"] for item in summary["results"]))
        self.assertEqual(by_case["send_intent_not_found"]["observed"]["tool_status"], "failed_retryable")
        self.assertEqual(by_case["transport_sent_not_found"]["observed"]["recovery_decision"], "reconcile_backoff")
        self.assertEqual(
            by_case["transport_sent_not_found"]["evidence"]["backend_effect_capability"],
            "idempotency_index_only",
        )
        self.assertEqual(
            by_case["transport_sent_not_found"]["evidence"]["effect_submission_state"],
            "transport_sent_observed",
        )
        self.assertIsNone(by_case["transport_sent_not_found"]["evidence"]["downstream_acceptance_id"])
        self.assertEqual(by_case["backend_accepted_not_found"]["observed"]["tool_status"], "manual_intervention")
        self.assertEqual(
            by_case["backend_accepted_not_found"]["observed"]["recovery_decision"],
            "backend_accepted_not_found_incident",
        )
        self.assertEqual(by_case["effect_committed_reconcile_reuse"]["observed"]["tool_status"], "succeeded")
        self.assertEqual(
            by_case["tool_succeeded_eventstore_write_failed"]["observed"]["tool_status"],
            "uncertain",
        )
        self.assertEqual(
            by_case["tool_succeeded_eventstore_write_failed"]["observed"]["recovery_decision"],
            "reconcile_required_after_eventstore_failure",
        )
        self.assertGreaterEqual(by_case["outbox_publish_failure"]["observed"]["outbox_dead_letter"], 1)
        self.assertEqual(by_case["reconcile_conflict"]["observed"]["recovery_decision"], "idempotency_conflict")
        self.assertEqual(by_case["unsupported_schema_version"]["observed"]["run_status"], "migration_blocked")
        self.assertEqual(
            by_case["migration_block_resolve_checkpoint_continue"]["observed"]["run_status"],
            "running",
        )
        self.assertEqual(
            by_case["migration_block_resolve_checkpoint_continue"]["observed"]["freshness_action"],
            "continue_from_checkpoint",
        )
        self.assertEqual(
            by_case["migration_block_resolve_checkpoint_continue"]["observed"]["blocked_tool_status"],
            "reconciling",
        )
        self.assertEqual(
            by_case["migration_block_resolve_checkpoint_continue"]["observed"]["completed_tool_status"],
            "succeeded",
        )
        self.assertEqual(by_case["legacy_no_receipt_high_risk"]["observed"]["tool_status"], "manual_intervention")
        self.assertEqual(by_case["approval_epoch_conflict"]["evidence"]["error_code"], "approval_epoch_conflict")
        self.assertEqual(
            by_case["approval_supersede_replacement_atomic"]["observed"]["old_approval_status"],
            "superseded",
        )
        self.assertEqual(
            by_case["approval_supersede_replacement_atomic"]["observed"]["stale_approve_error"],
            "approval_stale_or_superseded",
        )
        self.assertEqual(by_case["approval_expired_before_approve"]["evidence"]["approval_status"], "expired")
        self.assertEqual(by_case["checkpoint_stale"]["observed"]["freshness_result"], "too_old")
        self.assertFalse(by_case["context_heavy_evidence_incomplete"]["observed"]["required_evidence_complete"])
        self.assertTrue(
            by_case["loop_observation_decision_context_binding"]["observed"]["bound_to_latest_decision_build"]
        )
        self.assertNotEqual(
            by_case["loop_observation_decision_context_binding"]["observed"]["plan_context_build_id"],
            by_case["loop_observation_decision_context_binding"]["observed"]["observation_context_build_id"],
        )
        self.assertEqual(
            by_case["loop_observation_decision_context_binding"]["observed"]["root_cause_rule_id"],
            "RC_CONTEXT_OMITTED_HIGH_RISK",
        )
        self.assertEqual(
            by_case["evidence_historical_volatile_excluded"]["observed"]["recovery_decision"],
            None,
        )
        self.assertEqual(
            by_case["evidence_historical_volatile_excluded"]["evidence"]["policy_reason"]["historical_volatile_excluded_count"],
            1,
        )
        self.assertTrue(
            by_case["evidence_mixed_volatile_frozen_requires_revalidation"]["evidence"]["policy_reason"]["mixed_volatile_frozen"]
        )
        self.assertEqual(by_case["memory_contradiction"]["observed"]["memory_status"], "needs_revalidation")
        self.assertEqual(by_case["memory_stale_evidence_watch"]["observed"]["memory_status"], "needs_revalidation")
        self.assertEqual(
            by_case["memory_bypassed_evidence_ref"]["observed"]["error_code"],
            "memory_bypassed_evidence_ref",
        )
        self.assertEqual(by_case["duplicate_idempotency_key"]["evidence"]["duplicate_event_count"], 1)
        self.assertEqual(
            by_case["permission_revoked_before_execution"]["observed"]["error_code"],
            "permission_revoked_before_execution",
        )
        self.assertEqual(
            by_case["worker_queue_reconcile_required"]["observed"]["blocked_statuses"],
            ["uncertain", "reconciling"],
        )
        self.assertEqual(
            by_case["worker_queue_reconcile_required"]["observed"]["queue_statuses"],
            ["failed", "failed"],
        )
        self.assertEqual(
            by_case["worker_queue_reconcile_required"]["observed"]["error_code"],
            "tool_call_uncertain_reconcile_required",
        )
        self.assertEqual(
            {
                item["tool_error_code"]
                for item in by_case["worker_queue_reconcile_required"]["evidence"]["blocked_tool_calls"]
            },
            {"tool_call_uncertain_reconcile_required"},
        )
        self.assertEqual(by_case["root_cause_rule_missing"]["observed"]["root_cause_rule_id"], "RC_RULE_MISSING")
        self.assertEqual(
            by_case["high_risk_memory_only_blocked"]["observed"]["error_code"],
            "high_risk_action_cannot_depend_only_on_memory",
        )
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        self.assertEqual(metrics["memory_high_risk_blocked_total"], 1)
        self.assertEqual(metrics["memory_bypassed_evidence_ref_total"], 1)
        self.assertEqual(metrics["permission_revoked_before_execution_total"], 1)
        self.assertGreaterEqual(metrics["evidence_volatile_requires_revalidation_total"], 1)
        self.assertGreaterEqual(metrics["evidence_historical_volatile_excluded_total"], 1)
        self.assertGreaterEqual(metrics["evidence_mixed_volatile_frozen_total"], 1)

    def test_worker_claim_and_orphan_recovery(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="读取项目上下文"),
            current_user=self.owner,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=self.owner,
        )

        queue_service = AgentWorkerQueueService(self.db)
        item = queue_service.claim_next(worker_id="worker-1", lease_seconds=1)
        self.assertIsNotNone(item)
        self.assertEqual(item.tool_call_id, call.tool_call_id)
        self.assertEqual(item.status, "leased")

        item.lease_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        self.db.commit()
        self.assertEqual(queue_service.recover_orphans(), 1)
        recovered = self.db.scalar(select(AgentWorkerQueue).where(AgentWorkerQueue.queue_id == item.queue_id))
        self.assertEqual(recovered.status, "queued")

    def test_harness_worker_queue_audit_payload_contract_matches_service(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import audit_agent_worker_queue

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required WorkerQueue audit payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required WorkerQueue audit payload contract:" in path.read_text(encoding="utf-8")
        ]
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="queue contract"),
            current_user=self.owner,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
                idempotency_key="worker-queue-contract",
            ),
            current_user=self.owner,
        )
        current = datetime.now(UTC).replace(tzinfo=None)
        queue_item = self.db.scalar(select(AgentWorkerQueue).where(AgentWorkerQueue.tool_call_id == call.tool_call_id))
        queue_item.status = "leased"
        queue_item.lease_owner = "worker-a"
        queue_item.lease_expires_at = current - timedelta(seconds=1)
        self.db.add(
            AgentWorkerQueue(
                queue_id="agent-queue-contract-duplicate",
                run_id=run.run_id,
                tool_call_id=call.tool_call_id,
                status="queued",
                priority=100,
                available_at=current,
                created_at=current,
                lease_owner="worker-b",
            )
        )
        self.db.commit()

        audit = AgentWorkerQueueAuditService(self.db).audit(project_id=10)
        route_payload = audit_agent_worker_queue(project_id=10, db=self.db, current_user=self.owner)["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(WORKER_QUEUE_AUDIT_FIELDS))
            self.assertEqual(contract["expired_lease_fields"], list(WORKER_QUEUE_EXPIRED_LEASE_FIELDS))
            self.assertEqual(contract["duplicate_active_fields"], list(WORKER_QUEUE_DUPLICATE_ACTIVE_FIELDS))
            self.assertEqual(contract["derived_from_fields"], list(WORKER_QUEUE_DERIVED_FROM_FIELDS))
            self.assertEqual(contract["source"], "AgentWorkerQueueAuditService.audit")
        self.assertEqual(list(AgentWorkerQueueAuditRead.model_fields), list(WORKER_QUEUE_AUDIT_FIELDS))
        self.assertEqual(list(audit), list(WORKER_QUEUE_AUDIT_FIELDS))
        self.assertEqual(list(route_payload), list(WORKER_QUEUE_AUDIT_FIELDS))
        self.assertEqual(list(audit["expired_leases"][0]), list(WORKER_QUEUE_EXPIRED_LEASE_FIELDS))
        self.assertEqual(list(route_payload["expired_leases"][0]), list(WORKER_QUEUE_EXPIRED_LEASE_FIELDS))
        self.assertEqual(list(audit["duplicate_active_leases"][0]), list(WORKER_QUEUE_DUPLICATE_ACTIVE_FIELDS))
        self.assertEqual(list(route_payload["duplicate_active_leases"][0]), list(WORKER_QUEUE_DUPLICATE_ACTIVE_FIELDS))
        self.assertEqual(list(audit["derived_from"]), list(WORKER_QUEUE_DERIVED_FROM_FIELDS))
        self.assertEqual(list(route_payload["derived_from"]), list(WORKER_QUEUE_DERIVED_FROM_FIELDS))

    def test_worker_queue_audit_reports_stable_queue(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="queue stable"),
            current_user=self.owner,
        )
        ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=self.owner,
        )

        audit = AgentWorkerQueueAuditService(self.db).audit(project_id=10)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertTrue(audit["lease_scan_stable"])
        self.assertEqual(audit["status_counts"]["queued"], 1)
        self.assertEqual(audit["expired_lease_count"], 0)
        self.assertEqual(audit["duplicate_active_lease_count"], 0)
        self.assertEqual(metrics["worker_queue_expired_lease_total"], 0)
        self.assertEqual(metrics["worker_queue_duplicate_active_lease_total"], 0)
        self.assertIn("worker_queue_oldest_queued_age_ms", metrics)

    def test_worker_queue_audit_detects_expired_lease_and_alert(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="queue expired lease"),
            current_user=self.owner,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=self.owner,
        )
        queue_item = self.db.scalar(select(AgentWorkerQueue).where(AgentWorkerQueue.tool_call_id == call.tool_call_id))
        queue_item.status = "leased"
        queue_item.lease_owner = "worker-old"
        queue_item.lease_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        self.db.commit()

        audit = AgentWorkerQueueAuditService(self.db).audit(project_id=10)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        alerts = {item["alert_id"]: item for item in alert_snapshot["alerts"]}
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertFalse(audit["lease_scan_stable"])
        self.assertEqual(audit["expired_lease_count"], 1)
        self.assertEqual(audit["expired_leases"][0]["tool_call_id"], call.tool_call_id)
        self.assertEqual(metrics["worker_queue_expired_lease_total"], 1)
        self.assertIn("agent_worker_queue_expired_lease", alerts)
        self.assertEqual(alerts["agent_worker_queue_expired_lease"]["severity"], "P1")
        self.assertEqual(alerts["agent_worker_queue_expired_lease"]["runbook_id"], "worker_queue_recovery")
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P1")
        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "attention")

    def test_worker_queue_audit_detects_duplicate_active_lease_and_alert(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="queue duplicate active lease"),
            current_user=self.owner,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=self.owner,
        )
        current = datetime.now(UTC).replace(tzinfo=None)
        queue_item = self.db.scalar(select(AgentWorkerQueue).where(AgentWorkerQueue.tool_call_id == call.tool_call_id))
        queue_item.status = "leased"
        queue_item.lease_owner = "worker-a"
        queue_item.lease_expires_at = current + timedelta(seconds=60)
        self.db.add(
            AgentWorkerQueue(
                queue_id="agent-queue-duplicate-active",
                run_id=run.run_id,
                tool_call_id=call.tool_call_id,
                status="leased",
                priority=100,
                available_at=current,
                lease_owner="worker-b",
                lease_expires_at=current + timedelta(seconds=60),
            )
        )
        self.db.commit()

        audit = AgentWorkerQueueAuditService(self.db).audit(project_id=10)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        alerts = {item["alert_id"]: item for item in alert_snapshot["alerts"]}
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertFalse(audit["lease_scan_stable"])
        self.assertEqual(audit["duplicate_active_lease_count"], 1)
        self.assertEqual(audit["duplicate_active_leases"][0]["tool_call_id"], call.tool_call_id)
        self.assertEqual(metrics["worker_queue_duplicate_active_lease_total"], 1)
        self.assertIn("agent_worker_queue_duplicate_active_lease", alerts)
        self.assertEqual(alerts["agent_worker_queue_duplicate_active_lease"]["severity"], "P0")
        self.assertEqual(alerts["agent_worker_queue_duplicate_active_lease"]["runbook_id"], "worker_queue_recovery")
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P0")
        self.assertEqual(dashboard["readiness"], "blocked")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "blocked")

    def test_executor_blocks_when_execute_time_permission_is_revoked(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="读取报告"),
            current_user=self.member,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="report.read_summary",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=self.member,
        )

        result = ToolExecutor(self.db).execute_next(worker_id="worker-1")

        self.assertEqual(result.tool_call_id, call.tool_call_id)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "permission_revoked_before_execution")

    def test_executor_blocks_high_risk_tool_when_backend_capability_is_missing(self):
        from app.core.sensitive_data import request_fingerprint

        run = self._create_run("missing backend capability")
        refs = [
            {
                "evidence_ref_id": "execution-record-capability",
                "ref_type": "execution_record",
                "ref_id": "execution-capability",
                "mutability_class": "immutable",
                "dependency_role": "decision_dependency",
                "active_for_policy": True,
                "authority": "system_record",
                "content_hash": "hash-execution-capability",
            }
        ]
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=refs,
                required_evidence_ref_ids=["execution-record-capability"],
            ),
            current_user=self.owner,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
                decision_context_build_id=build.context_build_id,
                evidence_refs=refs,
            ),
            current_user=self.owner,
        )
        call.resolved_side_effect_class = "business_create"
        call.backend_effect_capability = None
        self.db.commit()

        result = ToolExecutor(self.db, backend_factory=lambda db: RaisingBackend()).execute_next(worker_id="worker-capability")
        queue_item = self.db.scalar(select(AgentWorkerQueue).where(AgentWorkerQueue.tool_call_id == call.tool_call_id))
        events = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )

        self.assertEqual(result.tool_call_id, call.tool_call_id)
        self.assertEqual(result.status, "manual_intervention")
        self.assertEqual(result.error_code, "backend_capability_too_weak")
        self.assertEqual(queue_item.status, "failed")
        self.assertEqual(queue_item.last_error_code, "backend_capability_too_weak")
        self.assertEqual(events[-1].event_type, "tool.failed")
        self.assertEqual(events[-1].payload_json["error_code"], "backend_capability_too_weak")
        execution_context = result.policy_reason_json["execution_context"]
        expected_context = {
            "execution_context_version_hash": "agent-tool-execution-v1",
            "tool_call_id": call.tool_call_id,
            "run_id": run.run_id,
            "runtime_snapshot_id": call.runtime_snapshot_id,
            "tool_name": "project.read_context",
            "tool_version": "1.0.0",
            "worker_id": "worker-capability",
            "tool_status": "manual_intervention",
            "execution_phase": "blocked",
            "effect_submission_state": "none",
            "effect_boundary_crossed": False,
            "backend_name": "project-service",
            "backend_operation": "read_context",
            "backend_contract_version": "v1",
            "backend_request_schema_hash": call.backend_request_schema_hash,
            "backend_output_schema_hash": call.backend_output_schema_hash,
            "reconcile_contract_version": call.reconcile_contract_version,
            "result_adapter_version": call.result_adapter_version,
            "backend_effect_capability": None,
            "resolved_side_effect_class": "business_create",
            "resolved_replay_policy": call.resolved_replay_policy,
            "approval_required": False,
            "approval_state": "not_required",
            "approval_lineage_id": None,
            "approval_epoch": 0,
            "approved_approval_id": None,
            "approved_by": None,
            "input_hash": call.input_hash,
            "output_hash": None,
            "recovery_decision": "backend_capability_required_before_execution",
            "error_code": "backend_capability_too_weak",
            "error_message_hash": None,
        }
        self.assertEqual(
            {key: execution_context[key] for key in expected_context},
            expected_context,
        )
        self.assertEqual(
            execution_context["execution_context_hash"],
            request_fingerprint(expected_context),
        )
        self.assertNotIn("input_json_redacted", execution_context)
        self.assertNotIn("output_json_redacted", execution_context)
        self.assertNotIn("evidence_refs_json", execution_context)

    def test_executor_runs_read_only_tool_and_writes_completion_events(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="读取项目上下文"),
            current_user=self.owner,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=self.owner,
        )

        result = ToolExecutor(self.db).execute_next(worker_id="worker-1")
        events = [item.event_type for item in self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all()]

        self.assertEqual(result.tool_call_id, call.tool_call_id)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.effect_submission_state, "effect_committed")
        self.assertIn("tool.completed", events)

    def test_executor_records_execution_context_envelope_after_approved_tool(self):
        from app.core.sensitive_data import request_fingerprint

        run, call, approval = self._create_pending_approval()
        call.resolved_side_effect_class = "read_only"
        self.db.commit()
        ApprovalService(self.db).approve(
            tool_call_id=call.tool_call_id,
            payload=self._approval_decision(approval, reason="approved for execution context"),
            current_user=self.owner,
        )

        result = ToolExecutor(self.db).execute_next(worker_id="worker-execution-context")
        execution_context = result.policy_reason_json["execution_context"]
        expected_context = {
            "execution_context_version_hash": "agent-tool-execution-v1",
            "tool_call_id": call.tool_call_id,
            "run_id": run.run_id,
            "runtime_snapshot_id": call.runtime_snapshot_id,
            "tool_name": "project.read_context",
            "tool_version": "1.0.0",
            "worker_id": "worker-execution-context",
            "tool_status": "succeeded",
            "execution_phase": "completed",
            "effect_submission_state": "effect_committed",
            "effect_boundary_crossed": False,
            "backend_name": "project-service",
            "backend_operation": "read_context",
            "backend_contract_version": "v1",
            "backend_request_schema_hash": call.backend_request_schema_hash,
            "backend_output_schema_hash": call.backend_output_schema_hash,
            "reconcile_contract_version": call.reconcile_contract_version,
            "result_adapter_version": call.result_adapter_version,
            "backend_effect_capability": "idempotency_index_only",
            "resolved_side_effect_class": "read_only",
            "resolved_replay_policy": call.resolved_replay_policy,
            "approval_required": True,
            "approval_state": "approved",
            "approval_lineage_id": approval.approval_lineage_id,
            "approval_epoch": approval.approval_epoch,
            "approved_approval_id": approval.approval_id,
            "approved_by": self.owner.id,
            "input_hash": call.input_hash,
            "output_hash": result.output_hash,
            "recovery_decision": None,
            "error_code": None,
            "error_message_hash": None,
        }

        self.assertEqual(
            {key: execution_context[key] for key in expected_context},
            expected_context,
        )
        self.assertEqual(
            execution_context["execution_context_hash"],
            request_fingerprint(expected_context),
        )
        self.assertNotIn("input_json_redacted", execution_context)
        self.assertNotIn("output_json_redacted", execution_context)
        self.assertNotIn("evidence_refs_json", execution_context)

    def test_executor_records_recovery_execution_context_on_backend_failure(self):
        from app.core.sensitive_data import request_fingerprint

        run = self._create_run("backend failure execution context")
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=self.owner,
        )

        class FailingToolRuntime:
            def __init__(self, db, *, backend_factory):
                self.db = db
                self.backend_factory = backend_factory

            def execute(self, *, call, current_user):
                raise RuntimeError("backend adapter exploded with secret-token")

        result = ToolExecutor(
            self.db,
            tool_runtime_factory=lambda db, backend_factory: FailingToolRuntime(
                db,
                backend_factory=backend_factory,
            ),
        ).execute_next(worker_id="worker-failure")

        execution_context = result.policy_reason_json["execution_context"]
        expected_context = {
            "execution_context_version_hash": "agent-tool-execution-v1",
            "tool_call_id": call.tool_call_id,
            "run_id": run.run_id,
            "runtime_snapshot_id": call.runtime_snapshot_id,
            "tool_name": "project.read_context",
            "tool_version": "1.0.0",
            "worker_id": "worker-failure",
            "tool_status": "failed",
            "execution_phase": "pre_effect",
            "effect_submission_state": "transport_sent_observed",
            "effect_boundary_crossed": False,
            "backend_name": "project-service",
            "backend_operation": "read_context",
            "backend_contract_version": "v1",
            "backend_request_schema_hash": call.backend_request_schema_hash,
            "backend_output_schema_hash": call.backend_output_schema_hash,
            "reconcile_contract_version": call.reconcile_contract_version,
            "result_adapter_version": call.result_adapter_version,
            "backend_effect_capability": "idempotency_index_only",
            "resolved_side_effect_class": "read_only",
            "resolved_replay_policy": call.resolved_replay_policy,
            "approval_required": False,
            "approval_state": "not_required",
            "approval_lineage_id": None,
            "approval_epoch": 0,
            "approved_approval_id": None,
            "approved_by": None,
            "input_hash": call.input_hash,
            "output_hash": None,
            "recovery_decision": "tool_execution_failed_repair_required",
            "error_code": "tool_execution_failed",
            "error_message_hash": request_fingerprint({"error_message": result.error_message}),
        }

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "tool_execution_failed")
        self.assertEqual(
            {key: execution_context[key] for key in expected_context},
            expected_context,
        )
        self.assertEqual(
            execution_context["execution_context_hash"],
            request_fingerprint(expected_context),
        )
        self.assertNotIn("secret-token", str(execution_context))
        self.assertNotIn("input_json_redacted", execution_context)
        self.assertNotIn("output_json_redacted", execution_context)
        self.assertNotIn("evidence_refs_json", execution_context)

    def test_executor_delegates_backend_call_to_tool_runtime(self):
        run = self._create_run("runtime delegates backend execution")
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=self.owner,
        )
        runtime_calls = []

        class FakeToolRuntime:
            def __init__(self, db, *, backend_factory):
                self.db = db
                self.backend_factory = backend_factory

            def execute(self, *, call, current_user):
                runtime_calls.append({
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                    "user_id": current_user.id,
                })
                return {
                    "executed_by": "tool-runtime",
                    "project_id": call.input_json_redacted["project_id"],
                }

        result = ToolExecutor(
            self.db,
            backend_factory=lambda db: RaisingBackend(),
            tool_runtime_factory=lambda db, backend_factory: FakeToolRuntime(
                db,
                backend_factory=backend_factory,
            ),
        ).execute_next(worker_id="worker-runtime")

        self.assertEqual(result.tool_call_id, call.tool_call_id)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.output_json_redacted["executed_by"], "tool-runtime")
        self.assertEqual(runtime_calls, [{
            "tool_call_id": call.tool_call_id,
            "tool_name": "project.read_context",
            "user_id": self.owner.id,
        }])

    def test_executor_runs_ai_skill_draft_tool_through_allowlisted_backend(self):
        run = self._create_run("ai draft")
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="ai_skill.run_draft",
                input={
                    "project_id": 10,
                    "environment_id": 20,
                    "skill_id": "http-test-case",
                    "operation": "generate",
                    "input": {"interface_text": "GET /users"},
                },
                step_index=0,
            ),
            current_user=self.owner,
        )

        with patch("app.services.agent_tool_service.AISkillService.run_skill", return_value={"cases": []}) as run_skill:
            result = ToolExecutor(self.db).execute_next(worker_id="worker-ai-draft")

        self.assertEqual(result.tool_call_id, call.tool_call_id)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.backend_operation, "run_draft")
        self.assertEqual(result.output_json_redacted["skill_id"], "http-test-case")
        self.assertEqual(result.output_json_redacted["operation"], "generate")
        run_skill.assert_called_once()

    def test_executor_runs_scenario_dry_run_as_execution_record(self):
        run = self._create_run("scenario dry run")
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="scenario.execute_dry_run",
                input={"project_id": 10, "scenario_id": 33, "idempotency_key": "agent-dry-run-1"},
                step_index=0,
            ),
            current_user=self.owner,
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        scenario_run = SimpleNamespace(
            id=44,
            execution_id=None,
            scenario_id=33,
            project_id=10,
            environment_id=20,
            dataset_id=None,
            dataset_name=None,
            record_id=None,
            record_name=None,
            status="passed",
            trigger_type="agent_dry_run",
            variables_snapshot={},
            step_results=[],
            current_step_id=None,
            current_step_index=None,
            last_event_sequence=0,
            started_at=now,
            finished_at=now,
            duration_ms=1,
            created_at=now,
        )

        with patch("app.services.agent_tool_service.ScenarioService.execute_scenario", return_value=[scenario_run]) as execute:
            result = ToolExecutor(self.db).execute_next(worker_id="worker-scenario-dry-run")

        self.assertEqual(result.tool_call_id, call.tool_call_id)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.resolved_side_effect_class, "execution_record")
        self.assertEqual(result.backend_operation, "execute_dry_run")
        self.assertTrue(result.effect_boundary_crossed)
        self.assertEqual(result.output_json_redacted["run_ids"], [44])
        self.assertEqual(execute.call_args.kwargs["trigger_type"], "agent_dry_run")

    def test_reconcile_result_statuses_parse(self):
        for status_value in [
            "succeeded",
            "running",
            "failed",
            "not_found",
            "conflict",
            "unsupported_schema_version",
        ]:
            result = ReconcileResult.model_validate({
                "found": status_value == "succeeded",
                "status": status_value,
                "backend_contract_version": "v1",
            })
            self.assertEqual(result.status, status_value)

    def test_harness_reconcile_contract_matches_worker_and_schema(self):
        from pathlib import Path

        def _split_csv(value: str) -> set[str]:
            return {item.strip() for item in value.split(",") if item.strip()}

        def _parse_contract(text: str) -> dict[str, set[str]]:
            section = text[text.index("Required Reconcile contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            return {
                key.strip(): _split_csv(value.strip())
                for line in block.splitlines()
                if "=" in line
                for key, value in [line.split("=", 1)]
            }

        expected_contract = {
            "eligible_tool_call_statuses": RECONCILE_ELIGIBLE_STATUSES,
            "result_statuses": RECONCILE_RESULT_STATUSES,
            "schema_support_values": RECONCILE_SCHEMA_SUPPORT_VALUES,
            "success_result_statuses": RECONCILE_SUCCESS_RESULT_STATUSES,
            "backoff_result_statuses": RECONCILE_BACKOFF_RESULT_STATUSES,
            "terminal_failure_result_statuses": RECONCILE_TERMINAL_FAILURE_RESULT_STATUSES,
            "direct_manual_result_statuses": RECONCILE_DIRECT_MANUAL_RESULT_STATUSES,
            "state_dependent_result_statuses": RECONCILE_STATE_DEPENDENT_RESULT_STATUSES,
            "migration_result_statuses": RECONCILE_MIGRATION_RESULT_STATUSES,
            "backoff_effect_states": RECONCILE_BACKOFF_EFFECT_STATES,
            "backoff_capabilities": RECONCILE_BACKOFF_CAPABILITIES,
            "result_envelope_fields": RECONCILE_RESULT_ENVELOPE_FIELDS,
            "summary_fields": RECONCILE_SUMMARY_FIELDS,
            "skipped_backoff_fields": RECONCILE_SKIPPED_BACKOFF_FIELDS,
        }
        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            _parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Reconcile contract:" in path.read_text(encoding="utf-8")
        ]
        schema = ReconcileResult.model_json_schema()
        skipped_payload = {
            "tool_call_id": "tool-1",
            "next_retry_at": "2026-06-26T00:00:00",
            "attempt_seq": 1,
            "result_status": "not_found",
        }
        summary = ReconcileWorker._summary("run-1", [], skipped_backoff=[skipped_payload])

        self.assertEqual(len(documented_contracts), 2)
        for contract in documented_contracts:
            self.assertEqual(contract, expected_contract)
        self.assertEqual(set(schema["properties"]["status"]["enum"]), RECONCILE_RESULT_STATUSES)
        self.assertEqual(
            set(schema["properties"]["schema_support"]["enum"]),
            RECONCILE_SCHEMA_SUPPORT_VALUES,
        )
        self.assertEqual(set(ReconcileResult.model_fields), RECONCILE_RESULT_ENVELOPE_FIELDS)
        self.assertEqual(set(summary), RECONCILE_SUMMARY_FIELDS)
        self.assertEqual(set(summary["skipped_backoff_tool_calls"][0]), RECONCILE_SKIPPED_BACKOFF_FIELDS)

    def test_reconcile_succeeded_marks_tool_call_succeeded(self):
        run = self._create_run("恢复成功")
        call = self._create_uncertain_call(run.run_id, step_index=0)
        result = ReconcileResult(
            found=True,
            status="succeeded",
            backend_contract_version="v1",
            external_resource_type="agent_tool",
            external_resource_id="resource-1",
            canonical_summary_json={"ok": True},
        )

        summary = ReconcileWorker(self.db, router=StaticReconcileRouter(result)).reconcile_run(
            run_id=run.run_id,
            current_user=self.owner,
        )
        refreshed = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == call.tool_call_id))
        attempts = list(self.db.scalars(select(AgentReconcileAttempt).where(
            AgentReconcileAttempt.tool_call_id == call.tool_call_id
        )).all())
        events = [item.event_type for item in self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all()]

        self.assertEqual(summary["reconciled"], 1)
        self.assertEqual(refreshed.status, "succeeded")
        self.assertEqual(refreshed.effect_submission_state, "effect_committed")
        self.assertEqual(refreshed.external_resource_id, "resource-1")
        self.assertEqual(refreshed.recovery_decision, "mark_succeeded_from_reconcile")
        self.assertEqual(len(attempts), 1)
        self.assertIn("tool.reconciled", events)

    def test_reconcile_not_found_rules_are_state_specific(self):
        run = self._create_run("not found 分流")
        send_intent = self._create_uncertain_call(
            run.run_id,
            step_index=0,
            effect_state="send_intent_recorded",
        )
        transport = self._create_uncertain_call(
            run.run_id,
            step_index=1,
            effect_state="transport_sent_observed",
        )
        accepted = self._create_uncertain_call(
            run.run_id,
            step_index=2,
            effect_state="backend_accepted",
        )
        accepted.backend_effect_capability = "receipt_first"
        committed = self._create_uncertain_call(
            run.run_id,
            step_index=3,
            effect_state="effect_committed",
        )
        self.db.commit()
        AgentOutboxPublisher(self.db, publisher=lambda event: None).publish_pending(limit=100)
        result = ReconcileResult(
            found=False,
            status="not_found",
            backend_contract_version="v1",
            error_code="reconcile_not_found",
        )
        metrics_before = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot_before = AgentAlertService(self.db).snapshot(project_id=10)
        alerts_before = {
            item["alert_id"]: item
            for item in alert_snapshot_before["alerts"]
        }
        dashboard_before = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks_before = {item["name"]: item for item in dashboard_before["checks"]}

        summary = ReconcileWorker(self.db, router=StaticReconcileRouter(result)).reconcile_run(
            run_id=run.run_id,
            current_user=self.owner,
        )
        AgentOutboxPublisher(self.db, publisher=lambda event: None).publish_pending(limit=100)

        refreshed = {
            item.tool_call_id: item
            for item in self.db.scalars(select(AgentToolCall).where(AgentToolCall.run_id == run.run_id)).all()
        }
        metrics_after = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot_after = AgentAlertService(self.db).snapshot(project_id=10)
        alerts_after = {
            item["alert_id"]: item
            for item in alert_snapshot_after["alerts"]
        }
        dashboard_after = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks_after = {item["name"]: item for item in dashboard_after["checks"]}

        self.assertEqual(metrics_before["tool_call_send_intent_orphan_total"], 1)
        self.assertEqual(metrics_before["tool_call_transport_sent_uncertain_total"], 1)
        self.assertEqual(metrics_before["tool_call_backend_accepted_uncertain_total"], 1)
        self.assertGreaterEqual(metrics_before["backend_effect_capability_receipt_first_total"], 1)
        self.assertIn("agent_tool_call_send_intent_orphan", alerts_before)
        self.assertIn("agent_tool_call_transport_sent_uncertain", alerts_before)
        self.assertIn("agent_tool_call_backend_accepted_uncertain", alerts_before)
        self.assertEqual(alerts_before["agent_tool_call_send_intent_orphan"]["severity"], "P2")
        self.assertEqual(alerts_before["agent_tool_call_send_intent_orphan"]["runbook_id"], "tool_call_uncertain")
        self.assertEqual(alerts_before["agent_tool_call_transport_sent_uncertain"]["severity"], "P1")
        self.assertEqual(alerts_before["agent_tool_call_transport_sent_uncertain"]["runbook_id"], "tool_call_uncertain")
        self.assertEqual(alerts_before["agent_tool_call_backend_accepted_uncertain"]["severity"], "P0")
        self.assertEqual(alerts_before["agent_tool_call_backend_accepted_uncertain"]["runbook_id"], "tool_call_uncertain")
        self.assertEqual(alert_snapshot_before["summary"]["highest_severity"], "P0")
        self.assertEqual(dashboard_before["readiness"], "blocked")
        self.assertEqual(checks_before["monitoring_alerts_clear"]["status"], "blocked")
        self.assertEqual(summary["processed"], 4)
        self.assertEqual(refreshed[send_intent.tool_call_id].status, "failed_retryable")
        self.assertEqual(refreshed[send_intent.tool_call_id].recovery_decision, "safe_retry_same_idempotency_key")
        self.assertEqual(refreshed[transport.tool_call_id].status, "uncertain")
        self.assertEqual(refreshed[transport.tool_call_id].recovery_decision, "reconcile_backoff")
        self.assertEqual(refreshed[accepted.tool_call_id].status, "manual_intervention")
        self.assertEqual(refreshed[accepted.tool_call_id].recovery_decision, "backend_accepted_not_found_incident")
        self.assertEqual(refreshed[committed.tool_call_id].status, "manual_intervention")
        self.assertEqual(refreshed[committed.tool_call_id].recovery_decision, "effect_committed_not_found_incident")
        self.assertEqual(metrics_after["tool_call_safe_retry_after_send_intent_not_found_total"], 1)
        self.assertEqual(metrics_after["tool_call_transport_sent_uncertain_total"], 1)
        self.assertIn("agent_tool_call_safe_retry_after_send_intent_not_found", alerts_after)
        self.assertIn("agent_tool_call_transport_sent_uncertain", alerts_after)
        self.assertEqual(
            alerts_after["agent_tool_call_safe_retry_after_send_intent_not_found"]["severity"],
            "P2",
        )
        self.assertEqual(
            alerts_after["agent_tool_call_safe_retry_after_send_intent_not_found"]["runbook_id"],
            "tool_call_uncertain",
        )
        self.assertEqual(alerts_after["agent_tool_call_transport_sent_uncertain"]["severity"], "P1")
        self.assertEqual(alerts_after["agent_tool_call_transport_sent_uncertain"]["runbook_id"], "tool_call_uncertain")
        self.assertEqual(alert_snapshot_after["summary"]["highest_severity"], "P1")
        self.assertEqual(dashboard_after["readiness"], "attention")
        self.assertEqual(checks_after["monitoring_alerts_clear"]["status"], "attention")

    def test_reconcile_backoff_skips_until_next_retry_at(self):
        run = self._create_run("reconcile backoff")
        call = self._create_uncertain_call(
            run.run_id,
            step_index=0,
            effect_state="transport_sent_observed",
        )
        result = ReconcileResult(
            found=False,
            status="not_found",
            backend_contract_version="v1",
            error_code="reconcile_not_found",
        )

        first = ReconcileWorker(self.db, router=StaticReconcileRouter(result), backoff_seconds=3600).reconcile_run(
            run_id=run.run_id,
            current_user=self.owner,
        )
        second = ReconcileWorker(self.db, router=RaisingReconcileRouter()).reconcile_run(
            run_id=run.run_id,
            current_user=self.owner,
        )
        attempts = list(self.db.scalars(select(AgentReconcileAttempt).where(
            AgentReconcileAttempt.tool_call_id == call.tool_call_id
        )).all())
        call.status = "reconciling"
        call.effect_submission_state = "unknown"
        self.db.commit()
        AgentOutboxPublisher(self.db, publisher=lambda event: None).publish_pending(limit=100)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        alerts = {item["alert_id"]: item for item in alert_snapshot["alerts"]}
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)

        self.assertEqual(first["processed"], 1)
        self.assertEqual(first["skipped_backoff"], 0)
        self.assertEqual(second["processed"], 0)
        self.assertEqual(second["skipped_backoff"], 1)
        self.assertEqual(second["skipped_backoff_tool_calls"][0]["tool_call_id"], call.tool_call_id)
        self.assertEqual(len(attempts), 1)
        self.assertIsNotNone(attempts[0].next_retry_at)
        self.assertEqual(metrics["reconcile_backoff_active_total"], 1)
        self.assertIn("agent_reconcile_backoff_pending", alerts)
        self.assertEqual(alerts["agent_reconcile_backoff_pending"]["severity"], "P2")
        self.assertEqual(alerts["agent_reconcile_backoff_pending"]["runbook_id"], "tool_call_uncertain")
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P2")
        self.assertEqual(dashboard["readiness"], "pass")

    def test_reconcile_unsupported_schema_creates_migration_block(self):
        run = self._create_run("schema migration")
        call = self._create_uncertain_call(run.run_id, step_index=0)
        result = ReconcileResult(
            found=False,
            status="unsupported_schema_version",
            schema_support="unsupported",
            backend_contract_version="v1",
            error_code="unsupported_schema_version",
            error_message="adapter required",
        )

        summary = ReconcileWorker(self.db, router=StaticReconcileRouter(result)).reconcile_run(
            run_id=run.run_id,
            current_user=self.owner,
        )
        refreshed_run = AgentRuntimeService(self.db).get_run(run_id=run.run_id, current_user=self.owner)
        refreshed_call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == call.tool_call_id))
        block = self.db.scalar(select(AgentMigrationBlock).where(AgentMigrationBlock.run_id == run.run_id))

        self.assertEqual(summary["needs_migration"], 1)
        self.assertEqual(refreshed_call.status, "needs_migration")
        self.assertEqual(refreshed_run.status, "migration_blocked")
        self.assertEqual(refreshed_run.migration_block_count, 1)
        self.assertEqual(refreshed_run.blocking_tool_call_ids_json, [call.tool_call_id])
        self.assertEqual(block.status, "open")
        AgentOutboxPublisher(self.db, publisher=lambda event: None).publish_pending(limit=100)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        alerts = {
            item["alert_id"]: item
            for item in alert_snapshot["alerts"]
        }
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertEqual(metrics["migration_block_open_total"], 1)
        self.assertEqual(metrics["backend_contract_migration_block_total"], 1)
        self.assertEqual(metrics["run_migration_blocked_total"], 1)
        self.assertIn("agent_migration_block_open", alerts)
        self.assertIn("agent_backend_contract_migration_block", alerts)
        self.assertIn("agent_run_migration_blocked", alerts)
        self.assertEqual(alerts["agent_migration_block_open"]["severity"], "P1")
        self.assertEqual(alerts["agent_migration_block_open"]["runbook_id"], "migration_blocked")
        self.assertEqual(alerts["agent_backend_contract_migration_block"]["runbook_id"], "migration_blocked")
        self.assertEqual(alerts["agent_run_migration_blocked"]["runbook_id"], "migration_blocked")
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P1")
        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["live_recovery_attention"]["status"], "attention")
        self.assertEqual(
            checks["live_recovery_attention"]["details"]["migration_block_open_total"],
            1,
        )

    def test_reconcile_missing_backend_contract_alerts_tool_call_contract_unsupported(self):
        run = self._create_run("missing backend contract")
        call = self._create_uncertain_call(run.run_id, step_index=0)
        call.backend_contract_version = "missing-contract-version"
        self.db.commit()

        summary = ReconcileWorker(self.db, router=RaisingReconcileRouter()).reconcile_run(
            run_id=run.run_id,
            current_user=self.owner,
        )
        refreshed_call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == call.tool_call_id))
        AgentOutboxPublisher(self.db, publisher=lambda event: None).publish_pending(limit=100)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        alerts = {
            item["alert_id"]: item
            for item in alert_snapshot["alerts"]
        }
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertEqual(summary["needs_migration"], 1)
        self.assertEqual(refreshed_call.status, "needs_migration")
        self.assertEqual(refreshed_call.error_code, "backend_contract_unsupported")
        self.assertEqual(metrics["tool_call_backend_contract_unsupported_total"], 1)
        self.assertIn("agent_tool_call_backend_contract_unsupported", alerts)
        self.assertEqual(alerts["agent_tool_call_backend_contract_unsupported"]["severity"], "P1")
        self.assertEqual(alerts["agent_tool_call_backend_contract_unsupported"]["runbook_id"], "migration_blocked")
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P1")
        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "attention")

    def test_resolve_migration_block_runs_freshness_gate_and_resumes_when_fresh(self):
        run, call, block = self._create_migration_block()

        resolved, freshness = MigrationCoordinator(self.db).resolve_block(
            run_id=run.run_id,
            block_id=block.block_id,
            current_user=self.owner,
            resolution_note="adapter deployed",
        )
        refreshed_run = AgentRuntimeService(self.db).get_run(run_id=run.run_id, current_user=self.owner)
        refreshed_call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == call.tool_call_id))
        events = [item.event_type for item in self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all()]

        self.assertEqual(resolved.status, "resolved")
        self.assertEqual(resolved.resolved_by, self.owner.id)
        self.assertEqual(freshness["action"], "continue_from_checkpoint")
        self.assertEqual(refreshed_run.status, "running")
        self.assertEqual(refreshed_run.migration_block_count, 0)
        self.assertEqual(refreshed_run.blocking_tool_call_ids_json, [])
        self.assertEqual(refreshed_call.status, "reconciling")
        self.assertIn("checkpoint.freshness_checked", events)
        self.assertIn("run.migration_resolved", events)

    def test_resolve_migration_block_pauses_when_evidence_is_stale(self):
        run, _, block = self._create_migration_block()
        ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[
                    {
                        "evidence_ref_id": "scenario-current",
                        "ref_type": "scenario",
                        "ref_id": "scenario-1",
                        "mutability_class": "mutable_current",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
            ),
            current_user=self.owner,
        )
        EvidenceWatchService(self.db).mark_stale_by_ref(
            ref_type="scenario",
            ref_id="scenario-1",
            stale_reason="scenario.updated",
        )

        resolved, freshness = MigrationCoordinator(self.db).resolve_block(
            run_id=run.run_id,
            block_id=block.block_id,
            current_user=self.owner,
        )
        refreshed_run = AgentRuntimeService(self.db).get_run(run_id=run.run_id, current_user=self.owner)

        self.assertEqual(resolved.status, "resolved")
        self.assertEqual(freshness["result"], "evidence_stale")
        self.assertEqual(freshness["action"], "fetch_evidence_and_rebuild_context")
        self.assertEqual(refreshed_run.status, "paused")
        self.assertEqual(refreshed_run.error_code, "fetch_evidence_and_rebuild_context")

    def test_checkpoint_freshness_gate_detects_missing_checkpoint(self):
        run = self._create_run("missing checkpoint")
        run.last_checkpoint_id = None
        self.db.commit()

        freshness = CheckpointFreshnessGate(self.db).evaluate(run=run)

        self.assertEqual(freshness["result"], "too_old")
        self.assertEqual(freshness["action"], "replan_from_latest_safe_state")

    def test_resume_run_pauses_when_runtime_snapshot_mismatches_checkpoint(self):
        run = self._create_run("runtime snapshot mismatch")
        checkpoint = self.db.get(AgentCheckpoint, run.last_checkpoint_id)
        previous_snapshot_id = run.runtime_snapshot_id
        run.runtime_snapshot_id = "agent-snap-replaced-runtime"
        run.status = "paused"
        self.db.commit()

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alerts = {
            item["alert_id"]: item
            for item in AgentAlertService(self.db).snapshot(project_id=10)["alerts"]
        }

        self.assertFalse(result["resumed"])
        self.assertEqual(result["run"].status, "paused")
        self.assertEqual(result["run"].error_code, "checkpoint_stale_replan_required")
        self.assertEqual(result["checkpoint_freshness"]["result"], "too_old")
        self.assertEqual(result["checkpoint_freshness"]["reason"], "runtime_snapshot_mismatch")
        self.assertEqual(result["checkpoint_freshness"]["checkpoint_runtime_snapshot_id"], previous_snapshot_id)
        self.assertEqual(result["checkpoint_freshness"]["run_runtime_snapshot_id"], "agent-snap-replaced-runtime")
        self.assertFalse(result["checkpoint_freshness"]["runtime_snapshot_compatible"])
        self.assertEqual(checkpoint.runtime_snapshot_id, previous_snapshot_id)
        paused_event = self.db.scalar(
            select(AgentEvent)
            .where(AgentEvent.run_id == run.run_id, AgentEvent.event_type == "run.paused")
            .order_by(AgentEvent.event_seq.desc())
        )
        self.assertEqual(paused_event.payload_json["error_code"], "checkpoint_stale_replan_required")
        self.assertEqual(metrics["checkpoint_freshness_failed_total"], 1)
        self.assertIn("agent_checkpoint_freshness_failed", alerts)
        self.assertEqual(alerts["agent_checkpoint_freshness_failed"]["severity"], "P1")
        self.assertEqual(alerts["agent_checkpoint_freshness_failed"]["runbook_id"], "checkpoint_stale")

    def test_resume_run_pauses_when_checkpoint_runtime_snapshot_is_missing(self):
        run = self._create_run("runtime snapshot missing")
        checkpoint = self.db.get(AgentCheckpoint, run.last_checkpoint_id)
        snapshot = self.db.scalar(
            select(AgentRuntimeSnapshot).where(
                AgentRuntimeSnapshot.project_id == run.project_id,
                AgentRuntimeSnapshot.snapshot_id == checkpoint.runtime_snapshot_id,
            )
        )
        self.assertIsNotNone(snapshot)
        self.db.delete(snapshot)
        run.status = "paused"
        self.db.commit()

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)
        paused_event = self.db.scalar(
            select(AgentEvent)
            .where(AgentEvent.run_id == run.run_id, AgentEvent.event_type == "run.paused")
            .order_by(AgentEvent.event_seq.desc())
        )

        self.assertFalse(result["resumed"])
        self.assertEqual(result["run"].status, "paused")
        self.assertEqual(result["run"].error_code, "checkpoint_stale_replan_required")
        self.assertEqual(result["checkpoint_freshness"]["result"], "too_old")
        self.assertEqual(result["checkpoint_freshness"]["reason"], "runtime_snapshot_missing")
        self.assertEqual(
            result["checkpoint_freshness"]["checkpoint_runtime_snapshot_id"],
            checkpoint.runtime_snapshot_id,
        )
        self.assertEqual(result["checkpoint_freshness"]["run_runtime_snapshot_id"], run.runtime_snapshot_id)
        self.assertFalse(result["checkpoint_freshness"]["runtime_snapshot_compatible"])
        self.assertEqual(paused_event.payload_json["error_code"], "checkpoint_stale_replan_required")

    def test_harness_runtime_snapshot_freshness_contract_matches_gate(self):
        from pathlib import Path

        def _parse_contract(text: str) -> dict[str, object]:
            section = text[text.index("Required runtime snapshot freshness contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            parsed: dict[str, object] = {}
            for line in block.splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                if key in {"freshness_fields", "reasons"}:
                    parsed[key] = [item.strip() for item in value.split(",") if item.strip()]
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            _parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required runtime snapshot freshness contract:" in path.read_text(encoding="utf-8")
        ]
        expected_contract = {
            "freshness_fields": list(RUNTIME_SNAPSHOT_FRESHNESS_FIELDS),
            "result": RUNTIME_SNAPSHOT_FRESHNESS_RESULT,
            "action": RUNTIME_SNAPSHOT_FRESHNESS_ACTION,
            "reasons": list(RUNTIME_SNAPSHOT_FRESHNESS_REASONS),
            "paused_error_code": RUNTIME_SNAPSHOT_FRESHNESS_ERROR_CODE,
        }
        mismatch_run = self._create_run("runtime snapshot contract mismatch")
        mismatch_checkpoint = self.db.get(AgentCheckpoint, mismatch_run.last_checkpoint_id)
        mismatch_run.runtime_snapshot_id = "agent-snap-contract-mismatch"
        mismatch_run.status = "paused"
        self.db.commit()
        mismatch = AgentRunResumeService(self.db).resume_run(run_id=mismatch_run.run_id, current_user=self.owner)

        missing_run = self._create_run("runtime snapshot contract missing")
        missing_checkpoint = self.db.get(AgentCheckpoint, missing_run.last_checkpoint_id)
        missing_snapshot = self.db.scalar(
            select(AgentRuntimeSnapshot).where(
                AgentRuntimeSnapshot.project_id == missing_run.project_id,
                AgentRuntimeSnapshot.snapshot_id == missing_checkpoint.runtime_snapshot_id,
            )
        )
        self.assertIsNotNone(missing_snapshot)
        self.db.delete(missing_snapshot)
        missing_run.status = "paused"
        self.db.commit()

        missing = AgentRunResumeService(self.db).resume_run(run_id=missing_run.run_id, current_user=self.owner)

        self.assertEqual(len(documented_contracts), 2)
        for documented in documented_contracts:
            self.assertEqual(documented, expected_contract)
        for result in (mismatch, missing):
            freshness = result["checkpoint_freshness"]
            self.assertFalse(result["resumed"])
            self.assertEqual(result["run"].error_code, RUNTIME_SNAPSHOT_FRESHNESS_ERROR_CODE)
            self.assertEqual(freshness["result"], RUNTIME_SNAPSHOT_FRESHNESS_RESULT)
            self.assertEqual(freshness["action"], RUNTIME_SNAPSHOT_FRESHNESS_ACTION)
            self.assertIn(freshness["reason"], RUNTIME_SNAPSHOT_FRESHNESS_REASONS)
            self.assertTrue(set(RUNTIME_SNAPSHOT_FRESHNESS_FIELDS).issubset(freshness))
            self.assertFalse(freshness["runtime_snapshot_compatible"])
        self.assertEqual(mismatch["checkpoint_freshness"]["reason"], RUNTIME_SNAPSHOT_FRESHNESS_REASONS[1])
        self.assertEqual(
            mismatch["checkpoint_freshness"]["checkpoint_runtime_snapshot_id"],
            mismatch_checkpoint.runtime_snapshot_id,
        )
        self.assertEqual(mismatch["checkpoint_freshness"]["run_runtime_snapshot_id"], "agent-snap-contract-mismatch")
        self.assertEqual(missing["checkpoint_freshness"]["reason"], RUNTIME_SNAPSHOT_FRESHNESS_REASONS[0])
        self.assertEqual(
            missing["checkpoint_freshness"]["checkpoint_runtime_snapshot_id"],
            missing_checkpoint.runtime_snapshot_id,
        )

    def test_resume_run_pauses_when_backend_contract_is_missing(self):
        run = self._create_run("backend contract missing freshness")
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=self.owner,
            enqueue=False,
        )
        run.status = "paused"
        contract = self.db.scalar(
            select(AgentBackendContract).where(
                AgentBackendContract.backend_name == call.backend_name,
                AgentBackendContract.backend_operation == call.backend_operation,
                AgentBackendContract.backend_contract_version == call.backend_contract_version,
            )
        )
        self.assertIsNotNone(contract)
        self.db.delete(contract)
        self.db.commit()

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)
        paused_event = self.db.scalar(
            select(AgentEvent)
            .where(AgentEvent.run_id == run.run_id, AgentEvent.event_type == "run.paused")
            .order_by(AgentEvent.event_seq.desc())
        )

        self.assertFalse(result["resumed"])
        self.assertEqual(result["run"].status, "paused")
        self.assertEqual(result["run"].error_code, "migration_block")
        self.assertEqual(result["checkpoint_freshness"]["result"], "backend_contract_changed")
        self.assertEqual(result["checkpoint_freshness"]["action"], "migration_block")
        self.assertEqual(result["checkpoint_freshness"]["reason"], "backend_contract_missing")
        self.assertEqual(result["checkpoint_freshness"]["backend_contract_missing_count"], 1)
        self.assertEqual(call.backend_name, "project-service")
        self.assertEqual(call.backend_operation, "read_context")
        self.assertEqual(call.backend_contract_version, "v1")
        self.assertEqual(paused_event.payload_json["error_code"], "migration_block")

    def test_resume_run_reports_expired_pending_approval_freshness(self):
        run, call, approval = self._create_pending_approval(
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        )
        run.status = "paused"
        self.db.commit()

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertFalse(result["resumed"])
        self.assertEqual(result["run"].status, "paused")
        self.assertEqual(result["checkpoint_freshness"]["result"], "approval_stale")
        self.assertEqual(result["checkpoint_freshness"]["reason"], "pending_approval_expired")
        self.assertEqual(result["checkpoint_freshness"]["pending_approval_count"], 1)
        self.assertEqual(result["checkpoint_freshness"]["expired_pending_approval_count"], 1)
        self.assertEqual(result["checkpoint_freshness"]["stale_pending_approval_count"], 0)
        self.assertEqual(
            result["checkpoint_freshness"]["pending_approval_details"][0]["approval_id"],
            approval.approval_id,
        )
        self.assertEqual(
            result["checkpoint_freshness"]["pending_approval_details"][0]["tool_call_id"],
            call.tool_call_id,
        )
        self.assertIn("expired", result["checkpoint_freshness"]["pending_approval_details"][0]["stale_reasons"])
        self.assertEqual(metrics["checkpoint_freshness_failed_total"], 1)

    def test_resume_run_reports_stale_pending_approval_freshness(self):
        run, call, approval = self._create_pending_approval()
        call.input_hash = "changed-after-approval"
        run.status = "paused"
        self.db.commit()

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)

        freshness = result["checkpoint_freshness"]
        self.assertFalse(result["resumed"])
        self.assertEqual(result["run"].status, "paused")
        self.assertEqual(freshness["result"], "approval_stale")
        self.assertEqual(freshness["reason"], "pending_approval_stale")
        self.assertEqual(freshness["pending_approval_count"], 1)
        self.assertEqual(freshness["expired_pending_approval_count"], 0)
        self.assertEqual(freshness["stale_pending_approval_count"], 1)
        self.assertEqual(freshness["pending_approval_details"][0]["approval_id"], approval.approval_id)
        self.assertEqual(freshness["pending_approval_details"][0]["tool_call_id"], call.tool_call_id)
        self.assertIn("immutable_mismatch", freshness["pending_approval_details"][0]["stale_reasons"])

    def test_resume_run_reports_pending_approval_after_wait_freshness(self):
        run, call, approval = self._create_pending_approval()
        run.status = "paused"
        self.db.commit()

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)

        freshness = result["checkpoint_freshness"]
        self.assertFalse(result["resumed"])
        self.assertEqual(result["run"].status, "paused")
        self.assertEqual(freshness["result"], "approval_stale")
        self.assertEqual(freshness["reason"], "pending_approval_after_wait")
        self.assertEqual(freshness["pending_approval_count"], 1)
        self.assertEqual(freshness["expired_pending_approval_count"], 0)
        self.assertEqual(freshness["stale_pending_approval_count"], 0)
        self.assertEqual(freshness["pending_approval_details"][0]["approval_id"], approval.approval_id)
        self.assertEqual(freshness["pending_approval_details"][0]["tool_call_id"], call.tool_call_id)
        self.assertEqual(freshness["pending_approval_details"][0]["stale_reasons"], ["pending_after_wait"])

    def test_harness_pending_approval_freshness_contract_matches_gate(self):
        from pathlib import Path

        def _parse_contract(text: str) -> dict[str, object]:
            section = text[text.index("Required pending approval freshness contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            parsed: dict[str, object] = {}
            for line in block.splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                if key in {"freshness_fields", "detail_fields", "reasons", "stale_reasons"}:
                    parsed[key] = [item.strip() for item in value.split(",") if item.strip()]
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            _parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required pending approval freshness contract:" in path.read_text(encoding="utf-8")
        ]
        expected_contract = {
            "freshness_fields": list(PENDING_APPROVAL_FRESHNESS_FIELDS),
            "detail_fields": list(PENDING_APPROVAL_DETAIL_FIELDS),
            "reasons": list(PENDING_APPROVAL_FRESHNESS_REASONS),
            "stale_reasons": list(PENDING_APPROVAL_DETAIL_STALE_REASONS),
            "result": PENDING_APPROVAL_FRESHNESS_RESULT,
            "action": PENDING_APPROVAL_FRESHNESS_ACTION,
        }

        expired_run, _, _ = self._create_pending_approval(
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
        )
        stale_run, stale_call, _ = self._create_pending_approval()
        stale_call.input_hash = "contract-mismatch"
        waiting_run, _, _ = self._create_pending_approval()
        self.db.commit()

        expired = CheckpointFreshnessGate(self.db).evaluate(run=expired_run)
        stale = CheckpointFreshnessGate(self.db).evaluate(run=stale_run)
        waiting = CheckpointFreshnessGate(self.db).evaluate(run=waiting_run)

        self.assertEqual(len(documented_contracts), 2)
        for documented in documented_contracts:
            self.assertEqual(documented, expected_contract)
        for freshness in (expired, stale, waiting):
            self.assertEqual(freshness["result"], PENDING_APPROVAL_FRESHNESS_RESULT)
            self.assertEqual(freshness["action"], PENDING_APPROVAL_FRESHNESS_ACTION)
            self.assertTrue(set(PENDING_APPROVAL_FRESHNESS_FIELDS).issubset(freshness))
            self.assertEqual(set(freshness["pending_approval_details"][0]), set(PENDING_APPROVAL_DETAIL_FIELDS))
            self.assertIn(freshness["reason"], PENDING_APPROVAL_FRESHNESS_REASONS)
            self.assertTrue(
                set(freshness["pending_approval_details"][0]["stale_reasons"]).issubset(
                    PENDING_APPROVAL_DETAIL_STALE_REASONS
                )
            )
        self.assertEqual(expired["reason"], PENDING_APPROVAL_FRESHNESS_REASONS[0])
        self.assertEqual(stale["reason"], PENDING_APPROVAL_FRESHNESS_REASONS[1])
        self.assertEqual(waiting["reason"], PENDING_APPROVAL_FRESHNESS_REASONS[2])

    def test_resume_run_pauses_when_required_permission_was_revoked(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="resume permission freshness"),
            current_user=self.member,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="report.read_summary",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=self.member,
            enqueue=False,
        )
        call.status = "failed_retryable"
        run.status = "paused"
        self.db.commit()

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.member)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertFalse(result["resumed"])
        self.assertEqual(result["run"].status, "paused")
        self.assertEqual(result["checkpoint_freshness"]["result"], "permission_stale")
        self.assertEqual(result["checkpoint_freshness"]["reason"], "required_permission_revoked")
        self.assertEqual(result["checkpoint_freshness"]["revoked_required_permission_count"], 1)
        self.assertEqual(
            result["checkpoint_freshness"]["revoked_required_permissions"][0]["tool_call_id"],
            call.tool_call_id,
        )
        self.assertEqual(
            result["checkpoint_freshness"]["revoked_required_permissions"][0]["permission"],
            "report:view",
        )
        self.assertEqual(metrics["checkpoint_freshness_failed_total"], 1)

    def test_permission_freshness_scans_all_resume_candidate_tool_statuses(self):
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="resume permission freshness statuses"),
            current_user=self.owner,
        )
        calls_by_status = {}
        for step_index, tool_status in enumerate(sorted(PERMISSION_FRESHNESS_TOOL_STATUSES)):
            call = ExecutionLedgerService(self.db).create_tool_call(
                payload=AgentToolCallCreateRequest(
                    run_id=run.run_id,
                    tool_name="report.read_summary",
                    input={"project_id": 10, "status": tool_status},
                    step_index=step_index,
                ),
                current_user=self.owner,
                enqueue=False,
            )
            call.status = tool_status
            calls_by_status[tool_status] = call
        completed_call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="report.read_summary",
                input={"project_id": 10, "status": "succeeded"},
                step_index=len(calls_by_status),
            ),
            current_user=self.owner,
            enqueue=False,
        )
        completed_call.status = "succeeded"
        run.status = "paused"
        self.db.commit()

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.member)
        freshness = result["checkpoint_freshness"]
        revoked_by_status = {
            item["status"]: item
            for item in freshness["revoked_required_permissions"]
        }

        self.assertFalse(result["resumed"])
        self.assertEqual(freshness["result"], "permission_stale")
        self.assertEqual(freshness["reason"], "required_permission_revoked")
        self.assertEqual(freshness["revoked_required_permission_count"], len(PERMISSION_FRESHNESS_TOOL_STATUSES))
        self.assertEqual(set(revoked_by_status), PERMISSION_FRESHNESS_TOOL_STATUSES)
        self.assertNotIn("succeeded", revoked_by_status)
        for tool_status, call in calls_by_status.items():
            self.assertEqual(revoked_by_status[tool_status]["tool_call_id"], call.tool_call_id)
            self.assertEqual(revoked_by_status[tool_status]["permission"], "report:view")

    def test_harness_permission_freshness_contract_matches_gate(self):
        from pathlib import Path

        def _parse_contract(text: str) -> dict[str, object]:
            section = text[text.index("Required permission freshness contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            parsed: dict[str, object] = {}
            list_keys = {"tool_statuses", "freshness_fields", "detail_fields"}
            for line in block.splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                if key in list_keys:
                    parsed[key] = [item.strip() for item in value.split(",") if item.strip()]
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            _parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required permission freshness contract:" in path.read_text(encoding="utf-8")
        ]
        expected_contract = {
            "tool_statuses": sorted(PERMISSION_FRESHNESS_TOOL_STATUSES),
            "freshness_fields": list(PERMISSION_FRESHNESS_FIELDS),
            "detail_fields": list(PERMISSION_FRESHNESS_DETAIL_FIELDS),
            "result": PERMISSION_FRESHNESS_RESULT,
            "action": PERMISSION_FRESHNESS_ACTION,
            "reason": PERMISSION_FRESHNESS_REASON,
        }
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="permission freshness contract"),
            current_user=self.owner,
        )
        for step_index, tool_status in enumerate(sorted(PERMISSION_FRESHNESS_TOOL_STATUSES)):
            call = ExecutionLedgerService(self.db).create_tool_call(
                payload=AgentToolCallCreateRequest(
                    run_id=run.run_id,
                    tool_name="report.read_summary",
                    input={"project_id": 10, "status": tool_status},
                    step_index=step_index,
                ),
                current_user=self.owner,
                enqueue=False,
            )
            call.status = tool_status
        succeeded = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="report.read_summary",
                input={"project_id": 10, "status": "succeeded"},
                step_index=99,
            ),
            current_user=self.owner,
            enqueue=False,
        )
        succeeded.status = "succeeded"
        run.status = "paused"
        self.db.commit()

        freshness = CheckpointFreshnessGate(self.db).evaluate(run=run, current_user=self.member)
        revoked_by_status = {
            item["status"]: item
            for item in freshness["revoked_required_permissions"]
        }

        self.assertEqual(len(documented_contracts), 2)
        for documented in documented_contracts:
            self.assertEqual(documented, expected_contract)
        self.assertEqual(freshness["result"], PERMISSION_FRESHNESS_RESULT)
        self.assertEqual(freshness["action"], PERMISSION_FRESHNESS_ACTION)
        self.assertEqual(freshness["reason"], PERMISSION_FRESHNESS_REASON)
        self.assertTrue(set(PERMISSION_FRESHNESS_FIELDS).issubset(freshness))
        self.assertEqual(freshness["revoked_required_permission_count"], len(PERMISSION_FRESHNESS_TOOL_STATUSES))
        self.assertEqual(set(revoked_by_status), PERMISSION_FRESHNESS_TOOL_STATUSES)
        self.assertNotIn("succeeded", revoked_by_status)
        self.assertTrue(
            set(PERMISSION_FRESHNESS_DETAIL_FIELDS).issubset(freshness["revoked_required_permissions"][0])
        )

    def test_runbook_catalog_and_run_diagnosis_cover_recovery_states(self):
        from app.services.agent_observability_service import ALERT_RULES

        run, call, _ = self._create_pending_approval()
        call.status = "uncertain"
        call.effect_submission_state = "transport_sent_observed"
        call.backend_effect_capability = "legacy_reconcile_only"
        call.recovery_decision = "reconcile_required_after_eventstore_failure"
        call.error_code = "eventstore_write_failed_after_effect"
        call.policy_reason_json = {
            **(call.policy_reason_json or {}),
            "execution_context": {
                "execution_context_version_hash": "agent-tool-execution-v1",
                "tool_call_id": call.tool_call_id,
                "run_id": run.run_id,
                "runtime_snapshot_id": call.runtime_snapshot_id,
                "tool_name": call.tool_name,
                "tool_version": call.tool_version,
                "worker_id": "worker-runbook-context",
                "tool_status": "uncertain",
                "execution_phase": "completed",
                "effect_submission_state": "transport_sent_observed",
                "effect_boundary_crossed": True,
                "backend_name": call.backend_name,
                "backend_operation": call.backend_operation,
                "backend_contract_version": call.backend_contract_version,
                "backend_effect_capability": "legacy_reconcile_only",
                "resolved_side_effect_class": call.resolved_side_effect_class,
                "resolved_replay_policy": call.resolved_replay_policy,
                "approval_state": "approved",
                "approval_lineage_id": call.approval_lineage_id,
                "approval_epoch": call.approval_epoch,
                "approved_approval_id": call.approved_approval_id,
                "input_hash": call.input_hash,
                "output_hash": call.output_hash,
                "recovery_decision": "reconcile_required_after_eventstore_failure",
                "error_code": "eventstore_write_failed_after_effect",
                "error_message_hash": "safe-error-message-hash",
                "execution_context_hash": "safe-execution-context-hash",
                "input_json_redacted": {"token": "do-not-copy"},
                "output_json_redacted": {"secret": "do-not-copy"},
                "evidence_refs_json": [{"ref_id": "do-not-copy"}],
            },
        }
        run.last_checkpoint_id = None
        self.db.add(
            AgentLoopObservation(
                observation_id="agent-obs-runbook-root-cause-missing",
                run_id=run.run_id,
                iteration=1,
                step_index=0,
                decision_context_build_id="agent-context-runbook-missing",
                decision_context_degradation_level="none",
                iteration_context_degradation_max="none",
                required_evidence_complete_for_decision=True,
                omitted_required_evidence_refs_json=[],
                next_action="stop",
                next_action_is_high_risk=False,
                stop_action_reason="unregistered_reason",
                stop_reasons_all_json=["unregistered_reason"],
                root_cause_primary="root_cause_rule_missing",
                root_cause_rule_id="RC_RULE_MISSING",
                causal_chain_json=["unregistered_reason"],
                mitigation_action="add_explicit_root_cause_rule",
                observation_json={"source": "test_runbook_diagnosis"},
            )
        )
        self.db.commit()
        MigrationCoordinator(self.db).create_tool_call_block(
            run=run,
            call=call,
            reason="unsupported_schema_version",
            details={"schema": "old"},
        )
        AgentRuntimeService(self.db).append_event(
            run,
            "memory.bypassed_evidence_ref",
            {"error_code": "memory_bypassed_evidence_ref"},
        )
        self.db.commit()

        service = AgentRunbookService(self.db)
        catalog = service.list_runbooks()
        diagnosis = service.diagnose_run(run_id=run.run_id, current_user=self.owner)
        runbook_ids = {item["runbook_id"] for item in diagnosis["recommendations"]}
        catalog_ids = {item["runbook_id"] for item in catalog}
        alert_runbook_ids = {
            rule["runbook_id"]
            for rule in ALERT_RULES
            if rule["severity"] in {"P0", "P1"}
        }

        for runbook_id in [
            "tool_call_uncertain",
            "event_replay_recovery",
            "fault_injection_coverage",
            "worker_queue_recovery",
            "backend_capability_degraded",
            "context_linkage_repair",
            "agent_runtime_loop_repair",
            "root_cause_rule_missing",
            "memory_evidence_ref_violation",
            "release_gate_violation",
        ]:
            self.assertIn(runbook_id, catalog_ids)
        self.assertIn("migration_blocked", runbook_ids)
        self.assertIn("approval_stale", runbook_ids)
        self.assertIn("checkpoint_stale", runbook_ids)
        self.assertIn("tool_call_uncertain", runbook_ids)
        self.assertIn("backend_capability_degraded", runbook_ids)
        self.assertIn("context_linkage_repair", runbook_ids)
        self.assertIn("root_cause_rule_missing", runbook_ids)
        self.assertIn("memory_evidence_ref_violation", runbook_ids)
        self.assertNotIn(None, alert_runbook_ids)
        self.assertTrue(alert_runbook_ids.issubset(catalog_ids))
        for runbook_id in ("tool_call_uncertain", "backend_capability_degraded"):
            recommendation = next(
                item
                for item in diagnosis["recommendations"]
                if item["runbook_id"] == runbook_id
            )
            execution_context = recommendation["details"]["execution_context"]
            self.assertEqual(execution_context["execution_context_hash"], "safe-execution-context-hash")
            self.assertEqual(execution_context["tool_status"], "uncertain")
            self.assertEqual(execution_context["execution_phase"], "completed")
            self.assertEqual(execution_context["effect_submission_state"], "transport_sent_observed")
            self.assertEqual(execution_context["backend_effect_capability"], "legacy_reconcile_only")
            self.assertEqual(
                execution_context["recovery_decision"],
                "reconcile_required_after_eventstore_failure",
            )
            self.assertEqual(execution_context["error_code"], "eventstore_write_failed_after_effect")
            self.assertEqual(execution_context["error_message_hash"], "safe-error-message-hash")
            self.assertEqual(execution_context["worker_id"], "worker-runbook-context")
            self.assertEqual(execution_context["runtime_snapshot_id"], call.runtime_snapshot_id)
            self.assertNotIn("input_json_redacted", execution_context)
            self.assertNotIn("output_json_redacted", execution_context)
            self.assertNotIn("evidence_refs_json", execution_context)
        memory_recommendation = next(
            item
            for item in diagnosis["recommendations"]
            if item["runbook_id"] == "memory_evidence_ref_violation"
        )
        self.assertEqual(memory_recommendation["severity"], "P0")

    def test_runbook_diagnosis_surfaces_runtime_loop_repair_observations(self):
        run = self._create_run("runtime loop repair runbook")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": "evidence-runtime-runbook",
                        "ref_type": "execution_record",
                        "ref_id": "execution-runtime-runbook-1",
                        "mutability_class": "immutable",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
                required_evidence_ref_ids=["evidence-runtime-runbook"],
            ),
            current_user=self.owner,
        )
        runtime_reasons = [
            "tool_prerequisite_missing",
            "tool_request_format_invalid",
            "required_tool_followup_missing",
            "max_iterations",
            "same_failure_no_progress",
        ]
        for step_index, reason in enumerate(runtime_reasons):
            LoopController(self.db).record_observation(
                run_id=run.run_id,
                payload=AgentLoopObservationCreateRequest(
                    decision_context_build_id=build.context_build_id,
                    next_action="stop" if reason in {"max_iterations", "same_failure_no_progress"} else "repair",
                    next_action_is_high_risk=False,
                    reasons=[reason],
                    observation={"source": "runtime_loop_repair_runbook_test", "reason": reason},
                    step_index=step_index,
                ),
                current_user=self.owner,
            )

        diagnosis = AgentRunbookService(self.db).diagnose_run(run_id=run.run_id, current_user=self.owner)
        recommendations = [
            item
            for item in diagnosis["recommendations"]
            if item["runbook_id"] == "agent_runtime_loop_repair"
        ]
        details_by_reason = {
            item["details"]["stop_action_reason"]: item["details"]
            for item in recommendations
        }

        self.assertEqual(set(details_by_reason), set(runtime_reasons))
        for reason, details in details_by_reason.items():
            self.assertEqual(details["stop_reasons_all"], [reason])
            self.assertIn(details["root_cause_rule_id"], {
                "RC_TOOL_PREREQUISITE_MISSING",
                "RC_TOOL_REQUEST_FORMAT_INVALID",
                "RC_REQUIRED_TOOL_FOLLOWUP_MISSING",
                "RC_MAX_ITERATIONS",
                "RC_NO_PROGRESS_PURE",
            })
            self.assertIn("mitigation_action", details)
            self.assertTrue(details["observation_id"].startswith("agent-obs-"))
        self.assertTrue(all(item["severity"] == "P2" for item in recommendations))
        self.assertTrue(all(
            item["reason"] == "runtime_loop_repair_or_stop_observed"
            for item in recommendations
        ))
        self.assertTrue(all(
            item["action"] == "GET /api/v1/agents/runs/{run_id}/loop-observations"
            for item in recommendations
        ))

    def test_harness_required_runbook_catalog_matches_architecture_contract(self):
        from pathlib import Path
        import re

        from app.services.agent_observability_service import ALERT_RULES, REQUIRED_RUNBOOKS
        from app.services.agent_runbook_service import RUNBOOKS

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        architecture_text = next(
            path.read_text(encoding="utf-8")
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required catalog 覆盖所有 P0/P1 alert rule" in path.read_text(encoding="utf-8")
        )
        paragraph = architecture_text[
            architecture_text.index("`runbook_catalog_complete` 必须输出"):
            architecture_text.index("`AgentRunbookService.diagnose_run` 不得只诊断")
        ]
        documented_runbooks = set(re.findall(r"`([a-z0-9_]+)`", paragraph))
        documented_runbooks -= {
            "runbook_catalog_complete",
            "covered_required_runbook_ids",
            "missing_required_runbook_ids",
            "runbook_id",
            "safe_api_actions",
        }
        p0_p1_alert_runbooks = {
            rule["runbook_id"]
            for rule in ALERT_RULES
            if rule["severity"] in {"P0", "P1"}
        }
        catalog = AgentRunbookService(self.db).list_runbooks()
        catalog_ids = {item["runbook_id"] for item in catalog}
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        runbook_check = {
            item["name"]: item
            for item in dashboard["checks"]
        }["runbook_catalog_complete"]

        self.assertEqual(documented_runbooks, REQUIRED_RUNBOOKS)
        self.assertEqual(set(RUNBOOKS), REQUIRED_RUNBOOKS)
        self.assertEqual(catalog_ids, REQUIRED_RUNBOOKS)
        self.assertTrue(p0_p1_alert_runbooks.issubset(REQUIRED_RUNBOOKS))
        self.assertEqual(
            set(runbook_check["details"]["covered_required_runbook_ids"]),
            REQUIRED_RUNBOOKS,
        )
        self.assertEqual(runbook_check["details"]["missing_required_runbook_ids"], [])
        self.assertEqual(set(dashboard["runbooks"]["covered_required_runbook_ids"]), REQUIRED_RUNBOOKS)
        self.assertEqual(dashboard["runbooks"]["missing_required_runbook_ids"], [])

    def test_runbook_safe_api_actions_match_openapi_contract(self):
        from app.main import create_app
        from app.services.agent_runbook_service import RUNBOOKS

        openapi_routes = {
            (method.lower(), path)
            for path, methods in create_app().openapi()["paths"].items()
            if path.startswith("/api/v1/agents")
            for method in methods
        }
        runbook_actions = {
            (parts[0].lower(), parts[1])
            for runbook in RUNBOOKS.values()
            for action in runbook["safe_api_actions"]
            for parts in [action.split()]
        }

        self.assertTrue(runbook_actions)
        self.assertEqual(runbook_actions - openapi_routes, set())
        for method, route in runbook_actions:
            self.assertTrue(route.startswith("/api/v1/agents"), route)
            self.assertIn(method, {"get", "post", "patch", "put", "delete"})

    def test_harness_runbook_diagnosis_contract_matches_schema_and_actions(self):
        from pathlib import Path

        from app.api.v1.routers.agents import diagnose_agent_runbook, list_agent_runbooks
        from app.main import create_app
        from app.services.agent_runbook_service import RUNBOOKS

        def _split_csv(value: str) -> set[str]:
            return {item.strip() for item in value.split(",") if item.strip()}

        def _parse_contract(text: str) -> dict[str, object]:
            section = text[text.index("Required Runbook diagnosis contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            parsed: dict[str, object] = {}
            for line in block.splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                if key == "checkpoint_freshness_safe_actions":
                    parsed[key] = {
                        action_key.strip(): action_value.strip()
                        for item in value.split(",")
                        for action_key, action_value in [item.split(":", 1)]
                    }
                elif key in {"runbook_fields", "diagnosis_fields", "recommendation_fields"}:
                    parsed[key] = [item.strip() for item in value.split(",") if item.strip()]
                elif key.endswith("_fields") or key == "recommendation_runbook_ids":
                    parsed[key] = _split_csv(value)
                else:
                    parsed[key] = value
            return parsed

        expected_contract = {
            "runbook_fields": list(RUNBOOK_FIELDS),
            "diagnosis_fields": list(RUNBOOK_DIAGNOSIS_FIELDS),
            "recommendation_fields": list(RUNBOOK_RECOMMENDATION_FIELDS),
            "recommendation_required_fields": RUNBOOK_RECOMMENDATION_REQUIRED_FIELDS,
            "recommendation_optional_fields": RUNBOOK_RECOMMENDATION_OPTIONAL_FIELDS,
            "recommendation_runbook_ids": RUNBOOK_DIAGNOSIS_RECOMMENDATION_RUNBOOK_IDS,
            "recommendation_action_contract": "openapi_agent_route",
            "recommendation_severity_source": "runbook_catalog",
            "checkpoint_freshness_safe_actions": CHECKPOINT_FRESHNESS_SAFE_ACTIONS,
        }
        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            _parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Runbook diagnosis contract:" in path.read_text(encoding="utf-8")
        ]
        run = self._create_run("runbook diagnosis contract")
        checkpoint = self.db.get(AgentCheckpoint, run.last_checkpoint_id)
        checkpoint.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=5)
        self.db.commit()

        diagnosis = AgentRunbookService(self.db).diagnose_run(
            run_id=run.run_id,
            current_user=self.owner,
        )
        catalog_route_payload = list_agent_runbooks(db=self.db, current_user=self.owner)["data"]
        diagnosis_route_payload = diagnose_agent_runbook(
            run_id=run.run_id,
            db=self.db,
            current_user=self.owner,
        )["data"]
        checkpoint_recommendation = next(
            item
            for item in diagnosis["recommendations"]
            if item["runbook_id"] == "checkpoint_stale"
        )
        openapi_routes = {
            (method.lower(), path)
            for path, methods in create_app().openapi()["paths"].items()
            if path.startswith("/api/v1/agents")
            for method in methods
        }

        self.assertEqual(len(documented_contracts), 2)
        for contract in documented_contracts:
            self.assertEqual(contract, expected_contract)
        self.assertEqual(list(AgentRunbookRead.model_fields), list(RUNBOOK_FIELDS))
        self.assertEqual(list(AgentRunbookDiagnosisRead.model_fields), list(RUNBOOK_DIAGNOSIS_FIELDS))
        self.assertEqual(
            list(AgentRunbookRecommendationRead.model_fields),
            list(RUNBOOK_RECOMMENDATION_FIELDS),
        )
        self.assertEqual(list(diagnosis), list(RUNBOOK_DIAGNOSIS_FIELDS))
        self.assertEqual(list(diagnosis_route_payload), list(RUNBOOK_DIAGNOSIS_FIELDS))
        self.assertTrue(all(list(item) == list(RUNBOOK_FIELDS) for item in diagnosis["runbooks"]))
        self.assertTrue(all(list(item) == list(RUNBOOK_FIELDS) for item in catalog_route_payload))
        self.assertTrue(all(list(item) == list(RUNBOOK_FIELDS) for item in diagnosis_route_payload["runbooks"]))
        self.assertTrue(all(list(item) == list(RUNBOOK_RECOMMENDATION_FIELDS) for item in diagnosis["recommendations"]))
        self.assertTrue(
            all(list(item) == list(RUNBOOK_RECOMMENDATION_FIELDS) for item in diagnosis_route_payload["recommendations"])
        )
        self.assertEqual(checkpoint_recommendation["action"], "POST /api/v1/agents/runs/{run_id}/context-builds")
        self.assertEqual(checkpoint_recommendation["details"]["action"], "replan_from_latest_safe_state")
        for recommendation in diagnosis["recommendations"]:
            recommendation_keys = set(recommendation)
            self.assertTrue(RUNBOOK_RECOMMENDATION_REQUIRED_FIELDS.issubset(recommendation_keys))
            self.assertTrue(
                recommendation_keys.issubset(
                    RUNBOOK_RECOMMENDATION_REQUIRED_FIELDS | RUNBOOK_RECOMMENDATION_OPTIONAL_FIELDS
                )
            )
            self.assertIn(recommendation["runbook_id"], RUNBOOK_DIAGNOSIS_RECOMMENDATION_RUNBOOK_IDS)
            self.assertEqual(recommendation["severity"], RUNBOOKS[recommendation["runbook_id"]]["severity"])
            self.assertIn(recommendation["action"], RUNBOOKS[recommendation["runbook_id"]]["safe_api_actions"])
            method, route = recommendation["action"].split()
            self.assertIn((method.lower(), route), openapi_routes)

    def test_runbook_diagnosis_includes_release_gate_violations(self):
        from app.services.agent_tool_service import ToolRegistry, ToolSpec

        run = self._create_run("runbook release gate violation")
        base_specs = ToolRegistry().list_specs()
        blocked_spec = ToolSpec(
            name="project.create_business_record",
            version="1.0.0",
            summary="Business create operation intentionally beyond L2 rollout.",
            side_effect_class="business_create",
            replay_policy="require_revalidation",
            required_permissions=(),
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        )

        with patch.object(ToolRegistry, "list_specs", return_value=[*base_specs, blocked_spec]):
            diagnosis = AgentRunbookService(self.db).diagnose_run(
                run_id=run.run_id,
                current_user=self.owner,
            )

        recommendation = next(
            item
            for item in diagnosis["recommendations"]
            if item["runbook_id"] == "release_gate_violation"
        )

        self.assertEqual(recommendation["severity"], "P0")
        self.assertEqual(recommendation["reason"], "current_tool_matrix_has_rollout_violations")
        self.assertEqual(recommendation["details"]["current_level"], "L2")
        self.assertEqual(recommendation["details"]["violation_count"], 1)
        self.assertEqual(
            recommendation["details"]["violations"][0]["tool_name"],
            "project.create_business_record",
        )

    def test_resume_run_continues_when_checkpoint_is_fresh(self):
        run = self._create_run("resume fresh")
        run.status = "paused"
        self.db.commit()

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)
        events = [item.event_type for item in self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all()]

        self.assertTrue(result["resumed"])
        self.assertEqual(result["run"].status, "running")
        self.assertEqual(result["checkpoint_freshness"]["action"], "continue_from_checkpoint")
        self.assertIn("run.resumed", events)

    def test_resume_run_executes_approved_blocking_tool_and_completes_conversation(self):
        run, call, approval = self._create_pending_approval()
        call.resolved_side_effect_class = "read_only"
        run.status = "needs_human"
        run.blocking_tool_call_ids_json = [call.tool_call_id]
        self.db.commit()
        ApprovalService(self.db).approve(
            tool_call_id=call.tool_call_id,
            payload=self._approval_decision(approval),
            current_user=self.owner,
        )

        captured_messages = []

        def fake_stream(self, payload):
            captured_messages.extend(payload.messages)
            yield {"type": "delta", "content": "审批后的项目上下文已读取，可以继续执行测试规划。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch(
                "app.services.agent_runtime_service.AgentToolBackend.execute",
                return_value={"project": {"id": 10, "name": "TestAuto"}},
            ),
        ):
            result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)

        refreshed_call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == call.tool_call_id))
        queue_item = self.db.scalar(select(AgentWorkerQueue).where(AgentWorkerQueue.tool_call_id == call.tool_call_id))
        events = [
            item.event_type
            for item in self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        ]

        self.assertTrue(result["resumed"])
        self.assertEqual(result["run"].status, "completed")
        self.assertEqual(result["run"].result_json["message"], "审批后的项目上下文已读取，可以继续执行测试规划。")
        self.assertEqual(result["executed_tool_call_ids"], [call.tool_call_id])
        self.assertEqual(refreshed_call.status, "succeeded")
        self.assertEqual(queue_item.status, "completed")
        self.assertEqual(self.db.get(AgentRun, run.id).blocking_tool_call_ids_json, [])
        self.assertIn("tool.result_observed", events)
        self.assertIn("run.resumed", events)
        self.assertIn("model.delta", events)
        self.assertIn("run.completed", events)
        self.assertIn("工具执行结果如下", captured_messages[-2].content)
        self.assertEqual(captured_messages[-1].content, "以上工具已完成审批和执行。请基于这些工具结果给用户最终回复，不要再请求工具。")

    def test_resume_run_blocks_when_migration_block_open(self):
        run, _, _ = self._create_migration_block()

        with self.assertRaises(HTTPException) as ctx:
            AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "run_migration_blocked")

    def test_resume_run_pauses_when_evidence_is_stale(self):
        run = self._create_run("resume stale")
        ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[
                    {
                        "evidence_ref_id": "scenario-current",
                        "ref_type": "scenario",
                        "ref_id": "scenario-1",
                        "mutability_class": "mutable_current",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
            ),
            current_user=self.owner,
        )
        EvidenceWatchService(self.db).mark_stale_by_ref(
            ref_type="scenario",
            ref_id="scenario-1",
            stale_reason="scenario.updated",
        )

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)

        self.assertFalse(result["resumed"])
        self.assertEqual(result["run"].status, "paused")
        self.assertEqual(result["run"].error_code, "fetch_evidence_and_rebuild_context")
        self.assertEqual(result["checkpoint_freshness"]["result"], "evidence_stale")
        self.assertEqual(result["checkpoint_freshness"]["action"], "fetch_evidence_and_rebuild_context")
        self.assertEqual(result["checkpoint_freshness"]["reason"], "stale_evidence_watch")
        self.assertEqual(result["checkpoint_freshness"]["stale_evidence_watch_count"], 1)
        self.assertEqual(result["checkpoint_freshness"]["environment_changed_count"], 0)
        self.assertEqual(
            result["checkpoint_freshness"]["stale_evidence_watch_details"][0]["evidence_ref_id"],
            "scenario-current",
        )
        self.assertEqual(result["checkpoint_freshness"]["stale_evidence_watch_details"][0]["ref_type"], "scenario")
        self.assertEqual(result["checkpoint_freshness"]["stale_evidence_watch_details"][0]["ref_id"], "scenario-1")
        self.assertEqual(
            result["checkpoint_freshness"]["stale_evidence_watch_details"][0]["stale_reason"],
            "scenario.updated",
        )

    def test_resume_run_revalidates_when_environment_evidence_changed(self):
        run = self._create_run("resume environment changed")
        ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[
                    {
                        "evidence_ref_id": "environment-current",
                        "ref_type": "environment",
                        "ref_id": "environment-20",
                        "mutability_class": "mutable_current",
                        "freshness_policy": "revalidate_before_side_effect",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
            ),
            current_user=self.owner,
        )
        EvidenceWatchService(self.db).mark_stale_by_ref(
            ref_type="environment",
            ref_id="environment-20",
            stale_reason="environment.updated",
        )

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)
        AgentOutboxPublisher(self.db, publisher=lambda event: None).publish_pending(limit=100)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        alerts = {item["alert_id"]: item for item in alert_snapshot["alerts"]}
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertFalse(result["resumed"])
        self.assertEqual(result["run"].status, "paused")
        self.assertEqual(result["checkpoint_freshness"]["result"], "environment_changed")
        self.assertEqual(result["checkpoint_freshness"]["action"], "revalidate_before_side_effect")
        self.assertEqual(result["checkpoint_freshness"]["reason"], "environment_updated")
        self.assertEqual(result["checkpoint_freshness"]["environment_changed_count"], 1)
        self.assertEqual(result["checkpoint_freshness"]["stale_evidence_watch_details"][0]["ref_type"], "environment")
        self.assertEqual(metrics["checkpoint_freshness_failed_total"], 1)
        self.assertIn("agent_checkpoint_freshness_failed", alerts)
        self.assertEqual(alerts["agent_checkpoint_freshness_failed"]["severity"], "P1")
        self.assertEqual(alerts["agent_checkpoint_freshness_failed"]["runbook_id"], "checkpoint_stale")
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P1")
        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "attention")

    def test_resume_run_materializes_ephemeral_latest_policy_evidence(self):
        run = self._create_run("resume latest evidence")
        ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[
                    {
                        "evidence_ref_id": "latest-execution-sample",
                        "ref_type": "latest_execution_sample",
                        "ref_id": "latest",
                        "mutability_class": "immutable",
                        "dependency_role": "validation_evidence",
                        "active_for_policy": True,
                    },
                    {
                        "evidence_ref_id": "ephemeral-latest-policy-ref",
                        "ref_type": "execution_record",
                        "ref_id": "execution-latest-placeholder",
                        "mutability_class": "ephemeral_latest",
                        "dependency_role": "validation_evidence",
                        "active_for_policy": True,
                    }
                ],
            ),
            current_user=self.owner,
        )

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertFalse(result["resumed"])
        self.assertEqual(result["run"].status, "paused")
        self.assertEqual(result["checkpoint_freshness"]["result"], "evidence_stale")
        self.assertEqual(result["checkpoint_freshness"]["action"], "materialize_latest_evidence")
        self.assertEqual(result["checkpoint_freshness"]["reason"], "ephemeral_latest_requires_materialization")
        self.assertEqual(result["checkpoint_freshness"]["active_evidence_revalidation_count"], 2)
        details_by_id = {
            item["evidence_ref_id"]: item
            for item in result["checkpoint_freshness"]["active_evidence_revalidation_details"]
        }
        self.assertEqual(set(details_by_id), {"latest-execution-sample", "ephemeral-latest-policy-ref"})
        self.assertEqual(details_by_id["latest-execution-sample"]["ref_type"], "latest_execution_sample")
        self.assertEqual(details_by_id["ephemeral-latest-policy-ref"]["mutability_class"], "ephemeral_latest")
        self.assertEqual(metrics["checkpoint_freshness_failed_total"], 1)

    def test_resume_run_revalidates_external_uncontrolled_policy_evidence(self):
        run = self._create_run("resume external evidence")
        ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[
                    {
                        "evidence_ref_id": "revalidate-policy-current",
                        "ref_type": "system_record",
                        "ref_id": "policy-source-1",
                        "mutability_class": "immutable",
                        "freshness_policy": "revalidate_on_resume",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    },
                    {
                        "evidence_ref_id": "external-uncontrolled-current",
                        "ref_type": "document",
                        "ref_id": "doc-current",
                        "mutability_class": "external_uncontrolled",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    },
                    {
                        "evidence_ref_id": "external-doc-current",
                        "ref_type": "external_doc",
                        "ref_id": "https://example.test/spec",
                        "mutability_class": "immutable",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    },
                ],
            ),
            current_user=self.owner,
        )

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertFalse(result["resumed"])
        self.assertEqual(result["run"].status, "paused")
        self.assertEqual(result["checkpoint_freshness"]["result"], "evidence_stale")
        self.assertEqual(result["checkpoint_freshness"]["action"], "fetch_evidence_and_rebuild_context")
        self.assertEqual(result["checkpoint_freshness"]["reason"], "active_evidence_requires_revalidation")
        self.assertEqual(result["checkpoint_freshness"]["active_evidence_revalidation_count"], 3)
        details_by_id = {
            item["evidence_ref_id"]: item
            for item in result["checkpoint_freshness"]["active_evidence_revalidation_details"]
        }
        self.assertEqual(set(details_by_id), {
            "revalidate-policy-current",
            "external-uncontrolled-current",
            "external-doc-current",
        })
        self.assertEqual(details_by_id["revalidate-policy-current"]["freshness_policy"], "revalidate_on_resume")
        self.assertEqual(details_by_id["external-uncontrolled-current"]["mutability_class"], "external_uncontrolled")
        self.assertEqual(details_by_id["external-doc-current"]["ref_type"], "external_doc")
        self.assertEqual(metrics["checkpoint_freshness_failed_total"], 1)

    def test_harness_evidence_freshness_contract_matches_gate(self):
        from pathlib import Path

        def _parse_contract(text: str) -> dict[str, object]:
            section = text[text.index("Required evidence freshness contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            parsed: dict[str, object] = {}
            list_keys = {
                "environment_fields",
                "environment_detail_fields",
                "active_evidence_fields",
                "active_evidence_detail_fields",
                "active_evidence_actions",
                "active_evidence_reasons",
            }
            for line in block.splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                if key in list_keys:
                    parsed[key] = [item.strip() for item in value.split(",") if item.strip()]
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            _parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required evidence freshness contract:" in path.read_text(encoding="utf-8")
        ]
        expected_contract = {
            "environment_fields": list(ENVIRONMENT_FRESHNESS_FIELDS),
            "environment_detail_fields": list(STALE_EVIDENCE_WATCH_DETAIL_FIELDS),
            "environment_result": ENVIRONMENT_FRESHNESS_RESULT,
            "environment_action": ENVIRONMENT_FRESHNESS_ACTION,
            "environment_reason": ENVIRONMENT_FRESHNESS_REASON,
            "active_evidence_fields": list(ACTIVE_EVIDENCE_REVALIDATION_FIELDS),
            "active_evidence_detail_fields": list(ACTIVE_EVIDENCE_REVALIDATION_DETAIL_FIELDS),
            "active_evidence_result": ACTIVE_EVIDENCE_REVALIDATION_RESULT,
            "active_evidence_actions": list(ACTIVE_EVIDENCE_REVALIDATION_ACTIONS),
            "active_evidence_reasons": list(ACTIVE_EVIDENCE_REVALIDATION_REASONS),
        }

        environment_run = self._create_run("evidence freshness environment contract")
        ContextBuilder(self.db).build(
            run_id=environment_run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[
                    {
                        "evidence_ref_id": "environment-contract",
                        "ref_type": "environment",
                        "ref_id": "environment-contract",
                        "mutability_class": "mutable_current",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
            ),
            current_user=self.owner,
        )
        EvidenceWatchService(self.db).mark_stale_by_ref(
            ref_type="environment",
            ref_id="environment-contract",
            stale_reason="environment.updated",
        )

        latest_run = self._create_run("evidence freshness latest contract")
        ContextBuilder(self.db).build(
            run_id=latest_run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[
                    {
                        "evidence_ref_id": "latest-contract",
                        "ref_type": "latest_execution_sample",
                        "ref_id": "latest",
                        "mutability_class": "immutable",
                        "dependency_role": "validation_evidence",
                        "active_for_policy": True,
                    }
                ],
            ),
            current_user=self.owner,
        )

        external_run = self._create_run("evidence freshness external contract")
        ContextBuilder(self.db).build(
            run_id=external_run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[
                    {
                        "evidence_ref_id": "external-contract",
                        "ref_type": "external_doc",
                        "ref_id": "https://example.test/spec",
                        "mutability_class": "immutable",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
            ),
            current_user=self.owner,
        )

        environment = CheckpointFreshnessGate(self.db).evaluate(run=environment_run)
        latest = CheckpointFreshnessGate(self.db).evaluate(run=latest_run)
        external = CheckpointFreshnessGate(self.db).evaluate(run=external_run)

        self.assertEqual(len(documented_contracts), 2)
        for documented in documented_contracts:
            self.assertEqual(documented, expected_contract)
        self.assertEqual(environment["result"], ENVIRONMENT_FRESHNESS_RESULT)
        self.assertEqual(environment["action"], ENVIRONMENT_FRESHNESS_ACTION)
        self.assertEqual(environment["reason"], ENVIRONMENT_FRESHNESS_REASON)
        self.assertTrue(set(ENVIRONMENT_FRESHNESS_FIELDS).issubset(environment))
        self.assertTrue(
            set(STALE_EVIDENCE_WATCH_DETAIL_FIELDS).issubset(environment["stale_evidence_watch_details"][0])
        )
        for freshness in (latest, external):
            self.assertEqual(freshness["result"], ACTIVE_EVIDENCE_REVALIDATION_RESULT)
            self.assertTrue(set(ACTIVE_EVIDENCE_REVALIDATION_FIELDS).issubset(freshness))
            self.assertTrue(
                set(ACTIVE_EVIDENCE_REVALIDATION_DETAIL_FIELDS).issubset(
                    freshness["active_evidence_revalidation_details"][0]
                )
            )
            self.assertIn(freshness["action"], ACTIVE_EVIDENCE_REVALIDATION_ACTIONS)
            self.assertIn(freshness["reason"], ACTIVE_EVIDENCE_REVALIDATION_REASONS)
        self.assertEqual(latest["action"], ACTIVE_EVIDENCE_REVALIDATION_ACTIONS[0])
        self.assertEqual(latest["reason"], ACTIVE_EVIDENCE_REVALIDATION_REASONS[0])
        self.assertEqual(external["action"], ACTIVE_EVIDENCE_REVALIDATION_ACTIONS[1])
        self.assertEqual(external["reason"], ACTIVE_EVIDENCE_REVALIDATION_REASONS[1])

    def test_resume_run_ignores_audit_only_latest_evidence_in_policy_metadata(self):
        run = self._create_run("resume audit latest evidence")
        audit_latest_ref = {
            "evidence_ref_id": "audit-latest-sample",
            "ref_type": "latest_execution_sample",
            "ref_id": "latest",
            "mutability_class": "ephemeral_latest",
            "dependency_role": "audit_background",
            "active_for_policy": False,
        }
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[audit_latest_ref],
            ),
            current_user=self.owner,
        )
        build.build_metadata_json = {"policy_refs": [audit_latest_ref]}
        run.status = "paused"
        self.db.commit()

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)

        self.assertTrue(result["resumed"])
        self.assertEqual(result["run"].status, "running")
        self.assertEqual(result["checkpoint_freshness"]["result"], "fresh")
        self.assertEqual(result["checkpoint_freshness"]["active_evidence_revalidation_count"], 0)
        self.assertEqual(result["checkpoint_freshness"]["active_evidence_revalidation_details"], [])

    def test_resume_run_pauses_when_active_memory_needs_revalidation(self):
        run = self._create_run("resume stale memory")
        manager = MemoryManager(self.db)
        memory = manager.create_memory(
            project_id=10,
            memory_type="project_rule",
            title="MFA repair hint",
            content="Login repair should preserve MFA validation.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        memory_ref = MemoryEvidenceAdapter().to_evidence_ref(memory=memory, usage_role="policy_dependency")
        ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[memory_ref],
                memory_ids_used=[memory.id],
            ),
            current_user=self.owner,
        )
        memory.status = "needs_revalidation"
        memory.stale_score = 0.85
        run.status = "paused"
        self.db.commit()

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertFalse(result["resumed"])
        self.assertEqual(result["run"].status, "paused")
        self.assertEqual(result["checkpoint_freshness"]["result"], "evidence_stale")
        self.assertEqual(result["checkpoint_freshness"]["reason"], "active_memory_needs_revalidation")
        self.assertEqual(result["checkpoint_freshness"]["active_memory_needs_revalidation_ids"], [memory.id])
        self.assertEqual(metrics["checkpoint_freshness_failed_total"], 1)

    def test_resume_run_ignores_audit_only_memory_needing_revalidation(self):
        run = self._create_run("resume audit memory")
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Audit-only repair hint",
            content="This stale memory explains history but should not drive policy.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        audit_ref = MemoryEvidenceAdapter().to_evidence_ref(memory=memory, usage_role="repair_hint")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[audit_ref],
            ),
            current_user=self.owner,
        )
        build.build_metadata_json = {"policy_refs": [audit_ref]}
        memory.status = "needs_revalidation"
        memory.stale_score = 0.85
        run.status = "paused"
        self.db.commit()

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)

        self.assertTrue(result["resumed"])
        self.assertEqual(result["run"].status, "running")
        self.assertEqual(result["checkpoint_freshness"]["result"], "fresh")
        self.assertEqual(result["checkpoint_freshness"]["active_memory_needs_revalidation_count"], 0)
        self.assertEqual(result["checkpoint_freshness"]["active_memory_needs_revalidation_ids"], [])

    def test_resume_run_requeues_failed_retryable_tool_call(self):
        run = self._create_run("resume retryable")
        call = self._create_uncertain_call(run.run_id, step_index=0, effect_state="send_intent_recorded")
        call.status = "failed_retryable"
        run.status = "paused"
        self.db.commit()

        result = AgentRunResumeService(self.db).resume_run(run_id=run.run_id, current_user=self.owner)
        queue_item = self.db.scalar(select(AgentWorkerQueue).where(AgentWorkerQueue.tool_call_id == call.tool_call_id))
        refreshed_call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == call.tool_call_id))

        self.assertTrue(result["resumed"])
        self.assertEqual(result["scheduled_tool_call_ids"], [call.tool_call_id])
        self.assertEqual(queue_item.status, "queued")
        self.assertEqual(refreshed_call.status, "planned")

    def test_backend_contracts_can_be_seeded_and_queried_by_operation(self):
        AgentRuntimeService(self.db).ensure_backend_contracts()

        contract = self.db.scalar(select(AgentBackendContract).where(
            AgentBackendContract.backend_name == "project-service",
            AgentBackendContract.backend_operation == "read_context",
            AgentBackendContract.backend_contract_version == "v1",
        ))

        self.assertIsNotNone(contract)
        self.assertEqual(contract.effect_capability, "idempotency_index_only")
        operations = {
            item.backend_operation
            for item in self.db.scalars(select(AgentBackendContract)).all()
        }
        self.assertIn("run_draft", operations)
        self.assertIn("execute_dry_run", operations)

    def test_backend_contract_route_requires_admin(self):
        from app.api.v1.routers.agents import get_agent_backend_contract

        with self.assertRaises(HTTPException) as owner_ctx:
            get_agent_backend_contract(
                backend_name="project-service",
                backend_operation="read_context",
                db=self.db,
                current_user=self.owner,
            )

        admin_response = get_agent_backend_contract(
            backend_name="project-service",
            backend_operation="read_context",
            db=self.db,
            current_user=self.admin,
        )

        self.assertEqual(owner_ctx.exception.status_code, 403)
        self.assertEqual(admin_response["data"]["backend_name"], "project-service")
        self.assertEqual(admin_response["data"]["backend_operation"], "read_context")
        self.assertEqual(admin_response["data"]["effect_capability"], "idempotency_index_only")

    def test_reconcile_conflict_goes_to_manual_intervention(self):
        run = self._create_run("conflict")
        call = self._create_uncertain_call(run.run_id, step_index=0)
        result = ReconcileResult(
            found=True,
            status="conflict",
            backend_contract_version="v1",
            error_code="idempotency_conflict",
        )

        summary = ReconcileWorker(self.db, router=StaticReconcileRouter(result)).reconcile_run(
            run_id=run.run_id,
            current_user=self.owner,
        )
        refreshed = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == call.tool_call_id))

        self.assertEqual(summary["manual_intervention"], 1)
        self.assertEqual(refreshed.status, "manual_intervention")
        self.assertEqual(refreshed.recovery_decision, "idempotency_conflict")
        AgentOutboxPublisher(self.db, publisher=lambda event: None).publish_pending(limit=100)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        alerts = {item["alert_id"]: item for item in alert_snapshot["alerts"]}
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertEqual(metrics["tool_call_reconcile_manual_total"], 1)
        self.assertIn("agent_reconcile_manual_intervention", alerts)
        self.assertEqual(alerts["agent_reconcile_manual_intervention"]["severity"], "P1")
        self.assertEqual(alerts["agent_reconcile_manual_intervention"]["runbook_id"], "tool_call_uncertain")
        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "attention")

    def test_reconcile_running_and_failed_record_attempts(self):
        run = self._create_run("running failed")
        running = self._create_uncertain_call(run.run_id, step_index=0)
        failed = self._create_uncertain_call(run.run_id, step_index=1)
        router = MappingReconcileRouter({
            running.tool_call_id: ReconcileResult(
                found=True,
                status="running",
                backend_contract_version="v1",
            ),
            failed.tool_call_id: ReconcileResult(
                found=True,
                status="failed",
                backend_contract_version="v1",
                error_code="backend_failed",
                error_message="downstream failed",
            ),
        })

        summary = ReconcileWorker(self.db, router=router).reconcile_run(
            run_id=run.run_id,
            current_user=self.owner,
        )
        attempts = list(self.db.scalars(select(AgentReconcileAttempt).order_by(
            AgentReconcileAttempt.tool_call_id,
            AgentReconcileAttempt.attempt_seq,
        )).all())
        refreshed = {
            item.tool_call_id: item
            for item in self.db.scalars(select(AgentToolCall).where(AgentToolCall.run_id == run.run_id)).all()
        }

        self.assertEqual(summary["processed"], 2)
        self.assertEqual(refreshed[running.tool_call_id].status, "reconciling")
        self.assertEqual(refreshed[running.tool_call_id].recovery_decision, "still_running")
        self.assertEqual(refreshed[failed.tool_call_id].status, "failed")
        self.assertEqual(refreshed[failed.tool_call_id].error_code, "backend_failed")
        self.assertEqual(sorted(item.result_status for item in attempts), ["failed", "running"])

    def test_legacy_no_receipt_high_risk_cannot_auto_reconcile(self):
        run = self._create_run("legacy no receipt")
        call = self._create_uncertain_call(run.run_id, step_index=0)
        call.resolved_side_effect_class = "business_create"
        call.backend_effect_capability = "legacy_no_receipt"
        self.db.commit()

        summary = ReconcileWorker(self.db, router=RaisingReconcileRouter()).reconcile_run(
            run_id=run.run_id,
            current_user=self.owner,
        )
        refreshed = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == call.tool_call_id))

        self.assertEqual(summary["manual_intervention"], 1)
        self.assertEqual(refreshed.status, "manual_intervention")
        self.assertEqual(refreshed.recovery_decision, "legacy_no_receipt_high_risk_manual")
        self.assertEqual(refreshed.error_code, "backend_reconcile_not_supported")
        self.assertEqual(self.db.query(AgentReconcileAttempt).count(), 0)
        AgentOutboxPublisher(self.db, publisher=lambda event: None).publish_pending(limit=100)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        alerts = {item["alert_id"]: item for item in alert_snapshot["alerts"]}
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks = {item["name"]: item for item in dashboard["checks"]}
        self.assertEqual(metrics["backend_effect_capability_legacy_no_receipt_total"], 1)
        self.assertEqual(metrics["tool_call_legacy_no_receipt_manual_total"], 1)
        self.assertIn("agent_legacy_no_receipt_manual_intervention", alerts)
        self.assertEqual(alerts["agent_legacy_no_receipt_manual_intervention"]["severity"], "P0")
        self.assertEqual(
            alerts["agent_legacy_no_receipt_manual_intervention"]["runbook_id"],
            "backend_capability_degraded",
        )
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P0")
        self.assertEqual(dashboard["readiness"], "blocked")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "blocked")

    def test_worker_blocks_uncertain_or_reconciling_tool_call_until_reconcile(self):
        for call_status in ["uncertain", "reconciling"]:
            with self.subTest(call_status=call_status):
                run = self._create_run(f"{call_status} queued by mistake")
                call = self._create_uncertain_call(run.run_id, step_index=0)
                call.status = call_status
                self.db.commit()
                AgentWorkerQueueService(self.db).enqueue_tool_call(call)

                result = ToolExecutor(self.db, backend_factory=lambda db: RaisingBackend()).execute_next(
                    worker_id=f"worker-{call_status}"
                )
                refreshed = self.db.scalar(
                    select(AgentToolCall).where(AgentToolCall.tool_call_id == call.tool_call_id)
                )
                queue_item = self.db.scalar(
                    select(AgentWorkerQueue).where(AgentWorkerQueue.tool_call_id == call.tool_call_id)
                )
                events = list(self.db.scalars(
                    select(AgentEvent).where(
                        AgentEvent.run_id == run.run_id,
                        AgentEvent.event_type == "tool.failed",
                    )
                ).all())

                self.assertIsNone(result)
                self.assertEqual(refreshed.status, call_status)
                self.assertEqual(refreshed.error_code, "tool_call_uncertain_reconcile_required")
                self.assertEqual(refreshed.recovery_decision, "reconcile_required_before_execution")
                self.assertEqual(queue_item.status, "failed")
                self.assertEqual(queue_item.last_error_code, "tool_call_uncertain_reconcile_required")
                self.assertEqual(events[-1].payload_json["error_code"], "tool_call_uncertain_reconcile_required")

    def test_agent_reconcile_route_is_declared(self):
        from app.main import create_app

        paths = create_app().openapi()["paths"]

        self.assertIn("/api/v1/agents/runs/{run_id}/reconcile", paths)

    def test_create_pending_approval_persists_lineage_and_event(self):
        run, call, approval = self._create_pending_approval()
        events = [item.event_type for item in self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all()]

        self.assertTrue(call.approval_required)
        self.assertEqual(call.approval_lineage_id, approval.approval_lineage_id)
        self.assertEqual(call.approval_epoch, 1)
        self.assertEqual(approval.approval_status, "pending")
        self.assertEqual(self.db.query(AgentApprovalLineage).count(), 1)
        self.assertEqual(self.db.query(AgentApprovalMutationLog).count(), 1)
        self.assertIn("approval.created", events)

    def test_approve_success_marks_tool_executable_and_logs_mutation(self):
        run, call, approval = self._create_pending_approval()

        approved, lineage, refreshed_call, mutation = ApprovalService(self.db).approve(
            tool_call_id=call.tool_call_id,
            payload=self._approval_decision(approval),
            current_user=self.owner,
        )
        queue_item = self.db.scalar(select(AgentWorkerQueue).where(AgentWorkerQueue.tool_call_id == call.tool_call_id))
        events = [item.event_type for item in self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all()]

        self.assertEqual(approved.approval_status, "approved")
        self.assertEqual(lineage.status, "approved")
        self.assertEqual(refreshed_call.approved_approval_id, approval.approval_id)
        self.assertEqual(mutation.mutation_type, "approve")
        self.assertEqual(queue_item.status, "queued")
        self.assertIn("approval.approved", events)

    def test_supersede_with_replacement_is_atomic_and_stales_old_approval(self):
        run, old_call, old_approval = self._create_pending_approval()
        replacement_payload = AgentToolCallCreateRequest(
            run_id=run.run_id,
            tool_name="project.read_context",
            input={"project_id": 10, "replacement": True},
            step_index=old_call.step_index,
            evidence_refs=[
                {
                    "evidence_ref_id": "replacement-evidence",
                    "ref_type": "testcase",
                    "ref_id": "case-replacement",
                    "mutability_class": "versioned",
                    "version_id": "v2",
                    "dependency_role": "decision_dependency",
                    "active_for_policy": True,
                }
            ],
        )

        superseded, lineage, replacement_call, replacement_approval, supersede_mutation, create_mutation = (
            ApprovalService(self.db).supersede_with_replacement(
                tool_call_id=old_call.tool_call_id,
                replacement_payload=replacement_payload,
                current_user=self.owner,
                reason="repair replaced unsafe input",
            )
        )
        stale_payload = self._approval_decision(old_approval)
        with self.assertRaises(HTTPException) as stale_ctx:
            ApprovalService(self.db).approve(
                tool_call_id=old_call.tool_call_id,
                payload=stale_payload,
                current_user=self.owner,
            )
        self.assertEqual(replacement_approval.approval_status, "pending")

        approved, approved_lineage, approved_call, _ = ApprovalService(self.db).approve(
            tool_call_id=replacement_call.tool_call_id,
            payload=self._approval_decision(replacement_approval),
            current_user=self.owner,
        )
        events = [item.event_type for item in self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all()]
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertEqual(superseded.approval_status, "superseded")
        self.assertEqual(lineage.current_epoch, 2)
        self.assertEqual(lineage.tool_call_id, replacement_call.tool_call_id)
        self.assertEqual(replacement_approval.approval_epoch, 2)
        self.assertEqual(replacement_call.approval_lineage_id, old_call.approval_lineage_id)
        self.assertEqual(replacement_call.approval_epoch, 2)
        self.assertEqual(self.db.get(AgentToolCall, old_call.id).status, "obsolete")
        self.assertEqual(supersede_mutation.mutation_type, "supersede")
        self.assertEqual(create_mutation.mutation_type, "create_replacement")
        self.assertEqual(stale_ctx.exception.status_code, 409)
        self.assertEqual(stale_ctx.exception.detail["code"], "approval_stale_or_superseded")
        self.assertEqual(approved.approval_status, "approved")
        self.assertEqual(approved_lineage.current_epoch, 2)
        self.assertEqual(approved_call.approved_approval_id, replacement_approval.approval_id)
        self.assertIn("approval.superseded", events)
        self.assertIn("approval.created", events)
        self.assertEqual(metrics["approval_replacement_atomic_total"], 1)

    def test_reject_success_blocks_tool_call(self):
        run, call, approval = self._create_pending_approval()

        rejected, lineage, refreshed_call, mutation = ApprovalService(self.db).reject(
            tool_call_id=call.tool_call_id,
            payload=self._approval_decision(approval, reason="not acceptable"),
            current_user=self.owner,
        )

        self.assertEqual(rejected.approval_status, "rejected")
        self.assertEqual(lineage.status, "rejected")
        self.assertEqual(refreshed_call.status, "manual_intervention")
        self.assertEqual(refreshed_call.error_code, "approval_rejected")
        self.assertEqual(mutation.mutation_type, "reject")
        events = [item.event_type for item in self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all()]
        self.assertIn("approval.rejected", events)

    def test_reject_expired_pending_approval_marks_expired_and_returns_stale_409(self):
        run, call, approval = self._create_pending_approval(
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        )

        with self.assertRaises(HTTPException) as ctx:
            ApprovalService(self.db).reject(
                tool_call_id=call.tool_call_id,
                payload=self._approval_decision(approval, reason="stale client reject"),
                current_user=self.owner,
            )

        refreshed_approval = self.db.scalar(
            select(AgentApproval).where(AgentApproval.approval_id == approval.approval_id)
        )
        refreshed_call = self.db.scalar(
            select(AgentToolCall).where(AgentToolCall.tool_call_id == call.tool_call_id)
        )
        conflict_events = list(
            self.db.scalars(
                select(AgentEvent).where(
                    AgentEvent.run_id == run.run_id,
                    AgentEvent.event_type == "approval.reject_conflict",
                )
            ).all()
        )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "approval_stale_or_superseded")
        expired_event = self.db.scalar(
            select(AgentEvent).where(
                AgentEvent.run_id == run.run_id,
                AgentEvent.event_type == "approval.expired",
            )
        )
        expire_mutation = self.db.scalar(
            select(AgentApprovalMutationLog).where(
                AgentApprovalMutationLog.approval_id == approval.approval_id,
                AgentApprovalMutationLog.mutation_type == "expire",
            )
        )

        self.assertEqual(refreshed_approval.approval_status, "expired")
        self.assertEqual(refreshed_call.status, "manual_intervention")
        self.assertEqual(refreshed_call.error_code, "approval_expired")
        self.assertIsNotNone(expired_event)
        self.assertIsNotNone(expire_mutation)
        self.assertEqual(len(conflict_events), 1)
        self.assertEqual(conflict_events[0].payload_json["error_code"], "approval_stale_or_superseded")

    def test_approve_expired_pending_approval_marks_expired_and_returns_stale_409(self):
        run, call, approval = self._create_pending_approval(
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        )

        with self.assertRaises(HTTPException) as ctx:
            ApprovalService(self.db).approve(
                tool_call_id=call.tool_call_id,
                payload=self._approval_decision(approval, reason="stale client approve"),
                current_user=self.owner,
            )

        refreshed_approval = self.db.scalar(
            select(AgentApproval).where(AgentApproval.approval_id == approval.approval_id)
        )
        refreshed_call = self.db.scalar(
            select(AgentToolCall).where(AgentToolCall.tool_call_id == call.tool_call_id)
        )
        events = [
            item.event_type
            for item in self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        ]

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "approval_stale_or_superseded")
        self.assertEqual(refreshed_approval.approval_status, "expired")
        self.assertEqual(refreshed_call.status, "manual_intervention")
        self.assertEqual(refreshed_call.error_code, "approval_expired")
        self.assertIn("approval.expired", events)
        self.assertIn("approval.approve_conflict", events)

    def test_approval_decisions_reject_non_approvable_tool_call_status(self):
        run, running_call, running_approval = self._create_pending_approval()
        running_call.status = "running_pre_effect"
        self.db.commit()

        with self.assertRaises(HTTPException) as approve_ctx:
            ApprovalService(self.db).approve(
                tool_call_id=running_call.tool_call_id,
                payload=self._approval_decision(running_approval),
                current_user=self.owner,
            )

        reject_run, obsolete_call, obsolete_approval = self._create_pending_approval()
        obsolete_call.status = "obsolete"
        self.db.commit()

        with self.assertRaises(HTTPException) as reject_ctx:
            ApprovalService(self.db).reject(
                tool_call_id=obsolete_call.tool_call_id,
                payload=self._approval_decision(obsolete_approval),
                current_user=self.owner,
            )

        refreshed_running_approval = self.db.scalar(
            select(AgentApproval).where(AgentApproval.approval_id == running_approval.approval_id)
        )
        refreshed_obsolete_approval = self.db.scalar(
            select(AgentApproval).where(AgentApproval.approval_id == obsolete_approval.approval_id)
        )
        approve_conflict = self.db.scalar(
            select(AgentEvent).where(
                AgentEvent.run_id == run.run_id,
                AgentEvent.event_type == "approval.approve_conflict",
            )
        )
        reject_conflict = self.db.scalar(
            select(AgentEvent).where(
                AgentEvent.run_id == reject_run.run_id,
                AgentEvent.event_type == "approval.reject_conflict",
            )
        )

        self.assertEqual(approve_ctx.exception.status_code, 409)
        self.assertEqual(approve_ctx.exception.detail["code"], "tool_call_not_approvable")
        self.assertEqual(reject_ctx.exception.status_code, 409)
        self.assertEqual(reject_ctx.exception.detail["code"], "tool_call_not_approvable")
        self.assertEqual(refreshed_running_approval.approval_status, "pending")
        self.assertEqual(refreshed_obsolete_approval.approval_status, "pending")
        self.assertEqual(self.db.get(AgentToolCall, running_call.id).status, "running_pre_effect")
        self.assertEqual(self.db.get(AgentToolCall, obsolete_call.id).status, "obsolete")
        self.assertEqual(approve_conflict.payload_json["error_code"], "tool_call_not_approvable")
        self.assertEqual(reject_conflict.payload_json["error_code"], "tool_call_not_approvable")

    def test_approval_stale_and_epoch_conflicts_return_409_codes(self):
        run, call, approval = self._create_pending_approval()

        stale_payload = self._approval_decision(approval)
        stale_payload.input_hash = "different"
        with self.assertRaises(HTTPException) as stale_ctx:
            ApprovalService(self.db).approve(
                tool_call_id=call.tool_call_id,
                payload=stale_payload,
                current_user=self.owner,
            )
        self.assertEqual(stale_ctx.exception.status_code, 409)
        self.assertEqual(stale_ctx.exception.detail["code"], "approval_input_changed")
        self.db.rollback()

        epoch_payload = self._approval_decision(approval)
        epoch_payload.approval_epoch = 2
        with self.assertRaises(HTTPException) as epoch_ctx:
            ApprovalService(self.db).approve(
                tool_call_id=call.tool_call_id,
                payload=epoch_payload,
                current_user=self.owner,
            )
        self.assertEqual(epoch_ctx.exception.status_code, 409)
        self.assertEqual(epoch_ctx.exception.detail["code"], "approval_epoch_conflict")
        conflict_events = list(self.db.scalars(
            select(AgentEvent).where(
                AgentEvent.run_id == run.run_id,
                AgentEvent.event_type == "approval.approve_conflict",
            )
        ).all())
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alerts = {
            item["alert_id"]: item
            for item in AgentAlertService(self.db).snapshot(project_id=10)["alerts"]
        }

        self.assertEqual(len(conflict_events), 2)
        self.assertEqual(
            sorted(item.payload_json["error_code"] for item in conflict_events),
            ["approval_epoch_conflict", "approval_input_changed"],
        )
        self.assertEqual(metrics["approval_approve_conflict_total"], 2)
        self.assertEqual(metrics["approval_epoch_conflict_total"], 1)
        self.assertIn("agent_approval_approve_conflict", alerts)
        self.assertIn("agent_approval_epoch_conflict", alerts)
        self.assertEqual(alerts["agent_approval_approve_conflict"]["runbook_id"], "approval_stale")

    def test_approval_lineage_lock_metrics_alert_with_runbook(self):
        AgentRuntimeService(self.db).ensure_backend_contracts()
        run, call, approval = self._create_pending_approval()
        self.db.add(
            AgentApprovalMutationLog(
                approval_lineage_id=approval.approval_lineage_id,
                approval_id=approval.approval_id,
                tool_call_id=call.tool_call_id,
                run_id=run.run_id,
                mutation_type="expire",
                from_status="pending",
                to_status="expired",
                actor_user_id=self.owner.id,
                reason="lineage lock observability",
                details_json={
                    "lineage_lock_wait_ms": 25,
                    "lineage_lock_skip_total": 1,
                },
            )
        )
        self.db.commit()
        AgentOutboxPublisher(self.db, publisher=lambda event: None).publish_pending(limit=100)

        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        alerts = {
            item["alert_id"]: item
            for item in alert_snapshot["alerts"]
        }
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertEqual(metrics["approval_lineage_lock_wait_ms"], 25)
        self.assertEqual(metrics["approval_lineage_lock_skip_total"], 1)
        self.assertIn("agent_approval_lineage_lock_wait", alerts)
        self.assertIn("agent_approval_lineage_lock_skip", alerts)
        self.assertEqual(alerts["agent_approval_lineage_lock_wait"]["severity"], "P2")
        self.assertEqual(alerts["agent_approval_lineage_lock_wait"]["runbook_id"], "approval_stale")
        self.assertEqual(alerts["agent_approval_lineage_lock_skip"]["severity"], "P2")
        self.assertEqual(alerts["agent_approval_lineage_lock_skip"]["runbook_id"], "approval_stale")
        self.assertEqual(alert_snapshot["summary"]["highest_severity"], "P2")
        self.assertEqual(dashboard["readiness"], "pass")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "pass")

    def test_approval_time_permission_revoked_returns_403(self):
        _, call, approval = self._create_pending_approval(current_user=self.member)
        approval.required_permissions_json = ["report:view"]
        self.db.commit()

        with self.assertRaises(HTTPException) as ctx:
            ApprovalService(self.db).approve(
                tool_call_id=call.tool_call_id,
                payload=self._approval_decision(approval),
                current_user=self.member,
            )

        self.assertEqual(ctx.exception.status_code, 403)

    def test_worker_does_not_claim_unapproved_tool_call(self):
        _, call, _ = self._create_pending_approval()
        AgentWorkerQueueService(self.db).enqueue_tool_call(call)

        claimed = AgentWorkerQueueService(self.db).claim_next(worker_id="worker-approval")
        queue_item = self.db.scalar(select(AgentWorkerQueue).where(AgentWorkerQueue.tool_call_id == call.tool_call_id))

        self.assertIsNone(claimed)
        self.assertEqual(queue_item.status, "blocked_approval")
        self.assertEqual(queue_item.last_error_code, "approval_required_before_execution")

    def test_execute_time_permission_revoked_after_approval_still_blocks_backend(self):
        run, call, approval = self._create_pending_approval(current_user=self.member)
        call.resolved_side_effect_class = "read_only"
        self.db.commit()
        ApprovalService(self.db).approve(
            tool_call_id=call.tool_call_id,
            payload=self._approval_decision(approval),
            current_user=self.member,
        )
        permissions = list(self.db.scalars(select(ProjectMemberPermission)).all())
        for permission in permissions:
            self.db.delete(permission)
        self.db.commit()

        result = ToolExecutor(self.db).execute_next(worker_id="worker-approval")

        self.assertEqual(result.tool_call_id, call.tool_call_id)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "permission_revoked_before_execution")

    def test_harness_approval_expire_payload_contract_matches_service(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import (
            audit_agent_approval_expiration,
            process_agent_approval_expiration,
        )

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Approval expire payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Approval expire payload contract:" in path.read_text(encoding="utf-8")
        ]
        for index in range(2):
            self._create_pending_approval(
                expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=index + 1)
            )

        scanner = ApprovalExpireScanner(self.db)
        audit = scanner.audit(project_id=10)
        audit_route_payload = audit_agent_approval_expiration(
            project_id=10,
            db=self.db,
            current_user=self.owner,
        )["data"]
        process_summary = scanner.expire_due_summary(project_id=10, limit=1)
        process_route_payload = process_agent_approval_expiration(
            project_id=10,
            limit=1,
            db=self.db,
            current_user=self.owner,
        )["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["audit_fields"], list(APPROVAL_EXPIRE_AUDIT_FIELDS))
            self.assertEqual(contract["process_fields"], list(APPROVAL_EXPIRE_PROCESS_FIELDS))
            self.assertEqual(contract["derived_from_fields"], list(APPROVAL_EXPIRE_DERIVED_FROM_FIELDS))
            self.assertEqual(contract["source"], "ApprovalExpireScanner")
        self.assertEqual(list(AgentApprovalExpireAuditRead.model_fields), list(APPROVAL_EXPIRE_AUDIT_FIELDS))
        self.assertEqual(list(AgentApprovalExpireProcessRead.model_fields), list(APPROVAL_EXPIRE_PROCESS_FIELDS))
        self.assertEqual(list(audit), list(APPROVAL_EXPIRE_AUDIT_FIELDS))
        self.assertEqual(list(audit_route_payload), list(APPROVAL_EXPIRE_AUDIT_FIELDS))
        self.assertEqual(list(process_summary), list(APPROVAL_EXPIRE_PROCESS_FIELDS))
        self.assertEqual(list(process_route_payload), list(APPROVAL_EXPIRE_PROCESS_FIELDS))
        self.assertEqual(list(audit["derived_from"]), list(APPROVAL_EXPIRE_DERIVED_FROM_FIELDS))
        self.assertEqual(list(audit_route_payload["derived_from"]), list(APPROVAL_EXPIRE_DERIVED_FROM_FIELDS))
        self.assertEqual(list(process_summary["derived_from"]), list(APPROVAL_EXPIRE_DERIVED_FROM_FIELDS))
        self.assertEqual(list(process_route_payload["derived_from"]), list(APPROVAL_EXPIRE_DERIVED_FROM_FIELDS))

    def test_expire_scanner_expires_due_pending_approvals_idempotently(self):
        AgentRuntimeService(self.db).ensure_backend_contracts()
        run, call, approval = self._create_pending_approval(
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        )
        AgentOutboxPublisher(self.db, publisher=lambda event: None).publish_pending(limit=100)

        scanner = ApprovalExpireScanner(self.db)
        audit_before = scanner.audit(project_id=10)
        metrics_before = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot_before = AgentAlertService(self.db).snapshot(project_id=10)
        alerts_before = {
            item["alert_id"]: item
            for item in alert_snapshot_before["alerts"]
        }
        dashboard_before = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        checks_before = {item["name"]: item for item in dashboard_before["checks"]}
        summary = scanner.expire_due_summary(project_id=10)
        expired_again = scanner.expire_due()
        refreshed = self.db.scalar(select(AgentApproval).where(AgentApproval.approval_id == approval.approval_id))
        events = [item.event_type for item in self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all()]
        audit_after = scanner.audit(project_id=10)

        self.assertEqual(audit_before["due_count"], 1)
        self.assertEqual(audit_before["candidate_lineage_count"], 1)
        self.assertGreaterEqual(audit_before["oldest_due_lag_ms"], 0)
        self.assertTrue(audit_before["batch_safe"])
        self.assertEqual(metrics_before["approval_expire_due_total"], 1)
        self.assertIn("approval_expire_batch_lag_ms", metrics_before)
        self.assertIn("approval_lineage_lock_wait_ms", metrics_before)
        self.assertIn("approval_lineage_lock_skip_total", metrics_before)
        self.assertIn("agent_approval_expire_backlog", alerts_before)
        self.assertIn("agent_approval_expire_batch_lag", alerts_before)
        self.assertEqual(alerts_before["agent_approval_expire_backlog"]["severity"], "P2")
        self.assertEqual(alerts_before["agent_approval_expire_backlog"]["runbook_id"], "approval_stale")
        self.assertEqual(alerts_before["agent_approval_expire_batch_lag"]["severity"], "P2")
        self.assertEqual(alerts_before["agent_approval_expire_batch_lag"]["runbook_id"], "approval_stale")
        self.assertEqual(alert_snapshot_before["summary"]["highest_severity"], "P2")
        self.assertEqual(dashboard_before["readiness"], "attention")
        self.assertEqual(checks_before["live_recovery_attention"]["status"], "attention")
        self.assertEqual(checks_before["monitoring_alerts_clear"]["status"], "pass")
        self.assertEqual(summary["attempted"], 1)
        self.assertEqual(summary["expired"], 1)
        self.assertGreaterEqual(summary["lineage_lock_wait_ms"], 0)
        self.assertEqual(summary["lineage_lock_skip_total"], 0)
        self.assertEqual(summary["due_before"], 1)
        self.assertEqual(summary["due_after"], 0)
        self.assertEqual(summary["lineage_hotspot_count_before"], 0)
        self.assertEqual(expired_again, 0)
        self.assertEqual(audit_after["due_count"], 0)
        self.assertEqual(refreshed.approval_status, "expired")
        self.assertIn("approval.expired", events)
        mutation = self.db.scalar(
            select(AgentApprovalMutationLog).where(
                AgentApprovalMutationLog.approval_id == approval.approval_id,
                AgentApprovalMutationLog.mutation_type == "expire",
            )
        )
        self.assertIsNotNone(mutation)
        self.assertIn("lineage_lock_wait_ms", mutation.details_json)
        metrics_after = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        self.assertGreaterEqual(metrics_after["approval_lineage_lock_wait_ms"], 0)
        self.assertEqual(metrics_after["approval_lineage_lock_skip_total"], 0)

    def test_approval_expire_audit_detects_lineage_hotspot(self):
        _, _, approval = self._create_pending_approval(
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=2)
        )
        self.db.add(
            AgentApproval(
                approval_id="agent-appr-hotspot-extra",
                approval_lineage_id=approval.approval_lineage_id,
                approval_epoch=approval.approval_epoch + 1,
                run_id=approval.run_id,
                tool_call_id=approval.tool_call_id,
                project_id=approval.project_id,
                approval_status="pending",
                requested_by=approval.requested_by,
                input_hash=approval.input_hash,
                runtime_snapshot_id=approval.runtime_snapshot_id,
                resource_scope_hash=approval.resource_scope_hash,
                approval_reason="stale duplicate pending approval",
                required_permissions_json=list(approval.required_permissions_json),
                expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
            )
        )
        self.db.commit()

        audit = ApprovalExpireScanner(self.db).audit(project_id=10)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_ids = {item["alert_id"] for item in AgentAlertService(self.db).snapshot(project_id=10)["alerts"]}

        self.assertFalse(audit["batch_safe"])
        self.assertEqual(audit["due_count"], 2)
        self.assertEqual(audit["lineage_hotspot_count"], 1)
        self.assertIn(approval.approval_lineage_id, audit["hotspot_lineage_ids"])
        self.assertEqual(metrics["approval_lineage_hotspot_total"], 1)
        self.assertIn("agent_approval_lineage_hotspot", alert_ids)

    def test_expire_scanner_processes_each_lineage_once_when_hotspot_exists(self):
        _, _, approval = self._create_pending_approval(
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=2)
        )
        self.db.add(
            AgentApproval(
                approval_id="agent-appr-hotspot-skip-extra",
                approval_lineage_id=approval.approval_lineage_id,
                approval_epoch=approval.approval_epoch + 1,
                run_id=approval.run_id,
                tool_call_id=approval.tool_call_id,
                project_id=approval.project_id,
                approval_status="pending",
                requested_by=approval.requested_by,
                input_hash=approval.input_hash,
                runtime_snapshot_id=approval.runtime_snapshot_id,
                resource_scope_hash=approval.resource_scope_hash,
                approval_reason="duplicate pending approval in same lineage",
                required_permissions_json=list(approval.required_permissions_json),
                expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
            )
        )
        self.db.commit()

        summary = ApprovalExpireScanner(self.db).expire_due_summary(project_id=10)
        mutations = list(
            self.db.scalars(
                select(AgentApprovalMutationLog).where(
                    AgentApprovalMutationLog.approval_lineage_id == approval.approval_lineage_id,
                    AgentApprovalMutationLog.mutation_type == "expire",
                )
            ).all()
        )

        self.assertEqual(summary["due_before"], 2)
        self.assertEqual(summary["attempted"], 1)
        self.assertEqual(summary["expired"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["skipped_duplicate_lineage_count"], 1)
        self.assertEqual(summary["processed_lineage_ids"], [approval.approval_lineage_id])
        self.assertEqual(summary["due_after"], 1)
        self.assertEqual(len(mutations), 1)

    def test_approval_expire_process_schema_exposes_lineage_observability_fields(self):
        _, _, approval = self._create_pending_approval(
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=2)
        )
        self.db.add(
            AgentApproval(
                approval_id="agent-appr-hotspot-schema-extra",
                approval_lineage_id=approval.approval_lineage_id,
                approval_epoch=approval.approval_epoch + 1,
                run_id=approval.run_id,
                tool_call_id=approval.tool_call_id,
                project_id=approval.project_id,
                approval_status="pending",
                requested_by=approval.requested_by,
                input_hash=approval.input_hash,
                runtime_snapshot_id=approval.runtime_snapshot_id,
                resource_scope_hash=approval.resource_scope_hash,
                approval_reason="schema duplicate lineage skip count",
                required_permissions_json=list(approval.required_permissions_json),
                expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
            )
        )
        self.db.commit()

        summary = ApprovalExpireScanner(self.db).expire_due_summary(project_id=10)
        payload = AgentApprovalExpireProcessRead.model_validate(summary)

        dumped = payload.model_dump()

        self.assertEqual(payload.skipped_duplicate_lineage_count, 1)
        for key in (
            "skipped_duplicate_lineage_count",
            "lineage_lock_wait_ms",
            "lineage_lock_skip_total",
        ):
            self.assertIn(key, dumped)
            self.assertEqual(dumped[key], summary[key])

    def test_agent_approval_routes_are_declared(self):
        from app.main import create_app

        paths = create_app().openapi()["paths"]

        self.assertIn("/api/v1/agents/tool-calls/{tool_call_id}/approve", paths)
        self.assertIn("/api/v1/agents/tool-calls/{tool_call_id}/reject", paths)
        self.assertIn("/api/v1/agents/runs/{run_id}/approvals", paths)
        self.assertIn("/api/v1/agents/metrics", paths)
        self.assertIn("/api/v1/agents/dashboard", paths)
        self.assertIn("/api/v1/agents/alerts", paths)
        self.assertIn("/api/v1/agents/root-cause-rules/audit", paths)
        self.assertIn("/api/v1/agents/approvals/expire-audit", paths)
        self.assertIn("/api/v1/agents/approvals/expire", paths)
        self.assertIn("/api/v1/agents/worker-queue/audit", paths)
        self.assertIn("/api/v1/agents/events/replay-stress-audit", paths)
        self.assertIn("/api/v1/agents/outbox/publish", paths)
        self.assertIn("/api/v1/agents/release-gates", paths)
        self.assertIn("/api/v1/agents/release-gates/promotion", paths)
        self.assertIn("/api/v1/agents/fault-injections", paths)
        self.assertIn("/api/v1/agents/fault-injections/coverage", paths)
        self.assertIn("/api/v1/agents/fault-injections/run", paths)
        self.assertIn("/api/v1/agents/runbooks", paths)
        self.assertIn("/api/v1/agents/runs/{run_id}/runbook", paths)
        self.assertIn("/api/v1/agents/runs/{run_id}/events/replay-audit", paths)

    def test_harness_documented_agent_routes_match_openapi(self):
        from pathlib import Path
        import re

        from app.main import create_app

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        docs = sorted(docs_dir.glob("*Harness_Loop_Agent*Memory*.md"))
        documented_routes: set[tuple[str, str]] = set()
        route_pattern = re.compile(r"\b(GET|POST|PATCH|PUT|DELETE)\s+(/api/v1/agents[^\s`]*)")
        for path in docs:
            for method, route in route_pattern.findall(path.read_text(encoding="utf-8")):
                route = re.split(r"[`，,。；;）)]", route, maxsplit=1)[0]
                documented_routes.add((method.lower(), route.replace("{id}", "{memory_id}")))

        openapi = create_app().openapi()["paths"]
        openapi_routes = {
            (method.lower(), path)
            for path, methods in openapi.items()
            if path.startswith("/api/v1/agents")
            for method in methods
        }

        self.assertGreaterEqual(len(documented_routes), 49)
        self.assertEqual(documented_routes - openapi_routes, set())
        self.assertEqual(openapi_routes - documented_routes, set())

    def test_agent_approval_decision_openapi_requires_cas_fields(self):
        from app.main import create_app

        openapi = create_app().openapi()
        schema = openapi["components"]["schemas"]["AgentApprovalDecisionRequest"]
        required_fields = set(schema["required"])
        cas_fields = {
            "input_hash",
            "runtime_snapshot_id",
            "resource_scope_hash",
            "approval_lineage_id",
            "approval_epoch",
        }

        self.assertEqual(required_fields & cas_fields, cas_fields)
        self.assertNotIn("reason", required_fields)
        for path in (
            "/api/v1/agents/tool-calls/{tool_call_id}/approve",
            "/api/v1/agents/tool-calls/{tool_call_id}/reject",
        ):
            request_schema = (
                openapi["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]
            )
            self.assertEqual(request_schema["$ref"], "#/components/schemas/AgentApprovalDecisionRequest")

    def test_harness_approval_concurrency_contract_matches_guard_and_openapi(self):
        from pathlib import Path

        from app.main import create_app

        def _split_csv(value: str) -> set[str]:
            if value in {"true", "false"}:
                return {value}
            return {item.strip() for item in value.split(",") if item.strip()}

        def _parse_contract(text: str) -> dict[str, set[str]]:
            section = text[text.index("Required Approval concurrency contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            return {
                key.strip(): _split_csv(value.strip())
                for line in block.splitlines()
                if "=" in line
                for key, value in [line.split("=", 1)]
            }

        expected_contract = {
            "final_statuses": APPROVAL_FINAL_STATUSES,
            "approvable_tool_call_statuses": APPROVABLE_TOOL_CALL_STATUSES,
            "supersede_blocked_tool_call_statuses": SUPERSEDE_BLOCKED_TOOL_CALL_STATUSES,
            "immutable_fields": set(APPROVAL_IMMUTABLE_FIELDS),
            "mutation_types": APPROVAL_MUTATION_TYPES,
            "event_types": APPROVAL_EVENT_TYPES,
            "conflict_error_codes": APPROVAL_CONFLICT_ERROR_CODES,
            "approve_reject_schema_required_fields": set(APPROVAL_IMMUTABLE_FIELDS),
            "reason_required": {"false"},
            "replacement_atomic": {"true"},
            "expire_process_one_lineage_per_mutation": {"true"},
        }
        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            _parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Approval concurrency contract:" in path.read_text(encoding="utf-8")
        ]
        openapi = create_app().openapi()
        schema = openapi["components"]["schemas"]["AgentApprovalDecisionRequest"]

        self.assertEqual(len(documented_contracts), 2)
        for contract in documented_contracts:
            self.assertEqual(contract, expected_contract)
        self.assertEqual(set(schema["required"]) & set(APPROVAL_IMMUTABLE_FIELDS), set(APPROVAL_IMMUTABLE_FIELDS))
        self.assertNotIn("reason", schema["required"])

        run, call, approval = self._create_pending_approval()
        approved, lineage, approved_call, approve_mutation = ApprovalService(self.db).approve(
            tool_call_id=call.tool_call_id,
            payload=self._approval_decision(approval),
            current_user=self.owner,
        )
        supersede_run, old_call, old_approval = self._create_pending_approval()
        replacement_payload = AgentToolCallCreateRequest(
            run_id=supersede_run.run_id,
            tool_name="project.read_context",
            input={"project_id": 10, "replacement": True},
            step_index=old_call.step_index,
        )
        superseded, replacement_lineage, replacement_call, replacement_approval, supersede_mutation, create_mutation = (
            ApprovalService(self.db).supersede_with_replacement(
                tool_call_id=old_call.tool_call_id,
                replacement_payload=replacement_payload,
                current_user=self.owner,
                reason="contract replacement",
            )
        )
        events = {
            item.event_type
            for item in self.db.scalars(select(AgentEvent)).all()
            if item.event_type.startswith("approval.")
        }

        self.assertEqual(approved.approval_status, "approved")
        self.assertEqual(lineage.status, "approved")
        self.assertEqual(approved_call.approved_approval_id, approval.approval_id)
        self.assertEqual(approve_mutation.mutation_type, "approve")
        self.assertEqual(superseded.approval_status, "superseded")
        self.assertEqual(replacement_lineage.current_epoch, old_approval.approval_epoch + 1)
        self.assertEqual(replacement_lineage.tool_call_id, replacement_call.tool_call_id)
        self.assertEqual(replacement_approval.approval_status, "pending")
        self.assertEqual(supersede_mutation.mutation_type, "supersede")
        self.assertEqual(create_mutation.mutation_type, "create_replacement")
        self.assertIn("approval.created", events)
        self.assertIn("approval.approved", events)
        self.assertIn("approval.superseded", events)

    def test_harness_frozen_status_enums_match_capabilities_contract(self):
        from pathlib import Path
        import re

        from app.schemas.agent import AgentMigrationBlockRead

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        plan_text = next(
            path.read_text(encoding="utf-8")
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "409 approval_stale_or_superseded" in path.read_text(encoding="utf-8")
        )
        section = plan_text[plan_text.index("### 4.2"):plan_text.index("### 4.3")]
        documented: dict[str, list[str]] = {}
        for title, block in re.findall(r"####\s+4\.2\.\d+\s+([^\n]+)\n\n```text\n(.*?)\n```", section, re.S):
            values = [line.strip() for line in block.splitlines() if line.strip()]
            if "Run" in title:
                documented["run_statuses"] = values
            elif "ToolCall" in title:
                documented["tool_call_statuses"] = values
            elif "Effect Submission State" in title:
                documented["effect_submission_states"] = values
            elif "BackendEffectCapability" in title:
                documented["backend_effect_capabilities"] = values
            elif "Approval" in title:
                documented["approval_statuses"] = values
            elif "Migration Block" in title:
                documented["migration_block_statuses"] = values

        capabilities = AgentRuntimeService(self.db).capabilities()

        self.assertEqual(set(documented), {
            "run_statuses",
            "tool_call_statuses",
            "effect_submission_states",
            "backend_effect_capabilities",
            "approval_statuses",
            "migration_block_statuses",
        })
        for key, values in documented.items():
            self.assertEqual(capabilities[key], values)
        self.assertIn("revoked", documented["approval_statuses"])
        AgentApprovalRead.model_validate({
            "approval_id": "agent-appr-revoked",
            "approval_lineage_id": "lineage-revoked",
            "approval_epoch": 1,
            "run_id": "agent-run-revoked",
            "tool_call_id": "agent-tool-revoked",
            "project_id": 10,
            "approval_status": "revoked",
            "requested_by": self.owner.id,
            "decided_by": None,
            "decided_at": None,
            "input_hash": "input",
            "runtime_snapshot_id": "snapshot",
            "resource_scope_hash": "scope",
            "approval_reason": None,
            "decision_reason": None,
            "required_permissions_json": [],
            "expires_at": None,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        })
        for status_value in documented["migration_block_statuses"]:
            AgentMigrationBlockRead.model_validate({
                "block_id": f"block-{status_value}",
                "run_id": "agent-run-migration",
                "tool_call_id": None,
                "status": status_value,
                "block_type": "run",
                "reason": "contract test",
                "backend_name": None,
                "backend_operation": None,
                "backend_contract_version": None,
                "required_migration_type": None,
                "details_json": None,
                "resolution_summary_json": None,
                "resolved_by": None,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "resolved_at": None,
            })

    def test_harness_frozen_api_error_codes_match_architecture_contract(self):
        from pathlib import Path
        import re

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        plan_text = next(
            path.read_text(encoding="utf-8")
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "### 4.3" in path.read_text(encoding="utf-8")
        )
        frozen_section = plan_text[plan_text.index("### 4.3"):plan_text.index("### 4.3.1")]
        frozen_codes = {
            (int(status_code), code)
            for status_code, code in re.findall(r"^([0-9]{3})\s+([a-z0-9_]+)$", frozen_section, re.M)
        }
        architecture_text = next(
            path.read_text(encoding="utf-8")
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "外部事件处理表：" in path.read_text(encoding="utf-8")
        )
        error_table = architecture_text[architecture_text.index("错误码："):architecture_text.index("SSE 事件类型扩展：")]
        architecture_codes = {
            (int(status_code), code)
            for status_code, code in re.findall(r"\|\s*([0-9]{3})\s*\|\s*`([^`]+)`\s*\|", error_table)
        }
        expected_codes = {
            (409, "approval_stale_or_superseded"),
            (409, "approval_epoch_conflict"),
            (409, "approval_input_changed"),
            (409, "tool_call_obsolete"),
            (409, "run_migration_blocked"),
            (409, "checkpoint_stale_replan_required"),
            (403, "permission_revoked_before_execution"),
            (422, "backend_contract_unsupported"),
            (423, "tool_call_uncertain_reconcile_required"),
            (424, "backend_reconcile_not_supported"),
            (424, "backend_capability_too_weak"),
            (422, "memory_event_not_stale_event"),
            (500, "event_outbox_write_failed"),
        }

        self.assertEqual(frozen_codes, expected_codes)
        self.assertEqual(architecture_codes, expected_codes)
        test_source = Path(__file__).read_text(encoding="utf-8")
        for _, code in expected_codes:
            self.assertGreaterEqual(test_source.count(code), 2, code)
        for event_name in ["execution_record.created", "permission.changed", "memory.status_changed"]:
            self.assertIn(event_name, plan_text)
            self.assertIn(event_name, architecture_text)
        self.assertIn("422 memory_event_not_stale_event", architecture_text)

    def test_harness_memory_governance_profiles_match_architecture_contract(self):
        from pathlib import Path
        import re

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        architecture_text = next(
            path.read_text(encoding="utf-8")
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "默认 profiles：" in path.read_text(encoding="utf-8")
        )
        source_section = architecture_text[
            architecture_text.index("不同来源必须有不同初始置信度："):architecture_text.index("实现要求：")
        ]
        execution_learned_row = next(
            line for line in source_section.splitlines()
            if "`execution_learned`" in line
        )
        self.assertIn("至少 2 次一致 execution evidence", architecture_text)
        self.assertIn("必须有关联 execution evidence", execution_learned_row)
        documented_sources = {
            source_type: {"initial_confidence": float(confidence), "authority": authority}
            for source_type, confidence, authority in re.findall(
                r"\|\s*`([^`]+)`\s*\|\s*`([0-9.]+)`\s*\|\s*`([^`]+)`",
                source_section,
            )
        }
        retrieval_section = architecture_text[
            architecture_text.index("默认 profiles："):architecture_text.index("计算公式必须引用 profile")
        ]
        documented_retrieval_profiles = {
            profile_name: {
                "min_confidence": float(min_confidence),
                "max_stale_score": float(max_stale_score),
            }
            for profile_name, min_confidence, max_stale_score in re.findall(
                r"\|\s*`([^`]+)`\s*\|[^|]*\|\s*`([0-9.]+)`\s*\|\s*`([0-9.]+)`",
                retrieval_section,
            )
        }

        MemorySourceProfileResolver(self.db).ensure_defaults()
        MemoryRetrievalProfileResolver(self.db).ensure_defaults()
        source_profiles = {
            item.source_type: item
            for item in self.db.scalars(select(AgentMemorySourceProfile)).all()
        }
        retrieval_profiles = {
            item.profile_name: item
            for item in self.db.scalars(select(AgentMemoryRetrievalProfile)).all()
        }

        self.assertEqual(set(source_profiles), set(documented_sources))
        for source_type, expected in documented_sources.items():
            profile = source_profiles[source_type]
            self.assertAlmostEqual(profile.initial_confidence, expected["initial_confidence"])
            self.assertEqual(profile.authority, expected["authority"])
            self.assertEqual(profile.status, "active")

        self.assertEqual(set(retrieval_profiles), set(documented_retrieval_profiles))
        for profile_name, expected in documented_retrieval_profiles.items():
            profile = retrieval_profiles[profile_name]
            self.assertAlmostEqual(profile.min_confidence, expected["min_confidence"])
            self.assertAlmostEqual(profile.max_stale_score, expected["max_stale_score"])
            self.assertEqual(profile.status, "active")
            self.assertEqual(profile.version, 1)
            self.assertTrue(profile.change_reason)
            self.assertEqual(profile.allow_memory_for_high_risk, profile_name == "high_risk_action_v1")
            for weight_field in [
                "semantic_weight",
                "confidence_weight",
                "recency_weight",
                "authority_weight",
                "validation_weight",
                "stale_weight",
                "contradiction_weight",
            ]:
                self.assertGreater(getattr(profile, weight_field), 0)

    def test_harness_memory_profile_catalog_payload_contract_matches_routes(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import (
            list_agent_memory_retrieval_profiles,
            list_agent_memory_source_profiles,
        )

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Memory profile catalog payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Memory profile catalog payload contract:" in path.read_text(encoding="utf-8")
        ]
        source_payload = list_agent_memory_source_profiles(db=self.db, current_user=self.owner)["data"]
        retrieval_payload = list_agent_memory_retrieval_profiles(db=self.db, current_user=self.owner)["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["source_profile_fields"], list(MEMORY_SOURCE_PROFILE_FIELDS))
            self.assertEqual(contract["retrieval_profile_fields"], list(MEMORY_RETRIEVAL_PROFILE_FIELDS))
            self.assertEqual(contract["source"], "MemoryProfileCatalogRoutes")
        self.assertEqual(list(AgentMemorySourceProfileRead.model_fields), list(MEMORY_SOURCE_PROFILE_FIELDS))
        self.assertEqual(list(AgentMemoryRetrievalProfileRead.model_fields), list(MEMORY_RETRIEVAL_PROFILE_FIELDS))
        self.assertEqual(len(source_payload), 6)
        self.assertEqual(len(retrieval_payload), 4)
        self.assertEqual(list(source_payload[0]), list(MEMORY_SOURCE_PROFILE_FIELDS))
        self.assertEqual(list(retrieval_payload[0]), list(MEMORY_RETRIEVAL_PROFILE_FIELDS))
        self.assertEqual(
            [item["source_type"] for item in source_payload],
            sorted(item["source_type"] for item in source_payload),
        )
        self.assertEqual(
            [item["profile_name"] for item in retrieval_payload],
            sorted(item["profile_name"] for item in retrieval_payload),
        )
        self.assertTrue(any(item["allowed_for_high_risk"] for item in source_payload))
        self.assertTrue(any(item["profile_name"] == "high_risk_action_v1" and item["allow_memory_for_high_risk"] for item in retrieval_payload))

    def test_harness_memory_contradiction_penalty_matches_architecture_contract(self):
        from pathlib import Path
        import math
        import re

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        architecture_text = next(
            path.read_text(encoding="utf-8")
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Severity multiplier：" in path.read_text(encoding="utf-8")
        )
        severity_section = architecture_text[
            architecture_text.index("Severity multiplier："):architecture_text.index("确定性计算：")
        ]
        documented_multipliers = {
            severity: float(multiplier)
            for severity, multiplier in re.findall(
                r"\|\s*`([^`]+)`\s*\|\s*`([0-9.]+)`",
                severity_section,
            )
        }
        cap_section = architecture_text[
            architecture_text.index("默认上限："):architecture_text.index("状态联动：")
        ]
        documented_caps = {
            profile_name: float(cap)
            for profile_name, cap in re.findall(
                r"([a-z_]+_v1)\.max_contradiction_penalty\s*=\s*([0-9.]+)",
                cap_section,
            )
        }

        MemoryRetrievalProfileResolver(self.db).ensure_defaults()
        retrieval_profiles = {
            item.profile_name: item
            for item in self.db.scalars(select(AgentMemoryRetrievalProfile)).all()
        }

        self.assertEqual(SEVERITY_MULTIPLIER, documented_multipliers)
        self.assertEqual(set(retrieval_profiles), set(documented_caps))
        for profile_name, max_penalty in documented_caps.items():
            self.assertAlmostEqual(retrieval_profiles[profile_name].max_contradiction_penalty, max_penalty)

        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Penalty rule",
            content="Old behavior",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        memory.contradiction_count = 3
        memory.recent_contradiction_count = 4
        memory.recent_validation_count = 2
        memory.max_recent_severity = "critical"
        memory.last_failure_fingerprint = "same-failure"
        self.db.commit()
        profile = retrieval_profiles["high_risk_action_v1"]

        expected_raw = (
            (
                math.log1p(memory.contradiction_count) * 0.12
                + min(memory.recent_contradiction_count * 0.08, 0.24)
                + 0.15
            )
            * documented_multipliers["critical"]
            - min(memory.recent_validation_count * 0.04, 0.16)
        )
        expected = max(0.0, min(profile.max_contradiction_penalty, expected_raw))

        self.assertAlmostEqual(compute_contradiction_penalty(memory=memory, profile=profile), expected)

    def test_harness_memory_evidence_ref_role_mapping_matches_development_plan(self):
        from pathlib import Path
        import re

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        plan_text = next(
            path.read_text(encoding="utf-8")
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "usage_role 映射到 `dependency_role`" in path.read_text(encoding="utf-8")
        )
        role_line = next(
            line for line in plan_text.splitlines()
            if "usage_role 映射到 `dependency_role`" in line
        )
        documented_roles = re.findall(r"([a-z_]+)", role_line.split("：", 1)[1])
        active_line = next(
            line for line in plan_text.splitlines()
            if "只有 `policy_dependency` 可设置 `active_for_policy=true`" in line
        )
        active_role = re.search(r"`([^`]+)`", active_line).group(1)

        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Evidence role rule",
            content="Use memory through EvidenceRef.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        adapter = MemoryEvidenceAdapter()

        self.assertEqual(documented_roles, ["trace_only", "planning_hint", "repair_hint", "policy_dependency"])
        for usage_role in documented_roles:
            evidence_ref = adapter.to_evidence_ref(memory=memory, usage_role=usage_role)
            self.assertEqual(evidence_ref["ref_type"], "memory")
            self.assertEqual(evidence_ref["ref_id"], str(memory.id))
            self.assertEqual(evidence_ref["version_id"], str(memory.memory_version))
            self.assertEqual(evidence_ref["content_hash"], memory.content_hash)
            self.assertEqual(evidence_ref["mutability_class"], "mutable_current")
            self.assertEqual(evidence_ref["freshness_policy"], "revalidate_before_side_effect")
            self.assertEqual(evidence_ref["dependency_role"], usage_role)
            self.assertEqual(evidence_ref["active_for_policy"], usage_role == active_role)
            self.assertFalse(evidence_ref["required_for_high_risk"])
            self.assertEqual(evidence_ref["authority"], f"memory:{memory.source_type}")

        policy_refs = EvidenceRefResolver().select_policy_refs([
            adapter.to_evidence_ref(memory=memory, usage_role=role)
            for role in documented_roles
        ])
        self.assertEqual([ref.dependency_role for ref in policy_refs], [active_role])

    def test_harness_documented_agent_api_paths_are_declared(self):
        from pathlib import Path
        import re

        from app.main import create_app

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_paths: set[str] = set()
        documented_operations: set[tuple[str, str]] = set()
        for doc_path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md"):
            text = doc_path.read_text(encoding="utf-8")
            documented_paths.update(
                re.findall(r"(?:GET|POST|PATCH|DELETE|PUT)\s+(/api/v1/agents[^\s`，。；]*)", text)
            )
            documented_operations.update(
                (method.lower(), path)
                for method, path in re.findall(r"\b(GET|POST|PATCH|DELETE|PUT)\s+(/api/v1/agents[^\s`，。；]*)", text)
            )

        normalized_paths = {
            path
            .replace("/memories/{id}", "/memories/{memory_id}")
            .replace("/memories/{id}/validate", "/memories/{memory_id}/validate")
            .replace("/memories/{id}/reject", "/memories/{memory_id}/reject")
            for path in documented_paths
        }
        normalized_operations = {
            (
                method,
                path
                .replace("/memories/{id}", "/memories/{memory_id}")
                .replace("/memories/{id}/validate", "/memories/{memory_id}/validate")
                .replace("/memories/{id}/reject", "/memories/{memory_id}/reject"),
            )
            for method, path in documented_operations
        }
        openapi = create_app().openapi()["paths"]
        openapi_paths = set(openapi)
        missing_operations = sorted(
            f"{method.upper()} {path}"
            for method, path in normalized_operations
            if path not in openapi or method not in openapi[path]
        )

        self.assertGreater(len(normalized_paths), 30)
        self.assertEqual(sorted(normalized_paths - openapi_paths), [])
        self.assertGreater(len(normalized_operations), 30)
        self.assertEqual(missing_operations, [])

    def test_evidence_ref_resolver_filters_active_policy_refs(self):
        refs = [
            {
                "evidence_ref_id": "audit-latest",
                "ref_type": "latest_execution_sample",
                "ref_id": "latest",
                "mutability_class": "ephemeral_latest",
                "dependency_role": "audit_background",
                "active_for_policy": False,
            },
            {
                "evidence_ref_id": "decision-case",
                "ref_type": "testcase",
                "ref_id": "case-1",
                "mutability_class": "versioned",
                "version_id": "v1",
                "dependency_role": "decision_dependency",
                "active_for_policy": True,
            },
        ]

        policy_refs, audit_refs, summary = EvidenceRefResolver().split_policy_and_audit_refs(refs)

        self.assertEqual([item["evidence_ref_id"] for item in policy_refs], ["decision-case"])
        self.assertEqual([item["evidence_ref_id"] for item in audit_refs], ["audit-latest"])
        self.assertFalse(summary["requires_revalidation"])
        self.assertTrue(summary["fully_frozen"])

    def test_tool_call_records_policy_and_audit_evidence_refs(self):
        run = self._create_run("evidence refs")
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
                evidence_refs=[
                    {
                        "evidence_ref_id": "audit-latest",
                        "ref_type": "latest_execution_sample",
                        "ref_id": "latest",
                        "mutability_class": "ephemeral_latest",
                        "dependency_role": "audit_background",
                        "active_for_policy": False,
                    },
                    {
                        "evidence_ref_id": "decision-project",
                        "ref_type": "project",
                        "ref_id": "10",
                        "mutability_class": "versioned",
                        "version_id": "v1",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    },
                ],
            ),
            current_user=self.owner,
            enqueue=False,
        )

        self.assertEqual([item["evidence_ref_id"] for item in call.policy_evidence_refs_json], ["decision-project"])
        self.assertEqual([item["evidence_ref_id"] for item in call.audit_evidence_refs_json], ["audit-latest"])
        self.assertEqual(self.db.query(AgentEvidenceWatch).count(), 1)
        self.assertEqual(call.evidence_mutability_summary_json["policy_ref_count"], 1)

    def test_tool_call_policy_reason_records_policy_context_envelope(self):
        from app.core.sensitive_data import request_fingerprint

        run = self._create_run("tool policy context")
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
                evidence_refs=[
                    {
                        "evidence_ref_id": "live-project-context",
                        "ref_type": "project",
                        "ref_id": "10",
                        "mutability_class": "mutable_current",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    },
                ],
            ),
            current_user=self.owner,
            enqueue=False,
        )

        policy_context = call.policy_reason_json["policy_context"]
        expected_context = {
            "policy_version_hash": "agent-policy-v1",
            "tool_name": "project.read_context",
            "tool_version": "1.0.0",
            "base_side_effect_class": "read_only",
            "resolved_side_effect_class": "read_only",
            "base_replay_policy": "reuse_allowed",
            "resolved_replay_policy": "require_revalidation",
            "approval_policy": "safe_side_effect_auto",
            "approval_required": False,
            "approval_required_reason": "safe_initial_tool",
            "active_policy_ref_count": 1,
            "volatile_policy_ref_count": 1,
            "frozen_policy_ref_count": 0,
            "historical_volatile_excluded_count": 0,
            "mixed_volatile_frozen": False,
        }

        self.assertEqual(
            {key: policy_context[key] for key in expected_context},
            expected_context,
        )
        self.assertEqual(policy_context["policy_hash"], request_fingerprint(expected_context))
        self.assertEqual(call.resolved_replay_policy, policy_context["resolved_replay_policy"])
        self.assertEqual(call.approval_required, policy_context["approval_required"])

    def test_context_build_records_degradation_and_required_evidence_gap(self):
        run = self._create_run("context build")
        refs = self._large_evidence_refs(count=10)
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=128,
                evidence_refs=refs,
                required_evidence_ref_ids=["evidence-9"],
            ),
            current_user=self.owner,
        )
        events = [item.event_type for item in self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all()]

        self.assertEqual(build.context_degradation_level, "heavy")
        self.assertFalse(build.required_evidence_complete)
        self.assertEqual(self.db.query(AgentContextBuild).count(), 1)
        runtime_snapshot = self.db.scalar(
            select(AgentRuntimeSnapshot).where(
                AgentRuntimeSnapshot.snapshot_id == run.runtime_snapshot_id
            )
        )
        self.assertIsNotNone(runtime_snapshot)
        runtime_metadata = (build.build_metadata_json or {})["runtime_snapshot"]
        self.assertEqual(runtime_metadata["snapshot_id"], run.runtime_snapshot_id)
        self.assertEqual(runtime_metadata["runtime_hash"], runtime_snapshot.runtime_hash)
        self.assertEqual(runtime_metadata["tool_registry_hash"], runtime_snapshot.tool_registry_hash)
        self.assertEqual(runtime_metadata["manifest_bundle_hash"], runtime_snapshot.manifest_bundle_hash)
        self.assertEqual(runtime_metadata["prompt_bundle_hash"], runtime_snapshot.prompt_bundle_hash)
        self.assertEqual(runtime_metadata["policy_version_hash"], runtime_snapshot.policy_version_hash)
        self.assertIn("project.read_context", runtime_metadata["available_tool_names"])
        self.assertEqual(runtime_metadata["tool_count"], len(runtime_snapshot.tools_json))
        self.assertIn("context.full_evidence_required", events)
        self.assertGreaterEqual(self.db.query(AgentEvidenceWatch).count(), 1)
        AgentOutboxPublisher(self.db, publisher=lambda event: None).publish_pending(limit=100)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        alerts = {item["alert_id"]: item for item in alert_snapshot["alerts"]}
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertEqual(metrics["context_full_evidence_required_total"], 1)
        self.assertIn("agent_context_required_evidence_missing", alerts)
        self.assertEqual(alerts["agent_context_required_evidence_missing"]["severity"], "P1")
        self.assertEqual(alerts["agent_context_required_evidence_missing"]["runbook_id"], "checkpoint_stale")
        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "attention")

    def test_context_build_records_permission_context_for_project_member(self):
        from app.core.sensitive_data import request_fingerprint

        run = self._create_run("context build permission context")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
            ),
            current_user=self.member,
        )

        permission_context = (build.build_metadata_json or {})["permission_context"]
        expected_profile = {
            "actor_user_id": self.member.id,
            "project_id": run.project_id,
            "access_level": "project_member",
            "project_access": True,
            "implicit_all_project_permissions": False,
            "explicit_permission_codes": ["project:view"],
            "explicit_permission_count": 1,
        }

        self.assertEqual(
            {key: permission_context[key] for key in expected_profile},
            expected_profile,
        )
        self.assertEqual(
            permission_context["permission_hash"],
            request_fingerprint(expected_profile),
        )

    def test_loop_observation_uses_decision_context_and_explicit_root_cause_rule(self):
        run = self._create_run("loop observation")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=128,
                evidence_refs=self._large_evidence_refs(count=10),
                required_evidence_ref_ids=["evidence-9"],
            ),
            current_user=self.owner,
        )

        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="execute_tool",
                next_action_is_high_risk=True,
                reasons=["same_failure_no_progress"],
            ),
            current_user=self.owner,
        )

        self.assertEqual(observation.decision_context_build_id, build.context_build_id)
        self.assertEqual(observation.root_cause_rule_id, "RC_CONTEXT_OMITTED_HIGH_RISK")
        self.assertIn("evidence_incomplete_for_high_risk_action", observation.stop_reasons_all_json)
        self.assertGreaterEqual(self.db.query(AgentRootCauseRule).count(), 1)
        self.assertEqual(self.db.query(AgentLoopObservation).count(), 1)

    def test_loop_observation_maps_light_evidence_gap_to_evidence_incomplete_rule(self):
        run = self._create_run("loop evidence incomplete")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=160,
                evidence_refs=self._large_evidence_refs(count=3),
                required_evidence_ref_ids=["evidence-2"],
            ),
            current_user=self.owner,
        )

        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="execute_tool",
                next_action_is_high_risk=True,
                reasons=[],
            ),
            current_user=self.owner,
        )

        self.assertEqual(build.context_degradation_level, "light")
        self.assertFalse(build.required_evidence_complete)
        self.assertEqual(observation.stop_action_reason, "evidence_incomplete_for_high_risk_action")
        self.assertEqual(observation.root_cause_rule_id, "RC_EVIDENCE_INCOMPLETE")
        self.assertEqual(observation.root_cause_primary, "evidence_incomplete_for_high_risk_action")
        self.assertEqual(observation.mitigation_action, "fetch_required_evidence")

    def test_loop_observation_maps_same_failure_to_no_progress_rule(self):
        run = self._create_run("loop no progress")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": "evidence-stable",
                        "ref_type": "execution_record",
                        "ref_id": "execution-1",
                        "mutability_class": "immutable",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
                required_evidence_ref_ids=["evidence-stable"],
            ),
            current_user=self.owner,
        )

        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="repair",
                next_action_is_high_risk=False,
                reasons=["same_failure_no_progress"],
            ),
            current_user=self.owner,
        )

        self.assertEqual(build.context_degradation_level, "none")
        self.assertTrue(build.required_evidence_complete)
        self.assertEqual(observation.stop_action_reason, "same_failure_no_progress")
        self.assertEqual(observation.root_cause_rule_id, "RC_NO_PROGRESS_PURE")
        self.assertEqual(observation.root_cause_primary, "same_failure_no_progress")
        self.assertEqual(observation.mitigation_action, "stop_or_escalate_repair_strategy")

    def test_loop_observation_maps_memory_contradiction_before_no_progress_rule(self):
        run = self._create_run("loop memory contradiction")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": "evidence-memory-contradiction",
                        "ref_type": "memory",
                        "ref_id": "1",
                        "mutability_class": "snapshot",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
                required_evidence_ref_ids=["evidence-memory-contradiction"],
            ),
            current_user=self.owner,
        )

        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="repair",
                next_action_is_high_risk=False,
                reasons=["same_failure_no_progress"],
                observation={"memory_contradiction_delta": 1},
            ),
            current_user=self.owner,
        )

        self.assertEqual(build.context_degradation_level, "none")
        self.assertTrue(build.required_evidence_complete)
        self.assertEqual(observation.stop_action_reason, "same_failure_no_progress")
        self.assertEqual(observation.root_cause_rule_id, "RC_MEMORY_CONTRADICTION")
        self.assertEqual(observation.root_cause_primary, "memory_contradiction")
        self.assertEqual(observation.mitigation_action, "demote_memory_and_replan")

    def test_loop_observation_derives_memory_contradiction_delta_from_policy_refs(self):
        run = self._create_run("loop derives memory contradiction")
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Contradicted memory",
            content="Old repair guidance.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        MemoryManager(self.db).record_contradiction(
            memory_id=memory.id,
            contradiction_type="execution_mismatch",
            severity="medium",
            failure_fingerprint="same-failure",
            evidence_ref_json={"ref_type": "execution_record", "ref_id": "execution-1"},
            reason="execution contradicted memory",
            current_user=self.owner,
        )
        memory_ref = MemoryEvidenceAdapter().to_evidence_ref(memory=memory, usage_role="policy_dependency")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[memory_ref],
                memory_ids_used=[memory.id],
                required_evidence_ref_ids=[memory_ref["evidence_ref_id"]],
            ),
            current_user=self.owner,
        )

        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="repair",
                next_action_is_high_risk=False,
                reasons=["same_failure_no_progress"],
                observation={},
            ),
            current_user=self.owner,
        )

        self.assertEqual(observation.root_cause_rule_id, "RC_MEMORY_CONTRADICTION")
        self.assertEqual(observation.root_cause_primary, "memory_contradiction")
        self.assertEqual(observation.observation_json["memory_contradiction_delta"], 1)
        self.assertEqual(observation.observation_json["memory_usage"]["memory_ids"], [memory.id])
        self.assertEqual(observation.observation_json["memory_usage"]["active_policy_count"], 1)

    def test_loop_observation_ignores_audit_only_memory_contradiction_refs(self):
        run = self._create_run("loop ignores audit memory contradiction")
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Audit contradicted memory",
            content="Historical repair guidance only.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        MemoryManager(self.db).record_contradiction(
            memory_id=memory.id,
            contradiction_type="execution_mismatch",
            severity="medium",
            failure_fingerprint="audit-memory-failure",
            evidence_ref_json={"ref_type": "execution_record", "ref_id": "execution-audit"},
            reason="execution contradicted audit memory",
            current_user=self.owner,
        )
        audit_ref = MemoryEvidenceAdapter().to_evidence_ref(memory=memory, usage_role="repair_hint")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[audit_ref],
            ),
            current_user=self.owner,
        )
        build.build_metadata_json = {"policy_refs": [audit_ref]}
        self.db.commit()

        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="repair",
                next_action_is_high_risk=False,
                reasons=["same_failure_no_progress"],
                observation={},
            ),
            current_user=self.owner,
        )

        self.assertEqual(observation.root_cause_rule_id, "RC_NO_PROGRESS_PURE")
        self.assertEqual(observation.root_cause_primary, "same_failure_no_progress")
        self.assertNotIn("memory_usage", observation.observation_json)
        self.assertNotIn("memory_contradiction_delta", observation.observation_json)

    def test_context_builder_requires_used_memory_to_be_active_policy_ref(self):
        from pathlib import Path

        architecture_text = next(
            path.read_text(encoding="utf-8")
            for path in (Path(__file__).resolve().parents[1] / "docs").glob("*Harness_Loop_Agent*Memory*.md")
            if "15.7 Memory 进入 Loop 的唯一合法路径" in path.read_text(encoding="utf-8")
        )
        self.assertIn("ContextBuilder", architecture_text)
        self.assertIn("ToolPolicyResolver.select_policy_evidence_refs", architecture_text)
        self.assertIn("active policy refs", architecture_text)
        run = self._create_run("memory audit ref bypass")
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Audit-only memory",
            content="This memory is not active policy evidence.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        audit_ref = MemoryEvidenceAdapter().to_evidence_ref(memory=memory, usage_role="planning_hint")

        with self.assertRaises(HTTPException) as ctx:
            ContextBuilder(self.db).build(
                run_id=run.run_id,
                payload=AgentContextBuildCreateRequest(
                    build_purpose="repair",
                    step_index=0,
                    token_budget=4000,
                    evidence_refs=[audit_ref],
                    memory_ids_used=[memory.id],
                    required_evidence_ref_ids=[audit_ref["evidence_ref_id"]],
                ),
                current_user=self.owner,
            )
        events = list(
            self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        )
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail["code"], "memory_bypassed_evidence_ref")
        self.assertEqual(events[-1].event_type, "memory.bypassed_evidence_ref")
        self.assertEqual(
            events[-1].payload_json["reason"],
            "memory_ids_used_missing_active_policy_memory_evidence_ref",
        )
        self.assertEqual(metrics["memory_bypassed_evidence_ref_total"], 1)

    def test_loop_observation_maps_policy_loop_before_no_progress_rule(self):
        run = self._create_run("loop policy loop")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": "evidence-policy",
                        "ref_type": "execution_record",
                        "ref_id": "execution-policy-1",
                        "mutability_class": "immutable",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
                required_evidence_ref_ids=["evidence-policy"],
            ),
            current_user=self.owner,
        )

        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="repair",
                next_action_is_high_risk=False,
                reasons=["same_failure_no_progress", "policy_loop"],
            ),
            current_user=self.owner,
        )

        self.assertEqual(build.context_degradation_level, "none")
        self.assertTrue(build.required_evidence_complete)
        self.assertEqual(observation.stop_action_reason, "policy_loop")
        self.assertEqual(observation.root_cause_rule_id, "RC_POLICY_LOOP")
        self.assertEqual(observation.root_cause_primary, "policy_loop")
        self.assertEqual(observation.mitigation_action, "change_plan_or_require_human")

    def test_loop_observation_maps_repair_regression_before_no_progress_rule(self):
        run = self._create_run("loop repair regression")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": "evidence-regression",
                        "ref_type": "execution_record",
                        "ref_id": "execution-regression-1",
                        "mutability_class": "immutable",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
                required_evidence_ref_ids=["evidence-regression"],
            ),
            current_user=self.owner,
        )

        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="repair",
                next_action_is_high_risk=False,
                reasons=["same_failure_no_progress", "new_failures_outside_scope"],
            ),
            current_user=self.owner,
        )

        self.assertEqual(build.context_degradation_level, "none")
        self.assertTrue(build.required_evidence_complete)
        self.assertEqual(observation.stop_action_reason, "new_failures_outside_scope")
        self.assertEqual(observation.root_cause_rule_id, "RC_REPAIR_REGRESSION")
        self.assertEqual(observation.root_cause_primary, "repair_regression")
        self.assertEqual(observation.mitigation_action, "rollback_patch_or_human_review")

    def test_loop_observation_maps_backend_capability_to_recovery_rule(self):
        run = self._create_run("loop backend degraded")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": "evidence-backend",
                        "ref_type": "execution_record",
                        "ref_id": "execution-backend-1",
                        "mutability_class": "immutable",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
                required_evidence_ref_ids=["evidence-backend"],
            ),
            current_user=self.owner,
        )

        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="reconcile",
                next_action_is_high_risk=False,
                reasons=["backend_capability_degraded"],
            ),
            current_user=self.owner,
        )

        self.assertEqual(build.context_degradation_level, "none")
        self.assertTrue(build.required_evidence_complete)
        self.assertEqual(observation.stop_action_reason, "backend_capability_degraded")
        self.assertEqual(observation.root_cause_rule_id, "RC_BACKEND_CAPABILITY_DEGRADED")
        self.assertEqual(observation.root_cause_primary, "backend_capability_degraded")
        self.assertEqual(
            observation.mitigation_action,
            "upgrade_backend_operation_contract_or_require_manual_reapproval",
        )

    def test_loop_observation_maps_max_iterations_to_resource_limit_rule(self):
        run = self._create_run("loop max iterations")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": "evidence-iteration",
                        "ref_type": "execution_record",
                        "ref_id": "execution-iteration-1",
                        "mutability_class": "immutable",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
                required_evidence_ref_ids=["evidence-iteration"],
            ),
            current_user=self.owner,
        )

        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="stop",
                next_action_is_high_risk=False,
                reasons=["max_iterations"],
            ),
            current_user=self.owner,
        )

        self.assertEqual(build.context_degradation_level, "none")
        self.assertTrue(build.required_evidence_complete)
        self.assertEqual(observation.stop_action_reason, "max_iterations")
        self.assertEqual(observation.root_cause_rule_id, "RC_MAX_ITERATIONS")
        self.assertEqual(observation.root_cause_primary, "max_iterations")
        self.assertEqual(observation.mitigation_action, "human_review_or_extend_limit")

    def test_loop_observation_maps_budget_exhaustion_to_resource_limit_rule(self):
        run = self._create_run("loop resource limit")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": "evidence-resource",
                        "ref_type": "execution_record",
                        "ref_id": "execution-resource-1",
                        "mutability_class": "immutable",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
                required_evidence_ref_ids=["evidence-resource"],
            ),
            current_user=self.owner,
        )

        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="stop",
                next_action_is_high_risk=False,
                reasons=["cost_budget_exceeded"],
            ),
            current_user=self.owner,
        )

        self.assertEqual(build.context_degradation_level, "none")
        self.assertTrue(build.required_evidence_complete)
        self.assertEqual(observation.stop_action_reason, "cost_budget_exceeded")
        self.assertEqual(observation.root_cause_rule_id, "RC_RESOURCE_LIMIT")
        self.assertEqual(observation.root_cause_primary, "resource_limit")
        self.assertEqual(observation.mitigation_action, "pause_or_request_budget")

    def test_loop_observation_maps_accepted_unknown_to_unknown_rule(self):
        run = self._create_run("loop accepted unknown")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": "evidence-accepted-unknown",
                        "ref_type": "execution_record",
                        "ref_id": "execution-accepted-unknown-1",
                        "mutability_class": "immutable",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
                required_evidence_ref_ids=["evidence-accepted-unknown"],
            ),
            current_user=self.owner,
        )

        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="stop",
                next_action_is_high_risk=False,
                reasons=["accepted_unknown"],
            ),
            current_user=self.owner,
        )

        self.assertEqual(build.context_degradation_level, "none")
        self.assertTrue(build.required_evidence_complete)
        self.assertEqual(observation.stop_action_reason, "accepted_unknown")
        self.assertEqual(observation.root_cause_rule_id, "RC_UNKNOWN")
        self.assertEqual(observation.root_cause_primary, "unknown")
        self.assertEqual(observation.mitigation_action, "manual_diagnosis")

    def test_loop_observation_keeps_unregistered_reason_as_rule_missing(self):
        run = self._create_run("loop unregistered reason")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": "evidence-unregistered",
                        "ref_type": "execution_record",
                        "ref_id": "execution-unregistered-1",
                        "mutability_class": "immutable",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
                required_evidence_ref_ids=["evidence-unregistered"],
            ),
            current_user=self.owner,
        )

        observation = LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="stop",
                next_action_is_high_risk=False,
                reasons=["new_unregistered_reason"],
            ),
            current_user=self.owner,
        )

        self.assertIsNone(observation.stop_action_reason)
        self.assertEqual(observation.root_cause_rule_id, "RC_RULE_MISSING")
        self.assertEqual(observation.root_cause_primary, "root_cause_rule_missing")
        self.assertEqual(observation.mitigation_action, "add_explicit_root_cause_rule")
        AgentOutboxPublisher(self.db, publisher=lambda event: None).publish_pending(limit=100)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        alert_snapshot = AgentAlertService(self.db).snapshot(project_id=10)
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=10)
        alerts = {item["alert_id"]: item for item in alert_snapshot["alerts"]}
        checks = {item["name"]: item for item in dashboard["checks"]}

        self.assertEqual(metrics["root_cause_rule_missing_total"], 1)
        self.assertIn("agent_root_cause_rule_missing", alerts)
        self.assertEqual(alerts["agent_root_cause_rule_missing"]["severity"], "P1")
        self.assertEqual(alerts["agent_root_cause_rule_missing"]["runbook_id"], "root_cause_rule_missing")
        self.assertEqual(dashboard["readiness"], "attention")
        self.assertEqual(checks["monitoring_alerts_clear"]["status"], "attention")

    def test_harness_root_cause_rule_authoring_contract_matches_governance(self):
        from pathlib import Path

        def _parse_contract(text: str) -> dict[str, object]:
            section = text[text.index("Required RootCause rule authoring contract:"):]
            block = section.split("```text", 1)[1].split("```", 1)[0]
            parsed: dict[str, object] = {}
            for line in block.splitlines():
                if "=" not in line:
                    continue
                key, value = [item.strip() for item in line.split("=", 1)]
                if key == "priority_bands":
                    parsed[key] = {
                        band: tuple(int(part) for part in range_text.split("-", 1))
                        for item in value.split(",")
                        for band, range_text in [item.split(":", 1)]
                    }
                elif key == "default_rules":
                    parsed[key] = {
                        rule_id: {"priority_band": band, "priority": int(priority)}
                        for item in value.split(",")
                        for rule_id, band, priority in [item.split(":", 2)]
                    }
                elif key == "new_rule_required_fixtures":
                    parsed[key] = int(value)
                elif "," in value:
                    parsed[key] = {item.strip() for item in value.split(",") if item.strip()}
                else:
                    parsed[key] = value
            return parsed

        expected_contract = {
            "priority_bands": ROOT_CAUSE_PRIORITY_BANDS,
            "default_rules": ROOT_CAUSE_DEFAULT_RULE_CONTRACT,
            "governance_fields": ROOT_CAUSE_GOVERNANCE_FIELDS,
            "new_rule_required_fixtures": ROOT_CAUSE_NEW_RULE_REQUIRED_FIXTURE_COUNT,
            "fallback_rule_id": ROOT_CAUSE_FALLBACK_RULE_ID,
            "accepted_unknown_rule_id": ROOT_CAUSE_ACCEPTED_UNKNOWN_RULE_ID,
            "missing_rule_metric": ROOT_CAUSE_MISSING_RULE_METRIC,
        }
        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_contracts = [
            _parse_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required RootCause rule authoring contract:" in path.read_text(encoding="utf-8")
        ]

        self.assertEqual(len(documented_contracts), 2)
        for contract in documented_contracts:
            self.assertEqual(contract, expected_contract)

        engine = RootCauseRuleEngine(self.db)
        audit = engine.audit_rule_governance()
        seeded = {
            rule.rule_id: rule
            for rule in self.db.scalars(select(AgentRootCauseRule)).all()
        }

        self.assertEqual(set(audit), {"rule_count", *ROOT_CAUSE_GOVERNANCE_FIELDS})
        self.assertEqual(
            {
                band: (item["min"], item["max"])
                for band, item in audit["priority_bands"].items()
            },
            ROOT_CAUSE_PRIORITY_BANDS,
        )
        self.assertTrue(audit["governance_pass"])
        self.assertEqual(audit["violation_count"], 0)
        self.assertEqual(set(seeded), set(ROOT_CAUSE_DEFAULT_RULE_CONTRACT))
        for rule_id, expected in ROOT_CAUSE_DEFAULT_RULE_CONTRACT.items():
            with self.subTest(rule_id=rule_id):
                self.assertEqual(seeded[rule_id].priority, expected["priority"])
                self.assertEqual(seeded[rule_id].priority_band, expected["priority_band"])
        self.assertEqual(
            engine.evaluate(reasons=["accepted_unknown"], observation={}).rule_id,
            ROOT_CAUSE_ACCEPTED_UNKNOWN_RULE_ID,
        )
        self.assertEqual(
            engine.evaluate(reasons=["not_registered_anywhere"], observation={}).rule_id,
            ROOT_CAUSE_FALLBACK_RULE_ID,
        )

        self.db.add(
            AgentRootCauseRule(
                rule_id="RC_UNKNOWN_PRIORITY_BAND",
                reason_key="unknown_priority_band",
                root_cause_primary="unknown_priority_band",
                causal_chain_json=["unknown_priority_band"],
                mitigation_action="fix_rule_priority_band",
                priority=50,
                priority_band="not_a_band",
                match_expression_json={"any_reasons": ["unknown_priority_band"]},
                status="active",
            )
        )
        self.db.commit()

        failed = engine.audit_rule_governance()
        self.assertFalse(failed["governance_pass"])
        self.assertIn(
            {
                "rule_id": "RC_UNKNOWN_PRIORITY_BAND",
                "priority": 50,
                "priority_band": "not_a_band",
                "violation": "unknown_priority_band",
            },
            failed["violations"],
        )

    def test_root_cause_rule_governance_audits_priority_bands(self):
        engine = RootCauseRuleEngine(self.db)
        audit = engine.audit_rule_governance()

        self.assertTrue(audit["governance_pass"])
        self.assertEqual(audit["violation_count"], 0)
        seeded = {
            rule.rule_id: rule
            for rule in self.db.scalars(select(AgentRootCauseRule)).all()
        }
        self.assertEqual(seeded["RC_PERMISSION_REVOKED"].priority, 15)
        self.assertEqual(seeded["RC_PERMISSION_REVOKED"].priority_band, "safety")
        self.assertEqual(seeded["RC_RULE_MISSING"].priority, 999)
        self.assertEqual(seeded["RC_RULE_MISSING"].priority_band, "fallback")
        self.assertEqual(seeded["RC_NO_PROGRESS_PURE"].priority, 60)
        self.assertEqual(seeded["RC_NO_PROGRESS_PURE"].priority_band, "repair_quality")
        self.assertEqual(seeded["RC_EVIDENCE_INCOMPLETE"].priority, 20)
        self.assertEqual(seeded["RC_EVIDENCE_INCOMPLETE"].priority_band, "evidence_context")
        self.assertEqual(seeded["RC_MEMORY_CONTRADICTION"].priority, 30)
        self.assertEqual(seeded["RC_MEMORY_CONTRADICTION"].priority_band, "evidence_context")
        self.assertEqual(seeded["RC_POLICY_LOOP"].priority, 18)
        self.assertEqual(seeded["RC_POLICY_LOOP"].priority_band, "safety")
        self.assertEqual(seeded["RC_BACKEND_CAPABILITY_DEGRADED"].priority, 45)
        self.assertEqual(seeded["RC_BACKEND_CAPABILITY_DEGRADED"].priority_band, "recovery")
        self.assertEqual(seeded["RC_TOOL_PREREQUISITE_MISSING"].priority, 50)
        self.assertEqual(seeded["RC_TOOL_PREREQUISITE_MISSING"].priority_band, "recovery")
        self.assertEqual(seeded["RC_TOOL_REQUEST_FORMAT_INVALID"].priority, 52)
        self.assertEqual(seeded["RC_TOOL_REQUEST_FORMAT_INVALID"].priority_band, "recovery")
        self.assertEqual(seeded["RC_REQUIRED_TOOL_FOLLOWUP_MISSING"].priority, 54)
        self.assertEqual(seeded["RC_REQUIRED_TOOL_FOLLOWUP_MISSING"].priority_band, "recovery")
        self.assertEqual(seeded["RC_REPAIR_REGRESSION"].priority, 65)
        self.assertEqual(seeded["RC_REPAIR_REGRESSION"].priority_band, "repair_quality")
        self.assertEqual(seeded["RC_MAX_ITERATIONS"].priority, 80)
        self.assertEqual(seeded["RC_MAX_ITERATIONS"].priority_band, "resource_limit")
        self.assertEqual(seeded["RC_RESOURCE_LIMIT"].priority, 85)
        self.assertEqual(seeded["RC_RESOURCE_LIMIT"].priority_band, "resource_limit")
        self.assertEqual(seeded["RC_UNKNOWN"].priority, 900)
        self.assertEqual(seeded["RC_UNKNOWN"].priority_band, "fallback")

        self.db.add(
            AgentRootCauseRule(
                rule_id="RC_BAD_BAND",
                reason_key="bad_band",
                root_cause_primary="bad_band",
                causal_chain_json=["bad_band"],
                mitigation_action="fix_rule_priority",
                priority=88,
                priority_band="safety",
                match_expression_json={"any_reasons": ["bad_band"]},
                status="active",
            )
        )
        self.db.commit()

        failed = engine.audit_rule_governance()

        self.assertFalse(failed["governance_pass"])
        self.assertEqual(failed["violation_count"], 1)
        self.assertEqual(failed["violations"][0]["rule_id"], "RC_BAD_BAND")
        self.assertEqual(failed["violations"][0]["violation"], "priority_outside_band")

    def test_root_cause_rule_governance_audit_route_requires_admin(self):
        from app.api.v1.routers.agents import audit_agent_root_cause_rules

        with self.assertRaises(HTTPException) as ctx:
            audit_agent_root_cause_rules(db=self.db, current_user=self.owner)
        self.assertEqual(ctx.exception.status_code, 403)

        self.owner.is_admin = True
        response = audit_agent_root_cause_rules(db=self.db, current_user=self.owner)
        data = response["data"]

        self.assertTrue(data["governance_pass"])
        self.assertEqual(data["violation_count"], 0)
        self.assertGreaterEqual(data["rule_count"], 10)
        self.assertEqual(data["priority_bands"]["safety"]["min"], 1)
        self.assertEqual(data["priority_bands"]["fallback"]["max"], 999)

    def test_high_risk_tool_call_requires_complete_decision_context_build(self):
        run = self._create_run("high risk context gate")
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=self.owner,
            enqueue=False,
        )
        call.resolved_side_effect_class = "business_create"
        self.db.commit()
        AgentWorkerQueueService(self.db).enqueue_tool_call(call)

        result = ToolExecutor(self.db).execute_next(worker_id="worker-context")

        self.assertEqual(result.status, "manual_intervention")
        self.assertEqual(result.error_code, "context_decision_build_required")

    def test_high_risk_tool_call_blocks_when_required_evidence_incomplete(self):
        run = self._create_run("high risk incomplete context")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=128,
                evidence_refs=self._large_evidence_refs(count=10),
                required_evidence_ref_ids=["evidence-9"],
            ),
            current_user=self.owner,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
                decision_context_build_id=build.context_build_id,
            ),
            current_user=self.owner,
            enqueue=False,
        )
        call.resolved_side_effect_class = "business_create"
        self.db.commit()
        AgentWorkerQueueService(self.db).enqueue_tool_call(call)

        result = ToolExecutor(self.db).execute_next(worker_id="worker-context")

        self.assertEqual(result.status, "manual_intervention")
        self.assertEqual(result.error_code, "required_evidence_incomplete_for_high_risk")

    def test_evidence_watch_mark_stale_by_external_ref(self):
        run = self._create_run("evidence stale")
        ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="plan",
                step_index=0,
                token_budget=4000,
                evidence_refs=[
                    {
                        "evidence_ref_id": "scenario-current",
                        "ref_type": "scenario",
                        "ref_id": "scenario-1",
                        "mutability_class": "mutable_current",
                        "dependency_role": "decision_dependency",
                        "active_for_policy": True,
                    }
                ],
            ),
            current_user=self.owner,
        )

        stale_count = EvidenceWatchService(self.db).mark_stale_by_ref(
            ref_type="scenario",
            ref_id="scenario-1",
            stale_reason="scenario.updated",
            stale_event_id="evt-1",
        )
        watch = self.db.scalar(select(AgentEvidenceWatch).where(AgentEvidenceWatch.ref_id == "scenario-1"))

        self.assertEqual(stale_count, 1)
        self.assertEqual(watch.watch_status, "stale")
        self.assertEqual(watch.stale_reason, "scenario.updated")

    def test_agent_loop_routes_are_declared(self):
        from app.main import create_app

        paths = create_app().openapi()["paths"]

        self.assertIn("/api/v1/agents/runs/{run_id}/context-builds", paths)
        self.assertIn("/api/v1/agents/runs/{run_id}/loop-observations", paths)
        self.assertIn("/api/v1/agents/runs/{run_id}/migration-blocks", paths)
        self.assertIn("/api/v1/agents/runs/{run_id}/migration-blocks/{block_id}/resolve", paths)
        self.assertIn("/api/v1/agents/runs/{run_id}/resume", paths)
        self.assertIn("/api/v1/agents/backend-contracts/{backend_name}/operations/{backend_operation}", paths)

    def test_memory_source_profile_sets_source_specific_initial_confidence(self):
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Login rule",
            content="Login tests should include MFA when enabled.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )

        self.assertEqual(memory.status, "active")
        self.assertEqual(memory.confidence, 0.85)
        self.assertEqual(memory.initial_confidence, 0.85)
        self.assertEqual(self.db.query(AgentMemorySourceProfile).count(), 6)
        self.assertEqual(self.db.query(ProjectMemory).count(), 1)

    def test_unknown_memory_source_profile_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            MemoryManager(self.db).create_memory(
                project_id=10,
                memory_type="project_rule",
                title="Unknown",
                content="unknown",
                source_type="mystery_source",
                source_ref_json=None,
                evidence_refs=[],
                current_user=self.owner,
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail["code"], "memory_source_profile_missing")

    def test_memory_retrieval_profile_hard_gate_and_evidence_ref_wrapping(self):
        MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="MFA login",
            content="Login scenarios should validate MFA challenge.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        low_confidence = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Agent guess",
            content="Maybe skip MFA.",
            source_type="agent_summarized",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        low_confidence.status = "active"
        self.db.commit()
        run = self._create_run("memory low confidence filtered")

        candidates = MemoryManager(self.db).retrieve(
            project_id=10,
            query="MFA login",
            profile_name="high_risk_action_v1",
            task_risk="high",
            usage_role="policy_dependency",
            current_user=self.owner,
            run_id=run.run_id,
            limit=10,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source_type, "user_confirmed")
        self.assertEqual(candidates[0].evidence_ref["ref_type"], "memory")
        self.assertTrue(candidates[0].evidence_ref["active_for_policy"])
        self.assertEqual(candidates[0].evidence_ref["dependency_role"], "policy_dependency")
        self.assertEqual(self.db.query(AgentMemoryRetrievalProfile).count(), 4)
        self.assertEqual(self.db.query(AgentMemoryUsageEvent).count(), 1)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        events = [
            item.event_type
            for item in self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        ]
        self.assertEqual(metrics["memory_retrieved_total"], 1)
        self.assertEqual(metrics["memory_used_active_policy_total"], 1)
        self.assertEqual(metrics["memory_low_confidence_filtered_total"], 1)
        self.assertIn("memory.low_confidence_filtered", events)

    def test_harness_memory_retrieval_payload_contract_matches_service(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import retrieve_agent_memories

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Memory retrieval payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Retrieval contract",
            content="Retrieval contract memory should be returned with stable fields.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Memory retrieval payload contract:" in path.read_text(encoding="utf-8")
        ]
        service_candidates = MemoryManager(self.db).retrieve(
            project_id=10,
            query="Retrieval contract",
            profile_name="normal_plan_v1",
            task_risk="normal",
            usage_role="policy_dependency",
            current_user=self.owner,
            limit=1,
        )
        service_payload = memory_candidate_to_payload(service_candidates[0])
        route_payload = retrieve_agent_memories(
            payload=AgentMemoryRetrieveRequest(
                project_id=10,
                query="Retrieval contract",
                profile_name="normal_plan_v1",
                task_risk="normal",
                usage_role="policy_dependency",
                limit=1,
            ),
            db=self.db,
            current_user=self.owner,
        )["data"][0]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["candidate_fields"], list(MEMORY_CANDIDATE_FIELDS))
            self.assertEqual(contract["evidence_ref_fields"], list(MEMORY_CANDIDATE_EVIDENCE_REF_FIELDS))
            self.assertEqual(contract["source"], "MemoryManager.retrieve")
        self.assertEqual(list(AgentMemoryCandidateRead.model_fields), list(MEMORY_CANDIDATE_FIELDS))
        self.assertEqual(list(service_payload), list(MEMORY_CANDIDATE_FIELDS))
        self.assertEqual(list(route_payload), list(MEMORY_CANDIDATE_FIELDS))
        self.assertEqual(list(service_payload["evidence_ref"]), list(MEMORY_CANDIDATE_EVIDENCE_REF_FIELDS))
        self.assertEqual(list(route_payload["evidence_ref"]), list(MEMORY_CANDIDATE_EVIDENCE_REF_FIELDS))
        self.assertEqual(route_payload["memory_id"], service_payload["memory_id"])
        self.assertEqual(route_payload["evidence_ref"]["ref_type"], "memory")
        self.assertTrue(route_payload["evidence_ref"]["active_for_policy"])
        self.assertEqual(route_payload["allowed_usage"], "policy_dependency")

    def test_memory_source_profile_high_risk_allowlist_is_enforced(self):
        from pathlib import Path
        import re

        architecture_text = next(
            path.read_text(encoding="utf-8")
            for path in (Path(__file__).resolve().parents[1] / "docs").glob("*Harness_Loop_Agent*Memory*.md")
            if "| source_type | 初始 confidence |" in path.read_text(encoding="utf-8")
        )
        source_section = architecture_text[
            architecture_text.index("不同来源必须有不同初始置信度："):architecture_text.index("实现要求：")
        ]
        documented_sources = {
            source_type: {
                "default_status": default_status,
                "allowed_for_high_risk": allowed == "true",
            }
            for source_type, _confidence, _authority, default_status, allowed in re.findall(
                r"\|\s*`([^`]+)`\s*\|\s*`([0-9.]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`(true|false)`",
                source_section,
            )
        }
        self.assertEqual(
            documented_sources,
            {
                "user_confirmed": {"default_status": "active", "allowed_for_high_risk": True},
                "execution_learned": {"default_status": "needs_review", "allowed_for_high_risk": True},
                "document_imported": {"default_status": "active", "allowed_for_high_risk": True},
                "agent_summarized": {"default_status": "needs_review", "allowed_for_high_risk": False},
                "repair_inferred": {"default_status": "needs_review", "allowed_for_high_risk": False},
                "external_imported": {"default_status": "needs_review", "allowed_for_high_risk": False},
            },
        )
        MemorySourceProfileResolver(self.db).ensure_defaults()
        source_profiles = {
            item.source_type: item
            for item in self.db.scalars(select(AgentMemorySourceProfile)).all()
        }
        for source_type, expected in documented_sources.items():
            self.assertEqual(source_profiles[source_type].allowed_for_high_risk, expected["allowed_for_high_risk"])
            self.assertEqual(
                source_profiles[source_type].requires_content_hash,
                source_type == "document_imported",
            )

        document_row = next(
            line for line in source_section.splitlines()
            if "`document_imported`" in line
        )
        self.assertIn("requires_content_hash", architecture_text)
        self.assertIn("content_hash", document_row)
        with self.assertRaises(HTTPException) as document_hash_ctx:
            MemoryManager(self.db).create_memory(
                project_id=10,
                memory_type="project_rule",
                title="Document import without hash",
                content="Invalid document import.",
                source_type="document_imported",
                source_ref_json={"document_id": "doc-missing-hash"},
                evidence_refs=[],
                current_user=self.owner,
            )
        self.assertEqual(document_hash_ctx.exception.status_code, 422)
        self.assertEqual(
            document_hash_ctx.exception.detail["code"],
            "document_imported_source_hash_required",
        )
        document_memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Document import with hash",
            content="Valid document import.",
            source_type="document_imported",
            source_ref_json={"document_id": "doc-with-hash", "content_hash": "hash-doc-with-hash"},
            evidence_refs=[],
            current_user=self.owner,
        )
        with self.assertRaises(HTTPException) as document_update_ctx:
            MemoryManager(self.db).update_memory(
                memory_id=document_memory.id,
                source_ref_json={"document_id": "doc-without-hash"},
                current_user=self.owner,
            )
        self.assertEqual(document_update_ctx.exception.status_code, 422)
        self.assertEqual(
            document_update_ctx.exception.detail["code"],
            "document_imported_source_hash_required",
        )
        document_memory.status = "archived"
        self.db.commit()

        with self.assertRaises(HTTPException) as missing_evidence_ctx:
            MemoryManager(self.db).create_memory(
                project_id=10,
                memory_type="project_rule",
                title="Execution learned without enough evidence",
                content="Invalid execution learned rule.",
                source_type="execution_learned",
                source_ref_json={"execution_record_id": "execution-missing-evidence"},
                evidence_refs=self._execution_record_evidence_refs("execution-only-one"),
                current_user=self.owner,
            )
        self.assertEqual(missing_evidence_ctx.exception.status_code, 422)
        self.assertEqual(
            missing_evidence_ctx.exception.detail["code"],
            "execution_learned_requires_two_execution_evidence",
        )
        execution_memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Execution learned rule",
            content="Execution learned rule supports high risk deploy.",
            source_type="execution_learned",
            source_ref_json={"execution_record_id": "execution-allow-1"},
            evidence_refs=self._execution_record_evidence_refs("execution-allow-1", "execution-allow-2"),
            current_user=self.owner,
        )
        external_memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="External imported rule",
            content="External imported rule also mentions high risk deploy.",
            source_type="external_imported",
            source_ref_json={"external_id": "external-1"},
            evidence_refs=[],
            current_user=self.owner,
        )
        validated_execution = MemoryManager(self.db).validate_memory(
            memory_id=execution_memory.id,
            reason="execution evidence verified",
            current_user=self.owner,
        )
        external_memory.status = "active"
        external_memory.confidence = 0.95
        self.db.commit()

        candidates = MemoryManager(self.db).retrieve(
            project_id=10,
            query="high risk deploy",
            profile_name="high_risk_action_v1",
            task_risk="high",
            usage_role="policy_dependency",
            current_user=self.owner,
            limit=10,
        )

        self.assertEqual(validated_execution.status, "active")
        self.assertAlmostEqual(validated_execution.confidence, 0.80)
        self.assertEqual([candidate.memory_id for candidate in candidates], [execution_memory.id])
        self.assertEqual(candidates[0].source_type, "execution_learned")

    def test_memory_retrieval_profile_missing_returns_422(self):
        with self.assertRaises(HTTPException) as ctx:
            MemoryRetrievalProfileResolver(self.db).get(profile_name="missing_profile")

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail["code"], "memory_retrieval_profile_missing")
        run = self._create_run("missing memory retrieval profile")

        with self.assertRaises(HTTPException) as retrieve_ctx:
            MemoryManager(self.db).retrieve(
                project_id=10,
                query="login",
                profile_name="missing_profile",
                task_risk="low",
                usage_role="trace_only",
                current_user=self.owner,
                run_id=run.run_id,
            )
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        events = [item.event_type for item in self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all()]

        self.assertEqual(retrieve_ctx.exception.status_code, 422)
        self.assertEqual(retrieve_ctx.exception.detail["code"], "memory_retrieval_profile_missing")
        self.assertEqual(metrics["memory_retrieval_profile_missing_total"], 1)
        self.assertIn("memory.retrieval_profile_missing", events)

    def test_harness_memory_entity_payload_contract_matches_routes(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import (
            create_agent_memory,
            list_agent_memories,
            reject_agent_memory,
            update_agent_memory,
            validate_agent_memory,
        )

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Memory entity payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Memory entity payload contract:" in path.read_text(encoding="utf-8")
        ]
        create_payload = create_agent_memory(
            payload=AgentMemoryCreateRequest(
                project_id=10,
                memory_type="project_rule",
                title="Entity payload contract",
                content="Entity payload contract should stay stable.",
                source_type="user_confirmed",
                source_ref_json=None,
                evidence_refs=[],
            ),
            db=self.db,
            current_user=self.owner,
        )["data"]
        list_payload = list_agent_memories(project_id=10, db=self.db, current_user=self.owner)["data"][0]
        update_payload = update_agent_memory(
            memory_id=create_payload["id"],
            payload=AgentMemoryUpdateRequest(
                title="Entity payload contract updated",
                content="Entity payload contract should stay stable after update.",
                reason="contract update",
            ),
            db=self.db,
            current_user=self.owner,
        )["data"]
        validate_payload = validate_agent_memory(
            memory_id=create_payload["id"],
            payload=AgentMemoryDecisionRequest(reason="contract validation"),
            db=self.db,
            current_user=self.owner,
        )["data"]
        reject_payload = reject_agent_memory(
            memory_id=create_payload["id"],
            payload=AgentMemoryDecisionRequest(reason="contract rejection"),
            db=self.db,
            current_user=self.owner,
        )["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(MEMORY_ENTITY_FIELDS))
            self.assertEqual(contract["source"], "AgentMemoryRead")
        self.assertEqual(list(AgentMemoryRead.model_fields), list(MEMORY_ENTITY_FIELDS))
        for payload in (create_payload, list_payload, update_payload, validate_payload, reject_payload):
            self.assertEqual(list(payload), list(MEMORY_ENTITY_FIELDS))
            self.assertEqual(payload["project_id"], 10)
            self.assertEqual(payload["source_type"], "user_confirmed")
        self.assertEqual(create_payload["memory_version"], 1)
        self.assertEqual(update_payload["memory_version"], 2)
        self.assertEqual(validate_payload["validation_count"], 1)
        self.assertEqual(validate_payload["status"], "active")
        self.assertEqual(reject_payload["status"], "rejected")
        self.assertLessEqual(reject_payload["confidence"], 0.10)

    def test_memory_patch_bumps_version_and_replaces_evidence_links(self):
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Old title",
            content="Old content",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[
                {
                    "evidence_ref_id": "old-scenario",
                    "ref_type": "scenario",
                    "ref_id": "old",
                    "version_id": "v1",
                    "mutability_class": "versioned",
                    "dependency_role": "audit_background",
                    "active_for_policy": False,
                }
            ],
            current_user=self.owner,
        )

        updated = MemoryManager(self.db).update_memory(
            memory_id=memory.id,
            title="New title",
            content="New content",
            evidence_refs=[
                {
                    "evidence_ref_id": "new-scenario",
                    "ref_type": "scenario",
                    "ref_id": "new",
                    "version_id": "v2",
                    "mutability_class": "versioned",
                    "dependency_role": "audit_background",
                    "active_for_policy": False,
                }
            ],
            reason="manual correction",
            current_user=self.owner,
        )
        links = list(self.db.scalars(select(AgentMemoryEvidenceLink)).all())

        self.assertEqual(updated.memory_version, 2)
        self.assertEqual(updated.title, "New title")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].evidence_ref_id, "new")

    def test_memory_patch_cannot_activate_unvalidated_agent_memory(self):
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Agent draft",
            content="Needs review",
            source_type="agent_summarized",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )

        with self.assertRaises(HTTPException) as ctx:
            MemoryManager(self.db).update_memory(
                memory_id=memory.id,
                status_value="active",
                current_user=self.owner,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "memory_requires_explicit_validation")

    def test_memory_validate_and_reject_apply_governance_state(self):
        from pathlib import Path
        import re

        architecture_text = next(
            path.read_text(encoding="utf-8")
            for path in (Path(__file__).resolve().parents[1] / "docs").glob("*Harness_Loop_Agent*Memory*.md")
            if "15.8 自动降权与验证规则" in path.read_text(encoding="utf-8")
        )
        user_validation_row = re.search(r"\|\s*用户确认正确\s*\|\s*(.*?)\s*\|", architecture_text)
        user_rejection_row = re.search(r"\|\s*memory 被用户明确否定\s*\|\s*(.*?)\s*\|", architecture_text)
        self.assertIsNotNone(user_validation_row)
        self.assertIsNotNone(user_rejection_row)
        self.assertIn("confidence +0.10", user_validation_row.group(1))
        self.assertIn("last_validated_at", user_validation_row.group(1))
        self.assertIn("status=rejected", user_rejection_row.group(1))
        self.assertIn("confidence=min(confidence,0.10)", user_rejection_row.group(1))
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Agent summary",
            content="Candidate",
            source_type="agent_summarized",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        memory.confidence = 0.80
        memory.stale_score = 0.40
        self.db.commit()

        validated = MemoryManager(self.db).validate_memory(
            memory_id=memory.id,
            reason="human checked",
            current_user=self.owner,
        )
        self.assertEqual(validated.status, "active")
        self.assertEqual(validated.validation_count, 1)
        self.assertAlmostEqual(validated.confidence, 0.90)
        self.assertIsNotNone(validated.last_validated_at)
        validation_event = self.db.scalar(
            select(AgentMemoryValidationEvent).where(AgentMemoryValidationEvent.memory_id == memory.id)
        )
        self.assertIsNotNone(validation_event)
        self.assertEqual(validation_event.project_id, 10)
        self.assertEqual(validation_event.validation_source, "user_confirmed")
        self.assertAlmostEqual(validation_event.previous_confidence, 0.80)
        self.assertAlmostEqual(validation_event.new_confidence, 0.90)
        self.assertAlmostEqual(validation_event.previous_stale_score, 0.40)
        self.assertAlmostEqual(validation_event.new_stale_score, 0.15)
        self.assertEqual(validation_event.previous_status, "needs_review")
        self.assertEqual(validation_event.new_status, "active")
        self.assertEqual(validation_event.validation_count, 1)
        low_confidence_memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Low confidence validation candidate",
            content="Candidate should use incremental validation confidence.",
            source_type="agent_summarized",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        low_confidence_memory.confidence = 0.20
        self.db.commit()

        low_confidence_validated = MemoryManager(self.db).validate_memory(
            memory_id=low_confidence_memory.id,
            reason="human checked low confidence candidate",
            current_user=self.owner,
        )
        low_confidence_event = self.db.scalar(
            select(AgentMemoryValidationEvent)
            .where(AgentMemoryValidationEvent.memory_id == low_confidence_memory.id)
        )

        self.assertAlmostEqual(low_confidence_validated.confidence, 0.30)
        self.assertAlmostEqual(low_confidence_event.previous_confidence, 0.20)
        self.assertAlmostEqual(low_confidence_event.new_confidence, 0.30)
        from app.api.v1.routers.agents import list_agent_memory_validation_events

        response = list_agent_memory_validation_events(
            project_id=10,
            validation_source="user_confirmed",
            limit=100,
            db=self.db,
            current_user=self.owner,
        )

        self.assertEqual(len(response["data"]), 2)
        self.assertEqual(
            {item["memory_id"] for item in response["data"]},
            {memory.id, low_confidence_memory.id},
        )
        self.assertEqual(
            {item["validation_source"] for item in response["data"]},
            {"user_confirmed"},
        )
        rejected = MemoryManager(self.db).reject_memory(
            memory_id=memory.id,
            reason="later disproved",
            current_user=self.owner,
        )

        self.assertEqual(rejected.status, "rejected")
        self.assertAlmostEqual(rejected.confidence, 0.10)
        self.assertAlmostEqual(rejected.stale_score, 1.0)
        self.assertEqual(rejected.memory_version, 3)

    def test_rejected_memory_is_not_retrieved_even_with_permissive_profile(self):
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Deprecated deploy rule",
            content="Deployments should use the old staging cluster.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        self.db.add(
            AgentMemoryRetrievalProfile(
                profile_name="status_gate_probe_v1",
                task_scope="audit",
                risk_level="normal",
                min_confidence=0.0,
                max_stale_score=1.0,
                allow_memory_for_high_risk=False,
                semantic_weight=1.0,
                confidence_weight=0.0,
                recency_weight=0.0,
                authority_weight=0.0,
                validation_weight=0.0,
                stale_weight=0.0,
                contradiction_weight=0.0,
                max_contradiction_penalty=1.0,
                change_reason="test rejected status hard gate",
            )
        )
        self.db.commit()

        MemoryManager(self.db).reject_memory(
            memory_id=memory.id,
            reason="user explicitly rejected",
            current_user=self.owner,
        )

        candidates = MemoryManager(self.db).retrieve(
            project_id=10,
            query="old staging cluster deploy",
            profile_name="status_gate_probe_v1",
            task_risk="normal",
            usage_role="audit_context",
            current_user=self.owner,
            limit=10,
        )

        self.assertEqual(candidates, [])
        self.assertEqual(self.db.query(AgentMemoryUsageEvent).count(), 0)

    def test_repair_inferred_requires_execution_validation_before_active(self):
        from pathlib import Path
        import re

        architecture_text = next(
            path.read_text(encoding="utf-8")
            for path in (Path(__file__).resolve().parents[1] / "docs").glob("*Harness_Loop_Agent*Memory*.md")
            if "15.9 Memory 写入边界" in path.read_text(encoding="utf-8")
        )
        repair_row = re.search(r"\|\s*`repair_inferred`\s*\|\s*P2\s*\|\s*(.*?)\s*\|", architecture_text)
        self.assertIsNotNone(repair_row)
        self.assertIn("必须后续执行验证", repair_row.group(1))
        self.assertIn("不得直接 active", repair_row.group(1))

        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Repair inferred rule",
            content="Repair suggests retry after cache refresh.",
            source_type="repair_inferred",
            source_ref_json=None,
            evidence_refs=self._execution_record_evidence_refs("repair-validate-1"),
            current_user=self.owner,
        )
        self.assertEqual(memory.status, "needs_review")

        with self.assertRaises(HTTPException) as direct_ctx:
            MemoryManager(self.db).validate_memory(
                memory_id=memory.id,
                reason="human checked but still needs execution",
                current_user=self.owner,
            )
        self.assertEqual(direct_ctx.exception.status_code, 409)
        self.assertEqual(
            direct_ctx.exception.detail["code"],
            "repair_inferred_requires_execution_validation",
        )

        summary = MemoryFeedbackWorker(self.db).process_execution_record_created(
            execution_record_id="repair-validate-1",
            verdict="validated",
            current_user=self.owner,
            run_id="agent-run-repair-validation",
            tool_call_id="tool-call-repair-validation",
            reason="repair inference was validated by execution",
        )
        refreshed = self.db.get(ProjectMemory, memory.id)
        validation_event = self.db.scalar(
            select(AgentMemoryValidationEvent).where(AgentMemoryValidationEvent.memory_id == memory.id)
        )

        self.assertEqual(summary["validations_recorded"], 1)
        self.assertEqual(summary["results"][0]["decision"], "memory_validated")
        self.assertEqual(refreshed.status, "active")
        self.assertEqual(refreshed.validation_count, 1)
        self.assertIsNotNone(validation_event)
        self.assertEqual(validation_event.validation_source, "execution_record.created")
        self.assertEqual(validation_event.run_id, "agent-run-repair-validation")
        self.assertEqual(validation_event.tool_call_id, "tool-call-repair-validation")

    def test_memory_contradiction_penalty_and_status_update_are_deterministic(self):
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Old rule",
            content="Old behavior",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        profile = MemoryRetrievalProfileResolver(self.db).get(profile_name="repair_v1")
        before = compute_contradiction_penalty(memory=memory, profile=profile)
        MemoryManager(self.db).record_contradiction(
            memory_id=memory.id,
            contradiction_type="execution_mismatch",
            severity="critical",
            current_user=self.owner,
            failure_fingerprint="same-failure",
        )
        refreshed = self.db.get(ProjectMemory, memory.id)
        after = compute_contradiction_penalty(memory=refreshed, profile=profile)
        run = self._create_run("memory contradiction penalty applied")
        candidates = MemoryManager(self.db).retrieve(
            project_id=10,
            query="Old behavior",
            profile_name="normal_plan_v1",
            task_risk="normal",
            usage_role="repair_hint",
            current_user=self.owner,
            run_id=run.run_id,
            limit=10,
        )
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        events = [
            item.event_type
            for item in self.db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
            ).all()
        ]

        self.assertEqual(before, 0.0)
        self.assertGreater(after, 0.0)
        self.assertEqual(refreshed.status, "needs_revalidation")
        self.assertEqual(refreshed.contradiction_count, 1)
        self.assertLess(refreshed.confidence, memory.initial_confidence)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(metrics["memory_contradiction_total"], 1)
        self.assertEqual(metrics["memory_contradiction_penalty_applied_total"], 1)
        self.assertIn("memory.contradiction_penalty_applied", events)

    def test_memory_repeated_same_failure_marks_suspect_from_architecture_contract(self):
        from pathlib import Path
        import re

        architecture_text = next(
            path.read_text(encoding="utf-8")
            for path in (Path(__file__).resolve().parents[1] / "docs").glob("*Harness_Loop_Agent*Memory*.md")
            if "15.8 自动降权与验证规则" in path.read_text(encoding="utf-8")
            and "同一 memory 连续导致相同 failure fingerprint" in path.read_text(encoding="utf-8")
        )
        repeated_failure_row = re.search(
            r"\|\s*同一 memory 连续导致相同 failure fingerprint\s*\|\s*(.*?)\s*\|",
            architecture_text,
        )
        self.assertIsNotNone(repeated_failure_row)
        self.assertIn("status=suspect", repeated_failure_row.group(1))
        self.assertIn("recent_contradiction_count +1", repeated_failure_row.group(1))

        manager = MemoryManager(self.db)
        direct_memory = manager.create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Repeated failure rule",
            content="This memory causes a repeated failure.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        manager.record_contradiction(
            memory_id=direct_memory.id,
            contradiction_type="execution_mismatch",
            severity="medium",
            current_user=self.owner,
            failure_fingerprint="repeat-failure",
        )
        first_direct = self.db.get(ProjectMemory, direct_memory.id)
        first_direct_status = first_direct.status
        manager.record_contradiction(
            memory_id=direct_memory.id,
            contradiction_type="execution_mismatch",
            severity="medium",
            current_user=self.owner,
            failure_fingerprint="repeat-failure",
        )
        second_direct = self.db.get(ProjectMemory, direct_memory.id)

        self.assertEqual(first_direct_status, "active")
        self.assertEqual(second_direct.status, "suspect")
        self.assertEqual(second_direct.recent_contradiction_count, 2)
        self.assertEqual(second_direct.last_failure_fingerprint, "repeat-failure")

        feedback_memory = manager.create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Feedback repeated failure rule",
            content="Feedback contradiction repeats.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        worker = MemoryFeedbackWorker(self.db)
        first_usage = AgentMemoryUsageEvent(
            memory_id=feedback_memory.id,
            retrieval_profile="repair_v1",
            retrieval_score=1.0,
            usage_role="repair_hint",
            active_for_policy=False,
            caused_tool_input_change=False,
            outcome="caused_failure",
            feedback_state="pending",
            feedback_result_json={
                "failure_fingerprint": "feedback-repeat",
                "contradiction_type": "memory_feedback",
                "severity": "medium",
                "reason": "first repeated feedback failure",
            },
        )
        self.db.add(first_usage)
        self.db.commit()
        first_summary = worker.process_due(limit=1, usage_event_id=first_usage.id)
        second_usage = AgentMemoryUsageEvent(
            memory_id=feedback_memory.id,
            retrieval_profile="repair_v1",
            retrieval_score=1.0,
            usage_role="repair_hint",
            active_for_policy=False,
            caused_tool_input_change=False,
            outcome="caused_failure",
            feedback_state="pending",
            feedback_result_json={
                "failure_fingerprint": "feedback-repeat",
                "contradiction_type": "memory_feedback",
                "severity": "medium",
                "reason": "second repeated feedback failure",
            },
        )
        self.db.add(second_usage)
        self.db.commit()
        second_summary = worker.process_due(limit=1, usage_event_id=second_usage.id)
        refreshed_feedback = self.db.get(ProjectMemory, feedback_memory.id)

        self.assertFalse(first_summary["results"][0]["same_failure_repeated"])
        self.assertTrue(second_summary["results"][0]["same_failure_repeated"])
        self.assertEqual(second_summary["results"][0]["memory_status"], "suspect")
        self.assertEqual(refreshed_feedback.status, "suspect")
        self.assertEqual(refreshed_feedback.recent_contradiction_count, 2)

    def test_memory_staleness_worker_updates_linked_memory(self):
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Scenario source",
            content="Use scenario source.",
            source_type="document_imported",
            source_ref_json={"document_id": "doc-1", "content_hash": "hash-doc-1"},
            evidence_refs=[
                {
                    "evidence_ref_id": "scenario-current",
                    "ref_type": "scenario",
                    "ref_id": "scenario-1",
                    "mutability_class": "mutable_current",
                    "dependency_role": "decision_dependency",
                    "active_for_policy": True,
                }
            ],
            current_user=self.owner,
        )

        touched = MemoryStalenessWorker(self.db).mark_memories_stale_for_ref(
            evidence_ref_type="scenario",
            evidence_ref_id="scenario-1",
            stale_reason="scenario.updated",
        )
        refreshed = self.db.get(ProjectMemory, memory.id)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]
        stale_event = self.db.scalar(
            select(AgentMemoryStalenessEvent).where(AgentMemoryStalenessEvent.memory_id == memory.id)
        )

        self.assertEqual(touched, 1)
        self.assertGreater(refreshed.stale_score, 0.0)
        self.assertEqual(refreshed.stale_reason_json["reason"], "scenario.updated")
        self.assertIsNotNone(stale_event)
        self.assertEqual(stale_event.project_id, 10)
        self.assertEqual(stale_event.evidence_ref_type, "scenario")
        self.assertEqual(stale_event.evidence_ref_id, "scenario-1")
        self.assertEqual(stale_event.stale_reason, "scenario.updated")
        self.assertEqual(stale_event.previous_status, "active")
        self.assertEqual(stale_event.new_status, refreshed.status)
        self.assertEqual(stale_event.new_stale_score, refreshed.stale_score)
        self.assertEqual(metrics["memory_evidence_watch_stale_total"], 1)
        from app.api.v1.routers.agents import list_agent_memory_staleness_events

        response = list_agent_memory_staleness_events(
            project_id=10,
            evidence_ref_type="scenario",
            evidence_ref_id="scenario-1",
            limit=100,
            db=self.db,
            current_user=self.owner,
        )

        self.assertEqual(len(response["data"]), 1)
        self.assertEqual(response["data"][0]["memory_id"], memory.id)
        self.assertEqual(response["data"][0]["stale_reason"], "scenario.updated")

    def test_memory_staleness_worker_matches_architecture_external_event_contract(self):
        from pathlib import Path
        import re

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        architecture_text = next(
            path.read_text(encoding="utf-8")
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "外部事件处理表：" in path.read_text(encoding="utf-8")
        )
        table_start = architecture_text.index("外部事件处理表：")
        table_end = architecture_text.index("\n---", table_start)
        table = architecture_text[table_start:table_end]
        stale_events = {
            "scenario.updated": "scenario",
            "testcase.updated": "testcase",
            "environment.updated": "environment",
            "manifest.changed": "manifest",
            "document.updated": "document",
            "report.updated": "report",
            "report.deleted": "report",
            "report.regenerated": "report",
        }
        documented_contract = {}
        for event_name, action in re.findall(r"\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|", table):
            if event_name not in stale_events:
                continue
            delta_match = re.search(r"stale_score \+([0-9.]+)", action)
            self.assertIsNotNone(delta_match, event_name)
            documented_contract[event_name] = {
                "ref_type": stale_events[event_name],
                "delta": float(delta_match.group(1)),
                "requires_revalidation": (
                    "并进入 `needs_revalidation`" in action
                    or "必须进入 `needs_revalidation`" in action
                ),
            }

        self.assertEqual(set(documented_contract), set(stale_events))
        for event_name, expected in documented_contract.items():
            with self.subTest(event_name=event_name):
                ref_type = expected["ref_type"]
                ref_id = f"{ref_type}-{event_name}"
                memory = MemoryManager(self.db).create_memory(
                    project_id=10,
                    memory_type="project_rule",
                    title=f"{event_name} source",
                    content=f"Use {event_name} source.",
                    source_type="document_imported",
                    source_ref_json={
                        "document_id": f"doc-{event_name}",
                        "content_hash": f"hash-doc-{event_name}",
                    },
                    evidence_refs=[
                        {
                            "evidence_ref_id": f"{ref_type}-current-{event_name}",
                            "ref_type": ref_type,
                            "ref_id": ref_id,
                            "mutability_class": "mutable_current",
                            "dependency_role": "decision_dependency",
                            "active_for_policy": True,
                        }
                    ],
                    current_user=self.owner,
                )

                touched = MemoryStalenessWorker(self.db).mark_memories_stale_for_ref(
                    evidence_ref_type=ref_type,
                    evidence_ref_id=ref_id,
                    stale_reason=event_name,
                )
                refreshed = self.db.get(ProjectMemory, memory.id)
                stale_event = self.db.scalar(
                    select(AgentMemoryStalenessEvent).where(AgentMemoryStalenessEvent.memory_id == memory.id)
                )

                self.assertEqual(touched, 1)
                self.assertEqual(refreshed.stale_score, expected["delta"])
                self.assertEqual(refreshed.stale_reason_json["reason"], event_name)
                self.assertIsNotNone(stale_event)
                self.assertEqual(stale_event.previous_stale_score, 0.0)
                self.assertEqual(stale_event.new_stale_score, expected["delta"])
                if expected["requires_revalidation"]:
                    self.assertEqual(refreshed.status, "needs_revalidation")
                    self.assertEqual(stale_event.new_status, "needs_revalidation")

    def test_memory_staleness_worker_rejects_non_stale_platform_events(self):
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Non stale event guard",
            content="Permission and execution events must not become stale events.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[
                {
                    "evidence_ref_id": "execution-record-non-stale",
                    "ref_type": "execution_record",
                    "ref_id": "execution-non-stale",
                    "mutability_class": "immutable",
                    "dependency_role": "decision_dependency",
                    "active_for_policy": True,
                    "content_hash": "hash-execution-non-stale",
                }
            ],
            current_user=self.owner,
        )
        before_score = memory.stale_score
        before_status = memory.status

        for event_name in ["execution_record.created", "permission.changed", "memory.status_changed"]:
            with self.subTest(event_name=event_name):
                with self.assertRaises(HTTPException) as ctx:
                    MemoryStalenessWorker(self.db).mark_memories_stale_for_ref(
                        evidence_ref_type="execution_record",
                        evidence_ref_id="execution-non-stale",
                        stale_reason=event_name,
                    )
                self.assertEqual(ctx.exception.status_code, 422)
                self.assertEqual(ctx.exception.detail["code"], "memory_event_not_stale_event")
                self.assertEqual(ctx.exception.detail["event_type"], event_name)

        refreshed = self.db.get(ProjectMemory, memory.id)
        stale_events = self.db.scalars(
            select(AgentMemoryStalenessEvent).where(AgentMemoryStalenessEvent.memory_id == memory.id)
        ).all()
        self.assertEqual(refreshed.stale_score, before_score)
        self.assertEqual(refreshed.status, before_status)
        self.assertEqual(stale_events, [])

    def test_environment_stale_memory_is_filtered_for_high_risk_profile(self):
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Environment source",
            content="Use environment-specific rule.",
            source_type="document_imported",
            source_ref_json={"document_id": "doc-env", "content_hash": "hash-doc-env"},
            evidence_refs=[
                {
                    "evidence_ref_id": "environment-current",
                    "ref_type": "environment",
                    "ref_id": "environment-20",
                    "mutability_class": "mutable_current",
                    "dependency_role": "decision_dependency",
                    "active_for_policy": True,
                }
            ],
            current_user=self.owner,
        )

        touched = MemoryStalenessWorker(self.db).mark_memories_stale_for_ref(
            evidence_ref_type="environment",
            evidence_ref_id="environment-20",
            stale_reason="environment.updated",
        )
        candidates = MemoryManager(self.db).retrieve(
            project_id=10,
            query="environment-specific rule",
            profile_name="high_risk_action_v1",
            task_risk="high",
            usage_role="policy_dependency",
            current_user=self.owner,
            limit=10,
        )
        refreshed = self.db.get(ProjectMemory, memory.id)
        stale_event = self.db.scalar(
            select(AgentMemoryStalenessEvent).where(AgentMemoryStalenessEvent.memory_id == memory.id)
        )

        self.assertEqual(touched, 1)
        self.assertEqual(candidates, [])
        self.assertEqual(refreshed.status, "needs_revalidation")
        self.assertEqual(refreshed.stale_reason_json["reason"], "environment.updated")
        self.assertEqual(refreshed.stale_score, 0.30)
        self.assertIsNotNone(stale_event)
        self.assertEqual(stale_event.previous_status, "active")
        self.assertEqual(stale_event.new_status, "needs_revalidation")

    def test_memory_feedback_worker_applies_positive_usage_once(self):
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Stable project rule",
            content="Always validate MFA.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        memory.confidence = 0.80
        memory.stale_score = 0.20
        self.db.commit()
        MemoryManager(self.db).retrieve(
            project_id=10,
            query="validate MFA",
            profile_name="normal_plan_v1",
            task_risk="normal",
            usage_role="policy_dependency",
            current_user=self.owner,
            limit=1,
        )
        usage = self.db.scalar(select(AgentMemoryUsageEvent).where(AgentMemoryUsageEvent.memory_id == memory.id))

        summary = MemoryFeedbackWorker(self.db).record_usage_feedback(
            usage_event_id=usage.id,
            outcome="succeeded",
            caused_tool_input_change=True,
            current_user=self.owner,
            reason="execution succeeded with this rule",
        )
        repeated = MemoryFeedbackWorker(self.db).process_due(limit=10)
        refreshed = self.db.get(ProjectMemory, memory.id)
        refreshed_usage = self.db.get(AgentMemoryUsageEvent, usage.id)

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(repeated["attempted"], 0)
        self.assertEqual(refreshed_usage.feedback_state, "processed")
        self.assertEqual(refreshed_usage.feedback_result_json["decision"], "confidence_adjusted")
        self.assertGreater(refreshed.confidence, 0.80)
        self.assertLess(refreshed.stale_score, 0.20)

    def test_memory_feedback_worker_records_contradiction_and_marks_revalidation(self):
        from pathlib import Path
        import re

        architecture_text = next(
            path.read_text(encoding="utf-8")
            for path in (Path(__file__).resolve().parents[1] / "docs").glob("*Harness_Loop_Agent*Memory*.md")
            if "15.8 自动降权与验证规则" in path.read_text(encoding="utf-8")
        )
        contradiction_row = re.search(
            r"\|\s*memory 被用于 Plan/Repair 后被 execution evidence 证明错误\s*\|\s*(.*?)\s*\|",
            architecture_text,
        )
        self.assertIsNotNone(contradiction_row)
        self.assertIn("confidence -0.15", contradiction_row.group(1))
        self.assertIn("stale_score +0.25", contradiction_row.group(1))
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Wrong rule",
            content="Skip MFA for admin users.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        MemoryManager(self.db).retrieve(
            project_id=10,
            query="admin MFA",
            profile_name="normal_plan_v1",
            task_risk="normal",
            usage_role="policy_dependency",
            current_user=self.owner,
            limit=1,
        )
        usage = self.db.scalar(select(AgentMemoryUsageEvent).where(AgentMemoryUsageEvent.memory_id == memory.id))

        summary = MemoryFeedbackWorker(self.db).record_usage_feedback(
            usage_event_id=usage.id,
            outcome="caused_failure",
            caused_tool_input_change=True,
            failure_fingerprint="mfa-admin-failure",
            contradiction_type="execution_mismatch",
            severity="critical",
            reason="backend required MFA",
            current_user=self.owner,
        )
        refreshed = self.db.get(ProjectMemory, memory.id)
        contradiction = self.db.scalar(select(AgentMemoryContradictionEvent).where(
            AgentMemoryContradictionEvent.memory_id == memory.id
        ))

        self.assertEqual(summary["contradictions_recorded"], 1)
        self.assertAlmostEqual(summary["results"][0]["confidence_delta"], -0.15)
        self.assertAlmostEqual(summary["results"][0]["stale_delta"], 0.25)
        self.assertEqual(refreshed.status, "needs_revalidation")
        self.assertEqual(refreshed.contradiction_count, 1)
        self.assertLess(refreshed.confidence, memory.initial_confidence)
        self.assertEqual(contradiction.failure_fingerprint, "mfa-admin-failure")

    def test_memory_feedback_worker_batch_processes_stale_outcome(self):
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Mutable rule",
            content="Depends on mutable scenario.",
            source_type="document_imported",
            source_ref_json={"document_id": "doc-1", "content_hash": "hash-doc-1"},
            evidence_refs=[],
            current_user=self.owner,
        )
        MemoryManager(self.db).retrieve(
            project_id=10,
            query="mutable scenario",
            profile_name="normal_plan_v1",
            task_risk="normal",
            usage_role="policy_dependency",
            current_user=self.owner,
            limit=1,
        )
        usage = self.db.scalar(select(AgentMemoryUsageEvent).where(AgentMemoryUsageEvent.memory_id == memory.id))
        usage.outcome = "stale"
        self.db.commit()

        summary = MemoryFeedbackWorker(self.db).process_due(limit=10)
        refreshed = self.db.get(ProjectMemory, memory.id)

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(refreshed.status, "needs_revalidation")
        self.assertEqual(refreshed.stale_reason_json["reason"], "memory_feedback.stale")

    def test_harness_memory_feedback_process_payload_contract_matches_service(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import process_agent_memory_feedback, record_agent_memory_usage_feedback
        from app.schemas.agent import AgentMemoryFeedbackRequest

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Memory feedback process payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        def _create_usage_for_feedback(title: str) -> AgentMemoryUsageEvent:
            memory = MemoryManager(self.db).create_memory(
                project_id=10,
                memory_type="project_rule",
                title=title,
                content=f"{title} must be validated by feedback.",
                source_type="user_confirmed",
                source_ref_json=None,
                evidence_refs=[],
                current_user=self.owner,
            )
            MemoryManager(self.db).retrieve(
                project_id=10,
                query=title,
                profile_name="normal_plan_v1",
                task_risk="normal",
                usage_role="policy_dependency",
                current_user=self.owner,
                limit=1,
            )
            usage = self.db.scalar(
                select(AgentMemoryUsageEvent)
                .where(AgentMemoryUsageEvent.memory_id == memory.id)
                .order_by(AgentMemoryUsageEvent.id.desc())
            )
            self.assertIsNotNone(usage)
            return usage

        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Memory feedback process payload contract:" in path.read_text(encoding="utf-8")
        ]
        usage_for_service = _create_usage_for_feedback("Service feedback contract")
        usage_for_service.outcome = "validated"
        usage_for_service.feedback_state = "pending"
        usage_for_service.feedback_result_json = {"reason": "service contract validation"}
        self.db.commit()
        service_summary = MemoryFeedbackWorker(self.db).process_due(limit=10)

        usage_for_record_route = _create_usage_for_feedback("Record route feedback contract")
        record_route_payload = record_agent_memory_usage_feedback(
            usage_event_id=usage_for_record_route.id,
            payload=AgentMemoryFeedbackRequest(outcome="validated", reason="route contract validation"),
            db=self.db,
            current_user=self.owner,
        )["data"]

        usage_for_process_route = _create_usage_for_feedback("Process route feedback contract")
        usage_for_process_route.outcome = "validated"
        usage_for_process_route.feedback_state = "pending"
        usage_for_process_route.feedback_result_json = {"reason": "process route contract validation"}
        self.db.commit()
        process_route_payload = process_agent_memory_feedback(limit=10, db=self.db, current_user=self.admin)["data"]

        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(MEMORY_FEEDBACK_PROCESS_FIELDS))
            self.assertEqual(contract["result_base_fields"], list(MEMORY_FEEDBACK_RESULT_BASE_FIELDS))
            self.assertEqual(contract["source"], "MemoryFeedbackWorker.process_due")
        self.assertEqual(list(AgentMemoryFeedbackProcessRead.model_fields), list(MEMORY_FEEDBACK_PROCESS_FIELDS))
        self.assertEqual(list(service_summary), list(MEMORY_FEEDBACK_PROCESS_FIELDS))
        self.assertEqual(list(record_route_payload), list(MEMORY_FEEDBACK_PROCESS_FIELDS))
        self.assertEqual(list(process_route_payload), list(MEMORY_FEEDBACK_PROCESS_FIELDS))
        for payload in (service_summary, record_route_payload, process_route_payload):
            self.assertEqual(payload["validations_recorded"], 1)
            self.assertEqual(list(payload["results"][0])[: len(MEMORY_FEEDBACK_RESULT_BASE_FIELDS)], list(MEMORY_FEEDBACK_RESULT_BASE_FIELDS))
            self.assertEqual(payload["results"][0]["decision"], "memory_validated")

    def test_memory_maintenance_worker_marks_unvalidated_expired_ttl_for_revalidation(self):
        expired = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Expired unvalidated rule",
            content="Needs execution evidence before reuse.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        validated = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Expired validated rule",
            content="Already has execution validation.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[],
            current_user=self.owner,
        )
        expired.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        expired.stale_score = 0.75
        validated.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        validated.validation_count = 1
        validated.recent_validation_count = 1
        validated.stale_score = 0.75
        self.db.commit()

        summary = MemoryMaintenanceWorker(self.db).process_expired_ttl(project_id=10, limit=10)
        refreshed_expired = self.db.get(ProjectMemory, expired.id)
        refreshed_validated = self.db.get(ProjectMemory, validated.id)
        metrics = AgentMetricsService(self.db).snapshot(project_id=10)["metrics"]

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["results"][0]["memory_id"], expired.id)
        self.assertEqual(refreshed_expired.status, "needs_revalidation")
        self.assertAlmostEqual(refreshed_expired.stale_score, 0.85)
        self.assertEqual(refreshed_expired.stale_reason_json["reason"], "memory_ttl.expired")
        self.assertEqual(refreshed_validated.status, "active")
        self.assertAlmostEqual(refreshed_validated.stale_score, 0.75)
        self.assertEqual(metrics["memory_needs_revalidation_total"], 1)

    def test_execution_record_created_validates_or_contradicts_linked_memory(self):
        from pathlib import Path
        import re

        architecture_text = next(
            path.read_text(encoding="utf-8")
            for path in (Path(__file__).resolve().parents[1] / "docs").glob("*Harness_Loop_Agent*Memory*.md")
            if "外部事件处理表：" in path.read_text(encoding="utf-8")
        )
        event_row = re.search(r"\|\s*`execution_record\.created`\s*\|\s*(.*?)\s*\|", architecture_text)
        self.assertIsNotNone(event_row)
        self.assertIn("validation/contradiction event", event_row.group(1))
        validation_rule_row = re.search(r"\|\s*多次 execution evidence 验证正确\s*\|\s*(.*?)\s*\|", architecture_text)
        self.assertIsNotNone(validation_rule_row)
        self.assertIn("confidence +0.05", validation_rule_row.group(1))
        self.assertIn("stale_score -0.10", validation_rule_row.group(1))
        worker = MemoryFeedbackWorker(self.db)
        validated_memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Learned execution rule",
            content="Execution confirms MFA is required.",
            source_type="execution_learned",
            source_ref_json={"execution_record_id": "execution-validate-1"},
            evidence_refs=self._execution_record_evidence_refs("execution-validate-1", "execution-validate-2"),
            current_user=self.owner,
        )
        validated_memory.stale_score = 0.35
        contradicted_memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Wrong execution rule",
            content="Execution says admin MFA can be skipped.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[
                {
                    "evidence_ref_id": "execution-record-contradict",
                    "ref_type": "execution_record",
                    "ref_id": "execution-contradict-1",
                    "version_id": "v1",
                    "content_hash": "hash-execution-contradict",
                    "mutability_class": "immutable",
                    "dependency_role": "decision_dependency",
                    "active_for_policy": True,
                }
            ],
            current_user=self.owner,
        )
        self.db.commit()

        validated = worker.process_execution_record_created(
            execution_record_id="execution-validate-1",
            verdict="validated",
            current_user=self.owner,
            run_id="agent-run-memory-validation",
            tool_call_id="tool-call-validation",
            reason="execution output supports the memory",
        )
        contradicted = worker.process_execution_record_created(
            execution_record_id="execution-contradict-1",
            verdict="contradicted",
            current_user=self.owner,
            run_id="agent-run-memory-contradiction",
            tool_call_id="tool-call-contradiction",
            failure_fingerprint="execution-contradiction-fp",
            severity="critical",
            reason="execution output refutes the memory",
        )
        refreshed_validated = self.db.get(ProjectMemory, validated_memory.id)
        refreshed_contradicted = self.db.get(ProjectMemory, contradicted_memory.id)
        contradiction = self.db.scalar(
            select(AgentMemoryContradictionEvent).where(
                AgentMemoryContradictionEvent.memory_id == contradicted_memory.id
            )
        )
        validation_event = self.db.scalar(
            select(AgentMemoryValidationEvent).where(
                AgentMemoryValidationEvent.memory_id == validated_memory.id
            )
        )

        self.assertEqual(validated["processed"], 1)
        self.assertEqual(validated["validations_recorded"], 1)
        self.assertEqual(validated["results"][0]["decision"], "memory_validated")
        self.assertAlmostEqual(validated["results"][0]["confidence_delta"], 0.05)
        self.assertAlmostEqual(validated["results"][0]["stale_delta"], -0.10)
        self.assertEqual(refreshed_validated.status, "active")
        self.assertEqual(refreshed_validated.validation_count, 1)
        self.assertEqual(refreshed_validated.recent_validation_count, 1)
        self.assertEqual(refreshed_validated.memory_version, 2)
        self.assertAlmostEqual(refreshed_validated.stale_score, 0.25)
        self.assertEqual(
            refreshed_validated.confidence_reason_json["last_validation_source"],
            "execution_record.created",
        )
        self.assertGreater(refreshed_validated.confidence, refreshed_validated.initial_confidence)
        self.assertEqual(contradicted["processed"], 1)
        self.assertEqual(contradicted["contradictions_recorded"], 1)
        self.assertEqual(contradicted["results"][0]["decision"], "contradiction_recorded")
        self.assertEqual(refreshed_contradicted.status, "needs_revalidation")
        self.assertEqual(refreshed_contradicted.contradiction_count, 1)
        self.assertIsNotNone(contradiction)
        self.assertEqual(contradiction.contradiction_type, "execution_record_created")
        self.assertEqual(contradiction.failure_fingerprint, "execution-contradiction-fp")
        self.assertEqual(contradiction.evidence_ref_json["ref_id"], "execution-contradict-1")
        self.assertIsNotNone(validation_event)
        self.assertEqual(validation_event.validation_source, "execution_record.created")
        self.assertEqual(validation_event.run_id, "agent-run-memory-validation")
        self.assertEqual(validation_event.tool_call_id, "tool-call-validation")
        self.assertIsNotNone(validation_event.usage_event_id)
        self.assertEqual(validation_event.evidence_ref_json["ref_id"], "execution-validate-1")
        self.assertAlmostEqual(validation_event.previous_stale_score, 0.35)
        self.assertAlmostEqual(validation_event.new_stale_score, 0.25)
        self.assertEqual(validation_event.validation_count, 1)

    def test_high_risk_tool_call_cannot_depend_only_on_memory(self):
        run = self._create_run("memory-only high risk")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[
                    {
                        "evidence_ref_id": "memory:1:v1",
                        "ref_type": "memory",
                        "ref_id": "1",
                        "mutability_class": "mutable_current",
                        "dependency_role": "policy_dependency",
                        "active_for_policy": True,
                        "authority": "memory:user_confirmed",
                    }
                ],
                required_evidence_ref_ids=["memory:1:v1"],
            ),
            current_user=self.owner,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
                decision_context_build_id=build.context_build_id,
                evidence_refs=[
                    {
                        "evidence_ref_id": "memory:1:v1",
                        "ref_type": "memory",
                        "ref_id": "1",
                        "mutability_class": "mutable_current",
                        "dependency_role": "policy_dependency",
                        "active_for_policy": True,
                        "authority": "memory:user_confirmed",
                    }
                ],
            ),
            current_user=self.owner,
            enqueue=False,
        )
        call.resolved_side_effect_class = "business_create"
        self.db.commit()
        AgentWorkerQueueService(self.db).enqueue_tool_call(call)

        result = ToolExecutor(self.db).execute_next(worker_id="worker-memory")

        self.assertEqual(result.status, "manual_intervention")
        self.assertEqual(result.error_code, "high_risk_action_cannot_depend_only_on_memory")

    def test_high_risk_memory_evidence_requires_trusted_non_memory_support(self):
        from pathlib import Path

        development_plan = next(
            path.read_text(encoding="utf-8")
            for path in (Path(__file__).resolve().parents[1] / "docs").glob("*Harness_Loop_Agent*Memory*.md")
            if "冻结或可重验证据支撑" in path.read_text(encoding="utf-8")
        )
        self.assertIn("不能靠任意非 memory 引用绕过", development_plan)
        self.assertIn("冻结或可重验证据支撑", development_plan)
        run = self._create_run("memory plus untrusted high risk")
        refs = [
            {
                "evidence_ref_id": "memory:1:v1",
                "ref_type": "memory",
                "ref_id": "1",
                "mutability_class": "mutable_current",
                "dependency_role": "policy_dependency",
                "active_for_policy": True,
                "authority": "memory:user_confirmed",
            },
            {
                "evidence_ref_id": "external-doc-current",
                "ref_type": "external_doc",
                "ref_id": "https://example.test/spec",
                "mutability_class": "external_uncontrolled",
                "dependency_role": "decision_dependency",
                "active_for_policy": True,
                "authority": "external",
            },
        ]
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=refs,
                required_evidence_ref_ids=["external-doc-current"],
            ),
            current_user=self.owner,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
                decision_context_build_id=build.context_build_id,
                evidence_refs=refs,
            ),
            current_user=self.owner,
            enqueue=False,
        )
        call.resolved_side_effect_class = "business_create"
        self.db.commit()

        with self.assertRaises(HTTPException) as ctx:
            PolicyManager(self.db).ensure_context_allows_execution(call=call)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "high_risk_action_cannot_depend_only_on_memory")

    def test_high_risk_action_requires_at_least_one_trusted_policy_ref(self):
        run = self._create_run("high risk empty policy refs")
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=[],
                required_evidence_ref_ids=[],
            ),
            current_user=self.owner,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
                decision_context_build_id=build.context_build_id,
                evidence_refs=[],
            ),
            current_user=self.owner,
            enqueue=False,
        )
        call.resolved_side_effect_class = "business_create"
        self.db.commit()

        with self.assertRaises(HTTPException) as ctx:
            PolicyManager(self.db).ensure_context_allows_execution(call=call)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "high_risk_action_cannot_depend_only_on_memory")

    def test_high_risk_memory_evidence_requires_frozen_or_revalidatable_trusted_support(self):
        run = self._create_run("memory plus mutable trusted high risk")
        refs = [
            {
                "evidence_ref_id": "memory:1:v1",
                "ref_type": "memory",
                "ref_id": "1",
                "mutability_class": "mutable_current",
                "dependency_role": "policy_dependency",
                "active_for_policy": True,
                "authority": "memory:user_confirmed",
            },
            {
                "evidence_ref_id": "execution-record-mutable",
                "ref_type": "execution_record",
                "ref_id": "execution-mutable",
                "mutability_class": "mutable_current",
                "dependency_role": "decision_dependency",
                "active_for_policy": True,
                "authority": "system_record",
            },
        ]
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=refs,
                required_evidence_ref_ids=["execution-record-mutable"],
            ),
            current_user=self.owner,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
                decision_context_build_id=build.context_build_id,
                evidence_refs=refs,
            ),
            current_user=self.owner,
            enqueue=False,
        )
        call.resolved_side_effect_class = "business_create"
        self.db.commit()

        with self.assertRaises(HTTPException) as ctx:
            PolicyManager(self.db).ensure_context_allows_execution(call=call)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "high_risk_action_cannot_depend_only_on_memory")

    def test_high_risk_memory_evidence_allows_trusted_execution_record_support(self):
        run = self._create_run("memory plus trusted high risk")
        refs = [
            {
                "evidence_ref_id": "memory:1:v1",
                "ref_type": "memory",
                "ref_id": "1",
                "mutability_class": "mutable_current",
                "dependency_role": "policy_dependency",
                "active_for_policy": True,
                "authority": "memory:user_confirmed",
            },
            {
                "evidence_ref_id": "execution-record-1",
                "ref_type": "execution_record",
                "ref_id": "execution-1",
                "mutability_class": "immutable",
                "dependency_role": "decision_dependency",
                "active_for_policy": True,
                "authority": "system_record",
                "content_hash": "hash-execution-1",
            },
        ]
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=refs,
                required_evidence_ref_ids=["execution-record-1"],
            ),
            current_user=self.owner,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
                decision_context_build_id=build.context_build_id,
                evidence_refs=refs,
            ),
            current_user=self.owner,
            enqueue=False,
        )
        call.resolved_side_effect_class = "business_create"
        self.db.commit()

        PolicyManager(self.db).ensure_context_allows_execution(call=call)

    def test_high_risk_memory_evidence_allows_revalidatable_trusted_support(self):
        run = self._create_run("memory plus revalidatable high risk")
        refs = [
            {
                "evidence_ref_id": "memory:1:v1",
                "ref_type": "memory",
                "ref_id": "1",
                "mutability_class": "mutable_current",
                "dependency_role": "policy_dependency",
                "active_for_policy": True,
                "authority": "memory:user_confirmed",
            },
            {
                "evidence_ref_id": "execution-record-revalidatable",
                "ref_type": "execution_record",
                "ref_id": "execution-revalidatable",
                "mutability_class": "mutable_current",
                "dependency_role": "decision_dependency",
                "active_for_policy": True,
                "authority": "system_record",
                "freshness_policy": "revalidate_before_side_effect",
            },
        ]
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=0,
                token_budget=4000,
                evidence_refs=refs,
                required_evidence_ref_ids=["execution-record-revalidatable"],
            ),
            current_user=self.owner,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
                decision_context_build_id=build.context_build_id,
                evidence_refs=refs,
            ),
            current_user=self.owner,
            enqueue=False,
        )
        call.resolved_side_effect_class = "business_create"
        self.db.commit()

        PolicyManager(self.db).ensure_context_allows_execution(call=call)

    def test_agent_memory_routes_are_declared(self):
        from app.main import create_app

        paths = create_app().openapi()["paths"]

        self.assertIn("/api/v1/agents/memories", paths)
        self.assertIn("/api/v1/agents/memories/{memory_id}", paths)
        self.assertIn("/api/v1/agents/memories/{memory_id}/validate", paths)
        self.assertIn("/api/v1/agents/memories/{memory_id}/reject", paths)
        self.assertIn("/api/v1/agents/memories/retrieve", paths)
        self.assertIn("/api/v1/agents/memory-retrieval-profiles", paths)
        self.assertIn("/api/v1/agents/memory-usage-events", paths)
        self.assertIn("/api/v1/agents/memory-staleness-events", paths)
        self.assertIn("/api/v1/agents/memory-validation-events", paths)
        self.assertIn("/api/v1/agents/memory-usage-events/{usage_event_id}/feedback", paths)
        self.assertIn("/api/v1/agents/memory-feedback/process", paths)

    def test_memory_usage_events_route_scopes_global_and_run_access(self):
        from app.api.v1.routers.agents import list_agent_memory_usage_events

        outsider = User(
            id=4,
            username="outsider",
            account="outsider",
            password_hash="x",
            phone="10000000004",
            email="outsider@example.test",
            is_admin=False,
        )
        self.db.add(outsider)
        run = self._create_run("memory usage route scope")
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Scoped usage memory",
            content="Only project members should read run-scoped usage.",
            source_type="user_confirmed",
            source_ref_json={"note": "usage-route-scope"},
            evidence_refs=[],
            current_user=self.owner,
        )
        usage = AgentMemoryUsageEvent(
            memory_id=memory.id,
            run_id=run.run_id,
            retrieval_profile="repair_v1",
            retrieval_score=0.91,
            usage_role="repair_hint",
            active_for_policy=False,
            caused_tool_input_change=False,
        )
        self.db.add(usage)
        self.db.commit()

        with self.assertRaises(HTTPException) as owner_global_ctx:
            list_agent_memory_usage_events(db=self.db, current_user=self.owner)
        with self.assertRaises(HTTPException) as outsider_run_ctx:
            list_agent_memory_usage_events(run_id=run.run_id, db=self.db, current_user=outsider)

        admin_global = list_agent_memory_usage_events(db=self.db, current_user=self.admin)
        member_scoped = list_agent_memory_usage_events(run_id=run.run_id, db=self.db, current_user=self.member)

        self.assertEqual(owner_global_ctx.exception.status_code, 403)
        self.assertEqual(outsider_run_ctx.exception.status_code, 403)
        self.assertEqual(len(admin_global["data"]), 1)
        self.assertEqual(len(member_scoped["data"]), 1)
        self.assertEqual(admin_global["data"][0]["run_id"], run.run_id)
        self.assertEqual(member_scoped["data"][0]["run_id"], run.run_id)

    def test_memory_audit_event_routes_scope_global_project_and_memory_access(self):
        from app.api.v1.routers.agents import (
            list_agent_memory_staleness_events,
            list_agent_memory_validation_events,
        )

        outsider = User(
            id=4,
            username="outsider",
            account="outsider",
            password_hash="x",
            phone="10000000004",
            email="outsider@example.test",
            is_admin=False,
        )
        self.db.add(outsider)
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Scoped audit memory",
            content="Only project members should read scoped audit events.",
            source_type="user_confirmed",
            source_ref_json={"note": "audit-route-scope"},
            evidence_refs=[],
            current_user=self.owner,
        )
        self.db.add_all([
            AgentMemoryStalenessEvent(
                project_id=10,
                memory_id=memory.id,
                evidence_ref_type="scenario",
                evidence_ref_id="scenario-route-scope",
                stale_reason="scenario.updated",
                previous_stale_score=0.20,
                new_stale_score=0.50,
                previous_status="active",
                new_status="needs_revalidation",
            ),
            AgentMemoryValidationEvent(
                project_id=10,
                memory_id=memory.id,
                validation_source="user_confirmed",
                evidence_ref_json={"ref_type": "execution_record", "ref_id": "execution-route-scope"},
                reason="route scope validation",
                previous_confidence=0.70,
                new_confidence=0.80,
                previous_stale_score=0.20,
                new_stale_score=0.10,
                previous_status="needs_review",
                new_status="active",
                validation_count=1,
            ),
        ])
        self.db.commit()

        with self.assertRaises(HTTPException) as owner_global_stale_ctx:
            list_agent_memory_staleness_events(limit=100, db=self.db, current_user=self.owner)
        with self.assertRaises(HTTPException) as owner_global_validation_ctx:
            list_agent_memory_validation_events(limit=100, db=self.db, current_user=self.owner)
        with self.assertRaises(HTTPException) as outsider_project_stale_ctx:
            list_agent_memory_staleness_events(project_id=10, limit=100, db=self.db, current_user=outsider)
        with self.assertRaises(HTTPException) as outsider_memory_validation_ctx:
            list_agent_memory_validation_events(memory_id=memory.id, limit=100, db=self.db, current_user=outsider)

        admin_stale = list_agent_memory_staleness_events(limit=100, db=self.db, current_user=self.admin)
        owner_project_stale = list_agent_memory_staleness_events(
            project_id=10,
            evidence_ref_type="scenario",
            evidence_ref_id="scenario-route-scope",
            limit=100,
            db=self.db,
            current_user=self.owner,
        )
        admin_validation = list_agent_memory_validation_events(limit=100, db=self.db, current_user=self.admin)
        member_memory_validation = list_agent_memory_validation_events(
            memory_id=memory.id,
            validation_source="user_confirmed",
            limit=100,
            db=self.db,
            current_user=self.member,
        )

        self.assertEqual(owner_global_stale_ctx.exception.status_code, 403)
        self.assertEqual(owner_global_validation_ctx.exception.status_code, 403)
        self.assertEqual(outsider_project_stale_ctx.exception.status_code, 403)
        self.assertEqual(outsider_memory_validation_ctx.exception.status_code, 403)
        self.assertEqual(admin_stale["data"][0]["memory_id"], memory.id)
        self.assertEqual(owner_project_stale["data"][0]["evidence_ref_id"], "scenario-route-scope")
        self.assertEqual(admin_validation["data"][0]["memory_id"], memory.id)
        self.assertEqual(member_memory_validation["data"][0]["validation_source"], "user_confirmed")

    def test_harness_memory_staleness_event_payload_contract_matches_route(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import list_agent_memory_staleness_events

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Memory staleness event payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Staleness event payload",
            content="Staleness event payload should expose stable audit fields.",
            source_type="user_confirmed",
            source_ref_json=None,
            evidence_refs=[
                {
                    "evidence_ref_id": "scenario:stale-contract",
                    "ref_type": "scenario",
                    "ref_id": "stale-contract",
                    "mutability_class": "mutable_current",
                    "dependency_role": "audit_trace",
                    "active_for_policy": False,
                }
            ],
            current_user=self.owner,
        )
        touched = MemoryStalenessWorker(self.db).mark_memories_stale_for_ref(
            evidence_ref_type="scenario",
            evidence_ref_id="stale-contract",
            stale_reason="scenario.updated",
        )
        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Memory staleness event payload contract:" in path.read_text(encoding="utf-8")
        ]
        admin_payload = list_agent_memory_staleness_events(limit=100, db=self.db, current_user=self.admin)["data"][0]
        project_payload = list_agent_memory_staleness_events(
            project_id=10,
            evidence_ref_type="scenario",
            evidence_ref_id="stale-contract",
            limit=100,
            db=self.db,
            current_user=self.owner,
        )["data"][0]
        memory_payload = list_agent_memory_staleness_events(
            memory_id=memory.id,
            limit=100,
            db=self.db,
            current_user=self.member,
        )["data"][0]

        self.assertEqual(touched, 1)
        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(MEMORY_STALENESS_EVENT_FIELDS))
            self.assertEqual(contract["source"], "GET /api/v1/agents/memory-staleness-events")
        self.assertEqual(list(AgentMemoryStalenessEventRead.model_fields), list(MEMORY_STALENESS_EVENT_FIELDS))
        self.assertEqual(list(admin_payload), list(MEMORY_STALENESS_EVENT_FIELDS))
        self.assertEqual(list(project_payload), list(MEMORY_STALENESS_EVENT_FIELDS))
        self.assertEqual(list(memory_payload), list(MEMORY_STALENESS_EVENT_FIELDS))
        self.assertEqual(admin_payload["memory_id"], memory.id)
        self.assertEqual(project_payload["evidence_ref_type"], "scenario")
        self.assertEqual(project_payload["evidence_ref_id"], "stale-contract")
        self.assertEqual(memory_payload["stale_reason"], "scenario.updated")
        self.assertEqual(memory_payload["previous_status"], "active")

    def test_harness_memory_validation_event_payload_contract_matches_route(self):
        from pathlib import Path
        import re

        from app.api.v1.routers.agents import list_agent_memory_validation_events

        def _parse_payload_contract(text: str) -> dict[str, list[str] | str]:
            section = text[text.index("Required Memory validation event payload contract:"):]
            block = re.search(r"```text\n(.*?)\n```", section, re.S)
            self.assertIsNotNone(block)
            parsed: dict[str, list[str] | str] = {}
            for line in block.group(1).splitlines():
                if not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                if "," in value:
                    parsed[key] = value.split(",")
                else:
                    parsed[key] = value
            return parsed

        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Validation event payload",
            content="Validation event payload should expose stable audit fields.",
            source_type="execution_learned",
            source_ref_json={"execution_record_id": "validation-contract"},
            evidence_refs=[
                {
                    "evidence_ref_id": "execution-record-validation-contract",
                    "ref_type": "execution_record",
                    "ref_id": "validation-contract",
                    "mutability_class": "immutable",
                    "dependency_role": "decision_dependency",
                    "active_for_policy": True,
                },
                {
                    "evidence_ref_id": "execution-record-validation-contract-2",
                    "ref_type": "execution_record",
                    "ref_id": "validation-contract-2",
                    "mutability_class": "immutable",
                    "dependency_role": "decision_dependency",
                    "active_for_policy": True,
                }
            ],
            current_user=self.owner,
        )
        validated = MemoryManager(self.db).validate_memory(
            memory_id=memory.id,
            reason="validation event payload contract",
            current_user=self.owner,
        )
        docs_dir = Path(__file__).resolve().parents[1] / "docs"
        documented_payload_contracts = [
            _parse_payload_contract(path.read_text(encoding="utf-8"))
            for path in docs_dir.glob("*Harness_Loop_Agent*Memory*.md")
            if "Required Memory validation event payload contract:" in path.read_text(encoding="utf-8")
        ]
        admin_payload = list_agent_memory_validation_events(limit=100, db=self.db, current_user=self.admin)["data"][0]
        project_payload = list_agent_memory_validation_events(
            project_id=10,
            validation_source="user_confirmed",
            limit=100,
            db=self.db,
            current_user=self.owner,
        )["data"][0]
        memory_payload = list_agent_memory_validation_events(
            memory_id=memory.id,
            limit=100,
            db=self.db,
            current_user=self.member,
        )["data"][0]

        self.assertEqual(validated.validation_count, 1)
        self.assertEqual(len(documented_payload_contracts), 2)
        for contract in documented_payload_contracts:
            self.assertEqual(contract["fields"], list(MEMORY_VALIDATION_EVENT_FIELDS))
            self.assertEqual(contract["source"], "GET /api/v1/agents/memory-validation-events")
        self.assertEqual(list(AgentMemoryValidationEventRead.model_fields), list(MEMORY_VALIDATION_EVENT_FIELDS))
        self.assertEqual(list(admin_payload), list(MEMORY_VALIDATION_EVENT_FIELDS))
        self.assertEqual(list(project_payload), list(MEMORY_VALIDATION_EVENT_FIELDS))
        self.assertEqual(list(memory_payload), list(MEMORY_VALIDATION_EVENT_FIELDS))
        self.assertEqual(admin_payload["memory_id"], memory.id)
        self.assertEqual(project_payload["validation_source"], "user_confirmed")
        self.assertEqual(memory_payload["reason"], "validation event payload contract")
        self.assertEqual(memory_payload["previous_status"], "needs_review")
        self.assertEqual(memory_payload["new_status"], "active")
        self.assertEqual(memory_payload["validation_count"], 1)

    def _create_run(self, intent: str):
        return AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent=intent),
            current_user=self.owner,
        )

    def _execution_record_evidence_refs(self, *record_ids: str) -> list[dict]:
        return [
            {
                "evidence_ref_id": f"execution-record-{record_id}",
                "ref_type": "execution_record",
                "ref_id": record_id,
                "version_id": "v1",
                "content_hash": f"hash-{record_id}",
                "mutability_class": "immutable",
                "dependency_role": "decision_dependency",
                "active_for_policy": True,
            }
            for record_id in record_ids
        ]

    def _create_uncertain_call(self, run_id: str, *, step_index: int, effect_state: str = "transport_sent_observed"):
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run_id,
                tool_name="project.read_context",
                input={"project_id": 10, "step": step_index},
                step_index=step_index,
            ),
            current_user=self.owner,
            enqueue=False,
        )
        call.status = "uncertain"
        call.effect_submission_state = effect_state
        self.db.commit()
        return call

    def _create_migration_block(self):
        run = self._create_run("schema migration resolve")
        call = self._create_uncertain_call(run.run_id, step_index=0)
        result = ReconcileResult(
            found=False,
            status="unsupported_schema_version",
            schema_support="unsupported",
            backend_contract_version="v1",
            error_code="unsupported_schema_version",
            error_message="adapter required",
        )
        ReconcileWorker(self.db, router=StaticReconcileRouter(result)).reconcile_run(
            run_id=run.run_id,
            current_user=self.owner,
        )
        block = self.db.scalar(select(AgentMigrationBlock).where(AgentMigrationBlock.run_id == run.run_id))
        self.assertIsNotNone(block)
        return run, call, block

    def _create_pending_approval(
        self,
        *,
        current_user=None,
        expires_at: datetime | None = None,
    ):
        user = current_user or self.owner
        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="approval flow"),
            current_user=user,
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name="project.read_context",
                input={"project_id": 10},
                step_index=0,
            ),
            current_user=user,
            enqueue=False,
        )
        call.resolved_side_effect_class = "business_create"
        call.approval_required = True
        self.db.flush()
        approval = ApprovalService(self.db).create_pending_approval(
            call=call,
            run=run,
            current_user=user,
            expires_at=expires_at,
        )
        self.db.refresh(call)
        return run, call, approval

    def _approval_decision(self, approval: AgentApproval, *, reason: str | None = None) -> AgentApprovalDecisionRequest:
        return AgentApprovalDecisionRequest(
            input_hash=approval.input_hash,
            runtime_snapshot_id=approval.runtime_snapshot_id,
            resource_scope_hash=approval.resource_scope_hash,
            approval_lineage_id=approval.approval_lineage_id,
            approval_epoch=approval.approval_epoch,
            reason=reason,
        )

    def _large_evidence_refs(self, *, count: int) -> list[dict]:
        return [
            {
                "evidence_ref_id": f"evidence-{index}",
                "ref_type": "testcase",
                "ref_id": f"case-{index}",
                "mutability_class": "mutable_current" if index % 2 else "versioned",
                "version_id": f"v{index}" if index % 2 == 0 else None,
                "dependency_role": "decision_dependency",
                "active_for_policy": True,
                "required_for_high_risk": index == count - 1,
                "content": "x" * 400,
            }
            for index in range(count)
        ]


class StaticReconcileRouter:
    def __init__(self, result: ReconcileResult):
        self.result = result

    def reconcile(self, **kwargs):
        return self.result


class RaisingReconcileRouter:
    def reconcile(self, **kwargs):
        raise AssertionError("high-risk legacy_no_receipt should not call reconcile adapter")


class RaisingBackend:
    def execute(self, **kwargs):
        raise AssertionError("backend execution should be blocked before adapter invocation")


class MappingReconcileRouter:
    def __init__(self, results: dict[str, ReconcileResult]):
        self.results = results

    def reconcile(self, *, call, **kwargs):
        return self.results[call.tool_call_id]


if __name__ == "__main__":
    unittest.main()
