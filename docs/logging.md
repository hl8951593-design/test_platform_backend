# 后端日志与报错排查

后端启动时会初始化统一日志，默认同时输出到控制台和 `logs/app.log`。

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

## 配置项

可通过 `.env` 覆盖：

```text
LOG_LEVEL=INFO
LOG_FILE_PATH=logs/app.log
LOG_REQUESTS=true
LOG_SLOW_REQUEST_MS=1000
```

`LOG_REQUESTS=false` 时，普通 2xx/3xx 请求不记录；4xx/5xx 和慢请求仍会记录。
