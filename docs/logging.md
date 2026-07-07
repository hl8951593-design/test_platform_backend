# 后端日志与报错排查

后端启动时会初始化统一日志，默认同时输出到控制台和 `logs/app.log`。

## 日志轮转与 Windows 文件锁

文件日志使用 Windows-safe rotating handler。默认 `logs/app.log` 达到 10MB 后会轮转，
最多保留 5 个历史文件。

在 Windows 本地开发、热重载或多个后端进程同时启动时，另一个进程可能正在占用
`logs/app.log`。标准 `RotatingFileHandler` 会在 rename 轮转时抛出
`PermissionError: [WinError 32]`，并打印 `--- Logging error ---`。当前实现会把这类
文件占用视为“轮转暂时不可用”：延迟 60 秒后再尝试轮转，期间继续写当前 `app.log`，
避免一次日志轮转失败影响接口请求、Agent trace 或执行队列日志。

如果部署形态需要多 worker 长期同时写日志，优先选择：

- 采集控制台 stdout/stderr，由进程管理器或日志平台负责切分和归档。
- 为不同进程配置不同的 `LOG_FILE_PATH`，避免多个进程竞争同一个轮转文件。

## 请求追踪

每个请求都会带一个 `request_id`：

- 如果前端请求头传了 `X-Request-ID`，后端沿用该值。
- 如果没传，后端自动生成 UUID。
- 响应头会返回 `X-Request-ID`。

排查前端报错时，先在浏览器 Network 面板找到响应头 `X-Request-ID`，然后在日志中搜索：

```text
[request-id]
```

## 日志内容

请求完成日志包含：

- `method`
- `path`
- `query`
- `status`
- `duration_ms`
- `client`

示例：

```text
2026-06-24 21:49:56 INFO [request-ok] app.request - request_completed method=GET path=/api/v1/test-cases query=project_id=1 status=200 duration_ms=18 client=127.0.0.1
```

## 错误日志

后端会记录：

- HTTPException，例如 400、404、409、502。
- 请求参数校验失败，例如 422。
- 未处理异常，例如 500，并带完整堆栈。
- 执行队列任务入队、开始、完成和失败，包含 `task_id`、`request_id`、执行函数和耗时。
- AI 返回 JSON 异常与模型修复失败，包括 `skill_id`、错误信息和截断后的模型输出预览。

AI JSON 相关关键词：

```text
AI skill returned invalid JSON
AI skill JSON repair failed
```

排查顺序：

1. 先搜索同一个 `request_id` 下的 `AI skill returned invalid JSON`，查看 `skill_id`、解析错误和 `raw_preview`。
2. 如果后续没有 `AI skill JSON repair failed`，说明本地解析兼容或一次模型修复已经恢复，接口可能仍成功返回。
3. 如果出现 `AI skill JSON repair failed`，说明本地修复和模型修复都失败，接口会返回 502；需要检查对应 skill prompt 是否缺少严格根对象、字段名、断言字段或控制字符约束。
4. HTTP 用例生成/扩写应重点检查模型是否输出了拆行字段名、字符串裸换行、未闭合引号、`assertions[].value` 等不符合契约的内容。

异步执行队列相关关键词：

```text
Execution worker task accepted
Execution worker task started
Execution worker task completed
Execution worker task failed
Execution worker queue full
```

## Agent 详细排障日志

Agent Runtime 额外使用 `app.agent.trace` logger 输出结构化排障日志，默认写入同一个
`logs/app.log`。默认日志只记录流程元数据、字段名、数量、长度、hash、状态和耗时，不记录完整
prompt、用户回复正文、请求头、请求体、响应体或工具完整输出。

如果本地排障需要看到 DeepSeek 实际返回和工具执行结果，可以显式打开正文预览：

```text
AGENT_TRACE_VERBOSE_PAYLOADS=true
AGENT_TRACE_PAYLOAD_MAX_CHARS=12000
```

开启后仍会做长度上限控制，并对工具 payload 里的 Authorization、token、password 等敏感字段脱敏。
该开关只建议在本地或临时排障环境打开，不建议生产常开。

如果本地排障需要看到组合后的完整模型 messages、完整模型返回、完整工具入参和完整工具结果，可以显式打开 full payload：

```text
AGENT_TRACE_FULL_PAYLOADS=true
```

该模式会额外输出 `*_full` 字段，不受 `AGENT_TRACE_PAYLOAD_MAX_CHARS` 裁剪，用于复现模型实际看到的组合提示词和工具结果链路。结构化 dict/list payload 仍会按敏感 key 脱敏，例如 Authorization、token、password、secret；纯文本 prompt / 模型回复会按全文写入日志。该开关可能产生大量日志并包含用户输入，只建议在本地或短时排障环境开启。

常用检索关键词：

```text
app.agent.trace
agent_trace_run_start
agent_trace_iteration_start
agent_trace_model_call_start
agent_trace_model_call_done
agent_trace_model_response_payload
agent_trace_model_prompt_full_payload
agent_trace_model_response_full_payload
agent_trace_tool_request_detected
agent_trace_tool_call_created
agent_trace_tool_call_executed
agent_trace_tool_output_payload
agent_trace_tool_input_full_payload
agent_trace_tool_output_full_payload
agent_trace_tool_call_needs_human
agent_trace_tool_backend_start
agent_trace_tool_backend_done
agent_trace_tool_backend_result_payload
agent_trace_tool_backend_input_full_payload
agent_trace_tool_backend_result_full_payload
agent_trace_run_completed
agent_trace_run_failed
```

默认 `LOG_LEVEL=INFO` 时，可以看到：

- run 启动、循环 iteration、最终完成或失败。
- 每次模型调用的开始、结束、模型名、finish_reason、输出长度、是否流中断。
- 模型识别出的工具名、证据引用数量和工具调用创建。
- 工具执行状态、错误码、输出 hash 和输出结构大小。
- 工具 backend 的开始、完成、失败和耗时。
- 人工审批阻断、前置工具缺失、最终总结阶段工具请求被抑制等关键分支。

打开 `AGENT_TRACE_VERBOSE_PAYLOADS=true` 后，额外可以看到：

- `agent_trace_model_response_payload`：DeepSeek 本轮流式输出组装后的完整预览。
- `agent_trace_tool_backend_result_payload`：工具 backend handler 的真实返回结果预览。
- `agent_trace_tool_output_payload`：工具结果进入 Agent 运行时后的输出预览。
- `*_preview_chars`、`*_size_chars`、`*_truncated`、`*_hash`：用于判断是否截断和对齐前后日志。

打开 `AGENT_TRACE_FULL_PAYLOADS=true` 后，额外可以看到：

- `agent_trace_model_prompt_full_payload`：调用模型前最终组合的 messages，包括 system prompt、run context、Skill context、history、tool result context 和当前用户意图。
- `agent_trace_model_response_full_payload`：DeepSeek 本轮流式输出组装后的全文。
- `agent_trace_tool_input_full_payload`：Agent ToolCall 创建时的完整入参。
- `agent_trace_tool_output_full_payload`：ToolCall 执行后进入 Agent runtime 的完整 redacted output。
- `agent_trace_tool_backend_input_full_payload`：工具 backend handler 收到的完整 payload。
- `agent_trace_tool_backend_result_full_payload`：工具 backend handler 返回的完整结果。
- `*_full`、`*_size_chars`、`*_hash`：用于直接查看全文并对齐前后日志。

如果需要进一步检查上下文预算和模型消息规模，把 `.env` 中日志级别调为：

```text
LOG_LEVEL=DEBUG
```

DEBUG 级别会额外记录：

- 模型调用前的 message 数量、角色分布和总字符数。
- 工具结果进入模型上下文时的已用字符、剩余预算、追加字符数和是否被截断。
- 工具结果上下文预算耗尽或已截断后跳过追加的原因。

排查一轮 Agent 卡住或前端显示异常时，推荐顺序：

1. 先按浏览器 Network 里的 `X-Request-ID` 搜索 `logs/app.log`。
2. 再按 `run_id=` 搜索同一轮 Agent 的所有 `app.agent.trace` 日志。
3. 如果模型没有继续调用工具，查看 `agent_trace_model_call_done` 的 `finish_reason`、`content_length` 和 `tool_request_marker_seen`。
4. 如果工具执行后卡住，查看 `agent_trace_tool_call_executed`、`agent_trace_tool_result_context_append` 和后续是否出现 `agent_trace_model_call_start`。
5. 如果审批后没有最终回复，查看 `agent_trace_complete_after_tool_results_start`、`agent_trace_final_summary_tool_request_suppressed` 和 `agent_trace_run_completed`。

## 配置项

可通过 `.env` 覆盖：

```text
LOG_LEVEL=INFO
LOG_FILE_PATH=logs/app.log
LOG_REQUESTS=true
LOG_SLOW_REQUEST_MS=1000
AGENT_TRACE_VERBOSE_PAYLOADS=false
AGENT_TRACE_FULL_PAYLOADS=false
AGENT_TRACE_PAYLOAD_MAX_CHARS=12000
```

`LOG_REQUESTS=false` 时，普通 2xx/3xx 请求不记录；4xx/5xx 和慢请求仍会记录。
