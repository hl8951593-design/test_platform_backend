---
name: scenario-composition
description: Use when the user asks to create, generate, compose, update, validate, dry-run, save, or explain a TestAuto scenario, scenario draft, visual flow, multi-step API workflow, dataset-driven scenario, precondition/postcondition chain, or current project scenario composition.
triggers:
  - 场景
  - scenario
  - 编排
  - 组合
  - 草稿
  - 数据集
  - companyid
  - 保存
  - 正式场景
routing_requires_tool:
  - 当前项目
  - 已有用例
  - 真实用例
  - 生成场景
  - 创建场景
  - 组合场景
  - 场景草稿
  - 执行场景
  - dry-run
  - 保存
  - 正式场景
routing_required_tool_after_success:
  - after=testcase.query_project_cases; require=scenario.compose_draft; min_total_fields=http_total,websocket_total; intent_markers=生成场景,创建场景,组合场景,场景草稿,执行场景,dry-run,数据集,参数化
guard_scenario_save_intent:
  - 保存
  - 正式场景
  - 持久化
  - 落库
  - 发布
guard_scenario_save_subject:
  - 场景
  - scenario
  - 草稿
  - 刚才
  - 上面
  - 直接
guard_scenario_save_classifier_prompt: save-intent-classifier.md
guard_scenario_save_unsupported_message: unsupported-save-message.md
guard_unsupported_capability:
  - name=scenario_save; intent=guard_scenario_save_intent; subject=guard_scenario_save_subject; unavailable_tools=scenario.save,scenario.create,scenario.persist; classifier_prompt=guard_scenario_save_classifier_prompt; requires_field=requires_scenario_persistence; completion_source=unsupported_scenario_save_guard; message=guard_scenario_save_unsupported_message
---

# Scenario Composition

## Workflow

1. For scenario creation, generation, composition, or update, query the current project cases first with `testcase.query_project_cases`.
2. Use real case ids returned by the query when calling `scenario.compose_draft`.
3. Do not invent case ids, environment ids, request fields, response samples, or execution results.
4. If the user asks to save, persist, publish, or create a formal scenario, only do so when an explicit save/persist tool is available.
5. If only draft and dry-run tools are available, explain that `scenario.compose_draft` creates a draft and does not save a formal scenario.

## Draft Quality

- Prefer dynamic variables, extractors, assertions, and clear dependency links over hardcoded downstream values.
- For dataset-driven requests, include `include_datasets=true` when updating the draft and explain whether the resulting draft truly covers multiple data rows.
- Treat authentication tokens, account passwords, secrets, permission approval, and private user inputs as blockers instead of fabricating them.
- Treat schema, missing fields, validation, binding, extractor path, assertion, and dataset structure issues as candidates for automatic repair with safe draft or validate tools.

## Final Reply

- Say whether the result is a draft, dry-run result, or a formal saved object.
- Do not claim that a scenario was saved unless a save/persist tool succeeded.
- Summarize completed work, automatic repairs, remaining blockers, and the next useful action.
