---
name: scenario-composition
description: Use when the user asks to create, generate, compose, update, validate, dry-run, save, or explain a TestAuto scenario, scenario draft, visual flow, multi-step API workflow, dataset-driven scenario, precondition/postcondition chain, or current project scenario composition.
capabilities:
  - scenario.compose
  - scenario.save
  - scenario.update
  - scenario.execute
  - scenario.repair
required_context:
  - project_context
  - test_case_inventory
  - scenario_inventory
tools:
  - project.read_context
  - testcase.query_project_cases
  - scenario.compose_draft
  - scenario.query_project_scenarios
  - scenario.create_saved
  - scenario.update_saved
  - scenario.execute_dry_run
owns:
  - scenario
consumes:
  - test_case
  - dataset
  - environment
  - report
  - execution
produces:
  - scenario
artifacts:
  - scenario_draft
  - saved_scenario
  - scenario_run_failure
  - test_case_query_snapshot
examples:
  - create enterprise automation flow
  - execute the flow I just created and summarize the result
  - save the scenario draft from this conversation
triggers:
  - 场景
  - scenario
  - 编排
  - 组合
  - 草稿
  - 数据集
  - 测试流程
  - 自动化测试流程
  - 企业
  - 关注
  - companyid
  - 保存
  - 正式场景
  - 执行测试
  - 运行测试
  - 试运行
  - 这个场景
  - 该场景
  - 场景执行
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
  - 执行测试
  - 运行测试
  - 场景下执行
  - 这个场景执行
  - 该场景执行
  - 场景执行
  - 试运行
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
2. Query cases first; for large projects use summary then selected detail. Retain the `test_case_query_snapshot` artifact id and hash.
3. Prefer `scenario.compose_draft(case_source={artifact_id,output_hash}, environment_reference=...)`. The backend resolves the full ledger result; never copy truncated cases or guess ids. Supply a natural-language `requirement`.
4. Describe desired bindings/hooks in `extra_requirements`; do not send scenario nodes as the input root. For save/update, reuse the latest complete draft with `scenario_validation.valid=true`, never a visible summary reconstruction.
5. Save formal scenarios with `scenario.create_saved` or `scenario.update_saved`. Saving requires approval; do not claim saved before the approved tool succeeds.
6. `scenario.compose_draft` is pure draft: it never executes candidates or self-validates. For dry-run, first query saved scenarios and explicitly use `scenario.execute_dry_run`.

## Draft Quality

- Build a real flow. Classify candidate roles before compose: precondition, data provider, main step, validation query, mutation, cleanup, or postcondition.
- Preserve saved request config, assertions, and extractors. Use bindings only when the saved source has the extractor and the saved target already contains the matching `{{variable}}`; otherwise keep nodes independent.
- Use `before_actions` for setup variables, random/fixed data, gates, waits, or script-derived values. Use `after_actions` for cleanup, waits, or post-step checks. Do not fake response extraction as `fixed_value`.
- Action kinds: `delay` for settle waits; `condition` for gates on `variables`/`steps`; `fixed_value`/`random` for setup data; `script` only for deterministic derived variables from declared inputs. Python/JavaScript scripts cannot read files, import modules, call network APIs, or touch secrets.
- Preserve or generate stable assertions: existing assertions, `status_code`, `code`, `success`, or WebSocket `message_count`. Avoid timestamps, tokens, signatures, random ids, and paging totals unless requested.
- Evidence grounding restores each referenced saved case's real request config; independent nodes are valid when no dependency is evidenced.
- Every primary node must reference a `case_source` saved case; method/path overrides must match. Extractors/bindings need evidence. Never invent edges.
- Require `scenario_validation.valid=true` before save/update. Repair reported quality/graph/reference/template issues; `scenario_draft_invalid` is diagnostic only.
- For data-driven requests, set `include_datasets=true` and state whether multiple rows are truly covered.
- Treat secrets, passwords, private tokens, approval, and missing user inputs as blockers. Treat schema, binding, extractor path, assertion, and dataset issues as repairable with safe draft/validate tools.

## Final Reply

- Say whether the result is a draft, dry-run result, or a formal saved object.
- Do not claim that a scenario was saved unless `scenario.create_saved` or `scenario.update_saved` succeeded after approval.
- Prefer test case names in the user-visible summary; include ids only as secondary references when needed.
- Summarize completed work, automatic repairs, remaining blockers, and the next useful action.
