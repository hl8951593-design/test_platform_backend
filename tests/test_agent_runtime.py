import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db.base import Base
from app.models.agent import (
    AgentApproval,
    AgentApprovalLineage,
    AgentApprovalMutationLog,
    AgentBackendContract,
    AgentContextBuild,
    AgentEvidenceWatch,
    AgentEvent,
    AgentLoopObservation,
    AgentMemoryRetrievalProfile,
    AgentMemorySourceProfile,
    AgentMemoryContradictionEvent,
    AgentMemoryUsageEvent,
    AgentMemoryEvidenceLink,
    AgentMigrationBlock,
    AgentOutbox,
    AgentReconcileAttempt,
    AgentRootCauseRule,
    AgentToolCall,
    AgentWorkerQueue,
    ProjectMemory,
)
from app.models.project import Project, ProjectMember, ProjectMemberPermission
from app.models.user import User
from app.schemas.agent import (
    AgentApprovalDecisionRequest,
    AgentContextBuildCreateRequest,
    AgentLoopObservationCreateRequest,
    AgentRunCreateRequest,
    AgentToolCallCreateRequest,
    ReconcileResult,
)
from app.services.agent_approval_service import ApprovalExpireScanner, ApprovalService
from app.services.agent_fault_injection_service import AgentFaultInjectionService
from app.services.agent_loop_service import ContextBuilder, EvidenceRefResolver, EvidenceWatchService, LoopController
from app.services.agent_memory_service import (
    MemoryFeedbackWorker,
    MemoryManager,
    MemoryRetrievalProfileResolver,
    MemorySourceProfileResolver,
    MemoryStalenessWorker,
    compute_contradiction_penalty,
)
from app.services.agent_observability_service import AgentMetricsService, AgentOutboxPublisher
from app.services.agent_reconcile_service import CheckpointFreshnessGate, MigrationCoordinator, ReconcileWorker
from app.services.agent_release_gate_service import AgentReleaseGateService
from app.services.agent_resume_service import AgentRunResumeService
from app.services.agent_runbook_service import AgentRunbookService
from app.services.agent_runtime_service import (
    AgentRuntimeService,
    AgentWorkerQueueService,
    ExecutionLedgerService,
    ToolExecutor,
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
        self.project = Project(id=10, name="Agent Project", description="demo", created_by_id=1)
        self.db.add_all([self.owner, self.member, self.project])
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
        self.assertEqual([item.event_type for item in events], ["run.queued", "run.started", "run.completed"])
        self.assertEqual([item.event_seq for item in events], [1, 2, 3])

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

    def test_fault_injection_service_runs_p0_recovery_cases(self):
        summary = AgentFaultInjectionService(self.db).run_cases(
            project_id=10,
            case_ids=None,
            current_user=self.owner,
        )
        by_case = {item["case_id"]: item for item in summary["results"]}

        self.assertEqual(summary["requested"], 6)
        self.assertEqual(summary["failed"], 0)
        self.assertTrue(all(item["passed"] for item in summary["results"]))
        self.assertEqual(by_case["send_intent_not_found"]["observed"]["tool_status"], "failed_retryable")
        self.assertEqual(by_case["transport_sent_not_found"]["observed"]["recovery_decision"], "reconcile_backoff")
        self.assertEqual(by_case["unsupported_schema_version"]["observed"]["run_status"], "migration_blocked")
        self.assertEqual(by_case["legacy_no_receipt_high_risk"]["observed"]["tool_status"], "manual_intervention")
        self.assertEqual(by_case["approval_epoch_conflict"]["evidence"]["error_code"], "approval_epoch_conflict")
        self.assertEqual(by_case["checkpoint_stale"]["observed"]["freshness_result"], "too_old")

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
        committed = self._create_uncertain_call(
            run.run_id,
            step_index=2,
            effect_state="effect_committed",
        )
        result = ReconcileResult(
            found=False,
            status="not_found",
            backend_contract_version="v1",
            error_code="reconcile_not_found",
        )

        summary = ReconcileWorker(self.db, router=StaticReconcileRouter(result)).reconcile_run(
            run_id=run.run_id,
            current_user=self.owner,
        )

        refreshed = {
            item.tool_call_id: item
            for item in self.db.scalars(select(AgentToolCall).where(AgentToolCall.run_id == run.run_id)).all()
        }
        self.assertEqual(summary["processed"], 3)
        self.assertEqual(refreshed[send_intent.tool_call_id].status, "failed_retryable")
        self.assertEqual(refreshed[send_intent.tool_call_id].recovery_decision, "safe_retry_same_idempotency_key")
        self.assertEqual(refreshed[transport.tool_call_id].status, "uncertain")
        self.assertEqual(refreshed[transport.tool_call_id].recovery_decision, "reconcile_backoff")
        self.assertEqual(refreshed[committed.tool_call_id].status, "manual_intervention")
        self.assertEqual(refreshed[committed.tool_call_id].recovery_decision, "effect_committed_not_found_incident")

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

    def test_runbook_catalog_and_run_diagnosis_cover_recovery_states(self):
        run, call, _ = self._create_pending_approval()
        call.status = "uncertain"
        call.effect_submission_state = "transport_sent_observed"
        run.last_checkpoint_id = None
        self.db.commit()
        MigrationCoordinator(self.db).create_tool_call_block(
            run=run,
            call=call,
            reason="unsupported_schema_version",
            details={"schema": "old"},
        )
        self.db.commit()

        service = AgentRunbookService(self.db)
        catalog = service.list_runbooks()
        diagnosis = service.diagnose_run(run_id=run.run_id, current_user=self.owner)
        runbook_ids = {item["runbook_id"] for item in diagnosis["recommendations"]}

        self.assertIn("tool_call_uncertain", {item["runbook_id"] for item in catalog})
        self.assertIn("migration_blocked", runbook_ids)
        self.assertIn("approval_stale", runbook_ids)
        self.assertIn("checkpoint_stale", runbook_ids)
        self.assertIn("tool_call_uncertain", runbook_ids)

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
        self.assertEqual(result["checkpoint_freshness"]["action"], "fetch_evidence_and_rebuild_context")

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
        self.assertEqual(self.db.query(AgentReconcileAttempt).count(), 0)

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
        self.assertEqual(stale_ctx.exception.detail["code"], "approval_stale_or_superseded")
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

        self.assertEqual(len(conflict_events), 2)
        self.assertEqual(metrics["approval_epoch_conflict_total"], 1)

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

    def test_expire_scanner_expires_due_pending_approvals_idempotently(self):
        run, call, approval = self._create_pending_approval(
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        )

        expired = ApprovalExpireScanner(self.db).expire_due()
        expired_again = ApprovalExpireScanner(self.db).expire_due()
        refreshed = self.db.scalar(select(AgentApproval).where(AgentApproval.approval_id == approval.approval_id))
        events = [item.event_type for item in self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run.run_id).order_by(AgentEvent.event_seq)
        ).all()]

        self.assertEqual(expired, 1)
        self.assertEqual(expired_again, 0)
        self.assertEqual(refreshed.approval_status, "expired")
        self.assertIn("approval.expired", events)

    def test_agent_approval_routes_are_declared(self):
        from app.main import create_app

        paths = create_app().openapi()["paths"]

        self.assertIn("/api/v1/agents/tool-calls/{tool_call_id}/approve", paths)
        self.assertIn("/api/v1/agents/tool-calls/{tool_call_id}/reject", paths)
        self.assertIn("/api/v1/agents/runs/{run_id}/approvals", paths)
        self.assertIn("/api/v1/agents/metrics", paths)
        self.assertIn("/api/v1/agents/outbox/publish", paths)
        self.assertIn("/api/v1/agents/release-gates", paths)
        self.assertIn("/api/v1/agents/fault-injections", paths)
        self.assertIn("/api/v1/agents/fault-injections/run", paths)
        self.assertIn("/api/v1/agents/runbooks", paths)
        self.assertIn("/api/v1/agents/runs/{run_id}/runbook", paths)

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
        self.assertIn("context.full_evidence_required", events)
        self.assertGreaterEqual(self.db.query(AgentEvidenceWatch).count(), 1)

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

        candidates = MemoryManager(self.db).retrieve(
            project_id=10,
            query="MFA login",
            profile_name="high_risk_action_v1",
            task_risk="high",
            usage_role="policy_dependency",
            current_user=self.owner,
            limit=10,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source_type, "user_confirmed")
        self.assertEqual(candidates[0].evidence_ref["ref_type"], "memory")
        self.assertTrue(candidates[0].evidence_ref["active_for_policy"])
        self.assertEqual(candidates[0].evidence_ref["dependency_role"], "policy_dependency")
        self.assertEqual(self.db.query(AgentMemoryRetrievalProfile).count(), 4)
        self.assertEqual(self.db.query(AgentMemoryUsageEvent).count(), 1)

    def test_memory_retrieval_profile_missing_returns_422(self):
        with self.assertRaises(HTTPException) as ctx:
            MemoryRetrievalProfileResolver(self.db).get(profile_name="missing_profile")

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail["code"], "memory_retrieval_profile_missing")

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

        validated = MemoryManager(self.db).validate_memory(
            memory_id=memory.id,
            reason="human checked",
            current_user=self.owner,
        )
        self.assertEqual(validated.status, "active")
        self.assertEqual(validated.validation_count, 1)
        rejected = MemoryManager(self.db).reject_memory(
            memory_id=memory.id,
            reason="later disproved",
            current_user=self.owner,
        )

        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.confidence, 0.0)
        self.assertEqual(rejected.memory_version, 3)

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

        self.assertEqual(before, 0.0)
        self.assertGreater(after, 0.0)
        self.assertEqual(refreshed.status, "needs_revalidation")
        self.assertEqual(refreshed.contradiction_count, 1)
        self.assertLess(refreshed.confidence, memory.initial_confidence)

    def test_memory_staleness_worker_updates_linked_memory(self):
        memory = MemoryManager(self.db).create_memory(
            project_id=10,
            memory_type="project_rule",
            title="Scenario source",
            content="Use scenario source.",
            source_type="document_imported",
            source_ref_json={"document_id": "doc-1"},
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

        self.assertEqual(touched, 1)
        self.assertGreater(refreshed.stale_score, 0.0)
        self.assertEqual(refreshed.stale_reason_json["reason"], "scenario.updated")

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
            source_ref_json={"document_id": "doc-1"},
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
        self.assertIn("/api/v1/agents/memory-usage-events/{usage_event_id}/feedback", paths)
        self.assertIn("/api/v1/agents/memory-feedback/process", paths)

    def _create_run(self, intent: str):
        return AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent=intent),
            current_user=self.owner,
        )

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


class MappingReconcileRouter:
    def __init__(self, results: dict[str, ReconcileResult]):
        self.results = results

    def reconcile(self, *, call, **kwargs):
        return self.results[call.tool_call_id]


if __name__ == "__main__":
    unittest.main()
