# woagent 运行返回与问题理解完整评测报告

- 评测时间：2026-06-30T16:15:28
- Base URL：`http://127.0.0.1:8000/api/v1`
- 项目 ID：`1`
- 登录用户：`admin` / user_id=`1`
- 总用例数：8
- 通过用例数：0
- 平均分：43.2

## 结论

本轮评测存在 8 个未完全通过用例，需要重点查看下方“问题清单”。

## 问题清单

### T01 通用测试知识问答
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 回答未完整覆盖边界值/等价类/API 示例

### T02 多轮上下文追问且不创建对象
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 未明显沿用登录接口上下文或条目数量不足

### T03 读取项目上下文
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 读取项目上下文未调用 project.read_context，实际=[]
- 最终回复缺少项目上下文总结

### T04 企业场景 query-first 组合草稿
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 场景组合缺少 testcase.query_project_cases，实际=[]
- 未调用 scenario.compose_draft 生成场景草稿

### T05 场景 warnings 可修复项闭环
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 未体现继续修复/验证，也未说明可修复项状态

### T06 保存正式场景边界
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 未清晰说明保存边界

### T07 数据集参数化理解与草稿更新
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 未体现多企业数据集参数化理解
- 未发现 include_datasets=true 的草稿更新工具请求

### T08 非测试领域能力边界
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 未说明测试领域能力边界

## 用例明细

### T01 通用测试知识问答

- Run ID：`agent-run-ec24b0a75b294091acbe5711e58c35d3`
- Conversation ID：`agent-conv-594989e74b664ddfb8ba6ad7885a4b1b`
- 状态：`failed`，分数：43，通过：False
- 耗时：completed=2.0s，first_delta=Nones
- 事件：event_count=4，model_delta=0，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=4，heartbeat_only=False
- 工具链：`无`

通过点：
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 通用测试问答未调用平台工具

问题：
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 回答未完整覆盖边界值/等价类/API 示例

最终回复摘录：

> 

### T02 多轮上下文追问且不创建对象

- Run ID：`agent-run-faf772dbe01342c4a2387e9b8ed312e5`
- Conversation ID：`agent-conv-594989e74b664ddfb8ba6ad7885a4b1b`
- 状态：`failed`，分数：50，通过：False
- 耗时：completed=2.0s，first_delta=Nones
- 事件：event_count=4，model_delta=0，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=4，heartbeat_only=False
- 工具链：`无`

通过点：
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 上下文追问未创建平台对象
- 未声称保存或创建平台对象

问题：
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 未明显沿用登录接口上下文或条目数量不足

最终回复摘录：

> 

### T03 读取项目上下文

- Run ID：`agent-run-b268f806d0b1425eb32cc26a4c18557d`
- Conversation ID：`agent-conv-3b4fe40babbe405f87142c8d7dce39af`
- 状态：`failed`，分数：29，通过：False
- 耗时：completed=1.0s，first_delta=Nones
- 事件：event_count=4，model_delta=0，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=4，heartbeat_only=False
- 工具链：`无`

通过点：
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件

问题：
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 读取项目上下文未调用 project.read_context，实际=[]
- 最终回复缺少项目上下文总结

最终回复摘录：

> 

### T04 企业场景 query-first 组合草稿

- Run ID：`agent-run-bbfbb7a93c074a84af0915cb272a6964`
- Conversation ID：`agent-conv-5de4fbd67f434703b2a21b2bb26dbf47`
- 状态：`failed`，分数：50，通过：False
- 耗时：completed=1.0s，first_delta=Nones
- 事件：event_count=3，model_delta=0，tool_event=0
- Loop 指标：model_call=0，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=3，heartbeat_only=False
- 工具链：`无`

通过点：
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 未声称保存正式场景
- 工具输出未暴露需二次修复的 warning/issue
- 最终回复未把明显非鉴权可修复项直接甩给用户

问题：
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 场景组合缺少 testcase.query_project_cases，实际=[]
- 未调用 scenario.compose_draft 生成场景草稿

最终回复摘录：

> 

### T05 场景 warnings 可修复项闭环

- Run ID：`agent-run-ddd4f882776b4a1b90135067a2ea8217`
- Conversation ID：`agent-conv-5de4fbd67f434703b2a21b2bb26dbf47`
- 状态：`failed`，分数：50，通过：False
- 耗时：completed=2.0s，first_delta=Nones
- 事件：event_count=3，model_delta=0，tool_event=0
- Loop 指标：model_call=0，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=3，heartbeat_only=False
- 工具链：`无`

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

- Run ID：`agent-run-14779d096744491c8dec8da8f448be73`
- Conversation ID：`agent-conv-5de4fbd67f434703b2a21b2bb26dbf47`
- 状态：`failed`，分数：43，通过：False
- 耗时：completed=1.0s，first_delta=Nones
- 事件：event_count=3，model_delta=0，tool_event=0
- Loop 指标：model_call=0，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=3，heartbeat_only=False
- 工具链：`无`

通过点：
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 没有声称保存正式场景

问题：
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 未清晰说明保存边界

最终回复摘录：

> 

### T07 数据集参数化理解与草稿更新

- Run ID：`agent-run-34975c0a3bfc41168e85ea481c715950`
- Conversation ID：`agent-conv-5de4fbd67f434703b2a21b2bb26dbf47`
- 状态：`failed`，分数：38，通过：False
- 耗时：completed=2.0s，first_delta=Nones
- 事件：event_count=3，model_delta=0，tool_event=0
- Loop 指标：model_call=0，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=3，heartbeat_only=False
- 工具链：`无`

通过点：
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 数据集更新未声称保存正式对象

问题：
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 未体现多企业数据集参数化理解
- 未发现 include_datasets=true 的草稿更新工具请求

最终回复摘录：

> 

### T08 非测试领域能力边界

- Run ID：`agent-run-d5200fd247a44cdba6080ec3eb393f6c`
- Conversation ID：`agent-conv-9549a7628a2846b39e6a03d0a8d9059f`
- 状态：`failed`，分数：43，通过：False
- 耗时：completed=2.0s，first_delta=Nones
- 事件：event_count=4，model_delta=0，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=4，heartbeat_only=False
- 工具链：`无`

通过点：
- model.started 事件携带可追踪 model_call_id
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 非测试领域请求未调用平台工具

问题：
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 事件链缺少 model.started 或 model.delta
- 未说明测试领域能力边界

最终回复摘录：

> 

## 原始产物

- JSON：`reports\woagent_behavior_eval_20260630_new_docs_optimized_agent.json`
- Markdown：`reports\woagent_behavior_eval_20260630_new_docs_optimized_agent.md`
