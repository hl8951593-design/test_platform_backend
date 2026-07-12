from __future__ import annotations

import copy
import json
import logging
import math
import re
import time
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Sequence

from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import ProjectPermission
from app.core.sensitive_data import decrypt_sensitive, encrypt_sensitive, mask_sensitive, request_fingerprint
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
from app.models.defect import Defect
from app.models.project import ProjectEnvironment
from app.models.scenario import TestScenario
from app.models.test_case import TestCase
from app.models.test_plan import TestPlan, TestPlanRun
from app.models.user import User
from app.models.visual_flow import VisualFlow
from app.models.websocket_test_case import WebSocketTestCase
from app.schemas.ai import (
    AIChatMessage,
    AIChatRequest,
    AIChatToolCall,
    AIChatToolCallFunction,
)
from app.schemas.agent import (
    AgentContextBuildCreateRequest,
    AgentLoopObservationCreateRequest,
    AgentRunCreateRequest,
    AgentToolCallCreateRequest,
)
from app.schemas.defect import DefectCreateRequest, DefectUpdateRequest
from app.schemas.scenario import ScenarioCreateRequest, ScenarioUpdateRequest
from app.schemas.test_case import AssertionConfig, TestCaseCreateRequest, TestCaseUpdateRequest
from app.schemas.test_plan import TestPlanCreateRequest, TestPlanUpdateRequest
from app.schemas.visual_flow import FlowCreateRequest, FlowDefinition, FlowUpdateRequest
from app.schemas.websocket_test_case import (
    WebSocketAssertionConfig,
    WebSocketTestCaseCreateRequest,
    WebSocketTestCaseUpdateRequest,
)
from app.services.agent_approval_service import ApprovalService, PolicyManager
from app.services.agent_artifact_resolver import (
    AgentArtifactResolver,
)
from app.services.agent_capability_plan_service import (
    AgentCapabilityPlanService,
    CapabilityPlanError,
    CapabilityPlanNotActive,
    CapabilityPlanToolNotAllowed,
    tool_matches_intent_decision,
)
from app.services.agent_context_manager import AgentContextManager, MODEL_PRIVATE_TOOL_NAMES
from app.services.agent_execution_plan import agent_execution_plan_id, agent_execution_plan_payload
from app.services.agent_loop_service import ContextBuilder, EvidenceRefResolver, EvidenceWatchService, LoopController
from app.services.agent_native_tool_call import (
    RUNTIME_REQUEST_CAPABILITY_ALIAS,
    NativeCapabilityRequest,
    NativeToolCallAccumulator,
    NativeToolCallError,
    build_native_tool_definitions,
)
from app.services.agent_intent_action import parse_agent_intent_action
from app.services.agent_intent_decision_service import (
    AgentIntentDecisionError,
    AgentIntentDecisionService,
    ValidatedAgentIntentDecision,
)
from app.services.agent_planning_service import (
    AgentPlanningDecisionService,
    AgentPlanningError,
    AgentPlanningFailed,
    ValidatedAgentPlanningDecision,
)
from app.services.agent_memory_service import MemoryCandidate, MemoryManager
from app.services.agent_skill_registry import (
    AgentSkill,
    AgentSkillRegistry,
    intent_matches_routing_phrase,
)
from app.services.agent_trace import (
    trace_debug,
    trace_error,
    trace_full_payload,
    trace_info,
    trace_message_summary,
    trace_payload_summary,
    trace_verbose_payload,
    trace_warning,
)
from app.services.agent_tool_result_policy import FINAL_RESPONSE_BUDGET_INSTRUCTION, build_tool_result_message
from app.services.ai_service import AIService
from app.services.agent_tool_service import AgentToolBackend, SAFE_SIDE_EFFECT_CLASSES, ToolContextRequirement, ToolPolicyResolver, ToolRegistry
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
AGENT_FINAL_SUMMARY_TOOL_REQUEST_SUPPRESSED_MESSAGE = (
    "工具执行结果已经进入上下文，但最终总结阶段模型又输出了工具请求。"
    "后端已阻止该工具请求展示给用户；请查看上方 ToolCall 失败详情，修正输入后重新提交。"
)
AGENT_FINAL_SUMMARY_TOOL_REQUEST_SUPPRESSED_SUCCESS_MESSAGE = (
    "工具已成功执行完成，但最终总结阶段模型又输出了工具请求。"
    "后端已阻止重复工具请求展示给用户；本次运行已按已完成工具结果结束。"
)
AGENT_INTERNAL_TOOL_CONTEXT_LEAK_MESSAGE = (
    "工具执行已完成，但模型返回了仅供内部循环使用的工具上下文摘要；后端已阻止该摘要展示给用户。"
)
AGENT_EMPTY_MODEL_RESPONSE_FALLBACK = (
    "模型本轮没有返回任何可展示内容，后端已阻止空回复作为成功结果展示。"
    "请稍后重试，或缩小请求范围后重新提交。"
)

AGENT_CAPABILITY_DENIAL_GUARD_MESSAGE = (
    "检测到能力路由不一致：模型刚才声称平台不支持该操作，但当前运行时工具目录中存在对应能力。"
    "我已阻止这条错误结论直接完成。本轮应按已召回的 Skill/Tool 重新规划，或由后端继续检查路由裁剪。"
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
AGENT_BUSINESS_OBJECT_DISPLAY_PROMPT = """
面向用户总结平台对象时，优先使用业务名称而不是只输出内部 ID：
- 测试用例、WebSocket 用例、场景、计划、报告、缺陷、环境、执行记录等对象，如果工具结果同时提供 id 和 name/title/resource_name，必须展示为“名称（ID: 7）”或表格列“名称 / ID”，不要只写“用例 ID：7, 8, 10”。
- 用例相关表格应优先包含“用例名称”“方法”“路径”“状态/问题”“ID”列；ID 只作为定位和后续工具输入，不作为用户理解结果的主要描述。
- 当工具结果提供 `case_display_rows`、`case_attention_rows` 或 `object_reference_manifest.object_references` 时，用例名称必须逐字复制这些结构里的 `name`/`display_name`；禁止按路径、历史上下文、语义理解或旧对话内容改写、翻译、补全名称。
- 如果需要按状态分组测试用例，优先使用工具结果里的 `case_status_summary` 与 `case_attention_rows`，不要自行重新匹配 ID 和名称。
- 如果工具结果只有 ID 没有名称，必须说明“工具结果未返回名称”，再展示 ID，不能臆造名称。
- 发起工具调用时仍必须使用工具 schema 要求的 id 字段；这条规则只改变面向用户的文字总结，不改变工具入参。
""".strip()
AGENT_TOOL_PROTOCOL_PROMPT = """
可用工具如下：
{tools}

如果本轮请求提供了 provider 原生 tools，需要调用工具时必须优先使用 provider 原生 Tool Calling；
不要在 assistant content 中重复输出工具 JSON，也不要同时输出自然语言和工具调用。
仅在本轮没有提供原生 tools，或系统明确要求修复旧协议时，才使用以下兼容 fenced block：
```agent_tool_request
{"tool_name":"project.read_context","input":{"project_id":123},"reason":"为什么需要这个工具","evidence_refs":[]}
```
不要在工具请求前后输出面向用户的自然语言。工具执行结果返回后，再根据结果给用户最终答复。
如果不需要工具，请直接用自然语言回答。

测试用例工具约束：
- 所有 `environment_id` 只能使用 `project.read_context.object_reference_manifest.environment_ids` 中的显式值；不要从历史文本或连续数字猜测环境。
- 分析/展示用例时先用 `testcase.query_project_cases` 的 `detail_level="summary"`；查看少量用例断言或请求细节时，使用显式 `test_case_ids`/`websocket_test_case_ids` 并设置 `detail_level="selected"`、`"assertions"` 或 `"full"`。
- 调用 `testcase.batch_execute`、`websocket_testcase.batch_execute`、`testcase.batch_update_assertions`、`websocket_testcase.batch_update_assertions` 前，必须重新调用 `testcase.query_project_cases`，对目标集合设置 `detail_level="execution_ready"`，然后复制返回的 `*_batch_execute_input`、`case_snapshot_id`、`object_references` 或显式 id 列表。不要从历史回复、用户口述、连续数字范围、summary 查询或 selected/assertions 查询拼批量输入。
- 同会话保存场景草稿时，优先传 `scenario_source={artifact_id,output_hash}`，让后端从 Artifact/Ledger 读取完整草稿；不要为了保存而搬运完整场景 JSON。
""".strip()
AGENT_FINAL_SUMMARY_SYSTEM_PROMPT = """
当前阶段：final_summary。
禁止输出 agent_tool_request，禁止调用任何工具，禁止要求读取额外完整工具结果。
只基于本次已完成的工具结果和用户原始请求给最终回复。
如果保存成功，说明对象名称、ID、环境和是否已执行；如果执行失败，说明失败工具、错误码和可恢复下一步。
回复保持简洁，只总结已完成、已验证、剩余阻断项和下一步。
""".strip()
AGENT_TOOL_REQUEST_REPAIR_SYSTEM_PROMPT = """
当前阶段：tool_request_repair。
你的唯一任务是修复上一条模型输出里的 agent_tool_request 格式。
只保留并修正已有的 tool_name、input、reason、evidence_refs；不要重新规划业务，不要追加解释，不要引用历史工具结果。
如果仍需工具，只输出一个合法的 ```agent_tool_request fenced JSON block；如果不需要工具，直接输出自然语言回复。
""".strip()
AGENT_CAPABILITY_DENIAL_REPLAN_SYSTEM_PROMPT = """
当前阶段：capability_denial_replan。
上一条模型回复错误声称平台不支持某个能力，但当前 runtime snapshot 中存在对应工具。
你的唯一任务是基于原始用户目标和当前已召回工具，重新规划下一步。
如果用户目标需要调用工具，优先使用 provider 原生 Tool Calling；仅在本轮没有提供原生 tools 时，
才输出一个合法的 ```agent_tool_request fenced JSON block。
不要输出最终总结，不要解释为什么上一条回复错了，不要要求用户手动复制草稿。
如果仍然无法安全调用工具，请直接输出简短诊断说明缺少哪些必需输入。
""".strip()
TOOL_REQUEST_BLOCK_RE = re.compile(r"```agent_tool_request\s*(?P<body>\{.*?\})\s*```", re.S)
TOOL_REQUEST_FENCE_RE = re.compile(r"```agent_tool_request\s*(?P<body>.*?)\s*```", re.S)
TOOL_REQUEST_JSON_REPAIR_MAX_CLOSERS = 8
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
AGENT_WORKING_CONTEXT_STATE_STATUSES = tuple(
    sorted(RUN_TERMINAL_STATUSES | {"migration_blocked", "needs_human"})
)
AGENT_CONVERSATION_TOOL_ARTIFACT_MANIFEST_MAX_CALLS = 50
AGENT_CONVERSATION_TOOL_ARTIFACT_CONTEXT_MAX_ITEMS = 12
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
AGENT_CAPABILITY_PLAN_CONTEXT_PREFIX = "agent-capability-plan-context://"
AGENT_MEMORY_CONTEXT_TITLE_MAX_CHARS = 180
AGENT_MEMORY_CONTEXT_CONTENT_MAX_CHARS = 500
AGENT_MEMORY_CONTEXT_TRUNCATION_MARKER = "[agent_memory_context_truncated]"
AGENT_MODEL_CONTEXT_TOTAL_BUDGET_UNITS = 15000
AGENT_MODEL_CONTEXT_STATIC_BUDGET_UNITS = 5000
AGENT_MODEL_CONTEXT_TOOL_CATALOG_BUDGET_UNITS = 3000
AGENT_MODEL_CONTEXT_SKILL_BUDGET_UNITS = 2500
AGENT_MODEL_CONTEXT_MEMORY_BUDGET_UNITS = 2000
AGENT_MODEL_CONTEXT_HISTORY_BUDGET_UNITS = 2400
AGENT_MODEL_CONTEXT_TOOL_RESULT_BUDGET_UNITS = 5000
AGENT_MODEL_CONTEXT_BUDGET_SCHEMA_VERSION = "agent_model_context_budget_v1"
AGENT_MODEL_CONTEXT_BUDGET_SCOPE = "agent_model_context"
AGENT_MODEL_CONTEXT_BUDGET_EVENT = "context.model_budget_compacted"
AGENT_MODEL_CONTEXT_LAYER_TRUNCATION_MARKER = (
    "\n\n[agent_model_context_layer_compacted: additional context remains available in ledger/events]"
)
AGENT_UNSUPPORTED_CAPABILITY_CLASSIFIER_PROMPT_MAX_CHARS = 3000
AGENT_UNSUPPORTED_CAPABILITY_CLASSIFIER_PROMPT_TRUNCATION_MARKER = (
    "\n\n[agent_classifier_prompt_truncated: full private classifier prompt is not injected into model context]"
)
AGENT_TOOL_RESULT_CONTEXT_TOTAL_MAX_CHARS = 64 * 1024
AGENT_TOOL_RESULT_CONTEXT_TRUNCATION_MARKER = (
    "\n\n[agent_tool_result_context_truncated: additional tool results remain available in ToolCall detail]"
)
AGENT_REPAIR_CONTEXT_MAX_CHARS = 3000
AGENT_REPAIR_CONTEXT_TRUNCATION_MARKER = (
    "\n\n[agent_repair_context_truncated: full previous model content is not injected into repair context]"
)
AGENT_FINAL_RESPONSE_REFERENCE_REPAIR_FALLBACK = (
    "模型最终回复引用了不在最新工具查询结果中的测试用例 ID，后端已阻止该回复直接展示。"
    "请基于上方最新 testcase.query_project_cases 工具结果重新生成总结。"
)
DETERMINISTIC_TOOL_INPUT_REPAIR_ENGINE_VERSION = "deterministic_tool_input_repair_v1"
SCENARIO_CREATION_STATE_MACHINE_VERSION = "scenario_creation_state_machine_v1"
SCENARIO_CREATION_STATE_MACHINE_NAME = "CREATE_SCENARIO"
SCENARIO_CREATION_STATES = (
    "START",
    "CHECK_CONTEXT",
    "QUERY_CASES",
    "COMPOSE_DRAFT",
    "VALIDATE",
    "SAVE_PENDING_APPROVAL",
    "EXECUTE",
    "SUMMARY",
    "END",
)
SCENARIO_CREATION_TOOL_STATES = {
    "project.read_context": "CHECK_CONTEXT",
    "testcase.query_project_cases": "QUERY_CASES",
    "scenario.compose_draft": "COMPOSE_DRAFT",
    "scenario.create_saved": "SAVE_PENDING_APPROVAL",
    "scenario.update_saved": "SAVE_PENDING_APPROVAL",
    "scenario.execute_dry_run": "EXECUTE",
}


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
    provider_tool_call_id: str | None = None

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


@dataclass(frozen=True)
class ToolInputRepairResult:
    input: dict[str, Any]
    repairs: list[dict[str, Any]]


class DeterministicToolInputRepairEngine:
    def repair(self, *, tool_name: str, tool_input: dict[str, Any]) -> ToolInputRepairResult:
        repaired = copy.deepcopy(tool_input)
        repairs: list[dict[str, Any]] = []
        if tool_name in {"scenario.create_saved", "scenario.update_saved"}:
            repairs.extend(self._hoist_nested_scenario_snapshot_fields(repaired))
        return ToolInputRepairResult(input=repaired, repairs=repairs)

    def _hoist_nested_scenario_snapshot_fields(self, tool_input: dict[str, Any]) -> list[dict[str, Any]]:
        scenario = tool_input.get("scenario")
        if not isinstance(scenario, dict):
            return []
        moved_fields: list[str] = []
        for field in ("environment_snapshot_id", "scenario_snapshot_id"):
            if field not in scenario:
                continue
            value = scenario.pop(field)
            if field not in tool_input or tool_input.get(field) in (None, ""):
                tool_input[field] = value
            moved_fields.append(field)
        if not moved_fields:
            return []
        return [
            {
                "strategy": "hoist_nested_scenario_snapshot_fields",
                "fields": moved_fields,
                "from_path": "scenario",
                "to_path": "tool_input",
            }
        ]


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
    "active_capability_plan_id",
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
    "capability_plan_id",
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
        terminal_transitions = _scenario_terminal_state_transitions(self.db, run=run)
        for transition in terminal_transitions:
            self.append_event(run, "scenario.state_transition", transition, commit=False)
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
        skill_manifests = {
            skill.name: skill.snapshot_manifest()
            for skill in AgentSkillRegistry().list_skills()
        }
        runtime_hash = request_fingerprint({
            "tool_runtime_hash": self.tool_registry.runtime_hash(),
            "skills": skill_manifests,
        })
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
            manifest_bundle_hash=request_fingerprint({
                "tool_manifest_bundle_hash": self.tool_registry.manifest_bundle_hash(),
                "skills": skill_manifests,
            }),
            prompt_bundle_hash=request_fingerprint({
                "prompt_bundle": "agent-runtime-v2",
                "skill_bodies": {
                    name: manifest.get("body", "")
                    for name, manifest in skill_manifests.items()
                },
            }),
            policy_version_hash=request_fingerprint({"policy": "agent-policy-v1"}),
            tools_json=registry_json,
            manifests_json={
                "tools": {item["name"]: item for item in registry_json},
                "skills": skill_manifests,
            },
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
    def __init__(
        self,
        db: Session,
        *,
        intent_decision_service: AgentIntentDecisionService | None = None,
        planning_decision_service: AgentPlanningDecisionService | None = None,
    ):
        self.db = db
        self.intent_decision_service = intent_decision_service or AgentIntentDecisionService()
        self.planning_decision_service = planning_decision_service or AgentPlanningDecisionService()
        self._provider_reasoning_by_tool_call_id: dict[str, str] = {}

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
        auto_followup_calls = self._execute_post_save_dry_run_followups(
            run=run,
            current_user=user,
            completed_calls=calls,
        )
        if auto_followup_calls:
            calls.extend(auto_followup_calls)
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES or run.status == "needs_human":
                return run
        messages = self._build_final_summary_messages(run, calls=calls)
        trace_info(
            "agent_trace_complete_after_tool_results_start",
            run_id=run.run_id,
            project_id=run.project_id,
            user_id=user.id,
            tool_call_count=len(calls),
            requested_tool_call_count=len(tool_call_ids),
            message_count=len(messages),
        )
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
            content, chunks, clean_model_payload, final_repair_tool_request = self._repair_empty_model_response(
                run=run,
                runtime=runtime,
                messages=messages,
                content=content,
                chunks=chunks,
                model_payload=clean_model_payload,
                iteration=run.current_iteration,
                final_summary=True,
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            if final_repair_tool_request is not None:
                return self._complete_suppressed_final_summary_tool_request(
                    run=run,
                    runtime=runtime,
                    content=content,
                    iteration=run.current_iteration,
                    tool_summaries=[_tool_call_summary(call) for call in calls],
                    model_payload=clean_model_payload,
                    resumed_after_approval=True,
                )
            if _looks_like_tool_request_content(content):
                return self._complete_suppressed_final_summary_tool_request(
                    run=run,
                    runtime=runtime,
                    content=content,
                    iteration=run.current_iteration,
                    tool_summaries=[_tool_call_summary(call) for call in calls],
                    model_payload=clean_model_payload,
                    resumed_after_approval=True,
                )
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
            content, chunks, clean_model_payload, final_repair_tool_request = self._repair_final_response_reference_issues(
                run=run,
                runtime=runtime,
                messages=messages,
                content=content,
                chunks=chunks,
                model_payload=clean_model_payload,
                iteration=run.max_iterations,
                final_summary=True,
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            if final_repair_tool_request is not None:
                return self._complete_suppressed_final_summary_tool_request(
                    run=run,
                    runtime=runtime,
                    content=content,
                    iteration=run.max_iterations,
                    tool_summaries=[_tool_call_summary(call) for call in calls],
                    model_payload=clean_model_payload,
                    resumed_after_approval=True,
                )
            content, chunks, clean_model_payload, final_repair_tool_request = self._repair_final_response_reference_issues(
                run=run,
                runtime=runtime,
                messages=messages,
                content=content,
                chunks=chunks,
                model_payload=clean_model_payload,
                iteration=run.current_iteration,
                final_summary=True,
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            if final_repair_tool_request is not None:
                return self._complete_suppressed_final_summary_tool_request(
                    run=run,
                    runtime=runtime,
                    content=content,
                    iteration=run.current_iteration,
                    tool_summaries=[_tool_call_summary(call) for call in calls],
                    model_payload=clean_model_payload,
                    resumed_after_approval=True,
                )
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
            trace_info(
                "agent_trace_run_completed",
                run_id=run.run_id,
                project_id=run.project_id,
                completion_mode="after_approval_tools",
                iteration=run.current_iteration,
                tool_call_count=len(calls),
                content_length=len(content),
            )
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

    def _execute_post_save_dry_run_followups(
        self,
        *,
        run: AgentRun,
        current_user: User,
        completed_calls: list[AgentToolCall],
    ) -> list[AgentToolCall]:
        if not _intent_requests_save_then_execute(run.intent):
            return []
        saved = self._saved_scenario_from_tool_calls(completed_calls)
        if saved is None:
            return []
        scenario_id = saved["scenario_id"]
        if self._has_existing_scenario_dry_run_call(run=run, scenario_id=scenario_id):
            return []

        runtime = AgentRuntimeService(self.db)
        followups: list[AgentToolCall] = []
        query_input: dict[str, Any] = {
            "project_id": run.project_id,
            "detail_level": "summary",
            "page_size": 50,
        }
        if saved.get("name"):
            query_input["keyword"] = saved["name"]
        runtime.append_event(
            run,
            "tool.auto_followup_requested",
            {
                "source_tool_call_id": saved["tool_call_id"],
                "source_tool_name": saved["tool_name"],
                "tool_name": "scenario.query_project_scenarios",
                "reason": "save_then_execute_requires_fresh_scenario_snapshot",
                "scenario_id": scenario_id,
            },
            commit=False,
        )
        query_call = self._create_and_execute_tool_request(
            run=run,
            current_user=current_user,
            tool_request=AgentToolRequest(
                tool_name="scenario.query_project_scenarios",
                tool_input=query_input,
                reason="保存成功后按用户要求执行场景前，先刷新场景快照。",
            ),
            iteration=run.current_iteration,
        )
        followups.append(query_call)
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES or run.status == "needs_human":
            return followups
        if query_call.status != "succeeded":
            return followups

        dry_run_input: dict[str, Any] = {
            "project_id": run.project_id,
            "scenario_id": scenario_id,
            "idempotency_key": f"{run.run_id}:{saved['tool_call_id']}:post-save-dry-run",
        }
        if saved.get("environment_id") is not None:
            dry_run_input["environment_id"] = saved["environment_id"]
        if saved.get("current_version") is not None:
            dry_run_input["scenario_version"] = saved["current_version"]
        runtime.append_event(
            run,
            "tool.auto_followup_requested",
            {
                "source_tool_call_id": saved["tool_call_id"],
                "source_tool_name": saved["tool_name"],
                "tool_name": "scenario.execute_dry_run",
                "reason": "user_requested_save_then_execute",
                "scenario_id": scenario_id,
                "environment_id": saved.get("environment_id"),
            },
            commit=False,
        )
        dry_run_call = self._create_and_execute_tool_request(
            run=run,
            current_user=current_user,
            tool_request=AgentToolRequest(
                tool_name="scenario.execute_dry_run",
                tool_input=dry_run_input,
                reason="保存成功后按用户要求立即执行场景 dry-run。",
            ),
            iteration=run.current_iteration,
        )
        followups.append(dry_run_call)
        return followups

    @staticmethod
    def _saved_scenario_from_tool_calls(calls: list[AgentToolCall]) -> dict[str, Any] | None:
        for call in calls:
            if call.tool_name not in {"scenario.create_saved", "scenario.update_saved"}:
                continue
            if call.status != "succeeded":
                continue
            output = call.output_json_redacted if isinstance(call.output_json_redacted, dict) else {}
            scenario = output.get("scenario") if isinstance(output.get("scenario"), dict) else {}
            scenario_id = _optional_positive_int(output.get("scenario_id"))
            if scenario_id is None:
                scenario_id = _optional_positive_int(scenario.get("id"))
            if scenario_id is None:
                continue
            environment_id = _optional_positive_int(scenario.get("environment_id"))
            if environment_id is None:
                environment_id = _optional_positive_int(scenario.get("environmentId"))
            if environment_id is None:
                environment_id = _optional_positive_int(output.get("environment_id"))
            current_version = _optional_positive_int(scenario.get("current_version"))
            if current_version is None:
                current_version = _optional_positive_int(scenario.get("currentVersion"))
            if current_version is None:
                current_version = _optional_positive_int(output.get("current_version"))
            return {
                "tool_call_id": call.tool_call_id,
                "tool_name": call.tool_name,
                "scenario_id": scenario_id,
                "environment_id": environment_id,
                "current_version": current_version,
                "name": str(scenario.get("name") or output.get("name") or "").strip(),
            }
        return None

    def _has_existing_scenario_dry_run_call(self, *, run: AgentRun, scenario_id: int) -> bool:
        calls = list(
            self.db.scalars(
                select(AgentToolCall)
                .where(
                    AgentToolCall.run_id == run.run_id,
                    AgentToolCall.tool_name == "scenario.execute_dry_run",
                )
                .order_by(AgentToolCall.id.desc())
            ).all()
        )
        for call in calls:
            payload = call.input_json_redacted if isinstance(call.input_json_redacted, dict) else {}
            if _optional_positive_int(payload.get("scenario_id")) == scenario_id:
                return True
        return False

    def _process_native_capability_request(
        self,
        *,
        run: AgentRun,
        current_user: User,
        runtime: AgentRuntimeService,
        messages: list[AIChatMessage],
        payload: dict[str, Any],
        iteration: int,
    ) -> None:
        tool_names = tuple(
            dict.fromkeys(
                str(name).strip()
                for name in (payload.get("tool_names") or [])
                if str(name).strip()
            )
        )
        reason = str(payload.get("reason") or "").strip()
        provider_tool_call_id = str(
            payload.get("provider_tool_call_id") or f"capability-{uuid.uuid4().hex}"
        )
        plan_service = AgentCapabilityPlanService(self.db)
        active_plan = plan_service.get_active_plan(run=run)
        runtime.append_event(
            run,
            "planner.capability_activation_requested",
            {
                "iteration": iteration,
                "capability_plan_id": active_plan.capability_plan_id,
                "tool_names": list(tool_names),
                "reason": reason[:1000],
                "provider_tool_call_id": provider_tool_call_id,
            },
            commit=True,
        )
        self.db.refresh(run)
        self.db.refresh(active_plan)
        permission_names = self._project_permission_names(
            current_user=current_user,
            project_id=run.project_id,
        )
        result = plan_service.request_capabilities(
            run=run,
            current=active_plan,
            tool_names=tool_names,
            reason=reason,
            permission_names=permission_names,
        )
        result_payload = {
            "ok": result.accepted,
            "code": (
                "agent_capability_activation_accepted"
                if result.accepted
                else "agent_capability_activation_rejected"
            ),
            "plan_id": result.plan_id,
            "activated_tools": list(result.activated_tools),
            "rejected_tools": list(result.rejected_tools),
            "rejection_reasons": result.rejection_reasons or {},
        }
        event_type = (
            "planner.capability_activation_accepted"
            if result.accepted
            else "planner.capability_activation_rejected"
        )
        runtime.append_event(
            run,
            event_type,
            {"iteration": iteration, **result_payload},
            commit=True,
        )
        if result.accepted and result.plan_id != active_plan.capability_plan_id:
            runtime.append_event(
                run,
                "planner.capability_plan_revised",
                {
                    "iteration": iteration,
                    "previous_plan_id": active_plan.capability_plan_id,
                    "capability_plan_id": result.plan_id,
                    "activated_tools": list(result.activated_tools),
                },
                commit=True,
            )
        messages.append(
            AIChatMessage(
                role="assistant",
                content=None,
                reasoning_content=self._provider_reasoning_by_tool_call_id.pop(
                    provider_tool_call_id,
                    None,
                ),
                tool_calls=[
                    AIChatToolCall(
                        id=provider_tool_call_id,
                        function=AIChatToolCallFunction(
                            name=RUNTIME_REQUEST_CAPABILITY_ALIAS,
                            arguments=json.dumps(
                                {"tool_names": list(tool_names), "reason": reason},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        ),
                    )
                ],
            )
        )
        messages.append(
            AIChatMessage(
                role="tool",
                tool_call_id=provider_tool_call_id,
                content=json.dumps(result_payload, ensure_ascii=False, separators=(",", ":")),
            )
        )

    def _project_permission_names(self, *, current_user: User, project_id: int) -> tuple[str, ...]:
        permission_service = PermissionService(self.db)
        project = permission_service.require_project_access(current_user, project_id)
        if permission_service.is_admin(current_user) or permission_service.is_project_creator(current_user, project):
            return tuple(permission.value for permission in ProjectPermission)
        return tuple(sorted(permission_service.project_repository.get_member_permission_codes(
            project_id=project_id,
            user_id=current_user.id,
        )))

    def _append_capability_call_rejection_context(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        messages: list[AIChatMessage],
        tool_request: AgentToolRequest,
        error: CapabilityPlanError,
        iteration: int,
    ) -> None:
        active_plan_id = (
            error.capability_plan_id
            if isinstance(error, CapabilityPlanToolNotAllowed)
            else run.active_capability_plan_id
        )
        result = {
            "ok": False,
            "code": "agent_capability_not_active",
            "tool_name": tool_request.tool_name,
            "active_plan_id": active_plan_id,
            "error_type": type(error).__name__,
            "next_action": "call runtime.request_capability",
        }
        runtime.append_event(
            run,
            "planner.capability_call_rejected",
            {"iteration": iteration, **result},
            commit=True,
        )
        content = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if tool_request.provider_tool_call_id:
            messages.append(
                AIChatMessage(
                    role="tool",
                    tool_call_id=tool_request.provider_tool_call_id,
                    content=content,
                )
            )
            return
        messages.append(
            AIChatMessage(
                role="system",
                content=f"Runtime capability result: {content}",
            )
        )

    def _record_scenario_draft_validation_event(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        call: AgentToolCall | Any,
        iteration: int,
    ) -> None:
        if call.tool_name != "scenario.compose_draft":
            return
        output = call.output_json_redacted if isinstance(call.output_json_redacted, dict) else {}
        draft = output.get("draft") if isinstance(output.get("draft"), dict) else {}
        validation = (
            draft.get("scenario_validation")
            if isinstance(draft.get("scenario_validation"), dict)
            else None
        )
        if validation is None:
            return
        event_type = (
            "scenario.draft_validation_completed"
            if validation.get("valid") is True
            else "scenario.draft_validation_failed"
        )
        fields = (
            "valid",
            "referenced_case_count",
            "unresolved_reference_count",
            "dependency_edge_count",
            "resolved_template_count",
            "unresolved_template_count",
            "extractor_count",
            "binding_count",
        )
        runtime.append_event(
            run,
            event_type,
            {
                "iteration": iteration,
                "tool_call_id": call.tool_call_id,
                **{field: validation.get(field) for field in fields if validation.get(field) is not None},
                "quality_issue_count": len(validation.get("quality_issues") or []),
                "graph_error_count": len(validation.get("graph_errors") or []),
            },
            commit=True,
        )

    def _build_final_summary_messages(self, run: AgentRun, *, calls: list[AgentToolCall]) -> list[AIChatMessage]:
        messages = [
            AIChatMessage(role="system", content=AGENT_FINAL_SUMMARY_SYSTEM_PROMPT),
            AIChatMessage(role="system", content=_format_run_context(run)),
            AIChatMessage(role="user", content=f"用户原始请求：{run.intent}"),
        ]
        messages.extend(_final_summary_tool_result_context_messages(calls))
        return messages

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
            trace_info(
                "agent_trace_run_start",
                run_id=run.run_id,
                project_id=run.project_id,
                user_id=user.id,
                conversation_id=run.conversation_id,
                status=run.status,
                max_iterations=run.max_iterations,
                intent_chars=len(run.intent or ""),
            )
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
            trace_debug(
                "agent_trace_context_built",
                run_id=run.run_id,
                project_id=run.project_id,
                **trace_message_summary(messages),
            )
            tool_summaries: list[dict[str, Any]] = []
            for iteration in range(max(1, run.max_iterations)):
                self.db.refresh(run)
                if run.status in RUN_TERMINAL_STATUSES:
                    return run
                self._carry_forward_capability_plan_if_needed(
                    run=run,
                    runtime=runtime,
                    messages=messages,
                    iteration=iteration,
                )
                self.db.refresh(run)
                trace_info(
                    "agent_trace_iteration_start",
                    run_id=run.run_id,
                    project_id=run.project_id,
                    iteration=iteration,
                    status=run.status,
                    current_step_index=run.current_step_index,
                    message_count=len(messages),
                    tool_call_count=len(tool_summaries),
                )
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
                native_capability_payload = clean_model_payload.get("native_capability_request")
                if isinstance(native_capability_payload, dict):
                    self._process_native_capability_request(
                        run=run,
                        current_user=user,
                        runtime=runtime,
                        messages=messages,
                        payload=native_capability_payload,
                        iteration=iteration,
                    )
                    self.db.refresh(run)
                    if run.status in RUN_TERMINAL_STATUSES:
                        return run
                    continue
                content, chunks, clean_model_payload, tool_request = self._repair_empty_model_response(
                    run=run,
                    runtime=runtime,
                    messages=messages,
                    content=content,
                    chunks=chunks,
                    model_payload=clean_model_payload,
                    iteration=iteration,
                    final_summary=False,
                )
                self.db.refresh(run)
                if run.status in RUN_TERMINAL_STATUSES:
                    return run
                try:
                    if tool_request is None:
                        tool_request = self._parse_tool_request(
                            content,
                            normalize_evidence_refs=True,
                            normalize_single_evidence_ref_object=False,
                        )
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
                        content, chunks, clean_model_payload, tool_request = self._repair_final_response_reference_issues(
                            run=run,
                            runtime=runtime,
                            messages=messages,
                            content=content,
                            chunks=chunks,
                            model_payload=clean_model_payload,
                            iteration=iteration,
                            final_summary=False,
                        )
                        self.db.refresh(run)
                        if run.status in RUN_TERMINAL_STATUSES:
                            return run
                        if tool_request is None:
                            self._guard_available_capability_denial(
                                run=run,
                                runtime=runtime,
                                content=content,
                                iteration=iteration,
                                final_summary=False,
                                model_payload=clean_model_payload,
                            )
                            if tool_request is None:
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
                                trace_info(
                                    "agent_trace_run_completed",
                                    run_id=run.run_id,
                                    project_id=run.project_id,
                                    completion_mode="without_tool",
                                    iteration=iteration,
                                    tool_call_count=len(tool_summaries),
                                    content_length=len(content),
                                )
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
                        "assistant_visible": False,
                        **clean_model_payload,
                    },
                    commit=False,
                )
                execution_plan_id = agent_execution_plan_id(
                    run_id=run.run_id,
                    iteration=iteration,
                    step_index=run.current_step_index,
                    tool_name=tool_request.tool_name,
                )
                detected_event_payload = {
                    **tool_request.detected_event_payload(iteration=iteration),
                    "execution_plan_id": execution_plan_id,
                }
                trace_info(
                    "agent_trace_tool_request_detected",
                    run_id=run.run_id,
                    project_id=run.project_id,
                    iteration=iteration,
                    tool_name=tool_request.tool_name,
                    evidence_ref_count=len(tool_request.evidence_refs_for_ledger()),
                    reason_chars=len(tool_request.reason or ""),
                )
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
                if tool_request.provider_tool_call_id:
                    active_plan = AgentCapabilityPlanService(self.db).get_active_plan(run=run)
                    provider_alias = next(
                        (
                            alias
                            for alias, canonical in (active_plan.tool_aliases_json or {}).items()
                            if canonical == tool_request.tool_name
                        ),
                        tool_request.tool_name,
                    )
                    messages.append(AIChatMessage(
                        role="assistant",
                        content=None,
                        reasoning_content=self._provider_reasoning_by_tool_call_id.pop(
                            tool_request.provider_tool_call_id,
                            None,
                        ),
                        tool_calls=[AIChatToolCall(
                            id=tool_request.provider_tool_call_id,
                            function=AIChatToolCallFunction(
                                name=provider_alias,
                                arguments=json.dumps(
                                    {
                                        "input": tool_request.input_for_ledger(),
                                        "reason": tool_request.reason,
                                        "evidence_refs": tool_request.evidence_refs_for_ledger(),
                                    },
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            ),
                        )],
                    ))
                else:
                    messages.append(
                        AIChatMessage(
                            role="assistant",
                            content=_tool_request_context_message(tool_request=tool_request, content=content),
                        )
                    )
                try:
                    call = self._create_and_execute_tool_request(
                        run=run,
                        current_user=user,
                        tool_request=tool_request,
                        iteration=iteration,
                        execution_plan_id=execution_plan_id,
                    )
                except (CapabilityPlanToolNotAllowed, CapabilityPlanNotActive) as exc:
                    self._append_capability_call_rejection_context(
                        run=run,
                        runtime=runtime,
                        messages=messages,
                        tool_request=tool_request,
                        error=exc,
                        iteration=iteration,
                    )
                    continue
                logger.info(
                    "agent_tool_request_finished run_id=%s iteration=%s tool_call_id=%s tool_name=%s status=%s",
                    run.run_id,
                    iteration,
                    call.tool_call_id,
                    call.tool_name,
                    call.status,
                )
                self._record_scenario_draft_validation_event(
                    run=run,
                    runtime=runtime,
                    call=call,
                    iteration=iteration,
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
                _append_tool_result_context_message(
                    messages,
                    call,
                    provider_tool_call_id=tool_request.provider_tool_call_id,
                )
                trace_debug(
                    "agent_trace_tool_result_context_appended",
                    run_id=run.run_id,
                    project_id=run.project_id,
                    iteration=iteration,
                    tool_call_id=call.tool_call_id,
                    tool_name=call.tool_name,
                    status=call.status,
                    message_count=len(messages),
                )

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
            content, chunks, clean_model_payload, final_repair_tool_request = self._repair_empty_model_response(
                run=run,
                runtime=runtime,
                messages=messages,
                content=content,
                chunks=chunks,
                model_payload=clean_model_payload,
                iteration=run.max_iterations,
                final_summary=True,
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return run
            if final_repair_tool_request is not None:
                return self._complete_suppressed_final_summary_tool_request(
                    run=run,
                    runtime=runtime,
                    content=content,
                    iteration=run.max_iterations,
                    tool_summaries=tool_summaries,
                    model_payload=clean_model_payload,
                    resumed_after_approval=False,
                )
            if _looks_like_tool_request_content(content):
                return self._complete_suppressed_final_summary_tool_request(
                    run=run,
                    runtime=runtime,
                    content=content,
                    iteration=run.max_iterations,
                    tool_summaries=tool_summaries,
                    model_payload=clean_model_payload,
                    resumed_after_approval=False,
                )
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
            guarded_content = self._guard_available_capability_denial(
                run=run,
                runtime=runtime,
                content=content,
                iteration=run.max_iterations,
                final_summary=True,
                model_payload=clean_model_payload,
            )
            if guarded_content is not None:
                content = guarded_content
                chunks = [content]
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
            trace_info(
                "agent_trace_run_completed",
                run_id=run.run_id,
                project_id=run.project_id,
                completion_mode="after_tools",
                iteration=run.max_iterations,
                tool_call_count=len(tool_summaries),
                content_length=len(content),
            )
            return runtime.complete_run(run, {"message": content, "tool_calls": tool_summaries, **clean_model_payload}, commit=True)
        except AgentPlanningFailed as exc:
            return self._fail_run_after_exception(
                run=run,
                runtime=runtime,
                error_code="agent_planning_failed",
                error_message=str(exc),
                original_exception=exc,
            )
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
            trace_warning(
                "agent_trace_run_failed",
                run_id=run.run_id,
                project_id=run.project_id,
                error_code=error_code,
                error_type=type(exc).__name__,
                error_message_chars=len(str(bounded_detail)),
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
            trace_error(
                "agent_trace_run_failed",
                run_id=run.run_id,
                project_id=run.project_id,
                error_code=error_code,
                error_type=type(exc).__name__,
                error_message_chars=len(str(bounded_detail)),
            )
            return self._fail_run_after_exception(
                run=run,
                runtime=runtime,
                error_code=error_code,
                error_message=bounded_detail,
                original_exception=exc,
            )

    def _complete_suppressed_final_summary_tool_request(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        content: str,
        iteration: int,
        tool_summaries: list[dict[str, Any]],
        model_payload: dict[str, Any],
        resumed_after_approval: bool,
    ) -> AgentRun:
        trace_payload = _model_trace_from_payload(model_payload)
        trace_warning(
            "agent_trace_final_summary_tool_request_suppressed",
            run_id=run.run_id,
            project_id=run.project_id,
            iteration=iteration,
            resumed_after_approval=resumed_after_approval,
            tool_call_count=len(tool_summaries),
            content_length=len(content),
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return run
        runtime.append_event(
            run,
            "model.markdown_normalized",
            {
                "iteration": iteration,
                "final_summary": True,
                "content": "",
                "replace_content": True,
                "normalization_reason": "final_summary_tool_request_suppressed",
                **trace_payload,
            },
            commit=False,
        )
        runtime.append_event(
            run,
            "model.completed",
            {
                "content": _bounded_agent_content_preview(
                    content,
                    reference="AgentConversationRunner.model.completed.final_summary_tool_request.content",
                ),
                "iteration": iteration,
                "final_summary": True,
                "requested_tool": True,
                "assistant_visible": False,
                "final_summary_tool_request_suppressed": True,
                "resumed_after_approval": resumed_after_approval,
                **model_payload,
            },
            commit=False,
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return run
        return runtime.complete_run(
            run,
            {
                "message": _final_summary_tool_request_suppressed_message(tool_summaries),
                "tool_calls": tool_summaries,
                "final_summary_tool_request_suppressed": True,
                **model_payload,
            },
            commit=True,
        )

    def _carry_forward_capability_plan_if_needed(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        messages: list[AIChatMessage],
        iteration: int,
    ) -> None:
        if not run.active_capability_plan_id:
            return
        service = AgentCapabilityPlanService(self.db)
        try:
            current = service.get_active_plan(run=run)
        except CapabilityPlanError:
            return
        if current.iteration >= iteration:
            return
        carried = service.carry_forward_plan(
            run=run,
            current=current,
            iteration=iteration,
        )
        identity_message = _capability_plan_identity_message(
            capability_plan_id=carried.capability_plan_id,
            plan_hash=carried.plan_hash,
            iteration=iteration,
            previous_capability_plan_id=current.capability_plan_id,
        )
        for index, message in enumerate(messages):
            if (message.content or "").startswith(AGENT_CAPABILITY_PLAN_CONTEXT_PREFIX):
                messages[index] = identity_message
                break
        else:
            # Plan identity is metadata. Keep the newest tool result or repair
            # instruction at the end so it remains the model's next task.
            messages.insert(max(0, len(messages) - 1), identity_message)
        runtime.append_event(
            run,
            "planner.capability_plan_created",
            {
                "capability_plan_id": carried.capability_plan_id,
                "previous_capability_plan_id": current.capability_plan_id,
                "iteration": iteration,
                "revision": carried.revision,
                "source": carried.source,
                "plan_hash": carried.plan_hash,
            },
            commit=True,
        )

    def _observe_capability_denial(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        content: str,
        iteration: int,
        final_summary: bool,
        model_payload: dict[str, Any],
    ) -> bool:
        snapshot = self.db.scalar(
            select(AgentRuntimeSnapshot).where(AgentRuntimeSnapshot.snapshot_id == run.runtime_snapshot_id)
        )
        runtime_tools = snapshot.tools_json if snapshot is not None and isinstance(snapshot.tools_json, list) else []
        active_plan = None
        if run.active_capability_plan_id:
            try:
                active_plan = AgentCapabilityPlanService(self.db).get_active_plan(run=run)
            except CapabilityPlanError:
                active_plan = None
        denied_tool_name = _denied_available_tool_name(
            content,
            runtime_tools,
            intent_decision=(active_plan.intent_decision_json if active_plan is not None else None),
        )
        reason = _assistant_denies_available_capability(content, runtime_tools)
        if reason is None and denied_tool_name is None:
            return False
        reason = reason or "denied_available_capability"
        runtime.append_event(
            run,
            "model.capability_denial_observed",
            {
                "reason": reason,
                "tool_name": denied_tool_name,
                "capability_plan_id": active_plan.capability_plan_id if active_plan is not None else None,
                "iteration": iteration,
                "final_summary": final_summary,
                "requestable": bool(
                    denied_tool_name
                    and active_plan is not None
                    and denied_tool_name not in set(active_plan.allowed_tools_json or [])
                ),
                "content_preview": _bounded_agent_content_preview(
                    content,
                    reference="AgentConversationRunner.capability_denial_observed.content",
                ),
                **_model_trace_from_payload(model_payload),
            },
            commit=True,
        )
        return True

    def _guard_available_capability_denial(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        content: str,
        iteration: int,
        final_summary: bool,
        model_payload: dict[str, Any],
    ) -> str | None:
        self._observe_capability_denial(
            run=run,
            runtime=runtime,
            content=content,
            iteration=iteration,
            final_summary=final_summary,
            model_payload=model_payload,
        )
        return None

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
        return True

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
                    f"优先使用 provider 原生 Tool Calling 来调用 "
                    f"`{required_followup.required_tool}`。"
                    "仅在本轮没有原生 tools 时使用 agent_tool_request 兼容块。"
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
        repair_strategy = None
        try:
            tool_request, repair_strategy = self._parse_repaired_tool_request(repaired_content)
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
                **({"repair_strategy": repair_strategy} if repair_strategy else {}),
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
        reasoning_parts: list[str] = []
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
        if run.active_capability_plan_id:
            trace_payload["capability_plan_id"] = run.active_capability_plan_id
        messages, context_budget = _apply_model_context_budget(messages)
        if context_budget["compacted"]:
            runtime.append_event(
                run,
                AGENT_MODEL_CONTEXT_BUDGET_EVENT,
                {**context_budget, **trace_payload},
                commit=True,
            )
            self.db.refresh(run)
            if run.status in RUN_TERMINAL_STATUSES:
                return "", [], {}
        message_summary = trace_message_summary(messages)
        context_metrics = _model_context_metrics(messages)
        model_payload: dict[str, Any] = dict(trace_payload)
        runtime.append_event(
            run,
            "model.started",
            {
                "provider": AIService.provider,
                "iteration": iteration,
                "final_summary": final_summary,
                "repair_attempt": repair_attempt,
                "message_summary": message_summary,
                "context_metrics": context_metrics,
                "context_budget": context_budget,
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
        trace_info(
            "agent_trace_model_call_start",
            run_id=run.run_id,
            project_id=run.project_id,
            iteration=iteration,
            final_summary=final_summary,
            repair_attempt=repair_attempt,
            suppress_visible_deltas=suppress_visible_deltas,
            loop_step=resolved_loop_step,
            model_call_id=trace_payload.get("model_call_id"),
            provider=AIService.provider,
            **message_summary,
        )
        trace_full_payload(
            "agent_trace_model_prompt_full_payload",
            _chat_messages_trace_payload(messages),
            prefix="messages",
            mask=True,
            run_id=run.run_id,
            project_id=run.project_id,
            iteration=iteration,
            final_summary=final_summary,
            repair_attempt=repair_attempt,
            suppress_visible_deltas=suppress_visible_deltas,
            loop_step=resolved_loop_step,
            model_call_id=trace_payload.get("model_call_id"),
            provider=AIService.provider,
        )
        self._release_db_transaction_before_external_wait()
        native_tools = []
        native_accumulator = None
        if (
            settings.AGENT_NATIVE_TOOL_CALLING_ENABLED
            and not final_summary
            and run.active_capability_plan_id
        ):
            try:
                native_plan = AgentCapabilityPlanService(self.db).get_active_plan(run=run)
            except CapabilityPlanError:
                native_plan = None
            if native_plan is not None:
                native_snapshot = self.db.scalar(
                    select(AgentRuntimeSnapshot).where(
                        AgentRuntimeSnapshot.snapshot_id == native_plan.runtime_snapshot_id
                    )
                )
                native_tools = build_native_tool_definitions(
                    allowed_tools=list(native_plan.allowed_tools_json or []),
                    tool_aliases=dict(native_plan.tool_aliases_json or {}),
                    runtime_tools=(
                        native_snapshot.tools_json
                        if native_snapshot is not None and isinstance(native_snapshot.tools_json, list)
                        else []
                    ),
                )
                if native_tools:
                    native_accumulator = NativeToolCallAccumulator(
                        tool_aliases=dict(native_plan.tool_aliases_json or {})
                    )
        request = AIChatRequest(
            messages=messages,
            temperature=0.2,
            tools=native_tools,
            tool_choice="auto" if native_tools else None,
            parallel_tool_calls=False,
        )
        self._release_db_transaction_before_external_wait()
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
                if item.get("type") == "tool_call_delta":
                    if native_accumulator is None:
                        continue
                    try:
                        for tool_call_delta in item.get("tool_calls") or []:
                            if isinstance(tool_call_delta, dict):
                                native_accumulator.feed(tool_call_delta)
                    except NativeToolCallError as exc:
                        model_payload["native_tool_call_error"] = str(exc)
                    continue
                if item.get("type") == "reasoning_delta":
                    reasoning = str(item.get("content") or "")
                    if reasoning:
                        reasoning_parts.append(reasoning)
                    continue
                if item.get("type") == "delta":
                    delta = str(item.get("content") or "")
                    if delta:
                        content_parts.append(delta)
                        content = "".join(content_parts)
                        if "```agent_tool_request" in content:
                            tool_request_marker_seen = True
                            visible_content = _visible_content_before_tool_request(content)
                            pending_visible_deltas.clear()
                            pending_visible_chars = 0
                            if visible_content and not suppress_visible_deltas and not visible_deltas_retracted:
                                if not deltas_emitted:
                                    runtime.append_event(
                                        run,
                                        "model.delta",
                                        {
                                            "iteration": iteration,
                                            "final_summary": final_summary,
                                            "repair_attempt": repair_attempt,
                                            "content": visible_content,
                                            **trace_payload,
                                        },
                                        commit=True,
                                    )
                                    self._release_db_transaction_before_external_wait()
                                    deltas_emitted = True
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
        if native_accumulator is not None and native_accumulator.has_data:
            try:
                native_request = native_accumulator.finalize()
                if isinstance(native_request, NativeCapabilityRequest):
                    model_payload["native_capability_request"] = {
                        "tool_names": list(native_request.tool_names),
                        "reason": native_request.reason,
                        "provider_tool_call_id": native_request.provider_tool_call_id,
                    }
                    detected_event_type = "model.native_capability_request_detected"
                    detected_payload = {
                        "tool_names": list(native_request.tool_names),
                        "provider_tool_call_id": native_request.provider_tool_call_id,
                        **trace_payload,
                    }
                else:
                    model_payload["native_tool_request"] = {
                        "tool_name": native_request.tool_name,
                        "input": native_request.tool_input,
                        "reason": native_request.reason,
                        "evidence_refs": list(native_request.evidence_refs),
                        "provider_tool_call_id": native_request.provider_tool_call_id,
                    }
                    detected_event_type = "model.native_tool_call_detected"
                    detected_payload = {
                        "tool_name": native_request.tool_name,
                        "provider_tool_call_id": native_request.provider_tool_call_id,
                        **trace_payload,
                    }
                if native_request.provider_tool_call_id and reasoning_parts:
                    self._provider_reasoning_by_tool_call_id[native_request.provider_tool_call_id] = "".join(
                        reasoning_parts
                    )
                runtime.append_event(
                    run,
                    detected_event_type,
                    detected_payload,
                    commit=True,
                )
                self._release_db_transaction_before_external_wait()
            except NativeToolCallError as exc:
                model_payload["native_tool_call_error"] = str(exc)
                runtime.append_event(
                    run,
                    "model.native_tool_call_invalid",
                    {
                        "error_message": str(exc),
                        **trace_payload,
                    },
                    commit=True,
                )
                self._release_db_transaction_before_external_wait()
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
        trace_info(
            "agent_trace_model_call_done",
            run_id=run.run_id,
            project_id=run.project_id,
            iteration=iteration,
            final_summary=final_summary,
            repair_attempt=repair_attempt,
            loop_step=resolved_loop_step,
            model_call_id=trace_payload.get("model_call_id"),
            content_length=len(content),
            chunk_count=len(content_parts),
            deltas_emitted=deltas_emitted,
            finish_reason=model_payload.get("finish_reason"),
            model=model_payload.get("model"),
            stream_interrupted=stream_interrupted,
            tool_request_marker_seen=tool_request_marker_seen,
        )
        trace_verbose_payload(
            "agent_trace_model_response_payload",
            content,
            prefix="content",
            mask=False,
            run_id=run.run_id,
            project_id=run.project_id,
            iteration=iteration,
            final_summary=final_summary,
            repair_attempt=repair_attempt,
            loop_step=resolved_loop_step,
            model_call_id=trace_payload.get("model_call_id"),
            finish_reason=model_payload.get("finish_reason"),
            model=model_payload.get("model"),
            stream_interrupted=stream_interrupted,
            tool_request_marker_seen=tool_request_marker_seen,
        )
        trace_full_payload(
            "agent_trace_model_response_full_payload",
            content,
            prefix="content",
            mask=False,
            run_id=run.run_id,
            project_id=run.project_id,
            iteration=iteration,
            final_summary=final_summary,
            repair_attempt=repair_attempt,
            loop_step=resolved_loop_step,
            model_call_id=trace_payload.get("model_call_id"),
            finish_reason=model_payload.get("finish_reason"),
            model=model_payload.get("model"),
            stream_interrupted=stream_interrupted,
            tool_request_marker_seen=tool_request_marker_seen,
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
        normalize_evidence_refs: bool = True,
        normalize_single_evidence_ref_object: bool = True,
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
            payload = _parse_tool_request_json_payload(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="模型工具请求不是合法 JSON",
            ) from exc
        return _tool_request_from_payload(
            payload,
            normalize_evidence_refs=normalize_evidence_refs,
            normalize_single_evidence_ref_object=normalize_single_evidence_ref_object,
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
        repair_strategy = "salvaged_internal_tool_context_summary"
        salvaged_tool_request = self._try_salvage_internal_tool_context_summary(invalid_content)
        if salvaged_tool_request is None:
            repair_strategy = "salvaged_fenced_tool_request"
            salvaged_tool_request = (
                self._try_salvage_mixed_tool_request(
                    invalid_content,
                    normalize_single_evidence_ref_object=False,
                )
                or self._try_salvage_tool_request_json(
                    invalid_content,
                    normalize_single_evidence_ref_object=False,
                )
            )
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
                    "repair_strategy": repair_strategy,
                    **_model_trace_from_payload(model_payload),
                },
                commit=True,
            )
            return invalid_content, [], model_payload, salvaged_tool_request

        _ = messages
        repair_messages = [
            AIChatMessage(role="system", content=AGENT_TOOL_REQUEST_REPAIR_SYSTEM_PROMPT),
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
        repair_strategy = None
        try:
            tool_request, repair_strategy = self._parse_repaired_tool_request(repaired_content)
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
                **({"repair_strategy": repair_strategy} if repair_strategy else {}),
                **_model_trace_from_payload(clean_payload),
            },
            commit=True,
        )
        return repaired_content, repaired_chunks, clean_payload, tool_request

    def _repair_empty_model_response(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        messages: list[AIChatMessage],
        content: str,
        chunks: list[str],
        model_payload: dict[str, Any],
        iteration: int,
        final_summary: bool,
    ) -> tuple[str, list[str], dict[str, Any], AgentToolRequest | None]:
        native_tool_request = _agent_tool_request_from_native_payload(model_payload.get("native_tool_request"))
        if native_tool_request is not None:
            return content, chunks, model_payload, native_tool_request
        if (content or "").strip():
            return content, chunks, model_payload, None
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return content, [], model_payload, None
        runtime.append_event(
            run,
            "model.empty_response_invalid",
            {
                "iteration": iteration,
                "final_summary": final_summary,
                "error_message": "model returned empty content with terminal finish_reason",
                **_model_trace_from_payload(model_payload),
            },
            commit=True,
        )
        repair_messages = [
            *messages,
            AIChatMessage(
                role="assistant",
                content="[empty_model_response: previous model call returned no visible content]",
            ),
            AIChatMessage(
                role="user",
                content=(
                    "上一条模型回复为空，不能作为最终用户回复。"
                    "请基于当前任务重新输出：如果需要平台工具，优先使用 provider 原生 Tool Calling；"
                    "仅在本轮没有原生 tools 时使用 agent_tool_request 兼容块；"
                    "如果不需要工具，直接给用户自然语言回复。不要解释空响应本身。"
                ),
            ),
        ]
        repaired_content, repaired_chunks, repaired_payload = self._stream_model_response(
            run=run,
            messages=repair_messages,
            runtime=runtime,
            iteration=iteration,
            final_summary=final_summary,
            repair_attempt=True,
            suppress_visible_deltas=True,
            loop_step="empty_response_repair",
        )
        clean_payload = {key: value for key, value in repaired_payload.items() if value is not None}
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return repaired_content, repaired_chunks, clean_payload, None
        if not (repaired_content or "").strip():
            runtime.append_event(
                run,
                "model.empty_response_repair_failed",
                {
                    "iteration": iteration,
                    "final_summary": final_summary,
                    "error_message": "empty response repair returned empty content",
                    **_model_trace_from_payload(clean_payload),
                },
                commit=True,
            )
            return AGENT_EMPTY_MODEL_RESPONSE_FALLBACK, [AGENT_EMPTY_MODEL_RESPONSE_FALLBACK], clean_payload, None
        try:
            repaired_tool_request = self._parse_tool_request(
                repaired_content,
                normalize_evidence_refs=True,
                normalize_single_evidence_ref_object=False,
            )
        except HTTPException:
            repaired_tool_request = None
        runtime.append_event(
            run,
            "model.empty_response_repaired",
            {
                "iteration": iteration,
                "final_summary": final_summary,
                "requested_tool": repaired_tool_request is not None,
                "tool_name": repaired_tool_request.tool_name if repaired_tool_request else None,
                **_model_trace_from_payload(clean_payload),
            },
            commit=True,
        )
        return repaired_content, repaired_chunks or [repaired_content], clean_payload, repaired_tool_request

    def _repair_final_response_reference_issues(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        messages: list[AIChatMessage],
        content: str,
        chunks: list[str],
        model_payload: dict[str, Any],
        iteration: int,
        final_summary: bool,
    ) -> tuple[str, list[str], dict[str, Any], AgentToolRequest | None]:
        reference_context = self._final_response_test_case_reference_context(run.run_id)
        if reference_context is None:
            return content, chunks, model_payload, None
        invalid_ids = _invalid_test_case_ids_in_final_response(
            content,
            valid_ids=set(reference_context["valid_test_case_ids"]),
        )
        if not invalid_ids:
            return content, chunks, model_payload, None

        trace_payload = _model_trace_from_payload(model_payload)
        runtime.append_event(
            run,
            "model.final_response_reference_invalid",
            {
                "iteration": iteration,
                "final_summary": final_summary,
                "invalid_test_case_ids": invalid_ids,
                "valid_test_case_ids": reference_context["valid_test_case_ids"],
                "source_tool_call_id": reference_context["tool_call_id"],
                "content_preview": _bounded_agent_content_preview(
                    content,
                    reference="AgentConversationRunner.model.final_response_reference_invalid.content",
                ),
                **trace_payload,
            },
            commit=True,
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return content, [], model_payload, None

        repair_messages = [
            *messages,
            AIChatMessage(role="assistant", content=_bounded_repair_context(content)),
            AIChatMessage(
                role="user",
                content=(
                    "上一条最终回复引用了不存在于最新 testcase.query_project_cases 工具结果中的测试用例 ID。"
                    f"无效 ID：{invalid_ids}。"
                    "请重写最终用户回复：只能使用下面 authoritative_case_display_rows 中的 id/name/method/path/status；"
                    "不要按连续数字区间补全，不要复用旧对话中的用例名称或 ID。"
                    f"\nauthoritative_valid_test_case_ids={reference_context['valid_test_case_ids']}"
                    f"\nauthoritative_case_display_rows={json.dumps(reference_context['case_display_rows'], ensure_ascii=False, default=str)}"
                ),
            ),
        ]
        repaired_content, repaired_chunks, repaired_payload = self._stream_model_response(
            run=run,
            messages=repair_messages,
            runtime=runtime,
            iteration=iteration,
            final_summary=final_summary,
            repair_attempt=True,
            suppress_visible_deltas=True,
            loop_step="final_response_reference_repair",
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            return repaired_content, repaired_chunks, repaired_payload, None
        clean_payload = {key: value for key, value in repaired_payload.items() if value is not None}
        try:
            repaired_tool_request, repair_strategy = self._parse_repaired_tool_request(repaired_content)
        except HTTPException as exc:
            if not _looks_like_tool_request_content(repaired_content):
                raise
            repair_error_message = _bounded_agent_error_message(
                _http_exception_detail(exc),
                reference="AgentConversationRunner.model.final_response_reference_tool_request_repair_failed",
            )
            runtime.append_event(
                run,
                "model.final_response_reference_repair_failed",
                {
                    "iteration": iteration,
                    "final_summary": final_summary,
                    "invalid_test_case_ids": invalid_ids,
                    "valid_test_case_ids": reference_context["valid_test_case_ids"],
                    "source_tool_call_id": reference_context["tool_call_id"],
                    "error_message": repair_error_message,
                    "content_preview": _bounded_agent_content_preview(
                        repaired_content,
                        reference="AgentConversationRunner.model.final_response_reference_tool_request_repair_failed.content",
                    ),
                    **_model_trace_from_payload(clean_payload),
                },
                commit=True,
            )
            repaired_content = AGENT_FINAL_RESPONSE_REFERENCE_REPAIR_FALLBACK
            repaired_chunks = [repaired_content] if chunks else []
            repaired_tool_request = None
        if repaired_tool_request is not None:
            runtime.append_event(
                run,
                "model.final_response_reference_tool_request_repaired",
                {
                    "iteration": iteration,
                    "final_summary": final_summary,
                    "requested_tool": True,
                    "tool_name": repaired_tool_request.tool_name,
                    "source_tool_call_id": reference_context["tool_call_id"],
                    **({"repair_strategy": repair_strategy} if repair_strategy else {}),
                    **_model_trace_from_payload(clean_payload),
                },
                commit=True,
            )
            return repaired_content, [], clean_payload, repaired_tool_request
        repaired_content = _normalize_agent_markdown_response(repaired_content)
        repaired_invalid_ids = _invalid_test_case_ids_in_final_response(
            repaired_content,
            valid_ids=set(reference_context["valid_test_case_ids"]),
        )
        if repaired_invalid_ids:
            runtime.append_event(
                run,
                "model.final_response_reference_repair_failed",
                {
                    "iteration": iteration,
                    "final_summary": final_summary,
                    "invalid_test_case_ids": repaired_invalid_ids,
                    "valid_test_case_ids": reference_context["valid_test_case_ids"],
                    "source_tool_call_id": reference_context["tool_call_id"],
                    "content_preview": _bounded_agent_content_preview(
                        repaired_content,
                        reference="AgentConversationRunner.model.final_response_reference_repair_failed.content",
                    ),
                    **_model_trace_from_payload(clean_payload),
                },
                commit=True,
            )
            repaired_content = AGENT_FINAL_RESPONSE_REFERENCE_REPAIR_FALLBACK
            repaired_chunks = [repaired_content] if chunks else []
        runtime.append_event(
            run,
            "model.markdown_normalized",
            {
                "iteration": iteration,
                "final_summary": final_summary,
                "original_length": len(content),
                "normalized_length": len(repaired_content),
                "content": repaired_content,
                "replace_content": True,
                "normalization_reason": "final_response_reference_repaired",
                **_model_trace_from_payload(clean_payload),
            },
            commit=False,
        )
        return repaired_content, [repaired_content] if chunks else repaired_chunks, clean_payload, None

    def _final_response_test_case_reference_context(self, run_id: str) -> dict[str, Any] | None:
        calls = list(
            self.db.scalars(
                select(AgentToolCall)
                .where(
                    AgentToolCall.run_id == run_id,
                    AgentToolCall.tool_name == "testcase.query_project_cases",
                    AgentToolCall.status == "succeeded",
                )
                .order_by(AgentToolCall.created_at.asc(), AgentToolCall.id.asc())
            ).all()
        )
        if not calls:
            return None

        valid_ids: list[int] = []
        case_rows_by_id: dict[int, dict[str, Any]] = {}
        latest_tool_call_id = calls[-1].tool_call_id
        for call in calls:
            if not isinstance(call.output_json_redacted, dict):
                continue
            output = call.output_json_redacted
            manifest = output.get("case_id_manifest") if isinstance(output.get("case_id_manifest"), dict) else {}
            call_valid_ids = _coerce_int_list(manifest.get("http_test_case_ids")) + _coerce_int_list(
                manifest.get("websocket_test_case_ids")
            )
            if not call_valid_ids:
                call_valid_ids = _coerce_int_list(output.get("http_test_case_ids")) + _coerce_int_list(
                    output.get("websocket_test_case_ids")
                )
            valid_ids.extend(call_valid_ids)
            case_display_rows = output.get("case_display_rows")
            if isinstance(case_display_rows, list):
                for row in case_display_rows:
                    if not isinstance(row, dict):
                        continue
                    try:
                        case_id = int(row.get("id"))
                    except (TypeError, ValueError):
                        continue
                    case_rows_by_id[case_id] = row

        merged_valid_ids = sorted(dict.fromkeys(valid_ids))
        if not merged_valid_ids:
            return None
        return {
            "tool_call_id": latest_tool_call_id,
            "valid_test_case_ids": merged_valid_ids,
            "case_display_rows": [case_rows_by_id[case_id] for case_id in merged_valid_ids if case_id in case_rows_by_id],
        }

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

    def _parse_repaired_tool_request(self, content: str) -> tuple[AgentToolRequest | None, str | None]:
        if not (content or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="tool request repair returned empty content",
            )
        try:
            return self._parse_tool_request(content, normalize_evidence_refs=True), None
        except HTTPException:
            salvaged_internal_summary = self._try_salvage_internal_tool_context_summary(content)
            if salvaged_internal_summary is not None:
                return salvaged_internal_summary, "salvaged_repair_internal_tool_context_summary"
            salvaged_json_tool_request = self._try_salvage_tool_request_json(content)
            if salvaged_json_tool_request is not None:
                return salvaged_json_tool_request, "salvaged_repair_tool_request_json"
            salvaged_tool_request = self._try_salvage_mixed_tool_request(content)
            if salvaged_tool_request is not None:
                return salvaged_tool_request, "salvaged_repair_fenced_tool_request"
            salvaged_first_tool_request = self._try_salvage_first_tool_request_block(content)
            if salvaged_first_tool_request is not None:
                return salvaged_first_tool_request, "salvaged_repair_first_tool_request_block"
            raise

    def _try_salvage_first_tool_request_block(self, content: str) -> AgentToolRequest | None:
        first_match = TOOL_REQUEST_BLOCK_RE.search(content)
        if first_match is None or TOOL_REQUEST_BLOCK_RE.search(content, first_match.end()) is None:
            return None
        try:
            return self._parse_tool_request(
                first_match.group(0),
                normalize_evidence_refs=True,
            )
        except HTTPException:
            return None

    def _try_salvage_mixed_tool_request(
        self,
        content: str,
        *,
        normalize_single_evidence_ref_object: bool = True,
    ) -> AgentToolRequest | None:
        match = TOOL_REQUEST_BLOCK_RE.search(content)
        if match is None:
            return self._try_salvage_tool_request_json(
                content,
                allow_surrounding_text=True,
                normalize_single_evidence_ref_object=normalize_single_evidence_ref_object,
            )
        if TOOL_REQUEST_BLOCK_RE.search(content, match.end()):
            return None
        surrounding = (content[:match.start()] + content[match.end():]).strip()
        if not surrounding:
            return None
        try:
            return self._parse_tool_request(
                content,
                allow_surrounding_text=True,
                normalize_evidence_refs=True,
                normalize_single_evidence_ref_object=normalize_single_evidence_ref_object,
            )
        except HTTPException:
            return self._try_salvage_tool_request_json(
                content,
                allow_surrounding_text=True,
                normalize_single_evidence_ref_object=normalize_single_evidence_ref_object,
            )

    def _try_salvage_internal_tool_context_summary(self, content: str) -> AgentToolRequest | None:
        payload = _internal_tool_context_summary_payload(content)
        if payload is None:
            return None
        tool_name = payload.get("tool_name")
        input_json = payload.get("input_json")
        if not isinstance(tool_name, str) or not isinstance(input_json, str):
            return None
        if AGENT_CONTENT_PREVIEW_TRUNCATION_MARKER in input_json:
            return None
        try:
            tool_input = json.loads(input_json)
        except ValueError:
            return None
        if not isinstance(tool_input, dict):
            return None

        evidence_refs: Any = []
        evidence_refs_json = payload.get("evidence_refs_json")
        if isinstance(evidence_refs_json, str) and AGENT_CONTENT_PREVIEW_TRUNCATION_MARKER not in evidence_refs_json:
            try:
                parsed_refs = json.loads(evidence_refs_json)
            except ValueError:
                parsed_refs = []
            if isinstance(parsed_refs, list):
                evidence_refs = parsed_refs

        try:
            return _tool_request_from_payload(
                {
                    "tool_name": tool_name,
                    "input": tool_input,
                    "reason": payload.get("reason") if isinstance(payload.get("reason"), str) else None,
                    "evidence_refs": evidence_refs,
                },
                normalize_evidence_refs=True,
                normalize_single_evidence_ref_object=False,
            )
        except HTTPException:
            return None

    def _try_salvage_tool_request_json(
        self,
        content: str,
        *,
        allow_surrounding_text: bool = False,
        normalize_single_evidence_ref_object: bool = True,
    ) -> AgentToolRequest | None:
        body: str | None = None
        match = TOOL_REQUEST_FENCE_RE.search(content)
        if match:
            if TOOL_REQUEST_FENCE_RE.search(content, match.end()):
                return None
            surrounding = (content[:match.start()] + content[match.end():]).strip()
            if surrounding and not allow_surrounding_text:
                return None
            body = match.group("body").strip()
        else:
            stripped = content.strip()
            if stripped.startswith("{") and '"tool_name"' in stripped:
                body = stripped
        if body is None:
            return None
        payload = _try_repair_tool_request_json_payload(body)
        if payload is None:
            return None
        try:
            return _tool_request_from_payload(
                payload,
                normalize_evidence_refs=True,
                normalize_single_evidence_ref_object=normalize_single_evidence_ref_object,
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
        execution_plan_id: str | None = None,
    ) -> AgentToolCall:
        runtime = AgentRuntimeService(self.db)
        tool_input = self._normalize_tool_input(
            run=run,
            tool_name=tool_request.tool_name,
            tool_input=tool_request.input_for_ledger(),
        )
        plan_payload = agent_execution_plan_payload(
            run=run,
            iteration=iteration,
            tool_name=tool_request.tool_name,
            tool_input=tool_input,
            reason=tool_request.reason,
            evidence_refs=tool_request.evidence_refs_for_ledger(),
            plan_id=execution_plan_id,
        )
        runtime.append_event(
            run,
            "planner.execution_plan_created",
            plan_payload,
            commit=True,
        )
        self.db.refresh(run)
        if run.status in RUN_TERMINAL_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="run already terminal")
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=run.run_id,
                capability_plan_id=run.active_capability_plan_id,
                tool_name=tool_request.tool_name,
                input=tool_input,
                step_index=run.current_step_index,
                attempt_index=iteration,
                evidence_refs=tool_request.evidence_refs_for_ledger(),
            ),
            current_user=current_user,
            enqueue=False,
        )
        trace_info(
            "agent_trace_tool_call_created",
            run_id=run.run_id,
            project_id=run.project_id,
            iteration=iteration,
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            step_index=call.step_index,
            attempt_index=call.attempt_index,
            approval_required=call.approval_required,
            side_effect_class=call.resolved_side_effect_class,
            replay_policy=call.resolved_replay_policy,
            evidence_ref_count=len(tool_request.evidence_refs_for_ledger()),
            **trace_payload_summary(tool_input, prefix="input"),
        )
        trace_full_payload(
            "agent_trace_tool_input_full_payload",
            tool_input,
            prefix="input",
            mask=True,
            run_id=run.run_id,
            project_id=run.project_id,
            iteration=iteration,
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            step_index=call.step_index,
            attempt_index=call.attempt_index,
            approval_required=call.approval_required,
            side_effect_class=call.resolved_side_effect_class,
            replay_policy=call.resolved_replay_policy,
            evidence_ref_count=len(tool_request.evidence_refs_for_ledger()),
        )
        if call.status not in TOOL_CALL_EXECUTABLE_STATUSES:
            trace_warning(
                "agent_trace_tool_call_preflight_blocked_before_approval",
                run_id=run.run_id,
                project_id=run.project_id,
                iteration=iteration,
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                status=call.status,
                error_code=call.error_code,
                execution_phase=call.execution_phase,
                recovery_decision=call.recovery_decision,
            )
            run.current_iteration = iteration + 1
            run.current_step_index += 1
            self.db.commit()
            self.db.refresh(run)
            self.db.refresh(call)
            return call
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
        blocked_by_case_ids = ToolExecutor(self.db)._reject_case_reference_ids_without_current_facts(
            call=call,
            run=run,
            queue_item=None,
            queue_service=AgentWorkerQueueService(self.db),
            runtime=runtime,
        )
        if blocked_by_case_ids is not None:
            trace_warning(
                "agent_trace_tool_call_blocked",
                run_id=run.run_id,
                project_id=run.project_id,
                iteration=iteration,
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                status=call.status,
                error_code=call.error_code,
                execution_phase=call.execution_phase,
                recovery_decision=call.recovery_decision,
            )
            run.current_iteration = iteration + 1
            run.current_step_index += 1
            self.db.commit()
            self.db.refresh(run)
            self.db.refresh(call)
            return call
        if call.approval_required:
            trace_info(
                "agent_trace_tool_call_needs_human",
                run_id=run.run_id,
                project_id=run.project_id,
                iteration=iteration,
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                side_effect_class=call.resolved_side_effect_class,
                replay_policy=call.resolved_replay_policy,
            )
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

        missing_context_requirement = self._missing_context_requirement_before_execution(run=run, call=call)
        if missing_context_requirement is not None:
            spec = ToolRegistry().get(call.tool_name)
            missing_prerequisite_tool = missing_context_requirement.primary_required_tool or missing_context_requirement.name
            error_code = (
                missing_context_requirement.missing_error_code
                or spec.missing_prerequisite_error_code
                or "tool_prerequisite_required"
            )
            next_action = missing_context_requirement.missing_next_action or spec.missing_prerequisite_next_action or (
                f"Call {missing_prerequisite_tool} before calling {call.tool_name}."
            )
            trace_warning(
                "agent_trace_tool_call_prerequisite_missing",
                run_id=run.run_id,
                project_id=run.project_id,
                iteration=iteration,
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                required_tool=missing_prerequisite_tool,
            )
            output = {
                "required_tool": missing_prerequisite_tool,
                "required_context_requirement": missing_context_requirement.name,
                "blocked_tool": call.tool_name,
                "next_action": next_action,
            }
            call.status = "failed"
            call.execution_phase = "blocked_by_harness"
            call.error_code = error_code
            call.error_message = (
                f"{call.tool_name} requires context requirement {missing_context_requirement.name} "
                "before execution."
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
        trace_info(
            "agent_trace_tool_call_executed",
            run_id=run.run_id,
            project_id=run.project_id,
            iteration=iteration,
            tool_call_id=executed.tool_call_id,
            tool_name=executed.tool_name,
            status=executed.status,
            execution_phase=executed.execution_phase,
            error_code=executed.error_code,
            **trace_payload_summary(executed.output_json_redacted, prefix="output"),
        )
        trace_verbose_payload(
            "agent_trace_tool_output_payload",
            executed.output_json_redacted,
            prefix="output",
            mask=True,
            run_id=run.run_id,
            project_id=run.project_id,
            iteration=iteration,
            tool_call_id=executed.tool_call_id,
            tool_name=executed.tool_name,
            status=executed.status,
            execution_phase=executed.execution_phase,
            error_code=executed.error_code,
            output_hash=executed.output_hash,
        )
        trace_full_payload(
            "agent_trace_tool_output_full_payload",
            executed.output_json_redacted,
            prefix="output",
            mask=True,
            run_id=run.run_id,
            project_id=run.project_id,
            iteration=iteration,
            tool_call_id=executed.tool_call_id,
            tool_name=executed.tool_name,
            status=executed.status,
            execution_phase=executed.execution_phase,
            error_code=executed.error_code,
            output_hash=executed.output_hash,
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
        tool_input = dict(tool_input)
        spec = ToolRegistry().get(tool_name)
        required = set((spec.input_schema or {}).get("required") or [])
        if "project_id" in required and "project_id" not in tool_input:
            tool_input["project_id"] = run.project_id
        if tool_name in {"scenario.create_saved", "scenario.update_saved"}:
            explicit_source = self._scenario_from_explicit_source(run=run, tool_input=tool_input)
            if explicit_source is not None:
                original_scenario = tool_input.get("scenario") if isinstance(tool_input.get("scenario"), dict) else {}
                scenario = copy.deepcopy(explicit_source["scenario"])
                if tool_name == "scenario.update_saved" and isinstance(original_scenario, dict):
                    version = original_scenario.get("version")
                    if version is not None:
                        scenario["version"] = version
                tool_input["scenario"] = scenario
                draft_source = {
                    "source": "artifact_reference" if explicit_source.get("artifact_id") else "tool_call_scenario_source",
                    "run_id": explicit_source["run_id"],
                    "tool_call_id": explicit_source["tool_call_id"],
                    "path": explicit_source["path"],
                    "output_hash": explicit_source["output_hash"],
                }
                if explicit_source.get("artifact_id"):
                    draft_source["artifact_id"] = explicit_source["artifact_id"]
                if explicit_source.get("artifact_type"):
                    draft_source["artifact_type"] = explicit_source["artifact_type"]
                tool_input["scenario_draft_source"] = draft_source
                return tool_input
            draft = self._latest_reusable_scenario_draft(run)
            if draft is not None and _intent_requests_latest_scenario_draft(run.intent):
                original_scenario = tool_input.get("scenario") if isinstance(tool_input.get("scenario"), dict) else {}
                scenario = copy.deepcopy(draft["scenario"])
                if tool_name == "scenario.update_saved" and isinstance(original_scenario, dict):
                    version = original_scenario.get("version")
                    if version is not None:
                        scenario["version"] = version
                tool_input["scenario"] = scenario
                tool_input["scenario_draft_source"] = {
                    "source": "latest_conversation_scenario_compose_draft",
                    "run_id": draft["run_id"],
                    "tool_call_id": draft["tool_call_id"],
                }
        return tool_input

    def _scenario_from_explicit_source(self, *, run: AgentRun, tool_input: dict[str, Any]) -> dict[str, Any] | None:
        source = tool_input.get("scenario_source")
        if not isinstance(source, dict):
            source = tool_input.get("source_artifact")
        if not isinstance(source, dict):
            return None
        artifact_id = str(source.get("artifact_id") or source.get("id") or "").strip()
        artifact_type = ""
        tool_call_id = str(source.get("tool_call_id") or "").strip()
        if artifact_id and not tool_call_id:
            parsed_artifact = _parse_tool_artifact_id(artifact_id)
            if parsed_artifact is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"code": "scenario_source_artifact_id_invalid", "artifact_id": artifact_id},
                )
            artifact_type = parsed_artifact["artifact_type"]
            if artifact_type != "scenario_draft":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "scenario_source_artifact_type_invalid",
                        "artifact_id": artifact_id,
                        "artifact_type": artifact_type,
                    },
                )
            tool_call_id = parsed_artifact["tool_call_id"]
        if not tool_call_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "scenario_source_tool_call_id_required"},
            )
        path = str(source.get("path") or source.get("output_path") or "draft.scenario").strip()
        expected_hash = str(source.get("output_hash") or "").strip()
        row = self.db.execute(
            select(AgentToolCall, AgentRun)
            .join(AgentRun, AgentRun.run_id == AgentToolCall.run_id)
            .where(
                AgentToolCall.tool_call_id == tool_call_id,
                AgentToolCall.status == "succeeded",
                AgentRun.project_id == run.project_id,
                AgentRun.user_id == run.user_id,
                AgentRun.id <= run.id,
            )
        ).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "scenario_source_tool_call_not_found", "tool_call_id": tool_call_id},
            )
        call, source_run = row
        if expected_hash and expected_hash != str(call.output_hash or ""):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "scenario_source_output_hash_mismatch",
                    "tool_call_id": tool_call_id,
                    "expected_hash": expected_hash,
                    "actual_hash": call.output_hash,
                },
            )
        try:
            scenario = _json_path_get(call.output_json_redacted, path)
        except HTTPException:
            raise
        if not isinstance(scenario, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "scenario_source_path_not_object", "tool_call_id": tool_call_id, "path": path},
            )
        try:
            validated = ScenarioCreateRequest.model_validate(scenario)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "scenario_source_schema_invalid", "errors": exc.errors()},
            ) from exc
        return {
            "scenario": validated.model_dump(mode="json"),
            "run_id": source_run.run_id,
            "tool_call_id": call.tool_call_id,
            "path": path,
            "output_hash": call.output_hash,
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
        }

    def _latest_reusable_scenario_draft(self, run: AgentRun) -> dict[str, Any] | None:
        if not run.conversation_id:
            return None
        calls = list(
            self.db.scalars(
                select(AgentToolCall)
                .join(AgentRun, AgentRun.run_id == AgentToolCall.run_id)
                .where(
                    AgentRun.project_id == run.project_id,
                    AgentRun.user_id == run.user_id,
                    AgentRun.conversation_id == run.conversation_id,
                    AgentRun.id <= run.id,
                    AgentToolCall.tool_name == "scenario.compose_draft",
                    AgentToolCall.status == "succeeded",
                )
                .order_by(AgentToolCall.id.desc())
                .limit(10)
            ).all()
        )
        reusable: list[dict[str, Any]] = []
        for call in calls:
            scenario = _scenario_from_compose_draft_output(call.output_json_redacted)
            if scenario is None:
                continue
            try:
                validated = ScenarioCreateRequest.model_validate(scenario)
            except ValidationError:
                continue
            candidate = {
                "scenario": validated.model_dump(mode="json"),
                "run_id": call.run_id,
                "tool_call_id": call.tool_call_id,
            }
            if _scenario_name_matches_intent(candidate["scenario"], run.intent):
                return candidate
            reusable.append(candidate)
        if reusable:
            return reusable[0]
        return None

    def _missing_tool_prerequisite_before_execution(self, *, run: AgentRun, call: AgentToolCall) -> str | None:
        missing_requirement = self._missing_context_requirement_before_execution(run=run, call=call)
        if missing_requirement is None:
            return None
        return missing_requirement.primary_required_tool or missing_requirement.name

    def _missing_context_requirement_before_execution(
        self,
        *,
        run: AgentRun,
        call: AgentToolCall,
    ) -> ToolContextRequirement | None:
        spec = ToolRegistry().get(call.tool_name)
        for requirement in spec.required_context_requirements:
            if not self._context_requirement_satisfied(run=run, call=call, requirement=requirement):
                return requirement
        return None

    def _context_requirement_satisfied(
        self,
        *,
        run: AgentRun,
        call: AgentToolCall,
        requirement: ToolContextRequirement,
    ) -> bool:
        return any(
            self._context_requirement_source_satisfied(run=run, call=call, source=source)
            for source in requirement.sources
        )

    def _context_requirement_source_satisfied(
        self,
        *,
        run: AgentRun,
        call: AgentToolCall,
        source: Any,
    ) -> bool:
        source_type = str(getattr(source, "source_type", "") or "")
        if source_type == "fresh_tool_execution":
            tool_name = getattr(source, "tool_name", None)
            return bool(
                tool_name
                and self._has_successful_tool_call(run, str(tool_name), before_tool_call_id=call.id)
            )
        if source_type in {"run_artifact", "conversation_artifact"}:
            return self._has_context_artifact(
                run=run,
                call=call,
                artifact_type=getattr(source, "artifact_type", None),
                artifact_class=getattr(source, "artifact_class", None),
                scope="conversation" if source_type == "conversation_artifact" else "run",
            )
        return False

    def _has_context_artifact(
        self,
        *,
        run: AgentRun,
        call: AgentToolCall,
        artifact_type: str | None,
        artifact_class: str | None,
        scope: str,
    ) -> bool:
        if not artifact_type:
            return False
        rows_query = (
            select(AgentToolCall, AgentRun)
            .join(AgentRun, AgentRun.run_id == AgentToolCall.run_id)
            .where(
                AgentRun.project_id == run.project_id,
                AgentRun.user_id == run.user_id,
                AgentToolCall.status == "succeeded",
            )
            .order_by(AgentToolCall.id.desc())
        )
        if scope == "conversation":
            if not run.conversation_id:
                return False
            rows_query = rows_query.where(
                AgentRun.conversation_id == run.conversation_id,
                AgentRun.id <= run.id,
            )
        else:
            rows_query = rows_query.where(AgentRun.run_id == run.run_id)

        rows = self.db.execute(rows_query.limit(AGENT_CONVERSATION_TOOL_ARTIFACT_MANIFEST_MAX_CALLS)).all()
        for source_call, source_run in rows:
            if source_run.id == run.id and source_call.id >= call.id:
                continue
            manifest = _tool_call_artifact_manifest(source_call, source_run)
            if not manifest:
                continue
            if manifest.get("artifact_type") != artifact_type:
                continue
            if artifact_class and manifest.get("artifact_class") != artifact_class:
                continue
            return True
        return False

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
        runtime_snapshot = self.db.scalar(
            select(AgentRuntimeSnapshot).where(
                AgentRuntimeSnapshot.snapshot_id == run.runtime_snapshot_id,
                AgentRuntimeSnapshot.project_id == run.project_id,
            )
        )
        frozen_skill_manifests = (
            (runtime_snapshot.manifests_json or {}).get("skills")
            if runtime_snapshot is not None
            else None
        )
        skill_registry = (
            AgentSkillRegistry.from_snapshot_manifests(frozen_skill_manifests)
            if isinstance(frozen_skill_manifests, dict) and frozen_skill_manifests
            else AgentSkillRegistry()
        )
        context_manager = AgentContextManager(skill_registry=skill_registry)
        messages = [AIChatMessage(role="system", content=_conversation_static_system_prompt())]
        messages.append(AIChatMessage(role="system", content=_format_run_context(run)))
        working_context: dict[str, Any] | None = None
        previous_runs: list[AgentRun] = []
        previous_state_runs: list[AgentRun] = []
        tool_artifact_manifests: list[dict[str, Any]] = []
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
            previous_state_runs = list(
                self.db.scalars(
                    select(AgentRun)
                    .where(
                        AgentRun.project_id == run.project_id,
                        AgentRun.conversation_id == run.conversation_id,
                        AgentRun.id < run.id,
                        AgentRun.status.in_(AGENT_WORKING_CONTEXT_STATE_STATUSES),
                    )
                    .order_by(AgentRun.id.desc())
                    .limit(AGENT_HISTORY_CONTEXT_MAX_RUNS)
                ).all()
            )
            previous_state_runs = list(reversed(previous_state_runs))
            tool_artifact_manifests = self._conversation_tool_artifact_manifests(run)
            working_context = _conversation_working_context(
                current_intent=run.intent,
                previous_runs=previous_state_runs,
                tool_artifact_manifests=tool_artifact_manifests,
            )
        capability_plan_service = AgentCapabilityPlanService(self.db)
        active_plan_record = None
        planning_decision: ValidatedAgentPlanningDecision | None = None
        intent_decision: ValidatedAgentIntentDecision | None = None
        if run.active_capability_plan_id:
            active_plan_record = capability_plan_service.get_active_plan(run=run)
            if active_plan_record.intent_decision_json.get("selected_skills"):
                planning_decision = _validated_planning_decision_from_plan(active_plan_record.intent_decision_json)
                context_plan = context_manager.route_planning_decision(
                    run.intent,
                    decision=planning_decision,
                )
            else:
                intent_decision = _validated_intent_decision_from_plan(active_plan_record.intent_decision_json)
                context_plan = context_manager.route(
                    run.intent,
                    working_context=working_context,
                    intent_action=intent_decision.as_intent_action(),
                )
        elif settings.AGENT_LLM_INTENT_DECISION_ENABLED:
            planning_decision = self._resolve_planning_decision(
                run=run,
                current_user=current_user,
                runtime=runtime,
                working_context=working_context,
                tool_artifact_manifests=tool_artifact_manifests,
            )
            context_plan = context_manager.route_planning_decision(
                run.intent,
                decision=planning_decision,
            )
        else:
            intent_decision = self._resolve_intent_decision(
                run=run,
                runtime=runtime,
                working_context=working_context,
            )
            context_plan = context_manager.route(
                run.intent,
                working_context=working_context,
                intent_action=intent_decision.as_intent_action(),
            )
        if active_plan_record is None:
            decision_to_persist = planning_decision or intent_decision
            if decision_to_persist is None:
                raise AgentPlanningFailed(
                    last_error=AgentPlanningError(
                        "runtime did not produce a planning decision",
                        code="planner_decision_missing",
                    )
                )
            active_plan_record = capability_plan_service.create_active_plan(
                run=run,
                iteration=run.current_iteration,
                context_plan=context_plan,
                intent_decision=decision_to_persist,
                source=decision_to_persist.source,
            )
            runtime.append_event(
                run,
                "planner.capability_plan_created",
                {
                    "capability_plan_id": active_plan_record.capability_plan_id,
                    "iteration": run.current_iteration,
                    "revision": active_plan_record.revision,
                    "source": active_plan_record.source,
                    "plan_hash": active_plan_record.plan_hash,
                },
                commit=True,
            )
            self.db.refresh(run)
        messages.append(context_manager.skill_plan_message(context_plan))
        messages.append(context_manager.tool_catalog_message(context_plan))
        messages.append(context_manager.capability_plan_message(context_plan))
        messages.append(_capability_plan_identity_message(
            capability_plan_id=active_plan_record.capability_plan_id,
            plan_hash=active_plan_record.plan_hash,
            iteration=active_plan_record.iteration,
        ))
        messages.append(context_manager.skill_catalog_message(context_plan))
        tool_contract_message = context_manager.tool_contract_message(
            context_plan,
            input_summary_builder=_tool_input_summary,
        )
        if tool_contract_message is not None:
            messages.append(tool_contract_message)
        messages.extend(context_manager.skill_messages(context_plan))
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
                assistant_transform=lambda previous, assistant: _assistant_history_for_working_context(
                    previous,
                    assistant,
                    working_context=working_context,
                ),
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

    def _resolve_planning_decision(
        self,
        *,
        run: AgentRun,
        current_user: User,
        runtime: AgentRuntimeService,
        working_context: dict[str, Any] | None,
        tool_artifact_manifests: list[dict[str, Any]],
    ) -> ValidatedAgentPlanningDecision:
        snapshot = self.db.scalar(
            select(AgentRuntimeSnapshot).where(
                AgentRuntimeSnapshot.snapshot_id == run.runtime_snapshot_id,
                AgentRuntimeSnapshot.project_id == run.project_id,
            )
        )
        if snapshot is None:
            raise AgentPlanningFailed(
                last_error=AgentPlanningError(
                    "runtime snapshot is unavailable",
                    code="planner_runtime_snapshot_missing",
                )
            )
        frozen_skill_manifests = (snapshot.manifests_json or {}).get("skills")
        if isinstance(frozen_skill_manifests, dict) and frozen_skill_manifests:
            frozen_registry = AgentSkillRegistry.from_snapshot_manifests(frozen_skill_manifests)
            skill_index = [skill.planner_metadata() for skill in frozen_registry.list_skills()]
        else:
            # Compatibility only for runs created by pre-v2 snapshots.
            skill_index = [skill.planner_metadata() for skill in AgentSkillRegistry().list_skills()]
        tool_index = [
            {
                key: item.get(key)
                for key in (
                    "name",
                    "summary",
                    "side_effect_class",
                    "replay_policy",
                    "required_permissions",
                    "schema_hash",
                )
                if item.get(key) is not None
            }
            for item in snapshot.tools_json
            if isinstance(item, dict) and item.get("name")
        ]
        artifact_index = AgentArtifactResolver().model_handles(tool_artifact_manifests)
        permissions = self._project_permission_names(
            current_user=current_user,
            project_id=run.project_id,
        )
        runtime.append_event(
            run,
            "planner.llm_decision_started",
            {
                "project_id": run.project_id,
                "skill_count": len(skill_index),
                "tool_count": len(tool_index),
                "artifact_count": len(artifact_index),
            },
            commit=True,
        )
        self.db.refresh(run)
        try:
            def record_planning_event(event_type: str, payload: dict[str, Any]) -> None:
                runtime.append_event(
                    run,
                    f"planner.llm_decision_{event_type}",
                    payload,
                    commit=True,
                )
                self.db.refresh(run)

            decision = self.planning_decision_service.decide(
                intent=run.intent,
                conversation_context=working_context,
                skill_index=skill_index,
                tool_index=tool_index,
                artifact_index=artifact_index,
                project_id=run.project_id,
                permissions=permissions,
                on_event=record_planning_event,
            )
        except AgentPlanningFailed as exc:
            runtime.append_event(
                run,
                "planner.llm_decision_failed",
                {
                    "code": exc.code,
                    "details": exc.details,
                },
                commit=True,
            )
            raise
        runtime.append_event(
            run,
            "planner.llm_decision_completed",
            decision.model_view(),
            commit=True,
        )
        self.db.refresh(run)
        return decision

    def _resolve_intent_decision(
        self,
        *,
        run: AgentRun,
        runtime: AgentRuntimeService,
        working_context: dict[str, Any] | None,
    ) -> ValidatedAgentIntentDecision:
        if settings.AGENT_LLM_INTENT_DECISION_ENABLED:
            raise AgentPlanningFailed(
                last_error=AgentPlanningError(
                    "legacy intent router is unavailable while unified LLM planning is enabled",
                    code="planner_legacy_router_disabled",
                )
            )
        fallback = parse_agent_intent_action(run.intent, working_context=working_context)
        return ValidatedAgentIntentDecision(
            action=fallback.action,
            target_domain=fallback.target_domain,
            source_domains=fallback.source_domains,
            confidence=fallback.confidence,
            source="deterministic_fallback",
            reason_codes=(*fallback.reason_codes, "intent_decision:deterministic_fallback"),
            write_authorized=True,
        )

    def _conversation_tool_artifact_manifests(self, run: AgentRun) -> list[dict[str, Any]]:
        if not run.conversation_id:
            return []
        rows = list(
            self.db.execute(
                select(AgentToolCall, AgentRun)
                .join(AgentRun, AgentRun.run_id == AgentToolCall.run_id)
                .where(
                    AgentRun.project_id == run.project_id,
                    AgentRun.user_id == run.user_id,
                    AgentRun.conversation_id == run.conversation_id,
                    AgentRun.id <= run.id,
                    AgentToolCall.status == "succeeded",
                )
                .order_by(AgentToolCall.id.desc())
                .limit(AGENT_CONVERSATION_TOOL_ARTIFACT_MANIFEST_MAX_CALLS)
            ).all()
        )
        manifests: list[dict[str, Any]] = []
        for call, source_run in reversed(rows):
            manifest = _tool_call_artifact_manifest(call, source_run)
            if manifest is not None:
                manifests.append(manifest)
        return _prioritize_tool_artifact_manifests_for_context(manifests)

    def _conversation_history_messages(
        self,
        *,
        previous_runs: list[AgentRun],
        compaction_window_metadata: Callable[[], dict[str, Any]] | dict[str, Any] | None = None,
        assistant_transform: Callable[[AgentRun, str], str] | None = None,
    ) -> tuple[list[AIChatMessage], dict[str, Any] | None]:
        pairs = [
            {
                "run_id": previous.run_id,
                "status": previous.status,
                "intent": previous.intent,
                "assistant": (
                    assistant_transform(previous, _assistant_message_from_run(previous) or "")
                    if assistant_transform is not None
                    else (_assistant_message_from_run(previous) or "")
                ),
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

        capability_plan_id = payload.capability_plan_id or run.active_capability_plan_id
        if capability_plan_id is not None:
            AgentCapabilityPlanService(self.db).require_tool_membership(
                run=run,
                capability_plan_id=capability_plan_id,
                tool_name=payload.tool_name,
            )

        spec = self.tool_registry.get(payload.tool_name)
        resolved = self.policy_resolver.resolve(spec=spec, evidence_refs=payload.evidence_refs)
        input_repair = DeterministicToolInputRepairEngine().repair(
            tool_name=payload.tool_name,
            tool_input=payload.input,
        )
        tool_input = input_repair.input
        input_hash_before_repair = request_fingerprint(payload.input)
        idempotency_key = payload.idempotency_key or request_fingerprint({
            "run_id": payload.run_id,
            "step_index": payload.step_index,
            "attempt_index": payload.attempt_index,
            "tool_name": payload.tool_name,
            "input": tool_input,
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
        input_hash = request_fingerprint(tool_input)
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
            capability_plan_id=capability_plan_id,
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
            input_json_redacted=_protected_tool_input_for_storage(spec.name, tool_input),
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
                "input_hash": input_hash,
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
        if input_repair.repairs:
            runtime.append_event(
                run,
                "tool.input_repaired",
                {
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                    "repair_engine": DETERMINISTIC_TOOL_INPUT_REPAIR_ENGINE_VERSION,
                    "strategy": (
                        input_repair.repairs[0]["strategy"]
                        if len(input_repair.repairs) == 1
                        else "multiple_deterministic_repairs"
                    ),
                    "repairs": input_repair.repairs,
                    "input_hash_before": input_hash_before_repair,
                    "input_hash_after": input_hash,
                },
                commit=False,
            )
        runtime.append_event(run, "tool.planned", {"tool_call_id": call.tool_call_id, "tool_name": call.tool_name}, commit=False)
        scenario_state_payload = _scenario_state_transition_for_tool_call(self.db, run=run, call=call)
        if scenario_state_payload is not None:
            runtime.append_event(run, "scenario.state_transition", scenario_state_payload, commit=False)
        if call.approval_required:
            executor = ToolExecutor(self.db)
            blocked_by_action_preflight = executor._reject_case_reference_ids_without_current_facts(
                call=call,
                run=run,
                queue_item=None,
                queue_service=AgentWorkerQueueService(self.db),
                runtime=runtime,
            )
            if blocked_by_action_preflight is not None:
                self.db.commit()
                self.db.refresh(call)
                return call
            blocked_by_schema_preflight = executor._reject_tool_input_schema_invalid_before_approval(
                call=call,
                run=run,
                runtime=runtime,
            )
            if blocked_by_schema_preflight is not None:
                self.db.refresh(call)
                return call
            blocked_by_scenario_quality_preflight = (
                executor._reject_scenario_orchestration_quality_missing_before_approval(
                    call=call,
                    run=run,
                    runtime=runtime,
                )
            )
            if blocked_by_scenario_quality_preflight is not None:
                self.db.refresh(call)
                return call
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
        payload = decrypt_sensitive(dict(call.input_json_redacted or {}))
        payload.setdefault("_agent_run_id", call.run_id)
        payload.setdefault("_agent_tool_call_id", call.tool_call_id)
        return self.backend_factory(self.db).execute(
            tool_name=call.tool_name,
            payload=payload,
            current_user=current_user,
        )


@dataclass(frozen=True)
class ObjectReferenceGuardRule:
    object_type: str
    query_tool: str
    db_model: type[Any]
    request_id_keys: tuple[str, ...]
    manifest_keys: tuple[str, ...]
    id_keys: tuple[str, ...]
    object_list_keys: tuple[str, ...]
    batch_result_paths: tuple[tuple[str, str], ...]
    valid_key: str
    invalid_key: str
    stale_key: str
    invalid_error_code: str
    stale_error_code: str
    snapshot_error_code: str
    invalid_error_message: str
    stale_error_message: str
    snapshot_error_message: str
    query_before_retry_decision: str
    refresh_before_retry_decision: str
    snapshot_before_retry_decision: str
    request_id_array_keys: tuple[str, ...] = ()
    request_snapshot_id_keys: tuple[str, ...] = ()
    request_item_list_key: str | None = None
    request_item_id_key: str | None = None
    request_nested_id_paths: tuple[tuple[str, ...], ...] = ()
    request_nested_id_array_paths: tuple[tuple[str, ...], ...] = ()
    request_nested_filtered_id_paths: tuple[tuple[tuple[str, ...], str, str, str], ...] = ()
    request_nested_snapshot_id_paths: tuple[tuple[str, ...], ...] = ()
    request_ref_keys: tuple[str, ...] = ("object_reference",)
    request_ref_array_keys: tuple[str, ...] = ("object_references",)
    not_deleted_attr: str | None = None


HTTP_TEST_CASE_REFERENCE_RULE = ObjectReferenceGuardRule(
    object_type="http_test_case",
    query_tool="testcase.query_project_cases",
    db_model=TestCase,
    request_id_keys=("test_case_id",),
    request_id_array_keys=("test_case_ids",),
    request_item_list_key="items",
    request_item_id_key="test_case_id",
    manifest_keys=("http_test_case_ids", "http_assertion_update_ids"),
    id_keys=("http_test_case_ids",),
    object_list_keys=("http_test_cases",),
    batch_result_paths=(("http_batch_execute_input", "test_case_ids"),),
    valid_key="valid_test_case_ids",
    invalid_key="invalid_test_case_ids",
    stale_key="stale_test_case_ids",
    invalid_error_code="agent_testcase_ids_not_from_query_result",
    stale_error_code="agent_testcase_id_stale_or_deleted",
    snapshot_error_code="agent_testcase_snapshot_not_latest",
    invalid_error_message="Test case ids must come from the latest testcase.query_project_cases result.",
    stale_error_message="Test case ids from the latest query are stale or deleted; refresh before execution.",
    snapshot_error_message="Test case snapshot id must match the latest testcase.query_project_cases result.",
    query_before_retry_decision="query_project_cases_before_retry",
    refresh_before_retry_decision="refresh_case_snapshot_before_retry",
    snapshot_before_retry_decision="refresh_case_snapshot_before_retry",
    request_snapshot_id_keys=("case_snapshot_id",),
)
WEBSOCKET_TEST_CASE_REFERENCE_RULE = ObjectReferenceGuardRule(
    object_type="websocket_test_case",
    query_tool="testcase.query_project_cases",
    db_model=WebSocketTestCase,
    request_id_keys=("test_case_id",),
    request_id_array_keys=("websocket_test_case_ids",),
    request_item_list_key="items",
    request_item_id_key="test_case_id",
    manifest_keys=("websocket_test_case_ids", "websocket_assertion_update_ids"),
    id_keys=("websocket_test_case_ids",),
    object_list_keys=("websocket_test_cases",),
    batch_result_paths=(("websocket_batch_execute_input", "websocket_test_case_ids"),),
    valid_key="valid_websocket_test_case_ids",
    invalid_key="invalid_websocket_test_case_ids",
    stale_key="stale_websocket_test_case_ids",
    invalid_error_code="agent_websocket_testcase_ids_not_from_query_result",
    stale_error_code="agent_websocket_testcase_id_stale_or_deleted",
    snapshot_error_code="agent_websocket_testcase_snapshot_not_latest",
    invalid_error_message="Test case ids must come from the latest testcase.query_project_cases result.",
    stale_error_message="Test case ids from the latest query are stale or deleted; refresh before execution.",
    snapshot_error_message="Test case snapshot id must match the latest testcase.query_project_cases result.",
    query_before_retry_decision="query_project_cases_before_retry",
    refresh_before_retry_decision="refresh_case_snapshot_before_retry",
    snapshot_before_retry_decision="refresh_case_snapshot_before_retry",
    request_snapshot_id_keys=("case_snapshot_id",),
)
FLOW_HTTP_TEST_CASE_REFERENCE_RULE = replace(
    HTTP_TEST_CASE_REFERENCE_RULE,
    request_id_keys=(),
    request_id_array_keys=(),
    request_item_list_key=None,
    request_item_id_key=None,
    request_nested_filtered_id_paths=(
        (("flow", "definition", "nodes", "*"), "kind", "api_case", "referenceId"),
        (("flow", "definition", "nodes", "*"), "kind", "api_case", "reference_id"),
    ),
    request_ref_keys=(),
    request_ref_array_keys=(),
)
FLOW_WEBSOCKET_TEST_CASE_REFERENCE_RULE = replace(
    WEBSOCKET_TEST_CASE_REFERENCE_RULE,
    request_id_keys=(),
    request_id_array_keys=(),
    request_item_list_key=None,
    request_item_id_key=None,
    request_nested_filtered_id_paths=(
        (("flow", "definition", "nodes", "*"), "kind", "websocket_case", "referenceId"),
        (("flow", "definition", "nodes", "*"), "kind", "websocket_case", "reference_id"),
    ),
    request_ref_keys=(),
    request_ref_array_keys=(),
)
SCENARIO_REFERENCE_RULE = ObjectReferenceGuardRule(
    object_type="scenario",
    query_tool="scenario.query_project_scenarios",
    db_model=TestScenario,
    request_id_keys=("scenario_id",),
    manifest_keys=("scenario_ids", "scenario_execute_ids"),
    id_keys=("scenario_ids",),
    object_list_keys=("scenarios",),
    batch_result_paths=(),
    not_deleted_attr="is_deleted",
    valid_key="valid_scenario_ids",
    invalid_key="invalid_scenario_ids",
    stale_key="stale_scenario_ids",
    invalid_error_code="agent_scenario_ids_not_from_query_result",
    stale_error_code="agent_scenario_id_stale_or_deleted",
    snapshot_error_code="agent_scenario_snapshot_not_latest",
    invalid_error_message="Scenario ids must come from the latest scenario.query_project_scenarios result.",
    stale_error_message="Scenario ids from the latest query are stale or deleted; refresh before execution.",
    snapshot_error_message="Scenario snapshot id must match the latest scenario.query_project_scenarios result.",
    query_before_retry_decision="query_project_scenarios_before_retry",
    refresh_before_retry_decision="refresh_scenario_snapshot_before_retry",
    snapshot_before_retry_decision="refresh_scenario_snapshot_before_retry",
    request_snapshot_id_keys=("scenario_snapshot_id",),
)
PLAN_SCENARIO_TARGET_REFERENCE_RULE = replace(
    SCENARIO_REFERENCE_RULE,
    request_id_keys=(),
    request_nested_id_paths=(("plan", "targets", "*", "reference_id"),),
    request_ref_keys=(),
    request_ref_array_keys=(),
)
ENVIRONMENT_REFERENCE_RULE = ObjectReferenceGuardRule(
    object_type="environment",
    query_tool="project.read_context",
    db_model=ProjectEnvironment,
    request_id_keys=("environment_id",),
    request_nested_id_paths=(
        ("case", "environment_id"),
        ("scenario", "environment_id"),
        ("flow", "definition", "environmentId"),
        ("flow", "definition", "environment_id"),
    ),
    request_nested_id_array_paths=(("case", "environment_ids"), ("plan", "environment_ids")),
    manifest_keys=("environment_ids", "environment_execute_ids"),
    id_keys=(),
    object_list_keys=("environments",),
    batch_result_paths=(),
    not_deleted_attr="is_deleted",
    valid_key="valid_environment_ids",
    invalid_key="invalid_environment_ids",
    stale_key="stale_environment_ids",
    invalid_error_code="agent_environment_ids_not_from_query_result",
    stale_error_code="agent_environment_id_stale_or_deleted",
    snapshot_error_code="agent_environment_snapshot_not_latest",
    invalid_error_message="Environment ids must come from the latest project.read_context result.",
    stale_error_message="Environment ids from the latest project context are stale or deleted; refresh before execution.",
    snapshot_error_message="Environment snapshot id must match the latest project.read_context result.",
    query_before_retry_decision="project_read_context_before_retry",
    refresh_before_retry_decision="refresh_project_context_before_retry",
    snapshot_before_retry_decision="refresh_project_context_before_retry",
    request_snapshot_id_keys=("environment_snapshot_id",),
    request_nested_snapshot_id_paths=(("case", "environment_snapshot_id"), ("scenario", "environment_snapshot_id")),
    request_ref_keys=("environment_reference",),
    request_ref_array_keys=("environment_references",),
)
PLAN_REFERENCE_RULE = ObjectReferenceGuardRule(
    object_type="test_plan",
    query_tool="plan.query_project_plans",
    db_model=TestPlan,
    request_id_keys=("plan_id",),
    manifest_keys=("plan_ids",),
    id_keys=("plan_ids",),
    object_list_keys=("plans",),
    batch_result_paths=(),
    not_deleted_attr="is_deleted",
    valid_key="valid_plan_ids",
    invalid_key="invalid_plan_ids",
    stale_key="stale_plan_ids",
    invalid_error_code="agent_plan_ids_not_from_query_result",
    stale_error_code="agent_plan_id_stale_or_deleted",
    snapshot_error_code="agent_plan_snapshot_not_latest",
    invalid_error_message="Plan ids must come from the latest plan.query_project_plans result.",
    stale_error_message="Plan ids from the latest query are stale or deleted; refresh before execution.",
    snapshot_error_message="Plan snapshot id must match the latest plan.query_project_plans result.",
    query_before_retry_decision="query_project_plans_before_retry",
    refresh_before_retry_decision="refresh_plan_snapshot_before_retry",
    snapshot_before_retry_decision="refresh_plan_snapshot_before_retry",
    request_snapshot_id_keys=("plan_snapshot_id",),
)
PLAN_RUN_REFERENCE_RULE = ObjectReferenceGuardRule(
    object_type="test_plan_run",
    query_tool="plan.query_runs",
    db_model=TestPlanRun,
    request_id_keys=("run_id",),
    manifest_keys=("plan_run_ids",),
    id_keys=("plan_run_ids",),
    object_list_keys=("runs",),
    batch_result_paths=(),
    not_deleted_attr="is_deleted",
    valid_key="valid_plan_run_ids",
    invalid_key="invalid_plan_run_ids",
    stale_key="stale_plan_run_ids",
    invalid_error_code="agent_plan_run_ids_not_from_query_result",
    stale_error_code="agent_plan_run_id_stale_or_deleted",
    snapshot_error_code="agent_plan_run_snapshot_not_latest",
    invalid_error_message="Plan run ids must come from the latest plan.query_runs result.",
    stale_error_message="Plan run ids from the latest query are stale or deleted; refresh before reading.",
    snapshot_error_message="Plan run snapshot id must match the latest plan.query_runs result.",
    query_before_retry_decision="query_plan_runs_before_retry",
    refresh_before_retry_decision="refresh_plan_run_snapshot_before_retry",
    snapshot_before_retry_decision="refresh_plan_run_snapshot_before_retry",
    request_snapshot_id_keys=("plan_run_snapshot_id",),
)
FLOW_REFERENCE_RULE = ObjectReferenceGuardRule(
    object_type="visual_flow",
    query_tool="flow.query_project_flows",
    db_model=VisualFlow,
    request_id_keys=("flow_id",),
    manifest_keys=("flow_ids",),
    id_keys=("flow_ids",),
    object_list_keys=("flows",),
    batch_result_paths=(),
    valid_key="valid_flow_ids",
    invalid_key="invalid_flow_ids",
    stale_key="stale_flow_ids",
    invalid_error_code="agent_flow_ids_not_from_query_result",
    stale_error_code="agent_flow_id_stale_or_deleted",
    snapshot_error_code="agent_flow_snapshot_not_latest",
    invalid_error_message="Flow ids must come from the latest flow.query_project_flows result.",
    stale_error_message="Flow ids from the latest query are stale or deleted; refresh before execution.",
    snapshot_error_message="Flow snapshot id must match the latest flow.query_project_flows result.",
    query_before_retry_decision="query_project_flows_before_retry",
    refresh_before_retry_decision="refresh_flow_snapshot_before_retry",
    snapshot_before_retry_decision="refresh_flow_snapshot_before_retry",
    request_snapshot_id_keys=("flow_snapshot_id",),
)
DEFECT_REFERENCE_RULE = ObjectReferenceGuardRule(
    object_type="defect",
    query_tool="defect.query_project_defects",
    db_model=Defect,
    request_id_keys=("defect_id",),
    manifest_keys=("defect_ids",),
    id_keys=("defect_ids",),
    object_list_keys=("defects",),
    batch_result_paths=(),
    valid_key="valid_defect_ids",
    invalid_key="invalid_defect_ids",
    stale_key="stale_defect_ids",
    invalid_error_code="agent_defect_ids_not_from_query_result",
    stale_error_code="agent_defect_id_stale_or_deleted",
    snapshot_error_code="agent_defect_snapshot_not_latest",
    invalid_error_message="Defect ids must come from the latest defect.query_project_defects result.",
    stale_error_message="Defect ids from the latest query are stale or deleted; refresh before updating.",
    snapshot_error_message="Defect snapshot id must match the latest defect.query_project_defects result.",
    query_before_retry_decision="query_project_defects_before_retry",
    refresh_before_retry_decision="refresh_defect_snapshot_before_retry",
    snapshot_before_retry_decision="refresh_defect_snapshot_before_retry",
    request_snapshot_id_keys=("defect_snapshot_id",),
)
OBJECT_REFERENCE_GUARD_RULES: dict[str, tuple[ObjectReferenceGuardRule, ...]] = {
    "environment.update_config": (ENVIRONMENT_REFERENCE_RULE,),
    "environment.delete_config": (ENVIRONMENT_REFERENCE_RULE,),
    "environment.upsert_variable": (ENVIRONMENT_REFERENCE_RULE,),
    "environment.delete_variable": (ENVIRONMENT_REFERENCE_RULE,),
    "testcase.create_saved": (ENVIRONMENT_REFERENCE_RULE,),
    "testcase.execute_saved": (HTTP_TEST_CASE_REFERENCE_RULE, ENVIRONMENT_REFERENCE_RULE),
    "testcase.batch_execute": (HTTP_TEST_CASE_REFERENCE_RULE, ENVIRONMENT_REFERENCE_RULE),
    "testcase.update_saved": (HTTP_TEST_CASE_REFERENCE_RULE, ENVIRONMENT_REFERENCE_RULE),
    "testcase.update_assertions": (HTTP_TEST_CASE_REFERENCE_RULE,),
    "testcase.batch_update_assertions": (HTTP_TEST_CASE_REFERENCE_RULE,),
    "websocket_testcase.create_saved": (ENVIRONMENT_REFERENCE_RULE,),
    "websocket_testcase.execute_saved": (WEBSOCKET_TEST_CASE_REFERENCE_RULE, ENVIRONMENT_REFERENCE_RULE),
    "websocket_testcase.batch_execute": (WEBSOCKET_TEST_CASE_REFERENCE_RULE, ENVIRONMENT_REFERENCE_RULE),
    "websocket_testcase.update_saved": (WEBSOCKET_TEST_CASE_REFERENCE_RULE, ENVIRONMENT_REFERENCE_RULE),
    "websocket_testcase.update_assertions": (WEBSOCKET_TEST_CASE_REFERENCE_RULE,),
    "websocket_testcase.batch_update_assertions": (WEBSOCKET_TEST_CASE_REFERENCE_RULE,),
    "scenario.create_saved": (ENVIRONMENT_REFERENCE_RULE,),
    "scenario.update_saved": (SCENARIO_REFERENCE_RULE, ENVIRONMENT_REFERENCE_RULE),
    "scenario.execute_dry_run": (SCENARIO_REFERENCE_RULE, ENVIRONMENT_REFERENCE_RULE),
    "plan.create_saved": (PLAN_SCENARIO_TARGET_REFERENCE_RULE, ENVIRONMENT_REFERENCE_RULE),
    "plan.update_saved": (PLAN_REFERENCE_RULE, PLAN_SCENARIO_TARGET_REFERENCE_RULE, ENVIRONMENT_REFERENCE_RULE),
    "plan.set_enabled": (PLAN_REFERENCE_RULE,),
    "plan.execute_saved": (PLAN_REFERENCE_RULE, ENVIRONMENT_REFERENCE_RULE),
    "plan.read_run": (PLAN_RUN_REFERENCE_RULE,),
    "flow.create_saved": (
        FLOW_HTTP_TEST_CASE_REFERENCE_RULE,
        FLOW_WEBSOCKET_TEST_CASE_REFERENCE_RULE,
        ENVIRONMENT_REFERENCE_RULE,
    ),
    "flow.update_saved": (
        FLOW_REFERENCE_RULE,
        FLOW_HTTP_TEST_CASE_REFERENCE_RULE,
        FLOW_WEBSOCKET_TEST_CASE_REFERENCE_RULE,
        ENVIRONMENT_REFERENCE_RULE,
    ),
    "flow.execute_saved": (FLOW_REFERENCE_RULE, ENVIRONMENT_REFERENCE_RULE),
    "defect.update_saved": (DEFECT_REFERENCE_RULE,),
    "defect.transition_status": (DEFECT_REFERENCE_RULE,),
}
TOOL_INPUT_SCHEMA_PREFLIGHTS: dict[str, tuple[tuple[str, ...], type[BaseModel]]] = {
    "testcase.create_saved": (("case",), TestCaseCreateRequest),
    "testcase.update_saved": (("case",), TestCaseUpdateRequest),
    "testcase.update_assertions": (("assertions", "*"), AssertionConfig),
    "testcase.batch_update_assertions": (("items", "*", "assertions", "*"), AssertionConfig),
    "websocket_testcase.create_saved": (("case",), WebSocketTestCaseCreateRequest),
    "websocket_testcase.update_saved": (("case",), WebSocketTestCaseUpdateRequest),
    "websocket_testcase.update_assertions": (("assertions", "*"), WebSocketAssertionConfig),
    "websocket_testcase.batch_update_assertions": (("items", "*", "assertions", "*"), WebSocketAssertionConfig),
    "scenario.create_saved": (("scenario",), ScenarioCreateRequest),
    "scenario.update_saved": (("scenario",), ScenarioUpdateRequest),
    "plan.create_saved": (("plan",), TestPlanCreateRequest),
    "plan.update_saved": (("plan",), TestPlanUpdateRequest),
    "flow.validate_graph": (("definition",), FlowDefinition),
    "flow.create_saved": (("flow",), FlowCreateRequest),
    "flow.update_saved": (("flow",), FlowUpdateRequest),
    "defect.create_saved": (("defect",), DefectCreateRequest),
    "defect.update_saved": (("defect",), DefectUpdateRequest),
}


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
    def _object_reference_guard_rules(tool_name: str) -> tuple[ObjectReferenceGuardRule, ...]:
        return OBJECT_REFERENCE_GUARD_RULES.get(tool_name, ())

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

    @staticmethod
    def _value_at_path(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
        current: Any = payload
        for segment in path:
            if not isinstance(current, dict):
                return None
            current = current.get(segment)
        return current

    @classmethod
    def _values_at_path(cls, value: Any, path: tuple[str, ...]) -> list[Any]:
        if not path:
            return [value]
        segment, *remaining = path
        tail = tuple(remaining)
        if segment == "*":
            if isinstance(value, list):
                values: list[Any] = []
                for item in value:
                    values.extend(cls._values_at_path(item, tail))
                return values
            return []
        if not isinstance(value, dict) or segment not in value:
            return []
        return cls._values_at_path(value.get(segment), tail)

    @classmethod
    def _object_reference_requested_ids(cls, call: AgentToolCall, rule: ObjectReferenceGuardRule) -> list[int]:
        payload = call.input_json_redacted if isinstance(call.input_json_redacted, dict) else {}
        ids: list[int] = []
        for key in rule.request_id_keys:
            ids.extend(cls._as_int_list([payload.get(key)]))
        for key in rule.request_id_array_keys:
            ids.extend(cls._as_int_list(payload.get(key)))
        for path in rule.request_nested_id_paths:
            ids.extend(cls._as_int_list(cls._values_at_path(payload, path)))
        for path in rule.request_nested_id_array_paths:
            for value in cls._values_at_path(payload, path):
                ids.extend(cls._as_int_list(value))
        for item_path, discriminator_key, discriminator_value, id_key in rule.request_nested_filtered_id_paths:
            for item in cls._values_at_path(payload, item_path):
                if isinstance(item, dict) and item.get(discriminator_key) == discriminator_value:
                    ids.extend(cls._as_int_list([item.get(id_key)]))
        if rule.request_item_list_key and rule.request_item_id_key:
            for item in payload.get(rule.request_item_list_key) or []:
                if isinstance(item, dict):
                    ids.extend(cls._as_int_list([item.get(rule.request_item_id_key)]))
        return list(dict.fromkeys(ids))

    @staticmethod
    def _as_str_list(value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        refs: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                refs.append(item.strip())
        return refs

    @classmethod
    def _object_reference_requested_refs(cls, call: AgentToolCall, rule: ObjectReferenceGuardRule) -> list[str]:
        payload = call.input_json_redacted if isinstance(call.input_json_redacted, dict) else {}
        refs: list[str] = []
        for key in rule.request_ref_keys:
            refs.extend(cls._as_str_list(payload.get(key)))
        for key in rule.request_ref_array_keys:
            refs.extend(cls._as_str_list(payload.get(key)))
        for item in payload.get("items") or []:
            if isinstance(item, dict):
                for key in rule.request_ref_keys:
                    refs.extend(cls._as_str_list(item.get(key)))
                for key in rule.request_ref_array_keys:
                    refs.extend(cls._as_str_list(item.get(key)))
        return list(dict.fromkeys(refs))

    @classmethod
    def _object_reference_requested_snapshot_ids(
        cls,
        call: AgentToolCall,
        rule: ObjectReferenceGuardRule,
    ) -> list[str]:
        payload = call.input_json_redacted if isinstance(call.input_json_redacted, dict) else {}
        snapshot_ids: list[str] = []
        for key in rule.request_snapshot_id_keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                snapshot_ids.append(value.strip())
        for path in rule.request_nested_snapshot_id_paths:
            value = cls._value_at_path(payload, path)
            if isinstance(value, str) and value.strip():
                snapshot_ids.append(value.strip())
        return list(dict.fromkeys(snapshot_ids))

    @staticmethod
    def _object_reference_snapshot_id_from_mapping(value: Any) -> str | None:
        if not isinstance(value, dict):
            return None
        snapshot_id = value.get("snapshot_id")
        if isinstance(snapshot_id, str) and snapshot_id.strip():
            return snapshot_id.strip()
        return None

    @classmethod
    def _object_ids_from_query_output(cls, output: Any, *, rule: ObjectReferenceGuardRule) -> list[int]:
        if not isinstance(output, dict):
            return []
        ids: list[int] = []
        manifest = output.get("case_id_manifest")
        if isinstance(manifest, dict):
            for key in rule.manifest_keys:
                ids.extend(cls._as_int_list(manifest.get(key)))
        object_manifest = output.get("object_reference_manifest")
        if isinstance(object_manifest, dict):
            object_family = object_manifest.get("object_type") or object_manifest.get("object_family")
            family_matches = object_family == rule.object_type or (
                object_family == "test_case"
                and rule.object_type in {"http_test_case", "websocket_test_case"}
            )
        else:
            family_matches = False
        if family_matches and isinstance(object_manifest, dict):
            for key in rule.manifest_keys:
                ids.extend(cls._as_int_list(object_manifest.get(key)))
        for key in rule.id_keys:
            ids.extend(cls._as_int_list(output.get(key)))
        for key in rule.object_list_keys:
            for item in output.get(key) or []:
                if isinstance(item, dict):
                    ids.extend(cls._as_int_list([item.get("id")]))
        for parent_key, child_key in rule.batch_result_paths:
            parent = output.get(parent_key)
            if isinstance(parent, dict):
                ids.extend(cls._as_int_list(parent.get(child_key)))
        return sorted(set(ids))

    @classmethod
    def _object_reference_map_from_query_output(
        cls,
        output: Any,
        *,
        rule: ObjectReferenceGuardRule,
    ) -> dict[str, int]:
        if not isinstance(output, dict):
            return {}
        ref_map: dict[str, int] = {}
        manifests: list[dict[str, Any]] = []
        object_manifest = output.get("object_reference_manifest")
        if isinstance(object_manifest, dict):
            manifests.append(object_manifest)
        for manifest_key in ("case_id_manifest", "scenario_id_manifest", "environment_id_manifest"):
            manifest = output.get(manifest_key)
            if isinstance(manifest, dict):
                manifests.append(manifest)
        for manifest in manifests:
            for item in manifest.get("object_references") or []:
                if not isinstance(item, dict):
                    continue
                object_type = item.get("object_type")
                object_ref = item.get("object_ref") or item.get("ref")
                object_id = item.get("id")
                if not isinstance(object_ref, str) or not isinstance(object_id, int):
                    continue
                if object_type and object_type != rule.object_type:
                    continue
                ref_map[object_ref] = object_id
        for key in ("http_test_cases", "websocket_test_cases", "scenarios", "environments"):
            for item in output.get(key) or []:
                if not isinstance(item, dict):
                    continue
                object_ref = item.get("object_ref") or item.get("ref")
                object_id = item.get("id")
                if isinstance(object_ref, str) and isinstance(object_id, int):
                    ref_map.setdefault(object_ref, object_id)
        return ref_map

    @classmethod
    def _object_snapshot_id_from_query_output(cls, output: Any, *, rule: ObjectReferenceGuardRule) -> str | None:
        if not isinstance(output, dict):
            return None
        for key in ("case_id_manifest", "scenario_id_manifest", "environment_id_manifest"):
            snapshot_id = cls._object_reference_snapshot_id_from_mapping(output.get(key))
            if snapshot_id:
                return snapshot_id
        object_manifest = output.get("object_reference_manifest")
        if isinstance(object_manifest, dict):
            object_family = object_manifest.get("object_type") or object_manifest.get("object_family")
            family_matches = object_family == rule.object_type or (
                object_family == "test_case"
                and rule.object_type in {"http_test_case", "websocket_test_case"}
            )
            if family_matches:
                snapshot_id = cls._object_reference_snapshot_id_from_mapping(object_manifest)
                if snapshot_id:
                    return snapshot_id
        for key in ("case_snapshot", "scenario_snapshot", "environment_snapshot"):
            snapshot_id = cls._object_reference_snapshot_id_from_mapping(output.get(key))
            if snapshot_id:
                return snapshot_id
        return None

    def _latest_object_query_facts(
        self,
        *,
        call: AgentToolCall,
        rule: ObjectReferenceGuardRule,
    ) -> tuple[list[int], str | None, dict[str, int]]:
        current_run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == call.run_id))
        query = select(AgentToolCall).where(
            AgentToolCall.tool_name == rule.query_tool,
            AgentToolCall.status == "succeeded",
        )
        if current_run is not None and current_run.conversation_id:
            query = (
                query
                .join(AgentRun, AgentRun.run_id == AgentToolCall.run_id)
                .where(
                    AgentRun.project_id == current_run.project_id,
                    AgentRun.user_id == current_run.user_id,
                    AgentRun.conversation_id == current_run.conversation_id,
                    AgentRun.id <= current_run.id,
                )
            )
        else:
            query = query.where(AgentToolCall.run_id == call.run_id)
        if call.id is not None:
            query = query.where(
                (AgentToolCall.run_id != call.run_id) | (AgentToolCall.id < call.id)
            )
        query = query.order_by(AgentToolCall.id.desc()).limit(20)
        query_calls = list(self.db.scalars(query).all())
        query_call = next(
            (
                item
                for item in query_calls
                if self._query_output_matches_required_case_mode(call=call, rule=rule, output=item.output_json_redacted)
            ),
            None,
        )
        if query_call is None:
            return [], None, {}
        return (
            self._object_ids_from_query_output(query_call.output_json_redacted, rule=rule),
            self._object_snapshot_id_from_query_output(query_call.output_json_redacted, rule=rule),
            self._object_reference_map_from_query_output(query_call.output_json_redacted, rule=rule),
        )

    @staticmethod
    def _query_output_matches_required_case_mode(
        *,
        call: AgentToolCall,
        rule: ObjectReferenceGuardRule,
        output: Any,
    ) -> bool:
        if call.tool_name not in {
            "testcase.batch_execute",
            "websocket_testcase.batch_execute",
            "testcase.batch_update_assertions",
            "websocket_testcase.batch_update_assertions",
        }:
            return True
        if rule.query_tool != "testcase.query_project_cases":
            return True
        if not isinstance(output, dict):
            return False
        policy = output.get("case_result_policy")
        snapshot = output.get("case_snapshot")
        return (
            output.get("detail_level") == "execution_ready"
            or (isinstance(policy, dict) and policy.get("execution_ready") is True)
            or (isinstance(snapshot, dict) and snapshot.get("execution_ready") is True)
        )

    def _latest_object_query_ids(self, *, call: AgentToolCall, rule: ObjectReferenceGuardRule) -> list[int]:
        return self._latest_object_query_facts(call=call, rule=rule)[0]

    @staticmethod
    def _object_reference_preflight_payload(
        *,
        rule: ObjectReferenceGuardRule,
        call: AgentToolCall,
        status: str,
        reason: str,
        requested_ids: list[int],
        valid_ids: list[int],
        requested_snapshot_ids: list[str],
        latest_snapshot_id: str | None,
        invalid_ids: list[int] | None = None,
        stale_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "preflight_version": "object_reference_preflight_v1",
            "status": status,
            "reason": reason,
            "object_type": rule.object_type,
            "query_tool": rule.query_tool,
            "blocked_tool": call.tool_name,
            "requested_ids": requested_ids,
            "valid_ids": valid_ids,
            "requested_snapshot_ids": requested_snapshot_ids,
            "latest_snapshot_id": latest_snapshot_id,
        }
        if invalid_ids is not None:
            payload["invalid_ids"] = invalid_ids
        if stale_ids is not None:
            payload["stale_ids"] = stale_ids
        return payload

    def _reject_case_reference_ids_without_current_facts(
        self,
        *,
        call: AgentToolCall,
        run: AgentRun,
        queue_item: AgentWorkerQueue | None,
        queue_service: AgentWorkerQueueService,
        runtime: AgentRuntimeService,
    ) -> AgentToolCall | None:
        for rule in self._object_reference_guard_rules(call.tool_name):
            blocked = self._reject_object_reference_rule_without_current_facts(
                call=call,
                run=run,
                queue_item=queue_item,
                queue_service=queue_service,
                runtime=runtime,
                rule=rule,
            )
            if blocked is not None:
                return blocked
        return None

    def _reject_object_reference_rule_without_current_facts(
        self,
        *,
        call: AgentToolCall,
        run: AgentRun,
        queue_item: AgentWorkerQueue | None,
        queue_service: AgentWorkerQueueService,
        runtime: AgentRuntimeService,
        rule: ObjectReferenceGuardRule,
    ) -> AgentToolCall | None:
        payload = call.input_json_redacted if isinstance(call.input_json_redacted, dict) else {}
        top_level_scalar_refs = [
            item
            for key in rule.request_ref_keys
            for item in self._as_str_list(payload.get(key))
        ]
        top_level_array_refs = [
            item
            for key in rule.request_ref_array_keys
            for item in self._as_str_list(payload.get(key))
        ]
        requested_refs = self._object_reference_requested_refs(call, rule)
        requested_ids = self._object_reference_requested_ids(call, rule)
        requested_snapshot_ids = self._object_reference_requested_snapshot_ids(call, rule)
        if not requested_ids and not requested_refs and not requested_snapshot_ids:
            return None
        valid_ids, latest_snapshot_id, object_ref_map = self._latest_object_query_facts(call=call, rule=rule)
        invalid_refs = [item for item in requested_refs if item not in object_ref_map]
        resolved_ref_ids = [object_ref_map[item] for item in requested_refs if item in object_ref_map]
        if resolved_ref_ids:
            requested_ids = list(dict.fromkeys([*requested_ids, *resolved_ref_ids]))
            if isinstance(call.input_json_redacted, dict) and rule.request_id_keys and top_level_scalar_refs:
                call.input_json_redacted.setdefault(rule.request_id_keys[0], object_ref_map[top_level_scalar_refs[0]])
            if isinstance(call.input_json_redacted, dict) and rule.request_id_array_keys and top_level_array_refs:
                call.input_json_redacted.setdefault(
                    rule.request_id_array_keys[0],
                    [object_ref_map[item] for item in top_level_array_refs if item in object_ref_map],
                )
            if (
                isinstance(call.input_json_redacted, dict)
                and rule.request_item_list_key
                and rule.request_item_id_key
            ):
                for item in call.input_json_redacted.get(rule.request_item_list_key) or []:
                    if not isinstance(item, dict):
                        continue
                    for ref_key in rule.request_ref_keys:
                        item_ref = item.get(ref_key)
                        if isinstance(item_ref, str) and item_ref in object_ref_map:
                            item.setdefault(rule.request_item_id_key, object_ref_map[item_ref])
                            break
        valid_id_set = set(valid_ids)
        if requested_snapshot_ids and latest_snapshot_id not in set(requested_snapshot_ids):
            preflight = self._object_reference_preflight_payload(
                rule=rule,
                call=call,
                status="blocked",
                reason="snapshot_mismatch",
                requested_ids=requested_ids,
                valid_ids=valid_ids,
                requested_snapshot_ids=requested_snapshot_ids,
                latest_snapshot_id=latest_snapshot_id,
            )
            output = {
                "required_tool": rule.query_tool,
                "blocked_tool": call.tool_name,
                "object_type": rule.object_type,
                "requested_snapshot_id": requested_snapshot_ids[0],
                "latest_snapshot_id": latest_snapshot_id,
                "snapshot_mismatch": True,
                rule.valid_key: valid_ids,
                "object_reference_preflight": preflight,
                "next_action": (
                    f"Call {rule.query_tool} again and retry only with the latest snapshot_id and ids."
                ),
            }
            call.status = "failed"
            call.execution_phase = "blocked_by_harness"
            call.error_code = rule.snapshot_error_code
            call.error_message = rule.snapshot_error_message
            call.recovery_decision = rule.snapshot_before_retry_decision
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
                    "error_code": rule.snapshot_error_code,
                    "snapshot_mismatch": True,
                    "requested_snapshot_id": requested_snapshot_ids[0],
                    "latest_snapshot_id": latest_snapshot_id,
                    "object_reference_preflight": preflight,
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
                    "error_code": rule.snapshot_error_code,
                },
                commit=False,
            )
            ApprovalService(self.db).supersede_pending_for_terminal_tool_call(
                call=call,
                run=run,
                reason="tool_call_failed_before_approval",
                commit=False,
            )
            if queue_item is not None:
                queue_service.mark_failed(queue_item, error_code=rule.snapshot_error_code, commit=False)
            self.db.commit()
            self.db.refresh(call)
            return call

        if not requested_ids and not invalid_refs:
            return None
        invalid_ids = [item for item in requested_ids if item not in valid_id_set]

        error_code = rule.invalid_error_code
        error_message = rule.invalid_error_message
        recovery_decision = rule.query_before_retry_decision
        output: dict[str, Any]
        diagnostic_key = rule.invalid_key
        diagnostic_ids = invalid_ids
        if not invalid_ids and not invalid_refs:
            existing_statement = select(rule.db_model.id).where(
                rule.db_model.project_id == run.project_id,
                rule.db_model.id.in_(list(dict.fromkeys(requested_ids))),
            )
            if rule.not_deleted_attr:
                existing_statement = existing_statement.where(
                    getattr(rule.db_model, rule.not_deleted_attr).is_(False)
                )
            existing_ids = set(self.db.scalars(existing_statement).all())
            stale_ids = [item for item in list(dict.fromkeys(requested_ids)) if item not in existing_ids]
            if not stale_ids:
                return None
            error_code = rule.stale_error_code
            diagnostic_key = rule.stale_key
            diagnostic_ids = stale_ids
            error_message = rule.stale_error_message
            recovery_decision = rule.refresh_before_retry_decision
            preflight = self._object_reference_preflight_payload(
                rule=rule,
                call=call,
                status="blocked",
                reason="stale_or_deleted",
                requested_ids=requested_ids,
                valid_ids=valid_ids,
                requested_snapshot_ids=requested_snapshot_ids,
                latest_snapshot_id=latest_snapshot_id,
                stale_ids=stale_ids,
            )
            output = {
                "required_tool": rule.query_tool,
                "blocked_tool": call.tool_name,
                "object_type": rule.object_type,
                rule.stale_key: stale_ids,
                rule.valid_key: valid_ids,
                "object_reference_preflight": preflight,
                "next_action": (
                    f"Call {rule.query_tool} again and retry only with ids from the latest current snapshot."
                ),
            }
        else:
            preflight = self._object_reference_preflight_payload(
                rule=rule,
                call=call,
                status="blocked",
                reason="ids_not_from_query_result",
                requested_ids=requested_ids,
                valid_ids=valid_ids,
                requested_snapshot_ids=requested_snapshot_ids,
                latest_snapshot_id=latest_snapshot_id,
                invalid_ids=invalid_ids,
            )
            output = {
                "required_tool": rule.query_tool,
                "blocked_tool": call.tool_name,
                "object_type": rule.object_type,
                rule.invalid_key: invalid_ids,
                rule.valid_key: valid_ids,
                "invalid_object_references": invalid_refs,
                "valid_object_references": sorted(object_ref_map.keys()),
                "object_reference_preflight": preflight,
                "next_action": (
                    f"Call {rule.query_tool} in this Agent conversation and retry using only the ids "
                    "returned in its latest explicit id lists; do not infer ids from numeric ranges or older prose."
                ),
            }
        call.status = "failed"
        call.execution_phase = "blocked_by_harness"
        call.error_code = error_code
        call.error_message = error_message
        call.recovery_decision = recovery_decision
        call.output_json_redacted = output
        call.output_hash = request_fingerprint(output)
        call.policy_reason_json = _policy_reason_with_execution_context(
            call,
            worker_id=queue_item.lease_owner if queue_item is not None else call.lease_owner,
        )
        _clear_tool_call_lease(call)
        event_payload = {
            "tool_call_id": call.tool_call_id,
            "tool_name": call.tool_name,
            "error_code": error_code,
            diagnostic_key: diagnostic_ids,
            "object_reference_preflight": output["object_reference_preflight"],
        }
        if "invalid_object_references" in output:
            event_payload["invalid_object_references"] = output["invalid_object_references"]
            event_payload["valid_object_references"] = output["valid_object_references"]
        runtime.append_event(
            run,
            "tool.failed",
            event_payload,
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
        ApprovalService(self.db).supersede_pending_for_terminal_tool_call(
            call=call,
            run=run,
            reason="tool_call_failed_before_approval",
            commit=False,
        )
        if queue_item is not None:
            queue_service.mark_failed(queue_item, error_code=error_code, commit=False)
        self.db.commit()
        self.db.refresh(call)
        return call

    @staticmethod
    def _path_values(data: Any, path: tuple[str, ...], *, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
        if not path:
            return [(prefix, data)]
        current, *remaining = path
        if current == "*":
            if not isinstance(data, list):
                return [(prefix, None)]
            values: list[tuple[tuple[str, ...], Any]] = []
            for index, item in enumerate(data):
                values.extend(ToolExecutor._path_values(item, tuple(remaining), prefix=(*prefix, str(index))))
            return values
        if not isinstance(data, dict) or current not in data:
            return [((*prefix, current), None)]
        return ToolExecutor._path_values(data[current], tuple(remaining), prefix=(*prefix, current))

    @staticmethod
    def _safe_validation_errors(exc: ValidationError, *, base_path: tuple[str, ...]) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        for item in exc.errors():
            loc = tuple(str(part) for part in item.get("loc", ()))
            error: dict[str, Any] = {
                "path": ".".join((*base_path, *loc)),
                "type": str(item.get("type") or "value_error"),
                "message": str(item.get("msg") or "Invalid value"),
            }
            if "input" in item:
                input_preview = repr(item.get("input"))
                if len(input_preview) > 240:
                    input_preview = f"{input_preview[:240]}..."
                error["input_preview"] = _bounded_agent_error_message(
                    input_preview,
                    reference="ToolExecutor.schema_preflight.validation_input",
                )
            errors.append(error)
        return errors

    def _reject_tool_input_schema_invalid_before_approval(
        self,
        *,
        call: AgentToolCall,
        run: AgentRun,
        runtime: AgentRuntimeService,
    ) -> AgentToolCall | None:
        preflight = TOOL_INPUT_SCHEMA_PREFLIGHTS.get(call.tool_name)
        if preflight is None:
            return None
        path, model = preflight
        errors: list[dict[str, Any]] = []
        for value_path, value in self._path_values(call.input_json_redacted, path):
            try:
                model.model_validate(value)
            except ValidationError as exc:
                errors.extend(self._safe_validation_errors(exc, base_path=value_path))
        if not errors:
            return None

        output = {
            "blocked_tool": call.tool_name,
            "schema_preflight": {
                "tool_name": call.tool_name,
                "schema_name": model.__name__,
                "errors": errors,
            },
            "next_action": (
                "Repair the tool input to match the backend save schema before requesting approval. "
                "For scenario response extraction, use test_case.config.extractors or "
                "test_case.config._scenario_context.extractions instead of fixed_value after_actions."
            ),
        }
        call.status = "failed"
        call.execution_phase = "blocked_by_harness"
        call.error_code = "agent_tool_input_schema_invalid"
        call.error_message = "Tool input failed backend schema preflight before approval."
        call.recovery_decision = "repair_tool_input_schema_before_retry"
        call.output_json_redacted = output
        call.output_hash = request_fingerprint(output)
        call.policy_reason_json = _policy_reason_with_execution_context(call, worker_id=call.lease_owner)
        _clear_tool_call_lease(call)
        runtime.append_event(
            run,
            "tool.failed",
            {
                "tool_call_id": call.tool_call_id,
                "tool_name": call.tool_name,
                "error_code": call.error_code,
                "schema_preflight": output["schema_preflight"],
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
                "error_code": call.error_code,
            },
            commit=False,
        )
        self.db.commit()
        self.db.refresh(call)
        return call

    def _reject_scenario_orchestration_quality_missing_before_approval(
        self,
        *,
        call: AgentToolCall,
        run: AgentRun,
        runtime: AgentRuntimeService,
    ) -> AgentToolCall | None:
        if call.tool_name not in {"scenario.create_saved", "scenario.update_saved"}:
            return None
        payload = call.input_json_redacted if isinstance(call.input_json_redacted, dict) else {}
        scenario = payload.get("scenario")
        if not isinstance(scenario, dict):
            return None
        quality = _scenario_orchestration_quality_missing(intent=run.intent, scenario=scenario)
        if quality is None:
            return None

        output = {
            "blocked_tool": call.tool_name,
            "quality_preflight": {
                "tool_name": call.tool_name,
                "reason": "scenario_orchestration_quality_missing",
                **quality,
            },
            "next_action": (
                "Reuse the latest scenario.compose_draft draft.scenario from the same conversation, "
                "or recompose the scenario with scenario-level before_actions, after_actions, "
                "_scenario_context.extractions, _scenario_context.bindings, and downstream {{variable}} references "
                "before requesting approval to save."
            ),
        }
        call.status = "failed"
        call.execution_phase = "blocked_by_harness"
        call.error_code = "agent_scenario_orchestration_quality_missing"
        call.error_message = "Scenario save input is a degraded test-case list without scenario orchestration data."
        call.recovery_decision = "reuse_or_recompose_scenario_draft_before_save"
        call.output_json_redacted = output
        call.output_hash = request_fingerprint(output)
        call.policy_reason_json = _policy_reason_with_execution_context(call, worker_id=call.lease_owner)
        _clear_tool_call_lease(call)
        runtime.append_event(
            run,
            "tool.failed",
            {
                "tool_call_id": call.tool_call_id,
                "tool_name": call.tool_name,
                "error_code": call.error_code,
                "quality_preflight": output["quality_preflight"],
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
                "error_code": call.error_code,
            },
            commit=False,
        )
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
        blocked_by_case_ids = self._reject_case_reference_ids_without_current_facts(
            call=call,
            run=run,
            queue_item=queue_item,
            queue_service=queue_service,
            runtime=runtime,
        )
        if blocked_by_case_ids is not None:
            return blocked_by_case_ids
        if call.approval_required and not call.approved_approval_id:
            return self._defer_unapproved_tool_call(
                call=call,
                run=run,
                queue_item=queue_item,
                queue_service=queue_service,
                runtime=runtime,
                current_user=current_user,
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

    def _defer_unapproved_tool_call(
        self,
        *,
        call: AgentToolCall,
        run: AgentRun,
        queue_item: AgentWorkerQueue | None,
        queue_service: AgentWorkerQueueService,
        runtime: "AgentRuntimeService",
        current_user: User,
    ) -> AgentToolCall:
        ApprovalService(self.db).create_pending_approval(
            call=call,
            run=run,
            current_user=current_user,
            commit=False,
        )
        blocking = list(run.blocking_tool_call_ids_json or [])
        if call.tool_call_id not in blocking:
            blocking.append(call.tool_call_id)
        run.status = "needs_human"
        run.blocking_tool_call_ids_json = blocking
        call.status = "planned"
        call.execution_phase = "awaiting_approval"
        call.error_code = None
        call.error_message = None
        call.recovery_decision = "awaiting_approval"
        call.policy_reason_json = _policy_reason_with_execution_context(
            call,
            worker_id=queue_item.lease_owner if queue_item is not None else call.lease_owner,
        )
        _clear_tool_call_lease(call)
        if queue_item is not None:
            queue_item.status = "blocked_approval"
            queue_item.last_error_code = "approval_required_before_execution"
            queue_item.lease_owner = None
            queue_item.lease_expires_at = None
        runtime.append_event(
            run,
            "run.needs_human",
            {
                "reason": "tool_approval_required",
                "tool_call_id": call.tool_call_id,
                "tool_name": call.tool_name,
            },
            commit=False,
        )
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
        "capability_plan_id": call.capability_plan_id,
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
        "capability_plan_id": call.capability_plan_id,
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


def _protected_tool_input_for_storage(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    if tool_name != "environment.upsert_variable":
        return mask_sensitive(tool_input)
    protected = dict(tool_input)
    variable_name = str(protected.get("name") or "")
    raw_value = protected.get("value")
    should_encrypt = (
        protected.get("is_secret") is True
        or _agent_environment_value_looks_secret(variable_name)
        or _agent_environment_value_looks_secret(raw_value)
    )
    if should_encrypt and raw_value is not None:
        protected["value"] = encrypt_sensitive({"token": raw_value})["token"]
    return protected


def _agent_environment_value_looks_secret(value: object) -> bool:
    normalized = str(value or "").casefold()
    return any(
        marker in normalized
        for marker in (
            "authorization",
            "auth",
            "bearer ",
            "cookie",
            "jwt",
            "password",
            "secret",
            "token",
            "api_key",
            "apikey",
            "access_key",
            "client_secret",
            "lingxi-auth",
        )
    )


def _conversation_system_messages() -> list[AIChatMessage]:
    return [
        AIChatMessage(role="system", content=_conversation_static_system_prompt()),
        AIChatMessage(role="system", content=_conversation_tool_catalog_prompt()),
        AIChatMessage(role="system", content=_conversation_skill_catalog_prompt()),
    ]


def _conversation_system_prompt() -> str:
    return "\n\n".join(message.content for message in _conversation_system_messages())


def _conversation_static_system_prompt() -> str:
    return "\n\n".join([
        AGENT_CONVERSATION_SYSTEM_PROMPT,
        AGENT_MARKDOWN_RESPONSE_PROMPT,
        AGENT_BUSINESS_OBJECT_DISPLAY_PROMPT,
        AGENT_TOOL_PROTOCOL_PROMPT.replace("可用工具如下：\n{tools}\n\n", ""),
    ])


def _conversation_tool_catalog_prompt() -> str:
    tools = [
        {
            "name": spec.name,
            "summary": spec.summary,
            "side_effect_class": spec.side_effect_class,
            "approval_required": spec.side_effect_class not in SAFE_SIDE_EFFECT_CLASSES,
        }
        for spec in ToolRegistry().list_specs()
        if spec.name not in MODEL_PRIVATE_TOOL_NAMES
    ]
    return (
        "可用工具如下。该层是工具 catalog/model view；完整 schema、权限和副作用仍以后端 ToolRuntime 校验为准。\n"
        f"{json.dumps(tools, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
    )


def _conversation_skill_catalog_prompt() -> str:
    return AGENT_SKILL_CATALOG_PROMPT.replace(
        "{skills}",
        json.dumps(AgentSkillRegistry().catalog(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


def _tool_contract_context_message(intent: str) -> AIChatMessage | None:
    tool_names = _tool_contract_tool_names_for_intent(intent)
    if not tool_names:
        return None
    registry = ToolRegistry()
    contracts = []
    for tool_name in tool_names:
        spec = registry.get(tool_name)
        contracts.append({
            "name": spec.name,
            "input_summary": _tool_input_summary(spec.input_schema),
        })
    return AIChatMessage(
        role="system",
        content=(
            "当前任务相关工具入参契约（Layer 2 model view；完整 schema、权限和副作用由后端 Runtime Validation 裁决）：\n"
            f"{json.dumps(contracts, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
        ),
    )


def _tool_contract_tool_names_for_intent(intent: str) -> list[str]:
    context_plan = AgentContextManager().route(intent)
    return sorted(name for name in context_plan.allowed_tools if name not in MODEL_PRIVATE_TOOL_NAMES)


def _tool_input_summary(schema: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    summary: dict[str, Any] = {
        "required": [str(item) for item in required],
        "properties": sorted(str(key) for key in properties),
    }
    enum_props: dict[str, list[Any]] = {}
    for key, value in properties.items():
        if isinstance(value, dict) and isinstance(value.get("enum"), list):
            enum_props[str(key)] = value["enum"]
    if enum_props:
        summary["enums"] = enum_props
    nested_required: dict[str, list[str]] = {}
    for key, value in properties.items():
        required_fields = _schema_property_nested_required(value)
        if required_fields:
            nested_required[str(key)] = required_fields
    if nested_required:
        summary["nested_required"] = nested_required
    return summary


def _schema_property_nested_required(schema: Any) -> list[str]:
    if not isinstance(schema, dict):
        return []
    required = schema.get("required")
    if isinstance(required, list) and required:
        return sorted(str(item) for item in required)
    for union_key in ("oneOf", "anyOf", "allOf"):
        variants = schema.get(union_key)
        if not isinstance(variants, list):
            continue
        collected: set[str] = set()
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            variant_required = variant.get("required")
            if isinstance(variant_required, list):
                collected.update(str(item) for item in variant_required)
        if collected:
            return sorted(collected)
    return []


def _bind_context_plan_to_persisted_capabilities(context_plan: Any, plan_record: Any) -> Any:
    """Make rebuilt model context use the persisted plan as its tool authority."""
    allowed_tools = tuple(plan_record.allowed_tools_json or ())
    capability_plan = context_plan.capability_plan
    if capability_plan is not None:
        capability_plan = replace(
            capability_plan,
            allowed_tools=allowed_tools,
            reason_codes=tuple(plan_record.reason_codes_json or ()),
        )
    return replace(
        context_plan,
        allowed_tools=allowed_tools,
        capability_plan=capability_plan,
    )


def _capability_plan_identity_message(
    *,
    capability_plan_id: str,
    plan_hash: str,
    iteration: int,
    previous_capability_plan_id: str | None = None,
) -> AIChatMessage:
    payload: dict[str, Any] = {
        "capability_plan_id": capability_plan_id,
        "plan_hash": plan_hash,
        "iteration": iteration,
    }
    if previous_capability_plan_id:
        payload["previous_capability_plan_id"] = previous_capability_plan_id
    return AIChatMessage(
        role="system",
        content=(
            f"{AGENT_CAPABILITY_PLAN_CONTEXT_PREFIX}\n"
            "当前模型上下文绑定此 Capability Plan；所有工具选择必须来自该计划。\n"
            f"{json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
        ),
    )


def _apply_model_context_budget(messages: list[AIChatMessage]) -> tuple[list[AIChatMessage], dict[str, Any]]:
    before_messages = list(messages)
    before_units = _model_context_layer_units(before_messages)
    adjusted_messages = list(before_messages)
    compacted_layers: list[str] = []

    total_limit_chars = AGENT_MODEL_CONTEXT_TOTAL_BUDGET_UNITS * 4
    if _model_context_chars(adjusted_messages) > total_limit_chars:
        for layer in _model_context_compaction_order():
            current_total_chars = _model_context_chars(adjusted_messages)
            if current_total_chars <= total_limit_chars:
                break
            layer_chars = _model_context_layer_chars(adjusted_messages, layer)
            if layer_chars <= 0:
                continue
            non_layer_chars = current_total_chars - layer_chars
            max_layer_chars = max(0, total_limit_chars - non_layer_chars)
            adjusted_messages, changed = _cap_model_context_layer(
                adjusted_messages,
                layer=layer,
                max_chars=max_layer_chars,
            )
            if changed and layer not in compacted_layers:
                compacted_layers.append(layer)

    after_units = _model_context_layer_units(adjusted_messages)
    compacted = bool(compacted_layers)
    budget_limit_reached = before_units["total"] > AGENT_MODEL_CONTEXT_TOTAL_BUDGET_UNITS
    context_budget = {
        "schema_version": AGENT_MODEL_CONTEXT_BUDGET_SCHEMA_VERSION,
        "phase": "pre_model_call",
        "budget_scope": AGENT_MODEL_CONTEXT_BUDGET_SCOPE,
        "budget_limit_units": AGENT_MODEL_CONTEXT_TOTAL_BUDGET_UNITS,
        "budget_limit_reached": budget_limit_reached,
        "compacted": compacted,
        "compacted_layers": compacted_layers,
        "estimated_input_units_before": before_units["total"],
        "estimated_input_units_after": after_units["total"],
        "layer_budgets": _model_context_layer_budgets(),
        "layer_actual_units_before": before_units,
        "layer_actual_units_after": after_units,
        "source": "AgentConversationRunner._stream_model_response",
    }
    return adjusted_messages, context_budget


def _model_context_layer_budgets() -> dict[str, int]:
    return {
        "static": AGENT_MODEL_CONTEXT_STATIC_BUDGET_UNITS,
        "tool_catalog": AGENT_MODEL_CONTEXT_TOOL_CATALOG_BUDGET_UNITS,
        "tool_contract": AGENT_MODEL_CONTEXT_TOOL_CATALOG_BUDGET_UNITS,
        "skill_catalog": AGENT_MODEL_CONTEXT_SKILL_BUDGET_UNITS,
        "skill": AGENT_MODEL_CONTEXT_SKILL_BUDGET_UNITS,
        "memory": AGENT_MODEL_CONTEXT_MEMORY_BUDGET_UNITS,
        "history": AGENT_MODEL_CONTEXT_HISTORY_BUDGET_UNITS,
        "tool_result": AGENT_MODEL_CONTEXT_TOOL_RESULT_BUDGET_UNITS,
        "tool_request_context": AGENT_MODEL_CONTEXT_TOOL_RESULT_BUDGET_UNITS,
        "task": AGENT_MODEL_CONTEXT_TOTAL_BUDGET_UNITS,
        "run_context": AGENT_MODEL_CONTEXT_STATIC_BUDGET_UNITS,
        "working_context": AGENT_MODEL_CONTEXT_HISTORY_BUDGET_UNITS,
        "total": AGENT_MODEL_CONTEXT_TOTAL_BUDGET_UNITS,
    }


def _model_context_compaction_order() -> tuple[str, ...]:
    return (
        "history",
        "working_context",
        "memory",
        "tool_result",
        "tool_request_context",
        "skill",
        "skill_catalog",
        "tool_contract",
        "tool_catalog",
    )


def _model_context_chars(messages: list[AIChatMessage]) -> int:
    return sum(len(message.content or "") for message in messages)


def _model_context_layer_units(messages: list[AIChatMessage]) -> dict[str, int]:
    layer_chars: dict[str, int] = {key: 0 for key in _model_context_layer_budgets() if key != "total"}
    for index, message in enumerate(messages):
        layer = _model_context_message_layer(messages, index)
        layer_chars[layer] = layer_chars.get(layer, 0) + len(message.content or "")
    units = {layer: math.ceil(chars / 4) for layer, chars in layer_chars.items()}
    units["total"] = math.ceil(_model_context_chars(messages) / 4)
    return units


def _model_context_layer_chars(messages: list[AIChatMessage], layer: str) -> int:
    return sum(
        len(message.content or "")
        for index, message in enumerate(messages)
        if _model_context_message_layer(messages, index) == layer
    )


def _model_context_message_layer(messages: list[AIChatMessage], index: int) -> str:
    message = messages[index]
    content = message.content or ""
    if _is_tool_result_context_content(content):
        return "tool_result"
    if _looks_like_internal_tool_context_leak(content):
        return "tool_request_context"
    if content.startswith("项目记忆上下文"):
        return "memory"
    if content.startswith("同一会话工作上下文"):
        return "working_context"
    if content.startswith("当前 Agent Run 上下文"):
        return "run_context"
    if content.startswith("可用工具如下"):
        return "tool_catalog"
    if content.startswith("当前任务相关工具入参契约"):
        return "tool_contract"
    if content.startswith("Agent Skill 目录如下"):
        return "skill_catalog"
    if content.startswith("已加载 Agent Skill"):
        return "skill"
    last_user_index = _last_user_message_index(messages)
    if index == last_user_index and message.role == "user":
        return "task"
    if message.role == "system":
        if "Conversation history compacted for prompt budget." in content:
            return "history"
        return "static"
    return "history"


def _last_user_message_index(messages: list[AIChatMessage]) -> int:
    last_user_index = -1
    for index, message in enumerate(messages):
        if message.role == "user":
            last_user_index = index
    return last_user_index


def _cap_model_context_layer(
    messages: list[AIChatMessage],
    *,
    layer: str,
    max_chars: int,
) -> tuple[list[AIChatMessage], bool]:
    capped: list[AIChatMessage] = []
    used_chars = 0
    changed = False
    marker_added = False
    for index, message in enumerate(messages):
        if _model_context_message_layer(messages, index) != layer:
            capped.append(message)
            continue
        content = message.content or ""
        remaining = max_chars - used_chars
        if remaining <= 0:
            changed = True
            if not marker_added and max_chars > 0 and used_chars == 0:
                marker = _model_context_layer_compaction_marker(layer)
                capped.append(AIChatMessage(role="system", content=marker[:max_chars]))
                used_chars += min(len(marker), max_chars)
                marker_added = True
            continue
        if len(content) > remaining:
            capped.append(AIChatMessage(role=message.role, content=_cap_model_context_text(content, remaining, layer)))
            used_chars += min(len(content), remaining)
            changed = True
            continue
        capped.append(message)
        used_chars += len(content)
    return capped, changed


def _cap_model_context_text(content: str, max_chars: int, layer: str) -> str:
    marker = _model_context_layer_compaction_marker(layer)
    if max_chars <= 0:
        return marker
    if len(content) <= max_chars:
        return content
    if max_chars <= len(marker):
        return marker[:max_chars]
    return f"{content[: max_chars - len(marker)]}{marker}"


def _model_context_layer_compaction_marker(layer: str) -> str:
    return AGENT_MODEL_CONTEXT_LAYER_TRUNCATION_MARKER.replace("]", f"; layer={layer}]")


def _model_context_metrics(messages: list[AIChatMessage]) -> dict[str, int | str]:
    contents = [message.content or "" for message in messages]
    total_chars = sum(len(content) for content in contents)
    last_user_index = _last_user_message_index(messages)

    system_chars = 0
    task_chars = 0
    history_chars = 0
    tool_result_chars = 0
    tool_request_context_chars = 0
    for index, message in enumerate(messages):
        content = message.content or ""
        content_chars = len(content)
        if message.role == "system":
            system_chars += content_chars
            continue
        if _is_tool_result_context_content(content):
            tool_result_chars += content_chars
            continue
        if _looks_like_internal_tool_context_leak(content):
            tool_request_context_chars += content_chars
            continue
        if index == last_user_index and message.role == "user":
            task_chars += content_chars
            continue
        history_chars += content_chars

    return {
        "schema_version": "agent_model_context_metrics_v1",
        "message_count": len(messages),
        "system_chars": system_chars,
        "task_chars": task_chars,
        "history_chars": history_chars,
        "tool_result_chars": tool_result_chars,
        "tool_request_context_chars": tool_request_context_chars,
        "total_chars": total_chars,
        "estimated_input_units": math.ceil(total_chars / 4),
    }


def _is_tool_result_context_content(content: str) -> bool:
    return (
        content.startswith("工具执行结果如下")
        or content.startswith("工具执行结果摘要如下")
        or AGENT_TOOL_RESULT_CONTEXT_TRUNCATION_MARKER in content
        or "tool_result_model_context_truncated" in content
    )


def _agent_skill_messages(intent: str) -> list[AIChatMessage]:
    return [
        AIChatMessage(role="system", content=_format_agent_skill_context(skill))
        for skill in AgentSkillRegistry().route_for_intent(intent).selected_skills
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


def _final_summary_tool_request_suppressed_message(tool_summaries: list[dict[str, Any]]) -> str:
    if tool_summaries and all(summary.get("status") == "succeeded" for summary in tool_summaries):
        return AGENT_FINAL_SUMMARY_TOOL_REQUEST_SUPPRESSED_SUCCESS_MESSAGE
    return AGENT_FINAL_SUMMARY_TOOL_REQUEST_SUPPRESSED_MESSAGE


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


def _normalize_model_evidence_refs(
    value: Any,
    *,
    allow_single_object: bool = True,
) -> list[dict[str, Any]] | Any:
    if value is None:
        return []
    if isinstance(value, dict):
        if not allow_single_object:
            return value
        return [dict(value)] if value else []
    if not isinstance(value, list):
        ref = _model_evidence_ref_from_string(value)
        return [ref] if ref is not None else []

    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(dict(item))
            continue
        ref = _model_evidence_ref_from_string(item)
        if ref is not None:
            normalized.append(ref)
    return normalized


def _tool_request_from_payload(
    payload: Any,
    *,
    normalize_evidence_refs: bool = True,
    normalize_single_evidence_ref_object: bool = True,
) -> AgentToolRequest:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="模型工具请求 JSON 必须是对象")
    payload = _hoist_misnested_tool_request_metadata(payload)
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
        evidence_refs = _normalize_model_evidence_refs(
            evidence_refs,
            allow_single_object=normalize_single_evidence_ref_object,
        )
    if not isinstance(evidence_refs, list) or not all(isinstance(item, dict) for item in evidence_refs):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="模型工具 evidence_refs 必须是对象列表")
    return AgentToolRequest(
        tool_name=tool_name,
        tool_input=dict(tool_input),
        reason=payload.get("reason") if isinstance(payload.get("reason"), str) else None,
        evidence_refs=tuple(dict(item) for item in evidence_refs),
    )


def _hoist_misnested_tool_request_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    tool_input = payload.get("input")
    if not isinstance(tool_input, dict):
        return payload
    normalized = dict(payload)
    normalized_input = dict(tool_input)
    if "reason" not in normalized and isinstance(normalized_input.get("reason"), str):
        normalized["reason"] = normalized_input.pop("reason")
    if "evidence_refs" not in normalized and "evidence_refs" in normalized_input:
        normalized["evidence_refs"] = normalized_input.pop("evidence_refs")
    if normalized_input is not tool_input:
        normalized["input"] = normalized_input
    return normalized


def _parse_tool_request_json_payload(raw: str) -> Any:
    return json.loads(raw)


def _try_repair_tool_request_json_payload(raw: str) -> Any | None:
    candidates = [raw]
    completed = _complete_missing_json_closers(raw)
    if completed is not None and completed != raw:
        candidates.append(completed)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def _complete_missing_json_closers(raw: str) -> str | None:
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in raw:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char == "}":
            if not stack or stack[-1] != "{":
                return None
            stack.pop()
        elif char == "]":
            if not stack or stack[-1] != "[":
                return None
            stack.pop()
    if in_string or escaped or len(stack) > TOOL_REQUEST_JSON_REPAIR_MAX_CLOSERS:
        return None
    closers = "".join("}" if opener == "{" else "]" for opener in reversed(stack))
    return f"{raw}{closers}" if closers else raw


def _model_evidence_ref_from_string(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    ref = value.strip()
    if not ref:
        return None
    for prefix in ("tool-call:", "tool_call:"):
        if ref.startswith(prefix):
            tool_call_id = ref[len(prefix):].strip()
            return _tool_call_audit_evidence_ref(tool_call_id) if tool_call_id else None
    if ref.startswith("agent-tool-"):
        return _tool_call_audit_evidence_ref(ref)
    if ref.startswith("agent-run-"):
        return {
            "evidence_ref_id": f"run:{ref}",
            "ref_type": "agent_run",
            "ref_id": ref,
            "mutability_class": "immutable",
            "dependency_role": "audit_background",
            "active_for_policy": False,
        }
    return None


def _tool_call_audit_evidence_ref(tool_call_id: str) -> dict[str, Any]:
    return {
        "evidence_ref_id": f"tool-call:{tool_call_id}",
        "ref_type": "tool_call",
        "ref_id": tool_call_id,
        "mutability_class": "immutable",
        "dependency_role": "audit_background",
        "active_for_policy": False,
    }


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


def _final_summary_tool_result_context_messages(calls: list[AgentToolCall]) -> list[AIChatMessage]:
    messages: list[AIChatMessage] = []
    used_chars = 0
    budget = 6000
    marker = AGENT_TOOL_RESULT_CONTEXT_TRUNCATION_MARKER
    for call in calls:
        content = _final_summary_tool_result_message(call)
        remaining = budget - used_chars
        if remaining <= 0:
            messages.append(AIChatMessage(role="user", content=marker))
            break
        if len(content) > remaining:
            prefix_length = max(0, remaining - len(marker))
            messages.append(AIChatMessage(role="user", content=f"{content[:prefix_length]}{marker}"))
            break
        messages.append(AIChatMessage(role="user", content=content))
        used_chars += len(content)
    return messages


def _final_summary_tool_result_message(call: AgentToolCall) -> str:
    output = call.output_json_redacted if isinstance(call.output_json_redacted, dict) else {}
    summary: dict[str, Any] = {
        "tool_call_id": call.tool_call_id,
        "tool_name": call.tool_name,
        "status": call.status,
        "error_code": call.error_code,
        "error_message": call.error_message,
    }
    if isinstance(output, dict):
        for key in (
            "operation",
            "project_id",
            "test_case_id",
            "websocket_test_case_id",
            "scenario_id",
            "run_ids",
            "total",
            "http_total",
            "websocket_total",
        ):
            if key in output:
                summary[key] = output.get(key)
        for object_key in ("scenario", "test_case", "websocket_test_case", "project"):
            value = output.get(object_key)
            if isinstance(value, dict):
                summary[object_key] = {
                    key: value.get(key)
                    for key in ("id", "name", "environment_id", "current_version", "status")
                    if key in value
                }
        if "warnings" in output:
            summary["warnings"] = output.get("warnings")
        if "issues" in output:
            summary["issues"] = output.get("issues")
    return "工具执行结果摘要如下。\n" + json.dumps(summary, ensure_ascii=False, default=str, sort_keys=True)


def _append_tool_result_context_message(
    messages: list[AIChatMessage],
    call: AgentToolCall,
    *,
    provider_tool_call_id: str | None = None,
) -> None:
    if any(AGENT_TOOL_RESULT_CONTEXT_TRUNCATION_MARKER in (message.content or "") for message in messages):
        trace_debug(
            "agent_trace_tool_result_context_skip_after_truncation",
            run_id=call.run_id,
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            status=call.status,
            message_count=len(messages),
        )
        return
    used_chars = sum(
        len(message.content or "")
        for message in messages
        if _is_tool_result_context_message(message)
    )
    remaining_chars = AGENT_TOOL_RESULT_CONTEXT_TOTAL_MAX_CHARS - used_chars
    if remaining_chars <= 0:
        trace_debug(
            "agent_trace_tool_result_context_budget_exhausted",
            run_id=call.run_id,
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            status=call.status,
            used_chars=used_chars,
            budget_chars=AGENT_TOOL_RESULT_CONTEXT_TOTAL_MAX_CHARS,
        )
        return
    raw_content = _tool_result_message(call)
    content = _cap_tool_result_context_message(raw_content, remaining_chars)
    trace_debug(
        "agent_trace_tool_result_context_append",
        run_id=call.run_id,
        tool_call_id=call.tool_call_id,
        tool_name=call.tool_name,
        status=call.status,
        used_chars=used_chars,
        remaining_chars=remaining_chars,
        raw_chars=len(raw_content),
        appended_chars=len(content),
        truncated=AGENT_TOOL_RESULT_CONTEXT_TRUNCATION_MARKER in content,
        budget_chars=AGENT_TOOL_RESULT_CONTEXT_TOTAL_MAX_CHARS,
    )
    if provider_tool_call_id:
        messages.append(AIChatMessage(
            role="tool",
            content=content,
            tool_call_id=provider_tool_call_id,
        ))
    else:
        messages.append(AIChatMessage(role="user", content=content))


def _is_tool_result_context_message(message: AIChatMessage) -> bool:
    content = message.content or ""
    return (
        message.role == "tool"
        or content.startswith("工具执行结果如下")
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
    if not (intent or "").strip():
        return False
    registry = registry or AgentSkillRegistry()
    intent_keywords = registry.private_list(guard.skill_name, guard.intent_key)
    subject_keywords = registry.private_list(guard.skill_name, guard.subject_key)
    if not any(intent_matches_routing_phrase(intent, keyword) for keyword in intent_keywords):
        return False
    ambiguous_subjects = {item.casefold() for item in AMBIGUOUS_DEICTIC_GUARD_SUBJECTS}
    explicit_subject_keywords = tuple(
        keyword
        for keyword in subject_keywords
        if keyword.casefold() not in ambiguous_subjects
    )
    return any(intent_matches_routing_phrase(intent, keyword) for keyword in explicit_subject_keywords)


def _unsupported_capability_classifier_prompt(guard: UnsupportedCapabilityGuard) -> str | None:
    prompt = AgentSkillRegistry().private_resource_text(guard.skill_name, guard.classifier_prompt_key)
    if prompt is None:
        return None
    return _cap_unsupported_capability_classifier_prompt(prompt)


def _unsupported_capability_message(guard: UnsupportedCapabilityGuard) -> str | None:
    return AgentSkillRegistry().private_resource_text(guard.skill_name, guard.message_key)


def _required_tool_followup_rules_for_intent(intent: str) -> tuple[RequiredToolFollowupRule, ...]:
    registry = AgentSkillRegistry()
    rules: list[RequiredToolFollowupRule] = []
    for skill in registry.select_for_intent(intent):
        for raw_rule in registry.private_list(skill.name, REQUIRED_TOOL_AFTER_SUCCESS_ROUTING_KEY):
            rule = _parse_required_tool_followup_rule(raw_rule)
            if rule is not None and _required_tool_followup_rule_matches_intent(rule, intent):
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
    return any(intent_matches_routing_phrase(text, marker) for marker in rule.intent_markers)


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
    if not (intent or "").strip():
        return False
    registry = AgentSkillRegistry()
    for skill in registry.list_skills():
        values = registry.private_list(skill.name, key)
        if any(intent_matches_routing_phrase(intent, value) for value in values):
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


def _scenario_state_transition_for_tool_call(db: Session, *, run: AgentRun, call: AgentToolCall) -> dict[str, Any] | None:
    to_state = SCENARIO_CREATION_TOOL_STATES.get(call.tool_name)
    if to_state is None or not _run_uses_scenario_state_machine(run=run, tool_name=call.tool_name):
        return None
    return _scenario_state_transition_payload(
        db,
        run=run,
        to_state=to_state,
        reason="tool_planned",
        tool_call_id=call.tool_call_id,
        tool_name=call.tool_name,
    )


def _scenario_terminal_state_transitions(db: Session, *, run: AgentRun) -> list[dict[str, Any]]:
    last_state = _latest_scenario_state(db, run_id=run.run_id)
    if last_state is None or last_state == "END":
        return []
    transitions = []
    if last_state != "SUMMARY":
        summary_payload = _scenario_state_transition_payload(
            db,
            run=run,
            to_state="SUMMARY",
            reason="final_response",
        )
        if summary_payload is not None:
            transitions.append(summary_payload)
    end_payload = _scenario_state_transition_payload(
        db,
        run=run,
        to_state="END",
        reason="run_completed",
        from_state_override="SUMMARY" if transitions else None,
    )
    if end_payload is not None:
        transitions.append(end_payload)
    return transitions


def _scenario_state_transition_payload(
    db: Session,
    *,
    run: AgentRun,
    to_state: str,
    reason: str,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    from_state_override: str | None = None,
) -> dict[str, Any] | None:
    if to_state not in SCENARIO_CREATION_STATES:
        return None
    from_state = from_state_override or _latest_scenario_state(db, run_id=run.run_id) or "START"
    return {
        "state_machine": SCENARIO_CREATION_STATE_MACHINE_NAME,
        "state_machine_version": SCENARIO_CREATION_STATE_MACHINE_VERSION,
        "states": list(SCENARIO_CREATION_STATES),
        "from_state": from_state,
        "to_state": to_state,
        "reason": reason,
        "iteration": run.current_iteration,
        "step_index": run.current_step_index,
        **({"tool_call_id": tool_call_id} if tool_call_id else {}),
        **({"tool_name": tool_name} if tool_name else {}),
    }


def _latest_scenario_state(db: Session, *, run_id: str) -> str | None:
    event = db.scalar(
        select(AgentEvent)
        .where(AgentEvent.run_id == run_id, AgentEvent.event_type == "scenario.state_transition")
        .order_by(AgentEvent.event_seq.desc())
        .limit(1)
    )
    if event is None or not isinstance(event.payload_json, dict):
        return None
    state = event.payload_json.get("to_state")
    return str(state) if isinstance(state, str) else None


def _run_uses_scenario_state_machine(*, run: AgentRun, tool_name: str) -> bool:
    if tool_name.startswith("scenario."):
        return True
    route = AgentSkillRegistry().route_for_intent(run.intent)
    return route.primary_skill is not None and route.primary_skill.name == "scenario-composition"


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


def _visible_content_before_tool_request(content: str) -> str:
    marker_index = content.find("```agent_tool_request")
    if marker_index < 0:
        return content.strip()
    return content[:marker_index].rstrip()


def _invalid_test_case_ids_in_final_response(content: str, *, valid_ids: set[int]) -> list[int]:
    if not valid_ids:
        return []
    referenced_ids = _referenced_test_case_ids_in_text(content)
    return sorted(item for item in referenced_ids if item not in valid_ids)


def _referenced_test_case_ids_in_text(content: str) -> set[int]:
    ids: set[int] = set()
    case_ref_prefix = r"(?:测试用例|用例|HTTP\s*用例|WebSocket\s*用例|case)"
    for match in re.finditer(r"object-ref://test_case/[^\s|)>]+/(\d+)\b", content, flags=re.I):
        ids.add(int(match.group(1)))
    for match in re.finditer(
        rf"{case_ref_prefix}\s*ID\s*[:：]?\s*(\d+)\s*[-~～—]\s*(\d+)\b",
        content,
        flags=re.I,
    ):
        start = int(match.group(1))
        end = int(match.group(2))
        if 0 < start <= end and end - start <= 500:
            ids.update(range(start, end + 1))
    explicit_pattern = rf"{case_ref_prefix}\s*ID\s*[:：]?\s*(\d+)\b"
    for match in re.finditer(explicit_pattern, content, flags=re.I):
        ids.add(int(match.group(1)))
    parenthesized_pattern = (
        rf"{case_ref_prefix}"
        rf"(?:(?!(?:项目|环境|project|environment|\bID\b))[^\n|]){{0,80}}?"
        rf"[（(]\s*ID\s*[:：]?\s*(\d+)\s*[）)]"
    )
    for match in re.finditer(parenthesized_pattern, content, flags=re.I):
        ids.add(int(match.group(1)))
    return ids


def _coerce_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _looks_like_internal_tool_context_leak(content: str) -> bool:
    text = content or ""
    if AGENT_TOOL_REQUEST_CONTEXT_SUMMARY_VERSION in text:
        return True
    markers = (
        "上一轮模型已发起工具请求",
        "给后续模型使用的有界摘要",
        "完整结构化事实以 ExecutionLedger/ToolCall 为准",
        "evidence_refs_json",
        "source_content_preview",
        "full_content_reference=AgentConversationRunner.model.completed.tool_request.content",
        "AgentConversationRunner.model_context.tool_request",
        "AgentConversationRunner.model.completed.tool_request.content",
    )
    hits = sum(1 for marker in markers if marker in text)
    if hits >= 2:
        return True
    return (
        "input_json" in text
        and "tool_name" in text
        and ("tool_request" in text or "ToolCall" in text)
    )


def _internal_tool_context_summary_payload(content: str) -> dict[str, Any] | None:
    if not _looks_like_internal_tool_context_leak(content):
        return None
    text = (content or "").strip()
    decoder = json.JSONDecoder()
    for match in re.finditer(r"{", text):
        try:
            payload, _ = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("summary_version") == AGENT_TOOL_REQUEST_CONTEXT_SUMMARY_VERSION:
            return payload
    return None


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
    tool_artifact_manifests: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    tool_artifact_manifests = list(tool_artifact_manifests or [])
    if not previous_runs and not tool_artifact_manifests:
        return None
    artifact_resolver = AgentArtifactResolver()
    ledger_artifact_candidates = [
        artifact_resolver.ensure_artifact_class(item)
        for item in tool_artifact_manifests
        if item.get("artifact_type") and item.get("artifact_type") != "tool_result"
    ]
    active_artifact_handles = artifact_resolver.model_handles(ledger_artifact_candidates)
    active_artifact_action = _active_artifact_action_context(
        current_intent=current_intent,
        ledger_artifact_candidates=active_artifact_handles,
    )
    recent_runs = previous_runs[-AGENT_HISTORY_CONTEXT_FULL_TURNS:]
    turns = []
    artifacts = []
    for run in recent_runs:
        assistant = _assistant_message_from_run(run) or ""
        assistant = _assistant_text_for_active_artifact_action(
            assistant,
            active_artifact_action=active_artifact_action,
        )
        turn = {
            "run_id": run.run_id,
            "user_intent": _truncate_history_text(run.intent, AGENT_HISTORY_CONTEXT_RECENT_USER_CHARS),
            "assistant_message": _truncate_history_text(assistant, AGENT_HISTORY_CONTEXT_SUMMARY_CHARS),
        }
        inferred = _infer_working_artifact(run.intent, assistant)
        if inferred is not None:
            turn["inferred_artifact"] = inferred
            artifacts.append({"source_run_id": run.run_id, "artifact_class": "SUMMARY", **inferred})
        turns.append(turn)
    payload: dict[str, Any] = {
        "schema_version": "conversation_working_context_v2",
        "current_intent": current_intent,
        "current_intent_is_deictic_followup": _intent_is_deictic_followup(current_intent),
        "recent_turns": turns,
        "recent_run_states": [_run_state_for_working_context(run) for run in recent_runs],
        "current_artifact_candidates": [
            *active_artifact_handles[-AGENT_CONVERSATION_TOOL_ARTIFACT_CONTEXT_MAX_ITEMS:],
            *artifacts[-3:],
        ],
        "resolution_rules": [
            "If current_intent_is_deictic_followup is true, resolve it against current_artifact_candidates before choosing tools.",
            "Prefer matching active_artifact_handles over inferred artifacts from assistant text.",
            "Prefer the latest artifact whose domain matches the user's last concrete request.",
            "If the referenced artifact cannot be identified, ask a short clarification instead of guessing.",
            "High-risk writes still require the matching approved tool and human approval.",
        ],
    }
    if active_artifact_action is not None:
        payload["active_artifact_action"] = active_artifact_action
    if active_artifact_handles:
        payload["active_artifact_handles"] = active_artifact_handles
    return payload


def _run_state_for_working_context(run: AgentRun) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": run.run_id,
        "status": run.status,
        "user_intent": _truncate_history_text(
            run.intent,
            AGENT_HISTORY_CONTEXT_RECENT_USER_CHARS,
        ),
        "last_event_sequence": run.last_event_sequence,
        "current_iteration": run.current_iteration,
        "current_step_index": run.current_step_index,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }
    if run.error_code:
        payload["error_code"] = run.error_code
    if run.error_message:
        payload["error_message"] = _truncate_history_text(
            str(mask_sensitive(run.error_message)),
            AGENT_ERROR_MESSAGE_MAX_CHARS,
        )
    return {key: value for key, value in payload.items() if value is not None}


def _format_conversation_working_context(payload: dict[str, Any]) -> str:
    return (
        "同一会话工作上下文：\n"
        "当前用户请求可能是对上一轮产物的省略回指；请先依据此结构化上下文解析“直接、刚才、上面、这个”等指代，"
        "再决定是否调用工具、调用哪个工具、是否需要审批。若存在 active_artifact_handles，"
        "它是同会话权威 ToolCall artifact 的模型可见索引，优先于从 assistant 摘要推断的产物；"
        "完整 ToolCall 输出仅供后端 ledger/UI 检查，不能要求直接读取 full result。\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)}"
    )


def _conversation_routing_intent(current_intent: str, working_context: dict[str, Any] | None) -> str:
    routing_hint = _active_artifact_action_routing_hint(working_context)
    if not routing_hint:
        return current_intent
    return f"{current_intent}\n{routing_hint}"


def _active_artifact_action_routing_hint(working_context: dict[str, Any] | None) -> str:
    active_action = _working_context_active_artifact_action(working_context)
    if not active_action:
        return ""
    artifact_type = str(active_action.get("artifact_type") or "")
    action = str(active_action.get("action") or "")
    tool_name = str(active_action.get("tool_name") or "")
    if artifact_type == "scenario_draft" and action == "save" and tool_name:
        return (
            "active_artifact_type=scenario_draft; active_artifact_action=save; "
            "route_skill=scenario-composition; enable_tools=scenario.create_saved,scenario.update_saved; "
            "use scenario_source artifact reference instead of reconstructing scenario JSON."
        )
    if artifact_type == "scenario_run_failure" and action == "repair" and tool_name:
        return (
            "active_artifact_type=scenario_run_failure; active_artifact_action=repair; "
            "route_skill=scenario-composition; "
            "enable_tools=scenario.query_project_scenarios,testcase.query_project_cases,"
            "scenario.compose_draft,scenario.update_saved,scenario.execute_dry_run; "
            "repair the failed saved scenario from the SOURCE dry-run artifact, then validate with dry-run."
        )
    return ""


def _working_context_active_artifact_action(working_context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(working_context, dict):
        return None
    active_action = working_context.get("active_artifact_action")
    return active_action if isinstance(active_action, dict) else None


def _active_artifact_action_context(
    *,
    current_intent: str,
    ledger_artifact_candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if _intent_requests_repair_action(current_intent):
        for item in reversed(ledger_artifact_candidates):
            if item.get("artifact_type") != "scenario_run_failure":
                continue
            actions = item.get("available_followup_actions")
            if isinstance(actions, list) and "repair" not in actions:
                continue
            artifact_id = item.get("artifact_id")
            if not artifact_id:
                continue
            summary = item.get("artifact_summary") if isinstance(item.get("artifact_summary"), dict) else {}
            tool_input_hint: dict[str, Any] = {"source_artifact_id": artifact_id}
            for key in ("scenario_id", "environment_id", "run_ids", "failed_run_ids", "failures", "statuses"):
                if summary.get(key) is not None:
                    tool_input_hint[key] = summary.get(key)
            action_context = {
                "schema_version": "active_artifact_action_v1",
                "artifact_type": "scenario_run_failure",
                "artifact_class": item.get("artifact_class"),
                "artifact_trust": item.get("artifact_trust"),
                "domain": "scenario",
                "action": "repair",
                "tool_name": "scenario.compose_draft",
                "required_tools": [
                    "scenario.query_project_scenarios",
                    "testcase.query_project_cases",
                    "scenario.compose_draft",
                    "scenario.update_saved",
                    "scenario.execute_dry_run",
                ],
                "artifact_id": artifact_id,
                "source_tool_call_id": item.get("tool_call_id"),
                "output_hash": item.get("output_hash"),
                "artifact_summary": summary,
                "tool_input_hint": tool_input_hint,
                "routing_hint": "enable scenario repair tools from failed dry-run artifact",
            }
            return {key: value for key, value in action_context.items() if value not in (None, {}, [])}

    if _intent_requests_save_action(current_intent):
        if _intent_targets_non_scenario_save_subject(current_intent):
            return None
        for item in reversed(ledger_artifact_candidates):
            if item.get("artifact_type") != "scenario_draft":
                continue
            actions = item.get("available_followup_actions")
            if isinstance(actions, list) and "save" not in actions and "update_saved" not in actions:
                continue
            artifact_id = item.get("artifact_id")
            if not artifact_id:
                continue
            scenario_source = {
                "artifact_id": artifact_id,
            }
            if item.get("output_hash"):
                scenario_source["output_hash"] = item.get("output_hash")
            action_context: dict[str, Any] = {
                "schema_version": "active_artifact_action_v1",
                "artifact_type": "scenario_draft",
                "artifact_class": item.get("artifact_class"),
                "artifact_trust": item.get("artifact_trust"),
                "domain": "scenario",
                "action": "save",
                "tool_name": "scenario.create_saved",
                "artifact_id": artifact_id,
                "source_tool_call_id": item.get("tool_call_id"),
                "output_hash": item.get("output_hash"),
                "artifact_summary": item.get("artifact_summary") if isinstance(item.get("artifact_summary"), dict) else {},
                "tool_input_hint": {
                    "scenario_source": scenario_source,
                },
                "routing_hint": "enable scenario.create_saved and submit approval using scenario_source",
            }
            if _intent_requests_execute_action(current_intent):
                action_context["after_save_actions"] = ["scenario.execute_dry_run"]
            return {key: value for key, value in action_context.items() if value not in (None, {}, [])}
    return None


def _assistant_history_for_working_context(
    run: AgentRun,
    assistant: str,
    *,
    working_context: dict[str, Any] | None,
) -> str:
    active_action = _working_context_active_artifact_action(working_context)
    return _assistant_text_for_active_artifact_action(assistant, active_artifact_action=active_action)


def _assistant_text_for_active_artifact_action(
    assistant: str,
    *,
    active_artifact_action: dict[str, Any] | None,
) -> str:
    if not active_artifact_action:
        return assistant
    if (
        active_artifact_action.get("artifact_type") == "scenario_draft"
        and active_artifact_action.get("action") == "save"
        and _looks_like_stale_unsupported_scenario_save_message(assistant)
    ):
        return ""
    return assistant


def _looks_like_stale_unsupported_scenario_save_message(text: str) -> bool:
    lowered = (text or "").casefold()
    if not lowered:
        return False
    save_markers = ("保存", "持久化", "落库", "正式场景", "save")
    scenario_markers = ("场景", "scenario", "草稿", "draft")
    unsupported_markers = (
        "暂不包含场景保存",
        "没有场景保存",
        "缺少场景保存",
        "不包含场景保存",
        "无法在此直接持久化",
        "无法直接保存为正式场景",
        "无法把",
        "手动创建场景",
    )
    return (
        any(marker in lowered for marker in save_markers)
        and any(marker in lowered for marker in scenario_markers)
        and any(marker in lowered for marker in unsupported_markers)
    )


def _validated_intent_decision_from_plan(payload: dict[str, Any]) -> ValidatedAgentIntentDecision:
    return ValidatedAgentIntentDecision(
        action=payload.get("action"),
        target_domain=payload.get("target_domain"),
        source_domains=tuple(payload.get("source_domains") or ()),
        confidence=float(payload.get("confidence", 1.0)),
        source=str(payload.get("source") or "persisted_plan"),
        reason_codes=tuple(payload.get("reason_codes") or ()),
        write_authorized=bool(payload.get("write_authorized", True)),
    )


def _validated_planning_decision_from_plan(payload: dict[str, Any]) -> ValidatedAgentPlanningDecision:
    return ValidatedAgentPlanningDecision(
        goal=str(payload.get("goal") or "Continue the validated Agent plan."),
        action=str(payload.get("action") or "query"),
        target_domain=(str(payload["target_domain"]) if payload.get("target_domain") else None),
        source_domains=tuple(str(item) for item in (payload.get("source_domains") or ())),
        selected_skills=tuple(str(item) for item in (payload.get("selected_skills") or ())),
        selected_tools=tuple(str(item) for item in (payload.get("selected_tools") or ())),
        selected_artifact_ids=tuple(str(item) for item in (payload.get("selected_artifact_ids") or ())),
        required_facts=tuple(str(item) for item in (payload.get("required_facts") or ())),
        requested_effect_scope=str(payload.get("requested_effect_scope") or "observe"),
        confidence=float(payload.get("confidence", 1.0)),
        reason_summary=str(payload.get("reason_summary") or "Persisted validated planning decision."),
        source=str(payload.get("source") or "persisted_plan"),
    )


def _agent_tool_request_from_native_payload(payload: Any) -> AgentToolRequest | None:
    if not isinstance(payload, dict):
        return None
    tool_name = payload.get("tool_name")
    tool_input = payload.get("input")
    evidence_refs = payload.get("evidence_refs") or []
    if not isinstance(tool_name, str) or not tool_name or not isinstance(tool_input, dict):
        return None
    if not isinstance(evidence_refs, list) or not all(isinstance(item, dict) for item in evidence_refs):
        return None
    reason = payload.get("reason")
    return AgentToolRequest(
        tool_name=tool_name,
        tool_input=dict(tool_input),
        reason=reason if isinstance(reason, str) else None,
        evidence_refs=tuple(dict(item) for item in evidence_refs),
        provider_tool_call_id=(
            str(payload.get("provider_tool_call_id"))
            if payload.get("provider_tool_call_id")
            else None
        ),
    )


def _denied_available_tool_name(
    message: str,
    runtime_tools: Sequence[dict[str, Any]],
    *,
    intent_decision: dict[str, Any] | None = None,
) -> str | None:
    lowered = (message or "").casefold()
    denial_terms = ("没有", "不包含", "不支持", "无法", "只能", "no direct", "unsupported", "cannot")
    if not any(term.casefold() in lowered for term in denial_terms):
        return None
    tool_names = sorted({
        str(tool.get("name") or tool.get("tool_name") or "")
        for tool in runtime_tools
        if isinstance(tool, dict) and (tool.get("name") or tool.get("tool_name"))
    })
    explicitly_named = [name for name in tool_names if name.casefold() in lowered]
    if explicitly_named:
        return explicitly_named[0]
    if intent_decision:
        matching = [name for name in tool_names if tool_matches_intent_decision(name, intent_decision)]
        if matching:
            return matching[0]
    if "缺陷" in lowered and "defect.create_saved" in tool_names:
        return "defect.create_saved"
    return None


def _assistant_denies_available_capability(
    message: str,
    runtime_tools: Sequence[dict[str, Any]],
) -> str | None:
    lowered = (message or "").casefold()
    denial_terms = ("没有", "不支持", "无法", "只能", "no direct", "unsupported", "cannot")
    if not any(term.casefold() in lowered for term in denial_terms):
        return None
    denied_tool = _denied_available_tool_name(message, runtime_tools)
    if denied_tool == "defect.create_saved":
        return "route_missed_available_defect_create"
    return None


def _intent_requests_save_action(intent: str) -> bool:
    text = (intent or "").casefold()
    return any(marker in text for marker in ("保存", "持久化", "落库", "发布", "正式场景", "save"))


def _intent_requests_execute_action(intent: str) -> bool:
    text = (intent or "").casefold()
    return any(marker in text for marker in ("保存后执行", "保存并执行", "执行", "试运行", "dry-run", "dryrun"))


def _intent_requests_repair_action(intent: str) -> bool:
    text = (intent or "").casefold()
    return any(
        marker in text
        for marker in (
            "\u4fee\u590d",
            "\u89e3\u51b3",
            "\u4fee\u597d",
            "\u6539\u597d",
            "\u5904\u7406\u95ee\u9898",
            "fix",
            "repair",
            "resolve",
        )
    )


def _intent_targets_non_scenario_save_subject(intent: str) -> bool:
    text = (intent or "").casefold()
    if any(marker in text for marker in ("场景", "scenario", "草稿", "draft", "流程")):
        return False
    return any(marker in text for marker in ("断言", "assertion", "测试用例", "用例", "testcase", "test case"))


def _scenario_from_compose_draft_output(output: Any) -> dict[str, Any] | None:
    _, scenario = _scenario_artifact_from_compose_draft_output(output)
    return scenario


def _json_path_get(payload: Any, path: str | None) -> Any:
    if not path:
        return payload
    current = payload
    for raw_segment in path.split("."):
        segment = raw_segment.strip()
        if not segment:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="path contains an empty segment",
            )
        if isinstance(current, dict):
            if segment not in current:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"path segment not found: {segment}",
                )
            current = current[segment]
            continue
        if isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"path index out of range: {segment}",
                )
            current = current[index]
            continue
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"path segment cannot be applied: {segment}",
        )
    return current


def _scenario_artifact_from_compose_draft_output(output: Any) -> tuple[str | None, dict[str, Any] | None]:
    if not isinstance(output, dict):
        return None, None
    draft = output.get("draft")
    if isinstance(draft, dict) and isinstance(draft.get("scenario"), dict):
        return "draft.scenario", copy.deepcopy(draft["scenario"])
    if isinstance(output.get("scenario"), dict):
        return "scenario", copy.deepcopy(output["scenario"])
    return None, None


def _saved_scenario_artifact_from_output(output: Any) -> tuple[str | None, dict[str, Any] | None]:
    if not isinstance(output, dict):
        return None, None
    scenario = output.get("scenario")
    if isinstance(scenario, dict):
        return "scenario", copy.deepcopy(scenario)
    scenario_id = _optional_positive_int(output.get("scenario_id"))
    if scenario_id is None:
        return None, None
    scenario_payload: dict[str, Any] = {"id": scenario_id}
    for key in ("name", "environment_id", "current_version"):
        if output.get(key) is not None:
            scenario_payload[key] = output[key]
    return None, scenario_payload


def _parse_tool_artifact_id(artifact_id: str) -> dict[str, str] | None:
    prefix = "agent-tool-artifact://"
    if not artifact_id.startswith(prefix):
        return None
    rest = artifact_id[len(prefix) :]
    parts = rest.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return {"tool_call_id": parts[0], "artifact_type": parts[1]}


def _tool_call_artifact_manifest(call: AgentToolCall, source_run: AgentRun) -> dict[str, Any] | None:
    output = call.output_json_redacted
    if output is None:
        return None
    artifact_type = "tool_result"
    domain = call.tool_name.split(".", 1)[0] if call.tool_name else "tool"
    output_path: str | None = None
    artifact_summary = _tool_output_artifact_summary(output)
    available_followup_actions = ["inspect_ledger_detail"]

    if call.tool_name == "scenario.compose_draft":
        scenario_path, scenario = _scenario_artifact_from_compose_draft_output(output)
        if scenario is not None:
            draft_envelope = output.get("draft") if isinstance(output, dict) else None
            scenario_validation = (
                draft_envelope.get("scenario_validation")
                if isinstance(draft_envelope, dict) and isinstance(draft_envelope.get("scenario_validation"), dict)
                else None
            )
            explicitly_invalid = scenario_validation is not None and scenario_validation.get("valid") is not True
            artifact_type = "scenario_draft_invalid" if explicitly_invalid else "scenario_draft"
            domain = "scenario"
            output_path = scenario_path
            artifact_summary = _scenario_draft_artifact_summary(scenario)
            if explicitly_invalid:
                artifact_summary["scenario_validation"] = {
                    "valid": False,
                    "unresolved_reference_count": scenario_validation.get("unresolved_reference_count"),
                    "unresolved_template_count": scenario_validation.get("unresolved_template_count"),
                    "quality_issue_count": len(scenario_validation.get("quality_issues") or []),
                    "graph_error_count": len(scenario_validation.get("graph_errors") or []),
                }
                available_followup_actions = ["repair"]
            else:
                available_followup_actions = ["save", "update_saved"]
    elif call.tool_name in {"scenario.create_saved", "scenario.update_saved"}:
        scenario_path, scenario = _saved_scenario_artifact_from_output(output)
        if scenario is not None:
            artifact_type = "saved_scenario"
            domain = "scenario"
            output_path = scenario_path
            artifact_summary = _saved_scenario_artifact_summary(output, scenario)
            available_followup_actions = ["execute", "query_runs", "update_saved"]
    elif call.tool_name == "scenario.execute_dry_run" and isinstance(output, dict):
        scenario_run_summary = _scenario_run_failure_artifact_summary(output)
        if scenario_run_summary is not None:
            artifact_type = "scenario_run_failure"
            domain = "scenario"
            artifact_summary = scenario_run_summary
            available_followup_actions = ["repair", "query_scenario", "compose_fix", "update_saved", "execute"]
    elif call.tool_name == "testcase.query_project_cases" and isinstance(output, dict):
        artifact_type = "test_case_query_snapshot"
        domain = "test_case"
        artifact_summary = _test_case_query_snapshot_artifact_summary(output)
        available_followup_actions = [
            "analyze_cases",
            "compose_scenario",
            "update_assertions",
            "batch_update_assertions",
            "execute",
        ]

    artifact_class = AgentArtifactResolver().artifact_class_for_type(artifact_type)
    manifest = {
        "artifact_id": f"agent-tool-artifact://{call.tool_call_id}/{artifact_type}",
        "artifact_type": artifact_type,
        "artifact_class": artifact_class,
        "domain": domain,
        "status": "available",
        "source": "tool_call_ledger",
        "tool_call_id": call.tool_call_id,
        "tool_name": call.tool_name,
        "run_id": call.run_id,
        "conversation_id": source_run.conversation_id,
        "output_hash": call.output_hash,
        "output_path": output_path,
        "redaction": "output_json_redacted",
        "artifact_summary": artifact_summary,
        "available_followup_actions": available_followup_actions,
        "full_output_reference": "ToolCall.output_json_redacted",
    }
    return {key: value for key, value in manifest.items() if value is not None}


def _prioritize_tool_artifact_manifests_for_context(manifests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    limit = AGENT_CONVERSATION_TOOL_ARTIFACT_CONTEXT_MAX_ITEMS
    if len(manifests) <= limit:
        return manifests
    selected: list[dict[str, Any]] = []
    seen_artifact_ids: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        artifact_id = str(item.get("artifact_id") or "")
        if not artifact_id or artifact_id in seen_artifact_ids or len(selected) >= limit:
            return
        selected.append(item)
        seen_artifact_ids.add(artifact_id)

    for item in reversed(manifests):
        if item.get("artifact_type") != "tool_result":
            add(item)
    for item in reversed(manifests):
        add(item)
    return list(reversed(selected))


def _scenario_draft_artifact_summary(scenario: dict[str, Any]) -> dict[str, Any]:
    nodes = scenario.get("nodes") if isinstance(scenario.get("nodes"), list) else []
    datasets = scenario.get("datasets") if isinstance(scenario.get("datasets"), list) else []
    summary: dict[str, Any] = {
        "node_count": len(nodes),
        "dataset_count": len(datasets),
    }
    name = scenario.get("name")
    if isinstance(name, str) and name.strip():
        summary["name"] = _truncate_history_text(name, AGENT_HISTORY_CONTEXT_SUMMARY_CHARS)
    description = scenario.get("description")
    if isinstance(description, str) and description.strip():
        summary["description"] = _truncate_history_text(description, AGENT_HISTORY_CONTEXT_SUMMARY_CHARS)
    environment_id = scenario.get("environment_id")
    if environment_id is not None:
        summary["environment_id"] = environment_id
    return summary


def _saved_scenario_artifact_summary(output: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    scenario_id = _optional_positive_int(output.get("scenario_id"))
    if scenario_id is None:
        scenario_id = _optional_positive_int(scenario.get("id"))
    if scenario_id is not None:
        summary["scenario_id"] = scenario_id

    name = scenario.get("name") or output.get("name")
    if isinstance(name, str) and name.strip():
        summary["name"] = _truncate_history_text(name, AGENT_HISTORY_CONTEXT_SUMMARY_CHARS)

    environment_id = _optional_positive_int(scenario.get("environment_id"))
    if environment_id is None:
        environment_id = _optional_positive_int(scenario.get("environmentId"))
    if environment_id is None:
        environment_id = _optional_positive_int(output.get("environment_id"))
    if environment_id is not None:
        summary["environment_id"] = environment_id

    current_version = _optional_positive_int(scenario.get("current_version"))
    if current_version is None:
        current_version = _optional_positive_int(scenario.get("currentVersion"))
    if current_version is None:
        current_version = _optional_positive_int(output.get("current_version"))
    if current_version is not None:
        summary["current_version"] = current_version

    return summary


def _scenario_run_failure_artifact_summary(output: dict[str, Any]) -> dict[str, Any] | None:
    runs = output.get("runs")
    if not isinstance(runs, list):
        runs = []
    failed_run_ids: list[int] = []
    run_ids: list[int] = []
    statuses: dict[str, int] = {}
    failures: list[dict[str, Any]] = []
    environment_id: int | None = _optional_positive_int(output.get("environment_id"))
    scenario_id: int | None = _optional_positive_int(output.get("scenario_id"))

    for run in runs:
        if not isinstance(run, dict):
            continue
        run_id = _optional_positive_int(run.get("id"))
        if run_id is None:
            run_id = _optional_positive_int(run.get("run_id"))
        if run_id is not None:
            run_ids.append(run_id)

        if scenario_id is None:
            scenario_id = _optional_positive_int(run.get("scenario_id"))
        if environment_id is None:
            environment_id = _optional_positive_int(run.get("environment_id"))
        if environment_id is None:
            environment_id = _optional_positive_int(run.get("environmentId"))

        status_value = str(run.get("status") or "unknown").casefold()
        statuses[status_value] = statuses.get(status_value, 0) + 1
        run_failed = status_value in {"failed", "failure", "error", "errored", "timeout", "cancelled"}
        step_results = run.get("step_results")
        if not isinstance(step_results, list):
            step_results = run.get("stepResults")
        if not isinstance(step_results, list):
            step_results = run.get("steps")
        if not isinstance(step_results, list):
            step_results = []
        for step in step_results:
            if not isinstance(step, dict):
                continue
            step_status = str(step.get("status") or "").casefold()
            if step_status not in {"failed", "failure", "error", "errored", "timeout", "cancelled"}:
                continue
            run_failed = True
            if len(failures) >= 5:
                continue
            failure: dict[str, Any] = {}
            for source_key, target_key in (
                ("node_id", "node_id"),
                ("nodeId", "node_id"),
                ("node_name", "node_name"),
                ("nodeName", "node_name"),
                ("case_id", "case_id"),
                ("caseId", "case_id"),
                ("status", "status"),
                ("error_message", "error_message"),
                ("errorMessage", "error_message"),
                ("message", "error_message"),
            ):
                value = step.get(source_key)
                if value is None or target_key in failure:
                    continue
                failure[target_key] = (
                    _truncate_history_text(str(value), AGENT_HISTORY_CONTEXT_SUMMARY_CHARS)
                    if isinstance(value, str)
                    else value
                )
            if failure:
                failures.append(failure)
        if run_failed and run_id is not None:
            failed_run_ids.append(run_id)

    if not failed_run_ids and "failed" not in statuses and "error" not in statuses:
        return None

    summary: dict[str, Any] = {
        "run_ids": run_ids or output.get("run_ids") or [],
        "failed_run_ids": sorted(dict.fromkeys(failed_run_ids)),
        "statuses": statuses,
    }
    if scenario_id is not None:
        summary["scenario_id"] = scenario_id
    if environment_id is not None:
        summary["environment_id"] = environment_id
    if failures:
        summary["failures"] = failures
    return summary


def _test_case_query_snapshot_artifact_summary(output: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("project_id", "environment_id", "detail_level", "http_total", "websocket_total"):
        value = output.get(key)
        if value is not None:
            summary[key] = value

    case_manifest = output.get("case_id_manifest") if isinstance(output.get("case_id_manifest"), dict) else {}
    object_manifest = (
        output.get("object_reference_manifest")
        if isinstance(output.get("object_reference_manifest"), dict)
        else {}
    )
    snapshot = output.get("case_snapshot") if isinstance(output.get("case_snapshot"), dict) else {}
    snapshot_id = object_manifest.get("snapshot_id") or case_manifest.get("snapshot_id") or snapshot.get("snapshot_id")
    if snapshot_id is not None:
        summary["snapshot_id"] = snapshot_id
    for key in (
        "http_test_case_ids",
        "websocket_test_case_ids",
        "http_assertion_update_ids",
        "websocket_assertion_update_ids",
        "http_test_case_refs",
        "websocket_test_case_refs",
    ):
        values = object_manifest.get(key)
        if not isinstance(values, list):
            values = case_manifest.get(key)
        if not isinstance(values, list):
            values = output.get(key)
        if isinstance(values, list):
            summary[f"{key}_count"] = len(values)
    object_references = object_manifest.get("object_references")
    if isinstance(object_references, list):
        summary["object_reference_count"] = len(object_references)
    case_display_rows = output.get("case_display_rows")
    if isinstance(case_display_rows, list):
        summary["case_display_rows_count"] = len(case_display_rows)
    if isinstance(output.get("case_result_policy"), dict):
        execution_ready = output["case_result_policy"].get("execution_ready")
        if execution_ready is not None:
            summary["execution_ready"] = bool(execution_ready)
    return summary


def _tool_output_artifact_summary(output: Any) -> dict[str, Any]:
    if isinstance(output, dict):
        summary: dict[str, Any] = {
            "top_level_keys": [str(key) for key in list(output.keys())[:8]],
        }
        for key, value in output.items():
            if isinstance(value, list):
                summary[f"{key}_count"] = len(value)
            elif isinstance(value, dict):
                summary[f"{key}_keys"] = [str(item) for item in list(value.keys())[:5]]
        return summary
    if isinstance(output, list):
        return {"item_count": len(output)}
    return {"value_type": type(output).__name__}


def _optional_positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _compact_reference_text(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", (value or "").casefold(), flags=re.UNICODE)


def _scenario_name_matches_intent(scenario: Any, intent: str) -> bool:
    if not isinstance(scenario, dict):
        return False
    name = str(scenario.get("name") or "").strip()
    if not name:
        return False
    compact_name = _compact_reference_text(name)
    compact_intent = _compact_reference_text(intent or "")
    return bool(compact_name and compact_name in compact_intent)


def _has_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker.casefold() in text for marker in markers)


SCENARIO_SAVE_MARKERS = ("保存", "持久化", "落库", "發布", "发布", "save", "persist")
SCENARIO_OBJECT_MARKERS = ("场景", "場景", "scenario", "草稿", "draft", "流程", "编排", "編排", "flow")
SCENARIO_DEICTIC_MARKERS = (
    "该",
    "該",
    "此",
    "这个",
    "這個",
    "刚才",
    "剛才",
    "上面",
    "前面",
    "直接",
    "它",
    "this",
    "that",
    "above",
    "previous",
)
SCENARIO_EXECUTE_MARKERS = (
    "执行",
    "執行",
    "运行",
    "運行",
    "调试",
    "調試",
    "验证",
    "驗證",
    "dry-run",
    "dryrun",
    "execute",
    "run",
)


def _intent_is_action_only_followup(intent: str) -> bool:
    compact = _compact_reference_text(intent or "")
    if not compact:
        return False
    removable_markers = (
        *SCENARIO_SAVE_MARKERS,
        *SCENARIO_EXECUTE_MARKERS,
        "后",
        "後",
        "然后",
        "然後",
        "并",
        "並",
        "并且",
        "並且",
        "再",
        "直接",
        "马上",
        "立即",
        "帮我",
        "幫我",
        "一下",
        "把",
        "吧",
        "please",
    )
    remainder = compact
    for marker in sorted(removable_markers, key=len, reverse=True):
        compact_marker = _compact_reference_text(marker)
        if compact_marker:
            remainder = remainder.replace(compact_marker, "")
    return not remainder


def _intent_requests_latest_scenario_draft(intent: str) -> bool:
    text = (intent or "").casefold()
    if not text:
        return False
    return (
        _has_any_marker(text, SCENARIO_SAVE_MARKERS)
        and (
            _has_any_marker(text, SCENARIO_OBJECT_MARKERS)
            or _intent_is_deictic_followup(intent)
            or _has_any_marker(text, SCENARIO_DEICTIC_MARKERS)
            or _intent_is_action_only_followup(intent)
        )
    )


def _intent_requests_save_then_execute(intent: str) -> bool:
    text = (intent or "").casefold()
    if not text:
        return False
    return (
        _has_any_marker(text, SCENARIO_SAVE_MARKERS)
        and _has_any_marker(text, SCENARIO_EXECUTE_MARKERS)
        and (
            _has_any_marker(text, SCENARIO_OBJECT_MARKERS)
            or _intent_is_deictic_followup(intent)
            or _intent_is_action_only_followup(intent)
        )
    )


def _scenario_orchestration_quality(scenario: Any) -> dict[str, Any]:
    nodes = scenario.get("nodes") if isinstance(scenario, dict) else []
    if not isinstance(nodes, list):
        nodes = []
    quality = {
        "node_count": len(nodes),
        "action_count": 0,
        "extraction_count": 0,
        "binding_count": 0,
        "template_reference_count": 0,
        "empty_test_case_configs": 0,
    }
    for node in nodes:
        if not isinstance(node, dict):
            continue
        before_actions = node.get("before_actions", node.get("beforeActions"))
        after_actions = node.get("after_actions", node.get("afterActions"))
        quality["action_count"] += len(before_actions) if isinstance(before_actions, list) else 0
        quality["action_count"] += len(after_actions) if isinstance(after_actions, list) else 0
        test_case = node.get("test_case", node.get("testCase"))
        if not isinstance(test_case, dict):
            continue
        config = test_case.get("config")
        if not isinstance(config, dict) or not config:
            quality["empty_test_case_configs"] += 1
            config = {}
        context = config.get("_scenario_context")
        if not isinstance(context, dict):
            context = {}
        quality["extraction_count"] += _count_context_items(config, "extractors")
        quality["extraction_count"] += _count_context_items(context, "extractions", "extractors")
        quality["binding_count"] += _count_context_items(context, "bindings", "inputBindings", "input_bindings")
        quality["template_reference_count"] += _count_template_references(config)
    return quality


def _count_context_items(data: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return len([item for item in value if isinstance(item, dict)])
    return 0


def _count_template_references(value: Any) -> int:
    if isinstance(value, str):
        return len(re.findall(r"\{\{\s*[^{}]+?\s*\}\}", value))
    if isinstance(value, dict):
        return sum(_count_template_references(item) for item in value.values())
    if isinstance(value, list):
        return sum(_count_template_references(item) for item in value)
    return 0


def _scenario_save_intent_requires_orchestration(intent: str, scenario: Any) -> bool:
    scenario_text = ""
    if isinstance(scenario, dict):
        scenario_text = "\n".join(str(scenario.get(key) or "") for key in ("name", "description"))
    text = f"{intent or ''}\n{scenario_text}".casefold()
    markers = (
        "依赖",
        "依賴",
        "取值",
        "前置",
        "后置",
        "後置",
        "上下文",
        "链路",
        "鏈路",
        "流程",
        "编排",
        "編排",
        "binding",
        "dependency",
        "extract",
        "precondition",
        "postcondition",
        "workflow",
        "context",
    )
    return any(marker.casefold() in text for marker in markers)


def _scenario_orchestration_quality_missing(*, intent: str, scenario: Any) -> dict[str, Any] | None:
    quality = _scenario_orchestration_quality(scenario)
    if quality["node_count"] <= 1:
        return None
    if not _scenario_save_intent_requires_orchestration(intent, scenario):
        return None
    if quality["action_count"] or quality["extraction_count"] or quality["binding_count"]:
        return None
    empty_config_threshold = max(1, (quality["node_count"] + 1) // 2)
    if quality["empty_test_case_configs"] < empty_config_threshold:
        return None
    return quality


def _intent_is_deictic_followup(intent: str) -> bool:
    text = (intent or "").casefold()
    if not text:
        return False
    if _intent_is_action_only_followup(intent):
        return True
    markers = (
        "直接",
        "刚才",
        "上面",
        "前面",
        "该",
        "該",
        "此",
        "这个",
        "這個",
        "这些",
        "這些",
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
    if not _looks_like_working_artifact_signal(text):
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


def _looks_like_working_artifact_signal(text: str) -> bool:
    markers = (
        "草稿",
        "尚未保存",
        "未保存",
        "已生成",
        "生成",
        "创建",
        "组合",
        "编排",
        "分析",
        "修复",
        "更新",
        "更改",
        "变更",
        "保存",
        "审批",
        "draft",
        "generated",
        "created",
        "composed",
        "updated",
        "fixed",
        "saved",
        "approval",
    )
    return any(marker in text for marker in markers)


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


def _chat_messages_trace_payload(messages: list[AIChatMessage]) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "role": str(getattr(message, "role", "") or ""),
            "content": str(getattr(message, "content", "") or ""),
        }
        for index, message in enumerate(messages)
    ]


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
