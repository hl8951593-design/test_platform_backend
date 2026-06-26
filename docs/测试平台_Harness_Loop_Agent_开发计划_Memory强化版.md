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

### 4.3 必须冻结的 API 错误码

```text
409 approval_stale_or_superseded
409 approval_epoch_conflict
409 tool_call_obsolete
409 run_migration_blocked
409 checkpoint_stale_replan_required
403 permission_revoked_before_execution
422 backend_contract_unsupported
423 tool_call_uncertain_reconcile_required
424 backend_reconcile_not_supported
424 backend_capability_too_weak
500 event_outbox_write_failed
```


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
- Memory 检索结果必须包装成 `ref_type=memory` 的 EvidenceRef。

### 4.4 必须冻结的灰度等级

| 灰度 | 允许工具 | 禁止工具 | 前置条件 |
|---|---|---|---|
| L0 | read_only | 所有副作用 | Run/Event/Snapshot 可用 |
| L1 | deterministic_compute / draft_only | business_create/update | Ledger/Worker 可用 |
| L2 | execution_record | external_effect/destructive | Reconcile 最低支持 |
| L3 | business_create | destructive | Approval + Reconcile + Execute-time Check |
| L4 | receipt_first operation | destructive 默认关闭 | durable receipt / operation 级 capability |
| L5 | external_effect / destructive | 无 | 强审批 + full evidence + rollback/manual path |

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
- EventStore 失败必须让主事务失败。

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
POST /api/v1/agents/runs
GET  /api/v1/agents/runs/{run_id}
GET  /api/v1/agents/runs/{run_id}/events
POST /api/v1/agents/runs/{run_id}/cancel
GET  /api/v1/agents/runtime-snapshots/{snapshot_id}
```

### 5.4 测试任务

- 创建 run 后必须生成或复用 snapshot。
- run.started / run.completed 必须写入 EventStore。
- SSE 断线后可用 Last-Event-ID 续播。
- Outbox 发布失败后可重试。
- cancel 后不能继续调度 tool_call。
- checkpoint 可恢复 iteration 和 step_index。

### 5.5 验收标准

- 无工具调用的 run 可端到端完成。
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

### 6.3 服务任务

#### 6.3.1 ToolRegistry

- 从 AgentRuntimeSnapshot 读取 ToolSpec。
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
- backend_accepted + not_found => backend contract incident。
- unsupported_schema_version => ToolCall needs_migration。
- legacy_no_receipt + business_create => manual_intervention。
- conflict => manual_intervention。
- succeeded reconcile => mark_succeeded_from_reconcile。
- running reconcile => still_running，延迟重试。

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

### 8.6 Approval API

```text
POST /api/v1/agents/tool-calls/{tool_call_id}/approve
POST /api/v1/agents/tool-calls/{tool_call_id}/reject
GET  /api/v1/agents/tool-calls/{tool_call_id}
```

approve 必须校验：

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

### 8.9 验收标准

- 审批 input 不可变。
- 新旧 approval 不会同时 pending。
- 旧 approval 不会被错误批准。
- 高风险工具没有有效 approval 不会执行。
- 所有审批动作可审计。
- 批量后台任务不会成为 lineage 锁热点。

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
  "dependency_role": "policy_dependency | audit_context | debug_context | superseded_evidence",
  "active_for_policy": true,
  "superseded_by_ref": null,
  "freshness_policy": "none | revalidate_on_resume | revalidate_before_side_effect"
}
```

#### 9.2.2 策略证据筛选

只有以下证据参与 replay_policy：

```text
active_for_policy=true
AND dependency_role=policy_dependency
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

初始规则：

```text
RC_CONTEXT_OMITTED_HIGH_RISK
RC_EVIDENCE_INCOMPLETE
RC_MEMORY_CONTRADICTION
RC_POLICY_LOOP
RC_BACKEND_CAPABILITY_DEGRADED
RC_REPAIR_REGRESSION
RC_NO_PROGRESS_PURE
RC_RESOURCE_LIMIT
RC_MAX_ITERATIONS
RC_UNKNOWN
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
| backend_contract_changed | migration block |
| environment_changed | revalidate before side effect |
| too_old | replan from latest safe state |

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
ai_agent_memory_evidence_links
```

#### 10.3.2 Source Profile

开发任务：

- 实现 `MemorySourceProfileResolver`。
- 为 `user_confirmed / execution_learned / document_imported / agent_summarized / repair_inferred / external_imported` 定义不同初始 confidence。
- source_type 未配置 profile 时，禁止创建 active memory。
- `agent_summarized` 与 `repair_inferred` 默认不得进入高风险动作 policy dependency。

验收：

- 用户确认 memory 初始 confidence 高于 agent_summarized。
- 所有 memory 创建事件都记录 initial_confidence 和 confidence_reason_json。
- 未知 source_type 创建失败或进入 needs_review。

#### 10.3.3 Retrieval Profile

开发任务：

- 实现 `MemoryRetrievalProfile`。
- 将检索权重从代码常量迁移到 `ai_agent_memory_retrieval_profiles`。
- 实现 hard gate：status、expires_at、min_confidence、max_stale_score、risk_level。
- 默认 profile 至少包括：`normal_plan_v1 / repair_v1 / high_risk_action_v1 / audit_explain_v1`。

验收：

- semantic_score 不能绕过 min_confidence。
- high_risk_action_v1 不允许低 confidence 或高 stale memory 进入 active policy refs。
- profile 缺失时触发 `memory_retrieval_profile_missing_total`。

#### 10.3.4 contradiction_penalty

开发任务：

- 实现 `ai_agent_memory_contradiction_events`。
- 实现确定性 `compute_contradiction_penalty`。
- 支持 severity multiplier：low / medium / high / critical。
- 支持 recent_contradiction_count、same_failure_fingerprint、validation_offset。

验收：

- contradiction_penalty 有单元测试和边界测试。
- critical contradiction 会让 memory 进入 needs_revalidation 或 rejected。
- 用户明确否定的 memory 不再被检索。

#### 10.3.5 Memory 与 EvidenceRef 集成

开发任务：

- 实现 `MemoryEvidenceAdapter.to_evidence_ref`。
- Memory 检索结果必须转换为 `ref_type=memory`。
- usage_role 映射到 `dependency_role`：trace_only / planning_hint / repair_hint / policy_dependency。
- 只有 `policy_dependency` 可设置 `active_for_policy=true`。
- ToolPolicyResolver 对 active memory evidence 视为 `mutable_current`。

验收：

- Memory 不能绕过 EvidenceRef 直接进入 prompt。
- 只作为背景提示的 memory 不影响 replay_policy。
- 直接影响 tool input 的 memory 必须出现在 evidence_refs_json。
- 高风险动作不能只依赖 memory。

#### 10.3.6 Memory 与 EvidenceWatch 联动

开发任务：

- 实现 `ai_agent_memory_evidence_links`。
- MemoryManager 通过现有 `ai_agent_evidence_watches` 注册关联 scenario/testcase/environment/report/manifest/document。
- `scenario.updated / testcase.updated / environment.updated / manifest.changed / document.updated` 触发 MemoryStalenessWorker。
- stale event 更新 memory.stale_score 或 status=needs_revalidation。

验收：

- 不重复实现一套 Memory 专用外部事件监听。
- EvidenceWatch stale event 能级联到关联 memory。
- environment.updated 关联 memory 在 high-risk profile 中被过滤。

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

### 10.5 监控指标

P0 指标：

```text
tool_call_uncertain_total
tool_call_reconcile_success_total
tool_call_reconcile_manual_total
tool_call_orphan_recovered_total
tool_call_duplicate_blocked_total
approval_superseded_total
approval_epoch_conflict_total
permission_revoked_before_execution_total
backend_contract_unsupported_total
migration_block_open_total
outbox_publish_lag_ms
```

P1 指标：

```text
context_degraded_total
context_full_evidence_required_total
root_cause_rule_missing_total
same_failure_no_progress_total
memory_contradiction_total
memory_used_active_policy_total
memory_high_risk_blocked_total
memory_needs_revalidation_total
memory_bypassed_evidence_ref_total
checkpoint_freshness_failed_total
backend_capability_degraded_total
```

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
POST /api/v1/agents/runs
GET  /api/v1/agents/runs/{run_id}
GET  /api/v1/agents/runs/{run_id}/events
POST /api/v1/agents/runs/{run_id}/cancel
POST /api/v1/agents/runs/{run_id}/resume
POST /api/v1/agents/runs/{run_id}/reconcile
```

### 11.2 ToolCall API

```text
GET  /api/v1/agents/tool-calls/{tool_call_id}
POST /api/v1/agents/tool-calls/{tool_call_id}/approve
POST /api/v1/agents/tool-calls/{tool_call_id}/reject
```

### 11.3 Snapshot API

```text
GET /api/v1/agents/runtime-snapshots/{snapshot_id}
```

### 11.4 Memory API

```text
GET   /api/v1/agents/memories
POST  /api/v1/agents/memories
PATCH /api/v1/agents/memories/{memory_id}
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
Reconcile backoff 不造成风暴
Approval 批量 expire 不造成锁热点
SSE 高并发下可重放
故障注入覆盖率达标
监控 dashboard 完整
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

只有满足以上条件，才允许从 `read_only / draft_only / execution_record` 灰度扩大到 `business_create`。
