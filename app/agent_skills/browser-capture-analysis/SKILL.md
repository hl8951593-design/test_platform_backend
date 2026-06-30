---
name: browser-capture-analysis
description: Use when the user asks to analyze, import, clean, deduplicate, convert, or explain Chrome browser-captured HTTP/WebSocket traffic, capture batches, HAR-like records, API drafts, websocket drafts, or capture-to-test-case workflows.
triggers:
  - 浏览器采集
  - Chrome插件
  - chrome插件
  - 抓包
  - HAR
  - capture
  - 采集批次
  - 接口采集
  - 流量
  - 去重
  - 转用例
---

# Browser Capture Analysis

## Workflow

1. Use this skill for browser-captured traffic analysis, cleanup, deduplication, and conversion planning.
2. If the user asks for real project capture batches, imported drafts, or saved test cases, use available project read tools first and state when no capture-specific tool is available.
3. For converting captured HTTP traffic into a draft HTTP test case, use `ai_skill.run_draft` with `skill_id=http-test-case` when enough request context is present.
4. For converting captured WebSocket traffic into a draft WebSocket test case, use `ai_skill.run_draft` with `skill_id=websocket-test-case` when enough handshake and message context is present.
5. Do not claim capture import, deduplication, draft save, or test case creation unless a backend tool for that action succeeds.

## Cleanup Rules

- Remove or redact cookies, bearer tokens, passwords, session ids, one-time nonces, and tracking headers.
- Normalize dynamic query parameters, timestamps, cache busters, and correlation ids into variables when they affect repeatability.
- Group requests by business action, not by every static asset or analytics request.
- Preserve enough request/response evidence to design assertions and extractors.

## Final Reply

- Separate captured evidence, cleaned assumptions, proposed test drafts, and unsupported persistence actions.
