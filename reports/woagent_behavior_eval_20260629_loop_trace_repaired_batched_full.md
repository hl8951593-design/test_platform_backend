# woagent 运行返回与问题理解完整评测报告

- 评测时间：2026-06-29T22:41:03
- Base URL：`http://127.0.0.1:8000/api/v1`
- 项目 ID：`1`
- 登录用户：`admin` / user_id=`1`
- 总用例数：8
- 通过用例数：6
- 平均分：97.0

## 结论

本轮评测存在 2 个未完全通过用例，需要重点查看下方“问题清单”。

## 问题清单

### T05 场景 warnings 可修复项闭环
- 修复闭环追问出现保存正式对象声称

### T07 数据集参数化理解与草稿更新
- 数据集更新错误声称保存正式对象

## 用例明细

### T01 通用测试知识问答

- Run ID：`agent-run-99044f9423ef4a0eb1da82ad490db825`
- Conversation ID：`agent-conv-dfc0d2e5438742babec74bd2365240bd`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=21.0s，first_delta=3.453s
- 事件：event_count=105，model_delta=100，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=105，heartbeat_only=False
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

> 边界值分析关注输入域边界及邻近点（如最小值、最大值、刚好超出），等价类划分则按规则将输入域划为有效/无效等价区间，每类取一代表值。对登录接口：等价类划分选“有效用户名+有效密码”代表有效类，选“空用户名+有效密码”代表无效类；边界值分析则取密码长度最小8、最大20，测7、8、20、21字符以验证边界。

### T02 多轮上下文追问且不创建对象

- Run ID：`agent-run-764ea95c64f348e38472bf5a066c9e49`
- Conversation ID：`agent-conv-dfc0d2e5438742babec74bd2365240bd`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=17.0s，first_delta=6.672s
- 事件：event_count=62，model_delta=56，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=62，heartbeat_only=False
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

> 1. 有效凭据登录成功 2. 用户名为空提示必填 3. 密码为空提示必填 4. 密码7字符提示过短 5. 密码8字符登录成功 6. 密码21字符提示超限

### T03 读取项目上下文

- Run ID：`agent-run-e16ffaf9de30496e8e3ef3e92c57cd2d`
- Conversation ID：`agent-conv-3d0dffc25e204a45898647cd9d18d2b5`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=10.0s，first_delta=10.75s
- 事件：event_count=16，model_delta=1，tool_event=7
- Loop 指标：model_call=2，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=16，heartbeat_only=False
- 工具链：`project.read_context`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 按需调用 project.read_context
- 最终回复基于项目/环境/资源维度总结

最终回复摘录：

> 当前项目 ID=1，默认环境为「test」，基地址 `https://www.lingxidata.cn`。上下文中尚未返回测试用例和场景列表，因此暂无法看到具体测试资源与已有场景。如需查看用例，我可立即查询。

### T04 企业场景 query-first 组合草稿

- Run ID：`agent-run-627ea550a5ab4ffb9595f05edd97594f`
- Conversation ID：`agent-conv-257c06050473480d8db97476b733bd7b`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=93.0s，first_delta=94.031s
- 事件：event_count=29，model_delta=1，tool_event=15
- Loop 指标：model_call=3，tool_request_repair=1，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=29，heartbeat_only=False
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

> ## 场景草稿生成完成（未保存） 场景 `企业信息查看与关注流程` 已成功生成并通过自验证（7/7 步骤均通过）。以下是最终草稿结构： ### 步骤概览 | 步骤 | 节点名称 | 用例 | 方法 | 关键变量绑定 | 断言 | |------|---------|------|------|-------------|------| | 1 | 获取企业列表 | 用例7 | POST | 提取 `companyId`、`companyName` | status_code=200, body 含 `success` | | 2 | 获取对应企业CT画像数 | 用例8 | GET | query `companyId` ← 步骤1 | status_code=200, body 含 `code` | | 3 | 关注企业 | 用例9 | POST | body `companyId`、`companyName` ← 步骤1 | ...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["候选用例 8、9、11、12、16、18 的最近执行均返回 '请求未授权' (code: 90001)，表明鉴权失败。场景中保留了这些用例的原始 headers 配置（包含 Lingxi-Auth 变量），但未提供有效的 token 生成步骤。建议在场景前增加登录或 token 获取步骤，或确保环境变量 Lingxi-Auth 已正确配置。", "候选用...

### T05 场景 warnings 可修复项闭环

- Run ID：`agent-run-74e52923f6164e578bcd744253781a2e`
- Conversation ID：`agent-conv-257c06050473480d8db97476b733bd7b`
- 状态：`completed`，分数：88，通过：False
- 耗时：completed=106.0s，first_delta=105.922s
- 事件：event_count=33，model_delta=1，tool_event=18
- Loop 指标：model_call=4，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=33，heartbeat_only=False
- 工具链：`scenario.compose_draft, testcase.query_project_cases, scenario.compose_draft`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 对可修复项作出继续处理或明确状态说明
- 未把明显非鉴权可修复项直接甩给用户

问题：
- 修复闭环追问出现保存正式对象声称

最终回复摘录：

> 场景草稿已再次生成并通过自验证，**7/7 步骤全部通过**，无需继续自动修复。以下是最终草稿结构与变量绑定总结： --- ## 场景：企业信息查看与关注流程（未保存） ### 步骤概览 | 步骤 | 节点 | 用例 ID | 方法 | 关键变量绑定 | 断言 | |---|---|---|---|---|---| | 1 | 获取企业列表 | 7 | POST | → 提取 `companyId`、`companyName` | `status_code=200` + `body_contains success` | | 2 | 获取对应企业CT画像数 | 8 | GET | `query_params.companyId` ← `{{companyId}}` | `status_code=200` + `body_contains code` | | 3 | 关注企业 | 9 | POST | `body.companyI...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["用例8、9、11、12、16、18的最近执行均返回“请求未授权”，可能因鉴权令牌过期或环境限制，场景执行时需确保Lingxi-Auth有效。", "用例7的响应样本中data.dataList数组包含多个企业，提取器默认取第一个元素的companyId和companyName，若需动态选择请调整提取路径。", "用例16的body.orgIds绑定为字符...

### T06 保存正式场景边界

- Run ID：`agent-run-73bc5110012d4a64b07b26aa361a5be6`
- Conversation ID：`agent-conv-257c06050473480d8db97476b733bd7b`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=3.0s，first_delta=3.5s
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

- Run ID：`agent-run-bdac70223657455791aec4be0f9f9f58`
- Conversation ID：`agent-conv-257c06050473480d8db97476b733bd7b`
- 状态：`completed`，分数：88，通过：False
- 耗时：completed=232.0s，first_delta=232.797s
- 事件：event_count=52，model_delta=1，tool_event=28
- Loop 指标：model_call=5，tool_request_repair=3，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=52，heartbeat_only=False
- 工具链：`testcase.query_project_cases, scenario.compose_draft, scenario.compose_draft, scenario.compose_draft`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 理解 companyId 多企业数据集参数化诉求
- 草稿更新工具请求包含 include_datasets=true

问题：
- 数据集更新错误声称保存正式对象

最终回复摘录：

> ## 当前草稿状态（未保存） 通过 `execute_candidates=true` 已成功获取用例 7 的企业列表响应样本，并生成了带数据集的场景草稿，流程通过自验证。**但数据集覆盖多企业的目标尚未在草稿中实质达成**，具体原因和解决方案如下。 --- ### 数据集覆盖多企业的理想方案 平台数据集机制允许为场景定义一个二维表，每一行代表一组变量值。理想流程： 1. **步骤 1** 执行 `POST /api/lingxi-chain/cloudentchain/getEntPageList`，返回 `data.dataList` 数组，例如： ```json [ {"companyId": "20012112150000146396", "companyName": "中国铝业集团有限公司"}, {"companyId": "20012112150000221448", "companyName": "某科技公司"},...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["所有下游接口（用例8、9、11、12、16、18）均返回 '请求未授权' (code: 90001)，表明硬编码的 Lingxi-Auth token 可能已过期或无效。建议添加登录步骤以动态获取有效 token，或更新 token。当前场景保留硬编码 token，可能导致执行失败。", "用例16（资质认定）的 body 中 groupIds 字段使用...
- `scenario.compose_draft` warning: draft.warnings: ["所有下游用例的execution_sample均返回'请求未授权'，可能因{{Lingxi-Auth}}变量未正确提供或已过期。场景中未包含鉴权步骤，需确保环境变量或前置动作中已设置有效的Lingxi-Auth。", "用例16（资质认定）的body中orgIds和groupIds使用了硬编码值，仅将companyId替换为变量，groupIds保持原值...

### T08 非测试领域能力边界

- Run ID：`agent-run-dadb0e95dcfd4bf995a35fcabf484c7a`
- Conversation ID：`agent-conv-f1044c3873a04c8fb34db6577793eff0`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=14.0s，first_delta=3.391s
- 事件：event_count=67，model_delta=62，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=67，heartbeat_only=False
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

> 抱歉，我的能力范围专注于软件测试和 TestAuto 平台相关的事务，比如接口测试、场景编排、缺陷分析等，无法为您创作情诗。如果您的目标与测试相关（例如为某个 API 编写测试用例、生成测试场景），请告诉我具体需求，我会尽力协助。

## 原始产物

- JSON：`reports\woagent_behavior_eval_20260629_loop_trace_repaired_batched_full.json`
- Markdown：`reports\woagent_behavior_eval_20260629_loop_trace_repaired_batched_full.md`
