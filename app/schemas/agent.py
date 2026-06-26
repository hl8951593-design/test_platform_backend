from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


RunStatus = Literal[
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
    "migration_blocked",
    "needs_human",
]

ToolCallStatus = Literal[
    "planned",
    "leased",
    "running_pre_effect",
    "effect_sent",
    "uncertain",
    "reconciling",
    "succeeded",
    "failed",
    "failed_retryable",
    "obsolete",
    "needs_migration",
    "manual_intervention",
]

EffectSubmissionState = Literal[
    "none",
    "send_intent_recorded",
    "transport_sent_observed",
    "backend_accepted",
    "effect_committed",
    "unknown",
]

BackendEffectCapability = Literal[
    "receipt_first",
    "idempotency_index_only",
    "legacy_reconcile_only",
    "legacy_no_receipt",
]

ApprovalStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "expired",
    "superseded",
]


class AgentRunCreateRequest(BaseModel):
    project_id: int = Field(description="项目 ID")
    intent: str = Field(min_length=1, max_length=4000, description="用户目标")
    conversation_id: str | None = Field(default=None, max_length=64)
    max_iterations: int = Field(default=3, ge=1, le=10)
    auto_complete: bool = Field(default=False, description="框架冒烟用：无工具时是否立即完成")


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    project_id: int
    user_id: int
    conversation_id: str | None = None
    intent: str
    status: RunStatus
    current_iteration: int
    current_step_index: int
    max_iterations: int
    runtime_snapshot_id: str
    last_checkpoint_id: int | None = None
    last_event_sequence: int
    migration_block_count: int = 0
    blocking_tool_call_ids_json: list[str] | None = None
    result_json: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AgentRuntimeSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snapshot_id: str
    project_id: int
    created_by: int
    runtime_hash: str
    tool_registry_hash: str
    manifest_bundle_hash: str
    prompt_bundle_hash: str | None = None
    policy_version_hash: str | None = None
    tools_json: list[dict[str, Any]]
    manifests_json: dict[str, Any]
    adapters_json: dict[str, Any] | None = None
    policies_json: dict[str, Any] | None = None
    created_at: datetime


class AgentEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_seq: int
    event_type: str
    payload_json: dict[str, Any]
    created_at: datetime


class AgentToolCallCreateRequest(BaseModel):
    run_id: str
    tool_name: str
    input: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    step_index: int = Field(ge=0)
    attempt_index: int = Field(default=0, ge=0)
    idempotency_key: str | None = Field(default=None, max_length=128)
    decision_context_build_id: str | None = Field(default=None, max_length=64)


class AgentToolCallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tool_call_id: str
    run_id: str
    step_index: int
    attempt_index: int
    runtime_snapshot_id: str
    tool_name: str
    tool_version: str
    schema_hash: str
    manifest_hash: str
    idempotency_scope: str
    idempotency_key: str
    base_side_effect_class: str
    resolved_side_effect_class: str
    base_replay_policy: str
    resolved_replay_policy: str
    policy_reason_json: dict[str, Any]
    status: ToolCallStatus
    execution_phase: str | None = None
    effect_submission_state: EffectSubmissionState
    input_hash: str
    input_json_redacted: dict[str, Any]
    evidence_refs_json: list[dict[str, Any]]
    policy_evidence_refs_json: list[dict[str, Any]] | None = None
    audit_evidence_refs_json: list[dict[str, Any]] | None = None
    evidence_mutability_summary_json: dict[str, Any] | None = None
    decision_context_build_id: str | None = None
    output_hash: str | None = None
    output_json_redacted: dict[str, Any] | None = None
    required_permissions_json: list[str]
    permission_snapshot_json: dict[str, Any]
    approval_required: bool
    approval_scope_hash: str | None = None
    approval_lineage_id: str | None = None
    approval_epoch: int = 0
    approved_approval_id: str | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    backend_name: str | None = None
    backend_operation: str | None = None
    backend_contract_version: str | None = None
    backend_request_schema_hash: str | None = None
    backend_output_schema_hash: str | None = None
    reconcile_contract_version: str | None = None
    result_adapter_version: str | None = None
    backend_effect_capability: str | None = None
    recovery_decision: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    current_approval: "AgentApprovalRead | None" = None
    approval_lineage: "AgentApprovalLineageRead | None" = None
    recent_reconcile_attempts: list["AgentReconcileAttemptRead"] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AgentCapabilitiesRead(BaseModel):
    run_statuses: list[str]
    tool_call_statuses: list[str]
    effect_submission_states: list[str]
    backend_effect_capabilities: list[str]
    tools: list[dict[str, Any]]


class ReconcileResult(BaseModel):
    found: bool = False
    status: Literal[
        "succeeded",
        "running",
        "failed",
        "not_found",
        "conflict",
        "unsupported_schema_version",
    ]
    schema_support: Literal["supported", "unsupported", "adapter_required"] = "supported"
    backend_contract_version: str
    output_schema_version: str | None = None
    external_resource_type: str | None = None
    external_resource_id: str | None = None
    acceptance_id: str | None = None
    canonical_summary_json: dict[str, Any] = Field(default_factory=dict)
    raw_output_object_key: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class AgentReconcileAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt_seq: int
    backend_name: str
    backend_operation: str
    backend_contract_version: str
    result_status: str
    raw_result_object_key: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    next_retry_at: datetime | None = None
    created_at: datetime


class AgentApprovalLineageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    approval_lineage_id: str
    run_id: str
    tool_call_id: str
    project_id: int
    current_epoch: int
    status: str
    immutable_input_hash: str
    runtime_snapshot_id: str
    resource_scope_hash: str
    created_by: int
    created_at: datetime
    updated_at: datetime


class AgentApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    approval_id: str
    approval_lineage_id: str
    approval_epoch: int
    run_id: str
    tool_call_id: str
    project_id: int
    approval_status: ApprovalStatus
    requested_by: int
    decided_by: int | None = None
    decided_at: datetime | None = None
    input_hash: str
    runtime_snapshot_id: str
    resource_scope_hash: str
    approval_reason: str | None = None
    decision_reason: str | None = None
    required_permissions_json: list[str]
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AgentApprovalMutationLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    approval_lineage_id: str
    approval_id: str | None = None
    tool_call_id: str
    run_id: str
    mutation_type: str
    from_status: str | None = None
    to_status: str
    actor_user_id: int | None = None
    reason: str | None = None
    details_json: dict[str, Any] | None = None
    created_at: datetime


class AgentApprovalDecisionRequest(BaseModel):
    input_hash: str = Field(min_length=1, max_length=64)
    runtime_snapshot_id: str = Field(min_length=1, max_length=64)
    resource_scope_hash: str = Field(min_length=1, max_length=64)
    approval_lineage_id: str = Field(min_length=1, max_length=64)
    approval_epoch: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=512)


class AgentApprovalDecisionRead(BaseModel):
    approval: AgentApprovalRead
    lineage: AgentApprovalLineageRead
    tool_call: AgentToolCallRead
    mutation_log: AgentApprovalMutationLogRead | None = None


class AgentContextBuildCreateRequest(BaseModel):
    build_purpose: str = Field(default="plan", max_length=64)
    step_index: int = Field(default=0, ge=0)
    token_budget: int = Field(default=4000, ge=128)
    model_name: str | None = Field(default=None, max_length=128)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    required_evidence_ref_ids: list[str] = Field(default_factory=list)
    prompt_object_key: str | None = Field(default=None, max_length=512)


class AgentContextBuildRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    context_build_id: str
    run_id: str
    iteration: int
    step_index: int
    build_seq: int
    build_purpose: str
    model_name: str | None = None
    token_budget: int
    estimated_input_tokens: int
    context_degradation_level: str
    compressed_sections_json: dict[str, Any] | None = None
    omitted_evidence_refs_json: list[dict[str, Any]] | None = None
    required_evidence_refs_json: list[str] | None = None
    required_evidence_complete: bool
    decision_quality_risk: str
    prompt_object_key: str | None = None
    prompt_hash: str | None = None
    build_metadata_json: dict[str, Any] | None = None
    created_at: datetime


class AgentEvidenceWatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evidence_watch_id: str
    run_id: str
    tool_call_id: str | None = None
    evidence_ref_id: str
    ref_type: str
    ref_id: str
    watched_version_id: str | None = None
    watched_content_hash: str | None = None
    watch_status: str
    stale_reason: str | None = None
    stale_event_id: str | None = None
    created_at: datetime
    stale_at: datetime | None = None


class AgentRootCauseRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: str
    reason_key: str
    root_cause_primary: str
    causal_chain_json: list[str]
    mitigation_action: str
    priority: int
    priority_band: str
    match_expression_json: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


class AgentLoopObservationCreateRequest(BaseModel):
    decision_context_build_id: str = Field(min_length=1, max_length=64)
    next_action: str = Field(default="repair", max_length=64)
    next_action_is_high_risk: bool = False
    reasons: list[str] = Field(default_factory=list)
    observation: dict[str, Any] = Field(default_factory=dict)


class AgentLoopObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    observation_id: str
    run_id: str
    iteration: int
    step_index: int
    decision_context_build_id: str
    decision_context_degradation_level: str
    iteration_context_degradation_max: str
    required_evidence_complete_for_decision: bool
    omitted_required_evidence_refs_json: list[dict[str, Any]] | None = None
    next_action: str
    next_action_is_high_risk: bool
    stop_action_reason: str | None = None
    stop_reasons_all_json: list[str]
    root_cause_primary: str
    root_cause_rule_id: str
    causal_chain_json: list[str]
    mitigation_action: str
    observation_json: dict[str, Any] | None = None
    created_at: datetime


class AgentRunReconcileRead(BaseModel):
    run_id: str
    processed: int
    reconciled: int
    still_uncertain: int
    needs_migration: int
    manual_intervention: int
    tool_call_ids: list[str] = Field(default_factory=list)


class AgentRunResumeRead(BaseModel):
    run: AgentRunRead
    resumed: bool
    checkpoint_freshness: dict[str, Any]
    scheduled_tool_call_ids: list[str] = Field(default_factory=list)


class AgentBackendContractRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    backend_name: str
    backend_operation: str
    backend_contract_version: str
    request_schema_hash: str
    output_schema_hash: str
    reconcile_contract_version: str
    result_adapter_version: str
    effect_capability: str
    compatibility_status: str
    support_until: datetime | None = None
    owner_team: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentMigrationBlockRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    block_id: str
    run_id: str
    tool_call_id: str | None = None
    status: str
    block_type: str
    reason: str
    backend_name: str | None = None
    backend_operation: str | None = None
    backend_contract_version: str | None = None
    required_migration_type: str | None = None
    details_json: dict[str, Any] | None = None
    resolution_summary_json: dict[str, Any] | None = None
    resolved_by: int | None = None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None


class AgentMigrationBlockResolveRequest(BaseModel):
    resolution_note: str | None = Field(default=None, max_length=512)


class AgentMigrationBlockResolveRead(BaseModel):
    block: AgentMigrationBlockRead
    checkpoint_freshness: dict[str, Any]


class AgentMemoryCreateRequest(BaseModel):
    project_id: int
    memory_type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1)
    source_type: str = Field(min_length=1, max_length=64)
    source_ref_json: dict[str, Any] | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)


class AgentMemoryUpdateRequest(BaseModel):
    memory_type: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=256)
    content: str | None = Field(default=None, min_length=1)
    source_ref_json: dict[str, Any] | None = None
    evidence_refs: list[dict[str, Any]] | None = None
    status: str | None = Field(default=None, max_length=32)
    reason: str | None = Field(default=None, max_length=512)


class AgentMemoryDecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=512)


class AgentMemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    memory_type: str
    title: str
    content: str
    content_hash: str
    memory_version: int
    source_type: str
    source_ref_json: dict[str, Any] | None = None
    authority: str
    confidence: float
    initial_confidence: float
    confidence_reason_json: dict[str, Any] | None = None
    contradiction_count: int
    recent_contradiction_count: int
    validation_count: int
    recent_validation_count: int
    stale_score: float
    stale_reason_json: dict[str, Any] | None = None
    status: str
    evidence_refs_json: list[dict[str, Any]] | None = None
    watched_refs_json: list[dict[str, Any]] | None = None
    created_by: int
    created_at: datetime
    updated_at: datetime


class AgentMemoryRetrieveRequest(BaseModel):
    project_id: int
    query: str = ""
    profile_name: str = "normal_plan_v1"
    task_risk: str = "normal"
    usage_role: str = "planning_hint"
    run_id: str | None = None
    step_index: int | None = Field(default=None, ge=0)
    limit: int = Field(default=5, ge=1, le=20)


class AgentMemoryCandidateRead(BaseModel):
    memory_id: int
    memory_version: int
    title: str
    content: str
    source_type: str
    confidence: float
    stale_score: float
    retrieval_score: float
    retrieval_profile: str
    evidence_ref: dict[str, Any]
    allowed_usage: str


class AgentMemorySourceProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_type: str
    initial_confidence: float
    authority: str
    default_ttl_days: int | None = None
    requires_source_ref: bool
    requires_content_hash: bool
    allowed_for_high_risk: bool
    status: str


class AgentMemoryRetrievalProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    profile_name: str
    task_scope: str
    risk_level: str
    min_confidence: float
    max_stale_score: float
    allow_memory_for_high_risk: bool
    semantic_weight: float
    confidence_weight: float
    recency_weight: float
    authority_weight: float
    validation_weight: float
    stale_weight: float
    contradiction_weight: float
    max_contradiction_penalty: float
    version: int
    status: str
    change_reason: str | None = None


class AgentMemoryUsageEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    memory_id: int
    run_id: str | None = None
    iteration: int | None = None
    step_index: int | None = None
    tool_call_id: str | None = None
    context_build_id: str | None = None
    retrieval_profile: str
    retrieval_score: float
    usage_role: str
    active_for_policy: bool
    caused_tool_input_change: bool
    outcome: str | None = None
    evidence_ref_json: dict[str, Any] | None = None
    feedback_state: str
    feedback_processed_at: datetime | None = None
    feedback_result_json: dict[str, Any] | None = None
    created_at: datetime


class AgentMemoryFeedbackRequest(BaseModel):
    outcome: str = Field(min_length=1, max_length=64)
    caused_tool_input_change: bool | None = None
    failure_fingerprint: str | None = Field(default=None, max_length=64)
    contradiction_type: str | None = Field(default=None, max_length=64)
    severity: str | None = Field(default=None, max_length=32)
    reason: str | None = Field(default=None, max_length=512)


class AgentMemoryFeedbackProcessRead(BaseModel):
    attempted: int
    processed: int
    skipped: int
    contradictions_recorded: int
    results: list[dict[str, Any]]


class AgentOutboxPublishRead(BaseModel):
    attempted: int
    published: int
    failed: int
    dead_letter: int
    pending_remaining: int
    outbox_publish_lag_ms: int


class AgentMetricsSnapshotRead(BaseModel):
    project_id: int | None = None
    generated_at: str
    metrics: dict[str, int | float]
    derived_from: dict[str, Any]


class AgentReleaseGateToolRead(BaseModel):
    tool_name: str
    tool_version: str
    side_effect_class: str
    replay_policy: str
    required_permissions: list[str]
    backend_name: str | None = None
    backend_operation: str | None = None
    backend_contract_version: str | None = None
    backend_effect_capability: str | None = None
    backend_contract_status: str | None = None
    rollout_allowed: bool
    rollout_decision: str


class AgentReleaseGateLevelRead(BaseModel):
    level: str
    summary: str
    required_gates: list[str]
    unlocked: bool
    blocked_reasons: list[str]


class AgentReleaseGateViolationRead(BaseModel):
    tool_name: str
    reason: str
    side_effect_class: str


class AgentReleaseGateRead(BaseModel):
    current_level: str
    current_level_summary: str
    allowed_side_effect_classes: list[str]
    blocked_side_effect_classes: list[str]
    tool_matrix: list[AgentReleaseGateToolRead]
    expansion_gates: list[AgentReleaseGateLevelRead]
    violations: list[AgentReleaseGateViolationRead]


class AgentRunbookRead(BaseModel):
    runbook_id: str
    title: str
    trigger: str
    severity: str
    steps: list[str]
    safe_api_actions: list[str]


class AgentRunbookRecommendationRead(BaseModel):
    runbook_id: str
    reason: str
    severity: str
    action: str
    tool_call_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AgentRunbookDiagnosisRead(BaseModel):
    run_id: str
    run_status: str
    recommendations: list[AgentRunbookRecommendationRead]
    runbooks: list[AgentRunbookRead]


class AgentFaultInjectionCaseRead(BaseModel):
    case_id: str
    description: str
    expected: dict[str, Any]


class AgentFaultInjectionRequest(BaseModel):
    project_id: int
    case_ids: list[str] | None = Field(default=None, max_length=20)


class AgentFaultInjectionResultRead(BaseModel):
    case_id: str
    run_id: str
    tool_call_id: str | None = None
    passed: bool
    observed: dict[str, Any]
    evidence: dict[str, Any]


class AgentFaultInjectionRunRead(BaseModel):
    project_id: int
    requested: int
    passed: int
    failed: int
    results: list[AgentFaultInjectionResultRead]


AgentToolCallRead.model_rebuild()
