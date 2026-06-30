# 自动化测试平台后端技术架构文档

状态：当前实现
最后核验：2026-06-30

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
| 实时事件 | SSE + MySQL 持久化事件表 | 支持鉴权请求头、Last-Event-ID 重放、心跳和终态关闭 |
| 测试报告 | 自研 | 基于执行记录生成平台内置报告 |
| 配置管理 | pydantic-settings + .env | 管理环境配置 |
| 日志 | Python logging 或 loguru | 记录系统日志和执行日志 |

`/api/v1/agents/model-health` 的 `error_message` 仍保持字符串字段以兼容前端，但 live probe 的长错误不会原样透出：短错误直接返回，超过 `AGENT_ERROR_MESSAGE_MAX_CHARS=512` 的 provider/HTTP 异常会被 `_bounded_agent_error_message()` 收口为 `agent_error_message_summary_v1` preview、截断标记、原始长度、hash 和 `full_error_reference`，避免模型供应商长响应或异常尾部进入前端探测结果。

Harness Loop Agent 的业务工具调用走 Codex 式闭环：Runner 组装 run context、ToolRegistry、权限边界和历史上下文后调用 `AIService`，模型只能通过受控 `agent_tool_request` 发起 ToolCall，Harness 执行后把 `tool.result_observed` 回灌给下一轮模型；其中项目 Memory 以 `conversation_context` 注入时只进入有界系统消息，title/content 字段级截断且整条消息受 `AGENT_MEMORY_CONTEXT_MESSAGE_MAX_CHARS` 保护，完整 Memory 正文仍以 Memory/usage 审计接口为准。模型输出的 fenced JSON 先被解析成内部 `AgentToolRequest` envelope，再进入 EventStore 和 ExecutionLedger：该 envelope 只保留 `tool_name`、`tool_input`、`reason`、`evidence_refs` 四类受控字段，并通过拷贝方法生成 ToolCall input/evidence 与 `model.tool_request_detected` payload，未知模型字段不会穿透到后端账本或前端事件。ToolCall 执行链路已拆成 `ToolExecutor` 生命周期编排、`AgentToolRuntime` 后端调用门面、`AgentToolRouter` 显式 handler 路由三层：Executor 负责审批/权限/队列/EventStore 状态推进，Runtime 负责把已落账的 ToolCall 转成后端执行请求，Router 负责从 `ToolRegistry` 的私有 `backend_handler` 解析可调用处理器。普通自然语言流式回复采用低延迟 EventStore/SSE 路径：首个可见 `model.delta` 立即写入，后续小碎片按短时间窗口或字符阈值微批提交，减少高频数据库事务；但涉及项目上下文、场景组合、保存动作等工具规划轮时，Runner 会先静默收流并解析工具请求，防止内部 `agent_tool_request` JSON 或候选分析泄露到 assistant 气泡；若工具 fenced block 在短暂可见 preamble 之后才到达，Runner 会用同一 `model_call_id` 写入 `model.markdown_normalized(content="", replace_content=true, normalization_reason=tool_request_stream_suppressed)` 撤回临时文本，再写入 `model.tool_request_stream_suppressed` 审计事件；若静默规划轮最终产出普通文本，Runner 只补发一个合并后的可见 `model.delta`，避免长文本逐 token 回放压住 SSE/EventStore；模型若把自然语言和单个工具 fenced block 混在一起，会优先本地挽救并规范化轻微 schema 偏差，其他非法格式才进入一次 LLM 工具请求修复；工具请求格式修复和 required follow-up 缺失修复的模型调用只接收 `AGENT_REPAIR_CONTEXT_MAX_CHARS` 内的上一轮输出上下文，超长内容以 `agent_repair_context_truncated` 标记截断，不把完整异常文本重新注入模型。SSE 对 `queued/running` run 使用短轮询，对非活跃状态保持普通轮询和 heartbeat。`Last-Event-ID` 与 `after_sequence` 是 run-scoped cursor；若客户端把其他 run 的较大 cursor 带到当前 run，后端会在 cursor 大于当前 `last_event_sequence` 时重置为 0 重放当前 run 事件，避免 heartbeat-only 连接。为避免 worker 崩溃、进程重启或前端错过终态导致 UI 无限“正在思考”，Agent read paths 会用最新 EventStore 事件时间识别超过 `AGENT_RUN_STALE_TIMEOUT_SECONDS` 的 `queued/running` run，并写入 `run.failed(agent_run_stale_worker_lost)` 作为可审计终态；所有通过 `AgentRuntimeService.fail_run()` 写入的 `AgentRun.error_message` 与 `run.failed.payload.error_message` 仍保持字符串兼容，短错误原样返回，长错误通过 `agent_error_message_summary_v1` 写入 preview、截断标记、原始长度、hash 与 `full_error_reference`，Runner 的 HTTP/未预期失败日志也记录同一有界字符串和 `error_type`，不再用 `logger.exception` 打完整异常尾部；若 DeepSeek 已产生部分内容后流式连接中断，Runner 写入 `model.stream_interrupted` 并尽量用 partial content 继续解析/完成，避免用户可见结果为空。Agent 同时具备软件测试领域的通用自然语言回答能力：测试理论、用例设计、接口/WebSocket 测试、断言、测试数据、缺陷定位、回归策略、CI 和报告解读等不需要项目实时事实或平台副作用的问题，可以直接通过 `model.delta`/`run.completed.result.message` 回答；超出软件测试领域的问题必须说明边界。工具结果质量闭环由 `ToolResultPolicy` 统一实现：任何成功 ToolCall 输出中的 `warnings`、`issues`、`diagnostics`、`errors` 或 `valid=false` 都会被抽取并拆分为可自动修复项、用户/外部配置阻断项和待模型继续判断项；按工具推荐的修复路径由各 `ToolSpec.tool_result_repair_guidance` 后端私有字段声明，策略层只负责读取元数据和通用 fallback；回灌给模型的工具结果消息必须有硬上限，小输出保持原 `output` 结构，大输出只给 `output_preview`、`output_truncated`、`output_size_chars`、`output_hash` 和 `full_output_reference`，完整 `output_json_redacted` 继续留在 ToolCall Detail；多条工具结果进入后续模型调用或审批恢复 final summary 前还受 `AGENT_TOOL_RESULT_CONTEXT_TOTAL_MAX_CHARS` 聚合预算约束，超出部分用 `agent_tool_result_context_truncated` 标记，完整输出仍留在 ToolCall/summary/report 详情中；失败 ToolCall 若错误属于输入、schema、validation、草稿结构或字段格式，也会进入修复闭环；若修复后同一工具连续两次以相同 `error_code` 与 `error_message` 失败，Runner 会写入 stop 用 ContextBuild 与 `loop.observed(RC_NO_PROGRESS_PURE)`，并以 `run.failed(agent_repair_no_progress)` 停止继续消耗模型和工具循环；硬编码字段、结构校验、提取器、断言 expected、数据集、schema/type/format 等可由平台数据或安全工具推断的问题，应优先通过 read/query/draft/validate/dry-run 工具继续修复或验证，鉴权令牌、账号密码、密钥、审批或没有平台来源的私有输入才交给用户。工具结果后的最终回复默认只输出已完成、已自动修复/验证、剩余阻断项和下一步，完整草稿结构和长 JSON 留在 ToolCall/summary/report 详情中。场景组合仍是当前强约束 recipe，但规则来源已收口到 Skill/ToolSpec：`scenario-composition/SKILL.md` 的私有 `routing_required_tool_after_success` 负责 query 成功后缺 compose 的静默修复，且可用 `intent_markers` 把 follow-up 限定在生成、创建、组合、执行场景、场景草稿、dry-run、数据集/参数化等明确场景编排意图内；`scenario.compose_draft` 的 ToolSpec 私有 `required_successful_tool_before` 负责执行前顺序校验。直接 compose 会被 Runner 以 `scenario_compose_requires_case_query` 阻断并回灌给模型纠正；query 成功但模型没有继续 compose 时，只有命中 `intent_markers` 才会写入 `model.required_tool_missing(after_tool, required_tool)`，绑定修复用 decision ContextBuild，写入 `loop.observed(RC_REQUIRED_TOOL_FOLLOWUP_MISSING)` 并静默修复。纯项目上下文、资源盘点或“是否已有场景”这类只读问题即使命中 scenario Skill，也允许在 read/query 工具后直接给最终总结。保存/持久化这类副作用遵循 Skill 声明式语义 guardrail：`guard_unsupported_capability` 声明缺失工具集合、预检查关键词、分类 prompt、分类 JSON 字段、最终消息资源和 completion source；Runner 只解释规则，只有分类确认用户要求正式持久化且 ToolRegistry 没有对应工具时，才以 `unsupported_scenario_save_guard` 说明当前无法保存；“不要保存/仅生成草稿”的请求继续走 query-first 组合链路。

工具请求解析/修复错误事件也遵循同一有界诊断原则：`model.tool_request_invalid.payload.error_message`、对应 LoopObservation 的 `observation_json.error_message`、修复 prompt 中嵌入的错误摘要，以及 `model.tool_request_repair_failed.payload.error_message` 都只保留短错误原文或 `agent_error_message_summary_v1` 有界摘要；长 parse/repair 异常以 preview、截断标记、原始长度、hash 和 `full_error_reference` 表达，不把完整模型输出解析异常尾部复制到 EventStore/SSE timeline 或下一次模型修复上下文。

ToolPolicyResolver 会把工具策略判定固化到 `AgentToolCall.policy_reason_json.policy_context`：该 envelope 记录 `policy_version_hash`、tool name/version、base/resolved side effect、base/resolved replay policy、approval policy、approval reason、active/volatile/frozen policy evidence 计数、mixed evidence 标记和 `policy_hash`。这样 ToolCall Detail、Runbook 和后续评测可以从一个稳定 hash 解释“为什么该工具需要审批、为什么 replay policy 被提升为 require_revalidation、以及本次策略解析基于哪些证据类别”，形态上更接近 openai/codex per-turn `approval_policy` 与工具上下文，但不暴露原始 evidence 内容。

ToolExecutor 在工具真正跨过 runtime/backend routing 边界后，还会把 `policy_reason_json.dispatch_trace` 写入 ToolCall：该白名单 trace 记录 dispatch trace version、tool/run/runtime snapshot 标识、tool name/version、schema/manifest hash、`AgentToolRouter.resolve`、`AgentToolRuntime.execute`、backend handler、backend contract 标识、resolved side effect/replay policy、最终状态和 `dispatch_trace_hash`。这让 ToolCall Detail、Runbook 和评测可以解释“模型请求的工具到底被哪个 router/runtime 分派到了哪个后端 handler”，形态上对齐 openai/codex 的 tool router/orchestrator/dispatch trace 分层，但不复制原始 input、output、evidence 或业务 payload。若 effect 已提交但后续 EventStore 写入失败，ToolExecutor 会在标记 `uncertain(eventstore_write_failed_after_effect)` 后重新生成 dispatch trace，确保 trace 中的 `status` 与 `effect_submission_state` 表达最终恢复状态，而不是保留写事件前的成功态。

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

同一个用户问题在 Agent loop 中可能触发多次 LLM 调用，后端通过 `iteration_id`、`model_call_id`、`loop_step` 把 `model.started`、`model.delta`、`model.markdown_normalized`、`model.completed`、`model.stream_interrupted` 串成可追踪的调用链，并通过嵌套 `loop_state` envelope 明确 `iteration`、`phase`、`step`、`model_call_id`、`tool_call_id` 与 `decision_reason`。旧顶层 trace 字段继续保留，方便前端兼容；新 envelope 让评测报告和调试 UI 可以区分普通回答、工具规划、工具请求修复、必需工具修复、工具执行/观察、最终总结和意图能力 guard，也让前端不再把工具规划轮的暂时无 delta 误判为后端卡死。工具前置条件被 Harness 阻断时，runner 会同时创建修复用 decision ContextBuild 和 `loop.observed`，以 `RC_TOOL_PREREQUISITE_MISSING` 记录需要先调用的 prerequisite tool；模型输出非法 `agent_tool_request` 时同样以 `RC_TOOL_REQUEST_FORMAT_INVALID` 记录格式修复决策，避免这些可恢复纠错只表现为普通审计事件或 `tool.failed`。

当工具闭环达到 `run.max_iterations` 后仍需要给用户最终总结时，Runner 会先绑定 stop 用 decision ContextBuild，并写入 `loop.observed(RC_MAX_ITERATIONS)`，`next_action=stop`、`reasons=[max_iterations]`，再进入 `final_summary` 模型调用。这让迭代上限从隐式 for-loop 退出变成可审计 Resource / Limit 决策；前端和 Runbook 应把它展示为 stop observation，而不是 assistant 文本或普通工具失败。`AgentMetricsService.snapshot` 也会按 LoopObservation 的 stop reason 输出运行时纠错/停止指标：`tool_prerequisite_missing_total`、`tool_request_format_invalid_total`、`required_tool_followup_missing_total`、`max_iterations_total` 与 `same_failure_no_progress_total`，并纳入 dashboard `metrics_catalog_complete`，防止已审计的 Agent 循环纠错原因只停留在事件流里。`AgentRunbookService.diagnose_run` 会把这些已知运行时 repair/stop observation 聚合为 `agent_runtime_loop_repair` recommendation，携带 observation id、RootCause、stop reason 和 mitigation，作为 loop diagnostics 的跳转入口。

DeepSeek stream 只在首个 `delta/done` 前做可配置重试，避免 provider 首包前 SSL EOF、连接重置或短暂 5xx 直接让 run 失败；每次 retry 写入 `model.stream_retrying`，payload 只包含 attempt、delay 和安全错误摘要，不包含 prompt、API key 或请求体。若已经收到 partial content 后才断流，则保持 `model.stream_interrupted` 路径，用 partial content 尽量继续完成，避免重复输出；`model.stream_interrupted.payload.error_message` 与 interrupted `model.completed.error_message` 同样只写入 `agent_error_message_summary_v1` 有界摘要或短错误原文，不复制 provider/HTTP 长响应尾部。

数据库连接池默认开启 pre-ping、recycle、MySQL connect timeout 和 pool size/overflow/timeout 配置。SQLAlchemy transient disconnect 进入统一错误处理分支，返回 503 `database_connection_lost` 与 `Retry-After: 1`，并 dispose 当前 engine pool，让后续请求重新建连；业务响应不暴露 SQL、DSN 或堆栈。

为提高多轮 agent 的 provider prompt/cache 命中率，Runner 构造系统提示时保持稳定前缀：ToolRegistry 清单按工具名排序，工具 JSON 使用固定字段排序和紧凑分隔符序列化；只要工具集合和策略版本未变，同一 runtime hash 下重复构建的系统提示字符串应保持一致。

Runner 同时对服务端 conversation history 执行轻量上下文预算控制：同一会话历史最多取最近若干轮，估算 token 超过预算时把较早轮次压成一个 system 摘要，并保留最近完整轮次的截断内容；压缩会写入 `context.history_compacted` 审计事件，前端和评测可以据此区分“长历史被压缩”与“历史丢失”。

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

`ContextBuilder` 会在 `build_metadata_json` 中记录本轮实际选中的 Agent Skill 摘要、匹配到的私有 routing rule 摘要、run 当前 RuntimeSnapshot 摘要和当前操作者的项目权限上下文摘要。Skill 侧只保存 name/hash、after_tool/required_tool/rule_hash 等诊断字段，不落私有规则原文或 Skill 正文；runtime 侧只保存 snapshot id、runtime/tool registry/manifest/prompt/policy hash、available tool names 和 tool count，不复制完整工具 schema；permission 侧只保存 actor/project/access level、显式权限码列表/count 和 permission hash，不复制用户资料或完整授权表。这样 required-tool follow-up、unsupported capability guard、工具前置阻断、权限相关停止决策和后续 Runbook 都能从 decision ContextBuild 追溯“为什么这轮模型被要求继续调用某个工具，以及当时基于哪版工具/策略/权限环境”，形态上接近 openai/codex 的 per-turn `TurnContext`，但仍保持前端 catalog 只读元数据边界。

当前内置 Agent Skill：

- `general-testing-answer`：软件测试、自动化、接口/WebSocket、断言、提取器、测试数据、缺陷、CI、报告等通用问答。
- `project-context`：当前项目上下文、真实项目用例、资源和实时平台事实读取；通过 `project.read_context` 或 `testcase.query_project_cases` 取得证据。
- `project-permission-admin`：项目、成员、角色、管理员、项目创建者、普通测试人员、权限码、项目访问和 403 授权失败诊断；没有权限写入 ToolCall 时只给管理员操作清单。
- `environment-config-management`：多环境、默认环境、`base_url`、环境变量、鉴权变量、变量替换和多环境绑定建议；真实环境事实通过 `project.read_context` 取得。
- `security-auth-testing`：鉴权、认证、授权、JWT/token/session/cookie、权限边界、越权、限流、CSRF 和安全负向测试；真实令牌或权限状态必须由工具证据确认，私密凭据不能编造或输出。
- `api-definition-import`：OpenAPI/Swagger、接口定义、接口资产、endpoint catalog、path/method/schema 提取和从接口生成用例规划；缺少接口资产写入工具时不声称导入或保存。
- `ai-skill-runtime-governance`：AI Skill 包、manifest/schema、prompt、JSON 修复、模型输出、provider 状态和 AI Skill Run 可观测诊断；生成结果始终保持草稿边界直到保存工具确认。
- `http-test-case-design`：HTTP/API 测试用例设计、生成、扩写、断言、提取器、变量、请求体和 Schema 校验；需要草稿时通过 `ai_skill.run_draft` 调用 `http-test-case`，需要结构校验时使用 `testcase.validate_schema`。
- `websocket-test-case-design`：WebSocket 握手、鉴权 header、子协议、消息顺序、接收断言、超时、ping/pong 和关闭行为；需要草稿时通过 `ai_skill.run_draft` 调用 `websocket-test-case`。
- `assertion-extractor-binding`：断言、提取器、变量路径、响应字段、上下游参数流和变量绑定修复；真实路径必须来自响应样本、执行详情或报告证据。
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

新增 Agent 能力时优先添加或修改独立 `SKILL.md` 的正文、`triggers` 和必要的私有 `guard_*` / `routing_*` hints；窄 guard 或 classifier 的长提示词与 guard 最终回复放入同 Skill 目录的私有资源文件，再用 registry 单测锁定触发范围；每个按 intent 注入模型的 Skill prompt block 必须有硬上限，unsupported capability classifier prompt 作为模型系统消息时也必须受 `AGENT_UNSUPPORTED_CAPABILITY_CLASSIFIER_PROMPT_MAX_CHARS` 保护，超长正文或私有分类提示词只能以截断标记进入模型上下文，避免业务规则增长破坏 prompt budget。需要表达“用户要求的能力当前缺少后端工具”的边界时，优先新增 `guard_unsupported_capability` 规则，而不是在 Runner 中新增业务专用 guard。需要强制静默工具规划或漏调用修复的实时平台事实请求应优先补充 `routing_requires_tool` 或 `routing_required_tool_after_success`，其中 follow-up 规则应配置足够窄的 `intent_markers`，避免只读查询被 broad trigger 误推进到写草稿/执行类工具；不要为了新增业务领域继续修改中央 prompt 或硬编码 Python 路由表。只有需要稳定审计、权限、幂等、EventStore、ToolCall 生命周期、执行前安全顺序校验或工具结果修复路径的规则才下沉到 Runner/ToolRegistry 代码中。ToolRegistry 的内置 `ToolSpec` 同时声明后端私有 `backend_handler`、可选 `required_successful_tool_before` 和可选 `tool_result_repair_guidance`，`AgentToolBackend` 从 spec 解析执行函数，Runner 从 spec 解析前置工具要求，`ToolResultPolicy` 从 spec 解析工具结果修复 guidance，避免工具 manifest、执行 map、前置校验和修复策略分叉；这些后端私有字段不进入 `to_json()`、模型初始工具清单或前端契约。

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
