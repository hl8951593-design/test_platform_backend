# 自动化测试平台后端技术架构文档

状态：当前实现
最后核验：2026-07-01

文档入口、权威范围和维护要求见 [文档索引与维护规范](README.md)。

开发过程中的模块关系、业务逻辑、数据权限和用户权限记录见 [开发过程技术文档](development_technical_notes.md)。

项目权限底座接口见 [项目权限接口文档](api_project_permissions.md)。

测试用例接口见 [测试用例接口文档](api_test_cases.md)。

WebSocket 测试用例接口见 [WebSocket 测试用例接口技术文档](api_websocket_test_cases.md)。

AI 能力、Skill Runtime 和 DeepSeek 接入见 [AI 能力接口文档](api_ai.md) 与
[AI 开发记录](development_ai_notes.md)。

场景组合与实时事件接口见 [场景组合接口文档](api_scenarios.md)。

缺陷跟踪接口见 [缺陷跟踪接口文档](api_defects.md)。

MinIO 图片附件接口和部署配置见 [媒体存储接口文档](api_media.md)。

场景从触发到 dataset record、步骤、变量和事件持久化的完整关系见
[场景组合执行流程图谱](scenario_execution_graph.md)。

场景版本只保存 `nodes[]`：每个节点绑定一个 HTTP/WebSocket 主用例，并以
`before_actions[]`、`after_actions[]` 显式表达动作位置。执行器按节点顺序展开为
`before_actions -> test_case -> after_actions`；前置或主用例失败不会跳过本节点后置动作，
后置动作逐项尝试，失败仍如实计入运行终态。旧 `steps/execution_phase` 只允许通过
`0020_scenario_nodes` 一次性迁移，运行时没有兼容分支。

## 1. 项目定位

本项目是一个基于 FastAPI 的自动化测试平台后端，主要面向接口自动化测试场景。

平台核心目标不是简单封装 pytest 或 Allure，而是自研一套接口测试用例管理、测试流程编排、执行引擎和测试报告体系。用户可以在前端维护接口、组合测试流程、选择环境并触发执行，后端负责执行请求、处理变量、执行断言、记录结果并生成报告数据。

## 2. 总体技术选型

| 模块 | 技术选型 | 说明 |
| --- | --- | --- |
| Web 框架 | FastAPI | 提供 REST API，支持 OpenAPI 文档和类型校验 |
| ASGI 服务 | Uvicorn | 本地开发和服务启动 |
| 数据库 | MySQL | 保存用户、项目、接口、用例、流程、缺陷、执行记录和报告 |
| ORM | SQLAlchemy 2.x | 负责数据库模型和查询 |
| 数据库迁移 | Alembic | 管理表结构版本演进 |
| 数据校验 | Pydantic v2 | 定义请求和响应数据结构 |
| 认证 | JWT | 支持前后端分离认证 |
| 密码加密 | passlib[bcrypt] | 用户密码哈希存储 |
| 缓存/临时状态 | Redis | 保存 token 状态、任务状态、临时变量和限流数据 |
| 对象存储 | MinIO（S3 兼容） | 私有保存缺陷截图等二进制媒体，MySQL 只保存对象键和元数据 |
| HTTP 执行引擎 | httpx | 执行接口测试步骤 |
| AI Provider | DeepSeek OpenAI 兼容接口 | 通过 `AIService` 统一调用，业务能力由 AI Skill Runtime 与 Harness Loop Agent 承载；Agent 使用 `/api/v1/agents/model-health` 做配置与 live stream 探测，使用 `/api/v1/agents/launch-audit` 聚合前端联调/上线准备状态，并使用 `/api/v1/agents/backend-completion-audit` 聚合后端仓库拥有的 Agent 功能完成度，不暴露 API key |
| 异步任务 | FastAPI BackgroundTasks（当前）/ 独立 Worker（演进目标） | 当前场景手工执行在响应后继续运行；生产可靠性阶段迁移到独立 Worker |
| 实时事件 | SSE + MySQL 持久化事件表 | 支持鉴权请求头、Last-Event-ID 重放、心跳、终态关闭和出站 item_id envelope |
| 测试报告 | 自研 | 基于执行记录生成平台内置报告 |
| 配置管理 | pydantic-settings + .env | 管理环境配置 |
| 日志 | Python logging 或 loguru | 记录系统日志和执行日志 |

`/api/v1/agents/model-health` 的 `error_message` 仍保持字符串字段以兼容前端，但 live probe 的长错误不会原样透出：短错误直接返回，超过 `AGENT_ERROR_MESSAGE_MAX_CHARS=512` 的 provider/HTTP 异常会被 `_bounded_agent_error_message()` 收口为 `agent_error_message_summary_v1` preview、截断标记、原始长度、hash 和 `full_error_reference`，避免模型供应商长响应或异常尾部进入前端探测结果。

`/api/v1/agents/capabilities` 是运行时状态枚举和工具 manifest 的公开能力出口，响应字段由 `AgentCapabilitiesRead` 固定。`tools[]` 只能来自 `ToolSpec.to_json()` 的公开字段，包含 `item_id=agent-tool-spec://{name}/{version}`、schema/manifest hash 和 backend contract 摘要；`backend_handler`、`required_successful_tool_before`、`missing_prerequisite_error_code`、`missing_prerequisite_next_action` 与 `tool_result_repair_guidance` 仍是后端私有字段，不得泄露到 capabilities、模型初始工具清单或前端契约。Harness 文档用 `Required Agent capabilities payload contract` 机器契约锁住该边界。

`testcase.execute_saved`、`testcase.batch_execute`、`websocket_testcase.execute_saved` 与 `websocket_testcase.batch_execute` 是 Agent 触发真实测试执行的受控工具，均声明 `side_effect_class=execution_record`、`replay_policy=require_revalidation` 和 `test:execute` 权限。它们复用 HTTP/WebSocket 用例执行服务创建业务执行记录，并把来源写入执行记录自身：人工接口执行默认为 `trigger_source=manual`，Agent 工具执行为 `trigger_source=agent`，同时记录 `agent_run_id`、`agent_tool_call_id` 与 `trigger_tool_name`。这样执行中心、报告和 Agent ToolCall 详情都能区分人工执行与 AI 代用户执行；即使 Agent ToolCall 日志被单独查看，也能通过 execution id 追溯到业务留痕。

`testcase.create_saved`、`testcase.update_saved`、`testcase.update_assertions`、`testcase.batch_update_assertions`、`websocket_testcase.create_saved`、`websocket_testcase.update_saved`、`websocket_testcase.update_assertions` 与 `websocket_testcase.batch_update_assertions` 是 Agent 修改已保存测试用例的受控工具，均声明 `side_effect_class=business_update`、`replay_policy=require_revalidation` 和 `case:manage` 权限。它们复用 HTTP/WebSocket 用例保存服务，但不会在模型发起工具请求时立即写入业务表；ExecutionLedger 会先落 `approval_required=true` 的 ToolCall，ApprovalService 创建 pending approval 并把 run 置为 `needs_human`。只有用户审批并 resume 后，worker 才会执行对应后端 handler 写入 `test_cases` 或 `websocket_test_cases`。其中 `update_assertions` / `batch_update_assertions` 是字段级 patch 工具，只替换 `assertions`，不覆盖请求配置、提取器、重试策略或 WebSocket 连接/消息配置；这类局部工具用于承接同一会话中“保存刚才生成的断言”之类的后续动作，避免模型为了写单字段而要求完整用例 JSON。

`testcase.query_project_cases` 除返回 HTTP/WebSocket 用例明细外，还返回 `http_test_case_ids` 与 `websocket_test_case_ids` 两个升序 ID 数组，作为 Agent 批量执行规划的结构化事实，避免模型把离散 ID 误读为连续区间。两个批量执行工具在任何 enqueue/execute 副作用前执行全量 ID 预校验；发现无效 ID 时返回结构化 `422`，并保证不创建部分执行记录、不留下 queued 业务留痕。

`AgentRuntimeSnapshot` 是每个 run 冻结运行时工具集合和 hash 解释的事实源：`tools_json` 来自同一时刻的 `ToolRegistry.registry_json()`，`manifests_json.tools` 是同一公开工具 manifest 按名称 keyed 的映射；`runtime_hash`、`tool_registry_hash` 和 `manifest_bundle_hash` 分别由 `ToolRegistry.runtime_hash()`、`ToolRegistry.registry_hash()` 与 `ToolRegistry.manifest_bundle_hash()` 计算。Snapshot 工具 manifest 与 capabilities 一样只包含 `ToolSpec.to_json()` 公开字段、`agent-tool-spec://{name}/{version}` 工具 row identity 和 schema/manifest hash，后端私有 handler、前置工具和修复 guidance 仍留在 registry/runtime 内部。`AgentRuntimeSnapshotRead.item_id=agent-runtime-snapshot://{snapshot_id}` 把该冻结运行时事实作为独立 timeline/debug/download item 暴露，但不替代 run/tool/approval 里的 `runtime_snapshot_id` 引用。Harness 文档用 `Required RuntimeSnapshot entity payload contract` 机器契约锁住 snapshot、registry、hash 来源和 item prefix，避免冻结运行时事实、模型提示工具清单与诊断解释分叉。

模型初始工具提示是 Plan 阶段的精简协议，而不是完整 manifest 出口：`_conversation_system_prompt()` 从 `ToolRegistry.list_specs()` 派生 `approval_required,input_schema,name,side_effect_class,summary` 五个字段，并用 `json.dumps(sort_keys=True,separators=(",", ":"))` 输出稳定 JSON，便于 prompt cache 复用。完整 manifest 字段仍由 capabilities/runtime snapshot/ToolCall 诊断承载，后端私有 handler、前置工具和修复 guidance 只供 Runtime/Runner/Policy 内部读取。Harness 文档用 `Required Agent initial tool prompt contract` 机器契约锁住模型可见工具协议，避免模型规划入口与 registry、snapshot 或前端契约分叉。

ToolCall Detail 中的 `recent_reconcile_attempts[]` 也补齐稳定 item identity：`AgentReconcileAttemptRead.item_id=agent-reconcile-attempt://{tool_call_id}/{attempt_seq}` 定位单次 reconcile/backoff 诊断项。该字段由现有 ToolCall id 和 attempt 序号派生，不新增数据库列，不替代父级 `tool_call_id` 或 run-scoped `agent-tool-call://{run_id}/{tool_call_id}` item；Harness ToolCall entity 契约同时锁定嵌套 attempt 字段和 item prefix。

Reconcile summary 中被 backoff 节流跳过的 `skipped_backoff_tool_calls[]` 也补齐稳定 item identity：`item_id=agent-reconcile-skipped-backoff://{tool_call_id}/{attempt_seq}`。该字段由最新 reconcile attempt 的 ToolCall id 与 attempt 序号派生，不新增数据库列，也不改变 next_retry_at、backoff eligibility、adapter 分流或 retry 窗口；它只用于前端稳定定位本次 reconcile summary 的 skipped row 和导出包 debug item。

Harness Loop Agent 的业务工具调用走 Codex 式闭环：Runner 组装 run context、ToolRegistry、权限边界、会话工作上下文和历史上下文后调用 `AIService`，模型只能通过受控 `agent_tool_request` 发起 ToolCall，Harness 执行后把 `tool.result_observed` 回灌给下一轮模型；其中项目 Memory 以 `conversation_context` 注入时只进入有界系统消息，title/content 字段级截断且整条消息受 `AGENT_MEMORY_CONTEXT_MESSAGE_MAX_CHARS` 保护，完整 Memory 正文仍以 Memory/usage 审计接口为准。同一 conversation 的已完成历史除了按 user/assistant 消息回放，还会生成 redaction-safe 的“同一会话工作上下文”system 消息：最近轮次被整理为 `recent_turns`，可识别产物被整理为 `current_artifact_candidates`，当前请求若包含“直接、刚才、上面、这个”等省略表达会标记 `current_intent_is_deictic_followup=true`，模型必须先解析回指再选择工具或询问澄清。该工作上下文同时参与 Skill selection，使“直接保存”这类省略请求能加载上一轮产物所属领域的 Skill，而不是只按当前短文本选 Skill。Unsupported capability guard 只能用显式领域 subject 命中，`直接/刚才/上面/这个` 等回指词不能单独触发某个领域 guard；否则会在模型读取工作上下文前错误终止同一会话的多轮理解。

Agent runner 的异常面必须先收敛 run 事实，再让 worker 退出：普通 HTTP/model/tool-request 修复异常仍通过当前 `AgentRuntimeService.fail_run()` 写入 `run.failed`；如果异常发生时 MySQL 连接已断开，导致当前 SQLAlchemy session 进入 `PendingRollbackError` 或其他不可继续写入状态，Runner 会 rollback 主 session、dispose 断连连接池，并用新的 `SessionLocal` 重新读取同一 run 后写入 `run.failed`。这个 recovery session 只负责补齐终态和有界 `error_code/error_message`，不重放工具副作用、不覆盖已 terminal 的 run，也不改变 SSE 契约；前端继续只消费 EventStore/Run Summary 的 `failed` 终态。

Agent 模型流和请求依赖的数据库连接边界也必须短事务化：`AgentConversationRunner._stream_model_response()` 写完 `model.started` 后，在进入 `AIService.chat_stream()` 前释放当前 SQLAlchemy transaction；流式期间每次只用短事务刷新 run terminal 状态，非终态立即 rollback 释放连接；写入 `model.delta`、`model.stream_retrying` 或撤回临时 markdown 后也释放事务，再继续等待 provider。FastAPI `get_db()` 依赖在 handler 抛异常时先 rollback 再 close，避免异常路径把未结束事务交回连接池。该策略不改变 EventStore 顺序、ToolCall 副作用或 SSE payload，只减少长 provider 静默、长 dashboard 聚合、网络抖动或 RDS TCP reset 放大成长事务/坏连接的概率。

模型输出的 fenced JSON 先被解析成内部 `AgentToolRequest` envelope，再进入 EventStore 和 ExecutionLedger：该 envelope 只保留 `tool_name`、`tool_input`、`reason`、`evidence_refs` 四类受控字段，并通过拷贝方法生成 ToolCall input/evidence 与 `model.tool_request_detected` payload，未知模型字段不会穿透到后端账本或前端事件。ToolCall 执行链路已拆成 `ToolExecutor` 生命周期编排、`AgentToolRuntime` 后端调用门面、`AgentToolRouter` 显式 handler 路由三层：Executor 负责审批/权限/队列/EventStore 状态推进，Runtime 负责把已落账的 ToolCall 转成后端执行请求，Router 负责从 `ToolRegistry` 的私有 `backend_handler` 解析可调用处理器。普通自然语言流式回复采用低延迟 EventStore/SSE 路径：首个可见 `model.delta` 立即写入，后续小碎片按短时间窗口或字符阈值微批提交，减少高频数据库事务；但涉及项目上下文、场景组合、保存动作等工具规划轮时，Runner 会先静默收流并解析工具请求，防止内部 `agent_tool_request` JSON 或候选分析泄露到 assistant 气泡；若工具 fenced block 在短暂可见 preamble 之后才到达，Runner 会用同一 `model_call_id` 写入 `model.markdown_normalized(content="", replace_content=true, normalization_reason=tool_request_stream_suppressed)` 撤回临时文本，再写入 `model.tool_request_stream_suppressed` 审计事件；若静默规划轮最终产出普通文本，Runner 只补发一个合并后的可见 `model.delta`，避免长文本逐 token 回放压住 SSE/EventStore；模型若把自然语言和单个工具 fenced block 混在一起，会优先本地挽救并规范化轻微 schema 偏差，其他非法格式才进入一次 LLM 工具请求修复；工具请求格式修复和 required follow-up 缺失修复的模型调用只接收 `AGENT_REPAIR_CONTEXT_MAX_CHARS` 内的上一轮输出上下文，超长内容以 `agent_repair_context_truncated` 标记截断，不把完整异常文本重新注入模型。Runner 在每次模型重新采样前、ToolCall 执行返回后和 final summary 前都会重新读取 run terminal 状态；若外部 Stop 在工具执行期间写入 `run.cancelled`，Runner 不会继续发起下一次 `AIService.chat_stream()`，也不会写 `run.completed` 覆盖取消终态。SSE 对 `queued/running` run 使用短轮询，对非活跃状态保持普通轮询和 heartbeat。`Last-Event-ID` 与 `after_sequence` 是 run-scoped cursor；若客户端把其他 run 的较大 cursor 带到当前 run，后端会在 cursor 大于当前 `last_event_sequence` 时重置为 0 重放当前 run 事件，避免 heartbeat-only 连接。为避免 worker 崩溃、进程重启或前端错过终态导致 UI 无限“正在思考”，Agent read paths 会用最新 EventStore 事件时间识别超过 `AGENT_RUN_STALE_TIMEOUT_SECONDS` 的 `queued/running` run，并写入 `run.failed(agent_run_stale_worker_lost)` 作为可审计终态；所有通过 `AgentRuntimeService.fail_run()` 写入的 `AgentRun.error_message` 与 `run.failed.payload.error_message` 仍保持字符串兼容，短错误原样返回，长错误通过 `agent_error_message_summary_v1` 写入 preview、截断标记、原始长度、hash 与 `full_error_reference`，Runner 的 HTTP/未预期失败日志也记录同一有界字符串和 `error_type`，不再用 `logger.exception` 打完整异常尾部；若 DeepSeek 已产生部分内容后流式连接中断，Runner 写入 `model.stream_interrupted` 并尽量用 partial content 继续解析/完成，避免用户可见结果为空。Agent 同时具备软件测试领域的通用自然语言回答能力：测试理论、用例设计、接口/WebSocket 测试、断言、测试数据、缺陷定位、回归策略、CI 和报告解读等不需要项目实时事实或平台副作用的问题，可以直接通过 `model.delta`/`run.completed.result.message` 回答；超出软件测试领域的问题必须说明边界。工具结果质量闭环由 `ToolResultPolicy` 统一实现：任何成功 ToolCall 输出中的 `warnings`、`issues`、`diagnostics`、`errors` 或 `valid=false` 都会被抽取并拆分为可自动修复项、用户/外部配置阻断项和待模型继续判断项；按工具推荐的修复路径由各 `ToolSpec.tool_result_repair_guidance` 后端私有字段声明，策略层只负责读取元数据和通用 fallback；回灌给模型的工具结果消息必须有硬上限，小输出保持原 `output` 结构，大输出只给 `output_preview`、`output_truncated`、`output_size_chars`、`output_hash` 和 `full_output_reference`，完整 `output_json_redacted` 继续留在 ToolCall Detail；多条工具结果进入后续模型调用或审批恢复 final summary 前还受 `AGENT_TOOL_RESULT_CONTEXT_TOTAL_MAX_CHARS` 聚合预算约束，超出部分用 `agent_tool_result_context_truncated` 标记，完整输出仍留在 ToolCall/summary/report 详情中；失败 ToolCall 若错误属于输入、schema、validation、草稿结构或字段格式，也会进入修复闭环；若修复后同一工具连续两次以相同 `error_code` 与 `error_message` 失败，Runner 会写入 stop 用 ContextBuild 与 `loop.observed(RC_NO_PROGRESS_PURE)`，并以 `run.failed(agent_repair_no_progress)` 停止继续消耗模型和工具循环；硬编码字段、结构校验、提取器、断言 expected、数据集、schema/type/format 等可由平台数据或安全工具推断的问题，应优先通过 read/query/draft/validate/dry-run 工具继续修复或验证，鉴权令牌、账号密码、密钥、审批或没有平台来源的私有输入才交给用户。工具结果后的最终回复默认只输出已完成、已自动修复/验证、剩余阻断项和下一步，完整草稿结构和长 JSON 留在 ToolCall/summary/report 详情中。场景组合仍是当前强约束 recipe，但规则来源已收口到 Skill/ToolSpec：`scenario-composition/SKILL.md` 的私有 `routing_required_tool_after_success` 负责 query 成功后缺 compose 的静默修复，且可用 `intent_markers` 把 follow-up 限定在生成、创建、组合、执行场景、场景草稿、dry-run、数据集/参数化等明确场景编排意图内；`scenario.compose_draft` 的 ToolSpec 私有 `required_successful_tool_before` 负责执行前顺序校验。直接 compose 会被 Runner 以 `scenario_compose_requires_case_query` 阻断并回灌给模型纠正；query 成功但模型没有继续 compose 时，只有命中 `intent_markers` 才会写入 `model.required_tool_missing(after_tool, required_tool)`，绑定修复用 decision ContextBuild，写入 `loop.observed(RC_REQUIRED_TOOL_FOLLOWUP_MISSING)` 并静默修复。纯项目上下文、资源盘点或“是否已有场景”这类只读问题即使命中 scenario Skill，也允许在 read/query 工具后直接给最终总结。保存/持久化这类副作用遵循 Skill 声明式语义 guardrail：`guard_unsupported_capability` 声明缺失工具集合、预检查关键词、分类 prompt、分类 JSON 字段、最终消息资源和 completion source；Runner 只解释规则，只有分类确认用户要求正式持久化且 ToolRegistry 没有对应工具时，才以 `unsupported_scenario_save_guard` 说明当前无法保存；“不要保存/仅生成草稿”的请求继续走 query-first 组合链路。

Unsupported capability guard 路径也复用同一终态门禁：Skill 私有 classifier 返回后，`AgentConversationRunner` 会先刷新 run terminal 状态；如果外部 Stop 已写入 `run.cancelled`，不会继续调用 guard synthetic completion，也不会写 `model.started/model.delta/model.completed/run.completed` 覆盖取消终态。

模型调用入口自身也复用同一终态门禁：`AgentConversationRunner._stream_model_response()` 在生成 loop trace、写 `model.started` 或调用 `AIService.chat_stream()` 前会先刷新 run terminal 状态；如果 run 已经是 `completed/failed/cancelled`，直接返回空模型结果，不再追加新的模型事件或触发 provider 调用。

用户可见回复完成路径也复用同一终态门禁：`AIService.chat_stream()` 已经返回普通自然语言或 final summary 后，Runner 在 Markdown normalization、补发/flush `model.delta`、写入 `model.completed` 和 `run.completed` 前都会刷新 run terminal 状态；如果 Stop 恰好落在 stream 结束后的后处理窗口，Runner 返回 `cancelled`，不会把 run 覆盖为 completed。

partial stream interruption 路径也复用同一终态门禁：模型已经返回部分内容后如果 provider 抛出 HTTPException，Runner 在写入 `model.stream_interrupted` 前会刷新 run terminal 状态；如果 Stop 已经写入 `run.cancelled`，不会再追加 interruption 审计事件、`model.completed` 或 `run.completed`。

late tool request suppression 路径也复用同一终态门禁：模型先输出可见 preamble、随后出现 fenced `agent_tool_request` 时，Runner 会用 `model.markdown_normalized(replace_content=true, normalization_reason=tool_request_stream_suppressed)` 撤回临时文本；在写入后续 `model.tool_request_stream_suppressed` 审计事件前也会刷新 run terminal 状态，避免 Stop 后继续追加 suppression 审计、ToolCall 或完成事件。

工具请求修复路径也复用同一终态门禁：`_repair_invalid_tool_request()` 和 `_repair_missing_required_tool_request()` 在 repair 模型返回后、解析 repaired 内容后，以及写入 `model.tool_request_repaired/model.required_tool_repaired/model.tool_request_repair_failed/model.required_tool_repair_failed` 前都会刷新 run terminal 状态；如果 Stop 恰好落在 repair 解析窗口，Runner 返回 `cancelled`，不会继续创建 ToolCall、写修复完成/失败事件或覆盖 run 终态。

内部工具请求上下文摘要也是受保护的模型上下文，不是 assistant 内容源。Runner 如果在工具执行后的下一轮模型输出中检测到 `agent_tool_request_context_summary_v1`，会把它作为 `model.tool_request_invalid` 进入一次静默修复；如果修复仍返回同类内部摘要，则写入 `model.internal_context_leak_suppressed` 审计事件并替换为安全兜底消息，保证该摘要不会进入用户可见 `model.delta`、`model.completed.content` 或 `run.completed.result.message`。

异常落库路径也复用同一终态门禁：`AgentConversationRunner.run()` 与 `complete_after_tool_results()` 的 HTTPException/Exception 处理器在调用 `AgentRuntimeService.fail_run()` 前会刷新 run terminal 状态；如果 Stop 已经写入 `run.cancelled`，异常不会再把 run 覆盖为 failed。

公共终态写入口自身也执行同一防御：`AgentRuntimeService.complete_run()` 与 `fail_run()` 在写 `run.completed/run.failed` 前会刷新 run terminal 状态；如果 run 已经是 `completed/failed/cancelled`，直接返回现有终态。这让漏掉上层 guard 的调用点也不能覆盖已经生效的取消。

EventStore 封装层也执行同一防御：`AgentRuntimeService.append_event()` 锁定 run 后会检查 terminal 状态，只允许对应的首次 `run.completed/run.failed/run.cancelled` 事件完成终态转换；一旦 terminal 事件已经存在，后续普通 late event 会直接返回最新事件，不再递增 `last_event_sequence`、创建 `AgentEvent` 或写入 Outbox。

Approval resume 路径复用同一终态门禁：已批准阻断 ToolCall 执行返回后，`AgentRunResumeService` 会先刷新 run terminal 状态；如果外部 Stop 已写入 `run.cancelled`，不会把 run 改回 running，不会调用 `complete_after_tool_results()` 启动审批后的 final summary，也不会写 `run.completed` 覆盖取消终态。

Approval resume 复用 WorkerQueue 时还必须把 `failed` queue 视为带原因的事实，而不是泛化可执行状态：已批准阻断 ToolCall 只有在没有 queue 行的兼容路径、queue 仍为 `queued/blocked_approval`，或历史 queue 为 `failed(last_error_code=approval_required_before_execution)` 时才可进入 `ToolExecutor`。如果 ToolCall 已有 queue 行但失败原因为取消、queue context mismatch、effect evidence、不可执行状态或其他非审批阻断原因，resume 必须保持 blocking，不调用 backend，也不启动审批后的 final summary。

Approval resume 的 EventStore 语义也必须和真实进展一致：如果 freshness check 通过后没有任何已批准 ToolCall 执行成功、没有 `failed_retryable` 被重新排队，且 run 仍有 blocking ToolCall，`AgentRunResumeService` 只提交 `checkpoint.freshness_checked` 并保持 `needs_human/resumed=false`，不得追加 `run.resumed`。`run.resumed` 只表达本次恢复确实推进了执行、调度或阻断清理，不能用来表示一次仍被阻断的 resume 检查；如果本次恢复已经把 `failed_retryable` 重新 enqueue，这个 tool_call_id 即使历史上残留在 `blocking_tool_call_ids_json` 中，也必须从剩余 blocking 计算中移除。

Resume 响应形状也必须保持稳定：`AgentRunResumeService.resume_run()` 的所有返回路径都必须提供 `scheduled_tool_call_ids` 和 `executed_tool_call_ids` 数组；terminal/noop、freshness pause 或 no-progress blocking 等没有实际调度/执行工具的路径返回空数组，不能依赖 API router 的默认值补字段。两份 Harness 文档还以 `Required Agent Run resume payload contract` 机器契约固定 `AgentRunResumeRead` 字段顺序和稳定数组字段，并由专项回归同时校验 route response 与 direct service payload。

WorkerQueue claim 入口也复用同一终态门禁：`AgentWorkerQueueService.claim_next()` 会在发放 queue/ToolCall lease 前锁定对应 run；如果 run 已经 cancelled/failed/completed，该 ToolCall 转为 `obsolete(agent_run_cancelled_before_tool_execution)`，queue 标为 failed，不返回可执行 queue item，也不调用 `AgentToolRuntime.execute()`。

WorkerQueue claim 还必须尊重 queue/run/call 归属和 ExecutionLedger 的 ToolCall 当前状态：claim 发放 lease 前必须确认 queued item 指向真实 ToolCall、queued item 的 `run_id` 与 ToolCall 的 `run_id` 一致，且对应 AgentRun 仍存在；若 ToolCall 已不存在，只能把 queue item 标为 `failed(tool_call_missing)` 并清理 queue lease，不得返回可执行 item 或短暂发放 active lease；若 AgentRun 已缺失，只能把 queue item 标为 `failed(run_missing)`，把仍为 planned 的 ToolCall 写为 `failed/execution_phase=blocked`，记录 `run_context_missing_before_execution` 并清理 ToolCall lease，不得先发放 active lease 再等待 executor 兜底；若 run 归属不一致，只能把 queue item 标为 `failed(tool_call_queue_context_mismatch)` 并清理 queue lease，保留 ToolCall 原状态，不得用 queue 上错误 run 的 terminal 状态或权限上下文覆盖 ToolCall。归属一致后，只有 `planned` ToolCall 可以从 queued item 领取为 `leased`；`uncertain/reconciling` 走 reconcile-required 阻断，并必须清理 queue 与 ToolCall 残留 lease 字段，避免待 reconcile 状态继续暴露 active worker lease；其他非 claimable 状态说明队列行已经陈旧，只能把 queue item 标为 `failed(tool_call_not_claimable)` 并清理 lease 字段，不得把 `obsolete/succeeded/failed/failed_retryable/needs_migration/manual_intervention/leased/running_pre_effect` 等状态改回 `leased`。`failed_retryable` 的恢复必须由 resume service 先显式重置为 `planned` 后重新 enqueue。

WorkerQueue active lease 路径也必须尊重 queue/run/call 归属：`heartbeat()` 与 `recover_orphans()` 在读取 queue 对应 run 做 terminal 判断、按 ToolCall 状态续约或按 effect evidence 重排/转 reconcile 前，必须确认 queue `run_id` 与 ToolCall `run_id` 一致。若不一致，queue 只能标为 `failed(tool_call_queue_context_mismatch)` 并清理 queue lease；由于 heartbeat/orphan 已经处于 active lease 窗口，`leased/running_pre_effect` ToolCall 还必须转为 `uncertain`、清理 ToolCall lease，并记录 `reconcile_required_after_queue_context_mismatch`，不得用错误 run 的 terminal 状态覆盖 ToolCall，也不得留下无人接管的 active ToolCall lease。

failed_retryable 的 resume 重排是一个新的执行窗口，而不是沿用上一轮发送窗口：`AgentRunResumeService._schedule_retryable_tool_calls()` 只有在没有 active queued/leased queue item 时才会重新 enqueue，并在把 ToolCall 改回 `planned` 前清理 `execution_phase`、effect submission state/boundary、downstream send/transport/acceptance 证据、ToolCall lease/heartbeat 和 error 字段，再记录 `resume_retry_same_idempotency_key`。这样 same-key safe retry 仍复用幂等键，但不会把旧 send intent、旧 heartbeat 或旧错误带入下一次执行；若 run 的 blocking list 仍包含该 ToolCall，本次已调度 id 会被视为已恢复进展并从 blocking list 清除，避免前端 action state 继续显示需要人工处理。

WorkerQueue heartbeat 续约也复用同一终态门禁：`AgentWorkerQueueService.heartbeat()` 会在延长 queue/ToolCall lease 前锁定对应 run；如果 run 已经 cancelled/failed/completed，不再延长 lease，而是把 queue 标为 failed，并在 ToolCall 仍为 planned/leased 或 pre-send-intent `running_pre_effect(effect_submission_state=none,effect_boundary_crossed=false)` 时转为 `obsolete(agent_run_cancelled_before_tool_execution)`，避免 Stop 后 worker 心跳持续保活已取消任务。

WorkerQueue heartbeat 还必须只作用于活跃租约：续约查询必须同时匹配 queue id、worker id 和 `status=leased`；completed/failed/blocked/queued 等非活跃 queue item 不得因为旧 `lease_owner` 残留而被旧 worker 心跳刷新 lease，也不得更新 ToolCall `last_heartbeat_at` 或 `lease_expires_at`。

WorkerQueue heartbeat 同时必须确认 ToolCall 仍处于可保活执行态：`running_pre_effect` 可以承载 send intent/transport/backend/effect 发送窗口里的真实执行心跳；`leased` 只有在没有 effect submission evidence 时才允许刷新 queue lease 与 ToolCall heartbeat。如果 ToolCall 已经 succeeded、failed、obsolete、uncertain、reconciling 或缺失，queue 只能标为 failed 并清理 lease，不得刷新 ToolCall `last_heartbeat_at` 或 `lease_expires_at`；如果 `leased` ToolCall 已记录 send intent / transport sent / backend accepted / effect committed，或 `effect_boundary_crossed=true`，queue 必须标为 `failed(tool_call_heartbeat_after_effect_submission_started)`，ToolCall 必须转为 `uncertain`、清理 ToolCall lease，并保留 effect submission 证据交给 ReconcileWorker。

WorkerQueue 的 completed/failed 终态 helper 也必须清理队列自身 lease：`mark_completed()` 与 `mark_failed()` 写入终态时同步清空 queue `lease_owner` 和 `lease_expires_at`，让队列终态、审计快照和后续 worker 心跳查询都不再携带已结束租约。

ToolCall 进入执行器终态或待 reconcile 状态时也必须清理自身 lease：`ToolExecutor` 在 succeeded、failed、manual_intervention、obsolete、uncertain 路径中先把 worker id 写入 `policy_reason_json.execution_context.worker_id`，再清空 ToolCall `lease_owner` 与 `lease_expires_at`；执行归属保留为审计证据，但终态 ToolCall 不再作为 active lease 呈现。

ToolExecutor claim 后缺执行上下文也必须作为执行前拒绝边界处理：`AgentWorkerQueueService.claim_next()` 会先拒绝领取前已缺失的 AgentRun；如果 WorkerQueue 已领取 queue/ToolCall lease 后，`ToolExecutor.execute_next()` 在 claim 与执行上下文解析之间又发现 `AgentRun` 消失，或 run 绑定 user 已缺失，不得继续进入 `execute_tool_call()`、backend adapter 或普通工具事件；queue 必须标为 failed 并清理 queue lease，ToolCall 必须写为 `failed/execution_phase=blocked`、记录 `run_missing/user_missing` 与对应恢复决策、清理 ToolCall lease。worker id 只保留在 `policy_reason_json.execution_context.worker_id` 中作为审计证据，不能继续暴露为 active lease。

工具执行入口保留同一终态兜底：queued ToolCall 即使绕过 worker claim 直接进入 `ToolExecutor.execute_tool_call()`，也会在审批/权限检查、`tool.running`、send-intent 记录和 backend adapter 调用前重新读取 run terminal 状态；如果 run 已经 terminal 且 ToolCall 仍处在 `planned/leased` 执行前窗口，或是 pre-send-intent `running_pre_effect(effect_submission_state=none,effect_boundary_crossed=false)`，该 ToolCall 转为 `obsolete(agent_run_cancelled_before_tool_execution)`，queue 标为 failed，不调用 backend，也不追加任何 terminal 后的普通 Tool 事件。

工具执行入口还必须以 ExecutionLedger 的 ToolCall 状态、queue context 和 effect submission evidence 为最终事实源：`ToolExecutor.execute_tool_call()` 在审批、权限、`tool.running`、send-intent 与 backend adapter 前，必须先确认传入 queue item 的 `tool_call_id/run_id` 与 ToolCall 一致；若 stale direct caller 把错误 queue item 传给执行器，执行器只能把 queue 标为 `failed(tool_call_queue_context_mismatch)` 并清理 queue lease，queue 所属 active ToolCall 转为 `uncertain`、清理 ToolCall lease，并写入 `reconcile_required_after_queue_context_mismatch`，不得调用 backend，也不得把错误 queue context 绑定到另一个 ToolCall。归属一致后，执行器只允许没有 effect submission evidence 的 `planned/leased` 进入执行；若 stale queue 或 direct caller 传入已经 `succeeded/failed/obsolete/uncertain/reconciling/running_pre_effect` 等不可执行 ToolCall，执行器只失败仍未终态的 queue 为 `tool_call_not_executable` 并清理 queue lease，保留 ToolCall 原 status/output/error/recovery decision 与事件序列，不重复调用 backend 或追加 `tool.completed`。若 `planned/leased/running_pre_effect` 已记录 send intent / transport sent / backend accepted / effect committed / unknown，或 `effect_boundary_crossed=true`，执行器必须先把 queue 标为 `failed(tool_call_execution_after_effect_submission_started)`、ToolCall 转为 `uncertain`、清理 ToolCall lease，并保留 effect evidence 交给 ReconcileWorker；不得重新写 `tool.running/tool.send_intent_recorded` 或调用 backend。这个状态/evidence 门禁在 terminal run 下同样优先于 obsolete 分支：已经 succeeded/failed/obsolete/uncertain/reconciling 或已进入发送/效果窗口的 ToolCall 不得因为 run terminal 被覆盖为 obsolete。

WorkerQueue orphan recovery 也复用同一终态门禁：`AgentWorkerQueueService.recover_orphans()` 扫描到过期 leased queue 行时，会先锁定对应 run；active run 仍按原语义把 queue 重新置为 queued、ToolCall 回到 planned，但 terminal run 下不得复活任务，而是把 queue 标为 failed，并在 ToolCall 仍为 planned/leased 或 pre-send-intent `running_pre_effect(effect_submission_state=none,effect_boundary_crossed=false)` 时标为 `obsolete(agent_run_cancelled_before_tool_execution)`、清理 lease owner/expires，避免后台恢复扫描在 Stop 后重新触发工具执行。

WorkerQueue orphan recovery 还必须尊重 ToolCall 当前状态和 effect submission boundary：对应 ToolCall 仍是 `leased` 且没有 effect submission evidence 时，过期 queue 可以恢复为 queued 且 ToolCall 回到 planned；`running_pre_effect` 只有在 `effect_submission_state` 仍为空/`none` 且 `effect_boundary_crossed=false` 时才可同样重排。若 ToolCall 已经 succeeded、failed、obsolete、uncertain 或缺失，queue 只能标为 failed 并清理 queue lease，不得把已结束工具复排；若 `leased/running_pre_effect` 已记录 send intent / transport sent / backend accepted / effect committed，或 `effect_boundary_crossed=true`，queue 必须标为 `failed(tool_call_orphaned_after_effect_submission_started)`，ToolCall 必须转为 `uncertain`、清理 ToolCall lease，并保留 effect submission 证据交给 ReconcileWorker。

安全工具执行完成前也复用同一终态门禁：`ToolExecutor.execute_tool_call()` 在 read-only / deterministic compute 工具的 `AgentToolRuntime.execute()` 返回后，会在写 `tool.effect_committed/tool.completed`、标记 ToolCall succeeded 或完成 queue 前刷新 run terminal 状态；如果 run 已经 cancelled，该 ToolCall 转为 `obsolete(agent_run_cancelled_during_tool_execution)`，queue 标为 failed，不进入后续 `tool.result_observed` 或模型回灌。

非安全 effectful 工具执行完成前也必须走终态对账门禁：如果 `AgentToolRuntime.execute()` 已返回工具输出，但 run 在返回前已经进入 cancelled/failed/completed，`ToolExecutor` 不得继续把 ToolCall 和 WorkerQueue 标为成功，也不得追加 `tool.completed`；ToolCall 需要保留脱敏 output 与 output_hash，转为 `uncertain(agent_run_cancelled_after_tool_effect)`，`recovery_decision=reconcile_required_after_run_terminal`，queue 标为 failed，由 reconcile/runbook 面板确认外部副作用是否已真实提交。即使 run 已 terminal，只要仍有 `uncertain/reconciling` ToolCall，Action State 仍应暴露 `reconcile_run`，ReconcileWorker 可处理这些 ToolCall 的对账结果，但必须保持 run 的 terminal 状态不被 reopen、completed、failed 或 migration_blocked 覆盖，EventStore 仍不得追加 terminal 后普通事件。若 terminal run 的对账结果需要 backend contract migration，可创建 open migration block 并让 ToolCall 进入 `needs_migration`，但 run 仍保持原 terminal 状态；解决该 block 后 ToolCall 回到 `reconciling`，run 仍不恢复 active，由下一次 `reconcile_run` 继续收敛 ToolCall 事实。Action State 对 Runbook 入口必须区分干净完成和带恢复上下文的完成：只有 `run_completed` 这一个阻断原因时 `open_runbook` 保持禁用；如果 completed run 仍有 uncertain ToolCall、open migration block 或其他恢复原因，`open_runbook` 必须启用，便于前端进入 Runbook 查看残留恢复上下文；`resolve_migration.details` 在 terminal run 上也必须携带 `run_status`、`run_terminal`、`resolve_preserves_terminal_run`、`post_resolve_next_action=reconcile_run` 和 `tool_call_status_after_resolve=reconciling`，避免右侧操作区在点击前缺少 terminal-preserve 语义。Runbook 对 terminal migration block 的 recommendation 也必须表达同一事实：`reason=open_migration_block_on_terminal_run`，details 包含 `run_status`、`run_terminal`、`resolve_preserves_terminal_run`、`post_resolve_next_action=reconcile_run` 和 `tool_call_status_after_resolve=reconciling`，避免恢复面板把 resolve block 误导为 resume。`MigrationCoordinator.resolve_block()` 在 terminal run 上返回的 `checkpoint_freshness` 也必须携带 `terminal_run_preserved`、`terminal_run_status`、`resolve_preserves_terminal_run`、`post_resolve_next_action` 和 `tool_call_status_after_resolve`；`post_resolve_next_action` 必须由 ToolCall 当前状态决定，仍需对账时为 `reconcile_run`，已收敛的幂等重复 resolve 为 `none`，使直接调用 resolve API 的前端同样不会把 freshness 的 `continue_from_checkpoint` 误读为可 resume 或重复提示过期恢复动作。

Run Summary 的轻量按钮语义必须与同一事实源对齐：只要 `open_migration_block_count > 0`，`AgentRuntimeService.get_run_summary()` 的 `can_resume` 必须为 `false`，即使 run 仍是非终态 `migration_blocked` 或存在 `blocking_tool_call_ids`；恢复入口应由 Action State 暴露 `resolve_migration`，否则前端会在 RunInspector 上得到可 resume 信号，但 resume service 实际以 `409 run_migration_blocked` 拒绝。

Run Summary 暴露的 `blocking_tool_call_ids` 也必须是稳定去重后的摘要级定位列表；底层 `blocking_tool_call_ids_json` 如果因历史恢复或兼容路径残留重复 id，Summary 不得把重复项传给 RunInspector 或后续 Action State 派生入口。

反过来，如果 `run.status=migration_blocked` 但没有 open migration block，Action State 必须把它当作 `resume_run` 候选，和 Summary 的 `can_resume=true` 保持一致；这类残留状态应交给 resume/freshness gate 收敛，而不是只暴露 cancel。

同一规则也适用于 pending approval：只要 `pending_approval_count > 0`，Summary 的 `can_resume` 必须为 `false`，即使 run 已进入 `needs_human` 并带有 blocking ToolCall；此时 Action State 应优先暴露 `review_approvals`，审批通过后才由 resume service 接管执行已批准的阻断 ToolCall。

safe retry 的入口也必须在 Summary 中可见：如果 run 内存在 `failed_retryable` ToolCall，且没有 pending approval 或 open migration block，Summary 的 `can_resume` 必须为 `true`，与 Action State 的 `retryable_tool_calls` / `resume_run` 保持一致；resume service 会开启新的执行窗口，把该 ToolCall 清理旧发送事实后重置为 `planned` 并重新入队。

Action State 的 `primary_action_ids` 不得复用固定 `actions` payload 顺序；后端必须按 `review_approvals`、`resolve_migration`、`reconcile_run`、`resume_run`、`open_runbook`、`cancel_run` 的恢复优先级过滤 enabled action。这样 pending approval、open migration block、uncertain ToolCall、safe retry 和恢复 Runbook 都能先于取消入口成为右侧主操作，`cancel_run` 只作为最后兜底。

Action State 的 action 级 `resource_ids` 还必须是稳定去重后的定位列表，不能把同一个 ToolCall 因为同时出现在 blocking 与 `failed_retryable` 集合而输出两次；来源分类保留在 `details.blocking_tool_call_ids`、`details.pending_approval_tool_call_ids` 和 `details.retryable_tool_call_ids` 中。

Action State 同时暴露 `resource_item_ids` 作为同一 action 关联资源的 Codex-style timeline/debug item 定位列表：`review_approvals` 指向待审批目标 ToolCall 的 `agent-tool-call://{run_id}/{tool_call_id}`，`resume_run` 与 `reconcile_run` 指向 ToolCall item，`resolve_migration` 指向 `agent-migration-block://{run_id}/{block_id}`。`resource_ids` 继续作为 hydrate API 的业务 id，`resource_item_ids` 只用于前端高亮、下载包或调试 item 定位，不新增数据库字段，也不改变 action 状态机。

Action State 读取资源 id 时必须显式排序：ToolCall 资源按 `step_index`、`attempt_index`、内部 id 排序，Approval 与 MigrationBlock 资源按 `created_at`、内部 id 排序。该顺序是前端右侧操作区和刷新 diff 的稳定契约，不应依赖 SQLite/MySQL 当前查询计划的偶然返回顺序。

上述 Action State 主操作优先级、资源排序/去重和 `resource_item_ids` 语义必须进入 Harness 机器可读契约块，并由测试从文档抽取后对齐代码常量与实际路由输出；这类非字段语义不得只保留在散文说明里。

工具请求解析/修复错误事件也遵循同一有界诊断原则：`model.tool_request_invalid.payload.error_message`、对应 LoopObservation 的 `observation_json.error_message`、修复 prompt 中嵌入的错误摘要，以及 `model.tool_request_repair_failed.payload.error_message` 都只保留短错误原文或 `agent_error_message_summary_v1` 有界摘要；长 parse/repair 异常以 preview、截断标记、原始长度、hash 和 `full_error_reference` 表达，不把完整模型输出解析异常尾部复制到 EventStore/SSE timeline 或下一次模型修复上下文。相关 `content_preview` 也只保留短内容或 `agent_content_preview_summary_v1` 有界摘要，长模型输出以 `agent_content_preview_truncated`、长度、hash 和 `full_content_reference` 表达。合法工具请求的 `model.completed.content` 在 `requested_tool=true` 时同样只作为 EventStore/SSE 诊断预览：短工具请求保持字符串兼容，超长内部 `agent_tool_request` 使用 `agent_content_preview_summary_v1`、截断标记、长度、hash 与 `full_content_reference=AgentConversationRunner.model.completed.tool_request.content`；Runner 解析和 ToolCall 创建仍使用内存里的完整模型输出，但下一轮模型上下文只回放 `agent_tool_request_context_summary_v1` 有界摘要，包含 tool_name、短 input/evidence JSON、reason 摘要和 `source_content_preview`。合法工具请求的模型规划理由也只作为有界诊断文本进入事件：`model.tool_request_detected.reason/decision_reason` 与后续 tool trace 的 `decision_reason` 对短 reason 保持兼容，超长 reason 使用同一 `agent_error_message_summary_v1` 形态，`full_error_reference=AgentConversationRunner.model.tool_request_detected.reason` 或 `AgentConversationRunner.tool_trace.decision_reason`。

required follow-up 静默修复失败时也保持同一边界：query-first 规则触发 `model.required_tool_missing` 后，如果修复模型输出仍无法解析，`model.required_tool_repair_failed.payload.error_message` 只保留短错误原文或 `agent_error_message_summary_v1` 有界摘要，并使用 `full_error_reference=AgentConversationRunner.model.required_tool_repair_failed`；`model.required_tool_missing` 和 `model.required_tool_repair_failed` 的 `content_preview` 同样只保留短内容或 `agent_content_preview_summary_v1` 有界摘要，避免业务 recipe 修复失败把完整模型输出或解析异常尾部复制到 EventStore/SSE timeline。

unsupported capability classifier 的 provider/HTTP 失败、非 JSON 响应或成功分类结果中的长 `reason` 只影响 guard 判定与诊断表达，不改变正常对话路径；`AgentConversationRunner._classify_unsupported_capability_intent()` 捕获 HTTPException 后写入 `agent_unsupported_capability_classification_failed` warning log，解析失败时写入 `agent_unsupported_capability_classification_invalid_json` warning log，成功分类时写入 `agent_unsupported_capability_classified` info log，并把长错误/长响应/长 reason 收口为 `agent_error_message_summary_v1`，`full_error_reference=AgentConversationRunner.unsupported_capability_classifier`、`AgentConversationRunner.unsupported_capability_classifier.invalid_json` 或 `AgentConversationRunner.unsupported_capability_classifier.reason`。这些日志不复制完整 provider 响应尾部，也不会新增前端事件或 response 字段。

Unsupported capability guard 的 synthetic completion 只在 run 仍未 terminal 时生成：若 classifier 调用期间 run 被 Stop/cancel，Runner 返回 `cancelled`，不再写 guard synthetic reply 的 `model.started/model.delta/model.completed/run.completed` 事件。

ToolPolicyResolver 会把工具策略判定固化到 `AgentToolCall.policy_reason_json.policy_context`：该 envelope 记录 `policy_version_hash`、tool name/version、base/resolved side effect、base/resolved replay policy、approval policy、approval reason、active/volatile/frozen policy evidence 计数、mixed evidence 标记和 `policy_hash`。这样 ToolCall Detail、Runbook 和后续评测可以从一个稳定 hash 解释“为什么该工具需要审批、为什么 replay policy 被提升为 require_revalidation、以及本次策略解析基于哪些证据类别”，形态上更接近 openai/codex per-turn `approval_policy` 与工具上下文，但不暴露原始 evidence 内容。

ToolExecutor 在工具真正跨过 runtime/backend routing 边界后，还会把 `policy_reason_json.dispatch_trace` 写入 ToolCall：该白名单 trace 记录 dispatch trace version、tool/run/runtime snapshot 标识、tool name/version、schema/manifest hash、`AgentToolRouter.resolve`、`AgentToolRuntime.execute`、backend handler、backend contract 标识、resolved side effect/replay policy、最终状态和 `dispatch_trace_hash`。这让 ToolCall Detail、Runbook 和评测可以解释“模型请求的工具到底被哪个 router/runtime 分派到了哪个后端 handler”，形态上对齐 openai/codex 的 tool router/orchestrator/dispatch trace 分层，但不复制原始 input、output、evidence 或业务 payload。若 effect 已提交但后续 EventStore 写入失败，ToolExecutor 会在标记 `uncertain(eventstore_write_failed_after_effect)` 后重新生成 dispatch trace，确保 trace 中的 `status` 与 `effect_submission_state` 表达最终恢复状态，而不是保留写事件前的成功态。

`AgentRunRead.item_id=agent-run://{run_id}` 把 AgentRun 作为 Codex-style turn/run 自身的 timeline/debug/download item 暴露。它由现有 `run_id` 派生，不新增数据库列，不替代 run-scoped API 的 `run_id`，也不替代 SSE/EventStore 的 `event_seq` cursor；Summary、Transcript、Export、Resume、Action State 和 Event Snapshot 中嵌套的 run 都使用同一个值，方便前端把顶层 turn、事件、工具、审批和恢复操作串到同一条调试链上。

`AgentRuntimeSnapshotRead.item_id=agent-runtime-snapshot://{snapshot_id}` 把冻结 runtime snapshot 作为独立 timeline/debug/download item 暴露。它由现有 `snapshot_id` 派生，不新增数据库列，不替代 `runtime_snapshot_id` 业务引用；Run、ToolCall、Approval CAS 和 dispatch/execution context 仍用 `runtime_snapshot_id` 绑定当时工具/策略版本，`item_id` 只负责调试定位和导出包 item key。

`AgentContextBuildRead.item_id=agent-context-build://{run_id}/{context_build_id}` 把一次 decision ContextBuild 作为独立 timeline/debug/download item 暴露。它由现有 `run_id/context_build_id` 派生，不新增数据库列，不替代 `context_build_id` 或 `decision_context_build_id` 的业务引用；LoopObservation、ToolCall 和修复/停止诊断仍通过 `context_build_id` 绑定决策上下文，`item_id` 只用于前端高亮、导出包定位和调试 item key。

`AgentLoopObservationRead.item_id=agent-loop-observation://{run_id}/{observation_id}` 把一次 loop observation 作为独立 timeline/debug/download item 暴露。它由现有 `run_id/observation_id` 派生，不新增数据库列，不替代 `observation_id` 或 `decision_context_build_id`；ContextBuild 继续解释该观察基于哪次决策上下文，LoopObservation item 负责定位修复、停止和 RootCause 诊断本身。

`AgentToolCallRead` 暴露 `item_id=agent-tool-call://{run_id}/{tool_call_id}`，由 ToolCall/ExecutionLedger 事实派生，作为 ToolCall Detail、审批响应、conversation export 与前端 timeline/debug item 的稳定 key；它与 EventStore 事件 `item_id=agent-event://{run_id}/{event_seq}` 分离，不新增数据库列，也不把 ToolCall item identity 写入事件 payload。

`AgentApprovalRead` 暴露两层稳定定位：`item_id=agent-approval://{run_id}/{approval_id}` 表示审批记录自身的 timeline/debug/download item，`tool_call_item_id=agent-tool-call://{run_id}/{tool_call_id}` 表示审批请求绑定的目标 ToolCall item。前者用于审批列表、ToolCall Detail current approval、approve/reject 响应和 conversation export 直接定位审批记录；后者用于高亮或继续操作被审批的 ToolCall。两个字段都由现有 run/approval/tool facts 派生，不新增数据库列，也不改变审批状态机或 EventStore payload。

`AgentApprovalLineageRead` 也暴露稳定 item 定位：`item_id=agent-approval-lineage://{run_id}/{approval_lineage_id}` 表示审批 lineage 自身的 timeline/debug item，`tool_call_item_id=agent-tool-call://{run_id}/{tool_call_id}` 指向该 lineage 绑定的目标 ToolCall item。该 identity 从现有 run/lineage/tool facts 派生，不新增数据库列，也不改变 ApprovalMutationGuard 的 CAS、lineage epoch 或事务状态机。

`AgentApprovalMutationLogRead` 同样补齐审计 item 定位：`item_id=agent-approval-mutation://{run_id}/{mutation_log_db_id}` 表示本次 approve/reject/supersede/expire mutation 自身的 timeline/debug item，`tool_call_item_id=agent-tool-call://{run_id}/{tool_call_id}` 指向被该 mutation 影响的目标 ToolCall item。该 identity 从现有 mutation log 主键与 run/tool facts 派生，不新增数据库列，也不改变 ApprovalMutationGuard 的 CAS、lineage 或事务状态机。

`AgentMigrationBlockRead.item_id` 暴露 `agent-migration-block://{run_id}/{block_id}`，把兼容阻断作为独立 timeline/debug/download item 定位；当 block 绑定 ToolCall 时，`tool_call_item_id=agent-tool-call://{run_id}/{tool_call_id}` 指向被阻断的目标 ToolCall item，未绑定 ToolCall 时为 `null`。这两个字段都由现有 `run_id/block_id/tool_call_id` 事实派生，不新增数据库列，也不改变 reconcile 或 migration resolve 状态机。

Memory 审计事件也按全局审计事实暴露稳定 item identity：`AgentMemoryUsageEventRead.item_id=agent-memory-usage-event://{id}`、`AgentMemoryStalenessEventRead.item_id=agent-memory-staleness-event://{id}`、`AgentMemoryValidationEventRead.item_id=agent-memory-validation-event://{id}`。这些 identity 从对应审计表主键派生，不新增数据库列，也不替代 `id`、`memory_id`、`run_id`、EvidenceRef 或 validation source 过滤字段；它们只用于 Memory 审计列表、调试定位和导出包 item key。

Memory feedback process 的结果行也补齐稳定 item identity：`results[].item_id=agent-memory-feedback-result://{usage_event_id}`，字段顺序固定为 `item_id,usage_event_id,processed,decision`。这些 item id 从 Memory usage event id 派生，不新增数据库列，也不改变 feedback worker 的置信度/陈旧度 delta、validation/contradiction 记录、幂等 already-processed 分支或 admin process 语义；它们只用于稳定定位 feedback 处理结果行和导出包 debug item。

Runbook catalog 与 run diagnosis recommendation 也作为恢复诊断 item 暴露稳定 identity：`AgentRunbookRead.item_id=agent-runbook://{runbook_id}`，`AgentRunbookRecommendationRead.item_id=agent-runbook-recommendation://{run_id}/{runbook_id}/{stable_digest}`。前者由静态 runbook id 派生，后者由 run id、runbook id 和公开稳定的推荐身份字段派生，不新增数据库列，不替代 `runbook_id`、`tool_call_id`、`action` 或 recommendation details；Runbook 面板、导出包和 debug timeline 可直接用该 item key 定位诊断建议，同时保持 recommendation 规则、排序、severity、action 和恢复状态机不变。

Agent Alert 也按告警事实暴露稳定 item identity：`AgentAlertRead.item_id=agent-alert://{alert_id}`，由静态 `ALERT_RULES.alert_id` 或动态 release gate alert id 派生；它不新增数据库列，不替代 `alert_id`、`metric_key`、`runbook_id` 或 dashboard `monitoring_alerts_clear` 的阻断语义。`AgentAlertService.snapshot()` 和 Readiness Dashboard 嵌套 `alerts[]` 复用同一 item key，使告警列表、发布门禁、Runbook 入口和导出包能稳定定位同一个 firing alert。

Release gate snapshot 内的 tool row、level row 和 violation row 也补齐稳定 item identity：`AgentReleaseGateToolRead.item_id=agent-release-gate-tool://{tool_name}/{tool_version}`，`AgentReleaseGateLevelRead.item_id=agent-release-gate-level://{level}`，`AgentReleaseGateViolationRead.item_id=agent-release-gate-violation://{tool_name}/{reason}`。这些 item id 从当前门禁快照的公开字段派生，不新增数据库列，也不改变 rollout level、tool matrix 排序、violation reason、promotion blocker 或 dashboard readiness 判定；它们只用于前端定位发布门禁重复项和导出包 debug item。

Release gate minimum go-live check row 也补齐稳定 item identity：`minimum_go_live.checks[].item_id=agent-minimum-go-live-check://{requirement_id}`，字段顺序固定为 `item_id,requirement_id,label,status,details`。这些 item id 从最低上线要求 id 派生，不新增数据库列，也不改变 requirement ordering、status、details、minimum go-live pass、promotion blocker 或 dashboard readiness 判定；它们只用于前端稳定定位最低上线要求 check 和导出包 debug item。

Release gate go-live gate check row 也补齐稳定 item identity：`go_live_gates.tiers[].checks[].item_id=agent-go-live-gate-check://{priority}/{gate_id}`，字段顺序固定为 `item_id,gate_id,label,status,evidence`。这些 item id 从 go-live priority 与 gate id 派生，不新增数据库列，也不改变 tier ordering、gate ordering、status、evidence、go-live pass、promotion blocker 或 dashboard readiness 判定；它们只用于前端稳定定位上线门禁分层 check 和导出包 debug item。

Release gate final delivery category/check row 也补齐稳定 item identity：`final_delivery.categories[].item_id=agent-final-delivery-category://{category}`，嵌套 `checks[].item_id=agent-final-delivery-check://{category}/{artifact_id}`；category 字段顺序固定为 `item_id,category,external_scope,required_artifact_ids,delivered_artifact_ids,external_scope_artifact_ids,missing_artifact_ids,checks,pass`，check 字段顺序固定为 `item_id,artifact_id,label,status,evidence`。这些 item id 从 final delivery category 与 artifact id 派生，不新增数据库列，也不改变 external scope、artifact ordering、status、evidence、final delivery pass、promotion blocker 或 dashboard readiness 判定；它们只用于前端稳定定位最终交付 category/check 和导出包 debug item。

Promotion assessment 的 blocker row 也补齐稳定 item identity：`blockers[].item_id=agent-promotion-blocker://{target_level}/{source}/{reason}`。这些 item id 从 promotion blocker 的公开稳定字段派生，不新增数据库列，也不改变 target level、blocker source、reason、severity、details、promotion decision 或 dashboard readiness 判定；它们只用于前端稳定定位晋级阻断项和导出包 debug item。

Promotion assessment 的 check row 也补齐稳定 item identity：`checks[].item_id=agent-promotion-check://{target_level}/{name}`，字段顺序固定为 `item_id,name,status,details`。这些 item id 从目标级别与 check name 派生，不新增数据库列，也不改变 target level、check ordering、status、details、promotion decision 或 dashboard readiness 判定；它们与 `AgentDashboardCheckRead` / dashboard `checks[]` 分离，只用于前端稳定定位晋级评估 check 和导出包 debug item。

Readiness Dashboard、Agent Launch Audit 与 Agent Backend Completion Audit 共享的 check row 也补齐稳定 item identity：`AgentDashboardCheckRead.item_id=agent-dashboard-check://{name}`。该 item id 只从公开 check name 派生，不新增数据库列，也不改变 check 排序、状态、severity、readiness、launch ready 或 backend completion 判定；它只用于前端稳定定位 dashboard/audit 重复诊断项和导出包 debug item。Promotion assessment 的自由形态 checks 不复用 `AgentDashboardCheckRead`，继续保持原摘要结构。

Fault Injection catalog case 与 run result 也补齐稳定 item identity：`AgentFaultInjectionCaseRead.item_id=agent-fault-injection-case://{case_id}`，`AgentFaultInjectionResultRead.item_id=agent-fault-injection-result://{run_id}/{case_id}`。这些 item id 从生产硬化用例 id 与执行 run id 派生，不新增数据库列，也不改变 required fault case set、执行 handler、coverage ratio、dashboard readiness 或 go-live 判定；它们只用于前端稳定定位故障注入目录/执行结果和导出包 debug item。

WorkerQueue audit 的 expired lease 与 duplicate active lease 诊断项也补齐稳定 item identity：`expired_leases[].item_id=agent-worker-queue-expired-lease://{queue_id}`，`duplicate_active_leases[].item_id=agent-worker-queue-duplicate-active://{tool_call_id}`。这些 item id 从现有 queue/tool facts 派生，不新增数据库列，也不改变 claim、heartbeat、orphan recovery、lease scan stability、告警或 dashboard readiness 判定；它们只用于前端稳定定位 worker queue 审计重复项和导出包 debug item。

Event Replay stress audit 的 run 行与 cursor 行也补齐稳定 item identity：`run_audits[].item_id=agent-event-replay-run://{run_id}`，`cursor_audits[].item_id=agent-event-replay-cursor://{run_id}/{after_sequence}`。这些 item id 从现有 run id 与 run-scoped cursor 事实派生，不新增数据库列，也不改变 EventStore、SSE Last-Event-ID、`event_seq`、cursor window 或 replayable 判定；它们只用于前端稳定定位 replay stress audit 的重复诊断项和导出包 debug item。

Agent observability 接口的性能边界是 dashboard、alerts、metrics 和 promotion 的内部实现约束，不改变公开 schema：`AgentReadinessDashboardService.snapshot()` 在一次请求内复用已计算的 metrics 和 release gate snapshot，`AgentAlertService.snapshot()` 可接收 dashboard 传入的 metrics/release gate，`AgentReleaseGateService.promotion_assessment()` 把同一 release gate 传入 dashboard，避免嵌套调用重复跑完整 metrics 聚合。Event Replay stress audit 保持抽样 run/cursor payload 不变，但批量读取抽样 run 的 events 后在内存复用；`event_replay_gap_total` 使用按 run 聚合的事件序列完整性判断，避免逐 run 调用 `audit_run()` 加载事件明细。

RootCause rule governance audit 的 violation 行也补齐稳定 item identity：`violations[].item_id=agent-root-cause-rule-violation://{rule_id}/{violation}`。这些 item id 从现有 rule id 与 violation 类型派生，不新增数据库列，也不改变 priority band、fallback rule、RootCause matching、`root_cause_rule_missing_total` 或 dashboard readiness 判定；它们只用于前端稳定定位 RootCause 治理审计违规项和导出包 debug item。

ToolExecutor 会把执行侧上下文固化到 `AgentToolCall.policy_reason_json.execution_context`：成功提交效果、backend capability guard 阻断、审批/权限 guard 阻断、backend exception 失败以及 eventstore 写入失败后的 uncertain recovery，都会记录 tool/run/runtime snapshot、worker、tool status、execution/effect state、backend contract/schema hash/effect capability、resolved policy、approval lineage/epoch/approved approval、input/output hash、recovery decision、error code、error message hash 与 `execution_context_hash`。这让 ToolCall Detail、Runbook 和评测能够从同一个摘要解释“本次工具执行由哪个审批 lineage 放行、打到了哪个后端契约、是否跨过效果边界、失败或恢复原因是什么”，形态上继续对齐 openai/codex 的 `ToolCtx`/`ApprovalCtx`/sandbox attempt 组合，但不复制原始 input、output、evidence 或 error message。Runbook 诊断在 `tool_call_uncertain` 和 `backend_capability_degraded` recommendation 的 `details.execution_context` 与 `details.dispatch_trace` 中只嵌入白名单摘要，使恢复面板能直接展示执行上下文、router/runtime/backend handler、schema/manifest hash 和调度状态，同时仍要求完整 payload 通过 ToolCall Detail 按权限读取。

ToolCall 失败终态的错误消息也保持有界：backend 工具异常写入 `tool_execution_failed`，effect 后 EventStore 写失败写入 `eventstore_write_failed_after_effect`，两者的 `AgentToolCall.error_message` 与 `tool.failed.payload.error_message` 都是短错误原文或 `agent_error_message_summary_v1` 有界摘要；`policy_reason_json.execution_context.error_message_hash` 基于该有界字符串计算，Runbook 和 ToolCall Detail 不复制完整 backend/provider 异常尾部。

Outbox 发布失败后的人工诊断列同样保持有界：`AgentOutboxPublisher.publish_pending()` 写入 `ai_agent_outbox.last_error` 时，短 publish 错误保留原文，超过 512 字符的异常改用 `agent_error_message_summary_v1` preview、截断标记、原始长度、hash 与 `full_error_reference=AgentOutboxPublisher.publish_pending`，避免 dead-letter 排障面复制完整 provider/backend 异常尾部；`POST /api/v1/agents/outbox/publish` 的响应契约仍只返回批处理 summary，不把逐条 `last_error` 扩散到前端 API。

Runbook 诊断里的事件型 recommendation 也遵循同一条诊断面边界：`approval_conflict_event_seen` 与 `memory_bypassed_evidence_ref_event_seen` 不复制完整 `AgentEvent.payload_json`，只输出 `runbook_event_payload_summary_v1`，包含事件 id/seq、payload keys、固定长度预览、截断状态、大小、稳定 hash 和 `full_payload_reference=AgentEvent.payload_json`。这样恢复面板可以定位原始 EventStore 事实，同时避免长 transcript、Memory snapshot 或未脱敏业务 payload 经 Runbook API 扩散。

`AgentBackendCompletionAuditService.audit` 把这条执行诊断链纳入后端完成度验收面：`runtime_contracts` 声明 ToolCall dispatch trace、ToolCall execution context、Runbook execution context 白名单摘要、Runbook dispatch trace 白名单摘要和摘要字段；`diagnostics` 声明 ToolCall Detail 与 Runbook diagnosis 跳转入口；`observability_and_release_gate.details` 同步输出摘要字段，供交付验收确认工具分派、执行上下文、Runbook 和诊断入口已经成为后端完成边界。该 audit 仍只做能力和入口摘要，不触发 live provider，不复制原始 input/output/evidence/error message，也不替代 ToolCall Detail 的权限校验。

同一个 completion audit 还声明多用例行为评测套件可用性：`behavior_evaluation_suite_available` 指向 `scripts/agent_behavior_evaluation.py`、由 `scripts.agent_behavior_evaluation.CASES` 派生的 T01-T08 case ids、由 `scripts.agent_behavior_evaluation.ASSERTIONS` 派生的行为断言维度、由每个 `EvalCase.assertion_ids` 汇总的 `assertion_coverage` 覆盖映射、由 `undeclared_case_assertions()` 派生的未声明断言治理映射、由 `MODEL_CALL_TRACE_FIELDS` 派生的 `model_call_trace_fields`、由 `MARKDOWN_REPORT_SECTIONS` 派生的 `markdown_sections`、由 `behavior_evaluation_runbook()` 派生的安全运行命令/环境变量要求/report schema version、由 `latest_report_summary()` 派生的最近历史报告白名单摘要和 `reports/woagent_behavior_eval_*.json|md` 产物约定。它用于把通用问答、上下文追问、项目工具调用、query-first、工具结果修复、保存边界、数据集参数化、领域边界、ToolCall 诊断链、model call trace 和 SSE 高 cursor 重放这些 Agent loop 行为纳入交付验收导航。`assertion_coverage` 只统计已登记到 `ASSERTIONS` 的断言；case 上存在拼写错误或尚未登记的断言时，`undeclared_case_assertions` 输出 assertion -> case ids，`assertion_metadata_complete=false`，并使该 check 进入 attention，防止脚本 CASES、ASSERTIONS、completion audit 和前端验收面产生静默漂移。`tool_diagnostic_chain` 断言覆盖 T03/T04/T05/T07，报告 schema v2 在每个成功抓取的 ToolCall 的 JSON `tool_calls[].diagnostic_chain` 中只记录 execution/dispatch hash、router/runtime/backend handler 和状态摘要；同一用例只要有任一成功抓取的 ToolCall 缺诊断摘要，latest report 就必须把该 case 标记为缺 ToolCall diagnostic chain 证据。`tool_calls[].input_json_redacted` 在行为评测报告中保留旧字段名但值为 `agent_behavior_eval_tool_input_summary_v1`，只记录 input keys、布尔字段索引、有界 preview、截断状态、大小、hash 和 `full_input_reference=AgentToolCallRead.input_json_redacted`，让数据集参数化等断言读取安全信号而不复制完整工具输入。Markdown 报告的“工具诊断链摘要”渲染同一安全字段供人工排查，避免评测报告复制完整 `policy_reason_json` 或原始 payload。`model_call_trace` 断言覆盖 T01-T08，报告 JSON 的 `model_call_trace[]` 从 EventStore 事件按 `model_call_id` 聚合 iteration、loop step、phase、started/completed、delta/retry/interrupted 计数、final_summary/repair_attempt 与 finish 摘要，Markdown 报告的“模型调用链摘要”渲染同一安全字段，避免复制 prompt、delta content、错误明文、assistant transcript 或 secrets；`sse_high_cursor_replay` 断言覆盖 T01-T08，latest report 只记录哪些 case 具备非 heartbeat 重放证据和哪些 case 缺失，不复制事件正文或 preview。completion audit 通过 `model_call_trace_fields` 和 `markdown_sections` 让这些 JSON 字段与 Markdown 章节变成机器可读契约。audit 能直接看出每个断言由哪些 case 覆盖、维护者应如何复现评测、最近历史报告是否存在、JSON 是否有同名 Markdown companion、该报告 summary 计数是否匹配 `results` 派生计数、该报告是否覆盖当前 CASES、报告 schema 是否匹配当前脚本期望、历史报告是否覆盖当前 `model_call_trace` 证据、工具型用例是否覆盖当前 ToolCall diagnostic chain 证据以及每个用例是否覆盖 SSE high-cursor replay 证据；即使报告缺失或 JSON 损坏，latest report 摘要也保持 markdown artifact、`report_schema_version=null`、`expected_report_schema_version=agent_behavior_evaluation_report_v2`、`schema_matches_current=false`、`summary_counts_match_results=false`、expected/missing/current case set、model trace coverage、tool diagnostic chain coverage 和 SSE replay coverage 字段稳定。同 schema 但缺少 `model_call_trace`、ToolCall `diagnostic_chain`、SSE replay 或 Markdown companion 的旧报告会分别被 `missing_model_call_trace_case_ids` / `model_call_trace_complete=false`、`missing_tool_diagnostic_chain_case_ids` / `tool_diagnostic_chain_complete=false`、`missing_sse_high_cursor_replay_case_ids` / `sse_high_cursor_replay_complete=false` 与 `artifact_pair_complete=false` 标记出来。audit 本身不运行 live DeepSeek 评测，不携带 `AGENT_EVAL_PASSWORD` 值，不复制 `login_user`、assistant transcript、tool payload、model trace content、SSE event preview 或 Markdown 正文，也不把历史报告摘要、artifact pair、schema match、summary count match、current case set、model trace coverage、tool diagnostic chain coverage 或 SSE replay coverage 状态用于 `complete/status` 判定，真实评测仍由维护者显式设置环境变量、运行脚本并审查报告。

行为评测 JSON result 的 `assistant_message` 是报告预览而不是完整 transcript：`run_case()` 仍把完整 `AgentRunSummary.assistant_message` 交给 `evaluate_case()` 做语义断言，但写入报告的 `assistant_message` 只保留 `agent_behavior_eval_assistant_message_preview_v1` 有界 preview，并附带原始长度、截断状态和 `full_assistant_message_reference=AgentRunSummary.assistant_message`。因此 completion audit/latest-report 只把行为评测产物当作安全摘要入口；需要完整 assistant 正文时仍应走 Run Summary/Transcript 的权限边界。

行为评测异常面也按同一 artifact 边界处理：`summarize_error_for_report()` 生成 `agent_behavior_eval_error_summary_v1` 摘要，ToolCall Detail fetch error、SSE replay error 和单 case 异常 result/progress 都只保存固定长度 preview、截断状态、原始长度、hash 与完整错误引用。这样 latest-report/Markdown 可以保留排查入口，又不会把超长 HTTP body、traceback、provider 响应正文或异常尾部内容复制进评测产物。

同一错误预览边界也前移到行为评测 HTTP client：`ApiClient.request_json()` 与 `request_sse_text()` 在 HTTPError/URLError 上抛出的 `RuntimeError` 由 `format_error_for_runtime()` 生成，异常字符串只包含 preview、截断状态、原始长度、hash 和完整错误引用，避免登录、summary 或 SSE 请求失败时绕过 per-case artifact 捕获并把完整 body 打到控制台。

`behavior_evaluation_suite_available.details.latest_report_fields` 由 `scripts.agent_behavior_evaluation.LATEST_REPORT_SUMMARY_FIELDS` 派生，用于把 latest report 核心白名单字段顺序也变成机器可读契约，避免 completion audit、Harness 文档和评测脚本分别维护字段清单。

`summary_counts_match_results` 对比 `summary.case_count`、`summary.passed_count`、`summary.failed_count` 与 `results` 派生计数；计数缺失、类型不为整数、数值不一致，或任一 `results[].evaluation.passed` 不是布尔值时为 false，避免历史报告 summary 数字和明细行脱节时仍被前端当作校准事实展示。

`summary_average_score_matches_results` 对比 `summary.average_score` 与每条 `results[].evaluation.score` 按脚本生成规则派生的平均分；任一分数字段缺失、类型不为数值、数值不是有限值（`NaN`、`Infinity`、`-Infinity`）、任一 result 不是对象，或在所有分数均为有限数值时与生成规则不一致时为 false，避免历史报告平均分和明细行脱节时仍被前端当作校准事实展示。

`invalid_evaluation_case_ids` 列出最近历史报告中 `evaluation.passed` 不是布尔值或 `evaluation.score` 不是有限数值的 case id；该字段只暴露 case id，不复制原始 evaluation payload，用于解释 summary count/average score 状态为何不能作为校准事实。

报告生成端也使用同一套强类型边界：`report_summary_from_results()` 只把 `evaluation.passed is True` 且 `evaluation.score` 为有限数值的结果计入通过；畸形 evaluation 行不会中断 JSON/Markdown 产物生成，而是按失败进入 summary，非法 score（含 `NaN/Infinity`）按 0 参与生成端平均分，并保留原始 result 让 latest-report 摘要继续用 `invalid_evaluation_case_ids` 定位。

JSON artifact 写盘边界必须保持标准 JSON：`write_json()` 先用 `json_safe_value()` 递归扫描 payload，将 `NaN`、`Infinity`、`-Infinity` 替换为 `<non-finite-number:nan|inf|-inf>` 字符串哨兵，再以 `allow_nan=false` 序列化。这样部分 result 中的非有限浮点不会生成裸常量污染报告文件；前端、completion audit 和 CI 仍通过 `invalid_evaluation_case_ids`、summary 校验字段和哨兵值判断该报告不可作为校准事实。

历史 JSON 读取边界同样必须严格：`latest_report_summary()` 通过 `parse_constant=reject_non_standard_json_constant` 拒绝裸 `NaN`、`Infinity`、`-Infinity`，并把该报告降级为 `available=false`、`error=NonStandardJsonConstantError` 的 unavailable 摘要。这样旧脚本或手工产物生成的非标准 JSON 不会被 Python 宽松解析成看似可用的 latest report。

Markdown companion 和 progress log 属于同一 artifact 可读面：`markdown_report()` 必须在渲染前复用 `json_safe_value()`，`main()` 的 `[done]` progress 记录也必须用该安全展示值输出 `evaluation.score`。非有限分数在 JSON、Markdown 和 progress 中都显示为 `<non-finite-number:nan|inf|-inf>`，避免人工排查看到裸 `nan` 而误以为 summary 校验规则没有生效。

生成端 progress 与 Markdown 渲染不能成为第二个崩溃点：`evaluation.score/passed/passes/issues` 缺失或类型异常时，脚本必须保留单条原始 result、继续写出 JSON/Markdown，并由 `<missing>` 占位和 latest-report 的 invalid/summary 校验字段表达不可校准状态，不能因为日志或 Markdown 访问异常追加重复 error result。

单 case 执行异常也必须保留为完整失败行：`run_case()` 抛异常时，`main()` 需要补齐报告消费字段（status、timing、event count、SSE replay error、空工具/trace 列表和失败 evaluation），让 JSON/Markdown artifact pair 继续生成；该错误行应被 summary 计为失败且平均分为 0，latest-report 仍能校验 summary 与明细一致。

Markdown companion 对部分 result 行采用占位渲染而不是改写事实：当 runtime、SSE replay、tool list、assistant snippet 或 ToolCall 列表字段缺失时，`markdown_report()` 输出 `<missing>` 或空集合，JSON artifact 保留原始缺字段状态，latest-report summary 继续按 JSON 明细判断校准性。

评估函数本身同样是自恢复边界：`evaluate_case()` / `evaluate_common()` 对缺失运行摘要、assistant 正文、工具列表、ToolCall 列表或 SSE replay 摘要的 result，必须返回带 issues 的失败 evaluation，而不是抛异常；这样单条坏 result 会进入报告和 latest-report integrity checks，而不是中断整个行为评测。

`latest_report.duplicate_case_ids` 用于暴露同一历史报告中重复出现的 case id；`current_case_set_complete` 只有在缺失、额外和重复 case 集合都为空时才为 true，避免重复执行某个 case 的损坏报告被当作当前 CASES 全量覆盖。重复 case 同样会让 `model_call_trace_complete`、`tool_diagnostic_chain_complete` 与 `sse_high_cursor_replay_complete` 保持 false，即便各自的 `missing_*_case_ids` 为空，也不能把损坏报告视为诊断证据完整。

`schema_matches_current` 是三个诊断 complete 字段的共同前提；旧 schema 或缺 schema 的历史报告即便 case set 与诊断覆盖集合看起来完整，也只能作为人工参考，`model_call_trace_complete`、`tool_diagnostic_chain_complete` 与 `sse_high_cursor_replay_complete` 必须保持 false，避免非当前 report schema 产物被当作可信评测结果。

`behavior_evaluation_suite_available.details.uncovered_assertion_ids` 由 `scripts.agent_behavior_evaluation.uncovered_assertion_ids()` 派生，列出已登记到 `ASSERTIONS` 但没有任何 `EvalCase.assertion_ids` 覆盖的断言；与 `undeclared_case_assertions` 一起决定 `assertion_metadata_complete`，任一集合非空都会使行为评测 check 进入 attention，避免新增断言维度后没有真实 case 验证。

Model call trace、Tool diagnostic chain 与 SSE high-cursor replay 的期望 case 集都由 `EvalCase.assertion_ids` 派生。`latest_report_summary()` 使用这些派生集合计算 `missing_*_case_ids`，并且 ToolCall diagnostic chain 覆盖判定与 `evaluate_tool_diagnostic_chain()` 保持一致：只忽略 `fetch_error` 的 ToolCall，所有成功抓取的 ToolCall 都必须带 execution/dispatch 摘要，`execution_context_present` 与 `dispatch_trace_present` 必须严格为布尔 true，`execution_context_hash` 与 `dispatch_trace_hash` 必须是非空字符串。`evaluate_case()` 也只在 case 声明对应 assertion 时检查 model trace、ToolCall diagnostic chain 或 SSE replay 证据，避免报告覆盖状态与真实评估逻辑出现第二份诊断用例列表。

Model call trace 覆盖判定也由脚本内 `result_has_model_call_trace()` 统一：只有非空 `model_call_trace[]` 中每条摘要具备 `model_call_id`、`loop_step` 且 `started_event_seen=true`，并且在报告提供 `model_call_count` 时该值是正整数且数量一致，latest report 才会把对应 case 标记为具备 model trace 证据；非空但不完整、`started_event_seen` 不是布尔 true、或 `model_call_count` 不是正整数的 trace 必须进入缺失集合，避免历史报告靠弱证据通过验收导航。

SSE high-cursor replay 覆盖判定也由脚本内 `result_has_sse_high_cursor_replay()` 统一：只有 `sse_high_cursor_replay` 为对象、没有 `error`、`event_count` 与 `non_heartbeat_event_count` 都是正整数、非 heartbeat 数量不大于总事件数，且 `heartbeat_only=false`，latest report 才会把对应 case 标记为具备 SSE replay 证据；带 error、缺计数字段或计数不一致的历史报告必须进入缺失集合。

缺失 `report_schema_version` 的历史行为评测 JSON 仍保留 `available=true` 摘要，方便人工追溯，但会输出 `report_schema_version=null` 与 `schema_matches_current=false`，防止早期无 schema 产物被误当作当前 v2 评测证据。

报告缺失或 JSON 损坏时，`latest_report_summary()` 也输出 `report_schema_version=null`，但此时 `available=false`，语义是没有可读取的真实历史报告 schema；当前期望 schema 仍只由 `expected_report_schema_version` 和 runbook 元数据表达。

该 audit 的 `derived_from` 同步提供 `behavior_evaluation_cases`、`behavior_evaluation_assertions`、`behavior_evaluation_assertion_coverage`、`behavior_evaluation_undeclared_case_assertions`、`behavior_evaluation_runbook`、`behavior_evaluation_model_call_trace_fields`、`behavior_evaluation_markdown_sections`、`behavior_evaluation_latest_report` 与 `behavior_evaluation_latest_report_fields` 来源键，分别指向 `scripts.agent_behavior_evaluation.CASES`、`scripts.agent_behavior_evaluation.ASSERTIONS`、`scripts.agent_behavior_evaluation.assertion_coverage`、`scripts.agent_behavior_evaluation.undeclared_case_assertions`、`scripts.agent_behavior_evaluation.behavior_evaluation_runbook`、`scripts.agent_behavior_evaluation.MODEL_CALL_TRACE_FIELDS`、`scripts.agent_behavior_evaluation.MARKDOWN_REPORT_SECTIONS`、`scripts.agent_behavior_evaluation.latest_report_summary` 和 `scripts.agent_behavior_evaluation.LATEST_REPORT_SUMMARY_FIELDS`，让 completion audit 的评测 metadata 与历史报告摘要可追溯到脚本事实源，而不是服务层静态副本。

`derived_from.behavior_evaluation_uncovered_assertions` 指向 `scripts.agent_behavior_evaluation.uncovered_assertion_ids`，把已登记未覆盖断言治理纳入同一事实源追溯面。

同一个用户问题在 Agent loop 中可能触发多次 LLM 调用，后端通过 `iteration_id`、`model_call_id`、`loop_step` 把 `model.started`、`model.delta`、`model.markdown_normalized`、`model.completed`、`model.stream_interrupted` 串成可追踪的调用链，并为同一次调用派生 `model_response_item_id=agent-model-response://{run_id}/{model_call_id}`，让流式 delta、Markdown replacement 和 completed 可以归到同一个 assistant 响应项；这个响应项 id 与 EventStore 事件自身的 `item_id=agent-event://{run_id}/{event_seq}` 分离。嵌套 `loop_state` envelope 明确 `iteration`、`phase`、`step`、`model_call_id`、`tool_call_id` 与 `decision_reason`。旧顶层 trace 字段继续保留，方便前端兼容；新 envelope 让评测报告和调试 UI 可以区分普通回答、工具规划、工具请求修复、必需工具修复、工具执行/观察、最终总结和意图能力 guard，也让前端不再把工具规划轮的暂时无 delta 误判为后端卡死。工具前置条件被 Harness 阻断时，runner 会同时创建修复用 decision ContextBuild 和 `loop.observed`，以 `RC_TOOL_PREREQUISITE_MISSING` 记录需要先调用的 prerequisite tool；模型输出非法 `agent_tool_request` 时同样以 `RC_TOOL_REQUEST_FORMAT_INVALID` 记录格式修复决策，避免这些可恢复纠错只表现为普通审计事件或 `tool.failed`。

当工具闭环达到 `run.max_iterations` 后仍需要给用户最终总结时，Runner 会先绑定 stop 用 decision ContextBuild，并写入 `loop.observed(RC_MAX_ITERATIONS)`，`next_action=stop`、`reasons=[max_iterations]`，再进入 `final_summary` 模型调用。这让迭代上限从隐式 for-loop 退出变成可审计 Resource / Limit 决策；前端和 Runbook 应把它展示为 stop observation，而不是 assistant 文本或普通工具失败。`AgentMetricsService.snapshot` 也会按 LoopObservation 的 stop reason 输出运行时纠错/停止指标：`tool_prerequisite_missing_total`、`tool_request_format_invalid_total`、`required_tool_followup_missing_total`、`max_iterations_total` 与 `same_failure_no_progress_total`，并纳入 dashboard `metrics_catalog_complete`，防止已审计的 Agent 循环纠错原因只停留在事件流里。`AgentRunbookService.diagnose_run` 会把这些已知运行时 repair/stop observation 聚合为 `agent_runtime_loop_repair` recommendation，携带 observation id、RootCause、stop reason 和 mitigation，作为 loop diagnostics 的跳转入口。

DeepSeek stream 只在首个 `delta/done` 前做可配置重试，避免 provider 首包前 SSL EOF、连接重置或短暂 5xx 直接让 run 失败；每次 retry 写入 `model.stream_retrying`，payload 只包含 attempt、delay 和安全错误摘要，不包含 prompt、API key 或请求体。若已经收到 partial content 后才断流，则保持 `model.stream_interrupted` 路径，用 partial content 尽量继续完成，避免重复输出；`model.stream_interrupted.payload.error_message` 与 interrupted `model.completed.error_message` 同样只写入 `agent_error_message_summary_v1` 有界摘要或短错误原文，不复制 provider/HTTP 长响应尾部。

数据库连接池默认开启 pre-ping、recycle、MySQL connect timeout 和 pool size/overflow/timeout 配置。SQLAlchemy transient disconnect 进入统一错误处理分支，返回 503 `database_connection_lost` 与 `Retry-After: 1`，并 dispose 当前 engine pool，让后续请求重新建连；业务响应不暴露 SQL、DSN 或堆栈。

为提高多轮 agent 的 provider prompt/cache 命中率，Runner 构造系统提示时保持稳定前缀：ToolRegistry 清单按工具名排序，工具 JSON 使用固定字段排序和紧凑分隔符序列化；只要工具集合和策略版本未变，同一 runtime hash 下重复构建的系统提示字符串应保持一致。

Runner 同时对服务端 conversation history 执行轻量上下文预算控制：模型 prompt 只读取同一会话最近已完成 run，估算输入单位超过预算时把较早轮次压成一个 system 摘要，并保留最近完整轮次的截断内容；压缩会写入 `context.history_compacted` 审计事件，前端和评测可以据此区分“长历史被压缩”与“历史丢失”。该事件 payload 现在是 redaction-safe compaction envelope，固定 `trigger/reason/phase/implementation`、压缩策略、压缩/保留轮数、`estimated_input_units_before/after`、`budget_limit_units`、summary role、replacement history、initial context injection、reference context item、context baseline、window identity 与 source，避免 `token_budget` 等 key 被 EventStore masking 擦除，也让该事件语义对齐 openai/codex `ContextCompactionItem`。本地 `context_baseline=system_run_skill_memory_rebuilt_per_model_call` 表示 Runner 在每次模型调用前重建 system prompt、run context、Skill catalog/正文和 Memory context；它是与 Codex 持久化 WorldState full baseline 的边界说明，不复制 raw prompt、WorldState 或压缩摘要正文。`window_number/first_window_id/previous_window_id/window_id` 按 conversation 生成单调窗口链，用来区分同一 run 初始调用、审批后 final summary 或恢复路径里的重复压缩窗口。已完成历史 run 的用户 `intent` 会继续作为多轮上下文回放；历史 assistant 回复只有在对应 run 的 `assistant_visible` 未显式为 `false` 时才会进入模型上下文，避免未完成 run 以及 smoke/debug/auto-complete 的不可见结果污染后续模型判断。Transcript/List/Export 仍保留完整 run 历史，不等同于 Runner prompt 输入；Transcript/Export 额外暴露 `context_compactions` 索引，按 run 顺序和 event_seq 汇总 `context.history_compacted` 的安全 payload，并用 `item_id=agent-context-compaction://{run_id}/{event_seq}` 提供对齐 openai/codex `ContextCompaction { id }` 的稳定 timeline marker，方便恢复/导出定位 compaction 审计事实，同时不复制模型 prompt 或压缩摘要正文。Run event snapshot 也暴露当前 run scoped 的 `context_compactions` 索引，使断线恢复在本次事件窗口为空或不包含较早 compaction event 时仍能定位该 run 的压缩事实。Runner 还会把当前 checkpoint 的 `context_compaction_object_key` 更新为对应 `agent-event://{run_id}/{event_seq}`；Checkpoint Freshness Gate 输出该引用、event seq/type 和可用状态，引用缺失或格式错误时要求 `replan_from_latest_safe_state`，避免从不可重建的压缩窗口继续 resume。两份 Harness 文档的 `Required Agent conversation history context contract`、`Required Agent history compaction envelope contract`、conversation transcript/export payload contract、run event snapshot payload contract 和 checkpoint context compaction freshness contract 由专项回归固定 source status、排除状态、oldest-to-newest 历史顺序、压缩 envelope 字段、compaction 索引字段、checkpoint compaction 引用字段、system 摘要角色和当前用户消息末尾位置，使该 prompt/恢复组装边界可测试、可审计。

EventStore 的只读事件结构也补齐稳定 item identity：`AgentEventRead.item_id=agent-event://{run_id}/{event_seq}`，由 `ai_agent_events.run_id/event_seq` 派生，不新增数据库列、不改变事件 payload，也不影响 SSE 的 `id: event_seq` cursor 语义。Snapshot、Conversation Export 等 JSON 恢复面可用该字段作为 timeline/debug/download item key，对齐 openai/codex 每个 ThreadItem/ResponseItem 均携带稳定 `id` 的恢复模型。SSE 实时流保持浏览器事件 `id` 为 `event_seq`，但会把同源 `item_id` 合入出站 `data` envelope；该字段不写回 `payload_json`，只用于让实时流、snapshot 和 export 使用同一 timeline item key。

## 3. 架构分层

建议项目逐步演进为如下结构：

```text
app/
├── main.py
├── core/
│   ├── config.py
│   ├── security.py
│   └── redis.py
├── db/
│   ├── session.py
│   └── base.py
├── api/
│   └── v1/
│       ├── routers/
│       └── deps.py
├── ai_skills/
│   ├── base.py
│   ├── registry.py
│   └── packages/
├── models/
│   ├── user.py
│   ├── project.py
│   ├── environment.py
│   ├── api_case.py
│   ├── test_flow.py
│   └── test_report.py
├── schemas/
├── services/
├── repositories/
├── runner/
│   ├── flow_runner.py
│   ├── step_executor.py
│   ├── request_builder.py
│   ├── assertion_engine.py
│   ├── extractor.py
│   └── report_recorder.py
├── tasks/
│   └── test_tasks.py
└── utils/
```

### 3.1 API 层

API 层负责对外提供 HTTP 接口，包括用户认证、项目管理、环境管理、接口管理、用例管理、流程管理、缺陷跟踪、执行管理和报告查询。

API 层只做参数接收、权限校验和响应封装，不直接写复杂业务逻辑。

### 3.2 Service 层

Service 层负责业务编排，例如创建测试流程、触发执行任务、生成报告摘要、校验用户权限等。

Service 层可以调用 Repository、Runner、Redis 和任务队列。

### 3.3 Repository 层

Repository 层负责数据库访问，封装常见 CRUD 和复杂查询，避免 SQLAlchemy 查询逻辑散落在 API 或 Service 中。

### 3.4 Runner 执行层

Runner 是平台的核心能力，负责将平台中的接口测试流程转化为真实 HTTP 请求，并记录每一步执行结果。

建议拆分为：

| 模块 | 职责 |
| --- | --- |
| FlowRunner | 执行完整测试流程 |
| StepExecutor | 执行单个接口步骤 |
| RequestBuilder | 根据环境、变量和步骤配置构造请求 |
| AssertionEngine | 执行断言规则 |
| Extractor | 从响应中提取变量 |
| ReportRecorder | 写入执行记录和报告数据 |
| ErrorHandler | 处理异常、失败策略、跳过策略 |

### 3.5 AI Skill Runtime

AI 能力按正式 skill 包组织，不把长 prompt 写在 Router 或业务 Service 中。

| 模块 | 职责 |
| --- | --- |
| `app/services/ai_service.py` | DeepSeek Chat Completions 和流式 SSE 增量读取 |
| `app/ai_skills/packages/{skill_id}/` | `SKILL.md`、`manifest.json`、prompt 和可复用资源 |
| `app/ai_skills/{skill_module}.py` | Runtime adapter，负责构造请求、解析响应、归一化输出和 Schema 校验 |
| `app/ai_skills/base.py` | 通用 skill runner、JSON 解析兼容、一次模型修复兜底、run trace 事件 |
| `app/services/ai_skill_run_service.py` | 可观测 AI Skill Run 创建、查询和后台执行 |

当前内置 `http-test-case`、`websocket-test-case` 和 `scenario-composer`。HTTP 用例 prompt
要求固定 JSON 根对象、字段名不能拆行、字符串内不输出真实控制字符，断言必须使用
`expected` 字段。模型输出仍被视为不可信，必须经过 JSON 修复、业务归一化和 Pydantic
Schema 校验后才能作为草稿返回。

### 3.6 Harness Agent Skills

Harness Loop Agent 的对话型能力采用 Codex 风格的渐进加载 Skill 目录，而不是把所有业务规则长期硬编码在 `AgentConversationRunner` 主 prompt 中。

| 模块 | 职责 |
| --- | --- |
| `app/agent_skills/{skill_name}/SKILL.md` | 可复用 Agent Skill，使用 `name`、`description`、后端私有 `triggers` 以及 `guard_*` / `routing_*` frontmatter 描述目录、触发范围和窄 guard 预检查；正文记录工具顺序、业务边界和输出约束；同目录可放置后端私有 prompt 资源 |
| `app/services/agent_skill_registry.py` | 读取、校验、排序并缓存 Skill；提供前端元数据 catalog，并按每个 Skill 自带的 `triggers` 和 description 选择相关 Skill；后端可读取私有 routing hints（例如 `routing_requires_tool`、带 `intent_markers` 的 `routing_required_tool_after_success`）和 Skill-local 私有资源文本，但不会把它们放入 catalog 或 prompt block |
| `GET /api/v1/agents/skills` | 只返回 `{name,description}` 元数据，Skill 正文仅供后端运行时注入，不作为前端可见指令 |
| `AgentConversationRunner` | 系统 prompt 只携带稳定 Skill catalog；每次 run 根据用户 intent 注入相关 Skill 正文 |

`_conversation_system_prompt()` 中的初始 Skill catalog 是渐进加载入口的公开目录，只能来自 `AgentSkillRegistry.catalog()`，并以稳定 key 排序和紧凑分隔符序列化为 `description,name` 两个字段。后端私有 `triggers`、`routing_hints`、`private_values`、`guard_*`、`routing_*`、Skill 正文、私有资源文件名和路径只供 intent selection、guard、routing、ContextBuild 摘要或按 intent 的正文注入使用，不进入初始 catalog prompt 或前端 Skill catalog。Harness 文档用 `Required Agent initial skill catalog prompt contract` 锁住该边界，避免 Codex-style 渐进加载退化为一次性泄露全部私有路由规则。

`ContextBuilder` 会在 `build_metadata_json` 中记录本轮实际选中的 Agent Skill 摘要、匹配到的私有 routing rule 摘要、run 当前 RuntimeSnapshot 摘要和当前操作者的项目权限上下文摘要。Skill 侧只保存 name/hash、after_tool/required_tool/rule_hash 等诊断字段，不落私有规则原文或 Skill 正文；runtime 侧只保存 snapshot id、runtime/tool registry/manifest/prompt/policy hash、available tool names 和 tool count，不复制完整工具 schema；permission 侧只保存 actor/project/access level、显式权限码列表/count 和 permission hash，不复制用户资料或完整授权表。两份 Harness 文档用 `Required ContextBuild metadata contract` 固定 metadata key 顺序、各 envelope 字段清单和私有字段排除边界，使该诊断 envelope 像 openai/codex per-turn `TurnContext` 一样可恢复、可审计、可测试。这样 required-tool follow-up、unsupported capability guard、工具前置阻断、权限相关停止决策和后续 Runbook 都能从 decision ContextBuild 追溯“为什么这轮模型被要求继续调用某个工具，以及当时基于哪版工具/策略/权限环境”，同时仍保持前端 catalog 只读元数据边界。

需要人工审批的高风险 ToolCall 不允许把 ContextBuild 缺口留到批准后的执行阶段。`ExecutionLedgerService.create_tool_call()` 在创建 `AgentApproval` 前会为 `business_create/business_update/destructive/external_effect` 这类审批工具确保存在可执行的 `decision_context_build_id`；当模型没有提供可信 policy evidence 时，后端以已落账 ToolCall 的冻结输入 hash 创建 `system_record` evidence ref，并用 `build_purpose=approval` 构建 ContextBuild。该 ref 是审计引用，不复制完整 `input_json_redacted`；审批 CAS、ToolCall input hash、runtime snapshot 和 resource scope 仍是判断 approval 是否过期或被替换的事实源。

`ContextBuilder` 的 degraded 构建还会在 `compressed_sections_json` 中记录 redaction-safe 的 context window 诊断：预算范围、估算输入单位、预算上限、剩余预算、是否触顶、压缩等级、保留/省略 evidence ref 数量和 required evidence 完整性；`context.degraded.payload.context_window` 携带同一结构。字段名刻意避免 `token` key，避免 EventStore masking 把预算数字擦除；语义上对齐 openai/codex `ContextWindowTokenStatus`，让长上下文压缩从“只知道 degraded”升级为可恢复、可审计、可测试的预算状态。

当前内置 Agent Skill：

- `general-testing-answer`：软件测试、自动化、接口/WebSocket、断言、提取器、测试数据、缺陷、CI、报告等通用问答。
- `project-context`：当前项目上下文、真实项目用例、资源和实时平台事实读取；通过 `project.read_context` 或 `testcase.query_project_cases` 取得证据。
- `project-permission-admin`：项目、成员、角色、管理员、项目创建者、普通测试人员、权限码、项目访问和 403 授权失败诊断；没有权限写入 ToolCall 时只给管理员操作清单。
- `environment-config-management`：多环境、默认环境、`base_url`、环境变量、鉴权变量、变量替换和多环境绑定建议；真实环境事实通过 `project.read_context` 取得。
- `security-auth-testing`：鉴权、认证、授权、JWT/token/session/cookie、权限边界、越权、限流、CSRF 和安全负向测试；真实令牌或权限状态必须由工具证据确认，私密凭据不能编造或输出。
- `api-definition-import`：OpenAPI/Swagger、接口定义、接口资产、endpoint catalog、path/method/schema 提取和从接口生成用例规划；缺少接口资产写入工具时不声称导入或保存。
- `ai-skill-runtime-governance`：AI Skill 包、manifest/schema、prompt、JSON 修复、模型输出、provider 状态和 AI Skill Run 可观测诊断；生成结果始终保持草稿边界直到保存工具确认。
- `http-test-case-design`：HTTP/API 测试用例设计、生成、扩写、断言、提取器、变量、请求体和 Schema 校验；新用例草稿可通过 `ai_skill.run_draft` 调用 `http-test-case/generate`，但该路径要求 `interface_text`，已保存用例补断言或保存断言应先用 `testcase.query_project_cases` 取得真实 id，再走 `testcase.update_assertions` / `testcase.batch_update_assertions` 字段级 patch，需要结构校验时使用 `testcase.validate_schema`。
- `websocket-test-case-design`：WebSocket 握手、鉴权 header、子协议、消息顺序、接收断言、超时、ping/pong 和关闭行为；需要草稿时通过 `ai_skill.run_draft` 调用 `websocket-test-case`。
- `assertion-extractor-binding`：断言、提取器、变量路径、响应字段、上下游参数流和变量绑定修复；真实路径必须来自响应样本、执行详情或报告证据；保存 assertion-only 更改时使用 HTTP/WebSocket 的 `update_assertions` / `batch_update_assertions` 工具，不能把已保存用例断言 follow-up 误路由到需要接口文档的 `http-test-case/generate`。
- `test-asset-lifecycle`：测试资产标签、目录、复制、重命名、删除、归档、版本历史和依赖影响评估；破坏性操作必须先确认引用和历史记录边界。
- `visual-flow-design`：可视化 Flow DAG、HTTP/WebSocket 节点、条件、延迟、数据绑定、节点执行和 Flow 报告/执行记录诊断；没有 Flow 写入 ToolCall 时不声称保存流程。
- `scenario-composition`：测试场景创建、组合、校验、dry-run、数据驱动、保存边界和 query-first 工具链。
- `dataset-parameterization`：场景数据集、records、参数化、CSV/JSON 测试数据、请求覆盖、每 record 独立运行和数据驱动执行建议；缺少数据集写入工具时不声称导入或保存。
- `mock-service-virtualization`：Mock API、stub、fake dependency、服务虚拟化、挡板和契约模拟设计；缺少 mock 写入工具时只输出契约和规则草案，不声称创建 Mock 服务。
- `test-plan-management`：测试计划、计划目标、冒烟/回归套件、覆盖率、发布准入、计划运行和计划报告分析；真实计划结果优先从报告摘要读取。
- `ci-release-integration`：CI/CD、Jenkins/GitLab/GitHub Actions、webhook、定时回归、发布门禁和部署准入设计；缺少流水线写入工具时只输出集成契约，不声称配置已生效。
- `batch-execution-scheduling`：批量执行、调度、队列、worker、并发、超时、重试、取消和执行顺序治理；真实队列或运行状态需由工具证据确认。
- `execution-diagnosis`：HTTP/WebSocket/场景/Flow 执行失败、flaky、超时、重试、断言/提取失败、SSE 卡住和环境不匹配诊断；优先复用 `report.read_summary` 与 `project.read_context`。
- `api-error-contract-debugging`：统一错误响应、HTTP 状态码、`request_id`、422 校验错误、401/403/404/409/500 和前端错误展示契约排障；不泄露内部堆栈或密钥。
- `notification-alerting-config`：通知、告警、邮件、SMTP、webhook、失败/完成提醒和 release gate 消息配置设计；缺少通知写入或投递工具时不声称已发送。
- `report-summary`：报告摘要、执行结果、通过率、失败原因和缺陷建议；通过 `report.read_summary` 读取最近测试报告、失败报告样本、状态统计和返回页内用例通过率。
- `report-archive-export`：HTML/PDF 导出、报告归档、历史趋势、保留周期、分享链接和审计证据设计；缺少导出/归档工具时不声称生成文件或持久化归档。
- `data-privacy-redaction`：敏感数据、PII、token/cookie/key、日志、报告、截图、签名 URL 和 AI prompt 脱敏治理；最终回复不复述原始密钥或个人信息。
- `migration-compatibility-planning`：数据库迁移、Alembic、API 兼容、历史数据修复、旧客户端、上线顺序和回滚规划；真实迁移状态必须验证后再陈述。
- `defect-triage`：缺陷草拟、分类、严重程度/优先级、复现步骤、截图/媒体证据和生命周期建议；当前没有缺陷写入 ToolCall 时只输出待保存草稿，不声称创建或更新缺陷。
- `media-evidence-management`：截图、附件、媒体证据、MinIO 对象、预签名 URL、格式校验、脱敏和删除/孤儿对象风险说明；缺少媒体工具时只输出证据处理清单。
- `browser-capture-analysis`：Chrome 插件/浏览器采集流量清洗、脱敏、去重、业务动作分组和转 HTTP/WebSocket 用例建议；需要草稿时复用 HTTP/WebSocket AI Skill，缺少采集写入工具时不声称导入或保存。
- `agent-runtime-operations`：Agent Run、SSE/EventStore、model streaming、readiness dashboard、runbook、worker queue、stale run、Memory usage、model health 和行为评测诊断。

新增 Agent 能力时优先添加或修改独立 `SKILL.md` 的正文、`triggers` 和必要的私有 `guard_*` / `routing_*` hints；窄 guard 或 classifier 的长提示词与 guard 最终回复放入同 Skill 目录的私有资源文件，再用 registry 单测锁定触发范围；每个按 intent 注入模型的 Skill prompt block 必须有硬上限，unsupported capability classifier prompt 作为模型系统消息时也必须受 `AGENT_UNSUPPORTED_CAPABILITY_CLASSIFIER_PROMPT_MAX_CHARS` 保护，超长正文或私有分类提示词只能以截断标记进入模型上下文，避免业务规则增长破坏 prompt budget。需要表达“用户要求的能力当前缺少后端工具”的边界时，优先新增 `guard_unsupported_capability` 规则，而不是在 Runner 中新增业务专用 guard；但 guard subject 必须是显式领域词，不能只依赖“直接、刚才、上面、这个”等回指词，否则会绕过同一会话工作上下文。需要强制静默工具规划或漏调用修复的实时平台事实请求应优先补充 `routing_requires_tool` 或 `routing_required_tool_after_success`，其中 follow-up 规则应配置足够窄的 `intent_markers`，避免只读查询被 broad trigger 误推进到写草稿/执行类工具；不要为了新增业务领域继续修改中央 prompt 或硬编码 Python 路由表。只有需要稳定审计、权限、幂等、EventStore、ToolCall 生命周期、执行前安全顺序校验、同一会话回指解析或工具结果修复路径的规则才下沉到 Runner/ToolRegistry/ToolExecutor 代码中。ToolRegistry 的内置 `ToolSpec` 同时声明后端私有 `backend_handler`、可选 `required_successful_tool_before` 和可选 `tool_result_repair_guidance`，`AgentToolBackend` 从 spec 解析执行函数，Runner 从 spec 解析前置工具要求，`ToolResultPolicy` 从 spec 解析工具结果修复 guidance，避免工具 manifest、执行 map、前置校验和修复策略分叉；这些后端私有字段不进入 `to_json()`、模型初始工具清单或前端契约。保存类断言更新还由 ToolExecutor 在副作用边界前校验输入 id 必须来自同一 run 最近一次成功 `testcase.query_project_cases` 的显式返回列表，禁止模型按连续区间或记忆猜测测试用例 id 后直接执行业务写入。

## 4. 核心业务模块

### 4.1 用户与认证

认证采用 JWT，推荐 access token + refresh token 模式。

认证接口的具体调用方式见 [认证接口文档](api_auth.md)。

```text
用户登录
-> 校验账号密码
-> 签发 access_token 和 refresh_token
-> refresh_token 或 token 状态写入 Redis
-> 前端携带 access_token 请求接口
```

建议策略：

| Token | 有效期 | 用途 |
| --- | --- | --- |
| access_token | 30 分钟左右 | 请求接口 |
| refresh_token | 7 天左右 | 刷新 access_token |

Redis 可用于：

- 保存 refresh token
- 保存 token 黑名单
- 实现退出登录
- 实现强制下线
- 保存用户登录版本号

### 4.2 项目管理

项目是测试资源的组织单位。

项目下可以包含：

- 环境配置
- 接口定义
- 测试用例
- 测试流程
- 执行记录
- 测试报告
- 成员与权限

### 4.3 环境管理

环境用于区分 dev、test、stage、prod 等不同运行目标。

环境配置建议包含：

- base_url
- 全局 headers
- 全局变量
- 数据库连接信息，可选
- 前置认证配置，可选

执行测试流程时，Runner 根据用户选择的环境组装最终请求。

### 4.4 接口用例管理

接口用例用于保存单个接口请求定义。

建议包含：

- 请求方法
- 请求路径
- headers
- query 参数
- body
- timeout
- 前置变量
- 后置提取规则
- 断言规则

### 4.5 测试流程编排

测试流程由多个接口步骤组成。

每个步骤可以配置：

- 执行顺序
- 引用接口用例
- 本步骤覆盖参数
- 是否继续执行
- 失败处理策略
- 变量提取
- 断言规则

典型流程：

```text
登录
-> 提取 token
-> 创建数据
-> 查询数据
-> 修改数据
-> 删除数据
-> 校验删除结果
```

### 4.6 测试执行

接口流程执行不依赖 pytest，直接使用 httpx 作为 HTTP 执行引擎。

#### 后端异步与非阻塞执行原则

本平台按多人协作平台设计，不能按个人本地工具处理执行链路。后续预计约 50 人同时使用时，
一个用户触发的长流程、外部接口等待、AI 生成、文件处理或批量任务不应阻塞其他用户的接口访问。

执行类能力必须优先满足以下原则：

- API 请求只负责鉴权、参数校验、创建持久化任务和返回任务身份；长流程优先返回 HTTP 202。
- 任务状态、进度事件和最终结果必须可查询或可订阅，不能只依赖内存中的临时状态。
- 同步执行只允许用于短耗时、可严格超时、并发影响可控的调试或兼容场景，并必须在文档中标明边界。
- 所有外部 I/O 包括 HTTP、WebSocket、AI 服务、MinIO、数据库批量操作和报告导出都必须设置超时；重试必须带指数退避、抖动和最大等待。
- 在 FastAPI `async def` 路由内不得直接执行长时间同步阻塞逻辑；无法换成异步客户端时，应放到线程池、独立进程或 Worker。
- 批量执行、数据驱动 record 展开、定时任务和 Webhook 触发必须设计项目级并发限制、取消、失败恢复和资源保护。

当前场景手工执行链路：

```text
前端点击执行
-> FastAPI 校验权限、场景版本、环境和数据集
-> MySQL 写入 test_scenario_executions
-> 每个已选择数据集的每条 enabled record 写入 test_scenario_runs 和 run_queued
-> API 返回 HTTP 202、execution_id、run_id 和订阅地址
-> FastAPI BackgroundTasks 使用独立 Session 执行已有 run
-> 步骤执行继续复用原变量渲染、用例执行、断言和提取逻辑
-> 每个状态边界先写 test_scenario_run_events，再由 SSE 读取
-> 前端通过 Last-Event-ID 重连，必要时用 run detail 恢复快照
```

执行入口不直接等待长场景。API 先创建持久化 `queued` 运行并返回 HTTP 202，再由
应用内后台任务继续执行。当前实现保证任务 ID、运行快照和事件在响应前落库，但尚未提供
进程重启后的自动领取和恢复，因此不能把 `BackgroundTasks` 视为可靠任务队列。

生产环境可将“读取 queued execution 并执行 run”的边界迁移到 Celery、RQ 或专用 Worker，
无需改变现有 API、运行状态和 SSE 事件协议。迁移时必须增加原子 claim、租约、Worker 心跳、
重复投递幂等和孤儿任务恢复。

### 4.7 场景实时事件模型

```text
test_scenario_executions
  1 -> N test_scenario_runs
         1 -> N test_scenario_run_events
```

- execution 表示一次用户点击或一次幂等执行请求。
- run 表示一个数据集 record 的一次运行，是详情快照和最终结果的权威来源。
- event 表示 run 内不可变的有序状态变化，`run_id + sequence` 唯一。
- 事件必须先提交数据库，再允许 SSE 客户端读取。
- SSE 采用至少一次读取语义，客户端以 `run_id + sequence` 去重。
- 心跳也持久化并占用 sequence，保证所有带 ID 的消息都可以重放。
- 完整请求和响应正文不进入 SSE，只保存在执行详情及关联用例执行记录中。

运行状态机：

```text
queued -> running -> passed | failed | timeout | cancelled
```

步骤状态机：

```text
pending -> running -> passed | failed | timeout | skipped | cancelled
```

执行期间 `test_scenario_runs` 维护 `current_step_id`、`current_step_index`、
`last_event_sequence` 和渐进式 `step_results`，用于页面刷新或事件流中断后的快照恢复。

### 4.8 数据驱动请求解析

场景数据集使用 `records` 表示独立测试输入。未指定数据集时选择所有启用数据集；显式指定
数据集时保留原有选择语义。每个选中数据集只展开其 `enabled=true` 的 record，每条 record
创建一个独立 run。没有 `records` 的历史数据集在读取时归一化为一条兼容 record。

每个步骤按以下顺序构建最终请求：

```text
读取不可变场景版本和步骤请求快照
-> 深拷贝当前步骤请求
-> 应用当前 record 对该步骤的 request_overrides
-> 解析数据集变量、环境变量和上游步骤绑定
-> 按协议 Schema 校验最终请求
-> 执行并保存已解析请求快照
```

覆盖项优先于保存的请求快照，但模板解析发生在覆盖之后，因此覆盖值可以继续使用
`{{variable}}`。HTTP 步骤支持 `path`、`headers`、`query_params` 和嵌套 JSON `body`；
WebSocket 步骤支持 `path` 和 `headers`。覆盖只作用于当前 run 的请求副本，不修改场景版本。

核心资源列表统一使用 `{items,total,page,page_size}` 分页结构。HTTP 和 WebSocket 用例支持
关键字与环境筛选；可视化 Flow 支持关键字与状态筛选。列表查询在 Repository 层完成 count、
filter、offset 和 limit，Service 负责权限和响应组装。

### 4.9 统一错误边界

应用级异常处理器统一覆盖业务 HTTP 异常、请求校验、框架 404 和未处理异常：

```text
Router / Dependency / Service 抛出异常
-> StarletteHTTPException 保留状态码和结构化 detail
-> RequestValidationError 返回 422 字段定位数组
-> 未处理异常记录服务端堆栈和 request_id
-> 客户端统一接收 {code,message,data}
```

500 响应不泄露内部异常，使用 `X-Request-ID` 关联服务日志。公共 `ErrorResponse` Schema 和
常见状态码已注册到 OpenAPI。详细契约见 [统一错误响应文档](api_errors.md)。

### 4.10 步骤内部重试

HTTP 和 WebSocket 的自动重试位于协议执行器内部，而不是场景步骤结果路由层。单个步骤可
经历多个 attempt，但场景外层只接收最终成功或最终失败。

```text
发送请求或建立会话
-> 分类网络错误、超时、HTTP 状态
-> 必要时指数退避 + Full Jitter
-> 执行断言
-> 轮询断言必要时重试
-> 断言全部通过后提取变量
-> 返回步骤最终结果
```

HTTP 默认重试网络错误、超时、408、429、500、502、503、504；普通 4xx 不自动重试，
429 优先尊重 `Retry-After`。POST/PATCH 等非幂等方法默认禁止自动重试。WebSocket 每次
attempt 都重新建立连接并重放消息序列。所有 attempt 写入执行记录，失败 attempt 不修改变量。

### 4.11 统一执行记录查询

执行中心采用只读聚合层，不建立新的执行总表，也不改变四类执行器的持久化职责：

```text
GET /execution-records
-> ExecutionRecordService 校验 report:view
-> ExecutionRecordRepository
-> UNION ALL(
     test_case_executions,
     websocket_test_case_executions,
     test_scenario_runs,
     visual_flow_executions
   )
-> 公共筛选、计数、排序和分页
```

公共摘要统一执行类型、资源、项目、环境、触发人、状态、耗时、时间和错误信息。详情按
`execution_type + execution_id` 回查原始表，HTTP/WebSocket 保留请求或会话、响应、断言和
attempt 历史；场景保留 dataset record、变量、步骤结果和持久化事件；Flow 保留上下文和节点
执行明细。该边界使报告和趋势统计复用统一读取模型，同时避免复制历史数据或影响现有执行链路。

被删除资源通过外连接返回历史记录，资源名称允许为 `null`。统一执行记录是报告域能力，使用
`report:view`，不要求调用方同时具备四类资源查看权限。

### 4.12 媒体对象存储

缺陷图片采用 MySQL 元数据与 MinIO 对象分离的存储边界：

```text
前端 multipart 上传图片
-> FastAPI 校验项目权限、大小、MIME 和文件签名
-> MinIO 私有桶 testplatform 保存对象
-> media_objects 保存项目、所有者、对象键和文件元数据
-> 创建/更新缺陷时用 media_ids 绑定 defect_id
-> 查询缺陷时按需生成短期 S3 V4 预签名 URL
```

数据库不保存 MinIO 凭据，也不保存会过期的预签名 URL。对象键使用随机 UUID，原始文件名
仅作为展示元数据。当前仅接受 PNG、JPEG、GIF 和 WebP；SVG 因可嵌入脚本不进入首版白名单。
删除单个媒体、缺陷或项目时同步删除对象。MinIO 和 MySQL 不具备跨系统原子事务，因此删除
中存储不可用时接口返回 `503` 并保留数据库记录，便于重试；后续可增加 outbox 和孤儿对象巡检。

## 5. 自研测试报告设计

测试报告基于执行过程中的结构化数据生成，不依赖 Allure。

当前首版不建立独立报告表，而是使用测试计划运行和 Flow 执行的不可变快照生成只读报告：

```text
GET /reports
-> TestReportService 校验 report:view
-> TestReportRepository 聚合 test_plan_runs + visual_flow_executions
-> 返回报告历史摘要

GET /reports/{source_type}/{source_id}
-> plan: target_results + test_scenario_runs + step_results
-> flow: context_snapshot + visual_flow_node_executions
-> 生成统一 summary、来源专属 metrics 和 items
```

### 5.1 报告核心指标

报告应包含：

- 执行人
- 执行项目
- 执行环境
- 开始时间
- 结束时间
- 总耗时
- 总用例数
- 成功用例数
- 失败用例数
- 跳过用例数
- 总步骤数
- 成功步骤数
- 失败步骤数
- 断言总数
- 成功断言数
- 失败断言数
- 失败原因摘要

计划报告区分目标级计数和 dataset record 场景运行级计数。Flow 报告按节点统计通过、失败、
跳过和通过率。运行尚未完成时，结束时间和耗时允许为空。

### 5.2 步骤执行明细

每个步骤建议记录：

- 请求 method
- 请求 URL
- 请求 headers
- 请求 query
- 请求 body
- 响应 status_code
- 响应 headers
- 响应 body
- 请求耗时
- 断言结果
- 提取变量结果
- 错误信息

### 5.3 HTML 导出

HTML 导出与结构化报告使用同一读取模型，不再次查询或复制执行数据。导出内容包括摘要、
指标卡片和可展开的完整明细，使用 `Content-Disposition: attachment` 下载。所有运行名称、
节点标识和 JSON 明细在写入 HTML 前必须转义，防止执行数据形成脚本注入。

当前不持久化导出文件；每次下载即时生成。PDF 和长期归档仍属于后续阶段。

### 5.4 历史趋势

趋势接口在数据库内合并测试计划运行和 Flow 执行，按开始日期分组，统计执行次数、通过、
失败、其他状态、通过率和平均耗时。默认窗口 30 天，最大 366 天，可按来源类型和环境过滤。
趋势粒度是一次报告来源运行，不是计划目标、dataset record 或 Flow 节点。

### 5.5 数据存储注意事项

请求和响应数据可能很大，也可能包含敏感信息。

建议：

- 对超大响应体进行截断
- 对 token、password、secret 等字段脱敏
- 执行日志和报告设置保留周期
- 重要报告允许归档
- 当即时聚合无法满足数据量和归档要求时，再引入报告摘要与明细表

## 6. Redis 使用规划

Redis 在平台中主要用于临时数据和高频状态。

推荐使用场景：

| 场景 | 说明 |
| --- | --- |
| token 状态 | refresh token、黑名单、强制下线 |
| 任务状态 | pending、running、success、failed |
| 执行进度 | 当前步骤、总步骤数、进度百分比 |
| 临时变量 | 短生命周期执行上下文 |
| 接口限流 | 登录接口、执行接口限流 |
| 验证码 | 图形验证码、邮箱验证码、短信验证码 |

不建议把 Redis 作为主数据存储。用户、项目、用例、流程和报告应以 MySQL 为准。

## 7. MySQL 数据定位

MySQL 用于保存平台核心业务数据。

主要数据类型：

- 用户与角色
- 项目与成员
- 环境配置
- 接口定义
- 测试用例
- 测试流程
- 执行任务
- 执行结果
- 测试报告
- 操作日志

设计建议：

- 所有核心表保留 created_at、updated_at
- 重要业务表保留 created_by、updated_by
- 删除优先使用软删除
- 流程步骤保留排序字段
- 报告表注意索引设计
- 大字段谨慎入库，必要时拆分明细表

## 8. 技术选型优劣

### 8.1 FastAPI

优点：

- 性能好
- 类型提示友好
- 自动生成 OpenAPI 文档
- 与 Pydantic 集成紧密
- 适合前后端分离 API 项目

缺点：

- 分层架构需要自行规划
- 异步和同步代码混用时需要规范
- 大型项目需要提前设计依赖注入和异常处理

### 8.2 MySQL

优点：

- 成熟稳定
- 部署和运维经验丰富
- 适合保存平台业务数据
- 生态完善

缺点：

- 对复杂 JSON 查询不如 PostgreSQL
- 报告明细数据量大时需要分表、归档或冷热分离
- 并发写入较高时需要优化索引和事务范围

### 8.3 JWT

优点：

- 适合前后端分离
- 服务端可以保持较轻状态
- 易于多端接入

缺点：

- token 签发后无法天然失效
- 退出登录、强制下线需要 Redis 配合
- token 泄露后需要依赖过期时间和黑名单控制风险

### 8.4 Redis

优点：

- 性能高
- 适合缓存、任务状态和短生命周期数据
- TTL 能力适合 token、验证码和临时变量

缺点：

- 不能替代 MySQL 保存核心业务数据
- 需要关注内存容量和过期策略
- 生产环境需要考虑持久化和高可用

### 8.5 requests

优点：

- 简单稳定
- 社区成熟
- 适合自研 HTTP 执行器
- 更方便将请求、响应、断言结果结构化入库

缺点：

- 同步阻塞，不适合直接在 API 请求线程中跑长流程
- 并发能力依赖任务队列或线程/进程模型
- 需要自研变量、断言、失败策略和报告能力

### 8.6 自研报告

优点：

- 数据结构完全可控
- 更适合平台页面展示
- 可以深度结合项目、环境、流程和历史趋势
- 不受 Allure 数据格式限制

缺点：

- 需要自行设计报告模型
- 需要自行实现报告统计和可视化
- 需要处理大字段、脱敏和历史归档

## 9. 推荐建设阶段

### 第一阶段：基础平台

- 项目结构搭建
- MySQL 接入
- SQLAlchemy 和 Alembic 接入
- JWT 登录认证
- Redis 接入
- 用户、项目、环境基础 CRUD

### 第二阶段：接口测试核心

- 接口定义管理
- 单接口调试
- 接口用例保存
- 变量替换
- 基础断言
- 执行结果保存

### 第三阶段：流程编排

- 多接口步骤编排
- 上下文变量传递
- 响应提取
- 失败处理策略
- 流程执行记录

### 第四阶段：自研报告（基础能力已实现）

- 执行摘要
- 步骤明细
- 断言明细
- 失败原因
- 历史报告查询
- 报告趋势统计
- HTML 离线导出

### 第五阶段：任务系统

- 场景异步执行与持久化 SSE（已完成基础版本）
- 独立 Worker、任务 claim 和重启恢复
- 定时执行
- 批量执行
- 实时进度协议扩展到可视化 Flow
- 执行取消

### 第六阶段：平台增强

- 角色权限
- 操作日志
- 接口限流
- 数据脱敏
- 报告归档
- WebSocket 实时日志

## 10. 当前结论

当前项目已完成认证、项目权限、环境、HTTP/WebSocket 用例、场景组合、测试计划、
浏览器采集、场景实时执行、统一执行记录、报告查询、HTML 导出和按日趋势等核心能力。
后续主线为执行可靠性、前端联调以及报告归档和 PDF 扩展：

```text
FastAPI API 服务
-> MySQL 业务数据
-> JWT 用户认证
-> httpx 自研接口执行器
-> MySQL 持久化运行快照与 SSE 事件
-> 跨协议统一执行记录读取模型
-> 独立 Worker 和可靠任务领取
-> 自研测试报告与趋势读取模型
```

这套架构更适合建设一个真正的平台型后端，而不是简单调用第三方测试框架。它的前期建设成本略高，但对可视化编排、执行历史、报告分析、权限管理和后续扩展更友好。
