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
3. For HTTP test case draft generation or expansion, use `ai_skill.run_draft` with `skill_id=http-test-case` and operation `generate` or `expand`.
4. For draft structure, field, assertion, extractor, or schema issues, use `testcase.validate_schema` when a concrete draft is available.
5. Do not claim that a test case was saved, deleted, archived, copied, or executed unless an explicit platform tool for that action succeeds.

## Draft Quality

- Prefer environment variables and extracted variables over hardcoded tokens, ids, timestamps, or company names.
- Assertions should check status, business code, response shape, and key field semantics; use the platform `expected` field for assertion expectations.
- Extractors should use stable paths from proven response samples. If the response sample is unauthorized, empty, or unavailable, mark the extractor path as a hypothesis.
- Separate authentication blockers from fixable draft issues. Tokens, passwords, secrets, and approvals need user or environment input.

## Final Reply

- Say whether the result is advice, a draft, a validation result, or a repair suggestion.
- Summarize changed fields, remaining blockers, and the next safe action.
