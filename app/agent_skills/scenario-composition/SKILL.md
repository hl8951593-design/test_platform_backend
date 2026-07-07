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
  - 场景组合
  - 测试场景组合
  - 场景草稿
  - 执行场景
  - dry-run
  - 保存
  - 正式场景
routing_required_tool_after_success:
  - after=testcase.query_project_cases; require=scenario.compose_draft; min_total_fields=http_total,websocket_total; intent_markers=生成场景,创建场景,组合场景,场景组合,测试场景组合,场景草稿,执行场景,dry-run,数据集,参数化
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
  - name=scenario_save; intent=guard_scenario_save_intent; subject=guard_scenario_save_subject; unavailable_tools=scenario.create_saved,scenario.update_saved; classifier_prompt=guard_scenario_save_classifier_prompt; requires_field=requires_scenario_persistence; completion_source=unsupported_scenario_save_guard; message=guard_scenario_save_unsupported_message
---

# Scenario Composition

## Workflow

1. A scenario is an orchestration artifact, not a copied case list. It owns `nodes`, `before_actions`, `after_actions`, `_scenario_context.extractions`, `_scenario_context.bindings`, datasets, and downstream `{{variable}}` references.
2. For create/generate/compose/update, query current project cases first with `testcase.query_project_cases`; for large projects use summary, then selected `assertions` or `full` detail.
3. Call `scenario.compose_draft` only with real ids from the latest query. Do not invent case/scenario/environment ids, request fields, samples, or results.
4. For same-conversation save/update, reuse the latest complete `scenario.compose_draft.draft.scenario`; never reconstruct JSON from the visible summary.
5. Save formal scenarios with `scenario.create_saved` or `scenario.update_saved`. Saving requires approval; do not claim saved before the approved tool succeeds.
6. For existing saved scenarios or dry-run, first use `scenario.query_project_scenarios`; execute only explicit current results with `scenario.execute_dry_run`.

## Draft Quality

- Build a real flow. Classify candidate roles before compose: precondition, data provider, main step, validation query, mutation, cleanup, or postcondition.
- Prefer variables, extractors, assertions, and bindings over hardcoded downstream values.
- Upstream response values go in `test_case.config.extractors` and `_scenario_context.extractions`; downstream consumers go in `_scenario_context.bindings` plus `headers`, `query_params`, `body`, `path`, or WebSocket `messages` using `{{variable}}`.
- Use `before_actions` for setup variables, random/fixed data, gates, waits, or script-derived values. Use `after_actions` for cleanup, waits, or post-step checks. Do not fake response extraction as `fixed_value`.
- Action kinds: `delay` for settle waits; `condition` for gates on `variables`/`steps`; `fixed_value`/`random` for setup data; `script` only for deterministic derived variables from declared inputs. Python/JavaScript scripts cannot read files, import modules, call network APIs, or touch secrets.
- Preserve or generate stable assertions: existing assertions, `status_code`, `code`, `success`, or WebSocket `message_count`. Avoid timestamps, tokens, signatures, random ids, and paging totals unless requested.
- Multi-node dependency/context/precondition/postcondition scenarios must not degrade into nodes containing only `reference_id` and empty `config`.
- For data-driven requests, set `include_datasets=true` and state whether multiple rows are truly covered.
- Treat secrets, passwords, private tokens, approval, and missing user inputs as blockers. Treat schema, binding, extractor path, assertion, and dataset issues as repairable with safe draft/validate tools.

## Final Reply

- Say whether the result is a draft, dry-run result, or a formal saved object.
- Do not claim that a scenario was saved unless `scenario.create_saved` or `scenario.update_saved` succeeded after approval.
- Prefer test case names in the user-visible summary; include ids only as secondary references when needed.
- Summarize completed work, automatic repairs, remaining blockers, and the next useful action.
