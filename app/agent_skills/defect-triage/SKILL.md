---
name: defect-triage
description: Use when the user asks to analyze, draft, classify, reproduce, prioritize, update, close, reopen, or explain TestAuto defects, bug reports, severity, priority, screenshots, media attachments, or defect lifecycle.
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

1. For defect analysis and drafting, use available project, report, or execution evidence before making conclusions.
2. If the user asks to create, update, close, reopen, delete, or attach media to a defect, only claim completion when a dedicated backend tool exists and succeeds.
3. When no defect write tool is available, produce a ready-to-copy defect draft and say that it has not been saved.
4. Do not expose private tokens, passwords, cookies, or raw secrets in defect text; ask the user to redact or store them as environment variables.

## Defect Draft Fields

- Title, module, environment, severity, priority, preconditions, steps to reproduce, actual result, expected result, evidence, suspected cause, impact, workaround, owner suggestion, and regression scope.
- Link failures to report/run/tool evidence when provided.
- Distinguish product defect, test script defect, environment issue, data issue, and permission/authentication issue.

## Final Reply

- State whether this is a draft, triage conclusion, or unsupported persistence action.
- Keep the next action concrete: save manually, provide missing evidence, rerun, or adjust test data/environment.
