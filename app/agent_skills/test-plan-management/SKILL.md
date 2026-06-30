---
name: test-plan-management
description: Use when the user asks to design, explain, review, schedule, execute, diagnose, or report on TestAuto test plans, plan targets, plan runs, regression suites, smoke suites, coverage, pass rate, or release readiness.
triggers:
  - test plan
  - test suite
  - smoke
  - regression
  - release readiness
  - coverage
  - 测试计划
  - 测试套件
  - 冒烟
  - 回归
  - 覆盖率
  - 发布准入
routing_requires_tool:
  - current project test plan
  - recent plan run
  - plan report
  - 当前项目测试计划
  - 最近计划执行
  - 计划报告
---

# Test Plan Management

## Workflow

1. For test-plan strategy, coverage design, suite grouping, and release-readiness advice, answer directly.
2. For real plan run results, pass rate, and failure evidence, use `report.read_summary` where available.
3. Use `project.read_context` when the plan needs current environments or project metadata.
4. Do not claim that a plan, target, schedule, or run was created, updated, executed, cancelled, or archived unless a dedicated backend tool succeeds.

## Planning Rules

- Separate smoke, regression, release gate, exploratory, and risk-based suites.
- Tie each target to business risk, protocol, environment, owner, expected runtime, and failure triage path.
- Treat unstable tests, missing authentication, missing seed data, and environment drift as release-readiness risks.
- Use report evidence to distinguish product failure, test data failure, environment failure, and test script failure.

## Final Reply

- Provide coverage gaps, recommended suite structure, and next verification steps.
- Make unsupported persistence or execution boundaries explicit.
