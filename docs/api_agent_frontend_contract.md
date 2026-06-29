# Agent 前端接口契约

状态：前端接入契约方案
最后核验：2026-06-27

本文档用于指导另一个 React 19 + Vite + TypeScript 前端项目接入 Harness Loop Agent 后端。接口基础路径沿用现有前端技术文档：

```text
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

所有受保护接口必须通过现有 `requestWithAuth` 或同等封装自动携带 `Authorization`。页面组件不得直接拼接鉴权头。

## 1. 通用响应

普通 JSON 接口统一返回：

```ts
type ApiEnvelope<T> = {
  code: number;
  message: string;
  data: T;
};
```

SSE 接口 `GET /agents/runs/{run_id}/events` 返回 `text/event-stream`，不使用 `ApiEnvelope`。

## 2. 前端建议封装

| 文件 | 职责 |
| --- | --- |
| `src/api/agents.ts` | `/agents/*` 接口函数 |
| `src/api/agentStream.ts` | `fetch + ReadableStream` SSE parser |
| `src/types/agents.ts` | 后端契约类型 |
| `src/pages/AgentPage.tsx` | 页面容器 |
| `src/components/agent/*` | Agent 工作台组件 |
| `src/pages/AgentPage.test.tsx` | 页面集成测试 |
| `src/api/agents.test.ts` | 接口封装和 SSE parser 测试 |

## 3. 核心接口清单

### 3.1 Capabilities

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/capabilities` | 初始化状态枚举、工具目录、能力开关 |

### 3.1.1 Model Health

| method | path | purpose |
| --- | --- | --- |
| `GET` | `/agents/model-health` | Read Agent model provider configuration and optionally run a minimal live DeepSeek stream probe |
| `POST` | `/agents/conversation-smoke` | Admin-only full Agent conversation smoke: create run, execute runner, return summary and event chain |

Query:
```text
live=false by default; live=true runs a tiny AIService.chat_stream probe and is admin-only.
```

`AgentModelHealthRead` fields:
```text
provider,configured,base_url,default_model,live,reachable,latency_ms,first_delta_received,completed,model,finish_reason,error_code,error_message,checked_at
```

The response never includes the DeepSeek API key. Frontend can call `GET /agents/model-health` during Agent page boot to show whether the backend model provider is configured. Admin-only `live=true` is for debugging the "run created but no assistant reply" path: `configured=false` means the key is missing, `reachable=false` means the provider call failed, and `first_delta_received=false` means the provider did not stream assistant content during the probe.

`POST /agents/conversation-smoke` accepts:
```text
project_id,intent,max_iterations
```

It returns `AgentConversationSmokeRead`:
```text
project_id,run_id,conversation_id,status,completed,first_delta_received,assistant_visible,assistant_message,error_code,error_message,event_types,latest_event_sequence,run_summary,latency_ms,generated_at
```

This route is admin-only and creates a real Agent Run/EventStore record. Use it when `model-health` is reachable but the full Agent page still does not show a reply.

Backend maintainers can also run the normal-user E2E diagnostic script against the real configured database and DeepSeek provider before blaming frontend streaming:

```powershell
.\.venv\Scripts\python.exe scripts\agent_conversation_e2e_check.py --project-id 1 --user-id 1 --intent "Reply exactly: Agent e2e ok." --timeout-seconds 90
```

The script succeeds only when live health is reachable, a normal `POST /agents/runs` starts the runner, EventStore receives `model.started` plus at least one `model.delta`, the run reaches `run.completed`, and summary returns `assistant_visible=true`. It never prints the DeepSeek API key.

### 3.2 Run 和流式事件

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/runs` | 按项目、conversation、status 查询 run 历史 |
| `POST` | `/agents/runs` | 创建 Agent Run |
| `GET` | `/agents/runs/{run_id}` | 校准 run 状态 |
| `GET` | `/agents/runs/{run_id}/summary` | 聚合右侧 RunInspector 摘要 |
| `GET` | `/agents/runs/{run_id}/actions` | 聚合右侧操作按钮状态 |
| `POST` | `/agents/runs/{run_id}/cancel` | 停止 run |
| `POST` | `/agents/runs/{run_id}/resume` | 从 checkpoint 恢复 |
| `POST` | `/agents/runs/{run_id}/reconcile` | 触发 reconcile |
| `GET` | `/agents/runs/{run_id}/events` | SSE 事件流 |
| `GET` | `/agents/runs/{run_id}/events/snapshot` | 非流式事件快照和 cursor 状态 |
| `GET` | `/agents/runs/{run_id}/events/replay-audit` | 断线重放审计 |

`AgentRunRead` 字段：

```text
run_id,project_id,user_id,conversation_id,intent,status,current_iteration,current_step_index,max_iterations,runtime_snapshot_id,last_checkpoint_id,last_event_sequence,migration_block_count,blocking_tool_call_ids_json,result_json,error_code,error_message,started_at,completed_at,created_at,updated_at
```

`GET /agents/runs/{run_id}/summary` 返回 `AgentRunSummaryRead`，用于 Codex 风格右侧 RunInspector 的轻量聚合展示。它只读聚合 run、最新 EventStore 事实、ToolCall 计数、Approval 计数、MigrationBlock 计数、Memory usage 计数、assistant 展示元数据和按钮状态；该路由与 `GET /agents/runs/{run_id}` 一样必须按 run 所属项目校验访问权限。

`AgentRunSummaryRead` 字段：
```text
run,assistant_message,assistant_visible,completion_source,model_invoked,model,finish_reason,usage,event_count,latest_event_sequence,latest_event_types,tool_call_count,pending_tool_call_count,approval_count,pending_approval_count,migration_block_count,open_migration_block_count,memory_usage_count,blocking_tool_call_ids,terminal,can_cancel,can_resume,updated_at
```

前端约定：
- 只有 `assistant_visible=true` 时才渲染 `assistant_message` 为 assistant 回复；smoke/debug run 会返回 `assistant_visible=false`。
- `assistant_message` 是后端完成前校准过的 GitHub Flavored Markdown，可直接交给 Markdown renderer；若包含表格，表头、分隔行和每条数据行都已独占一行。
- `can_cancel`、`can_resume`、`terminal` 用于 RunInspector 操作按钮状态。
- `latest_event_sequence` 与 `latest_event_types` 只做轻量新鲜度摘要，完整时间线仍以 SSE 为准。

`GET /agents/runs/{run_id}/actions` 返回 `AgentRunActionStateRead`，用于右侧操作区、Runbook 入口和待办按钮状态：
```text
run_summary,actions,primary_action_ids,blocked_reasons,generated_at
```

每个 action 字段：
```text
action_id,label,method,path,enabled,reason,severity,resource_ids,details
```

固定 `action_id` 顺序：
```text
view_summary,stream_events,cancel_run,review_approvals,resume_run,reconcile_run,resolve_migration,open_runbook
```

前端约定：
- 只用 `enabled` 决定按钮是否可点击；禁用说明显示 `reason`。
- `primary_action_ids` 是后端给出的当前优先操作顺序，例如 pending approval 时优先 `review_approvals`，uncertain ToolCall 时优先 `reconcile_run`。
- `resource_ids` 放当前 action 关联的 approval、tool_call 或 migration block id；详情列表仍按对应接口 hydrate。
- `resume_run.details.blocking_tool_call_ids` 会合并 Run 阻断字段和 pending approval 对应的 `tool_call_id`；`pending_approval_tool_call_ids` 可用于把审批卡片定位回具体 ToolCall。

`POST /agents/runs` `auto_complete` is backend smoke/debug only. Normal frontend conversations must omit it or send `false`. When `auto_complete=true`, the backend does not call the model and `run.completed.result` contains `completion_source=smoke_auto_complete`, `model_invoked=false`, and `assistant_visible=false`; frontend must not render this as a real assistant reply.

Normal `POST /agents/runs` conversations start the backend `AgentConversationRunner` after `run.started`; MySQL and file-backed SQLite both start the background worker. Only in-memory SQLite test databases skip the worker to avoid cross-thread test isolation issues. If the frontend sees only `run.queued/run.started` plus heartbeat, call `/events/snapshot` and `/agents/model-health` with `live=true`; absence of `model.started` means the runner did not start. If `scripts/agent_conversation_e2e_check.py` succeeds for the same project/user but the UI still has no assistant bubble, the backend has produced a normal reply and the remaining issue is likely frontend stream parsing, cursor recovery, auth headers, or rendering state.

`POST /agents/runs/{run_id}/resume` 返回 `AgentRunResumeRead`：

```text
run,resumed,checkpoint_freshness,scheduled_tool_call_ids,executed_tool_call_ids
```

当 run 因审批进入 `needs_human`，且阻断 ToolCall 已被 approve 后，resume 会先执行已批准的阻断工具，把执行成功的 id 放入 `executed_tool_call_ids`，再继续生成最终 assistant 回复。前端应重新打开或继续监听该 run 的 SSE，按 `tool.result_observed`、后续 `model.delta` 和 `run.completed` 更新时间线。

`POST /agents/runs/{run_id}/cancel` 写入 `run.cancelled` 后，后端对话 runner 会在模型 stream、工具请求 repair、ToolCall 创建前和 final summary 结束后重新读取 terminal 状态；如果取消已经生效，后续不会再写 `run.completed` 覆盖 cancelled。前端 Stop 后仍应继续监听 SSE 或刷新 `/actions`，以服务端 terminal 状态为准。

### 3.2.1 Conversation 历史

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/conversations?project_id=...` | 查询服务端 conversation 列表 |
| `GET` | `/agents/conversations/{conversation_id}/runs?project_id=...` | 查询单个 conversation 下的 run 列表 |
| `GET` | `/agents/conversations/{conversation_id}/transcript?project_id=...` | 恢复 Codex 式多轮 transcript |
| `GET` | `/agents/conversations/{conversation_id}/export?project_id=...` | 导出 conversation 调试包 |

`AgentConversationRead` 字段：

```text
conversation_id,project_id,title,run_count,latest_run_id,latest_run_status,created_at,updated_at
```

`AgentConversationTranscriptRead` 字段：
```text
conversation,turns,generated_at
```

`conversation` 使用 `AgentConversationRead` 字段；`turns` 按 run 创建时间升序返回 `AgentRunSummaryRead[]`。前端刷新页面、切换设备或从左侧历史打开会话时，应优先调用 transcript 恢复 user prompt、assistant 最终回复、run 状态和右侧 badge；SSE 仍只负责当前活跃 run 的实时增量。

`GET /agents/conversations/{conversation_id}/export` 返回 `AgentConversationExportRead`，用于下载或调试 Codex 式 conversation：
```text
conversation,turns,events_by_run_id,tool_calls_by_run_id,approvals_by_run_id,migration_blocks_by_run_id,export_format,generated_at,derived_from
```

前端约定：
- `events_by_run_id` 按 `event_seq` 升序保存每个 run 的 EventStore 事件。
- `tool_calls_by_run_id`、`approvals_by_run_id`、`migration_blocks_by_run_id` 只包含对应 run 的派生事实；敏感字段仍使用后端 redacted 字段。
- `export_format=agent_conversation_export_v1`，可作为下载文件格式版本。

创建 run 时如果前端不传 `conversation_id`，后端会生成 `agent-conv-*` 并在 `AgentRunRead.conversation_id` 返回。继续多轮对话时，前端必须复用该值；后端会把同 conversation 最近已完成 run 的 `intent` 与 `result_json.message` 作为模型上下文。

`AgentEventRead` 字段：

```text
event_seq,event_type,payload_json,created_at
```

`GET /agents/runs/{run_id}/events/snapshot?after_sequence=...&limit=...` 返回 `AgentRunEventSnapshotRead`，用于前端调试、断线恢复前校准、或无法直接观察 ReadableStream 时判断后端是否已经写入 `model.delta`。它不是新的事实源，只是 EventStore 的 JSON 快照：
```text
run,events,after_sequence,event_count,latest_event_sequence,next_after_sequence,terminal,generated_at
```

前端约定：
- `events` 与 SSE 使用同一个 `AgentEventRead` 结构，并按 `event_seq` 升序返回。
- 下一次轮询或重连可以使用 `next_after_sequence` 作为 cursor。
- `terminal=true` 且 `next_after_sequence >= latest_event_sequence` 时，当前 run 的事件已经追平。

SSE data payload 必须至少包含：

```text
schema_version,run_id,project_id,event_seq,event_type,occurred_at
```

前端必须处理的对话生成事件：

```text
model.started
memory.context_injected
model.delta
model.completed
model.markdown_normalized
model.tool_request_detected
model.tool_request_invalid
model.tool_request_repaired
model.tool_request_repair_failed
tool.planned
tool.running
tool.completed
tool.failed
tool.result_observed
run.completed
run.failed
```

`model.delta` 的 payload 使用 `content` 字段传输可展示的 assistant 增量文本；普通自然语言回复会在 DeepSeek stream 尚未结束时实时写入 EventStore/SSE，不需要等 `model.completed`。后端要求所有用户可见自然语言回复遵守 GitHub Flavored Markdown，并在完成前校准最终文本：`model.completed.content` 与 `run.completed.result.message` 都是规范化后的 Markdown，表格行不会以 `| |` 方式挤在同一行。若后端发现模型流式内容需要修复，会在 `model.completed` 前写入 `model.markdown_normalized`，payload 包含 `content` 与 `replace_content=true`；前端应使用该 `content` 替换当前 assistant 气泡，而不是追加。`model.completed` 的 payload 使用 `content` 字段记录本轮模型完整输出，并可附带 `provider`、`model`、`finish_reason`、`usage`。当模型输出受控工具请求时，后端会先缓冲疑似 `agent_tool_request` 内容，写入 `model.tool_request_detected` 后通过 `tool.*` 事件展示 ToolCall 生命周期；这类工具请求 JSON 属于审计内容，前端不要把它渲染成 assistant 对话气泡。工具执行完成后，后端会把工具结果回灌给模型，最终自然语言回复仍通过后续实时 `model.delta`、`model.markdown_normalized` 和 `run.completed.result.message` 展示。

场景组合工具链固定为 query-first：当用户要求创建、生成或组合测试场景时，`AgentConversationRunner` 会要求模型先调用 `testcase.query_project_cases` 读取当前项目 HTTP/WebSocket 用例，再使用返回的真实 case id 调用 `scenario.compose_draft`。如果模型在同一 run 内尚无成功的 `testcase.query_project_cases` 结果时直接请求 `scenario.compose_draft`，后端会创建可审计 ToolCall，但在执行前阻断并写入 `tool.failed`、`tool.result_observed`，`error_code=scenario_compose_requires_case_query`；前端应将其展示为 ToolCall 错误/纠正状态，并继续等待后续模型按工具结果重新规划，不要把该错误渲染成最终 assistant 回复，除非 run 已进入 terminal failed。

如果模型输出的工具请求格式不合法，后端会写入 `model.tool_request_invalid`，并让模型进行一次格式修复；修复成功写入 `model.tool_request_repaired` 后继续进入 `model.tool_request_detected` 和 ToolCall 生命周期。修复失败写入 `model.tool_request_repair_failed`，run 会进入 failed。前端可把这些事件展示为审计状态，不渲染为 assistant 气泡。

对话型 run 在调用模型前会用 `normal_plan_v1` 检索项目 Memory，并以 `conversation_context` 注入模型上下文；命中时事件流会出现 `memory.context_injected`，payload 包含 `profile_name`、`usage_role`、`active_for_policy=false`、`memory_ids`、`memory_versions` 和 `count`。该事件是审计/时间线提示，不渲染为 assistant 气泡；详情可用 `GET /agents/memory-usage-events?run_id={run_id}` 查询。

`run.completed.result.message` 是刷新后校准最终回复的权威字段；有工具调用时，`run.completed.result.tool_calls` 会包含本次 run 内模型驱动 ToolCall 的摘要，其中可能包含被 harness guard 阻断的失败 ToolCall，前端应按 `status/error_code` 区分纠正过程和最终结果。

### 3.3 Runtime Snapshot

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/runtime-snapshots/{snapshot_id}` | 查看冻结运行时契约、工具目录和策略 |

`AgentRuntimeSnapshotRead` 字段：

```text
snapshot_id,project_id,created_by,runtime_hash,tool_registry_hash,manifest_bundle_hash,prompt_bundle_hash,policy_version_hash,tools_json,manifests_json,adapters_json,policies_json,created_at
```

### 3.4 ToolCall

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/tool-calls/{tool_call_id}` | 查看工具输入、输出、审批、reconcile 信息 |
| `POST` | `/agents/tool-calls/{tool_call_id}/approve` | 审批工具调用 |
| `POST` | `/agents/tool-calls/{tool_call_id}/reject` | 拒绝工具调用 |

`AgentToolCallRead` 字段：

```text
tool_call_id,run_id,step_index,attempt_index,runtime_snapshot_id,tool_name,tool_version,schema_hash,manifest_hash,idempotency_scope,idempotency_key,base_side_effect_class,resolved_side_effect_class,base_replay_policy,resolved_replay_policy,policy_reason_json,status,execution_phase,effect_submission_state,input_hash,input_json_redacted,evidence_refs_json,policy_evidence_refs_json,audit_evidence_refs_json,evidence_mutability_summary_json,decision_context_build_id,output_hash,output_json_redacted,required_permissions_json,permission_snapshot_json,approval_required,approval_scope_hash,approval_lineage_id,approval_epoch,approved_approval_id,approved_by,approved_at,backend_name,backend_operation,backend_contract_version,backend_request_schema_hash,backend_output_schema_hash,reconcile_contract_version,result_adapter_version,backend_effect_capability,recovery_decision,error_code,error_message,current_approval,approval_lineage,recent_reconcile_attempts,created_at,updated_at
```

Approval decision 请求必须携带 CAS 字段：

```text
input_hash,runtime_snapshot_id,resource_scope_hash,approval_lineage_id,approval_epoch,reason?
```

### 3.5 ContextBuild 和 LoopObservation

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/agents/runs/{run_id}/context-builds` | 创建上下文构建记录 |
| `GET` | `/agents/runs/{run_id}/context-builds` | 列出 run 的上下文构建 |
| `POST` | `/agents/runs/{run_id}/loop-observations` | 记录 loop 观察 |
| `GET` | `/agents/runs/{run_id}/loop-observations` | 列出 loop 观察 |

`AgentContextBuildRead` 字段：

```text
context_build_id,run_id,iteration,step_index,build_seq,build_purpose,model_name,token_budget,estimated_input_tokens,context_degradation_level,compressed_sections_json,omitted_evidence_refs_json,required_evidence_refs_json,required_evidence_complete,decision_quality_risk,prompt_object_key,prompt_hash,build_metadata_json,created_at
```

`AgentLoopObservationRead` 字段：

```text
observation_id,run_id,iteration,step_index,decision_context_build_id,decision_context_degradation_level,iteration_context_degradation_max,required_evidence_complete_for_decision,omitted_required_evidence_refs_json,next_action,next_action_is_high_risk,stop_action_reason,stop_reasons_all_json,root_cause_primary,root_cause_rule_id,causal_chain_json,mitigation_action,observation_json,created_at
```

### 3.6 Approvals 和 Migration Blocks

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/runs/{run_id}/approvals` | 查询 run 审批列表 |
| `GET` | `/agents/runs/{run_id}/migration-blocks` | 查询 migration blocks |
| `POST` | `/agents/runs/{run_id}/migration-blocks/{block_id}/resolve` | 解决 migration block |
| `GET` | `/agents/approvals/expire-audit` | 审批过期审计 |
| `POST` | `/agents/approvals/expire` | 审批过期处理 |

### 3.7 Memory

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/memories` | memory 列表 |
| `POST` | `/agents/memories` | 创建 memory |
| `PATCH` | `/agents/memories/{memory_id}` | 更新 memory |
| `POST` | `/agents/memories/{memory_id}/validate` | 验证 memory |
| `POST` | `/agents/memories/{memory_id}/reject` | 拒绝 memory |
| `POST` | `/agents/memories/retrieve` | 检索 memory |
| `GET` | `/agents/memory-source-profiles` | source profile catalog |
| `GET` | `/agents/memory-retrieval-profiles` | retrieval profile catalog |
| `GET` | `/agents/memory-usage-events` | usage events |
| `POST` | `/agents/memory-usage-events/{usage_event_id}/feedback` | memory feedback |
| `GET` | `/agents/memory-staleness-events` | staleness events |
| `GET` | `/agents/memory-validation-events` | validation events |
| `POST` | `/agents/memory-feedback/process` | admin feedback worker |

Agent 对话 runner 自动检索 Memory 时会写入 `AgentMemoryUsageEvent`：`usage_role=conversation_context`、`retrieval_profile=normal_plan_v1`、`active_for_policy=false`。前端 Memory tab 可按 run 查询这些 usage events，并允许用户对误导/过期/有用的记忆提交 feedback。

### 3.8 Dashboard、Runbook 和上线门禁

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/dashboard` | readiness dashboard |
| `GET` | `/agents/launch-audit` | frontend integration and launch readiness audit |
| `GET` | `/agents/backend-completion-audit` | backend-owned Agent feature completion audit |
| `GET` | `/agents/metrics` | metrics snapshot |
| `GET` | `/agents/alerts` | alerts snapshot |
| `GET` | `/agents/runbooks` | runbook catalog |
| `GET` | `/agents/runs/{run_id}/runbook` | run diagnosis |
| `GET` | `/agents/release-gates` | release gate snapshot |
| `GET` | `/agents/release-gates/promotion` | promotion assessment |

`GET /agents/launch-audit?project_id=...` 返回 `AgentLaunchAuditRead`，用于前端进入 Agent 工作台前判断后端是否已经具备可联调状态。该接口不触发 live DeepSeek 调用，不暴露 API key；`project_id` 作用域下项目成员可读，不传 `project_id` 时仅 admin 可读全局审计。

字段：
```text
project_id,generated_at,ready,status,checks,model_health,dashboard,promotion,derived_from
```

固定 checks：
```text
model_provider_configured,normal_conversation_runtime_available,frontend_event_contract_available,dashboard_readiness_not_blocked,backend_repository_delivery_complete,frontend_external_scope_declared,promotion_assessment_available
```

前端约定：`ready=true` 表示后端拥有的 Agent 对话链路、SSE/snapshot/summary/actions/history/export 契约和 dashboard/release gate 输入已经可供前端联调；它不表示 L3 生产灰度已放开，`promotion.decision` 仍可能因发布策略保持 `blocked`。

`GET /agents/backend-completion-audit?project_id=...` 返回 `AgentBackendCompletionAuditRead`，用于回答“后端仓库拥有的 Codex 风格 Agent 功能是否已经开发完成”。该接口同样不触发 live DeepSeek 调用，不暴露 API key；`project_id` 作用域下项目成员可读，不传 `project_id` 时仅 admin 可读全局审计。它把对话流式生成、服务端历史、工具循环、审批恢复、Memory 注入、前端契约、观测门禁、文档同步和真实 E2E 诊断路径汇总为固定 checks。

字段：
```text
project_id,generated_at,complete,status,checks,backend_scope,launch_audit,runtime_contracts,diagnostics,derived_from
```

固定 checks：
```text
model_provider_configured,conversation_runner_streaming,server_side_conversation_history,tool_loop_and_approval_resume,memory_context_injection,frontend_contract_surface,observability_and_release_gate,backend_delivery_docs_synced,live_e2e_diagnostic_available
```

前端约定：`complete=true` 表示后端仓库范围内 Agent 对话、流式事件、工具/审批/Memory/诊断/契约已具备联调完成度；`backend_scope.frontend_delivery=external repository` 表示前端实现仍在另一个仓库交付；`launch_audit.promotion_decision=blocked` 只表示生产发布门禁仍按策略阻断，不等于后端 Agent 对话功能不可用。

### 3.9 运维审计和后台处理

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/worker-queue/audit` | WorkerQueue lease/duplicate audit |
| `POST` | `/agents/outbox/publish` | Outbox publish |
| `GET` | `/agents/events/replay-stress-audit` | event replay stress audit |
| `GET` | `/agents/fault-injections` | fault injection catalog |
| `GET` | `/agents/fault-injections/coverage` | fault coverage |
| `POST` | `/agents/fault-injections/run` | run fault injection |
| `GET` | `/agents/root-cause-rules/audit` | root cause rule governance |
| `GET` | `/agents/backend-contracts/{backend_name}/operations/{backend_operation}` | backend operation contract |

## 4. 前端禁止事项

- 不要在页面组件中直接 `fetch` 普通接口；必须封装到 `src/api/agents.ts`。
- 不要把后端 snake_case 字段改成 camelCase 后再跨组件传递，除非建立完整映射层和测试。
- 不要用原生 `EventSource` 访问需要 Authorization header 的 SSE。
- 不要忽略 approve/reject 的 CAS 字段。

## 5. 必测项

| 类型 | 用例 |
| --- | --- |
| API 封装 | 每个函数拼接正确路径、方法、query/body |
| SSE parser | 多 event、断包、heartbeat、Last-Event-ID、AbortController |
| Run 流程 | create run -> stream -> terminal -> close |
| ToolCall | event 触发详情拉取、输出展开、错误展示 |
| Approval | CAS 字段提交、409 冲突提示 stale approval |
| Approval resume | approve 后触发 resume，展示 `executed_tool_call_ids` 对应工具输出和后续 assistant 回复 |
| History | 本地 conversation index 增删改、run 校准失败降级 |
| 权限 | 403 展示无权限，不重试破坏性动作 |
| 文档同步 | 字段与本文件和 Harness `Required ... contract` 保持一致 |
