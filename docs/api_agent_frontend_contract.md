# Agent 前端接口契约

状态：前端接入契约方案
最后核验：2026-07-12

本文档用于指导另一个 React 19 + Vite + TypeScript 前端项目接入 Harness Loop Agent 后端。接口基础路径沿用现有前端技术文档：

```text
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

所有受保护接口必须通过现有 `requestWithAuth` 或同等封装自动携带 `Authorization`。页面组件不得直接拼接鉴权头。

## 1. 通用响应

普通 JSON 接口统一返回：

```ts
type ApiEnvelope<T> = {
  code: number;
  message: string;
  data: T;
};
```

SSE 接口 `GET /agents/runs/{run_id}/events` 返回 `text/event-stream`，不使用 `ApiEnvelope`。

## 2. 前端建议封装

| 文件 | 职责 |
| --- | --- |
| `src/api/agents.ts` | `/agents/*` 接口函数 |
| `src/api/agentStream.ts` | `fetch + ReadableStream` SSE parser |
| `src/types/agents.ts` | 后端契约类型 |
| `src/pages/AgentPage.tsx` | 页面容器 |
| `src/components/agent/*` | Agent 工作台组件 |
| `src/pages/AgentPage.test.tsx` | 页面集成测试 |
| `src/api/agents.test.ts` | 接口封装和 SSE parser 测试 |

## 3. 核心接口清单

### 3.1 Capabilities

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/capabilities` | 初始化状态枚举、工具目录、能力开关 |
| `GET` | `/agents/skills` | 查询 Agent Skill 元数据目录 |

`GET /agents/capabilities` 返回 `AgentCapabilitiesRead`：

```text
run_statuses,tool_call_statuses,effect_submission_states,backend_effect_capabilities,approval_statuses,migration_block_statuses,tools
```

`tools[]` 只包含 `ToolSpec.to_json()` 的公开 manifest 字段：

```text
item_id,name,version,summary,side_effect_class,replay_policy,required_permissions,input_schema,output_schema,backend_contract,schema_hash,manifest_hash
```

每个公开 tool manifest row 都携带稳定 `item_id=agent-tool-spec://{name}/{version}`。该字段由公开 tool name/version 派生，不新增数据库列，不替代 `name`、`version`、`schema_hash` 或 `manifest_hash`；`GET /agents/capabilities`、`AgentRuntimeSnapshot.tools_json` 与 `AgentRuntimeSnapshot.manifests_json.tools` 使用同一 `ToolSpec.to_json()` 形态，前端可直接用该值作为工具目录、冻结运行时解释和导出包里的稳定 key，不要自行拼接。

后端私有字段 `backend_handler`、`required_context_requirements`、`missing_prerequisite_error_code`、`missing_prerequisite_next_action` 与 `tool_result_repair_guidance` 不进入 capabilities、模型初始工具清单或前端契约；这些字段只供后端 routing、上下文要求校验和工具结果修复策略使用。

当前 capabilities 返回 48 个 ToolSpec。相对原有 29 个工具，本次新增 19 个平台业务工具：`execution.query_records/read_detail/diagnose`；`plan.query_project_plans/create_saved/update_saved/set_enabled/execute_saved/query_runs/read_run`；`flow.query_project_flows/validate_graph/create_saved/update_saved/execute_saved`；`defect.query_project_defects/create_saved/update_saved/transition_status`。这是对 `tools[]` 的加法扩展，没有删除或重命名旧工具。前端不得写死工具数量；应按 `name`、`item_id`、`schema_hash` 和 `manifest_hash` 渲染当前 capabilities/runtime snapshot。

四类 query 工具会返回 `snapshot`、`object_reference_manifest` 和对象级 `object_ref`，供后续详情、更新、执行或状态流转工具引用。对测试计划、Flow 和缺陷的写入/执行动作，引用只代表当前 Agent 会话最新查询事实，不是长期业务主键；旧 snapshot、伪造 ref、跨项目 ID 或查询后已删除对象会在审批和业务 handler 前被 preflight 阻断。`flow.create_saved/update_saved` 还会按节点 `kind` 分别校验 `api_case` 与 `websocket_case` 引用来自同一个最新 `testcase.query_project_cases` 快照，不能把 HTTP ID 当成 WebSocket ID。执行详情/诊断是只读链路，由 Skill 要求先 `execution.query_records`，后端 `ExecutionRecordService` 再校验项目归属，不把只读查询错误提升成审批式引用门禁。`plan.execute_saved` 和 `flow.execute_saved` 成功表示后台 run/execution 已受理，前端应继续读取返回的 run/execution identity 和状态接口，不能把 ToolCall 成功等同于业务执行已经通过。

模型可见目录仍由 Skill Planner 与 Capability Resolver 按本轮意图裁剪：执行失败分析加载 `execution-diagnosis`；测试计划管理加载 `test-plan-management`；可视化 Flow 管理加载 `visual-flow-design`；缺陷查询和流转加载 `defect-triage`。全局 capabilities 能看到 48 个工具，不表示单轮模型上下文会收到全部工具，也不改变 ToolRuntime 的权限、审批、schema 和引用预检边界。

`project.read_context` 除返回项目基础信息、`environments[]` 和 `default_environment` 外，还返回 `environment_snapshot`、`environment_id_manifest` 和通用 `object_reference_manifest`。其中 `object_reference_manifest.object_family=environment`、`query_tool=project.read_context`，`environment_ids` / `environment_execute_ids` 是后续执行工具可引用的显式环境 ID。带 `environment_id` 的受控副作用工具会按同一 `ObjectReferenceGuardRule` 校验该 ID 是否来自同一 Agent 会话内最新成功 `project.read_context`，并再次确认 `project_environments.project_id` 匹配且 `is_deleted=false`。模型初始工具 schema 中所有顶层 `environment_id` 字段，以及 `testcase.create_saved`、`testcase.update_saved`、`websocket_testcase.create_saved`、`websocket_testcase.update_saved` 的嵌套 `case.environment_id` / `case.environment_ids` 字段、`scenario.create_saved` / `scenario.update_saved` 的嵌套 `scenario.environment_id` 字段，也必须声明 `Use only ids from project.read_context.object_reference_manifest.environment_ids`，让模型规划阶段先引用同一事实源；执行器校验仍是最终强边界。未查询或旧查询环境 ID 会以 `agent_environment_ids_not_from_query_result` 阻断，输出 `invalid_environment_ids` / `valid_environment_ids`；最新快照中的环境若执行前被删除，会以 `agent_environment_id_stale_or_deleted` 阻断，输出 `stale_environment_ids` / `valid_environment_ids`，`recovery_decision=refresh_project_context_before_retry`。

受控副作用工具的输入 schema 还提供兼容性的 snapshot 显式引用字段：测试用例工具使用 `case_snapshot_id`，场景 dry-run 使用 `scenario_snapshot_id`，带环境引用的工具使用 `environment_snapshot_id`。这些字段应取自对应查询结果的 `object_reference_manifest.snapshot_id`。字段仍为可选，旧客户端只传 ID 仍会按最新查询清单校验；但一旦模型或前端传入 snapshot_id，后端会要求它等于同一会话最新成功查询的 snapshot_id。若 snapshot_id 已被更新的查询取代，即使 ID 仍出现在最新清单中，ToolCall 也会以 `agent_testcase_snapshot_not_latest`、`agent_websocket_testcase_snapshot_not_latest`、`agent_scenario_snapshot_not_latest` 或 `agent_environment_snapshot_not_latest` 阻断，`output_json_redacted` 包含 `requested_snapshot_id`、`latest_snapshot_id`、`snapshot_mismatch=true`、对应有效 ID 列表和 `next_action`。前端可把这些字段展示为“基于旧快照，请重新查询后提交”，不要自动把旧 snapshot_id 改写后重试。

对象引用 preflight 阻断会同时返回统一 envelope：`output_json_redacted.object_reference_preflight`，对应实时 `tool.failed.payload.object_reference_preflight` 也携带同一结构。该对象字段为 `preflight_version=object_reference_preflight_v1`、`status=blocked`、`reason`、`object_type`、`query_tool`、`blocked_tool`、`requested_ids`、`valid_ids`、`requested_snapshot_ids`、`latest_snapshot_id`，并按失败类型附带 `invalid_ids` 或 `stale_ids`。`reason` 当前可为 `ids_not_from_query_result`、`stale_or_deleted` 或 `snapshot_mismatch`。旧的 `invalid_test_case_ids`、`valid_test_case_ids`、`requested_snapshot_id` 等平铺字段继续保留兼容；前端新实现应优先读取 `object_reference_preflight` 做统一展示和调试定位。实时 timeline 可直接使用 `tool.failed.payload.object_reference_preflight` 渲染阻断原因，不需要先额外请求 ToolCall Detail。

场景保存工具还有一个场景编排质量 preflight：当 `scenario.create_saved` / `scenario.update_saved` 的多节点输入明显退化为仅包含测试用例 `reference_id` 的列表，而用户目标或场景描述明确要求依赖、上下文、取值、前置、后置、流程或编排时，ToolCall 会在创建审批前失败，`error_code=agent_scenario_orchestration_quality_missing`、`recovery_decision=reuse_or_recompose_scenario_draft_before_save`。失败输出固定包含 `output_json_redacted.quality_preflight`，实时 `tool.failed.payload.quality_preflight` 也携带同一摘要，字段包括 `tool_name`、`reason=scenario_orchestration_quality_missing`、`node_count`、`action_count`、`extraction_count`、`binding_count`、`template_reference_count` 和 `empty_test_case_configs`。前端应把它展示为“场景缺少前置/后置/取值/依赖编排，需复用或重新生成完整草稿”，不要弹出审批框。

同一会话“保存该场景/保存刚才的场景/保存「某流程」/保存后执行”属于草稿 artifact follow-up。模型可在 `scenario.create_saved` / `scenario.update_saved` 入参中传 `scenario_source={artifact_id,output_hash}`，其中 `artifact_id` 来自模型上下文里的 `active_artifact_handles[]`；后端再从同项目、同用户、同会话成功 ToolCall ledger 中解析 `scenario_draft` artifact 并读取完整 `draft.scenario`。`active_artifact_handles[]` 现在同时携带 `artifact_class` 和 `artifact_trust`：只有 `artifact_trust=SOURCE` 的 artifact handle 会参与 Capability Resolver 和保存/执行动作解锁；`artifact_class=AUTHORITATIVE` 只是业务权威分类，不能单独解锁 action。`DERIVED`/`SUMMARY` trust 或 class 只能作为展示、解释或背景信息。兼容旧格式 `scenario_source={tool_call_id,path,output_hash}` 和别名 `source_artifact`。后端会用 `output_hash` 校验来源未漂移；模型不需要、也不应为了保存把完整场景 JSON 搬进 prompt。如果模型仍只表达“保存这个/保存刚才的场景”而未显式传 `scenario_source`，后端会按当前 intent 名称优先、否则最近成功草稿的规则复用 `scenario.compose_draft` artifact。被复用的保存 ToolCall input 会包含 `scenario_source` 或 `scenario_draft_source={source,run_id,tool_call_id,path,output_hash,artifact_id,artifact_type}`，供 ToolCall Detail 展示来源。该字段是诊断元数据，不是业务 `ScenarioCreateRequest` 的一部分。

同一会话 `scenario.create_saved` / `scenario.update_saved` 成功后，成功 ToolCall ledger 会生成 SOURCE `saved_scenario` artifact handle，`artifact_summary` 至少包含可解析时的 `scenario_id`，并可包含 `name`、`environment_id`、`current_version`。该 handle 的 `available_followup_actions` 包含 `execute/query_runs/update_saved`，用于下一轮“执行刚创建的自动化测试流程/运行这个测试流程/执行刚才创建的流程”这类跨轮 follow-up 解锁 `scenario.query_project_scenarios` 与 `scenario.execute_dry_run`。前端可在调试面板展示为“已保存场景可执行句柄”，但它仍只是 Agent model view，不是执行结果；真正是否执行成功必须看后续 `scenario.query_project_scenarios`、`scenario.execute_dry_run` ToolCall 和场景 run 结果。

同一会话 `scenario.execute_dry_run` 成功返回但其中任一场景 run 为失败状态时，成功 ToolCall ledger 会额外生成 SOURCE `scenario_run_failure` artifact handle。该 handle 的 `artifact_summary` 只包含模型修复所需的有界摘要，例如 `scenario_id`、`environment_id`、`run_ids`、`failed_run_ids`、`statuses` 与最多若干条失败节点 `failures[]`，完整 run、步骤结果和响应体仍以 ToolCall Detail / 场景 run 详情为准。`available_followup_actions` 固定包含 `repair/query_scenario/compose_fix/update_saved/execute`，用于下一轮“修复问题/解决问题/fix/repair”这类省略 follow-up 解锁 `scenario.query_project_scenarios`、`testcase.query_project_cases`、`scenario.compose_draft`、`scenario.update_saved` 和 `scenario.execute_dry_run`。前端可把该 handle 展示为“场景执行失败，可修复”，但不要把它渲染为 assistant 回复或完整执行报告。

当当前用户输入是“保存/保存后执行”等 action-only follow-up，且同一会话 ledger 中存在可保存的 SOURCE `scenario_draft` artifact 时，Runner 会在模型上下文的 `conversation_working_context_v1` 中注入 `active_artifact_handles[]` 和可选 `active_artifact_action`。`active_artifact_action` 固定 `schema_version=active_artifact_action_v1`、`artifact_type=scenario_draft`、`artifact_class=AUTHORITATIVE`、`artifact_trust=SOURCE`、`domain=scenario`、`action=save`、`tool_name=scenario.create_saved`、`artifact_id`、可选 `output_hash/artifact_summary`，并提供 `tool_input_hint.scenario_source={artifact_id,output_hash}`；如果用户说“保存后执行/保存并执行”，还会带 `after_save_actions=["scenario.execute_dry_run"]`。该字段用于模型路由和前端调试展示，表示“当前轮可基于这个草稿提交保存审批”，不表示场景已经保存成功。前端可以在 Agent timeline 或调试面板中把它展示为“检测到可保存草稿”，但最终状态仍以 `scenario.create_saved` ToolCall、pending approval、审批后执行结果为准。

当当前用户输入是“修复问题/解决问题/fix/repair”等 repair follow-up，且同一会话 ledger 中存在 SOURCE `scenario_run_failure` artifact 时，`active_artifact_action` 会改为 `artifact_type=scenario_run_failure`、`domain=scenario`、`action=repair`、`tool_name=scenario.compose_draft`，并携带 `required_tools=["scenario.query_project_scenarios","testcase.query_project_cases","scenario.compose_draft","scenario.update_saved","scenario.execute_dry_run"]` 与 `tool_input_hint` 中的失败摘要。该字段表示“当前轮可以基于失败 dry-run 事实修复已保存场景并再次验证”，不是自动完成修复；真正的修改仍必须通过后续 `scenario.compose_draft` / `scenario.update_saved` ToolCall、审批和 dry-run 结果确认。

Plan 阶段模型上下文中还会出现轻量 `Capability Resolver` system message，payload 为 `agent_capability_plan_v1`。它由 `AgentContextManager` 根据当前 intent、Skill Router 结果、`active_artifact_handles/active_artifact_action/current_artifact_candidates` 和 artifact `available_followup_actions` 生成，且只允许 `artifact_trust=SOURCE` 的 artifact 解锁保存、执行等后续动作；Skill 文本里提到的工具不会绕过该 artifact boundary。字段包含 `allowed_tools`、可选 `domain/intent_action`、`available_actions[]`、`blocked_actions[]`、`required_facts[]`、`tool_input_hints` 和 `reason_codes[]`。如果存在 `artifact_class=AUTHORITATIVE` 但 `artifact_trust!=SOURCE` 的候选 artifact，`blocked_actions[].reason` 会是 `artifact_trust_not_source`，前端可在调试面板展示为“该产物不是工具真实输出，不能作为保存/执行来源”。前端如果在调试面板、prompt 预览或日志导出中看到该结构，应把它解释为“本轮为什么可见这些工具”的诊断 model view：`tool_input_hints.scenario.create_saved.scenario_source` 可以辅助解释模型为何能保存刚才的草稿，但它不是业务保存结果、不是审批记录，也不应渲染为 assistant 气泡。真正可执行状态仍以 routed tool catalog、ToolCall、Approval、Run Action State 和 ToolRuntime preflight 为准。

Plan 阶段模型上下文中也会出现轻量 `Skill Planner` system message，payload 为 `agent_skill_plan_v1`。字段包含 `primary_skill`、`supporting_skills`、`allowed_skills`、`candidate_skills[]`、`selection_strategy`、`ranker_mode` 和 `reason_codes[]`；同一轮 `Capability Resolver` payload 也会携带 `allowed_skills`，方便前端调试“为什么这个工具目录来自这个 Skill”。前端可在 Agent 调试面板或导出包中把它展示为“本轮 Skill 规划”，但不要把它当作用户可见回复、业务结果或工具执行结果。典型解释是：存在 SOURCE `saved_scenario` artifact 且用户说“execute the flow I just created and summarize the result”时，`Skill Planner.allowed_skills=["scenario-composition"]`、`reason_codes` 含 `artifact_action:saved_scenario.execute`，随后 Capability 才暴露 `scenario.query_project_scenarios/scenario.execute_dry_run`；没有可执行 artifact action 的“查询场景33执行报告”则应保持 `report-summary` 与 `report.read_summary`。

同一会话正式场景保存成功后，用户输入“在这个场景下执行测试/运行测试/试运行并总结结果/执行刚创建的自动化测试流程/执行刚才创建的测试流程”等场景执行 follow-up 时，后端 `AgentContextManager` 必须把本轮 route 到 `scenario-composition`，并在 routed tool catalog 中暴露 `scenario.query_project_scenarios` 与 `scenario.execute_dry_run`；`执行结果` 在这个语境中表示“执行完成后的总结”，不应把本轮降级成只读 `report.read_summary`。如果用户明确说“查询场景33执行报告/查看历史执行报告”，才按 `report-summary` 加载 `report.read_summary`。前端无需新增字段，但在调试面板或 timeline 中排查“为什么 Agent 不能执行场景”时，应优先检查当前 run 的 `Capability Resolver.allowed_tools`、`available_actions[].artifact_type=saved_scenario`、routed tool catalog 和 Skill，而不是只看全局 capabilities。

Agent 现在可以通过四个 `execution_record` 工具触发真实用例执行：`testcase.execute_saved`、`testcase.batch_execute`、`websocket_testcase.execute_saved`、`websocket_testcase.batch_execute`。这些工具都要求 `test:execute` 权限、`replay_policy=require_revalidation`，会创建 HTTP/WebSocket 业务执行记录，并在执行记录上写入来源字段：`trigger_source=agent`、`agent_run_id`、`agent_tool_call_id`、`trigger_tool_name`；普通前端人工执行继续写入 `trigger_source=manual`，其 Agent 关联字段为空。前端执行中心和 Agent ToolCall 详情可用这些字段区分“人工点击执行”和“AI/Agent 代用户执行”，不要把 Agent 执行记录当成无来源的普通人工执行。`testcase.query_project_cases` 返回 `case_snapshot`、`case_id_manifest` 与通用别名 `object_reference_manifest`：`case_snapshot.snapshot_id` 是本次查询事实快照，`object_family=test_case`，`validity_scope=current_agent_conversation_latest_query`，`identity_semantics` 明确测试用例 ID 只是可删除/可变化的数据库行定位符；`case_id_manifest.http_test_case_ids` / `websocket_test_case_ids` 是当前过滤结果升序 ID，`http_assertion_update_ids` / `websocket_assertion_update_ids` 是断言保存工具可用 ID，`id_source_rule` 固定提示“只能使用最新查询快照中的显式 ID，不得推断连续区间或复用历史文本中的 ID”；`object_reference_manifest` 携带 `object_family=test_case`、`query_tool=testcase.query_project_cases`、同一 `snapshot_id`、同一 `validity_scope` 和同一组显式 ID，作为后续更多业务对象接入 FactSnapshot/ActionPreflight 的通用前端调试入口；同时保留兼容字段 `http_test_case_ids`、`websocket_test_case_ids`、`http_batch_execute_input` 与 `websocket_batch_execute_input`。前端和模型调试面板应优先展示 `case_snapshot` / `case_id_manifest` / `object_reference_manifest`，不要从连续区间、旧消息或压缩摘要推断 ID。两个批量执行工具在创建任何执行记录前会一次性校验所有输入 ID 是否属于当前项目；存在无效或已删除 ID 时返回结构化 `422`，HTTP detail 包含 `code=agent_testcase_batch_invalid_ids`、`invalid_test_case_ids`、`valid_case_ids`、`required_tool=testcase.query_project_cases`、`next_action=refresh_case_snapshot_before_retry`，WebSocket detail 包含 `code=agent_websocket_testcase_batch_invalid_ids`、`invalid_websocket_test_case_ids`、`valid_case_ids`、`required_tool=testcase.query_project_cases`、`next_action=refresh_case_snapshot_before_retry`，并且不会留下部分 queued/passed/failed 执行记录。后端不再返回 `retry_batch_execute_input`，失败恢复必须重新查询当前项目用例快照，而不是过滤历史 ID 后继续执行。

`testcase.query_project_cases` 现在还为每个 HTTP/WebSocket 用例返回后端生成的对象引用句柄：`http_test_cases[].object_ref`、`websocket_test_cases[].object_ref`、`case_id_manifest.http_test_case_refs`、`case_id_manifest.websocket_test_case_refs` 和 `object_reference_manifest.object_references[]` 指向同一组引用。`object_references[]` 每项包含 `object_ref`、`id`、`object_type`、`name`、`path`、可选 `method` 和 `snapshot_id`。用例副作用工具继续兼容裸 ID，同时模型可传 `object_reference` 或 `object_references`；后端只从同一会话最新成功查询的 `object_references[]` 解析真实 ID，并在审批、权限和业务 handler 前回填 `test_case_id` 或 `test_case_ids`。前端可以把 `object_ref` 当作复制给 Agent 工具的稳定句柄展示，但不应把它当作长期业务身份；伪造、旧查询或未查询句柄会被 Harness preflight 阻断。

`testcase.query_project_cases` 支持 `detail_level` 控制工具结果大小，默认值为 `summary`，因此模型或旧前端不显式传值时也只返回轻量清单。`summary` 只返回 id/object_ref/name/method/path/environment/last_execution_status 以及 `assertion_count`、`extractor_count`、`has_body` 等摘要字段；`assertions` 和 `selected` 在摘要基础上返回 `assertions` 与 `extractors`，但仍省略 headers/query/body；`full` 返回完整用例定义并保持兼容；`execution_ready` 是批量执行和批量断言保存前的动作快照，返回 `case_snapshot.execution_ready=true`、`case_result_policy.execution_ready=true`、`*_batch_execute_input.case_snapshot_id` 与 `object_references`。工具还支持 `test_case_ids` 与 `websocket_test_case_ids` 精确回查。返回体包含 `case_result_policy.detail_fetch_hint` 与 `case_result_policy.large_task_strategy(strategy_id=summary_then_selected_detail_then_execution_ready_action)`，前端可在 ToolCall 详情里展示：大项目或断言补全任务先查 `detail_level=summary` 得到完整 ID/name 清单，再按显式 ID 用 `detail_level=selected/assertions` 查询详情并分析；真正提交 `testcase.batch_execute`、`websocket_testcase.batch_execute`、`testcase.batch_update_assertions` 或 `websocket_testcase.batch_update_assertions` 前，必须重新查询 `detail_level=execution_ready`，并复制后端返回的批量输入、snapshot_id 和 object_references。不要在截断后重新全量查询 `full`，也不要让用户确认本可由定点查询取得的详情。

Agent 模型上下文中的 `testcase.query_project_cases` 工具结果现在使用 Tool Result Projection，不等同于 ToolCall Detail 里的完整返回体。`AgentToolCallRead.output_json_redacted`、ToolCall Detail、导出包和调试面板仍保留完整 Ledger View，包括 `case_result_policy`、完整 `case_id_manifest/object_reference_manifest`、batch input 和用例详情；但回灌给模型的消息只包含 `payload.output.projection_version=tool_result_projection_v1`、snapshot 摘要、`counts`、预算内的 `cases[]` 和必要的 `case_details[]` 摘要，并带 `output_compacted_for_model=true`、`output_projection_version=tool_result_projection_v1`、`full_output_reference=ToolCall.output_json_redacted`。该引用只是审计/调试定位，不再附带模型可调用的 `full_output_read_tool`。前端展示工具结果时应继续以 ToolCall Detail 的完整字段为准，不要把模型 Model View 当作 UI 数据源；若需要解释“为什么模型没有看到全部用例”，可展示 `cases_truncated.returned/total`、`full_output_reference` 和 ToolCall Detail 入口作为调试线索。

场景和环境也使用同一对象引用句柄协议：`scenario.query_project_scenarios` 返回 `scenarios[].object_ref`、`scenario_id_manifest.scenario_refs` 与 `object_reference_manifest.object_references[]`；`project.read_context` 返回 `environments[].object_ref`、`environment_id_manifest.environment_refs` 与 `object_reference_manifest.object_references[]`。`scenario.query_project_scenarios` 支持 `detail_level=summary|full`：`summary` 返回场景元信息和 `definition_summary.node_count/dataset_count/test_case_count/tag_count`，省略 `nodes` 与 `datasets`；`full` 返回完整场景定义。`scenario.execute_dry_run` 继续兼容 `scenario_id` / `environment_id`，也可以传 `object_reference` 引用场景、传 `environment_reference` 引用环境；后端会从最新成功的 `scenario.query_project_scenarios` 和 `project.read_context` manifest 中分别解析真实 ID。前端展示时可以统一把 `object_reference_manifest.object_references[]` 作为“可引用对象清单”，但任何副作用工具仍必须经过执行器 preflight。

Agent 现在也可以通过环境管理工具读取和修改项目环境配置：`environment.query_project_configs` 是只读工具，要求 `environment:view` 权限，可返回环境清单和已脱敏变量；`environment.create_config`、`environment.update_config`、`environment.delete_config`、`environment.upsert_variable`、`environment.delete_variable` 都是 `business_update + require_revalidation` 工具，要求 `environment:manage` 权限，并且必须走 pending approval 后才会写入业务表。环境变量写入工具支持 `environment_id`、`environment_reference` 或 `environment_name` 定位环境；带显式环境 ID/引用的写工具会经过 `project.read_context` 环境事实快照校验，未查询、旧快照、伪造引用或已删除环境会以 `agent_environment_ids_not_from_query_result` / `agent_environment_id_stale_or_deleted` 阻断。`environment.upsert_variable` 对 `is_secret=true` 或名称/值疑似 token、secret、auth、cookie、bearer 的变量做双层保护：Ledger 内保存可执行的加密值，`AgentToolCallRead.input_json_redacted`、ToolCall Detail、审批面板和工具输出只显示 `***`，前端不得渲染原始 secret 或加密 marker。

Agent 还可以通过保存类工具修改已保存测试用例和测试场景：`testcase.create_saved`、`testcase.update_saved`、`testcase.update_assertions`、`testcase.batch_update_assertions`、`websocket_testcase.create_saved`、`websocket_testcase.update_saved`、`websocket_testcase.update_assertions`、`websocket_testcase.batch_update_assertions`、`scenario.create_saved`、`scenario.update_saved`。测试用例保存工具要求 `case:manage` 权限，测试场景保存工具要求 `scenario:manage` 权限；全部保存类工具都是 `side_effect_class=business_update`、`replay_policy=require_revalidation`，因此模型发起工具请求后不会直接写入业务表；后端会创建 `AgentToolCall(status=planned, approval_required=true)` 和 `AgentApproval(status=pending)`，并把 run 置为 `needs_human`。前端应在审批面板展示 ToolCall 的 `input_json_redacted`、`required_permissions_json`、`policy_reason_json.policy_context.approval_required_reason=unsafe_side_effect` 和当前 approval，不要显示为“已保存/已更新”。只有用户通过 `/agents/tool-calls/{tool_call_id}/approve` 审批并 resume 后，worker 才会执行对应保存工具。

当用户说“根据现有用例创建等价类用例/生成边界值用例/基于已有接口用例扩展新用例”时，后端会把本轮路由到 `http-test-case-design`，`Capability Resolver` 的 model view 会出现 `intent_action=create_cases`，`required_facts` 包含 `test_case_source_inventory`，并在 routed tool catalog 中暴露 `project.read_context`、`testcase.query_project_cases`、`ai_skill.run_draft`、`testcase.validate_schema` 与 `testcase.create_saved`。前端无需新增字段；调试面板只需按现有 `Capability Resolver.allowed_tools`、ToolCall、Approval 和 Run Action State 展示。`testcase.create_saved` 出现在 allowed tools 只表示本轮可以提交创建审批，不表示用例已创建。

`ai_skill.run_draft` 的 `input` 字段在 ToolSpec 中允许对象或 JSON 编码对象字符串，这是 Agent 工具壳对模型输出的容错边界；后端会把字符串解析为对象后再进入 `AISkillRunRequest` 和具体 AI Skill schema。非法字符串或非对象 JSON 会以 `agent_ai_skill_run_input_invalid` 阻断，不应在前端显示为 Python `ValueError`。前端 ToolCall Detail 可以原样展示 redacted input/output，但不要把 JSON 字符串形态理解为业务接口允许任意自由文本。

`testcase.create_saved`、`testcase.execute_saved`、`testcase.batch_execute`、`testcase.update_saved`、`testcase.update_assertions`、`testcase.batch_update_assertions`、`websocket_testcase.create_saved`、`websocket_testcase.execute_saved`、`websocket_testcase.batch_execute`、`websocket_testcase.update_saved`、`websocket_testcase.update_assertions` 和 `websocket_testcase.batch_update_assertions` 在真正调用后端执行/保存服务前都会校验输入 ID 是否来自同一 Agent 会话内、同项目、同用户、早于当前工具调用的最新一次已成功 `testcase.query_project_cases` 显式结果；保存类工具如果携带嵌套 `case.environment_id` 或 `case.environment_ids`，也会在进入审批执行或业务写入前校验这些环境 ID 是否来自最新 `project.read_context`。HTTP 工具只能使用最新 `case_id_manifest.http_test_case_ids` / `http_assertion_update_ids`、兼容字段 `http_test_case_ids`、`http_batch_execute_input.test_case_ids` 或 `http_test_cases[].id` 中出现的 id；WebSocket 工具只能使用最新 `case_id_manifest.websocket_test_case_ids` / `websocket_assertion_update_ids`、兼容字段 `websocket_test_case_ids`、`websocket_batch_execute_input.websocket_test_case_ids` 或 `websocket_test_cases[].id` 中出现的 id。批量执行和批量断言保存工具额外要求这些 ID 来自最新 `execution_ready` 查询事实，`summary` 或 `selected/assertions` 查询只能用于展示和分析，不能作为批量副作用提交依据。校验失败时 ToolCall 不会跨过副作用边界，状态为 `failed`、`execution_phase=blocked_by_harness`，HTTP error_code 为 `agent_testcase_ids_not_from_query_result`，WebSocket error_code 为 `agent_websocket_testcase_ids_not_from_query_result`，环境 error_code 为 `agent_environment_ids_not_from_query_result`，`output_json_redacted` 包含 `required_tool`、`blocked_tool`、对应 `invalid_*_ids`、最新有效 id 列表和 `next_action`，对应 `tool.failed` 事件也携带相同的 invalid 字段。 如果 ID 曾出现在最新快照但执行前已被删除，HTTP error_code 为 `agent_testcase_id_stale_or_deleted`，WebSocket error_code 为 `agent_websocket_testcase_id_stale_or_deleted`，环境 error_code 为 `agent_environment_id_stale_or_deleted`，`recovery_decision` 指向对应 refresh 动作，`output_json_redacted` 与 `tool.failed` 事件携带对应 `stale_*` 字段，而不是 invalid 字段。前端应把这些展示为工具失败/可恢复提示，不要把模型猜测的连续区间、旧查询结果或未查询 id 继续提交审批。

Agent 也可以通过 `scenario.query_project_scenarios` 获取当前项目已保存场景的显式 ID 快照，再通过 `scenario.execute_dry_run` 触发场景 dry-run 执行记录，或通过 `scenario.update_saved` 更新已保存场景。`scenario.create_saved` 不需要现有场景 ID，但它的 `scenario.environment_id` 仍必须来自最新 `project.read_context`；`scenario.update_saved` 在调用 `ScenarioService.update_scenario` 前必须校验 `scenario_id` 来自同一 Agent 会话内最新成功 `scenario.query_project_scenarios`。当用户请求“保存后执行/保存并执行/dry-run”且 `scenario.create_saved` / `scenario.update_saved` 审批执行成功后，后端会在 final summary 前自动追加 `scenario.query_project_scenarios(detail_level=summary, keyword=已保存场景名)` 和 `scenario.execute_dry_run`，并写入普通 ToolCall 与 `tool.auto_followup_requested` 审计事件；前端应把它们当作同一 run 的后续工具结果展示，而不是等待模型再发起新工具请求。`scenario.query_project_scenarios` 是只读工具，输入为 `project_id`、可选 `keyword`、`page_size` 和 `detail_level`，返回 `scenario_snapshot`、`scenario_id_manifest`、`object_reference_manifest`、`scenario_ids` 和 `scenarios[]`；`object_reference_manifest.object_family=scenario`、`query_tool=scenario.query_project_scenarios`，`scenario_ids` / `scenario_execute_ids` 是 dry-run 和 update 可引用的显式 ID。`scenario.execute_dry_run` / `scenario.update_saved` 在进入业务服务前会再次查询 `test_scenarios` 确认场景仍属于当前项目且 `is_deleted=false`。未查询、旧查询或历史文本中的场景 ID 会以 `agent_scenario_ids_not_from_query_result` 阻断，输出 `invalid_scenario_ids` / `valid_scenario_ids`；最新快照中的场景若执行前被删除，会以 `agent_scenario_id_stale_or_deleted` 阻断，输出 `stale_scenario_ids` / `valid_scenario_ids`，`recovery_decision=refresh_scenario_snapshot_before_retry`。前端应把这些和测试用例 ID 阻断一样展示为可恢复工具失败，不要继续提交审批或自动重试旧 ID。

保存类等高风险审批工具在创建 `AgentApproval` 前必须先通过 action preflight，并绑定可执行的 `decision_context_build_id`。action preflight 复用执行期 `ObjectReferenceGuardRule`：测试用例、WebSocket 用例、场景和环境 ID 必须来自同一 Agent 会话内最新成功事实快照；批量执行和批量断言保存还必须来自 `detail_level=execution_ready` 的动作快照。随后保存类工具还会用正式业务 Pydantic schema 做输入预校验；例如 `scenario.create_saved` 的响应提取必须放在 `test_case.config.extractors` 或 `test_case.config._scenario_context.extractions`，不能把 `{name,path}` 提取器误写成 `fixed_value after_actions`。如果模型使用旧 `case_snapshot_id`、selected/assertions 查询结果、历史 ID、不存在的对象或不合法保存 schema，ToolCall 会直接变为 `failed + blocked_by_harness`；对象引用失败返回 `output_json_redacted.object_reference_preflight`，schema 失败返回 `output_json_redacted.schema_preflight` 和 `error_code=agent_tool_input_schema_invalid`。这类失败不会创建 pending approval，也不会把 run 置为 `needs_human`。前端应把它展示为工具失败/需要重新查询或修复输入后重试，不应渲染审批弹窗或自动提交审批。通过 action preflight 后，如果模型请求没有显式 `evidence_refs`，后端会把已落账 ToolCall 的冻结输入 hash 作为 `system_record` 决策证据加入该 ToolCall 的 policy evidence，并创建 `build_purpose=approval` 的 ContextBuild；这个证据只包含 `tool_call_id`、`input_hash`、`runtime_snapshot_id` 等可审计引用，不把完整请求体扩散到前端或模型上下文。这样用户批准后 resume 不会再因为缺少 `context_decision_build_required` 才失败；若 ContextBuild 真的缺少必需证据，仍由高风险 evidence gate 阻断。

保存类工具输入直接复用现有业务 schema：创建 HTTP 用例使用 `{"project_id":1,"case": TestCaseCreateRequest}`；完整更新 HTTP 用例使用 `{"project_id":1,"test_case_id":7,"case": TestCaseUpdateRequest}`；仅保存 HTTP 断言使用 `{"project_id":1,"test_case_id":7,"assertions":[AssertionConfig]}`，批量保存 HTTP 断言使用 `{"project_id":1,"items":[{"test_case_id":7,"assertions":[AssertionConfig]}]}`。创建 WebSocket 用例使用 `{"project_id":1,"case": WebSocketTestCaseCreateRequest}`；完整更新 WebSocket 用例使用 `{"project_id":1,"test_case_id":3,"case": WebSocketTestCaseUpdateRequest}`；仅保存 WebSocket 断言使用 `{"project_id":1,"test_case_id":3,"assertions":[WebSocketAssertionConfig]}`，批量保存 WebSocket 断言使用 `{"project_id":1,"items":[{"test_case_id":3,"assertions":[WebSocketAssertionConfig]}]}`。创建测试场景使用 `{"project_id":1,"scenario": ScenarioCreateRequest}`；更新测试场景使用 `{"project_id":1,"scenario_id":5,"scenario": ScenarioUpdateRequest}`，其中 `ScenarioUpdateRequest.version` 必须等于最新 `current_version`，否则业务服务返回版本冲突。`update_assertions` / `batch_update_assertions` 只替换 `assertions` 字段，不覆盖 method/path/headers/query/body/extractors 或 WebSocket path/headers/messages/timeout/extractors。执行成功后的 `output_json_redacted` 分别返回 `operation`、`project_id`、`test_case_id` / `websocket_test_case_id` / `scenario_id`，以及 `test_case` / `websocket_test_case` / `scenario` 详情。审批前这些输出为空，因为业务数据尚未写入。

### 3.1.1 Model Health

| method | path | purpose |
| --- | --- | --- |
| `GET` | `/agents/model-health` | Read Agent model provider configuration and optionally run a minimal live DeepSeek stream probe |
| `POST` | `/agents/conversation-smoke` | Admin-only full Agent conversation smoke: create run, execute runner, return summary and event chain |

Query:
```text
live=false by default; live=true runs a tiny AIService.chat_stream probe and is admin-only.
```

`AgentModelHealthRead` fields:
```text
provider,configured,base_url,default_model,live,reachable,latency_ms,first_delta_received,completed,model,finish_reason,error_code,error_message,checked_at
```

The response never includes the DeepSeek API key. Frontend can call `GET /agents/model-health` during Agent page boot to show whether the backend model provider is configured. Admin-only `live=true` is for debugging the "run created but no assistant reply" path: `configured=false` means the key is missing, `reachable=false` means the provider call failed, and `first_delta_received=false` means the provider did not stream assistant content during the probe. `error_message` remains a string for compatibility: short errors are returned as-is, while errors longer than `AGENT_ERROR_MESSAGE_MAX_CHARS=512` are summarized in-place with `agent_error_message_summary_v1`, `agent_error_message_truncated`, original size, hash, and `full_error_reference`.

`POST /agents/conversation-smoke` accepts:
```text
project_id,intent,max_iterations
```

`max_iterations` 可省略，后端默认使用 12；前端显式传值时允许范围为 1-20。该字段表示单个 Agent run 的模型/工具闭环上限，不是 UI 轮询次数；当后端因达到上限进入最终总结，会写入 `loop.observed(RC_MAX_ITERATIONS)` 供 timeline/Runbook 调试。

It returns `AgentConversationSmokeRead`:
```text
project_id,run_id,conversation_id,status,completed,first_delta_received,assistant_visible,assistant_message,error_code,error_message,event_types,latest_event_sequence,run_summary,latency_ms,generated_at
```

This route is admin-only and creates a real Agent Run/EventStore record. Use it when `model-health` is reachable but the full Agent page still does not show a reply.

Backend maintainers can also run the normal-user E2E diagnostic script against the real configured database and DeepSeek provider before blaming frontend streaming:

```powershell
.\.venv\Scripts\python.exe scripts\agent_conversation_e2e_check.py --project-id 1 --user-id 1 --intent "Reply exactly: Agent e2e ok." --timeout-seconds 90
```

The script succeeds only when live health is reachable, a normal `POST /agents/runs` starts the runner, EventStore receives `model.started` plus at least one `model.delta`, the run reaches `run.completed`, and summary returns `assistant_visible=true`. It never prints the DeepSeek API key.

### 3.1.2 Agent Skill Catalog

| method | path | purpose |
| --- | --- | --- |
| `GET` | `/agents/skills` | Read the Codex-style Agent Skill catalog metadata available to the backend runner |

Response data:

```text
AgentSkillRead[] = [{ name, description }]
```

Only public metadata is returned. `SKILL.md` bodies, Skill-local private prompt resources, and routing-only fields such as `triggers`, `guard_*`, and `routing_*` remain backend-only prompt/routing material and must not be fetched or rendered by the frontend as user-visible instructions. The backend runner uses a two-level Codex-style loading model:

- The backend still exposes the complete public skill metadata catalog through `/agents/skills`; this is for diagnostics and capability panels, not the exact per-run model context.
- `_conversation_system_prompt()` keeps a stable full skill catalog snapshot for prompt-cache and Harness contract tests; the real `AgentConversationRunner` context is now built by `AgentContextManager`, which injects only the Skill catalog row(s) routed for the current intent and working context.
- For each run, `AgentContextManager.skill_messages()` injects only the selected skill bodies into the model context; each injected Skill prompt block has a backend hard cap and may end with `agent_skill_prompt_truncated` or `agent_context_skill_truncated` if the `SKILL.md` body is too long.
- The model-visible tool catalog follows the same layered rule: frontend `/agents/capabilities` may show the full public ToolRegistry manifest, while the per-run model context only receives a routed tool catalog plus a separate Layer 2 `input_summary` contract for relevant tools. Routed catalog `summary` is a capped model view; full tool descriptions and full schemas remain in capabilities/runtime snapshot/ToolCall diagnostics. `input_summary` may include `nested_required`, for example `scenario.compose_draft` exposes `{"input":["requirement"]}` so the model can see that object-mode compose input must contain `input.requirement` even though the full schema is not injected.
- Intent matching uses each Skill's own frontmatter `triggers`; narrow guard pre-checks, unsupported capability guards, tool-required routing, and required follow-up tool repair may use private `guard_*` / `routing_*` lists such as `guard_unsupported_capability`, `routing_requires_tool`, and `routing_required_tool_after_success`. Required follow-up rules can also declare backend-private `intent_markers`, so a broad Skill trigger like "scenario" does not force `scenario.compose_draft` for read-only project-context questions such as "whether an existing scenario exists". Adding or adjusting a Skill route should not require editing the central runner prompt or Python phrase table.
- Narrow classifier prompts and guard final messages can live in Skill-local private resource files, for example `scenario-composition/save-intent-classifier.md` and `scenario-composition/unsupported-save-message.md`; these resources are loaded only by backend guard code and never by the frontend catalog. Classifier prompts that are sent to the model are also capped by `AGENT_UNSUPPORTED_CAPABILITY_CLASSIFIER_PROMPT_MAX_CHARS` and may end with `agent_classifier_prompt_truncated` when a private resource is too long.
- If the unsupported capability classifier provider call fails, returns non-JSON content, or returns a long classification `reason`, the backend logs `agent_unsupported_capability_classification_failed`, `agent_unsupported_capability_classification_invalid_json`, or `agent_unsupported_capability_classified` and continues the normal conversation path when the guard is not triggered. Those logs use the same bounded error format as other Agent diagnostics: short errors/content/reasons remain readable, while values longer than `AGENT_ERROR_MESSAGE_MAX_CHARS=512` use `agent_error_message_summary_v1`, `agent_error_message_truncated`, original size, hash, and `full_error_reference=AgentConversationRunner.unsupported_capability_classifier`, `AgentConversationRunner.unsupported_capability_classifier.invalid_json`, or `AgentConversationRunner.unsupported_capability_classifier.reason`. If the run is cancelled while the classifier call is in flight, backend preserves `cancelled` and does not emit the guard's synthetic completion events. This does not add a frontend event or response field.
- Current built-in skills are `agent-runtime-operations`, `ai-skill-runtime-governance`, `api-definition-import`, `api-error-contract-debugging`, `assertion-extractor-binding`, `batch-execution-scheduling`, `browser-capture-analysis`, `ci-release-integration`, `data-privacy-redaction`, `dataset-parameterization`, `defect-triage`, `environment-config-management`, `execution-diagnosis`, `general-testing-answer`, `http-test-case-design`, `media-evidence-management`, `migration-compatibility-planning`, `mock-service-virtualization`, `notification-alerting-config`, `project-context`, `project-permission-admin`, `report-archive-export`, `report-summary`, `scenario-composition`, `security-auth-testing`, `test-asset-lifecycle`, `test-plan-management`, `visual-flow-design`, and `websocket-test-case-design`.
- The frontend may show the catalog in diagnostics or capability panels, but normal conversation behavior is still driven by `/agents/runs` and SSE events.

模型工具调用现在以 provider 原生 `tools/tool_calls` 为主，Markdown `agent_tool_request` 仅是旧协议兼容回退。这是后端与模型之间的 wire 变更，不改变前端的 Run、EventStore、ToolCall、Approval 或 Summary 响应结构。DeepSeek thinking 轮次所需的 `reasoning_content` 只在后端内存中短暂回传 provider，不出现在 SSE、Run Summary 或对话气泡中；前端无需新增该字段。

`scenario.compose_draft` 对 Agent 始终是纯草稿 Tool：即使模型输入 `execute_candidates=true` 或 `self_validate=true`，后端也会强制关闭，避免 `draft` Capability Plan 跨越到执行副作用。草稿节点的 request/assertions/extractors 会从 `case_source` 对应的保存用例恢复，无证据 binding 会被删除；`draft.scenario_grounding` 提供归一化摘要，`draft.scenario_validation.valid=true` 才能作为可保存的 AUTHORITATIVE 草稿。前端继续按普通 ToolCall 展示，不要把 compose 视为已执行。

模型收到的 `scenario.compose_draft` Planning View 固定包含 `source.reference_ids`、`candidate.reference_ids/omitted_by_composer_reference_ids/omitted_reason_status`、`scenario.node_count/reference_ids`、`grounding.excluded_nodes`、`validation`、`execution.executed=false`、`persistence.saved=false` 和 `authoritative_summary`。这是模型回灌摘要，不新增前端 API 字段；前端查看完整依据时仍以 ToolCall `output_json_redacted.draft.scenario_grounding/scenario_validation` 为准。`omitted_reason_status=not_recorded_do_not_infer` 表示只能显示“原因未记录”，不能根据历史执行或模型 warning 猜测原因。

当结构化意图动作为 `analyze` 或 `query` 时，Capability Resolver 只会向模型暴露 `read_only` / `deterministic_compute` 工具；目标领域和证据领域仍由本轮 LLM 意图决策与 supporting Skills 决定。前端应继续根据实际 ToolCall timeline 展示读取链，不要预设分析请求只有固定的一个工具序列。

### 3.2 Run 和流式事件

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/runs` | 按项目、conversation、status 查询 run 历史 |
| `POST` | `/agents/runs` | 创建 Agent Run |
| `GET` | `/agents/runs/{run_id}` | 校准 run 状态 |
| `GET` | `/agents/runs/{run_id}/summary` | 聚合右侧 RunInspector 摘要 |
| `GET` | `/agents/runs/{run_id}/actions` | 聚合右侧操作按钮状态 |
| `POST` | `/agents/runs/{run_id}/cancel` | 停止 run |
| `POST` | `/agents/runs/{run_id}/resume` | 从 checkpoint 恢复 |
| `POST` | `/agents/runs/{run_id}/reconcile` | 触发 reconcile |
| `GET` | `/agents/runs/{run_id}/events` | SSE 事件流 |
| `GET` | `/agents/runs/{run_id}/events/snapshot` | 非流式事件快照和 cursor 状态 |
| `GET` | `/agents/runs/{run_id}/events/replay-audit` | 断线重放审计 |

`AgentRunRead` 字段：

```text
item_id,run_id,project_id,user_id,conversation_id,intent,status,current_iteration,current_step_index,max_iterations,runtime_snapshot_id,last_checkpoint_id,last_event_sequence,migration_block_count,blocking_tool_call_ids_json,result_json,error_code,error_message,started_at,completed_at,created_at,updated_at
```

`AgentRunRead.item_id=agent-run://{run_id}` 由 run 事实派生，表示 Codex-style turn/run 自身的 timeline/debug/download item。它不替代 `run_id` 业务标识，也不替代 SSE 的 `event_seq` cursor；Transcript、Export、Summary、Resume、Action State 和 Event Snapshot 中嵌套的 `run` 都应携带同一值，便于前端稳定定位整个 run/turn。

`GET /agents/runs/{run_id}/summary` 返回 `AgentRunSummaryRead`，用于 Codex 风格右侧 RunInspector 的轻量聚合展示。它只读聚合 run、最新 EventStore 事实、ToolCall 计数、Approval 计数、MigrationBlock 计数、Memory usage 计数、assistant 展示元数据和按钮状态；该路由与 `GET /agents/runs/{run_id}` 一样必须按 run 所属项目校验访问权限。

`AgentRunSummaryRead` 字段：
```text
run,assistant_message,assistant_visible,completion_source,model_invoked,model,finish_reason,usage,event_count,latest_event_sequence,latest_event_types,tool_call_count,pending_tool_call_count,approval_count,pending_approval_count,migration_block_count,open_migration_block_count,memory_usage_count,blocking_tool_call_ids,terminal,can_cancel,can_resume,updated_at
```

前端约定：
- 只有 `assistant_visible=true` 时才渲染 `assistant_message` 为 assistant 回复；smoke/debug run 会返回 `assistant_visible=false`。
- `assistant_message` 是后端完成前校准过的 GitHub Flavored Markdown，可直接交给 Markdown renderer；若包含表格，表头、分隔行和每条数据行都已独占一行。
- `assistant_message` 面向用户描述平台对象时应优先展示业务名称，ID 只作为定位字段；例如测试用例应展示为“用例名称（ID: 7）”或表格列“用例名称 / ID”，而不是只输出 `7, 8, 10`。如果工具结果没有返回名称，后端 Agent 才会说明“工具结果未返回名称”并展示 ID。
- final summary 阶段使用独立的极简模型上下文，不再注入 `可用工具如下`、Agent Skill 正文或 `tool_result.read_full` 读取指引；该阶段只接收用户原始请求和已完成 ToolCall 的紧凑摘要，用于生成最终用户回复。当 Summary 的 `run.result_json.final_summary_tool_request_suppressed=true` 时，表示模型仍输出了工具请求且已被后端兜底阻止；前端仍按 `assistant_visible=true` 展示后端给出的 `assistant_message`。如果同一结果中的 `tool_calls[]` 状态全部为 `succeeded`，该消息应是“工具已成功执行但重复工具请求被阻止”的成功态说明；只有存在失败/阻断 ToolCall 时才展示为需要查看失败详情或修复输入。
- `can_cancel`、`can_resume`、`terminal` 用于 RunInspector 操作按钮状态；`can_resume=true` 表示当前 run 可直接调用 resume，候选来源包括 `paused/needs_human/migration_blocked`、残留 blocking id 或 `failed_retryable` ToolCall；当 `pending_approval_count > 0` 或 `open_migration_block_count > 0` 时，`can_resume` 必须为 `false`，前端应先走 `review_approvals` 或 `resolve_migration` 流程。`blocking_tool_call_ids` 是摘要级定位列表，必须按存储顺序稳定去重，避免历史 JSON 残留重复 id 导致 RunInspector 或 Action State 派生入口重复渲染。
- `latest_event_sequence` 与 `latest_event_types` 只做轻量新鲜度摘要，完整时间线仍以 SSE 为准。

`GET /agents/runs/{run_id}/actions` 返回 `AgentRunActionStateRead`，用于右侧操作区、Runbook 入口和待办按钮状态：
```text
run_summary,actions,primary_action_ids,blocked_reasons,generated_at
```

每个 action 字段：
```text
action_id,label,method,path,enabled,reason,severity,resource_ids,resource_item_ids,details
```

固定 `action_id` 顺序：
```text
view_summary,stream_events,cancel_run,review_approvals,resume_run,reconcile_run,resolve_migration,open_runbook
```

前端约定：
- 只用 `enabled` 决定按钮是否可点击；禁用说明显示 `reason`。
- `primary_action_ids` 是后端给出的当前优先操作顺序，独立于固定 `actions` payload 顺序，按 `review_approvals` -> `resolve_migration` -> `reconcile_run` -> `resume_run` -> `open_runbook` -> `cancel_run` 过滤 enabled action，`cancel_run` 只能作为最后兜底主操作；例如 pending approval 时优先 `review_approvals`，uncertain ToolCall 时优先 `reconcile_run`。当 run 状态为 `migration_blocked` 但已经没有 open migration block 时，`resume_run` 必须 enabled 并进入 `primary_action_ids`，让用户通过 resume/freshness 继续收敛残留状态。即使 run 已经 terminal，只要仍有 `uncertain/reconciling` ToolCall，`reconcile_run` 仍会 enabled，`resume_run` 和 `cancel_run` 继续按 terminal 禁用。若 terminal run 上存在 open migration block，`resolve_migration` 可用，但解决 block 只把 ToolCall 从 `needs_migration` 推回 `reconciling`，不得把 run 改回 active；此时 `resolve_migration.details` 必须携带 `run_status`、`run_terminal=true`、`resolve_preserves_terminal_run=true`、`post_resolve_next_action=reconcile_run` 与 `tool_call_status_after_resolve=reconciling`，让右侧操作区在用户点击前就能提示真实恢复语义。干净 `completed` run 不显示 Runbook 主入口；但 `completed` run 如果仍有 uncertain ToolCall、open migration block 或其他恢复原因，`open_runbook` 必须 enabled 并进入 `primary_action_ids`。
- `resource_ids` 放当前 action 关联的 approval、tool_call 或 migration block id，必须保持稳定排序与去重；ToolCall 类资源按 `step_index`、`attempt_index`、内部 id 输出，Approval 与 MigrationBlock 类资源按创建时间、内部 id 输出。例如同一 `failed_retryable` ToolCall 同时残留在 blocking list 时，`resume_run.resource_ids` 只输出一次该 `tool_call_id`，但 `details.blocking_tool_call_ids` 与 `details.retryable_tool_call_ids` 仍可分别表达来源。详情列表仍按对应接口 hydrate。
- `resource_item_ids` 放同一 action 关联资源的 Codex-style timeline/debug item id，必须与 `resource_ids` 同步稳定排序与去重；`review_approvals` 指向待审批的目标 ToolCall item，即 `agent-tool-call://{run_id}/{tool_call_id}`，不是 approval 自身 id；`resume_run` 和 `reconcile_run` 指向 ToolCall item；`resolve_migration` 指向 `agent-migration-block://{run_id}/{block_id}`。前端用 `resource_ids` 调详情接口，用 `resource_item_ids` 高亮 timeline/debug/download item，不要在前端重新拼接。
- `resume_run.details.blocking_tool_call_ids` 会合并 Run 阻断字段和 pending approval 对应的 `tool_call_id`；`pending_approval_tool_call_ids` 可用于把审批卡片定位回具体 ToolCall。

`POST /agents/runs` `auto_complete` is backend smoke/debug only. Normal frontend conversations must omit it or send `false`. When `auto_complete=true`, the backend does not call the model and `run.completed.result` contains `completion_source=smoke_auto_complete`, `model_invoked=false`, and `assistant_visible=false`; frontend must not render this as a real assistant reply.

Normal `POST /agents/runs` conversations start the backend `AgentConversationRunner` after `run.started`; MySQL and file-backed SQLite both start the background worker. Only in-memory SQLite test databases skip the worker to avoid cross-thread test isolation issues. If the frontend sees only `run.queued/run.started` plus heartbeat, call `/events/snapshot` and `/agents/model-health` with `live=true`; absence of `model.started` means the runner did not start. If an active `queued/running` run has no new EventStore event for longer than `AGENT_RUN_STALE_TIMEOUT_SECONDS` (default 900s), backend read paths mark it `failed` and append `run.failed(error_code=agent_run_stale_worker_lost)` so the UI must stop the thinking state and show a recoverable backend interruption. If `scripts/agent_conversation_e2e_check.py` succeeds for the same project/user but the UI still has no assistant bubble, the backend has produced a normal reply and the remaining issue is likely frontend stream parsing, cursor recovery, auth headers, or rendering state.

Agent worker 异常必须收敛为服务端终态，而不是只写后台日志。`AgentConversationRunner` 在模型流、工具请求修复、final summary 或审批后续写阶段抛出异常时，应通过 `AgentRuntimeService.fail_run()` 追加 `run.failed` 并把 `AgentRun.status` 置为 `failed`；如果异常本身来自 MySQL 断连、`PendingRollbackError` 等导致当前 SQLAlchemy session 已不可继续使用，runner 会 rollback/丢弃坏连接并用新的 `SessionLocal` 兜底写入同一个 `run.failed`。前端不需要识别该恢复路径，只要在 SSE 或 `/events/snapshot` 看到 `run.failed`、或 Run Summary 的 `terminal=true/status=failed`，就必须结束“运行中”状态并展示 `error_code/error_message`。

Agent worker 调用模型 provider 时不应长期占用数据库事务。`model.started`、`model.delta`、`model.stream_retrying` 等事件提交后，Runner 会在等待 `AIService.chat_stream()` 下一段输出前释放当前 SQLAlchemy transaction；取消检查只做短事务读取，非终态时立即释放连接。这是后端内部连接治理，不新增前端字段，也不改变 SSE 顺序；它降低 DeepSeek 长时间静默、网络抖动或 RDS 断开空闲连接时把 run 卡在 active 状态的概率。

When a run fails through `AgentRuntimeService.fail_run()`, `AgentRun.error_message` and `run.failed.payload.error_message` remain string fields. Short errors are returned as-is; errors longer than `AGENT_ERROR_MESSAGE_MAX_CHARS=512` are summarized in-place with `agent_error_message_summary_v1`, `agent_error_message_truncated`, original size, hash, and `full_error_reference`. `POST /agents/conversation-smoke` and Run Summary read the same bounded string.

`POST /agents/runs/{run_id}/resume` 返回 `AgentRunResumeRead`：

```text
run,resumed,checkpoint_freshness,scheduled_tool_call_ids,executed_tool_call_ids,observed_tool_call_ids
```

`scheduled_tool_call_ids`、`executed_tool_call_ids` 与 `observed_tool_call_ids` 在所有 resume 结果中都必须稳定返回数组；terminal/noop、freshness pause、no-progress blocking 等未调度、未成功执行或未观察到工具终态的路径返回空数组，而不是省略字段。`executed_tool_call_ids` 只表示本次 resume 成功执行的 ToolCall；`observed_tool_call_ids` 表示本次 resume 已观察到终态并可从审批阻塞中清除的 ToolCall，可能包含 `failed/manual_intervention`。

两份 Harness 文档用 `Required Agent Run resume payload contract` 机器契约固定该响应的字段顺序、稳定数组字段和 `source=AgentRunResumeRead`；后端回归会同时校验 route response 与 direct service dict，前端类型应按这个契约生成或维护。

`checkpoint_freshness` 现在始终包含 compaction 引用诊断字段：`context_compaction_object_key`、`context_compaction_event_seq`、`context_compaction_event_type`、`context_compaction_available`。当当前 checkpoint 对应的 run 曾触发 `context.history_compacted` 时，object key 形如 `agent-event://{run_id}/{event_seq}`，用于定位同一 run 的 redaction-safe compaction envelope；该字段不是模型 prompt、压缩摘要正文或 assistant 内容。若 checkpoint 指向的 compaction event 丢失或引用格式错误，Freshness Gate 会返回 `result=too_old`、`action=replan_from_latest_safe_state`，避免前端继续触发不可恢复的 resume。

当 run 因审批进入 `needs_human`，且阻断 ToolCall 已被 approve 后，resume 会先执行已批准的阻断工具，把执行成功的 id 放入 `executed_tool_call_ids`，再继续生成最终 assistant 回复。若已批准工具执行失败，审批本身仍视为已决策，后端会写入 `tool.failed` 和 `tool.result_observed(status=failed)`，从 `blocking_tool_call_ids_json` 清除该 ToolCall，并把失败作为已观察到的工具结果回灌给后续模型回复；失败 ToolCall 不进入 `executed_tool_call_ids`，前端应以 ToolCall 详情里的 `status/error_code/error_message` 展示失败原因，不要继续显示同一个 pending approval 卡片。`run.resumed` 只在本次 resume 确实观察到已批准 ToolCall 终态、调度了 `failed_retryable` 或清理了 blocking 时写入；如果本次 resume 已经把 `failed_retryable` 重新入队，后端会把这些 `scheduled_tool_call_ids` 从残留的 `blocking_tool_call_ids_json` 中清除，run 可回到 `running` 并由 worker 后续执行；如果 freshness 通过但没有任何工具执行/重排，且仍存在 blocking ToolCall，响应保持 `resumed=false`，不会追加 `run.resumed`。重复提交同一已批准 approval、且 lineage/epoch/input/resource 全部一致时，approve 按幂等成功返回同一审批结果；真正过期、被 supersede、epoch 不一致或输入 hash 变化仍返回 409。若 ToolCall 已排队但 worker 领取前 run 被取消，后端会在 worker claim 阶段直接把 ToolCall 标记为 `obsolete(agent_run_cancelled_before_tool_execution)`，queue 标为 failed，不发放 lease，不调用 backend；若 worker 已领取但尚未执行，后续 heartbeat 也不会继续保活该 lease，而会把 queue/ToolCall 收敛到同一 obsolete/failed 终态；即使直接进入执行器，执行入口也会做同一兜底。若安全工具执行期间 run 被取消，后端会保留 `cancelled` 终态，ToolCall 标记为 `obsolete(agent_run_cancelled_during_tool_execution)`，不会进入 `executed_tool_call_ids`，不启动审批后的 final summary 模型调用，也不写 `run.completed` 覆盖取消。若非安全 effectful 工具返回时 run 已取消，后端会保留脱敏工具输出和 output_hash，但 ToolCall 标记为 `uncertain(agent_run_cancelled_after_tool_effect)`、`recovery_decision=reconcile_required_after_run_terminal`，queue 标为 failed，等待 reconcile 对账而不是进入成功工具结果回灌；此时前端刷新 `/actions` 应显示 `reconcile_run.enabled=true`，执行 reconcile 只收敛 ToolCall 事实，不把 run 从 `cancelled/failed/completed` 重新打开。若 reconcile 因 schema/adapter 不支持创建 migration block，run 仍保持 terminal；解决 block 后 ToolCall 回到 `reconciling`，前端再通过 `reconcile_run` 继续对账。前端应重新打开或继续监听该 run 的 SSE，按 `tool.result_observed`、后续 `model.delta` 和 `run.completed` 更新时间线；若看到 `run.cancelled`，以取消终态为准。

`POST /agents/runs/{run_id}/cancel` 写入 `run.cancelled` 后，后端对话 runner 和 approval resume 路径会在模型 stream 函数入口、模型 stream、partial stream interruption 事件落库前、late tool request suppression 审计事件落库前、stream 返回后的用户可见回复 Markdown normalization / delta flush / `model.completed` 写入前、unsupported capability guard 分类返回、guard synthetic completion、工具请求 repair 模型返回后的解析/修复事件落库前、异常处理器写 `run.failed` 前、ToolCall 创建前、每次重新调用模型前、worker claim 发放 lease 前、worker heartbeat 续约 lease 前、ToolCall 执行入口、ToolCall 执行返回后和 final summary 前后重新读取 terminal 状态；底层 `AgentRuntimeService.complete_run()` / `fail_run()` 也会在写 `run.completed/run.failed` 前重新读取 terminal，`append_event()` 也会在 terminal run 上跳过非终态 late event，WorkerQueue claim 不会把已取消 run 的 queued ToolCall 租约领取，WorkerQueue heartbeat 不会继续保活已取消 run 的 leased ToolCall，工具执行器会在 backend 调用前把已取消 run 的 ToolCall 转为 obsolete，orphan lease recovery 不会把已取消 run 的 ToolCall 重新排回 queued/planned，安全工具执行器会在成功落账前把取消后的 ToolCall 转为 obsolete，非安全 effectful 工具执行器会在 effect 已返回但 run 已 terminal 时转为 uncertain 并要求 reconcile；terminal run 内残留的 uncertain ToolCall 仍可通过 `reconcile_run` 对账，但对账不得追加普通 terminal 后事件或改变 run 终态。如果取消已经生效，后续不会再发起下一次模型调用，也不会写 `model.started`、`model.stream_interrupted`、`model.tool_request_stream_suppressed`、`model.tool_request_repaired`、`model.required_tool_repaired`、`model.completed`、`run.completed` 或 `run.failed` 覆盖 cancelled；即使漏掉上层 guard 的调用点尝试追加普通事件，EventStore 也不会继续递增 sequence 或写入 Outbox。前端 Stop 后仍应继续监听 SSE 或刷新 `/actions`，以服务端 terminal 状态为准。

### 3.2.1 Conversation 历史

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/conversations?project_id=...` | 查询服务端 conversation 列表 |
| `GET` | `/agents/conversations/{conversation_id}/runs?project_id=...` | 查询单个 conversation 下的 run 列表 |
| `GET` | `/agents/conversations/{conversation_id}/transcript?project_id=...` | 恢复 Codex 式多轮 transcript |
| `GET` | `/agents/conversations/{conversation_id}/export?project_id=...` | 导出 conversation 调试包 |

`AgentConversationRead` 字段：

```text
conversation_id,project_id,title,run_count,latest_run_id,latest_run_status,created_at,updated_at
```

`AgentConversationTranscriptRead` 字段：
```text
conversation,turns,context_compactions,generated_at
```

`conversation` 使用 `AgentConversationRead` 字段；`turns` 按 run 创建时间升序返回 `AgentRunSummaryRead[]`。`context_compactions` 是同一 conversation 内 `context.history_compacted` 事件的只读索引，字段为 `item_id,run_id,event_seq,event_type,payload_json,created_at`，用于恢复/调试时定位发生过预算压缩的 run；其中 `item_id=agent-context-compaction://{run_id}/{event_seq}`，对齐 openai/codex `ContextCompaction { id }` 的 timeline marker 语义。它不复制模型 prompt、压缩摘要正文或未脱敏上下文。前端刷新页面、切换设备或从左侧历史打开会话时，应优先调用 transcript 恢复 user prompt、assistant 最终回复、run 状态、右侧 badge 和 compaction 审计状态；SSE 仍只负责当前活跃 run 的实时增量。

后端在当前 run 调用模型前会按预算组装同一 conversation 的已完成历史消息，并额外注入一条“同一会话工作上下文”system 消息。历史消息保留用户 `intent` 与可见 assistant 回复；工作上下文则把最近轮次整理为结构化 `recent_turns`、`current_artifact_candidates`、`current_intent_is_deictic_followup` 和回指解析规则，供模型理解“直接、刚才、上面、这个”等省略表达应绑定到上一轮哪个产物。该工作上下文只进入模型输入和技能选择，不作为前端 transcript/export 的新业务 payload；前端仍以 run summary、events、ToolCall 和 approval 作为展示事实源。Unsupported capability guard 只能用显式领域 subject 预拦截，不能仅凭回指词在模型读取会话工作上下文前终止 run。

历史较长时，Runner 会把较早轮次压成一个 system 摘要、保留最近若干轮，并写入 `context.history_compacted` 事件；transcript/export 会把这些事件汇总到 `context_compactions`，避免前端只能扫描完整 EventStore 才能知道历史是否被压缩。该事件 payload 是 redaction-safe compaction envelope，包含 `trigger=auto`、`reason=history_budget_exceeded`、`phase=pre_model_call`、`implementation=inline_deterministic_summary`、`strategy=summarize_older_keep_recent`、压缩/保留轮次数、`estimated_input_units_before/after`、`budget_limit_units`、`summary_role`、`replacement_history`、`initial_context_injection`、`reference_context_item`、`context_baseline=system_run_skill_memory_rebuilt_per_model_call`、`window_number`、`first_window_id`、`previous_window_id`、`window_id` 与 `source`；不会再使用会被通用脱敏擦除的 `token_budget` / `estimated_tokens_*` key。`context_baseline` 表示本地 Runner 在每次模型调用前重建 system prompt、run context、Skill catalog/正文和 Memory context，而不是把 Codex 的 WorldState full baseline 或原始 prompt 复制进事件。`window_*` 字段按同一 conversation 的 compaction 事件生成单调窗口链，`window_id` 形如 `agent-window://{scope_hash}/{window_number}`，第一窗口的 `previous_window_id=null`。已完成历史 run 的用户 `intent` 会保留为多轮上下文；历史 assistant 回复只有在对应 run 的 `assistant_visible` 未显式为 `false` 时才会进入模型上下文，smoke/debug/auto-complete 等不可见结果不会作为 assistant 历史回放。queued/running/paused 等未完成 run 仍可通过 transcript/list/export 查看，但不会进入当前模型 prompt。两份 Harness 文档的 `Required Agent conversation history context contract`、`Required Agent history compaction envelope contract` 和 transcript/export payload contract 会机器校验这些 source status、排除状态、历史顺序、压缩策略、compaction envelope 字段和 `context_compactions` 索引字段。前端可把该事件展示为调试审计状态，但不要把压缩摘要渲染成 assistant 气泡。

`GET /agents/conversations/{conversation_id}/export` 返回 `AgentConversationExportRead`，用于下载或调试 Codex 式 conversation：
```text
conversation,turns,context_compactions,events_by_run_id,tool_calls_by_run_id,approvals_by_run_id,migration_blocks_by_run_id,export_format,generated_at,derived_from
```

前端约定：
- `context_compactions` 与 transcript 同源，按 run 顺序和 event_seq 排序；每项的 `item_id` 可作为前端 timeline/debug item 的稳定 key，便于下载包直接定位 compaction 审计事实。
- `events_by_run_id` 按 `event_seq` 升序保存每个 run 的 EventStore 事件；每个事件的 `item_id=agent-event://{run_id}/{event_seq}` 可作为导出包和前端 timeline/debug item 的稳定 key。
- `tool_calls_by_run_id`、`approvals_by_run_id`、`migration_blocks_by_run_id` 只包含对应 run 的派生事实；`AgentToolCallRead.item_id=agent-tool-call://{run_id}/{tool_call_id}` 可作为 ToolCall Detail、审批响应、导出包和前端 timeline/debug item 的稳定 key；`AgentApprovalRead.item_id=agent-approval://{run_id}/{approval_id}` 表示审批记录自身的稳定 item，`tool_call_item_id=agent-tool-call://{run_id}/{tool_call_id}` 表示该审批请求绑定的目标 ToolCall item；`AgentApprovalLineageRead.item_id=agent-approval-lineage://{run_id}/{approval_lineage_id}` 表示审批 lineage 自身的稳定 timeline/debug item，`tool_call_item_id` 指向该 lineage 绑定的目标 ToolCall item；`AgentMigrationBlockRead.item_id=agent-migration-block://{run_id}/{block_id}` 表示兼容阻断资源自身的稳定 item，`tool_call_item_id` 在阻断绑定 ToolCall 时指向被阻断的 ToolCall item，未绑定时为 `null`；敏感字段仍使用后端 redacted 字段。
- `export_format=agent_conversation_export_v1`，可作为下载文件格式版本。

创建 run 时如果前端不传 `conversation_id`，后端会生成 `agent-conv-*` 并在 `AgentRunRead.conversation_id` 返回。继续多轮对话时，前端必须复用该值；后端会把同 conversation 最近已完成 run 的 `intent` 作为模型上下文，并只回放 `assistant_visible` 未显式为 `false` 的 `result_json.message`。

`AgentEventRead` 字段：

```text
item_id,event_seq,event_type,payload_json,created_at
```

`item_id` 由 EventStore 事实派生，不是数据库新列；格式固定为 `agent-event://{run_id}/{event_seq}`，对齐 openai/codex 每个 timeline/thread item 都有稳定 `id` 的恢复模型。`event_seq` 仍是 run 内 cursor，前端不要跨 run 复用。

`GET /agents/runs/{run_id}/events/snapshot?after_sequence=...&limit=...` 返回 `AgentRunEventSnapshotRead`，用于前端调试、断线恢复前校准、或无法直接观察 ReadableStream 时判断后端是否已经写入 `model.delta`。它不是新的事实源，只是 EventStore 的 JSON 快照：
```text
run,events,context_compactions,after_sequence,event_count,latest_event_sequence,next_after_sequence,terminal,generated_at
```

前端约定：
- `events` 使用 `AgentEventRead` 结构，并按 `event_seq` 升序返回；`item_id` 可作为 snapshot 恢复后 timeline/debug item 的稳定 key。SSE 仍使用 `id: event_seq` 作为浏览器重连 cursor，并在 `data` envelope 中额外携带同源 `item_id`，让实时流和 snapshot/export 使用同一个 timeline/debug key。
- `context_compactions` 是当前 run 内 `context.history_compacted` 事件的只读索引，字段与 transcript/export 的 `context_compactions` 相同：`item_id,run_id,event_seq,event_type,payload_json,created_at`。它用于断线恢复时定位本 run 发生过的长历史压缩，即使本次 `events` 窗口为空或不包含较早的 compaction event；它不复制模型 prompt、压缩摘要正文或未脱敏上下文。
- 下一次轮询或重连可以使用 `next_after_sequence` 作为 cursor。
- `event_seq` 是 run 内序号，前端必须按 run 保存 cursor；如果误把其他 run 的 `Last-Event-ID/after_sequence` 带到当前 run，后端会在 cursor 大于当前 `latest_event_sequence` 时重置为 0 并重放当前 run 事件，避免连接只收到 heartbeat。
- `terminal=true` 且 `next_after_sequence >= latest_event_sequence` 时，当前 run 的事件已经追平；如果 terminal 是 stale guard 触发的 `run.failed(agent_run_stale_worker_lost)`，前端应结束 pending assistant 气泡并提示用户重试或查看 runbook，而不是继续显示“正在思考”。

SSE data payload 必须至少包含：

```text
item_id,schema_version,run_id,project_id,event_seq,event_type,occurred_at
```

`item_id` 由后端发送 SSE 时从 `AgentEvent.item_id` 派生并合入出站 `data` envelope，不写回 `AgentEvent.payload_json`；因此旧客户端继续按 `event_seq` 和事件类型解析，前端新 timeline 可优先用 `item_id` 去重/定位。

前端必须处理的对话生成事件：

```text
model.started
context.model_budget_compacted
memory.context_injected
model.delta
model.completed
model.markdown_normalized
model.stream_retrying
model.stream_interrupted
model.tool_request_detected
planner.execution_plan_created
model.tool_request_invalid
model.tool_request_repaired
model.final_response_reference_tool_request_repaired
model.tool_request_repair_failed
model.internal_context_leak_suppressed
model.tool_request_stream_suppressed
model.required_tool_missing
model.required_tool_repaired
model.required_tool_repair_failed
tool.planned
tool.input_repaired
tool.running
tool.completed
tool.failed
tool.result_observed
scenario.state_transition
run.completed
run.failed
```

对话事件 payload 会带有 Loop trace 字段，用于区分同一个用户问题内的多次模型调用：`iteration_id` 表示 run 内循环轮次，`model_call_id` 表示一次具体 LLM 调用，`loop_step` 表示调用阶段（例如 `assistant_response`、`tool_planning`、`tool_request_repair`、`required_tool_repair`、`final_summary`、`intent_capability_guard`）。这些旧顶层字段保持兼容；新增的 `loop_state` 是稳定嵌套 envelope，字段包括 `iteration`、`iteration_id`、`phase`、`step`，并在可得时携带 `model_call_id`、`tool_call_id`、`decision_reason`。`phase=model` 用于模型调用、工具规划、修复和最终总结，`phase=tool` 用于工具执行/观察链路，前端可优先按 `loop_state.phase + loop_state.step` 分组展示调试轨迹。`model.started`、`model.delta`、`model.markdown_normalized`、`model.completed`、`model.stream_retrying` 和 `model.stream_interrupted` 必须尽量携带同一个 `model_call_id` 与 `model_response_item_id=agent-model-response://{run_id}/{model_call_id}`；其中 `model_call_id` 表示一次 LLM 调用，`model_response_item_id` 表示这次调用正在更新的 assistant 响应项，和 EventStore/SSE 事件自身的 `item_id=agent-event://{run_id}/{event_seq}` 不是同一层身份。`model.stream_retrying` 表示 DeepSeek stream 在首个 delta/done 之前遇到可重试错误，payload 包含 `attempt`、`max_retries`、`delay_seconds`、`error_message`，前端可作为时间线审计状态展示，不应渲染为 assistant 文本。`model.tool_request_detected`、`tool.result_observed`、`tool.failed` 等审计事件可额外携带 `tool_call_id` 与 `decision_reason`。前端不得用 `model.started` 次数判断“一个问题只调用一次 LLM”，而应按 `model_call_id + loop_step`、`model_response_item_id` 或 `loop_state` 展示/调试 Plan/Act/Observe/Repair/Final 的循环。

`model.started.payload.context_budget` 是模型调用前的总上下文预算 envelope，`schema_version=agent_model_context_budget_v1`，字段包括 `budget_scope`、`budget_limit_units`、`budget_limit_reached`、`estimated_input_units_before/after`、`layer_budgets`、`layer_actual_units_before/after`、`compacted` 与 `compacted_layers`。当 `compacted=true` 时，事件流会在对应 `model.started` 前出现 `context.model_budget_compacted`，payload 使用同一 envelope 并携带同一 `model_call_id/loop_state`；前端可在调试面板展示它，但不得渲染为 assistant 气泡。该事件说明后端已在发送 provider 前压缩 history、working context、Memory、工具结果或 Skill 上下文，不代表会话历史丢失；完整事实仍以 Transcript、ToolCall ledger、Run Event Snapshot 和 ToolCall Detail 为准。

`tool.input_repaired` 表示后端确定性输入修复引擎在 ToolCall 创建、审批冻结和 idempotency hash 前改写了模型输入；当前 `repair_engine=deterministic_tool_input_repair_v1`，payload 至少包含 `tool_call_id`、`tool_name`、`strategy`、`input_hash_before`、`input_hash_after` 和修复摘要。该事件用于 timeline/Runbook 审计，不渲染为 assistant 气泡。典型场景是模型把 `environment_snapshot_id` 或 `scenario_snapshot_id` 错放到 `scenario` 对象内部，后端将其提升到工具顶层后继续审批/执行。

`scenario.state_transition` 是场景创建状态机审计事件，`state_machine=CREATE_SCENARIO`、`state_machine_version=scenario_creation_state_machine_v1`，payload 包含 `from_state`、`to_state`、`trigger`、`tool_name`、`tool_call_id` 与可选 `summary`。企业/场景组合链路通常会依次出现 `CHECK_CONTEXT`、`QUERY_CASES`、`COMPOSE_DRAFT`、`SAVE_PENDING_APPROVAL`，run 完成前补写 `SUMMARY` 和 `END`。前端可将它作为流程进度和调试时间线展示，但最终用户回复仍以 `run.completed.result.message` 为准。

`planner.execution_plan_created` 是 Planner/Executor 分离后的工具执行计划审计事件，出现在 `model.tool_request_detected` 之后、`tool.planned` 之前。payload 使用 `schema_version=agent_execution_plan_v1`，包含 `plan_id`、`planner=llm_tool_planner`、`executor=tool_runtime`、`verifier=runtime_verifier`、`run_id`、`project_id`、`iteration`、`step_index` 和 `steps[]`；单步 `steps[]` 会记录 `tool_name`、`input_hash`、`input_keys`、`evidence_ref_count` 与有界 `reason`。同一次 `model.tool_request_detected.payload.execution_plan_id` 会指向该 `plan_id`。前端可把它展示为 Planner -> Executor -> Verifier 的调试链路，不应渲染为 assistant 气泡，也不代表工具已经执行成功。

`model.tool_request_detected.payload.reason`、`model.tool_request_detected.payload.decision_reason` 以及后续 `tool.*.payload.decision_reason` / `loop_state.decision_reason` 保持字符串兼容但有界：短工具规划理由原样返回，超过 `AGENT_ERROR_MESSAGE_MAX_CHARS=512` 时使用 `agent_error_message_summary_v1`、`agent_error_message_truncated`、原始长度、hash 和 `full_error_reference=AgentConversationRunner.model.tool_request_detected.reason` 或 `AgentConversationRunner.tool_trace.decision_reason` 表达。前端 timeline 可展示该摘要，但不应把这些字段当作完整模型规划文本来源。

`model.tool_request_invalid.payload.content_preview`、`model.tool_request_repair_failed.payload.content_preview`、`model.required_tool_missing.payload.content_preview`、`model.required_tool_repair_failed.payload.content_preview` 以及对应 LoopObservation 的 `observation_json.content_preview` 仍是字符串预览字段，但也保持有界：短内容原样返回，超过 `AGENT_CONTENT_PREVIEW_MAX_CHARS=512` 时使用 `agent_content_preview_summary_v1`、`agent_content_preview_truncated`、原始长度、hash 和 `full_content_reference` 表达。前端 timeline 可展示该摘要；完整模型输出不从这些字段恢复，应以后端 EventStore/Runbook 指向的引用或后续可见 assistant 内容为准。

`model.completed.payload.requested_tool=true` 表示该次模型调用输出的是内部工具请求而非用户可见 assistant 文本。此时 payload 必须携带 `assistant_visible=false`；前端 timeline 可展示审计预览，但不得渲染为 assistant 气泡。`model.completed.payload.content` 仍保持字符串字段，但只承载短工具请求原文或 `agent_content_preview_summary_v1` 有界预览；超长 `agent_tool_request` 会以 `agent_content_preview_truncated`、原始长度、hash 和 `full_content_reference=AgentConversationRunner.model.completed.tool_request.content` 表达。后端给下一轮模型回放上一轮工具请求时也不会复制完整 fenced JSON，而是使用 `agent_tool_request_context_summary_v1`，包含 tool_name、短 input/evidence JSON、reason 有界摘要和 `source_content_preview`。如果 `final_summary` 阶段模型仍输出 fenced `agent_tool_request`，后端会写入 `model.markdown_normalized(content="", replace_content=true, normalization_reason=final_summary_tool_request_suppressed)` 清空临时气泡，再写入 `model.completed(requested_tool=true, assistant_visible=false, final_summary_tool_request_suppressed=true)` 审计事件，并用安全兜底文案完成 run，避免工具请求进入 `run.completed.result.message`。前端不得从这些字段恢复完整工具 JSON；ToolCall 详情、`model.tool_request_detected` 和 ExecutionLedger 才是结构化工具事实源。

如果工具执行后下一轮模型错误复述了内部 `agent_tool_request_context_summary_v1`，后端会把该输出视为内部上下文泄漏而不是用户回复：先写入 `model.tool_request_invalid` 并触发一次静默修复；若修复仍返回同类内部摘要，后端写入 `model.internal_context_leak_suppressed` 审计事件，并用安全兜底文案替换即将进入用户可见 `model.delta`、`model.completed.content` 和 `run.completed.result.message` 的内容。前端不得把 `model.internal_context_leak_suppressed.payload.content_preview` 渲染为 assistant 气泡；它只用于 timeline/Runbook 调试。

`model.stream_retrying.payload.error_message`、`model.stream_interrupted.payload.error_message` 和 interrupted `model.completed.error_message` remain string fields. Short errors are returned as-is; errors longer than `AGENT_ERROR_MESSAGE_MAX_CHARS=512` are summarized in-place with `agent_error_message_summary_v1`, `agent_error_message_truncated`, original size, hash, and `full_error_reference`, so timeline diagnostics do not copy provider response tails.

当工具闭环用满 `run.max_iterations` 且仍需要进入最终总结时，后端会在 `final_summary` 模型调用前创建 stop 用 decision ContextBuild 并写入 `loop.observed`，RootCause 为 `RC_MAX_ITERATIONS`、`next_action=stop`、`mitigation_action=human_review_or_extend_limit`；`observation_json.source=max_iteration_guard`，并记录 `max_iterations`、`current_iteration`、`final_summary_iteration` 与 `tool_call_ids`。该事件属于 Resource / Limit 审计轨迹，不渲染为 assistant 气泡；最终用户可见回复仍以后续 `model.delta`、`model.markdown_normalized`、`model.completed.content` 和 `run.completed.result.message` 为准。前端可在 timeline/Runbook 中展示该 stop decision，但不应把 `final_summary` 的额外 `model.started` 当成新用户轮次。

`model.delta` 的 payload 使用 `content` 字段传输可展示的 assistant 文本；但主对话循环采用 planner-first 语义，不再依赖用户 intent 的关键词匹配来预判是否需要工具。后端会先静默收完整模型输出，让模型在同一次 planning 响应中决定普通回答或 `agent_tool_request`；如果解析结果是工具请求，只写审计事件和 ToolCall，不把 preamble、候选分析或 fenced JSON 渲染为 assistant 气泡；如果解析结果是普通自然语言，后端再补发一个合并后的可见 `model.delta`，随后写入 `model.completed` 和 `run.completed`。因此前端不应假设主循环普通回复会在 provider stream 尚未结束前出现首个 delta；`queued/running` 期间应通过 run/timeline 状态展示思考中，看到 `model.delta` 后按到达顺序追加即可。审批恢复 final summary 等明确总结阶段仍可继续通过后续 `model.delta`、`model.markdown_normalized` 和 `run.completed.result.message` 展示用户可见回复。若模型在自然语言中混入一个完整 fenced `agent_tool_request`，后端会写入 `model.tool_request_invalid`，优先本地剥离并规范化轻微 schema 偏差，再写入 `model.tool_request_repaired(repair_strategy=salvaged_fenced_tool_request)`；其他非法格式才调用一次 LLM 修复。LLM repair 或 required follow-up repair 返回后如果再次混入自然语言但只包含一个合法工具块，后端会复用本地剥离逻辑并在 `model.tool_request_repaired` / `model.required_tool_repaired` 上标记 `repair_strategy=salvaged_repair_fenced_tool_request`。planner-first 后正常工具规划不应再产生“先展示 preamble 再撤回”的事件；`model.markdown_normalized(content="", replace_content=true, normalization_reason=tool_request_stream_suppressed)` 仅作为兼容旧路径或非主循环后处理的撤回语义保留。SSE 对 `queued/running` run 使用短轮询以降低 EventStore 到浏览器的传播延迟，非活跃状态保持普通轮询和 heartbeat。软件测试领域的通用问答也是普通自然语言回复：例如测试理论、用例设计、接口/WebSocket 测试、断言、测试数据、缺陷定位、回归策略、CI 和报告解读等不需要读取项目实时事实或创建平台对象的问题，可以没有 ToolCall，前端直接按 assistant 气泡展示。后端要求所有用户可见自然语言回复遵守 GitHub Flavored Markdown，并在完成前校准最终文本：`model.completed.content` 与 `run.completed.result.message` 都是规范化后的 Markdown，表格行不会以 `| |` 方式挤在同一行。若后端发现模型流式内容需要修复，会在 `model.completed` 前写入 `model.markdown_normalized`，payload 包含 `content` 与 `replace_content=true`；前端应使用该 `content` 替换当前 assistant 气泡，而不是追加。如果 Stop/cancel 发生在 stream 已返回但 Markdown normalization、补发 delta、ToolCall 创建或 `model.completed` 尚未落库的后处理窗口，后端以 `run.cancelled` 为准，不再写最终完成事件覆盖取消。`model.completed` 的 payload 对用户可见自然语言和最终总结使用 `content` 字段记录本轮完整输出；`requested_tool=true` 的工具请求型 `model.completed.content` 只记录有界预览，并可附带 `provider`、`model`、`finish_reason`、`usage`。若 DeepSeek 已返回部分内容后流式连接中断，后端写入 `model.stream_interrupted`，并尽量用已收到的 partial content 继续解析工具或生成可见结果，避免 UI 空白。工具执行完成后，后端会把工具结果以有界模型视图回灌给模型；大输出不会完整进入模型上下文，而是以 `output_preview`、`output_truncated`、`output_size_chars`、`output_hash`、`full_output_reference=ToolCall.output_json_redacted` 表达。该引用只是审计和 UI 定位，不是模型可调用动作；模型缺少详情时应重新调用业务 query 工具做 selected/assertions/execution_ready 精确查询，完整 redacted 输出只通过后端 Runtime、ToolCall Detail、导出包和调试面板查看。

若 LLM repair 后仍连续返回多个合法 `agent_tool_request` fenced block，后端保持一轮一个 ToolCall 的账本边界，只解析第一个合法工具块并写入 `model.tool_request_repaired(repair_strategy=salvaged_repair_first_tool_request_block)`；后续工具不会在同一事件中批量创建，必须等下一轮模型基于最新 ToolResult 再规划。前端应把该策略显示为修复审计状态，不要把被忽略的后续 fenced block 渲染成 assistant 内容或额外 ToolCall。

若后端发现普通最终回复引用了不在最新 `testcase.query_project_cases` 结果中的用例 ID，会写入 `model.final_response_reference_invalid` 并触发一次 `final_response_reference_repair`。该 repair 如果返回合法 `agent_tool_request`，后端写入 `model.final_response_reference_tool_request_repaired`，随后继续正常的 `model.tool_request_detected -> ToolCall -> tool.result_observed -> 下一轮模型`，不得把 repair 的工具请求当成用户可见回答或直接 `run.completed`。该事件只用于 timeline/Runbook 调试，前端仍以后续可见 `model.delta`、`model.completed.content` 与 `run.completed.result.message` 校准 assistant 气泡。

场景组合工具链当前采用 query-first：`scenario-composition/SKILL.md` 通过私有 `routing_required_tool_after_success` 声明 `testcase.query_project_cases -> scenario.compose_draft` 的 follow-up 规则，`scenario.compose_draft` 的 `ToolSpec.required_context_requirements` 声明 `case_inventory_context`。该 requirement 可由三类来源满足：同一 run 内更早成功的 `testcase.query_project_cases` fresh execution、当前 run 已产出的 `artifact_class=AUTHORITATIVE` `test_case_query_snapshot` artifact，或同一会话历史成功 ToolCall 产出的权威 `test_case_query_snapshot` artifact。如果模型在缺少该上下文时直接请求 `scenario.compose_draft`，后端会创建可审计 ToolCall，但在执行前阻断并写入 `tool.failed`、`tool.result_observed`，`error_code=scenario_compose_requires_case_query`，`output_json_redacted.required_context_requirement=case_inventory_context`；同时后端会绑定一个修复用 decision ContextBuild 并写入 `loop.observed`，RootCause 为 `RC_TOOL_PREREQUISITE_MISSING`、`next_action=repair`，`observation_json` 记录 `blocked_tool`、`required_tool`、`tool_call_id` 与错误码。前端应将这些事件展示为 ToolCall 错误/纠正状态和调试审计轨迹，并继续等待后续模型按工具结果重新规划，不要把该错误或 `loop.observed` 渲染成最终 assistant 回复，除非 run 已进入 terminal failed。若查询用例成功且存在候选用例，但模型没有继续调用 `scenario.compose_draft` 而输出自然语言分析，后端只有在用户目标命中 follow-up 规则的 `intent_markers`（例如生成/创建/组合/执行场景、场景草稿、dry-run、数据集/参数化）时才写入 `model.required_tool_missing`，payload 包含 `after_tool` 与 `required_tool`；同时后端会绑定修复用 decision ContextBuild 并写入 `loop.observed`，RootCause 为 `RC_REQUIRED_TOOL_FOLLOWUP_MISSING`、`next_action=repair`，`observation_json` 记录 `after_tool`、`required_tool` 与内容预览，然后进行一次静默修复。该修复调用只接收有界的上一轮自然语言输出上下文，超长内容以 `agent_repair_context_truncated` 截断，前端不应把修复 prompt 视为完整 assistant 内容来源。修复成功写入 `model.required_tool_repaired` 后继续 ToolCall 生命周期；若 repaired 内容混入自然语言但包含单个合法工具块，仍按成功修复处理并带 `repair_strategy=salvaged_repair_fenced_tool_request`；修复失败写入 `model.required_tool_repair_failed`。纯项目上下文、资源盘点或“是否已有场景”这类只读问题可以在 `project.read_context` / `testcase.query_project_cases` 后直接完成，不应因出现“场景”二字被前端视为漏调用 compose。

`scenario.compose_draft` 是 Agent-facing 编排工具，Tool input 的 `input` 字段既可以是完整 `AIScenarioComposeRequest` 对象，也可以是非空自然语言字符串。对象模式下 `input.requirement` 是必填自然语言目标；Layer 2 `input_summary.nested_required.input=["requirement"]` 会把这个嵌套必填项暴露给模型。字符串会在后端工具适配层归一化为 `{"requirement": "<原字符串>"}`，顶层误放的 `requirement/scenario_name/self_validate/execute_candidates/max_nodes/include_*/*_test_case_ids/extra_requirements` 等 `AIScenarioComposeRequest` 字段也会在不覆盖嵌套 `input` 显式值的前提下合并进 compose input。若模型把已规划的 `nodes`、`_scenario_context`、`before_actions`、`after_actions` 或 `datasets` 误当作 compose input root 且缺少 `requirement`，后端会兼容注入通用 requirement、从节点引用中提取候选用例 ID，并把这段结构化意图写入 `extra_requirements` 交给 compose skill 重新生成草稿；这是兼容 guard，不是推荐入参形态。这样模型把“创建企业模块全量测试场景”直接放进 `input` 时，不会再触发 Python `dict(string)` 的 `dictionary update sequence element #0 has length 1; 2 is required`，也不会因结构化草稿提示缺少 `requirement` 直接暴露 Pydantic 错误；真正非法类型会以 `agent_scenario_compose_input_invalid` 阻断。成功生成草稿后，Tool Runtime 会执行 `ScenarioGraphValidator`，再把修复后的 `draft.scenario` 返回给模型和前端；`draft.graph_validation.schema_version=scenario_graph_validation_v1`，包含 `valid`、`issue_count`、`open_issue_count` 和 `issues[]`，`draft.graph_repair.schema_version=scenario_graph_repair_v1`，包含 `applied` 与 `repaired_issue_codes[]`。当前确定性修复覆盖从 `config.extractors` 补齐 `_scenario_context.extractions`、为已由上游定义且被 `{{variable}}` 消费的变量补齐 `_scenario_context.bindings`；消费了但此前没有定义的变量会保留为 `undefined_variable` open issue，前端可在 ToolCall Detail 或调试面板展示为草稿质量问题。

场景组合 follow-up 的 intent marker 明确覆盖中文“场景组合 / 测试场景组合”，并通过统一短语匹配兼容“测试场景生成”等常见换位表达。主循环工具决策由模型 planner 输出决定；Skill routing/intent marker 只作为 required follow-up、unsupported guard 和审计治理的辅助防线。这类请求不应按普通问答展示中间规划文本；后端会静默收流，并在 query 成功但未 compose 时触发 `model.required_tool_missing -> model.required_tool_repaired`。

`model.required_tool_repair_failed.payload.error_message` 也保持字符串兼容但有界：短错误原样返回，超过 `AGENT_ERROR_MESSAGE_MAX_CHARS=512` 时用 `agent_error_message_summary_v1`、`agent_error_message_truncated`、原始长度、hash 和 `full_error_reference=AgentConversationRunner.model.required_tool_repair_failed` 表达。前端 timeline 可展示该摘要，但不应假设能从事件里拿到完整解析异常正文。

当任意成功 ToolCall 的输出包含 `warnings`、`issues`、`diagnostics`、`errors` 或 `valid=false` 时，后端会通过 `ToolResultPolicy` 在工具结果回灌消息中加入通用工具结果质量闭环规则；按工具推荐的修复路径来自对应 `ToolSpec` 的后端私有 `tool_result_repair_guidance`，而不是策略类里的工具名分支，且该字段不进入 `ToolSpec.to_json()`、模型初始工具清单或前端契约。`ToolResultPolicy` 回灌给模型的整条消息必须有硬上限；小输出保持 `output` 原结构，大输出改为 `output_preview` 摘要并标记 `output_truncated=true`，完整脱敏结构仍以 `AgentToolCallRead.output_json_redacted` 为准。多条工具结果进入后续模型调用或审批恢复 final summary 前还会受 `AGENT_TOOL_RESULT_CONTEXT_TOTAL_MAX_CHARS` 聚合预算保护，超出部分以 `agent_tool_result_context_truncated` 标记截断；前端应继续通过 ToolCall Detail、run summary 或报告详情读取完整结构。模型应先把问题分为可自动修复项、需要用户输入/外部配置的阻断项和待继续判断项：硬编码业务字段、未动态绑定、提取器路径、断言 expected、数据集变量、schema/type/format 校验等可修复项应触发下一次安全工具调用，例如复用 `ai_skill.run_draft` 的 `input.extra_requirements`、再次 `testcase.validate_schema` 或重新 `scenario.compose_draft`；鉴权令牌、账号密码、密钥、审批或没有平台来源的私有输入才作为阻断项交给用户。如果 ToolCall 本身失败，但错误属于输入、schema、validation、草稿结构或字段格式问题，后端同样会在工具结果回灌中加入失败修复闭环，要求模型修正参数并重试安全工具，而不是直接把 Pydantic/schema 错误交给用户。前端可能看到同一个 run 中连续多个同类 ToolCall，这是正常的修复闭环，不应当成重复提交错误；但如果同一工具连续两次以相同 `error_code` 与 `error_message` 失败，后端会绑定 stop 用 decision ContextBuild 并写入 `loop.observed`，RootCause 为 `RC_NO_PROGRESS_PURE`、`next_action=stop`、`observation_json.source=tool_result_no_progress_guard`，随后写入 `run.failed(error_code=agent_repair_no_progress)`，前端应结束 pending assistant 气泡并在 timeline/Runbook 展示该 repair no-progress 状态。工具结果后的最终用户回复默认受预算约束：只总结已完成、已自动修复/验证、剩余阻断项和下一步；完整步骤、草稿结构、原始 warning 和长 JSON 以 ToolCall 详情、run summary 或报告详情为准，前端不应依赖 assistant 气泡承载全部结构化细节。

如果模型输出的工具请求格式不合法，后端会写入 `model.tool_request_invalid`，并绑定修复用 decision ContextBuild 写入 `loop.observed`，RootCause 为 `RC_TOOL_REQUEST_FORMAT_INVALID`、`next_action=repair`，`observation_json` 记录 `model_call_id`、错误摘要和内容预览；若工具 JSON 只是缺少尾部闭合括号，或把 `reason/evidence_refs` 误嵌进 `input` envelope，后端会优先用本地确定性 salvage 修正并继续 ToolCall 生命周期。只有本地无法修正时，后端才让模型进行一次格式修复；该修复调用使用修复专用 system prompt、`AGENT_REPAIR_CONTEXT_MAX_CHARS` 内的上一轮模型输出片段和有界错误摘要，不继承完整历史 messages，也不重新注入大 ToolResult。超长非法 JSON 或混合自然语言会以 `agent_repair_context_truncated` 标记截断；`model.tool_request_invalid.content_preview` 仍只是审计预览，不代表完整修复上下文。`model.tool_request_invalid.payload.error_message`、对应 LoopObservation 的 `observation_json.error_message`、修复 prompt 内的错误摘要，以及 `model.tool_request_repair_failed.payload.error_message` 都保持字符串兼容但有界：短错误原样返回，超过 `AGENT_ERROR_MESSAGE_MAX_CHARS=512` 时用 `agent_error_message_summary_v1`、`agent_error_message_truncated`、原始长度、hash 和 `full_error_reference` 表达，避免 timeline 或 repair prompt 复制完整解析异常尾部。工具请求解析会在 envelope 边界归一化模型常见的 `evidence_refs` 简写：单个对象转为对象列表，`agent-tool-*` / `tool-call:*` / `tool_call:*` 字符串转为 audit-only `tool_call` evidence ref，无法识别的字符串会丢弃；这只影响审计证据，不放宽 `input` schema、业务 Pydantic schema 或 `ObjectReferenceGuard`。修复模型返回后，后端会在解析 repaired 内容和写入 `model.tool_request_repaired/model.tool_request_repair_failed` 前再次检查 terminal；如果 Stop 已生效，保留 `run.cancelled`，不再创建 ToolCall。修复成功写入 `model.tool_request_repaired` 后继续进入 `model.tool_request_detected` 和 ToolCall 生命周期；若 repaired 内容混入自然语言但包含单个合法工具块，仍按成功修复处理并带 `repair_strategy=salvaged_repair_fenced_tool_request`。修复失败写入 `model.tool_request_repair_failed`，run 会进入 failed。前端可把这些事件展示为审计状态，不渲染为 assistant 气泡。

当用户疑似要求保存、持久化、发布或创建正式场景，但当前 ToolRegistry 没有 `scenario.save/create/persist` 类工具时，后端不会仅凭关键词短路，而是由 `scenario-composition/SKILL.md` 的后端私有 `guard_unsupported_capability` 规则声明预检查关键词、缺失工具集合、分类 prompt、分类 JSON 字段、最终消息资源和 `completion_source`。Runner 只解释这条 Skill 规则：先用结构化意图分类判断用户是否真的要求把场景持久化为正式实体，分类 prompt 和最终 guard 回复都来自 Skill 私有资源文件，不写在 Runner 主 prompt 或 Python 消息常量中。只有分类结果为需要正式保存且 run 仍未进入 terminal 时，才会用 `unsupported_scenario_save_guard` 直接完成 run，说明当前只能生成草稿或 dry-run，不能假装已保存，也不会重新调用 `scenario.compose_draft` 冒充保存结果；如果用户在分类期间 Stop，后端以 `run.cancelled` 为准，不再写 guard 合成回复。若用户明确说“不要保存”“不保存”“仅生成草稿”等，run 仍应进入正常 query-first 场景组合链路。前端按普通 assistant 回复展示 guard 结果即可。

对话型 run 在调用模型前会用 `normal_plan_v1` 检索项目 Memory，并以 `conversation_context` 注入模型上下文；注入给模型的 Memory 系统消息会对 title/content 做字段级截断，并受 `AGENT_MEMORY_CONTEXT_MESSAGE_MAX_CHARS` 总硬上限保护，超长内容只以 `agent_memory_context_truncated` 标记出现。命中时事件流会出现 `memory.context_injected`，payload 包含 `profile_name`、`usage_role`、`active_for_policy=false`、`memory_ids`、`memory_versions` 和 `count`；该事件是审计/时间线提示，不承载完整 Memory 正文，也不渲染为 assistant 气泡；详情可用 `GET /agents/memory-usage-events?run_id={run_id}` 查询。

`run.completed.result.message` 是刷新后校准最终回复的权威字段；有工具调用时，`run.completed.result.tool_calls` 会包含本次 run 内模型驱动 ToolCall 的摘要，其中可能包含被 harness guard 阻断的失败 ToolCall，前端应按 `status/error_code` 区分纠正过程和最终结果。

### 3.3 Runtime Snapshot

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/runtime-snapshots/{snapshot_id}` | 查看冻结运行时契约、工具目录和策略 |

`AgentRuntimeSnapshotRead` 字段：

```text
item_id,snapshot_id,project_id,created_by,runtime_hash,tool_registry_hash,manifest_bundle_hash,prompt_bundle_hash,policy_version_hash,tools_json,manifests_json,adapters_json,policies_json,created_at
```

`AgentRuntimeSnapshotRead.item_id=agent-runtime-snapshot://{snapshot_id}` 由冻结运行时事实派生，表示一次 runtime/tool/manifest/policy snapshot 本身的 Codex-style timeline/debug/download item。它不替代 `snapshot_id`，也不改变 `AgentRunRead.runtime_snapshot_id`、ToolCall `runtime_snapshot_id` 或 Approval CAS 中 `runtime_snapshot_id` 的业务引用语义；前端可用 `item_id` 做调试面板定位和导出包稳定 key。

后端会稳定构建 Agent 系统提示中的 ToolRegistry 清单：工具按名称排序，工具 JSON 使用固定字段排序和紧凑分隔符序列化。这样同一 runtime hash 下的多轮请求尽量保持系统提示/工具清单前缀一致，便于模型服务侧复用 prompt/cache；前端只消费 snapshot/hash 和事件流，不需要自行重排工具清单。

模型初始工具提示不是完整 capabilities manifest。`_conversation_system_prompt()` 只给模型注入 `approval_required,input_summary,name,side_effect_class,summary` 五个精简字段，来源是 `ToolRegistry.list_specs()`，序列化规则是稳定 key 排序和紧凑分隔符。`input_summary` 只包含顶层 `required`、`properties` 和少量 enum 值，用于让模型选择工具和填关键入参；完整 `input_schema`、`version,replay_policy,required_permissions,output_schema,backend_contract,schema_hash,manifest_hash` 仍留在 capabilities/runtime snapshot/ToolCall 诊断接口中；`backend_handler`、前置工具和修复 guidance 等后端私有字段不进入模型初始 prompt。

`tools_json` 必须来自创建 run 时冻结的 `ToolRegistry.registry_json()`，工具字段与 capabilities 的 `tools[]` 公开字段一致：`name,version,summary,side_effect_class,replay_policy,required_permissions,input_schema,output_schema,backend_contract,schema_hash,manifest_hash`。`manifests_json.tools` 是同一数组按 `name` keyed 的映射；`runtime_hash`、`tool_registry_hash` 与 `manifest_bundle_hash` 分别来自 `ToolRegistry.runtime_hash()`、`ToolRegistry.registry_hash()` 与 `ToolRegistry.manifest_bundle_hash()`。后端私有字段 `backend_handler`、`required_context_requirements`、`missing_prerequisite_error_code`、`missing_prerequisite_next_action` 与 `tool_result_repair_guidance` 不进入 RuntimeSnapshot 工具 manifest；前端如需解释执行入口，应读取 ToolCall/Runbook 的白名单 dispatch trace，而不是从 snapshot 推断私有 handler。

### 3.4 ToolCall

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/tool-calls/{tool_call_id}` | 查看工具输入、输出、审批、reconcile 信息 |
| `POST` | `/agents/tool-calls/{tool_call_id}/approve` | 审批工具调用 |
| `POST` | `/agents/tool-calls/{tool_call_id}/reject` | 拒绝工具调用 |

`AgentToolCallRead` 字段：

```text
item_id,tool_call_id,run_id,step_index,attempt_index,runtime_snapshot_id,tool_name,tool_version,schema_hash,manifest_hash,idempotency_scope,idempotency_key,base_side_effect_class,resolved_side_effect_class,base_replay_policy,resolved_replay_policy,policy_reason_json,status,execution_phase,effect_submission_state,input_hash,input_json_redacted,evidence_refs_json,policy_evidence_refs_json,audit_evidence_refs_json,evidence_mutability_summary_json,decision_context_build_id,output_hash,output_json_redacted,required_permissions_json,permission_snapshot_json,approval_required,approval_scope_hash,approval_lineage_id,approval_epoch,approved_approval_id,approved_by,approved_at,backend_name,backend_operation,backend_contract_version,backend_request_schema_hash,backend_output_schema_hash,reconcile_contract_version,result_adapter_version,backend_effect_capability,recovery_decision,error_code,error_message,current_approval,approval_lineage,recent_reconcile_attempts,created_at,updated_at
```

`recent_reconcile_attempts[]` 使用 `AgentReconcileAttemptRead` 字段：

```text
item_id,attempt_seq,backend_name,backend_operation,backend_contract_version,result_status,raw_result_object_key,error_code,error_message,next_retry_at,created_at
```

`AgentReconcileAttemptRead.item_id=agent-reconcile-attempt://{tool_call_id}/{attempt_seq}` 由对账尝试事实派生，用于在 ToolCall Detail、Runbook 或调试包中定位单次 reconcile/backoff 诊断项。它不替代父级 `tool_call_id`，也不新增数据库字段。

`POST /agents/runs/{run_id}/reconcile` 返回的 `skipped_backoff_tool_calls[]` 同样暴露稳定 item identity：字段为 `item_id,tool_call_id,next_retry_at,attempt_seq,result_status`，其中 `item_id=agent-reconcile-skipped-backoff://{tool_call_id}/{attempt_seq}`。该字段由当前 backoff 对应的 ToolCall id 和最新 reconcile attempt 序号派生，不新增数据库列，不替代 `tool_call_id`、`attempt_seq`、`next_retry_at` 或 backoff 判定；前端可用它定位本次 reconcile summary 中被节流跳过的行，但不要据此改变 retry 窗口。

`report.read_summary` 是只读 ToolCall。输入支持 `project_id`、可选 `source_type`（`plan` 或 `flow`）、`status`、`environment_id` 和 `page_size`（1-20）；`output_json_redacted` 包含 `filters`、`report_count`、`returned_report_count`、`status_counts`、`returned_case_totals`、`latest_reports` 和最多 3 条 `failure_reports`。前端仍应把它当作通用 ToolCall 详情输出，不新增独立 report-summary API 事实源。

`policy_reason_json.policy_context` 是 ToolPolicyResolver 对本次 ToolCall 的冻结策略 envelope：包含 `policy_version_hash`、tool name/version、base/resolved side effect、base/resolved replay policy、`approval_policy`、`approval_required`、`approval_required_reason`、active/volatile/frozen policy evidence 计数、`mixed_volatile_frozen` 与 `policy_hash`。前端可在 ToolCall 诊断面板展示该摘要，用于解释为什么 replay policy 被提升为 `require_revalidation`、为什么需要审批或为什么被视为安全工具；不要把它当作新的业务输入，也不要从中反推未脱敏 evidence 内容。

`policy_reason_json.dispatch_trace` 是 ToolExecutor 在工具已分派到后端 routing/runtime 路径后写入的工具调度摘要：包含 `dispatch_trace_version_hash`、tool/run/runtime snapshot 标识、tool name/version、`schema_hash`、`manifest_hash`、router/runtime 名称、`backend_handler`、backend contract 标识、resolved side effect/replay policy、最终 status/effect submission state 与 `dispatch_trace_hash`。它用于解释 ToolCall 如何从 ToolSpec/Router/Runtime 进入具体后端 handler；不包含原始 input/output、evidence 或未脱敏业务 payload。若后端 effect 已提交但写 `tool.effect_committed` 或 `tool.completed` EventStore 事件失败，ToolCall 会进入 `uncertain(eventstore_write_failed_after_effect)`，此时 dispatch trace 必须重新反映最终 `status=uncertain` 与 `effect_submission_state=effect_committed`，Runbook/前端不得把旧的 `status=succeeded` trace 当作恢复状态。

`policy_reason_json.execution_context` 是 ToolExecutor 在 ToolCall 成功、失败、manual intervention 或 uncertain recovery 终态写入的执行上下文 envelope：包含 `execution_context_version_hash`、tool/run/runtime snapshot 标识、worker id、`tool_status`、execution/effect state、backend contract/version/schema hash、backend effect capability、resolved side effect/replay policy、approval lineage/epoch/approved approval、input/output hash、`recovery_decision`、`error_code`、`error_message_hash` 与 `execution_context_hash`。前端可把它作为 ToolCall Detail 的执行诊断摘要，用于解释本次执行基于哪个审批 lineage、哪个后端契约、哪个效果提交状态以及哪个恢复动作；不要把它当作可重放输入，也不要展示或推断原始 input/output/evidence/error message 内容。Runbook 诊断中的 `tool_call_uncertain` 与 `backend_capability_degraded` recommendation 会在 `details.execution_context` 中附带该 envelope 的白名单摘要，并在 `details.dispatch_trace` 中附带 dispatch trace 白名单摘要，便于 Runbook 面板直接展示执行 hash、worker、状态、效果提交状态、后端能力、恢复动作、错误 hash、router/runtime/backend handler、schema/manifest hash 和调度状态；这些摘要同样不会包含原始 input/output/evidence/error message 或未脱敏业务 payload。

`AgentToolCall.error_message` and `tool.failed.payload.error_message` remain string fields. Short backend/tool errors are returned as-is; backend execution failures or post-effect EventStore failures longer than `AGENT_ERROR_MESSAGE_MAX_CHARS=512` are summarized in-place with `agent_error_message_summary_v1`, `agent_error_message_truncated`, original size, hash, and `full_error_reference`. `execution_context.error_message_hash` hashes this bounded string, not the full backend exception.

Approval decision 请求必须携带 CAS 字段：

```text
input_hash,runtime_snapshot_id,resource_scope_hash,approval_lineage_id,approval_epoch,reason?
```

`POST /agents/tool-calls/{tool_call_id}/approve` 与 `/reject` 返回 `AgentApprovalDecisionRead`：

```text
approval,lineage,tool_call,mutation_log
```

其中 `approval` 表示本次审批记录。`AgentApprovalRead.item_id=agent-approval://{run_id}/{approval_id}` 从 approval 事实派生，定位本次审批记录自身；`tool_call_item_id=agent-tool-call://{run_id}/{tool_call_id}` 指向被审批的目标 ToolCall item。审批创建时如果后端调用方没有显式传入 `expires_at`，服务端默认写入创建时间后 30 分钟；前端审批卡的风险原因应优先展示 `approval_reason`，权限范围应使用 `required_permissions_json` 的可读列表。二者都只用于 timeline/debug/download 定位和审批说明展示，不新增数据库列，不改变审批 CAS 或状态机。

`lineage` 表示本次审批 lineage 的当前快照。`AgentApprovalLineageRead.item_id=agent-approval-lineage://{run_id}/{approval_lineage_id}` 从 lineage 事实派生，`tool_call_item_id=agent-tool-call://{run_id}/{tool_call_id}` 指向该 lineage 绑定的目标 ToolCall item；它们只用于 timeline/debug/download 定位，不新增数据库列，不改变审批 CAS、lineage epoch 或 mutation guard 状态机。

`mutation_log` 是本次 approve/reject 的审计 mutation。`AgentApprovalMutationLogRead.item_id=agent-approval-mutation://{run_id}/{mutation_log_db_id}` 从 mutation log 事实派生，`tool_call_item_id=agent-tool-call://{run_id}/{tool_call_id}` 指向目标 ToolCall item；它们只用于 timeline/debug/download 定位，不新增数据库列，不改变审批 CAS 或 mutation guard 状态机。前端展示审批结果时用 `approval.item_id` 定位审批记录，用 `lineage.item_id` 定位 lineage，用 `approval.tool_call_item_id`、`lineage.tool_call_item_id`、`tool_call.item_id` 和 `mutation_log.tool_call_item_id` 关联同一目标工具项，不要在前端自行拼接。

### 3.5 ContextBuild 和 LoopObservation

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/agents/runs/{run_id}/context-builds` | 创建上下文构建记录 |
| `GET` | `/agents/runs/{run_id}/context-builds` | 列出 run 的上下文构建 |
| `POST` | `/agents/runs/{run_id}/loop-observations` | 记录 loop 观察 |
| `GET` | `/agents/runs/{run_id}/loop-observations` | 列出 loop 观察 |

`AgentContextBuildRead` 字段：

```text
item_id,context_build_id,run_id,iteration,step_index,build_seq,build_purpose,model_name,token_budget,estimated_input_tokens,context_degradation_level,compressed_sections_json,omitted_evidence_refs_json,required_evidence_refs_json,required_evidence_complete,decision_quality_risk,prompt_object_key,prompt_hash,build_metadata_json,created_at
```

`AgentContextBuildRead.item_id=agent-context-build://{run_id}/{context_build_id}` 由 ContextBuild 事实派生，表示一次决策上下文构建本身的 Codex-style timeline/debug/download item。它不替代 `context_build_id` 业务标识，也不改变 `decision_context_build_id` 引用语义；LoopObservation、ToolCall 和相关诊断仍使用 `context_build_id` 串联决策上下文，前端可用 `item_id` 做 timeline 高亮、调试面板定位或导出包稳定 key。

`build_metadata_json` 会包含本次决策实际命中的 Codex-style Agent Skill 摘要、冻结运行时摘要与权限上下文摘要：`selected_agent_skills` 仅暴露 Skill `name` 与 `skill_hash`，`matched_agent_skill_routing_rules` 仅暴露匹配到的 routing rule 摘要（如 `routing_required_tool_after_success` 的 `after_tool` / `required_tool` / `rule_hash`），`runtime_snapshot` 仅暴露 `snapshot_id`、runtime/tool registry/manifest/prompt/policy hash、`available_tool_names` 与 `tool_count`，`permission_context` 仅暴露 `actor_user_id`、`project_id`、`access_level`、`project_access`、`implicit_all_project_permissions`、`explicit_permission_codes`、`explicit_permission_count` 与 `permission_hash`。这些字段用于解释 required-tool 修复、工具前置阻断、权限相关停止决策为何发生，并确认当时可用工具/策略/权限版本；不暴露私有 frontmatter 原文、Skill 正文、私有 prompt 资源、完整工具 schema、用户资料或完整授权表。两份 Harness 文档的 `Required ContextBuild metadata contract` 机器契约固定 metadata key 顺序、Skill/routing/runtime/permission 字段清单和私有字段排除边界；前端可在诊断面板展示这些字段，但不要把它渲染为 assistant 气泡。

当 ContextBuild 因预算压缩进入 degraded 状态时，`compressed_sections_json` 会暴露 redaction-safe 的 context window 诊断结构，包括 `budget_scope`、`estimated_input_units`、`budget_limit_units`、`units_until_budget`、`budget_limit_reached`、`degradation`、保留/省略 evidence ref 数量和 `required_evidence_complete`；同步写出的 `context.degraded.payload.context_window` 使用同一结构。该结构对齐 openai/codex `ContextWindowTokenStatus` 的预算可观测性，但仍属于 timeline/诊断信息，不应渲染为 assistant 气泡，也不替代 ToolCall 或 run summary 的完整详情。

`AgentLoopObservationRead` 字段：

```text
item_id,observation_id,run_id,iteration,step_index,decision_context_build_id,decision_context_degradation_level,iteration_context_degradation_max,required_evidence_complete_for_decision,omitted_required_evidence_refs_json,next_action,next_action_is_high_risk,stop_action_reason,stop_reasons_all_json,root_cause_primary,root_cause_rule_id,causal_chain_json,mitigation_action,observation_json,created_at
```

`AgentLoopObservationRead.item_id=agent-loop-observation://{run_id}/{observation_id}` 由 LoopObservation 事实派生，表示一次 loop 观察/修复/停止决策本身的 Codex-style timeline/debug/download item。它不替代 `observation_id`，也不改变 `decision_context_build_id` 指向 ContextBuild 的语义；前端可用 `item_id` 做 loop 诊断详情、高亮和导出包稳定 key，仍用 `observation_id` 调用业务 hydrate/诊断接口。

### 3.6 Approvals 和 Migration Blocks

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/runs/{run_id}/approvals` | 查询 run 审批列表 |
| `GET` | `/agents/runs/{run_id}/migration-blocks` | 查询 migration blocks |
| `POST` | `/agents/runs/{run_id}/migration-blocks/{block_id}/resolve` | 解决 migration block |
| `GET` | `/agents/approvals/expire-audit` | 审批过期审计 |
| `POST` | `/agents/approvals/expire` | 审批过期处理 |

`POST /agents/runs/{run_id}/migration-blocks/{block_id}/resolve` 返回 `AgentMigrationBlockResolveRead`，其中 `checkpoint_freshness` 保留 Checkpoint Freshness Gate 的原始 `result/action/reason`。如果被解决的是 terminal run 上的 migration block，`checkpoint_freshness` 还必须包含 `terminal_run_preserved=true`、`terminal_run_status`、`resolve_preserves_terminal_run=true`、`post_resolve_next_action` 和 `tool_call_status_after_resolve`；前端应优先使用这些 terminal-preserve 字段提示用户该操作不会把 run 恢复为 active。`post_resolve_next_action` 按当前 ToolCall 状态计算：仍处于 `needs_migration/uncertain/reconciling` 时为 `reconcile_run`，重复 resolve 且 ToolCall 已经收敛到 `succeeded/failed/manual_intervention/obsolete` 等非对账状态时为 `none`。

### 3.7 Memory

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/memories` | memory 列表 |
| `POST` | `/agents/memories` | 创建 memory |
| `PATCH` | `/agents/memories/{memory_id}` | 更新 memory |
| `POST` | `/agents/memories/{memory_id}/validate` | 验证 memory |
| `POST` | `/agents/memories/{memory_id}/reject` | 拒绝 memory |
| `POST` | `/agents/memories/retrieve` | 检索 memory |
| `GET` | `/agents/memory-source-profiles` | source profile catalog |
| `GET` | `/agents/memory-retrieval-profiles` | retrieval profile catalog |
| `GET` | `/agents/memory-usage-events` | usage events |
| `POST` | `/agents/memory-usage-events/{usage_event_id}/feedback` | memory feedback |
| `GET` | `/agents/memory-staleness-events` | staleness events |
| `GET` | `/agents/memory-validation-events` | validation events |
| `POST` | `/agents/memory-feedback/process` | admin feedback worker |

Agent 对话 runner 自动检索 Memory 时会写入 `AgentMemoryUsageEvent`：`usage_role=conversation_context`、`retrieval_profile=normal_plan_v1`、`active_for_policy=false`。前端 Memory tab 可按 run 查询这些 usage events，并允许用户对误导/过期/有用的记忆提交 feedback；usage event 是审计事实源，不能反推出模型收到的完整 Memory 正文，因为模型侧上下文可能已按硬上限截断。

Memory audit event 也暴露稳定 item identity：`AgentMemoryUsageEventRead.item_id=agent-memory-usage-event://{id}`、`AgentMemoryStalenessEventRead.item_id=agent-memory-staleness-event://{id}`、`AgentMemoryValidationEventRead.item_id=agent-memory-validation-event://{id}`。这些字段都由现有审计事件 DB id 派生，不新增数据库列，不替代 `id`、`memory_id`、`run_id` 或 EvidenceRef 过滤字段；前端可把它们作为 Memory 审计列表、调试面板和导出包的稳定 key，不要自行拼接。

Memory feedback process 的 `results[]` 也暴露稳定 item identity：字段前缀为 `item_id,usage_event_id,processed,decision`，其中 `item_id=agent-memory-feedback-result://{usage_event_id}`。该字段由 usage event id 派生，不新增数据库列，不替代 `usage_event_id`、feedback state、Memory 置信度/陈旧度更新或 validation/contradiction 记录；`POST /agents/memory-usage-events/{usage_event_id}/feedback` 与 admin `POST /agents/memory-feedback/process` 返回同一结果行形态，前端和调试面板不要自行拼接。

### 3.8 Dashboard、Runbook 和上线门禁

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/dashboard` | readiness dashboard |
| `GET` | `/agents/launch-audit` | frontend integration and launch readiness audit |
| `GET` | `/agents/backend-completion-audit` | backend-owned Agent feature completion audit |
| `GET` | `/agents/metrics` | metrics snapshot |
| `GET` | `/agents/alerts` | alerts snapshot |
| `GET` | `/agents/runbooks` | runbook catalog |
| `GET` | `/agents/runs/{run_id}/runbook` | run diagnosis |
| `GET` | `/agents/release-gates` | release gate snapshot |
| `GET` | `/agents/release-gates/promotion` | promotion assessment |

Runbook catalog 和 run diagnosis payload 也暴露稳定 item identity：`AgentRunbookRead` 字段为 `item_id,runbook_id,title,trigger,severity,steps,safe_api_actions`，其中 `item_id=agent-runbook://{runbook_id}`；`AgentRunbookRecommendationRead` 字段为 `item_id,runbook_id,reason,severity,action,tool_call_id,details`，其中 `item_id=agent-runbook-recommendation://{run_id}/{runbook_id}/{stable_digest}`。recommendation digest 只由公开且稳定的推荐身份字段派生，不新增数据库列，不替代 `runbook_id`、`tool_call_id` 或 `action`，前端应把它作为 Runbook 面板、timeline/debug/download item 的稳定 key，不要自行拼接。

Alert snapshot 中每条 `AgentAlertRead` 也暴露稳定 item identity：字段为 `item_id,alert_id,severity,status,metric_key,observed_value,threshold,summary,action,runbook_id,details`，其中 `item_id=agent-alert://{alert_id}`。该字段由告警规则或动态告警的稳定 `alert_id` 派生，不新增数据库列，不替代 `alert_id`、`metric_key` 或 `runbook_id`；`/agents/alerts` 和 dashboard 嵌套 `alerts[]` 使用同一值，前端可用它作为监控告警列表、上线门禁阻断项、timeline/debug/download item 的稳定 key。

Release gate snapshot 的重复项也暴露稳定 item identity：`AgentReleaseGateToolRead.item_id=agent-release-gate-tool://{tool_name}/{tool_version}`，`AgentReleaseGateLevelRead.item_id=agent-release-gate-level://{level}`，`AgentReleaseGateViolationRead.item_id=agent-release-gate-violation://{tool_name}/{reason}`。这些字段都由当前发布门禁快照中的公开稳定事实派生，不新增数据库列，不替代 `tool_name`、`tool_version`、`level`、`reason` 或 rollout decision；`/agents/release-gates`、dashboard 嵌套 release gate、promotion assessment 的 `release_gate` 摘要都使用同一派生结构，前端不要自行拼接。

Release gate snapshot 的 `minimum_go_live.checks[]` 也暴露稳定 item identity：字段为 `item_id,requirement_id,label,status,details`，其中 `item_id=agent-minimum-go-live-check://{requirement_id}`。该字段由 minimum go-live requirement id 派生，不新增数据库列，不替代 `requirement_id`、`status` 或 go-live/promotion 判定；`/agents/release-gates`、dashboard 嵌套 release gate、promotion assessment 的 `release_gate.minimum_go_live` 使用同一派生结构，前端可用它作为上线前最低要求 check 列表和导出包 item key。

Release gate snapshot 的 `go_live_gates.tiers[].checks[]` 也暴露稳定 item identity：字段为 `item_id,gate_id,label,status,evidence`，其中 `item_id=agent-go-live-gate-check://{priority}/{gate_id}`。该字段由 go-live priority 和 gate id 派生，不新增数据库列，不替代 `priority`、`gate_id`、`status` 或 go-live/promotion 判定；`/agents/release-gates`、dashboard 嵌套 release gate、promotion assessment 的 `release_gate.go_live_gates` 使用同一派生结构，前端可用它作为上线门禁分层 check 列表和导出包 item key。

Release gate snapshot 的 `final_delivery.categories[]` 与嵌套 `checks[]` 也暴露稳定 item identity：category 字段为 `item_id,category,external_scope,required_artifact_ids,delivered_artifact_ids,external_scope_artifact_ids,missing_artifact_ids,checks,pass`，`item_id=agent-final-delivery-category://{category}`；check 字段为 `item_id,artifact_id,label,status,evidence`，`item_id=agent-final-delivery-check://{category}/{artifact_id}`。这些字段由 final delivery category 和 artifact id 派生，不新增数据库列，不替代 `category`、`artifact_id`、`status` 或 final delivery/promotion 判定；`/agents/release-gates`、dashboard 嵌套 release gate、promotion assessment 的 `release_gate.final_delivery` 使用同一派生结构。

Promotion assessment 的 `blockers[]` 也暴露稳定 item identity：字段为 `item_id,source,reason,severity,details`，其中 `item_id=agent-promotion-blocker://{target_level}/{source}/{reason}`。该字段由阻断目标级别、阻断来源和阻断原因派生，不新增数据库列，不替代 `source`、`reason`、`severity`、`details.target_level` 或 promotion decision；`/agents/release-gates/promotion` 与 dashboard 嵌套 promotion assessment 使用同一派生结构，前端可用它作为晋级阻断列表、上线门禁调试面板和导出包 item key。

Promotion assessment 的 `checks[]` 也暴露稳定 item identity：字段为 `item_id,name,status,details`，其中 `item_id=agent-promotion-check://{target_level}/{name}`。该字段由目标级别和 check name 派生，不新增数据库列，不替代 `name`、`status`、`details.target_level` 或 promotion decision；这些 check row 独立于 `AgentDashboardCheckRead` / dashboard `checks[]`，前端可用它作为晋级评估 check 列表、上线门禁调试面板和导出包 item key。

Readiness dashboard、launch audit 与 backend completion audit 复用的 `AgentDashboardCheckRead` 也暴露稳定 item identity：字段为 `item_id,name,status,severity,summary,details`，其中 `item_id=agent-dashboard-check://{name}`。该字段由公开 check name 派生，不新增数据库列，不替代 `name`、`status`、`severity` 或 readiness/audit 判定；`/agents/dashboard`、`/agents/launch-audit`、`/agents/backend-completion-audit` 的 `checks[]` 使用同一派生结构，前端可用它作为 dashboard/audit check 列表、timeline/debug/download item 的稳定 key。Promotion assessment 内部的自由形态 `checks` 仍按各自摘要合同处理，不纳入本字段。

`GET /agents/metrics` 与 dashboard 的 `metrics` 字段会暴露 Runtime 修复/停止类 LoopObservation 聚合指标，包括 `tool_prerequisite_missing_total`、`tool_request_format_invalid_total`、`required_tool_followup_missing_total`、`max_iterations_total` 与 `same_failure_no_progress_total`。Phase 0 Agent 基线指标也会在同一 `metrics` 字段中输出：`agent_task_success_rate`、`agent_avg_iterations`、`agent_avg_tokens`、`agent_avg_tool_calls`、`agent_context_avg_chars`、`agent_context_max_chars`、`agent_context_avg_system_chars`、`agent_context_avg_tool_result_chars`、`agent_context_growth_rate`、`agent_repair_rate`、`agent_tool_retry_total`、`agent_tool_schema_error_total` 与 `agent_tool_request_repair_success_total`。这些指标来自 `model.started.payload.context_metrics(agent_model_context_metrics_v1)`、ToolCall ledger 和 repair events，其中模型输入估算字段使用 `estimated_input_units`，避免通用脱敏层把 token 字段遮蔽。指标用于工作台健康度、Runbook/运营排查、Phase 1/2/4 优化收益对比和趋势展示，不代表新的 assistant 消息；`metrics_catalog_complete.details.required_metric_keys` 会同时包含这些 key，前端可用该 check 判断后端是否漏导出指标。

Agent 观测接口保持响应 shape 稳定，但后端会在单次 dashboard / promotion 计算链路中复用同一份 metrics 与 release gate snapshot：`/agents/dashboard` 嵌套的 alerts 不会重新触发完整 metrics 聚合，`/agents/release-gates/promotion` 也会把已计算的 release gate 传入 dashboard。`event_replay_gap_total` 继续表示不可完整重放的 run 数量，但由数据库聚合判断事件序列完整性；event replay stress audit 继续返回同一 payload，只在服务端批量读取抽样 run 的 events 后复用，避免按 cursor 重复查询。实时 metrics 路径只读取 ToolCall、LoopObservation、AgentEvent 等表的必要窄列或 count-only 聚合，并依赖 `0030_agent_observability_indexes` / `0031_agent_approval_expire_index` 中的观测索引；前端字段和判定语义不变。

`GET /agents/runs/{run_id}/runbook` 会把上述 Runtime 修复/停止类 LoopObservation 归入 `agent_runtime_loop_repair` recommendation。前端可在 Runbook 面板展示 `details.stop_action_reason`、`details.root_cause_rule_id`、`details.mitigation_action` 和 `details.observation_id`，并把 `action=GET /api/v1/agents/runs/{run_id}/loop-observations` 作为跳转到 loop 诊断详情的安全入口；这类 recommendation 是运维/调试建议，不应渲染成 assistant 气泡。对于需要从 ToolCall 恢复的 `tool_call_uncertain` 和 `backend_capability_degraded`，前端可优先展示 `details.execution_context` 与 `details.dispatch_trace` 的白名单摘要，再通过 `tool_call_id` 打开完整 ToolCall Detail。对于 terminal run 上的 migration block，`migration_blocked` recommendation 会使用 `reason=open_migration_block_on_terminal_run`，并在 details 中输出 `run_status`、`run_terminal=true`、`resolve_preserves_terminal_run=true`、`post_resolve_next_action=reconcile_run` 与 `tool_call_status_after_resolve=reconciling`，前端应提示 resolve block 不会恢复该 run，只会让 ToolCall 回到 reconcile 流程；对应 resolve response 的 `checkpoint_freshness` 也会输出同源 terminal-preserve 字段，并按 ToolCall 当前状态计算 `post_resolve_next_action`，避免调用方只看到 `action=continue_from_checkpoint` 而误触发 resume 或重复提示已经过期的 reconcile。

对于 `approval_conflict_event_seen` 与 `memory_bypassed_evidence_ref_event_seen` 这类事件型 Runbook recommendation，`details` 只携带 `runbook_event_payload_summary_v1` 摘要：`event_id`、`event_seq`、`payload_keys`、有界 `payload_preview`、`payload_truncated`、`payload_size_chars`、`payload_hash` 和 `full_payload_reference=AgentEvent.payload_json`。前端可展示 keys、hash 和预览定位原始事件；不要把该摘要当成完整 payload，也不要依赖 Runbook API 承载长 transcript、Memory snapshot 或其他原始业务数据。

`GET /agents/launch-audit?project_id=...` 返回 `AgentLaunchAuditRead`，用于前端进入 Agent 工作台前判断后端是否已经具备可联调状态。该接口不触发 live DeepSeek 调用，不暴露 API key；`project_id` 作用域下项目成员可读，不传 `project_id` 时仅 admin 可读全局审计。

字段：
```text
project_id,generated_at,ready,status,checks,model_health,dashboard,promotion,derived_from
```

固定 checks：
```text
model_provider_configured,normal_conversation_runtime_available,frontend_event_contract_available,dashboard_readiness_not_blocked,backend_repository_delivery_complete,frontend_external_scope_declared,promotion_assessment_available
```

前端约定：`ready=true` 表示后端拥有的 Agent 对话链路、SSE/snapshot/summary/actions/history/export 契约和 dashboard/release gate 输入已经可供前端联调；它不表示 L3 生产灰度已放开，`promotion.decision` 仍可能因发布策略保持 `blocked`。

`GET /agents/backend-completion-audit?project_id=...` 返回 `AgentBackendCompletionAuditRead`，用于回答“后端仓库拥有的 Codex 风格 Agent 功能是否已经开发完成”。该接口同样不触发 live DeepSeek 调用，不暴露 API key；`project_id` 作用域下项目成员可读，不传 `project_id` 时仅 admin 可读全局审计。它把对话流式生成、服务端历史、工具循环、审批恢复、Memory 注入、前端契约、观测门禁、文档同步、真实 E2E 诊断路径和多用例行为评测套件汇总为固定 checks。

字段：
```text
project_id,generated_at,complete,status,checks,backend_scope,launch_audit,runtime_contracts,diagnostics,derived_from
```

固定 checks：
```text
model_provider_configured,conversation_runner_streaming,server_side_conversation_history,tool_loop_and_approval_resume,memory_context_injection,frontend_contract_surface,observability_and_release_gate,backend_delivery_docs_synced,live_e2e_diagnostic_available,behavior_evaluation_suite_available
```

`runtime_contracts` 除基础 run/events/snapshot/summary/actions/history/transcript/export 入口外，还固定声明 `tool_execution_context=AgentToolCall.policy_reason_json.execution_context`、`tool_dispatch_trace=AgentToolCall.policy_reason_json.dispatch_trace`、`runbook_execution_context_summary=AgentRunbookRecommendation.details.execution_context`、`runbook_execution_context_summary_fields`、`runbook_dispatch_trace_summary=AgentRunbookRecommendation.details.dispatch_trace` 与 `runbook_dispatch_trace_summary_fields` 白名单；`diagnostics` 除 model health、launch/completion audit、conversation smoke 和 E2E 脚本外，还固定提供 `tool_call_detail=GET /api/v1/agents/tool-calls/{tool_call_id}`、`runbook_diagnosis=GET /api/v1/agents/runs/{run_id}/runbook`、`behavior_evaluation_script=scripts/agent_behavior_evaluation.py` 与 `behavior_evaluation_reports=reports/woagent_behavior_eval_*.json|md`。前端或交付验收可以先读 completion audit 判断这条执行诊断链和多用例行为评测套件是否属于后端完成边界，再跳转 ToolCall Detail/Runbook 或查看评测产物。

`behavior_evaluation_suite_available.details` 固定输出 `script`、`case_ids`、`case_count`、`assertions`、`assertion_coverage`、`undeclared_case_assertions`、`uncovered_assertion_ids`、`assertion_metadata_complete`、`model_call_trace_fields`、`markdown_sections`、`runbook`、`latest_report`、`output_prefix` 与 `artifacts`。当前 `case_ids` 由 `scripts.agent_behavior_evaluation.CASES` 派生为 T01..T08，`assertions` 由 `scripts.agent_behavior_evaluation.ASSERTIONS` 派生，包含 `tool_diagnostic_chain`、`model_call_trace` 与 `sse_high_cursor_replay` 等后端诊断链断言；`assertion_coverage` 由每个 `EvalCase.assertion_ids` 汇总为 declared assertion -> case ids 映射，且只保留 `ASSERTIONS` 中声明过的断言；`undeclared_case_assertions` 由 `scripts.agent_behavior_evaluation.undeclared_case_assertions()` 派生，用于暴露 case 上拼写错误或尚未登记到 `ASSERTIONS` 的断言，`uncovered_assertion_ids` 由 `scripts.agent_behavior_evaluation.uncovered_assertion_ids()` 派生，用于暴露已登记但无任何 case 覆盖的断言，`assertion_metadata_complete=false` 时该 check 会进入 attention，避免新增评测维度后 completion audit、脚本和前端验收面静默漂移。`tool_diagnostic_chain` 当前覆盖 T03/T04/T05/T07，要求工具型用例抓取每个成功返回的 ToolCall Detail，并在报告的每个 `tool_calls[].diagnostic_chain` 中看到 `execution_context_hash` 与 `dispatch_trace_hash` 等安全摘要，不复制完整 `policy_reason_json`、input/output/evidence 或 secrets；`tool_calls[].input_json_redacted` 在行为评测报告中是兼容旧字段名的 `agent_behavior_eval_tool_input_summary_v1` 输入摘要，只包含 input keys、布尔字段索引、有界 preview、截断状态、大小、hash 和 `full_input_reference=AgentToolCallRead.input_json_redacted`，用于保留 `include_datasets=true` 等评测信号而不复制完整工具输入。同一用例只要有任一成功抓取的 ToolCall 缺诊断摘要，latest report 就必须把该 case 计入 `missing_tool_diagnostic_chain_case_ids`。对应 Markdown 报告会在“工具诊断链摘要”中展示同一组安全 hash、router/runtime/backend handler、backend operation 与状态摘要，方便人工排查不用打开 JSON；Markdown 同样不得展示完整 `policy_reason_json` 或原始 payload。`model_call_trace` 覆盖 T01-T08，报告 JSON 的 `model_call_trace[]` 只按 `model_call_id` 白名单聚合 iteration、loop step、phase、started/completed、delta/retry/interrupted 计数、final_summary/repair_attempt 和模型 finish 摘要；`model_call_trace_fields` 由 `scripts.agent_behavior_evaluation.MODEL_CALL_TRACE_FIELDS` 派生，`markdown_sections` 由 `MARKDOWN_REPORT_SECTIONS` 派生并当前固定包含“模型调用链摘要”和“工具诊断链摘要”，用于让 completion audit 机器可读地声明报告字段/章节契约。Markdown 报告会在“模型调用链摘要”中展示同一安全摘要，方便人工排查 Plan/Act/Repair/Final 的模型调用链，不复制 prompt messages、delta content、错误明文、assistant transcript 或 secrets。`sse_high_cursor_replay` 覆盖 T01-T08，要求每个用例在超大 Last-Event-ID 重放下至少返回一个非 heartbeat 事件，latest report 只记录覆盖 case ids 和缺失 case ids，不复制事件正文或 preview。`runbook` 由 `scripts.agent_behavior_evaluation.behavior_evaluation_runbook()` 派生，包含安全运行命令、必需环境变量 `AGENT_EVAL_PASSWORD`、可选环境变量默认值和 `report_schema_version=agent_behavior_evaluation_report_v2`。`latest_report` 由 `scripts.agent_behavior_evaluation.latest_report_summary()` 派生，只读取最近 `reports/woagent_behavior_eval_*.json` 的白名单摘要，包括 historical 标记、JSON 路径、同名 Markdown 路径、`markdown_available`、`artifact_pair_complete`、schema 版本、`expected_report_schema_version`、`schema_matches_current`、summary 计数/平均分、`summary_counts_match_results`、`summary_average_score_matches_results`、通过/失败/无效 evaluation case ids、reported/expected/missing/extra/duplicate case ids、`current_case_set_complete`、`model_call_trace_case_ids`、`missing_model_call_trace_case_ids`、`model_call_trace_complete`、`tool_diagnostic_chain_case_ids`、`missing_tool_diagnostic_chain_case_ids`、`tool_diagnostic_chain_complete`、`sse_high_cursor_replay_case_ids`、`missing_sse_high_cursor_replay_case_ids` 与 `sse_high_cursor_replay_complete`；即使没有报告或报告 JSON 损坏，`available=false` 摘要也必须保留这些 artifact/schema/summary count/average score/evaluation/case set/model trace/tool diagnostic chain/SSE replay 状态字段，并以 `report_schema_version=null` 表示没有可读取的真实报告 schema，继续输出 `expected_report_schema_version=agent_behavior_evaluation_report_v2`、`schema_matches_current=false`、`summary_counts_match_results=false` 与 `summary_average_score_matches_results=false`，便于前端稳定展示旧报告、缺失报告、坏报告、summary 计数或平均分不一致的报告、evaluation 字段损坏的报告、重复 case 的报告、同 schema 但缺 model trace 证据的报告、缺 ToolCall 诊断链证据的报告、缺 SSE replay 证据的报告，或缺 Markdown companion 的报告。它不携带 `login_user`、assistant transcript、tool payload、model trace content、SSE event preview、Markdown 正文或密码值，也不因历史报告 artifact/schema/summary count/average score/evaluation/model trace/tool diagnostic chain/SSE replay 是否匹配而改变 audit `complete/status`。completion audit 不实时执行评测；真实执行仍由维护者显式设置环境变量、运行脚本并查看 `reports/woagent_behavior_eval_*.json|md`。

行为评测 JSON result 的 `assistant_message` 是报告预览字段，不是完整 assistant transcript：`scripts/agent_behavior_evaluation.py` 在 `run_case()` 中保留完整 `AgentRunSummary.assistant_message` 供 `evaluate_case()` 判分，但写入报告的 `assistant_message` 必须使用 `agent_behavior_eval_assistant_message_preview_v1` 有界 preview，并同时输出 `assistant_message_length`、`assistant_message_truncated` 与 `full_assistant_message_reference=AgentRunSummary.assistant_message`。前端或人工验收若需要完整回复，应通过 Run Summary/Transcript 权限边界读取，不应从行为评测 JSON/Markdown 产物恢复完整正文。

行为评测 JSON/Markdown/progress 中的异常文本同样是报告预览：`run_case()` 的 ToolCall Detail fetch error、SSE high-cursor replay error，以及 `main()` 捕获的单 case 异常，都必须通过 `agent_behavior_eval_error_summary_v1` 输出固定长度 `error`/`fetch_error` preview、`*_truncated`、原始长度、hash 与 `full_*_error_reference`。短错误可以保持原字符串；超长 HTTP body、traceback、provider 响应正文或异常尾部内容不得完整进入行为评测 artifact。

`scripts/agent_behavior_evaluation.py` 的 HTTP client 抛错也必须复用同一错误预览边界：`ApiClient.request_json()` 与 `request_sse_text()` 在 HTTPError/URLError 上抛出的 `RuntimeError` 应包含 `agent_behavior_eval_error_summary_v1` preview、截断状态、长度、hash 和 `full_error_reference`，不得把完整 HTTP body 或 provider 响应正文拼进异常字符串。

`behavior_evaluation_suite_available.details.latest_report_fields` 同样是固定输出字段，来源为 `scripts.agent_behavior_evaluation.LATEST_REPORT_SUMMARY_FIELDS`，用于声明 `latest_report` 核心白名单字段的有序契约。

`latest_report.summary_counts_match_results` 由 `summary.case_count`、`summary.passed_count`、`summary.failed_count` 与 `results` 派生计数对比得到；任一计数缺失、非整数、与结果行不一致，或任一 `results[].evaluation.passed` 不是布尔值时为 false，前端应把 summary 计数视为历史参考而非已校准事实。

`latest_report.summary_average_score_matches_results` 由 `summary.average_score` 与每条 `results[].evaluation.score` 派生平均分对比得到；任一分数字段缺失、非数值、非有限数值（`NaN`、`Infinity`、`-Infinity`），任一 result 不是对象，或在所有分数均为有限数值时与脚本生成规则 `round(sum(scores) / max(case_count, 1), 1)` 不一致时为 false，前端应把 summary 平均分视为历史参考而非已校准事实。

`latest_report.invalid_evaluation_case_ids` 会列出最近历史报告中 `evaluation.passed` 不是布尔值，或 `evaluation.score` 不是有限数值的 case id；该字段只暴露 case id，不复制原始 evaluation payload，前端可用它解释 summary 计数或平均分为何不能作为已校准事实。

行为评测脚本生成报告时同样使用强类型汇总：`report_summary_from_results()` 只有在 `evaluation.passed is True` 且 `evaluation.score` 是有限数值时才把结果计入 `passed_count`；畸形 evaluation 行不会让脚本崩溃，而是按失败写入 summary，非法 score（含 `NaN/Infinity`）按 0 参与生成端平均分，同时保留原始 result 供 `latest_report.invalid_evaluation_case_ids` 后续定位。

行为评测 JSON artifact 必须保持标准 JSON，而不是依赖 Python/JavaScript 对 `NaN`、`Infinity` 的宽松扩展：`write_json()` 写盘前会递归把 payload 内所有非有限浮点替换为 `<non-finite-number:nan|inf|-inf>` 字符串哨兵，并以 `allow_nan=false` 序列化。该替换只发生在 artifact 边界，用于保证前端、CI 和外部 JSON parser 可稳定读取；summary 派生仍以严格 `evaluation_score_value()` 为准，替换后的哨兵会继续让对应 case 出现在 `invalid_evaluation_case_ids` 中。

`latest_report_summary()` 读取历史 JSON artifact 时也必须按标准 JSON 处理：裸 `NaN`、`Infinity` 或 `-Infinity` 通过 `parse_constant` 被拒绝，并返回 `available=false` 的稳定摘要，`error=NonStandardJsonConstantError`。前端应把这类报告与语法损坏 JSON 一样展示为不可用历史报告，而不是把 Python 宽松解析后的结果当作可校准事实。

Markdown companion 与 progress log 也必须复用同一安全展示边界：`markdown_report()` 在渲染前对 payload 应用 `json_safe_value()`，`[done]` progress 记录中的 `score=` 也必须输出 `<non-finite-number:nan|inf|-inf>` 哨兵，而不是裸 `nan`、`inf` 或 `-inf`。这保证前端下载、人工排查和 CI 日志看到的是同一套可解释 artifact 语义。

生成端的 progress 与 Markdown 渲染也必须按同一容错边界读取 evaluation：`evaluation.score/passed/passes/issues` 缺失或类型异常时不得触发重复 error result，也不得中断 JSON/Markdown 产物生成；Markdown 明细可以显示 `<missing>` 占位，latest-report 摘要继续用 `invalid_evaluation_case_ids` 和 summary 校验字段表达该报告不可作为校准事实。

当单个 `run_case()` 抛异常时，行为评测脚本必须把异常沉淀为一条完整失败 result，而不是让整轮评测产物缺失：该行应包含报告消费所需的 `status=error`、空/0 timing 与 event count、`sse_high_cursor_replay.error`、空 `tool_names/model_call_trace/tool_calls`、`evaluation.passed=false` 与 `score=0`，使 JSON/Markdown companion 和 latest-report summary 仍可生成并保持 summary 计数/平均分与明细一致。

Markdown companion 只负责可读呈现，不应补写或伪造 JSON 原始 result。若某条 result 缺少 `run_id`、`conversation_id`、`status`、timing、event count、`sse_high_cursor_replay`、`tool_names`、`assistant_message_snippet` 或 `tool_calls`，`markdown_report()` 必须用 `<missing>` 或空列表安全渲染该行，保持 JSON artifact 原样，latest-report summary 继续从 JSON 明细派生可信度状态。

评估阶段本身也必须容忍部分 result：`evaluate_case()` / `evaluate_common()` 遇到缺失 `status`、`terminal`、`assistant_message`、`tool_names`、`tool_calls` 或 `sse_high_cursor_replay` 时，应把缺失字段转为 issues，并返回 `passed=false` 的 evaluation，而不是抛 KeyError 中断整轮评测；这保证生成端 report/Markdown 自恢复有机会继续执行。

`latest_report.duplicate_case_ids` 会列出同一份历史报告中重复出现的 case id；`current_case_set_complete` 只有在 `missing_case_ids`、`extra_case_ids` 和 `duplicate_case_ids` 都为空时才为 true，避免重复跑同一 case 的损坏报告被误判为覆盖当前 CASES。只要 `duplicate_case_ids` 非空，即使 `missing_model_call_trace_case_ids`、`missing_tool_diagnostic_chain_case_ids` 或 `missing_sse_high_cursor_replay_case_ids` 为空，对应 `*_complete` 也必须为 false，避免重复 case 的报告被误判为诊断证据完整。

`latest_report.schema_matches_current` 同样是 `model_call_trace_complete`、`tool_diagnostic_chain_complete` 与 `sse_high_cursor_replay_complete` 的共同前提；legacy schema 或缺失 schema 的历史报告可以继续展示 case/diagnostic 覆盖集合供人工参考，但三个诊断 complete 必须为 false，避免前端把非当前 schema 产物当作可信评测证据。

`behavior_evaluation_suite_available.details.uncovered_assertion_ids` 由 `scripts.agent_behavior_evaluation.uncovered_assertion_ids()` 派生，用于列出已登记到 `ASSERTIONS` 但没有任何 `EvalCase.assertion_ids` 覆盖的断言；当存在未声明断言或已登记未覆盖断言时，`assertion_metadata_complete=false` 且该 check 进入 attention，避免新增评测维度后只有断言清单变化、没有真实 case 验证。

Model call trace、Tool diagnostic chain 与 SSE high-cursor replay 的期望 case 集都由 `EvalCase.assertion_ids` 派生。`latest_report_summary()` 使用这些派生集合计算 `missing_*_case_ids`，并且 ToolCall diagnostic chain 覆盖判定与 `evaluate_tool_diagnostic_chain()` 保持一致：只忽略 `fetch_error` 的 ToolCall，所有成功抓取的 ToolCall 都必须带 execution/dispatch 摘要，`execution_context_present` 与 `dispatch_trace_present` 必须是布尔 true，`execution_context_hash` 与 `dispatch_trace_hash` 必须是非空字符串。`evaluate_case()` 也只在 case 声明对应 assertion 时检查 model trace、ToolCall diagnostic chain 或 SSE replay 证据，避免报告覆盖状态和真实评估逻辑分别维护诊断用例列表。

Model call trace 覆盖判定同样与 `evaluate_common()` 保持一致：`latest_report_summary()` 只有在 `result_has_model_call_trace()` 看到非空 `model_call_trace[]`，每条摘要包含 `model_call_id`、`loop_step` 且 `started_event_seen=true`，并且报告提供 `model_call_count` 时该值是正整数且 trace 数量与其一致，才会把 case 计入 `model_call_trace_case_ids`。非空但缺关键字段、`started_event_seen` 不是布尔 true、或 `model_call_count` 不是正整数的历史报告必须进入 `missing_model_call_trace_case_ids`，避免前端把弱 trace 当成当前可审查证据。

SSE high-cursor replay 覆盖判定同样与 `evaluate_common()` 保持一致：`latest_report_summary()` 只有在 `result_has_sse_high_cursor_replay()` 看到 `sse_high_cursor_replay` 为对象、没有 `error`、`event_count` 和 `non_heartbeat_event_count` 都是正整数、非 heartbeat 数量不大于总事件数、且 `heartbeat_only=false` 时，才会把 case 计入 `sse_high_cursor_replay_case_ids`。带 error、缺 `event_count` 或计数不一致的历史摘要必须留在 `missing_sse_high_cursor_replay_case_ids`，避免异常重放被误读为当前可审查证据。

缺失 `report_schema_version` 的历史 JSON 报告仍会以 `available=true` 被读取用于人工参考，但 `report_schema_version=null` 且 `schema_matches_current=false`，不得被 completion audit 或前端误判为当前 schema 的可信评测结果。

没有报告或最近 JSON 损坏的 unavailable 摘要同样输出 `report_schema_version=null`，区别是 `available=false`，用于表达“没有可读取的真实报告 schema”；`behavior_evaluation_runbook().report_schema_version` 仍只表示当前脚本期望生成的报告 schema。

`derived_from` 同步声明 `behavior_evaluation_cases=scripts.agent_behavior_evaluation.CASES`、`behavior_evaluation_assertions=scripts.agent_behavior_evaluation.ASSERTIONS`、`behavior_evaluation_assertion_coverage=scripts.agent_behavior_evaluation.assertion_coverage`、`behavior_evaluation_undeclared_case_assertions=scripts.agent_behavior_evaluation.undeclared_case_assertions`、`behavior_evaluation_runbook=scripts.agent_behavior_evaluation.behavior_evaluation_runbook`、`behavior_evaluation_model_call_trace_fields=scripts.agent_behavior_evaluation.MODEL_CALL_TRACE_FIELDS`、`behavior_evaluation_markdown_sections=scripts.agent_behavior_evaluation.MARKDOWN_REPORT_SECTIONS`、`behavior_evaluation_latest_report=scripts.agent_behavior_evaluation.latest_report_summary` 与 `behavior_evaluation_latest_report_fields=scripts.agent_behavior_evaluation.LATEST_REPORT_SUMMARY_FIELDS`，用于追溯 completion audit 中行为评测 metadata 的脚本来源。

`derived_from.behavior_evaluation_uncovered_assertions` 指向 `scripts.agent_behavior_evaluation.uncovered_assertion_ids`，与 `assertion_coverage` 和 `undeclared_case_assertions` 一起构成行为评测断言元数据治理来源。

前端约定：`complete=true` 表示后端仓库范围内 Agent 对话、流式事件、工具/审批/Memory/诊断/契约已具备联调完成度；`backend_scope.frontend_delivery=external repository` 表示前端实现仍在另一个仓库交付；`launch_audit.promotion_decision=blocked` 只表示生产发布门禁仍按策略阻断，不等于后端 Agent 对话功能不可用。

### 3.9 运维审计和后台处理

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/agents/worker-queue/audit` | WorkerQueue lease/duplicate audit |
| `POST` | `/agents/outbox/publish` | Outbox publish |
| `GET` | `/agents/events/replay-stress-audit` | event replay stress audit |
| `GET` | `/agents/fault-injections` | fault injection catalog |
| `GET` | `/agents/fault-injections/coverage` | fault coverage |
| `POST` | `/agents/fault-injections/run` | run fault injection |
| `GET` | `/agents/root-cause-rules/audit` | root cause rule governance |
| `GET` | `/agents/backend-contracts/{backend_name}/operations/{backend_operation}` | backend operation contract |

WorkerQueue audit 中的 lease 诊断项也暴露稳定 item identity：`expired_leases[].item_id=agent-worker-queue-expired-lease://{queue_id}`，`duplicate_active_leases[].item_id=agent-worker-queue-duplicate-active://{tool_call_id}`。这些字段由公开 queue/tool facts 派生，不新增数据库列，不替代 `queue_id`、`tool_call_id`、lease owner/status 列表或 worker recovery 判定；前端可用它们作为 WorkerQueue 审计列表、告警详情、timeline/debug/download item 的稳定 key。

Event Replay stress audit 中的嵌套重复项也暴露稳定 item identity：`run_audits[].item_id=agent-event-replay-run://{run_id}`，`run_audits[].cursor_audits[].item_id=agent-event-replay-cursor://{run_id}/{after_sequence}`。这些字段由 run id 和 run-scoped replay cursor facts 派生，不新增数据库列，不替代 `event_seq`、`after_sequence`、Last-Event-ID 或 `replayable/replay_cursor_valid` 判定；前端可用它们稳定定位压力审计里的 run 行与 cursor 行，但不要据此改变 SSE cursor 或回放窗口算法。

RootCause rule governance audit 中的 violation 行也暴露稳定 item identity：`violations[].item_id=agent-root-cause-rule-violation://{rule_id}/{violation}`。该字段由规则 id 和 violation 类型派生，不新增数据库列，不替代 `rule_id`、`priority`、`priority_band` 或 governance pass 判定；前端可用它稳定定位规则治理审计里的违规项，`expected_range` 只在 priority 越界类 violation 中出现。

Fault injection catalog 与 run result 也暴露稳定 item identity：`AgentFaultInjectionCaseRead.item_id=agent-fault-injection-case://{case_id}`，`AgentFaultInjectionResultRead.item_id=agent-fault-injection-result://{run_id}/{case_id}`。这些字段由公开 case/run facts 派生，不新增数据库列，不替代 `case_id`、`run_id`、`tool_call_id`、coverage set 或 dashboard `fault_injection_catalog_complete` 判定；前端可用它们作为生产硬化用例目录、执行结果、timeline/debug/download item 的稳定 key。

`POST /agents/outbox/publish` 的 response summary 只包含 `attempted/published/failed/dead_letter/pending_remaining/outbox_publish_lag_ms`，不暴露逐条 outbox 的 `last_error`。后端诊断列 `AgentOutbox.last_error` 仍必须和其他 Agent 错误面一致：短 publish 错误保留原文，超过 `AGENT_ERROR_MESSAGE_MAX_CHARS=512` 时用 `agent_error_message_summary_v1`、`agent_error_message_truncated`、原始长度、hash 和 `full_error_reference=AgentOutboxPublisher.publish_pending` 表达，避免 dead-letter 排障面复制完整 provider/backend 异常尾部。

## 4. 前端禁止事项

- 不要在页面组件中直接 `fetch` 普通接口；必须封装到 `src/api/agents.ts`。
- 不要把后端 snake_case 字段改成 camelCase 后再跨组件传递，除非建立完整映射层和测试。
- 不要用原生 `EventSource` 访问需要 Authorization header 的 SSE。
- 不要忽略 approve/reject 的 CAS 字段。

## 5. 必测项

| 类型 | 用例 |
| --- | --- |
| API 封装 | 每个函数拼接正确路径、方法、query/body |
| SSE parser | 多 event、断包、heartbeat、Last-Event-ID、AbortController |
| Run 流程 | create run -> stream -> terminal -> close |
| ToolCall | event 触发详情拉取、输出展开、错误展示 |
| Approval | CAS 字段提交、409 冲突提示 stale approval |
| Approval resume | approve 后触发 resume，展示 `executed_tool_call_ids` 对应工具输出和后续 assistant 回复 |
| History | 本地 conversation index 增删改、run 校准失败降级 |
| 权限 | 403 展示无权限，不重试破坏性动作 |
| 文档同步 | 字段与本文件和 Harness `Required ... contract` 保持一致 |
## Agent Skill Orchestration v2 运行时语义

后端 Agent 正在从“单 Skill 预路由”演进为“候选 Skill/Tool 召回 + LLM 规划 + Runtime 校验”的模式。`/agents/capabilities` 仍展示全量公开 ToolSpec；单个 run 的模型上下文只展示本轮候选工具，但候选工具由当前用户目标和历史 artifact 证据共同决定。前端不得假设单轮只会出现一个业务 Skill，也不得根据上一轮 artifact 类型推断本轮目标领域。

当前用户明确目标优先于历史 artifact follow-up action。例如用户说“根据失败用例创建缺陷”时，失败用例快照是 evidence，缺陷是 target，后端会召回 `defect.create_saved` 以及必要的测试用例读取工具；只有“执行它”“保存这个”“修复这些断言”等省略指代请求，才允许 artifact action 成为主流程。所有写入、执行、状态流转仍以 ToolCall、Approval、ObjectReferenceGuardRule 和业务权限为准，模型文本不得被视为业务动作已完成。

Run diagnostics 中的 `skill_plan.primary_skill` 表示目标领域主 Skill，`supporting_skills` 表示证据或辅助领域 Skill；前端应按列表渲染，不要假设只有一个 Skill。若后端写入 `model.capability_denial_guarded` 事件，表示模型曾错误否认一个 runtime snapshot 中实际存在的能力，前端可按普通模型事件展示该诊断，不需要新增审批入口。

`skill_plan.reason_codes` 可能包含 `planner:supporting_skill:{skill}:evidence:{domain}`，用于说明 supporting Skill 来自 Skill contract 的 `owns/consumes/produces` 语义，而不是用户直接请求该 Skill。Supporting Skill 的存在不表示其所有写入工具都可用；后端默认只把 evidence Skill 的只读/确定性工具加入本轮候选工具，副作用工具仍必须由当前目标动作、审批策略和 Runtime preflight 明确允许。

当 `model.capability_denial_guarded` 后紧跟 `model.capability_denial_replanned`，表示后端已经对错误能力否认做了一次隐藏重规划，并成功让模型重新输出工具请求。前端后续仍按既有 ToolCall/Approval 事件展示：写入类工具会进入 `needs_human` 或 pending approval 相关状态，前端不要因为 replan 事件新增独立审批入口。若只出现 guarded 而没有 replanned，表示后端阻止了错误结论但未得到可执行工具请求，应按普通诊断事件展示。

## Capability Plan 增量字段与事件

`AgentRunRead` 新增可空字段 `active_capability_plan_id`，表示该 run 当前有效的能力计划；`AgentToolCallRead` 新增可空字段 `capability_plan_id`，表示该次工具调用实际绑定的计划。没有 Capability Plan 的历史 run/ToolCall 可以为 `null`；run 一旦存在 active plan，后端会在 ToolCall 省略该字段时自动绑定当前计划并严格校验。前端必须按加法兼容处理，不能据此隐藏旧 ToolCall。

前端可按普通诊断事件展示 `planner.intent_decision_created`、`planner.intent_decision_fallback`、`planner.capability_plan_created`、`planner.route_mismatch_detected`、`model.native_tool_call_detected` 和 `model.native_tool_call_invalid`。`planner.capability_plan_created.payload_json` 至少包含当前计划 ID、iteration、revision、source 与 plan hash；发生 carry-forward 或 route rebuild 时还包含上一计划 ID。计划变更不新增审批入口，也不替代 ToolCall/Approval 状态机。

原生 provider tool call 不改变前端 SSE 主协议：模型规划文本仍保持隐藏，合法调用仍形成既有 AgentToolCall；工具结果仍通过原有 ToolCall、Approval、run event 和最终 assistant 消息展示。前端无需解析 provider tool alias、原生 arguments 或旧 fenced JSON，这些都属于后端模型传输层实现。

## LLM-Driven Planning 与真实场景增量契约

本节替代上文关于 `model.capability_denial_guarded/replanned`、`planner.intent_decision_fallback` 和 route rebuild 的旧前端语义。新生产路径不会因为模型自然语言否认而重建计划，也不会使用关键词 fallback 授权 Tool。

| event_type | 中文显示名 | 前端处理 |
| --- | --- | --- |
| `planner.llm_decision_started` | 智能规划开始 | 普通运行诊断，不创建 Tool 卡片 |
| `planner.llm_decision_completed` | 智能规划完成 | 可展示 selected Skills/Tools、effect scope 和 plan 摘要 |
| `planner.llm_decision_invalid` | 规划校验未通过 | 展示结构化 code；不要展示 prompt 或推理链 |
| `planner.llm_decision_retrying` | 正在修复规划 | 普通诊断；最多一次 |
| `planner.llm_decision_failed` | 智能规划失败 | Run 最终错误码为 `agent_planning_failed` |
| `planner.capability_activation_requested` | 请求扩展能力 | Runtime 控制事件，不是业务 ToolCall |
| `planner.capability_activation_accepted` | 能力扩展成功 | 计划 revision 已提交，不代表业务动作已执行 |
| `planner.capability_activation_rejected` | 能力扩展被拒绝 | 展示 rejected tools/reasons，不新增审批入口 |
| `planner.capability_plan_revised` | 能力计划已更新 | 更新当前 plan id；仍按 ToolCall/Approval 展示业务动作 |
| `planner.capability_call_rejected` | 工具尚未激活 | 模型会收到 `agent_capability_not_active` 并继续规划 |
| `model.capability_denial_observed` | 模型能力判断诊断 | 仅观测，不替换 assistant 文本、不重建计划 |
| `scenario.draft_validation_completed` | 场景草稿校验通过 | payload 提供引用/模板/依赖统计，可允许后续保存入口 |
| `scenario.draft_validation_failed` | 场景草稿校验失败 | 显示问题计数并引导修复；不得显示“可保存” |

`scenario.compose_draft` ToolResult 的 `draft.scenario_validation` 是新增 envelope，包含 `valid/referenced_case_count/unresolved_reference_count/dependency_edge_count/resolved_template_count/unresolved_template_count/extractor_count/binding_count/graph_errors/quality_issues/evidence_sources`。前端只有在 `valid=true` 时才能把 artifact 标为权威场景草稿；`scenario_draft_invalid` 是诊断 artifact，`available_followup_actions` 只有 `repair`。

错误码增量：`agent_planning_failed` 表示两次结构化规划均未通过；`agent_capability_not_active` 表示模型调用了当前 plan 外的 Tool，Runtime 已阻止业务 handler；`agent_capability_activation_rejected` 表示内部能力扩展请求未通过注册表/Skill/权限校验；`agent_scenario_case_source_invalid` 表示 case artifact 的项目、用户、会话、hash、环境或用例引用无效；`agent_scenario_draft_invalid` 表示草稿未通过真实引用与证据质量门。上述错误都不改变 REST/SSE envelope。
