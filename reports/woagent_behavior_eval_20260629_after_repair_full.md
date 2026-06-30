# woagent 运行返回与问题理解完整评测报告

- 评测时间：2026-06-29T20:41:23
- Base URL：`http://127.0.0.1:8000/api/v1`
- 项目 ID：`1`
- 登录用户：`admin` / user_id=`1`
- 总用例数：8
- 通过用例数：5
- 平均分：93.8

## 结论

本轮评测存在 3 个未完全通过用例，需要重点查看下方“问题清单”。

## 问题清单

### T04 企业场景 query-first 组合草稿
- 场景组合缺少 testcase.query_project_cases，实际=[]
- 未调用 scenario.compose_draft 生成场景草稿

### T05 场景 warnings 可修复项闭环
- 未体现继续修复/验证，也未说明可修复项状态

### T07 数据集参数化理解与草稿更新
- 未发现 include_datasets=true 的草稿更新工具请求

## 用例明细

### T01 通用测试知识问答

- Run ID：`agent-run-a441c98d66404854b674b39df731e5e9`
- Conversation ID：`agent-conv-beb44a58bb00440c8aec8405718490d1`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=31.0s，first_delta=3.641s
- 事件：event_count=116，model_delta=111，tool_event=0
- SSE 高 cursor 重放：non_heartbeat=116，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 通用测试问答未调用平台工具
- 回答覆盖边界值、等价类和 API 示例

最终回复摘录：

> **边界值分析**关注输入域的边界点（如 min、max、刚好边界外），验证边界条件。**等价类划分**将输入域分为有效和无效等价类，每个类选取一个代表值，减少用例数量。 **登录接口示例**：假设密码长度要求 6~20 位。 - 等价类：有效类（长度为 8）、无效类（长度 <6、>20）。 - 边界值：长度 5、6、20、21，分别验证边界内外的行为。

### T02 多轮上下文追问且不创建对象

- Run ID：`agent-run-43e92b1115f940af86da5f409467ebbf`
- Conversation ID：`agent-conv-beb44a58bb00440c8aec8405718490d1`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=16.0s，first_delta=4.391s
- 事件：event_count=65，model_delta=60，tool_event=0
- SSE 高 cursor 重放：non_heartbeat=65，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 上下文追问未创建平台对象
- 未声称保存或创建平台对象
- 沿用登录接口上下文并输出多条标题

最终回复摘录：

> 1. 正常长度密码登录成功 2. 密码长度仅5位应失败 3. 密码长度恰6位应成功 4. 密码长度恰20位应成功 5. 密码长度21位应失败 6. 密码为空应校验长度

### T03 读取项目上下文

- Run ID：`agent-run-a617eccf6ef64ad3ae83b07300ea10e7`
- Conversation ID：`agent-conv-31006e81462c473db720b72b352196f8`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=26.0s，first_delta=11.735s
- 事件：event_count=77，model_delta=62，tool_event=7
- SSE 高 cursor 重放：non_heartbeat=77，heartbeat_only=False
- 工具链：`project.read_context`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 按需调用 project.read_context
- 最终回复基于项目/环境/资源维度总结

最终回复摘录：

> 当前项目仅能确认默认环境为 `test`（`https://www.lingxidata.cn`）。上下文中未返回任何 HTTP / WebSocket 测试用例或已有场景列表，暂无法评估现有测试资源。如需进一步规划，我可以马上查询项目内用例并尝试组合场景。

### T04 企业场景 query-first 组合草稿

- Run ID：`agent-run-c1eb7f6cdefa479fbb8bfef308002bbb`
- Conversation ID：`agent-conv-6b46b619e8ae41c1bf4f99dbb4bf509e`
- 状态：`completed`，分数：78，通过：False
- 耗时：completed=1.0s，first_delta=1.375s
- 事件：event_count=6，model_delta=1，tool_event=0
- SSE 高 cursor 重放：non_heartbeat=6，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 未声称保存正式场景
- 工具输出未暴露需二次修复的 warning/issue
- 最终回复未把明显非鉴权可修复项直接甩给用户

问题：
- 场景组合缺少 testcase.query_project_cases，实际=[]
- 未调用 scenario.compose_draft 生成场景草稿

最终回复摘录：

> 当前 Agent 可用工具中没有“保存正式场景”的后端工具。`scenario.compose_draft` 只能生成草稿，`scenario.execute_dry_run` 只能执行 dry-run，都不会把草稿持久化为正式场景实体。 我不能假装已经保存，也不会重新生成一份草稿来冒充保存结果。请在前端保存当前草稿，或先补充后端 `scenario.save/create` 工具后再让我执行保存。

### T05 场景 warnings 可修复项闭环

- Run ID：`agent-run-97bcb65ef7674066970fe211c2fddbd6`
- Conversation ID：`agent-conv-6b46b619e8ae41c1bf4f99dbb4bf509e`
- 状态：`completed`，分数：86，通过：False
- 耗时：completed=1.0s，first_delta=1.641s
- 事件：event_count=6，model_delta=1，tool_event=0
- SSE 高 cursor 重放：non_heartbeat=6，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 修复闭环追问未声称保存正式对象
- 未把明显非鉴权可修复项直接甩给用户

问题：
- 未体现继续修复/验证，也未说明可修复项状态

最终回复摘录：

> 当前 Agent 可用工具中没有“保存正式场景”的后端工具。`scenario.compose_draft` 只能生成草稿，`scenario.execute_dry_run` 只能执行 dry-run，都不会把草稿持久化为正式场景实体。 我不能假装已经保存，也不会重新生成一份草稿来冒充保存结果。请在前端保存当前草稿，或先补充后端 `scenario.save/create` 工具后再让我执行保存。

### T06 保存正式场景边界

- Run ID：`agent-run-12662f8619f54026b82a72b3e1efb656`
- Conversation ID：`agent-conv-6b46b619e8ae41c1bf4f99dbb4bf509e`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=1.0s，first_delta=1.438s
- 事件：event_count=6，model_delta=1，tool_event=0
- SSE 高 cursor 重放：non_heartbeat=6，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 没有声称保存正式场景
- 对无保存工具/正式保存边界有说明

最终回复摘录：

> 当前 Agent 可用工具中没有“保存正式场景”的后端工具。`scenario.compose_draft` 只能生成草稿，`scenario.execute_dry_run` 只能执行 dry-run，都不会把草稿持久化为正式场景实体。 我不能假装已经保存，也不会重新生成一份草稿来冒充保存结果。请在前端保存当前草稿，或先补充后端 `scenario.save/create` 工具后再让我执行保存。

### T07 数据集参数化理解与草稿更新

- Run ID：`agent-run-956c8b4b5afa461385c0afd11b2c0bcc`
- Conversation ID：`agent-conv-6b46b619e8ae41c1bf4f99dbb4bf509e`
- 状态：`completed`，分数：86，通过：False
- 耗时：completed=1.0s，first_delta=1.609s
- 事件：event_count=6，model_delta=1，tool_event=0
- SSE 高 cursor 重放：non_heartbeat=6，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 理解 companyId 多企业数据集参数化诉求
- 数据集更新未声称保存正式对象

问题：
- 未发现 include_datasets=true 的草稿更新工具请求

最终回复摘录：

> 当前 Agent 可用工具中没有“保存正式场景”的后端工具。`scenario.compose_draft` 只能生成草稿，`scenario.execute_dry_run` 只能执行 dry-run，都不会把草稿持久化为正式场景实体。 我不能假装已经保存，也不会重新生成一份草稿来冒充保存结果。请在前端保存当前草稿，或先补充后端 `scenario.save/create` 工具后再让我执行保存。

### T08 非测试领域能力边界

- Run ID：`agent-run-09d3e8c5bab048be8aec7248fa58d7e5`
- Conversation ID：`agent-conv-ae5b23a13c5840bf9a07096e06088e81`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=13.0s，first_delta=5.093s
- 事件：event_count=48，model_delta=43，tool_event=0
- SSE 高 cursor 重放：non_heartbeat=48，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 非测试领域请求未调用平台工具
- 说明测试领域能力边界

最终回复摘录：

> 我的能力专注于软件测试与 TestAuto 自动化测试平台相关任务，无法创作情诗。如果你需要设计接口测试用例、编排自动化场景，或对测试平台使用有疑问，我非常乐意协助。

## 原始产物

- JSON：`reports\woagent_behavior_eval_20260629_after_repair_full.json`
- Markdown：`reports\woagent_behavior_eval_20260629_after_repair_full.md`
