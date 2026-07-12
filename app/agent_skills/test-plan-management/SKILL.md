---
name: test-plan-management
description: Use when the user asks to design, explain, review, schedule, execute, diagnose, or report on TestAuto test plans, plan targets, plan runs, regression suites, smoke suites, coverage, pass rate, or release readiness.
tools:
  - project.read_context
  - scenario.query_project_scenarios
  - plan.query_project_plans
  - plan.create_saved
  - plan.update_saved
  - plan.set_enabled
  - plan.execute_saved
  - plan.query_runs
  - plan.read_run
  - report.read_summary
owns:
  - test_plan
consumes:
  - report
  - defect
  - test_case
  - scenario
  - execution
produces:
  - test_plan
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
2. For current plans, call `plan.query_project_plans`; for run history call `plan.query_runs`, then `plan.read_run` for target-level results.
3. Before `plan.create_saved`, call `project.read_context` and `scenario.query_project_scenarios`, then use only their current environment/scenario ids. Creating a plan requires approval.
4. Before `plan.update_saved` or `plan.set_enabled`, refresh `plan.query_project_plans` and copy its `object_ref`, snapshot id, and current version. Both actions require approval.
5. Before `plan.execute_saved`, refresh the plan and project environment snapshots. Execution is asynchronous; after acceptance use `plan.query_runs` rather than submitting a duplicate.
6. For report-level pass rate and failure evidence, use `report.read_summary` where available.
7. Do not claim that a plan, target, schedule, or run was created, updated, enabled, disabled, or executed unless the matching tool succeeds.

## Planning Rules

- Separate smoke, regression, release gate, exploratory, and risk-based suites.
- Tie each target to business risk, protocol, environment, owner, expected runtime, and failure triage path.
- Treat unstable tests, missing authentication, missing seed data, and environment drift as release-readiness risks.
- Use report evidence to distinguish product failure, test data failure, environment failure, and test script failure.

## Final Reply

- Provide coverage gaps, recommended suite structure, and next verification steps.
- Make unsupported persistence or execution boundaries explicit.
