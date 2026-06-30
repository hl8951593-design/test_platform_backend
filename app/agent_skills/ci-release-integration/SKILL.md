---
name: ci-release-integration
description: Use when the user asks to integrate TestAuto runs with CI/CD pipelines, webhooks, Jenkins, GitLab, GitHub Actions, release gates, promotion checks, scheduled regression, or deployment readiness.
triggers:
  - CI
  - CD
  - pipeline
  - webhook
  - Jenkins
  - GitLab
  - GitHub Actions
  - 流水线
  - 持续集成
  - 发布门禁
  - 发布准入
  - 回归门禁
  - 定时回归
routing_requires_tool:
  - real release gate
  - current pipeline
  - recent plan run
  - plan report
  - webhook config
  - 真实发布门禁
  - 当前流水线
  - 最近计划执行
  - 计划报告
  - webhook配置
---

# CI Release Integration

## Workflow

1. Clarify whether the integration is for pull request checks, nightly regression, release promotion, deployment smoke tests, or post-release monitoring.
2. Use existing test plans, report summaries, environments, and execution history before recommending a gate threshold.
3. Define trigger source, target environment, test scope, timeout, retry policy, pass threshold, failure notification, and artifact/report link behavior.
4. For release gates, distinguish hard blockers from advisory warnings. Security, auth, data loss, and critical path failures should block by default.
5. If no platform webhook or pipeline write tool exists, provide the integration contract and explicitly say no CI configuration was changed.

## Final Reply

- State the recommended gate, required evidence, and what the CI system should consume.
- Do not claim a pipeline, webhook, or release gate was created unless a tool result confirms it.
- Include concise next checks for flaky or slow suites.
