# Agent Codex 风格前端开发计划

状态：开发方案
最后核验：2026-06-27

适用前端技术栈：React 19、Vite、TypeScript、Vitest、Testing Library、CSS。接口基础路径通过 `VITE_API_BASE_URL` 配置，默认 `/api/v1`。

## 1. 开发边界

本计划只设计和指导前端实现，不在当前后端仓库创建 React 工程。前端工程应按现有约定放置：

| 文件 | 说明 |
| --- | --- |
| `src/api/agents.ts` | 普通 JSON API 封装 |
| `src/api/agentStream.ts` | SSE fetch stream 封装 |
| `src/types/agents.ts` | Agent 后端契约类型 |
| `src/pages/AgentPage.tsx` | `/agents` 页面 |
| `src/components/agent/` | Agent 专用组件 |
| `src/pages/AgentPage.test.tsx` | 页面测试 |
| `src/api/agents.test.ts` | API 封装测试 |
| `src/api/agentStream.test.ts` | SSE parser 测试 |

## 2. 里程碑

### P0 - 契约类型与 API 封装

目标：所有后端接口先进入类型和 API 层，页面不直接拼接路径。

任务：

1. 新增 `src/types/agents.ts`，按 `docs/api_agent_frontend_contract.md` 定义类型。
2. 新增 `src/api/agents.ts`，封装 run、run summary、run action state、conversation transcript、conversation export、tool call、approval、context build、loop observation、memory、dashboard、launch audit、runbook、release gate、model health。
3. 新增 `src/api/agentStream.ts`，用 `fetch + ReadableStream` 解析 SSE，并在流解析异常时可回退调用 `GET /agents/runs/{run_id}/events/snapshot` 补齐 EventStore 事件。
4. API 返回统一使用 `ApiEnvelope<T>`。
5. 编写 API 路径和 SSE parser 单元测试。

验收：

- API 测试覆盖所有前端会调用的 `/agents/*` 路径。
- API 测试覆盖 `GET /agents/model-health`，普通配置检查不触发 live probe；admin 调试路径可传 `live=true`。
- API 测试覆盖 `GET /agents/launch-audit`，确认普通项目成员可按 `project_id` 读取后端联调状态，且不触发 live DeepSeek probe。
- API 测试覆盖 `GET /agents/backend-completion-audit`，确认普通项目成员可按 `project_id` 读取后端 Agent 完成度，且不触发 live DeepSeek probe。
- API 测试覆盖 admin-only `POST /agents/conversation-smoke`，用于验证完整 Agent Run/EventStore/Summary 链路。
- API 测试覆盖 `GET /agents/runs/{run_id}/summary`，字段顺序使用后端 `AgentRunSummaryRead`。
- API 测试覆盖 `GET /agents/runs/{run_id}/actions`，字段顺序使用后端 `AgentRunActionStateRead`，固定 action id 不在前端重命名。
- API 测试覆盖 `GET /agents/conversations/{conversation_id}/transcript`，刷新历史会话不再由前端拼接 run list。
- API 测试覆盖 `GET /agents/conversations/{conversation_id}/export`，导出包包含 events、tool calls、approvals 和 migration blocks 分组。
- SSE parser 支持 `id`、`event`、`data`、heartbeat、断包。
- `Last-Event-ID` 可通过 header 传入。
- API 测试覆盖 `GET /agents/runs/{run_id}/events/snapshot`，确认 `events[]` 使用 `AgentEventRead` 字段并按 `next_after_sequence` 续拉。

### P1 - Agent 工作台骨架

目标：实现 Codex 风格三栏工作台。

任务：

1. 在路由中启用 `/agents`。
2. 左侧 `AgentRunSidebar` 支持新会话、本地历史、搜索、状态筛选。
3. 中间 `AgentTranscript` 支持事件时间线。
4. 右侧 `RunInspector` 支持 Run、Tool、Approval、Memory、Runbook、Dashboard tabs；Run tab 读取 `GET /agents/runs/{run_id}/summary`，顶部 action bar 优先读取 `GET /agents/runs/{run_id}/actions`。
5. 右侧环境/运行信息区域显示 `GET /agents/launch-audit?project_id=...` 的 `ready/status/checks`、`GET /agents/backend-completion-audit?project_id=...` 的 `complete/status/checks/backend_scope`，并显示 `GET /agents/model-health` 的 configured/reachable/first_delta_received 状态；普通用户只显示配置、launch audit 和 backend completion audit 状态，管理员可触发 live probe 和 `POST /agents/conversation-smoke` 端到端诊断。
6. 底部 `AgentComposer` 支持 prompt、max_iterations、send/stop；`auto_complete` 仅作为后端 smoke/debug 字段，普通 UI 不暴露并固定为 false。

验收：

- 空态、加载、错误、无权限、断线、终态都可见。
- 窄屏左/右栏可折叠。
- 不依赖 mock 字段，字段名来自后端契约。

### P2 - Run 创建与流式事件

目标：从用户 prompt 创建 run，并实时展示事件。

任务：

1. `POST /agents/runs` 创建 run。
2. 保存 `{conversationId, runId, intent, updatedAt}` 到本地最近打开缓存，并以服务端 history 接口为准。
3. 连接 `GET /agents/runs/{run_id}/events`。
4. 事件到达后追加到 `eventsByRunId`；断线或调试时用 `GET /agents/runs/{run_id}/events/snapshot?after_sequence=...` 补齐缺口。
5. `memory.context_injected` 只作为项目 Memory 注入审计提示，并驱动右侧 Memory tab 查询 `GET /agents/memory-usage-events?run_id={run_id}`。
6. `model.delta.content` 实时创建或更新 assistant 气泡；普通自然语言回复不需要等待 `model.completed` 才展示，assistant 气泡按 GitHub Flavored Markdown 渲染。若收到 `model.markdown_normalized.replace_content=true`，用该事件的 `content` 替换当前气泡；`model.completed.content` 只用于冻结完整回复。
7. `model.tool_request_detected` 只作为工具计划审计提示，不渲染为 assistant 文本；等待后续 `tool.*` card。
8. `model.tool_request_invalid` / `model.tool_request_repaired` / `model.tool_request_repair_failed` 只作为工具请求格式修复审计提示；修复成功后继续等待 ToolCall，失败后校准 run。
9. terminal 状态后调用 `GET /agents/runs/{run_id}/actions` 校准最终状态、`assistant_message`、计数 badge 和 action 状态；需要单独 summary 或原始 run 详情时再读取 `GET /agents/runs/{run_id}/summary` / `GET /agents/runs/{run_id}`。
10. 断线后用 `Last-Event-ID` 重连。

验收：

- 可连续发送多轮 prompt，复用 `conversation_id`。
- 可看到后端通过 SSE 实时返回的模型流式回复，首个普通自然语言 delta 应在模型 stream 完成前出现。
- 最终 `assistant_message`、`model.completed.content` 和 `run.completed.result.message` 均可按 Markdown 渲染；表格不应出现多行被 `| |` 拼在同一行的情况。
- 普通 run 创建后事件链应从 `run.started` 继续到 `model.started`；如果只有 heartbeat，用事件快照判断是 runner 未启动还是前端 stream 未消费。
- `GET /agents/backend-completion-audit?project_id=...` 的 `complete=true` 且 `GET /agents/launch-audit?project_id=...` 的 `ready=true` 时，前端不得继续把后端整体标记为不可用；若仍无回复，应进入 SSE/parser/rendering 排查。
- 当 SSE parser 没有收到 `model.delta` 时，可用事件快照接口确认后端是否已写入 EventStore，并用 `next_after_sequence` 恢复 cursor。
- 前端联调前或排查“没有 assistant 回复”时，后端应先运行 `scripts/agent_conversation_e2e_check.py --project-id <id> --user-id <id>`；若该脚本返回 `result= ok`，前端测试应重点覆盖 stream parser、Authorization header、cursor recovery 和 `assistant_visible/model.delta` 渲染。
- 可看到后端对话前注入的 Memory usage，并能从 Memory tab 进入 feedback。
- 模型工具请求格式有轻微错误时，前端可看到一次自动修复状态，修复成功后继续工具调用，不把错误 JSON 当 assistant 文本。
- 可以 stop 当前 run；即使后端正在工具回灌后的 final summary 流式生成中，最终状态也必须保持 cancelled，不被后续 completed 覆盖。
- 可以刷新页面后从服务端 conversation/run list 恢复当前 run。

### P3 - ToolCall、Approval、Migration

目标：展示并操作 Agent 的工具调用和人工确认流程。

任务：

1. 事件中发现 `tool_call_id` 后请求 `GET /agents/tool-calls/{tool_call_id}`。
2. ToolCall card 展示输入、输出、策略、权限、错误和 reconcile attempts。
3. `tool.result_observed` 表示后端已把工具输出回灌给下一轮模型；UI 保持工具卡片并等待后续自然语言回复。
4. 场景组合工具链按 `testcase.query_project_cases` -> `scenario.compose_draft` 展示；若 `scenario.compose_draft` 先被后端以 `scenario_compose_requires_case_query` 阻断，ToolCall card 展示错误并继续等待模型后续纠正，不把它当作 terminal 失败。
5. `GET /agents/runs/{run_id}/approvals` 展示 pending approvals。
6. approve/reject 提交 CAS 字段。
7. `RunInspector` action bar 使用 `GET /agents/runs/{run_id}/actions` 显示 `review_approvals`、`resume_run`、`reconcile_run`、`resolve_migration` 等动作是否可用，并展示后端返回的阻塞原因。
8. approve 成功后调用 `POST /agents/runs/{run_id}/resume`，读取 `executed_tool_call_ids` 并继续监听 SSE。
9. `GET /agents/runs/{run_id}/migration-blocks` 展示阻断项。
10. `POST /agents/runs/{run_id}/migration-blocks/{block_id}/resolve` 支持解决阻断。

验收：

- approve/reject 409 时提示“审批已过期或上下文已变化”。
- approve 后 resume 能展示已执行工具输出，并继续收到最终 assistant 回复。
- ToolCall 输出默认折叠，用户可展开查看 redacted output。
- 场景组合联调测试覆盖 query-first 正常顺序，以及 `scenario_compose_requires_case_query` 后继续等待后续 ToolCall 和最终 assistant 回复。
- migration block resolve 后自动 refresh run、context、events。

### P4 - Context、Loop、Memory

目标：展示 Agent 决策上下文、循环观察和 Memory 证据。

任务：

1. `GET /agents/runs/{run_id}/context-builds` 展示 context degradation、required evidence。
2. `GET /agents/runs/{run_id}/loop-observations` 展示 root cause、causal chain、mitigation。
3. `GET /agents/memory-usage-events?run_id={run_id}` 展示本 run Memory 使用。
4. 支持 memory feedback：`POST /agents/memory-usage-events/{usage_event_id}/feedback`。
5. Profile catalog 用于说明 Memory 策略，不在普通用户路径里默认编辑。

验收：

- ContextBuild 和 LoopObservation 可从 timeline 跳转到右侧详情。
- Memory usage 可标记 useful / misleading / stale。
- 高风险动作只依赖 Memory 时需要明显风险提示。

### P5 - Runbook、Dashboard、Release Gate

目标：把后端治理能力变成可执行建议。

任务：

1. `GET /agents/runs/{run_id}/runbook` 展示 diagnosis 和 recommendations。
2. Runbook safe actions 映射到已有前端操作：resume、reconcile、context rebuild、migration block、tool call detail。
3. `GET /agents/dashboard` 展示 readiness。
4. `GET /agents/metrics`、`GET /agents/alerts` 展示监控摘要。
5. `GET /agents/release-gates`、`GET /agents/release-gates/promotion` 展示上线门禁。

验收：

- P0/P1 alerts 在右侧面板明显显示。
- safe action 只调用后端 OpenAPI 已存在路径。
- 无权限 admin 接口不展示操作按钮。

### P6 - 历史会话和体验收口

目标：完成类似 Codex 的历史对话体验。

任务：

1. 使用 `GET /agents/conversations` 支持服务端 conversation history 搜索和跨设备恢复。
2. 使用 `GET /agents/conversations/{conversation_id}/transcript` 恢复单个 conversation 的 Codex 式 transcript；仅在需要列表管理时再调用 `GET /agents/conversations/{conversation_id}/runs`。
3. 使用 `GET /agents/conversations/{conversation_id}/export` 导出当前 conversation 的事件、tool output、approval 和 migration block 调试包。
4. 支持键盘快捷键：新会话、发送、停止、搜索、打开 command palette。
5. 增加无障碍标签和焦点管理。

本地缓存只保存置顶、草稿、最近打开和 inspector UI 状态；服务端列表是历史事实源。

## 3. 页面测试计划

| 测试 | 覆盖 |
| --- | --- |
| `agents.test.ts` | API 路径、method、body、query |
| `agentStream.test.ts` | SSE parser、Last-Event-ID、abort、heartbeat |
| `AgentPage.test.tsx` | 创建 run、事件到 UI、stop、重连 |
| `ToolCallCard.test.tsx` | 输出展开、错误、审批状态 |
| `ApprovalCard.test.tsx` | CAS 字段、approve/reject、409 |
| `RunInspector.test.tsx` | tabs、run action state、runbook、dashboard |
| `history.test.ts` | 服务端 conversation list、conversation transcript、conversation export、run list、本地草稿/置顶缓存 |

## 4. 文档同步要求

实现时需要同步更新前端项目中的：

- `AGENTS.md`
- `docs/documentation-governance.md`
- 现有 TestAuto 技术文档的 Agent 运行章节
- API 封装说明
- 测试基线

变更完成标准：

- 前端字段与 `docs/api_agent_frontend_contract.md` 一致。
- 服务端历史能力必须使用 `docs/api_agent_frontend_contract.md` 中声明的接口，不得继续使用 localStorage 作为跨设备事实源。
- 所有新增页面、组件、API 和权限规则都有文档记录。

## 5. 风险和处理

| 风险 | 处理 |
| --- | --- |
| EventSource 无法带 Authorization | 使用 `fetch + ReadableStream` |
| 服务端历史接口返回与本地缓存不一致 | 服务端为准，本地缓存仅保留草稿、置顶和最近打开 |
| SSE 事件与最终 run 状态短暂不一致 | terminal 后用 `GET /agents/runs/{run_id}` 校准 |
| ToolCall 输出大或敏感 | 默认折叠，只展示 redacted 字段 |
| approval CAS 冲突 | 明确提示 stale，刷新 approvals/tool call |
| admin-only 接口误展示 | 根据 403 和用户权限隐藏或禁用 |

## 6. 建议开发顺序

1. `types/agents.ts`
2. `api/agents.ts`
3. `api/agentStream.ts`
4. `AgentPage` 三栏布局
5. Run create + SSE timeline
6. ToolCall details
7. Approval / Migration operations
8. ContextBuild / LoopObservation / Memory
9. Runbook / Dashboard / Release Gate
10. 本地历史和体验 polish
