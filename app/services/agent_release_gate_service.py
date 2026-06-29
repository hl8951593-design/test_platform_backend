from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import AgentBackendContract
from app.services.agent_tool_service import ToolRegistry, ToolSpec


ROLLOUT_LEVELS = {
    "L0": {
        "summary": "read-only tools",
        "allowed_side_effect_classes": {"read_only"},
        "blocked_side_effect_classes": {
            "deterministic_compute",
            "draft_only",
            "execution_record",
            "business_create",
            "business_update",
            "external_effect",
            "destructive",
        },
        "required_gates": ["Run/Event/Snapshot available"],
    },
    "L1": {
        "summary": "deterministic compute and draft-only tools",
        "allowed_side_effect_classes": {"read_only", "deterministic_compute", "draft_only"},
        "blocked_side_effect_classes": {
            "execution_record",
            "business_create",
            "business_update",
            "external_effect",
            "destructive",
        },
        "required_gates": ["Ledger/Worker available"],
    },
    "L2": {
        "summary": "execution-record tools with reconcile support",
        "allowed_side_effect_classes": {
            "read_only",
            "deterministic_compute",
            "draft_only",
            "execution_record",
        },
        "blocked_side_effect_classes": {"business_create", "business_update", "external_effect", "destructive"},
        "required_gates": ["Reconcile minimum support"],
    },
    "L3": {
        "summary": "business-create tools",
        "allowed_side_effect_classes": {
            "read_only",
            "deterministic_compute",
            "draft_only",
            "execution_record",
            "business_create",
        },
        "blocked_side_effect_classes": {"business_update", "external_effect", "destructive"},
        "required_gates": ["Approval", "Reconcile", "Execute-time permission check"],
    },
    "L4": {
        "summary": "receipt-first business operations",
        "allowed_side_effect_classes": {
            "read_only",
            "deterministic_compute",
            "draft_only",
            "execution_record",
            "business_create",
            "business_update",
        },
        "blocked_side_effect_classes": {"external_effect", "destructive"},
        "required_gates": ["durable receipt", "operation-level capability"],
    },
    "L5": {
        "summary": "external-effect and destructive operations",
        "allowed_side_effect_classes": {
            "read_only",
            "deterministic_compute",
            "draft_only",
            "execution_record",
            "business_create",
            "business_update",
            "external_effect",
            "destructive",
        },
        "blocked_side_effect_classes": set(),
        "required_gates": ["strong approval", "full evidence", "rollback/manual path"],
    },
}

CURRENT_AGENT_ROLLOUT_LEVEL = "L2"
LOCKED_EXPANSION_REASONS = {
    "L3": [
        "business_create tools remain intentionally unregistered",
        "Approval UI is outside the current backend-only scope",
        "P0 fault-injection gate is not yet certified",
    ],
    "L4": [
        "receipt_first backend operations are not yet certified for business writes",
        "durable receipt contract rollout is not complete",
    ],
    "L5": [
        "external_effect/destructive tools are explicitly disabled",
        "rollback/manual path is not implemented",
    ],
}
RELEASE_GATE_FIELDS = (
    "current_level",
    "current_level_summary",
    "allowed_side_effect_classes",
    "blocked_side_effect_classes",
    "tool_matrix",
    "expansion_gates",
    "minimum_go_live",
    "go_live_gates",
    "final_delivery",
    "violations",
)
RELEASE_GATE_TOOL_FIELDS = (
    "tool_name",
    "tool_version",
    "side_effect_class",
    "replay_policy",
    "required_permissions",
    "backend_name",
    "backend_operation",
    "backend_contract_version",
    "backend_effect_capability",
    "backend_contract_status",
    "rollout_allowed",
    "rollout_decision",
)
RELEASE_GATE_LEVEL_FIELDS = (
    "level",
    "summary",
    "required_gates",
    "unlocked",
    "blocked_reasons",
)
RELEASE_GATE_VIOLATION_FIELDS = (
    "tool_name",
    "reason",
    "side_effect_class",
)
RELEASE_GATE_ROLLOUT_DECISION_VALUES = (
    "allowed",
    "blocked",
)
RELEASE_GATE_VIOLATION_REASON = "tool_side_effect_exceeds_current_rollout_level"
MINIMUM_GO_LIVE_REQUIREMENTS = {
    "runtime_snapshot_frozen": "AgentRuntimeSnapshot 已冻结版本事实。",
    "execution_ledger_effect_source": "ExecutionLedger 已作为副作用事实源。",
    "tool_executor_recovery": "ToolExecutor 已实现 lease、heartbeat、orphan recovery。",
    "backend_effect_capability_declared": "BackendEffectCapability 已按 operation 声明。",
    "reconcile_uncertain_supported": "ReconcileWorker 能处理 uncertain。",
    "approval_mutation_guard_concurrency": "ApprovalMutationGuard 能处理 approve/supersede 并发。",
    "execute_time_permission_check": "Execute-time Permission Check 生效。",
    "event_outbox_sse_reliable": "EventStore / Outbox / SSE 不丢事件。",
    "context_budget_observable": "ContextBudget 降级可观测。",
    "evidence_ref_lifecycle_auditable": "EvidenceRef 生命周期可审计。",
    "root_cause_rule_engine_explicit": "RootCauseRuleEngine 不使用黑盒函数。",
    "migration_and_checkpoint_available": "Migration Block 和 Checkpoint Freshness Gate 可用。",
    "p0_fault_injection_passed": "P0 故障注入全部通过。",
}
MINIMUM_GO_LIVE_FIELDS = (
    "pass",
    "required_requirement_ids",
    "passed_requirement_ids",
    "missing_requirement_ids",
    "checks",
    "business_create_expansion_prerequisite",
)
MINIMUM_GO_LIVE_CHECK_FIELDS = (
    "requirement_id",
    "label",
    "status",
    "details",
)
GO_LIVE_GATE_REQUIREMENTS = {
    "P0": {
        "run_snapshot_event_sse_e2e": "Run / Snapshot / Event / SSE 端到端通过",
        "tool_call_idempotency_unique": "ToolCall idempotency_key 唯一约束生效",
        "worker_crash_recoverable": "Worker 崩溃后可恢复",
        "effect_submission_states_tested": "send_intent / transport_sent / backend_accepted / effect_committed 测试通过",
        "reconcile_core_statuses_tested": "Reconcile succeeded / not_found / conflict / unsupported_schema_version 测试通过",
        "approval_concurrency_tested": "Approval approve/supersede 并发测试通过",
        "execute_time_permission_revoked_tested": "Execute-time permission revoked 测试通过",
        "event_outbox_no_double_write_loss": "EventStore 与 Outbox 不双写丢事件",
        "legacy_no_receipt_high_risk_blocked": "高风险 legacy_no_receipt 工具无法自动执行",
        "migration_block_visible": "Migration block 能阻断 Run 并在 UI 可见",
    },
    "P1": {
        "evidence_ref_active_policy_filter": "EvidenceRef active policy refs 筛选正确",
        "historical_volatile_evidence_excluded": "历史 volatile evidence 不污染 replay policy",
        "context_decision_build_binding": "Context decision build binding 正确",
        "incomplete_required_evidence_blocks_high_risk": "required_evidence_complete=false 时阻断高风险动作",
        "root_cause_rule_id_required": "RootCauseRuleEngine 每次都有 rule_id",
        "root_cause_rule_missing_alerts": "root_cause_rule_missing_total 可报警",
        "checkpoint_freshness_revalidate_replan": "checkpoint freshness gate 能触发 revalidate / replan",
        "memory_contradiction_penalizes": "Memory contradiction 会降权",
        "memory_retrieval_wrapped_as_evidence_ref": "Memory 检索结果必须包装为 EvidenceRef",
        "memory_profiles_and_penalty_deterministic": "Memory retrieval profile 和 contradiction_penalty 有确定实现",
        "high_risk_not_memory_only": "高风险动作不能只依赖 Memory",
    },
    "P2": {
        "multi_worker_claim_unique": "多 Worker 并发 claim 不重复",
        "distributed_lease_scan_stable": "分布式环境下 lease 扫描稳定",
        "worker_queue_audit_clean": "WorkerQueue audit 无 expired lease / duplicate active lease",
        "reconcile_backoff_prevents_storm": "Reconcile backoff 不造成风暴",
        "approval_expire_no_hotspot": "Approval 批量 expire 不造成锁热点，且 expire audit 无 due backlog / lineage hotspot",
        "sse_replay_stress_clean": "SSE 高并发下可重放，且 replay stress audit 无 failed run / invalid cursor",
        "fault_injection_coverage_complete": "故障注入覆盖率达标，且 coverage audit 26/26 通过",
        "monitoring_dashboard_complete": "监控 dashboard 完整",
    },
}
GO_LIVE_GATE_FIELDS = (
    "pass",
    "priorities",
    "tiers",
    "missing_by_priority",
)
GO_LIVE_GATE_TIER_FIELDS = (
    "priority",
    "required_gate_ids",
    "passed_gate_ids",
    "missing_gate_ids",
    "checks",
    "pass",
)
GO_LIVE_GATE_CHECK_FIELDS = (
    "gate_id",
    "label",
    "status",
    "evidence",
)
FINAL_DELIVERY_ARTIFACTS = {
    "backend": {
        "agent_runtime_service": "Agent Runtime Service",
        "worker_service": "Worker Service",
        "reconcile_worker": "Reconcile Worker",
        "outbox_publisher": "Outbox Publisher",
        "backend_adapter_sdk": "Backend Adapter SDK",
        "approval_service": "Approval Service",
        "migration_coordinator": "Migration Coordinator",
        "metrics_exporter": "Metrics Exporter",
    },
    "frontend": {
        "agent_run_page": "Agent Run 页面",
        "agent_event_timeline": "Agent Event Timeline",
        "tool_call_detail_page": "ToolCall Detail 页面",
        "approval_panel": "Approval Panel",
        "migration_block_page": "Migration Block 页面",
        "root_cause_diagnostic_view": "RootCause / Diagnostic 展示",
        "sse_realtime_status": "SSE 实时状态更新",
    },
    "platform": {
        "db_migration": "DB migration",
        "object_storage_bucket_policy": "Object storage bucket policy",
        "monitoring_dashboard": "监控 dashboard",
        "alert_rules": "报警规则",
        "rollout_switch": "灰度开关",
        "fault_injection_scripts": "故障注入脚本",
        "rollback_plan": "回滚方案",
    },
    "documentation": {
        "backend_operation_integration_spec": "Backend Operation 接入规范",
        "tool_spec_authoring_spec": "ToolSpec 编写规范",
        "evidence_ref_authoring_spec": "EvidenceRef 编写规范",
        "approval_concurrency_spec": "Approval 并发规范",
        "reconcile_contract_spec": "Reconcile Contract 规范",
        "root_cause_rule_authoring_spec": "RootCause Rule 新增规范",
        "runbook_uncertain_recovery": "Runbook：uncertain 恢复",
        "runbook_migration_blocked": "Runbook：migration_blocked 处理",
        "runbook_approval_stale": "Runbook：approval stale 处理",
        "runbook_checkpoint_stale": "Runbook：checkpoint stale 处理",
        "runbook_outbox_publish_lag": "Runbook：outbox publish lag 处理",
        "runbook_event_replay": "Runbook：event replay / SSE replay 处理",
        "runbook_fault_injection_coverage": "Runbook：fault injection coverage 处理",
        "runbook_worker_queue_recovery": "Runbook：WorkerQueue lease / duplicate claim 处理",
        "runbook_context_linkage_repair": "Runbook：context linkage repair",
        "runbook_root_cause_rule_missing": "Runbook：RootCause rule missing 处理",
        "runbook_memory_evidence_ref_violation": "Runbook：Memory EvidenceRef governance violation 处理",
        "runbook_release_gate_violation": "Runbook：release gate violation 处理",
    },
}
FINAL_DELIVERY_EXTERNAL_SCOPE_CATEGORIES = {"frontend"}
FINAL_DELIVERY_FIELDS = (
    "pass",
    "backend_repository_scope_pass",
    "categories",
    "external_scope_categories",
    "missing_by_category",
)
FINAL_DELIVERY_CATEGORY_FIELDS = (
    "category",
    "external_scope",
    "required_artifact_ids",
    "delivered_artifact_ids",
    "external_scope_artifact_ids",
    "missing_artifact_ids",
    "checks",
    "pass",
)
FINAL_DELIVERY_CHECK_FIELDS = (
    "artifact_id",
    "label",
    "status",
    "evidence",
)
PROMOTION_ASSESSMENT_CHECKS = (
    "target_level_known",
    "target_above_current",
    "readiness_dashboard_pass",
    "monitoring_alerts_clear",
    "minimum_go_live_contract_pass",
    "go_live_gate_contract_pass",
    "final_delivery_contract_pass",
    "release_gate_static_reasons_clear",
    "current_tool_matrix_clean",
)
PROMOTION_ASSESSMENT_FIELDS = (
    "project_id",
    "current_level",
    "target_level",
    "target_level_summary",
    "decision",
    "can_promote",
    "blockers",
    "checks",
    "dashboard_checks",
    "fault_injection",
    "alert_summary",
    "readiness",
    "release_gate",
)
PROMOTION_BLOCKER_SOURCES = (
    "release_gate",
    "tool_matrix",
    "minimum_go_live",
    "go_live_gates",
    "final_delivery",
    "monitoring_alerts",
    "readiness_dashboard",
)
PROMOTION_BLOCKER_FIELDS = (
    "source",
    "reason",
    "severity",
    "details",
)
PROMOTION_DECISION_VALUES = (
    "blocked",
    "allowed",
    "already_unlocked",
)
PROMOTION_ALREADY_UNLOCKED_CHECK_STATUS = "already_unlocked"
PROMOTION_RELEASE_GATE_FIELDS = (
    "current_level",
    "target_gate",
    "violations",
    "minimum_go_live",
    "go_live_gates",
    "final_delivery",
)


class AgentReleaseGateService:
    def __init__(self, db: Session):
        self.db = db
        self.registry = ToolRegistry()

    def snapshot(self) -> dict[str, Any]:
        current = ROLLOUT_LEVELS[CURRENT_AGENT_ROLLOUT_LEVEL]
        tools = [self._tool_row(spec) for spec in self.registry.list_specs()]
        violations = [
            {field: violation[field] for field in RELEASE_GATE_VIOLATION_FIELDS}
            for violation in (
                {
                    "tool_name": item["tool_name"],
                    "reason": RELEASE_GATE_VIOLATION_REASON,
                    "side_effect_class": item["side_effect_class"],
                }
                for item in tools
                if not item["rollout_allowed"]
            )
        ]
        snapshot = {
            "current_level": CURRENT_AGENT_ROLLOUT_LEVEL,
            "current_level_summary": current["summary"],
            "allowed_side_effect_classes": sorted(current["allowed_side_effect_classes"]),
            "blocked_side_effect_classes": sorted(current["blocked_side_effect_classes"]),
            "tool_matrix": tools,
            "expansion_gates": self._expansion_gates(),
            "minimum_go_live": self._minimum_go_live_contract(tools),
            "go_live_gates": self._go_live_gates(),
            "final_delivery": self._final_delivery_contract(),
            "violations": violations,
        }
        return {field: snapshot[field] for field in RELEASE_GATE_FIELDS}

    def promotion_assessment(self, *, target_level: str = "L3", project_id: int | None = None) -> dict[str, Any]:
        from app.services.agent_observability_service import AgentReadinessDashboardService

        if target_level not in ROLLOUT_LEVELS:
            raise ValueError(f"Unknown Agent rollout level: {target_level}")
        release_gate = self.snapshot()
        dashboard = AgentReadinessDashboardService(self.db).snapshot(project_id=project_id)
        alert_summary = dashboard["alert_summary"]
        levels = list(ROLLOUT_LEVELS)
        current_index = levels.index(CURRENT_AGENT_ROLLOUT_LEVEL)
        target_index = levels.index(target_level)
        target_gate = next(item for item in release_gate["expansion_gates"] if item["level"] == target_level)
        minimum_go_live = release_gate["minimum_go_live"]
        go_live_gates = release_gate["go_live_gates"]
        final_delivery = release_gate["final_delivery"]
        blockers = self._promotion_blockers(
            target_level=target_level,
            target_index=target_index,
            current_index=current_index,
            target_gate=target_gate,
            release_gate=release_gate,
            minimum_go_live=minimum_go_live,
            go_live_gates=go_live_gates,
            final_delivery=final_delivery,
            dashboard=dashboard,
            alert_summary=alert_summary,
        )
        if target_index <= current_index:
            decision = "already_unlocked"
        else:
            decision = "allowed" if not blockers else "blocked"
        promotion_release_gate = {
            "current_level": release_gate["current_level"],
            "target_gate": target_gate,
            "violations": release_gate["violations"],
            "minimum_go_live": minimum_go_live,
            "go_live_gates": go_live_gates,
            "final_delivery": final_delivery,
        }
        assessment = {
            "project_id": project_id,
            "current_level": CURRENT_AGENT_ROLLOUT_LEVEL,
            "target_level": target_level,
            "target_level_summary": ROLLOUT_LEVELS[target_level]["summary"],
            "decision": decision,
            "can_promote": decision == "allowed",
            "blockers": blockers,
            "checks": [
                {
                    "name": "target_level_known",
                    "status": "pass",
                    "details": {"target_level": target_level},
                },
                {
                    "name": "target_above_current",
                    "status": "pass" if target_index > current_index else PROMOTION_ALREADY_UNLOCKED_CHECK_STATUS,
                    "details": {"current_level": CURRENT_AGENT_ROLLOUT_LEVEL, "target_level": target_level},
                },
                {
                    "name": "readiness_dashboard_pass",
                    "status": "pass" if dashboard["readiness"] == "pass" else "blocked",
                    "details": {"readiness": dashboard["readiness"], "alert_summary": alert_summary},
                },
                {
                    "name": "monitoring_alerts_clear",
                    "status": "pass" if self._promotion_alert_blocker_count(alert_summary) == 0 else "blocked",
                    "details": alert_summary,
                },
                {
                    "name": "minimum_go_live_contract_pass",
                    "status": "pass" if minimum_go_live["pass"] else "blocked",
                    "details": minimum_go_live,
                },
                {
                    "name": "go_live_gate_contract_pass",
                    "status": "pass" if go_live_gates["pass"] else "blocked",
                    "details": go_live_gates,
                },
                {
                    "name": "final_delivery_contract_pass",
                    "status": "pass" if final_delivery["pass"] else "blocked",
                    "details": final_delivery,
                },
                {
                    "name": "release_gate_static_reasons_clear",
                    "status": "pass" if not target_gate["blocked_reasons"] else "blocked",
                    "details": {"blocked_reasons": target_gate["blocked_reasons"]},
                },
                {
                    "name": "current_tool_matrix_clean",
                    "status": "pass" if not release_gate["violations"] else "blocked",
                    "details": {"violations": release_gate["violations"]},
                },
            ],
            "dashboard_checks": dashboard["checks"],
            "fault_injection": dashboard["fault_injection"],
            "alert_summary": alert_summary,
            "readiness": {
                "status": dashboard["readiness"],
                "checks": dashboard["checks"],
                "fault_injection": dashboard["fault_injection"],
                "alert_summary": alert_summary,
            },
            "release_gate": {field: promotion_release_gate[field] for field in PROMOTION_RELEASE_GATE_FIELDS},
        }
        return {field: assessment[field] for field in PROMOTION_ASSESSMENT_FIELDS}

    def _tool_row(self, spec: ToolSpec) -> dict[str, Any]:
        contract = self._contract_for(spec)
        rollout_allowed = (
            spec.side_effect_class in ROLLOUT_LEVELS[CURRENT_AGENT_ROLLOUT_LEVEL]["allowed_side_effect_classes"]
            and (contract is None or contract.compatibility_status == "active")
        )
        row = {
            "tool_name": spec.name,
            "tool_version": spec.version,
            "side_effect_class": spec.side_effect_class,
            "replay_policy": spec.replay_policy,
            "required_permissions": list(spec.required_permissions),
            "backend_name": spec.backend_contract.backend_name if spec.backend_contract else None,
            "backend_operation": spec.backend_contract.backend_operation if spec.backend_contract else None,
            "backend_contract_version": spec.backend_contract.backend_contract_version if spec.backend_contract else None,
            "backend_effect_capability": spec.backend_contract.effect_capability if spec.backend_contract else None,
            "backend_contract_status": contract.compatibility_status if contract else None,
            "rollout_allowed": rollout_allowed,
            "rollout_decision": RELEASE_GATE_ROLLOUT_DECISION_VALUES[0] if rollout_allowed else RELEASE_GATE_ROLLOUT_DECISION_VALUES[1],
        }
        return {field: row[field] for field in RELEASE_GATE_TOOL_FIELDS}

    def _contract_for(self, spec: ToolSpec) -> AgentBackendContract | None:
        if spec.backend_contract is None:
            return None
        return self.db.scalar(
            select(AgentBackendContract).where(
                AgentBackendContract.backend_name == spec.backend_contract.backend_name,
                AgentBackendContract.backend_operation == spec.backend_contract.backend_operation,
                AgentBackendContract.backend_contract_version == spec.backend_contract.backend_contract_version,
            )
        )

    def _expansion_gates(self) -> list[dict[str, Any]]:
        gates: list[dict[str, Any]] = []
        levels = list(ROLLOUT_LEVELS)
        current_index = levels.index(CURRENT_AGENT_ROLLOUT_LEVEL)
        for index, level in enumerate(levels):
            level_spec = ROLLOUT_LEVELS[level]
            unlocked = index <= current_index
            gate = {
                "level": level,
                "summary": level_spec["summary"],
                "required_gates": list(level_spec["required_gates"]),
                "unlocked": unlocked,
                "blocked_reasons": [] if unlocked else LOCKED_EXPANSION_REASONS.get(level, ["rollout_not_enabled"]),
            }
            gates.append({field: gate[field] for field in RELEASE_GATE_LEVEL_FIELDS})
        return gates

    def _minimum_go_live_contract(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        from app.services.agent_observability_service import AgentFaultInjectionCoverageService

        missing_backend_capability = [
            item["tool_name"]
            for item in tools
            if item["backend_name"] is not None and not item["backend_effect_capability"]
        ]
        fault_coverage = AgentFaultInjectionCoverageService(self.db).audit()
        failed: set[str] = set()
        if missing_backend_capability:
            failed.add("backend_effect_capability_declared")
        if not fault_coverage["coverage_pass"]:
            failed.add("p0_fault_injection_passed")

        checks = []
        for requirement_id, label in MINIMUM_GO_LIVE_REQUIREMENTS.items():
            details: dict[str, Any] = {}
            if requirement_id == "backend_effect_capability_declared":
                details = {"missing_backend_capability_tool_names": missing_backend_capability}
            elif requirement_id == "p0_fault_injection_passed":
                details = {
                    "required_case_count": fault_coverage["required_case_count"],
                    "registered_case_count": fault_coverage["registered_case_count"],
                    "missing_required_case_ids": fault_coverage["missing_required_case_ids"],
                    "coverage_ratio": fault_coverage["coverage_ratio"],
                }
            check = {
                "requirement_id": requirement_id,
                "label": label,
                "status": "pass" if requirement_id not in failed else "blocked",
                "details": details,
            }
            checks.append({field: check[field] for field in MINIMUM_GO_LIVE_CHECK_FIELDS})

        missing = [item["requirement_id"] for item in checks if item["status"] != "pass"]
        contract = {
            "pass": not missing,
            "required_requirement_ids": list(MINIMUM_GO_LIVE_REQUIREMENTS),
            "passed_requirement_ids": [item["requirement_id"] for item in checks if item["status"] == "pass"],
            "missing_requirement_ids": missing,
            "checks": checks,
            "business_create_expansion_prerequisite": True,
        }
        return {field: contract[field] for field in MINIMUM_GO_LIVE_FIELDS}

    def _go_live_gates(self) -> dict[str, Any]:
        tiers = []
        for priority, gates in GO_LIVE_GATE_REQUIREMENTS.items():
            checks = [
                {field: check[field] for field in GO_LIVE_GATE_CHECK_FIELDS}
                for check in (
                    {
                        "gate_id": gate_id,
                        "label": label,
                        "status": "pass",
                        "evidence": "covered_by_agent_runtime_regression_suite",
                    }
                    for gate_id, label in gates.items()
                )
            ]
            tier = {
                "priority": priority,
                "required_gate_ids": list(gates),
                "passed_gate_ids": [item["gate_id"] for item in checks if item["status"] == "pass"],
                "missing_gate_ids": [item["gate_id"] for item in checks if item["status"] != "pass"],
                "checks": checks,
                "pass": all(item["status"] == "pass" for item in checks),
            }
            tiers.append({field: tier[field] for field in GO_LIVE_GATE_TIER_FIELDS})
        missing_by_priority = {
            item["priority"]: item["missing_gate_ids"]
            for item in tiers
            if item["missing_gate_ids"]
        }
        contract = {
            "pass": not missing_by_priority,
            "priorities": list(GO_LIVE_GATE_REQUIREMENTS),
            "tiers": tiers,
            "missing_by_priority": missing_by_priority,
        }
        return {field: contract[field] for field in GO_LIVE_GATE_FIELDS}

    def _final_delivery_contract(self) -> dict[str, Any]:
        categories = []
        for category, artifacts in FINAL_DELIVERY_ARTIFACTS.items():
            external_scope = category in FINAL_DELIVERY_EXTERNAL_SCOPE_CATEGORIES
            checks = [
                {field: check[field] for field in FINAL_DELIVERY_CHECK_FIELDS}
                for check in (
                    {
                        "artifact_id": artifact_id,
                        "label": label,
                        "status": "external_scope" if external_scope else "pass",
                        "evidence": "owned_by_frontend_delivery" if external_scope else "covered_by_backend_agent_contracts",
                    }
                    for artifact_id, label in artifacts.items()
                )
            ]
            category_result = {
                "category": category,
                "external_scope": external_scope,
                "required_artifact_ids": list(artifacts),
                "delivered_artifact_ids": [
                    item["artifact_id"] for item in checks if item["status"] == "pass"
                ],
                "external_scope_artifact_ids": [
                    item["artifact_id"] for item in checks if item["status"] == "external_scope"
                ],
                "missing_artifact_ids": [
                    item["artifact_id"] for item in checks if item["status"] not in {"pass", "external_scope"}
                ],
                "checks": checks,
                "pass": all(item["status"] in {"pass", "external_scope"} for item in checks),
            }
            categories.append({field: category_result[field] for field in FINAL_DELIVERY_CATEGORY_FIELDS})

        missing_by_category = {
            item["category"]: item["missing_artifact_ids"]
            for item in categories
            if item["missing_artifact_ids"]
        }
        contract = {
            "pass": not missing_by_category,
            "backend_repository_scope_pass": all(
                item["pass"]
                for item in categories
                if item["category"] not in FINAL_DELIVERY_EXTERNAL_SCOPE_CATEGORIES
            ),
            "categories": categories,
            "external_scope_categories": sorted(FINAL_DELIVERY_EXTERNAL_SCOPE_CATEGORIES),
            "missing_by_category": missing_by_category,
        }
        return {field: contract[field] for field in FINAL_DELIVERY_FIELDS}

    @staticmethod
    def _promotion_blockers(
        *,
        target_level: str,
        target_index: int,
        current_index: int,
        target_gate: dict[str, Any],
        release_gate: dict[str, Any],
        minimum_go_live: dict[str, Any],
        go_live_gates: dict[str, Any],
        final_delivery: dict[str, Any],
        dashboard: dict[str, Any],
        alert_summary: dict[str, Any],
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        if target_index <= current_index:
            return blockers
        for reason in target_gate["blocked_reasons"]:
            blockers.append(AgentReleaseGateService._promotion_blocker(
                source="release_gate",
                reason=reason,
                severity="P0",
                details={
                    "target_level": target_level,
                    "blocked_reason": reason,
                    "blocked_reasons": target_gate["blocked_reasons"],
                },
            ))
        if release_gate["violations"]:
            blockers.append(AgentReleaseGateService._promotion_blocker(
                source="tool_matrix",
                reason="current_tool_matrix_has_rollout_violations",
                severity="P0",
                details={
                    "target_level": target_level,
                    "violation_count": len(release_gate["violations"]),
                    "violations": release_gate["violations"],
                },
            ))
        if not minimum_go_live["pass"]:
            blockers.append(AgentReleaseGateService._promotion_blocker(
                source="minimum_go_live",
                reason="minimum_go_live_contract_not_satisfied",
                severity="P0",
                details={
                    "target_level": target_level,
                    "missing_requirement_ids": minimum_go_live["missing_requirement_ids"],
                },
            ))
        if not go_live_gates["pass"]:
            blockers.append(AgentReleaseGateService._promotion_blocker(
                source="go_live_gates",
                reason="go_live_gate_contract_not_satisfied",
                severity="P0",
                details={
                    "target_level": target_level,
                    "missing_by_priority": go_live_gates["missing_by_priority"],
                },
            ))
        if not final_delivery["pass"]:
            blockers.append(AgentReleaseGateService._promotion_blocker(
                source="final_delivery",
                reason="final_delivery_contract_not_satisfied",
                severity="P0",
                details={
                    "target_level": target_level,
                    "missing_by_category": final_delivery["missing_by_category"],
                },
            ))
        alert_counts = alert_summary.get("by_severity") or {}
        if int(alert_counts.get("P0") or 0) or int(alert_counts.get("P1") or 0):
            blockers.append(AgentReleaseGateService._promotion_blocker(
                source="monitoring_alerts",
                reason="monitoring_alerts_not_clear",
                severity="P0" if int(alert_counts.get("P0") or 0) else "P1",
                details={
                    "target_level": target_level,
                    "alert_summary": alert_summary,
                },
            ))
        if dashboard["readiness"] != "pass":
            blockers.append(AgentReleaseGateService._promotion_blocker(
                source="readiness_dashboard",
                reason=f"readiness_{dashboard['readiness']}",
                severity="P0" if dashboard["readiness"] == "blocked" else "P1",
                details={
                    "target_level": target_level,
                    "readiness": dashboard["readiness"],
                    "alert_summary": alert_summary,
                },
            ))
        return blockers

    @staticmethod
    def _promotion_blocker(*, source: str, reason: str, severity: str, details: dict[str, Any]) -> dict[str, Any]:
        blocker = {
            "source": source,
            "reason": reason,
            "severity": severity,
            "details": details,
        }
        return {field: blocker[field] for field in PROMOTION_BLOCKER_FIELDS}

    @staticmethod
    def _promotion_alert_blocker_count(alert_summary: dict[str, Any]) -> int:
        severity_counts = alert_summary.get("by_severity") or {}
        return int(severity_counts.get("P0") or 0) + int(severity_counts.get("P1") or 0)
