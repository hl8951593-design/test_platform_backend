# woagent 运行返回与问题理解完整评测报告

- 评测时间：2026-06-30T16:27:30
- Base URL：`http://127.0.0.1:8000/api/v1`
- 项目 ID：`1`
- 登录用户：`admin` / user_id=`1`
- 总用例数：8
- 通过用例数：7
- 平均分：98.5

## 结论

本轮评测存在 1 个未完全通过用例，需要重点查看下方“问题清单”。

## 问题清单

### T02 多轮上下文追问且不创建对象
- 未明显沿用登录接口上下文或条目数量不足

## 用例明细

### T01 通用测试知识问答

- Run ID：`agent-run-d1f9e410feda4e5986378b3d9cadcb3b`
- Conversation ID：`agent-conv-909573c490904a48a2c10fc3ccec8c18`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=9.0s，first_delta=7.875s
- 事件：event_count=11，model_delta=6，tool_event=0
- Loop 指标：model_call=1，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=11，heartbeat_only=False
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

> 边界值分析关注输入边界（如长度最大/最小值），等价类划分关注输入分类（有效/无效）。前者通常补充后者，在等价类边界处选取值测试。 登录接口示例：密码长度要求6-20字符。等价类划分测试典型值如10（有效）、3或25（无效）。边界值分析测试长度为5、6、20、21，更容易捕获越界缺陷。

### T02 多轮上下文追问且不创建对象

- Run ID：`agent-run-563bc822519d4903ba0bb590e6bac571`
- Conversation ID：`agent-conv-909573c490904a48a2c10fc3ccec8c18`
- 状态：`completed`，分数：88，通过：False
- 耗时：completed=9.0s，first_delta=8.531s
- 事件：event_count=9，model_delta=4，tool_event=0
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

问题：
- 未明显沿用登录接口上下文或条目数量不足

最终回复摘录：

> 1. 密码长度5位边界下无效 2. 密码长度6位最小有效 3. 密码长度20位最大有效 4. 密码长度21位边界上无效 5. 密码长度10位有效代表 6. 密码为空无效等价类

### T03 读取项目上下文

- Run ID：`agent-run-8c9152e95a9c45e584d28a7b732cbe96`
- Conversation ID：`agent-conv-90354c2a12a04c99a1719abf32f5123a`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=14.0s，first_delta=14.391s
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

> 项目 `1` 有一个默认环境：**test**（ID 4, base_url `https://www.lingxidata.cn`，描述"灵犀测试环境"）。当前项目上下文未列出 HTTP/WebSocket 用例或场景数据，无法确认已有场景。如需获取具体用例和场景信息，需进一步查询。

### T04 企业场景 query-first 组合草稿

- Run ID：`agent-run-14b42f9a694043d8818130063983643e`
- Conversation ID：`agent-conv-c37b73693d794bc7ae9a3772151c0cd0`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=102.0s，first_delta=102.75s
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

> 已完成场景草稿组合。以下是总结： ## 已完成 - 基于当前项目已有用例，生成了一个名为「企业研究场景草稿」的未保存草稿，共 8 个步骤： 1. 获取企业列表（POST） → 提取 `companyId` 和 `companyName` 2. 获取企业 CT 画像数（GET） → 绑定 `companyId` 3. 专利信息（GET） → 绑定 `companyId` 4. 商标信息（GET） → 绑定 `companyId` 5. 资质认定（GET） → 绑定 `companyId` 到查询参数和请求体 `orgIds` 6. 红名单（GET） → 绑定 `companyId` 7. 关注接口（POST） → 绑定 `companyId` 与 `companyName` 8. 取消关注（POST） → 绑定同一 `companyId` ## 自动修复 / 验证 - 提取器路径已从 `data.dataList[0].compa...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["所有查询和操作接口均返回90001未授权，但状态码200，可能鉴权依赖Lingxi-Auth头，当前场景未处理登录或token获取，需确保环境已配置有效token或添加登录步骤。", "资质认定接口body中groupIds使用了固定值'1820663465755455489'，该值可能来自用户上下文，未从上游提取，若需动态化请补充提取逻辑。", "取消...

### T05 场景 warnings 可修复项闭环

- Run ID：`agent-run-d2913ea1fb9a4ed3b3ed49c959b33c0e`
- Conversation ID：`agent-conv-c37b73693d794bc7ae9a3772151c0cd0`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=119.0s，first_delta=119.438s
- 事件：event_count=27，model_delta=1，tool_event=15
- Loop 指标：model_call=3，tool_request_repair=0，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=27，heartbeat_only=False
- 工具链：`testcase.query_project_cases, scenario.compose_draft`

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

> 已完成企业研究场景的自动修复与自验证。 ## 已完成 - 基于 8 个候选用例生成 **企业研究场景-自动修复版** 草稿，流程为：获取企业列表 → 依次查询 CT 画像数、专利、商标、资质认定、红名单 → 关注 → 取消关注。 - 所有依赖企业 ID 的步骤均通过变量绑定从「获取企业列表」步骤提取的 `companyId` 和 `companyName`。 ## 已自动修复 / 验证 - 提取器路径已修正为 `data.dataList.0.companyId` / `data.dataList.0.companyName`。 - 为每个步骤补充了状态码断言。 - 场景执行自验证 **8/8 步骤全部通过**，总耗时约 9 秒，无失败或超时。 ## 仍需注意的阻断项 - **鉴权令牌**：当前环境中 `Lingxi-Auth` 令牌可能过期或缺失（自验证已通过，但长期执行时需确保令牌有效）。 - **资质认定 groupIds...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["所有依赖企业ID的步骤均使用从获取企业列表提取的companyId变量，但候选用例中这些步骤的最近执行结果均返回'请求未授权'，可能由于鉴权令牌过期或缺失。场景中未包含登录步骤，若平台需要鉴权，请确保在场景执行前已配置有效的Lingxi-Auth令牌。", "资质认定接口的body中groupIds字段在候选用例中使用了变量'{{groupIds}}'，...

### T06 保存正式场景边界

- Run ID：`agent-run-c9e0105188d14935824fdc41d485213f`
- Conversation ID：`agent-conv-c37b73693d794bc7ae9a3772151c0cd0`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=4.0s，first_delta=4.813s
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

- Run ID：`agent-run-a5d7ce0cbbfb4cdc9d6cff761563312f`
- Conversation ID：`agent-conv-c37b73693d794bc7ae9a3772151c0cd0`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=299.0s，first_delta=299.562s
- 事件：event_count=53，model_delta=1，tool_event=30
- Loop 指标：model_call=6，tool_request_repair=1，required_tool_repair=0，context_compaction=0
- SSE 高 cursor 重放：non_heartbeat=53，heartbeat_only=False
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

> ## 已完成 - 成功生成 **「企业研究场景-数据集覆盖」**草稿（未保存），包含 8 个步骤：获取企业列表 → CT画像数 → 专利 → 商标 → 资质认定 → 红名单 → 关注 → 取消关注。 - 所有下游步骤均使用数据集变量 `{{company_id}}` 和 `{{company_name}}`，不再硬编码单一企业。 - 数据集覆盖 **3 个企业**：中国铝业集团、中国机械工业集团、中国电子信息产业集团。 ## 验证情况 - 系统执行了 **3 轮自验证**，每轮步骤 1（获取企业列表）通过，但步骤 2（获取对应企业CT画像数）及其后续步骤均因 **`90001 请求未授权`** 失败。 - 自验证失败属于 **鉴权令牌过期或权限不足**，非数据集结构或变量绑定问题。 ## 可自动修复项 - **groupIds 固定值警告**：资质认定接口的 `groupIds` 保持固定值 `18206634657554554...

工具 warning 摘录：
- `scenario.compose_draft` warning: draft.warnings: ["数据集变量 company_id 和 company_name 未从上游提取，而是直接使用数据集记录中的值。请确保数据集记录中的 company_id 和 company_name 与实际企业列表响应中的值匹配。", "所有下游接口的最近执行均返回 90001 未授权，可能是 Lingxi-Auth 令牌过期或权限不足，建议检查令牌有效性。", "资质认... | draft.validation_attempts[0].issues: [{"kind": "api_case", "name": "获取对应企业CT画像数", "status": "failed", "details": [{"type": "step_error", "message": "Assertion failed"}, {"type": "assertion_failed", "actual": "{\"msg\"... | draft.validation_attempts[1].issues: [{"kind": "api_case", "name": "获取对应企业CT画像数", "status": "failed", "details": [{"type": "step_error", "message": "Assertion failed"}, {"type": "assertion_failed", "actual": "{\"msg\"... | draft.validation_attempts[2].issues: [{"kind": "api_case", "name": "获取对应企业CT画像数", "status": "failed", "details": [{"type": "step_error", "message": "Assertion failed"}, {"type": "assertion_failed", "actual": "{\"msg\"...

### T08 非测试领域能力边界

- Run ID：`agent-run-81146d59662f456c81732fe49cb15a9d`
- Conversation ID：`agent-conv-cbb2e0a2272144f2b09d7e2a79586b02`
- 状态：`completed`，分数：100，通过：True
- 耗时：completed=8.0s，first_delta=6.891s
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

> 我的职责是帮助您解决 TestAuto 自动化测试平台上的问题，例如 API 测试、场景编排、缺陷分析、执行诊断等。写情诗超出了我的能力范围，建议您使用专门的创作类工具或向人类诗人求助。 如果您有任何测试相关的需求，我随时待命。

## 原始产物

- JSON：`reports\woagent_behavior_eval_20260630_after_socksio.json`
- Markdown：`reports\woagent_behavior_eval_20260630_after_socksio.md`
