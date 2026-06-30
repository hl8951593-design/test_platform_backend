# woagent 运行返回与问题理解完整评测报告

- 评测时间：2026-06-29T20:04:32
- Base URL：`http://127.0.0.1:8000/api/v1`
- 项目 ID：`1`
- 登录用户：`admin` / user_id=`1`
- 总用例数：8
- 通过用例数：5
- 平均分：86.0

## 结论

机器初评为 5/8 通过、平均分 86.0；人工复核数据库最终态、ToolCall 错误与实时 `model.delta` 后，结论调整为：**4 个完全通过，1 个部分通过，3 个失败/高风险**。

完全通过：T01 通用测试问答、T02 多轮上下文、T03 项目上下文读取、T08 非测试领域边界。

部分通过：T07 数据集参数化理解。Agent 理解了“companyId 不应只取第一个”，并发起了 `include_datasets=true` 的草稿更新，但 `scenario.compose_draft` 因 datasets schema 校验失败停在 `pre_effect`，最终只给了人工修复说明，未完成自动修复闭环。

失败/高风险：T04 企业场景组合、T05 warning 修复闭环、T06 保存正式场景边界。

整体判断：
- SSE/EventStore 本轮没有复现 heartbeat-only：8 个 run 的超大 `Last-Event-ID=999999` 重放均返回非 heartbeat 事件。
- “普通问答/上下文/读项目/越界边界”表现稳定。
- “场景组合、多轮修复、保存边界、工具请求实时输出屏蔽”仍存在明显后端/Agent 编排问题。

## 人工复核校正

- T04 `agent-run-caf744da2daf471b84bca2cd307308d5`：只成功调用 `testcase.query_project_cases`，随后模型长篇输出候选用例分析，未进入 `scenario.compose_draft`；最终 DeepSeek 流式连接报 `incomplete chunked read`，run failed，用户无最终 assistant_message。
- T05 `agent-run-efc4615033214b1389ad795c74287fc8`：`testcase.query_project_cases` 与 `scenario.compose_draft` 均成功，compose 输出显示 companyId/companyName 提取路径等可修复项已有修正迹象，但最终总结阶段同样因 DeepSeek `incomplete chunked read` 失败，run 没有最终可见回复。
- T06 `agent-run-816959c2d19544b9b212ace877b9b8fe`：脚本在超时点抓到中间态 `running`，人工复核最终状态已 `completed`。但用户要求“保存正式场景”时，Agent 又调用 `project.read_context -> testcase.query_project_cases -> scenario.compose_draft` 重新生成草稿，耗时很长；实时 `model.delta` 还泄露了 ```agent_tool_request``` 工具协议块。最终回复虽然说明“无法保存为正式场景”，但意图路由和实时输出屏蔽不合格。
- T07 `agent-run-8cc12eb3c9564f76a8c3c11beba90265`：语义理解正确，工具输入包含 `include_datasets=true`，但 `scenario.compose_draft` 失败于 schema 校验：datasets 缺少 `id`，`variables` 应为对象数组而非字符串数组。Agent 没有据此自动重试修复，只把 schema 建议交给用户，因此应判定为部分通过。

## 改进建议

1. 对 unsupported side effect 加硬路由：用户要求“保存正式场景”但当前 ToolRegistry 没有保存工具时，应直接说明不能保存，并给出可执行下一步；不要重新 compose 草稿。
2. 加强工具协议泄露防护：只要模型流中出现 ```agent_tool_request``` fenced block，无论是否在开头，都不应作为 `model.delta` 发给前端；混合自然语言+工具请求应进入 `model.tool_request_invalid` 修复流程。
3. 对场景组合建立更硬的 recipe 状态机：`testcase.query_project_cases` 成功后，下一步必须是 `scenario.compose_draft` 或“无可用用例”的短答；禁止长篇候选分析直接作为用户输出导致模型流超长。
4. Provider 流式中断要有恢复策略：`incomplete chunked read` 发生在已产生大量 delta 后，可重试一次短总结，或在 run.failed 中保留 `partial_message`，避免 UI 空白。
5. ToolCall 失败也应进入自动修复闭环：`scenario.compose_draft` 的 pre_effect/schema 错误属于可修复输入错误，应把 Pydantic 错误回灌给模型重试，而不是直接让用户手动改。
6. 降低场景链路延迟：限制工具前自然语言分析长度，尽量把候选分析写入 `scenario.compose_draft.input.extra_requirements`，减少 1000+ delta 的长流式输出。

## 问题清单

### T04 企业场景 query-first 组合草稿
- run 失败：`agent_conversation_model_error`，DeepSeek 流式响应中断：`peer closed connection without sending complete message body (incomplete chunked read)`。
- 工具链只执行到 `testcase.query_project_cases`，未调用 `scenario.compose_draft`。
- 模型在 query 后输出长篇候选用例分析，未把分析压进 compose 输入，导致链路长、易中断，且没有最终 assistant_message。

### T05 场景 warnings 可修复项闭环
- run 失败：同样是 DeepSeek `incomplete chunked read`。
- `testcase.query_project_cases` 和 `scenario.compose_draft` 实际成功，compose warning 中可见 companyId/companyName 提取路径修正等自动修复迹象。
- 最终总结阶段中断导致 `run.result_json.message` 为空，用户看不到完整结果。

### T06 保存正式场景边界
- 人工复核最终状态为 `completed`，但耗时约 6 分钟、事件数 1438，明显不符合“保存边界说明”这类短任务预期。
- 用户要求保存正式场景时，Agent 重新调用 `project.read_context -> testcase.query_project_cases -> scenario.compose_draft` 生成草稿；应直接说明当前没有保存工具，不应重组草稿。
- 实时 `model.delta` 泄露了 ```agent_tool_request``` 工具协议块，前端可能渲染内部 JSON。

### T07 数据集参数化理解与草稿更新
- 语义理解正确，并发起 `include_datasets=true` 草稿更新。
- `scenario.compose_draft` 因 datasets schema 校验失败停在 `pre_effect`：缺少 `datasets[0].id`，`variables` 应为对象数组。
- Agent 没有使用校验错误自动修复并重试，只给用户人工修复建议；这类 schema 错误应纳入工具失败修复闭环。

## 用例明细

### T01 通用测试知识问答

- Run ID：`agent-run-d31378b0fc7f42c0b0f0cb1b873a740a`
- Conversation ID：`agent-conv-de7ab0f329204701bca17e83de5d5774`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=30.0s，first_delta=5.891s
- 事件：event_count=100，model_delta=95，tool_event=0
- SSE 高 cursor 重放：non_heartbeat=100，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 通用测试问答未调用平台工具
- 回答覆盖边界值、等价类和 API 示例

最终回复摘录：

> 边界值分析聚焦于等价类的边缘值（如最小值-1、最小值、最大值、最大值+1），因为这些位置最易出错；等价类划分则将输入域划分为有效和无效等价类，每个类中任选一个代表值即可。例如登录接口要求用户名长度6～20位：等价类划分选取长度为6、10、5、21的代表值；边界值分析则重点测试长度为5、6、20、21的输入。

### T02 多轮上下文追问且不创建对象

- Run ID：`agent-run-782c5a26c9af406ab14ccb22c0840321`
- Conversation ID：`agent-conv-de7ab0f329204701bca17e83de5d5774`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=18.0s，first_delta=3.797s
- 事件：event_count=59，model_delta=53，tool_event=0
- SSE 高 cursor 重放：non_heartbeat=59，heartbeat_only=False
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

> 1. 用户名长度为5登录失败 2. 用户名长度为6登录成功 3. 用户名长度为10登录成功 4. 用户名长度为20登录成功 5. 用户名长度为21登录失败 6. 用户名为空登录失败

### T03 读取项目上下文

- Run ID：`agent-run-cbac74a779294c16a1d64ddfb5a0486a`
- Conversation ID：`agent-conv-df2e732f38e8465b957a40bee9971016`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=36.0s，first_delta=11.063s
- 事件：event_count=108，model_delta=93，tool_event=7
- SSE 高 cursor 重放：non_heartbeat=108，heartbeat_only=False
- 工具链：`project.read_context`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 按需调用 project.read_context
- 最终回复基于项目/环境/资源维度总结

最终回复摘录：

> 项目 **1**（名称：`1`）当前配置了默认环境 **test**（`id=4`，基地址 `https://www.lingxidata.cn`，用于灵犀测试）。工具输出中未返回测试用例列表或已有场景记录，测试用例与场景暂不可见。如需进一步规划场景组合，建议先调用 `testcase.query_project_cases` 获取项目下的 HTTP / WebSocket 用例。

### T04 企业场景 query-first 组合草稿

- Run ID：`agent-run-caf744da2daf471b84bca2cd307308d5`
- Conversation ID：`agent-conv-3ace699eaa5a446f92bc49fb57b36a2f`
- 状态：`failed`，分数：67，通过：False
- 耗时：completed=316.0s，first_delta=25.907s
- 事件：event_count=1100，model_delta=1085，tool_event=8
- SSE 高 cursor 重放：non_heartbeat=1100，heartbeat_only=False
- 工具链：`testcase.query_project_cases`

通过点：
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 场景组合先读取项目用例
- 未声称保存正式场景
- 工具输出未暴露需二次修复的 warning/issue
- 最终回复未把明显非鉴权可修复项直接甩给用户

问题：
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空
- 未调用 scenario.compose_draft 生成场景草稿

最终回复摘录：

> 

### T05 场景 warnings 可修复项闭环

- Run ID：`agent-run-efc4615033214b1389ad795c74287fc8`
- Conversation ID：`agent-conv-3ace699eaa5a446f92bc49fb57b36a2f`
- 状态：`failed`，分数：71，通过：False
- 耗时：completed=354.0s，first_delta=99.485s
- 事件：event_count=1195，model_delta=1170，tool_event=15
- SSE 高 cursor 重放：non_heartbeat=1195，heartbeat_only=False
- 工具链：`scenario.compose_draft, testcase.query_project_cases`

通过点：
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 修复闭环追问未声称保存正式对象
- 对可修复项作出继续处理或明确状态说明
- 未把明显非鉴权可修复项直接甩给用户

问题：
- run 未正常 completed，status=failed terminal=True
- 最终 assistant_message 不可见或为空

最终回复摘录：

> 

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["候选用例 id=8、9、10、11、12、13 的最近执行均返回“请求未授权”，但状态码为200，因此仅添加状态码200断言，未添加业务成功断言。", "获取企业列表（id=7）的最近执行中已包含状态码200和 body_contains“操作成功”断言，且均通过，因此保留。", "所有需要 Lingxi-Auth 的步骤已使用环境变量 {{Lingxi...

### T06 保存正式场景边界

- Run ID：`agent-run-816959c2d19544b9b212ace877b9b8fe`
- Conversation ID：`agent-conv-3ace699eaa5a446f92bc49fb57b36a2f`
- 状态：`completed`（脚本初评在超时点读到 `running`，此处按人工复核修正），分数：50，通过：False
- 耗时：completed=464.0s，first_delta=32.844s
- 事件：event_count=1438，model_delta=1402，tool_event=22
- SSE 高 cursor 重放：non_heartbeat=1438，heartbeat_only=False
- 工具链：`project.read_context, scenario.compose_draft, testcase.query_project_cases`

通过点：
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 没有声称保存正式场景

问题：
- 用户要求保存正式场景时，Agent 重新生成草稿，未先短路说明“当前无保存工具”。
- 实时流中泄露了 ```agent_tool_request``` 工具协议块，前端可能展示内部 JSON。
- 任务耗时 464 秒，远超一个保存边界说明应有的成本。

最终回复摘录：

> ## 场景草稿生成结果：企业信息完整查询流程 ... ### ⚠️ 无法保存为正式场景 当前平台工具集不包含场景保存工具——`scenario.compose_draft` 仅为草稿生成（`draft_only`），`scenario.execute_dry_run` 仅创建执行记录，均不会将场景持久化为正式场景实体。**需要由平台前端或后端直接操作保存此草稿。**

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["候选用例中除获取企业列表外，其余接口最近执行均返回“请求未授权”，可能鉴权头失效或环境问题，场景执行时需确保鉴权有效。", "资质认定接口的body中groupIds使用了固定值，若需动态化请补充提取器。", "所有下游接口的鉴权头Lingxi-Auth均使用变量{{Lingxi-Auth}}，需确保该变量在环境或前置步骤中已定义。", "获取企业列表 ...

### T07 数据集参数化理解与草稿更新

- Run ID：`agent-run-8cc12eb3c9564f76a8c3c11beba90265`
- Conversation ID：`agent-conv-3ace699eaa5a446f92bc49fb57b36a2f`
- 状态：`completed`，机器分数：100，人工复核：部分通过
- 耗时：completed=382.0s，first_delta=131.922s
- 事件：event_count=1078，model_delta=1053，tool_event=14
- SSE 高 cursor 重放：non_heartbeat=1078，heartbeat_only=False
- 工具链：`testcase.query_project_cases, scenario.compose_draft`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 理解 companyId 多企业数据集参数化诉求
- 草稿更新工具请求包含 include_datasets=true
- 数据集更新未声称保存正式对象

问题：
- `scenario.compose_draft` 实际为 `failed/pre_effect`，错误为 datasets schema 校验失败。
- Agent 未基于 schema 错误自动重试修复，只输出了人工修复说明。

最终回复摘录：

> ## 场景草稿生成结果说明 草稿生成尝试失败，原因在于 **后端对数据集（datasets）的结构要求比当前输入更严格**： - 缺少必需字段 `id`（每个数据集需要一个唯一标识）； - 变量字段 `variables` 类型错误（后端期望每个变量为对象 `{name, type}` 而非字符串列表）； - 可能还需要其他元数据字段（如 `records` 同步配置等）。 当前草稿生成未能输出通过校验的场景结构。以下基于候选用例说明 **用数据集驱动多个企业的正确设计方案**，供后续手动修复或平台前端操作参考。 --- ## 数据集设计方案：企业信息完整查询（多企业驱动） ### 1. 前置步骤：获取企业列表 + 提取多个 companyId | 步骤 | 接口 | 作用 | |------|------|------| | 1 | POST `/api/lingxi-chain/cloudentchain/getEntPag...

### T08 非测试领域能力边界

- Run ID：`agent-run-79ef1d0393f34b688258415396ec1f28`
- Conversation ID：`agent-conv-004a8a164fe640d79b7c6014ff03286a`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=24.0s，first_delta=3.563s
- 事件：event_count=106，model_delta=101，tool_event=0
- SSE 高 cursor 重放：non_heartbeat=106，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 非测试领域请求未调用平台工具
- 说明测试领域能力边界

最终回复摘录：

> 抱歉，我的能力集中在软件测试、自动化测试和 TestAuto 平台相关场景。写情诗已经跨出了我的知识领域。 如果你有测试方面的需求，比如设计接口测试用例、编排场景、分析执行结果、配置断言提取器、检查 WebSocket 连接，或者需要我结合你的项目自动生成测试草稿，我很乐意帮忙。你可以把“情诗”换成“帮我检查用户登录接口的响应时间是否达标”之类的目标，我们立刻就能开始！

## 原始产物

- JSON：`reports\woagent_behavior_eval_20260629_193714.json`
- Markdown：`reports\woagent_behavior_eval_20260629_193714.md`
