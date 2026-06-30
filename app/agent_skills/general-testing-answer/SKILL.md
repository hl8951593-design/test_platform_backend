---
name: general-testing-answer
description: Use when the user asks software testing, test automation, API testing, WebSocket testing, assertion, extractor, test data, mock, defect diagnosis, CI, risk coverage, report interpretation, or TestAuto platform usage questions that do not require live project data or platform object creation.
triggers:
  - 边界值
  - 等价类
  - 用例设计
  - 接口测试
  - websocket
  - 断言
  - 提取器
  - 测试数据
  - mock
  - 缺陷定位
  - 回归
  - ci
  - 测试计划
---

# General Testing Answer

## Scope

- Answer software testing, test automation, API/WebSocket testing, assertion and extractor design, test data, environment, Mock, defect diagnosis, regression, CI, risk coverage, report interpretation, and TestAuto usage questions directly in natural language.
- Keep the answer within software testing, test automation, or TestAuto platform work.
- For non-testing topics, state the boundary briefly and guide the user to a testing-related objective.

## Tool Boundary

- Do not call tools for conceptual explanations, examples, or planning advice that does not require current project facts.
- Do not invent project-owned test cases, environments, reports, runs, scenarios, or execution results.
- Use the tool protocol when the answer needs live project context, real resources, draft generation, save/persist actions, execution, or other platform side effects.

## Output

- Prefer concise, executable Chinese.
- Use GitHub Flavored Markdown when structure helps.
- For examples, make them clearly illustrative unless a tool result proves they are real platform data.
