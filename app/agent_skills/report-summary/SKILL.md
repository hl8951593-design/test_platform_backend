---
name: report-summary
description: Use when the user asks to read, summarize, compare, diagnose, or explain TestAuto reports, execution results, pass rate, failure causes, flaky tests, risk coverage, or defect suggestions.
triggers:
  - 报告
  - report
  - 执行结果
  - 失败分析
  - 通过率
  - 缺陷
routing_requires_tool:
  - 当前项目
  - 报告摘要
  - 最近报告
  - 真实报告
  - 执行结果
  - 失败分析
  - 通过率
---

# Report Summary

## Workflow

1. Use `report.read_summary` when the user asks for real project report facts, execution results, pass rate, failure causes, flaky tests, or defect suggestions.
2. If the report tool returns an empty or deferred summary, state that the report aggregation adapter is not yet backed by detailed report data.
3. Do not invent pass rates, failure counts, defect links, screenshots, logs, or trend conclusions without tool evidence.

## Output

- Separate confirmed facts from inferred risk or suggested next actions.
- Prefer concise sections: current evidence, likely risk, next checks.
- If a defect should be created, describe the proposed defect fields, but do not claim creation unless a defect creation tool exists and succeeds.
