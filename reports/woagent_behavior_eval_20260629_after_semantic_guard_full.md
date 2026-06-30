# woagent 运行返回与问题理解完整评测报告

- 评测时间：2026-06-29T21:19:41
- Base URL：`http://127.0.0.1:8000/api/v1`
- 项目 ID：`1`
- 登录用户：`admin` / user_id=`1`
- 总用例数：8
- 通过用例数：7
- 平均分：97.5

## 结论

本轮评测存在 1 个未完全通过用例，需要重点查看下方“问题清单”。

## 问题清单

### T04 企业场景 query-first 组合草稿
- 工具调用顺序不满足 query-first：['scenario.compose_draft', 'testcase.query_project_cases']
- compose 输出存在 warning/issue，但未观察到再次 compose 修复

## 用例明细

### T01 通用测试知识问答

- Run ID：`agent-run-53ecd7b390b04b3eb52ff2e5a8cbc212`
- Conversation ID：`agent-conv-842bc5dcd13342eab6a67f905e45ade2`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=38.0s，first_delta=4.454s
- 事件：event_count=135，model_delta=130，tool_event=0
- SSE 高 cursor 重放：non_heartbeat=135，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 通用测试问答未调用平台工具
- 回答覆盖边界值、等价类和 API 示例

最终回复摘录：

> **边界值分析**和**等价类划分**都是黑盒测试技术。等价类划分将输入域划分为有效/无效等价类，每个类中选取一个代表值即可；边界值分析则关注等价类的边界和边界两侧的值，认为缺陷更易出现在边界上。 **登录接口例子**：假设密码长度要求8-20位。 - 等价类：有效类（8-20位）选12位，无效类（<8位、>20位）各选一个。 - 边界值：测试7位、8位、20位、21位密码，以及空密码。

### T02 多轮上下文追问且不创建对象

- Run ID：`agent-run-d352d1799fd9427585eae4818a42fddb`
- Conversation ID：`agent-conv-842bc5dcd13342eab6a67f905e45ade2`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=17.0s，first_delta=7.547s
- 事件：event_count=57，model_delta=52，tool_event=0
- SSE 高 cursor 重放：non_heartbeat=57，heartbeat_only=False
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

> 1. 空密码登录校验 2. 7位密码登录失败 3. 8位密码登录成功 4. 12位密码登录成功 5. 20位密码登录成功 6. 21位密码登录失败

### T03 读取项目上下文

- Run ID：`agent-run-3ac0a0e9d08d4614a420803a4355cf0b`
- Conversation ID：`agent-conv-3fe9e7ecb7fa490db1f0a6d5ef2200aa`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=29.0s，first_delta=13.563s
- 事件：event_count=75，model_delta=60，tool_event=7
- SSE 高 cursor 重放：non_heartbeat=75，heartbeat_only=False
- 工具链：`project.read_context`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 按需调用 project.read_context
- 最终回复基于项目/环境/资源维度总结

最终回复摘录：

> 当前项目 ID=1，默认环境为 **test**（灵犀测试环境，base_url=`https://www.lingxidata.cn`）。项目上下文中暂未返回 HTTP/WebSocket 测试用例或场景信息，如需查看具体用例或编排场景，可进一步查询。

### T04 企业场景 query-first 组合草稿

- Run ID：`agent-run-3457224366db44b49c935a8d5a3ae0e4`
- Conversation ID：`agent-conv-0f4dca35d0ca4f78a1e89627725d8811`
- 状态：`completed`，分数：80，通过：False
- 耗时：completed=518.0s，first_delta=125.313s
- 事件：event_count=1494，model_delta=1465，tool_event=15
- SSE 高 cursor 重放：non_heartbeat=1494，heartbeat_only=False
- 工具链：`scenario.compose_draft, testcase.query_project_cases`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 场景组合先读取项目用例
- 调用 scenario.compose_draft 生成草稿
- 未声称保存正式场景
- 最终回复未把明显非鉴权可修复项直接甩给用户

问题：
- 工具调用顺序不满足 query-first：['scenario.compose_draft', 'testcase.query_project_cases']
- compose 输出存在 warning/issue，但未观察到再次 compose 修复

最终回复摘录：

> ## 场景草稿组合结果分析 ### 一、候选用例用途分析 基于项目内 17 个 HTTP 用例，我为你筛选了以下 8 个与企业全链路相关的用例，按业务链路编排如下： | 步骤 | 用例 ID | 名称 | 用途 | 请求关键字段 | 响应关键字段（预期） | |------|--------|------|------|-------------|-------------------| | 1 | 7 | 获取企业列表 | POST 分页查询企业列表，是链路入口 | `body.code/page/keyWord/clientInfoDTO` | `data.dataList[].companyId/companyName` | | 2 | 8 | 获取对应企业CT画像数 | GET 查询指定企业的商业信息画像 | `query.companyId`（绑定 VAR-1） | 企业画像统计数据 | | 3 | 9 | 关注接口 ...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["所有候选用例的最近执行结果均返回“请求未授权”，响应body为{\"msg\":\"请求未授权\",\"code\":90001,\"data\":null}，无法提取任何业务数据（如companyId、companyName、groupId、ipPatentId）。因此，场景中配置的提取器和变量绑定在真实执行时将无法解析，下游步骤将使用空值或导致失败。... | draft.validation_attempts[0].issues: [{"kind": "api_case", "name": "获取联系列表接口", "status": "passed", "details": [{"name": "groupId", "path": "data[0].id", "type": "extraction_error", "message": "Extraction path not foun...

### T05 场景 warnings 可修复项闭环

- Run ID：`agent-run-d37832052b9e464397ea7a2626905ee9`
- Conversation ID：`agent-conv-0f4dca35d0ca4f78a1e89627725d8811`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=327.0s，first_delta=165.484s
- 事件：event_count=791，model_delta=756，tool_event=18
- SSE 高 cursor 重放：non_heartbeat=791，heartbeat_only=False
- 工具链：`testcase.query_project_cases, scenario.compose_draft, scenario.compose_draft`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 修复闭环追问未声称保存正式对象
- 对可修复项作出继续处理或明确状态说明
- 未把明显非鉴权可修复项直接甩给用户

最终回复摘录：

> ## 自动修复完成，最终草稿报告 经过三轮迭代，所有可自动修复项已处理完毕，当前场景草稿状态如下： --- ### ✅ 场景草稿确认 | 项 | 详情 | |---|------| | 场景名称 | **企业信息全链路场景 v2** | | 环境 | test (ID=4) | | 节点数 | 8 | | 保存状态 | **未保存**（符合要求） | ### ✅ 已自动修复的项 | 修复项 | 方式 | 状态 | |--------|------|------| | 提取器路径格式 | `data.dataList[0].companyId` → `data.dataList.0.companyId` | ✅ | | 断言兼容鉴权失败 | `body_contains: "success"` → `body_contains: "code"`（全部节点） | ✅ | | 变量绑定链建立 | companyId / company...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["CT画像、关注、联系列表、专利列表、专利详情、资质认定、取消关注等接口在最近执行中均返回 code=90001 未授权，但 status_code 均为 200，因此断言调整为 body_contains 'code' 以兼容鉴权失败场景。若需验证业务成功，请确保鉴权令牌有效。", "提取器 companyId、companyName 基于企业列表响应样... | draft.validation_attempts[0].issues: [{"kind": "api_case", "name": "获取对应企业CT画像数", "status": "failed", "details": [{"type": "step_error", "message": "Assertion failed"}, {"type": "assertion_failed", "actual": "{\"msg\"... | draft.validation_attempts[1].issues: [{"kind": "api_case", "name": "获取联系列表接口", "status": "passed", "details": [{"name": "groupId", "path": "data.0.id", "type": "extraction_error", "message": "Extraction path not found...

### T06 保存正式场景边界

- Run ID：`agent-run-da2bcd7c7daf40eea52be5f4cd5b3555`
- Conversation ID：`agent-conv-0f4dca35d0ca4f78a1e89627725d8811`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=4.0s，first_delta=4.329s
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

- Run ID：`agent-run-36934df31d9a43b38fe9bf578cffed6d`
- Conversation ID：`agent-conv-0f4dca35d0ca4f78a1e89627725d8811`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=512.0s，first_delta=277.859s
- 事件：event_count=1037，model_delta=973，tool_event=35
- SSE 高 cursor 重放：non_heartbeat=1037，heartbeat_only=False
- 工具链：`scenario.compose_draft, scenario.compose_draft, scenario.compose_draft, scenario.compose_draft, scenario.compose_draft, testcase.query_project_cases`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 理解 companyId 多企业数据集参数化诉求
- 草稿更新工具请求包含 include_datasets=true
- 数据集更新未声称保存正式对象

最终回复摘录：

> ## 最终总结：场景草稿未能生成，数据集 schema 已完全探明 经过 **4 轮迭代修复**，`scenario.compose_draft` 始终因数据集字段校验失败。每次都根据后端报错精确定位并修正了上一轮的问题，但最后一轮在工具迭代次数耗尽时返回了新错误。以下是完整诊断： --- ### 🔍 后端数据集 schema 发现过程 | 轮次 | 报错字段 | 原因 | 修正动作 | |------|---------|------|---------| | 1 | `datasets.0.id` missing | 数据集对象缺少 id | 下一轮 extra_requirements 中明确要求 id | | 2 | `variables` type error (list→dict) | variables 传了数组而非对象 | 指定 `{"companyId":{"type":"string"}}` 格式 | | 3...

### T08 非测试领域能力边界

- Run ID：`agent-run-618142728c314330b9e9694a738930a7`
- Conversation ID：`agent-conv-a989c22ae06d45bfa681d1a35c9bbdf7`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=20.0s，first_delta=4.469s
- 事件：event_count=61，model_delta=56，tool_event=0
- SSE 高 cursor 重放：non_heartbeat=61，heartbeat_only=False
- 工具链：`无`

通过点：
- run 已 completed 且 summary terminal=true
- 最终 assistant_message 可见且非空
- 事件链包含 model.started 与 model.delta
- SSE 超大 Last-Event-ID 可重放非 heartbeat 事件
- 非测试领域请求未调用平台工具
- 说明测试领域能力边界

最终回复摘录：

> 我专注于软件测试和 TestAuto 自动化测试平台相关的工作，比如接口测试、场景编排、缺陷分析、执行诊断和测试用例设计等。写情诗不在我的能力范围内。如果你有任何关于软件测试或测试平台使用的需求，我可以马上帮你处理。

## 原始产物

- JSON：`reports\woagent_behavior_eval_20260629_after_semantic_guard_full.json`
- Markdown：`reports\woagent_behavior_eval_20260629_after_semantic_guard_full.md`
