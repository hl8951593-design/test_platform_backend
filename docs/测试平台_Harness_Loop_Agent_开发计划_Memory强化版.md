# 测试平台 Harness+Loop Agent 开发计划

> 版本：v1.0  
> 依据：`测试平台_Harness_Loop_Agent_架构_四次修正版.md`  
> 目标：严格按四次修正版架构落地生产级测试平台 Agent Runtime。  
> 原则：先完成安全事实源和恢复闭环，再开放高风险自动化能力。

---

## 1. 开发目标与边界

### 1.1 总目标

建设一套生产级测试平台 Agent Runtime，使 Agent 能够在现有平台能力之上完成：

```text
Plan      根据用户目标和项目上下文规划下一步
Reason    结合上下文、工具结果、失败证据和记忆做判断
Act       调用受控 Tool 执行动作
Observe   读取工具结果、执行记录、报告和业务反馈
Loop      基于观察结果继续修复、暂停、审批或终止
Memory    使用项目记忆，但不把记忆当硬事实
State     持久化 run、step、tool call、event、checkpoint
Policy    做 plan-time / approval-time / execute-time 权限控制
Recovery  从 Worker 崩溃、未知提交、schema 不兼容、审批过期中恢复
```

### 1.2 明确不做的事

首期不做：

```text
不引入 LangGraph。
不让 Agent 直接改业务数据库。
不让 Agent 绕过 AIService / AISkillService。
不让 Agent 绕过 Scenario / Flow / TestCase / WS / Report / Defect Service。
不让 SSE 成为事实源。
不在没有 ExecutionLedger 的情况下接入副作用工具。
不在没有 BackendEffectCapability 的情况下做自动恢复。
不在没有 ApprovalMutationGuard 的情况下开放 business_create / business_update。
不在没有 Context decision build 绑定的情况下执行高风险动作。
```

### 1.3 架构落地顺序

```text
AgentRuntimeSnapshot
-> EventStore / Outbox
-> ExecutionLedger
-> WorkerQueue / ToolExecutor
-> BackendExecutionContract / BackendEffectCapability
-> ReconcileWorker
-> PolicyManager / ApprovalService / ApprovalMutationGuard
-> EvidenceRefResolver / ToolPolicyResolver
-> ContextBuilder / ContextBudget
-> LoopController / RootCauseRuleEngine
-> MigrationCoordinator / Checkpoint Freshness Gate
-> MemoryManager
-> 灰度上线与故障注入
```

---

## 2. 项目阶段总览

| 阶段 | 名称 | 核心目标 | 建议周期 | 是否 P0 |
|---|---|---|---:|---:|
| Phase 0 | 架构冻结与工程准备 | 冻结状态机、枚举、API、DB migration、灰度策略 | 1 周 | 是 |
| Phase 1 | Runtime 基础事实源 | Run、Snapshot、EventStore、Outbox、SSE、Checkpoint | 2 周 | 是 |
| Phase 2 | Ledger 与 Worker 执行底座 | ExecutionLedger、WorkerQueue、ToolExecutor、Effect Submission State | 2-3 周 | 是 |
| Phase 3 | Backend Contract 与 Reconcile | operation 级 BackendEffectCapability、ReconcileWorker、下游适配 | 2-3 周 | 是 |
| Phase 4 | 权限与审批闭环 | 三阶段权限、ApprovalLineage、ApprovalMutationGuard、审批 UI | 2 周 | 是 |
| Phase 5 | Loop / Evidence / Context / RootCause | EvidenceRef、ContextBudget、LoopController、RootCauseRuleEngine | 3 周 | 是/P1 |
| Phase 6 | Migration / Memory / 生产硬化 | MigrationCoordinator、Checkpoint Freshness、Memory、故障注入、监控 | 2-3 周 | P1/P2 |

建议总周期：12-16 周。

---

## 3. 团队与模块分工

### 3.1 Runtime 后端组

负责模块：

```text
AgentOrchestrator
AgentRuntimeSnapshot
StateStore / CheckpointStore
ExecutionLedgerService
WorkerQueueService
ToolExecutor
EventStore
OutboxPublisher
MigrationCoordinator
MetricsExporter
```

建议人力：2-3 名后端。

### 3.2 Backend Adapter 组

负责模块：

```text
BackendContractRegistry
IdempotentToolBackend SDK
ScenarioBackendAdapter
FlowBackendAdapter
TestCaseBackendAdapter
AISkillBackendAdapter
ReportBackendAdapter
DefectBackendAdapter
Reconcile Adapter
```

建议人力：1-2 名熟悉现有测试平台服务的后端。

### 3.3 Policy / Approval 组

负责模块：

```text
PolicyManager
PermissionService Adapter
ApprovalService
ApprovalLineage
ApprovalMutationGuard
Approval Expire Scanner
Approval Frontend Panel
```

建议人力：1 名后端 + 1 名前端。

### 3.4 Loop Intelligence 组

负责模块：

```text
ContextBuilder
ContextBudget
EvidenceRefResolver
ToolPolicyResolver
LoopController
RootCauseRuleEngine
MemoryManager
Prompt Bundle
AIService Adapter
```

建议人力：1-2 名后端或算法工程师。

### 3.5 QA / 稳定性组

负责：

```text
DB migration 验证
并发测试
Worker 崩溃测试
Reconcile 测试
Approval 并发测试
SSE 回放测试
性能压测
故障注入
灰度验收
Runbook 验证
```

建议人力：1-2 名测试工程师。

---

## 4. Phase 0：架构冻结与工程准备

### 4.1 目标

在编码前冻结工程边界，避免开发过程中出现状态名、表结构、错误码、锁协议、下游契约反复变化。

### 4.2 必须冻结的状态枚举

#### 4.2.1 Run 状态

```text
queued
running
paused
completed
failed
cancelled
migration_blocked
needs_human
```

#### 4.2.2 ToolCall 状态

```text
planned
leased
running_pre_effect
effect_sent
uncertain
reconciling
succeeded
failed
failed_retryable
obsolete
needs_migration
manual_intervention
```

#### 4.2.3 Effect Submission State

```text
none
send_intent_recorded
transport_sent_observed
backend_accepted
effect_committed
unknown
```

#### 4.2.4 BackendEffectCapability

```text
receipt_first
idempotency_index_only
legacy_reconcile_only
legacy_no_receipt
```

#### 4.2.5 Approval 状态

```text
pending
approved
rejected
expired
revoked
superseded
```

#### 4.2.6 Migration Block 状态

```text
open
resolved
cancelled
```

`GET /api/v1/agents/capabilities` 必须把本节冻结枚举作为机器可读契约输出，至少包含 `run_statuses`、`tool_call_statuses`、`effect_submission_states`、`backend_effect_capabilities`、`approval_statuses` 与 `migration_block_statuses`。后端契约测试应从 4.2 文档抽取这些枚举并与 capabilities 响应逐项比对，避免文档、Pydantic schema 与运行时能力出口漂移。

### 4.3 必须冻结的 API 错误码

```text
409 approval_stale_or_superseded
409 approval_epoch_conflict
409 approval_input_changed
409 tool_call_obsolete
409 run_migration_blocked
409 checkpoint_stale_replan_required
403 permission_revoked_before_execution
422 backend_contract_unsupported
423 tool_call_uncertain_reconcile_required
424 backend_reconcile_not_supported
424 backend_capability_too_weak
422 memory_event_not_stale_event
500 event_outbox_write_failed
```

后端契约测试必须从本节抽取完整冻结错误码清单，并与架构文档错误码表逐项比对；新增、删除或重命名 code 时必须同步两份 Harness 文档并补充对应回归断言，避免实现仍使用冻结 code 但文档或测试只覆盖局部子集。

### 4.3.1 必须冻结的 Memory 治理配置

Memory 模块在进入编码前必须冻结以下配置，不能等实现时临时猜：

```text
Memory source_type 初始 confidence 表
Memory retrieval_profile 默认权重与 hard gate
contradiction_penalty 计算公式与 severity multiplier
Memory -> EvidenceRef 转换规则
Memory high-risk usage gate
Memory 与 EvidenceWatch 的 stale 联动规则
```

冻结要求：

- `source_type` 未配置 profile 时，不允许创建 active memory。
- `retrieval_profile` 未配置时，不允许 MemoryManager 检索。
- `contradiction_penalty` 必须有单元测试，禁止留空函数名。
- `contradiction_penalty` 的 severity multiplier、默认 profile 上限与确定性公式必须由后端文档驱动测试锁住，测试从架构文档 15.5 抽取表格和默认上限，并与 `SEVERITY_MULTIPLIER`、`compute_contradiction_penalty` 对齐。
- Memory 检索结果必须包装成 `ref_type=memory` 的 EvidenceRef。
- 后端契约测试必须从架构文档 Memory source profile 与默认 retrieval profile 表格抽取冻结配置，并与 `MemorySourceProfileResolver` / `MemoryRetrievalProfileResolver` 默认 seed 精确对齐，确保初始 confidence、authority、min_confidence、max_stale_score、change_reason 和权重治理字段不会漂移。

### 4.4 必须冻结的灰度等级

Required rollout matrix:

| level | summary | allowed_side_effect_classes | blocked_side_effect_classes | required_gates |
|---|---|---|---|---|
| L0 | read-only tools | read_only | deterministic_compute, draft_only, execution_record, business_create, business_update, external_effect, destructive | Run/Event/Snapshot available |
| L1 | deterministic compute and draft-only tools | read_only, deterministic_compute, draft_only | execution_record, business_create, business_update, external_effect, destructive | Ledger/Worker available |
| L2 | execution-record tools with reconcile support | read_only, deterministic_compute, draft_only, execution_record | business_create, business_update, external_effect, destructive | Reconcile minimum support |
| L3 | business-create tools | read_only, deterministic_compute, draft_only, execution_record, business_create | business_update, external_effect, destructive | Approval; Reconcile; Execute-time permission check |
| L4 | receipt-first business operations | read_only, deterministic_compute, draft_only, execution_record, business_create, business_update | external_effect, destructive | durable receipt; operation-level capability |
| L5 | external-effect and destructive operations | read_only, deterministic_compute, draft_only, execution_record, business_create, business_update, external_effect, destructive | none | strong approval; full evidence; rollback/manual path |

后端契约测试必须从开发计划和架构文档抽取 Required rollout matrix，并与 `AgentReleaseGateService.ROLLOUT_LEVELS`、当前 snapshot 的 allowed/blocked side effect classes 以及 expansion gates 精确对齐。

### 4.5 交付物

```text
状态枚举文档
API 错误码文档
DB migration 初稿
Backend Operation 接入矩阵
灰度发布矩阵
锁协议说明
故障注入清单
```

### 4.6 验收标准

- 所有状态枚举只有一种语义。
- 所有 P0 状态转换都有表格或状态图。
- 每个高风险接口都有明确错误码。
- 每个下游 operation 都能声明 BackendEffectCapability。
- 审批锁协议和批量扫描锁协议均已评审。

---

## 5. Phase 1：Runtime 基础事实源

### 5.1 目标

实现 Agent 的最小事实源：Run、Snapshot、EventStore、Outbox、SSE、Checkpoint。此阶段不接入真实副作用工具。

### 5.2 数据库任务

#### 5.2.1 ai_agent_runtime_snapshots

用途：冻结 Tool Registry、Skill Manifest、Schema、Adapter、Prompt、Policy。

关键字段：

```text
snapshot_id
project_id
created_by
runtime_hash
tool_registry_hash
manifest_bundle_hash
prompt_bundle_hash
policy_version_hash
tools_json
manifests_json
adapters_json
policies_json
created_at
```

开发要求：

- run 创建时必须绑定 runtime_snapshot_id。
- 历史 run resume 时只能读取 run.runtime_snapshot_id。
- 相同 runtime_hash 可复用 snapshot。
- Adapter 不支持旧 snapshot 时，进入 needs_migration 或 migration_blocked。

#### 5.2.2 ai_agent_runs

用途：Run 级事实源。

关键字段：

```text
run_id
project_id
user_id
conversation_id
intent
status
current_iteration
current_step_index
max_iterations
runtime_snapshot_id
last_checkpoint_id
started_at
completed_at
error_code
error_message
created_at
updated_at
```

开发要求：

- 支持创建、查询、取消、恢复。
- status 只能按状态机流转。
- cancel 后不得调度新的 tool_call。

#### 5.2.3 ai_agent_events

用途：事件事实源。

关键字段：

```text
run_id
event_seq
event_type
payload_json
created_at
```

开发要求：

- event_seq 在 run 内递增。
- SSE 只读 EventStore。
- EventStore / Outbox 同事务写入失败必须让主事务失败，并返回 `500 event_outbox_write_failed`；该错误码属于 Phase 0 冻结 API code，不能退化成原始数据库异常。

#### 5.2.4 ai_agent_outbox

用途：异步发布 SSE / 通知。

关键字段：

```text
event_id
status
publish_attempts
next_retry_at
last_error
created_at
updated_at
```

开发要求：

- Outbox 发布失败不影响 EventStore 事实。
- 支持重试和死信。
- 支持 outbox_publish_lag_ms 指标。
- `POST /api/v1/agents/outbox/publish` 属于 admin-only 全局后台处理入口，普通项目用户不得手动触发 Outbox 发布或重试批处理。

Required Outbox publish payload contract:

```text
fields=attempted,published,failed,dead_letter,pending_remaining,outbox_publish_lag_ms
source=AgentOutboxPublisher.publish_pending
```

#### 5.2.5 ai_agent_checkpoints

用途：恢复 Loop 所需运行态摘要。

关键字段：

```text
run_id
checkpoint_seq
runtime_snapshot_id
iteration
current_step_index
active_plan_summary_json
active_draft_summary_json
last_failure_summary_json
recent_tool_call_ids_json
pending_approval_tool_call_ids_json
context_compaction_object_key
freshness_metadata_json
created_at
```

开发要求：

- checkpoint 不用于判断副作用是否重放。
- 副作用恢复只看 ExecutionLedger。
- checkpoint resume 前必须支持 Freshness Gate。

### 5.3 API 任务

```text
GET  /api/v1/agents/capabilities
GET  /api/v1/agents/alerts
GET  /api/v1/agents/dashboard
GET  /api/v1/agents/launch-audit
GET  /api/v1/agents/backend-completion-audit
GET  /api/v1/agents/release-gates/promotion
GET  /api/v1/agents/worker-queue/audit
GET  /api/v1/agents/model-health
POST /api/v1/agents/conversation-smoke
GET  /api/v1/agents/conversations
GET  /api/v1/agents/conversations/{conversation_id}/runs
GET  /api/v1/agents/conversations/{conversation_id}/transcript
GET  /api/v1/agents/conversations/{conversation_id}/export
GET  /api/v1/agents/runs
POST /api/v1/agents/runs
GET  /api/v1/agents/runs/{run_id}
GET  /api/v1/agents/runs/{run_id}/summary
GET  /api/v1/agents/runs/{run_id}/actions
GET  /api/v1/agents/runs/{run_id}/events
GET  /api/v1/agents/runs/{run_id}/events/replay-audit
POST /api/v1/agents/runs/{run_id}/cancel
GET  /api/v1/agents/runtime-snapshots/{snapshot_id}
```

`GET /api/v1/agents/model-health` is the Agent model-provider diagnostic endpoint. Default `live=false` only reports provider configuration and nullable live probe fields without calling DeepSeek and must never expose `DEEPSEEK_API_KEY`. `live=true` is admin-only and runs a minimal `AIService.chat_stream()` probe, returning `reachable`, `latency_ms`, `first_delta_received`, `completed`, `model`, `finish_reason`, `error_code`, and `error_message`. This endpoint is used to diagnose the frontend case where `POST /api/v1/agents/runs` succeeds but no assistant reply appears.

`POST /api/v1/agents/conversation-smoke` is an admin-only end-to-end Agent conversation diagnostic. Unlike `model-health`, it creates a real Agent Run, runs `AgentConversationRunner` synchronously, and returns the resulting summary plus event chain. It must use the same `AIService.chat_stream()` and EventStore path as normal Agent conversations, so it can prove whether `POST /runs -> model.delta -> run.completed -> summary` is working.

Required Agent Conversation smoke payload contract:

```text
fields=project_id,run_id,conversation_id,status,completed,first_delta_received,assistant_visible,assistant_message,error_code,error_message,event_types,latest_event_sequence,run_summary,latency_ms,generated_at
run_summary_fields=run,assistant_message,assistant_visible,completion_source,model_invoked,model,finish_reason,usage,event_count,latest_event_sequence,latest_event_types,tool_call_count,pending_tool_call_count,approval_count,pending_approval_count,migration_block_count,open_migration_block_count,memory_usage_count,blocking_tool_call_ids,terminal,can_cancel,can_resume,updated_at
source=AgentConversationSmokeRead
```

Harness 文档中出现的 `/api/v1/agents...` 路径及其 HTTP method 必须进入 FastAPI OpenAPI；测试需要从开发计划和架构文档抽取 Agent API method+path 并与 `create_app().openapi()["paths"]` 对齐，历史 `{id}` memory 占位符归一化为当前 `{memory_id}`。

### 5.4 测试任务

- 创建 run 后必须生成或复用 snapshot。
- run.started / run.completed 必须写入 EventStore。
- `POST /api/v1/agents/runs` 创建普通对话 run 后必须启动 `AgentConversationRunner`；MySQL 和文件 SQLite 都应提交后台 worker，只有 in-memory SQLite 单元测试库可以跳过后台线程，避免跨线程测试库不可见。若事件链停在 `run.started` 且只有 heartbeat，必须能通过 `/events/snapshot` 与 `model-health` 判断是 runner 未启动、模型未配置还是前端 stream 未消费。
- 后端仓库必须保留可重复的真实链路诊断脚本 `scripts/agent_conversation_e2e_check.py`。该脚本在真实配置数据库和 DeepSeek provider 上执行普通用户 `POST /api/v1/agents/runs`，并只在 live health reachable、事件链包含 `model.started` 和至少一个 `model.delta`、最终出现 `run.completed`、summary 返回 `assistant_visible=true` 时成功。它用于区分后端链路故障和前端 SSE/parser/rendering 故障，不得打印 `DEEPSEEK_API_KEY`。
- `AgentRunCreateRequest.auto_complete` 只能用于后端 smoke/debug 和 EventStore/Outbox 回归；真实 Codex 式对话必须保持 false 并走 `AIService.chat_stream()`。auto-complete 结果必须标记 `completion_source=smoke_auto_complete`、`model_invoked=false`、`assistant_visible=false`，前端不得渲染为真实 assistant 回复。
- 对话型 run 必须通过 AIService 写入 model.started / model.delta / model.completed，并最终写入 run.completed；普通自然语言回复的 model.delta 必须在模型 stream 完成前实时进入 EventStore/SSE。涉及项目上下文、场景组合、保存动作等工具规划轮时，后端可先静默收流解析工具请求，疑似或混合的 agent_tool_request 内容必须先缓冲/修复，避免工具 JSON 被当作 assistant 气泡展示；若静默规划轮最终产出普通文本，应只补发合并后的可见 `model.delta`，避免长文本逐 token 回放压住 EventStore/SSE；如发生抑制或格式修复，应写入 `model.tool_request_stream_suppressed`、`model.tool_request_invalid` 等审计事件。用户可见自然语言回复必须是 GitHub Flavored Markdown；后端在写入 `model.completed.content` 与 `run.completed.result.message` 前必须校准最终 Markdown，若修复了模型流式内容，应先写入 `model.markdown_normalized(replace_content=true)` 供前端替换当前气泡。
- 同一个用户问题内允许多次 LLM 调用，必须用 Loop trace 字段把每次调用串起来：`model.started`、`model.delta`、`model.markdown_normalized`、`model.completed`、`model.stream_interrupted` 应携带 `iteration_id`、`model_call_id`、`loop_step`，工具计划、修复、最终总结和意图能力 guard 不得在事件层混成一次不可解释的模型调用；`tool.*` 审计事件应在可得时携带 `tool_call_id` 和 `decision_reason`。
- 对话型 run 的系统提示必须保持 prompt cache 友好的稳定前缀：ToolRegistry 清单按工具名排序，工具 JSON 使用固定字段排序和紧凑分隔符序列化；同一 runtime hash 下重复构建的系统提示字符串应保持一致。
- 对话型 run 的业务提示规则必须优先沉淀为 Codex-style Agent Skill：`app/agent_skills/*/SKILL.md` 使用 `name`、`description`、后端私有 `triggers` 以及 `guard_*` / `routing_*` frontmatter 描述目录、触发范围、窄 guard 预检查、unsupported capability guard（例如 `guard_unsupported_capability`）、需要工具的私有路由（例如 `routing_requires_tool`）和成功工具后的必需 follow-up（例如 `routing_required_tool_after_success`），正文记录工具顺序、能力边界和输出约束；窄 guard/classifier 的长提示词和 guard 最终回复应放在同 Skill 目录的后端私有资源文件中，由 `AgentSkillRegistry.private_resource_text()` 读取。`AgentSkillRegistry` 在系统提示中只注入稳定 Skill catalog，每次 run 再按 intent 渐进加载相关 Skill 正文。前端 `GET /api/v1/agents/skills` 只能读取 `{name,description}` 元数据，不读取或展示 `SKILL.md` 正文、私有资源、`triggers`、`routing_requires_tool` 或 guard/routing hints。`ContextBuilder.build_metadata_json` 只能记录本轮选中 Skill、匹配 routing rule 和 RuntimeSnapshot 的摘要/hash，供 required-tool 修复、工具前置阻断和 Runbook 诊断追溯，不得泄露私有 frontmatter 原文、Skill 正文、完整工具 schema 或 manifest bundle。
- 对话型 run 组装服务端 conversation history 时必须有预算压缩：长历史超过估算 token 预算后，较早轮次压成 system 摘要，最近若干轮保留截断内容，并写入 `context.history_compacted` 审计事件；该摘要不作为 assistant 气泡展示。
- 对话型 run 必须支持软件测试领域通用问答：当用户询问测试理论、用例设计、接口/WebSocket 测试、断言与提取器、测试数据、环境配置、Mock、缺陷定位、执行诊断、回归策略、CI、风险覆盖、报告解读、测试计划或平台使用建议，且不需要读取项目实时事实或创建/保存平台对象时，Agent 应直接自然语言回答，不得声称没有通用回答能力；超出软件测试领域时必须说明能力边界。
- 对话型 run 调用模型前必须用 `normal_plan_v1` 检索项目 Memory，按 `usage_role=conversation_context` 注入模型上下文，并写入 `memory.context_injected` 与 `AgentMemoryUsageEvent(active_for_policy=false)`；该 Memory 只能辅助自然语言规划，不得替代高风险动作的 EvidenceRef/审批/工具结果。
- 当模型按受控协议请求工具时，AgentConversationRunner 必须写入 model.tool_request_detected，通过 ExecutionLedgerService 创建 ToolCall，复用 ToolExecutor 执行安全工具，再写入 tool.result_observed 并把工具结果回灌给下一轮模型生成最终自然语言回复。
- 场景组合必须采用 query-first 工具链，但规则来源必须可扩展：`scenario-composition/SKILL.md` 用私有 `routing_required_tool_after_success` 声明 `testcase.query_project_cases` 成功后必须继续 `scenario.compose_draft`，`scenario.compose_draft` 的 ToolSpec 用后端私有 `required_successful_tool_before` 声明执行前必须已有成功 query 结果。若模型在同一 run 内没有成功的 `testcase.query_project_cases` 结果就直接请求 `scenario.compose_draft`，AgentConversationRunner 必须按 ToolSpec 前置规则在执行前阻断该 ToolCall，写入 `tool.failed`、`tool.result_observed` 和 `error_code=scenario_compose_requires_case_query`，并把这个失败结果回灌给模型继续纠正；若 query 成功且有候选用例但模型只输出自然语言分析而不 compose，必须按 Skill follow-up rule 写入 `model.required_tool_missing(after_tool, required_tool)` 并静默修复为 `scenario.compose_draft` 请求。
- 任意成功 ToolCall 输出 `warnings`、`issues`、`diagnostics`、`errors` 或 `valid=false` 时，AgentConversationRunner 必须通过 `ToolResultPolicy` 进入通用工具结果质量闭环：抽取质量问题，拆分为可自动修复项、用户/外部配置阻断项和待模型继续判断项，并把分类与推荐修复路径回灌给模型。推荐修复路径必须来自对应 `ToolSpec.tool_result_repair_guidance` 后端私有字段，未知工具才使用通用 fallback，避免 `ToolResultPolicy` 继续维护按工具名分支。硬编码业务字段、未动态绑定、提取器路径、断言 expected、数据集变量、schema/type/format 校验等应优先通过 read/query/draft/validate/dry-run 安全工具继续修复或验证；鉴权令牌、账号密码、密钥、审批或没有平台来源的私有输入才交给用户确认。失败 ToolCall 若错误属于输入、schema、validation、草稿结构或字段格式，也必须进入同类修复闭环，优先修正参数并重试安全工具；若同一工具连续两次以相同 `error_code` 与 `error_message` 失败，必须写入 stop 用 ContextBuild 与 `loop.observed(RC_NO_PROGRESS_PURE)`，并以 `run.failed(agent_repair_no_progress)` 停止继续重试。
- 用户疑似要求保存正式场景但 ToolRegistry 尚未暴露保存工具时，AgentConversationRunner 必须通过命中 Skill 的私有 `guard_unsupported_capability` 规则处理：规则声明预检查关键词、缺失工具集合、分类 prompt、分类 JSON 字段、最终消息资源和 `completion_source`。分类 prompt 与最终回复必须来自 `scenario-composition` Skill 的私有资源文件，而不是 Runner 主 prompt 或 Python 消息常量。只有确认需要保存时才直接说明当前只能生成草稿或 dry-run，不能假装保存，也不能重新 compose 草稿冒充保存结果。若用户明确说“不要保存/仅生成草稿”，必须继续进入 query-first 场景组合链路。
- 当模型输出的工具请求 JSON 不合法时，AgentConversationRunner 必须写入 `model.tool_request_invalid`，给模型一次格式修复机会；修复成功写入 `model.tool_request_repaired` 并继续进入 ToolCall，修复失败写入 `model.tool_request_repair_failed` 并按模型错误终止 run。
- 当模型请求的 ToolCall 因 approval_required 进入 `needs_human` 时，approve 后的 `POST /api/v1/agents/runs/{run_id}/resume` 必须先通过 Checkpoint Freshness Gate，再执行已批准的 blocking ToolCall，写入 `tool.result_observed(resumed_after_approval=true)`，清理 `blocking_tool_call_ids_json`，并由 AgentConversationRunner 基于工具结果生成最终自然语言回复。
- 模型工具请求 JSON 只作为 EventStore 审计内容和 ToolCall 规划输入，不作为前端 assistant 气泡展示内容；最终用户可见回复以后续 `model.delta`、`model.markdown_normalized`、`model.completed.content` 和 `run.completed.result.message` 为准，其中最终 summary 必须可直接按 Markdown 渲染。工具结果后的最终回复默认受预算约束，只输出已完成、已修复/验证、剩余阻断项和下一步；完整步骤、草稿结构和原始输出由 ToolCall 详情、summary 或报告详情承载。
- SSE 断线后可用 Last-Event-ID 续播，且 `GET /api/v1/agents/runs/{run_id}/events` 必须先按 run 所属项目校验访问权限，项目外用户不得订阅事件流。前端调试、断线恢复前校准或 ReadableStream 解析异常时，可用 `GET /api/v1/agents/runs/{run_id}/events/snapshot` 拉取同一 EventStore 的 JSON 快照；该接口也必须按 run 所属项目校验访问权限，不能成为新的事实源。`event_seq` 是 run-scoped cursor，若客户端误把其他 run 的较大 Last-Event-ID/after_sequence 带到当前 run，后端必须重置为 0 并重放当前 run 事件，避免 heartbeat-only 连接。若 `queued/running` run 超过 `AGENT_RUN_STALE_TIMEOUT_SECONDS` 没有新的 EventStore 事件，后端读路径必须自动写入 `run.failed(error_code=agent_run_stale_worker_lost)`，让前端结束 pending 状态并进入可重试/Runbook 诊断。
- Outbox 发布失败后可重试。
- cancel 后不能继续调度 tool_call，也不能在外部取消已经写入 `run.cancelled` 后继续写入 `model.completed(final_summary=true)` 或 `run.completed`。`AgentConversationRunner` 必须在模型 stream、工具请求 repair、ToolCall 创建前和 final summary 结束后重新读取 run terminal 状态，避免 Stop 与后台生成竞争。
- 达到 `max_iterations` 后进入最终总结前，AgentConversationRunner 必须先写入 stop 用 ContextBuild 与 `loop.observed(RC_MAX_ITERATIONS)`，再调用 `final_summary`；该 observation 是审计/Runbook 状态，不作为 assistant 气泡展示。
- checkpoint 可恢复 iteration 和 step_index。

### 5.5 验收标准

- 无工具调用的 run 可端到端完成。
- 软件测试领域通用问答不需要 ToolCall 即可端到端完成，系统提示必须明确测试领域回答范围、非测试领域边界和需要真实项目资源时的工具协议。
- 模型驱动的安全工具调用可端到端完成：model.tool_request_detected -> tool.planned -> tool.running -> tool.completed -> tool.result_observed -> 后续 model.delta -> run.completed。
- 对话型 run 的自然语言流式输出必须保持低延迟：首个可见 `model.delta` 在模型 stream 尚未结束时立即写入 EventStore，后续极小 delta 可按短时间窗口或字符阈值微批提交以降低数据库事务频率；SSE 对 `queued/running` run 使用短轮询，对非活跃状态保持普通轮询和 heartbeat。前端仍只依赖 `model.delta.content` 追加语义，不依赖 token 粒度。
- 陈旧 active run 兜底可证明：构造只有 `run.queued/run.started` 且最新事件早于 `AGENT_RUN_STALE_TIMEOUT_SECONDS` 的 `running` run，读取 run/detail/snapshot/SSE 事件时必须变为 `failed` 并出现 `run.failed(agent_run_stale_worker_lost)`，前端不再无限显示“正在思考”。
- 跨 run cursor 防御可证明：对当前 run 使用大于 `latest_event_sequence` 的 `Last-Event-ID/after_sequence` 读取 SSE 或 snapshot 时，后端必须重置 cursor 并返回当前 run 的已落库事件，而不是只返回 heartbeat。
- 场景组合工具调用可证明 query-first：正常路径必须出现 `testcase.query_project_cases` 后再出现成功的 `scenario.compose_draft`；异常路径中直接 `scenario.compose_draft` 会被 `scenario_compose_requires_case_query` 阻断，后续模型仍可根据回灌错误改为 query -> compose -> final answer。
- 通用工具结果质量闭环可证明：第一次 ToolCall 返回可修复 warnings/issues/diagnostics 后，下一轮模型必须收到质量闭环规则、问题分类和来自对应 ToolSpec 私有 `tool_result_repair_guidance` 的推荐修复路径，并可再次调用合适的安全工具修复或验证；最终回复只把鉴权令牌等用户阻断项或已重试仍无法自动修复的剩余风险交给用户；如果同一失败签名重复出现，必须出现 `loop.observed(RC_NO_PROGRESS_PURE)` 与 `run.failed(agent_repair_no_progress)`，而不是继续第三轮同类 ToolCall。
- 模型工具请求格式轻微错误时可自动修复一次：model.tool_request_invalid -> model.tool_request_repaired -> model.tool_request_detected -> tool.result_observed -> 后续 model.delta -> run.completed；如果能从自然语言中的单个 fenced 工具块本地挽救，则可不额外触发 `model.started(repair_attempt=true)`，并在 `model.tool_request_repaired.repair_strategy` 标记为 `salvaged_fenced_tool_request`。
- 工具规划轮不会泄露内部 `agent_tool_request` JSON；混合自然语言与工具请求会触发 `model.tool_request_invalid` 修复或本地挽救，query 后缺失必需 compose 会触发 `model.required_tool_missing -> model.required_tool_repaired`，失败 ToolCall 的 schema/input 错误会触发重试。
- 保存正式场景无工具时可证明 guard：`scenario-composition/SKILL.md` 的私有 `guard_unsupported_capability` 规则会先做关键词预检查和结构化语义分类，确认需要持久化且缺少 `scenario.save/create/persist` 后不调用 `scenario.compose_draft`，直接用 Skill 私有最终消息完成并说明当前无保存工具；“不要保存/仅生成草稿”的请求不得触发该 guard，必须继续 query -> compose。
- 审批阻断的模型工具调用可在 approve + resume 后端到端完成：approval.approved -> resume freshness check -> tool.completed -> tool.result_observed -> run.resumed -> 后续 model.delta -> run.completed；resume payload 必须返回 `executed_tool_call_ids`。
- 对话型 run 命中项目 Memory 时，事件流必须包含 `memory.context_injected`，`GET /api/v1/agents/memory-usage-events` 带 `run_id` 查询参数必须能看到 `usage_role=conversation_context`、`retrieval_profile=normal_plan_v1`、`active_for_policy=false` 的 usage event。
- 前端发送普通对话 prompt 后，SSE 可在模型 stream 尚未完成时收到首个 model.delta 增量，并在 terminal 事件后关闭；多个模型小片段可被后端合并成一个 `model.delta.content`，但按顺序追加后必须还原完整 assistant 回复。工具规划轮如果静默解析后返回普通文本，也必须只补发合并后的完整可见 delta，避免按原始 token 数写入大量事件。
- 前端 Stop 当前 run 后，后端必须保持 `cancelled` 为最终状态；即使取消发生在工具结果回灌后的 final summary 流式生成中，也不得被后台 runner 覆盖为 completed。
- EventStore 可重放 run 全部事件。
- Snapshot 查询结果与 run 创建时一致。
- SSE 不作为事实源，只作为传输层。

---

## 6. Phase 2：ExecutionLedger、WorkerQueue 与 ToolExecutor

### 6.1 目标

实现工具调用的事实源、幂等键、Worker lease、heartbeat、orphan 恢复、多阶段 effect_submission_state。此阶段只开放 read_only、deterministic_compute、draft_only。

### 6.2 数据库任务

#### 6.2.1 ai_agent_tool_calls

关键字段：

```text
run_id
step_index
attempt_index
runtime_snapshot_id
tool_name
tool_version
schema_hash
manifest_hash
idempotency_scope
idempotency_key
base_side_effect_class
resolved_side_effect_class
base_replay_policy
resolved_replay_policy
policy_reason_json
status
execution_phase
effect_submission_state
effect_boundary_crossed
downstream_send_intent_at
downstream_request_observed_sent_at
downstream_acceptance_id
downstream_acceptance_at
input_hash
input_json_redacted
evidence_refs_json
output_hash
output_json_redacted
raw_output_object_key
permission_snapshot_json
required_permissions_json
approval_required
approval_scope_hash
lease_owner
lease_expires_at
last_heartbeat_at
recovery_decision
backend_name
backend_operation
backend_contract_version
backend_effect_capability
external_resource_type
external_resource_id
error_code
error_message
created_at
updated_at
```

必需索引：

```sql
UNIQUE KEY uk_agent_tool_idem (idempotency_scope, idempotency_key);
UNIQUE KEY uk_agent_tool_step (run_id, step_index, attempt_index);
INDEX idx_agent_tool_status (status, lease_expires_at);
INDEX idx_agent_tool_run (run_id, step_index);
INDEX idx_agent_tool_backend (backend_name, backend_operation, backend_contract_version);
```

#### 6.2.2 ai_agent_worker_queue

关键字段：

```text
queue_id
run_id
tool_call_id
status
priority
available_at
lease_owner
lease_expires_at
attempt_count
last_error_code
created_at
updated_at
```

开发要求：

- DB-backed WorkerQueue 是事实源。
- Redis/MQ 只能做加速，不作为事实源。
- claim 必须原子化。
- 多 Worker 不得重复执行同一 tool_call。
- 后端通过 `AgentWorkerQueueAuditService` 暴露当前队列审计快照，统计 active queue、expired lease、duplicate active lease 与 oldest queued age；`GET /api/v1/agents/worker-queue/audit` 用于验证多 Worker claim 不重复与 lease 扫描稳定性。
- `GET /api/v1/agents/worker-queue/audit` 的权限边界必须区分全局审计与项目审计：不带 `project_id` 时仅 admin 可读取全局队列审计；带 `project_id` 时必须校验项目访问权限后只返回该项目 run 的队列快照。

### 6.3 服务任务

#### 6.3.1 ToolRegistry

- 从 AgentRuntimeSnapshot 读取 ToolSpec。
- 内置工具的 ToolSpec 需要声明后端私有 `backend_handler`，由 `AgentToolBackend` 从 ToolRegistry 解析并执行；需要执行前顺序校验的工具可声明后端私有 `required_successful_tool_before`、`missing_prerequisite_error_code` 和 `missing_prerequisite_next_action`；需要工具结果质量闭环差异化建议的工具可声明后端私有 `tool_result_repair_guidance`，由 `ToolResultPolicy` 读取；这些字段不进入模型初始工具清单或前端契约，避免 manifest、执行 map、前置校验和结果修复策略分叉。
- 禁止读取最新 manifest 来恢复历史 run。
- 校验 tool input schema。
- 校验 tool_version / schema_hash / manifest_hash。

#### 6.3.2 ToolPolicyResolver

- 根据 ToolSpec 默认策略和 EvidenceRef active policy refs 解析单次调用策略。
- 输出 resolved_side_effect_class。
- 输出 resolved_replay_policy。
- 输出 resolved_requires_approval。
- 输出 policy_reason_json。

#### 6.3.3 ToolExecutor

执行顺序必须固定：

```text
1. claim worker queue item
2. acquire tool_call lease
3. execute-time permission check
4. mark running_pre_effect
5. record send_intent_recorded
6. 根据 backend capability 调用 backend
7. 更新 transport_sent_observed / backend_accepted / effect_committed / unknown
8. mark succeeded / failed / uncertain
9. append EventStore
10. enqueue Outbox
```

### 6.4 Effect Submission State 恢复规则

| 状态 | 含义 | 恢复策略 |
|---|---|---|
| none | 未触达下游 | 可重新入队 |
| send_intent_recorded | 本地准备调用下游，但不确定请求是否发出 | reconcile not_found 可用同一 idempotency_key 安全重试 |
| transport_sent_observed | 请求可能已发出 | 不得盲重试，先 reconcile/backoff |
| backend_accepted | 下游 durable receipt 已持久化 | reconcile not_found 是下游契约异常 |
| effect_committed | 确认副作用完成 | resume 复用结果 |
| unknown | 无法判断 | reconcile 或人工 |

### 6.5 首批工具

```text
project.read_context
testcase.query_project_cases
scenario.compose_draft
testcase.validate_schema
report.read_summary
```

暂不接：

```text
scenario.save
scenario.execute_real
defect.create
environment.update
external_effect
destructive
```

### 6.6 测试任务

- Worker claim 后崩溃。
- running_pre_effect 后崩溃。
- send_intent_recorded 后崩溃。
- lease 过期后重新入队。
- 同一 idempotency_key 重复提交被唯一索引拦截。
- read_only 工具可安全重试。
- draft_only 工具可复用或重放。
- EventStore 写失败时主事务回滚。

### 6.7 验收标准

- ToolCall 状态机完整可测。
- Worker 崩溃不会导致 running 永久卡死。
- 所有工具调用都有 idempotency_key。
- 所有工具状态变化都有 EventStore 事件。
- 未实现 BackendEffectCapability 的高风险工具无法接入。

---

## 7. Phase 3：BackendExecutionContract 与 Reconcile

### 7.1 目标

实现 operation 级 BackendEffectCapability 和 ReconcileWorker，使 uncertain 能在安全范围内自动收敛。

### 7.2 数据库任务

#### 7.2.1 ai_agent_backend_contracts

唯一键必须是：

```text
backend_name + backend_operation + backend_contract_version
```

不能只按 backend_name 绑定能力，因为同一个服务的不同 operation 可能具有不同接入能力。

关键字段：

```text
backend_name
backend_operation
backend_contract_version
request_schema_hash
output_schema_hash
reconcile_contract_version
result_adapter_version
effect_capability
compatibility_status
support_until
owner_team
created_at
updated_at
```

Backend operation contract 查询接口 `GET /api/v1/agents/backend-contracts/{backend_name}/operations/{backend_operation}` 是 admin-only 全局治理契约视图，用于读取 request/output schema hash、reconcile contract、result adapter 与 effect capability；普通项目用户不能枚举跨 backend 的 contract/capability 信息。

Required backend adapter contract defaults:

```text
reconcile_contract_version=reconcile-v1
result_adapter_version=v1
compatibility_status=active
owner_team=test-platform
unsafe_side_effect_requires_backend_contract=true
seed_contracts_from_tool_registry=true
```

Backend Adapter SDK / ToolSpec / Reconcile Contract 必须共享同一份 operation 级契约：ToolRegistry 中每个接入 Agent 的 ToolSpec 都要声明 `BackendContractSpec`，其 request/output schema hash 必须由 ToolSpec input/output schema 计算得到；`AgentRuntimeService.ensure_backend_contracts()` 只能从 ToolRegistry seed `ai_agent_backend_contracts`，Release Gate `tool_matrix` 也必须读取同一 backend contract 状态，防止 adapter SDK、DB 治理视图和灰度门禁出现三份口径。

#### 7.2.2 ai_agent_reconcile_attempts

关键字段：

```text
tool_call_id
attempt_seq
backend_name
backend_operation
backend_contract_version
result_status
raw_result_object_key
error_code
error_message
next_retry_at
created_at
```

### 7.3 BackendEffectCapability 分级

| 能力 | 下游要求 | Agent 恢复能力 |
|---|---|---|
| receipt_first | 下游先写 durable receipt，再执行真实副作用 | 最强，可区分 backend_accepted |
| idempotency_index_only | 下游能按 idempotency_key 反查最终结果 | 可自动 reconcile，但不能证明请求已被接收 |
| legacy_reconcile_only | 只能通过业务字段弱反查 | 只允许低风险工具有限恢复 |
| legacy_no_receipt | 无可靠反查 | 高风险工具禁止自动恢复 |

### 7.4 ReconcileWorker 任务

流程：

```text
1. 扫描 uncertain / reconciling tool_call
2. 读取 backend_name + backend_operation + backend_contract_version
3. 读取 BackendEffectCapability
4. 调用对应 backend.reconcile
5. 写 ai_agent_reconcile_attempts
6. 根据结果更新 tool_call
7. 必要时创建 migration block
8. 写 EventStore / Outbox
```

### 7.5 ReconcileResult 标准

```json
{
  "status": "succeeded | running | failed | not_found | conflict | unsupported_schema_version",
  "external_resource_type": "scenario_execution",
  "external_resource_id": "12345",
  "backend_contract_version": "scenario-execute-v1",
  "output_schema_version": "v1",
  "canonical_summary_json": {},
  "raw_output_object_key": "obj://...",
  "error_code": null,
  "error_message": null
}
```

Required Reconcile contract:

```text
eligible_tool_call_statuses=uncertain,reconciling
result_statuses=succeeded,running,failed,not_found,conflict,unsupported_schema_version
schema_support_values=supported,unsupported,adapter_required
success_result_statuses=succeeded
backoff_result_statuses=running,not_found
terminal_failure_result_statuses=failed
direct_manual_result_statuses=conflict
state_dependent_result_statuses=not_found
migration_result_statuses=unsupported_schema_version
backoff_effect_states=transport_sent_observed
backoff_capabilities=receipt_first,idempotency_index_only
result_envelope_fields=found,status,schema_support,backend_contract_version,output_schema_version,external_resource_type,external_resource_id,acceptance_id,canonical_summary_json,raw_output_object_key,error_code,error_message
summary_fields=run_id,processed,skipped_backoff,reconciled,still_uncertain,needs_migration,manual_intervention,tool_call_ids,skipped_backoff_tool_calls
skipped_backoff_fields=tool_call_id,next_retry_at,attempt_seq,result_status
```

### 7.6 首批接入 operation

| 优先级 | Backend | Operation | 目标能力 |
|---|---|---|---|
| P0 | Scenario | execute_dry_run | idempotency_index_only |
| P0 | TestCase | execute | idempotency_index_only |
| P0 | AISkill | run | idempotency_index_only |
| P1 | Flow | execute | idempotency_index_only |
| P1 | Report | generate | idempotency_index_only |
| P1 | Defect | create | receipt_first 或强审批 |

### 7.7 测试任务

- send_intent_recorded + not_found => safe retry。
- transport_sent_observed + not_found => backoff，不盲重试。
- `ReconcileWorker` 必须读取最新 `AgentReconcileAttempt.next_retry_at`；未到窗口的 ToolCall 不调用 backend reconcile adapter，并在 `AgentRunReconcileRead.skipped_backoff` 与 `reconcile_backoff_active_total` 中可见。
- backend_accepted + not_found => backend contract incident。
- unsupported_schema_version => ToolCall needs_migration。
- legacy_no_receipt + business_create => manual_intervention，错误码固定为 `backend_reconcile_not_supported`。
- conflict => manual_intervention。
- succeeded reconcile => mark_succeeded_from_reconcile。
- running reconcile => still_running，延迟重试。
- `uncertain/reconciling` ToolCall 不允许被 WorkerQueue 直接执行；若误入执行队列，必须阻断执行并返回 `tool_call_uncertain_reconcile_required`，要求先走 reconcile。

### 7.8 验收标准

- 每个接入 operation 都声明 capability。
- ReconcileWorker 不把 unsupported_schema_version 当 not_found。
- 高风险 legacy_no_receipt 工具不能自动恢复。
- uncertain 在支持能力下可以自动收敛。
- 所有 reconcile attempt 可审计。

---

## 8. Phase 4：Policy、Permission 与 Approval

### 8.1 目标

实现三阶段权限和不可变审批，确保高风险工具只有在有效审批和最新权限下才能执行。

### 8.2 三阶段权限

#### Plan-time

目的：避免模型规划明显越权动作。

要求：

- 过滤用户无权使用的 tool。
- 记录 permission_snapshot_json。
- 不把 plan-time 权限当执行凭证。

#### Approval-time

目的：确认审批人当前有权批准。

要求：

- approve/reject 前检查审批人权限。
- 审批人权限不足返回 403。
- 审批动作写审计事件。

#### Execute-time

目的：Worker 真正执行前用最新权限判断。

要求：

- ToolExecutor 执行前必须调用 execute_time_check。
- 项目成员、环境、资源范围、审批状态变化都必须重新判断。
- 权限撤销后返回 permission_revoked_before_execution。

### 8.3 数据库任务

#### ai_agent_approval_lineages

关键字段：

```text
approval_lineage_id
run_id
resource_scope_hash
current_epoch
status
created_at
updated_at
```

#### ai_agent_approvals

关键字段：

```text
run_id
tool_call_id
approval_lineage_id
approval_epoch
approver_id
approval_status
approval_scope_hash
input_hash
runtime_snapshot_id
resource_scope_hash
superseded_by_tool_call_id
reason
expires_at
approved_at
revoked_at
created_at
updated_at
```

#### ai_agent_approval_mutation_logs

用途：记录 approve/reject/expire/supersede/replacement 的业务级互斥变更。

### 8.4 ApprovalMutationGuard 锁协议

单次 approve/reject/supersede/replacement 必须遵守：

```text
1. 锁 approval_lineage FOR UPDATE
2. 校验 approval_epoch
3. 锁旧 tool_call
4. 锁旧 approval
5. 执行业务变更
6. 更新 approval_epoch
7. 写 mutation log
8. 写 EventStore / Outbox
```

Required Approval concurrency contract:

```text
final_statuses=approved,rejected,expired,superseded
approvable_tool_call_statuses=planned,pending_approval
supersede_blocked_tool_call_statuses=leased,running_pre_effect,effect_sent,uncertain,reconciling,succeeded
immutable_fields=input_hash,runtime_snapshot_id,resource_scope_hash,approval_lineage_id,approval_epoch
mutation_types=create,approve,reject,supersede,create_replacement,expire
event_types=approval.created,approval.approved,approval.rejected,approval.superseded,approval.expired,approval.approve_conflict,approval.reject_conflict
conflict_error_codes=approval_stale_or_superseded,approval_epoch_conflict,approval_input_changed,tool_call_not_approvable,cannot_supersede_executing_call
approve_reject_schema_required_fields=input_hash,runtime_snapshot_id,resource_scope_hash,approval_lineage_id,approval_epoch
reason_required=false
replacement_atomic=true
expire_process_one_lineage_per_mutation=true
```

Approval 并发规范必须和 `ApprovalMutationGuard` 保持一致：approve/reject 只能操作当前 lineage epoch 的 pending approval；replacement 必须在同一事务中把旧 approval 标记为 `superseded`、旧 ToolCall 标记为 `obsolete`、创建 replacement ToolCall 与新 pending approval，并递增 `approval_epoch`；过期扫描必须逐 lineage 短事务处理，不能批量长事务锁多个 lineage。

### 8.5 批量后台任务锁策略

过期扫描、批量 supersede、后台清理不得长事务锁多个 lineage。

必须遵守：

```text
1. 每次只处理一个 lineage。
2. 固定排序。
3. 使用 SKIP LOCKED 或 NOWAIT。
4. 单 lineage 短事务。
5. 失败退避。
6. 不在一个事务中遍历整个 run 的所有 lineage。
7. 所有后台任务必须幂等。
```

当前后端落地：

- `ApprovalExpireScanner.audit(project_id)` 只读扫描 pending 且已到期的 approval，按 lineage 聚合 due backlog、最老滞后、候选 lineage 数和同 lineage 多 pending 热点。
- `ApprovalExpireScanner.expire_due_summary(project_id, limit)` 在处理前后各做一次审计，按唯一 `approval_lineage_id` 逐条复用 `ApprovalMutationGuard.expire_approval`，返回 attempted/expired/skipped、skipped_duplicate_lineage_count、processed_lineage_ids、due_before/due_after 和 hotspot 变化。
- Dashboard 指标暴露 `approval_expire_due_total`、`approval_expire_batch_lag_ms`、`approval_lineage_hotspot_total`，Alert 暴露 `agent_approval_expire_backlog`、`agent_approval_expire_batch_lag` 与 `agent_approval_lineage_hotspot`。

### 8.6 Approval API

```text
POST /api/v1/agents/tool-calls/{tool_call_id}/approve
POST /api/v1/agents/tool-calls/{tool_call_id}/reject
GET  /api/v1/agents/tool-calls/{tool_call_id}
GET  /api/v1/agents/runs/{run_id}/approvals
GET  /api/v1/agents/approvals/expire-audit
POST /api/v1/agents/approvals/expire
```

Approval expire 治理接口必须区分全局批处理与项目批处理：`GET /api/v1/agents/approvals/expire-audit` 和 `POST /api/v1/agents/approvals/expire` 不带 `project_id` 时仅 admin 可读取或执行全局扫描；带 `project_id` 时必须校验项目访问权限，并只审计或处理该项目 approval lineage。

Required Approval expire payload contract:

```text
audit_fields=project_id,generated_at,due_count,candidate_lineage_count,oldest_due_lag_ms,lineage_hotspot_count,hotspot_lineage_ids,batch_safe,derived_from
process_fields=project_id,generated_at,limit,attempted,expired,skipped,skipped_duplicate_lineage_count,processed_lineage_ids,lineage_lock_wait_ms,lineage_lock_skip_total,due_before,due_after,oldest_due_lag_ms_before,oldest_due_lag_ms_after,lineage_hotspot_count_before,lineage_hotspot_count_after,batch_safe,derived_from
derived_from_fields=approval_table,mutation_log_table,candidate_order,processing_model,scope
source=ApprovalExpireScanner
```

approve/reject 请求体必须在 OpenAPI 中引用同一个 `AgentApprovalDecisionRequest`，且 required 字段固定包含 `input_hash`、`runtime_snapshot_id`、`resource_scope_hash`、`approval_lineage_id`、`approval_epoch`；`reason` 只作为可选审计说明。

approve/reject 必须校验：

```text
approval_status == pending
approval_epoch == expected_epoch
input_hash == expected_input_hash
runtime_snapshot_id == expected_runtime_snapshot_id
resource_scope_hash == expected_resource_scope_hash
expires_at > now
approver 当前有权限
old tool_call 未 obsolete / superseded / running
```

### 8.7 前端任务

- Approval 列表。
- Tool input 摘要展示。
- 风险理由展示。
- 权限范围展示。
- approve/reject 按钮。
- superseded 后禁用旧按钮。
- 409 approval_stale_or_superseded 自动刷新。
- SSE 实时更新 approval.created / approved / rejected / superseded / expired。

### 8.8 测试任务

- approve 与 supersede 并发。
- replacement tool_call 创建与旧 approval supersede 同事务。
- 旧 approval approve 返回 409。
- 审批人权限被撤销后 approve 返回 403。
- approve 后执行前权限被撤销，execute-time 阻断。
- 批量 expire 与 approve 并发无死锁。
- SKIP LOCKED 后扫描可重试。
- expire audit 能发现 due backlog 和同 lineage 多 pending 热点。
- expire process 幂等，重复扫描不会重复写 expired。

### 8.9 验收标准

- 审批 input 不可变。
- 新旧 approval 不会同时 pending。
- 旧 approval 不会被错误批准。
- 高风险工具没有有效 approval 不会执行。
- 所有审批动作可审计。
- 批量后台任务不会成为 lineage 锁热点。
- Approval expire backlog 与 lineage hotspot 可通过 dashboard/alerts 观测并进入 P2 门禁。

---

## 9. Phase 5：EvidenceRef、ToolPolicy、Context 与 Loop

### 9.1 目标

实现动态 replay policy、证据生命周期、上下文压缩可观测、Loop 多原因停止、RootCause 显式规则。

### 9.2 EvidenceRefResolver

#### 9.2.1 EvidenceRef 结构

```json
{
  "ref_type": "execution_record | scenario | report | environment | testcase | memory | external_doc",
  "ref_id": "string",
  "version_id": "string|null",
  "content_hash": "string|null",
  "snapshot_id": "string|null",
  "captured_at": "datetime",
  "mutability_class": "immutable | versioned | mutable_current | ephemeral_latest | external_uncontrolled",
  "dependency_role": "decision_dependency | validation_evidence | policy_dependency | audit_background | trace_only | superseded",
  "active_for_policy": true,
  "superseded_by_ref": null,
  "freshness_policy": "none | revalidate_on_resume | revalidate_before_side_effect"
}
```

Required EvidenceRef authoring contract:

```text
mutability_classes=immutable,versioned,mutable_current,ephemeral_latest,external_uncontrolled
frozen_mutability_classes=immutable,versioned
volatile_mutability_classes=mutable_current,ephemeral_latest,external_uncontrolled
active_policy_dependency_roles=decision_dependency,validation_evidence,policy_dependency
audit_dependency_roles=audit_background,trace_only,superseded
dependency_roles=decision_dependency,validation_evidence,policy_dependency,audit_background,trace_only,superseded
freshness_policies=none,revalidate_on_resume,revalidate_before_side_effect
default_mutability_class=mutable_current
default_dependency_role=audit_background
policy_filter=active_for_policy=true;dependency_role=in_active_policy_dependency_roles;superseded_by_ref=null
```

EvidenceRef 编写规范必须和 `EvidenceRefResolver` 保持一致：缺省 ref 只能作为 audit background，不能自动进入策略；参与 replay_policy 的证据必须 `active_for_policy=true`、`dependency_role` 属于 `decision_dependency / validation_evidence / policy_dependency`，且没有 `superseded_by_ref`；`audit_background / trace_only / superseded` 只能进入审计与诊断，不得污染 replay policy。

#### 9.2.2 策略证据筛选

只有以下证据参与 replay_policy：

```text
active_for_policy=true
AND dependency_role IN (decision_dependency, validation_evidence, policy_dependency)
AND superseded_by_ref IS NULL
```

历史证据可以保留作审计，但不能污染当前 replay policy。

#### 9.2.3 外部变化监听

实现：

```text
ai_agent_evidence_watches
```

监听事件：

```text
scenario.updated
testcase.updated
environment.updated
execution_record.created
report.regenerated
permission.changed
memory.status_changed
```

策略：

- 未接入主动监听时，ephemeral_latest 默认 require_revalidation。
- 已接入监听时，可将 latest ref materialize 为 immutable execution_record + output_hash。

### 9.3 ToolPolicyResolver

规则：

```text
1. execute_candidates=true => external_effect / never_replay / approval_required
2. self_validate=true => execution_record / reuse_result 或 require_revalidation
3. active policy evidence 中只要存在 volatile => require_revalidation
4. active policy evidence 全部 frozen/hash/version/snapshot => reuse_result
5. volatile 优先级高于 frozen
6. audit_context 不影响 replay_policy
```

### 9.4 ContextBuilder / ContextBudget

实现表：

```text
ai_agent_context_builds
```

关键字段：

```text
run_id
iteration
step_index
model_name
token_budget
estimated_input_tokens
context_degradation_level
compressed_sections_json
omitted_evidence_refs_json
required_evidence_complete
decision_quality_risk
prompt_object_key
prompt_hash
created_at
```

要求：

- Context 分 Tier A/B/C/D。
- 不静默丢弃证据。
- 每次模型决策绑定 decision_context_build_id。
- required_evidence_complete=false 时禁止 business_create/business_update/destructive/external_effect。
- 支持 fetch_full_evidence_and_rebuild_context。

### 9.5 LoopController

实现表：

```text
ai_agent_loop_observations
```

关键字段：

```text
run_id
iteration
decision_context_build_id
validation_status
failure_signature
failure_fingerprint
patch_fingerprint
changed_paths_json
improved
stop_action_reason
root_cause_primary
root_cause_rule_id
causal_chain_json
mitigation_action
stop_reasons_all_json
diagnostic_summary
created_at
```

Loop 决策：

```text
passed => Stop(completed)
requires_approval => Pause(pending_approval)
migration_block => Pause(migration_blocked)
safety_violation => Stop/Pause(needs_human)
regression => Stop/Pause(needs_human)
no_progress => Stop/Pause(repair_failed)
evidence_risk => fetch_full_evidence 或人工
resource_limit => Stop(resource_limit)
max_iterations => Stop(max_iterations)
otherwise => Continue(repair)
```

### 9.6 RootCauseRuleEngine

实现表：

```text
ai_agent_root_cause_rules
```

字段：

```text
rule_id
priority
priority_band
condition_json
root_cause_primary
mitigation_action
test_fixture_object_key
status
owner
created_at
updated_at
```

Priority Band：

| Band | 范围 |
|---|---:|
| Safety / Policy | 1-19 |
| Evidence / Context | 20-39 |
| Backend / Recovery | 40-59 |
| Repair Quality | 60-79 |
| Resource / Limit | 80-89 |
| Fallback | 900-999 |

Required RootCause rule authoring contract:

```text
priority_bands=safety:1-19,evidence_context:20-39,recovery:40-59,repair_quality:60-79,resource_limit:80-89,fallback:900-999
default_rules=RC_CONTEXT_OMITTED_HIGH_RISK:safety:10,RC_PERMISSION_REVOKED:safety:15,RC_POLICY_LOOP:safety:18,RC_EVIDENCE_INCOMPLETE:evidence_context:20,RC_MEMORY_CONTRADICTION:evidence_context:30,RC_APPROVAL_PENDING:recovery:40,RC_BACKEND_CAPABILITY_DEGRADED:recovery:45,RC_TOOL_PREREQUISITE_MISSING:recovery:50,RC_TOOL_REQUEST_FORMAT_INVALID:recovery:52,RC_REQUIRED_TOOL_FOLLOWUP_MISSING:recovery:54,RC_NO_PROGRESS_PURE:repair_quality:60,RC_REPAIR_REGRESSION:repair_quality:65,RC_MAX_ITERATIONS:resource_limit:80,RC_RESOURCE_LIMIT:resource_limit:85,RC_UNKNOWN:fallback:900,RC_RULE_MISSING:fallback:999
governance_fields=priority_bands,violations,violation_count,governance_pass
new_rule_required_fixtures=3
fallback_rule_id=RC_RULE_MISSING
accepted_unknown_rule_id=RC_UNKNOWN
missing_rule_metric=root_cause_rule_missing_total
```

RootCause Rule 新增规范必须和 `RootCauseRuleEngine.audit_rule_governance()` 保持一致：新增 rule 先选 priority band，再写 rule_id、reason_key、match expression、root_cause_primary、causal_chain、mitigation_action 和至少 3 个测试夹具；无法分类但已接受的原因必须显式命中 `RC_UNKNOWN`，未登记的新 reason 必须落到 `RC_RULE_MISSING` 并触发 `root_cause_rule_missing_total`，不能通过新增黑盒推断函数绕过规则表。

后端 `RootCauseRuleEngine.audit_rule_governance()` 必须审计所有规则的 `priority` 是否落入 `priority_band` 固定范围，并通过 `GET /api/v1/agents/root-cause-rules/audit` 暴露只读治理审计结果；默认规则要求 `RC_PERMISSION_REVOKED` 位于 Safety / Policy band（priority=15），`RC_POLICY_LOOP` 位于 Safety / Policy band（priority=18），`RC_EVIDENCE_INCOMPLETE` 位于 Evidence / Context band（priority=20），`RC_MEMORY_CONTRADICTION` 位于 Evidence / Context band（priority=30），`RC_BACKEND_CAPABILITY_DEGRADED` 位于 Backend / Recovery band（priority=45），`RC_TOOL_PREREQUISITE_MISSING` 位于 Backend / Recovery band（priority=50），`RC_TOOL_REQUEST_FORMAT_INVALID` 位于 Backend / Recovery band（priority=52），`RC_REQUIRED_TOOL_FOLLOWUP_MISSING` 位于 Backend / Recovery band（priority=54），`RC_NO_PROGRESS_PURE` 位于 Repair Quality band（priority=60），`RC_REPAIR_REGRESSION` 位于 Repair Quality band（priority=65），`RC_MAX_ITERATIONS` 位于 Resource / Limit band（priority=80），`RC_RESOURCE_LIMIT` 位于 Resource / Limit band（priority=85），`RC_UNKNOWN` 位于 Fallback band（priority=900），`RC_RULE_MISSING` 位于 Fallback band（priority=999），避免规则表数字优先级重新变成不可审计约定。

初始规则：

```text
RC_CONTEXT_OMITTED_HIGH_RISK
RC_EVIDENCE_INCOMPLETE
RC_MEMORY_CONTRADICTION
RC_POLICY_LOOP
RC_BACKEND_CAPABILITY_DEGRADED
RC_TOOL_PREREQUISITE_MISSING
RC_TOOL_REQUEST_FORMAT_INVALID
RC_REQUIRED_TOOL_FOLLOWUP_MISSING
RC_REPAIR_REGRESSION
RC_NO_PROGRESS_PURE
RC_RESOURCE_LIMIT
RC_MAX_ITERATIONS
RC_UNKNOWN
RC_RULE_MISSING
```

### 9.7 测试任务

- 历史 volatile evidence 被 superseded 后不影响 replay。
- active evidence 同时有 volatile 和 frozen => require_revalidation。
- audit_context 不影响 replay_policy。
- required_evidence_complete=false 时高风险工具阻断。
- 一个 iteration 多次 context build 时 observation 绑定正确 build。
- context heavy + no_progress => root cause 指向 context。
- memory contradiction => root cause 指向 memory。
- 新增 reason 未配置 rule => root_cause_rule_missing_total。

### 9.8 验收标准

- resolved_replay_policy 可解释、可审计。
- Context 压缩影响可观测。
- Loop 停止原因不丢失。
- RootCause 不是黑盒函数。
- 高风险动作必须有完整证据。

---

## 10. Phase 6：Migration、Checkpoint Freshness、Memory 与生产硬化

### 10.1 MigrationCoordinator

实现表：

```text
ai_agent_migration_blocks
```

字段：

```text
block_id
run_id
tool_call_id
block_type
status
reason
created_at
resolved_at
resolved_by
```

规则：

- ToolCall needs_migration 时，Run 进入 migration_blocked。
- 一个 Run 可以有多个 open migration block。
- 所有 blocking block resolved 后，Run 才能恢复。
- resolve 后不得直接续跑旧 checkpoint，必须进入 Checkpoint Freshness Gate。

### 10.2 Checkpoint Freshness Gate

resume 前检查：

```text
checkpoint_age
runtime_snapshot compatibility
backend_contract compatibility
active evidence freshness
environment freshness
permission freshness
pending approval freshness
memory freshness
```

处理策略：

| 检查结果 | 处理 |
|---|---|
| fresh | 从 checkpoint 续跑 |
| evidence_stale | fetch evidence + rebuild context |
| approval_stale | supersede approval |
| permission_stale | refresh permissions or manual review |
| backend_contract_changed | migration block |
| environment_changed | revalidate before side effect |
| too_old | replan from latest safe state |

Memory freshness 检查必须读取最新 ContextBuild 的 active policy memory EvidenceRef；当对应 `ProjectMemory.status=needs_revalidation` 或 `stale_score>=0.8` 时，Freshness Gate 返回 `result=evidence_stale`、`reason=active_memory_needs_revalidation`，并输出 `active_memory_needs_revalidation_ids`，禁止 resume 直接从旧 checkpoint 继续。

Runtime snapshot compatibility 检查必须确认 checkpoint 绑定的 `runtime_snapshot_id` 仍存在，且与 run 当前 `runtime_snapshot_id` 一致；当 snapshot 缺失或不一致时，Freshness Gate 返回 `result=too_old`、`action=replan_from_latest_safe_state`、`reason=runtime_snapshot_missing/runtime_snapshot_mismatch`，禁止使用旧 runtime registry 解释新的 resume。
当 Freshness Gate 要求 `replan_from_latest_safe_state` 时，Run 暂停态必须暴露冻结错误码 `checkpoint_stale_replan_required`，并在 `run.paused` 事件 payload 中同步输出，避免 UI 只能解析内部 action 字符串。

Required runtime snapshot freshness contract:

```text
freshness_fields=checkpoint_runtime_snapshot_id,run_runtime_snapshot_id,runtime_snapshot_compatible
result=too_old
action=replan_from_latest_safe_state
reasons=runtime_snapshot_missing,runtime_snapshot_mismatch
paused_error_code=checkpoint_stale_replan_required
```

Permission freshness 检查必须在 resume 前重验当前操作者对恢复后可能继续调度/执行的 ToolCall 所需权限；当 `planned/approved/executable/failed_retryable/uncertain/reconciling` ToolCall 的 `required_permissions_json` 中任一权限已撤销时，Freshness Gate 返回 `result=permission_stale`、`action=refresh_permissions_or_manual_review`、`reason=required_permission_revoked`，并输出 `revoked_required_permissions`，禁止先 resume 再等 execute-time 失败。

Required permission freshness contract:

```text
tool_statuses=approved,executable,failed_retryable,planned,reconciling,uncertain
freshness_fields=revoked_required_permission_count,revoked_required_permissions
detail_fields=tool_call_id,tool_name,permission,status
result=permission_stale
action=refresh_permissions_or_manual_review
reason=required_permission_revoked
```

Pending approval freshness 检查必须输出可审计明细，而不是只给 pending 数量。Freshness Gate 对 pending approval 输出 `pending_approval_details`、`expired_pending_approval_count` 与 `stale_pending_approval_count`；当任一 pending approval 已过期时返回 `reason=pending_approval_expired`，当 input/runtime/resource_scope/lineage/epoch 与当前 ToolCall 不一致时返回 `reason=pending_approval_stale`，否则保留 `reason=pending_approval_after_wait`，方便 UI/runbook 选择 expire、supersede 或继续等待。

Required pending approval freshness contract:

```text
freshness_fields=pending_approval_count,expired_pending_approval_count,stale_pending_approval_count,pending_approval_details
detail_fields=approval_id,tool_call_id,approval_lineage_id,approval_epoch,expires_at,stale_reasons
reasons=pending_approval_expired,pending_approval_stale,pending_approval_after_wait
stale_reasons=expired,tool_call_missing,immutable_mismatch,pending_after_wait
result=approval_stale
action=supersede_or_refresh_approval
```

Environment freshness 检查必须从 stale EvidenceWatch 中区分环境类证据；当 `ref_type=environment` 或 `stale_reason=environment.updated` 时，Freshness Gate 返回 `result=environment_changed`、`action=revalidate_before_side_effect`、`reason=environment_updated`，并输出 `environment_changed_count` 与 `stale_evidence_watch_details`。普通 scenario/report 等 stale evidence 继续返回 `evidence_stale / fetch_evidence_and_rebuild_context`。

Active evidence freshness 检查必须主动识别最新 ContextBuild 的 policy refs；当 active policy refs 中仍存在 `ref_type=latest_execution_sample` 或 `mutability_class=ephemeral_latest` 时，即使 EvidenceWatch 尚未 stale，也必须返回 `result=evidence_stale`、`action=materialize_latest_evidence`、`reason=ephemeral_latest_requires_materialization`，并输出 `active_evidence_revalidation_details`，禁止旧 checkpoint 直接复用未冻结的 latest 证据。当 active policy refs 包含 `freshness_policy=revalidate_on_resume`、`mutability_class=external_uncontrolled` 或 `ref_type=external_doc` 的外部不可控证据时，Freshness Gate 必须返回 `result=evidence_stale`、`action=fetch_evidence_and_rebuild_context`、`reason=active_evidence_requires_revalidation`，要求 resume 前重新获取证据并重建上下文。

Required evidence freshness contract:

```text
environment_fields=environment_changed_count,stale_evidence_watch_details
environment_detail_fields=evidence_ref_id,ref_type,ref_id,stale_reason
environment_result=environment_changed
environment_action=revalidate_before_side_effect
environment_reason=environment_updated
active_evidence_fields=active_evidence_revalidation_count,active_evidence_revalidation_details
active_evidence_detail_fields=evidence_ref_id,ref_type,ref_id,mutability_class,freshness_policy
active_evidence_result=evidence_stale
active_evidence_actions=materialize_latest_evidence,fetch_evidence_and_rebuild_context
active_evidence_reasons=ephemeral_latest_requires_materialization,active_evidence_requires_revalidation
```

### 10.3 MemoryManager

MemoryManager 不能按旧版占位设计直接实现。必须先完成 Memory 与 EvidenceRef、EvidenceWatch、RootCause 的集成，避免 Memory 成为主链路外的旁路证据。

#### 10.3.1 数据库表

必须实现：

```text
ai_project_memories
ai_agent_memory_source_profiles
ai_agent_memory_retrieval_profiles
ai_agent_memory_usage_events
ai_agent_memory_contradiction_events
ai_agent_memory_staleness_events
ai_agent_memory_evidence_links
```

#### 10.3.2 Source Profile

开发任务：

- 实现 `MemorySourceProfileResolver`。
- 为 `user_confirmed / execution_learned / document_imported / agent_summarized / repair_inferred / external_imported` 定义不同初始 confidence。
- source_type 未配置 profile 时，禁止创建 active memory。
- `agent_summarized` 与 `repair_inferred` 默认不得进入高风险动作 policy dependency。
- high-risk Memory 检索必须同时执行 source profile allowlist；`external_imported` 即使被人工抬高 confidence 且置为 active，也不得进入高风险 policy dependency。

验收：

- 用户确认 memory 初始 confidence 高于 agent_summarized。
- 所有 memory 创建事件都记录 initial_confidence 和 confidence_reason_json。
- 未知 source_type 创建失败或进入 needs_review。
- source profile 的 `allowed_for_high_risk` 必须由架构表文档驱动测试固化，并由 Memory hard gate 实际执行。
- source profile 的 `requires_content_hash` 必须由默认 profiles 显式配置；`document_imported=true`，其余内置 source_type 为 `false`，运行时 source_ref hash 校验必须读取 profile。

#### 10.3.3 Retrieval Profile

开发任务：

- 实现 `MemoryRetrievalProfile`。
- 将检索权重从代码常量迁移到 `ai_agent_memory_retrieval_profiles`。
- 实现 hard gate：status、expires_at、min_confidence、max_stale_score、risk_level。
- 默认 profile 至少包括：`normal_plan_v1 / repair_v1 / high_risk_action_v1 / audit_explain_v1`。

验收：

- semantic_score 不能绕过 min_confidence。
- high_risk_action_v1 不允许低 confidence 或高 stale memory 进入 active policy refs。
- profile 缺失时触发 `memory_retrieval_profile_missing_total`；带 run 上下文的 Memory 检索会写入 `memory.retrieval_profile_missing` 事件，dashboard/metrics 按该事件计数。
- 低于 retrieval profile `min_confidence` 的 memory 被 hard gate 过滤时，带 run 上下文的 Memory 检索会写入 `memory.low_confidence_filtered` 事件，并计入 `memory_low_confidence_filtered_total`。

#### 10.3.4 contradiction_penalty

开发任务：

- 实现 `ai_agent_memory_contradiction_events`。
- 实现确定性 `compute_contradiction_penalty`。
- 支持 severity multiplier：low / medium / high / critical。
- 支持 recent_contradiction_count、same_failure_fingerprint、validation_offset。
- 实现 `MemoryMaintenanceWorker.process_expired_ttl`，处理超过 TTL 且尚未被执行样本验证的 memory。

验收：

- contradiction_penalty 有单元测试和边界测试。
- memory 被 Plan/Repair 使用后若被 execution evidence 证明错误，必须固定执行 `contradiction_count +1; confidence -0.15; stale_score +0.25`，不能按 severity 改写该基础降权幅度。
- critical contradiction 会让 memory 进入 needs_revalidation 或 rejected。
- 同一 memory 连续导致相同 failure fingerprint 时必须进入 `suspect`，并累计 `recent_contradiction_count`。
- 用户明确否定的 memory 必须 `status=rejected` 且 `confidence=min(confidence,0.10)`，并不再被检索。
- 用户或系统确认正确时必须写入 `ai_agent_memory_validation_events`，记录 validation_source、confidence/stale/status 前后值、validation_count 和关联 evidence/usage 信息。
- 带 run 上下文的 Memory 检索在 contradiction penalty 大于 0 时写入 `memory.contradiction_penalty_applied` 事件，并计入 `memory_contradiction_penalty_applied_total`。
- 超过 TTL 且 `validation_count=0` 的 memory 必须 `stale_score +0.10`；超过阈值后进入 `needs_revalidation`，已验证 memory 不因 TTL 维护任务降权。

#### 10.3.5 Memory 与 EvidenceRef 集成

开发任务：

- 实现 `MemoryEvidenceAdapter.to_evidence_ref`。
- Memory 检索结果必须转换为 `ref_type=memory`。
- usage_role 映射到 `dependency_role`：trace_only / planning_hint / repair_hint / policy_dependency。
- 只有 `policy_dependency` 可设置 `active_for_policy=true`。
- ToolPolicyResolver 对 active memory evidence 视为 `mutable_current`。
- 后端契约测试必须从本节抽取 Memory usage_role 列表和 active role，并验证 `MemoryEvidenceAdapter.to_evidence_ref` 输出的 `ref_type/ref_id/version_id/content_hash/mutability_class/freshness_policy/dependency_role/active_for_policy/required_for_high_risk/authority` 与文档一致。
- LoopObservation 必须从 decision ContextBuild 的 memory policy refs 自动派生 `memory_usage` 与 `memory_contradiction_delta`。

验收：

- Memory 不能绕过 EvidenceRef 直接进入 prompt。
- 只作为背景提示的 memory 不影响 replay_policy。
- 直接影响 tool input 的 memory 必须出现在 evidence_refs_json。
- 高风险动作不能只依赖 memory，也不能靠任意非 memory 引用绕过；active policy refs 中必须至少有一个 `system_record`、`project_config`、`execution_record` 或 `document_imported` 的冻结或可重验证据支撑。
- `RC_MEMORY_CONTRADICTION` 不能依赖调用方手工传入 `memory_contradiction_delta`；当 decision context 的 active memory policy refs 已有 contradiction event 时，应优先于普通 no-progress 规则命中。

#### 10.3.6 Memory 与 EvidenceWatch 联动

开发任务：

- 实现 `ai_agent_memory_evidence_links`。
- 实现 `ai_agent_memory_staleness_events`，记录 EvidenceWatch 触发后的 stale_score/status 前后值。
- MemoryManager 通过现有 `ai_agent_evidence_watches` 注册关联 scenario/testcase/environment/report/manifest/document。
- `scenario.updated / testcase.updated / environment.updated / manifest.changed / document.updated / report.updated / report.deleted / report.regenerated` 触发 MemoryStalenessWorker，分别按架构外部事件表更新 `stale_score +0.20/+0.20/+0.30/+0.25/+0.25/+0.20/+0.20/+0.20`。
- stale event 更新 memory.stale_score 或 status=needs_revalidation，其中 `manifest.changed` 与 `environment.updated` 必须进入 `needs_revalidation`。
- `execution_record.created` 不进入 stale 分支；它必须通过 `MemoryFeedbackWorker.process_execution_record_created` 复用 EvidenceLink，将 execution evidence 对关联 memory 的支持记录为 validation，将反驳记录为 contradiction event。
- `permission.changed` 与 `memory.status_changed` 不是 Memory stale event；MemoryStalenessWorker 必须以 `422 memory_event_not_stale_event` 拒绝这类非 stale 平台事件，分别交由 execute-time permission check 和 Memory 状态审计/检索事实处理，避免错误递归污染 stale_score。
- `POST /api/v1/agents/memory-feedback/process` 属于 admin-only 全局后台处理入口，用于消费 pending/retry memory usage feedback；普通项目用户不得手动触发全局反馈批处理。

Required Memory retrieval payload contract:

```text
candidate_fields=memory_id,memory_version,title,content,source_type,confidence,stale_score,retrieval_score,retrieval_profile,evidence_ref,allowed_usage
evidence_ref_fields=evidence_ref_id,ref_type,ref_id,mutability_class,dependency_role,active_for_policy,version_id,content_hash,captured_at,freshness_policy,required_for_high_risk,authority
source=MemoryManager.retrieve
```

Required Memory feedback process payload contract:

```text
fields=attempted,processed,skipped,contradictions_recorded,validations_recorded,results
result_base_fields=usage_event_id,processed,decision
source=MemoryFeedbackWorker.process_due
```

验收：

- 不重复实现一套 Memory 专用外部事件监听。
- EvidenceWatch stale event 能级联到关联 memory。
- MemoryStalenessWorker 的 stale_score delta/status 必须由架构 15.6 外部事件处理表的文档驱动测试固化。
- execution_record.created 必须生成 validation/contradiction 结果；若误路由到 MemoryStalenessWorker，必须以 `422 memory_event_not_stale_event` 拒绝，不能被误记为普通 stale event。
- permission.changed / memory.status_changed 必须被 MemoryStalenessWorker 以 `422 memory_event_not_stale_event` 拒绝，不能被误记为普通 stale event。
- 支持性 execution evidence 验证 memory 时必须按架构 15.8 执行 `validation_count +1; confidence +0.05; stale_score -0.10`，并由文档驱动测试固化。
- environment.updated 关联 memory 在 high-risk profile 中被过滤；即使 stale_score 等于 profile 阈值，也必须通过 `stale_reason=environment.updated` 进入 hard gate，避免环境变化后的 Memory 继续驱动高风险动作。

#### 10.3.7 Memory 写入边界

MVP 只允许：

```text
user_confirmed
document_imported
```

P1 才允许：

```text
execution_learned
agent_summarized 默认 needs_review
```

P2 才允许：

```text
repair_inferred 自动候选，但必须后续执行验证
```

验收：

- Agent 不得在 MVP 阶段无确认写入长期 active memory。
- 自动生成 memory 默认不能直接驱动高风险动作。
- `execution_learned` 创建或更新 evidence refs 时必须至少包含 2 个不同 `execution_record` EvidenceRef，否则返回 `execution_learned_requires_two_execution_evidence`。
- `document_imported` 创建或更新 source_ref 时必须携带文档内容 hash（`content_hash` / `document_hash` / `source_hash`），否则返回 `document_imported_source_hash_required`。
- `execution_learned` 创建后默认 `needs_review`，经明确验证后才可 active；`external_imported / agent_summarized / repair_inferred` 默认不得成为高风险动作 policy dependency。
- `repair_inferred` 不得通过普通 validate API 直接 active，必须经 `execution_record.created` 支持性验证后才允许进入 active。

### 10.4 故障注入

必须覆盖：

```text
Worker 在 send_intent_recorded 后崩溃
Worker 在 transport_sent_observed 后崩溃
Worker 在 backend_accepted 后崩溃
Tool succeeded 但 EventStore 写失败
EventStore 成功但 Outbox 发布失败
Reconcile 返回 not_found
Reconcile 返回 conflict
Reconcile 返回 unsupported_schema_version
approve 与 supersede 并发
过期扫描与 approve 并发
migration block resolve 后 checkpoint stale
context heavy 导致 evidence incomplete
memory contradiction
memory bypasses EvidenceRef should fail validation
high-risk action depends only on memory should be blocked
memory stale triggered by EvidenceWatch external event
duplicate idempotency_key
permission revoked before execution
```

当前后端故障注入服务 `AgentFaultInjectionService` 已可枚举并执行以下 26 个生产硬化用例：

```text
send_intent_not_found
transport_sent_not_found
backend_accepted_not_found
effect_committed_reconcile_reuse
tool_succeeded_eventstore_write_failed
outbox_publish_failure
reconcile_conflict
unsupported_schema_version
migration_block_resolve_checkpoint_continue
legacy_no_receipt_high_risk
approval_epoch_conflict
approval_supersede_replacement_atomic
approval_expired_before_approve
checkpoint_stale
context_heavy_evidence_incomplete
loop_observation_decision_context_binding
evidence_historical_volatile_excluded
evidence_mixed_volatile_frozen_requires_revalidation
memory_contradiction
memory_stale_evidence_watch
memory_bypassed_evidence_ref
duplicate_idempotency_key
permission_revoked_before_execution
worker_queue_reconcile_required
root_cause_rule_missing
high_risk_memory_only_blocked
```

其中 `backend_accepted_not_found` 明确转人工 incident，`effect_committed_reconcile_reuse` 验证已提交结果只复用不重放，`tool_succeeded_eventstore_write_failed` 验证工具后端成功但完成事件写入失败时转入 uncertain 并要求 reconcile，`outbox_publish_failure` 验证 EventStore 与 Outbox 发布失败解耦，`reconcile_conflict` 验证冲突转人工，`migration_block_resolve_checkpoint_continue` 验证 migration block resolve 后必须先过 Freshness Gate、Run 从 checkpoint 继续且已成功 ToolCall 不回滚，`approval_supersede_replacement_atomic` 验证 replacement tool_call 与旧 approval supersede 同事务完成，`approval_expired_before_approve` 验证过期审批阻断执行，`context_heavy_evidence_incomplete` 验证高风险动作缺证据时停机归因，`loop_observation_decision_context_binding` 验证同一 iteration 多个 ContextBuild 存在时 LoopObservation 必须绑定明确的 decision ContextBuild，`evidence_historical_volatile_excluded` 验证历史 volatile latest evidence 不污染 replay policy，`evidence_mixed_volatile_frozen_requires_revalidation` 验证 active volatile 与 frozen 混合时强制 require_revalidation，`memory_contradiction` 与 `memory_stale_evidence_watch` 验证 Memory 降权链路，`memory_bypassed_evidence_ref` 验证 Memory 未通过 EvidenceRef 包装时被 ContextBuilder 拒绝并计入 P0 事件，`duplicate_idempotency_key` 验证幂等拦截，`permission_revoked_before_execution` 验证 execute-time 权限撤销会在后端执行前阻断并进入监控指标，`worker_queue_reconcile_required` 验证 `uncertain/reconciling` ToolCall 误入 WorkerQueue 时必须被阻断并要求先 reconcile，`root_cause_rule_missing` 验证未知 reason 进入显式规则治理，`high_risk_memory_only_blocked` 验证高风险动作不能只依赖 Memory EvidenceRef。

故障注入清单与覆盖率审计接口 `GET /api/v1/agents/fault-injections`、`GET /api/v1/agents/fault-injections/coverage` 属于 admin-only 全局生产硬化目录/审计接口；`POST /api/v1/agents/fault-injections/run` 属于 admin-only 生产硬化执行入口，必须指定 `project_id` 且普通项目用户不得触发故障注入执行。coverage 以 26 个生产硬化用例作为 required set，返回 registered/required/missing/extra、coverage_ratio 与 coverage_pass；dashboard 与 metrics 使用同一审计结果，避免只校验 P0/P1 子集而遗漏 P2 生产硬化用例。

Required fault injection payload contract:

```text
case_fields=case_id,description,expected
coverage_fields=generated_at,registered_case_count,required_case_count,covered_required_case_ids,missing_required_case_ids,extra_case_ids,coverage_ratio,coverage_pass,derived_from
run_fields=project_id,requested,passed,failed,results
result_fields=case_id,run_id,tool_call_id,passed,observed,evidence
source=AgentFaultInjectionService_and_AgentFaultInjectionCoverageService
```

### 10.5 监控指标

P0 指标：

```text
tool_call_uncertain_total
tool_call_reconcile_success_total
tool_call_reconcile_manual_total
tool_call_orphan_recovered_total
tool_call_send_intent_orphan_total
tool_call_safe_retry_after_send_intent_not_found_total
tool_call_transport_sent_uncertain_total
tool_call_backend_accepted_uncertain_total
backend_effect_capability_receipt_first_total
backend_effect_capability_legacy_no_receipt_total
tool_call_legacy_no_receipt_manual_total
tool_call_backend_contract_unsupported_total
tool_call_duplicate_blocked_total
approval_superseded_total
approval_approve_conflict_total
approval_epoch_conflict_total
approval_replacement_atomic_total
permission_revoked_before_execution_total
backend_contract_unsupported_total
migration_block_open_total
runtime_snapshot_migration_block_total
backend_contract_migration_block_total
run_migration_blocked_total
release_gate_violation_count
outbox_publish_lag_ms
event_replay_gap_total
fault_injection_missing_required_total
```

P1 指标：

```text
context_degraded_total
context_full_evidence_required_total
context_decision_build_missing_total
loop_root_cause_context_degraded_total
loop_root_cause_unknown_total
root_cause_rule_missing_total
invalid_repair_scope_total
tool_prerequisite_missing_total
tool_request_format_invalid_total
required_tool_followup_missing_total
max_iterations_total
same_failure_no_progress_total
evidence_volatile_requires_revalidation_total
evidence_historical_volatile_excluded_total
evidence_mixed_volatile_frozen_total
memory_contradiction_total
memory_contradiction_penalty_applied_total
memory_retrieved_total
memory_used_active_policy_total
memory_low_confidence_filtered_total
memory_high_risk_blocked_total
memory_needs_revalidation_total
memory_evidence_watch_stale_total
memory_bypassed_evidence_ref_total
checkpoint_freshness_failed_total
backend_capability_degraded_total
fault_injection_required_case_total
fault_injection_registered_case_total
fault_injection_coverage_ratio
```

后端当前新增 `GET /api/v1/agents/metrics`、`GET /api/v1/agents/dashboard` 与 `GET /api/v1/agents/runbooks`，分别暴露 metrics snapshot、readiness dashboard 与 Runbook catalog。

`GET /api/v1/agents/dashboard` readiness dashboard 聚合：

```text
AgentMetricsService.snapshot
AgentReleaseGateService.snapshot
AgentFaultInjectionService.list_cases
AgentRunbookService.list_runbooks
AgentRunbookService.diagnose_run
AgentAlertService.snapshot
AgentEventReplayAuditService.audit_run
AgentEventReplayAuditService.audit_project
AgentWorkerQueueAuditService.audit
```

Dashboard 输出 `readiness=pass/attention/blocked`、P0/P1 checks、metrics、release_gate、promotion_assessment contract summary、fault_injection coverage、runbooks coverage、root_cause_governance 和 alert summary。P0 checks 包括 metrics catalog、current release gate、完整 fault injection coverage、monitoring alerts clear 与 `release_gate_promotion_assessment`；P1 checks 包括 recovery runbook catalog、RootCause priority band governance 与 live recovery attention。`root_cause_rule_governance` 复用 `RootCauseRuleEngine.audit_rule_governance()`，在 dashboard 顶层输出 `root_cause_governance`，当 `governance_pass=false` 或存在 priority band violation 时将 readiness 降为 attention。`metrics_catalog_complete.details.required_metric_keys` 必须覆盖本节 P0/P1 指标清单，包括 recovery、approval、context、root cause、memory、event replay、worker queue、fault coverage 和 backend capability degradation 指标，避免 snapshot 已计算但 dashboard 目录漏检；后端文档驱动测试必须从架构文档 `Required dashboard metrics` 代码块抽取完整 required metric keys，并与 `REQUIRED_DASHBOARD_METRICS`、dashboard details 和 `AgentMetricsService.snapshot` 输出全量对齐。Approval lineage 锁观测通过 mutation log `details_json.lineage_lock_wait_ms` 聚合为 `approval_lineage_lock_wait_ms`，批量扫描跳过锁计入 `approval_lineage_lock_skip_total`；这两个指标必须进入 dashboard required metrics catalog。Memory 检索命中并被选入结果后写入 `AgentMemoryUsageEvent`，并计入 `memory_retrieved_total`；Memory retrieval profile 缺失通过 `memory.retrieval_profile_missing` 事件计入 `memory_retrieval_profile_missing_total`；Memory 因 `min_confidence` hard gate 被过滤时通过 `memory.low_confidence_filtered` 事件计入 `memory_low_confidence_filtered_total`；Memory contradiction penalty 大于 0 并参与检索评分时通过 `memory.contradiction_penalty_applied` 事件计入 `memory_contradiction_penalty_applied_total`；EvidenceWatch 触发 Memory stale 时写入 `ai_agent_memory_staleness_events`，并计入 `memory_evidence_watch_stale_total`。Freshness Gate 因 active policy Memory `needs_revalidation` 或 `stale_score>=0.8` 阻止 resume 时同样写入 `checkpoint.freshness_checked(result=evidence_stale, reason=active_memory_needs_revalidation)`，并计入 `checkpoint_freshness_failed_total`。RootCause 聚合指标包含 `loop_root_cause_context_degraded_total` 与 `loop_root_cause_unknown_total`，分别用于观测上游根因为上下文压缩和 fallback unknown 的 LoopObservation 数量。`invalid_repair_scope_total` 用于观测 LoopObservation 中 `stop_reasons_all_json` 包含 `invalid_repair_scope` 的修复越界数量；`tool_prerequisite_missing_total`、`tool_request_format_invalid_total`、`required_tool_followup_missing_total`、`max_iterations_total` 与 `same_failure_no_progress_total` 用于观测 AgentConversationRunner 写入的运行时纠错/停止原因是否持续出现。`context_decision_build_missing_total` 用于审计 LoopObservation 引用了不存在的 decision ContextBuild，AlertService 以 `agent_context_decision_build_missing` 标记 P1，dashboard 进入 attention。`backend_capability_degraded_total` 大于 0 时，AlertService 以 `agent_backend_capability_degraded` 标记 P1，并通过 `backend_capability_degraded` runbook 指向 operation 级 contract/capability 升级或人工复核。`release_gate_promotion_assessment` 在 dashboard 内只校验 promotion endpoint 所需的 current level、target gate、静态 blocked_reasons、当前 tool violations 与 final delivery contract 输入可观测，避免 dashboard 反向调用依赖自身 readiness 的 promotion endpoint 形成递归。`runbook_catalog_complete` 要求 P0/P1 告警使用的处置 runbook 和已知运行时 loop repair/stop 诊断 runbook 全部注册，覆盖 uncertain/reconcile、migration、backend capability degradation、approval、checkpoint、outbox、event replay、fault injection、worker queue、context linkage、Agent runtime loop repair、RootCause rule、Memory EvidenceRef governance 和 release gate violation；后端契约测试必须从架构文档 Required catalog 段落抽取 required runbook id，并与 `REQUIRED_RUNBOOKS`、`AgentRunbookService.list_runbooks()`、dashboard check details 和 P0/P1 alert rule 引用全量对齐。

Required metrics snapshot payload contract:

```text
fields=project_id,generated_at,metrics,derived_from
derived_from_fields=counters,outbox_publish_lag_ms,scope
metrics_key_source=REQUIRED_DASHBOARD_METRICS
source=AgentMetricsService.snapshot
```

Required readiness dashboard payload contract:

```text
fields=project_id,generated_at,readiness,checks,metrics,release_gate,promotion_assessment,fault_injection,runbooks,root_cause_governance,alerts,alert_summary,derived_from
check_fields=name,status,severity,summary,details
checks=metrics_catalog_complete,release_gate_current_level_clean,fault_injection_catalog_complete,root_cause_rule_governance,runbook_catalog_complete,alert_metric_catalog_complete,live_recovery_attention,monitoring_alerts_clear,release_gate_promotion_assessment
readiness_values=pass,attention,blocked
source=AgentReadinessDashboardService.snapshot
```

Required launch audit payload contract:

```text
fields=project_id,generated_at,ready,status,checks,model_health,dashboard,promotion,derived_from
check_fields=name,status,severity,summary,details
checks=model_provider_configured,normal_conversation_runtime_available,frontend_event_contract_available,dashboard_readiness_not_blocked,backend_repository_delivery_complete,frontend_external_scope_declared,promotion_assessment_available
status_values=pass,attention,blocked
source=AgentLaunchAuditService.audit
```

Required backend completion audit payload contract:

```text
fields=project_id,generated_at,complete,status,checks,backend_scope,launch_audit,runtime_contracts,diagnostics,derived_from
check_fields=name,status,severity,summary,details
checks=model_provider_configured,conversation_runner_streaming,server_side_conversation_history,tool_loop_and_approval_resume,memory_context_injection,frontend_contract_surface,observability_and_release_gate,backend_delivery_docs_synced,live_e2e_diagnostic_available
status_values=pass,attention,blocked
runtime_contract_keys=run,events,snapshot,summary,actions,history,transcript,export,tool_execution_context,runbook_execution_context_summary,runbook_execution_context_summary_fields
diagnostic_keys=model_health,launch_audit,completion_audit,conversation_smoke,e2e_script,tool_call_detail,runbook_diagnosis
runbook_execution_context_summary_fields=execution_context_version_hash,execution_context_hash,tool_call_id,run_id,runtime_snapshot_id,tool_name,tool_version,worker_id,tool_status,execution_phase,effect_submission_state,effect_boundary_crossed,backend_name,backend_operation,backend_contract_version,backend_request_schema_hash,backend_output_schema_hash,reconcile_contract_version,result_adapter_version,backend_effect_capability,resolved_side_effect_class,resolved_replay_policy,approval_state,approval_lineage_id,approval_epoch,approved_approval_id,approved_by,input_hash,output_hash,recovery_decision,error_code,error_message_hash
source=AgentBackendCompletionAuditService.audit
```

`GET /api/v1/agents/backend-completion-audit` is the project-scoped backend-owned Agent feature completion audit. With `project_id`, any project member can read it after project permission validation; without `project_id`, it is admin-only global audit. It aggregates the launch audit and fixed backend completion checks for conversation streaming, server-side history, tool loop, approval resume, Memory injection, frontend contract surface, observability/release-gate inputs, documentation sync, and live E2E diagnostic availability. It must not run a live provider probe and must not expose `DEEPSEEK_API_KEY`. `runtime_contracts` must declare the `AgentToolCall.policy_reason_json.execution_context` source and the `AgentRunbookRecommendation.details.execution_context` whitelist summary fields; `diagnostics` must include ToolCall Detail and Runbook diagnosis entrypoints so completion audit can lead maintainers to full execution diagnostics. `complete=true` only claims the backend repository scope; frontend delivery remains external and L3 production rollout remains controlled by release gates.

`GET /api/v1/agents/launch-audit` is the project-scoped frontend integration and launch readiness audit. With `project_id`, any project member can read it after project permission validation; without `project_id`, it is admin-only global audit. It aggregates `AgentModelHealthService.check(live=false)`, `AgentReadinessDashboardService.snapshot`, and `AgentReleaseGateService.promotion_assessment` without running a live model probe or exposing `DEEPSEEK_API_KEY`. `ready=true` means the backend-owned Agent conversation and frontend contract surface are ready for integration; it does not override the L3 production rollout gate, which may remain blocked by release policy.

Dashboard catalog checks 的 details 必须与 summary 字段同名可审计：`fault_injection_catalog_complete.details` 输出 `covered_required_case_ids`、`missing_required_case_ids` 与 `extra_case_ids`；`runbook_catalog_complete.details` 输出 `covered_required_runbook_ids` 与 `missing_required_runbook_ids`；`alert_metric_catalog_complete.details` 输出 `required_alert_metric_keys`、`covered_alert_metric_keys`、`missing_alert_metric_keys`、`trigger_metric_keys`、`related_metric_keys` 与 `dynamic_metric_keys`，避免 UI 或自动验收只能读取 dashboard 顶层 summary 而无法定位具体缺口。后端文档驱动测试必须从架构文档 AgentAlertService 指标代码块抽取 required alert metrics，并与 `ALERT_FACT_METRICS`、`ALERT_RULES.metric_key`、`ALERT_RULES.related_metric_keys`、`DYNAMIC_ALERT_METRICS` 和 dashboard details 全量比对。
Runbook catalog 中每个 `safe_api_actions` 都必须指向当前 FastAPI OpenAPI 已注册的 `/api/v1/agents...` method+path；后端契约测试必须从 `AgentRunbookService.RUNBOOKS` 抽取安全恢复动作并与 OpenAPI 对齐，避免最终交付 Runbook 给出不可调用的恢复接口。
Run 级 Runbook 诊断必须从当前 run 事实表输出可执行 recommendation，而不是只返回 catalog：至少覆盖 uncertain/reconciling ToolCall、migration block、pending/stale approval、checkpoint stale、backend capability degradation、LoopObservation 缺失 decision ContextBuild、AgentConversationRunner 写入的 runtime repair/stop LoopObservation、RootCause rule missing、Memory EvidenceRef governance violation，以及当前 release gate tool matrix violation。对于 `tool_call_uncertain` 与 `backend_capability_degraded`，recommendation 的 `details.execution_context` 必须附带 ToolCall execution context 的白名单摘要，用于展示执行 hash、worker、运行时快照、效果状态、后端能力和恢复动作；不得把原始 input/output/evidence/error message 复制到 Runbook。`GET /api/v1/agents/runs/{run_id}/runbook` 必须先按 run 所属项目校验访问权限；项目成员和 admin 可读取，项目外用户必须 403，避免 Runbook 诊断泄露跨项目运行状态。

Required Runbook diagnosis contract:

```text
runbook_fields=runbook_id,title,trigger,severity,steps,safe_api_actions
diagnosis_fields=run_id,run_status,recommendations,runbooks
recommendation_fields=runbook_id,reason,severity,action,tool_call_id,details
recommendation_required_fields=runbook_id,reason,severity,action,details
recommendation_optional_fields=tool_call_id
recommendation_runbook_ids=tool_call_uncertain,migration_blocked,backend_capability_degraded,approval_stale,checkpoint_stale,outbox_publish_lag,event_replay_recovery,fault_injection_coverage,worker_queue_recovery,context_linkage_repair,agent_runtime_loop_repair,root_cause_rule_missing,memory_evidence_ref_violation,release_gate_violation
recommendation_action_contract=openapi_agent_route
recommendation_severity_source=runbook_catalog
checkpoint_freshness_safe_actions=continue_from_checkpoint:POST /api/v1/agents/runs/{run_id}/resume ,replan_from_latest_safe_state:POST /api/v1/agents/runs/{run_id}/context-builds ,migration_block:GET /api/v1/agents/runs/{run_id}/migration-blocks ,fetch_evidence_and_rebuild_context:POST /api/v1/agents/runs/{run_id}/context-builds ,materialize_latest_evidence:POST /api/v1/agents/runs/{run_id}/context-builds ,revalidate_before_side_effect:POST /api/v1/agents/runs/{run_id}/context-builds ,supersede_or_refresh_approval:GET /api/v1/agents/tool-calls/{tool_call_id} ,refresh_permissions_or_manual_review:GET /api/v1/agents/tool-calls/{tool_call_id}
```

监控告警接口 `GET /api/v1/agents/alerts` 复用 `AgentAlertService.snapshot`，按 metrics/release gate 规则输出 firing alerts、severity summary、action 和 runbook_id；dashboard 通过 `monitoring_alerts_clear` check 将 P0 alert 转为 blocked、P1 alert 转为 attention，并在 check details 中直接输出阻断告警 id 与对应 runbook id，避免 promotion/UI 只能从 severity count 反推。Reconcile 细分恢复指标必须进入告警：`tool_call_send_intent_orphan_total` 与 `tool_call_safe_retry_after_send_intent_not_found_total` 标记 P2，`tool_call_transport_sent_uncertain_total` 标记 P1，`tool_call_backend_accepted_uncertain_total` 标记 P0，并统一指向 `tool_call_uncertain` runbook。Migration 细分阻断指标必须进入告警：`runtime_snapshot_migration_block_total`、`backend_contract_migration_block_total` 与 `run_migration_blocked_total` 均标记 P1，并统一指向 `migration_blocked` runbook。Checkpoint freshness gate 失败必须进入告警：`checkpoint_freshness_failed_total` 标记 P1，并指向 `checkpoint_stale` runbook；Memory 进入 `needs_revalidation` 必须通过 `memory_needs_revalidation_total` 触发 `agent_memory_needs_revalidation` P1 告警，并同样指向 `checkpoint_stale` runbook，避免 Memory freshness 问题只停留在 metrics。ToolCall 级 contract/capability 降级必须进入告警：`tool_call_backend_contract_unsupported_total` 标记 P1 并指向 `migration_blocked` runbook，`tool_call_legacy_no_receipt_manual_total` 标记 P0 并指向 `backend_capability_degraded` runbook。Approval expire 指标必须进入告警：`approval_expire_due_total` 与 `approval_expire_batch_lag_ms` 标记 P2，并指向 `approval_stale` runbook。Approval 决策冲突必须区分总量与 epoch 子类：`approval_approve_conflict_total` 标记 P1 并指向 `approval_stale` runbook，`approval_epoch_conflict_total` 继续作为 stale client / supersede 频繁的子类 P1 告警。Approval lineage 锁观测必须进入告警：`approval_lineage_lock_wait_ms` 与 `approval_lineage_lock_skip_total` 标记 P2，并指向 `approval_stale` runbook，用于观察锁等待累积和批量扫描跳过 lineage，而不直接降低 dashboard readiness。所有 P0/P1 `ALERT_RULES` 必须提供非空 `runbook_id`，且该 id 必须出现在 `AgentRunbookService.list_runbooks()` 中；动态 release gate P0 alert 也必须显式绑定 `release_gate_violation` runbook。

Required alert snapshot payload contract:

```text
fields=project_id,generated_at,status,alerts,summary,derived_from
alert_fields=alert_id,severity,status,metric_key,observed_value,threshold,summary,action,runbook_id,details
summary_fields=total,by_severity,highest_severity
status_values=ok,firing
source=AgentAlertService.snapshot
```

Required monitoring alerts clear contract:

```text
dashboard_check=monitoring_alerts_clear
blocking_severities=P0,P1
status_rules=P0:blocked,P1:attention,none:pass
detail_fields=alert_total,by_severity,highest_severity,blocking_severities,blocking_alert_count,blocking_alert_ids,blocking_runbook_ids,p0_alert_ids,p1_alert_ids
```

Required alert runbook binding contract:

```text
runbook_required_severities=P0,P1
static_alert_rule_source=ALERT_RULES
dynamic_alert_runbooks=agent_release_gate_violation:release_gate_violation
dashboard_check=alert_metric_catalog_complete
dashboard_details=runbook_required_severities,alert_runbook_ids,covered_required_runbook_alert_ids,missing_required_runbook_alert_ids,dynamic_alert_runbooks,covered_dynamic_runbook_alert_ids,missing_dynamic_runbook_alert_ids
```
灰度发布门禁快照接口 `GET /api/v1/agents/release-gates` 是 admin-only 全局治理视图，用于读取当前 rollout level、tool matrix、静态门禁、minimum go-live、go-live gates、final delivery 与 violation。灰度晋级评估接口 `GET /api/v1/agents/release-gates/promotion` 复用 release gate snapshot 与 readiness dashboard，输出 `can_promote`、`decision`、`blockers`、静态发布门禁、dashboard checks、fault coverage、alert summary、minimum go-live、go-live gates、final delivery contract checks 与 `monitoring_alerts_clear` check；从 L2 晋级 L3/business_create 时必须同时满足静态门禁、current tool matrix 无 rollout violation、minimum go-live pass、go-live gates pass、final delivery pass、monitoring alerts 无 P0/P1 blocker 和 dashboard readiness=pass。

Required release gate snapshot payload contract:

```text
fields=current_level,current_level_summary,allowed_side_effect_classes,blocked_side_effect_classes,tool_matrix,expansion_gates,minimum_go_live,go_live_gates,final_delivery,violations
tool_fields=tool_name,tool_version,side_effect_class,replay_policy,required_permissions,backend_name,backend_operation,backend_contract_version,backend_effect_capability,backend_contract_status,rollout_allowed,rollout_decision
level_fields=level,summary,required_gates,unlocked,blocked_reasons
violation_fields=tool_name,reason,side_effect_class
rollout_decision_values=allowed,blocked
rollout_allowed_rule=current_side_effect_allowed_and_backend_contract_active_or_missing
violation_reason=tool_side_effect_exceeds_current_rollout_level
```

Dashboard 的 `release_gate_promotion_assessment` 只输出 promotion endpoint 所需输入摘要，不反向调用 promotion endpoint。该 summary 字段必须保持稳定，供 UI 和自动验收判断当前 dashboard 是否具备执行 promotion assessment 的所有输入。

Required dashboard promotion summary contract:

```text
summary_fields=endpoint,current_level,target_level,target_gate_known,target_gate_static_blocked_reasons,current_tool_violation_count,current_tool_violations,final_delivery_contract_pass,final_delivery_backend_repository_scope_pass,final_delivery_missing_by_category,final_delivery_external_scope_categories,assessment_available,dashboard_dependency
dashboard_check=release_gate_promotion_assessment
endpoint=/api/v1/agents/release-gates/promotion
dashboard_dependency=summary_only_no_recursive_promotion_call
```

Required promotion assessment contract:

```text
checks=target_level_known,target_above_current,readiness_dashboard_pass,monitoring_alerts_clear,minimum_go_live_contract_pass,go_live_gate_contract_pass,final_delivery_contract_pass,release_gate_static_reasons_clear,current_tool_matrix_clean
blocker_sources=release_gate,tool_matrix,minimum_go_live,go_live_gates,final_delivery,monitoring_alerts,readiness_dashboard
release_gate_fields=current_level,target_gate,violations,minimum_go_live,go_live_gates,final_delivery
```

Required promotion assessment payload contract:

```text
fields=project_id,current_level,target_level,target_level_summary,decision,can_promote,blockers,checks,dashboard_checks,fault_injection,alert_summary,readiness,release_gate
```

Required promotion decision contract:

```text
decision_values=blocked,allowed,already_unlocked
already_unlocked_rule=target_index<=current_index
already_unlocked_can_promote=false
already_unlocked_blockers=empty
target_above_current_status=already_unlocked
```

Required promotion blocker payload contract:

```text
fields=source,reason,severity,details
details_required_field=target_level
release_gate_details=target_level,blocked_reason,blocked_reasons
tool_matrix_details=target_level,violation_count,violations
minimum_go_live_details=target_level,missing_requirement_ids
go_live_gates_details=target_level,missing_by_priority
final_delivery_details=target_level,missing_by_category
monitoring_alerts_details=target_level,alert_summary
readiness_dashboard_details=target_level,readiness,alert_summary
```

EventStore/SSE 重放审计分两层：`GET /api/v1/agents/runs/{run_id}/events` 负责单 Run SSE 事件流与 Last-Event-ID 续播，`GET /api/v1/agents/runs/{run_id}/events/snapshot` 负责同一 EventStore 的非流式 JSON 快照和 cursor 状态，`GET /api/v1/agents/runs/{run_id}/events/replay-audit` 校验单 Run 的 `event_seq` 连续性、`last_event_sequence` 一致性、Last-Event-ID 后可重放窗口；三者都必须先按 run 所属项目校验访问权限，项目成员和 admin 可读取，项目外用户必须 403。`GET /api/v1/agents/events/replay-stress-audit` 按项目抽样最近 runs，并为每个 run 生成多个 Last-Event-ID 游标窗口，模拟高并发断线重连重放。`GET /api/v1/agents/events/replay-stress-audit` 不带 `project_id` 时仅 admin 可读取全局抽样审计；带 `project_id` 时必须校验项目访问权限后只审计该项目 runs。metrics 暴露 `event_replay_gap_total`、`event_replay_stress_failed_total`、`event_replay_stress_cursor_window_total`、`event_replay_stress_max_window_events`，alerts 暴露 `agent_event_replay_gap` 与 `agent_event_replay_stress_failed`；stress failed 告警的 `details.related_metrics` 必须带上 cursor window 数和最大 replay window，便于定位抽样覆盖范围。

Required Agent Event entity payload contract:

```text
fields=event_seq,event_type,payload_json,created_at
source=AgentEventRead
```

Required Agent Run event snapshot payload contract:

```text
fields=run,events,after_sequence,event_count,latest_event_sequence,next_after_sequence,terminal,generated_at
event_fields=event_seq,event_type,payload_json,created_at
source=AgentRunEventSnapshotRead
```

Required Event Replay audit payload contract:

```text
run_fields=run_id,project_id,last_event_sequence,after_sequence,event_count,replay_event_count,first_replay_event_seq,last_replay_event_seq,missing_sequences,duplicate_sequences,unexpected_sequences,replayable,replay_cursor_valid
stress_fields=project_id,generated_at,sample_limit,cursor_count,audited_run_count,cursor_window_count,failed_run_count,failed_run_ids,invalid_cursor_count,total_replay_events,max_replay_window_events,high_concurrency_replayable,run_audits,derived_from
stress_run_fields=run_id,project_id,last_event_sequence,event_count,cursor_audits,replayable
cursor_fields=after_sequence,replay_event_count,first_replay_event_seq,last_replay_event_seq,replayable,replay_cursor_valid
derived_from_fields=runs,events,cursor_policy
source=AgentEventReplayAuditService
```
WorkerQueue 审计接口 `GET /api/v1/agents/worker-queue/audit` 输出 `lease_scan_stable`、`expired_lease_count`、`duplicate_active_lease_count`、`oldest_queued_age_ms` 和异常明细；metrics 同步暴露 `worker_queue_expired_lease_total`、`worker_queue_duplicate_active_lease_total`、`worker_queue_oldest_queued_age_ms`，alerts 对 expired lease 触发 P1、duplicate active lease 触发 P0。

Required WorkerQueue audit payload contract:

```text
fields=project_id,generated_at,status_counts,total_count,active_count,expired_lease_count,duplicate_active_lease_count,oldest_queued_age_ms,lease_scan_stable,expired_leases,duplicate_active_leases,derived_from
expired_lease_fields=queue_id,run_id,tool_call_id,lease_owner,lease_expires_at,attempt_count,last_error_code
duplicate_active_fields=tool_call_id,queue_ids,statuses,lease_owners
derived_from_fields=queue_table,active_statuses,scope
source=AgentWorkerQueueAuditService.audit
```
Reconcile backoff 闸门会在 `next_retry_at` 未到时跳过重复 reconcile，接口返回 `skipped_backoff` 和 `skipped_backoff_tool_calls`，metrics 暴露 `reconcile_backoff_active_total`，alerts 以 `agent_reconcile_backoff_pending` 标记 P2 级节流状态，避免 not_found/running 场景形成重试风暴。
故障注入覆盖率闸门以完整 26 个 required cases 为准，metrics 暴露 `fault_injection_required_case_total`、`fault_injection_registered_case_total`、`fault_injection_missing_required_total`、`fault_injection_coverage_ratio`；alerts 以 `agent_fault_injection_coverage_incomplete` 标记缺失用例，并以 `agent_fault_injection_coverage_ratio_low` 在 `fault_injection_coverage_ratio < 1.0` 时标记覆盖率未达 100%。两个 fault coverage 告警的 `details.related_metrics` 必须携带 required、registered、missing 与 coverage ratio 上下文，避免只知道触发而不知道覆盖缺口规模。

### 10.6 验收标准

- migration_blocked 在 UI 和 API 可见。
- resolve migration block 后一定先过 Freshness Gate。
- stale checkpoint 不会直接执行高风险动作。
- Memory 错误会降权。
- P0 故障注入全部通过。
- 监控和报警可用。

---

## 11. API 开发清单

### 11.1 Run API

```text
GET  /api/v1/agents/capabilities
GET  /api/v1/agents/model-health
GET  /api/v1/agents/backend-completion-audit
POST /api/v1/agents/conversation-smoke
GET  /api/v1/agents/conversations
GET  /api/v1/agents/conversations/{conversation_id}/runs
GET  /api/v1/agents/conversations/{conversation_id}/transcript
GET  /api/v1/agents/conversations/{conversation_id}/export
GET  /api/v1/agents/runs
POST /api/v1/agents/runs
GET  /api/v1/agents/runs/{run_id}
GET  /api/v1/agents/runs/{run_id}/summary
GET  /api/v1/agents/runs/{run_id}/actions
GET  /api/v1/agents/runs/{run_id}/events
POST /api/v1/agents/runs/{run_id}/context-builds
GET  /api/v1/agents/runs/{run_id}/context-builds
POST /api/v1/agents/runs/{run_id}/loop-observations
GET  /api/v1/agents/runs/{run_id}/loop-observations
POST /api/v1/agents/runs/{run_id}/cancel
POST /api/v1/agents/runs/{run_id}/resume
POST /api/v1/agents/runs/{run_id}/reconcile
```

`GET /api/v1/agents/runs/{run_id}/summary`、`GET/POST /api/v1/agents/runs/{run_id}/context-builds`、`GET/POST /api/v1/agents/runs/{run_id}/loop-observations`、`GET /api/v1/agents/runs/{run_id}/approvals`、`GET /api/v1/agents/runs/{run_id}/migration-blocks` 与 `POST /api/v1/agents/runs/{run_id}/migration-blocks/{block_id}/resolve` 都属于 run-derived resource API，必须先按 run 所属项目校验访问权限；项目成员和 admin 可读取/操作本 run 派生资源，项目外用户即使知道 run_id、block_id 或 approval_id 也必须 403。

Required ContextBuild entity payload contract:

```text
fields=context_build_id,run_id,iteration,step_index,build_seq,build_purpose,model_name,token_budget,estimated_input_tokens,context_degradation_level,compressed_sections_json,omitted_evidence_refs_json,required_evidence_refs_json,required_evidence_complete,decision_quality_risk,prompt_object_key,prompt_hash,build_metadata_json,created_at
source=AgentContextBuildRead
```

`build_metadata_json` 必须包含 `policy_refs`、`selected_agent_skills`、`matched_agent_skill_routing_rules`、`runtime_snapshot` 与 `permission_context` 五类诊断输入，其中 Skill 相关字段只允许 name/hash、routing_key、after_tool、required_tool、min_total_fields 与 rule_hash 这类摘要字段，runtime snapshot 只允许 snapshot id、runtime/tool registry/manifest/prompt/policy hash、available tool names 与 tool count，permission context 只允许 actor/project/access level、project access flag、implicit permission flag、显式权限码列表/count 与 permission hash。required follow-up、工具前置阻断、工具请求格式修复、max-iteration stop、no-progress stop 和权限相关 stop 等由 Runner 创建的 decision ContextBuild 都必须保留该元数据，以便 LoopObservation/Runbook 可解释静默纠错来源和当时绑定的工具/策略/权限版本。

Required LoopObservation entity payload contract:

```text
fields=observation_id,run_id,iteration,step_index,decision_context_build_id,decision_context_degradation_level,iteration_context_degradation_max,required_evidence_complete_for_decision,omitted_required_evidence_refs_json,next_action,next_action_is_high_risk,stop_action_reason,stop_reasons_all_json,root_cause_primary,root_cause_rule_id,causal_chain_json,mitigation_action,observation_json,created_at
source=AgentLoopObservationRead
```

Required Agent Run entity payload contract:

```text
fields=run_id,project_id,user_id,conversation_id,intent,status,current_iteration,current_step_index,max_iterations,runtime_snapshot_id,last_checkpoint_id,last_event_sequence,migration_block_count,blocking_tool_call_ids_json,result_json,error_code,error_message,started_at,completed_at,created_at,updated_at
source=AgentRunRead
```

Required Agent Run summary payload contract:

```text
fields=run,assistant_message,assistant_visible,completion_source,model_invoked,model,finish_reason,usage,event_count,latest_event_sequence,latest_event_types,tool_call_count,pending_tool_call_count,approval_count,pending_approval_count,migration_block_count,open_migration_block_count,memory_usage_count,blocking_tool_call_ids,terminal,can_cancel,can_resume,updated_at
source=AgentRunSummaryRead
```

`GET /api/v1/agents/runs/{run_id}/actions` 返回 Codex 式右侧操作区所需的只读 action state。后端必须从 Run、ToolCall、Approval、MigrationBlock 等事实表聚合可操作入口，输出固定顺序 action 列表：`view_summary`、`stream_events`、`cancel_run`、`review_approvals`、`resume_run`、`reconcile_run`、`resolve_migration`、`open_runbook`。前端只根据 `enabled`、`reason`、`resource_ids` 和 `primary_action_ids` 渲染按钮，不再自行推断 pending approval、uncertain tool 或 migration block 的优先级。

Required Agent Run action state payload contract:

```text
fields=run_summary,actions,primary_action_ids,blocked_reasons,generated_at
action_fields=action_id,label,method,path,enabled,reason,severity,resource_ids,details
action_ids=view_summary,stream_events,cancel_run,review_approvals,resume_run,reconcile_run,resolve_migration,open_runbook
source=AgentRunActionStateRead
```

`GET /api/v1/agents/conversations/{conversation_id}/transcript` 返回服务端可恢复的 Codex 式 conversation transcript，按 run 创建时间升序返回每一轮的 `AgentRunSummaryRead`，用于前端刷新后恢复 user prompt、assistant 最终回复、运行状态和右侧计数 badge。该接口必须带 `project_id` 并先校验项目访问权限；项目外用户不得通过 conversation_id 枚举历史。

Required Agent Conversation transcript payload contract:

```text
fields=conversation,turns,generated_at
conversation_fields=conversation_id,project_id,title,run_count,latest_run_id,latest_run_status,created_at,updated_at
turn_fields=run,assistant_message,assistant_visible,completion_source,model_invoked,model,finish_reason,usage,event_count,latest_event_sequence,latest_event_types,tool_call_count,pending_tool_call_count,approval_count,pending_approval_count,migration_block_count,open_migration_block_count,memory_usage_count,blocking_tool_call_ids,terminal,can_cancel,can_resume,updated_at
source=AgentConversationTranscriptRead
```

`GET /api/v1/agents/conversations/{conversation_id}/export` 返回可下载/可调试的 Codex 式 conversation export 包。它必须复用 transcript 的项目权限校验和 run 顺序，并按 run_id 分组输出 EventStore、ToolCall、Approval、MigrationBlock 派生事实；导出包只包含后端 redacted 字段，不暴露未脱敏模型 prompt、密钥或原始大对象。

Required Agent Conversation export payload contract:

```text
fields=conversation,turns,events_by_run_id,tool_calls_by_run_id,approvals_by_run_id,migration_blocks_by_run_id,export_format,generated_at,derived_from
conversation_fields=conversation_id,project_id,title,run_count,latest_run_id,latest_run_status,created_at,updated_at
turn_fields=run,assistant_message,assistant_visible,completion_source,model_invoked,model,finish_reason,usage,event_count,latest_event_sequence,latest_event_types,tool_call_count,pending_tool_call_count,approval_count,pending_approval_count,migration_block_count,open_migration_block_count,memory_usage_count,blocking_tool_call_ids,terminal,can_cancel,can_resume,updated_at
event_fields=event_seq,event_type,payload_json,created_at
tool_call_fields=tool_call_id,run_id,step_index,attempt_index,runtime_snapshot_id,tool_name,tool_version,schema_hash,manifest_hash,idempotency_scope,idempotency_key,base_side_effect_class,resolved_side_effect_class,base_replay_policy,resolved_replay_policy,policy_reason_json,status,execution_phase,effect_submission_state,input_hash,input_json_redacted,evidence_refs_json,policy_evidence_refs_json,audit_evidence_refs_json,evidence_mutability_summary_json,decision_context_build_id,output_hash,output_json_redacted,required_permissions_json,permission_snapshot_json,approval_required,approval_scope_hash,approval_lineage_id,approval_epoch,approved_approval_id,approved_by,approved_at,backend_name,backend_operation,backend_contract_version,backend_request_schema_hash,backend_output_schema_hash,reconcile_contract_version,result_adapter_version,backend_effect_capability,recovery_decision,error_code,error_message,current_approval,approval_lineage,recent_reconcile_attempts,created_at,updated_at
source=AgentConversationExportRead
```

### 11.2 ToolCall API

```text
GET  /api/v1/agents/tool-calls/{tool_call_id}
POST /api/v1/agents/tool-calls/{tool_call_id}/approve
POST /api/v1/agents/tool-calls/{tool_call_id}/reject
```

`GET /api/v1/agents/tool-calls/{tool_call_id}` 必须先按 ToolCall 所属 run 的项目访问权限校验，项目成员和 admin 可读取，项目外用户必须 403，避免通过 tool_call_id 枚举跨项目执行细节。

Required ToolCall entity payload contract:

```text
fields=tool_call_id,run_id,step_index,attempt_index,runtime_snapshot_id,tool_name,tool_version,schema_hash,manifest_hash,idempotency_scope,idempotency_key,base_side_effect_class,resolved_side_effect_class,base_replay_policy,resolved_replay_policy,policy_reason_json,status,execution_phase,effect_submission_state,input_hash,input_json_redacted,evidence_refs_json,policy_evidence_refs_json,audit_evidence_refs_json,evidence_mutability_summary_json,decision_context_build_id,output_hash,output_json_redacted,required_permissions_json,permission_snapshot_json,approval_required,approval_scope_hash,approval_lineage_id,approval_epoch,approved_approval_id,approved_by,approved_at,backend_name,backend_operation,backend_contract_version,backend_request_schema_hash,backend_output_schema_hash,reconcile_contract_version,result_adapter_version,backend_effect_capability,recovery_decision,error_code,error_message,current_approval,approval_lineage,recent_reconcile_attempts,created_at,updated_at
source=AgentToolCallRead
```

`policy_reason_json.policy_context` 必须保留 ToolPolicyResolver 对该 ToolCall 的统一策略 envelope：policy version、tool name/version、base/resolved side effect、base/resolved replay policy、approval policy、approval reason、active/volatile/frozen policy evidence 计数、historical volatile excluded 计数、mixed evidence 标记和 `policy_hash`。ToolCall Detail、Runbook 和评测可以展示该摘要解释审批与 replay policy 决策；不得在该 envelope 中写入原始 evidence、完整模型输入或未脱敏业务 payload。

`policy_reason_json.execution_context` 必须保留 ToolExecutor 对成功、失败、manual intervention 和 uncertain recovery ToolCall 的执行/恢复上下文 envelope：execution context version、tool/run/runtime snapshot、worker、tool status、execution/effect state、backend contract/schema hash/effect capability、resolved side effect/replay policy、approval state/lineage/epoch/approved approval、input/output hash、recovery decision、error code、error message hash 和 `execution_context_hash`。ToolCall Detail、Runbook 和评测可以展示该摘要解释执行时审批、后端契约、效果提交状态和恢复原因；不得在该 envelope 中写入原始 input/output/evidence/error message 或未脱敏业务 payload。Runbook 展示该摘要时只能使用白名单字段，不能复制完整 `policy_reason_json` 或原始业务 payload。

### 11.3 Snapshot API

```text
GET /api/v1/agents/runtime-snapshots/{snapshot_id}
```

`GET /api/v1/agents/runtime-snapshots/{snapshot_id}` 必须按 snapshot.project_id 校验项目访问权限，项目成员和 admin 可读取，项目外用户必须 403，避免冻结运行时契约被跨项目枚举。

Required RuntimeSnapshot entity payload contract:

```text
fields=snapshot_id,project_id,created_by,runtime_hash,tool_registry_hash,manifest_bundle_hash,prompt_bundle_hash,policy_version_hash,tools_json,manifests_json,adapters_json,policies_json,created_at
source=AgentRuntimeSnapshotRead
```

### 11.4 Memory API

```text
GET   /api/v1/agents/memories
POST  /api/v1/agents/memories
PATCH /api/v1/agents/memories/{memory_id}
POST  /api/v1/agents/memories/{memory_id}/validate
POST  /api/v1/agents/memories/{memory_id}/reject
POST  /api/v1/agents/memories/retrieve
GET   /api/v1/agents/memory-source-profiles
GET   /api/v1/agents/memory-retrieval-profiles
GET   /api/v1/agents/memory-usage-events
GET   /api/v1/agents/memory-validation-events
GET   /api/v1/agents/memory-staleness-events
POST  /api/v1/agents/memory-usage-events/{usage_event_id}/feedback
POST  /api/v1/agents/memory-feedback/process
```

`GET /api/v1/agents/memory-usage-events` 不带 `run_id` 时是全局 Memory usage 审计视图，必须 admin-only；带 `run_id` 时必须先复用 Run 访问权限校验，再只返回该 run 的 usage events，避免普通项目用户枚举跨项目 Memory 使用轨迹。

Required Memory entity payload contract:

```text
fields=id,project_id,memory_type,title,content,content_hash,memory_version,source_type,source_ref_json,authority,confidence,initial_confidence,confidence_reason_json,contradiction_count,recent_contradiction_count,validation_count,recent_validation_count,stale_score,stale_reason_json,status,evidence_refs_json,watched_refs_json,created_by,created_at,updated_at
source=AgentMemoryRead
```

Required Memory profile catalog payload contract:

```text
source_profile_fields=source_type,initial_confidence,authority,default_ttl_days,requires_source_ref,requires_content_hash,allowed_for_high_risk,status
retrieval_profile_fields=profile_name,task_scope,risk_level,min_confidence,max_stale_score,allow_memory_for_high_risk,semantic_weight,confidence_weight,recency_weight,authority_weight,validation_weight,stale_weight,contradiction_weight,max_contradiction_penalty,version,status,change_reason
source=MemoryProfileCatalogRoutes
```

Required Memory usage event payload contract:

```text
fields=id,memory_id,run_id,iteration,step_index,tool_call_id,context_build_id,retrieval_profile,retrieval_score,usage_role,active_for_policy,caused_tool_input_change,outcome,evidence_ref_json,feedback_state,feedback_processed_at,feedback_result_json,created_at
evidence_ref_fields=evidence_ref_id,ref_type,ref_id,mutability_class,dependency_role,active_for_policy,version_id,content_hash,captured_at,freshness_policy,required_for_high_risk,authority
source=GET /api/v1/agents/memory-usage-events
```

Required Memory staleness event payload contract:

```text
fields=id,project_id,memory_id,evidence_ref_type,evidence_ref_id,stale_reason,previous_stale_score,new_stale_score,previous_status,new_status,created_at
source=GET /api/v1/agents/memory-staleness-events
```

Required Memory validation event payload contract:

```text
fields=id,project_id,memory_id,run_id,tool_call_id,usage_event_id,validation_source,evidence_ref_json,reason,previous_confidence,new_confidence,previous_stale_score,new_stale_score,previous_status,new_status,validation_count,created_at
source=GET /api/v1/agents/memory-validation-events
```

### 11.5 Migration API

```text
GET  /api/v1/agents/runs/{run_id}/migration-blocks
POST /api/v1/agents/runs/{run_id}/migration-blocks/{block_id}/resolve
```

---

## 12. 前端开发计划

### 12.1 Agent Run 页面

功能：

```text
创建 Agent Run
显示 run 状态
显示当前 iteration / step
显示事件时间线
显示 tool_call 状态
显示 pending approval
显示 migration block
显示最终结果
```

### 12.2 Event Timeline

展示事件：

```text
run.*
step.*
model.*
tool.*
approval.*
context.*
loop.*
heartbeat
```

要求：

- SSE 实时更新。
- 支持断线重连。
- 支持 EventStore replay。
- tool.uncertain / migration_blocked / approval.superseded 必须醒目展示。

### 12.3 ToolCall Detail

展示：

```text
tool_name / version
status
effect_submission_state
idempotency_key
resolved_side_effect_class
resolved_replay_policy
backend_operation
backend_effect_capability
evidence_refs
approval_required
output summary
error / recovery_decision
execution_context summary
```

### 12.4 Approval Panel

展示：

```text
审批内容摘要
input_hash
runtime_snapshot_id
resource_scope_hash
risk reason
permission scope
approval_epoch
expires_at
superseded_by_tool_call_id
```

交互：

- approve。
- reject。
- stale 后刷新。
- superseded 后禁用按钮。

### 12.5 Migration Block 页面

展示：

```text
block_type
reason
affected tool_call
backend_contract_version
unsupported schema 信息
resolve 按钮
resolve 后 freshness gate 结果
```

---

## 13. DB Migration 批次

### Batch 1：Runtime 基础

```text
ai_agent_runtime_snapshots
ai_agent_runs
ai_agent_events
ai_agent_outbox
ai_agent_checkpoints
```

### Batch 2：Tool 执行

```text
ai_agent_tool_calls
ai_agent_worker_queue
ai_agent_backend_contracts
ai_agent_reconcile_attempts
```

### Batch 3：审批

```text
ai_agent_approval_lineages
ai_agent_approvals
ai_agent_approval_mutation_logs
```

### Batch 4：Loop 与证据

```text
ai_agent_context_builds
ai_agent_loop_observations
ai_agent_evidence_watches
ai_agent_root_cause_rules
```

### Batch 5：Memory 与 Migration

```text
ai_project_memories
ai_agent_memory_source_profiles
ai_agent_memory_retrieval_profiles
ai_agent_memory_usage_events
ai_agent_memory_contradiction_events
ai_agent_memory_evidence_links
ai_agent_migration_blocks
```

---

## 14. MVP 范围

### 14.1 MVP 必须包含

```text
AgentRuntimeSnapshot
Run API
EventStore / Outbox / SSE
CheckpointStore
ExecutionLedger
WorkerQueue
ToolExecutor
ToolRegistry
ToolPolicyResolver
BackendContractRegistry
BackendEffectCapability
ReconcileWorker
Execute-time Permission Check
ApprovalService
ApprovalLineage
ApprovalMutationGuard
ContextBuilder
ContextBudget
EvidenceRefResolver
LoopController
RootCauseRuleEngine
MigrationCoordinator
Checkpoint Freshness Gate
MemorySourceProfile / MemoryRetrievalProfile 基础表
Memory -> EvidenceRef Adapter
基础监控
```

### 14.2 MVP 首批工具

```text
project.read_context
scenario.compose_draft
testcase.validate_schema
scenario.execute_dry_run
ai_skill.run_draft
report.read_summary
```

### 14.3 MVP 暂不开放

```text
defect.create
scenario.overwrite
environment.update
external_effect
destructive
跨项目 Agent
多 Agent 协作
自动 rollback
复杂长期记忆自动写入
未通过 EvidenceRef 包装的 Memory prompt 注入
高风险动作依赖 Memory 作为唯一依据
```

---

## 15. 里程碑与验收门禁

### Milestone 1：Runtime Skeleton

交付：

```text
Run API
Snapshot
EventStore
Outbox
SSE
Checkpoint
```

验收：

- 可创建 run。
- 可查询 snapshot。
- 可通过 SSE 看到事件。
- 可从 EventStore 重放事件。
- cancel 生效。

### Milestone 2：Safe Tool Execution

交付：

```text
ExecutionLedger
WorkerQueue
ToolExecutor
ToolRegistry
read_only / draft_only tools
```

验收：

- ToolCall 幂等。
- Worker 崩溃可恢复。
- lease 不会永久卡死。
- 状态变化写 EventStore。

### Milestone 3：Recoverable Side Effect

交付：

```text
BackendContractRegistry
BackendEffectCapability
ReconcileWorker
Scenario/TestCase/AISkill Adapter
```

验收：

- uncertain 可 reconcile。
- unsupported_schema_version 进入 migration block。
- legacy_no_receipt 高风险工具被阻断。

### Milestone 4：Approval Safe Execution

交付：

```text
三阶段权限
ApprovalService
ApprovalLineage
ApprovalMutationGuard
Approval UI
```

验收：

- approve/supersede 并发安全。
- 旧 approval 无法被批准。
- execute-time 权限撤销生效。

### Milestone 5：Loop Intelligence

交付：

```text
EvidenceRefResolver
ContextBuilder
ContextBudget
LoopController
RootCauseRuleEngine
```

验收：

- plan -> tool -> observe -> repair 可跑通。
- evidence 生命周期正确。
- context 降级可观测。
- root cause 有 rule_id。

### Milestone 6：Production Hardening

交付：

```text
MigrationCoordinator
Checkpoint Freshness Gate
MemoryManager
MemorySourceProfile / RetrievalProfile
MemoryEvidenceAdapter
MemoryFeedbackWorker
故障注入
监控报警
灰度开关
Runbook
```

验收：

- P0 故障注入通过。
- stale checkpoint 不直接执行高风险动作。
- migration block 可人工 resolve。
- Memory confidence/source profile、retrieval profile、contradiction penalty 均可审计。
- Memory 检索结果必须通过 EvidenceRef 进入 ContextBuilder。
- 监控 dashboard 可用。

---

## 16. 上线门禁

### 16.1 P0 门禁

```text
Run / Snapshot / Event / SSE 端到端通过
ToolCall idempotency_key 唯一约束生效
Worker 崩溃后可恢复
send_intent / transport_sent / backend_accepted / effect_committed 测试通过
Reconcile succeeded / not_found / conflict / unsupported_schema_version 测试通过
Approval approve/supersede 并发测试通过
Execute-time permission revoked 测试通过
EventStore 与 Outbox 不双写丢事件
高风险 legacy_no_receipt 工具无法自动执行
Migration block 能阻断 Run 并在 UI 可见
```

### 16.2 P1 门禁

```text
EvidenceRef active policy refs 筛选正确
历史 volatile evidence 不污染 replay policy
Context decision build binding 正确
required_evidence_complete=false 时阻断高风险动作
RootCauseRuleEngine 每次都有 rule_id
root_cause_rule_missing_total 可报警
checkpoint freshness gate 能触发 revalidate / replan
Memory contradiction 会降权
Memory 检索结果必须包装为 EvidenceRef
Memory retrieval profile 和 contradiction_penalty 有确定实现
高风险动作不能只依赖 Memory
```

### 16.3 P2 门禁

```text
多 Worker 并发 claim 不重复
分布式环境下 lease 扫描稳定
WorkerQueue audit 无 expired lease / duplicate active lease
Reconcile backoff 不造成风暴
Approval 批量 expire 不造成锁热点，且 expire audit 无 due backlog / lineage hotspot
SSE 高并发下可重放，且 replay stress audit 无 failed run / invalid cursor
故障注入覆盖率达标，且 coverage audit 26/26 通过
监控 dashboard 完整
```

Required go-live gate contract:

```text
P0=run_snapshot_event_sse_e2e,tool_call_idempotency_unique,worker_crash_recoverable,effect_submission_states_tested,reconcile_core_statuses_tested,approval_concurrency_tested,execute_time_permission_revoked_tested,event_outbox_no_double_write_loss,legacy_no_receipt_high_risk_blocked,migration_block_visible
P1=evidence_ref_active_policy_filter,historical_volatile_evidence_excluded,context_decision_build_binding,incomplete_required_evidence_blocks_high_risk,root_cause_rule_id_required,root_cause_rule_missing_alerts,checkpoint_freshness_revalidate_replan,memory_contradiction_penalizes,memory_retrieval_wrapped_as_evidence_ref,memory_profiles_and_penalty_deterministic,high_risk_not_memory_only
P2=multi_worker_claim_unique,distributed_lease_scan_stable,worker_queue_audit_clean,reconcile_backoff_prevents_storm,approval_expire_no_hotspot,sse_replay_stress_clean,fault_injection_coverage_complete,monitoring_dashboard_complete
```

Required go-live gate payload contract:

```text
fields=pass,priorities,tiers,missing_by_priority
tier_fields=priority,required_gate_ids,passed_gate_ids,missing_gate_ids,checks,pass
check_fields=gate_id,label,status,evidence
evidence=covered_by_agent_runtime_regression_suite
```

---

## 17. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 下游短期不愿改 durable receipt | receipt_first 无法快速落地 | 使用 operation 级 capability，先接 idempotency_index_only |
| legacy_no_receipt 工具过多 | 自动恢复率低 | 高风险工具不开放自动恢复，优先改造 P0 operation |
| Approval lineage 锁热点 | approve/expire 冲突 | 单 lineage 短事务、SKIP LOCKED、固定排序、退避 |
| Reconcile not_found 误判 | 可能误转人工或误重试 | 结合 effect_submission_state + capability 判断 |
| Context 压缩导致错误决策 | 高风险动作证据不足 | required_evidence_complete=false 时强制 fetch_full_evidence 或人工 |
| 长时间 migration/approval 后状态过期 | 旧 checkpoint 决策不可靠 | Checkpoint Freshness Gate，必要时 replan |
| RootCause 规则缺失 | 指标误导优化方向 | root_cause_rule_missing_total 报警，新增 reason 必须补规则 |
| Memory 陈旧或绕过 EvidenceRef | 污染 plan/repair/policy | Memory 必须包装成 EvidenceRef；source/retrieval profile hard gate；EvidenceWatch 触发 needs_revalidation；contradiction_penalty 明确定义 |

---

## 18. 开发依赖关系

```text
AgentRuntimeSnapshot
  -> ToolRegistry
  -> ToolCall creation

EventStore / Outbox
  -> SSE
  -> UI Timeline

ExecutionLedger
  -> WorkerQueue
  -> ToolExecutor
  -> ReconcileWorker

BackendContractRegistry
  -> ToolExecutor
  -> ReconcileWorker
  -> MigrationCoordinator

ApprovalLineage
  -> ApprovalService
  -> Approval Frontend
  -> Execute-time Check

EvidenceRefResolver
  -> ToolPolicyResolver
  -> ContextBuilder
  -> LoopController

ContextBuilder
  -> LoopObservation
  -> RootCauseRuleEngine

MigrationCoordinator
  -> Resume
  -> Checkpoint Freshness Gate
```

严禁跳过的依赖：

```text
没有 ExecutionLedger，不接副作用工具。
没有 BackendEffectCapability，不做 automatic recovery。
没有 ApprovalMutationGuard，不开放 business_create。
没有 EvidenceRefResolver，不做 require_revalidation。
没有 Context decision build binding，不执行高风险动作。
没有 RootCauseRuleEngine，不把 diagnostic_summary 作为可靠指标。
没有 MemoryEvidenceAdapter 和 retrieval profile，不让 Memory 进入自动 Plan/Repair。
```

---

## 19. 实际执行顺序建议

### 第一批：安全地基

```text
1. AgentRuntimeSnapshot
2. Run API
3. EventStore / Outbox / SSE
4. CheckpointStore
5. ExecutionLedger
6. WorkerQueue
7. ToolExecutor
8. read_only / draft_only 工具
```

### 第二批：可恢复副作用

```text
1. BackendContractRegistry
2. BackendEffectCapability
3. ReconcileWorker
4. Scenario execute_dry_run
5. TestCase execute
6. AISkill run
7. 故障注入
```

### 第三批：审批与权限

```text
1. Plan-time 权限过滤
2. Approval-time 权限校验
3. Execute-time 权限校验
4. ApprovalLineage
5. ApprovalMutationGuard
6. Approval 前端
7. 并发测试
```

### 第四批：Loop 智能化

```text
1. EvidenceRefResolver
2. ToolPolicyResolver
3. ContextBuilder
4. ContextBudget
5. LoopController
6. RootCauseRuleEngine
```

### 第五批：生产硬化

```text
1. MigrationCoordinator
2. Checkpoint Freshness Gate
3. MemorySourceProfile / MemoryRetrievalProfile
4. MemoryEvidenceAdapter
5. MemoryManager / MemoryFeedbackWorker
6. Metrics dashboard
7. Runbook
8. 灰度上线
```

---

## 20. 最终交付清单

### 20.1 后端交付

```text
Agent Runtime Service
Worker Service
Reconcile Worker
Outbox Publisher
Backend Adapter SDK
Approval Service
Migration Coordinator
Metrics Exporter
```

### 20.2 前端交付

```text
Agent Run 页面
Agent Event Timeline
ToolCall Detail 页面
Approval Panel
Migration Block 页面
RootCause / Diagnostic 展示
SSE 实时状态更新
```

### 20.3 平台交付

```text
DB migration
Object storage bucket policy
监控 dashboard
报警规则
灰度开关
故障注入脚本
回滚方案
```

### 20.4 文档交付

```text
Backend Operation 接入规范
ToolSpec 编写规范
EvidenceRef 编写规范
Approval 并发规范
Reconcile Contract 规范
RootCause Rule 新增规范
Runbook：uncertain 恢复
Runbook：migration_blocked 处理
Runbook：approval stale 处理
Runbook：checkpoint stale 处理
Runbook：outbox publish lag 处理
Runbook：event replay / SSE replay 处理
Runbook：fault injection coverage 处理
Runbook：WorkerQueue lease / duplicate claim 处理
Runbook：context linkage repair
Runbook：RootCause rule missing 处理
Runbook：Memory EvidenceRef governance violation 处理
Runbook：release gate violation 处理
```

Required final delivery contract:

```text
backend=agent_runtime_service,worker_service,reconcile_worker,outbox_publisher,backend_adapter_sdk,approval_service,migration_coordinator,metrics_exporter
frontend=agent_run_page,agent_event_timeline,tool_call_detail_page,approval_panel,migration_block_page,root_cause_diagnostic_view,sse_realtime_status
platform=db_migration,object_storage_bucket_policy,monitoring_dashboard,alert_rules,rollout_switch,fault_injection_scripts,rollback_plan
documentation=backend_operation_integration_spec,tool_spec_authoring_spec,evidence_ref_authoring_spec,approval_concurrency_spec,reconcile_contract_spec,root_cause_rule_authoring_spec,runbook_uncertain_recovery,runbook_migration_blocked,runbook_approval_stale,runbook_checkpoint_stale,runbook_outbox_publish_lag,runbook_event_replay,runbook_fault_injection_coverage,runbook_worker_queue_recovery,runbook_context_linkage_repair,runbook_root_cause_rule_missing,runbook_memory_evidence_ref_violation,runbook_release_gate_violation
```

Required final delivery payload contract:

```text
fields=pass,backend_repository_scope_pass,categories,external_scope_categories,missing_by_category
category_fields=category,external_scope,required_artifact_ids,delivered_artifact_ids,external_scope_artifact_ids,missing_artifact_ids,checks,pass
check_fields=artifact_id,label,status,evidence
external_scope_status=external_scope
backend_owned_status=pass
```

---

## 21. 最小上线版本定义

最小上线版本不以“模型是否足够聪明”为标准，而以“是否具备生产安全闭环”为标准。

必须满足：

```text
AgentRuntimeSnapshot 已冻结版本事实。
ExecutionLedger 已作为副作用事实源。
ToolExecutor 已实现 lease、heartbeat、orphan recovery。
BackendEffectCapability 已按 operation 声明。
ReconcileWorker 能处理 uncertain。
ApprovalMutationGuard 能处理 approve/supersede 并发。
Execute-time Permission Check 生效。
EventStore / Outbox / SSE 不丢事件。
ContextBudget 降级可观测。
EvidenceRef 生命周期可审计。
RootCauseRuleEngine 不使用黑盒函数。
Migration Block 和 Checkpoint Freshness Gate 可用。
P0 故障注入全部通过。
```

Required minimum go-live contract:

```text
runtime_snapshot_frozen
execution_ledger_effect_source
tool_executor_recovery
backend_effect_capability_declared
reconcile_uncertain_supported
approval_mutation_guard_concurrency
execute_time_permission_check
event_outbox_sse_reliable
context_budget_observable
evidence_ref_lifecycle_auditable
root_cause_rule_engine_explicit
migration_and_checkpoint_available
p0_fault_injection_passed
```

Required minimum go-live payload contract:

```text
fields=pass,required_requirement_ids,passed_requirement_ids,missing_requirement_ids,checks,business_create_expansion_prerequisite
check_fields=requirement_id,label,status,details
expansion_prerequisite=business_create
```

只有满足以上条件，才允许从 `read_only / draft_only / execution_record` 灰度扩大到 `business_create`。
