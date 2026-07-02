---
name: http-test-case-design
description: Use when the user asks to design, generate, expand, validate, repair, or explain TestAuto HTTP API test cases, assertions, extractors, variables, request bodies, headers, query parameters, retry policy, or schema validation.
triggers:
  - HTTP
  - http
  - API
  - api
  - 接口用例
  - HTTP用例
  - 测试用例
  - 断言
  - 提取器
  - header
  - query
  - body
  - validate_schema
routing_requires_tool:
  - generate HTTP test case
  - expand HTTP test case
  - validate HTTP test case
  - repair HTTP test case
  - 生成HTTP用例
  - 生成接口用例
  - 扩写HTTP用例
  - 扩写接口用例
  - 校验用例
  - 修复用例
  - validate_schema
---

# HTTP Test Case Design

## Workflow

1. For conceptual HTTP API testing advice, answer directly without tools.
2. For live project facts, use `project.read_context` or `testcase.query_project_cases` first.
3. For saved-case assertion follow-ups, first reuse same-conversation context or call `testcase.query_project_cases` for real ids and current case facts; generate conservative assertions from proven response samples, execution summaries, or safe baseline checks.
4. To persist assertions on saved HTTP cases, use `testcase.update_assertions` for one case or `testcase.batch_update_assertions` for many cases after user approval. These tools patch only `assertions`; do not ask for full case JSON just to save assertions.
5. Use `ai_skill.run_draft` with `skill_id=http-test-case` and `operation=generate` only when creating new unsaved HTTP case drafts from interface docs, curl, URL, request params, or business text. Its input requires `interface_text`.
6. Do not use `ai_skill.run_draft` with `skill_id=http-test-case` and `operation=generate` for saved-case assertion follow-ups, saved-case assertion saving, or batch assertion patching; it is not a replacement for `testcase.update_assertions`.
7. For draft structure, field, assertion, extractor, or schema issues, use `testcase.validate_schema` when a concrete draft is available.
8. Do not claim that a test case was saved, deleted, archived, copied, or executed unless an explicit platform tool for that action succeeds.

## Draft Quality

- Prefer environment variables and extracted variables over hardcoded tokens, ids, timestamps, or company names.
- Assertions should check status, business code, response shape, and key field semantics; use the platform `expected` field for assertion expectations.
- Extractors should use stable paths from proven response samples. If the response sample is unauthorized, empty, or unavailable, mark the extractor path as a hypothesis.
- Separate authentication blockers from fixable draft issues. Tokens, passwords, secrets, and approvals need user or environment input.

## Final Reply

- Say whether the result is advice, a draft, a validation result, or a repair suggestion.
- Summarize changed fields, remaining blockers, and the next safe action.
