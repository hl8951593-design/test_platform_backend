---
name: assertion-extractor-binding
description: Use when the user asks to design, repair, or diagnose assertions, extractors, variable paths, JSON path/dot path conversion, response-field binding, upstream/downstream parameter flow, or missing variable failures.
triggers:
  - 断言
  - 提取器
  - 提取路径
  - 变量绑定
  - 变量传递
  - JSONPath
  - dot path
  - 响应字段
  - 上下游
  - 参数流
  - missing variable
  - extractor
  - assertion
routing_requires_tool:
  - real assertion failure
  - real extractor failure
  - current response sample
  - variable binding failure
  - upstream response
  - 真实断言失败
  - 真实提取失败
  - 当前响应样本
  - 变量绑定失败
  - 上游响应
---

# Assertion Extractor Binding

## Workflow

1. Determine whether the issue is request rendering, response assertion, extractor path, variable scope, dataset override, or downstream binding.
2. Use real response samples, execution details, or report summaries before asserting exact JSON paths or actual values.
3. Prefer platform dot-path notation when the platform expects it, for example `data.dataList.0.companyId`; explain conversions from bracket notation when useful.
4. Extract variables only after assertions that prove the response is valid enough to trust. Do not bind downstream steps to fields from failed responses unless explicitly intended.
5. For saved-case assertion follow-ups, use same-conversation context or `testcase.query_project_cases` to recover real HTTP/WebSocket ids before saving; never infer a continuous id range from a table or prose.
6. To save assertion-only changes, use `testcase.update_assertions` / `testcase.batch_update_assertions` for HTTP cases or `websocket_testcase.update_assertions` / `websocket_testcase.batch_update_assertions` for WebSocket cases after user approval. These tools preserve request, extractor, retry, and connection/message configuration.
7. Do not use `ai_skill.run_draft` with `skill_id=http-test-case` and `operation=generate` to save or regenerate assertions for existing saved cases; that generate operation requires `interface_text` and is only for new draft creation from interface material.
8. For missing sample responses, provide candidate paths and ask for the response or recommend a dry-run/read tool instead of inventing field locations.

## Final Reply

- List fixed bindings separately from unresolved paths.
- State the source step, extracted variable name, path, target request field, and fallback behavior.
- Do not claim a path was validated unless a tool result or response sample proves it.
