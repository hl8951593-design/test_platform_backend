---
name: execution-diagnosis
description: Use when the user asks to diagnose TestAuto execution records, failed runs, flaky behavior, timeout, retry, environment mismatch, assertion failure, extractor failure, scenario run, visual flow execution, or SSE progress issues.
triggers:
  - 执行记录
  - 执行失败
  - 运行失败
  - flaky
  - 超时
  - 重试
  - 失败原因
  - 断言失败
  - 提取失败
  - SSE
  - 卡住
  - 正在思考
routing_requires_tool:
  - current project execution
  - recent execution
  - real execution result
  - failure cause
  - pass rate
  - recent report
  - 当前项目执行
  - 最近执行
  - 真实执行结果
  - 失败原因
  - 通过率
  - 最近报告
---

# Execution Diagnosis

## Workflow

1. For real project execution status, use `report.read_summary` when report or failure context is available.
2. Use `project.read_context` when diagnosis depends on environments, default base URL, or project metadata.
3. If no tool can read the requested execution detail, explain the missing backend read capability and provide a manual triage checklist.
4. Distinguish backend run/SSE delivery problems from target API failures, assertion failures, extractor failures, and environment/authentication failures.

## Diagnosis Checklist

- Confirm terminal status, latest event sequence, and whether the UI received non-heartbeat events.
- Compare environment base URL, variables, authentication, request snapshot, response snapshot, assertion output, extractor output, retry attempts, and elapsed time.
- For scenario or flow failures, locate the first failed node, its input bindings, upstream variable source, and whether dataset overrides changed the request.
- For flaky failures, check retry policy, timeout, non-idempotent requests, dynamic data, rate limits, and external service stability.

## Final Reply

- Separate confirmed facts, likely cause, missing evidence, and next checks.
- Do not invent logs, screenshots, run ids, report ids, or execution records.
