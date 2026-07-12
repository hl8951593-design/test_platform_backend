---
name: execution-diagnosis
description: Use when the user asks to diagnose TestAuto execution records, failed runs, flaky behavior, timeout, retry, environment mismatch, assertion failure, extractor failure, scenario run, visual flow execution, or SSE progress issues.
tools:
  - execution.query_records
  - execution.read_detail
  - execution.diagnose
  - report.read_summary
  - project.read_context
owns:
  - execution
consumes:
  - test_case
  - scenario
  - visual_flow
  - report
produces:
  - execution
  - diagnosis
triggers:
  - execution diagnosis
  - diagnose execution
  - failed execution
  - execution detail
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

1. For current execution history, call `execution.query_records` first. Use its explicit `execution_type`, `execution_id`, and `object_ref`; never guess an id.
2. Read `view=summary` with `execution.read_detail` for the selected execution.
3. If the terminal status is failed, timeout, or error, read `view=failures` before replying.
4. Read `view=step` only when `diagnostic_complete=false` or the user requests exact step evidence.
5. Read `view=artifact` only for an explicit evidence reference; never request full raw output by default.
6. Call `execution.diagnose` only after deterministic evidence is available. It creates analysis only and does not modify cases or executions.
7. Use `report.read_summary` for report-level trends and `project.read_context` for environment metadata.
8. Distinguish backend run/SSE delivery problems from target API failures, assertion failures, extractor failures, and environment/authentication failures.

## Diagnosis Checklist

- Confirm terminal status, latest event sequence, and whether the UI received non-heartbeat events.
- Compare environment base URL, variables, authentication, request snapshot, response snapshot, assertion output, extractor output, retry attempts, and elapsed time.
- For scenario or flow failures, locate the first failed node, its input bindings, upstream variable source, and whether dataset overrides changed the request.
- For flaky failures, check retry policy, timeout, non-idempotent requests, dynamic data, rate limits, and external service stability.

## Final Reply

- Separate confirmed facts, likely cause, missing evidence, and next checks.
- Do not invent logs, screenshots, run ids, report ids, or execution records.
