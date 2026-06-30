---
name: batch-execution-scheduling
description: Use when the user asks to plan, diagnose, or optimize batch execution, scheduled runs, parallelism, worker queue behavior, retries, timeout policy, cancellation, or execution ordering for TestAuto test cases, scenarios, flows, or plans.
triggers:
  - 批量执行
  - 调度
  - 队列
  - 并发
  - worker
  - retry
  - 重试
  - timeout
  - 超时
  - 取消执行
  - 定时执行
  - 执行顺序
routing_requires_tool:
  - real batch execution
  - current execution queue
  - recent scheduled run
  - worker status
  - execution order
  - 真实批量执行
  - 当前执行队列
  - 最近调度执行
  - worker状态
  - 执行顺序
---

# Batch Execution Scheduling

## Workflow

1. Identify the execution scope: single case batch, scenario, visual flow, test plan, data-driven records, or CI-triggered run.
2. For real run status, queue state, timing, retry count, or failure distribution, use available execution/report/context tools before stating facts.
3. Separate planning concerns: ordering, dependency, parallelism, timeout, retry, cancellation, idempotency, environment isolation, and report aggregation.
4. Avoid recommending retries for non-idempotent requests unless the request is explicitly safe or has a compensation strategy.
5. If the platform lacks a scheduling or cancellation write tool, describe the contract and do not claim the schedule or cancellation was applied.

## Final Reply

- State which parts are confirmed by platform evidence and which are an execution plan.
- Call out high-risk settings such as high concurrency, long timeout, repeated non-idempotent writes, and shared auth variables.
- Do not invent worker ids, queue depth, schedule ids, or run results.
