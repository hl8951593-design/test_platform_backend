---
name: websocket-test-case-design
description: Use when the user asks to design, generate, expand, validate, debug, or explain TestAuto WebSocket test cases, handshake headers, subprotocols, message sequence, receive assertions, timeout, close behavior, or long-connection debugging.
triggers:
  - WebSocket
  - websocket
  - ws
  - wss
  - 长连接
  - 握手
  - 子协议
  - 消息顺序
  - 接收消息
  - 主动断开
  - 超时
routing_requires_tool:
  - generate WebSocket test case
  - expand WebSocket test case
  - current project WebSocket
  - real WebSocket test case
  - 生成WebSocket用例
  - 扩写WebSocket用例
  - 当前项目WebSocket
  - 真实WebSocket用例
---

# WebSocket Test Case Design

## Workflow

1. For conceptual WebSocket testing advice, answer directly without tools.
2. For current project WebSocket facts or reusable cases, use available read-only project/case tools first.
3. For WebSocket test case draft generation or expansion, use `ai_skill.run_draft` with `skill_id=websocket-test-case` and operation `generate` or `expand`.
4. Do not output HTTP-only fields such as method, body, query, or status-code assertions as WebSocket case fields.
5. Do not claim that a WebSocket debug session was opened, closed, or persisted unless a dedicated backend tool succeeds.

## Draft Quality

- Cover handshake URL, headers, authentication variables, optional subprotocols, send messages, receive expectations, timeout, ping/pong, and close behavior.
- Message assertions should validate type, code, correlation id, payload schema, order, and terminal close event where applicable.
- Treat live credentials, one-time tokens, private websocket URLs, and production side effects as blockers.

## Final Reply

- State whether the response is a draft, review, debug plan, or unsupported live action.
- Keep protocol-specific advice separate from HTTP API testing advice.
