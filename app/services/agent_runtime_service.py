from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.sensitive_data import mask_sensitive, request_fingerprint
from app.db.session import SessionLocal, dispose_engine_after_disconnect
from app.models.agent import (
    AGENT_APPROVAL_ITEM_ID_PREFIX as AGENT_APPROVAL_MODEL_ITEM_ID_PREFIX,
    AGENT_APPROVAL_LINEAGE_ITEM_ID_PREFIX as AGENT_APPROVAL_LINEAGE_MODEL_ITEM_ID_PREFIX,
    AGENT_EVENT_ITEM_ID_PREFIX as AGENT_EVENT_MODEL_ITEM_ID_PREFIX,
    AGENT_MIGRATION_BLOCK_ITEM_ID_PREFIX as AGENT_MIGRATION_BLOCK_MODEL_ITEM_ID_PREFIX,
    AGENT_RECONCILE_ATTEMPT_ITEM_ID_PREFIX as AGENT_RECONCILE_ATTEMPT_MODEL_ITEM_ID_PREFIX,
    AGENT_RUNTIME_SNAPSHOT_ITEM_ID_PREFIX as AGENT_RUNTIME_SNAPSHOT_MODEL_ITEM_ID_PREFIX,
    AGENT_RUN_ITEM_ID_PREFIX as AGENT_RUN_MODEL_ITEM_ID_PREFIX,
    AGENT_TOOL_CALL_ITEM_ID_PREFIX as AGENT_TOOL_CALL_MODEL_ITEM_ID_PREFIX,
    AgentApproval,
    AgentBackendContract,
    AgentCheckpoint,
    AgentEvent,
    AgentMemoryUsageEvent,
    AgentMigrationBlock,
    AgentOutbox,
    AgentRun,
    AgentRuntimeSnapshot,
    AgentToolCall,
    AgentWorkerQueue,
)
from app.models.user import User
from app.schemas.ai import AIChatMessage, AIChatRequest
from app.schemas.agent import (
    AgentContextBuildCreateRequest,
    AgentLoopObservationCreateRequest,
    AgentRunCreateRequest,
    AgentToolCallCreateRequest,
)
from app.services.agent_approval_service import ApprovalService, PolicyManager
from app.services.agent_loop_service import ContextBuilder, EvidenceRefResolver, EvidenceWatchService, LoopController
from app.services.agent_memory_service import MemoryCandidate, MemoryManager
from app.services.agent_skill_registry import AgentSkill, AgentSkillRegistry
from app.services.agent_tool_result_policy import FINAL_RESPONSE_BUDGET_INSTRUCTION, build_tool_result_message
from app.services.ai_service import AIService
from app.services.agent_tool_service import AgentToolBackend, SAFE_SIDE_EFFECT_CLASSES, ToolPolicyResolver, ToolRegistry
from app.services.permission_service import PermissionService


logger = logging.getLogger(__name__)

RUN_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
RUN_TERMINAL_EVENT_TYPES_BY_STATUS = {
    "completed": "run.completed",
    "failed": "run.failed",
    "cancelled": "run.cancelled",
}
RUN_STALE_ACTIVE_STATUSES = {"queued", "running"}
RUN_STATUSES = ["queued", "running", "paused", "completed", "failed", "cancelled", "migration_blocked", "needs_human"]
TOOL_CALL_STATUSES = [
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
HIGH_RISK_SIDE_EFFECT_CLASSES = {"business_create", "business_update", "destructive", "external_effect"}
TOOL_CALL_CLAIMABLE_STATUSES = {"planned"}
TOOL_CALL_HEARTBEAT_ACTIVE_STATUSES = {"leased", "running_pre_effect"}
TOOL_CALL_EXECUTABLE_STATUSES = {"planned", "leased"}
TOOL_CALL_EFFECT_SUBMISSION_STARTED_STATES = {
    "send_intent_recorded",
    "transport_sent_observed",
    "backend_accepted",
    "effect_committed",
    "unknown",
}
EFFECT_SUBMISSION_STATES = [
    "none",
    "send_intent_recorded",
    "transport_sent_observed",
    "backend_accepted",
    "effect_committed",
    "unknown",
]
BACKEND_EFFECT_CAPABILITIES = [
    "receipt_first",
    "idempotency_index_only",
    "legacy_reconcile_only",
    "legacy_no_receipt",
]
APPROVAL_STATUSES = ["pending", "approved", "rejected", "expired", "revoked", "superseded"]
MIGRATION_BLOCK_STATUSES = ["open", "resolved", "cancelled"]
AGENT_ERROR_MESSAGE_SUMMARY_VERSION = "agent_error_message_summary_v1"
AGENT_ERROR_MESSAGE_MAX_CHARS = 512
AGENT_ERROR_MESSAGE_TRUNCATION_MARKER = "[agent_error_message_truncated]"
AGENT_CONTENT_PREVIEW_SUMMARY_VERSION = "agent_content_preview_summary_v1"
AGENT_CONTENT_PREVIEW_MAX_CHARS = 512
AGENT_CONTENT_PREVIEW_TRUNCATION_MARKER = "[agent_content_preview_truncated]"
AGENT_TOOL_REQUEST_CONTEXT_SUMMARY_VERSION = "agent_tool_request_context_summary_v1"
AGENT_INTERNAL_TOOL_CONTEXT_LEAK_MESSAGE = (
    "工具执行已完成，但模型返回了仅供内部循环使用的工具上下文摘要；后端已阻止该摘要展示给用户。"
)

AGENT_CONVERSATION_SYSTEM_PROMPT = (
    "你是 TestAuto 自动化测试平台的 Harness Loop Agent。"
    "你需要用简洁、可执行的中文回复用户，优先说明你能如何帮助测试平台完成接口测试、"
    "场景编排、缺陷分析、执行诊断、Agent 工具调用和运行恢复。"
    "当前能力必须以平台后端已经暴露的 Agent Run、EventStore、ToolCall、Approval、"
    "Memory、Runbook 和 Dashboard 契约为边界。"
    "当需要平台上下文或草稿能力时，只能通过下方工具协议提出一次工具调用，"
    "不要假装已经完成真实工具副作用。"
    "如果用户要求创建、生成、读取或分析平台对象，必须优先遵循已加载 Agent Skill 和可用工具，"
    "不要仅用自然语言答复。当前 Agent Run 已携带 project_id，除非工具确实缺少不可推断字段，否则不要向用户反问 project_id。"
)
AGENT_SKILL_CATALOG_PROMPT = """
Agent Skill 目录如下。它们采用 Codex 式渐进加载：模型始终可见 name/description；当用户目标命中某个 Skill 时，后端会额外注入该 Skill 的正文流程。
{skills}

选择行为：
- 先根据用户目标和 Skill description 判断任务类型。
- 已加载 Skill 正文时，优先遵循正文中的 workflow、tool boundary、output 和 done criteria。
- 未加载 Skill 正文时，只使用基础平台规则和可用工具，不要臆造未声明能力。
""".strip()
AGENT_MARKDOWN_RESPONSE_PROMPT = """
面向用户的自然语言回复必须严格遵守 GitHub Flavored Markdown：
- 不要把整段回复包在 ```markdown fenced block 中。
- 标题、列表、引用、代码块和表格前后要保留合理换行。
- 如果使用表格，必须是标准 Markdown 表格：表头、分隔行和每一条数据行都必须独占一行。
- 表格分隔行只使用 `---` / `:---` / `---:` / `:---:`；不要用 `| |` 把多行表格拼在同一行。
- 表格单元格内不要直接输出未转义的 `|`；复杂说明改用列表。
- 代码必须使用闭合 fenced block，并尽量标注语言。
- 最终回复前自检 Markdown 能被前端渲染器直接渲染。
""".strip()
AGENT_TOOL_PROTOCOL_PROMPT = """
可用工具如下：
{tools}

如果需要调用工具，请只输出一个 fenced block，格式必须完全符合：
```agent_tool_request
{"tool_name":"project.read_context","input":{"project_id":123},"reason":"为什么需要这个工具","evidence_refs":[]}
```
不要在工具请求前后输出面向用户的自然语言。工具执行结果返回后，再根据结果给用户最终答复。
如果不需要工具，请直接用自然语言回答。
""".strip()
TOOL_REQUEST_BLOCK_RE = re.compile(r"```agent_tool_request\s*(?P<body>\{.*?\})\s*```", re.S)
MARKDOWN_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
AGENT_MODEL_DELTA_FLUSH_INTERVAL_SECONDS = 0.35
AGENT_MODEL_DELTA_FLUSH_CHARS = 240
AGENT_MODEL_STREAM_CANCEL_CHECK_INTERVAL_SECONDS = 0.2
AGENT_HISTORY_CONTEXT_MAX_RUNS = 12
AGENT_HISTORY_CONTEXT_TOKEN_BUDGET = 2400
AGENT_HISTORY_CONTEXT_FULL_TURNS = 4
AGENT_HISTORY_CONTEXT_SUMMARY_CHARS = 360
AGENT_HISTORY_CONTEXT_RECENT_USER_CHARS = 800
AGENT_HISTORY_CONTEXT_RECENT_ASSISTANT_CHARS = 1200
AGENT_HISTORY_CONTEXT_SOURCE_STATUS = "completed"
AGENT_HISTORY_CONTEXT_EXCLUDED_STATUSES = tuple(
    status for status in RUN_STATUSES if status != AGENT_HISTORY_CONTEXT_SOURCE_STATUS
)
AGENT_HISTORY_CONTEXT_ASSISTANT_VISIBILITY_RULE = "assistant_visible_not_false"
AGENT_HISTORY_CONTEXT_USER_INTENT_RULE = "completed_history_user_intent_included"
AGENT_HISTORY_CONTEXT_ORDER = "oldest_to_newest_after_desc_limit"
AGENT_HISTORY_CONTEXT_COMPACTION_STRATEGY = "summarize_older_keep_recent"
AGENT_HISTORY_CONTEXT_COMPACTION_EVENT = "context.history_compacted"
AGENT_HISTORY_COMPACTION_PAYLOAD_FIELDS = (
    "trigger",
    "reason",
    "phase",
    "implementation",
    "strategy",
    "original_run_count",
    "compacted_run_count",
    "kept_full_run_count",
    "estimated_input_units_before",
    "estimated_input_units_after",
    "budget_limit_units",
    "summary_role",
    "replacement_history",
    "initial_context_injection",
    "reference_context_item",
    "context_baseline",
    "window_number",
    "first_window_id",
    "previous_window_id",
    "window_id",
    "source",
)
AGENT_HISTORY_COMPACTION_ENVELOPE_FIELDS = AGENT_HISTORY_COMPACTION_PAYLOAD_FIELDS
AGENT_HISTORY_COMPACTION_TRIGGER = "auto"
AGENT_HISTORY_COMPACTION_REASON = "history_budget_exceeded"
AGENT_HISTORY_COMPACTION_PHASE = "pre_model_call"
AGENT_HISTORY_COMPACTION_IMPLEMENTATION = "inline_deterministic_summary"
AGENT_HISTORY_COMPACTION_REPLACEMENT_HISTORY = "summary_plus_recent_turns"
AGENT_HISTORY_COMPACTION_INITIAL_CONTEXT_INJECTION = "system_prompt_before_history"
AGENT_HISTORY_COMPACTION_REFERENCE_CONTEXT_ITEM = "not_persisted"
AGENT_HISTORY_COMPACTION_CONTEXT_BASELINE = "system_run_skill_memory_rebuilt_per_model_call"
AGENT_HISTORY_COMPACTION_WINDOW_ID_PREFIX = "agent-window"
AGENT_HISTORY_COMPACTION_CODEX_ALIGNMENT = "ContextCompactionItem"
AGENT_HISTORY_COMPACTION_SOURCE = "AgentConversationRunner._conversation_history_messages"
AGENT_EVENT_ITEM_ID_PREFIX = AGENT_EVENT_MODEL_ITEM_ID_PREFIX
AGENT_RUN_ITEM_ID_PREFIX = AGENT_RUN_MODEL_ITEM_ID_PREFIX
AGENT_RUNTIME_SNAPSHOT_ITEM_ID_PREFIX = AGENT_RUNTIME_SNAPSHOT_MODEL_ITEM_ID_PREFIX
AGENT_APPROVAL_ITEM_ID_PREFIX = AGENT_APPROVAL_MODEL_ITEM_ID_PREFIX
AGENT_APPROVAL_LINEAGE_ITEM_ID_PREFIX = AGENT_APPROVAL_LINEAGE_MODEL_ITEM_ID_PREFIX
AGENT_MIGRATION_BLOCK_ITEM_ID_PREFIX = AGENT_MIGRATION_BLOCK_MODEL_ITEM_ID_PREFIX
AGENT_TOOL_CALL_ITEM_ID_PREFIX = AGENT_TOOL_CALL_MODEL_ITEM_ID_PREFIX
AGENT_RECONCILE_ATTEMPT_ITEM_ID_PREFIX = AGENT_RECONCILE_ATTEMPT_MODEL_ITEM_ID_PREFIX
AGENT_CONTEXT_COMPACTION_OBJECT_KEY_PREFIX = AGENT_EVENT_ITEM_ID_PREFIX
AGENT_CONTEXT_COMPACTION_ITEM_ID_PREFIX = "agent-context-compaction"
AGENT_MODEL_RESPONSE_ITEM_ID_PREFIX = "agent-model-response"
AGENT_HISTORY_CONTEXT_SUMMARY_ROLE = "system"
AGENT_HISTORY_CONTEXT_CURRENT_USER_POSITION = "last"
AGENT_MEMORY_CONTEXT_MESSAGE_MAX_CHARS = 3000
AGENT_MEMORY_CONTEXT_TITLE_MAX_CHARS = 180
AGENT_MEMORY_CONTEXT_CONTENT_MAX_CHARS = 500
AGENT_MEMORY_CONTEXT_TRUNCATION_MARKER = "[agent_memory_context_truncated]"
AGENT_UNSUPPORTED_CAPABILITY_CLASSIFIER_PROMPT_MAX_CHARS = 3000
AGENT_UNSUPPORTED_CAPABILITY_CLASSIFIER_PROMPT_TRUNCATION_MARKER = (
    "\n\n[agent_classifier_prompt_truncated: full private classifier prompt is not injected into model context]"
)
AGENT_TOOL_RESULT_CONTEXT_TOTAL_MAX_CHARS = 12000
AGENT_TOOL_RESULT_CONTEXT_TRUNCATION_MARKER = (
    "\n\n[agent_tool_result_context_truncated: additional tool results remain available in ToolCall detail]"
)
AGENT_REPAIR_CONTEXT_MAX_CHARS = 3000
AGENT_REPAIR_CONTEXT_TRUNCATION_MARKER = (
    "\n\n[agent_repair_context_truncated: full previous model content is not injected into repair context]"
)


REQUIRES_TOOL_ROUTING_KEY = "routing_requires_tool"
REQUIRED_TOOL_AFTER_SUCCESS_ROUTING_KEY = "routing_required_tool_after_success"
UNSUPPORTED_CAPABILITY_GUARD_KEY = "guard_unsupported_capability"
AMBIGUOUS_DEICTIC_GUARD_SUBJECTS = frozenset({
    "直接",
    "刚才",
    "上面",
    "前面",
    "这个",
    "这些",
    "它",
    "this",
    "that",
    "above",
    "previous",
})


@dataclass(frozen=True)
class RequiredToolFollowupRule:
    after_tool: str
    required_tool: str
    min_total_fields: tuple[str, ...] = ()
    intent_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnsupportedCapabilityGuard:
    skill_name: str
    name: str
    intent_key: str
    subject_key: str
    unavailable_tools: tuple[str, ...]
    classifier_prompt_key: str
    requires_field: str
    completion_source: str
    message_key: str
    synthetic_reason: str


@dataclass(frozen=True)
class AgentToolRequest:
    tool_name: str
    tool_input: dict[str, Any]
    reason: str | None = None
    evidence_refs: tuple[dict[str, Any], ...] = ()

    def input_for_ledger(self) -> dict[str, Any]:
        return dict(self.tool_input)

    def evidence_refs_for_ledger(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.evidence_refs]

    def detected_event_payload(self, *, iteration: int) -> dict[str, Any]:
        reason = (
            _bounded_agent_error_message(
                self.reason,
                reference="AgentConversationRunner.model.tool_request_detected.reason",
            )
            if self.reason is not None
            else None
        )
        return {
            "iteration": iteration,
            "tool_name": self.tool_name,
            "reason": reason,
            "decision_reason": reason,
        }


AGENT_RUN_FIELDS = (
    "item_id",
    "run_id",
    "project_id",
    "user_id",
    "conversation_id",
    "intent",
    "status",
    "current_iteration",
    "current_step_index",
    "max_iterations",
    "runtime_snapshot_id",
    "last_checkpoint_id",
    "last_event_sequence",
    "migration_block_count",
    "blocking_tool_call_ids_json",
    "result_json",
    "error_code",
    "error_message",
    "started_at",
    "completed_at",
    "created_at",
    "updated_at",
)

AGENT_RUN_SUMMARY_FIELDS = (
    "run",
    "assistant_message",
    "assistant_visible",
    "completion_source",
    "model_invoked",
    "model",
    "finish_reason",
    "usage",
    "event_count",
    "latest_event_sequence",
    "latest_event_types",
    "tool_call_count",
    "pending_tool_call_count",
    "approval_count",
    "pending_approval_count",
    "migration_block_count",
    "open_migration_block_count",
    "memory_usage_count",
    "blocking_tool_call_ids",
    "terminal",
    "can_cancel",
    "can_resume",
    "updated_at",
)

AGENT_RUN_ACTION_FIELDS = (
    "action_id",
    "label",
    "method",
    "path",
    "enabled",
    "reason",
    "severity",
    "resource_ids",
    "resource_item_ids",
    "details",
)

AGENT_RUN_ACTION_STATE_FIELDS = (
    "run_summary",
    "actions",
    "primary_action_ids",
    "blocked_reasons",
    "generated_at",
)
AGENT_RUN_ACTION_PRIMARY_PRIORITY = (
    "review_approvals",
    "resolve_migration",
    "reconcile_run",
    "resume_run",
    "open_runbook",
    "cancel_run",
)
AGENT_RUN_ACTION_RESOURCE_ORDER_TOOL_CALL = ("step_index", "attempt_index", "id")
AGENT_RUN_ACTION_RESOURCE_ORDER_APPROVAL = ("created_at", "id")
AGENT_RUN_ACTION_RESOURCE_ORDER_MIGRATION_BLOCK = ("created_at", "id")

AGENT_CONVERSATION_FIELDS = (
    "conversation_id",
    "project_id",
    "title",
    "run_count",
    "latest_run_id",
    "latest_run_status",
    "created_at",
    "updated_at",
)

AGENT_CONVERSATION_CONTEXT_COMPACTION_FIELDS = (
    "item_id",
    "run_id",
    "event_seq",
    "event_type",
    "payload_json",
    "created_at",
)

AGENT_CONVERSATION_TRANSCRIPT_FIELDS = (
    "conversation",
    "turns",
    "context_compactions",
    "generated_at",
)

AGENT_CONVERSATION_EXPORT_FIELDS = (
    "conversation",
    "turns",
    "context_compactions",
    "events_by_run_id",
    "tool_calls_by_run_id",
    "approvals_by_run_id",
    "migration_blocks_by_run_id",
    "export_format",
    "generated_at",
    "derived_from",
)

AGENT_MODEL_HEALTH_FIELDS = (
    "provider",
    "configured",
    "base_url",
    "default_model",
    "live",
    "reachable",
    "latency_ms",
    "first_delta_received",
    "completed",
    "model",
    "finish_reason",
    "error_code",
    "error_message",
    "checked_at",
)

AGENT_CONVERSATION_SMOKE_FIELDS = (
    "project_id",
    "run_id",
    "conversation_id",
    "status",
    "completed",
    "first_delta_received",
    "assistant_visible",
    "assistant_message",
    "error_code",
    "error_message",
    "event_types",
    "latest_event_sequence",
    "run_summary",
    "latency_ms",
    "generated_at",
)

AGENT_EVENT_FIELDS = (
    "item_id",
    "event_seq",
    "event_type",
    "payload_json",
    "created_at",
)

AGENT_RUN_EVENT_SNAPSHOT_FIELDS = (
    "run",
    "events",
    "context_compactions",
    "after_sequence",
    "event_count",
    "latest_event_sequence",
    "next_after_sequence",
    "terminal",
    "generated_at",
)

RUNTIME_SNAPSHOT_FIELDS = (
    "item_id",
    "snapshot_id",
    "project_id",
    "created_by",
    "runtime_hash",
    "tool_registry_hash",
    "manifest_bundle_hash",
    "prompt_bundle_hash",
    "policy_version_hash",
    "tools_json",
    "manifests_json",
    "adapters_json",
    "policies_json",
    "created_at",
)

TOOL_CALL_FIELDS = (
    "item_id",
    "tool_call_id",
    "run_id",
    "step_index",
    "attempt_index",
    "runtime_snapshot_id",
    "tool_name",
    "tool_version",
    "schema_hash",
    "manifest_hash",
    "idempotency_scope",
    "idempotency_key",
    "base_side_effect_class",
    "resolved_side_effect_class",
    "base_replay_policy",
    "resolved_replay_policy",
    "policy_reason_json",
    "status",
    "execution_phase",
    "effect_submission_state",
    "input_hash",
    "input_json_redacted",
    "evidence_refs_json",
    "policy_evidence_refs_json",
    "audit_evidence_refs_json",
    "evidence_mutability_summary_json",
    "decision_context_build_id",
    "output_hash",
    "output_json_redacted",
    "required_permissions_json",
    "permission_snapshot_json",
    "approval_required",
    "approval_scope_hash",
    "approval_lineage_id",
    "approval_epoch",
    "approved_approval_id",
    "approved_by",
    "approved_at",
    "backend_name",
    "backend_operation",
    "backend_contract_version",
    "backend_request_schema_hash",
    "backend_output_schema_hash",
    "reconcile_contract_version",
    "result_adapter_version",
    "backend_effect_capability",
    "recovery_decision",
    "error_code",
    "error_message",
    "current_approval",
    "approval_lineage",
    "recent_reconcile_attempts",
    "created_at",
    "updated_at",
)

APPROVAL_FIELDS = (
    "item_id",
    "approval_id",
    "approval_lineage_id",
    "approval_epoch",
    "run_id",
    "tool_call_id",
    "tool_call_item_id",
    "project_id",
    "approval_status",
    "requested_by",
    "decided_by",
    "decided_at",
    "input_hash",
    "runtime_snapshot_id",
    "resource_scope_hash",
    "approval_reason",
    "decision_reason",
    "required_permissions_json",
    "expires_at",
    "created_at",
    "updated_at",
)

MIGRATION_BLOCK_FIELDS = (
    "item_id",
    "block_id",
    "run_id",
    "tool_call_id",
    "tool_call_item_id",
    "status",
    "block_type",
    "reason",
    "backend_name",
    "backend_operation",
    "backend_contract_version",
    "required_migration_type",
    "details_json",
    "resolution_summary_json",
    "resolved_by",
    "created_at",
    "updated_at",
    "resolved_at",
)


class AgentModelHealthService:
    def check(self, *, live: bool = False) -> dict[str, Any]:
        ai_service = AIService()
        provider = ai_service.provider_config()
        payload: dict[str, Any] = {
            "provider": provider.provider,
            "configured": provider.configured,
            "base_url": provider.base_url,
            "default_model": provider.default_model,
            "live": live,
            "reachable": None,
            "latency_ms": None,
            "first_delta_received": None,
            "completed": None,
            "model": None,
            "finish_reason": None,
            "error_code": None,
            "error_message": None,
            "checked_at": _utcnow(),
        }
        if not live:
            return payload
        if not provider.configured:
            payload.update(
                {
                    "reachable": False,
                    "first_delta_received": False,
                    "completed": False,
                    "error_code": "deepseek_api_key_missing",
                    "error_message": "DeepSeek API Key is not configured",
                }
            )
            return payload

        started = time.perf_counter()
        try:
            request = AIChatRequest(
                messages=[AIChatMessage(role="user", content="Please reply with exactly: ok")],
                temperature=0,
                max_tokens=32,
            )
            first_delta_received = False
            completed = False
            model = None
            finish_reason = None
            for item in ai_service.chat_stream(request):
                if item.get("type") == "delta":
                    first_delta_received = True
                elif item.get("type") == "done":
                    completed = True
                    model = item.get("model")
                    finish_reason = item.get("finish_reason")
                    break
            payload.update(
                {
                    "reachable": True,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "first_delta_received": first_delta_received,
                    "completed": completed,
                    "model": model,
                    "finish_reason": finish_reason,
                }
            )
            return payload
        except HTTPException as exc:
            detail = _bounded_agent_error_message(
                _http_exception_detail(exc),
                reference="AgentModelHealthService.check.http_exception",
            )
            payload.update(
                {
                    "reachable": False,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "first_delta_received": False,
                    "completed": False,
                    "error_code": "deepseek_http_error",
                    "error_message": detail,
                }
            )
            return payload
        except Exception as exc:  # noqa: BLE001
            detail = _bounded_agent_error_message(
                exc,
                reference="AgentModelHealthService.check.exception",
            )
            payload.update(
                {
                    "reachable": False,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "first_delta_received": False,
                    "completed": False,
                    "error_code": "deepseek_probe_error",
                    "error_message": detail,
                }
            )
            return payload


class AgentRuntimeService:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)
        self.tool_registry = ToolRegistry()

    def capabilities(self) -> dict[str, Any]:
        return {
            "run_statuses": RUN_STATUSES,
            "tool_call_statuses": TOOL_CALL_STATUSES,
            "effect_submission_states": EFFECT_SUBMISSION_STATES,
            "backend_effect_capabilities": BACKEND_EFFECT_CAPABILITIES,
            "approval_statuses": APPROVAL_STATUSES,
            "migration_block_statuses": MIGRATION_BLOCK_STATUSES,
            "tools": self.tool_registry.registry_json(),
        }

    def run_conversation_smoke(
        self,
        *,
        project_id: int,
        intent: str,
        max_iterations: int,
        current_user: User,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        run = self.create_run(
            payload=AgentRunCreateRequest(
                project_id=project_id,
                intent=intent,
                max_iterations=max_iterations,
                auto_complete=False,
            ),
            current_user=current_user,
        )
        AgentConversationRunner(self.db).run(run_id=run.run_id, user_id=current_user.id)
        self.db.refresh(run)
        summary = self.get_run_summary(run_id=run.run_id, current_user=current_user)
        events = list(
            self.db.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == run.run_id)
                .order_by(AgentEvent.event_seq.asc())
            ).all()
        )
        event_types = [event.event_type for event in events]
        return {
            "project_id": project_id,
            "run_id": run.run_id,
            "conversation_id": run.conversation_id,
            "status": run.status,
            "completed": run.status == "completed",
            "first_delta_received": "model.delta" in event_types,
            "assistant_visible": bool(summary["assistant_visible"]),
            "assistant_message": summary["assistant_message"],
            "error_code": run.error_code,
            "error_message": run.error_message,
            "event_types": event_types,
            "latest_event_sequence": run.last_event_sequence,
            "run_summary": summary,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "generated_at": _utcnow(),
        }

    def ensure_backend_contracts(self, *, commit: bool = True) -> None:
        self._seed_backend_contracts()
        if commit:
            self.db.commit()
        else:
            self.db.flush()

    def create_run(self, *, payload: AgentRunCreateRequest, current_user: User) -> AgentRun:
        self.permission_service.require_project_access(current_user, payload.project_id)
        snapshot = self._get_or_create_snapshot(project_id=payload.project_id, current_user=current_user)
        now = _utcnow()
        conversation_id = payload.conversation_id or f"agent-conv-{uuid.uuid4().hex}"
        run = AgentRun(
            run_id=f"agent-run-{uuid.uuid4().hex}",
            project_id=payload.project_id,
            user_id=current_user.id,
            conversation_id=conversation_id,
            intent=payload.intent,
            status="queued",
            current_iteration=0,
            current_step_index=0,
            max_iterations=payload.max_iterations,
            runtime_snapshot_id=snapshot.snapshot_id,
            last_event_sequence=0,
            created_at=now,
            updated_at=now,
        )
        self.db.add(run)
        self.db.flush()
        self.append_event(run, "run.queued", {"intent": payload.intent}, commit=False)
        run.status = "running"
        run.started_at = now
        self.append_event(run, "run.started", {"runtime_snapshot_id": snapshot.snapshot_id}, commit=False)
        checkpoint = self.create_checkpoint(run, commit=False)
        run.last_checkpoint_id = checkpoint.id
        if payload.auto_complete:
            self.complete_run(
                run,
                {
                    "message": "Agent smoke run completed without model invocation.",
                    "completion_source": "smoke_auto_complete",
                    "model_invoked": False,
                    "assistant_visible": False,
                },
                commit=False,
            )
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_run(self, *, run_id: str, current_user: User) -> AgentRun:
        run = self._get_run_or_404(run_id)
        self.permission_service.require_project_access(current_user, run.project_id)
        return self._fail_stale_active_run_if_needed(run)

    def get_run_summary(self, *, run_id: str, current_user: User) -> dict[str, Any]:
        run = self.get_run(run_id=run_id, current_user=current_user)
        latest_events_desc = list(
            self.db.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == run_id)
                .order_by(AgentEvent.event_seq.desc())
                .limit(8)
            ).all()
        )
        latest_events = list(reversed(latest_events_desc))
        event_count = self._count_where(AgentEvent.run_id == run_id, model=AgentEvent)
        tool_call_count = self._count_where(AgentToolCall.run_id == run_id, model=AgentToolCall)
        pending_tool_call_count = self._count_where(
            AgentToolCall.run_id == run_id,
            AgentToolCall.status.notin_(["succeeded", "failed", "obsolete"]),
            model=AgentToolCall,
        )
        retryable_tool_call_count = self._count_where(
            AgentToolCall.run_id == run_id,
            AgentToolCall.status == "failed_retryable",
            model=AgentToolCall,
        )
        approval_count = self._count_where(AgentApproval.run_id == run_id, model=AgentApproval)
        pending_approval_count = self._count_where(
            AgentApproval.run_id == run_id,
            AgentApproval.approval_status == "pending",
            model=AgentApproval,
        )
        migration_block_count = self._count_where(AgentMigrationBlock.run_id == run_id, model=AgentMigrationBlock)
        open_migration_block_count = self._count_where(
            AgentMigrationBlock.run_id == run_id,
            AgentMigrationBlock.status == "open",
            model=AgentMigrationBlock,
        )
        memory_usage_count = self._count_where(AgentMemoryUsageEvent.run_id == run_id, model=AgentMemoryUsageEvent)

        result = run.result_json or {}
        model_completed_payload = self._latest_event_payload(run_id, "model.completed")
        assistant_visible = bool(result.get("assistant_visible", True))
        assistant_message = result.get("message") if assistant_visible else None
        model = result.get("model") or model_completed_payload.get("model")
        finish_reason = result.get("finish_reason") or model_completed_payload.get("finish_reason")
        usage = result.get("usage") or model_completed_payload.get("usage")
        model_invoked = result.get("model_invoked")
        if model_invoked is None:
            model_invoked = self._latest_event_payload(run_id, "model.started") != {}

        blocking_tool_call_ids = list(dict.fromkeys(run.blocking_tool_call_ids_json or []))
        terminal = run.status in RUN_TERMINAL_STATUSES
        resume_candidate = (
            run.status in {"paused", "needs_human", "migration_blocked"}
            or bool(blocking_tool_call_ids)
            or retryable_tool_call_count > 0
        )
        can_resume = (
            resume_candidate
            and not terminal
            and pending_approval_count == 0
            and open_migration_block_count == 0
        )
        return {
            "run": run,
            "assistant_message": assistant_message,
            "assistant_visible": assistant_visible,
            "completion_source": result.get("completion_source"),
            "model_invoked": model_invoked,
            "model": model,
            "finish_reason": finish_reason,
            "usage": usage,
            "event_count": event_count,
            "latest_event_sequence": run.last_event_sequence,
            "latest_event_types": [event.event_type for event in latest_events],
            "tool_call_count": tool_call_count,
            "pending_tool_call_count": pending_tool_call_count,
            "approval_count": approval_count,
            "pending_approval_count": pending_approval_count,
            "migration_block_count": migration_block_count,
            "open_migration_block_count": open_migration_block_count,
            "memory_usage_count": memory_usage_count,
            "blocking_tool_call_ids": blocking_tool_call_ids,
            "terminal": terminal,
            "can_cancel": not terminal,
            "can_resume": can_resume,
            "updated_at": run.updated_at,
        }

    def get_run_action_state(self, *, run_id: str, current_user: User) -> dict[str, Any]:
        run_summary = self.get_run_summary(run_id=run_id, current_user=current_user)
        run = run_summary["run"]
        terminal = bool(run_summary["terminal"])
        pending_approval_ids = self._ids_where(
            AgentApproval.approval_id,
            AgentApproval.run_id == run_id,
            AgentApproval.approval_status == "pending",
            model=AgentApproval,
            order_by=[AgentApproval.created_at.asc(), AgentApproval.id.asc()],
        )
        pending_approval_tool_call_ids = self._ids_where(
            AgentApproval.tool_call_id,
            AgentApproval.run_id == run_id,
            AgentApproval.approval_status == "pending",
            model=AgentApproval,
            order_by=[AgentApproval.created_at.asc(), AgentApproval.id.asc()],
        )
        open_migration_block_ids = self._ids_where(
            AgentMigrationBlock.block_id,
            AgentMigrationBlock.run_id == run_id,
            AgentMigrationBlock.status == "open",
            model=AgentMigrationBlock,
            order_by=[AgentMigrationBlock.created_at.asc(), AgentMigrationBlock.id.asc()],
        )
        uncertain_tool_call_ids = self._ids_where(
            AgentToolCall.tool_call_id,
            AgentToolCall.run_id == run_id,
            AgentToolCall.status.in_(["uncertain", "reconciling"]),
            model=AgentToolCall,
            order_by=[
                AgentToolCall.step_index.asc(),
                AgentToolCall.attempt_index.asc(),
                AgentToolCall.id.asc(),
            ],
        )
        retryable_tool_call_ids = self._ids_where(
            AgentToolCall.tool_call_id,
            AgentToolCall.run_id == run_id,
            AgentToolCall.status == "failed_retryable",
            model=AgentToolCall,
            order_by=[
                AgentToolCall.step_index.asc(),
                AgentToolCall.attempt_index.asc(),
                AgentToolCall.id.asc(),
            ],
        )

        blocked_reasons: list[str] = []
        if terminal:
            blocked_reasons.append(f"run_{run.status}")
        if pending_approval_ids:
            blocked_reasons.append("pending_approvals")
        if open_migration_block_ids:
            blocked_reasons.append("open_migration_blocks")
        if uncertain_tool_call_ids:
            blocked_reasons.append("uncertain_tool_calls")
        if retryable_tool_call_ids:
            blocked_reasons.append("retryable_tool_calls")
        if run.status == "paused" and run.error_code:
            blocked_reasons.append(run.error_code)

        blocking_tool_call_ids = list(dict.fromkeys(
            list(run_summary["blocking_tool_call_ids"]) + pending_approval_tool_call_ids
        ))
        resume_candidate = (
            run.status in {"paused", "needs_human", "migration_blocked"}
            or bool(blocking_tool_call_ids)
            or bool(retryable_tool_call_ids)
        )
        resume_enabled = not terminal and resume_candidate and not pending_approval_ids and not open_migration_block_ids
        if terminal:
            resume_reason = "run_terminal"
        elif open_migration_block_ids:
            resume_reason = "open_migration_blocks"
        elif pending_approval_ids:
            resume_reason = "pending_approvals_need_review"
        elif resume_candidate:
            resume_reason = "resume_candidate_ready"
        else:
            resume_reason = "no_resume_candidate"
        resume_resource_ids = list(dict.fromkeys(blocking_tool_call_ids + retryable_tool_call_ids))
        pending_approval_resource_item_ids = _tool_call_item_ids(
            run_id=run_id,
            tool_call_ids=pending_approval_tool_call_ids,
        )
        resume_resource_item_ids = _tool_call_item_ids(
            run_id=run_id,
            tool_call_ids=resume_resource_ids,
        )
        uncertain_tool_call_item_ids = _tool_call_item_ids(
            run_id=run_id,
            tool_call_ids=uncertain_tool_call_ids,
        )
        open_migration_block_item_ids = _migration_block_item_ids(
            run_id=run_id,
            block_ids=open_migration_block_ids,
        )
        reconcile_enabled = bool(uncertain_tool_call_ids)
        reconcile_reason = (
            "uncertain_tool_calls"
            if uncertain_tool_call_ids
            else ("run_terminal" if terminal else "no_uncertain_tool_calls")
        )
        resolve_migration_details = {
            "open_migration_block_count": len(open_migration_block_ids),
            "run_status": run.status,
            "run_terminal": terminal,
            "resolve_preserves_terminal_run": terminal,
            "post_resolve_next_action": (
                "reconcile_run" if terminal else "checkpoint_freshness_then_resume"
            ),
        }
        if terminal:
            resolve_migration_details["tool_call_status_after_resolve"] = "reconciling"
        runbook_recovery_reasons = [
            reason for reason in blocked_reasons if reason != "run_completed"
        ]
        open_runbook_enabled = bool(blocked_reasons) and (
            run.status != "completed" or bool(runbook_recovery_reasons)
        )

        actions = [
            self._run_action(
                "view_summary",
                "View run summary",
                "GET",
                f"/api/v1/agents/runs/{run_id}/summary",
                True,
                "always_available",
                "info",
            ),
            self._run_action(
                "stream_events",
                "Stream events",
                "GET",
                f"/api/v1/agents/runs/{run_id}/events",
                True,
                "always_available",
                "info",
            ),
            self._run_action(
                "cancel_run",
                "Stop run",
                "POST",
                f"/api/v1/agents/runs/{run_id}/cancel",
                not terminal,
                "run_active" if not terminal else "run_terminal",
                "warning",
            ),
            self._run_action(
                "review_approvals",
                "Review approvals",
                "GET",
                f"/api/v1/agents/runs/{run_id}/approvals",
                bool(pending_approval_ids),
                "pending_approvals" if pending_approval_ids else "no_pending_approvals",
                "warning",
                pending_approval_ids,
                {"pending_approval_count": len(pending_approval_ids)},
                resource_item_ids=pending_approval_resource_item_ids,
            ),
            self._run_action(
                "resume_run",
                "Resume run",
                "POST",
                f"/api/v1/agents/runs/{run_id}/resume",
                resume_enabled,
                resume_reason,
                "primary",
                resume_resource_ids,
                {
                    "blocking_tool_call_ids": blocking_tool_call_ids,
                    "pending_approval_tool_call_ids": pending_approval_tool_call_ids,
                    "retryable_tool_call_ids": retryable_tool_call_ids,
                },
                resource_item_ids=resume_resource_item_ids,
            ),
            self._run_action(
                "reconcile_run",
                "Reconcile uncertain tools",
                "POST",
                f"/api/v1/agents/runs/{run_id}/reconcile",
                reconcile_enabled,
                reconcile_reason,
                "warning",
                uncertain_tool_call_ids,
                {"uncertain_tool_call_count": len(uncertain_tool_call_ids)},
                resource_item_ids=uncertain_tool_call_item_ids,
            ),
            self._run_action(
                "resolve_migration",
                "Resolve migration block",
                "GET",
                f"/api/v1/agents/runs/{run_id}/migration-blocks",
                bool(open_migration_block_ids),
                "open_migration_blocks" if open_migration_block_ids else "no_open_migration_blocks",
                "danger",
                open_migration_block_ids,
                resolve_migration_details,
                resource_item_ids=open_migration_block_item_ids,
            ),
            self._run_action(
                "open_runbook",
                "Open runbook",
                "GET",
                f"/api/v1/agents/runs/{run_id}/runbook",
                open_runbook_enabled,
                "recovery_context_available" if open_runbook_enabled else "no_recovery_context",
                "info",
                [],
                {"blocked_reasons": blocked_reasons},
            ),
        ]
        enabled_action_ids = {action["action_id"] for action in actions if action["enabled"]}
        primary_action_ids = [
            action_id for action_id in AGENT_RUN_ACTION_PRIMARY_PRIORITY if action_id in enabled_action_ids
        ]
        return {
            "run_summary": run_summary,
            "actions": actions,
            "primary_action_ids": primary_action_ids,
            "blocked_reasons": blocked_reasons,
            "generated_at": _utcnow(),
        }

    def list_runs(
        self,
        *,
        project_id: int,
        current_user: User,
        conversation_id: str | None = None,
        status_filter: str | None = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        self.permission_service.require_project_access(current_user, project_id)
        statement = select(AgentRun).where(AgentRun.project_id == project_id)
        if conversation_id:
            statement = statement.where(AgentRun.conversation_id == conversation_id)
        if status_filter:
            statement = statement.where(AgentRun.status == status_filter)
        runs = list(
            self.db.scalars(
                statement.order_by(AgentRun.updated_at.desc(), AgentRun.id.desc()).limit(limit)
            ).all()
        )
        runs = [self._fail_stale_active_run_if_needed(run) for run in runs]
        if status_filter:
            runs = [run for run in runs if run.status == status_filter]
        return runs

    def _count_where(self, *criteria, model) -> int:
        return int(
            self.db.scalar(
                select(func.count()).select_from(model).where(*criteria)
            )
            or 0
        )

    def _latest_event_payload(self, run_id: str, event_type: str) -> dict[str, Any]:
        event = self.db.scalar(
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id, AgentEvent.event_type == event_type)
            .order_by(AgentEvent.event_seq.desc())
            .limit(1)
        )
        if event is None:
            return {}
        return dict(event.payload_json or {})

    def _latest_event_created_at(self, run_id: str) -> datetime | None:
        return self.db.scalar(
            select(AgentEvent.created_at)
            .where(AgentEvent.run_id == run_id)
            .order_by(AgentEvent.event_seq.desc())
            .limit(1)
        )

    def _fail_stale_active_run_if_needed(self, run: AgentRun) -> AgentRun:
        if run.status not in RUN_STALE_ACTIVE_STATUSES:
            return run
        timeout_seconds = float(settings.AGENT_RUN_STALE_TIMEOUT_SECONDS or 0)
        if timeout_seconds <= 0:
            return run
        last_activity_at = self._latest_event_created_at(run.run_id) or run.updated_at or run.started_at or run.created_at
        if last_activity_at is None:
            return run
        idle_seconds = _activity_idle_seconds(last_activity_at)
        if idle_seconds < timeout_seconds:
            return run

        locked_run = self.db.scalar(select(AgentRun).where(AgentRun.id == run.id).with_for_update())
        if locked_run is None or locked_run.status not in RUN_STALE_ACTIVE_STATUSES:
            return locked_run or run
        latest_event_at = self._latest_event_created_at(locked_run.run_id) or locked_run.updated_at or locked_run.started_at or locked_run.created_at
        latest_idle_seconds = _activity_idle_seconds(latest_event_at) if latest_event_at is not None else idle_seconds
        if latest_idle_seconds < timeout_seconds:
            return locked_run

        logger.warning(
            "agent_run_mark_stale_failed run_id=%s status=%s idle_seconds=%s timeout_seconds=%s last_event_sequence=%s",
            locked_run.run_id,
            locked_run.status,
            int(latest_idle_seconds),
            int(timeout_seconds),
            locked_run.last_event_sequence,
        )
        return self.fail_run(
            locked_run,
            error_code="agent_run_stale_worker_lost",
            error_message=(
                "Agent run did not produce events before the stale timeout; "
                "the background worker may have stopped before writing a terminal event."
            ),
            commit=True,
        )

    def _ids_where(self, column, *criteria, model, order_by=None) -> list[str]:
        statement = select(column).select_from(model).where(*criteria)
        if order_by:
            statement = statement.order_by(*order_by)
        return [
            str(value)
            for value in self.db.scalars(
                statement
            ).all()
        ]

    @staticmethod
    def _run_action(
        action_id: str,
        label: str,
        method: str,
        path: str,
        enabled: bool,
        reason: str,
        severity: str,
        resource_ids: list[str] | None = None,
        details: dict[str, Any] | None = None,
        resource_item_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "action_id": action_id,
            "label": label,
            "method": method,
            "path": path,
            "enabled": enabled,
            "reason": reason,
            "severity": severity,
            "resource_ids": resource_ids or [],
            "resource_item_ids": resource_item_ids or [],
            "details": details or {},
        }

    def list_conversations(
        self,
        *,
        project_id: int,
        current_user: User,
        search: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self.permission_service.require_project_access(current_user, project_id)
        runs = list(
            self.db.scalars(
                select(AgentRun)
                .where(AgentRun.project_id == project_id, AgentRun.conversation_id.is_not(None))
                .order_by(AgentRun.updated_at.desc(), AgentRun.id.desc())
            ).all()
        )
        runs = [self._fail_stale_active_run_if_needed(run) for run in runs]
        conversations: dict[str, dict[str, Any]] = {}
        for run in runs:
            if run.conversation_id is None:
                continue
            title = _conversation_title(run.intent)
            if search and search.lower() not in title.lower() and search.lower() not in run.conversation_id.lower():
                continue
            existing = conversations.get(run.conversation_id)
            if existing is None:
                conversations[run.conversation_id] = {
                    "conversation_id": run.conversation_id,
                    "project_id": run.project_id,
                    "title": title,
                    "run_count": 1,
                    "latest_run_id": run.run_id,
                    "latest_run_status": run.status,
                    "created_at": run.created_at,
                    "updated_at": run.updated_at,
                }
            else:
                existing["run_count"] += 1
                if run.updated_at > existing["updated_at"]:
                    existing["latest_run_id"] = run.run_id
                    existing["latest_run_status"] = run.status
                    existing["updated_at"] = run.updated_at
                if run.created_at < existing["created_at"]:
                    existing["created_at"] = run.created_at
                    existing["title"] = title
        return sorted(conversations.values(), key=lambda item: item["updated_at"], reverse=True)[:limit]

    def get_conversation_transcript(
        self,
        *,
        project_id: int,
        conversation_id: str,
        current_user: User,
        limit: int = 100,
    ) -> dict[str, Any]:
        self.permission_service.require_project_access(current_user, project_id)
        statement = (
            select(AgentRun)
            .where(
                AgentRun.project_id == project_id,
                AgentRun.conversation_id == conversation_id,
            )
            .order_by(AgentRun.created_at.asc(), AgentRun.id.asc())
            .limit(limit)
        )
        runs = list(self.db.scalars(statement).all())
        if not runs:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent conversation 不存在")
        runs = [self._fail_stale_active_run_if_needed(run) for run in runs]

        run_count = self._count_where(
            AgentRun.project_id == project_id,
            AgentRun.conversation_id == conversation_id,
            model=AgentRun,
        )
        latest_run = self.db.scalar(
            select(AgentRun)
            .where(
                AgentRun.project_id == project_id,
                AgentRun.conversation_id == conversation_id,
            )
            .order_by(AgentRun.updated_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
        first_run = runs[0]
        latest = latest_run or runs[-1]
        conversation = {
            "conversation_id": conversation_id,
            "project_id": project_id,
            "title": _conversation_title(first_run.intent),
            "run_count": run_count,
            "latest_run_id": latest.run_id,
            "latest_run_status": latest.status,
            "created_at": first_run.created_at,
            "updated_at": latest.updated_at,
        }
        return {
            "conversation": conversation,
            "turns": [
                self.get_run_summary(run_id=run.run_id, current_user=current_user)
                for run in runs
            ],
            "context_compactions": self._conversation_context_compactions(
                run_ids=[run.run_id for run in runs],
            ),
            "generated_at": _utcnow(),
        }

    def _conversation_context_compactions(self, *, run_ids: list[str]) -> list[dict[str, Any]]:
        if not run_ids:
            return []
        run_order = {run_id: index for index, run_id in enumerate(run_ids)}
        events = list(
            self.db.scalars(
                select(AgentEvent).where(
                    AgentEvent.run_id.in_(run_ids),
                    AgentEvent.event_type == AGENT_HISTORY_CONTEXT_COMPACTION_EVENT,
                )
            ).all()
        )
        events.sort(key=lambda event: (run_order.get(event.run_id, len(run_order)), event.event_seq, event.id))
        return [
            {
                "item_id": _agent_context_compaction_item_id(event=event),
                "run_id": event.run_id,
                "event_seq": event.event_seq,
                "event_type": event.event_type,
                "payload_json": event.payload_json,
                "created_at": event.created_at,
            }
            for event in events
        ]

    def export_conversation(
        self,
        *,
        project_id: int,
        conversation_id: str,
        current_user: User,
        limit: int = 100,
    ) -> dict[str, Any]:
        transcript = self.get_conversation_transcript(
            project_id=project_id,
            conversation_id=conversation_id,
            current_user=current_user,
            limit=limit,
        )
        run_ids = [turn["run"].run_id for turn in transcript["turns"]]
        events_by_run_id: dict[str, list[AgentEvent]] = {run_id: [] for run_id in run_ids}
        tool_calls_by_run_id: dict[str, list[AgentToolCall]] = {run_id: [] for run_id in run_ids}
        approvals_by_run_id: dict[str, list[AgentApproval]] = {run_id: [] for run_id in run_ids}
        migration_blocks_by_run_id: dict[str, list[AgentMigrationBlock]] = {run_id: [] for run_id in run_ids}

        if run_ids:
            for event in self.db.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id.in_(run_ids))
                .order_by(AgentEvent.run_id.asc(), AgentEvent.event_seq.asc())
            ).all():
                events_by_run_id.setdefault(event.run_id, []).append(event)
            for tool_call in self.db.scalars(
                select(AgentToolCall)
                .where(AgentToolCall.run_id.in_(run_ids))
                .order_by(AgentToolCall.run_id.asc(), AgentToolCall.step_index.asc(), AgentToolCall.attempt_index.asc(), AgentToolCall.id.asc())
            ).all():
                tool_calls_by_run_id.setdefault(tool_call.run_id, []).append(tool_call)
            for approval in self.db.scalars(
                select(AgentApproval)
                .where(AgentApproval.run_id.in_(run_ids))
                .order_by(AgentApproval.run_id.asc(), AgentApproval.created_at.asc(), AgentApproval.id.asc())
            ).all():
                approvals_by_run_id.setdefault(approval.run_id, []).append(approval)
            for block in self.db.scalars(
                select(AgentMigrationBlock)
                .where(AgentMigrationBlock.run_id.in_(run_ids))
                .order_by(AgentMigrationBlock.run_id.asc(), AgentMigrationBlock.created_at.asc(), AgentMigrationBlock.id.asc())
            ).all():
                migration_blocks_by_run_id.setdefault(block.run_id, []).append(block)

        return {
            **transcript,
            "events_by_run_id": events_by_run_id,
            "tool_calls_by_run_id": tool_calls_by_run_id,
            "approvals_by_run_id": approvals_by_run_id,
            "migration_blocks_by_run_id": migration_blocks_by_run_id,
            "export_format": "agent_conversation_export_v1",
            "generated_at": _utcnow(),
            "derived_from": {
                "conversation": "ai_agent_runs",
                "turns": "AgentRunSummaryRead",
                "context_compactions": "ai_agent_events.context.history_compacted",
                "events": "ai_agent_events",
                "tool_calls": "ai_agent_tool_calls",
                "approvals": "ai_agent_approvals",
                "migration_blocks": "ai_agent_migration_blocks",
                "run_ids": run_ids,
                "limit": limit,
            },
        }

    def cancel_run(self, *, run_id: str, current_user: User) -> AgentRun:
        run = self._get_run_or_404(run_id, for_update=True)
        self.permission_service.require_project_access(current_user, run.project_id)
        if run.status in RUN_TERMINAL_STATUSES:
            return run
        run.status = "cancelled"
        run.completed_at = _utcnow()
        self.append_event(run, "run.cancelled", {"status": run.status}, commit=False)
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_snapshot(self, *, snapshot_id: str, current_user: User) -> AgentRuntimeSnapshot:
        snapshot = self.db.scalar(
            select(AgentRuntimeSnapshot).where(AgentRuntimeSnapshot.snapshot_id == snapshot_id)
        )
        if snapshot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent runtime snapshot 不存在")
        self.permission_service.require_project_access(current_user, snapshot.project_id)
        return snapshot

    def list_events(self, *, run_id: str, after_sequence: int) -> tuple[list[AgentEvent], AgentRun]:
        run = self._get_run_or_404(run_id)
        run = self._fail_stale_active_run_if_needed(run)
        after_sequence = self._normalize_event_cursor(run=run, after_sequence=after_sequence)
        events = list(self.db.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id, AgentEvent.event_seq > after_sequence)
            .order_by(AgentEvent.event_seq)
        ).all())
        return events, run

    def get_event_snapshot(
        self,
        *,
        run_id: str,
        after_sequence: int,
        limit: int,
        current_user: User,
    ) -> dict[str, Any]:
        run = self.get_run(run_id=run_id, current_user=current_user)
        after_sequence = self._normalize_event_cursor(run=run, after_sequence=after_sequence)
        events = list(self.db.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id, AgentEvent.event_seq > after_sequence)
            .order_by(AgentEvent.event_seq)
            .limit(limit)
        ).all())
        next_after_sequence = events[-1].event_seq if events else after_sequence
        return {
            "run": run,
            "events": events,
            "context_compactions": self._conversation_context_compactions(run_ids=[run.run_id]),
            "after_sequence": after_sequence,
            "event_count": len(events),
            "latest_event_sequence": run.last_event_sequence,
            "next_after_sequence": next_after_sequence,
            "terminal": run.status in RUN_TERMINAL_STATUSES,
            "generated_at": _utcnow(),
        }

    def _normalize_event_cursor(self, *, run: AgentRun, after_sequence: int) -> int:
        if after_sequence <= (run.last_event_sequence or 0):
            return after_sequence
        logger.info(
            "agent_event_cursor_reset run_id=%s after_sequence=%s latest_event_sequence=%s status=%s",
            run.run_id,
            after_sequence,
            run.last_event_sequence,
            run.status,
        )
        return 0

    def append_event(
        self,
        run: AgentRun,
        event_type: str,
        payload: dict[str, Any],
        *,
        commit: bool = True,
    ) -> AgentEvent:
        try:
            locked_run = self.db.scalar(
                select(AgentRun).where(AgentRun.id == run.id).with_for_update()
            )
            if locked_run is not None:
                run = locked_run
            if run.status in RUN_TERMINAL_STATUSES:
                latest_event = self.db.scalar(
                    select(AgentEvent)
                    .where(AgentEvent.run_id == run.run_id)
                    .order_by(AgentEvent.event_seq.desc())
                    .limit(1)
                )
                terminal_event_type = RUN_TERMINAL_EVENT_TYPES_BY_STATUS.get(run.status)
                if event_type != terminal_event_type or (
                    latest_event is not None and latest_event.event_type == terminal_event_type
                ):
                    logger.info(
                        "agent_event_append_skipped_terminal run_id=%s status=%s event_type=%s latest_event_type=%s",
                        run.run_id,
                        run.status,
                        event_type,
                        latest_event.event_type if latest_event is not None else None,
                    )
                    if commit:
                        self.db.commit()
                        if latest_event is not None:
                            self.db.refresh(latest_event)
                    if latest_event is not None:
                        return latest_event
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"code": "agent_run_terminal_event_rejected"},
                    )
            event_seq = (run.last_event_sequence or 0) + 1
            event = AgentEvent(
                run_id=run.run_id,
                event_seq=event_seq,
                event_type=event_type,
                payload_json={
                    "schema_version": 1,
                    "run_id": run.run_id,
                    "project_id": run.project_id,
                    "event_seq": event_seq,
                    "event_type": event_type,
                    "occurred_at": _utcnow().isoformat(),
                    **mask_sensitive(payload),
                },
            )
            run.last_event_sequence = event_seq
            self.db.add(event)
            self.db.flush()
            self.db.add(AgentOutbox(event_id=event.id, status="pending"))
            if commit:
                self.db.commit()
                self.db.refresh(event)
            else:
                self.db.flush()
            return event
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "event_outbox_write_failed"},
            ) from exc

    def complete_run(self, run: AgentRun, result: dict[str, Any], *, commit: bool = True) -> AgentRun:
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return run
        run.status = "completed"
        run.result_json = mask_sensitive(result)
        run.completed_at = _utcnow()
        self.append_event(run, "run.completed", {"result": run.result_json}, commit=False)
        if commit:
            self.db.commit()
            self.db.refresh(run)
        return run

    def fail_run(self, run: AgentRun, *, error_code: str, error_message: str, commit: bool = True) -> AgentRun:
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return run
        run.status = "failed"
        run.error_code = error_code
        run.error_message = _bounded_run_failure_error_message(
            error_message,
            error_code=error_code,
        )
        run.completed_at = _utcnow()
        self.append_event(
            run,
            "run.failed",
            {"error_code": run.error_code, "error_message": run.error_message},
            commit=False,
        )
        if commit:
            self.db.commit()
            self.db.refresh(run)
        return run

    def create_checkpoint(self, run: AgentRun, *, commit: bool = True) -> AgentCheckpoint:
        checkpoint_seq = (
            self.db.scalar(
                select(func.max(AgentCheckpoint.checkpoint_seq)).where(AgentCheckpoint.run_id == run.run_id)
            )
            or 0
        ) + 1
        checkpoint = AgentCheckpoint(
            run_id=run.run_id,
            checkpoint_seq=checkpoint_seq,
            runtime_snapshot_id=run.runtime_snapshot_id,
            iteration=run.current_iteration,
            current_step_index=run.current_step_index,
            active_plan_summary_json={"intent": run.intent},
            active_draft_summary_json=None,
            last_failure_summary_json=None,
            recent_tool_call_ids_json=[],
            pending_approval_tool_call_ids_json=[],
            freshness_metadata_json={"created_from": "runtime_skeleton"},
        )
        self.db.add(checkpoint)
        if commit:
            self.db.commit()
            self.db.refresh(checkpoint)
        else:
            self.db.flush()
        return checkpoint

    def record_checkpoint_context_compaction(
        self,
        *,
        run: AgentRun,
        event: AgentEvent,
        commit: bool = True,
    ) -> AgentCheckpoint | None:
        if run.last_checkpoint_id is None:
            return None
        checkpoint = self.db.get(AgentCheckpoint, run.last_checkpoint_id)
        if checkpoint is None:
            return None
        object_key = _agent_context_compaction_object_key(
            run_id=event.run_id,
            event_seq=event.event_seq,
        )
        checkpoint.context_compaction_object_key = object_key
        freshness_metadata = dict(checkpoint.freshness_metadata_json or {})
        freshness_metadata["context_compaction"] = {
            "object_key": object_key,
            "event_seq": event.event_seq,
            "event_type": event.event_type,
        }
        checkpoint.freshness_metadata_json = freshness_metadata
        if commit:
            self.db.commit()
            self.db.refresh(checkpoint)
        else:
            self.db.flush()
        return checkpoint

    def context_compaction_window_metadata(self, *, run: AgentRun) -> dict[str, Any]:
        previous_events = self._context_compaction_events_for_window(run=run)
        window_number = len(previous_events) + 1
        scope_id = _agent_context_compaction_window_scope_id(run=run)
        window_id = _agent_context_compaction_window_id(scope_id=scope_id, window_number=window_number)

        if not previous_events:
            return {
                "window_number": window_number,
                "first_window_id": window_id,
                "previous_window_id": None,
                "window_id": window_id,
            }

        first_payload = previous_events[0].payload_json or {}
        previous_payload = previous_events[-1].payload_json or {}
        first_window_id = (
            first_payload.get("first_window_id")
            or first_payload.get("window_id")
            or _agent_context_compaction_window_id(scope_id=scope_id, window_number=1)
        )
        previous_window_number = previous_payload.get("window_number")
        if not isinstance(previous_window_number, int):
            previous_window_number = len(previous_events)
        previous_window_id = previous_payload.get("window_id") or _agent_context_compaction_window_id(
            scope_id=scope_id,
            window_number=previous_window_number,
        )
        return {
            "window_number": window_number,
            "first_window_id": first_window_id,
            "previous_window_id": previous_window_id,
            "window_id": window_id,
        }

    def _context_compaction_events_for_window(self, *, run: AgentRun) -> list[AgentEvent]:
        if not run.conversation_id:
            return list(
                self.db.scalars(
                    select(AgentEvent)
                    .where(
                        AgentEvent.run_id == run.run_id,
                        AgentEvent.event_type == AGENT_HISTORY_CONTEXT_COMPACTION_EVENT,
                    )
                    .order_by(AgentEvent.event_seq.asc(), AgentEvent.id.asc())
                ).all()
            )
        return list(
            self.db.scalars(
                select(AgentEvent)
                .join(AgentRun, AgentRun.run_id == AgentEvent.run_id)
                .where(
                    AgentRun.project_id == run.project_id,
                    AgentRun.conversation_id == run.conversation_id,
                    AgentRun.id <= run.id,
                    AgentEvent.event_type == AGENT_HISTORY_CONTEXT_COMPACTION_EVENT,
                )
                .order_by(AgentRun.id.asc(), AgentEvent.event_seq.asc(), AgentEvent.id.asc())
            ).all()
        )

    def _get_or_create_snapshot(self, *, project_id: int, current_user: User) -> AgentRuntimeSnapshot:
        registry_json = self.tool_registry.registry_json()
        runtime_hash = self.tool_registry.runtime_hash()
        existing = self.db.scalar(
            select(AgentRuntimeSnapshot).where(
                AgentRuntimeSnapshot.project_id == project_id,
                AgentRuntimeSnapshot.runtime_hash == runtime_hash,
            )
        )
        if existing is not None:
            return existing
        snapshot = AgentRuntimeSnapshot(
            snapshot_id=f"agent-snap-{uuid.uuid4().hex}",
            project_id=project_id,
            created_by=current_user.id,
            runtime_hash=runtime_hash,
            tool_registry_hash=self.tool_registry.registry_hash(),
            manifest_bundle_hash=self.tool_registry.manifest_bundle_hash(),
            prompt_bundle_hash=request_fingerprint({"prompt_bundle": "agent-runtime-v1"}),
            policy_version_hash=request_fingerprint({"policy": "agent-policy-v1"}),
            tools_json=registry_json,
            manifests_json={"tools": {item["name"]: item for item in registry_json}},
            adapters_json={"adapter_bundle": "agent-adapters-v1"},
            policies_json={"policy_bundle": "agent-policy-v1"},
        )
        self.db.add(snapshot)
        self._seed_backend_contracts()
        self.db.flush()
        return snapshot

    def _seed_backend_contracts(self) -> None:
        for spec in self.tool_registry.list_specs():
            contract = spec.backend_contract
            if contract is None:
                continue
            existing = self.db.scalar(
                select(AgentBackendContract).where(
                    AgentBackendContract.backend_name == contract.backend_name,
                    AgentBackendContract.backend_operation == contract.backend_operation,
                    AgentBackendContract.backend_contract_version == contract.backend_contract_version,
                )
            )
            if existing is not None:
                continue
            self.db.add(AgentBackendContract(
                backend_name=contract.backend_name,
                backend_operation=contract.backend_operation,
                backend_contract_version=contract.backend_contract_version,
                request_schema_hash=contract.request_schema_hash,
                output_schema_hash=contract.output_schema_hash,
                reconcile_contract_version=contract.reconcile_contract_version,
                result_adapter_version=contract.result_adapter_version,
                effect_capability=contract.effect_capability,
                compatibility_status=contract.compatibility_status,
                owner_team=contract.owner_team,
            ))

    def _get_run_or_404(self, run_id: str, *, for_update: bool = False) -> AgentRun:
        statement = select(AgentRun).where(AgentRun.run_id == run_id)
        if for_update:
            statement = statement.with_for_update()
        run = self.db.scalar(statement)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run 不存在")
        return run


class AgentConversationRunner:
    def __init__(self, db: Session):
        self.db = db

    def _fail_run_after_exception(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        error_code: str,
        error_message: str,
        original_exception: BaseException,
    ) -> AgentRun:
        try:
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            return runtime.fail_run(
                run,
                error_code=error_code,
                error_message=error_message,
                commit=True,
            )
        except SQLAlchemyError as fail_exc:
            logger.warning(
                "agent_conversation_primary_failure_write_failed run_id=%s error_code=%s "
                "original_error_type=%s failure_error_type=%s",
                run.run_id,
                error_code,
                type(original_exception).__name__,
                type(fail_exc).__name__,
            )
            return self._fail_run_with_recovery_session(
                run_id=run.run_id,
                error_code=error_code,
                error_message=error_message,
                original_exception=original_exception,
                failure_exception=fail_exc,
            )

    def _fail_run_with_recovery_session(
        self,
        *,
        run_id: str,
        error_code: str,
        error_message: str,
        original_exception: BaseException,
        failure_exception: BaseException,
    ) -> AgentRun:
        try:
            self.db.rollback()
        except SQLAlchemyError:
            logger.warning("agent_conversation_primary_session_rollback_failed run_id=%s", run_id, exc_info=True)
        if isinstance(original_exception, SQLAlchemyError) or isinstance(failure_exception, SQLAlchemyError):
            dispose_engine_after_disconnect()
        with SessionLocal() as recovery_db:
            recovery_run = recovery_db.scalar(select(AgentRun).where(AgentRun.run_id == run_id))
            if recovery_run is None:
                raise original_exception
            if recovery_run.status in RUN_TERMINAL_STATUSES:
                return recovery_run
            logger.error(
                "agent_conversation_failed_via_recovery_session run_id=%s error_code=%s "
                "original_error_type=%s failure_error_type=%s",
                run_id,
                error_code,
                type(original_exception).__name__,
                type(failure_exception).__name__,
            )
            return AgentRuntimeService(recovery_db).fail_run(
                recovery_run,
                error_code=error_code,
                error_message=error_message,
                commit=True,
            )

    def _release_db_transaction_before_external_wait(self) -> None:
        if self.db.in_transaction():
            self.db.rollback()

    def complete_after_tool_results(
        self,
        *,
        run_id: str,
        user_id: int,
        tool_call_ids: list[str],
    ) -> AgentRun | None:
        runtime = AgentRuntimeService(self.db)
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id))
        user = self.db.get(User, user_id)
        if run is None or user is None:
            return None
        if run.status in RUN_TERMINAL_STATUSES:
            return run

        calls = list(
            self.db.scalars(
                select(AgentToolCall)
                .where(
                    AgentToolCall.run_id == run.run_id,
                    AgentToolCall.tool_call_id.in_(tool_call_ids),
                )
                .order_by(AgentToolCall.step_index.asc(), AgentToolCall.attempt_index.asc())
            ).all()
        )
        messages = self._build_chat_messages(run, current_user=user, runtime=runtime)
        messages.extend(_tool_result_context_messages(calls))
        messages.append(AIChatMessage(
            role="user",
            content="以上工具已完成审批和执行。请基于这些工具结果给用户最终回复，不要再请求工具。",
        ))
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return run

        try:
            content, chunks, model_payload = self._stream_model_response(
                run=run,
                messages=messages,
                runtime=runtime,
                iteration=run.current_iteration,
                final_summary=True,
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            clean_model_payload = {key: value for key, value in model_payload.items() if value is not None}
            content, chunks = self._normalize_user_visible_markdown(
                run=run,
                runtime=runtime,
                content=content,
                chunks=chunks,
                iteration=run.current_iteration,
                final_summary=True,
                trace_payload=_model_trace_from_payload(clean_model_payload),
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            self._emit_model_deltas(
                run=run,
                runtime=runtime,
                chunks=chunks,
                trace_payload=_model_trace_from_payload(clean_model_payload),
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            runtime.append_event(
                run,
                "model.completed",
                {
                    "content": content,
                    "iteration": run.current_iteration,
                    "final_summary": True,
                    "resumed_after_approval": True,
                    **clean_model_payload,
                },
                commit=False,
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            return runtime.complete_run(
                run,
                {
                    "message": content,
                    "tool_calls": [_tool_call_summary(call) for call in calls],
                    **clean_model_payload,
                },
                commit=True,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            return self._fail_run_after_exception(
                run=run,
                runtime=runtime,
                error_code="agent_conversation_model_error",
                error_message=detail,
                original_exception=exc,
            )
        except Exception as exc:  # noqa: BLE001
            return self._fail_run_after_exception(
                run=run,
                runtime=runtime,
                error_code="agent_conversation_unhandled_error",
                error_message=str(exc),
                original_exception=exc,
            )

    def run(self, *, run_id: str, user_id: int) -> AgentRun | None:
        runtime = AgentRuntimeService(self.db)
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == run_id))
        user = self.db.get(User, user_id)
        if run is None or user is None:
            logger.warning("agent_conversation_skip_missing run_id=%s user_id=%s", run_id, user_id)
            return None
        if run.status in RUN_TERMINAL_STATUSES:
            logger.info("agent_conversation_skip_terminal run_id=%s status=%s", run.run_id, run.status)
            return run

        try:
            logger.info(
                "agent_conversation_start run_id=%s project_id=%s user_id=%s conversation_id=%s max_iterations=%s",
                run.run_id,
                run.project_id,
                user.id,
                run.conversation_id,
                run.max_iterations,
            )
            unsupported_guard = self._unsupported_capability_guard_for_run(run)
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            if unsupported_guard is not None:
                return self._complete_unsupported_capability(run=run, runtime=runtime, guard=unsupported_guard)

            messages = self._build_chat_messages(run, current_user=user, runtime=runtime)
            tool_summaries: list[dict[str, Any]] = []
            for iteration in range(max(1, run.max_iterations)):
                self.db.refresh(run)
                if run.status in RUN_TERMINAL_STATUSES:
                    return run
                content, chunks, model_payload = self._stream_model_response(
                    run=run,
                    messages=messages,
                    runtime=runtime,
                    iteration=iteration,
                    suppress_visible_deltas=self._should_suppress_realtime_deltas(run),
                )
                self.db.refresh(run)
                if run.status in RUN_TERMINAL_STATUSES:
                    return run
                clean_model_payload = {key: value for key, value in model_payload.items() if value is not None}
                try:
                    tool_request = self._parse_tool_request(content)
                except HTTPException as exc:
                    content, chunks, clean_model_payload, tool_request = self._repair_invalid_tool_request(
                        run=run,
                        current_user=user,
                        messages=messages,
                        invalid_content=content,
                        error_message=_http_exception_detail(exc),
                        model_payload=clean_model_payload,
                        runtime=runtime,
                        iteration=iteration,
                    )
                    self.db.refresh(run)
                    if run.status in RUN_TERMINAL_STATUSES:
                        return run
                if tool_request is None:
                    if _looks_like_internal_tool_context_leak(content):
                        content, chunks, clean_model_payload, tool_request = self._repair_invalid_tool_request(
                            run=run,
                            current_user=user,
                            messages=messages,
                            invalid_content=content,
                            error_message="model leaked internal tool request context summary",
                            model_payload=clean_model_payload,
                            runtime=runtime,
                            iteration=iteration,
                        )
                        self.db.refresh(run)
                        if run.status in RUN_TERMINAL_STATUSES:
                            return run
                        if tool_request is None and _looks_like_internal_tool_context_leak(content):
                            runtime.append_event(
                                run,
                                "model.internal_context_leak_suppressed",
                                {
                                    "iteration": iteration,
                                    "content_preview": _bounded_agent_content_preview(
                                        content,
                                        reference="AgentConversationRunner.model.internal_context_leak.content",
                                    ),
                                    **_model_trace_from_payload(clean_model_payload),
                                },
                                commit=False,
                            )
                            content = AGENT_INTERNAL_TOOL_CONTEXT_LEAK_MESSAGE
                            chunks = [content] if chunks else []
                    missing_required_tool = self._missing_required_tool_after_model_response(run)
                    if missing_required_tool is not None:
                        content, chunks, clean_model_payload, tool_request = self._repair_missing_required_tool_request(
                            run=run,
                            current_user=user,
                            messages=messages,
                            invalid_content=content,
                            required_followup=missing_required_tool,
                            runtime=runtime,
                            iteration=iteration,
                        )
                        self.db.refresh(run)
                        if run.status in RUN_TERMINAL_STATUSES:
                            return run
                    if tool_request is None:
                        content, chunks = self._normalize_user_visible_markdown(
                            run=run,
                            runtime=runtime,
                            content=content,
                            chunks=chunks,
                            iteration=iteration,
                            final_summary=False,
                            trace_payload=_model_trace_from_payload(clean_model_payload),
                        )
                        self.db.refresh(run)
                        if run.status in RUN_TERMINAL_STATUSES:
                            return run
                        self._emit_model_deltas(
                            run=run,
                            runtime=runtime,
                            chunks=chunks,
                            trace_payload=_model_trace_from_payload(clean_model_payload),
                        )
                        self.db.refresh(run)
                        if run.status in RUN_TERMINAL_STATUSES:
                            return run
                        runtime.append_event(
                            run,
                            "model.completed",
                            {
                                "content": content,
                                "iteration": iteration,
                                "requested_tool": False,
                                **clean_model_payload,
                            },
                            commit=False,
                        )
                        self.db.refresh(run)
                        if run.status in RUN_TERMINAL_STATUSES:
                            return run
                        result = {"message": content, **clean_model_payload}
                        if tool_summaries:
                            result["tool_calls"] = tool_summaries
                        logger.info(
                            "agent_conversation_complete_without_tool run_id=%s iteration=%s content_length=%s",
                            run.run_id,
                            iteration,
                            len(content),
                        )
                        return runtime.complete_run(run, result, commit=True)

                runtime.append_event(
                    run,
                    "model.completed",
                    {
                        "content": _bounded_agent_content_preview(
                            content,
                            reference="AgentConversationRunner.model.completed.tool_request.content",
                        ),
                        "iteration": iteration,
                        "requested_tool": True,
                        **clean_model_payload,
                    },
                    commit=False,
                )
                detected_event_payload = tool_request.detected_event_payload(iteration=iteration)
                runtime.append_event(
                    run,
                    "model.tool_request_detected",
                    {
                        **detected_event_payload,
                        **_model_trace_from_payload(clean_model_payload),
                    },
                    commit=True,
                )
                logger.info(
                    "agent_tool_request_detected run_id=%s iteration=%s tool_name=%s reason=%s",
                    run.run_id,
                    iteration,
                    tool_request.tool_name,
                    detected_event_payload.get("reason"),
                )
                self.db.refresh(run)
                if run.status in RUN_TERMINAL_STATUSES:
                    return run
                messages.append(
                    AIChatMessage(
                        role="assistant",
                        content=_tool_request_context_message(tool_request=tool_request, content=content),
                    )
                )
                call = self._create_and_execute_tool_request(
                    run=run,
                    current_user=user,
                    tool_request=tool_request,
                    iteration=iteration,
                )
                logger.info(
                    "agent_tool_request_finished run_id=%s iteration=%s tool_call_id=%s tool_name=%s status=%s",
                    run.run_id,
                    iteration,
                    call.tool_call_id,
                    call.tool_name,
                    call.status,
                )
                tool_summaries.append(_tool_call_summary(call))
                self.db.refresh(run)
                if run.status in RUN_TERMINAL_STATUSES:
                    return run
                if run.status == "needs_human":
                    return run
                previous_failed_call = self._previous_same_failed_tool_call(run=run, call=call)
                if previous_failed_call is not None:
                    self._record_tool_no_progress_loop_observation(
                        run=run,
                        current_user=user,
                        previous_call=previous_failed_call,
                        repeated_call=call,
                    )
                    return runtime.fail_run(
                        run,
                        error_code="agent_repair_no_progress",
                        error_message=(
                            f"Agent stopped because {call.tool_name} failed twice with the same error "
                            "during repair."
                        ),
                        commit=True,
                    )
                _append_tool_result_context_message(messages, call)

            self._record_max_iterations_loop_observation(
                run=run,
                current_user=user,
                tool_summaries=tool_summaries,
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            content, chunks, model_payload = self._stream_model_response(
                run=run,
                messages=[
                    *messages,
                    AIChatMessage(
                        role="user",
                        content=(
                            "工具迭代次数已达到上限。请基于当前已返回的工具结果给出最终总结，不要再请求工具。"
                            f"\n{FINAL_RESPONSE_BUDGET_INSTRUCTION}"
                        ),
                    ),
                ],
                runtime=runtime,
                iteration=run.max_iterations,
                final_summary=True,
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            clean_model_payload = {key: value for key, value in model_payload.items() if value is not None}
            content, chunks = self._normalize_user_visible_markdown(
                run=run,
                runtime=runtime,
                content=content,
                chunks=chunks,
                iteration=run.max_iterations,
                final_summary=True,
                trace_payload=_model_trace_from_payload(clean_model_payload),
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            self._emit_model_deltas(
                run=run,
                runtime=runtime,
                chunks=chunks,
                trace_payload=_model_trace_from_payload(clean_model_payload),
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            runtime.append_event(
                run,
                "model.completed",
                {"content": content, "iteration": run.max_iterations, "final_summary": True, **clean_model_payload},
                commit=False,
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            logger.info(
                "agent_conversation_complete_after_tools run_id=%s tool_call_count=%s content_length=%s",
                run.run_id,
                len(tool_summaries),
                len(content),
            )
            return runtime.complete_run(run, {"message": content, "tool_calls": tool_summaries, **clean_model_payload}, commit=True)
        except HTTPException as exc:
            error_code = "agent_conversation_model_error"
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            bounded_detail = _bounded_run_failure_error_message(detail, error_code=error_code)
            logger.warning(
                "agent_conversation_failed_http run_id=%s project_id=%s error=%s",
                run.run_id,
                run.project_id,
                bounded_detail,
            )
            return self._fail_run_after_exception(
                run=run,
                runtime=runtime,
                error_code=error_code,
                error_message=bounded_detail,
                original_exception=exc,
            )
        except Exception as exc:  # noqa: BLE001
            error_code = "agent_conversation_unhandled_error"
            bounded_detail = _bounded_run_failure_error_message(exc, error_code=error_code)
            logger.error(
                "agent_conversation_failed_unhandled run_id=%s project_id=%s error_type=%s error=%s",
                run.run_id,
                run.project_id,
                type(exc).__name__,
                bounded_detail,
            )
            return self._fail_run_after_exception(
                run=run,
                runtime=runtime,
                error_code=error_code,
                error_message=bounded_detail,
                original_exception=exc,
            )

    def _unsupported_capability_guard_for_run(self, run: AgentRun) -> UnsupportedCapabilityGuard | None:
        available_tools = {spec.name for spec in ToolRegistry().list_specs()}
        for guard in _unsupported_capability_guards_for_intent(run.intent):
            if any(tool_name in available_tools for tool_name in guard.unavailable_tools):
                continue
            if self._classify_unsupported_capability_intent(run, guard):
                return guard
        return None

    def _classify_unsupported_capability_intent(self, run: AgentRun, guard: UnsupportedCapabilityGuard) -> bool:
        classifier_prompt = _unsupported_capability_classifier_prompt(guard)
        if classifier_prompt is None:
            logger.warning(
                "agent_unsupported_capability_classifier_prompt_missing run_id=%s skill_name=%s guard_name=%s",
                run.run_id,
                guard.skill_name,
                guard.name,
            )
            return False
        messages = [
            AIChatMessage(role="system", content=classifier_prompt),
            AIChatMessage(
                role="user",
                content=(
                    "请根据系统分类规则判断下面的用户请求是否需要触发当前能力 guard。\n\n"
                    f"用户请求：{run.intent}"
                ),
            ),
        ]
        try:
            response = AIService().chat(
                AIChatRequest(
                    messages=messages,
                    temperature=0,
                    max_tokens=200,
                    response_format="json",
                )
            )
        except HTTPException as exc:
            logger.warning(
                "agent_unsupported_capability_classification_failed run_id=%s guard_name=%s error=%s",
                run.run_id,
                guard.name,
                _bounded_agent_error_message(
                    _http_exception_detail(exc),
                    reference="AgentConversationRunner.unsupported_capability_classifier",
                ),
            )
            return False

        try:
            payload = json.loads(response.content)
        except ValueError:
            logger.warning(
                "agent_unsupported_capability_classification_invalid_json run_id=%s guard_name=%s content=%s",
                run.run_id,
                guard.name,
                _bounded_agent_error_message(
                    response.content,
                    reference="AgentConversationRunner.unsupported_capability_classifier.invalid_json",
                ),
            )
            return False

        requires_guard = bool(payload.get(guard.requires_field))
        logger.info(
            "agent_unsupported_capability_classified run_id=%s guard_name=%s requires_guard=%s confidence=%s reason=%s",
            run.run_id,
            guard.name,
            requires_guard,
            payload.get("confidence"),
            _bounded_agent_error_message(
                payload.get("reason"),
                reference="AgentConversationRunner.unsupported_capability_classifier.reason",
            ),
        )
        return requires_guard

    def _complete_unsupported_capability(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        guard: UnsupportedCapabilityGuard,
    ) -> AgentRun:
        message = _unsupported_capability_message(guard) or (
            f"当前 Agent 可用工具中缺少 `{guard.name}` 对应的后端能力，"
            "我不能假装已经完成该操作。请先补充对应工具后再让我执行。"
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return run
        trace_payload = _loop_trace_payload(
            run=run,
            iteration=0,
            loop_step="intent_capability_guard",
            model_call_id=_new_model_call_id(run=run, iteration=0, loop_step="intent_capability_guard"),
        )
        runtime.append_event(
            run,
            "model.started",
            {
                "provider": "harness",
                "iteration": 0,
                "synthetic": True,
                "reason": guard.synthetic_reason,
                **trace_payload,
            },
            commit=True,
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return run
        runtime.append_event(run, "model.delta", {"content": message, **trace_payload}, commit=True)
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return run
        runtime.append_event(
            run,
            "model.completed",
            {
                "content": message,
                "iteration": 0,
                "requested_tool": False,
                "synthetic": True,
                "reason": guard.synthetic_reason,
                **trace_payload,
            },
            commit=False,
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return run
        return runtime.complete_run(
            run,
            {
                "message": message,
                "completion_source": guard.completion_source,
            },
            commit=True,
        )

    def _should_suppress_realtime_deltas(self, run: AgentRun) -> bool:
        return _intent_likely_requires_agent_tool(run.intent)

    def _missing_required_tool_after_model_response(self, run: AgentRun) -> RequiredToolFollowupRule | None:
        for rule in _required_tool_followup_rules_for_intent(run.intent):
            if self._has_successful_tool_call(run, rule.required_tool):
                continue
            after_call = self._latest_successful_tool_call(run, rule.after_tool)
            if after_call is None:
                continue
            if rule.min_total_fields and not _tool_output_min_total_satisfied(
                after_call.output_json_redacted,
                rule.min_total_fields,
            ):
                continue
            return rule
        return None

    def _latest_successful_tool_call(self, run: AgentRun, tool_name: str) -> AgentToolCall | None:
        return self.db.scalar(
            select(AgentToolCall)
            .where(
                AgentToolCall.run_id == run.run_id,
                AgentToolCall.tool_name == tool_name,
                AgentToolCall.status == "succeeded",
            )
            .order_by(AgentToolCall.id.desc())
            .limit(1)
        )

    def _repair_missing_required_tool_request(
        self,
        *,
        run: AgentRun,
        current_user: User,
        messages: list[AIChatMessage],
        invalid_content: str,
        required_followup: RequiredToolFollowupRule,
        runtime: AgentRuntimeService,
        iteration: int,
    ) -> tuple[str, list[str], dict[str, Any], AgentToolRequest | None]:
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return invalid_content, [], {}, None
        runtime.append_event(
            run,
            "model.required_tool_missing",
            {
                "iteration": iteration,
                "after_tool": required_followup.after_tool,
                "required_tool": required_followup.required_tool,
                "content_preview": _bounded_agent_content_preview(
                    invalid_content,
                    reference="AgentConversationRunner.model.required_tool_missing.content",
                ),
            },
            commit=True,
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return invalid_content, [], {}, None
        self._record_required_tool_followup_loop_observation(
            run=run,
            current_user=current_user,
            iteration=iteration,
            invalid_content=invalid_content,
            required_followup=required_followup,
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return invalid_content, [], {}, None
        repair_messages = [
            *messages,
            AIChatMessage(role="assistant", content=_bounded_repair_context(invalid_content)),
            AIChatMessage(
                role="user",
                content=(
                    f"用户目标要求继续调用 `{required_followup.required_tool}`；"
                    f"该调用必须发生在 `{required_followup.after_tool}` 成功后，"
                    "但上一条回复只输出了自然语言。"
                    f"请基于最新 `{required_followup.after_tool}` 工具结果，"
                    f"只输出一个合法的 ```agent_tool_request fenced JSON block 来调用 "
                    f"`{required_followup.required_tool}`。"
                    "不要输出候选用例分析、解释或最终总结；分析内容应写进工具 input.requirement 或 input.extra_requirements。"
                ),
            ),
        ]
        repaired_content, repaired_chunks, repaired_payload = self._stream_model_response(
            run=run,
            messages=repair_messages,
            runtime=runtime,
            iteration=iteration,
            repair_attempt=True,
            suppress_visible_deltas=True,
            loop_step="required_tool_repair",
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return repaired_content, repaired_chunks, repaired_payload, None
        clean_payload = {key: value for key, value in repaired_payload.items() if value is not None}
        try:
            tool_request = self._parse_tool_request(repaired_content)
        except HTTPException as exc:
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return repaired_content, repaired_chunks, clean_payload, None
            repair_error_message = _bounded_agent_error_message(
                _http_exception_detail(exc),
                reference="AgentConversationRunner.model.required_tool_repair_failed",
            )
            runtime.append_event(
                run,
                "model.required_tool_repair_failed",
                {
                    "iteration": iteration,
                    "after_tool": required_followup.after_tool,
                    "required_tool": required_followup.required_tool,
                    "error_message": repair_error_message,
                    "content_preview": _bounded_agent_content_preview(
                        repaired_content,
                        reference="AgentConversationRunner.model.required_tool_repair_failed.content",
                    ),
                },
                commit=True,
            )
            raise
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return repaired_content, repaired_chunks, clean_payload, None
        runtime.append_event(
            run,
            "model.required_tool_repaired",
            {
                "iteration": iteration,
                "after_tool": required_followup.after_tool,
                "required_tool": required_followup.required_tool,
                "requested_tool": tool_request is not None,
                "tool_name": tool_request.tool_name if tool_request else None,
            },
            commit=True,
        )
        return repaired_content, repaired_chunks, clean_payload, tool_request

    def _record_required_tool_followup_loop_observation(
        self,
        *,
        run: AgentRun,
        current_user: User,
        iteration: int,
        invalid_content: str,
        required_followup: RequiredToolFollowupRule,
    ) -> None:
        content_preview = _bounded_agent_content_preview(
            invalid_content,
            reference="AgentConversationRunner.loop_observation.required_tool_missing.content",
        )
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=run.current_step_index,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": f"model-output:{run.run_id}:iter-{iteration}:required-followup",
                        "ref_type": "model_output",
                        "ref_id": f"{run.run_id}:iter-{iteration}:required-followup",
                        "mutability_class": "immutable",
                        "dependency_role": "audit_background",
                        "active_for_policy": False,
                        "content_hash": request_fingerprint(
                            {
                                "after_tool": required_followup.after_tool,
                                "required_tool": required_followup.required_tool,
                                "content_preview": content_preview,
                            }
                        ),
                    }
                ],
                required_evidence_ref_ids=[],
            ),
            current_user=current_user,
            commit=False,
        )
        LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="repair",
                next_action_is_high_risk=False,
                reasons=["required_tool_followup_missing"],
                observation={
                    "source": "required_tool_followup_guard",
                    "after_tool": required_followup.after_tool,
                    "required_tool": required_followup.required_tool,
                    "content_preview": content_preview,
                },
            ),
            current_user=current_user,
        )

    def _record_max_iterations_loop_observation(
        self,
        *,
        run: AgentRun,
        current_user: User,
        tool_summaries: list[dict[str, Any]],
    ) -> None:
        tool_call_ids: list[str] = []
        evidence_refs: list[dict[str, Any]] = []
        for summary in tool_summaries:
            if not summary.get("tool_call_id"):
                continue
            tool_call_id = str(summary["tool_call_id"])
            tool_call_ids.append(tool_call_id)
            evidence_refs.append({
                "evidence_ref_id": f"tool-call:{tool_call_id}",
                "ref_type": "tool_call",
                "ref_id": tool_call_id,
                "mutability_class": "immutable",
                "dependency_role": "audit_background",
                "active_for_policy": False,
                "content_hash": request_fingerprint(summary),
            })
        if not evidence_refs:
            evidence_refs = [
                {
                    "evidence_ref_id": f"run:{run.run_id}:max-iterations",
                    "ref_type": "agent_run",
                    "ref_id": run.run_id,
                    "mutability_class": "immutable",
                    "dependency_role": "audit_background",
                    "active_for_policy": False,
                    "content_hash": request_fingerprint(
                        {
                            "run_id": run.run_id,
                            "max_iterations": run.max_iterations,
                            "current_iteration": run.current_iteration,
                        }
                    ),
                }
            ]
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="stop",
                step_index=run.current_step_index,
                token_budget=1024,
                evidence_refs=evidence_refs,
                required_evidence_ref_ids=[],
            ),
            current_user=current_user,
            commit=False,
        )
        LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="stop",
                next_action_is_high_risk=False,
                reasons=["max_iterations"],
                observation={
                    "source": "max_iteration_guard",
                    "max_iterations": run.max_iterations,
                    "current_iteration": run.current_iteration,
                    "final_summary_iteration": run.max_iterations,
                    "tool_call_count": len(tool_summaries),
                    "tool_call_ids": tool_call_ids,
                },
            ),
            current_user=current_user,
        )

    def _previous_same_failed_tool_call(self, *, run: AgentRun, call: AgentToolCall) -> AgentToolCall | None:
        current_signature = _tool_failure_signature(call)
        if current_signature is None:
            return None
        previous = self.db.scalar(
            select(AgentToolCall)
            .where(
                AgentToolCall.run_id == run.run_id,
                AgentToolCall.id < call.id,
            )
            .order_by(AgentToolCall.id.desc())
            .limit(1)
        )
        if previous is None:
            return None
        if _tool_failure_signature(previous) != current_signature:
            return None
        return previous

    def _record_tool_no_progress_loop_observation(
        self,
        *,
        run: AgentRun,
        current_user: User,
        previous_call: AgentToolCall,
        repeated_call: AgentToolCall,
    ) -> None:
        evidence_refs = []
        for call in (previous_call, repeated_call):
            evidence_refs.append({
                "evidence_ref_id": f"tool-call:{call.tool_call_id}",
                "ref_type": "tool_call",
                "ref_id": call.tool_call_id,
                "mutability_class": "immutable",
                "dependency_role": "audit_background",
                "active_for_policy": False,
                "content_hash": call.output_hash
                or request_fingerprint(
                    {
                        "tool_call_id": call.tool_call_id,
                        "tool_name": call.tool_name,
                        "status": call.status,
                        "error_code": call.error_code,
                        "error_message": call.error_message,
                    }
                ),
            })
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="stop",
                step_index=run.current_step_index,
                token_budget=1024,
                evidence_refs=evidence_refs,
                required_evidence_ref_ids=[],
            ),
            current_user=current_user,
            commit=False,
        )
        LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="stop",
                next_action_is_high_risk=False,
                reasons=["same_failure_no_progress"],
                observation={
                    "source": "tool_result_no_progress_guard",
                    "tool_name": repeated_call.tool_name,
                    "error_code": repeated_call.error_code,
                    "error_message": repeated_call.error_message,
                    "repeat_count": 2,
                    "tool_call_ids": [previous_call.tool_call_id, repeated_call.tool_call_id],
                },
            ),
            current_user=current_user,
        )

    def _stream_model_response(
        self,
        *,
        run: AgentRun,
        messages: list[AIChatMessage],
        runtime: AgentRuntimeService,
        iteration: int,
        final_summary: bool = False,
        repair_attempt: bool = False,
        suppress_visible_deltas: bool = False,
        loop_step: str | None = None,
    ) -> tuple[str, list[str], dict[str, Any]]:
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return "", [], {}
        content_parts: list[str] = []
        resolved_loop_step = loop_step or _default_model_loop_step(
            final_summary=final_summary,
            repair_attempt=repair_attempt,
            suppress_visible_deltas=suppress_visible_deltas,
        )
        trace_payload = _loop_trace_payload(
            run=run,
            iteration=iteration,
            loop_step=resolved_loop_step,
            model_call_id=_new_model_call_id(run=run, iteration=iteration, loop_step=resolved_loop_step),
        )
        model_payload: dict[str, Any] = dict(trace_payload)
        runtime.append_event(
            run,
            "model.started",
            {
                "provider": AIService.provider,
                "iteration": iteration,
                "final_summary": final_summary,
                "repair_attempt": repair_attempt,
                **trace_payload,
            },
            commit=True,
        )
        logger.info(
            "agent_model_stream_start run_id=%s project_id=%s iteration=%s final_summary=%s repair_attempt=%s message_count=%s",
            run.run_id,
            run.project_id,
            iteration,
            final_summary,
            repair_attempt,
            len(messages),
        )
        self._release_db_transaction_before_external_wait()
        request = AIChatRequest(messages=messages, temperature=0.2)
        deltas_emitted = False
        first_delta_logged = False
        pending_visible_deltas: list[str] = []
        pending_visible_chars = 0
        last_delta_flush_at = time.monotonic()
        last_cancel_check_at = 0.0
        tool_request_marker_seen = False
        visible_deltas_retracted = False
        stream_interrupted = False

        def should_stop_stream(*, force: bool = False) -> bool:
            nonlocal last_cancel_check_at
            current = time.monotonic()
            if not force and current - last_cancel_check_at < AGENT_MODEL_STREAM_CANCEL_CHECK_INTERVAL_SECONDS:
                return False
            last_cancel_check_at = current
            self.db.refresh(run)
            terminal = run.status in RUN_TERMINAL_STATUSES
            if not terminal:
                self._release_db_transaction_before_external_wait()
            return terminal

        def log_first_delta_once() -> None:
            nonlocal first_delta_logged
            if first_delta_logged:
                return
            logger.info(
                "agent_model_first_delta run_id=%s iteration=%s final_summary=%s",
                run.run_id,
                iteration,
                final_summary,
            )
            first_delta_logged = True

        def flush_visible_delta(*, force: bool = False) -> None:
            nonlocal last_cancel_check_at, pending_visible_chars, last_delta_flush_at
            if not pending_visible_deltas:
                return
            current = time.monotonic()
            if (
                not force
                and pending_visible_chars < AGENT_MODEL_DELTA_FLUSH_CHARS
                and current - last_delta_flush_at < AGENT_MODEL_DELTA_FLUSH_INTERVAL_SECONDS
            ):
                return
            if should_stop_stream(force=force):
                pending_visible_deltas.clear()
                pending_visible_chars = 0
                last_delta_flush_at = current
                return
            delta = "".join(pending_visible_deltas)
            pending_visible_deltas.clear()
            pending_visible_chars = 0
            last_delta_flush_at = current
            log_first_delta_once()
            runtime.append_event(run, "model.delta", {"content": delta, **trace_payload}, commit=True)
            self._release_db_transaction_before_external_wait()
            last_cancel_check_at = 0.0

        def queue_visible_delta(delta: str, *, immediate: bool = False) -> None:
            nonlocal pending_visible_chars
            if suppress_visible_deltas:
                return
            pending_visible_deltas.append(delta)
            pending_visible_chars += len(delta)
            flush_visible_delta(force=immediate)

        try:
            for item in AIService().chat_stream(request):
                if should_stop_stream():
                    break
                if item.get("type") == "retry":
                    error_message = _bounded_agent_error_message(
                        item.get("error_message"),
                        reference="AgentConversationRunner.model.stream_retrying",
                    )
                    retry_payload = {
                        "provider": AIService.provider,
                        "iteration": iteration,
                        "final_summary": final_summary,
                        "repair_attempt": repair_attempt,
                        "attempt": item.get("attempt"),
                        "max_retries": item.get("max_retries"),
                        "delay_seconds": item.get("delay_seconds"),
                        "error_message": error_message,
                        **trace_payload,
                    }
                    runtime.append_event(run, "model.stream_retrying", retry_payload, commit=True)
                    self._release_db_transaction_before_external_wait()
                    logger.warning(
                        "agent_model_stream_retrying run_id=%s iteration=%s final_summary=%s attempt=%s max_retries=%s error=%s",
                        run.run_id,
                        iteration,
                        final_summary,
                        item.get("attempt"),
                        item.get("max_retries"),
                        error_message,
                    )
                    continue
                if item.get("type") == "delta":
                    delta = str(item.get("content") or "")
                    if delta:
                        content_parts.append(delta)
                        content = "".join(content_parts)
                        if "```agent_tool_request" in content:
                            tool_request_marker_seen = True
                            pending_visible_deltas.clear()
                            pending_visible_chars = 0
                            if deltas_emitted and not visible_deltas_retracted:
                                runtime.append_event(
                                    run,
                                    "model.markdown_normalized",
                                    {
                                        "iteration": iteration,
                                        "final_summary": final_summary,
                                        "repair_attempt": repair_attempt,
                                        "content": "",
                                        "replace_content": True,
                                        "normalization_reason": "tool_request_stream_suppressed",
                                        **trace_payload,
                                    },
                                    commit=True,
                                )
                                self._release_db_transaction_before_external_wait()
                                visible_deltas_retracted = True
                            continue
                        if suppress_visible_deltas:
                            continue
                        if deltas_emitted:
                            queue_visible_delta(delta)
                        elif not _should_hold_for_tool_request_detection(content):
                            deltas_emitted = True
                            for pending_delta in content_parts:
                                queue_visible_delta(pending_delta, immediate=True)
                elif item.get("type") == "done":
                    model_payload = {
                        **trace_payload,
                        "provider": AIService.provider,
                        "model": item.get("model"),
                        "finish_reason": item.get("finish_reason"),
                        "usage": item.get("usage"),
                    }
        except HTTPException as exc:
            if not content_parts:
                raise
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                content = "".join(content_parts).strip()
                return content, [], model_payload
            stream_interrupted = True
            detail = _bounded_agent_error_message(
                _http_exception_detail(exc),
                reference="AgentConversationRunner.model.stream_interrupted",
            )
            model_payload = {
                **trace_payload,
                "provider": AIService.provider,
                "finish_reason": "stream_interrupted",
                "stream_interrupted": True,
                "error_message": detail,
            }
            runtime.append_event(
                run,
                "model.stream_interrupted",
                {
                    "iteration": iteration,
                    "final_summary": final_summary,
                    "repair_attempt": repair_attempt,
                    "content_length": len("".join(content_parts)),
                    "error_message": detail,
                    **trace_payload,
                },
                commit=True,
            )
            logger.warning(
                "agent_model_stream_interrupted run_id=%s iteration=%s final_summary=%s content_length=%s error=%s",
                run.run_id,
                iteration,
                final_summary,
                len("".join(content_parts)),
                detail,
            )
        flush_visible_delta(force=True)
        content = "".join(content_parts).strip()
        if (
            content_parts
            and not suppress_visible_deltas
            and not deltas_emitted
            and not _looks_like_tool_request_content(content)
        ):
            for pending_delta in content_parts:
                queue_visible_delta(pending_delta)
            flush_visible_delta(force=True)
            deltas_emitted = True
        if tool_request_marker_seen and deltas_emitted:
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return content, [] if deltas_emitted else content_parts, model_payload
            runtime.append_event(
                run,
                "model.tool_request_stream_suppressed",
                {
                    "iteration": iteration,
                    "final_summary": final_summary,
                    "repair_attempt": repair_attempt,
                    "content_length": len(content),
                    **trace_payload,
                },
                commit=True,
            )
        logger.info(
            "agent_model_stream_done run_id=%s iteration=%s final_summary=%s content_length=%s deltas_emitted=%s finish_reason=%s model=%s stream_interrupted=%s",
            run.run_id,
            iteration,
            final_summary,
            len(content),
            deltas_emitted,
            model_payload.get("finish_reason"),
            model_payload.get("model"),
            stream_interrupted,
        )
        if suppress_visible_deltas and not deltas_emitted:
            if content and not _looks_like_tool_request_content(content):
                return content, [content], model_payload
            return content, [], model_payload
        return content, [] if deltas_emitted else content_parts, model_payload

    def _emit_model_deltas(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        chunks: list[str],
        trace_payload: dict[str, Any] | None = None,
    ) -> None:
        trace_payload = trace_payload or {}
        for delta in chunks:
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return
            runtime.append_event(run, "model.delta", {"content": delta, **trace_payload}, commit=True)

    def _normalize_user_visible_markdown(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        content: str,
        chunks: list[str],
        iteration: int,
        final_summary: bool,
        trace_payload: dict[str, Any] | None = None,
    ) -> tuple[str, list[str]]:
        normalized = _normalize_agent_markdown_response(content)
        if normalized == content:
            return content, chunks
        logger.info(
            "agent_markdown_response_normalized run_id=%s iteration=%s final_summary=%s original_length=%s normalized_length=%s",
            run.run_id,
            iteration,
            final_summary,
            len(content),
            len(normalized),
        )
        runtime.append_event(
            run,
            "model.markdown_normalized",
            {
                "iteration": iteration,
                "final_summary": final_summary,
                "original_length": len(content),
                "normalized_length": len(normalized),
                "content": normalized,
                "replace_content": True,
                **(trace_payload or {}),
            },
            commit=False,
        )
        return normalized, [normalized] if chunks else chunks

    def _parse_tool_request(
        self,
        content: str,
        *,
        allow_surrounding_text: bool = False,
        normalize_evidence_refs: bool = False,
    ) -> AgentToolRequest | None:
        raw = None
        match = TOOL_REQUEST_BLOCK_RE.search(content)
        if match:
            surrounding = (content[:match.start()] + content[match.end():]).strip()
            if surrounding and not allow_surrounding_text:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="模型工具请求必须只包含 agent_tool_request fenced JSON block，不能混合自然语言",
                )
            if allow_surrounding_text and TOOL_REQUEST_BLOCK_RE.search(content, match.end()):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="模型工具请求只能包含一个 agent_tool_request fenced JSON block",
                )
            raw = match.group("body")
        else:
            stripped = content.strip()
            if stripped.startswith("{") and stripped.endswith("}") and '"tool_name"' in stripped:
                raw = stripped
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="模型工具请求不是合法 JSON",
            ) from exc
        tool_name = payload.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="模型工具请求缺少 tool_name")
        tool_input = payload.get("input", {})
        if tool_input is None:
            tool_input = {}
        if not isinstance(tool_input, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="模型工具 input 必须是对象")
        evidence_refs = payload.get("evidence_refs", [])
        if evidence_refs is None:
            evidence_refs = []
        if normalize_evidence_refs:
            if isinstance(evidence_refs, dict):
                evidence_refs = [evidence_refs] if evidence_refs else []
            elif isinstance(evidence_refs, list):
                evidence_refs = [item for item in evidence_refs if isinstance(item, dict)]
            else:
                evidence_refs = []
        if not isinstance(evidence_refs, list) or not all(isinstance(item, dict) for item in evidence_refs):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="模型工具 evidence_refs 必须是对象列表")
        return AgentToolRequest(
            tool_name=tool_name,
            tool_input=dict(tool_input),
            reason=payload.get("reason") if isinstance(payload.get("reason"), str) else None,
            evidence_refs=tuple(dict(item) for item in evidence_refs),
        )

    def _repair_invalid_tool_request(
        self,
        *,
        run: AgentRun,
        current_user: User,
        messages: list[AIChatMessage],
        invalid_content: str,
        error_message: str,
        model_payload: dict[str, Any],
        runtime: AgentRuntimeService,
        iteration: int,
    ) -> tuple[str, list[str], dict[str, Any], AgentToolRequest | None]:
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return invalid_content, [], model_payload, None
        error_message = _bounded_agent_error_message(
            error_message,
            reference="AgentConversationRunner.model.tool_request_invalid",
        )
        runtime.append_event(
            run,
            "model.tool_request_invalid",
            {
                "iteration": iteration,
                "error_message": error_message,
                "content_preview": _bounded_agent_content_preview(
                    invalid_content,
                    reference="AgentConversationRunner.model.tool_request_invalid.content",
                ),
                **_model_trace_from_payload(model_payload),
            },
            commit=True,
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return invalid_content, [], model_payload, None
        self._record_invalid_tool_request_loop_observation(
            run=run,
            current_user=current_user,
            iteration=iteration,
            invalid_content=invalid_content,
            error_message=error_message,
            model_payload=model_payload,
        )
        salvaged_tool_request = self._try_salvage_mixed_tool_request(invalid_content)
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return invalid_content, [], model_payload, None
        if salvaged_tool_request is not None:
            runtime.append_event(
                run,
                "model.tool_request_repaired",
                {
                    "iteration": iteration,
                    "requested_tool": True,
                    "tool_name": salvaged_tool_request.tool_name,
                    "repair_strategy": "salvaged_fenced_tool_request",
                    **_model_trace_from_payload(model_payload),
                },
                commit=True,
            )
            return invalid_content, [], model_payload, salvaged_tool_request

        repair_messages = [
            *messages,
            AIChatMessage(role="assistant", content=_bounded_repair_context(invalid_content)),
            AIChatMessage(
                role="user",
                content=(
                    "上一条回复看起来想调用工具，但 agent_tool_request 格式无效。"
                    f"错误：{error_message}\n"
                    "请重新输出：如果仍需工具，请只输出一个合法的 ```agent_tool_request fenced JSON block；"
                    "如果不需要工具，请直接给用户自然语言回复。不要解释格式错误。"
                ),
            ),
        ]
        repaired_content, repaired_chunks, repaired_payload = self._stream_model_response(
            run=run,
            messages=repair_messages,
            runtime=runtime,
            iteration=iteration,
            repair_attempt=True,
            suppress_visible_deltas=True,
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return repaired_content, repaired_chunks, repaired_payload, None
        clean_payload = {key: value for key, value in repaired_payload.items() if value is not None}
        try:
            tool_request = self._parse_tool_request(repaired_content)
        except HTTPException as exc:
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return repaired_content, repaired_chunks, clean_payload, None
            repair_error_message = _bounded_agent_error_message(
                _http_exception_detail(exc),
                reference="AgentConversationRunner.model.tool_request_repair_failed",
            )
            runtime.append_event(
                run,
                "model.tool_request_repair_failed",
                {
                    "iteration": iteration,
                    "error_message": repair_error_message,
                    "content_preview": _bounded_agent_content_preview(
                        repaired_content,
                        reference="AgentConversationRunner.model.tool_request_repair_failed.content",
                    ),
                    **_model_trace_from_payload(clean_payload),
                },
                commit=True,
            )
            raise
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return repaired_content, repaired_chunks, clean_payload, None
        runtime.append_event(
            run,
            "model.tool_request_repaired",
            {
                "iteration": iteration,
                "requested_tool": tool_request is not None,
                "tool_name": tool_request.tool_name if tool_request else None,
                **_model_trace_from_payload(clean_payload),
            },
            commit=True,
        )
        return repaired_content, repaired_chunks, clean_payload, tool_request

    def _record_invalid_tool_request_loop_observation(
        self,
        *,
        run: AgentRun,
        current_user: User,
        iteration: int,
        invalid_content: str,
        error_message: str,
        model_payload: dict[str, Any],
    ) -> None:
        model_call_id = model_payload.get("model_call_id")
        content_preview = _bounded_agent_content_preview(
            invalid_content,
            reference="AgentConversationRunner.loop_observation.tool_request_invalid.content",
        )
        evidence_ref_id = f"model-call:{model_call_id}" if model_call_id else f"model-output:{run.run_id}:iter-{iteration}"
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=run.current_step_index,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": evidence_ref_id,
                        "ref_type": "model_output",
                        "ref_id": str(model_call_id or f"{run.run_id}:iter-{iteration}"),
                        "mutability_class": "immutable",
                        "dependency_role": "audit_background",
                        "active_for_policy": False,
                        "content_hash": request_fingerprint({
                            "content_preview": content_preview,
                            "error_message": error_message,
                        }),
                    }
                ],
                required_evidence_ref_ids=[],
            ),
            current_user=current_user,
            commit=False,
        )
        LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="repair",
                next_action_is_high_risk=False,
                reasons=["tool_request_format_invalid"],
                observation={
                    "source": "tool_request_parse_guard",
                    "model_call_id": model_call_id,
                    "content_preview": content_preview,
                    "error_message": error_message,
                },
            ),
            current_user=current_user,
        )

    def _try_salvage_mixed_tool_request(self, content: str) -> AgentToolRequest | None:
        match = TOOL_REQUEST_BLOCK_RE.search(content)
        if match is None or TOOL_REQUEST_BLOCK_RE.search(content, match.end()):
            return None
        surrounding = (content[:match.start()] + content[match.end():]).strip()
        if not surrounding:
            return None
        try:
            return self._parse_tool_request(
                content,
                allow_surrounding_text=True,
                normalize_evidence_refs=True,
            )
        except HTTPException:
            return None

    def _create_and_execute_tool_request(
        self,
        *,
        run: AgentRun,
        current_user: User,
        tool_request: AgentToolRequest,
        iteration: int,
    ) -> AgentToolCall:
        runtime = AgentRuntimeService(self.db)
        tool_input = self._normalize_tool_input(
            run=run,
            tool_name=tool_request.tool_name,
            tool_input=tool_request.input_for_ledger(),
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                tool_name=tool_request.tool_name,
                input=tool_input,
                step_index=run.current_step_index,
                attempt_index=iteration,
                evidence_refs=tool_request.evidence_refs_for_ledger(),
            ),
            current_user=current_user,
            enqueue=False,
        )
        decision_reason = (
            _bounded_agent_error_message(
                tool_request.reason,
                reference="AgentConversationRunner.tool_trace.decision_reason",
            )
            if tool_request.reason is not None
            else None
        )
        tool_trace_payload = _loop_trace_payload(
            run=run,
            iteration=iteration,
            loop_step="tool_execution",
            tool_call_id=call.tool_call_id,
            decision_reason=decision_reason,
        )
        self.db.refresh(run)
        if call.approval_required:
            blocking = list(run.blocking_tool_call_ids_json or [])
            if call.tool_call_id not in blocking:
                blocking.append(call.tool_call_id)
            run.status = "needs_human"
            run.blocking_tool_call_ids_json = blocking
            runtime.append_event(
                run,
                "run.needs_human",
                {
                    "reason": "tool_approval_required",
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                    **tool_trace_payload,
                },
                commit=False,
            )
            self.db.commit()
            self.db.refresh(run)
            self.db.refresh(call)
            return call

        missing_prerequisite_tool = self._missing_tool_prerequisite_before_execution(run=run, call=call)
        if missing_prerequisite_tool is not None:
            spec = ToolRegistry().get(call.tool_name)
            output = {
                "required_tool": missing_prerequisite_tool,
                "blocked_tool": call.tool_name,
                "next_action": spec.missing_prerequisite_next_action or (
                    f"Call {missing_prerequisite_tool} before calling {call.tool_name}."
                ),
            }
            call.status = "failed"
            call.execution_phase = "blocked_by_harness"
            call.error_code = spec.missing_prerequisite_error_code or "tool_prerequisite_required"
            call.error_message = (
                f"{call.tool_name} requires a successful {missing_prerequisite_tool} result "
                "in the same Agent Run before execution."
            )
            call.output_json_redacted = output
            call.output_hash = request_fingerprint(output)
            runtime.append_event(
                run,
                "tool.failed",
                {
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                    "error_code": call.error_code,
                    "error_message": call.error_message,
                    **tool_trace_payload,
                },
                commit=False,
            )
            runtime.append_event(
                run,
                "tool.result_observed",
                {
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                    "status": call.status,
                    "error_code": call.error_code,
                    **tool_trace_payload,
                },
                commit=False,
            )
            self._record_tool_prerequisite_loop_observation(
                run=run,
                current_user=current_user,
                call=call,
                required_tool=missing_prerequisite_tool,
            )
            run.current_iteration = iteration + 1
            run.current_step_index += 1
            self.db.commit()
            self.db.refresh(run)
            self.db.refresh(call)
            return call

        executed = ToolExecutor(self.db).execute_tool_call(
            call=call,
            run=run,
            queue_item=None,
            current_user=current_user,
        )
        self.db.refresh(run)
        run.current_iteration = iteration + 1
        run.current_step_index += 1
        runtime.append_event(
            run,
            "tool.result_observed",
            {
                "tool_call_id": executed.tool_call_id,
                "tool_name": executed.tool_name,
                "status": executed.status,
                **tool_trace_payload,
            },
            commit=False,
        )
        self.db.commit()
        self.db.refresh(run)
        self.db.refresh(executed)
        return executed

    def _record_tool_prerequisite_loop_observation(
        self,
        *,
        run: AgentRun,
        current_user: User,
        call: AgentToolCall,
        required_tool: str,
    ) -> None:
        build = ContextBuilder(self.db).build(
            run_id=run.run_id,
            payload=AgentContextBuildCreateRequest(
                build_purpose="repair",
                step_index=run.current_step_index,
                token_budget=1024,
                evidence_refs=[
                    {
                        "evidence_ref_id": f"tool-call:{call.tool_call_id}",
                        "ref_type": "tool_call",
                        "ref_id": call.tool_call_id,
                        "mutability_class": "immutable",
                        "dependency_role": "audit_background",
                        "active_for_policy": False,
                        "content_hash": call.output_hash,
                    }
                ],
                required_evidence_ref_ids=[],
            ),
            current_user=current_user,
            commit=False,
        )
        LoopController(self.db).record_observation(
            run_id=run.run_id,
            payload=AgentLoopObservationCreateRequest(
                decision_context_build_id=build.context_build_id,
                next_action="repair",
                next_action_is_high_risk=False,
                reasons=["tool_prerequisite_missing"],
                observation={
                    "source": "tool_prerequisite_guard",
                    "tool_call_id": call.tool_call_id,
                    "blocked_tool": call.tool_name,
                    "required_tool": required_tool,
                    "error_code": call.error_code,
                },
            ),
            current_user=current_user,
        )

    def _normalize_tool_input(self, *, run: AgentRun, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        spec = ToolRegistry().get(tool_name)
        required = set((spec.input_schema or {}).get("required") or [])
        if "project_id" in required and "project_id" not in tool_input:
            tool_input["project_id"] = run.project_id
        return tool_input

    def _missing_tool_prerequisite_before_execution(self, *, run: AgentRun, call: AgentToolCall) -> str | None:
        prerequisite_tool = ToolRegistry().get(call.tool_name).required_successful_tool_before
        if prerequisite_tool is None:
            return None
        if self._has_successful_tool_call(run, prerequisite_tool, before_tool_call_id=call.id):
            return None
        return prerequisite_tool

    def _has_successful_tool_call(
        self,
        run: AgentRun,
        tool_name: str,
        *,
        before_tool_call_id: int | None = None,
    ) -> bool:
        query = select(AgentToolCall.tool_call_id).where(
            AgentToolCall.run_id == run.run_id,
            AgentToolCall.tool_name == tool_name,
            AgentToolCall.status == "succeeded",
        )
        if before_tool_call_id is not None:
            query = query.where(AgentToolCall.id < before_tool_call_id)
        return self.db.scalar(query.limit(1)) is not None

    def _build_chat_messages(
        self,
        run: AgentRun,
        *,
        current_user: User,
        runtime: AgentRuntimeService,
    ) -> list[AIChatMessage]:
        messages = [AIChatMessage(role="system", content=_conversation_system_prompt())]
        messages.append(AIChatMessage(role="system", content=_format_run_context(run)))
        working_context: dict[str, Any] | None = None
        previous_runs: list[AgentRun] = []
        if run.conversation_id:
            previous_runs = list(
                self.db.scalars(
                    select(AgentRun)
                    .where(
                        AgentRun.project_id == run.project_id,
                        AgentRun.conversation_id == run.conversation_id,
                        AgentRun.id < run.id,
                        AgentRun.status == AGENT_HISTORY_CONTEXT_SOURCE_STATUS,
                    )
                    .order_by(AgentRun.id.desc())
                    .limit(AGENT_HISTORY_CONTEXT_MAX_RUNS)
                ).all()
            )
            previous_runs = list(reversed(previous_runs))
            working_context = _conversation_working_context(
                current_intent=run.intent,
                previous_runs=previous_runs,
            )
        skill_intent = run.intent
        if working_context is not None:
            skill_intent = f"{run.intent}\n{json.dumps(working_context, ensure_ascii=False, default=str)}"
        messages.extend(_agent_skill_messages(skill_intent))
        memory_context = self._memory_context_message(run=run, current_user=current_user, runtime=runtime)
        if memory_context is not None:
            messages.append(memory_context)
        if run.conversation_id:
            if working_context is not None:
                messages.append(AIChatMessage(
                    role="system",
                    content=_format_conversation_working_context(working_context),
                ))
            history_messages, compaction_payload = self._conversation_history_messages(
                previous_runs=previous_runs,
                compaction_window_metadata=lambda: runtime.context_compaction_window_metadata(run=run),
            )
            messages.extend(history_messages)
            if compaction_payload is not None:
                compaction_event = runtime.append_event(
                    run,
                    AGENT_HISTORY_CONTEXT_COMPACTION_EVENT,
                    compaction_payload,
                    commit=True,
                )
                runtime.record_checkpoint_context_compaction(
                    run=run,
                    event=compaction_event,
                    commit=True,
                )
        messages.append(AIChatMessage(role="user", content=run.intent))
        return messages

    def _conversation_history_messages(
        self,
        *,
        previous_runs: list[AgentRun],
        compaction_window_metadata: Callable[[], dict[str, Any]] | dict[str, Any] | None = None,
    ) -> tuple[list[AIChatMessage], dict[str, Any] | None]:
        pairs = [
            {
                "run_id": previous.run_id,
                "status": previous.status,
                "intent": previous.intent,
                "assistant": _assistant_message_from_run(previous) or "",
            }
            for previous in previous_runs
        ]
        full_messages = _history_pairs_to_messages(pairs)
        estimated_before = _estimate_chat_messages_tokens(full_messages)
        if estimated_before <= AGENT_HISTORY_CONTEXT_TOKEN_BUDGET:
            return full_messages, None

        recent_count = min(AGENT_HISTORY_CONTEXT_FULL_TURNS, len(pairs))
        older_pairs = pairs[:-recent_count] if recent_count else pairs
        recent_pairs = pairs[-recent_count:] if recent_count else []
        compacted_messages = []
        if older_pairs:
            compacted_messages.append(AIChatMessage(
                role=AGENT_HISTORY_CONTEXT_SUMMARY_ROLE,
                content=_compact_history_summary(older_pairs),
            ))
        compacted_messages.extend(_history_pairs_to_messages(
            recent_pairs,
            user_chars=AGENT_HISTORY_CONTEXT_RECENT_USER_CHARS,
            assistant_chars=AGENT_HISTORY_CONTEXT_RECENT_ASSISTANT_CHARS,
        ))
        estimated_after = _estimate_chat_messages_tokens(compacted_messages)
        if compaction_window_metadata is None:
            raise ValueError("compaction_window_metadata is required when conversation history is compacted")
        if callable(compaction_window_metadata):
            window_metadata = compaction_window_metadata()
        else:
            window_metadata = dict(compaction_window_metadata)
        payload = {
            "trigger": AGENT_HISTORY_COMPACTION_TRIGGER,
            "reason": AGENT_HISTORY_COMPACTION_REASON,
            "phase": AGENT_HISTORY_COMPACTION_PHASE,
            "implementation": AGENT_HISTORY_COMPACTION_IMPLEMENTATION,
            "strategy": AGENT_HISTORY_CONTEXT_COMPACTION_STRATEGY,
            "original_run_count": len(pairs),
            "compacted_run_count": len(older_pairs),
            "kept_full_run_count": len(recent_pairs),
            "estimated_input_units_before": estimated_before,
            "estimated_input_units_after": estimated_after,
            "budget_limit_units": AGENT_HISTORY_CONTEXT_TOKEN_BUDGET,
            "summary_role": AGENT_HISTORY_CONTEXT_SUMMARY_ROLE,
            "replacement_history": AGENT_HISTORY_COMPACTION_REPLACEMENT_HISTORY,
            "initial_context_injection": AGENT_HISTORY_COMPACTION_INITIAL_CONTEXT_INJECTION,
            "reference_context_item": AGENT_HISTORY_COMPACTION_REFERENCE_CONTEXT_ITEM,
            "context_baseline": AGENT_HISTORY_COMPACTION_CONTEXT_BASELINE,
            **window_metadata,
            "source": AGENT_HISTORY_COMPACTION_SOURCE,
        }
        return compacted_messages, payload

    def _memory_context_message(
        self,
        *,
        run: AgentRun,
        current_user: User,
        runtime: AgentRuntimeService,
    ) -> AIChatMessage | None:
        try:
            candidates = MemoryManager(self.db).retrieve(
                project_id=run.project_id,
                query=run.intent,
                profile_name="normal_plan_v1",
                task_risk="normal",
                usage_role="conversation_context",
                current_user=current_user,
                run_id=run.run_id,
                step_index=run.current_step_index,
                limit=5,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            runtime.append_event(
                run,
                "memory.context_unavailable",
                {
                    "profile_name": "normal_plan_v1",
                    "usage_role": "conversation_context",
                    "error": detail,
                },
                commit=True,
            )
            return None
        if not candidates:
            return None
        runtime.append_event(
            run,
            "memory.context_injected",
            {
                "profile_name": "normal_plan_v1",
                "usage_role": "conversation_context",
                "active_for_policy": False,
                "memory_ids": [candidate.memory_id for candidate in candidates],
                "memory_versions": {
                    str(candidate.memory_id): candidate.memory_version
                    for candidate in candidates
                },
                "count": len(candidates),
            },
            commit=True,
        )
        return AIChatMessage(role="system", content=_format_memory_context(candidates))


class ExecutionLedgerService:
    def __init__(self, db: Session):
        self.db = db
        self.tool_registry = ToolRegistry()
        self.policy_resolver = ToolPolicyResolver()
        self.permission_service = PermissionService(db)

    def create_tool_call(
        self,
        *,
        payload: AgentToolCallCreateRequest,
        current_user: User,
        enqueue: bool = True,
    ) -> AgentToolCall:
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == payload.run_id).with_for_update())
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run 不存在")
        self.permission_service.require_project_access(current_user, run.project_id)
        if run.status == "cancelled":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "tool_call_obsolete"})
        if run.status == "migration_blocked":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "run_migration_blocked"})

        spec = self.tool_registry.get(payload.tool_name)
        resolved = self.policy_resolver.resolve(spec=spec, evidence_refs=payload.evidence_refs)
        idempotency_key = payload.idempotency_key or request_fingerprint({
            "run_id": payload.run_id,
            "step_index": payload.step_index,
            "attempt_index": payload.attempt_index,
            "tool_name": payload.tool_name,
            "input": payload.input,
        })
        existing = self.db.scalar(
            select(AgentToolCall).where(
                AgentToolCall.idempotency_scope == payload.run_id,
                AgentToolCall.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            self._record_duplicate_blocked(run=run, existing=existing, idempotency_key=idempotency_key)
            return existing

        permission_snapshot = {
            "user_id": current_user.id,
            "project_id": run.project_id,
            "required_permissions": list(spec.required_permissions),
            "captured_at": _utcnow().isoformat(),
            "audit_only": True,
        }
        contract = spec.backend_contract
        tool_call_id = f"agent-tool-{uuid.uuid4().hex}"
        input_hash = request_fingerprint(payload.input)
        evidence_refs = copy_evidence_refs(payload.evidence_refs)
        decision_context_build_id = payload.decision_context_build_id
        if resolved.approval_required and resolved.resolved_side_effect_class in HIGH_RISK_SIDE_EFFECT_CLASSES:
            frozen_input_ref = _approval_tool_call_input_evidence_ref(
                run=run,
                tool_call_id=tool_call_id,
                tool_name=spec.name,
                input_hash=input_hash,
            )
            evidence_refs = [*evidence_refs, frozen_input_ref]
            if decision_context_build_id is None:
                build = ContextBuilder(self.db).build(
                    run_id=run.run_id,
                    payload=AgentContextBuildCreateRequest(
                        build_purpose="approval",
                        step_index=payload.step_index,
                        token_budget=1024,
                        evidence_refs=evidence_refs,
                        required_evidence_ref_ids=[frozen_input_ref["evidence_ref_id"]],
                    ),
                    current_user=current_user,
                    commit=False,
                )
                decision_context_build_id = build.context_build_id
        policy_evidence_refs, audit_evidence_refs, evidence_summary = EvidenceRefResolver().split_policy_and_audit_refs(
            evidence_refs
        )
        call = AgentToolCall(
            tool_call_id=tool_call_id,
            run_id=run.run_id,
            step_index=payload.step_index,
            attempt_index=payload.attempt_index,
            runtime_snapshot_id=run.runtime_snapshot_id,
            tool_name=spec.name,
            tool_version=spec.version,
            schema_hash=spec.schema_hash,
            manifest_hash=spec.manifest_hash,
            idempotency_scope=run.run_id,
            idempotency_key=idempotency_key,
            base_side_effect_class=spec.side_effect_class,
            resolved_side_effect_class=resolved.resolved_side_effect_class,
            base_replay_policy=spec.replay_policy,
            resolved_replay_policy=resolved.resolved_replay_policy,
            policy_reason_json=resolved.policy_reason,
            status="planned",
            effect_submission_state="none",
            input_hash=input_hash,
            input_json_redacted=mask_sensitive(payload.input),
            evidence_refs_json=evidence_refs,
            policy_evidence_refs_json=policy_evidence_refs,
            audit_evidence_refs_json=audit_evidence_refs,
            evidence_mutability_summary_json=evidence_summary,
            decision_context_build_id=decision_context_build_id,
            permission_snapshot_json=permission_snapshot,
            required_permissions_json=list(spec.required_permissions),
            approval_required=resolved.approval_required,
            approval_scope_hash=request_fingerprint({
                "run_id": run.run_id,
                "tool_name": spec.name,
                "input_hash": request_fingerprint(payload.input),
            }),
            backend_name=contract.backend_name if contract else None,
            backend_operation=contract.backend_operation if contract else None,
            backend_contract_version=contract.backend_contract_version if contract else None,
            backend_request_schema_hash=contract.request_schema_hash if contract else None,
            backend_output_schema_hash=contract.output_schema_hash if contract else None,
            reconcile_contract_version=contract.reconcile_contract_version if contract else None,
            result_adapter_version=contract.result_adapter_version if contract else None,
            backend_effect_capability=contract.effect_capability if contract else None,
        )
        self.db.add(call)
        self.db.flush()
        runtime = AgentRuntimeService(self.db)
        runtime.append_event(run, "tool.planned", {"tool_call_id": call.tool_call_id, "tool_name": call.tool_name}, commit=False)
        EvidenceWatchService(self.db).register_watches(
            run=run,
            evidence_refs=evidence_refs,
            tool_call_id=call.tool_call_id,
            commit=False,
        )
        if call.approval_required:
            ApprovalService(self.db).create_pending_approval(
                call=call,
                run=run,
                current_user=current_user,
                commit=False,
            )
        if enqueue and not call.approval_required:
            AgentWorkerQueueService(self.db).enqueue_tool_call(call, commit=False)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(
                select(AgentToolCall).where(
                    AgentToolCall.idempotency_scope == payload.run_id,
                    AgentToolCall.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                self._record_duplicate_blocked(run=run, existing=existing, idempotency_key=idempotency_key)
                return existing
            raise
        self.db.refresh(call)
        return call

    def _record_duplicate_blocked(self, *, run: AgentRun, existing: AgentToolCall, idempotency_key: str) -> None:
        AgentRuntimeService(self.db).append_event(
            run,
            "tool.duplicate_blocked",
            {
                "tool_call_id": existing.tool_call_id,
                "tool_name": existing.tool_name,
                "idempotency_scope": run.run_id,
                "idempotency_key": idempotency_key,
            },
            commit=True,
        )

    def get_tool_call(self, *, tool_call_id: str, current_user: User) -> AgentToolCall:
        call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == tool_call_id))
        if call is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent tool call 不存在")
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == call.run_id))
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run 不存在")
        self.permission_service.require_project_access(current_user, run.project_id)
        return call


def _approval_tool_call_input_evidence_ref(
    *,
    run: AgentRun,
    tool_call_id: str,
    tool_name: str,
    input_hash: str,
) -> dict[str, Any]:
    return {
        "evidence_ref_id": f"tool-call-input:{tool_call_id}",
        "ref_type": "system_record",
        "ref_id": tool_call_id,
        "authority": "system_record",
        "mutability_class": "immutable",
        "dependency_role": "decision_dependency",
        "active_for_policy": True,
        "required_for_high_risk": True,
        "content_hash": input_hash,
        "snapshot_id": run.runtime_snapshot_id,
        "captured_at": _utcnow().isoformat(),
        "freshness_policy": "none",
        "tool_name": tool_name,
    }


class AgentWorkerQueueService:
    def __init__(self, db: Session):
        self.db = db

    def enqueue_tool_call(self, call: AgentToolCall, *, commit: bool = True, priority: int = 100) -> AgentWorkerQueue:
        item = AgentWorkerQueue(
            queue_id=f"agent-queue-{uuid.uuid4().hex}",
            run_id=call.run_id,
            tool_call_id=call.tool_call_id,
            status="queued",
            priority=priority,
            available_at=_utcnow(),
        )
        self.db.add(item)
        if commit:
            self.db.commit()
            self.db.refresh(item)
        else:
            self.db.flush()
        return item

    def claim_next(self, *, worker_id: str, lease_seconds: int = 60) -> AgentWorkerQueue | None:
        now = _utcnow()
        item = self.db.scalar(
            select(AgentWorkerQueue)
            .where(
                AgentWorkerQueue.status == "queued",
                AgentWorkerQueue.available_at <= now,
            )
            .order_by(AgentWorkerQueue.priority.asc(), AgentWorkerQueue.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if item is None:
            return None
        call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == item.tool_call_id).with_for_update())
        call_run = (
            self.db.scalar(select(AgentRun).where(AgentRun.run_id == item.run_id).with_for_update())
            if item.run_id is not None
            else None
        )
        if call is None:
            item.status = "failed"
            item.last_error_code = "tool_call_missing"
            item.lease_owner = None
            item.lease_expires_at = None
            self.db.commit()
            return None
        if call is not None and call.run_id != item.run_id:
            self.mark_queue_item_context_mismatch(
                item=item,
                call=call,
                mark_active_call_uncertain=False,
                error_message="Worker queue item run_id does not match ToolCall run_id before worker claim",
            )
            self.db.commit()
            return None
        if call is not None and call.status in {"uncertain", "reconciling"}:
            item.status = "failed"
            item.last_error_code = "tool_call_uncertain_reconcile_required"
            item.lease_owner = None
            item.lease_expires_at = None
            call.error_code = "tool_call_uncertain_reconcile_required"
            call.recovery_decision = "reconcile_required_before_execution"
            _clear_tool_call_lease(call)
            if call_run is not None:
                AgentRuntimeService(self.db).append_event(
                    call_run,
                    "tool.failed",
                    {"tool_call_id": call.tool_call_id, "error_code": call.error_code},
                    commit=False,
                )
            self.db.commit()
            return None
        if call_run is not None and call_run.status in RUN_TERMINAL_STATUSES:
            self._mark_queue_item_obsolete_before_execution(
                item=item,
                call=call,
                run=call_run,
                worker_id=worker_id,
                error_message="Agent run reached a terminal state before worker claim could start tool execution",
            )
            self.db.commit()
            return None
        if call is not None and call.status not in TOOL_CALL_CLAIMABLE_STATUSES:
            item.status = "failed"
            item.last_error_code = "tool_call_not_claimable"
            item.lease_owner = None
            item.lease_expires_at = None
            self.db.commit()
            return None
        if call_run is None:
            item.status = "failed"
            item.last_error_code = "run_missing"
            item.lease_owner = None
            item.lease_expires_at = None
            call.status = "failed"
            call.execution_phase = "blocked"
            call.error_code = "run_missing"
            call.error_message = "Agent run was missing before worker claim could start tool execution"
            call.recovery_decision = "run_context_missing_before_execution"
            call.policy_reason_json = _policy_reason_with_execution_context(call, worker_id=worker_id)
            _clear_tool_call_lease(call)
            self.db.commit()
            return None
        if call is not None and call.approval_required and not call.approved_approval_id:
            item.status = "blocked_approval"
            item.last_error_code = "approval_required_before_execution"
            call.status = "planned"
            call.recovery_decision = "awaiting_approval"
            self.db.commit()
            return None
        item.status = "leased"
        item.lease_owner = worker_id
        item.lease_expires_at = now + timedelta(seconds=lease_seconds)
        item.attempt_count += 1
        if call is not None:
            call.status = "leased"
            call.lease_owner = worker_id
            call.lease_expires_at = item.lease_expires_at
        self.db.commit()
        self.db.refresh(item)
        return item

    def heartbeat(self, *, queue_id: str, worker_id: str, lease_seconds: int = 60) -> AgentWorkerQueue:
        item = self.db.scalar(
            select(AgentWorkerQueue)
            .where(
                AgentWorkerQueue.queue_id == queue_id,
                AgentWorkerQueue.lease_owner == worker_id,
                AgentWorkerQueue.status == "leased",
            )
            .with_for_update()
        )
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent worker queue item 不存在")
        now = _utcnow()
        call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == item.tool_call_id).with_for_update())
        call_run = (
            self.db.scalar(select(AgentRun).where(AgentRun.run_id == item.run_id).with_for_update())
            if item.run_id is not None
            else None
        )
        if call is not None and call.run_id != item.run_id:
            self.mark_queue_item_context_mismatch(
                item=item,
                call=call,
                mark_active_call_uncertain=True,
                error_message="Worker queue item run_id does not match ToolCall run_id during worker heartbeat; reconcile required",
            )
            self.db.commit()
            self.db.refresh(item)
            return item
        if call_run is not None and call_run.status in RUN_TERMINAL_STATUSES:
            self._mark_queue_item_obsolete_before_execution(
                item=item,
                call=call,
                run=call_run,
                worker_id=worker_id,
                error_message="Agent run reached a terminal state before worker heartbeat could extend tool execution",
            )
            self.db.commit()
            self.db.refresh(item)
            return item
        if call is None:
            item.status = "failed"
            item.last_error_code = "tool_call_missing"
            item.lease_owner = None
            item.lease_expires_at = None
            self.db.commit()
            self.db.refresh(item)
            return item
        if call.status == "leased" and (
            call.effect_submission_state in TOOL_CALL_EFFECT_SUBMISSION_STARTED_STATES
            or bool(call.effect_boundary_crossed)
        ):
            self._mark_queue_item_uncertain_after_heartbeat_effect_submission(item=item, call=call)
            self.db.commit()
            self.db.refresh(item)
            return item
        if call.status not in TOOL_CALL_HEARTBEAT_ACTIVE_STATUSES:
            item.status = "failed"
            item.last_error_code = "tool_call_not_active_for_heartbeat"
            item.lease_owner = None
            item.lease_expires_at = None
            self.db.commit()
            self.db.refresh(item)
            return item
        item.lease_expires_at = now + timedelta(seconds=lease_seconds)
        call.last_heartbeat_at = now
        call.lease_expires_at = item.lease_expires_at
        self.db.commit()
        self.db.refresh(item)
        return item

    def recover_orphans(self, *, now: datetime | None = None, limit: int = 100) -> int:
        current = now or _utcnow()
        items = list(self.db.scalars(
            select(AgentWorkerQueue)
            .where(
                AgentWorkerQueue.status == "leased",
                AgentWorkerQueue.lease_expires_at.is_not(None),
                AgentWorkerQueue.lease_expires_at <= current,
            )
            .order_by(AgentWorkerQueue.lease_expires_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all())
        for item in items:
            call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == item.tool_call_id).with_for_update())
            call_run = (
                self.db.scalar(select(AgentRun).where(AgentRun.run_id == item.run_id).with_for_update())
                if item.run_id is not None
                else None
            )
            if call is not None and call.run_id != item.run_id:
                self.mark_queue_item_context_mismatch(
                    item=item,
                    call=call,
                    mark_active_call_uncertain=True,
                    error_message="Worker queue item run_id does not match ToolCall run_id during orphan recovery; reconcile required",
                )
                continue
            if call_run is not None and call_run.status in RUN_TERMINAL_STATUSES:
                lease_owner = item.lease_owner
                self._mark_queue_item_obsolete_before_execution(
                    item=item,
                    call=call,
                    run=call_run,
                    worker_id=lease_owner,
                    error_message="Agent run reached a terminal state before orphaned tool execution could recover",
                )
                continue
            if call is None:
                item.status = "failed"
                item.last_error_code = "tool_call_missing"
                item.lease_owner = None
                item.lease_expires_at = None
                continue
            can_requeue_pre_effect = (
                call.status == "running_pre_effect"
                and call.effect_submission_state in {None, "none"}
                and not call.effect_boundary_crossed
            )
            requires_reconcile_after_effect_submission = (
                call.status in {"leased", "running_pre_effect"}
                and (
                    call.effect_submission_state in TOOL_CALL_EFFECT_SUBMISSION_STARTED_STATES
                    or bool(call.effect_boundary_crossed)
                )
            )
            if requires_reconcile_after_effect_submission:
                self._mark_queue_item_uncertain_after_orphan_effect_submission(item=item, call=call)
                continue
            if call.status != "leased" and not can_requeue_pre_effect:
                item.status = "failed"
                item.last_error_code = "tool_call_not_recoverable_from_orphan"
                item.lease_owner = None
                item.lease_expires_at = None
                continue
            item.status = "queued"
            item.lease_owner = None
            item.lease_expires_at = None
            call.status = "planned"
            call.execution_phase = None
            call.effect_submission_state = "none"
            call.effect_boundary_crossed = False
            call.lease_owner = None
            call.lease_expires_at = None
            call.recovery_decision = "lease_expired_requeued"
        self.db.commit()
        return len(items)

    def mark_queue_item_context_mismatch(
        self,
        *,
        item: AgentWorkerQueue,
        call: AgentToolCall | None,
        mark_active_call_uncertain: bool,
        error_message: str,
    ) -> None:
        error_code = "tool_call_queue_context_mismatch"
        worker_id = item.lease_owner
        item.status = "failed"
        item.last_error_code = error_code
        item.lease_owner = None
        item.lease_expires_at = None
        if call is None or not mark_active_call_uncertain:
            return
        if call.status not in TOOL_CALL_HEARTBEAT_ACTIVE_STATUSES:
            return
        call.status = "uncertain"
        if call.effect_submission_state in {None, "none"}:
            call.effect_submission_state = "unknown"
        call.error_code = error_code
        call.error_message = error_message
        call.recovery_decision = "reconcile_required_after_queue_context_mismatch"
        call.policy_reason_json = _policy_reason_with_execution_context(call, worker_id=worker_id)
        _clear_tool_call_lease(call)

    def _mark_queue_item_uncertain_after_orphan_effect_submission(
        self,
        *,
        item: AgentWorkerQueue,
        call: AgentToolCall,
    ) -> None:
        error_code = "tool_call_orphaned_after_effect_submission_started"
        worker_id = item.lease_owner
        item.status = "failed"
        item.last_error_code = error_code
        item.lease_owner = None
        item.lease_expires_at = None
        call.status = "uncertain"
        if call.effect_submission_state in {None, "none"}:
            call.effect_submission_state = "unknown"
        call.error_code = error_code
        call.error_message = "Tool execution lease expired after effect submission started; reconcile required"
        call.recovery_decision = "reconcile_required_after_orphaned_tool_execution"
        call.policy_reason_json = _policy_reason_with_execution_context(call, worker_id=worker_id)
        _clear_tool_call_lease(call)

    def _mark_queue_item_uncertain_after_heartbeat_effect_submission(
        self,
        *,
        item: AgentWorkerQueue,
        call: AgentToolCall,
    ) -> None:
        error_code = "tool_call_heartbeat_after_effect_submission_started"
        worker_id = item.lease_owner
        item.status = "failed"
        item.last_error_code = error_code
        item.lease_owner = None
        item.lease_expires_at = None
        call.status = "uncertain"
        if call.effect_submission_state in {None, "none"}:
            call.effect_submission_state = "unknown"
        call.error_code = error_code
        call.error_message = "Tool heartbeat found a leased tool after effect submission started; reconcile required"
        call.recovery_decision = "reconcile_required_after_invalid_tool_call_heartbeat"
        call.policy_reason_json = _policy_reason_with_execution_context(call, worker_id=worker_id)
        _clear_tool_call_lease(call)

    def _mark_queue_item_obsolete_before_execution(
        self,
        *,
        item: AgentWorkerQueue,
        call: AgentToolCall | None,
        run: AgentRun,
        worker_id: str | None,
        error_message: str,
    ) -> None:
        error_code = f"agent_run_{run.status}_before_tool_execution"
        item.status = "failed"
        item.last_error_code = error_code
        item.lease_owner = None
        item.lease_expires_at = None
        if call is None or call.status in {"uncertain", "reconciling"}:
            return
        if (
            call.status in {"planned", "leased", "running_pre_effect"}
            and call.effect_submission_state in {None, "none"}
            and not call.effect_boundary_crossed
        ):
            call.status = "obsolete"
            call.execution_phase = "cancelled"
            call.effect_submission_state = "none"
            call.effect_boundary_crossed = False
            call.lease_owner = None
            call.lease_expires_at = None
            call.error_code = error_code
            call.error_message = error_message
            call.recovery_decision = f"run_{run.status}_before_tool_execution"
            call.policy_reason_json = _policy_reason_with_execution_context(call, worker_id=worker_id)

    def mark_completed(self, item: AgentWorkerQueue, *, commit: bool = True) -> None:
        item.status = "completed"
        item.lease_owner = None
        item.lease_expires_at = None
        if commit:
            self.db.commit()

    def mark_failed(self, item: AgentWorkerQueue, *, error_code: str, commit: bool = True) -> None:
        item.status = "failed"
        item.last_error_code = error_code
        item.lease_owner = None
        item.lease_expires_at = None
        if commit:
            self.db.commit()


class AgentToolRuntime:
    def __init__(
        self,
        db: Session,
        *,
        backend_factory: Callable[[Session], AgentToolBackend] = AgentToolBackend,
    ):
        self.db = db
        self.backend_factory = backend_factory

    def execute(self, *, call: AgentToolCall, current_user: User) -> dict[str, Any]:
        payload = dict(call.input_json_redacted or {})
        payload.setdefault("_agent_run_id", call.run_id)
        payload.setdefault("_agent_tool_call_id", call.tool_call_id)
        return self.backend_factory(self.db).execute(
            tool_name=call.tool_name,
            payload=payload,
            current_user=current_user,
        )


class ToolExecutor:
    def __init__(
        self,
        db: Session,
        *,
        runtime_factory: Callable[[Session], AgentRuntimeService] = AgentRuntimeService,
        backend_factory: Callable[[Session], AgentToolBackend] = AgentToolBackend,
        tool_runtime_factory: Callable[..., AgentToolRuntime] = AgentToolRuntime,
    ):
        self.db = db
        self.policy_manager = PolicyManager(db)
        self.runtime_factory = runtime_factory
        self.backend_factory = backend_factory
        self.tool_runtime_factory = tool_runtime_factory

    def execute_next(self, *, worker_id: str) -> AgentToolCall | None:
        queue_item = AgentWorkerQueueService(self.db).claim_next(worker_id=worker_id)
        if queue_item is None:
            return None
        call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == queue_item.tool_call_id))
        if call is None:
            AgentWorkerQueueService(self.db).mark_failed(queue_item, error_code="tool_call_missing")
            return None
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == call.run_id))
        if run is None:
            return self._reject_claimed_tool_call_missing_execution_context(
                call=call,
                queue_item=queue_item,
                error_code="run_missing",
                recovery_decision="run_context_missing_before_execution",
                error_message="Agent run was missing after worker queue claim",
            )
        user = self.db.get(User, run.user_id)
        if user is None:
            return self._reject_claimed_tool_call_missing_execution_context(
                call=call,
                queue_item=queue_item,
                error_code="user_missing",
                recovery_decision="run_user_missing_before_execution",
                error_message="Agent run user was missing after worker queue claim",
            )
        return self.execute_tool_call(call=call, run=run, queue_item=queue_item, current_user=user)

    def _reject_claimed_tool_call_missing_execution_context(
        self,
        *,
        call: AgentToolCall,
        queue_item: AgentWorkerQueue,
        error_code: str,
        recovery_decision: str,
        error_message: str,
    ) -> AgentToolCall:
        worker_id = queue_item.lease_owner or call.lease_owner
        call.status = "failed"
        call.execution_phase = "blocked"
        call.error_code = error_code
        call.error_message = error_message
        call.recovery_decision = recovery_decision
        call.policy_reason_json = _policy_reason_with_execution_context(call, worker_id=worker_id)
        _clear_tool_call_lease(call)
        AgentWorkerQueueService(self.db).mark_failed(queue_item, error_code=error_code, commit=False)
        self.db.commit()
        self.db.refresh(call)
        return call

    @staticmethod
    def _case_update_query_guard_mode(tool_name: str) -> str | None:
        if tool_name in {"testcase.update_assertions", "testcase.batch_update_assertions"}:
            return "http"
        if tool_name in {"websocket_testcase.update_assertions", "websocket_testcase.batch_update_assertions"}:
            return "websocket"
        return None

    @staticmethod
    def _as_int_list(value: Any) -> list[int]:
        if not isinstance(value, list):
            return []
        ids: list[int] = []
        for item in value:
            if isinstance(item, bool):
                continue
            if isinstance(item, int):
                ids.append(item)
            elif isinstance(item, str) and item.strip().isdigit():
                ids.append(int(item.strip()))
        return ids

    @classmethod
    def _case_update_requested_ids(cls, call: AgentToolCall) -> list[int]:
        payload = call.input_json_redacted if isinstance(call.input_json_redacted, dict) else {}
        if call.tool_name in {"testcase.batch_update_assertions", "websocket_testcase.batch_update_assertions"}:
            ids: list[int] = []
            for item in payload.get("items") or []:
                if isinstance(item, dict):
                    ids.extend(cls._as_int_list([item.get("test_case_id")]))
            return ids
        return cls._as_int_list([payload.get("test_case_id")])

    @classmethod
    def _case_ids_from_query_output(cls, output: Any, *, mode: str) -> list[int]:
        if not isinstance(output, dict):
            return []
        if mode == "websocket":
            id_keys = ("websocket_test_case_ids",)
            case_keys = ("websocket_test_cases",)
            batch_keys = (("websocket_batch_execute_input", "websocket_test_case_ids"),)
        else:
            id_keys = ("http_test_case_ids",)
            case_keys = ("http_test_cases",)
            batch_keys = (("http_batch_execute_input", "test_case_ids"),)
        ids: list[int] = []
        for key in id_keys:
            ids.extend(cls._as_int_list(output.get(key)))
        for key in case_keys:
            for item in output.get(key) or []:
                if isinstance(item, dict):
                    ids.extend(cls._as_int_list([item.get("id")]))
        for parent_key, child_key in batch_keys:
            parent = output.get(parent_key)
            if isinstance(parent, dict):
                ids.extend(cls._as_int_list(parent.get(child_key)))
        return sorted(set(ids))

    def _latest_query_project_case_ids(self, *, call: AgentToolCall, mode: str) -> list[int]:
        query = (
            select(AgentToolCall)
            .where(
                AgentToolCall.run_id == call.run_id,
                AgentToolCall.tool_name == "testcase.query_project_cases",
                AgentToolCall.status == "succeeded",
            )
            .order_by(AgentToolCall.id.desc())
        )
        if call.id is not None:
            query = query.where(AgentToolCall.id < call.id)
        query_call = self.db.scalar(query.limit(1))
        if query_call is None:
            return []
        return self._case_ids_from_query_output(query_call.output_json_redacted, mode=mode)

    def _reject_case_update_ids_not_from_prior_query(
        self,
        *,
        call: AgentToolCall,
        run: AgentRun,
        queue_item: AgentWorkerQueue | None,
        queue_service: AgentWorkerQueueService,
        runtime: AgentRuntimeService,
    ) -> AgentToolCall | None:
        mode = self._case_update_query_guard_mode(call.tool_name)
        if mode is None:
            return None
        requested_ids = self._case_update_requested_ids(call)
        if not requested_ids:
            return None
        valid_ids = self._latest_query_project_case_ids(call=call, mode=mode)
        valid_id_set = set(valid_ids)
        invalid_ids = [item for item in requested_ids if item not in valid_id_set]
        if not invalid_ids:
            return None

        invalid_key = "invalid_websocket_test_case_ids" if mode == "websocket" else "invalid_test_case_ids"
        valid_key = "valid_websocket_test_case_ids" if mode == "websocket" else "valid_test_case_ids"
        error_code = (
            "agent_websocket_testcase_ids_not_from_query_result"
            if mode == "websocket"
            else "agent_testcase_ids_not_from_query_result"
        )
        output = {
            "required_tool": "testcase.query_project_cases",
            "blocked_tool": call.tool_name,
            invalid_key: invalid_ids,
            valid_key: valid_ids,
            "next_action": (
                "Call testcase.query_project_cases in this Agent Run and retry using only the ids "
                "returned in its explicit id lists; do not infer ids from numeric ranges."
            ),
        }
        call.status = "failed"
        call.execution_phase = "blocked_by_harness"
        call.error_code = error_code
        call.error_message = "Test case assertion update ids must come from testcase.query_project_cases returned ids."
        call.recovery_decision = "query_project_cases_before_retry"
        call.output_json_redacted = output
        call.output_hash = request_fingerprint(output)
        call.policy_reason_json = _policy_reason_with_execution_context(
            call,
            worker_id=queue_item.lease_owner if queue_item is not None else call.lease_owner,
        )
        _clear_tool_call_lease(call)
        runtime.append_event(
            run,
            "tool.failed",
            {
                "tool_call_id": call.tool_call_id,
                "tool_name": call.tool_name,
                "error_code": error_code,
                invalid_key: invalid_ids,
            },
            commit=False,
        )
        runtime.append_event(
            run,
            "tool.result_observed",
            {
                "tool_call_id": call.tool_call_id,
                "tool_name": call.tool_name,
                "status": "failed",
                "error_code": error_code,
            },
            commit=False,
        )
        if queue_item is not None:
            queue_service.mark_failed(queue_item, error_code=error_code, commit=False)
        self.db.commit()
        self.db.refresh(call)
        return call

    def execute_tool_call(
        self,
        *,
        call: AgentToolCall,
        run: AgentRun,
        queue_item: AgentWorkerQueue | None,
        current_user: User,
    ) -> AgentToolCall:
        runtime = self.runtime_factory(self.db)
        queue_service = AgentWorkerQueueService(self.db)
        self.db.refresh(run)
        if queue_item is not None and (
            queue_item.tool_call_id != call.tool_call_id
            or queue_item.run_id != call.run_id
        ):
            queue_owner_call = call
            if queue_item.tool_call_id != call.tool_call_id:
                queue_owner_call = self.db.scalar(
                    select(AgentToolCall)
                    .where(AgentToolCall.tool_call_id == queue_item.tool_call_id)
                    .with_for_update()
                )
            if queue_item.status not in {"completed", "failed"}:
                queue_service.mark_queue_item_context_mismatch(
                    item=queue_item,
                    call=queue_owner_call,
                    mark_active_call_uncertain=True,
                    error_message=(
                        "Tool executor received a queue item whose run_id/tool_call_id "
                        "does not match the ToolCall; reconcile required"
                    ),
                )
            self.db.commit()
            self.db.refresh(call)
            return call
        if (
            call.status in {"planned", "leased", "running_pre_effect"}
            and (
                call.effect_submission_state in TOOL_CALL_EFFECT_SUBMISSION_STARTED_STATES
                or bool(call.effect_boundary_crossed)
            )
        ):
            return self._mark_tool_uncertain_before_execution_after_effect_submission(
                call=call,
                queue_item=queue_item,
                queue_service=queue_service,
            )
        if call.status not in TOOL_CALL_EXECUTABLE_STATUSES:
            if (
                run.status in RUN_TERMINAL_STATUSES
                and call.status == "running_pre_effect"
                and call.effect_submission_state in {None, "none"}
                and not call.effect_boundary_crossed
            ):
                return self._mark_tool_obsolete_before_execution(
                    call=call,
                    run=run,
                    queue_item=queue_item,
                    queue_service=queue_service,
                )
            return self._reject_tool_call_not_executable(
                call=call,
                queue_item=queue_item,
                queue_service=queue_service,
            )
        if run.status in RUN_TERMINAL_STATUSES:
            return self._mark_tool_obsolete_before_execution(
                call=call,
                run=run,
                queue_item=queue_item,
                queue_service=queue_service,
            )
        try:
            self.policy_manager.ensure_context_allows_execution(call=call)
            self.policy_manager.ensure_approval_allows_execution(call=call)
            self.policy_manager.require_tool_execution_permissions(call=call, run=run, current_user=current_user)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_403_FORBIDDEN:
                call.status = "failed"
                call.execution_phase = "blocked"
                call.error_code = "permission_revoked_before_execution"
                call.error_message = "Execute-time permission check failed"
                call.recovery_decision = "permission_required_before_execution"
                call.policy_reason_json = _policy_reason_with_execution_context(
                    call,
                    worker_id=queue_item.lease_owner if queue_item is not None else call.lease_owner,
                )
                _clear_tool_call_lease(call)
                runtime.append_event(
                    run,
                    "tool.failed",
                    {"tool_call_id": call.tool_call_id, "error_code": call.error_code},
                    commit=False,
                )
                if queue_item is not None:
                    queue_service.mark_failed(queue_item, error_code=call.error_code, commit=False)
                self.db.commit()
                return call
            if exc.status_code == status.HTTP_409_CONFLICT:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                call.status = "manual_intervention"
                call.execution_phase = "blocked"
                call.error_code = str(detail.get("code") or "approval_required_before_execution")
                call.error_message = "Approval guard blocked execution"
                call.recovery_decision = "approval_required_before_execution"
                call.policy_reason_json = _policy_reason_with_execution_context(
                    call,
                    worker_id=queue_item.lease_owner if queue_item is not None else call.lease_owner,
                )
                _clear_tool_call_lease(call)
                runtime.append_event(
                    run,
                    "tool.failed",
                    {"tool_call_id": call.tool_call_id, "error_code": call.error_code},
                    commit=False,
                )
                if queue_item is not None:
                    queue_service.mark_failed(queue_item, error_code=call.error_code, commit=False)
                self.db.commit()
                return call
            raise

        if call.backend_effect_capability is None and call.resolved_side_effect_class not in SAFE_SIDE_EFFECT_CLASSES:
            call.status = "manual_intervention"
            call.execution_phase = "blocked"
            call.error_code = "backend_capability_too_weak"
            call.recovery_decision = "backend_capability_required_before_execution"
            call.policy_reason_json = _policy_reason_with_execution_context(
                call,
                worker_id=queue_item.lease_owner if queue_item is not None else call.lease_owner,
            )
            _clear_tool_call_lease(call)
            runtime.append_event(run, "tool.failed", {"tool_call_id": call.tool_call_id, "error_code": call.error_code}, commit=False)
            if queue_item is not None:
                queue_service.mark_failed(queue_item, error_code=call.error_code, commit=False)
            self.db.commit()
            return call

        blocked_by_case_ids = self._reject_case_update_ids_not_from_prior_query(
            call=call,
            run=run,
            queue_item=queue_item,
            queue_service=queue_service,
            runtime=runtime,
        )
        if blocked_by_case_ids is not None:
            return blocked_by_case_ids

        try:
            now = _utcnow()
            call.status = "running_pre_effect"
            call.execution_phase = "pre_effect"
            runtime.append_event(run, "tool.running", {"tool_call_id": call.tool_call_id, "tool_name": call.tool_name}, commit=False)
            call.effect_submission_state = "send_intent_recorded"
            call.downstream_send_intent_at = now
            runtime.append_event(run, "tool.send_intent_recorded", {"tool_call_id": call.tool_call_id}, commit=False)
            call.effect_submission_state = "transport_sent_observed"
            call.downstream_request_observed_sent_at = _utcnow()
            runtime.append_event(run, "tool.transport_sent_observed", {"tool_call_id": call.tool_call_id}, commit=False)

            output = self.tool_runtime_factory(
                self.db,
                backend_factory=self.backend_factory,
            ).execute(call=call, current_user=current_user)
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES and call.resolved_side_effect_class in SAFE_SIDE_EFFECT_CLASSES:
                return self._mark_safe_tool_obsolete_after_run_terminal(
                    call=call,
                    run=run,
                    queue_item=queue_item,
                    queue_service=queue_service,
                )
            if run.status in RUN_TERMINAL_STATUSES:
                return self._mark_effectful_tool_uncertain_after_run_terminal(
                    call=call,
                    run=run,
                    queue_item=queue_item,
                    queue_service=queue_service,
                    output=output,
                )

            if call.backend_effect_capability == "receipt_first":
                call.effect_submission_state = "backend_accepted"
                call.downstream_acceptance_id = call.idempotency_key
                call.downstream_acceptance_at = _utcnow()
                runtime.append_event(run, "tool.backend_accepted", {"tool_call_id": call.tool_call_id}, commit=False)
            call.effect_submission_state = "effect_committed"
            call.effect_boundary_crossed = call.resolved_side_effect_class not in {"read_only", "deterministic_compute"}
            call.output_json_redacted = mask_sensitive(output)
            call.output_hash = request_fingerprint(output)
            call.status = "succeeded"
            call.execution_phase = "completed"
            call.policy_reason_json = _policy_reason_with_dispatch_trace(call)
            call.policy_reason_json = _policy_reason_with_execution_context(
                call,
                worker_id=queue_item.lease_owner if queue_item is not None else call.lease_owner,
            )
            _clear_tool_call_lease(call)
            try:
                runtime.append_event(run, "tool.effect_committed", {"tool_call_id": call.tool_call_id}, commit=False)
                runtime.append_event(run, "tool.completed", {"tool_call_id": call.tool_call_id, "status": call.status}, commit=False)
            except Exception as exc:  # noqa: BLE001
                return self._mark_eventstore_write_failed_after_effect(call=call, queue_item=queue_item, queue_service=queue_service, exc=exc)
            if queue_item is not None:
                queue_service.mark_completed(queue_item, commit=False)
            self.db.commit()
            self.db.refresh(call)
            return call
        except Exception as exc:  # noqa: BLE001
            call.status = "failed"
            call.error_code = "tool_execution_failed"
            call.error_message = _bounded_agent_error_message(
                exc,
                reference="ToolExecutor.execute_tool_call.tool_execution_failed",
            )
            call.recovery_decision = "tool_execution_failed_repair_required"
            call.policy_reason_json = _policy_reason_with_dispatch_trace(call)
            call.policy_reason_json = _policy_reason_with_execution_context(
                call,
                worker_id=queue_item.lease_owner if queue_item is not None else call.lease_owner,
            )
            _clear_tool_call_lease(call)
            runtime.append_event(
                run,
                "tool.failed",
                {"tool_call_id": call.tool_call_id, "error_code": call.error_code, "error_message": call.error_message},
                commit=False,
            )
            if queue_item is not None:
                queue_service.mark_failed(queue_item, error_code=call.error_code, commit=False)
            self.db.commit()
        self.db.refresh(call)
        return call

    def _mark_tool_uncertain_before_execution_after_effect_submission(
        self,
        *,
        call: AgentToolCall,
        queue_item: AgentWorkerQueue | None,
        queue_service: AgentWorkerQueueService,
    ) -> AgentToolCall:
        error_code = "tool_call_execution_after_effect_submission_started"
        worker_id = queue_item.lease_owner if queue_item is not None else call.lease_owner
        call.status = "uncertain"
        if call.effect_submission_state in {None, "none"}:
            call.effect_submission_state = "unknown"
        call.error_code = error_code
        call.error_message = "Tool executor found a leased tool after effect submission started; reconcile required"
        call.recovery_decision = "reconcile_required_after_invalid_tool_call_execution"
        call.policy_reason_json = _policy_reason_with_execution_context(call, worker_id=worker_id)
        _clear_tool_call_lease(call)
        if queue_item is not None and queue_item.status not in {"completed", "failed"}:
            queue_service.mark_failed(queue_item, error_code=error_code, commit=False)
        self.db.commit()
        self.db.refresh(call)
        return call

    def _reject_tool_call_not_executable(
        self,
        *,
        call: AgentToolCall,
        queue_item: AgentWorkerQueue | None,
        queue_service: AgentWorkerQueueService,
    ) -> AgentToolCall:
        if queue_item is not None and queue_item.status not in {"completed", "failed"}:
            queue_service.mark_failed(queue_item, error_code="tool_call_not_executable", commit=False)
        self.db.commit()
        self.db.refresh(call)
        return call

    def _mark_safe_tool_obsolete_after_run_terminal(
        self,
        *,
        call: AgentToolCall,
        run: AgentRun,
        queue_item: AgentWorkerQueue | None,
        queue_service: AgentWorkerQueueService,
    ) -> AgentToolCall:
        error_code = f"agent_run_{run.status}_during_tool_execution"
        call.status = "obsolete"
        call.execution_phase = "cancelled"
        call.error_code = error_code
        call.error_message = "Agent run reached a terminal state before the safe tool result could be recorded"
        call.recovery_decision = f"run_{run.status}_before_tool_completion"
        call.policy_reason_json = _policy_reason_with_dispatch_trace(call)
        call.policy_reason_json = _policy_reason_with_execution_context(
            call,
            worker_id=queue_item.lease_owner if queue_item is not None else call.lease_owner,
        )
        _clear_tool_call_lease(call)
        if queue_item is not None:
            queue_service.mark_failed(queue_item, error_code=error_code, commit=False)
        self.db.commit()
        self.db.refresh(call)
        return call

    def _mark_tool_obsolete_before_execution(
        self,
        *,
        call: AgentToolCall,
        run: AgentRun,
        queue_item: AgentWorkerQueue | None,
        queue_service: AgentWorkerQueueService,
    ) -> AgentToolCall:
        error_code = f"agent_run_{run.status}_before_tool_execution"
        call.status = "obsolete"
        call.execution_phase = "cancelled"
        call.effect_submission_state = "none"
        call.effect_boundary_crossed = False
        call.error_code = error_code
        call.error_message = "Agent run reached a terminal state before tool execution started"
        call.recovery_decision = f"run_{run.status}_before_tool_execution"
        call.policy_reason_json = _policy_reason_with_execution_context(
            call,
            worker_id=queue_item.lease_owner if queue_item is not None else call.lease_owner,
        )
        _clear_tool_call_lease(call)
        if queue_item is not None:
            queue_service.mark_failed(queue_item, error_code=error_code, commit=False)
        self.db.commit()
        self.db.refresh(call)
        return call

    def _mark_effectful_tool_uncertain_after_run_terminal(
        self,
        *,
        call: AgentToolCall,
        run: AgentRun,
        queue_item: AgentWorkerQueue | None,
        queue_service: AgentWorkerQueueService,
        output: dict[str, Any],
    ) -> AgentToolCall:
        error_code = f"agent_run_{run.status}_after_tool_effect"
        call.status = "uncertain"
        call.execution_phase = "completed"
        call.effect_submission_state = "effect_committed"
        call.effect_boundary_crossed = True
        call.output_json_redacted = mask_sensitive(output)
        call.output_hash = request_fingerprint(output)
        call.error_code = error_code
        call.error_message = "Agent run reached a terminal state after an effectful tool returned; reconcile required"
        call.recovery_decision = "reconcile_required_after_run_terminal"
        call.policy_reason_json = _policy_reason_with_dispatch_trace(call)
        call.policy_reason_json = _policy_reason_with_execution_context(
            call,
            worker_id=queue_item.lease_owner if queue_item is not None else call.lease_owner,
        )
        _clear_tool_call_lease(call)
        if queue_item is not None:
            queue_service.mark_failed(queue_item, error_code=error_code, commit=False)
        self.db.commit()
        self.db.refresh(call)
        return call

    def _mark_eventstore_write_failed_after_effect(
        self,
        *,
        call: AgentToolCall,
        queue_item: AgentWorkerQueue | None,
        queue_service: AgentWorkerQueueService,
        exc: Exception,
    ) -> AgentToolCall:
        call.status = "uncertain"
        call.execution_phase = "completed"
        call.error_code = "eventstore_write_failed_after_effect"
        call.error_message = _bounded_agent_error_message(
            exc,
            reference="ToolExecutor.execute_tool_call.eventstore_write_failed_after_effect",
        )
        call.recovery_decision = "reconcile_required_after_eventstore_failure"
        call.policy_reason_json = _policy_reason_with_dispatch_trace(call)
        call.policy_reason_json = _policy_reason_with_execution_context(
            call,
            worker_id=queue_item.lease_owner if queue_item is not None else call.lease_owner,
        )
        _clear_tool_call_lease(call)
        if queue_item is not None:
            queue_service.mark_failed(queue_item, error_code=call.error_code, commit=False)
        self.db.commit()
        self.db.refresh(call)
        return call


def _clear_tool_call_lease(call: AgentToolCall) -> None:
    call.lease_owner = None
    call.lease_expires_at = None


def _policy_reason_with_dispatch_trace(call: AgentToolCall) -> dict[str, Any]:
    spec = ToolRegistry().get(call.tool_name)
    dispatch_trace = {
        "dispatch_trace_version_hash": "agent-tool-dispatch-v1",
        "tool_call_id": call.tool_call_id,
        "run_id": call.run_id,
        "runtime_snapshot_id": call.runtime_snapshot_id,
        "tool_name": call.tool_name,
        "tool_version": call.tool_version,
        "schema_hash": call.schema_hash,
        "manifest_hash": call.manifest_hash,
        "router": "AgentToolRouter.resolve",
        "runtime": "AgentToolRuntime.execute",
        "backend_handler": spec.backend_handler,
        "backend_name": call.backend_name,
        "backend_operation": call.backend_operation,
        "backend_contract_version": call.backend_contract_version,
        "resolved_side_effect_class": call.resolved_side_effect_class,
        "resolved_replay_policy": call.resolved_replay_policy,
        "status": call.status,
        "effect_submission_state": call.effect_submission_state,
    }
    dispatch_trace["dispatch_trace_hash"] = request_fingerprint(dispatch_trace)
    return {
        **(call.policy_reason_json or {}),
        "dispatch_trace": dispatch_trace,
    }


def _policy_reason_with_execution_context(call: AgentToolCall, *, worker_id: str | None) -> dict[str, Any]:
    execution_context = {
        "execution_context_version_hash": "agent-tool-execution-v1",
        "tool_call_id": call.tool_call_id,
        "run_id": call.run_id,
        "runtime_snapshot_id": call.runtime_snapshot_id,
        "tool_name": call.tool_name,
        "tool_version": call.tool_version,
        "worker_id": worker_id,
        "tool_status": call.status,
        "execution_phase": call.execution_phase,
        "effect_submission_state": call.effect_submission_state,
        "effect_boundary_crossed": bool(call.effect_boundary_crossed),
        "backend_name": call.backend_name,
        "backend_operation": call.backend_operation,
        "backend_contract_version": call.backend_contract_version,
        "backend_request_schema_hash": call.backend_request_schema_hash,
        "backend_output_schema_hash": call.backend_output_schema_hash,
        "reconcile_contract_version": call.reconcile_contract_version,
        "result_adapter_version": call.result_adapter_version,
        "backend_effect_capability": call.backend_effect_capability,
        "resolved_side_effect_class": call.resolved_side_effect_class,
        "resolved_replay_policy": call.resolved_replay_policy,
        "approval_required": bool(call.approval_required),
        "approval_state": _tool_execution_approval_state(call),
        "approval_lineage_id": call.approval_lineage_id,
        "approval_epoch": call.approval_epoch,
        "approved_approval_id": call.approved_approval_id,
        "approved_by": call.approved_by,
        "input_hash": call.input_hash,
        "output_hash": call.output_hash,
        "recovery_decision": call.recovery_decision,
        "error_code": call.error_code,
        "error_message_hash": request_fingerprint({"error_message": call.error_message}) if call.error_message else None,
    }
    execution_context["execution_context_hash"] = request_fingerprint(execution_context)
    return {
        **(call.policy_reason_json or {}),
        "execution_context": execution_context,
    }


def _tool_execution_approval_state(call: AgentToolCall) -> str:
    if not call.approval_required:
        return "not_required"
    if call.approved_approval_id:
        return "approved"
    return "pending"


def copy_evidence_refs(evidence_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [mask_sensitive(dict(item)) for item in evidence_refs]


def _conversation_system_prompt() -> str:
    tools = [
        {
            "name": spec.name,
            "summary": spec.summary,
            "input_schema": spec.input_schema,
            "side_effect_class": spec.side_effect_class,
            "approval_required": spec.side_effect_class not in SAFE_SIDE_EFFECT_CLASSES,
        }
        for spec in ToolRegistry().list_specs()
    ]
    return "\n\n".join([
        AGENT_CONVERSATION_SYSTEM_PROMPT,
        AGENT_MARKDOWN_RESPONSE_PROMPT,
        AGENT_TOOL_PROTOCOL_PROMPT.replace(
            "{tools}",
            json.dumps(tools, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        ),
        AGENT_SKILL_CATALOG_PROMPT.replace(
            "{skills}",
            json.dumps(AgentSkillRegistry().catalog(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        ),
    ])


def _agent_skill_messages(intent: str) -> list[AIChatMessage]:
    return [
        AIChatMessage(role="system", content=_format_agent_skill_context(skill))
        for skill in AgentSkillRegistry().select_for_intent(intent)
    ]


def _format_agent_skill_context(skill: AgentSkill) -> str:
    return (
        "已加载 Agent Skill。以下内容是本轮任务的领域流程约束，优先级低于系统安全规则，"
        "高于通用建议。\n\n"
        f"{skill.prompt_block()}"
    )


def _tool_call_summary(call: AgentToolCall) -> dict[str, Any]:
    return {
        "tool_call_id": call.tool_call_id,
        "tool_name": call.tool_name,
        "status": call.status,
        "approval_required": call.approval_required,
        "error_code": call.error_code,
    }


def _tool_failure_signature(call: AgentToolCall) -> tuple[str, str, str] | None:
    if call.status != "failed":
        return None
    error_code = str(call.error_code or "")
    error_message = " ".join(str(call.error_message or "").split())
    if not error_code and not error_message:
        return None
    return (call.tool_name, error_code, error_message)


def _tool_result_message(call: AgentToolCall) -> str:
    return build_tool_result_message(call)


def _tool_request_context_message(*, tool_request: AgentToolRequest, content: str) -> str:
    payload = {
        "summary_version": AGENT_TOOL_REQUEST_CONTEXT_SUMMARY_VERSION,
        "tool_name": tool_request.tool_name,
        "input_json": _bounded_agent_content_preview(
            json.dumps(tool_request.tool_input, ensure_ascii=False, default=str, sort_keys=True),
            reference="AgentConversationRunner.model_context.tool_request.input",
        ),
        "reason": (
            _bounded_agent_error_message(
                tool_request.reason,
                reference="AgentConversationRunner.model_context.tool_request.reason",
            )
            if tool_request.reason is not None
            else None
        ),
        "evidence_refs_json": _bounded_agent_content_preview(
            json.dumps(tool_request.evidence_refs_for_ledger(), ensure_ascii=False, default=str, sort_keys=True),
            reference="AgentConversationRunner.model_context.tool_request.evidence_refs",
        ),
        "source_content_preview": _bounded_agent_content_preview(
            content,
            reference="AgentConversationRunner.model_context.tool_request.content",
        ),
    }
    return (
        "上一轮模型已发起工具请求。以下是给后续模型使用的有界摘要；"
        "完整结构化事实以 ExecutionLedger/ToolCall 为准。\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)}"
    )


def _tool_result_context_messages(calls: list[AgentToolCall]) -> list[AIChatMessage]:
    messages: list[AIChatMessage] = []
    for call in calls:
        _append_tool_result_context_message(messages, call)
    return messages


def _append_tool_result_context_message(messages: list[AIChatMessage], call: AgentToolCall) -> None:
    if any(AGENT_TOOL_RESULT_CONTEXT_TRUNCATION_MARKER in (message.content or "") for message in messages):
        return
    used_chars = sum(
        len(message.content or "")
        for message in messages
        if _is_tool_result_context_message(message)
    )
    remaining_chars = AGENT_TOOL_RESULT_CONTEXT_TOTAL_MAX_CHARS - used_chars
    if remaining_chars <= 0:
        return
    content = _cap_tool_result_context_message(_tool_result_message(call), remaining_chars)
    messages.append(AIChatMessage(role="user", content=content))


def _is_tool_result_context_message(message: AIChatMessage) -> bool:
    content = message.content or ""
    return (
        content.startswith("工具执行结果如下")
        or AGENT_TOOL_RESULT_CONTEXT_TRUNCATION_MARKER in content
    )


def _cap_tool_result_context_message(message: str, max_chars: int) -> str:
    if len(message) <= max_chars:
        return message
    marker = AGENT_TOOL_RESULT_CONTEXT_TRUNCATION_MARKER
    prefix_length = max(0, max_chars - len(marker))
    return f"{message[:prefix_length]}{marker}"


def _format_memory_context(candidates: list[MemoryCandidate]) -> str:
    lines = [
        "项目记忆上下文（用于辅助理解当前请求，不等同于实时证据；涉及高风险工具或副作用时仍需 EvidenceRef/审批/工具结果确认）："
    ]
    for index, candidate in enumerate(candidates, start=1):
        title = _truncate_memory_context_text(candidate.title, AGENT_MEMORY_CONTEXT_TITLE_MAX_CHARS)
        content = _truncate_memory_context_text(candidate.content, AGENT_MEMORY_CONTEXT_CONTENT_MAX_CHARS)
        lines.append(
            (
                f"{index}. memory_id={candidate.memory_id}, version={candidate.memory_version}, "
                f"profile={candidate.retrieval_profile}, score={candidate.retrieval_score:.4f}, "
                f"confidence={candidate.confidence:.2f}, stale_score={candidate.stale_score:.2f}, "
                f"title={title}\n"
                f"   content={content}"
            )
        )
    return _cap_memory_context_message("\n".join(lines))


def _format_run_context(run: AgentRun) -> str:
    return (
        "当前 Agent Run 上下文：\n"
        f"- run_id={run.run_id}\n"
        f"- project_id={run.project_id}\n"
        f"- conversation_id={run.conversation_id or ''}\n"
        f"- max_iterations={run.max_iterations}\n"
        "回答能力规则：软件测试相关的通用问答、解释和建议可以直接回答；"
        "超出软件测试领域的问题需要说明能力边界；"
        "只有需要项目实时事实、真实资源、草稿生成、保存动作或平台副作用时才调用工具。\n"
        "工具调用规则：如果工具 input schema 需要 project_id，直接使用当前 project_id，"
        "不要向用户反问 project_id。具体业务流程、工具顺序和输出边界以本轮加载的 Agent Skill 为准。"
        "如缺少 environment_id 或其他平台事实，可先调用只读工具获取上下文。"
    )


def _intent_likely_requires_agent_tool(intent: str) -> bool:
    return _intent_matches_selected_skill_private_list(intent, REQUIRES_TOOL_ROUTING_KEY)


def _unsupported_capability_guards_for_intent(intent: str) -> tuple[UnsupportedCapabilityGuard, ...]:
    registry = AgentSkillRegistry()
    guards: list[UnsupportedCapabilityGuard] = []
    for skill in registry.select_for_intent(intent):
        for raw_rule in registry.private_list(skill.name, UNSUPPORTED_CAPABILITY_GUARD_KEY):
            guard = _parse_unsupported_capability_guard(skill.name, raw_rule)
            if guard is not None and _intent_matches_unsupported_capability_guard(intent, guard, registry=registry):
                guards.append(guard)
    return tuple(guards)


def _parse_unsupported_capability_guard(skill_name: str, raw_rule: str) -> UnsupportedCapabilityGuard | None:
    fields = _parse_semicolon_fields(raw_rule)
    name = fields.get("name")
    intent_key = fields.get("intent")
    subject_key = fields.get("subject")
    classifier_prompt_key = fields.get("classifier_prompt")
    requires_field = fields.get("requires_field")
    completion_source = fields.get("completion_source")
    message_key = fields.get("message")
    if not all((name, intent_key, subject_key, classifier_prompt_key, requires_field, completion_source, message_key)):
        return None
    unavailable_tools = tuple(
        item.strip()
        for item in fields.get("unavailable_tools", "").split(",")
        if item.strip()
    )
    return UnsupportedCapabilityGuard(
        skill_name=skill_name,
        name=name,
        intent_key=intent_key,
        subject_key=subject_key,
        unavailable_tools=unavailable_tools,
        classifier_prompt_key=classifier_prompt_key,
        requires_field=requires_field,
        completion_source=completion_source,
        message_key=message_key,
        synthetic_reason=fields.get("reason") or f"unsupported_{name}",
    )


def _intent_matches_unsupported_capability_guard(
    intent: str,
    guard: UnsupportedCapabilityGuard,
    *,
    registry: AgentSkillRegistry | None = None,
) -> bool:
    text = (intent or "").casefold()
    if not text:
        return False
    registry = registry or AgentSkillRegistry()
    intent_keywords = registry.private_list(guard.skill_name, guard.intent_key)
    subject_keywords = registry.private_list(guard.skill_name, guard.subject_key)
    if not any(keyword.casefold() in text for keyword in intent_keywords):
        return False
    explicit_subject_keywords = tuple(
        keyword
        for keyword in subject_keywords
        if keyword.casefold() not in {item.casefold() for item in AMBIGUOUS_DEICTIC_GUARD_SUBJECTS}
    )
    return any(keyword.casefold() in text for keyword in explicit_subject_keywords)


def _unsupported_capability_classifier_prompt(guard: UnsupportedCapabilityGuard) -> str | None:
    prompt = AgentSkillRegistry().private_resource_text(guard.skill_name, guard.classifier_prompt_key)
    if prompt is None:
        return None
    return _cap_unsupported_capability_classifier_prompt(prompt)


def _unsupported_capability_message(guard: UnsupportedCapabilityGuard) -> str | None:
    return AgentSkillRegistry().private_resource_text(guard.skill_name, guard.message_key)


def _required_tool_followup_rules_for_intent(intent: str) -> tuple[RequiredToolFollowupRule, ...]:
    registry = AgentSkillRegistry()
    text = (intent or "").casefold()
    rules: list[RequiredToolFollowupRule] = []
    for skill in registry.select_for_intent(intent):
        for raw_rule in registry.private_list(skill.name, REQUIRED_TOOL_AFTER_SUCCESS_ROUTING_KEY):
            rule = _parse_required_tool_followup_rule(raw_rule)
            if rule is not None and _required_tool_followup_rule_matches_intent(rule, text):
                rules.append(rule)
    return tuple(rules)


def _parse_required_tool_followup_rule(raw_rule: str) -> RequiredToolFollowupRule | None:
    fields = _parse_semicolon_fields(raw_rule)
    after_tool = fields.get("after")
    required_tool = fields.get("require")
    if not after_tool or not required_tool:
        return None
    min_total_fields = tuple(
        field.strip()
        for field in fields.get("min_total_fields", "").split(",")
        if field.strip()
    )
    return RequiredToolFollowupRule(
        after_tool=after_tool,
        required_tool=required_tool,
        min_total_fields=min_total_fields,
        intent_markers=tuple(
            marker.strip()
            for marker in fields.get("intent_markers", "").split(",")
            if marker.strip()
        ),
    )


def _required_tool_followup_rule_matches_intent(rule: RequiredToolFollowupRule, text: str) -> bool:
    if not rule.intent_markers:
        return True
    return any(marker.casefold() in text for marker in rule.intent_markers)


def _parse_semicolon_fields(raw_rule: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in raw_rule.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def _tool_output_min_total_satisfied(output: Any, field_names: tuple[str, ...]) -> bool:
    if not isinstance(output, dict):
        return True
    total = 0
    for field_name in field_names:
        try:
            total += int(output.get(field_name) or 0)
        except (TypeError, ValueError):
            continue
    return total > 0


def _intent_matches_selected_skill_private_list(intent: str, key: str) -> bool:
    text = (intent or "").casefold()
    if not text:
        return False
    registry = AgentSkillRegistry()
    for skill in registry.list_skills():
        values = registry.private_list(skill.name, key)
        if any(value.casefold() in text for value in values):
            return True
    return False


def _loop_iteration_id(*, run: AgentRun, iteration: int) -> str:
    return f"{run.run_id}:iter-{iteration}"


def _new_model_call_id(*, run: AgentRun, iteration: int, loop_step: str) -> str:
    return f"{run.run_id}:model-{iteration}-{loop_step}-{uuid.uuid4().hex}"


def _model_response_item_id(*, run: AgentRun, model_call_id: str) -> str:
    return f"{AGENT_MODEL_RESPONSE_ITEM_ID_PREFIX}://{run.run_id}/{model_call_id}"


def _tool_call_item_ids(*, run_id: str, tool_call_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(
        f"{AGENT_TOOL_CALL_ITEM_ID_PREFIX}://{run_id}/{tool_call_id}"
        for tool_call_id in tool_call_ids
    ))


def _migration_block_item_ids(*, run_id: str, block_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(
        f"{AGENT_MIGRATION_BLOCK_ITEM_ID_PREFIX}://{run_id}/{block_id}"
        for block_id in block_ids
    ))


def _loop_trace_payload(
    *,
    run: AgentRun,
    iteration: int,
    loop_step: str,
    model_call_id: str | None = None,
    tool_call_id: str | None = None,
    decision_reason: str | None = None,
) -> dict[str, Any]:
    iteration_id = _loop_iteration_id(run=run, iteration=iteration)
    phase = "tool" if tool_call_id and not model_call_id else "model"
    loop_state: dict[str, Any] = {
        "iteration": iteration,
        "iteration_id": iteration_id,
        "phase": phase,
        "step": loop_step,
    }
    payload: dict[str, Any] = {
        "iteration_id": iteration_id,
        "loop_step": loop_step,
        "loop_state": loop_state,
    }
    if model_call_id:
        payload["model_call_id"] = model_call_id
        payload["model_response_item_id"] = _model_response_item_id(
            run=run,
            model_call_id=model_call_id,
        )
        loop_state["model_call_id"] = model_call_id
    if tool_call_id:
        payload["tool_call_id"] = tool_call_id
        loop_state["tool_call_id"] = tool_call_id
    if decision_reason:
        payload["decision_reason"] = decision_reason
        loop_state["decision_reason"] = decision_reason
    return payload


def _model_trace_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload[key]
        for key in (
            "iteration_id",
            "model_call_id",
            "model_response_item_id",
            "loop_step",
            "loop_state",
        )
        if key in payload
    }


def _default_model_loop_step(
    *,
    final_summary: bool,
    repair_attempt: bool,
    suppress_visible_deltas: bool,
) -> str:
    if final_summary:
        return "final_summary"
    if repair_attempt:
        return "tool_request_repair"
    if suppress_visible_deltas:
        return "tool_planning"
    return "assistant_response"


def _should_hold_for_tool_request_detection(content: str) -> bool:
    stripped = content.lstrip()
    if not stripped:
        return True
    if "```agent_tool_request".startswith(stripped):
        return True
    if stripped.startswith("```agent_tool_request"):
        return True
    if "{".startswith(stripped) or stripped.startswith("{"):
        return True
    return False


def _looks_like_tool_request_content(content: str) -> bool:
    stripped = content.strip()
    return "```agent_tool_request" in stripped or (
        stripped.startswith("{")
        and stripped.endswith("}")
        and '"tool_name"' in stripped
    )


def _looks_like_internal_tool_context_leak(content: str) -> bool:
    return AGENT_TOOL_REQUEST_CONTEXT_SUMMARY_VERSION in (content or "")


def _normalize_agent_markdown_response(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = _normalize_inline_markdown_tables(normalized)
    normalized = _close_unclosed_markdown_fence(normalized)
    return "\n".join(line.rstrip() for line in normalized.splitlines()).strip()


def _normalize_inline_markdown_tables(content: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            lines.append(line.rstrip())
            in_fence = not in_fence
            continue
        if in_fence:
            lines.append(line.rstrip())
            continue
        normalized_table = _normalize_inline_markdown_table_line(line)
        if normalized_table is not None:
            lines.extend(normalized_table.split("\n"))
        else:
            lines.append(line.rstrip())
    return "\n".join(lines)


def _normalize_inline_markdown_table_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("|") or "----" not in stripped:
        return None
    cells = [cell.strip() for cell in stripped.split("|")]
    separator_start = -1
    separator_end = -1
    for index, cell in enumerate(cells):
        if not MARKDOWN_TABLE_SEPARATOR_CELL_RE.fullmatch(cell):
            continue
        end = index
        while end < len(cells) and MARKDOWN_TABLE_SEPARATOR_CELL_RE.fullmatch(cells[end]):
            end += 1
        if end - index >= 2:
            separator_start = index
            separator_end = end
            break
    if separator_start < 0:
        return None

    column_count = separator_end - separator_start
    before_separator = [cell for cell in cells[:separator_start] if cell]
    if len(before_separator) != column_count:
        return None
    after_separator = [cell for cell in cells[separator_end:] if cell]
    if after_separator and len(after_separator) % column_count != 0:
        return None

    header = before_separator
    separator = cells[separator_start:separator_end]
    rows = [
        after_separator[index:index + column_count]
        for index in range(0, len(after_separator), column_count)
    ]
    return "\n".join(
        [
            _format_markdown_table_row(header),
            _format_markdown_table_separator(separator),
            *[_format_markdown_table_row(row) for row in rows],
        ]
    )


def _format_markdown_table_row(cells: list[str]) -> str:
    normalized_cells = [_normalize_markdown_table_cell(cell) for cell in cells]
    return "| " + " | ".join(normalized_cells) + " |"


def _format_markdown_table_separator(cells: list[str]) -> str:
    normalized_cells = []
    for cell in cells:
        left_aligned = cell.startswith(":")
        right_aligned = cell.endswith(":")
        if left_aligned and right_aligned:
            normalized_cells.append(":---:")
        elif left_aligned:
            normalized_cells.append(":---")
        elif right_aligned:
            normalized_cells.append("---:")
        else:
            normalized_cells.append("---")
    return "| " + " | ".join(normalized_cells) + " |"


def _normalize_markdown_table_cell(cell: str) -> str:
    normalized = " ".join(cell.split())
    return normalized if normalized else "-"


def _close_unclosed_markdown_fence(content: str) -> str:
    fence_count = sum(1 for line in content.splitlines() if line.strip().startswith("```"))
    if fence_count % 2 == 0:
        return content
    return f"{content}\n```"


def _assistant_message_from_run(run: AgentRun) -> str | None:
    if not isinstance(run.result_json, dict):
        return None
    if run.result_json.get("assistant_visible") is False:
        return None
    message = run.result_json.get("message")
    if isinstance(message, str) and message.strip():
        return message
    return None


def _history_pairs_to_messages(
    pairs: list[dict[str, Any]],
    *,
    user_chars: int | None = None,
    assistant_chars: int | None = None,
) -> list[AIChatMessage]:
    messages: list[AIChatMessage] = []
    for pair in pairs:
        user_content = str(pair.get("intent") or "")
        assistant_content = str(pair.get("assistant") or "")
        if user_chars is not None:
            user_content = _truncate_history_text(user_content, user_chars)
        if assistant_chars is not None:
            assistant_content = _truncate_history_text(assistant_content, assistant_chars)
        messages.append(AIChatMessage(role="user", content=user_content))
        if assistant_content.strip():
            messages.append(AIChatMessage(role="assistant", content=assistant_content))
    return messages


def _conversation_working_context(
    *,
    current_intent: str,
    previous_runs: list[AgentRun],
) -> dict[str, Any] | None:
    if not previous_runs:
        return None
    recent_runs = previous_runs[-AGENT_HISTORY_CONTEXT_FULL_TURNS:]
    turns = []
    artifacts = []
    for run in recent_runs:
        assistant = _assistant_message_from_run(run) or ""
        turn = {
            "run_id": run.run_id,
            "user_intent": _truncate_history_text(run.intent, AGENT_HISTORY_CONTEXT_RECENT_USER_CHARS),
            "assistant_message": _truncate_history_text(assistant, AGENT_HISTORY_CONTEXT_SUMMARY_CHARS),
        }
        inferred = _infer_working_artifact(run.intent, assistant)
        if inferred is not None:
            turn["inferred_artifact"] = inferred
            artifacts.append({"source_run_id": run.run_id, **inferred})
        turns.append(turn)
    payload: dict[str, Any] = {
        "schema_version": "conversation_working_context_v1",
        "current_intent": current_intent,
        "current_intent_is_deictic_followup": _intent_is_deictic_followup(current_intent),
        "recent_turns": turns,
        "current_artifact_candidates": artifacts[-3:],
        "resolution_rules": [
            "If current_intent_is_deictic_followup is true, resolve it against current_artifact_candidates before choosing tools.",
            "Prefer the latest artifact whose domain matches the user's last concrete request.",
            "If the referenced artifact cannot be identified, ask a short clarification instead of guessing.",
            "High-risk writes still require the matching approved tool and human approval.",
        ],
    }
    return payload


def _format_conversation_working_context(payload: dict[str, Any]) -> str:
    return (
        "同一会话工作上下文：\n"
        "当前用户请求可能是对上一轮产物的省略回指；请先依据此结构化上下文解析“直接、刚才、上面、这个”等指代，"
        "再决定是否调用工具、调用哪个工具、是否需要审批。\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)}"
    )


def _intent_is_deictic_followup(intent: str) -> bool:
    text = (intent or "").casefold()
    if not text:
        return False
    markers = (
        "直接",
        "刚才",
        "上面",
        "前面",
        "这个",
        "这些",
        "继续",
        "按这个",
        "就这样",
        "this",
        "that",
        "above",
        "previous",
        "continue",
    )
    return any(marker.casefold() in text for marker in markers)


def _infer_working_artifact(user_intent: str, assistant_message: str) -> dict[str, Any] | None:
    text = f"{user_intent}\n{assistant_message}".casefold()
    if not text.strip():
        return None
    artifact_type: str | None = None
    domain: str | None = None
    if "断言" in text or "assertion" in text:
        artifact_type = "testcase_assertion_draft"
        domain = "testcase_assertions"
    elif "提取器" in text or "extractor" in text:
        artifact_type = "testcase_extractor_draft"
        domain = "testcase_extractors"
    elif "场景" in text or "scenario" in text:
        artifact_type = "scenario_draft"
        domain = "scenario"
    elif "测试用例" in text or "test case" in text or "testcase" in text:
        artifact_type = "testcase_draft"
        domain = "testcase"
    if artifact_type is None:
        return None
    status_value = "unknown"
    if "尚未保存" in text or "未保存" in text or "草稿" in text or "draft" in text:
        status_value = "draft_unsaved"
    elif "已保存" in text or "保存成功" in text:
        status_value = "saved"
    actions = []
    if "保存" in text or "save" in text:
        actions.append("save")
    if "审批" in text or "approval" in text:
        actions.append("requires_approval")
    return {
        "artifact_type": artifact_type,
        "domain": domain,
        "status": status_value,
        "available_followup_actions": actions,
        "summary": _truncate_history_text(assistant_message or user_intent, AGENT_HISTORY_CONTEXT_SUMMARY_CHARS),
    }


def _compact_history_summary(pairs: list[dict[str, Any]]) -> str:
    lines = [
        "Conversation history compacted for prompt budget.",
        "Older turns are summarized; use recent full turns and current user request as the strongest context.",
    ]
    for index, pair in enumerate(pairs, start=1):
        intent = _truncate_history_text(str(pair.get("intent") or ""), AGENT_HISTORY_CONTEXT_SUMMARY_CHARS)
        assistant = _truncate_history_text(str(pair.get("assistant") or ""), AGENT_HISTORY_CONTEXT_SUMMARY_CHARS)
        line = f"{index}. run_id={pair.get('run_id')}, status={pair.get('status')}, user={intent}"
        if assistant:
            line = f"{line}; assistant={assistant}"
        lines.append(line)
    return "\n".join(lines)


def _estimate_chat_messages_tokens(messages: list[AIChatMessage]) -> int:
    total_chars = sum(len(message.content or "") for message in messages)
    return max(1, total_chars // 4)


def _truncate_history_text(value: str, max_chars: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max(0, max_chars - 3)]}..."


def _truncate_memory_context_text(value: str, max_chars: int) -> str:
    normalized = " ".join((value or "").split())
    if len(normalized) <= max_chars:
        return normalized
    marker = f"... {AGENT_MEMORY_CONTEXT_TRUNCATION_MARKER}"
    prefix_length = max(0, max_chars - len(marker))
    return f"{normalized[:prefix_length]}{marker}"


def _cap_memory_context_message(value: str) -> str:
    if len(value) <= AGENT_MEMORY_CONTEXT_MESSAGE_MAX_CHARS:
        return value
    marker = f"\n\n{AGENT_MEMORY_CONTEXT_TRUNCATION_MARKER}"
    prefix_length = max(0, AGENT_MEMORY_CONTEXT_MESSAGE_MAX_CHARS - len(marker))
    return f"{value[:prefix_length]}{marker}"


def _cap_unsupported_capability_classifier_prompt(value: str) -> str:
    if len(value) <= AGENT_UNSUPPORTED_CAPABILITY_CLASSIFIER_PROMPT_MAX_CHARS:
        return value
    marker = AGENT_UNSUPPORTED_CAPABILITY_CLASSIFIER_PROMPT_TRUNCATION_MARKER
    prefix_length = max(0, AGENT_UNSUPPORTED_CAPABILITY_CLASSIFIER_PROMPT_MAX_CHARS - len(marker))
    return f"{value[:prefix_length]}{marker}"


def _bounded_repair_context(value: str) -> str:
    text = value or ""
    if len(text) <= AGENT_REPAIR_CONTEXT_MAX_CHARS:
        return text
    marker = AGENT_REPAIR_CONTEXT_TRUNCATION_MARKER
    prefix_length = max(0, AGENT_REPAIR_CONTEXT_MAX_CHARS - len(marker))
    return f"{text[:prefix_length]}{marker}"


def _bounded_agent_content_preview(content: Any, *, reference: str) -> str:
    text = str(content or "")
    if len(text) <= AGENT_CONTENT_PREVIEW_MAX_CHARS:
        return text
    suffix = (
        f"{AGENT_CONTENT_PREVIEW_TRUNCATION_MARKER} "
        f"content_summary_version={AGENT_CONTENT_PREVIEW_SUMMARY_VERSION} "
        f"content_size_chars={len(text)} "
        f"content_hash={request_fingerprint({'content': text})} "
        f"full_content_reference={reference}"
    )
    preview_max_chars = max(0, AGENT_CONTENT_PREVIEW_MAX_CHARS - len(suffix))
    return f"{text[:preview_max_chars]}{suffix}"


def _http_exception_detail(exc: HTTPException) -> str:
    if isinstance(exc.detail, str):
        return exc.detail
    return json.dumps(exc.detail, ensure_ascii=False, default=str)


def _bounded_agent_error_message(error: Any, *, reference: str) -> str:
    message = str(error or "")
    if len(message) <= AGENT_ERROR_MESSAGE_MAX_CHARS:
        return message
    suffix = (
        f"{AGENT_ERROR_MESSAGE_TRUNCATION_MARKER} "
        f"error_summary_version={AGENT_ERROR_MESSAGE_SUMMARY_VERSION} "
        f"error_size_chars={len(message)} "
        f"error_hash={request_fingerprint({'error_message': message})} "
        f"full_error_reference={reference}"
    )
    preview_max_chars = max(0, AGENT_ERROR_MESSAGE_MAX_CHARS - len(suffix))
    return f"{message[:preview_max_chars]}{suffix}"


def _bounded_run_failure_error_message(error: Any, *, error_code: str) -> str:
    return _bounded_agent_error_message(
        error,
        reference=f"AgentRuntimeService.fail_run.{error_code}",
    )


def _conversation_title(intent: str) -> str:
    normalized = " ".join(intent.split())
    return normalized[:60] if normalized else "未命名会话"


def _activity_idle_seconds(last_activity_at: datetime) -> float:
    utc_idle = (_utcnow() - last_activity_at).total_seconds()
    local_idle = (datetime.now().replace(tzinfo=None) - last_activity_at).total_seconds()
    non_negative_candidates = [value for value in (utc_idle, local_idle) if value >= 0]
    if non_negative_candidates:
        return min(non_negative_candidates)
    return max(utc_idle, local_idle)


def _agent_context_compaction_object_key(*, run_id: str, event_seq: int) -> str:
    return f"{AGENT_CONTEXT_COMPACTION_OBJECT_KEY_PREFIX}://{run_id}/{event_seq}"


def _agent_context_compaction_item_id(*, event: AgentEvent) -> str:
    return f"{AGENT_CONTEXT_COMPACTION_ITEM_ID_PREFIX}://{event.run_id}/{event.event_seq}"


def _agent_context_compaction_window_scope_id(*, run: AgentRun) -> str:
    return request_fingerprint({
        "project_id": run.project_id,
        "conversation_id": run.conversation_id or run.run_id,
    })[:16]


def _agent_context_compaction_window_id(*, scope_id: str, window_number: int) -> str:
    return f"{AGENT_HISTORY_COMPACTION_WINDOW_ID_PREFIX}://{scope_id}/{window_number}"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
