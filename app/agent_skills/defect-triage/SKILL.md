---
name: defect-triage
description: Use when the user asks to analyze, draft, classify, reproduce, prioritize, update, close, reopen, or explain TestAuto defects, bug reports, severity, priority, screenshots, media attachments, or defect lifecycle.
tools:
  - defect.query_project_defects
  - defect.create_saved
  - defect.update_saved
  - defect.transition_status
  - execution.query_records
  - execution.read_detail
  - report.read_summary
owns:
  - defect
consumes:
  - test_case
  - execution
  - report
  - media
produces:
  - defect
triggers:
  - 缺陷
  - bug
  - Bug
  - 故障
  - 严重程度
  - 优先级
  - 复现步骤
  - 截图
  - 附件
  - 媒体
  - 关闭缺陷
  - 重新激活
---

# Defect Triage

## Workflow

1. For current defects, call `defect.query_project_defects`. For failure evidence use `execution.query_records`, `execution.read_detail`, or `report.read_summary` before making conclusions.
   A `test_case_query_snapshot` with `failed_cases` proves only which latest case executions failed; when `failure_detail_available=false`, it does not prove the failure cause.
2. Use `defect.create_saved` only after the title, type, urgency, sanitized HTML content, and evidence are ready. Creation requires approval.
3. Before `defect.update_saved` or `defect.transition_status`, refresh `defect.query_project_defects` and use its current object reference. Both actions require approval.
4. Follow the backend lifecycle transition rules; do not skip states or claim a close/reopen before tool success.
5. Delete and binary upload are not available in this tool set. Do not claim those actions succeeded.
6. Do not expose private tokens, passwords, cookies, or raw secrets in defect text; ask the user to redact or store them as environment variables.

## Defect Draft Fields

- Title, module, environment, severity, priority, preconditions, steps to reproduce, actual result, expected result, evidence, suspected cause, impact, workaround, owner suggestion, and regression scope.
- Link failures to report/run/tool evidence when provided.
- Distinguish product defect, test script defect, environment issue, data issue, and permission/authentication issue.
- Treat negative test cases separately: an expected 4xx/business rejection is not a product defect unless the saved assertion or execution evidence proves the observed behavior violated the expected result.

## Final Reply

- State whether this is a draft, triage conclusion, or unsupported persistence action.
- Keep the next action concrete: save manually, provide missing evidence, rerun, or adjust test data/environment.
