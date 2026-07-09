---
name: http-test-case-design
description: Use when the user asks to design, generate, expand, validate, repair, or explain TestAuto HTTP API test cases, assertions, extractors, variables, request bodies, headers, query parameters, retry policy, or schema validation.
capabilities:
  - http_test_case.design
  - http_test_case.create
  - http_test_case.update
  - http_test_case.execute
  - http_test_case.assertions
required_context:
  - project_context
  - test_case_inventory
tools:
  - project.read_context
  - testcase.query_project_cases
  - ai_skill.run_draft
  - testcase.validate_schema
  - testcase.create_saved
  - testcase.update_saved
  - testcase.update_assertions
  - testcase.batch_update_assertions
  - testcase.execute_saved
  - testcase.batch_execute
artifacts:
  - test_case_query_snapshot
  - testcase_draft
  - testcase_assertion_draft
examples:
  - create equivalence class cases from existing cases
  - expand boundary value HTTP test cases
  - repair assertions for saved HTTP cases
triggers:
  - HTTP
  - http
  - API
  - api
  - 接口用例
  - HTTP用例
  - 测试用例
  - 现有用例
  - 等价类的用例
  - 等价类用例
  - 边界值用例
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
  - 创建用例
  - 生成用例
  - 根据现有用例创建
  - 基于现有用例生成
  - 创建等价类用例
  - 生成等价类用例
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
3. For saved-case assertion follow-ups, first reuse same-conversation context or call `testcase.query_project_cases` with `detail_level=summary` to get only the real id/name inventory and current case facts.
4. When the project contains many cases or the first query is large, split the work by explicit ids: query one selected `test_case_id` with `detail_level=assertions`, deduplicate or repair that case's assertions, save that case with `testcase.update_assertions`, then continue with the next case id. Do not re-query all cases with full detail after truncation and do not ask the user to confirm details that can be fetched per case.
5. To persist assertions on saved HTTP cases, prefer `testcase.update_assertions` per case for large assertion-repair batches; use `testcase.batch_update_assertions` only after every item was prepared from explicit per-case details. These tools patch only `assertions`; do not ask for full case JSON just to save assertions.
6. Use `ai_skill.run_draft` with `skill_id=http-test-case` and `operation=generate` only when creating new unsaved HTTP case drafts from interface docs, curl, URL, request params, or business text. Its input requires `interface_text`.
7. Do not use `ai_skill.run_draft` with `skill_id=http-test-case` and `operation=generate` for saved-case assertion follow-ups, saved-case assertion saving, or batch assertion patching; it is not a replacement for `testcase.update_assertions`.
8. For draft structure, field, assertion, extractor, or schema issues, use `testcase.validate_schema` when a concrete draft is available.
9. To persist full HTTP cases, use `testcase.create_saved` or `testcase.update_saved` and wait for approval. To run saved HTTP cases, use `testcase.execute_saved` or `testcase.batch_execute` only with ids from fresh project case facts.
10. Do not claim that a test case was saved, deleted, archived, copied, or executed unless an explicit platform tool for that action succeeds.

## Draft Quality

- Prefer environment variables and extracted variables over hardcoded tokens, ids, timestamps, or company names.
- Assertions should check status, business code, response shape, and key field semantics; use the platform `expected` field for assertion expectations.
- Extractors should use stable paths from proven response samples. If the response sample is unauthorized, empty, or unavailable, mark the extractor path as a hypothesis.
- Separate authentication blockers from fixable draft issues. Tokens, passwords, secrets, and approvals need user or environment input.

## Final Reply

- Say whether the result is advice, a draft, a validation result, or a repair suggestion.
- Summarize changed fields, remaining blockers, and the next safe action.
