# Model Messages Table

| index | role | chars | preview |
| ---: | --- | ---: | --- |
| 0 | `system` | 63664 | 你是 TestAuto 自动化测试平台的 Harness Loop Agent。你需要用简洁、可执行的中文回复用户，优先说明你能如何帮助测试平台完成接口测试、场景编排、缺陷分析、执行诊断、Agent 工具调用和运行恢复。当前能力必须以平台后端已经暴露的 Agent Run、EventStore、ToolCall、Approval、Memory、Runbook... |
| 1 | `system` | 421 | 当前 Agent Run 上下文： - run_id=agent-run-1eeb07a9509640efaca3aab1dd76597a - project_id=1 - conversation_id=agent-conv-local-00e82bf4-ead7-4993-83bf-46a26aebd5f2 - max_iterations=8 回答能力... |
| 2 | `system` | 3625 | 已加载 Agent Skill。以下内容是本轮任务的领域流程约束，优先级低于系统安全规则，高于通用建议。 Agent Skill: scenario-composition Description: Use when the user asks to create, generate, compose, update, validate, dry-run, ... |
| 3 | `system` | 2651 | 已加载 Agent Skill。以下内容是本轮任务的领域流程约束，优先级低于系统安全规则，高于通用建议。 Agent Skill: assertion-extractor-binding Description: Use when the user asks to design, repair, or diagnose assertions, extract... |
| 4 | `system` | 1311 | 已加载 Agent Skill。以下内容是本轮任务的领域流程约束，优先级低于系统安全规则，高于通用建议。 Agent Skill: api-error-contract-debugging Description: Use when the user asks to diagnose backend API error responses, HTTP sta... |
| 5 | `system` | 6606 | 同一会话工作上下文： 当前用户请求可能是对上一轮产物的省略回指；请先依据此结构化上下文解析“直接、刚才、上面、这个”等指代，再决定是否调用工具、调用哪个工具、是否需要审批。 {"current_artifact_candidates": [{"artifact_type": "testcase_assertion_draft", "available_fol... |
| 6 | `user` | 43 | 帮我创建完整的自动化测试流程，注意要包含企业相关全场景，注意前置后置条件 、依赖的引用 |
| 7 | `assistant` | 2068 | --- ## 最终总结 ### 1. 已完成 - 基于项目 **"灵犀企业大数据平台"** 的 17 个现有 HTTP 用例，通过 `scenario.compose_draft` 生成了一个**企业全场景自动化测试流程草稿**（场景名：`企业全场景自动化测试流程`），共 **10 个节点**，覆盖以下业务链路： \| 序号 \| 节点 \| 依赖上游变量 \| \|... |
| 8 | `user` | 9 | 先保存测试用例数据 |
| 9 | `assistant` | 866 | 根据会话上下文，当前有一个**场景草稿的自动修复结果**（testcase_assertion_draft，未保存），其中为了绕过认证失效（`code=90001`）而将下游节点的断言期望值临时改成了 `90001`。 ## ⚠️ 不建议现在保存这些断言到测试用例 直接保存这些断言会导致两个问题： 1. **原有用例的通过标准被破坏** —— 原本期望 `c... |
| 10 | `user` | 8 | 先保存测试 场景 |
| 11 | `assistant` | 619 | 抱歉，由于当前会话发生了 Agent Run 切换，上一轮生成的 `企业全场景自动化测试流程` 草稿的完整 JSON 在上下文截断中已经不可直接获取。按平台规则，我不能仅凭摘要去臆造 JSON 来保存正式场景。 ## 现在可以为你做什么 ### 方案 A：立刻重新生成并保存（推荐，走审批） 我会用**和上次完全相同的业务需求**重新跑一次 `scenario... |
| 12 | `user` | 5 | 执行方案A |
| 13 | `assistant` | 677 | ## ✅ 场景已成功保存！ 场景 **「企业全场景自动化测试流程」**（ID: 27）已创建并持久化，覆盖完整的企业业务链路。 \| 状态 \| 说明 \| \|------\|------\| \| **已保存** \| 10 个节点，企业列表 → CT 画像 → 关注 → 专利/商标/备案/技术专利/资质/红名单 → 取消关注 \| \| **已绑定** \| `entId`... |
| 14 | `user` | 6 | 执行查看问题 |
| 15 | `assistant` | 467 | 上一轮模型已发起工具请求。以下是给后续模型使用的有界摘要；完整结构化事实以 ExecutionLedger/ToolCall 为准。 {"evidence_refs_json": "[]", "input_json": "{\"project_id\": 1}", "reason": "读取项目最新上下文，获取环境、对象引用等事实，用于后续诊断。", "so... |
| 16 | `user` | 2771 | 工具执行结果如下。请根据这个结果继续完成用户请求；如果工具失败，请先判断是否属于可修复的输入、schema、validation、草稿结构或字段绑定问题；可修复时必须优先修复并重试 安全工具，不要再次声明已经执行成功。 如果下一步不再请求工具而要输出最终用户回复，请默认控制为简洁总结：1）已完成什么；2）已自动修复/验证什么；3）仍需用户或外部配置处理的阻断... |
| 17 | `assistant` | 557 | 上一轮模型已发起工具请求。以下是给后续模型使用的有界摘要；完整结构化事实以 ExecutionLedger/ToolCall 为准。 {"evidence_refs_json": "[]", "input_json": "{\"page_size\": 5, \"project_id\": 1, \"source_type\": \"flow\"}", "r... |
| 18 | `user` | 1883 | 工具执行结果如下。请根据这个结果继续完成用户请求；如果工具失败，请先判断是否属于可修复的输入、schema、validation、草稿结构或字段绑定问题；可修复时必须优 先修复并重试安全工具，不要再次声明已经执行成功。 如果下一步不再请求工具而要输出最终用户回复，请默认控制为简洁总结：1）已完成什么；2）已自动修复/验证什么；3）仍需用户或外部配置处理的阻断... |
| 19 | `assistant` | 572 | 上一轮模型已发起工具请求。以下是给后续模型使用的有界摘要；完整结构化事实以 ExecutionLedger/ToolCall 为准。 {"evidence_refs_json": "[]", "input_json": "{\"environment_id\": 4, \"project_id\": 1, \"scenario_id\": 27}", "re... |
| 20 | `user` | 2103 | 工具执行结果如下。请根据这个结果继续完成用户请求；如果工具失败，请先判断是否属于可修复的输入、schema、validation、草稿结构或字段绑定问题；可修复时必须优先修复并重试安全工具，不要再次声明已经执行成功。 工具失败修复闭环：本次 scenario.execute_dry_run 失败，但错误看起来可能由工具输入、schema、validation... |
| 21 | `assistant` | 706 | 上一轮模型已发起工具请求。以下是给后续模型使用的有界摘要；完整结构化事实以 ExecutionLedger/ToolCall 为准。 {"evidence_refs_json": "[]", "input_json": "{\"detail_level\": \"summary\", \"project_id\": 1}", "reason": "根据错误提... |
| 22 | `user` | 3506 | 工具执行结果如下。请根据这个结果继续完成用户请求；如果工具失败，请先判断是否属于可修复的输入、schema、validation、草稿结构或字段 绑定问题；可修复时必须优先修复并重试安全工具，不要再次声明已经执行成功。 如果下一步不再请求工具而要输出最终用户回复，请默认控制为简洁总结：1）已完成什么；2）已自动修复/验证什么；3）仍需用户或外部配置处理的阻断... |