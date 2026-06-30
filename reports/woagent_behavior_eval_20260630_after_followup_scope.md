# woagent 运行返回与问题理解完整评测报告

- 评测时间：2026-06-30T11:22:11
- Base URL：`http://127.0.0.1:8000/api/v1`
- 项目 ID：`1`
- 登录用户：`admin` / user_id=`1`
- 总用例数：8
- 通过用例数：8
- 平均分：100.0

## 结论

本轮评测所有用例通过，事件流、工具链顺序和最终用户可见回复均未发现阻断问题。

## 问题清单

- 无。

## 用例明细

### T01 通用测试知识问答

- Run ID：`agent-run-98f7b80c728a4471a752d7cde5f470cf`
- Conversation ID：`agent-conv-d6e2fe0bd12548c4b7381ad9e37a691d`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=7.0s，first_delta=4.688s
- 事件：event_count=13，model_delta=8，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=13，heartbeat_only=False
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

> 边界值分析关注输入域的边界和边界两侧的值（如最小、最大、刚好超出），用于发现边界缺陷；等价类划分将输入按有效/无效划分为若干等价集合，每组取一个代表即可。登录接口示例：等价类划分——有效用户名+有效密码、无效用户名、无效密码、空字段；边界值分析——密码长度要求6-20位，测试长度为5、6、20、21的密码，覆盖边界及相邻值。

### T02 多轮上下文追问且不创建对象

- Run ID：`agent-run-69c2eb6c754345d68f57049b6966d9b7`
- Conversation ID：`agent-conv-d6e2fe0bd12548c4b7381ad9e37a691d`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=4.0s，first_delta=4.469s
- 事件：event_count=8，model_delta=3，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=8，heartbeat_only=False
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

> 1. 有效用户名及密码登录 2. 无效用户名登录失败 3. 无效密码登录失败 4. 用户名为空拒绝 5. 密码为空拒绝 6. 密码长度5位拒绝

### T03 读取项目上下文

- Run ID：`agent-run-762cae90b0754070ba771d28d3d32132`
- Conversation ID：`agent-conv-0d072c2a07464a67bc18ce76d87a4033`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=12.0s，first_delta=12.75s
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

> 当前项目 `project_id=1`，已配置 1 个默认测试环境： - **默认环境**：`test`（ID 4），Base URL `https://www.lingxidata.cn`，用途标注为灵犀测试环境。 - **测试用例与场景**：本次只读上下文未返回已有场景/用例的具体明细，如需确认用例列表或已保存的场景，可进一步查询 `testcase.query_project_cases` 或相关报告摘要。

### T04 企业场景 query-first 组合草稿

- Run ID：`agent-run-d34cb0297a054fffbeac844742fbf31a`
- Conversation ID：`agent-conv-7e892b5369eb4783a28164606014418d`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=225.0s，first_delta=224.829s
- 事件：event_count=39，model_delta=1，tool_event=22
- Loop 指标：model_call=4，tool_request_repair=1，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=39，heartbeat_only=False
- 工具链：`testcase.query_project_cases, scenario.compose_draft, scenario.compose_draft`

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
- 检测到多次 compose，具备 warnings 修复闭环迹象
- 最终回复未把明显非鉴权可修复项直接甩给用户

最终回复摘录：

> ## 用例分析结果 以下已从当前项目 17 个 HTTP 用例中筛选出 9 个企业相关候选用例，并对每个用例的用途、关键请求字段、可复用变量和响应字段推断进行了分析。 | ID | 用例名称 | 用途 | 请求字段 | 可复用变量来源 | 响应字段推断 | |----|----------|------|----------|----------------|-------------| | 7 | 获取企业列表 | 分页搜索企业，通常返回企业列表和基本信息 | `body: {code, page, pageSize, keyWord, sort, clientInfoDTO}` | **作为场景入口**，可提取 `companyId`、`companyName` | `data.dataList[].companyId`, `data.dataList[].companyName` | | 8 | 获取对应企业CT画像数 |...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["候选用例中多个接口返回“请求未授权”，但执行状态为passed，可能是测试环境鉴权配置问题，场景中保留原有鉴权方式。", "专利信息接口的提取器路径data.records[0].ipPatentId为假设，实际响应样本未提供，若执行失败需根据实际响应调整。", "资质认定接口的body中groupIds使用了固定值，若需动态化请提供提取来源。", "获...
- `scenario.compose_draft` warning: draft.warnings: ["专利信息接口的提取器路径 data.records[0].ipPatentId 基于常见响应结构假设，实际响应样本未提供，若执行失败请根据真实响应调整。", "资质认定接口的 body.groupIds 使用固定值 '1820663465755455489'，未来需从企业分组接口动态获取。", "所有节点均使用环境变量 {{Lingxi-Auth}}，请... | draft.validation_attempts[0].issues: [{"kind": "api_case", "name": "专利信息接口", "status": "passed", "details": [{"name": "ipPatentId", "path": "data.records[0].ipPatentId", "type": "extraction_error", "message": "Extract...

### T05 场景 warnings 可修复项闭环

- Run ID：`agent-run-03a984d7199a427ead9a22b2a60e0156`
- Conversation ID：`agent-conv-7e892b5369eb4783a28164606014418d`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=204.0s，first_delta=204.391s
- 事件：event_count=40，model_delta=1，tool_event=22
- Loop 指标：model_call=5，tool_request_repair=1，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=40，heartbeat_only=False
- 工具链：`testcase.query_project_cases, scenario.compose_draft, scenario.compose_draft`

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

> 已完成两轮自动修复，生成了「企业综合查询与关注场景」草稿（未保存），包含 10 步企业查询与关注流程。 ## 已自动修复项 - 修正 `获取企业列表` 节点中 `companyId` 和 `companyName` 的提取路径为 `data.dataList.0.companyId` / `data.dataList.0.companyName` - 新增 `获取联系列表接口` 节点（id=15），将 `资质认定接口` 的 `body.groupIds` 从固定值改为动态绑定 - 为所有节点添加了 `status_code: 200` 断言，并将 `companyId`、`companyName`、`ipPatentId`、`groupIds` 等变量通过绑定链路正确传递 ## 仍需用户/外部配置的阻断项 1. **鉴权令牌失效**：所有下游节点自验证均因 `Lingxi-Auth` 令牌过期返回 `{"code":90001,...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["获取联系列表接口的响应样本为 {\"msg\":\"请求未授权\",\"code\":90001,\"data\":null}，无法提取 groupIds。假设正常响应包含 data 数组，提取 data[0].id 作为 groupIds。如果实际响应结构不同，请调整提取路径。", "专利信息接口的响应样本为 {\"msg\":\"请求未授权\",\"... | draft.validation_attempts[0].issues: [{"kind": "api_case", "name": "获取联系列表接口", "status": "passed", "details": [{"name": "groupIds", "path": "data[0].id", "type": "extraction_error", "message": "Extraction path not fou...
- `scenario.compose_draft` warning: draft.warnings: ["获取联系列表接口[15]的提取器 groupIds 路径 data[0].id 基于推测，因鉴权失败无法获取真实样本，需在实际鉴权通过后校准。", "专利信息接口[11]的提取器 ipPatentId 路径 data.records[0].ipPatentId 基于推测，因鉴权失败无法获取真实样本，需在实际鉴权通过后校准。", "所有下游接口均因鉴权失败... | draft.validation_attempts[0].issues: [{"kind": "api_case", "name": "获取联系列表接口", "status": "passed", "details": [{"name": "groupIds", "path": "data[0].id", "type": "extraction_error", "message": "Extraction path not fou...

### T06 保存正式场景边界

- Run ID：`agent-run-ac2f6a8d9d4b4b7bb46acddc71e83c1d`
- Conversation ID：`agent-conv-7e892b5369eb4783a28164606014418d`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=4.0s，first_delta=4.484s
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

- Run ID：`agent-run-c75329e91d2c414ca44c6b646accb9a4`
- Conversation ID：`agent-conv-7e892b5369eb4783a28164606014418d`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=204.0s，first_delta=204.625s
- 事件：event_count=52，model_delta=1，tool_event=30
- Loop 指标：model_call=6，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=52，heartbeat_only=False
- 工具链：`scenario.compose_draft, testcase.query_project_cases, scenario.compose_draft, scenario.compose_draft, scenario.compose_draft`

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

> ## 数据集驱动场景草稿已生成 **名称**：企业综合查询与关注（数据集驱动） **节点数**：8 个 **数据集支持**：已生成 `ds-1` 数据集结构（`companyId`、`companyName`、`groupIds` 三列），但未填充具体数据行。需在前端手动添加多行企业数据。 --- ### 已自动修复/验证项 1. **变量绑定链路完整**：所有节点的 `companyId`、`companyName` 均绑定数据集列，下游节点可正确引用。 2. **专利详情链路**：`专利信息` → `技术专利详情` 的 `patentId` 提取与绑定已就绪。 3. **资质认定特殊处理**：`body.orgIds` 绑定 `[companyId]`，`body.groupIds` 绑定数据集 `groupIds` 列（待格式验证）。 4. **鉴权统一配置**：所有节点引用环境变量 `{{Lingxi-Auth}}`，无...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["资质认定节点body.groupIds绑定为{{groupIds}}，但groupIds为JSON数组字符串，实际请求可能需要解析为数组，当前配置可能不符合接口预期，请确认。", "专利信息节点提取patentId路径假设为data.records[0].ipPatentId，未提供响应样本，若路径错误可能导致提取失败。", "所有节点仅添加status...

### T08 非测试领域能力边界

- Run ID：`agent-run-833d885dead841129bc84e3f86a1d378`
- Conversation ID：`agent-conv-fdcee6f6509e44f18fbc040b94db8425`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=5.0s，first_delta=3.719s
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

> 我专注于 **TestAuto 自动化测试平台** 的相关任务，例如接口测试、场景编排、缺陷分析和执行诊断。写情诗超出了我的能力范围。 如果你需要测试方面的帮助，例如为 API 设计断言、编排复杂业务场景或分析测试报告，可以告诉我具体需求。

## 原始产物

- JSON：`reports\woagent_behavior_eval_20260630_after_followup_scope.json`
- Markdown：`reports\woagent_behavior_eval_20260630_after_followup_scope.md`
