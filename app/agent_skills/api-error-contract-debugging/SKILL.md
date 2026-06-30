---
name: api-error-contract-debugging
description: Use when the user asks to diagnose backend API error responses, HTTP status mismatches, request validation errors, 401/403/404/409/422/500 responses, request_id log tracing, or frontend error-display contract issues.
triggers:
  - 错误响应
  - 统一错误
  - request_id
  - 400
  - 401
  - 403
  - 404
  - 409
  - 422
  - 500
  - validation failed
  - HTTP 状态码
  - ErrorResponse
routing_requires_tool:
  - real API error
  - request_id logs
  - validation error detail
  - current error response
  - frontend error display
  - 真实API错误
  - request_id日志
  - 校验错误详情
  - 当前错误响应
  - 前端错误展示
---

# API Error Contract Debugging

## Workflow

1. Classify the error as authentication, authorization, validation, business conflict, missing resource, upstream failure, execution failure, or internal error.
2. Use status code, `code`, `message`, `data`, `X-Request-ID`, and SSE event payloads consistently. SSE errors after stream establishment are event-level errors, not normal JSON error responses.
3. For real incidents, require the actual response body, request id, run id, or tool/report evidence before naming a root cause.
4. For frontend contract questions, map each status to the expected UI behavior and field location strategy.
5. Do not expose stack traces, secrets, SQL, token values, or internal exception details in final replies.

## Final Reply

- Provide a concise classification, likely cause, and next diagnostic evidence.
- Include the expected error envelope when the user asks for contract shape.
- Do not invent request ids, log lines, or hidden server errors.
