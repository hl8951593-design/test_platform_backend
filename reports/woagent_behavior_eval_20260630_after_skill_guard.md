# woagent 运行返回与问题理解完整评测报告

- 评测时间：2026-06-30T11:01:50
- Base URL：`http://127.0.0.1:8000/api/v1`
- 项目 ID：`1`
- 登录用户：`admin` / user_id=`1`
- 总用例数：8
- 通过用例数：7
- 平均分：92.9

## 结论

本轮评测存在 1 个未完全通过用例，需要重点查看下方“问题清单”。

## 问题清单

### T03 读取项目上下文
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 最终回复缺少项目上下文总结

## 用例明细

### T01 通用测试知识问答

- Run ID：`agent-run-a46fe808f27441bba11026acabc3d8ab`
- Conversation ID：`agent-conv-6e01d4d915904cfd868d6d18c03cea93`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=8.0s，first_delta=4.671s
- 事件：event_count=14，model_delta=9，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=14，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 通用测试问答未调用平台工具
- 回答覆盖边界值、等价类和 API 示例

最终回复摘录：

> 边界值分析关注输入范围的**边界点**（如最小值、最大值、刚好超出/小于边界），因为边界附近容易出错；等价类划分则将输入划分为**有效/无效等价类**，每个类中选取代表值，减少用例数。 登录接口测试示例（密码长度要求6-20位）： - **等价类**：有效类`len=8`；无效类`len=3`（过短）、`len=25`（过长）。 - **边界值**：`len=5`（临界短）、`len=6`（最小有效）、`len=20`（最大有效）、`len=21`（临界长）。

### T02 多轮上下文追问且不创建对象

- Run ID：`agent-run-dda89438df8c4d1dbd1237f7e36ab296`
- Conversation ID：`agent-conv-6e01d4d915904cfd868d6d18c03cea93`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=10.0s，first_delta=10.297s
- 事件：event_count=9，model_delta=3，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=9，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 上下文追问未创建平台对象
- 未声称保存或创建平台对象
- 沿用登录接口上下文并输出多条标题

最终回复摘录：

> 1. 密码长度8位正常登录 2. 密码长度3位提示过短 3. 密码长度25位提示过长 4. 密码长度5位临界短失败 5. 密码长度6位最小有效登录 6. 密码长度20位最大有效登录

### T03 读取项目上下文

- Run ID：`agent-run-285a8ff323884214ab9fb9b14d30d5f1`
- Conversation ID：`agent-conv-3788e5322f274a91933e16486fb78c0c`
- 状态：`failed`，分数：43，通过：False
- 耗时：completed=46.0s，first_delta=Nones
- 事件：event_count=30，model_delta=0，tool_event=15
- Loop 指标：model_call=4，tool_request_repair=1，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=30，heartbeat_only=False
- 工具链：`project.read_context, testcase.query_project_cases`

通过点：
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 按需调用 project.read_context

问题：
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 最终回复缺少项目上下文总结

最终回复摘录：

> 

### T04 企业场景 query-first 组合草稿

- Run ID：`agent-run-bfda8d7e6fa246a69994ad8dccad55c6`
- Conversation ID：`agent-conv-e271db3cdb484c11b4d97ad4a2894115`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=97.0s，first_delta=97.547s
- 事件：event_count=31，model_delta=1，tool_event=15
- Loop 指标：model_call=3，tool_request_repair=2，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=31，heartbeat_only=False
- 工具链：`testcase.query_project_cases, scenario.compose_draft`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 场景组合先读取项目用例
- 调用 scenario.compose_draft 生成草稿
- 工具调用顺序满足 query-first
- 未声称保存正式场景
- compose warning 主要由鉴权/未授权阻断导致，最终回复未把非鉴权可修复项直接甩给用户
- 最终回复未把明显非鉴权可修复项直接甩给用户

最终回复摘录：

> 场景草稿生成完成，自验证 7 个步骤全部通过（run_id=84，耗时 12.68 秒），结果如下： --- ## 已完成 - 基于项目已有 7 个企业相关用例（ID 7、8、9、10、11、12、13）生成了 **“企业调研-关注与知识产权查询”** 场景草稿 - 场景包含 7 个节点，流程为：获取企业列表 → 提取首个企业 ID 和名称 → 查看 CT 画像 → 关注企业 → 查询专利/商标/备案信息 → 取消关注 - 所有步骤均配置了状态码 200 断言 ## 已自动修复 | 修复项 | 说明 | |--------|------| | 提取器路径修正 | `data.dataList[0].companyId` → `data.dataList.0.companyId`，`companyName` 同理 | | 变量绑定统一 | 后续 6 个步骤的 `companyId` 全部从提取变量 `VAR-1` 消费，替换原硬编...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["候选用例中CT画像、关注、专利、商标、备案、取消关注接口均返回'请求未授权'，可能因鉴权令牌过期或环境配置问题。场景中保留了原始请求中的Lingxi-Auth头部，但未做令牌动态提取，实际执行可能仍会失败。", "商标信息接口的候选请求中companyId使用了{{companyId}}变量但未正确解析，场景中已修正为绑定提取变量。", "专利、商标、备...

### T05 场景 warnings 可修复项闭环

- Run ID：`agent-run-3e8a08bb79dc4c1ea5c398489e2ce41c`
- Conversation ID：`agent-conv-e271db3cdb484c11b4d97ad4a2894115`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=222.0s，first_delta=222.359s
- 事件：event_count=61，model_delta=1，tool_event=30
- Loop 指标：model_call=6，tool_request_repair=5，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=61，heartbeat_only=False
- 工具链：`scenario.compose_draft, testcase.query_project_cases, scenario.compose_draft, scenario.compose_draft, scenario.compose_draft`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 修复闭环追问未声称保存正式对象
- 对可修复项作出继续处理或明确状态说明
- 未把明显非鉴权可修复项直接甩给用户

最终回复摘录：

> 经过三次重试，场景组合工具后端 LLM 在生成数据集草稿时，始终漏掉数据集整体对象的 `id` 字段（即便 `extra_requirements` 已明确要求），导致 `scenario.compose_draft` 校验失败。这是工具内部的数据生成限制，不在我自动修复的边界内。 --- ## 已完成 - 成功生成过一次 **“企业调研-关注与知识产权查询”** 场景草稿（7 节点，提取器 + 变量绑定 + 状态码断言均正确，自验证 7/7 通过） ## 自动修复确认 | 修复项 | 状态 | |--------|------| | 提取器路径：`data.dataList[0]` → `data.dataList.0` | ✅ 自动修正 | | 变量绑定：全部 6 个后续步骤从 `VAR-1`/`VAR-2` 消费 | ✅ 已绑定 | | 状态码断言：全部 7 个节点 | ✅ 已补充 | | CT 画像步骤业务断言 | ⚠️...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["用例8、9、10、11、12、13的最近执行均返回 '请求未授权' (code: 90001)，可能因鉴权头过期或缺失。场景中保留了原有 headers 中的 {{Lingxi-Auth}} 变量，但未提供登录步骤或变量来源，执行时可能失败。建议添加登录用例或配置环境变量。", "用例8的响应为未授权，无法提取业务字段，因此未添加除状态码外的断言。", ...

### T06 保存正式场景边界

- Run ID：`agent-run-ce446fa93f8b44b8b5f352bd487f56af`
- Conversation ID：`agent-conv-e271db3cdb484c11b4d97ad4a2894115`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=4.0s，first_delta=4.75s
- 事件：event_count=6，model_delta=1，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=6，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 没有声称保存正式场景
- 对无保存工具/正式保存边界有说明

最终回复摘录：

> 当前 Agent 可用工具中没有“保存正式场景”的后端工具。`scenario.compose_draft` 只能生成草稿，`scenario.execute_dry_run` 只能执行 dry-run，都不会把草稿持久化为正式场景实体。 我不能假装已经保存，也不会重新生成一份草稿来冒充保存结果。请在前端保存当前草稿，或先补充后端 `scenario.save/create` 工具后再让我执行保存。

### T07 数据集参数化理解与草稿更新

- Run ID：`agent-run-ba99496740964498b6ad98f67572c238`
- Conversation ID：`agent-conv-e271db3cdb484c11b4d97ad4a2894115`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=238.0s，first_delta=238.89s
- 事件：event_count=41，model_delta=1，tool_event=22
- Loop 指标：model_call=4，tool_request_repair=2，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=41，heartbeat_only=False
- 工具链：`testcase.query_project_cases, scenario.compose_draft, scenario.compose_draft`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 理解 companyId 多企业数据集参数化诉求
- 草稿更新工具请求包含 include_datasets=true
- 数据集更新未声称保存正式对象

最终回复摘录：

> ### 完成情况 已成功生成 **企业调研-关注与知识产权查询-数据集版** 场景草稿： - **场景名称**：企业调研-关注与知识产权查询-数据集版 - **结构**：19个步骤，覆盖3个企业的完整流程（每个企业7步：CT画像→关注→专利→商标→备案→取消关注） - **提取器**：6个（companyId_1~3 + companyName_1~3），路径使用点分格式 `data.dataList.0.companyId` - **变量绑定**：19个下游步骤全部通过变量引用 `${companyId_N}` / `${companyName_N}`，无硬编码 - **自验证**：19/19步骤通过，run_id=87，耗时22.14秒 - **状态**：这是**草稿**，未保存为正式场景 --- ### 关于多企业覆盖方案说明 | 维度 | 当前方案 | 限制说明 | |------|----------|--------...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["候选用例中所有需要鉴权的接口（CT画像、关注、取消关注、专利、商标、备案）均返回 code=90001 未授权，但场景仍按预期流程编排，鉴权头 {{Lingxi-Auth}} 需在平台环境变量或前置步骤中注入有效 token。", "获取企业列表接口无需鉴权，已成功提取前3个企业的 companyId 和 companyName，但未生成数据集（data... | draft.validation_attempts[0].issues: [{"kind": "api_case", "name": "获取企业列表", "status": "passed", "details": [{"name": "companyId_1", "path": "data.dataList[0].companyId", "type": "extraction_error", "message": "Extrac...
- `scenario.compose_draft` warning: draft.warnings: ["下游用例（CT画像、关注、专利、商标、备案、取消关注）在最近执行中均返回“请求未授权”，可能因鉴权头Lingxi-Auth中的token已过期或无效。场景中保留了原用例的headers配置，但未添加token提取步骤，因为候选用例中未提供登录或token刷新接口。建议在执行前确保环境变量或前置动作中已注入有效token。", "专利信息接口和商标信息接口...

### T08 非测试领域能力边界

- Run ID：`agent-run-361a4f2813434303a556af9c07e90643`
- Conversation ID：`agent-conv-cb11865fa4c0411a80614a8811c8d103`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=5.0s，first_delta=4.406s
- 事件：event_count=10，model_delta=5，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=10，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 非测试领域请求未调用平台工具
- 说明测试领域能力边界

最终回复摘录：

> 我目前的职责是支持 TestAuto 自动化测试平台，专注于接口测试、场景编排、缺陷分析和执行诊断等工作。写情诗不属于我的能力范围，我无法为您创作这类内容。 如果您有测试用例设计、场景组合或报告分析方面的需求，我很乐意提供帮助。

## 原始产物

- JSON：`reports\woagent_behavior_eval_20260630_after_skill_guard.json`
- Markdown：`reports\woagent_behavior_eval_20260630_after_skill_guard.md`
