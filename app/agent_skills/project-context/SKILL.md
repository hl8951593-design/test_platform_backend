---
name: project-context
description: Use when the user asks to read or query current TestAuto project context, existing test cases, environments, resources, or other live platform facts.
triggers:
  - 当前项目
  - 项目上下文
  - 读取项目
  - 查询项目
  - 已有用例
  - 真实用例
  - 项目用例
  - 当前环境
routing_requires_tool:
  - 当前项目
  - 项目上下文
  - 读取项目
  - 查询项目
  - 已有用例
  - 真实用例
  - 项目用例
  - 当前环境
---

# Project Context

## Workflow

1. Use `project.read_context` when the user asks for current project context, resources, configuration, or live platform facts.
2. Use `testcase.query_project_cases` when the user asks for real existing test cases or needs project cases before another draft/composition step.
3. Do not invent project resources, case ids, environment ids, counts, names, owners, recent activity, or execution facts without tool evidence.
4. If no available tool can read the requested project fact, state the missing backend capability and suggest the closest available read-only check.

## Output

- Separate confirmed tool evidence from recommendations or assumptions.
- Keep the response concise and reference only facts returned by tools.
- If the request is only conceptual testing advice and does not need live project facts, answer without using project tools.
