---
name: agent-runtime-operations
description: Use when the user asks to diagnose, operate, evaluate, or explain Harness Loop Agent runtime behavior, runs, SSE events, model streaming, readiness dashboard, runbook, worker queue, stale run, memory usage, model health, launch audit, backend completion audit, or behavior evaluation.
triggers:
  - agent runtime
  - Harness Loop
  - readiness
  - runbook
  - worker queue
  - stale run
  - model health
  - launch audit
  - backend completion
  - behavior evaluation
  - Agent卡住
  - 正在思考
  - 事件流
  - model.delta
  - run.completed
routing_requires_tool:
  - current agent run
  - real agent event
  - readiness dashboard
  - model health
  - runbook
  - 当前Agent运行
  - 真实Agent事件
  - 就绪面板
  - 模型健康
---

# Agent Runtime Operations

## Workflow

1. Use this skill for the Agent system itself: run lifecycle, SSE delivery, model calls, tool loop, readiness, runbook, worker queue, stale active runs, and behavior evaluation.
2. For real run facts, prefer existing Agent run summary, event snapshot, dashboard, model-health, runbook, and behavior-eval evidence when available.
3. Do not confuse target API test failures with Agent runtime failures. Separate model/provider latency, silent tool-planning rounds, EventStore replay, frontend cursor issues, and backend worker loss.
4. Do not claim a run was cancelled, resumed, reconciled, archived, or fixed unless the corresponding backend action succeeds.

## Diagnosis Checklist

- Check run status, terminal event, latest event sequence, `model.started`, `model.delta`, `model.completed`, `tool.*`, `run.completed`, and heartbeat-only streams.
- Use `model_call_id` and `loop_step` to distinguish assistant response, tool planning, repair, required-tool repair, final summary, and guard classification.
- For "stuck thinking", compare SSE stream, snapshot endpoint, summary endpoint, stale-run guard, and frontend cursor reuse.
- For behavior evaluation, inspect both raw events and assistant-visible final output.

## Final Reply

- Provide confirmed runtime facts, likely failure layer, missing evidence, and next safe diagnostic command or API call.
