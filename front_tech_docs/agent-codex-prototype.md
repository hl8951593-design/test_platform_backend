# Agent Codex 风格前端原型

状态：原型方案
最后核验：2026-06-27

本文档面向另一个 React 19 + Vite + TypeScript 前端项目实现 `/agents` 页面。原型严格以当前后端 `/api/v1/agents/*`、两份 Harness Loop Agent 文档中的 `Required ... contract` 块和现有前端技术文档为边界，不假设未声明接口已经存在。

## 1. 原型目标

`/agents` 页面提供类似 Codex 的 Agent 工作台：

- 支持多轮对话：同一个 `conversation_id` 下连续创建多个 Agent Run。
- 支持流式传输：通过 `GET /agents/runs/{run_id}/events` 消费 SSE 事件流，并用 `Last-Event-ID` 续播。
- 支持事件快照：通过 `GET /agents/runs/{run_id}/events/snapshot` 在调试、断线恢复或流解析异常时拉取 EventStore JSON cursor。
- 支持工具调用与工具输出：从事件中的 `tool_call_id` 进入 `GET /agents/tool-calls/{tool_call_id}` 详情。
- 支持审批、取消、恢复、reconcile、migration block resolve。
- 支持历史对话：通过 `GET /agents/conversations`、`GET /agents/conversations/{conversation_id}/runs` 和 `GET /agents/runs` 从服务端恢复。
- 支持右侧环境/运行信息面板：展示项目、分支、运行状态、readiness、runbook、snapshot、memory usage。

参考图的信息架构来自 Codex 当前工作页：中间对话时间线、工具调用折叠块、右侧环境信息、底部 composer。

## 2. 页面结构

```text
/agents
┌──────────────────────────────────────────────────────────────────────────────┐
│ App 顶栏：项目选择 / 环境选择 / 用户 / 全局通知                              │
├───────────────┬──────────────────────────────────────────────┬───────────────┤
│ 会话与运行列表 │ Agent Transcript                             │ Run Inspector │
│               │                                              │               │
│ + 新会话       │  User prompt                                 │ Run summary   │
│ 搜索           │  Assistant/Agent status                       │ Snapshot      │
│ pinned filters │  Event Timeline                               │ Tool details  │
│ conversation   │  ToolCall card / output                       │ Approvals     │
│ run history    │  Approval card                                │ Memory        │
│ local drafts   │  Migration block card                         │ Runbook       │
│               │                                              │ Dashboard     │
├───────────────┴──────────────────────────────────────────────┴───────────────┤
│ Composer: prompt textarea / max_iterations / send / stop                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

布局规则：

- 默认三栏：左 280px，中间自适应，右 360px。
- 窄屏合并为：左侧抽屉、主时间线、右侧详情抽屉。
- 不做营销页，不做卡片套卡片；工作台以密集但清晰的信息操作为主。
- 工具调用、审批、migration、runbook 都是时间线内的折叠 item，右侧显示选中项详情。

## 3. 核心组件

| 组件 | 建议文件 | 职责 |
| --- | --- | --- |
| `AgentPage` | `src/pages/AgentPage.tsx` | 路由页、整体布局、当前 conversation/run 状态 |
| `AgentRunSidebar` | `src/components/agent/AgentRunSidebar.tsx` | 本地会话历史、run 状态、搜索、恢复入口 |
| `AgentTranscript` | `src/components/agent/AgentTranscript.tsx` | 事件流渲染、自动滚动、断线提示 |
| `AgentComposer` | `src/components/agent/AgentComposer.tsx` | 输入 prompt、创建 run、取消当前 run |
| `AgentEventItem` | `src/components/agent/AgentEventItem.tsx` | `AgentEventRead` 统一渲染入口 |
| `ToolCallCard` | `src/components/agent/ToolCallCard.tsx` | 工具计划、运行、输出、错误、审批状态 |
| `ApprovalCard` | `src/components/agent/ApprovalCard.tsx` | 展示 pending approval，并触发 approve/reject |
| `MigrationBlockCard` | `src/components/agent/MigrationBlockCard.tsx` | 展示 migration block 和 resolve 动作 |
| `ContextBuildCard` | `src/components/agent/ContextBuildCard.tsx` | 展示 context degradation、required evidence |
| `LoopObservationCard` | `src/components/agent/LoopObservationCard.tsx` | 展示 root cause、stop reasons、mitigation |
| `RunInspector` | `src/components/agent/RunInspector.tsx` | 优先读取 `GET /agents/runs/{run_id}/actions` 和 `GET /agents/runs/{run_id}/summary`，再按 tab hydrate 详情 |
| `RunbookPanel` | `src/components/agent/RunbookPanel.tsx` | runbook diagnosis 和 safe actions |
| `AgentDashboardPanel` | `src/components/agent/AgentDashboardPanel.tsx` | readiness、metrics、alerts、release gate 摘要 |
| `AgentModelHealthPanel` | `src/components/agent/AgentModelHealthPanel.tsx` | show `GET /agents/model-health` configuration status, admin live probe result, and admin-only `POST /agents/conversation-smoke` diagnostics without exposing API keys |
| `AgentLaunchAuditPanel` | `src/components/agent/AgentLaunchAuditPanel.tsx` | show `GET /agents/launch-audit?project_id=...` backend integration readiness, fixed audit checks, dashboard readiness, and promotion decision without running live provider probes |
| `AgentBackendCompletionPanel` | `src/components/agent/AgentBackendCompletionPanel.tsx` | show `GET /agents/backend-completion-audit?project_id=...` backend-owned Agent completion checks for conversation, tools, approvals, Memory, diagnostics, docs, and contracts |

## 4. 页面状态模型

建议新增 `src/api/agents.ts` 和 `src/types/agents.ts`。

```ts
type AgentConnectionState =
  | "idle"
  | "connecting"
  | "streaming"
  | "reconnecting"
  | "closed"
  | "error";

type AgentThreadState = {
  conversationId: string;
  activeRunId: string | null;
  runsById: Record<string, AgentRunRead>;
  runSummariesById: Record<string, AgentRunSummaryRead>;
  runActionStatesById: Record<string, AgentRunActionStateRead>;
  transcriptsByConversationId: Record<string, AgentConversationTranscriptRead>;
  eventsByRunId: Record<string, AgentEventRead[]>;
  toolCallsById: Record<string, AgentToolCallRead>;
  contextBuildsByRunId: Record<string, AgentContextBuildRead[]>;
  loopObservationsByRunId: Record<string, AgentLoopObservationRead[]>;
  approvalsByRunId: Record<string, AgentApprovalRead[]>;
  migrationBlocksByRunId: Record<string, AgentMigrationBlockRead[]>;
  selectedInspector:
    | { type: "run"; id: string }
    | { type: "tool_call"; id: string }
    | { type: "context_build"; id: string }
    | { type: "loop_observation"; id: string }
    | { type: "approval"; id: string }
    | { type: "migration_block"; id: string }
    | null;
};
```

历史会话说明：

- 当前后端 `AgentRunRead` 有 `conversation_id`，支持前端把多轮 run 归入一个 conversation。
- `GET /agents/conversations?project_id=...` 返回服务端 conversation 列表，字段包括 `conversation_id`、`title`、`run_count`、`latest_run_id`、`latest_run_status`、`created_at`、`updated_at`。
- `GET /agents/conversations/{conversation_id}/runs?project_id=...` 返回该 conversation 下的 run 列表；`GET /agents/runs` 可按 project、conversation、status 查询。
- `GET /agents/conversations/{conversation_id}/transcript?project_id=...` 返回可直接恢复 transcript 的 `conversation + turns`，其中 `turns` 是按创建时间升序排列的 `AgentRunSummaryRead[]`。
- `GET /agents/conversations/{conversation_id}/export?project_id=...` 返回可下载/调试的 conversation export 包，按 run_id 分组包含 events、tool calls、approvals 和 migration blocks。
- localStorage 只用于草稿、置顶、最近打开等本地体验缓存；跨设备历史以服务端接口为准。

## 5. 流式传输原型

后端事件流：

```text
GET /api/v1/agents/runs/{run_id}/events
Header: Last-Event-ID: <last_event_seq>
Response: text/event-stream
```

调试或断线校准：

```text
GET /api/v1/agents/runs/{run_id}/events/snapshot?after_sequence=<last_event_seq>&limit=100
Response: ApiEnvelope<AgentRunEventSnapshotRead>
```

SSE item：

```text
id: 3
event: run.completed
data: {"schema_version":1,"run_id":"...","project_id":10,"event_seq":3,"event_type":"run.completed",...}
```

前端实现注意：

- 原生 `EventSource` 不能设置 `Authorization` header。当前前端技术文档要求复用 `requestWithAuth` 和鉴权头，因此推荐用 `fetch + ReadableStream + SSE parser` 实现，而不是直接 `new EventSource()`。
- 每个 run 维护 `lastEventSeq`，断线后用 `Last-Event-ID` 继续拉。
- 如果浏览器流式解析异常或需要确认后端是否已写入增量，先调用 `/events/snapshot`，用 `events[]` 补齐缺口并把 `lastEventSeq` 更新到 `next_after_sequence`。
- 当 run 进入 `completed`、`failed`、`cancelled` 这类 terminal 状态，并且事件序号追上 `last_event_sequence` 后关闭流。
- 事件到达时先追加 `AgentEventRead`，再按 `event_type` 触发二级资源 hydration。

事件到 UI 的映射：

| event_type 前缀 | 时间线展示 | 二级请求 |
| --- | --- | --- |
| `run.*` | Run 状态、开始、完成、取消 | `GET /agents/runs/{run_id}` |
| `run.*` / inspector focus | 右侧 Run summary、按钮状态、计数 badge | `GET /agents/runs/{run_id}/actions`；需要单独校准 summary 时读 `GET /agents/runs/{run_id}/summary` |
| `model.delta` / `model.markdown_normalized` / `model.completed` | Assistant 对话气泡和实时流式 Markdown 文本 | 无；直接拼接实时到达的 `model.delta.content`，若收到 `model.markdown_normalized.replace_content=true` 则用其 `content` 替换当前气泡，terminal 后用 `run.completed.result.message` 校准 |
| `model.tool_request_detected` | 模型计划调用工具的审计提示 | 不渲染为 assistant 文本；等待后续 `tool.*` card |
| `model.tool_request_invalid` / `model.tool_request_repaired` / `model.tool_request_repair_failed` | 工具请求格式修复状态 | 不渲染为 assistant 文本；成功后继续等待 `model.tool_request_detected`，失败后校准 run 状态 |
| `memory.context_injected` | Memory 上下文注入提示或右侧 Memory tab badge | `GET /agents/memory-usage-events?run_id={run_id}` |
| `tool.*` | ToolCall card | 事件含 `tool_call_id` 时调用 `GET /agents/tool-calls/{tool_call_id}` |
| `context.*` | ContextBuild card 或提示 | `GET /agents/runs/{run_id}/context-builds` |
| `loop.*` | LoopObservation card | `GET /agents/runs/{run_id}/loop-observations` |
| `approval.*` | Approval card | `GET /agents/runs/{run_id}/approvals` |
| `migration.*` | Migration block card | `GET /agents/runs/{run_id}/migration-blocks` |

## 6. 关键交互

### 6.1 新建对话

1. 用户点击左侧“新会话”。
2. 前端生成 `conversation_id`，清空当前 active run。
3. 用户在 composer 输入 prompt。
4. 调用 `POST /agents/runs`：

```json
{
  "project_id": 10,
  "conversation_id": "agent-conv-local-...",
  "intent": "请帮我生成测试计划",
  "max_iterations": 8,
  "auto_complete": false
}
```

后端在 `run.started` 后应立即启动 `AgentConversationRunner`。MySQL 和文件 SQLite 都会启动后台 worker；只有 in-memory SQLite 单元测试库会跳过后台线程。若 UI 只看到 heartbeat 而没有 `model.started`，优先用 `/events/snapshot` 确认事件链，再让管理员跑 `model-health` 的 `live=true` 或 `conversation-smoke`。

5. 成功后保存 run 到本地 history，打开事件流。
6. 如果收到 `memory.context_injected`，在时间线/右侧 Memory tab 展示“已注入项目记忆”状态，并按 run 拉取 memory usage；不要把它渲染成 assistant 气泡。
7. 收到可展示的 `model.delta.content` 后立即创建/更新 assistant 气泡；普通自然语言 delta 会在模型 stream 结束前持续到达。Assistant 气泡按 GitHub Flavored Markdown 渲染；若收到 `model.markdown_normalized` 且 `replace_content=true`，用该事件的 `content` 替换当前气泡，修复表格换行等最终格式。收到 `model.completed` 后冻结气泡内容，并在 terminal 后用 `run.completed.result.message` 校准。
8. 如果先收到 `model.tool_request_detected`，先展示轻量“正在调用工具”状态，不要把工具请求 JSON 当成 assistant 回复。
9. 如果收到 `model.tool_request_invalid`，展示轻量“正在修复工具请求格式”状态；收到 `model.tool_request_repaired` 后继续等待 ToolCall 事件，收到 `model.tool_request_repair_failed` 后按 failed run 展示错误。

`auto_complete` is a backend smoke/debug flag. The normal UI must keep it false and should not expose it in the Composer. If a debug run returns `completion_source=smoke_auto_complete` and `assistant_visible=false`, show it as a system smoke result instead of an assistant message.

管理员排查“Run 创建成功但没有回复”时，先看 `GET /agents/model-health` 携带 `live=true` 后是否 `reachable/first_delta_received/completed`，再调用 `POST /agents/conversation-smoke` 验证完整 Agent Run/EventStore/Summary 链路。普通用户路径不展示该 smoke 按钮。

页面初始化时可读取 `GET /agents/launch-audit?project_id=...`，用 `ready/status/checks` 判断后端是否已具备前端联调状态。该接口不做 live DeepSeek 调用，适合作为普通项目成员可见的集成状态；如果 `ready=true` 但页面仍无回复，优先排查前端 stream parser、Authorization header、cursor recovery 和 `assistant_visible/model.delta` 渲染。`promotion.decision=blocked` 不代表对话功能不可用，它只说明 L3 生产灰度仍受发布策略限制。

页面初始化也可以读取 `GET /agents/backend-completion-audit?project_id=...`，用 `complete/status/checks/backend_scope` 展示后端仓库拥有的 Codex 风格 Agent 功能完成度。`complete=true` 表示后端对话流、服务端历史、工具循环、审批恢复、Memory 注入、前端契约、诊断脚本和文档同步已经完成；`backend_scope.frontend_delivery=external repository` 表示前端仍由当前独立项目实现。

后端仓库提供普通用户路径的真实诊断脚本：

```powershell
.\.venv\Scripts\python.exe scripts\agent_conversation_e2e_check.py --project-id 1 --user-id 1 --intent "Reply exactly: Agent e2e ok." --timeout-seconds 90
```

如果该脚本返回 `result= ok`，说明 DeepSeek、MySQL、普通 `POST /agents/runs`、后台 runner、`model.delta`、`run.completed` 和 summary 聚合均已打通；前端原型排查应转向 `fetch + ReadableStream` SSE 解析、`Last-Event-ID` 游标、Authorization header 或 `assistant_visible/model.delta` 渲染逻辑。

### 6.2 多轮继续

1. 保持当前 `conversation_id`。
2. 每次发送新 prompt 都创建新的 Agent Run。
3. 时间线展示为多个 turn：User prompt -> Run timeline -> result。
4. 打开历史会话时优先读取 `GET /agents/conversations/{conversation_id}/transcript?project_id=...`，用 `turns[].run.intent` 和 `turns[].assistant_message` 重建 transcript。
5. 用户导出会话时调用 `GET /agents/conversations/{conversation_id}/export?project_id=...`，不要从本地缓存拼装导出包。
6. 后端会把同 conversation 最近已完成 run 的 `intent` 与 `result_json.message` 带入模型上下文；服务端权威字段是 `AgentRunRead.intent` 和 `result_json.message`。
7. 每个 run 调用模型前还会按 `normal_plan_v1` 检索项目 Memory，并以 `conversation_context` 注入。前端只展示审计提示和 usage 详情，最终回复仍以 `model.delta` / `run.completed.result.message` 为准。

### 6.3 工具调用和输出

1. 时间线收到 `tool.planned`、`tool.running`、`tool.completed`、`tool.failed` 等事件。
2. 从 payload 读取 `tool_call_id`。
3. 调用 `GET /agents/tool-calls/{tool_call_id}`。
4. `ToolCallCard` 展示：
   - `tool_name`
   - `status`
   - `input_json_redacted`
   - `output_json_redacted`
   - `required_permissions_json`
   - `current_approval`
   - `recent_reconcile_attempts`
   - `error_code` / `error_message`
5. 收到 `tool.result_observed` 表示后端已把工具结果加入下一轮模型上下文；等待后续 `model.delta` 展示最终自然语言回复。
6. 场景组合的工具顺序必须按后端事实展示：正常链路是 `testcase.query_project_cases` -> `scenario.compose_draft` -> 最终 `model.delta`。如果先出现 `scenario.compose_draft` 且 ToolCall 返回 `error_code=scenario_compose_requires_case_query`，这是后端 harness guard 对模型流程的纠正，不是前端要终止整轮对话；UI 应展示该 ToolCall 错误并继续等待后续 `testcase.query_project_cases`、新的 `scenario.compose_draft` 和最终自然语言回复。

### 6.4 人工审批

1. Run 或 ToolCall 出现 pending approval。
2. 调用 `GET /agents/runs/{run_id}/approvals`。
3. `ApprovalCard` 显示 CAS 字段：`input_hash`、`runtime_snapshot_id`、`resource_scope_hash`、`approval_lineage_id`、`approval_epoch`。
4. approve/reject 必须提交当前 approval 的 CAS 字段，不能只提交 reason。
5. approve 成功后调用 `POST /agents/runs/{run_id}/resume`；若响应包含 `executed_tool_call_ids`，刷新对应 ToolCall card，并继续监听 SSE。
6. 审批恢复成功的时间线顺序通常是 `approval.approved` -> `tool.running` -> `tool.completed` -> `tool.result_observed` -> `run.resumed` -> 后续 `model.delta` -> `run.completed`。

### 6.5 恢复和治理

`RunInspector` 顶部 action bar 以 `GET /agents/runs/{run_id}/actions` 为权威来源。前端只渲染后端返回的固定 `action_id`，根据 `enabled`、`reason`、`severity`、`resource_ids` 和 `details` 控制按钮禁用、提示文案、红黄风险状态和二级资源刷新；不要在前端重新推导 pending approval、uncertain tool call 或 migration block 的阻塞原因。

| 操作 | 接口 | UI 入口 |
| --- | --- | --- |
| Read action state | `GET /agents/runs/{run_id}/actions` | RunInspector action bar、Runbook safe action |
| Cancel run | `POST /agents/runs/{run_id}/cancel` | composer Stop、RunInspector |
| Resume run | `POST /agents/runs/{run_id}/resume` | RunInspector、Runbook safe action |
| Reconcile run | `POST /agents/runs/{run_id}/reconcile` | ToolCall card、Runbook safe action |
| Resolve migration block | `POST /agents/runs/{run_id}/migration-blocks/{block_id}/resolve` | MigrationBlockCard |
| Diagnose run | `GET /agents/runs/{run_id}/runbook` | RunInspector Runbook tab |

Stop 成功后继续监听当前 run 的 SSE，直到收到 `run.cancelled` 或 `/actions` 显示 `terminal=true`。后端会在模型流、工具请求修复和 final summary 阶段感知外部取消；前端不要在本地把已取消 run 乐观改回 completed。

## 7. 视觉风格

设计基调：安静、密集、工作台式。避免大 hero、装饰渐变和营销布局。

| 区域 | 风格 |
| --- | --- |
| 左侧栏 | 低对比列表，状态点、更新时间、搜索 |
| 时间线 | 宽度约 760px，事件自然流式堆叠，工具调用为可折叠灰底块 |
| 工具块 | header 显示 icon、工具名、状态、耗时；body 默认折叠 output |
| 右侧栏 | tabs：Run、Tool、Approval、Memory、Runbook、Dashboard |
| Composer | 底部固定，多行输入，右侧 Send/Stop，附加 max iteration 控件 |

状态色建议：

| 状态 | 颜色语义 |
| --- | --- |
| running / streaming | blue |
| needs_human / pending approval | amber |
| migration_blocked / failed / P0 alert | red |
| completed / pass | green |
| cancelled / obsolete | neutral |

## 8. 原型验收清单

- 能从空白会话创建 run。
- 能展示 run.queued、run.started、run.completed 等事件。
- 能在断线后按 Last-Event-ID 继续接收事件。
- 能点击 tool card 拉取 ToolCall 详情。
- 能展示 approval 并提交 approve/reject CAS 请求。
- 能从 `GET /agents/runs/{run_id}/actions` 展示可执行/不可执行按钮、阻塞原因和 primary actions。
- 能展示 context build 和 loop observation。
- 能查看 runbook diagnosis、dashboard、metrics、alerts。
- 能通过 `GET /agents/conversations/{conversation_id}/export` 导出当前 conversation 的事件和工具输出调试包。
- 历史列表明确标注 MVP 为本地历史，不冒充服务端历史。
- 所有字段名使用后端 snake_case，不在前端私自改名。
