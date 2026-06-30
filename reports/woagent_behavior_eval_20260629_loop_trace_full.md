# woagent 运行返回与问题理解完整评测报告

- 评测时间：2026-06-29T21:53:06
- Base URL：`http://127.0.0.1:8000/api/v1`
- 项目 ID：`1`
- 登录用户：`admin` / user_id=`1`
- 总用例数：8
- 通过用例数：6
- 平均分：87.5

## 结论

本轮评测存在 2 个未完全通过用例，需要重点查看下方“问题清单”。

## 问题清单

### T05 场景 warnings 可修复项闭环
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 未体现继续修复/验证，也未说明可修复项状态

### T07 数据集参数化理解与草稿更新
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 未体现多企业数据集参数化理解

## 用例明细

### T01 通用测试知识问答

- Run ID：`agent-run-2bb38536035e4baa8aa7d67fcd26d356`
- Conversation ID：`agent-conv-0a6704adb7b24148821a89b5fa9d114e`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=27.0s，first_delta=8.75s
- 事件：event_count=109，model_delta=104，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=109，heartbeat_only=False
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

> 等价类划分将输入域划为有效/无效等价类，选代表值测试；边界值分析聚焦等价类边界，测试边界、边界+1/-1值，因边界更易出错。例：登录API要求用户名6-20位。等价类：有效“test12”（6-20），无效“abc”(<6)、“a...z”(>20)；边界值：长度5、6、20、21，搭配正确密码，验证错误提示与登录结果。

### T02 多轮上下文追问且不创建对象

- Run ID：`agent-run-db8d9ad89051411d8d545308c7735e07`
- Conversation ID：`agent-conv-0a6704adb7b24148821a89b5fa9d114e`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=13.0s，first_delta=3.375s
- 事件：event_count=65，model_delta=60，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=65，heartbeat_only=False
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

> 1. 用户名长度5位边界值登录 2. 用户名长度6位最小值登录 3. 用户名长度20位最大值登录 4. 用户名长度21位超长登录 5. 有效等价类正常登录 6. 无效等价类空用户名登录

### T03 读取项目上下文

- Run ID：`agent-run-f2e1176a768d42b6869fb63e78bf8232`
- Conversation ID：`agent-conv-99b4f322a0a4464994f889813bb84232`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=21.0s，first_delta=12.296s
- 事件：event_count=69，model_delta=54，tool_event=7
- Loop 指标：model_call=2，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=69，heartbeat_only=False
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

> 项目 ID=1，仅有 1 个默认测试环境 **test**（`https://www.lingxidata.cn`）。当前上下文中未返回任何测试用例或场景记录，推断项目尚无 HTTP/WebSocket 用例与已编排场景。

### T04 企业场景 query-first 组合草稿

- Run ID：`agent-run-169edc74d8474083bd81f75689b6d292`
- Conversation ID：`agent-conv-0ea3f7cb90b74a1088fbacd989c03878`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=121.0s，first_delta=120.984s
- 事件：event_count=31，model_delta=1，tool_event=15
- Loop 指标：model_call=4，tool_request_repair=1，required_tool_repair=0，context_compaction=0
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

> ## 候选用例分析报告 根据项目内 17 个用例，筛选出与企业尽调相关的 8 个核心用例，分析如下： ### 用例用途与字段分析 | case_id | 名称 | 方法 | 路径 | 请求关键字段 | 响应预期 | 可复用变量 | |---------|------|------|------|-------------|----------|-----------| | **7** | 获取企业列表 | POST | `/api/lingxi-chain/cloudentchain/getEntPageList` | body: `{code, page, sort, keyWord, pageSize, clientInfoDTO}` | 200 + success | `companyId` ← `data.dataList.0.companyId`<br>`companyName` ← `data.dataList.0....

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["所有需要鉴权的接口（CT画像数、专利、商标、备案、资质认定、红名单、关注）均使用了变量{{Lingxi-Auth}}，但候选用例中未提供鉴权步骤或提取该变量的用例。最近执行结果显示这些接口返回“请求未授权”，但状态码200，断言通过。场景中保留了{{Lingxi-Auth}}变量，但未绑定来源，执行时可能因未授权而失败。建议添加登录用例并提取token，...

### T05 场景 warnings 可修复项闭环

- Run ID：`agent-run-33c398afbee14e548ba7b3b983cf4f7c`
- Conversation ID：`agent-conv-0ea3f7cb90b74a1088fbacd989c03878`
- 状态：`failed`，分数：50，通过：False
- 耗时：completed=60.0s，first_delta=Nones
- 事件：event_count=18，model_delta=0，tool_event=8
- Loop 指标：model_call=3，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=18，heartbeat_only=False
- 工具链：`testcase.query_project_cases`

通过点：
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 修复闭环追问未声称保存正式对象
- 未把明显非鉴权可修复项直接甩给用户

问题：
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 未体现继续修复/验证，也未说明可修复项状态

最终回复摘录：

> 

### T06 保存正式场景边界

- Run ID：`agent-run-9f08783bd4d943bfbfafd54f2ed22d62`
- Conversation ID：`agent-conv-0ea3f7cb90b74a1088fbacd989c03878`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=4.0s，first_delta=3.516s
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

- Run ID：`agent-run-a7d056671f82419985acfb715acb4835`
- Conversation ID：`agent-conv-0ea3f7cb90b74a1088fbacd989c03878`
- 状态：`failed`，分数：50，通过：False
- 耗时：completed=119.0s，first_delta=Nones
- 事件：event_count=39，model_delta=0，tool_event=17
- Loop 指标：model_call=7，tool_request_repair=2，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=39，heartbeat_only=False
- 工具链：`scenario.compose_draft, testcase.query_project_cases, scenario.compose_draft`

通过点：
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 草稿更新工具请求包含 include_datasets=true
- 数据集更新未声称保存正式对象

问题：
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 未体现多企业数据集参数化理解

最终回复摘录：

> 

### T08 非测试领域能力边界

- Run ID：`agent-run-694e0f648bc14940b3850ec06ae87edb`
- Conversation ID：`agent-conv-324c604db62f4b8da4614b11dea96e1c`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=17.0s，first_delta=4.11s
- 事件：event_count=80，model_delta=75，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=80，heartbeat_only=False
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

> 抱歉，我的能力边界限定在软件测试、测试自动化和 TestAuto 平台相关场景。情诗创作属于非测试领域，我无法提供。 如果你愿意，我可以帮你把某个测试用例或场景描述得更有诗意（比如用押韵的方式编写用例说明），或者把一段需求描述转成测试场景的结构化草稿。需要这样吗？

## 原始产物

- JSON：`reports\woagent_behavior_eval_20260629_loop_trace_full.json`
- Markdown：`reports\woagent_behavior_eval_20260629_loop_trace_full.md`
