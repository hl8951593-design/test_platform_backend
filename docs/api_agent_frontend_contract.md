# Agent 前端接口契约

状态：前端接入契约方案
最后核验：2026-06-30

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
| `GET` | `/agents/skills` | 查询 Agent Skill 元数据目录 |

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

### 3.1.2 Agent Skill Catalog

| method | path | purpose |
| --- | --- | --- |
| `GET` | `/agents/skills` | Read the Codex-style Agent Skill catalog metadata available to the backend runner |

Response data:

```text
AgentSkillRead[] = [{ name, description }]
```

Only public metadata is returned. `SKILL.md` bodies, Skill-local private prompt resources, and routing-only fields such as `triggers`, `guard_*`, and `routing_*` remain backend-only prompt/routing material and must not be fetched or rendered by the frontend as user-visible instructions. The backend runner uses a two-level Codex-style loading model:

- The system prompt includes a stable skill catalog generated from `app/agent_skills/*/SKILL.md` `name` and `description` frontmatter.
- For each run, `AgentSkillRegistry.select_for_intent(intent)` injects only the relevant skill bodies into the model context.
- Intent matching uses each Skill's own frontmatter `triggers`; narrow guard pre-checks, unsupported capability guards, tool-required routing, and required follow-up tool repair may use private `guard_*` / `routing_*` lists such as `guard_unsupported_capability`, `routing_requires_tool`, and `routing_required_tool_after_success`. Required follow-up rules can also declare backend-private `intent_markers`, so a broad Skill trigger like "scenario" does not force `scenario.compose_draft` for read-only project-context questions such as "whether an existing scenario exists". Adding or adjusting a Skill route should not require editing the central runner prompt or Python phrase table.
- Narrow classifier prompts and guard final messages can live in Skill-local private resource files, for example `scenario-composition/save-intent-classifier.md` and `scenario-composition/unsupported-save-message.md`; these resources are loaded only by backend guard code and never by the frontend catalog.
- Current built-in skills are `agent-runtime-operations`, `ai-skill-runtime-governance`, `api-definition-import`, `api-error-contract-debugging`, `assertion-extractor-binding`, `batch-execution-scheduling`, `browser-capture-analysis`, `ci-release-integration`, `data-privacy-redaction`, `dataset-parameterization`, `defect-triage`, `environment-config-management`, `execution-diagnosis`, `general-testing-answer`, `http-test-case-design`, `media-evidence-management`, `migration-compatibility-planning`, `mock-service-virtualization`, `notification-alerting-config`, `project-context`, `project-permission-admin`, `report-archive-export`, `report-summary`, `scenario-composition`, `security-auth-testing`, `test-asset-lifecycle`, `test-plan-management`, `visual-flow-design`, and `websocket-test-case-design`.
- The frontend may show the catalog in diagnostics or capability panels, but normal conversation behavior is still driven by `/agents/runs` and SSE events.

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

Normal `POST /agents/runs` conversations start the backend `AgentConversationRunner` after `run.started`; MySQL and file-backed SQLite both start the background worker. Only in-memory SQLite test databases skip the worker to avoid cross-thread test isolation issues. If the frontend sees only `run.queued/run.started` plus heartbeat, call `/events/snapshot` and `/agents/model-health` with `live=true`; absence of `model.started` means the runner did not start. If an active `queued/running` run has no new EventStore event for longer than `AGENT_RUN_STALE_TIMEOUT_SECONDS` (default 900s), backend read paths mark it `failed` and append `run.failed(error_code=agent_run_stale_worker_lost)` so the UI must stop the thinking state and show a recoverable backend interruption. If `scripts/agent_conversation_e2e_check.py` succeeds for the same project/user but the UI still has no assistant bubble, the backend has produced a normal reply and the remaining issue is likely frontend stream parsing, cursor recovery, auth headers, or rendering state.

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

后端在当前 run 调用模型前会按预算组装同一 conversation 的历史消息。历史较长时，Runner 会把较早轮次压成一个 system 摘要、保留最近若干轮，并写入 `context.history_compacted` 事件，payload 包含 `strategy=summarize_older_keep_recent`、压缩前后估算 token、保留/压缩轮次数等审计字段（经过统一脱敏后可能显示为 redacted）。前端可把该事件展示为调试审计状态，但不要把压缩摘要渲染成 assistant 气泡。

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
- `event_seq` 是 run 内序号，前端必须按 run 保存 cursor；如果误把其他 run 的 `Last-Event-ID/after_sequence` 带到当前 run，后端会在 cursor 大于当前 `latest_event_sequence` 时重置为 0 并重放当前 run 事件，避免连接只收到 heartbeat。
- `terminal=true` 且 `next_after_sequence >= latest_event_sequence` 时，当前 run 的事件已经追平；如果 terminal 是 stale guard 触发的 `run.failed(agent_run_stale_worker_lost)`，前端应结束 pending assistant 气泡并提示用户重试或查看 runbook，而不是继续显示“正在思考”。

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
model.stream_retrying
model.stream_interrupted
model.tool_request_detected
model.tool_request_invalid
model.tool_request_repaired
model.tool_request_repair_failed
model.tool_request_stream_suppressed
model.required_tool_missing
model.required_tool_repaired
model.required_tool_repair_failed
tool.planned
tool.running
tool.completed
tool.failed
tool.result_observed
run.completed
run.failed
```

对话事件 payload 会带有 Loop trace 字段，用于区分同一个用户问题内的多次模型调用：`iteration_id` 表示 run 内循环轮次，`model_call_id` 表示一次具体 LLM 调用，`loop_step` 表示调用阶段（例如 `assistant_response`、`tool_planning`、`tool_request_repair`、`required_tool_repair`、`final_summary`、`intent_capability_guard`）。这些旧顶层字段保持兼容；新增的 `loop_state` 是稳定嵌套 envelope，字段包括 `iteration`、`iteration_id`、`phase`、`step`，并在可得时携带 `model_call_id`、`tool_call_id`、`decision_reason`。`phase=model` 用于模型调用、工具规划、修复和最终总结，`phase=tool` 用于工具执行/观察链路，前端可优先按 `loop_state.phase + loop_state.step` 分组展示调试轨迹。`model.started`、`model.delta`、`model.markdown_normalized`、`model.completed`、`model.stream_retrying` 和 `model.stream_interrupted` 必须尽量携带同一个 `model_call_id`；`model.stream_retrying` 表示 DeepSeek stream 在首个 delta/done 之前遇到可重试错误，payload 包含 `attempt`、`max_retries`、`delay_seconds`、`error_message`，前端可作为时间线审计状态展示，不应渲染为 assistant 文本。`model.tool_request_detected`、`tool.result_observed`、`tool.failed` 等审计事件可额外携带 `tool_call_id` 与 `decision_reason`。前端不得用 `model.started` 次数判断“一个问题只调用一次 LLM”，而应按 `model_call_id + loop_step` 或 `loop_state` 展示/调试 Plan/Act/Observe/Repair/Final 的循环。

当工具闭环用满 `run.max_iterations` 且仍需要进入最终总结时，后端会在 `final_summary` 模型调用前创建 stop 用 decision ContextBuild 并写入 `loop.observed`，RootCause 为 `RC_MAX_ITERATIONS`、`next_action=stop`、`mitigation_action=human_review_or_extend_limit`；`observation_json.source=max_iteration_guard`，并记录 `max_iterations`、`current_iteration`、`final_summary_iteration` 与 `tool_call_ids`。该事件属于 Resource / Limit 审计轨迹，不渲染为 assistant 气泡；最终用户可见回复仍以后续 `model.delta`、`model.markdown_normalized`、`model.completed.content` 和 `run.completed.result.message` 为准。前端可在 timeline/Runbook 中展示该 stop decision，但不应把 `final_summary` 的额外 `model.started` 当成新用户轮次。

`model.delta` 的 payload 使用 `content` 字段传输可展示的 assistant 增量文本；普通自然语言回复会在 DeepSeek stream 尚未结束时实时写入 EventStore/SSE，不需要等 `model.completed`。后端会立即写入首个可见 delta，随后对极小模型碎片做低延迟微批，减少每 token 一次数据库事务；因此一个 `model.delta.content` 可能包含一个或多个模型小片段，前端只需按到达顺序追加 content。涉及项目实时事实、场景组合、保存动作或其他平台工具规划的轮次，后端会先静默收完整模型输出并解析工具请求，再决定是否发出用户可见 delta，避免把内部 `agent_tool_request` JSON 或候选分析渲染给用户；如果静默规划轮最终不是工具请求而是可见自然语言，后端只补发一个合并后的 `model.delta`，避免长文本按 token 回放造成 SSE 和 EventStore 压力。若模型在自然语言中混入一个完整 fenced `agent_tool_request`，后端会写入 `model.tool_request_invalid`，优先本地剥离并规范化轻微 schema 偏差，再写入 `model.tool_request_repaired(repair_strategy=salvaged_fenced_tool_request)`；其他非法格式才调用一次 LLM 修复。若已检测到工具块并抑制实时输出，会写入 `model.tool_request_stream_suppressed` 审计事件。SSE 对 `queued/running` run 使用短轮询以降低 EventStore 到浏览器的传播延迟，非活跃状态保持普通轮询和 heartbeat。软件测试领域的通用问答也是普通自然语言回复：例如测试理论、用例设计、接口/WebSocket 测试、断言、测试数据、缺陷定位、回归策略、CI 和报告解读等不需要读取项目实时事实或创建平台对象的问题，可以没有 ToolCall，前端直接按 assistant 气泡展示。后端要求所有用户可见自然语言回复遵守 GitHub Flavored Markdown，并在完成前校准最终文本：`model.completed.content` 与 `run.completed.result.message` 都是规范化后的 Markdown，表格行不会以 `| |` 方式挤在同一行。若后端发现模型流式内容需要修复，会在 `model.completed` 前写入 `model.markdown_normalized`，payload 包含 `content` 与 `replace_content=true`；前端应使用该 `content` 替换当前 assistant 气泡，而不是追加。`model.completed` 的 payload 使用 `content` 字段记录本轮模型完整输出，并可附带 `provider`、`model`、`finish_reason`、`usage`；若 DeepSeek 已返回部分内容后流式连接中断，后端写入 `model.stream_interrupted`，并尽量用已收到的 partial content 继续解析工具或生成可见结果，避免 UI 空白。工具执行完成后，后端会把工具结果回灌给模型，最终自然语言回复仍通过后续实时 `model.delta`、`model.markdown_normalized` 和 `run.completed.result.message` 展示。

场景组合工具链当前采用 query-first：`scenario-composition/SKILL.md` 通过私有 `routing_required_tool_after_success` 声明 `testcase.query_project_cases -> scenario.compose_draft` 的 follow-up 规则，`scenario.compose_draft` 的 `ToolSpec` 通过后端私有 `required_successful_tool_before` 声明执行前必须已有成功 query 结果。如果模型在同一 run 内尚无成功的 `testcase.query_project_cases` 结果时直接请求 `scenario.compose_draft`，后端会创建可审计 ToolCall，但在执行前阻断并写入 `tool.failed`、`tool.result_observed`，`error_code=scenario_compose_requires_case_query`；同时后端会绑定一个修复用 decision ContextBuild 并写入 `loop.observed`，RootCause 为 `RC_TOOL_PREREQUISITE_MISSING`、`next_action=repair`，`observation_json` 记录 `blocked_tool`、`required_tool`、`tool_call_id` 与错误码。前端应将这些事件展示为 ToolCall 错误/纠正状态和调试审计轨迹，并继续等待后续模型按工具结果重新规划，不要把该错误或 `loop.observed` 渲染成最终 assistant 回复，除非 run 已进入 terminal failed。若查询用例成功且存在候选用例，但模型没有继续调用 `scenario.compose_draft` 而输出自然语言分析，后端只有在用户目标命中 follow-up 规则的 `intent_markers`（例如生成/创建/组合/执行场景、场景草稿、dry-run、数据集/参数化）时才写入 `model.required_tool_missing`，payload 包含 `after_tool` 与 `required_tool`；同时后端会绑定修复用 decision ContextBuild 并写入 `loop.observed`，RootCause 为 `RC_REQUIRED_TOOL_FOLLOWUP_MISSING`、`next_action=repair`，`observation_json` 记录 `after_tool`、`required_tool` 与内容预览，然后进行一次静默修复。修复成功写入 `model.required_tool_repaired` 后继续 ToolCall 生命周期，修复失败写入 `model.required_tool_repair_failed`。纯项目上下文、资源盘点或“是否已有场景”这类只读问题可以在 `project.read_context` / `testcase.query_project_cases` 后直接完成，不应因出现“场景”二字被前端视为漏调用 compose。

当任意成功 ToolCall 的输出包含 `warnings`、`issues`、`diagnostics`、`errors` 或 `valid=false` 时，后端会通过 `ToolResultPolicy` 在工具结果回灌消息中加入通用工具结果质量闭环规则；按工具推荐的修复路径来自对应 `ToolSpec` 的后端私有 `tool_result_repair_guidance`，而不是策略类里的工具名分支，且该字段不进入 `ToolSpec.to_json()`、模型初始工具清单或前端契约。模型应先把问题分为可自动修复项、需要用户输入/外部配置的阻断项和待继续判断项：硬编码业务字段、未动态绑定、提取器路径、断言 expected、数据集变量、schema/type/format 校验等可修复项应触发下一次安全工具调用，例如复用 `ai_skill.run_draft` 的 `input.extra_requirements`、再次 `testcase.validate_schema` 或重新 `scenario.compose_draft`；鉴权令牌、账号密码、密钥、审批或没有平台来源的私有输入才作为阻断项交给用户。如果 ToolCall 本身失败，但错误属于输入、schema、validation、草稿结构或字段格式问题，后端同样会在工具结果回灌中加入失败修复闭环，要求模型修正参数并重试安全工具，而不是直接把 Pydantic/schema 错误交给用户。前端可能看到同一个 run 中连续多个同类 ToolCall，这是正常的修复闭环，不应当成重复提交错误；但如果同一工具连续两次以相同 `error_code` 与 `error_message` 失败，后端会绑定 stop 用 decision ContextBuild 并写入 `loop.observed`，RootCause 为 `RC_NO_PROGRESS_PURE`、`next_action=stop`、`observation_json.source=tool_result_no_progress_guard`，随后写入 `run.failed(error_code=agent_repair_no_progress)`，前端应结束 pending assistant 气泡并在 timeline/Runbook 展示该 repair no-progress 状态。工具结果后的最终用户回复默认受预算约束：只总结已完成、已自动修复/验证、剩余阻断项和下一步；完整步骤、草稿结构、原始 warning 和长 JSON 以 ToolCall 详情、run summary 或报告详情为准，前端不应依赖 assistant 气泡承载全部结构化细节。

如果模型输出的工具请求格式不合法，后端会写入 `model.tool_request_invalid`，并绑定修复用 decision ContextBuild 写入 `loop.observed`，RootCause 为 `RC_TOOL_REQUEST_FORMAT_INVALID`、`next_action=repair`，`observation_json` 记录 `model_call_id`、错误摘要和内容预览；随后后端让模型进行一次格式修复。修复成功写入 `model.tool_request_repaired` 后继续进入 `model.tool_request_detected` 和 ToolCall 生命周期。修复失败写入 `model.tool_request_repair_failed`，run 会进入 failed。前端可把这些事件展示为审计状态，不渲染为 assistant 气泡。

当用户疑似要求保存、持久化、发布或创建正式场景，但当前 ToolRegistry 没有 `scenario.save/create/persist` 类工具时，后端不会仅凭关键词短路，而是由 `scenario-composition/SKILL.md` 的后端私有 `guard_unsupported_capability` 规则声明预检查关键词、缺失工具集合、分类 prompt、分类 JSON 字段、最终消息资源和 `completion_source`。Runner 只解释这条 Skill 规则：先用结构化意图分类判断用户是否真的要求把场景持久化为正式实体，分类 prompt 和最终 guard 回复都来自 Skill 私有资源文件，不写在 Runner 主 prompt 或 Python 消息常量中。只有分类结果为需要正式保存时，才会用 `unsupported_scenario_save_guard` 直接完成 run，说明当前只能生成草稿或 dry-run，不能假装已保存，也不会重新调用 `scenario.compose_draft` 冒充保存结果。若用户明确说“不要保存”“不保存”“仅生成草稿”等，run 仍应进入正常 query-first 场景组合链路。前端按普通 assistant 回复展示 guard 结果即可。

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

后端会稳定构建 Agent 系统提示中的 ToolRegistry 清单：工具按名称排序，工具 JSON 使用固定字段排序和紧凑分隔符序列化。这样同一 runtime hash 下的多轮请求尽量保持系统提示/工具清单前缀一致，便于模型服务侧复用 prompt/cache；前端只消费 snapshot/hash 和事件流，不需要自行重排工具清单。

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

`report.read_summary` 是只读 ToolCall。输入支持 `project_id`、可选 `source_type`（`plan` 或 `flow`）、`status`、`environment_id` 和 `page_size`（1-20）；`output_json_redacted` 包含 `filters`、`report_count`、`returned_report_count`、`status_counts`、`returned_case_totals`、`latest_reports` 和最多 3 条 `failure_reports`。前端仍应把它当作通用 ToolCall 详情输出，不新增独立 report-summary API 事实源。

`policy_reason_json.policy_context` 是 ToolPolicyResolver 对本次 ToolCall 的冻结策略 envelope：包含 `policy_version_hash`、tool name/version、base/resolved side effect、base/resolved replay policy、`approval_policy`、`approval_required`、`approval_required_reason`、active/volatile/frozen policy evidence 计数、`mixed_volatile_frozen` 与 `policy_hash`。前端可在 ToolCall 诊断面板展示该摘要，用于解释为什么 replay policy 被提升为 `require_revalidation`、为什么需要审批或为什么被视为安全工具；不要把它当作新的业务输入，也不要从中反推未脱敏 evidence 内容。

`policy_reason_json.execution_context` 是 ToolExecutor 在 ToolCall 成功、失败、manual intervention 或 uncertain recovery 终态写入的执行上下文 envelope：包含 `execution_context_version_hash`、tool/run/runtime snapshot 标识、worker id、`tool_status`、execution/effect state、backend contract/version/schema hash、backend effect capability、resolved side effect/replay policy、approval lineage/epoch/approved approval、input/output hash、`recovery_decision`、`error_code`、`error_message_hash` 与 `execution_context_hash`。前端可把它作为 ToolCall Detail 的执行诊断摘要，用于解释本次执行基于哪个审批 lineage、哪个后端契约、哪个效果提交状态以及哪个恢复动作；不要把它当作可重放输入，也不要展示或推断原始 input/output/evidence/error message 内容。Runbook 诊断中的 `tool_call_uncertain` 与 `backend_capability_degraded` recommendation 会在 `details.execution_context` 中附带该 envelope 的白名单摘要，便于 Runbook 面板直接展示执行 hash、worker、状态、效果提交状态、后端能力、恢复动作和错误 hash；该摘要同样不会包含原始 input/output/evidence/error message。

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

`build_metadata_json` 会包含本次决策实际命中的 Codex-style Agent Skill 摘要、冻结运行时摘要与权限上下文摘要：`selected_agent_skills` 仅暴露 Skill `name` 与 `skill_hash`，`matched_agent_skill_routing_rules` 仅暴露匹配到的 routing rule 摘要（如 `routing_required_tool_after_success` 的 `after_tool` / `required_tool` / `rule_hash`），`runtime_snapshot` 仅暴露 `snapshot_id`、runtime/tool registry/manifest/prompt/policy hash、`available_tool_names` 与 `tool_count`，`permission_context` 仅暴露 `actor_user_id`、`project_id`、`access_level`、`project_access`、`implicit_all_project_permissions`、`explicit_permission_codes`、`explicit_permission_count` 与 `permission_hash`。这些字段用于解释 required-tool 修复、工具前置阻断、权限相关停止决策为何发生，并确认当时可用工具/策略/权限版本；不暴露私有 frontmatter 原文、Skill 正文、私有 prompt 资源、完整工具 schema、用户资料或完整授权表。前端可在诊断面板展示这些字段；不要把它渲染为 assistant 气泡。

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

`GET /agents/metrics` 与 dashboard 的 `metrics` 字段会暴露 Runtime 修复/停止类 LoopObservation 聚合指标，包括 `tool_prerequisite_missing_total`、`tool_request_format_invalid_total`、`required_tool_followup_missing_total`、`max_iterations_total` 与 `same_failure_no_progress_total`。这些指标用于工作台健康度、Runbook/运营排查和趋势展示，不代表新的 assistant 消息；`metrics_catalog_complete.details.required_metric_keys` 会同时包含这些 key，前端可用该 check 判断后端是否漏导出指标。

`GET /agents/runs/{run_id}/runbook` 会把上述 Runtime 修复/停止类 LoopObservation 归入 `agent_runtime_loop_repair` recommendation。前端可在 Runbook 面板展示 `details.stop_action_reason`、`details.root_cause_rule_id`、`details.mitigation_action` 和 `details.observation_id`，并把 `action=GET /api/v1/agents/runs/{run_id}/loop-observations` 作为跳转到 loop 诊断详情的安全入口；这类 recommendation 是运维/调试建议，不应渲染成 assistant 气泡。对于需要从 ToolCall 恢复的 `tool_call_uncertain` 和 `backend_capability_degraded`，前端可优先展示 `details.execution_context` 的白名单摘要，再通过 `tool_call_id` 打开完整 ToolCall Detail。

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

`runtime_contracts` 除基础 run/events/snapshot/summary/actions/history/transcript/export 入口外，还固定声明 `tool_execution_context=AgentToolCall.policy_reason_json.execution_context`、`runbook_execution_context_summary=AgentRunbookRecommendation.details.execution_context` 与 `runbook_execution_context_summary_fields` 白名单；`diagnostics` 除 model health、launch/completion audit、conversation smoke 和 E2E 脚本外，还固定提供 `tool_call_detail=GET /api/v1/agents/tool-calls/{tool_call_id}` 与 `runbook_diagnosis=GET /api/v1/agents/runs/{run_id}/runbook`。前端或交付验收可以先读 completion audit 判断这条执行诊断链是否属于后端完成边界，再跳转 ToolCall Detail/Runbook 查看完整诊断。

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
