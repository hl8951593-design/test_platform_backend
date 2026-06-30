# 开发进度与开发计划

本文档是项目唯一的开发进度与开发计划主文档，用于持续记录平台各功能模块、业务逻辑、数据权限、模块关系、当前完成度和后续开发顺序。它不是一次性架构设计文档，而是后续需求评审、开发实施和版本验收时需要同步维护的业务技术账本。

## 0. 当前版本基线

| 项目 | 当前值 |
| --- | --- |
| 最近更新日期 | 2026-06-30 |
| 当前开发基线 | 3.0.282-agent-completion-audit-execution-diagnostics |
| 当前阶段 | 场景组合、P1 统一执行/报告、缺陷媒体、AI Skill Runtime 与 Harness Loop Agent 后端已实现；Agent Run 已接入对话生成 runner、低延迟实时模型 delta、服务端 conversation history、多轮上下文、长历史预算压缩、软件测试领域通用问答、Codex-style Agent SkillRegistry、29 个内置平台能力 Skill、Skill frontmatter triggers、Skill 私有 routing/guard hints、Skill 私有 prompt resources、Skill 声明式 unsupported capability guard、ToolSpec 私有 backend_handler / required_successful_tool_before / tool_result_repair_guidance、前端只读 Skill catalog 元数据、模型驱动工具闭环、ToolResultPolicy 通用工具结果质量闭环、工具请求格式自修复与本地挽救、复杂工具结果最终回复预算、审批后恢复生成、项目 Memory 对话上下文、Agent 模型健康/live stream 探测、Conversation Smoke 端到端诊断、Run Summary 聚合接口、Conversation Transcript 聚合接口、Run Action State 聚合接口、Conversation Export 聚合接口、Agent Run Event Snapshot 非流式事件快照接口、文件 SQLite/MySQL 后台 runner 启动边界、取消感知的对话 runner、陈旧 active run 自动终止兜底、真实 DeepSeek/MySQL 普通用户端到端诊断脚本、Agent Launch Audit 前端联调/上线准备聚合审计接口、Agent Backend Completion Audit 后端功能完成度聚合审计接口、Agent loop runtime trace/model call 可观测性、prompt cache 友好的稳定工具清单序列化，以及静默工具规划流的合并补发性能优化 |
| 数据库迁移 | 目标库已升级并验证至 `0028_agent_memory_staleness_events` head；Agent 表已落库，`alembic_version.version_num` 已扩展为 `VARCHAR(128)` 以兼容长 revision id |
| 当前主要协议 | HTTP、WebSocket |
| 当前主要执行方式 | 已保存 HTTP/WebSocket 用例、批量用例和已保存 Flow 内部通过共享执行工作池运行，但对前端保持原最终结果返回；场景、测试计划和 AI Skill Run 使用异步受理/事件查询；未保存调试、WebSocket 长连接调试和媒体上传仍为同步边界 |

本轮 Agent 稳定性与协议增量：DeepSeek stream 在首个 `delta/done` 前遇到可重试网络/上游错误时按配置退避重试，并写入 `model.stream_retrying` 审计事件；MySQL/SQLAlchemy transient disconnect 由统一错误层返回 503 `database_connection_lost`，同时 dispose 连接池，避免 `/agents/runs` 和 `/events/snapshot` 断连时退化为无上下文 500。模型 `agent_tool_request` 解析结果已从裸 dict 收敛为内部 `AgentToolRequest` envelope，只允许受控字段进入 ToolCall ledger 与 `model.tool_request_detected` 事件；ToolCall 执行链路已落地第一层 `AgentToolRuntime`/`AgentToolRouter` 分层，执行器保留审批、权限、队列和事件生命周期，Runtime 封装后端调用，Router 负责显式解析 `ToolRegistry.backend_handler`；Loop trace 在保留 `iteration_id`、`model_call_id`、`loop_step` 旧字段的同时新增 `loop_state` envelope，用 `phase=model/tool` 和 `step` 显式描述模型、工具与观察阶段；工具前置条件缺失的 Harness 阻断会创建修复用 ContextBuild 与 `loop.observed`，并通过 `RC_TOOL_PREREQUISITE_MISSING` 明确记录可恢复的工具顺序纠错；模型输出非法 `agent_tool_request` 时也会以 `RC_TOOL_REQUEST_FORMAT_INVALID` 记录格式修复决策；required follow-up 规则命中但模型提前自然语言收尾时会以 `RC_REQUIRED_TOOL_FOLLOWUP_MISSING` 记录静默修复决策；工具闭环达到 `max_iterations` 后进入最终总结前会绑定 stop 用 ContextBuild 并写入 `loop.observed(RC_MAX_ITERATIONS)`，把迭代上限停止从隐式退出提升为可审计 Resource / Limit 决策；同一工具连续相同失败会以 `RC_NO_PROGRESS_PURE` 终止无进展修复；这些运行时纠错/停止原因已同步进入 `AgentMetricsService.snapshot`、dashboard required metrics catalog 和 `agent_runtime_loop_repair` Runbook recommendation，便于前端工作台、Runbook 和运营排查聚合观察。

Codex-style Agent Skill 决策输入已进入 `ContextBuilder.build_metadata_json`：后端会记录 `selected_agent_skills` 和 `matched_agent_skill_routing_rules` 摘要/hash，使 required-tool follow-up 等静默修复可以从 decision ContextBuild 追溯到 Skill 规则来源，同时不泄露私有 frontmatter 原文、Skill 正文或私有 prompt 资源。

RuntimeSnapshot 决策输入也已进入 `ContextBuilder.build_metadata_json`：后端会记录 `runtime_snapshot` 摘要，包含 snapshot id、runtime/tool registry/manifest/prompt/policy hash、available tool names 和 tool count，使 LoopObservation/Runbook 能解释该轮修复或停止决策基于哪版工具和策略环境，同时不复制完整工具 schema 或 manifest bundle。

PermissionContext 决策输入也已进入 `ContextBuilder.build_metadata_json`：后端会记录 `permission_context` 摘要，包含 actor/project/access level、project access flag、implicit permission flag、显式权限码列表/count 与 permission hash，使 LoopObservation/Runbook 能解释权限相关阻断或停止决策基于哪类项目权限环境，同时不复制用户资料或完整授权表。

ToolPolicyContext 也已进入 `AgentToolCall.policy_reason_json`：后端会记录 `policy_context` envelope，包含 policy version、tool name/version、base/resolved side effect、base/resolved replay policy、approval policy、approval reason、active/volatile/frozen policy evidence 计数、mixed evidence 标记与 policy hash，使 ToolCall Detail/Runbook 能解释审批与 replay policy 决策，同时不复制原始 evidence 或未脱敏业务 payload。ToolExecutionContext 随后在 ToolExecutor 成功、失败、manual intervention 和 uncertain recovery 终态写入 `execution_context` envelope，记录 tool/run/runtime snapshot、worker、tool status、execution/effect state、backend contract/schema hash/effect capability、resolved policy、approval lineage/epoch/approved approval、input/output hash、recovery decision、error code、error message hash 与 execution hash，使执行诊断也能从稳定摘要追溯而不复制原始 input/output/evidence/error message。Runbook 诊断现在会在 `tool_call_uncertain` 与 `backend_capability_degraded` recommendation 的 `details.execution_context` 中嵌入白名单执行摘要，让恢复面板直接消费同一上下文，同时不复制原始 input/output/evidence/error message。

状态定义：

| 状态 | 含义 |
| --- | --- |
| 已实现 | 后端代码、接口和核心验证脚本均已存在，可进入联调 |
| 联调中 | 后端能力已具备，正在补齐前端接入、交互细节或回归验证 |
| 计划中 | 已明确业务目标和开发顺序，尚未开始完整实现 |
| 待规划 | 只有方向，尚未形成可执行方案 |

## 1. 文档维护规则

每完成一个功能模块或对现有模块做重要调整时，需要同步更新本文档。

必须记录的内容包括：

- 功能模块的职责边界
- 涉及的数据表、核心字段和数据关系
- 主要业务流程
- 用户权限和数据权限规则
- 对外接口和对应接口文档
- 与其他模块的依赖关系
- 已实现能力、待实现能力和风险点

接口的详细调用方式应写入对应接口文档；本文档只记录模块关系、业务规则和权限规则。

每次更新本文件时还必须：

- 更新“当前版本基线”的日期和阶段。
- 更新模块总览状态，不能保留与代码现状不一致的“待实现”。
- 在开发计划中标记完成项，并补充下一阶段优先级和验收标准。
- 新增接口时同步更新对应 `docs/api_*.md`；Agent 前端契约发生变化时同步更新 `docs/api_agent_frontend_contract.md`，前端页面实现变化同步到 `devtestplatform/docs/`。`front_tech_docs` 只保留历史快照，不再作为活跃维护目标。
- 新增数据表或字段时记录迁移文件、兼容策略和回滚风险。

## 2. 当前模块总览

| 模块 | 当前状态 | 主要职责 | 对应文档 |
| --- | --- | --- | --- |
| 用户与认证 | 已实现 | 用户注册、登录、JWT 签发、当前用户识别、管理员身份 | [认证接口文档](api_auth.md) |
| 项目与权限 | 已实现 | 项目管理、成员管理、项目内功能权限和数据权限 | [项目权限接口文档](api_project_permissions.md) |
| 环境与变量 | 已实现 | 多环境、默认环境、环境变量、用例环境绑定 | [环境配置接口文档](api_environment_configs.md) |
| HTTP 测试用例 | 已实现 | 用例保存、多环境绑定、临时调试、断言、提取、批量执行 | [测试用例接口文档](api_test_cases.md) |
| WebSocket 测试用例 | 联调中 | 自动执行、长连接手动调试、收发日志、主动断开 | [WebSocket 接口文档](api_websocket_test_cases.md) |
| AI 测试能力 | 已实现 | DeepSeek 接入、正式 AI Skill 包、HTTP/WebSocket 用例生成与扩写、场景组合、可观测 Skill Run、JSON 修复兜底 | [AI 接口文档](api_ai.md)、[AI 开发记录](development_ai_notes.md) |
| 可视化测试流程 | 联调中 | 版本化 DAG、HTTP/WebSocket 节点、条件、延迟、数据绑定和执行 | [流程接口文档](api_visual_flows.md) |
| 场景组合与实时运行 | 联调中 | nodes 绑定动作、版本快照、dataset record 独立运行、请求覆盖、受限脚本、异步启动和持久化 SSE | [场景接口文档](api_scenarios.md)、[执行图谱](scenario_execution_graph.md) |
| 执行记录 | 联调中 | 已统一查询 HTTP、WebSocket、场景和 Flow 历史，支持筛选、分页及协议专属详情 | [统一执行记录接口](api_execution_records.md) |
| 测试报告 | 联调中 | 测试计划与 Flow 支持报告历史、结构化指标、明细、HTML 下载和按日趋势 | [测试报告接口](api_test_reports.md) |
| 缺陷跟踪与媒体 | 已实现 | 项目缺陷 CRUD、富文本清洗、状态流转、MinIO 图片附件、权限和删除清理 | [缺陷跟踪接口文档](api_defects.md)、[媒体存储接口文档](api_media.md) |
| 浏览器接口采集 | 联调中 | Chrome 插件采集批次、HTTP/WebSocket 草稿幂等同步与结构化 AI | [浏览器采集接口文档](api_browser_captures.md) |
| 接口定义与导入 | 待规划 | 独立接口资产、OpenAPI 导入、从接口生成用例 | 本文档开发计划 |

### 2.1 当前已完成的核心链路

```text
登录与项目授权
-> 创建项目环境并配置变量
-> 创建 HTTP / WebSocket 测试用例
-> 临时调试、保存或批量执行
-> 使用 AI 生成和扩写用例草稿
-> 在可视化流程中编排 HTTP / WebSocket / 条件 / 延迟节点
-> 保存版本并执行流程
-> 场景手工执行立即返回 execution/run ID
-> 每个启用 dataset record 以独立请求覆盖执行
-> 通过持久化 SSE 展示步骤、连线和最终状态
-> 持久化用例执行和流程节点执行记录
-> 记录、查询和推进项目缺陷生命周期
-> 上传缺陷截图到 MinIO，并以附件元数据和短期签名 URL 安全展示
```

### 2.2 当前主要缺口

- 统一执行记录查询已实现，尚缺前端执行中心联调、归档和聚合统计。
- 测试报告、HTML 导出和按日趋势已实现，尚缺前端联调、PDF 和长期归档。
- 场景手工执行已支持应用内后台任务和实时进度，但缺少独立 Worker、启动恢复扫描、取消、重试和并发控制。
- 可视化 Flow 执行仍为同步执行，尚未复用场景实时运行协议。
- HTTP 用例、WebSocket 用例和流程缺少完整的删除、归档、复制和分页检索能力。
- 已形成统一的 `unittest discover` 回归套件，但尚未接入 CI 门禁和真实 MySQL/SSE 集成环境。
- WebSocket 长连接调试会话保存在单进程内存中，多 Worker 或多实例部署需要会话路由方案。

## 3. 用户与认证模块

### 3.1 模块职责

用户与认证模块负责平台基础身份能力：

- 用户注册
- 用户登录
- 密码哈希存储
- JWT access token 和 refresh token 签发
- 根据 access token 识别当前登录用户
- 通过用户状态控制是否允许登录

当前认证方式为前后端分离 JWT 认证。前端登录成功后保存 `access_token`，后续请求通过 `Authorization: Bearer <access_token>` 访问需要认证的接口。

### 3.2 当前代码位置

| 类型 | 文件 | 说明 |
| --- | --- | --- |
| API Router | `app/api/v1/routers/auth.py` | 注册、登录接口入口 |
| 依赖注入 | `app/api/v1/deps.py` | 数据库会话、当前用户解析 |
| Service | `app/services/user_service.py` | 注册和登录业务逻辑 |
| Repository | `app/repositories/user_repository.py` | 用户查询和创建 |
| Model | `app/models/user.py` | 用户表模型 |
| Schema | `app/schemas/auth.py` | 注册、登录请求结构 |
| Schema | `app/schemas/user.py` | 用户信息、token 返回结构 |
| Security | `app/core/security.py` | 密码哈希、JWT 创建和解析 |

### 3.3 数据模型

当前用户表为 `users`。

| 字段 | 说明 | 权限/业务含义 |
| --- | --- | --- |
| id | 用户主键 | JWT `sub` 使用该字段识别用户 |
| username | 用户名 | 展示名称，不作为登录凭证 |
| avatar | 头像地址 | 用户资料字段，可为空 |
| account | 登录账号 | 唯一，登录时使用 |
| password_hash | 密码哈希 | 只存哈希，不存明文密码 |
| phone | 手机号 | 唯一，当前注册必填 |
| email | 邮箱 | 唯一，当前注册必填 |
| is_active | 是否启用 | 为 `false` 时禁止登录 |
| created_at | 创建时间 | 审计和展示 |
| updated_at | 更新时间 | 审计和展示 |

### 3.4 业务流程

注册流程：

```text
接收注册参数
-> 校验 account、phone、email 是否已存在
-> 对 password 做哈希
-> 创建 users 记录
-> 返回用户基础信息
```

登录流程：

```text
接收 account 和 password
-> 根据 account 查询用户
-> 校验密码哈希
-> 校验 is_active
-> 签发 access_token 和 refresh_token
-> 返回 token 和用户基础信息
```

当前用户识别流程：

```text
读取 Authorization Bearer token
-> 解析 JWT
-> 从 sub 中获取 user_id
-> 查询 users 表
-> 返回当前用户对象
```

### 3.5 用户权限规则

当前已实现的用户权限规则：

| 规则 | 当前状态 | 说明 |
| --- | --- | --- |
| 未登录用户不能访问需要登录的接口 | 部分实现 | 已提供 `get_current_user` 依赖，后续受保护接口需要显式使用 |
| 禁用用户不能登录 | 已实现 | `is_active=false` 时登录返回 403 |
| 密码不可明文存储 | 已实现 | 使用 bcrypt 哈希 |
| 用户不能伪造身份 | 已实现基础能力 | 通过 JWT `sub` 识别用户 |

后端权限架构按以下四类设计：

| 权限类型 | 功能权限 | 数据权限 | 授权能力 |
| --- | --- | --- | --- |
| 管理员权限 | 拥有所有功能权限 | 拥有所有数据权限 | 可以增加所有角色权限 |
| 项目创建者 | 拥有自己创建项目的所有功能权限 | 拥有自己创建项目的所有数据权限 | 只能增加普通测试人员权限 |
| 普通测试人员 | 被项目创建者拉入项目后获得项目创建者赋予的权限 | 只能访问被授权项目内的数据 | 无角色授权能力，除非后续明确扩展 |
| 通用权限 | 同一用户可在不同项目中拥有不同身份 | 数据权限按所在项目身份计算 | 项目创建者也可以是其他项目的普通测试人员 |

权限关系说明：

- 管理员是全局最高权限，不受项目归属限制。
- 项目创建者只对自己创建的项目拥有完整控制权。
- 普通测试人员必须被项目创建者加入项目后，才拥有该项目下的权限。
- 普通测试人员的具体权限不是天然固定值，而是由项目创建者赋予。
- 通用权限表示用户身份具有项目上下文，同一个用户在 A 项目可以是创建者，在 B 项目可以是普通测试人员。

### 3.6 数据权限规则

当前已实现项目级数据权限底座。

当前采用项目维度的数据权限，并叠加管理员全局权限：

| 数据类型 | 建议权限边界 |
| --- | --- |
| 项目 | 管理员可访问所有项目；项目创建者可访问自己创建的项目；普通测试人员只能访问被加入的项目 |
| 环境 | 跟随项目权限 |
| 接口定义 | 跟随项目权限 |
| 测试用例 | 跟随项目权限 |
| 测试流程 | 跟随项目权限 |
| 执行记录 | 跟随项目权限，记录执行人 |
| 测试报告 | 跟随项目权限，必要时支持公开分享 |

已新增 `projects`、`project_members`、`project_member_permissions` 表记录项目归属、项目成员和普通测试人员的项目内权限。所有项目下属资源查询时，应校验当前用户在该项目中的身份和被授予的权限。

## 4. 项目管理模块

### 4.1 模块职责

项目管理模块用于组织测试资源。项目下应包含环境、接口定义、测试用例、测试流程、执行记录和报告。

当前已实现项目创建、项目列表、项目详情访问控制、项目更新、项目软删除、项目普通测试人员授权，以及项目环境管理。

项目归项目创建者所有。项目创建者可以修改、编辑、删除自己创建的项目；管理员可以管理所有项目。

### 4.2 当前代码位置

| 类型 | 文件 | 说明 |
| --- | --- | --- |
| API Router | `app/api/v1/routers/projects.py` | 项目创建、查询、成员授权、权限编码查询 |
| API Router | `app/api/v1/routers/users.py` | 管理员权限设置 |
| 依赖注入 | `app/api/v1/deps.py` | 当前用户、管理员校验、项目权限依赖 |
| Model | `app/models/project.py` | 项目、项目成员、项目成员权限 |
| Repository | `app/repositories/project_repository.py` | 项目和成员权限数据访问 |
| Service | `app/services/project_service.py` | 项目业务逻辑 |
| Service | `app/services/permission_service.py` | 权限判断核心逻辑 |
| Schema | `app/schemas/project.py` | 项目和成员权限请求/响应结构 |
| Script | `scripts/sync_permission_schema.py` | 同步权限数据库结构 |
| Script | `scripts/set_admin.py` | 初始化或取消用户管理员权限 |

### 4.3 数据关系

```text
users
-> projects.created_by_id
-> project_members.user_id
-> project_members.added_by_id
projects
-> project_members.project_id
-> project_environments.project_id
project_members
-> project_member_permissions.member_id
projects
   -> environments
   -> api_definitions
   -> test_cases
   -> test_flows
   -> execution_records
   -> test_reports
```

### 4.4 已实现规则

| 问题 | 规则 |
| --- | --- |
| 项目是否必须有创建者 | 是，创建人默认为项目创建者 |
| 项目成员角色有哪些 | 管理员、项目创建者、普通测试人员 |
| 项目创建者能授权哪些角色 | 只能把用户加入自己创建的项目，并赋予普通测试人员权限 |
| 管理员能授权哪些角色 | 可以增加所有角色权限 |
| 删除项目是否物理删除 | 建议软删除 |
| 项目资源是否允许跨项目复用 | 初期不允许，后续可做复制功能 |

### 4.5 环境管理规则

同一个项目下允许存在多个环境，例如：

| 环境 | 用途 |
| --- | --- |
| prod | 生产环境 |
| uat | 用户验收测试环境 |
| test | 测试环境 |

当前已实现的数据表为 `project_environments`。

| 字段 | 说明 |
| --- | --- |
| project_id | 所属项目 |
| name | 环境名称，例如 prod、uat、test |
| base_url | 环境基础地址 |
| description | 环境描述 |
| is_default | 是否默认环境 |
| is_deleted | 是否软删除 |
| created_by_id | 环境创建人 |

环境权限规则：

- 管理员可以查看和管理所有项目环境。
- 项目创建者可以查看和管理自己创建项目下的所有环境。
- 普通测试人员需要 `environment:view` 才能查看项目环境。
- 普通测试人员需要 `environment:manage` 才能创建、修改、删除项目环境。
- 同一个项目只能有一个默认环境；设置新的默认环境时，旧默认环境会自动取消默认状态。

### 4.6 测试用例模块

测试用例模块用于保存、调试和执行项目下的接口测试用例。

当前已实现能力：

- 查询项目测试用例列表
- 新增测试用例
- 更新测试用例
- 执行已保存测试用例
- 执行未保存测试用例
- 按用户选择顺序批量执行测试用例
- 支持不同请求体格式
- 记录执行结果
- 读取环境变量并在请求中替换 `{{变量名}}`

当前代码位置：

| 类型 | 文件 | 说明 |
| --- | --- | --- |
| API Router | `app/api/v1/routers/test_cases.py` | 测试用例管理和执行接口 |
| Model | `app/models/test_case.py` | 测试用例和执行记录 |
| Repository | `app/repositories/test_case_repository.py` | 测试用例、执行记录、环境变量读取 |
| Service | `app/services/test_case_service.py` | 用例保存、执行、断言、批量执行 |
| Schema | `app/schemas/test_case.py` | 用例请求、断言、执行响应 |

数据表：

| 表 | 说明 |
| --- | --- |
| test_cases | 保存测试用例请求配置、断言、提取规则、创建人和最近执行状态 |
| test_case_executions | 保存每次执行的请求快照、响应快照、断言结果、执行人和耗时 |
| project_environment_variables | 保存项目环境变量，执行时可用于变量替换 |

测试用例请求体格式通过 `test_cases.body_type` 保存，当前支持：

| body_type | 说明 |
| --- | --- |
| none | 无请求体 |
| json | JSON 请求体 |
| form_urlencoded | `application/x-www-form-urlencoded` |
| multipart | `multipart/form-data` |
| raw_text | 原始文本 |
| raw_json | 原始 JSON |

业务关系：

```text
project
-> project_environments
-> project_environment_variables
-> test_cases
-> test_case_executions
```

权限规则：

- 查询测试用例需要 `case:view`。
- 新增和更新测试用例需要 `case:manage`。
- 执行已保存、未保存、批量测试用例需要 `test:execute`。
- 管理员和项目创建者默认拥有项目下全部测试用例权限。
- 普通测试人员只能在被加入项目且被授予对应权限后操作。

执行规则：

- 已保存测试用例执行：用例必须已存在于数据库。
- 未保存测试用例执行：用于前端编辑或新增后临时调试，不保存为用例，但保存执行记录。
- 批量执行：按前端传入的 `test_case_ids` 顺序执行。
- 执行时会关联项目、环境、环境变量、执行用户和断言结果。
- 用例最近执行时间和最近执行状态会回写到 `test_cases`。

### 4.7 缺陷跟踪模块

缺陷跟踪模块用于按项目记录 Bug，并维护从创建到关闭或重新激活的生命周期。

当前已实现能力：

- 查询项目缺陷列表，支持关键字、状态、紧急程度和分页筛选。
- 创建、查询、更新和删除缺陷。
- 独立状态推进接口，并校验合法状态流转。
- 创建和更新时对 `content_html` 做服务端清洗，删除脚本、事件属性和不安全 URL。
- 项目删除时同步清理项目下缺陷。

当前代码位置：

| 类型 | 文件 | 说明 |
| --- | --- | --- |
| API Router | `app/api/v1/routers/defects.py` | 缺陷列表、详情、创建、更新、删除和状态推进 |
| Model | `app/models/defect.py` | `defects` 表模型 |
| Repository | `app/repositories/defect_repository.py` | 缺陷查询和 CRUD |
| Service | `app/services/defect_service.py` | 权限、状态流转和富文本清洗 |
| Schema | `app/schemas/defect.py` | 缺陷请求、状态更新和响应结构 |
| Migration | `migrations/versions/0018_create_defect_tables.py` | 创建 `defects` 表和查询索引 |

数据表：

| 表 | 说明 |
| --- | --- |
| defects | 保存缺陷标题、指派人、类型、紧急程度、状态、富文本内容、报告人和时间 |

业务关系：

```text
project
-> defects
users
-> defects.reporter_id
```

权限规则：

- 查询缺陷需要 `defect:view`。
- 创建缺陷需要 `defect:create`。
- 更新缺陷需要 `defect:update`。
- 删除缺陷需要 `defect:delete`。
- 推进状态需要 `defect:transition`。
- 管理员和项目创建者默认拥有项目下全部缺陷权限。
- 普通测试人员只能在被加入项目且被授予对应权限后操作。

迁移与兼容：

- 新增迁移 `0018_create_defect_tables.py`，revision 为 `0018_defects`。
- 代码发布前必须执行 `alembic upgrade head`。
- 当前缺陷删除为物理删除；后续若需要审计历史，应引入缺陷变更记录或软删除字段。

## 5. 权限模型

### 5.1 权限类型

后端权限架构以用户图中的设计为准，分为管理员权限、项目创建者、普通测试人员、通用权限。

| 权限类型 | 权限定义 |
| --- | --- |
| 管理员权限 | 拥有所有功能权限和所有数据权限，可以增加所有角色权限 |
| 项目创建者 | 拥有自己创建项目的所有功能权限和所有数据权限，只能增加普通测试人员权限 |
| 普通测试人员 | 被项目创建者拉入项目后，拥有项目创建者赋予的权限 |
| 通用权限 | 同一个用户在不同项目中可以拥有不同权限身份 |

### 5.2 已实现数据建模

权限实现拆成全局管理员和项目成员权限两层：

| 数据表 | 作用 |
| --- | --- |
| users | 用户基础信息，`is_admin` 标识是否管理员 |
| projects | 项目信息，必须记录 `created_by` 表示项目创建者 |
| project_members | 项目成员关系，记录用户被加入哪个项目 |
| project_member_permissions | 普通测试人员在项目内被授予的具体功能权限 |

项目权限判断时，必须先判断管理员，再判断项目创建者，最后判断普通测试人员的项目成员权限。

### 5.3 统一权限判断方式

项目接口统一使用权限依赖函数和 `PermissionService`，不在每个接口中重复手写权限判断。

示例设计：

```text
get_current_user()
-> is_admin(user)
-> require_project_access(project_id)
-> require_project_permission(project_id, permission_code)
```

判断顺序：

```text
如果用户是管理员
-> 直接拥有全部功能权限和数据权限
否则如果用户是项目创建者
-> 只能访问和管理自己创建的项目
否则如果用户是普通测试人员
-> 只能访问被加入项目中被授予的功能和数据
否则
-> 无权限
```

### 5.4 权限校验原则

- 管理员拥有所有功能权限和所有数据权限。
- 项目创建者只拥有自己创建项目的完整权限。
- 项目创建者只能给项目添加普通测试人员权限，不能新增管理员权限。
- 普通测试人员只能访问被加入项目的数据。
- 普通测试人员的功能权限来自项目创建者赋权。
- 同一用户在不同项目中权限可以不同。
- 所有项目下属资源接口都必须先校验项目访问权限。
- 修改、删除、执行类接口必须校验具体功能权限。
- 查询单条资源时，需要校验该资源所属项目是否对当前用户可见。
- 列表查询时，只返回当前用户有权访问的数据；管理员可返回全部数据。
- 执行记录必须保存执行人，方便审计。

## 附录：后续开发记录模板

新增功能模块时，按下面模板追加记录：

```markdown
## 模块名称

### 模块职责

### 当前代码位置

### 数据模型

### 业务流程

### 用户权限规则

### 数据权限规则

### 对外接口

### 与其他模块关系

### 已实现

### 待实现

### 风险点
```
## 6. WebSocket 测试用例模块

WebSocket 测试用例与 HTTP 测试用例保持独立边界，不在 `test_cases` 中增加协议区分字段，也不复用 `test_case_executions`。

```text
websocket_test_cases
-> websocket_test_case_environments
-> websocket_test_case_executions
```

代码按 Router、Schema、Model、Repository、Service 独立拆分。执行器负责建立一次 WebSocket 会话、顺序发送消息、按数量接收消息、执行断言和提取变量。项目环境、环境变量以及 `case:view`、`case:manage`、`test:execute` 权限继续复用现有项目能力。详细接口和字段见 [WebSocket 测试用例接口技术文档](api_websocket_test_cases.md)。

测试工具 `scripts/websocket_mock_server.py` 是独立 FastAPI ASGI 应用，提供 echo、会话、连续推送、鉴权拒绝和主动关闭场景。`scripts/test_websocket_test_case_execution.py` 会启动真实 Uvicorn mock 服务完成集成验证。

WebSocket 调试使用独立长连接会话管理器 `app/services/websocket_debug_session_service.py`。它与自动化用例执行生命周期分离，由后台接收线程持续读取目标服务消息，通过 `session_id` 支持发送、增量查询、ping 心跳和主动断开。当前会话存储在单进程内存中，生产多实例部署需要粘性路由或专用连接 Worker。

## 7. AI 测试能力

AI 模块使用 DeepSeek OpenAI 兼容接口，通过正式 AI Skill Runtime 生成测试资产草稿，不直接写入用例表或场景表。

当前已实现：

- 查询 AI Provider 配置和基础对话补全。
- 根据接口描述生成 HTTP 测试用例草稿。
- 基于已保存 HTTP 用例扩写边界、异常和业务变体。
- 根据 WebSocket 协议描述生成 WebSocket 测试用例草稿。
- 基于已保存 WebSocket 用例扩写握手、鉴权、消息顺序、超时和关闭场景。
- 通过正式 skill 包管理 `SKILL.md`、`manifest.json` 和 prompt 资源。
- 使用统一 AI Skill Runtime 构造请求、解析模型输出、归一化和 Schema 校验。
- 可观测 AI Skill Run 支持创建、查询、SSE 订阅事件、模型增量输出、敏感 payload 脱敏和创建者/管理员访问控制。
- HTTP 用例生成/扩写提示词已明确根对象、字段名不可拆行、字符串中不得输出真实控制字符、断言必须使用 `expected`。
- JSON 解析层支持提取 JSON 片段、修复尾逗号、未转义引号、字段名断行和字符串控制字符；本地失败后会触发一次模型 JSON 修复。
- 使用 Pydantic 用例 Schema 校验 AI 输出，过滤协议不匹配字段。
- 读取项目和环境上下文时执行项目权限校验。

当前限制与后续方向：

- 尚未保存 AI 调用日志、模型版本、token 用量和费用。
- 尚未提供项目级 AI 开关、调用额度和审计能力。
- AI Skill Run 事件当前不持久化，应用重启会丢失历史 run/event。
- 尚未支持基于执行失败记录生成原因分析和修复建议。
- AI 生成结果必须继续以草稿形式返回，由用户确认后保存。

## 8. 可视化测试流程

可视化流程模块已实现版本化 DAG 保存与同步执行，支持把 HTTP 和 WebSocket 用例编排为可复用业务流程。

当前已实现：

- 流程列表、创建、详情和更新。
- 乐观锁版本控制和不可变流程版本快照。
- 已保存流程和未保存流程执行。
- `start`、`end`、`api_case`、`websocket_case`、`condition`、`delay` 节点。
- 节点级用例配置覆盖和上游输出绑定。
- 成功、失败、始终执行、条件 true/false 路由。
- DAG 环路、可达性、节点引用、绑定和分支规则校验。
- `Idempotency-Key` 执行幂等控制。
- 流程执行、节点执行、请求快照、输出快照和错误持久化。
- 常见敏感字段脱敏。

当前限制与后续方向：

- 当前执行接口会等待整个流程结束，不适合长流程和高并发执行。
- 尚未支持取消、暂停、恢复、节点重试和从失败节点继续。
- Flow 尚未提供执行进度推送；统一执行记录详情已可查询 Flow 节点日志。
- 可视化 Flow 尚未提供定时任务、Webhook 或 CI 触发入口；测试计划已提供 Cron 和验签 Webhook。

## 8.1 场景组合实时执行

场景组合模块使用不可变 `test_scenario_versions` 快照执行 HTTP、WebSocket、条件和延迟步骤。
手工执行接口与测试计划执行采用不同的调度入口，但共享同一套步骤执行、变量渲染、变量提取、
断言和敏感数据处理逻辑，避免实时化改造改变既有取值语义。

当前已实现：

- `POST /scenarios/{scenario_id}/execute` 返回 HTTP `202`，先持久化 execution、run 和
  `run_queued` 事件，再由 FastAPI `BackgroundTasks` 使用独立数据库会话继续执行。
- 一个请求创建一个 `test_scenario_executions` 分组；每个选中数据集的每条启用 record
  创建一个 `test_scenario_runs` 记录，并保存 `record_id`、`record_name`。
- record 可按步骤覆盖完整 path、header、query parameter 和嵌套 JSON body；执行时先复制
  请求快照并应用覆盖，再解析数据集变量、环境变量和上游步骤绑定。
- 没有 records 的历史数据集自动归一化为一条兼容 record；旧 dataset-level
  `request_overrides` 和 override `values` 继续支持读取，新写入统一使用 records。
- `test_scenario_run_events` 持久化单个 run 的有序事件；`sequence` 严格递增，
  事件写入成功后才允许 SSE 客户端读取。
- `GET /scenario-runs/{run_id}/events` 支持 Bearer Token、`Last-Event-ID`、历史重放、
  15 秒持久化心跳和终态自动关闭。
- `GET /scenario-runs/{run_id}` 在执行过程中提供 `current_step_id`、
  `current_step_index`、`last_event_sequence` 和 pending/running/terminal 步骤快照。
- 已提供 `run_queued`、`run_started`、`step_started`、`step_completed`、
  `step_failed`、`step_skipped`、`transition_started`、`run_completed`、
  `run_failed` 和 `heartbeat` 事件。
- 变量绑定和提取保留原始 JSON 类型；Authorization、Cookie、Token、Password、
  Secret 和 API Key 等敏感值不会通过 SSE 返回明文。
- 测试计划继续调用同步 `execute_scenario()`，未被手工执行接口的异步返回行为影响。
- HTTP/WebSocket 步骤支持内部 attempt 重试；网络错误、超时、配置状态码和显式轮询断言
  可触发指数退避与 Full Jitter，场景外层只接收最终步骤结果。
- 断言全部通过后才提取变量，失败 attempt 不会污染当前 record 的变量上下文。
- 执行记录和场景步骤详情保存 `attempt_history`，SSE 只返回 attempt 数量摘要。

数据关系：

```text
test_scenario_executions
  -> test_scenario_runs.execution_id
     -> test_scenario_run_events.run_id
     -> test_case_executions.scenario_run_id
     -> websocket_test_case_executions.scenario_run_id
```

迁移与兼容：

- 实时事件数据库迁移为 `0015_add_scenario_realtime_events.py`。
- record 运行身份数据库迁移为 `0016_add_scenario_run_records.py`，在
  `test_scenario_runs` 增加可空的 `record_id`、`record_name`，兼容历史运行。
- 步骤重试数据库迁移为 `0017_add_step_retry_policies.py`，为 HTTP/WebSocket 用例增加
  `retry_policy`，为两类执行记录增加 `attempt_history`。
- 场景节点破坏性迁移为 `0020_migrate_scenarios_to_nodes.py`：首用例前动作绑定到首节点前置，
  用例间动作绑定到下一节点前置，末尾动作绑定到末节点后置；不能保持 teardown 或停止边界的
  数据阻断升级。运行时只读 `nodes`。
- 代码发布前必须执行 `alembic upgrade head`；否则会因缺少
  `test_scenario_executions`、`test_scenario_run_events` 或 record 字段报错。
- records 保存在场景版本 JSON 中，不新增独立 record 表；旧 dataset-level overrides
  读取时归一化，新版本只写 records。0020 会改写历史场景版本的编排结构，但不改变用例快照。

当前限制与后续方向：

- `BackgroundTasks` 仍属于 API 进程内执行，不等同于可靠任务队列；进程异常退出时，
  已处于 queued/running 的任务不会自动被其他实例接管。
- 尚未实现服务启动后的孤儿任务扫描、租约、心跳超时判定和自动恢复。
- 尚未实现取消、手工重试、按失败步骤恢复和项目级并发限制。
- 事件当前随运行记录长期保留，尚未实现 24 小时下限之外的归档、清理和
  `EVENT_HISTORY_EXPIRED` 响应。
- 多个 API 实例可以读取同一事件表，但任务领取仍缺少跨实例 claim 机制。
- `request_overrides[].value` 当前是通用 JSON，不会根据 header/path 名称自动字段级加密；
  敏感值应通过环境变量模板引用，后续需增加 path-aware 加密和保存校验。

## 9. 开发计划

开发顺序遵循“先稳定已有主链路，再建设统一执行与报告，最后生产化”的原则。除紧急缺陷外，后续需求应按以下优先级推进。

### 9.1 P0：核心链路联调与稳定性

目标：让当前 2.6 已实现能力具备稳定演示、联调和持续回归条件。

计划事项：

| 事项 | 当前状态 | 验收标准 |
| --- | --- | --- |
| WebSocket 实时调试前后端联调 | 联调中 | 支持完整地址或环境相对路径；可连接、发送 Text/JSON、增量读取日志、清空日志、主动断开；编辑器关闭后最终释放连接 |
| 可视化流程前后端联调 | 联调中 | 可创建、编辑、保存版本、执行 HTTP/WebSocket/条件/延迟节点，并展示节点执行结果 |
| 场景数据驱动与实时执行前后端联调 | 联调中 | records 可编辑；每条启用 record 独立 run；覆盖字段定位准确；启动返回 202；SSE 可重放；运行详情可恢复状态 |
| 步骤级重试前后端联调 | 联调中 | 可配置 retry policy 和轮询断言；执行详情展示 attempt、原因、等待时间和最终结果 |
| 资源生命周期补齐 | 已实现 | HTTP/WebSocket 用例和 Flow 支持物理删除；保留执行历史并解除外键；Flow 引用存在时用例删除返回 409 |
| 列表查询能力补齐 | 已实现 | HTTP/WebSocket 用例支持分页、关键字和环境筛选；Flow 支持分页、关键字和状态筛选 |
| 错误响应一致性 | 已实现 | HTTP/校验/框架 404/未处理异常统一 `{code,message,data}`；500 返回 request ID 且不泄露内部异常 |
| 缺陷跟踪后端接口 | 已实现 | 支持项目缺陷 CRUD、富文本清洗、状态流转校验和 `defect:*` 权限 |
| 缺陷图片存储 | 已实现 | 私有 MinIO 桶、格式/大小校验、附件绑定、预签名读取、单对象/缺陷/项目清理 |
| 数据库迁移验证 | 已完成 | 目标库已到 `0020_scenario_nodes`；47 个版本无遗留 `steps`，4 个场景详情回读通过 |
| 自动化测试基线 | 进行中 | 当前 `unittest discover` 共 118 项通过；继续接入 CI 并增加真实 MinIO/MySQL 集成测试 |

P0 完成条件：

- 前端能够完成“项目 -> 环境 -> 用例 -> 调试/执行 -> 流程编排执行”的完整演示。
- 主链路接口具备稳定错误提示，不依赖人工查看后端日志判断失败原因。
- 每次合并前可以通过一条统一命令执行核心回归测试。

当前执行顺序：

1. 完成场景 records 编辑、请求覆盖、SSE 和运行详情恢复的前端联调。
2. 完成 WebSocket 实时连接和可视化流程的前后端联调问题收敛。
3. 将现有 98 项测试接入 CI，并增加真实 MySQL 迁移、Retry-After 和 SSE 重连集成测试。
4. 完成统一执行记录、HTML 报告和趋势页面联调，并进入 PDF/归档设计。

### 9.2 P1：统一执行中心与测试报告

目标：把已经持久化的 HTTP、WebSocket、场景和 Flow 执行记录变成可查询、可分析的产品能力。

计划事项：

| 事项 | 设计要求 | 验收标准 |
| --- | --- | --- |
| 统一执行记录接口 | 已实现：统一返回执行类型、项目、环境、执行人、状态、耗时、开始时间和错误摘要 | 已可分页筛选四类执行记录 |
| 执行详情 | 已实现：保留协议专属响应，同时提供统一摘要 | 已可查看请求/会话快照、响应、断言、attempt、场景事件和节点日志 |
| 测试报告 | 已实现：基于测试计划运行或 Flow 执行即时生成 | 已包含通过率、失败原因、耗时、record/步骤或节点明细 |
| 报告导出 | 已实现 HTML；后续扩展 PDF | 用户可下载并离线查看完整 HTML 报告 |
| 历史趋势 | 已实现：按项目、来源、环境和日期聚合，窗口最长 366 天 | 已返回执行数、通过率、失败数和平均耗时 |

P1 完成条件：

- 用户不需要查询数据库即可定位一次执行失败的具体请求、响应、断言或流程节点。
- 一次批量执行或流程执行能够生成可分享的测试报告。

### 9.3 P2：异步执行可靠性与任务调度

目标：支持长流程、并发执行和可靠任务控制。

计划事项：

- 将场景执行从进程内 `BackgroundTasks` 迁移到可独立部署的 Worker；保持现有 202、
  execution/run ID 和 SSE 契约不变。
- 增加任务 claim、租约、Worker 心跳、孤儿任务扫描和服务重启恢复。
- 在现有持久化实时进度基础上提供取消、失败重试和按失败步骤恢复。
- 增加项目级并发限制、超时和资源保护。
- 支持定时执行、Webhook 触发和 CI/CD 调用。
- 为 WebSocket 长连接调试设计 Redis 会话路由或专用连接 Worker。
- 明确任务幂等、Worker 异常恢复和重复执行策略。

P2 完成条件：

- 长流程执行不占用普通 HTTP 请求生命周期。
- 服务重启或 Worker 异常时，任务状态可追踪且不会静默丢失。

### 9.4 P3：接口资产与生产化能力

目标：提升测试资产复用效率，并满足正式部署、审计和治理要求。

计划事项：

- 建设独立接口定义模块，支持 OpenAPI 导入、接口更新和从接口生成用例。
- 增加用例复制、标签、目录、归档和跨环境批量运行。
- 增加结构化日志、指标、链路追踪和告警。
- 增加 AI 调用日志、token 用量、额度、项目级开关和审计。
- 完善密钥管理、敏感字段脱敏、数据保留和清理策略。
- 增加多实例部署方案、备份恢复方案和性能压测。

### 9.5 暂不进入当前阶段的范围

以下能力有价值，但在 P0 和 P1 完成前不作为主线开发事项：

- 性能压测和分布式压测执行器。
- 移动端专项测试。
- 浏览器 UI 自动化。
- 公共用例市场和跨项目实时共享。
- 复杂审批流和多组织租户体系。

## 10. 开发任务进入与完成标准

### 10.1 开始开发前

- 明确所属模块、用户目标、权限要求和数据边界。
- 确认是否需要数据库迁移以及对旧数据的兼容方式。
- 明确接口契约、错误场景和前端交互方式。
- 明确该功能是否可能产生阻塞、长耗时、批量执行、外部 I/O、CPU 密集计算或高频轮询。
- 对可能阻塞的功能，优先设计为异步任务、后台 Worker、状态查询、SSE/WebSocket 事件或可恢复执行链路。
- 明确测试范围和验收标准。

### 10.2 完成开发时

- 代码按 Router、Schema、Service、Repository、Model 的现有边界实现。
- 项目资源接口完成项目权限和资源归属校验。
- 新增或变更接口已更新对应 API 文档。
- 新增重要能力已补充自动化验证或集成测试脚本。
- 数据库迁移可在目标数据库执行。
- 新增长耗时或外部依赖能力已具备超时、重试退避、并发上限和失败记录；如果仍为同步执行，已写明原因、适用边界和异步化计划。
- `async def` 路由和异步服务中没有直接引入会长时间阻塞事件循环的同步 I/O、无限等待或 CPU 密集流程。
- 本文档中的模块状态、已实现能力、风险和后续计划已同步更新。

### 10.3 文档完成标准

- API 字段、状态码、权限、错误和兼容行为以对应 `docs/api_*.md` 为准，并与当前代码一致。
- 跨模块执行顺序、数据关系或基础设施变化同步更新
  [技术架构](technical_architecture.md)。
- 数据库字段变化必须同时具备 Model、Alembic migration、迁移执行结果和文档 revision。
- 持久化 JSON 结构变化必须写明旧数据读取、新写入格式以及是否需要数据回填。
- 测试数量只能在完整执行统一回归命令后更新，不能从新增测试文件数量推算。
- 文档中的“已实现”“联调中”“计划中”必须可从代码、迁移或测试中找到对应证据。
- 详细入口和逐项检查清单见 [文档索引与维护规范](README.md)。

## 11. 当前风险清单

| 风险 | 影响 | 当前处理计划 |
| --- | --- | --- |
| 新功能默认走同步执行 | 约 50 人并发使用时，一个用户的长流程、外部等待或批量任务可能阻塞其他用户和普通接口 | 所有新增执行类能力默认按异步/非阻塞设计；同步保留必须有超时、边界和迁移计划 |
| 未保存调试和长连接调试仍为同步边界 | 调试请求量较高时仍可能占用请求线程或进程内连接资源 | 后续新增任务载荷持久化和专用 WebSocket 连接 Worker |
| 共享执行工作池仍在 API 进程内 | 进程重启会影响已提交但未完成的执行任务 | 下一步迁移到独立 Worker，并增加统一 claim、租约、心跳和恢复扫描 |
| 单用例和可视化 Flow 同步执行占用请求线程 | 长流程超时、并发能力有限 | 已保存 HTTP/WebSocket 用例和已保存 Flow 的真实执行已迁移到共享执行工作池；接口为兼容前端仍等待最终结果后返回 |
| 场景后台执行仍依赖 API 进程 | 进程重启可能留下 queued/running 孤儿任务 | P2 增加 Worker claim、租约、心跳和恢复扫描 |
| SSE 事件长期保留且未归档 | 运行量增长后事件表持续膨胀 | P2/P3 增加保留期、归档和过期恢复协议 |
| WebSocket 调试会话保存在进程内存 | 多 Worker 下请求可能找不到会话 | P0 单实例联调；P2 设计集中式会话路由 |
| 执行记录前端入口尚未联调 | 后端已统一查询，但用户页面尚未形成完整定位链路 | P1 完成执行中心页面联调 |
| 报告尚缺 PDF 和归档 | HTML 和趋势已可用，但长期治理能力不足 | P1/P3 增加 PDF 和保留策略 |
| 回归测试尚未接入 CI | 本地已有统一命令，但合并时仍缺少自动门禁 | P0 接入 CI 并增加真实数据库集成验证 |
| AI 调用缺少治理 | 无法统计成本和审计使用情况 | P3 增加日志、额度和项目开关 |
| request override 通用值缺少路径感知加密 | 在场景版本中直接写入敏感 header 值可能形成明文快照 | 当前要求使用环境变量模板；P0 增加保存校验与 path-aware 加密 |
| 文档与代码漂移 | 后续人工和 AI 开发可能依赖过期契约产生回归 | 使用文档索引维护契约；接口、迁移、架构和计划随代码同批更新 |
| 非幂等请求重试产生重复副作用 | POST/PATCH 可能重复创建或扣款 | 默认禁止；仅显式开启并配合业务幂等键 |
| 高并发重试放大被测服务压力 | 多 record 同时失败可能形成重试风暴 | 指数退避、Full Jitter、最大等待和场景 deadline |
| 500 错误难以跨端定位 | 前端只能看到通用错误，排障依赖人工关联时间 | 返回并记录 `X-Request-ID`，通过 request ID 关联服务日志 |
| MinIO 与 MySQL 缺少跨系统事务 | 极端失败可能产生孤儿对象或元数据 | 写入失败立即补偿删除；删除失败保留元数据并返回 503；后续增加 outbox、周期巡检和生命周期规则 |

## 12. 进度更新记录

| 日期 | 版本/阶段 | 更新内容 |
| --- | --- | --- |
| 2026-06-08 | 2.0 | 将本文档升级为开发进度与开发计划主文档；同步 HTTP、WebSocket、AI、可视化流程实际完成度；确定 P0-P3 路线图 |
| 2026-06-12 | 2.1 | 场景手工执行改为 HTTP 202 异步启动；新增 execution 分组、运行中快照、持久化 SSE、Last-Event-ID 重放、心跳和变量追踪；迁移升级至 0015；明确可靠 Worker、取消和事件清理后续计划 |
| 2026-06-15 | 2.2 | 场景数据集升级为 records；每条启用 record 独立运行并支持 path/header/query/body 请求覆盖；兼容旧数据结构；运行记录增加 record 身份；迁移升级至 0016；完整回归 63 项通过 |
| 2026-06-15 | 2.3 | HTTP/WebSocket 增加步骤内部重试、指数退避与 Full Jitter、429 Retry-After、轮询断言和 attempt 审计；修正为断言通过后才提取变量；迁移升级至 0017；完整回归 71 项通过 |
| 2026-06-15 | 2.4 | HTTP/WebSocket 用例和 Flow 列表统一分页结构；增加关键字、环境和状态筛选；确认三类资源删除与历史关联策略已实现；无需新增迁移；完整回归 74 项通过 |
| 2026-06-15 | 2.5 | 全局统一 HTTP、422、框架 404 和安全 500 错误响应；保留结构化字段定位；500 增加 request ID；OpenAPI 注册公共错误 Schema；无需新增迁移；完整回归 81 项通过 |
| 2026-06-15 | 2.6 | 新增统一执行记录列表与详情，聚合 HTTP、WebSocket、场景和 Flow；支持项目、类型、状态、环境、执行人、时间和关键字筛选；详情保留协议专属快照、attempt、事件和节点日志；无需新增迁移；完整回归 89 项通过 |
| 2026-06-15 | 2.7 | 新增测试报告历史、计划与 Flow 结构化报告、指标统计、安全 HTML 导出和按日趋势；计划报告展开 dataset record 场景运行，Flow 报告展开节点明细；无需新增迁移；完整回归 98 项通过 |
| 2026-06-17 | 2.8 | 新增缺陷跟踪后端接口、`defects` 表、`defect:*` 权限、富文本清洗和状态流转校验；迁移升级至 0018；完整回归 101 项通过 |
| 2026-06-17 | 2.9 | 接入 MinIO 缺陷图片存储，新增 `media_objects`、安全图片校验、附件绑定、动态预签名 URL 和删除清理；代码迁移 head 升级至 0019；完整回归 106 项通过 |
| 2026-06-19 | 3.0 | 场景定义破坏性切换为 nodes 与绑定动作；新增随机、固定值和受限脚本动作、运行列表分页及统一 202 响应；加入可阻断的 0020 一次性迁移；完整回归 116 项通过 |
| 2026-06-20 | 3.0.1 | 扩展 0020 顺序迁移以覆盖用例间 condition 和 setup 用例；目标库 47 个版本全部转换，修复场景列表 `KeyError: nodes`；完整回归 117 项通过 |
| 2026-06-20 | 3.0.2 | 修复创建重复名称场景时唯一键异常在 flush 阶段漏出为 500；flush/commit 竞态统一返回 HTTP 409；完整回归 118 项通过 |
| 2026-06-24 | 3.0.2-doc | 新增后端异步与非阻塞工程约束，明确多人并发场景下新增执行类能力默认采用异步任务、状态查询/事件流、超时、并发上限和 Worker 演进边界 |
| 2026-06-24 | 3.0.3-dev | 新增共享执行工作池；已保存 HTTP/WebSocket 用例、批量用例和已保存 Flow 真实执行迁移到工作池但保持原接口最终结果返回；场景、测试计划和 AI Skill Run 继续使用异步受理后后台执行 |
| 2026-06-25 | 3.0.4 | AI Skill Runtime 增强 JSON 解析修复和一次模型修复兜底；HTTP 用例生成/扩写提示词收紧根对象、字段名、控制字符和 `expected` 断言契约；同步 AI 技术文档；完整回归 147 项通过 |
| 2026-06-26 | 3.0.5-agent | Agent Harness+Loop 生产硬化继续推进：故障注入服务从 6 项扩展到 23 项，新增 backend accepted not_found、effect committed 复用、Tool succeeded 但 EventStore 写失败转 uncertain/reconcile、Outbox 发布失败、reconcile conflict、审批 replacement/supersede 原子替换、审批过期、execute-time 权限撤销阻断、context heavy 缺证据、EvidenceRef 历史 volatile 排除与 mixed volatile/frozen 强制 revalidation、Memory contradiction/stale、Memory 绕过 EvidenceRef 阻断、重复幂等键、RootCause 缺失规则和 Memory-only 高风险阻断等可执行用例；新增 `ApprovalService.supersede_with_replacement` 后端互斥域能力和 `approval_replacement_atomic_total` 指标；补齐 EvidenceRef replay policy 三项监控指标，修正 `memory_high_risk_blocked_total` 监控计数的 error_code 对齐，并修复 RootCause 默认规则初始化读取 `rule_id` 时的标量查询错误；Agent runtime 专项回归 63 项通过 |
| 2026-06-26 | 3.0.6-agent | Agent Harness+Loop observability 继续推进：新增 `GET /api/v1/agents/dashboard` readiness dashboard，聚合 metrics snapshot、release gate、P0/P1 fault injection catalog 与 runbook catalog，输出 `pass/attention/blocked` readiness、P0/P1 checks、fault/runbook coverage 和 live recovery attention；补充 `AgentReadinessDashboardService`、Pydantic schema、OpenAPI route 与专项单测，文档同步到 Harness 开发计划和架构说明。 |
| 2026-06-26 | 3.0.7-agent | Agent Harness+Loop monitoring alerts 继续推进：新增 `AgentAlertService` 和 `GET /api/v1/agents/alerts`，按 metrics snapshot 与 release gate 评估 uncertain、manual intervention、approval epoch conflict、backend contract unsupported、migration block、outbox lag、required evidence missing、root cause rule missing、Memory EvidenceRef bypass、Memory-only high-risk block 与 release gate violation 等 firing alerts；dashboard 新增 `alerts`、`alert_summary` 与 `monitoring_alerts_clear` check，P0 alert 会将 readiness 降为 blocked，P1 alert 降为 attention；补充 schema、路由和专项单测。 |
| 2026-06-26 | 3.0.8-agent | Agent Harness+Loop release gate 继续推进：新增 `AgentReleaseGateService.promotion_assessment` 和 `GET /api/v1/agents/release-gates/promotion`，面向 L2 -> L3/business_create 灰度晋级输出 `can_promote`、`decision`、`blockers`、静态发布门禁、dashboard readiness、fault coverage 与 alert summary；promotion 会同时阻断静态 gate reason、当前 tool matrix violation 和 readiness dashboard P0/P1 告警，补充 schema、路由与专项单测。 |
| 2026-06-26 | 3.0.9-agent | Agent Harness+Loop EventStore/SSE replay 审计继续推进：新增 `AgentEventReplayAuditService.audit_run` 和 `GET /api/v1/agents/runs/{run_id}/events/replay-audit`，校验 `event_seq` 连续性、`last_event_sequence` 一致性、Last-Event-ID 后重放窗口、missing/duplicate/unexpected sequences；新增 `event_replay_gap_total` 指标和 `agent_event_replay_gap` 告警，dashboard/alerts 可发现 EventStore gap；补充 schema、路由、专项单测与 Harness 文档。 |
| 2026-06-26 | 3.0.10-agent | Agent Harness+Loop WorkerQueue 审计继续推进：新增 `AgentWorkerQueueAuditService` 和 `GET /api/v1/agents/worker-queue/audit`，输出 queued/leased 状态统计、`lease_scan_stable`、expired lease、duplicate active lease 与 oldest queued age；新增 `worker_queue_expired_lease_total`、`worker_queue_duplicate_active_lease_total`、`worker_queue_oldest_queued_age_ms` 指标和对应 P1/P0 告警，覆盖多 Worker claim 不重复与 lease 扫描稳定性的 P2 验收；补充 schema、路由、专项单测与 Harness 文档。 |
| 2026-06-26 | 3.0.11-agent | Agent Harness+Loop Reconcile backoff 继续推进：`ReconcileWorker` 现在读取最新 `AgentReconcileAttempt.next_retry_at`，未到窗口的 uncertain/reconciling ToolCall 会在 `reconcile_run` 中跳过且不调用 backend adapter，API 响应新增 `skipped_backoff` 和 `skipped_backoff_tool_calls`；新增 `reconcile_backoff_active_total` 指标和 `agent_reconcile_backoff_pending` P2 告警，覆盖 Reconcile backoff 不造成风暴的 P2 验收；补充专项单测与 Harness 文档。 |
| 2026-06-26 | 3.0.12-agent | Agent Harness+Loop Approval expire 审计继续推进：新增 `ApprovalExpireScanner.audit/expire_due_summary`、`GET /api/v1/agents/approvals/expire-audit` 与 `POST /api/v1/agents/approvals/expire`，输出 due backlog、oldest lag、candidate lineage、processed lineage 与同 lineage 多 pending 热点；新增 `approval_expire_due_total`、`approval_expire_batch_lag_ms`、`approval_lineage_hotspot_total` 指标和 `agent_approval_expire_backlog`/`agent_approval_lineage_hotspot` 告警，覆盖 Approval 批量 expire 不造成锁热点的 P2 验收；补充 schema、路由、专项单测与 Harness 文档。 |
| 2026-06-26 | 3.0.13-agent | Agent Harness+Loop SSE replay 高并发验收继续推进：新增 `AgentEventReplayAuditService.audit_project` 和 `GET /api/v1/agents/events/replay-stress-audit`，按项目抽样最近 runs 并为每个 run 生成多个 Last-Event-ID 游标窗口，输出 cursor_window_count、failed_run_ids、invalid_cursor_count、max_replay_window_events 与 `high_concurrency_replayable`；新增 `event_replay_stress_failed_total`、`event_replay_stress_cursor_window_total`、`event_replay_stress_max_window_events` 指标和 `agent_event_replay_stress_failed` 告警，覆盖 SSE 高并发下可重放的 P2 验收；补充 schema、路由、专项单测与 Harness 文档。 |
| 2026-06-26 | 3.0.14-agent | Agent Harness+Loop 故障注入覆盖率继续推进：将 dashboard required fault cases 从 16 项补齐为 23 项生产硬化用例，新增 `AgentFaultInjectionCoverageService.audit` 和 `GET /api/v1/agents/fault-injections/coverage`，输出 registered/required/missing/extra、coverage_ratio 与 coverage_pass；新增 `fault_injection_required_case_total`、`fault_injection_registered_case_total`、`fault_injection_missing_required_total`、`fault_injection_coverage_ratio` 指标和 `agent_fault_injection_coverage_incomplete` 告警，覆盖故障注入覆盖率达标的 P2 验收；补充 schema、路由、专项单测与 Harness 文档。 |
| 2026-06-26 | 3.0.15-agent | Agent Harness+Loop readiness dashboard 完整性继续推进：dashboard 新增 `promotion_assessment` contract summary 和 `release_gate_promotion_assessment` P0 check，暴露 `/api/v1/agents/release-gates/promotion` 所需的 current level、默认 L3 target gate、静态 blocked_reasons 与当前 tool violations；该 check 只验证晋级评估输入可观测，不反向调用依赖 dashboard readiness 的 promotion assessment，避免递归，同时不把当前 L3 静态阻塞误判为 dashboard 失败；补充 schema、专项单测与 Harness 文档，无需新增迁移。 |
| 2026-06-26 | 3.0.16-agent | Agent Harness+Loop dashboard 指标目录继续补齐：`metrics_catalog_complete` 的 required catalog 现在覆盖开发计划 P0/P1 监控清单中已由 snapshot 计算但先前未纳入目录校验的 `tool_call_orphan_recovered_total`、`approval_superseded_total`、`context_degraded_total`、`same_failure_no_progress_total`、`memory_used_active_policy_total` 与 `backend_capability_degraded_total`，并在 check details 中返回 `required_metric_keys` 方便 API 消费端和测试审计；补充专项单测与 Harness 文档，无需新增迁移。 |
| 2026-06-26 | 3.0.17-agent | Agent Harness+Loop LoopObservation 观测一致性继续推进：新增 `context_decision_build_missing_total` 指标，审计 LoopObservation 引用了不存在的 decision ContextBuild 的异常链路；`AgentAlertService` 新增 `agent_context_decision_build_missing` P1 告警，dashboard 通过 `monitoring_alerts_clear` 进入 attention；补充专项单测与 Harness 文档，无需新增迁移。 |
| 2026-06-26 | 3.0.18-agent | Agent Harness+Loop RootCause 聚合观测继续推进：新增 `loop_root_cause_context_degraded_total` 与 `loop_root_cause_unknown_total` 指标，分别统计 LoopObservation 根因为上下文压缩和 fallback unknown 的数量，并纳入 dashboard required metrics catalog；补充专项单测与 Harness 文档，无需新增迁移。 |
| 2026-06-26 | 3.0.19-agent | Agent Harness+Loop 修复越界观测继续推进：新增 `invalid_repair_scope_total` 指标，统计 LoopObservation `stop_reasons_all_json` 中包含 `invalid_repair_scope` 的修复越界数量，并纳入 dashboard required metrics catalog；补充专项单测与 Harness 文档，无需新增迁移。 |
| 2026-06-26 | 3.0.20-agent | Agent Harness+Loop Memory retrieval profile 观测继续推进：带 run 上下文的 Memory 检索在 profile 缺失时写入 `memory.retrieval_profile_missing` 事件，新增 `memory_retrieval_profile_missing_total` 指标并纳入 dashboard required metrics catalog；补充专项单测与 Harness 文档，无需新增迁移。 |
| 2026-06-26 | 3.0.21-agent | Agent Harness+Loop Memory retrieval 观测继续推进：新增 `memory_retrieved_total` 指标，按 `AgentMemoryUsageEvent` 统计 Memory 检索命中并被选入结果的次数，并纳入 dashboard required metrics catalog；补充专项单测与 Harness 文档，无需新增迁移。 |
| 2026-06-26 | 3.0.22-agent | Agent Harness+Loop Memory hard gate 观测继续推进：Memory 检索在 run 上下文中因 retrieval profile `min_confidence` 被过滤时写入 `memory.low_confidence_filtered` 事件，新增 `memory_low_confidence_filtered_total` 指标并纳入 dashboard required metrics catalog；补充专项单测与 Harness 文档，无需新增迁移。 |
| 2026-06-26 | 3.0.23-agent | Agent Harness+Loop Memory contradiction penalty 观测继续推进：Memory 检索在 run 上下文中计算出大于 0 的 contradiction penalty 时写入 `memory.contradiction_penalty_applied` 事件，新增 `memory_contradiction_penalty_applied_total` 指标并纳入 dashboard required metrics catalog；补充专项单测与 Harness 文档，无需新增迁移。 |
| 2026-06-26 | 3.0.24-agent | Agent Harness+Loop Memory EvidenceWatch stale 观测继续推进：新增 `ai_agent_memory_staleness_events` 审计表和迁移 `0028_agent_memory_staleness_events`，MemoryStalenessWorker 在 EvidenceWatch 触发 stale 更新时记录 stale_score/status 前后值；新增 `memory_evidence_watch_stale_total` 指标并纳入 dashboard required metrics catalog；补充专项单测与 Harness 文档。 |
| 2026-06-26 | 3.0.25-agent | Agent Harness+Loop Memory audit API 继续推进：新增 `GET /api/v1/agents/memory-staleness-events` 只读接口，支持按 project、memory 和 evidence ref 查询 EvidenceWatch stale 审计事件；补充 OpenAPI 路由断言、staleness event 字段断言与 Harness API 文档同步。 |
| 2026-06-26 | 3.0.26-agent | Agent Harness+Loop Runbook 覆盖继续推进：扩展 `AgentRunbookService` 的生产硬化 runbook，覆盖 outbox publish lag、event replay、fault injection coverage、WorkerQueue recovery、context linkage、RootCause rule missing 与 Memory EvidenceRef governance；P0/P1 `AgentAlertService` alert rule 现在必须映射到已注册 runbook，dashboard `runbook_catalog_complete` 同步纳入 required catalog；补充专项单测与 Harness 文档。 |
| 2026-06-26 | 3.0.27-agent | Agent Harness+Loop Approval lineage lock 观测继续推进：approve/reject/supersede/expire mutation log 现在记录 `lineage_lock_wait_ms`，Approval expire 批处理摘要输出 `lineage_lock_wait_ms` 与 `lineage_lock_skip_total`；Agent metrics/dashboard required catalog 新增 `approval_lineage_lock_wait_ms`、`approval_lineage_lock_skip_total`，补齐架构 11.3 后台任务指标闭环，并同步专项单测与 Harness 文档。 |
| 2026-06-26 | 3.0.28-agent | Agent Harness+Loop 副作用边界与 BackendEffectCapability 观测继续推进：`AgentMetricsService.snapshot` 新增 send_intent orphan、安全重试、transport/backend_accepted uncertain、receipt_first/legacy_no_receipt capability、legacy manual、backend contract unsupported alias，以及 runtime/backend contract/run migration block 细分指标；dashboard required metrics catalog 与专项测试同步覆盖，补齐架构第 28 节恢复/治理指标。 |
| 2026-06-26 | 3.0.29-agent | Agent Harness+Loop Release/Approval 治理指标继续推进：`AgentMetricsService.snapshot` 新增 `approval_approve_conflict_total` 统计 approve CAS 冲突总数，并保留 `approval_epoch_conflict_total` 作为 epoch 冲突子集；新增 `release_gate_violation_count` 复用 release gate snapshot violations，与 `agent_release_gate_violation` alert 的 metric_key 对齐；dashboard required metrics catalog、专项测试与 Harness 文档同步更新。 |
| 2026-06-26 | 3.0.30-agent | Agent Harness+Loop Release gate runbook 覆盖继续推进：新增 `release_gate_violation` 生产处置 runbook，动态 `agent_release_gate_violation` P0 alert 现在输出非空 runbook_id，dashboard `runbook_catalog_complete` required catalog 同步纳入 release gate 处置路径；补充动态 alert runbook 单测并同步 Harness 文档。 |
| 2026-06-26 | 3.0.31-agent | Agent Harness+Loop RootCause priority band 治理继续推进：新增 `RootCauseRuleEngine.audit_rule_governance()`，输出 priority band 范围、违规列表和 `governance_pass`；修正默认 RootCause 规则使 `RC_PERMISSION_REVOKED` 落入 Safety / Policy band priority=15、`RC_RULE_MISSING` 落入 Fallback band priority=999；补充 priority band 审计单测并同步 Harness 文档。 |
| 2026-06-26 | 3.0.32-agent | Agent Harness+Loop RootCause 默认规则继续推进：新增 `RC_NO_PROGRESS_PURE` 默认规则，将纯 `same_failure_no_progress` 归因为 `same_failure_no_progress`，priority=60 且落入 Repair Quality band；LoopObservation 在证据完整、非高风险场景下可直接命中该规则，避免 fallback 到 `RC_RULE_MISSING`；补充专项单测并同步 Harness 文档。 |
| 2026-06-26 | 3.0.33-agent | Agent Harness+Loop RootCause Backend/Recovery 默认规则继续推进：新增 `RC_BACKEND_CAPABILITY_DEGRADED` 默认规则，将 `backend_capability_degraded` / `backend_contract_unsupported` 归因为 `backend_capability_degraded`，priority=45 且落入 Backend / Recovery band；LoopObservation 在证据完整、非高风险场景下可直接命中该规则，避免 fallback 到 `RC_RULE_MISSING`；补充专项单测并同步 Harness 文档。 |
| 2026-06-26 | 3.0.34-agent | Agent Harness+Loop RootCause Resource/Limit 默认规则继续推进：新增 `RC_MAX_ITERATIONS` 默认规则，将 `max_iterations` 归因为 `max_iterations`，priority=80 且落入 Resource / Limit band；LoopObservation 在证据完整、非高风险场景下可直接命中该规则，避免迭代上限停止 fallback 到 `RC_RULE_MISSING`；补充专项单测和 priority band 治理断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.35-agent | Agent Harness+Loop RootCause Evidence/Context 默认规则继续推进：新增 `RC_EVIDENCE_INCOMPLETE` 默认规则，将非 heavy context 下的高风险动作缺失 required evidence 归因为 `evidence_incomplete_for_high_risk_action`，priority=20 且落入 Evidence / Context band；LoopObservation 会继续让 heavy context 优先命中 `RC_CONTEXT_OMITTED_HIGH_RISK`，light/medium evidence gap 命中新规则，避免一般证据缺口 fallback 到 `RC_RULE_MISSING`；补充专项单测和 priority band 治理断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.36-agent | Agent Harness+Loop RootCause Memory contradiction 默认规则继续推进：新增 `RC_MEMORY_CONTRADICTION` 默认规则和 `numeric_gt` match expression，将 `memory_contradiction_delta > 0` 且同轮出现 `same_failure_no_progress` 的 LoopObservation 归因为 `memory_contradiction`，priority=30 且落入 Evidence / Context band；该规则优先于纯 `RC_NO_PROGRESS_PURE`，避免 Memory 污染导致的修复失败被误归因为普通 no progress；补充专项单测和 priority band 治理断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.37-agent | Agent Harness+Loop RootCause Safety/Policy 默认规则继续推进：新增 `RC_POLICY_LOOP` 默认规则，将 `policy_loop` 归因为 `policy_loop`，priority=18 且落入 Safety / Policy band；当同轮同时存在 `policy_loop` 与 `same_failure_no_progress` 时，LoopObservation 会优先记录 policy loop，避免策略循环被误归因为普通 no progress；同步修正架构表中该规则 priority 口径，并补充专项单测和 priority band 治理断言。 |
| 2026-06-26 | 3.0.38-agent | Agent Harness+Loop RootCause Resource/Limit 默认规则继续推进：新增 `RC_RESOURCE_LIMIT` 默认规则，将 `cost_budget_exceeded` / `context_budget_exhausted` 归因为 `resource_limit`，priority=85 且落入 Resource / Limit band；LoopObservation 会记录资源预算耗尽的 primary stop reason，并给出 `pause_or_request_budget` 缓解动作；同步修正架构表中该规则 priority 口径，并补充专项单测和 priority band 治理断言。 |
| 2026-06-26 | 3.0.39-agent | Agent Harness+Loop RootCause Repair Quality 默认规则继续推进：新增 `RC_REPAIR_REGRESSION` 默认规则，将 `repair_regression` / `new_failures_outside_scope` 归因为 `repair_regression`，priority=65 且落入 Repair Quality band；`RC_NO_PROGRESS_PURE` 新增 `none_reasons` 排除更具体的 repair/policy/evidence/backend/resource 信号，避免回归信号被普通 no progress 吞掉；同步修正架构表中该规则 priority 口径，并补充专项单测和 priority band 治理断言。 |
| 2026-06-26 | 3.0.40-agent | Agent Harness+Loop RootCause Fallback 默认规则继续推进：新增 `RC_UNKNOWN` 默认规则，将显式登记的 `accepted_unknown` 归因为 `unknown`，priority=900 且落入 Fallback band；`RC_RULE_MISSING` 保持 priority=999 的最终 always fallback，只处理未登记的新 reason 并继续驱动 `root_cause_rule_missing_total` 治理告警；补充 accepted unknown 与 unregistered reason 专项单测、priority band 治理断言，并同步 Harness 文档。 |
| 2026-06-26 | 3.0.41-agent | Agent Harness+Loop RootCause 规则治理入口继续推进：新增 `GET /api/v1/agents/root-cause-rules/audit` 管理员只读接口和 `AgentRootCauseRuleGovernanceAuditRead` schema，暴露 `RootCauseRuleEngine.audit_rule_governance()` 的 `priority_bands`、`violations`、`violation_count` 与 `governance_pass`，使 priority band 治理不再只停留在内部测试；补充 OpenAPI 路由断言、管理员权限断言和接口响应专项单测，并同步 Harness 文档。 |
| 2026-06-26 | 3.0.42-agent | Agent Harness+Loop readiness dashboard RootCause 治理继续推进：dashboard 新增 `root_cause_rule_governance` P1 check 和顶层 `root_cause_governance` summary，复用 `RootCauseRuleEngine.audit_rule_governance()` 暴露 priority band violation；当治理审计失败时 readiness 降为 attention，使 RootCause priority band 违规进入上线前可观测面；补充 dashboard pass/attention 专项单测并同步 Harness 文档。 |
| 2026-06-26 | 3.0.43-agent | Agent Harness+Loop Checkpoint Freshness Gate Memory freshness 继续推进：Freshness Gate 新增 active policy Memory 检查，读取最新 ContextBuild 的 memory EvidenceRef 并回查 `ProjectMemory.status/stale_score`；当 Memory `needs_revalidation` 或 `stale_score>=0.8` 时返回 `evidence_stale / active_memory_needs_revalidation`，阻止 resume 直接从旧 checkpoint 继续，并将非 fresh 的 `checkpoint.freshness_checked` 统一计入 `checkpoint_freshness_failed_total`；补充 resume 专项单测并同步 Harness 文档。 |
| 2026-06-26 | 3.0.44-agent | Agent Harness+Loop Checkpoint Freshness Gate runtime snapshot compatibility 继续推进：Freshness Gate 新增 checkpoint runtime snapshot 校验，确认 checkpoint 绑定的 `runtime_snapshot_id` 仍存在且与 run 当前 snapshot 一致；当 snapshot 缺失或不一致时返回 `too_old / replan_from_latest_safe_state` 与 `runtime_snapshot_missing/runtime_snapshot_mismatch`，阻止旧 checkpoint 使用过期 runtime registry/manifest/policy 继续 resume；补充 resume mismatch 专项单测并同步 Harness 文档。 |
| 2026-06-26 | 3.0.45-agent | Agent Harness+Loop Checkpoint Freshness Gate permission freshness 继续推进：Freshness Gate 支持传入 `current_user`，在 resume/migration resolve 前重验恢复后可能继续调度或执行的 ToolCall 所需权限；当 `required_permissions_json` 中任一权限已撤销时返回 `permission_stale / refresh_permissions_or_manual_review / required_permission_revoked`，并输出 `revoked_required_permissions`，避免 run 先 resume 再由 executor 才发现权限撤销；补充 resume permission freshness 专项单测并同步 Harness 文档。 |
| 2026-06-26 | 3.0.46-agent | Agent Harness+Loop Checkpoint Freshness Gate pending approval freshness 继续推进：Freshness Gate 将 pending approval 检查从单一数量升级为可审计明细，输出 `pending_approval_details`、`expired_pending_approval_count` 与 `stale_pending_approval_count`；当 pending approval 已过期时返回 `pending_approval_expired`，当 input/runtime/resource_scope/lineage/epoch 与当前 ToolCall 不一致时返回 `pending_approval_stale`，使 resume 前即可区分 expire、supersede 或继续等待；补充 expired pending approval resume 专项单测并同步 Harness 文档。 |
| 2026-06-26 | 3.0.47-agent | Agent Harness+Loop Checkpoint Freshness Gate environment freshness 继续推进：Freshness Gate 将 stale EvidenceWatch 分为普通 evidence stale 与 environment changed；当 stale watch 的 `ref_type=environment` 或 `stale_reason=environment.updated` 时返回 `environment_changed / revalidate_before_side_effect / environment_updated`，并输出 `environment_changed_count` 与 `stale_evidence_watch_details`，避免环境更新被误归入通用重建上下文路径；补充 environment resume 专项单测并同步 Harness 文档。 |
| 2026-06-26 | 3.0.48-agent | Agent Harness+Loop Checkpoint Freshness Gate active evidence freshness 继续推进：Freshness Gate 主动读取最新 ContextBuild 的 policy refs，识别 `latest_execution_sample` / `ephemeral_latest` 未冻结证据；当 resume 前仍存在此类 active policy ref 时返回 `evidence_stale / materialize_latest_evidence / ephemeral_latest_requires_materialization`，并输出 `active_evidence_revalidation_details`，避免长时间等待后旧 checkpoint 直接复用未 materialize 的 latest 样本；补充 ephemeral latest resume 专项单测并同步 Harness 文档。 |
| 2026-06-26 | 3.0.49-agent | Agent Harness+Loop Checkpoint Freshness Gate active evidence freshness 继续推进：Freshness Gate 将 active policy refs 的通用重验范围扩展到 `freshness_policy=revalidate_on_resume`、`mutability_class=external_uncontrolled` 与 `ref_type=external_doc`；此类外部不可控证据在 resume 前返回 `evidence_stale / fetch_evidence_and_rebuild_context / active_evidence_requires_revalidation`，并复用 `active_evidence_revalidation_details` 输出命中证据，避免外部文档或平台资源变化绕过 replay policy；补充 external uncontrolled resume 专项单测并同步 Harness 文档。 |
| 2026-06-26 | 3.0.50-agent | Agent Harness+Loop readiness dashboard catalog 契约继续推进：`fault_injection_catalog_complete` check details 现在输出 `covered_required_case_ids`、`missing_required_case_ids` 与 `extra_case_ids`，`runbook_catalog_complete` check details 输出 `covered_required_runbook_ids` 与 `missing_required_runbook_ids`；dashboard 顶层 summary 与 P0/P1 check details 使用一致字段，便于 UI/自动验收直接定位缺失 fault case 或 runbook；补充 dashboard 专项断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.51-agent | Agent Harness+Loop backend capability degradation 监控闭环继续推进：`backend_capability_degraded_total` 现在触发 `agent_backend_capability_degraded` P1 告警，并新增 `backend_capability_degraded` runbook；dashboard monitoring alerts clear 会在 legacy_reconcile_only / legacy_no_receipt capability 存在时进入 attention，避免 backend capability 降级只停留在 metrics catalog 而没有处置路径；补充 degraded capability dashboard/alert 专项单测并同步 Harness 文档。 |
| 2026-06-26 | 3.0.52-agent | Agent Harness+Loop Reconcile 细分恢复告警继续推进：`tool_call_send_intent_orphan_total`、`tool_call_safe_retry_after_send_intent_not_found_total`、`tool_call_transport_sent_uncertain_total` 与 `tool_call_backend_accepted_uncertain_total` 现在分别触发细分 alerts，并统一指向 `tool_call_uncertain` runbook；backend_accepted uncertain 作为 P0、transport_sent uncertain 作为 P1、send_intent orphan/safe retry 作为 P2，避免恢复阶段只暴露泛化 uncertain 告警而无法区分重试风险；补充 pre/post reconcile 专项断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.53-agent | Agent Harness+Loop Migration 细分阻断告警继续推进：`runtime_snapshot_migration_block_total`、`backend_contract_migration_block_total` 与 `run_migration_blocked_total` 现在分别触发 P1 alerts，并统一指向 `migration_blocked` runbook；在已有 `migration_block_open_total` 泛化告警之外，dashboard/alerts 可直接区分 runtime snapshot、backend contract adapter 与 run.status=migration_blocked 三类阻断来源；补充 unsupported schema migration block 专项断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.54-agent | Agent Harness+Loop Approval conflict 告警闭环继续推进：`approval_approve_conflict_total` 现在触发 `agent_approval_approve_conflict` P1 告警，并统一指向 `approval_stale` runbook；`approval_epoch_conflict_total` 保留为 epoch 子类告警，避免 stale/superseded 等非 epoch 审批冲突只进入 metrics 而不进入 dashboard/alerts；补充 stale + epoch approval conflict 专项断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.55-agent | Agent Harness+Loop ToolCall contract/capability 告警继续推进：`tool_call_backend_contract_unsupported_total` 现在触发 `agent_tool_call_backend_contract_unsupported` P1 告警并指向 `migration_blocked` runbook；`tool_call_legacy_no_receipt_manual_total` 触发 `agent_legacy_no_receipt_manual_intervention` P0 告警并指向 `backend_capability_degraded` runbook，避免 ToolCall 级 contract/schema unsupported 或 high-risk legacy_no_receipt manual 只停留在 metrics；补充 migration 与 legacy_no_receipt 专项断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.56-agent | Agent Harness+Loop Approval lineage lock 告警继续推进：`approval_lineage_lock_wait_ms` 现在触发 `agent_approval_lineage_lock_wait` P2 告警，`approval_lineage_lock_skip_total` 触发 `agent_approval_lineage_lock_skip` P2 告警，二者统一指向 `approval_stale` runbook；dashboard 可观察 approval lineage 锁等待累积与批量 expire 跳过 lineage，但不把 P2 观测告警直接降级为 attention；补充 mutation log 聚合专项断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.57-agent | Agent Harness+Loop Approval expire batch lag 告警继续推进：`approval_expire_batch_lag_ms` 现在触发 `agent_approval_expire_batch_lag` P2 告警并指向 `approval_stale` runbook，补齐架构中 due backlog、batch lag 与 lineage hotspot 三类 expire 观测面的 alerts 闭环；补充到期审批扫描专项断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.58-agent | Agent Harness+Loop Checkpoint Freshness Gate 告警继续推进：`checkpoint_freshness_failed_total` 现在触发 `agent_checkpoint_freshness_failed` P1 告警并指向 `checkpoint_stale` runbook；resume 或 migration resolve 因 runtime snapshot、approval、permission、environment、active evidence 或 Memory freshness 被阻断时会进入 dashboard attention，避免 freshness gate 失败只停留在 metrics；补充 runtime snapshot mismatch 专项断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.59-agent | Agent Harness+Loop 条件化告警能力继续推进：`AgentAlertService` 的 metric rules 现在支持默认 `gt` 与显式 `lt` 条件、可配置 threshold；新增 `agent_fault_injection_coverage_ratio_low`，当 `fault_injection_coverage_ratio < 1.0` 时触发 P1 告警并指向 `fault_injection_coverage` runbook，补齐 fault coverage ratio 低于 100% 的可观测告警闭环；补充临时缺失 required case 专项断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.60-agent | Agent Harness+Loop 告警上下文指标继续推进：`AgentAlertService` 的 metric rules 新增 `related_metric_keys`，firing alert 会在 `details.related_metrics` 输出相关规模/分布指标；backend capability degraded 告警携带 receipt_first 与 legacy_no_receipt capability 分布，event replay stress 告警携带 cursor/window 规模，fault injection coverage 告警携带 required/registered/missing/coverage ratio 上下文，避免把正向指标误建为噪声告警，同时补齐架构事实表中上下文指标的可审计输出；补充三个专项断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.61-agent | Agent Harness+Loop alert metric catalog 审计继续推进：readiness dashboard 新增 `alert_metric_catalog_complete` P1 check，按 trigger、related 与 dynamic 三类路径审计 `ALERT_FACT_METRICS` 覆盖情况，details 输出 required/covered/missing、trigger、related 与 dynamic metric keys；`release_gate_violation_count` 作为动态 release gate 告警覆盖，正向规模指标通过 `related_metric_keys` 覆盖，避免 AgentAlertService 事实表和实现再次漂移；补充 dashboard catalog 专项断言并同步 Harness 文档。 |
| 2026-06-26 | 3.0.62-agent | Agent Harness+Loop API 契约覆盖继续推进：新增文档驱动 OpenAPI 覆盖测试，从开发计划和架构文档抽取所有 `/api/v1/agents...` 路径并与 `create_app().openapi()["paths"]` 对齐，历史 memory `{id}` 占位符归一化为当前 `{memory_id}`；避免 Harness 文档新增或修改 Agent API 后路由实现和 OpenAPI 声明漂移；同步 Harness API 契约测试说明。 |
| 2026-06-26 | 3.0.63-agent | Agent Harness+Loop API 契约覆盖继续推进：文档驱动 OpenAPI 覆盖测试从 path-only 升级为 method+path 校验，抽取 Harness 开发计划和架构文档中的 `GET/POST/PATCH/DELETE/PUT /api/v1/agents...` operation，并确认 OpenAPI 对应 path 下声明了相同 HTTP method；继续保留 memory `{id}` 到 `{memory_id}` 的占位符归一化，避免文档 method 语义和路由实现漂移。 |
| 2026-06-26 | 3.0.64-agent | Agent Harness+Loop Approval API 契约覆盖继续推进：新增 OpenAPI 请求体 schema 断言，要求 approve/reject 路由共用 `AgentApprovalDecisionRequest`，并将 `input_hash`、`runtime_snapshot_id`、`resource_scope_hash`、`approval_lineage_id`、`approval_epoch` 固定为 required CAS 字段，`reason` 保持可选；同步开发计划和架构文档中的审批请求体契约，并统一 epoch 冲突错误码为 `approval_epoch_conflict`。 |
| 2026-06-26 | 3.0.65-agent | Agent Harness+Loop Approval API 错误码契约继续推进：`ApprovalService` 现在将 approve/reject 提交的 `input_hash` 与当前审批 input 不一致单独返回 `approval_input_changed`，并在 `approval.approve_conflict` 事件 payload 中保留该错误码；专项单测覆盖 input hash 与 epoch 两类冲突的 HTTP code、事件 error_code、总冲突指标与 epoch 子类指标，开发计划错误码清单同步冻结 `approval_input_changed`。 |
| 2026-06-26 | 3.0.66-agent | Agent Harness+Loop EventStore/Outbox 写入契约继续推进：`AgentRuntimeService.append_event` 现在将 EventStore 或同事务 Outbox 持久化失败统一包装为 `500 event_outbox_write_failed`，并回滚失败事件、Outbox 记录与 `last_event_sequence` 推进；新增专项单测模拟 Outbox 约束失败，确认冻结错误码和事务回滚语义，同时同步 Harness 开发计划与架构文档中的事务边界说明。 |
| 2026-06-26 | 3.0.67-agent | Agent Harness+Loop Checkpoint Freshness API 错误码继续推进：`AgentRunResumeService.resume_run` 在 Freshness Gate 返回 `replan_from_latest_safe_state` 时，将 Run 暂停态 `error_code` 与 `run.paused` 事件 payload 固定为冻结错误码 `checkpoint_stale_replan_required`，同时保留原 freshness `result/action/reason` 供恢复决策使用；专项单测覆盖 runtime snapshot mismatch 下的 run error code、事件 error_code 与 checkpoint stale 告警，Harness 文档同步该契约。 |
| 2026-06-26 | 3.0.68-agent | Agent Harness+Loop Reconcile 冻结错误码继续推进：高风险 `legacy_no_receipt` ToolCall 命中自动 reconcile 阻断时改为专用 `backend_reconcile_not_supported`；WorkerQueue claim 阶段新增 uncertain/reconciling 防线，误入执行队列时不调用后端工具，队列项失败、ToolCall 保持 uncertain，并输出 `tool_call_uncertain_reconcile_required` 与 `reconcile_required_before_execution`；新增两项专项断言并同步 Harness ReconcileWorker 文档。 |
| 2026-06-26 | 3.0.69-agent | Agent Harness+Loop 冻结状态枚举契约继续推进：`GET /api/v1/agents/capabilities` 现在补齐 `approval_statuses` 与 `migration_block_statuses`，`ApprovalStatus` schema 接受文档冻结的 `revoked`，`AgentMigrationBlockRead.status` 收紧为 `MigrationBlockStatus`；新增文档驱动专项测试，从开发计划 4.2 抽取 Run、ToolCall、Effect Submission State、BackendEffectCapability、Approval 与 Migration Block 六组枚举并与 capabilities 响应精确比对，避免文档、schema 与运行时能力出口漂移。 |
| 2026-06-26 | 3.0.70-agent | Agent Harness+Loop Memory 治理冻结配置继续推进：新增文档驱动专项测试，从架构文档 Memory source profile 与默认 retrieval profile 表格抽取冻结契约，并与 `MemorySourceProfileResolver` / `MemoryRetrievalProfileResolver` 默认 seed 对齐；覆盖 source 初始 confidence/authority、retrieval profile 的 min_confidence/max_stale_score、active/version/change_reason 与 ranking 权重字段，避免 Memory 治理参数只停留在文档说明或代码常量中。 |
| 2026-06-26 | 3.0.71-agent | Agent Harness+Loop Memory contradiction penalty 冻结契约继续推进：新增文档驱动专项测试，从架构文档 15.5 抽取 Severity multiplier 与默认 `max_contradiction_penalty` 上限，并与 `SEVERITY_MULTIPLIER`、`MemoryRetrievalProfileResolver` 默认 seed 和 `compute_contradiction_penalty` 公式输出对齐；覆盖 base/recent/same_failure/severity/validation_offset/clamp 计算链路，避免 contradiction penalty 重新退化成不可审计黑盒函数。 |
| 2026-06-26 | 3.0.72-agent | Agent Harness+Loop Memory EvidenceRef 映射契约继续推进：新增文档驱动专项测试，从开发计划 Memory 章节抽取 `trace_only/planning_hint/repair_hint/policy_dependency` usage_role 与 active role，验证 `MemoryEvidenceAdapter.to_evidence_ref` 输出 `ref_type=memory`、版本/content hash、`mutable_current`、`revalidate_before_side_effect`、`required_for_high_risk=false`、`authority=memory:{source_type}`，并确认 `EvidenceRefResolver.select_policy_refs` 只选择 `policy_dependency`；同步架构文档中 Memory role 语义，消除旧 `decision_dependency` 示例与当前实现的漂移。 |
| 2026-06-26 | 3.0.73-agent | Agent Harness+Loop Memory high-risk gate 继续推进：`PolicyManager.ensure_context_allows_execution` 现在要求高风险动作的 active policy refs 至少包含 `system_record/project_config/execution_record/document_imported` 中一种可信支撑证据，避免 memory + 任意非 memory 引用绕过 `high_risk_action_cannot_depend_only_on_memory`；新增专项测试覆盖 memory+external_doc 仍阻断、memory+execution_record 放行，并同步架构伪代码与开发计划验收说明。 |
| 2026-06-26 | 3.0.74-agent | Agent Harness+Loop Memory EvidenceWatch 环境 stale gate 继续推进：`MemoryManager` high-risk hard gate 现在识别 `stale_reason=environment.updated` 并直接过滤，即使 stale_score 等于 `high_risk_action_v1.max_stale_score=0.30` 也不能继续作为高风险动作 Memory 候选；新增专项测试覆盖 environment EvidenceWatch stale 级联到 Memory staleness event、状态进入 `needs_revalidation` 且 high-risk 检索返回空，并同步开发计划和架构 hard gate 说明。 |
| 2026-06-26 | 3.0.75-agent | Agent Harness+Loop Memory EvidenceWatch 外部事件契约继续推进：新增文档驱动专项测试，从架构 15.6 外部事件处理表抽取 `scenario.updated/testcase.updated/environment.updated/manifest.changed/document.updated` 的 stale_score delta 与 `needs_revalidation` 要求，并逐项验证 `MemoryStalenessWorker` 级联更新 memory 与 staleness event；同步开发计划与架构表中 manifest delta/status 说明，避免 Memory 外部事件常量与文档漂移。 |
| 2026-06-26 | 3.0.76-agent | Agent Harness+Loop Memory execution_record.created 契约继续推进：新增 `MemoryFeedbackWorker.process_execution_record_created`，按 execution_record EvidenceLink 找到关联 memory，将支持性 execution evidence 记录为 `memory_validated` 并更新 validation_count/recent_validation_count/last_validated_at，将反驳性 execution evidence 复用 contradiction event 通路记录 `execution_record_created`；新增文档驱动专项测试确认架构 15.6 要求 validation/contradiction event，并覆盖验证与反驳两条分支，避免 execution_record.created 被误实现为 stale event。 |
| 2026-06-26 | 3.0.77-agent | Agent Harness+Loop Memory source profile high-risk allowlist 继续推进：`MemoryManager` high-risk hard gate 现在同时检查 `AgentMemorySourceProfile.allowed_for_high_risk`，阻断 `external_imported/agent_summarized/repair_inferred` 等来源即使被人工抬高 confidence 且置为 active 也进入高风险 policy dependency；架构 source profile 表新增默认创建状态与 allowed_for_high_risk 列，专项测试从文档解析 allowlist 并验证 `execution_learned` 经验证后可进入高风险候选、`external_imported` 仍被过滤。 |
| 2026-06-26 | 3.0.78-agent | Agent Harness+Loop Memory -> LoopObservation 链路继续推进：`LoopController.record_observation` 现在从 decision ContextBuild 的 active memory policy refs 自动派生 `memory_usage` 与 `memory_contradiction_delta`，并用派生后的 observation 进入 `RootCauseRuleEngine`；当 policy memory 已有 contradiction event 且出现 same_failure_no_progress 时，即使调用方未手工传入 `memory_contradiction_delta`，也会优先命中 `RC_MEMORY_CONTRADICTION` 而不是普通 no-progress；新增专项测试并同步开发计划与架构 15.7。 |
| 2026-06-26 | 3.0.79-agent | Agent Harness+Loop Memory TTL 自动降权继续推进：新增 `MemoryMaintenanceWorker.process_expired_ttl`，扫描超过 `expires_at` 且 `validation_count=0` 的 memory，按架构 15.8 将 `stale_score +0.10` 并记录 `stale_reason=memory_ttl.expired`，超过阈值后进入 `needs_revalidation`；专项测试覆盖未验证过期 memory 进入 revalidation、已验证 memory 不被 TTL 维护任务降权，并确认 `memory_needs_revalidation_total` 指标同步可见。 |
| 2026-06-26 | 3.0.80-agent | Agent Harness+Loop Memory revalidation 告警闭环继续推进：`memory_needs_revalidation_total` 现在进入 `ALERT_FACT_METRICS` 并触发 `agent_memory_needs_revalidation` P1 告警，指向 `checkpoint_stale` runbook；dashboard `monitoring_alerts_clear` 会因 Memory freshness/revalidation 问题进入 attention，避免 needs_revalidation 只停留在 metrics 或 resume 时才被动发现；新增专项测试覆盖 alert、runbook 与 dashboard readiness 联动并同步 Harness 监控文档。 |
| 2026-06-26 | 3.0.81-agent | Agent Harness+Loop Memory execution evidence 验证契约继续推进：`MemoryFeedbackWorker` 对 `validated` outcome 单独执行架构 15.8 的 `stale_score -0.10`，其他正反馈仍保持 `-0.08`；execution_record.created 专项测试现在从架构表抽取 `confidence +0.05 / stale_score -0.10` 并断言返回结果与落库 stale_score 一致，避免支持性 execution evidence 被普通正反馈 delta 吞掉；同步开发计划验收项。 |
| 2026-06-26 | 3.0.82-agent | Agent Harness+Loop Memory 人工否定契约继续推进：`MemoryManager.reject_memory` 按架构 15.8 将用户明确否定的 memory 置为 `status=rejected` 且 `confidence=min(confidence,0.10)`，不再直接清零置信度；治理专项测试从架构表抽取用户确认与用户否定规则，断言 validate 的 `confidence +0.10 / last_validated_at` 和 reject 的冻结置信度上限，开发计划同步该验收口径。 |
| 2026-06-26 | 3.0.83-agent | Agent Harness+Loop Memory 连续相同 failure fingerprint 治理继续推进：`MemoryManager.record_contradiction` 与 `MemoryFeedbackWorker` contradiction 分支现在都会在当前 `failure_fingerprint` 与上一条 `last_failure_fingerprint` 相同时将 memory 标记为 `suspect`，同时保留 critical/active policy 进入 `needs_revalidation` 的更高优先级；新增文档驱动专项测试从架构 15.8 抽取“同一 memory 连续导致相同 failure fingerprint”规则，并覆盖直接 contradiction 与 feedback contradiction 两条入口。 |
| 2026-06-26 | 3.0.84-agent | Agent Harness+Loop Memory execution evidence 反驳降权契约继续推进：`MemoryFeedbackWorker` contradiction 分支按架构 15.8 固定执行 `confidence -0.15; stale_score +0.25`，不再使用 severity-based confidence delta；feedback result 新增 `stale_delta` 便于审计，专项测试从架构表抽取“execution evidence 证明错误”动作并断言 confidence/stale 两个 delta，开发计划同步该基础降权幅度不能被 severity 改写。 |
| 2026-06-26 | 3.0.85-agent | Agent Harness+Loop Memory validation event 审计继续推进：新增 `ai_agent_memory_validation_events` 模型/迁移表、`AgentMemoryValidationEventRead` schema 和 `GET /api/v1/agents/memory-validation-events` 只读接口；`MemoryManager.validate_memory` 与 `MemoryFeedbackWorker` 的 `validated` 分支现在都会记录 validation_source、confidence/stale/status 前后值、validation_count、usage/evidence/run/tool 关联，补齐架构 15.8 “用户确认正确新增 validation event”的审计闭环；专项测试覆盖人工确认、execution_record.created 验证、OpenAPI 路由和文档驱动 API 清单。 |
| 2026-06-26 | 3.0.86-agent | Agent Harness+Loop Memory 写入边界继续推进：`MemoryManager.create_memory` 与 `update_memory` 现在强制 `execution_learned` 至少包含 2 个不同 `execution_record` EvidenceRef，否则返回 `422 execution_learned_requires_two_execution_evidence`；补充文档驱动专项测试从架构 15.9 / Source Profile 抽取“至少 2 次一致 execution evidence”要求，覆盖创建失败路径、合法 execution_learned 高风险候选和 execution_record.created 验证链路，开发计划同步创建/更新 evidence refs 的验收口径。 |
| 2026-06-26 | 3.0.87-agent | Agent Harness+Loop Memory repair_inferred 激活边界继续推进：`MemoryManager.validate_memory` 现在阻止 `repair_inferred` 通过普通 validate API 直接 active，返回 `409 repair_inferred_requires_execution_validation`；`execution_record.created` 支持性验证路径仍可将 repair 推断从 `needs_review` 激活，并写入 validation event；新增文档驱动专项测试覆盖架构 15.9 “必须后续执行验证，不得直接 active”要求，开发计划同步该边界。 |
| 2026-06-26 | 3.0.88-agent | Agent Harness+Loop Memory 用户确认验证增量契约继续推进：`MemoryManager.validate_memory` 现在严格按架构 15.8 执行 `confidence +0.10` 并 clamp 到 `0.0..0.95`，不再把低置信度候选直接抬升到 source profile 的 `initial_confidence`；治理专项测试补充低 confidence memory 的人工验证样例，并断言 validation event 的 previous/new confidence 精确记录该增量，避免用户确认路径绕过文档定义的置信度模型。 |
| 2026-06-26 | 3.0.89-agent | Agent Harness+Loop Memory 进入 Loop 唯一路径继续推进：`ContextBuilder` 现在要求 `memory_ids_used` 中声明已使用的 memory 必须存在对应的 active policy memory EvidenceRef，仅提供 `planning_hint/trace_only` 等 audit-only memory ref 仍会触发 `memory_bypassed_evidence_ref`，并写入 `memory.bypassed_evidence_ref` 事件；新增文档驱动专项测试从架构 15.7 抽取 `ContextBuilder -> ToolPolicyResolver.select_policy_evidence_refs -> active policy refs` 链路，避免 Memory 绕过 active policy refs 后导致 LoopObservation、RootCause 和监控统计漏判。 |
| 2026-06-26 | 3.0.90-agent | Agent Harness+Loop 高风险 Memory 支撑证据继续推进：`PolicyManager.ensure_context_allows_execution` 现在要求高风险动作的非 Memory 支撑证据同时满足受信来源与冻结/可重验证条件，`system_record/project_config/execution_record/document_imported` 仅在 `immutable/versioned` 且带 `content_hash/version_id/snapshot_id`，或声明 `freshness_policy=revalidate_before_side_effect` 时才可作为 Memory 之外的高风险支撑；专项测试覆盖任意非 Memory 引用阻断、受信但 mutable 且不可重验证阻断、immutable+hash 放行和可重验证放行，架构 15.7 同步执行时判定口径。 |
| 2026-06-26 | 3.0.91-agent | Agent Harness+Loop Memory 文档导入写入边界继续推进：`MemoryManager.create_memory` 与 `update_memory` 现在强制 `document_imported` 的 `source_ref_json` 携带文档内容 hash（`content_hash` / `document_hash` / `source_hash`），缺失时返回 `422 document_imported_source_hash_required`；文档驱动专项测试从架构 source profile 表抽取 `document_imported` 的 `content_hash` 要求，并覆盖缺 hash 阻断路径，既有 document_imported 样例同步补齐 source hash，开发计划 10.3.7 与架构 15.9 同步该验收口径。 |
| 2026-06-26 | 3.0.92-agent | Agent Harness+Loop Memory source profile 内容 hash 治理继续推进：默认 `MemorySourceProfileResolver` seed 现在显式写入 `requires_content_hash`，并将运行时 source_ref hash 校验改为读取 profile 配置；内置 profiles 中仅 `document_imported` 要求 source_ref 携带文档内容 hash，其余 source_type 保持关闭，避免字段存在但运行时仍靠来源名称硬编码。专项测试新增默认 profile `requires_content_hash` 对齐断言，并覆盖 document_imported 更新 source_ref 移除 hash 的阻断路径；开发计划与架构同步 profile 驱动验收口径。 |
| 2026-06-26 | 3.0.93-agent | Agent Harness+Loop 高风险空证据阻断继续推进：`PolicyManager.ensure_context_allows_execution` 现在对高风险动作强制要求至少一个 active policy ref 能提供受信且冻结/可重验证支撑，空 `policy_evidence_refs_json` 不再绕过 Memory-only 防线，而是返回 `409 high_risk_action_cannot_depend_only_on_memory`；专项测试覆盖存在 ContextBuild 但 active policy refs 为空的高风险动作阻断路径，架构 15.7 伪代码同步 frozen/revalidatable trusted support 判定，避免说明文字与示例逻辑漂移。 |
| 2026-06-26 | 3.0.94-agent | Agent Memory 用户否定检索门禁补强：围绕“用户明确否定的 memory 必须 rejected 且不再被检索”的验收补充运行时回归，使用 `min_confidence=0.0`、`max_stale_score=1.0` 的专用 retrieval profile 穿过低置信度与 stale 门槛，直接验证 rejected 状态本身会被 `MemoryManager.retrieve` 硬过滤，且不会产生 `AgentMemoryUsageEvent`；现有实现无需改动，测试防止后续检索逻辑放宽时让已否定 Memory 重新进入上下文。 |
| 2026-06-26 | 3.0.95-agent | Agent Approval reject 过期 CAS 补强：`ApprovalMutationGuard.reject` 现在与 approve 共用 pending/immutable 与 `expires_at > now` 校验，过期但仍 pending 的审批在用户点击 reject 时返回 `409 approval_stale_or_superseded`，写入 `approval.reject_conflict`，不会把 approval 改成 rejected；专项测试覆盖 stale client reject 场景，开发计划 8.6 与架构 API 说明同步为 approve/reject 共用 CAS 字段和过期检查，保证前端过期审批页统一走 409 刷新语义。 |
| 2026-06-26 | 3.0.96-agent | Agent Approval ToolCall 状态门禁补强：`ApprovalMutationGuard.approve/reject` 现在在 CAS 与过期检查后强制校验 ToolCall 仍处于可审批状态（`planned`/`pending_approval`），若已进入 `running_pre_effect`、`obsolete` 等执行中或废弃状态则返回 `409 tool_call_not_approvable` 并写入对应 approve/reject conflict 事件，不会继续批准、拒绝或改写 ToolCall；专项测试覆盖 running approve 与 obsolete reject 两条 stale 决策路径，架构 11.1 伪代码同步为所有非可审批状态统一返回冻结错误码 `tool_call_not_approvable`。 |
| 2026-06-26 | 3.0.97-agent | Agent Approval 过期决策落库补强：approve/reject 在持有 lineage、approval 与 ToolCall 锁后如果发现 `expires_at <= now`，现在复用同一条 expired mutation/event 路径先将 approval 标记为 `expired`、ToolCall 标记为 `manual_intervention` 且 `error_code=approval_expired`，再返回 `409 approval_stale_or_superseded` 并记录对应 approve/reject conflict；后台 `ApprovalExpireScanner` 与用户决策路径共享 `_mark_expired_locked`，专项测试覆盖 approve 与 reject 两条 stale client 决策路径，和架构 11.1 `mark_expired(approval)` 伪代码保持一致。 |
| 2026-06-26 | 3.0.98-agent | Agent Approval 批量 expire lineage 去重补强：`ApprovalExpireScanner.expire_due_summary` 现在按唯一 `approval_lineage_id` 执行短事务，同一 lineage 下重复 due pending approval 不再在同一批内多次推进，而是计入 `skipped_duplicate_lineage_count` 并纳入 `skipped`；专项测试覆盖 lineage hotspot 场景只写一条 expire mutation、`processed_lineage_ids` 保持唯一，开发计划 8.5 与架构 11.3 同步该返回字段和处理模型，避免批量后台任务在热点 lineage 上制造额外锁竞争。 |
| 2026-06-26 | 3.0.99-agent | Agent Approval expire process API schema 补齐：`AgentApprovalExpireProcessRead` 现在显式暴露 `skipped_duplicate_lineage_count`，避免 3.0.98 中 service summary 新增的 duplicate-lineage skip 观测字段在 API 响应模型中被吞掉；专项测试覆盖 `ApprovalExpireScanner.expire_due_summary` 经 Pydantic response schema 后仍保留该字段，并确认 model_dump 输出与 service summary 一致。Harness 开发计划与架构文档已在 3.0.98 同步字段语义，本轮无需新增迁移。 |
| 2026-06-26 | 3.0.100-agent | Agent Approval expire process 锁观测 schema 补齐：`AgentApprovalExpireProcessRead` 继续补齐 `lineage_lock_wait_ms` 与 `lineage_lock_skip_total`，使批量 expire process API 响应模型完整暴露架构 11.3 要求的 lineage 锁等待与跳过观测字段；专项测试扩展为同时验证 `skipped_duplicate_lineage_count`、`lineage_lock_wait_ms`、`lineage_lock_skip_total` 经 response schema 后与 service summary 保持一致。Harness 架构文档已声明这些字段，本轮无需新增迁移。 |
| 2026-06-26 | 3.0.101-agent | Agent Release Gate promotion 可观测字段补齐：`AgentReleaseGateService.promotion_assessment` 现在在顶层直接输出 `dashboard_checks`、`fault_injection` 与 `alert_summary`，同时保留原有 `readiness` 嵌套结构，方便前端和自动验收直接读取开发计划要求的 dashboard checks、fault coverage 与 alert summary；`AgentReleaseGatePromotionRead` 同步补齐这些字段，专项测试验证顶层字段与 nested readiness 保持一致并能通过 response schema。 |
| 2026-06-26 | 3.0.102-agent | Agent Fault Injection 全局目录权限边界补强：`GET /api/v1/agents/fault-injections` 与 `GET /api/v1/agents/fault-injections/coverage` 现在与 fault-injections/run 及其他全局审计接口保持一致，仅允许 admin 访问；非 admin 调用返回 403，admin 可读取生产硬化用例清单与 coverage 审计结果。专项测试覆盖 catalog/coverage 两个只读接口的 403 与 admin 成功路径，开发计划与架构文档同步 admin-only 全局生产硬化目录/审计边界。 |
| 2026-06-26 | 3.0.103-agent | Agent Memory usage 审计权限边界补强：`GET /api/v1/agents/memory-usage-events` 不带 `run_id` 时现在作为全局审计视图仅允许 admin 访问，非 admin 返回 403；带 `run_id` 时继续复用 `AgentRuntimeService.get_run` 的项目访问校验并只返回该 run 的 usage events。专项测试覆盖非 admin 全局拒绝、项目用户按 run 查询成功、admin 全局查询成功，开发计划与架构文档同步该全局/按 run 分层权限语义。 |
| 2026-06-26 | 3.0.104-agent | Agent Release Gate 全局快照权限边界补强：`GET /api/v1/agents/release-gates` 现在作为全局发布门禁治理视图仅允许 admin 访问，非 admin 返回 403；admin 可读取当前 rollout level、tool matrix、静态门禁与 violation 快照。专项测试覆盖非 admin 拒绝与 admin 成功读取，开发计划与架构文档同步该 admin-only 全局快照语义，并在架构聚合接口清单中补齐 `/release-gates` 路径。 |
| 2026-06-26 | 3.0.105-agent | Agent Backend Contract 全局契约权限边界补强：`GET /api/v1/agents/backend-contracts/{backend_name}/operations/{backend_operation}` 现在作为全局 backend operation contract 治理视图仅允许 admin 访问，非 admin 返回 403；admin 可读取 schema hash、reconcile contract、result adapter 与 operation 级 effect capability。专项测试覆盖非 admin 拒绝与 admin 成功查询，开发计划与架构文档同步该 admin-only contract/capability 查询语义。 |
| 2026-06-26 | 3.0.106-agent | Agent Memory report stale 事件契约补齐：MemoryStalenessWorker 现在显式支持 `report.updated`、`report.deleted` 与 `report.regenerated`，关联 report 的 Memory 统一 `stale_score +0.20` 并写入 `AgentMemoryStalenessEvent`；文档驱动测试将三类 report 事件纳入架构外部事件处理表校验，开发计划同步 scenario/testcase/environment/manifest/document/report 全量 stale 事件验收清单。 |
| 2026-06-26 | 3.0.107-agent | Agent Memory 非 stale 平台事件守门补强：MemoryStalenessWorker 现在拒绝 `execution_record.created`、`permission.changed` 与 `memory.status_changed`，返回 `422 memory_event_not_stale_event`，避免 execution validation、权限变更与 Memory 自身状态变化被误写成普通 stale event 并污染 stale_score；专项测试覆盖三类事件拒绝后 Memory 状态、stale_score 和 staleness event 均不变化，开发计划与架构文档同步非 stale 事件分流语义。 |
| 2026-06-26 | 3.0.108-agent | Agent Memory 非 stale 事件冻结错误码契约补强：将 `422 memory_event_not_stale_event` 登记到 Harness 开发计划 4.3 冻结 API 错误码清单，并在架构外部事件表中明确 `execution_record.created` 误路由、`permission.changed` 与 `memory.status_changed` 由 MemoryStalenessWorker 以该错误码拒绝后分流处理；新增文档驱动专项测试校验冻结错误码清单与架构事件表包含该 Memory staleness guard，避免实现已有守门错误码但 API 契约漏登记。 |
| 2026-06-26 | 3.0.109-agent | Agent BackendEffectCapability 弱能力执行守门回归补强：新增 ToolExecutor 专项测试覆盖高风险 ToolCall 已具备可信执行证据但缺失 operation 级 backend capability 时，必须在调用 backend adapter 前转 `manual_intervention`，写入冻结错误码 `backend_capability_too_weak`，并将 WorkerQueue 标记 failed；Harness 开发计划 4.3 已冻结该错误码，架构 7.4 已声明高风险副作用 capability 不满足时禁止/转人工，本轮补齐自动化验收防线，无需新增迁移。 |
| 2026-06-26 | 3.0.110-agent | Agent cancel 后调度冻结错误码回归补强：新增 ExecutionLedgerService 专项测试覆盖 Run 取消后再次创建 ToolCall 必须返回 `409 tool_call_obsolete`，且不会新增 `AgentToolCall` 落库；该行为对应 Harness 开发计划 Phase 0/4.3 中“cancel 后不得调度新的 tool_call”与冻结错误码 `tool_call_obsolete`，本轮补齐取消态调度边界的自动化验收，无需新增迁移。 |
| 2026-06-26 | 3.0.111-agent | Agent Checkpoint Freshness Gate pending approval 明细回归补强：在既有过期 approval 检查基础上，新增 `pending_approval_stale` 与 `pending_approval_after_wait` 两条专项测试，分别覆盖 approval 不可变字段与当前 ToolCall 不一致、以及仍在正常等待审批的恢复门禁输出；断言 `pending_approval_details`、`expired_pending_approval_count`、`stale_pending_approval_count` 和 reason 均符合 Harness 开发计划 10.2/架构 8.3 的可审计明细要求，无需新增迁移。 |
| 2026-06-26 | 3.0.112-agent | Agent Checkpoint Freshness Gate permission freshness 状态矩阵回归补强：新增专项测试固定 `planned/approved/executable/failed_retryable/uncertain/reconciling` 这组恢复后仍可能继续调度或执行的 ToolCall 都必须在 resume 前重验权限，缺失权限时统一输出 `permission_stale`、`required_permission_revoked` 与逐项 `revoked_required_permissions` 明细；同时加入 `succeeded` 反例，避免已结束 ToolCall 被误纳入恢复门禁，和 Harness 开发计划 10.2/架构 8.3 的 Permission freshness 契约保持一致，无需新增迁移。 |
| 2026-06-26 | 3.0.113-agent | Agent Checkpoint Freshness Gate runtime snapshot 缺失分支回归补强：新增专项测试覆盖 checkpoint 绑定的 `runtime_snapshot_id` 已不存在时，resume 必须暂停并返回 `result=too_old`、`action=replan_from_latest_safe_state`、`reason=runtime_snapshot_missing`，同时 Run 与 `run.paused` 事件统一暴露冻结错误码 `checkpoint_stale_replan_required`；该用例补齐 Harness 开发计划 10.2/架构 8.3 对 runtime snapshot compatibility 两类失败原因的自动化验收，无需新增迁移。 |
| 2026-06-26 | 3.0.114-agent | Agent Checkpoint Freshness Gate backend contract compatibility 回归补强：新增专项测试覆盖 ToolCall 携带 backend name/operation/contract version 但当前没有 active `AgentBackendContract` 时，resume 必须暂停并返回 `result=backend_contract_changed`、`action=migration_block`、`reason=backend_contract_missing`，Run 与 `run.paused` 事件统一暴露 `migration_block`；该用例补齐 Harness 开发计划 10.2 对 backend_contract compatibility 的恢复门禁验收，无需新增迁移。 |
| 2026-06-26 | 3.0.115-agent | Agent Checkpoint Freshness Gate 普通 stale evidence 明细回归补强：扩展 scenario EvidenceWatch stale 的 resume 专项测试，断言普通 scenario/report 等非环境 stale evidence 必须返回 `result=evidence_stale`、`action=fetch_evidence_and_rebuild_context`、`reason=stale_evidence_watch`，并输出 `stale_evidence_watch_count`、`environment_changed_count=0` 与逐项 `stale_evidence_watch_details`；该用例与 Harness 开发计划 10.2/架构 8.3 的 environment freshness 分流契约保持一致，无需新增迁移。 |
| 2026-06-26 | 3.0.116-agent | Agent Checkpoint Freshness Gate active evidence revalidation 条件矩阵回归补强：扩展外部不可控 evidence resume 专项测试，将 `freshness_policy=revalidate_on_resume`、`mutability_class=external_uncontrolled` 与 `ref_type=external_doc` 拆成三个独立 active policy ref，断言三者都会进入 `active_evidence_requires_revalidation`、`fetch_evidence_and_rebuild_context` 并输出逐项 `active_evidence_revalidation_details`；该用例补齐 Harness 开发计划 10.2/架构 8.3 对 active evidence freshness OR 条件的自动化验收，无需新增迁移。 |
| 2026-06-26 | 3.0.117-agent | Agent Checkpoint Freshness Gate latest evidence materialize 条件矩阵回归补强：扩展未冻结 latest evidence resume 专项测试，将 `ref_type=latest_execution_sample` 与 `mutability_class=ephemeral_latest` 拆成两个独立 active policy ref，断言二者都会触发 `ephemeral_latest_requires_materialization`、`materialize_latest_evidence` 并输出逐项 `active_evidence_revalidation_details`；该用例补齐 Harness 开发计划 10.2/架构 6.2.2/8.3 对 latest 证据 materialize OR 条件的自动化验收，无需新增迁移。 |
| 2026-06-26 | 3.0.118-agent | Agent Checkpoint Freshness Gate active memory 边界补强：`_active_memory_freshness` 现在显式只检查 `active_for_policy=true` 的 memory EvidenceRef，避免 audit/background memory 即使进入 latest ContextBuild metadata 且自身 `needs_revalidation` 也误挡 resume；新增反例测试模拟 audit-only memory ref 泄漏到 policy metadata 时仍可继续恢复，同时保留 active policy memory stale 会阻断的既有测试，补齐 Harness 开发计划 10.2/架构 8.3 对 active policy memory freshness 的边界验收，无需新增迁移。 |
| 2026-06-26 | 3.0.119-agent | Agent Checkpoint Freshness Gate active evidence 边界补强：新增统一 active policy ref 判定，要求 `active_for_policy=true`、`dependency_role` 属于 decision/validation/policy 角色且未 superseded，`_active_evidence_revalidation` 与 `_active_memory_freshness` 均复用该边界，避免 audit/background latest/external/memory ref 即使泄漏到 latest ContextBuild metadata 也误挡 resume；新增 audit-only latest evidence 反例测试，保留 active latest/external evidence 正向阻断测试，补齐 Harness 架构 EvidenceRef 生命周期和 active policy refs 的恢复门禁边界，无需新增迁移。 |
| 2026-06-26 | 3.0.120-agent | Agent LoopObservation active memory 派生边界补强：`LoopController._memory_observation_from_build` 现在与 `EvidenceRefResolver.select_policy_refs` 共享 active policy 角色集合，只从 `active_for_policy=true`、decision/validation/policy 角色且未 superseded 的 memory EvidenceRef 派生 `memory_usage` 与 `memory_contradiction_delta`；新增 audit-only memory contradiction 反例测试，证明泄漏到 ContextBuild metadata 的 repair_hint memory 不会误命中 `RC_MEMORY_CONTRADICTION`，补齐 Harness 开发计划 10.3/架构 15.7 对 decision ContextBuild memory policy refs 自动派生的边界验收，无需新增迁移。 |
| 2026-06-26 | 3.0.121-agent | Agent Memory active-policy 指标边界补强：`memory_used_active_policy_total` 已通过 `AgentMemoryUsageEvent.active_for_policy=true` 过滤，本轮新增专项回归测试同时写入 active policy 与 audit-only 两类 usage event，断言 `memory_retrieved_total=2` 但 `memory_used_active_policy_total=1`，避免观测层把审计/追踪 memory 使用误计入策略依赖指标；该项补齐 Harness Memory 观测指标的 active policy 语义验收，无需新增迁移。 |
| 2026-06-26 | 3.0.122-agent | Agent Reconcile backoff P2 观测语义补强：扩展 `test_reconcile_backoff_skips_until_next_retry_at`，在确认未到 `next_retry_at` 时不会调用 backend reconcile adapter、`skipped_backoff`/`skipped_backoff_tool_calls` 与 `reconcile_backoff_active_total` 可见之外，进一步断言 `agent_reconcile_backoff_pending` 为 P2、指向 `tool_call_uncertain` runbook，且 dashboard readiness 保持 `pass`，避免 backoff 节流被误升级为 P0/P1 发布阻断；无需新增迁移。 |
| 2026-06-26 | 3.0.123-agent | Agent Fault Injection coverage 告警上下文补齐：`agent_fault_injection_coverage_incomplete` 与 `agent_fault_injection_coverage_ratio_low` 的 `details.related_metrics` 现在都携带 `fault_injection_required_case_total`、`fault_injection_registered_case_total`、`fault_injection_missing_required_total` 与 `fault_injection_coverage_ratio` 四项上下文，避免 coverage 告警只能看到触发条件而缺少 required/registered/missing/ratio 规模信息；扩展专项测试逐项断言两个告警的 related metrics 与 snapshot metrics 一致，无需新增迁移。 |
| 2026-06-26 | 3.0.124-agent | Agent Backend capability degradation 告警上下文验收补强：扩展 `test_backend_capability_degraded_alert_affects_dashboard_readiness`，同时构造 `legacy_reconcile_only` 降级样本、`legacy_no_receipt` 分布样本与 `receipt_first` 对照样本，断言 `backend_capability_degraded_total=2`，并逐项确认 `agent_backend_capability_degraded.details.related_metrics` 中的 `backend_effect_capability_receipt_first_total` 与 `backend_effect_capability_legacy_no_receipt_total` 和 metrics snapshot 一致；该回归固定架构要求的 capability 分布上下文，避免告警只保留 runbook/readiness 而丢失规模诊断信息，无需新增迁移。 |
| 2026-06-26 | 3.0.125-agent | Agent RootCause rule missing 告警闭环补强：扩展 `test_loop_observation_keeps_unregistered_reason_as_rule_missing`，在验证未登记 reason 命中 `RC_RULE_MISSING`、`root_cause_primary=root_cause_rule_missing` 与 `add_explicit_root_cause_rule` 后，进一步断言 `root_cause_rule_missing_total=1`、`agent_root_cause_rule_missing` 以 P1 firing、指向 `root_cause_rule_missing` runbook，并使 dashboard `monitoring_alerts_clear` 进入 attention；该回归固定 Harness “新增 reason 未配置 rule 必须报警且不能只关闭报警”的治理闭环，无需新增迁移。 |
| 2026-06-26 | 3.0.126-agent | Agent Context full evidence required 告警闭环补强：扩展 `test_context_build_records_degradation_and_required_evidence_gap`，在验证 heavy context build 写入 `context.full_evidence_required` 且 `required_evidence_complete=false` 后，进一步断言 `context_full_evidence_required_total=1`、`agent_context_required_evidence_missing` 以 P1 firing、指向 `checkpoint_stale` runbook，并使 dashboard `monitoring_alerts_clear` 进入 attention；该回归固定 Harness 对高风险动作前证据不完整必须 fetch full evidence / rebuild context / 人工确认的观测闭环，无需新增迁移。 |
| 2026-06-26 | 3.0.127-agent | Agent Migration block open 告警与 live recovery 闭环补强：扩展 `test_reconcile_unsupported_schema_creates_migration_block`，在 unsupported schema 触发 ToolCall `needs_migration`、Run `migration_blocked` 与 backend-contract migration block 后，进一步断言 `migration_block_open_total=1`、`agent_migration_block_open` 以 P1 firing、指向 `migration_blocked` runbook，并使 dashboard readiness 进入 attention、`live_recovery_attention.details.migration_block_open_total=1`；该回归固定 Harness 对 open migration block 不得被普通运行状态吞掉、必须进入恢复治理面的要求，无需新增迁移。 |
| 2026-06-26 | 3.0.128-agent | Agent Reconcile manual intervention 告警闭环补强：扩展 `test_reconcile_conflict_goes_to_manual_intervention`，在 reconcile conflict 将 ToolCall 转为 `manual_intervention` 且 `recovery_decision=idempotency_conflict` 后，进一步断言 `tool_call_reconcile_manual_total=1`、`agent_reconcile_manual_intervention` 以 P1 firing、指向 `tool_call_uncertain` runbook，并使 dashboard `monitoring_alerts_clear` 进入 attention；该回归固定 Harness 对 reconcile 转人工不能只停留在 ToolCall 状态、必须进入告警和恢复治理面的要求，无需新增迁移。 |
| 2026-06-26 | 3.0.129-agent | Agent Memory contradiction snapshot 指标回归补强：扩展 `test_memory_contradiction_penalty_and_status_update_are_deterministic`，在真实 `MemoryManager.record_contradiction` 写入 `AgentMemoryContradictionEvent` 后同步断言 `memory_contradiction_total=1`，与既有 `memory_contradiction_penalty_applied_total=1` 一起锁定 memory 矛盾事件计数和降权事件计数的观测口径；该回归补齐 Dashboard required metrics 中 `memory_contradiction_total` 的显式专项覆盖，无需新增迁移。 |
| 2026-06-26 | 3.0.130-agent | Agent WorkerQueue reconcile 守门矩阵补强：将 `test_worker_blocks_uncertain_tool_call_until_reconcile` 扩展为 `uncertain` / `reconciling` 双状态 subTest，确认误入执行队列的 ToolCall 均不会调用 backend executor，而是把 queue item 标为 failed、写入冻结错误码 `tool_call_uncertain_reconcile_required`，并保留 ToolCall 原状态与 `reconcile_required_before_execution` 恢复决策；该回归对齐 Harness 开发计划中 `uncertain/reconciling` 必须先 reconcile、不得被 WorkerQueue 直接执行的要求，无需新增迁移。 |
| 2026-06-26 | 3.0.131-agent | Agent Fault Injection WorkerQueue 守门 required case 补强：新增 `worker_queue_reconcile_required` 到 `FAULT_CASES`、`REQUIRED_FAULT_CASES` 与 `AgentFaultInjectionService.run_cases`，一次覆盖 `uncertain` / `reconciling` ToolCall 误入 WorkerQueue 时 queue item failed、冻结错误码 `tool_call_uncertain_reconcile_required`、恢复决策 `reconcile_required_before_execution` 的生产硬化验证；同步 fault coverage 计数从 23 扩展到 24，并更新 Harness 开发计划与架构文档中的 required set 口径，无需新增迁移。 |
| 2026-06-26 | 3.0.132-agent | Agent Fault Injection migration resolve required case 补强：新增 `migration_block_resolve_checkpoint_continue` 到 `FAULT_CASES`、`REQUIRED_FAULT_CASES` 与 `AgentFaultInjectionService.run_cases`，在 unsupported schema 生成 open migration block 后执行 `MigrationCoordinator.resolve_block`，断言 Freshness Gate 返回 `continue_from_checkpoint`、Run 恢复 `running`、blocking tool list 清空、被阻断 ToolCall 转 `reconciling`，且已 `succeeded` ToolCall 保持完成状态不回滚；同步 fault coverage required set 从 24 扩展到 25，并更新 Harness 开发计划与架构文档中的 required case 数量口径，无需新增迁移。 |
| 2026-06-26 | 3.0.133-agent | Agent Fault Injection LoopObservation decision context 绑定 required case 补强：新增 `loop_observation_decision_context_binding` 到 `FAULT_CASES`、`REQUIRED_FAULT_CASES` 与 `AgentFaultInjectionService.run_cases`，在同一 iteration 内先创建 plan ContextBuild、再创建 repair/decision ContextBuild，并断言 LoopObservation 显式绑定后者而非前者，同时保持 `RC_CONTEXT_OMITTED_HIGH_RISK` 归因；同步 fault coverage required set 从 25 扩展到 26，并更新 Harness 开发计划与架构文档中的 required case 数量口径，无需新增迁移。 |
| 2026-06-26 | 3.0.134-agent | Agent Fault Injection idempotency_index_only acceptance 边界证据补强：扩展 `transport_sent_not_found` required case 的通过条件与 evidence，除继续断言 `uncertain` + `reconcile_backoff` + reconcile attempt 外，显式要求 `backend_effect_capability=idempotency_index_only`、`effect_submission_state=transport_sent_observed` 且 `downstream_acceptance_id is None`；专项测试同步断言这些 evidence，锁定 Harness 架构第 4 条“idempotency_index_only 工具不得写 backend_accepted，not_found 走 backoff”的验收口径，无需新增 required case 或迁移。 |
| 2026-06-26 | 3.0.135-agent | Agent WorkerQueue audit 告警闭环补强：扩展 expired lease 与 duplicate active lease 两条专项测试，在既有 `worker_queue_expired_lease_total` / `worker_queue_duplicate_active_lease_total` 指标和 alert id 断言之外，进一步固定 `agent_worker_queue_expired_lease` 为 P1、`agent_worker_queue_duplicate_active_lease` 为 P0，二者均指向 `worker_queue_recovery` runbook，并分别让 dashboard `monitoring_alerts_clear` 进入 attention / blocked；该回归锁定 Harness WorkerQueue audit 规则中 lease scanner 异常必须进入告警与 readiness 治理面的要求，无需新增迁移。 |
| 2026-06-26 | 3.0.136-agent | Agent Approval stale P2 告警闭环补强：扩展 `test_approval_lineage_lock_metrics_alert_with_runbook` 与 `test_expire_scanner_expires_due_pending_approvals_idempotently`，在原有指标断言之外固定 `agent_approval_lineage_lock_wait`、`agent_approval_lineage_lock_skip`、`agent_approval_expire_backlog`、`agent_approval_expire_batch_lag` 均以 P2 firing 并指向 `approval_stale` runbook；同时清理测试场景 outbox 背景噪声，断言 lineage lock P2 不直接降低 dashboard readiness，而 expire due backlog 通过 `live_recovery_attention` 进入 attention、`monitoring_alerts_clear` 仍保持 pass；该回归锁定 Harness 开发计划/架构中 Approval expire 与 lineage lock 观测信号的告警治理语义，无需新增迁移。 |
| 2026-06-26 | 3.0.137-agent | Agent Reconcile not_found 告警分级闭环补强：扩展 `test_reconcile_not_found_rules_are_state_specific`，在 send_intent orphan、transport_sent uncertain、backend_accepted uncertain 与 safe_retry_after_send_intent_not_found 的状态分流基础上，进一步固定 `agent_tool_call_send_intent_orphan`/`agent_tool_call_safe_retry_after_send_intent_not_found` 为 P2、`agent_tool_call_transport_sent_uncertain` 为 P1、`agent_tool_call_backend_accepted_uncertain` 为 P0，均指向 `tool_call_uncertain` runbook；同时断言 reconcile 前 P0 使 dashboard blocked、reconcile 后剩余 P1 使 dashboard attention，锁定 Harness 监控规则中副作用恢复分级不得漂移的语义，无需新增迁移。 |
| 2026-06-26 | 3.0.138-agent | Agent Backend contract/capability 降级告警闭环补强：扩展 `test_reconcile_missing_backend_contract_alerts_tool_call_contract_unsupported` 与 `test_legacy_no_receipt_high_risk_cannot_auto_reconcile`，固定 `agent_tool_call_backend_contract_unsupported` 为 P1 且指向 `migration_blocked` runbook，并让 dashboard `monitoring_alerts_clear` 进入 attention；固定 `agent_legacy_no_receipt_manual_intervention` 为 P0 且指向 `backend_capability_degraded` runbook，并让 dashboard blocked；该回归锁定 Harness 对 ToolCall 级 contract/capability 降级必须进入告警和 readiness 治理面的要求，无需新增迁移。 |
| 2026-06-26 | 3.0.139-agent | Agent EventStore/outbox 告警闭环补强：扩展 `test_event_replay_gap_is_reported_in_metrics_and_alerts` 与 `test_event_replay_stress_audit_reports_failed_run_and_alert`，固定 `agent_event_replay_gap`、`agent_event_replay_stress_failed` 均为 P1 且指向 `event_replay_recovery` runbook，并让 dashboard `monitoring_alerts_clear` 进入 attention，同时继续断言 stress failed 告警携带 cursor window 与最大 replay window 的 related metrics；新增 `test_outbox_publish_lag_alert_affects_dashboard_readiness`，固定 `agent_outbox_publish_lag` 为 P1、指向 `outbox_publish_lag` runbook，并通过 `live_recovery_attention.details.outbox_publish_lag_ms` 暴露恢复面规模；该回归锁定 Harness 对 SSE replay 与 Outbox lag 生产监控的告警治理语义，无需新增迁移。 |
| 2026-06-26 | 3.0.140-agent | Agent Checkpoint Freshness Gate 环境变更告警闭环补强：扩展 `test_resume_run_revalidates_when_environment_evidence_changed`，在既有 `environment_changed / revalidate_before_side_effect / environment_updated` 分流与 `environment_changed_count` 明细断言之外，固定 `checkpoint_freshness_failed_total=1` 触发 `agent_checkpoint_freshness_failed` P1 告警、指向 `checkpoint_stale` runbook，并让 dashboard `monitoring_alerts_clear` 进入 attention；该回归锁定 Harness 对环境类 stale EvidenceWatch 禁止直接 resume、必须进入 checkpoint stale 监控治理面的要求，无需新增迁移。 |
| 2026-06-26 | 3.0.141-agent | Agent Fault Injection coverage 发布门禁闭环补强：扩展 `test_fault_injection_coverage_ratio_alerts_when_below_full`，在缺失 required case 时固定 `agent_fault_injection_coverage_incomplete` 与 `agent_fault_injection_coverage_ratio_low` 均为 P1、指向 `fault_injection_coverage` runbook，并继续断言 required/registered/missing/coverage ratio related metrics；同时锁定 dashboard 语义：`monitoring_alerts_clear` 因 P1 alert 进入 attention，`fault_injection_catalog_complete` 作为 P0 check 直接 blocked 且输出缺失 case 明细，避免 fault coverage 未达 100% 被误当作普通可忽略告警。 |
| 2026-06-26 | 3.0.142-agent | Agent Release Gate violation 发布门禁闭环补强：新增 `test_release_gate_violation_blocks_dashboard_and_promotion`，通过临时注册 L2 不允许的 `business_create` ToolSpec，固定 `release_gate_violation_count=1`、`agent_release_gate_violation` 为 P0 且指向 `release_gate_violation` runbook；同时断言 dashboard `release_gate_current_level_clean` 与 `monitoring_alerts_clear` 均 blocked，灰度晋级评估输出 `tool_matrix` 与 `readiness_dashboard` blockers，锁定 Harness 对当前 rollout tool matrix violation 必须阻断 dashboard 和 promotion 的治理语义。 |
| 2026-06-26 | 3.0.143-agent | Agent Runbook diagnosis 恢复建议闭环补强：`AgentRunbookService.diagnose_run` 现在除 uncertain/migration/approval/checkpoint 外，会从同一 run 直接识别 `backend_capability_degraded`、缺失 decision ContextBuild 的 `context_linkage_repair`、`RC_RULE_MISSING` fallback 的 `root_cause_rule_missing`，以及 `memory.bypassed_evidence_ref` / high-risk memory-only ToolCall 对应的 `memory_evidence_ref_violation`；扩展 `test_runbook_catalog_and_run_diagnosis_cover_recovery_states`，把 catalog 完整性断言升级为具体 recommendation 触发断言，并固定 Memory EvidenceRef 违规为 P0 恢复建议，避免 Runbook 只存在于目录和告警规则中、无法在单次运行诊断页落到可执行恢复动作。 |
| 2026-06-26 | 3.0.144-agent | Agent Memory usage events 权限边界回归补强：新增 `test_memory_usage_events_route_scopes_global_and_run_access`，直接调用 `GET /api/v1/agents/memory-usage-events` 路由函数锁定文档要求的审计边界：普通项目用户不带 `run_id` 读取全局 usage events 必须 403，项目成员带 `run_id` 只能读取本 run usage events，非项目用户即使带同一 `run_id` 仍被 run 权限校验阻断，admin 可读取全局审计列表；该回归防止 Memory 使用轨迹被普通用户跨项目枚举，主 Harness 文档已有对应接口权限说明，无需新增迁移。 |
| 2026-06-26 | 3.0.145-agent | Agent Memory staleness/validation 审计接口权限边界回归补强：新增 `test_memory_audit_event_routes_scope_global_project_and_memory_access`，覆盖 `GET /api/v1/agents/memory-staleness-events` 与 `GET /api/v1/agents/memory-validation-events` 的全局、project scoped 与 memory scoped 访问语义；普通项目用户读取全局审计必须 403，项目外用户即使传 `project_id` 或 `memory_id` 也被权限校验阻断，项目成员可读取本项目/本 memory 审计事件，admin 可读取全局事件列表；该回归锁定 Memory EvidenceWatch stale 与 validation event 的审计数据不能被跨项目枚举，主 Harness 文档已有接口清单与审计事件说明，无需新增迁移。 |
| 2026-06-26 | 3.0.146-agent | Agent release gate promotion 权限边界回归补强：新增 `test_release_gate_promotion_route_scopes_global_and_project_access`，直接调用 `GET /api/v1/agents/release-gates/promotion` 路由函数锁定全局与项目范围评估语义；普通项目用户不带 `project_id` 读取全局晋级评估必须 403，项目外用户即使传 `project_id=10` 也被项目权限校验阻断，项目成员可读取本项目 promotion assessment，admin 可读取全局 assessment；该回归补齐灰度晋级接口的治理视图权限边界，防止普通用户枚举全局 release gate/promotion 状态，无需新增迁移。 |
| 2026-06-26 | 3.0.147-agent | Agent observability 观测接口权限边界回归补强：新增 `test_observability_routes_scope_global_and_project_access`，统一覆盖 `GET /api/v1/agents/metrics`、`GET /api/v1/agents/dashboard` 与 `GET /api/v1/agents/alerts` 的全局与项目范围访问语义；普通项目用户不带 `project_id` 读取全局观测视图必须 403，项目外用户即使传 `project_id=10` 也被项目权限校验阻断，项目成员可读取本项目 metrics/dashboard/alerts，admin 可读取全局观测快照；该回归锁定 Agent 监控与上线门禁观测面不能被跨项目枚举，无需新增迁移。 |
| 2026-06-26 | 3.0.148-agent | Agent release gate Runbook 诊断闭环补强：`AgentRunbookService.diagnose_run` 现在会读取当前 release gate snapshot，当注册工具矩阵存在超过当前 L2 rollout 的 side effect class 时，直接在 run 级诊断建议中返回 `release_gate_violation`，包含当前级别、违规数量和违规工具明细；新增 `test_runbook_diagnosis_includes_release_gate_violations`，通过临时注入 `business_create` ToolSpec 固定该建议为 P0，并把 `release_gate_violation` 纳入 runbook catalog 完整性断言，避免 release gate 违规只在 dashboard/alert 面可见而无法落入单次运行 Runbook 恢复建议；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.149-agent | Agent 操作审计接口权限边界回归补强：新增 `test_operational_audit_routes_scope_global_and_project_access`，统一覆盖 `GET /api/v1/agents/worker-queue/audit` 与 `GET /api/v1/agents/events/replay-stress-audit` 的全局与项目范围访问语义；普通项目用户不带 `project_id` 读取全局 WorkerQueue / Event replay stress 审计必须 403，项目外用户即使传 `project_id=10` 也被项目权限校验阻断，项目成员可读取本项目审计快照，admin 可读取全局审计快照；该回归锁定 WorkerQueue lease/duplicate claim 与 SSE replay stress 治理面不能被普通用户跨项目枚举，无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.150-agent | Agent Approval expiration 治理接口权限边界回归补强：新增 `test_approval_expiration_routes_scope_global_and_project_access`，统一覆盖 `GET /api/v1/agents/approvals/expire-audit` 与 `POST /api/v1/agents/approvals/expire` 的全局与项目范围访问语义；普通项目用户不带 `project_id` 读取或执行全局过期扫描必须 403，项目外用户即使传 `project_id=10` 也被项目权限校验阻断，项目成员可读取/处理本项目审批过期队列，admin 可读取/处理全局队列；该回归锁定 Approval lineage expire 批处理治理面不能被普通用户跨项目枚举或触发，无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.151-agent | Agent 后台处理入口 admin-only 回归补强：新增 `test_background_processing_routes_require_admin`，直接覆盖 `POST /api/v1/agents/outbox/publish` 与 `POST /api/v1/agents/memory-feedback/process` 的权限边界；普通项目用户手动触发 Agent Outbox 发布或 Memory feedback 批处理必须 403，admin 可执行空批次并获得结构化 summary；该回归锁定 EventStore/Outbox 发布器与 MemoryFeedbackWorker 这类全局后台处理入口不能被普通项目用户触发，无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.152-agent | Agent Run-scoped 治理接口权限边界回归补强：新增 `test_run_scoped_governance_routes_require_run_project_access`，直接覆盖 `GET /api/v1/agents/runs/{run_id}/runbook` 与 `GET /api/v1/agents/runs/{run_id}/events/replay-audit` 的 run 所属项目访问语义；项目成员和 admin 可读取本 run 的 Runbook 诊断与 EventStore/SSE replay audit，项目外用户即使知道 `run_id` 也必须 403；该回归锁定单 run 恢复诊断和重放审计治理面不能被跨项目枚举，无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.153-agent | Agent Fault Injection 执行入口 admin-only 回归补强：新增 `test_fault_injection_run_route_requires_admin`，直接覆盖 `POST /api/v1/agents/fault-injections/run` 的生产硬化执行权限边界；普通项目用户即使具备项目访问也必须 403，admin 可指定 `project_id` 并执行单个轻量故障注入用例 `root_cause_rule_missing`，返回 requested=1、failed=0 与 passed result；该回归锁定故障注入执行不能被普通项目用户触发，无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.154-agent | Agent SSE 事件流 run-scoped 权限边界回归补强：新增 `test_run_event_stream_route_requires_run_project_access`，直接覆盖 `GET /api/v1/agents/runs/{run_id}/events` 的订阅入口访问语义；项目成员和 admin 可建立 `text/event-stream` 响应，项目外用户即使知道 `run_id` 也必须在创建事件流前 403；该回归锁定 Last-Event-ID 续播与实时事件流不能被跨项目订阅，无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.155-agent | Agent Harness 文档路由契约回归补强：新增 `test_harness_documented_agent_routes_match_openapi`，从两份 Harness Memory 强化版文档抽取所有 `METHOD /api/v1/agents...` 声明，归一化历史 `{id}` memory 占位符后与 FastAPI OpenAPI method+path 对齐；当前 42 个文档声明路由均已存在于 OpenAPI，回归用于防止后续文档 API 契约和路由实现分叉；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.156-agent | Agent Harness 文档/OpenAPI 双向路由契约收口：补齐 Harness 文档中缺失的 `GET /api/v1/agents/metrics`、`GET /api/v1/agents/runbooks`、`GET /api/v1/agents/runs/{run_id}/approvals`、`GET/POST /api/v1/agents/runs/{run_id}/context-builds` 与 `GET/POST /api/v1/agents/runs/{run_id}/loop-observations` method+path 声明，并将 `test_harness_documented_agent_routes_match_openapi` 升级为双向断言；当前 49 个 Agent OpenAPI method+path 均已被两份 Harness 文档覆盖，且文档声明也必须存在于 OpenAPI；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.157-agent | Agent object-scoped 读取接口权限边界回归补强：新增 `test_object_scoped_read_routes_require_project_access`，直接覆盖 `GET /api/v1/agents/runtime-snapshots/{snapshot_id}` 与 `GET /api/v1/agents/tool-calls/{tool_call_id}` 的对象所属项目访问语义；项目成员和 admin 可读取 runtime snapshot 与 ToolCall 明细，项目外用户即使知道 snapshot_id 或 tool_call_id 也必须 403；同步 Harness 开发计划与架构文档，锁定冻结运行时契约和执行明细不能被跨项目枚举；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.158-agent | Agent run-derived resource 路由权限边界回归补强：新增 `test_run_derived_resource_routes_require_run_project_access`，统一覆盖 `GET/POST /api/v1/agents/runs/{run_id}/context-builds`、`GET/POST /api/v1/agents/runs/{run_id}/loop-observations`、`GET /api/v1/agents/runs/{run_id}/approvals`、`GET /api/v1/agents/runs/{run_id}/migration-blocks` 与 `POST /api/v1/agents/runs/{run_id}/migration-blocks/{block_id}/resolve` 的 run 所属项目访问语义；项目成员可读取/操作本 run 派生资源，项目外用户即使知道 run_id、approval_id 或 block_id 也必须 403；同步 Harness 开发计划与架构文档，锁定 ContextBuild、LoopObservation、Approval 与 MigrationBlock 不能被跨项目枚举或操作；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.159-agent | Agent 冻结 API 错误码契约收口：将 `test_harness_frozen_api_error_codes_include_memory_staleness_guard` 升级为 `test_harness_frozen_api_error_codes_match_architecture_contract`，从开发计划 4.3 抽取完整冻结错误码清单并与架构错误码表、预期 13 个 code 全量比对，同时要求每个冻结 code 在测试源中至少有独立回归断言；架构文档同步补齐 `checkpoint_stale_replan_required`、`permission_revoked_before_execution`、`backend_contract_unsupported`、`tool_call_uncertain_reconcile_required`、`backend_reconcile_not_supported`、`backend_capability_too_weak`、`memory_event_not_stale_event`、`event_outbox_write_failed`，并将历史 `tool_call_not_approvable` 统一为冻结 `tool_call_obsolete`；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.160-agent | Agent Runbook catalog 文档驱动契约收口：新增 `test_harness_required_runbook_catalog_matches_architecture_contract`，从架构文档 `runbook_catalog_complete` Required catalog 段落抽取 required runbook id，并与 `REQUIRED_RUNBOOKS`、`AgentRunbookService.list_runbooks()`、dashboard `runbook_catalog_complete.details.covered_required_runbook_ids/missing_required_runbook_ids`、顶层 runbooks summary 以及 P0/P1 `ALERT_RULES.runbook_id` 引用全量比对；开发计划和架构文档同步声明该文档驱动验收，防止新增告警或 runbook 时目录、dashboard 与文档出现漂移；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.161-agent | Agent Alert metric catalog 文档驱动契约收口：新增 `test_harness_alert_metric_catalog_matches_architecture_contract`，从架构文档 AgentAlertService 事实表指标代码块抽取 required alert metrics，并与 `ALERT_FACT_METRICS`、`ALERT_RULES.metric_key`、`ALERT_RULES.related_metric_keys`、`DYNAMIC_ALERT_METRICS`、dashboard `alert_metric_catalog_complete.details` 全量比对；同时固定 backend capability、event replay stress、fault injection coverage 等规模/正向指标必须作为 related metrics 暴露，`release_gate_violation_count` 必须作为 dynamic metric 暴露；开发计划和架构文档同步声明该文档驱动验收，防止新增告警指标后 dashboard catalog 或文档漏检；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.162-agent | Agent Metrics catalog 文档驱动契约收口：新增 `test_harness_metrics_catalog_matches_architecture_contract`，在架构文档补齐 `Required dashboard metrics` 65 项完整代码块，并从该代码块抽取 required metric keys 与 `REQUIRED_DASHBOARD_METRICS`、dashboard `metrics_catalog_complete.details.required_metric_keys/required_metric_count/missing_metric_keys`、`AgentMetricsService.snapshot` 输出全量比对；开发计划同步声明 metrics catalog 需从架构文档完整清单驱动验收，防止新增恢复/治理指标后 dashboard 目录或文档只覆盖局部子集；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.163-agent | Agent Fault Injection required cases 文档驱动契约收口：新增 `test_harness_required_fault_injection_cases_match_docs_contract`，从架构文档 `Required fault injection cases` 和开发计划 10.4 的 26 项清单抽取 required case id，并与 `REQUIRED_FAULT_CASES`、`AgentFaultInjectionService.list_cases()`、coverage audit、readiness dashboard `fault_injection` summary 以及 `fault_injection_catalog_complete.details` 全量比对；架构文档补齐 26 项 required case 明细，开发计划上线门禁旧口径从 23/23 修正为 26/26，防止故障注入 required set、dashboard 和文档出现漂移；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.164-agent | Agent Release Gate rollout matrix 文档驱动契约收口：新增 `test_harness_rollout_matrix_matches_docs_contract`，从开发计划与架构文档的 `Required rollout matrix` 抽取 L0-L5 summary、allowed/blocked side effect classes 与 required gates，并与 `ROLLOUT_LEVELS`、当前 release gate snapshot allowed/blocked classes、expansion gates 和 `CURRENT_AGENT_ROLLOUT_LEVEL=L2` 全量比对；开发计划 4.4 与架构 release gate 段同步改为可机器读取的冻结矩阵，防止灰度等级、业务写入开放边界和晋级前置条件漂移；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.165-agent | Agent Runbook safe API actions 契约收口：新增 `test_runbook_safe_api_actions_match_openapi_contract`，从 `AgentRunbookService.RUNBOOKS` 抽取每个 Runbook 的 `safe_api_actions`，并与 FastAPI OpenAPI 中 `/api/v1/agents...` method+path 全量比对；开发计划和架构文档同步声明 Runbook 恢复动作必须指向真实已注册路由，防止最终交付 Runbook 给出不可调用的恢复接口；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.166-agent | Agent Backend Adapter SDK / ToolSpec / Reconcile Contract 契约收口：新增 `test_backend_adapter_contract_defaults_match_docs_and_seeded_tool_specs`，从两份 Harness 文档的 `Required backend adapter contract defaults` 抽取默认 contract，校验 `ToolRegistry` 中每个 ToolSpec 的 schema hash、`BackendContractSpec` 默认值、unsafe side effect 后端契约要求、`AgentRuntimeService.ensure_backend_contracts()` seed 到 `ai_agent_backend_contracts` 的字段，以及 Release Gate `tool_matrix` 展示的 backend name/operation/version/effect capability/status 全部一致；开发计划 7.2.1 与架构 8.1 同步补齐机器可读默认值，防止 adapter SDK、DB 治理视图和灰度门禁口径漂移；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.167-agent | Agent EvidenceRef 编写规范契约收口：新增 `test_harness_evidence_ref_authoring_contract_matches_resolver`，从两份 Harness 文档的 `Required EvidenceRef authoring contract` 抽取 mutability class、active/audit dependency role、freshness policy、默认 mutability/role 与 policy filter，并与 `EvidenceRefResolver` 常量、缺省解析、policy/audit 分流、volatile requires_revalidation 和 fully frozen 判定全量比对；开发计划 9.2 与架构 EvidenceRef 段同步修正旧 `policy_dependency-only` 口径，明确 `decision_dependency / validation_evidence / policy_dependency` 均可作为 active policy refs，防止 EvidenceRef 编写规范、Memory 包装和 replay_policy 解析继续分叉；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.168-agent | Agent Approval 并发规范契约收口：新增 `test_harness_approval_concurrency_contract_matches_guard_and_openapi`，从两份 Harness 文档的 `Required Approval concurrency contract` 抽取 final status、可审批 ToolCall 状态、supersede 阻断状态、CAS immutable fields、mutation/event 类型、冲突错误码和后台 expire 逐 lineage 约束，并与 `ApprovalMutationGuard` 常量、OpenAPI `AgentApprovalDecisionRequest` required 字段、approve 成功流程、supersede replacement 原子流程产生的 mutation/event 全量比对；开发计划 8.4 与架构 Approve/Reject API 段同步补齐机器可读并发契约，防止 approve/reject/supersede/expire 的跨表业务互斥口径漂移；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.169-agent | Agent RootCause Rule 新增规范契约收口：新增 `test_harness_root_cause_rule_authoring_contract_matches_governance`，从两份 Harness 文档的 `Required RootCause rule authoring contract` 抽取 priority bands、默认 rule_id/band/priority、governance fields、新规则至少 3 个测试夹具、`RC_UNKNOWN`/`RC_RULE_MISSING` 与 `root_cause_rule_missing_total` 约束，并与 `RootCauseRuleEngine` 常量、seeded 默认规则、`audit_rule_governance()` 输出、accepted unknown 归因、未登记 reason fallback 和未知 priority band violation 全量比对；开发计划 9.6 与架构 13.1.1 同步补齐机器可读新增规则规范，防止 RootCause 规则表、dashboard governance 与文档口径漂移；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.170-agent | Agent Reconcile Contract 规范契约收口：新增 `test_harness_reconcile_contract_matches_worker_and_schema`，从两份 Harness 文档的 `Required Reconcile contract` 抽取 eligible ToolCall 状态、ReconcileResult status/schema_support 枚举、成功/backoff/失败/人工/状态依赖/migration 分流、not_found backoff 适用 effect state/capability、result envelope、summary 与 skipped_backoff payload 字段，并与 `ReconcileWorker` 常量、`ReconcileResult` Pydantic schema 和 `_summary()` 输出全量比对；开发计划 7.5 与架构 8.2 同步补齐机器可读 Reconcile 契约，防止 adapter 返回 envelope、worker 分流和文档规范漂移；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.171-agent | Agent Runbook diagnosis 输出契约收口：新增 `test_harness_runbook_diagnosis_contract_matches_schema_and_actions`，从两份 Harness 文档的 `Required Runbook diagnosis contract` 抽取 diagnosis 字段、recommendation required/optional 字段、可诊断 runbook id、severity 来源与 checkpoint freshness action 到安全 API 的映射，并与 `AgentRunbookDiagnosisRead` / `AgentRunbookRecommendationRead` schema、`AgentRunbookService` 常量、OpenAPI 路由和 runbook `safe_api_actions` 全量比对；`diagnose_run` 现在把当前用户传入 `CheckpointFreshnessGate`，并把 checkpoint 内部 freshness action 映射为真实 `/api/v1/agents...` 恢复动作，防止 Runbook 诊断页输出不可执行 action 或与前端 contract 漂移；无接口形状或数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.172-agent | Agent 最小上线版本契约收口：新增 `test_harness_minimum_go_live_contract_matches_release_gate`，从两份 Harness 文档的 `Required minimum go-live contract` 抽取 13 项最低上线 requirement id，并与 `MINIMUM_GO_LIVE_REQUIREMENTS`、`AgentReleaseGateService.snapshot().minimum_go_live`、`GET /api/v1/agents/release-gates` schema、L3 promotion assessment 的 `minimum_go_live_contract_pass` check 全量比对；release gate snapshot 现在暴露 minimum go-live checklist，promotion assessment 将其作为业务写入晋级前置检查，同时仍保留 L3 静态 blocked reasons，明确“最低上线通过是 business_create 灰度的必要条件而非自动放开条件”；无数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.173-agent | Agent 上线门禁 P0/P1/P2 契约收口：新增 `test_harness_go_live_gate_contract_matches_release_gate`，从两份 Harness 文档的 `Required go-live gate contract` 抽取 P0/P1/P2 gate id 清单，并与 `GO_LIVE_GATE_REQUIREMENTS`、`AgentReleaseGateService.snapshot().go_live_gates`、`GET /api/v1/agents/release-gates` schema 以及 L3 promotion assessment 的 `go_live_gate_contract_pass` check 全量比对；release gate snapshot 现在暴露分层 go-live gates，promotion assessment 将其纳入晋级检查，防止第 16 节上线门禁只停留在人工文档清单而无法被 API/UI/自动验收读取；无数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.174-agent | Agent 最终交付清单契约收口：新增 `test_harness_final_delivery_contract_matches_release_gate`，从两份 Harness 文档的 `Required final delivery contract` 抽取 backend/frontend/platform/documentation artifact id，并与 `FINAL_DELIVERY_ARTIFACTS`、`AgentReleaseGateService.snapshot().final_delivery` 和 `GET /api/v1/agents/release-gates` schema 全量比对；release gate snapshot 现在暴露 final_delivery 审计视图，backend/platform/documentation 在后端仓库范围内 pass，frontend 明确标记 external_scope，避免最终交付审计把前端页面伪报成后端已交付；无数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.175-agent | Agent 最终交付清单晋级门禁收口：将 `AgentReleaseGateService.snapshot().final_delivery` 纳入 `promotion_assessment()`，新增 `final_delivery_contract_pass` check，并在未满足时产生 `source=final_delivery` 的 P0 blocker；promotion response 的 `release_gate` payload 现在携带 final_delivery，readiness dashboard 的 `release_gate_promotion_assessment` summary 暴露 final delivery pass、backend repository scope pass、missing_by_category 与 external_scope_categories，防止最终交付清单只在 snapshot 可见但不参与晋级判断；同步更新两份 Harness 文档的 promotion assessment 规则，并扩展 `test_harness_final_delivery_contract_matches_release_gate` 覆盖 promotion 与 dashboard contract summary；无数据模型变化，无需新增迁移。 |
| 2026-06-26 | 3.0.176-agent | Agent promotion monitoring alert 门禁显式化：`AgentReleaseGateService.promotion_assessment()` 新增 `monitoring_alerts_clear` check，直接使用 readiness dashboard 的 `alert_summary.by_severity` 判定 P0/P1 alert blocker，并在存在 P0/P1 firing alert 时产生 `source=monitoring_alerts` 的 blocker；同步扩展 promotion 相关回归，验证清洁场景 check=pass、告警场景 check=blocked 且 blockers 同时包含 `monitoring_alerts`；开发计划与架构文档同步声明 promotion API 必须显式输出该 check，避免调用方只能通过 dashboard readiness 间接推断 monitoring alerts 是否满足上线门禁；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.177-agent | Agent promotion assessment 契约机器化收口：新增 `PROMOTION_ASSESSMENT_CHECKS`、`PROMOTION_BLOCKER_SOURCES` 与 `PROMOTION_RELEASE_GATE_FIELDS`，并让 promotion response 的 `release_gate` payload 按同一字段常量输出；两份 Harness 文档新增 `Required promotion assessment contract` 机器可读块，`test_harness_promotion_assessment_contract_matches_release_gate` 从文档抽取 checks、blocker_sources、release_gate_fields，与代码常量、`AgentReleaseGateService.promotion_assessment()` 实际输出和 `AgentReleaseGatePromotionRead` schema 全量比对，防止后续上线门禁新增 check、blocker 或 payload 字段时 API/UI/文档漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.178-agent | Agent Checkpoint Freshness pending approval 契约机器化收口：新增 `PENDING_APPROVAL_FRESHNESS_FIELDS`、`PENDING_APPROVAL_DETAIL_FIELDS`、`PENDING_APPROVAL_FRESHNESS_REASONS`、`PENDING_APPROVAL_DETAIL_STALE_REASONS`、`PENDING_APPROVAL_FRESHNESS_RESULT` 与 `PENDING_APPROVAL_FRESHNESS_ACTION`，并将 `CheckpointFreshnessGate` 的 pending approval 分支改为复用这些常量；两份 Harness 文档新增 `Required pending approval freshness contract` 机器可读块，`test_harness_pending_approval_freshness_contract_matches_gate` 从文档抽取 freshness/detail 字段、reason/stale_reason 枚举以及 result/action，与代码常量和 expired/stale/after-wait 三类实际 freshness 输出全量比对，防止 UI/runbook 依赖的审批等待诊断字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.179-agent | Agent Checkpoint Freshness evidence freshness 契约机器化收口：新增 environment freshness 与 active evidence revalidation 的字段、detail 字段、result/action/reason 常量，并将 `CheckpointFreshnessGate` 的 environment stale、latest/ephemeral materialization 与 external evidence revalidation 分支改为复用这些常量；两份 Harness 文档新增 `Required evidence freshness contract` 机器可读块，`test_harness_evidence_freshness_contract_matches_gate` 从文档抽取 environment/active evidence 契约，并与 environment.updated、latest_execution_sample、external_doc 三类实际 freshness 输出全量比对，防止恢复 UI/runbook 对 stale evidence 明细、materialize latest 与 fetch evidence 分流的依赖字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.180-agent | Agent Checkpoint Freshness permission freshness 契约机器化收口：新增 `PERMISSION_FRESHNESS_FIELDS`、`PERMISSION_FRESHNESS_DETAIL_FIELDS`、`PERMISSION_FRESHNESS_RESULT`、`PERMISSION_FRESHNESS_ACTION` 与 `PERMISSION_FRESHNESS_REASON`，并将 `CheckpointFreshnessGate` 的权限重验分支改为复用这些常量；两份 Harness 文档新增 `Required permission freshness contract` 机器可读块，`test_harness_permission_freshness_contract_matches_gate` 从文档抽取扫描 ToolCall 状态、freshness/detail 字段和 result/action/reason，与代码常量及实际 revoked permission 输出全量比对，锁定 resume 前权限撤销诊断字段和 `planned/approved/executable/failed_retryable/uncertain/reconciling` 扫描范围；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.181-agent | Agent Checkpoint Freshness runtime snapshot 契约机器化收口：新增 `RUNTIME_SNAPSHOT_FRESHNESS_FIELDS`、`RUNTIME_SNAPSHOT_FRESHNESS_RESULT`、`RUNTIME_SNAPSHOT_FRESHNESS_ACTION`、`RUNTIME_SNAPSHOT_FRESHNESS_REASONS` 与 `RUNTIME_SNAPSHOT_FRESHNESS_ERROR_CODE`，并让 `CheckpointFreshnessGate` 的 runtime snapshot missing/mismatch 分支和 `AgentRunResumeService` 的 paused error_code 映射复用同一常量；两份 Harness 文档新增 `Required runtime snapshot freshness contract` 机器可读块，`test_harness_runtime_snapshot_freshness_contract_matches_gate` 从文档抽取 freshness 字段、result/action、reason 枚举和 paused_error_code，与代码常量以及 missing/mismatch 两类实际 resume 输出全量比对，防止旧 checkpoint runtime registry 解释新运行态时 UI/runbook 只能解析内部 action；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.182-agent | Agent alert 到 Runbook 绑定契约机器化收口：新增 `ALERT_RUNBOOK_REQUIRED_SEVERITIES` 与 `ALERT_DYNAMIC_RUNBOOKS`，并让 `alert_metric_catalog_complete.details` 暴露 `runbook_required_severities`、`alert_runbook_ids`、静态 P0/P1 alert rule 的 covered/missing runbook 绑定以及动态 release gate alert 的 covered/missing runbook 绑定；两份 Harness 文档新增 `Required alert runbook binding contract` 机器可读块，`test_harness_alert_metric_catalog_matches_architecture_contract` 从文档抽取 required severities、静态规则来源、动态 alert->runbook 映射和 dashboard details 字段，与 `ALERT_RULES`、`ALERT_DYNAMIC_RUNBOOKS`、`AgentRunbookService.list_runbooks()` 和 dashboard 实际输出全量比对，防止 P0/P1 告警没有可执行处置 Runbook 或动态发布门禁告警脱离 Runbook catalog；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.183-agent | Agent `monitoring_alerts_clear` 上线门禁诊断契约收口：新增 `MONITORING_ALERT_BLOCKING_SEVERITIES` 与 `MONITORING_ALERTS_CLEAR_DETAIL_FIELDS`，并让 dashboard check details 直接输出 `blocking_alert_count`、`blocking_alert_ids`、`blocking_runbook_ids`、`p0_alert_ids` 与 `p1_alert_ids`；两份 Harness 文档新增 `Required monitoring alerts clear contract` 机器可读块，`test_harness_monitoring_alerts_clear_contract_matches_dashboard` 从文档抽取 blocking severities、status rules 和 detail 字段，并验证无告警 pass、P1 attention、P0 blocked 三类实际 dashboard 输出，防止 promotion/UI 只能从 severity count 反推具体阻断告警；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.184-agent | Agent dashboard promotion summary 契约收口：新增 `PROMOTION_DASHBOARD_SUMMARY_FIELDS`，并让 `AgentReadinessDashboardService._promotion_assessment_summary()` 按固定字段顺序输出 promotion endpoint 所需输入摘要；两份 Harness 文档新增 `Required dashboard promotion summary contract` 机器可读块，`test_harness_dashboard_promotion_summary_contract_matches_dashboard` 从文档抽取 summary 字段、dashboard check、endpoint 与 summary-only dependency 标记，并与 dashboard 顶层 `promotion_assessment`、`release_gate_promotion_assessment.details` 和代码常量全量比对，防止 dashboard 与 promotion endpoint 的最终门禁输入口径漂移或误形成递归调用；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.185-agent | Agent minimum go-live payload 契约收口：新增 `MINIMUM_GO_LIVE_FIELDS` 与 `MINIMUM_GO_LIVE_CHECK_FIELDS`，并让 `AgentReleaseGateService._minimum_go_live_contract()` 按固定顶层字段和 check 字段输出最低上线门槛审计结果；两份 Harness 文档新增 `Required minimum go-live payload contract` 机器可读块，`test_harness_minimum_go_live_contract_matches_release_gate` 同时抽取 requirement id 清单与 payload 字段契约，并与 release gate snapshot、route payload、promotion release_gate 镜像和代码常量全量比对，防止 business_create 扩容最低门槛的 pass/missing/checks 字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.186-agent | Agent go-live gate payload 契约收口：新增 `GO_LIVE_GATE_FIELDS`、`GO_LIVE_GATE_TIER_FIELDS` 与 `GO_LIVE_GATE_CHECK_FIELDS`，并让 `AgentReleaseGateService._go_live_gates()` 按固定顶层字段、priority tier 字段和单项 check 字段输出 P0/P1/P2 上线门禁审计结果；两份 Harness 文档新增 `Required go-live gate payload contract` 机器可读块，`test_harness_go_live_gate_contract_matches_release_gate` 同时抽取 gate id 分层清单与 payload 字段契约，并与 release gate snapshot、route payload、promotion release_gate 镜像和代码常量全量比对，防止 go-live gates 的 priorities/tiers/checks/evidence 字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.187-agent | Agent final delivery payload 契约收口：新增 `FINAL_DELIVERY_FIELDS`、`FINAL_DELIVERY_CATEGORY_FIELDS` 与 `FINAL_DELIVERY_CHECK_FIELDS`，并让 `AgentReleaseGateService._final_delivery_contract()` 按固定顶层字段、category 字段和 artifact check 字段输出最终交付清单审计结果；两份 Harness 文档新增 `Required final delivery payload contract` 机器可读块，`test_harness_final_delivery_contract_matches_release_gate` 同时抽取 artifact id 清单与 payload 字段契约，并与 release gate snapshot、route payload、promotion release_gate 镜像、dashboard promotion summary 和代码常量全量比对，防止 final delivery 的 category/check/evidence 字段漂移或把 frontend external scope 误报为后端已交付；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.188-agent | Agent promotion blocker payload 契约收口：新增 `PROMOTION_BLOCKER_FIELDS`，并让 `AgentReleaseGateService._promotion_blockers()` 通过统一 helper 输出 `source/reason/severity/details` 字段；所有 blocker details 都带 `target_level`，并按 source 暴露静态 release gate 原因、tool matrix violations、minimum go-live missing_requirement_ids、go-live missing_by_priority、final delivery missing_by_category、monitoring alert summary 与 dashboard readiness。两份 Harness 文档新增 `Required promotion blocker payload contract` 机器可读块，`test_harness_promotion_assessment_contract_matches_release_gate` 从文档抽取 blocker 字段和 source-specific details 字段，并与 promotion assessment 的 release_gate/monitoring_alerts/readiness_dashboard blocker 实际输出全量比对，防止 promotion/UI 只能解析 source/reason 而无法定位具体阻断缺口；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.189-agent | Agent promotion decision 契约收口：新增 `PROMOTION_DECISION_VALUES` 与 `PROMOTION_ALREADY_UNLOCKED_CHECK_STATUS`，并让 `AgentReleaseGateService.promotion_assessment()` 在 `target_index <= current_index` 时顶层输出 `decision=already_unlocked`、`can_promote=false`、`blockers=[]`，避免 UI 或自动晋级器把“目标层级已解锁/无需晋级”误判为可执行晋级动作。两份 Harness 文档新增 `Required promotion decision contract` 机器可读块，`test_harness_promotion_assessment_contract_matches_release_gate` 同时抽取 decision values、already_unlocked 规则和 check status，并用 L3 blocked 与 L2 already_unlocked 两类实际 promotion assessment 输出全量比对；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.190-agent | Agent promotion assessment 顶层 payload 契约收口：新增 `PROMOTION_ASSESSMENT_FIELDS`，并让 `AgentReleaseGateService.promotion_assessment()` 按固定字段输出 `project_id/current_level/target_level/target_level_summary/decision/can_promote/blockers/checks/dashboard_checks/fault_injection/alert_summary/readiness/release_gate`。两份 Harness 文档新增 `Required promotion assessment payload contract` 机器可读块，`test_harness_promotion_assessment_contract_matches_release_gate` 从文档抽取顶层 fields，并与 service dict、`AgentReleaseGatePromotionRead.model_fields` 和 `model_dump()` 输出全量比对，防止 promotion endpoint 顶层字段漂移导致 UI/自动验收漏读门禁上下文；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.191-agent | Agent release gate snapshot 顶层 payload 契约收口：新增 `RELEASE_GATE_FIELDS`，并让 `AgentReleaseGateService.snapshot()` 按固定字段输出 `current_level/current_level_summary/allowed_side_effect_classes/blocked_side_effect_classes/tool_matrix/expansion_gates/minimum_go_live/go_live_gates/final_delivery/violations`，作为 dashboard、alerts 与 promotion 的共同事实源。两份 Harness 文档新增 `Required release gate snapshot payload contract` 机器可读块，`test_harness_rollout_matrix_matches_docs_contract` 从文档抽取 snapshot fields，并与 service dict、`AgentReleaseGateRead.model_fields` 和 release-gates route payload 全量比对，防止发布门禁快照顶层字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.192-agent | Agent release gate snapshot item payload 契约收口：新增 `RELEASE_GATE_TOOL_FIELDS`、`RELEASE_GATE_LEVEL_FIELDS` 与 `RELEASE_GATE_VIOLATION_FIELDS`，并让 `tool_matrix`、`expansion_gates` 和 `violations` 的 item 输出全部按固定字段顺序生成。两份 Harness 文档的 `Required release gate snapshot payload contract` 增补 `tool_fields/level_fields/violation_fields`，`test_harness_rollout_matrix_matches_docs_contract` 同时比对文档字段、Pydantic item schema、service snapshot、release-gates route payload，以及临时 business_create 工具触发的 violation item，防止 UI/告警/Runbook 逐项解析 release gate 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.193-agent | Agent release gate rollout decision 语义契约收口：新增 `RELEASE_GATE_ROLLOUT_DECISION_VALUES` 与 `RELEASE_GATE_VIOLATION_REASON`，并让 `tool_matrix.rollout_decision` 与 `violations.reason` 复用同一组常量；两份 Harness 文档的 `Required release gate snapshot payload contract` 增补 `rollout_decision_values`、`rollout_allowed_rule` 与 `violation_reason`，`test_harness_rollout_matrix_matches_docs_contract` 同时比对文档、代码常量、正常 tool matrix 输出和临时 business_create violation 输出，防止 UI/告警/Runbook 对 blocked/allowed 或 violation reason 的解析漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.194-agent | Agent alert snapshot payload 契约收口：新增 `ALERT_SNAPSHOT_FIELDS`、`ALERT_ITEM_FIELDS`、`ALERT_SUMMARY_FIELDS` 与 `ALERT_STATUS_VALUES`，并让 `AgentAlertService.snapshot()`、静态 metric alerts 与动态 release gate alert 都按固定字段顺序输出。两份 Harness 文档新增 `Required alert snapshot payload contract` 机器可读块，`test_harness_alert_snapshot_payload_contract_matches_service` 同时比对文档、常量、Pydantic schema、service dict 与 `/api/v1/agents/alerts` route payload，覆盖 `ok` 空告警和 `memory.bypassed_evidence_ref` 触发 P0 firing alert 场景，防止 UI/promotion/runbook 解析 alert snapshot 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.195-agent | Agent readiness dashboard payload 契约收口：新增 `READINESS_DASHBOARD_FIELDS`、`DASHBOARD_CHECK_FIELDS`、`DASHBOARD_CHECK_NAMES` 与 `READINESS_STATUS_VALUES`，并让 `AgentReadinessDashboardService.snapshot()` 和 `_check()` 按固定字段顺序输出。两份 Harness 文档新增 `Required readiness dashboard payload contract` 机器可读块，架构文档同步补齐 `root_cause_rule_governance` check 清单；`test_harness_readiness_dashboard_payload_contract_matches_service` 同时比对文档、常量、Pydantic schema、service dict 与 `/api/v1/agents/dashboard` route payload，覆盖 dashboard 顶层字段、check item 字段、check 顺序、readiness 枚举、alert summary 与 promotion summary 依赖，防止 UI/promotion 自动验收读取 dashboard 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.196-agent | Agent Runbook catalog/diagnosis payload 契约收口：新增 `RUNBOOK_FIELDS` 与 `RUNBOOK_RECOMMENDATION_FIELDS`，并将 `RUNBOOK_DIAGNOSIS_FIELDS` 改为有序字段常量；`AgentRunbookService.list_runbooks()`、`diagnose_run()` 现在分别按固定 catalog item、diagnosis 顶层与 recommendation item 字段顺序输出，recommendation 统一补齐 `tool_call_id=None` 以匹配 API schema。两份 Harness 文档的 `Required Runbook diagnosis contract` 新增 `runbook_fields` 与 `recommendation_fields`，`test_harness_runbook_diagnosis_contract_matches_schema_and_actions` 同时比对文档、常量、Pydantic schema、service dict、`/api/v1/agents/runbooks` 与 `/api/v1/agents/runs/{run_id}/runbook` route payload，并继续校验 safe_api_actions 均存在于 OpenAPI；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.197-agent | Agent Fault Injection payload 契约收口：新增 `FAULT_INJECTION_CASE_FIELDS`、`FAULT_INJECTION_RUN_FIELDS`、`FAULT_INJECTION_RESULT_FIELDS` 与 `FAULT_INJECTION_COVERAGE_FIELDS`，并让 `AgentFaultInjectionService.list_cases()`、`run_cases()`、fault result 输出和 `AgentFaultInjectionCoverageService.audit()` 按固定字段顺序返回。两份 Harness 文档新增 `Required fault injection payload contract` 机器可读块，`test_harness_required_fault_injection_cases_match_docs_contract` 同时比对文档、常量、Pydantic schema、service dict、`/api/v1/agents/fault-injections`、`/api/v1/agents/fault-injections/coverage` 与 `/api/v1/agents/fault-injections/run` route payload，防止 minimum go-live、dashboard 与生产硬化验收读取 fault injection payload 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.198-agent | Agent metrics snapshot payload 契约收口：新增 `METRICS_SNAPSHOT_FIELDS` 与 `METRICS_DERIVED_FROM_FIELDS`，并让 `AgentMetricsService.snapshot()` 按固定顶层字段与 `derived_from` 字段顺序返回。两份 Harness 文档新增 `Required metrics snapshot payload contract` 机器可读块，`test_harness_metrics_catalog_matches_architecture_contract` 同时比对文档、常量、`AgentMetricsSnapshotRead` schema、service dict 与 `/api/v1/agents/metrics` route payload，并继续校验 `REQUIRED_DASHBOARD_METRICS` 覆盖 service、route 和 dashboard metrics，防止 dashboard、alert、readiness 读取 metrics snapshot 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.199-agent | Agent WorkerQueue audit payload 契约收口：新增 `WORKER_QUEUE_AUDIT_FIELDS`、`WORKER_QUEUE_EXPIRED_LEASE_FIELDS`、`WORKER_QUEUE_DUPLICATE_ACTIVE_FIELDS` 与 `WORKER_QUEUE_DERIVED_FROM_FIELDS`，并让 `AgentWorkerQueueAuditService.audit()`、expired lease item、duplicate active item 与 `derived_from` 按固定字段顺序返回。两份 Harness 文档新增 `Required WorkerQueue audit payload contract` 机器可读块，`test_harness_worker_queue_audit_payload_contract_matches_service` 同时比对文档、常量、`AgentWorkerQueueAuditRead` schema、service dict 与 `/api/v1/agents/worker-queue/audit` route payload，防止 lease 扫描、duplicate active 告警、dashboard readiness 和 runbook 读取 WorkerQueue 审计 payload 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.200-agent | Agent Event Replay audit payload 契约收口：新增 `EVENT_REPLAY_AUDIT_FIELDS`、`EVENT_REPLAY_STRESS_AUDIT_FIELDS`、`EVENT_REPLAY_STRESS_RUN_FIELDS`、`EVENT_REPLAY_CURSOR_AUDIT_FIELDS` 与 `EVENT_REPLAY_DERIVED_FROM_FIELDS`，并让 `AgentEventReplayAuditService.audit_run()`、`audit_project()`、stress run item、cursor item 与 `derived_from` 按固定字段顺序返回。两份 Harness 文档新增 `Required Event Replay audit payload contract` 机器可读块，`test_harness_event_replay_audit_payload_contract_matches_service` 同时比对文档、常量、`AgentEventReplayAuditRead` / `AgentEventReplayStressAuditRead` schema、service dict、`/api/v1/agents/runs/{run_id}/events/replay-audit` 与 `/api/v1/agents/events/replay-stress-audit` route payload，防止 SSE Last-Event-ID 重放审计、stress audit、metrics、alerts 与 runbook 读取 replay payload 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.201-agent | Agent Approval expire payload 契约收口：新增 `APPROVAL_EXPIRE_AUDIT_FIELDS`、`APPROVAL_EXPIRE_PROCESS_FIELDS` 与 `APPROVAL_EXPIRE_DERIVED_FROM_FIELDS`，并让 `ApprovalExpireScanner.audit()`、`expire_due_summary()` 与 `derived_from` 按固定字段顺序返回。两份 Harness 文档新增 `Required Approval expire payload contract` 机器可读块，`test_harness_approval_expire_payload_contract_matches_service` 同时比对文档、常量、`AgentApprovalExpireAuditRead` / `AgentApprovalExpireProcessRead` schema、service dict、`/api/v1/agents/approvals/expire-audit` 与 `/api/v1/agents/approvals/expire` route payload，防止 approval due backlog、lineage hotspot、dashboard metrics、alerts 与 runbook 读取 approval expire payload 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.202-agent | Agent Outbox publish payload 契约收口：新增 `OUTBOX_PUBLISH_FIELDS`，并让 `AgentOutboxPublisher.publish_pending()` 按固定字段顺序返回 `attempted/published/failed/dead_letter/pending_remaining/outbox_publish_lag_ms`。两份 Harness 文档新增 `Required Outbox publish payload contract` 机器可读块，`test_harness_outbox_publish_payload_contract_matches_service` 同时比对文档、常量、`AgentOutboxPublishRead` schema、service dict 与 `/api/v1/agents/outbox/publish` route payload，防止 outbox publish/retry/dead-letter、metrics、alerts、dashboard readiness 与 runbook 读取 outbox publish payload 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.203-agent | Agent Memory feedback process payload 契约收口：新增 `MEMORY_FEEDBACK_PROCESS_FIELDS` 与 `MEMORY_FEEDBACK_RESULT_BASE_FIELDS`，并让 `MemoryFeedbackWorker.process_due()` 固定返回 `attempted/processed/skipped/contradictions_recorded/validations_recorded/results`，同时补齐 `validations_recorded`，避免支持性 execution/memory feedback 验证被 route schema 丢弃。两份 Harness 文档新增 `Required Memory feedback process payload contract` 机器可读块，`test_harness_memory_feedback_process_payload_contract_matches_service` 同时比对文档、常量、`AgentMemoryFeedbackProcessRead` schema、service dict、`/api/v1/agents/memory-usage-events/{usage_event_id}/feedback` 与 `/api/v1/agents/memory-feedback/process` route payload，防止 Memory validation/contradiction/feedback 强化闭环读取 process payload 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.204-agent | Agent Memory retrieval payload 契约收口：新增 `MEMORY_CANDIDATE_FIELDS`、`MEMORY_CANDIDATE_EVIDENCE_REF_FIELDS` 与 `memory_candidate_to_payload()`，并让 `/api/v1/agents/memories/retrieve` 不再依赖 dataclass `__dict__` 输出候选 memory。两份 Harness 文档新增 `Required Memory retrieval payload contract` 机器可读块，`test_harness_memory_retrieval_payload_contract_matches_service` 同时比对文档、常量、`AgentMemoryCandidateRead` schema、service candidate payload 与 route payload，覆盖 memory candidate 顶层字段和内嵌 memory EvidenceRef 字段，防止 ContextBuilder、ToolPolicy、RootCause 与 Memory feedback 链路读取检索结果时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.205-agent | Agent Memory usage event payload 契约收口：新增 `MEMORY_USAGE_EVENT_FIELDS` 与 `MEMORY_USAGE_EVENT_EVIDENCE_REF_FIELDS`，并在两份 Harness 文档新增 `Required Memory usage event payload contract` 机器可读块。`test_harness_memory_usage_event_payload_contract_matches_route` 同时比对文档、常量、`AgentMemoryUsageEventRead` schema、run-scoped route payload 与 admin global route payload，覆盖 usage event 顶层审计字段和内嵌 EvidenceRef 字段，防止 Memory retrieval、feedback、metrics、dashboard 与审计 UI 读取 `GET /api/v1/agents/memory-usage-events` 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.206-agent | Agent Memory staleness event payload 契约收口：新增 `MEMORY_STALENESS_EVENT_FIELDS`，并在两份 Harness 文档新增 `Required Memory staleness event payload contract` 机器可读块。`test_harness_memory_staleness_event_payload_contract_matches_route` 同时比对文档、常量、`AgentMemoryStalenessEventRead` schema、admin global route、project scoped route 与 memory scoped route payload，覆盖 EvidenceWatch stale 级联 Memory 降权时的审计字段，防止 Memory staleness、metrics、dashboard、runbook 与审计 UI 读取 `GET /api/v1/agents/memory-staleness-events` 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.207-agent | Agent Memory validation event payload 契约收口：新增 `MEMORY_VALIDATION_EVENT_FIELDS`，并在两份 Harness 文档新增 `Required Memory validation event payload contract` 机器可读块。`test_harness_memory_validation_event_payload_contract_matches_route` 同时比对文档、常量、`AgentMemoryValidationEventRead` schema、admin global route、project scoped route 与 memory scoped route payload，覆盖人工确认和 execution evidence 支持 Memory 时的 validation 审计字段，防止 Memory validation、feedback、metrics、dashboard、runbook 与审计 UI 读取 `GET /api/v1/agents/memory-validation-events` 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.208-agent | Agent Memory profile catalog payload 契约收口：新增 `MEMORY_SOURCE_PROFILE_FIELDS` 与 `MEMORY_RETRIEVAL_PROFILE_FIELDS`，并在两份 Harness 文档新增 `Required Memory profile catalog payload contract` 机器可读块。`test_harness_memory_profile_catalog_payload_contract_matches_routes` 同时比对文档、常量、`AgentMemorySourceProfileRead` / `AgentMemoryRetrievalProfileRead` schema、`/api/v1/agents/memory-source-profiles` 与 `/api/v1/agents/memory-retrieval-profiles` route payload，覆盖 Memory source/retrieval profile catalog 顶层字段和排序稳定性，防止 Memory 创建、检索 hard gate、ToolPolicy、dashboard 与审计 UI 读取 profile catalog 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.209-agent | Agent Memory entity payload 契约收口：新增 `MEMORY_ENTITY_FIELDS`，并在两份 Harness 文档新增 `Required Memory entity payload contract` 机器可读块。`test_harness_memory_entity_payload_contract_matches_routes` 同时比对文档、常量、`AgentMemoryRead` schema、`GET/POST/PATCH /api/v1/agents/memories`、`POST /api/v1/agents/memories/{memory_id}/validate` 与 `POST /api/v1/agents/memories/{memory_id}/reject` route payload，覆盖 Memory 基础实体字段、version bump、validation_count 和 rejected 状态输出，防止 Memory UI、retrieval、feedback、metrics、dashboard 与审计链路读取实体 payload 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.210-agent | Agent Run entity payload 契约收口：新增 `AGENT_RUN_FIELDS`，并在两份 Harness 文档新增 `Required Agent Run entity payload contract` 机器可读块。`test_harness_agent_run_payload_contract_matches_routes` 同时比对文档、常量、`AgentRunRead` schema、`POST /api/v1/agents/runs`、`GET /api/v1/agents/runs/{run_id}` 与 `POST /api/v1/agents/runs/{run_id}/cancel` route payload，覆盖 Run 基础事实源字段、snapshot 指针、event sequence、migration/blocking 状态与 cancel 状态输出，防止 Agent Run 页面、SSE/event replay、resume/reconcile、dashboard 与 runbook 读取 Run entity payload 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.211-agent | Agent ToolCall entity payload 契约收口：新增 `TOOL_CALL_FIELDS`，并在两份 Harness 文档新增 `Required ToolCall entity payload contract` 机器可读块。`test_harness_tool_call_entity_payload_contract_matches_routes` 同时比对文档、常量、`AgentToolCallRead` schema、`GET /api/v1/agents/tool-calls/{tool_call_id}`、`POST /api/v1/agents/tool-calls/{tool_call_id}/approve` 与 `POST /api/v1/agents/tool-calls/{tool_call_id}/reject` route payload，覆盖 ToolCall 事实源字段、幂等/副作用/replay policy、EvidenceRef、审批 lineage、backend contract、reconcile 结果和详情页动态审计字段，防止 ToolCall Detail、Approval Panel、resume/reconcile、dashboard 与 runbook 读取 ToolCall entity payload 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.212-agent | Agent RuntimeSnapshot entity payload 契约收口：新增 `RUNTIME_SNAPSHOT_FIELDS`，并在两份 Harness 文档新增 `Required RuntimeSnapshot entity payload contract` 机器可读块。`test_harness_runtime_snapshot_payload_contract_matches_route` 同时比对文档、常量、`AgentRuntimeSnapshotRead` schema 与 `GET /api/v1/agents/runtime-snapshots/{snapshot_id}` route payload，覆盖 snapshot id、项目归属、创建人、runtime/tool registry/manifest/prompt/policy hash、tool/manifest/adapters/policies 冻结内容和创建时间，防止 Agent Run、ToolCall Detail、resume/replay、release gate 与 runbook 读取冻结运行时契约时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.213-agent | Agent Event entity payload 契约收口：新增 `AGENT_EVENT_FIELDS`，并在两份 Harness 文档新增 `Required Agent Event entity payload contract` 机器可读块。`test_harness_agent_event_payload_contract_matches_event_store` 同时比对文档、常量、`AgentEventRead` schema 与 `AgentRuntimeService.list_events` EventStore payload，覆盖 event_seq、event_type、payload_json、created_at 以及 payload 内 schema_version/run_id/project_id/event_seq/event_type 基础事件信封，防止 Agent Event Timeline、SSE Last-Event-ID replay、event replay audit、dashboard 与 runbook 读取事件流时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.214-agent | Agent ContextBuild entity payload 契约收口：新增 `CONTEXT_BUILD_FIELDS`，并在两份 Harness 文档新增 `Required ContextBuild entity payload contract` 机器可读块。`test_harness_context_build_payload_contract_matches_routes` 同时比对文档、常量、`AgentContextBuildRead` schema、`POST /api/v1/agents/runs/{run_id}/context-builds` 与 `GET /api/v1/agents/runs/{run_id}/context-builds` route payload，覆盖 context_build_id、run/iteration/step/build_seq、build purpose、model/token budget、context degradation、required evidence completeness、prompt object/hash 和 metadata，防止 ContextBuilder、LoopObservation、resume freshness、ToolPolicy、dashboard 与 runbook 读取 ContextBuild payload 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.215-agent | Agent LoopObservation entity payload 契约收口：新增 `LOOP_OBSERVATION_FIELDS`，并在两份 Harness 文档新增 `Required LoopObservation entity payload contract` 机器可读块。`test_harness_loop_observation_payload_contract_matches_routes` 同时比对文档、常量、`AgentLoopObservationRead` schema、`POST /api/v1/agents/runs/{run_id}/loop-observations` 与 `GET /api/v1/agents/runs/{run_id}/loop-observations` route payload，覆盖 observation id、decision ContextBuild 绑定、context degradation、required evidence completeness、next action、stop reasons、root cause rule、causal chain、mitigation action 和 observation_json，防止 LoopController、Runbook diagnosis、dashboard、fault injection 与恢复建议读取 LoopObservation payload 时字段漂移；无数据模型变化，无需新增迁移。 |
| 2026-06-27 | 3.0.216-agent-frontend | Agent Codex 风格前端原型与开发计划：新增 `front_tech_docs/agent-codex-prototype.md`、`front_tech_docs/agent-frontend-development-plan.md` 与 `docs/api_agent_frontend_contract.md`，基于当前 React 19/Vite/TypeScript 前端技术文档、参考图和后端 `/api/v1/agents/*` 契约设计 `/agents` 工作台。方案覆盖多轮 conversation、Run 创建、fetch stream SSE、ToolCall 输出、Approval CAS、Migration Block、ContextBuild、LoopObservation、Memory、Runbook、Dashboard、Release Gate、本地历史限制和后续服务端历史接口缺口；仅产出原型与计划，不创建前端工程代码。 |
| 2026-06-27 | 3.0.217-agent-migration-hotfix | 修复前端提交 `POST /api/v1/agents/runs` 时后端报 `ai_agent_runtime_snapshots` 不存在的问题：确认目标库仍停在 `0020_scenario_nodes` 且 Agent 表未落库后，执行 Agent 迁移至 `0028_agent_memory_staleness_events` head，验证 `ai_agent_runtime_snapshots`、`ai_agent_runs`、`ai_agent_tool_calls`、`ai_agent_context_builds`、`ai_agent_memory_staleness_events` 等 24 张 Agent 表存在；同时修复 `migrations/env.py`，在 MySQL 在线迁移前确保 `alembic_version.version_num` 为 `VARCHAR(128)` 并提交自修复事务，避免长 revision id 导致版本号写入失败和重复执行迁移。 |
| 2026-06-27 | 3.0.218-agent-conversation-runner | Agent 无工具调用对话生成流程接入：新增 `AgentConversationRunner`，`POST /api/v1/agents/runs` 创建非 terminal run 后通过共享 `execution_worker` 异步调用 `AIService.chat_stream()`，将 `model.started`、`model.delta`、`model.completed` 写入 EventStore / Outbox，并最终写入 `run.completed`；模型异常统一落 `run.failed`，worker 队列满时写 `agent_conversation_worker_queue_full`，测试环境 SQLite 路由直调跳过真实后台线程以避免误连线上模型。同步更新 Harness 架构/开发计划、前端原型与前端接口契约，明确前端按 `model.delta.content` 渲染 assistant 流式气泡。 |
| 2026-06-27 | 3.0.219-agent-conversation-history | Agent 服务端历史和多轮上下文补齐：`AgentRuntimeService.create_run` 在未传 `conversation_id` 时生成 `agent-conv-*`，新增 `GET /api/v1/agents/conversations`、`GET /api/v1/agents/conversations/{conversation_id}/runs` 与 `GET /api/v1/agents/runs`，按项目权限返回 conversation summary、单会话 run 列表和 run 历史；`AgentConversationRunner` 会将同 conversation 最近已完成 run 的 `intent` 与 `result_json.message` 作为 user/assistant 历史传给 `AIService.chat_stream()`，让多轮追问具备服务端上下文。同步更新 Harness 架构/开发计划、前端原型、前端开发计划和接口契约，移除 localStorage-only 历史限制。 |
| 2026-06-27 | 3.0.220-agent-model-tool-loop | Agent 模型驱动工具闭环接入：`AgentConversationRunner` 现在把 ToolRegistry 以受控 `agent_tool_request` 协议加入系统提示，模型可请求安全工具；后端解析后写入 `model.tool_request_detected`，通过 `ExecutionLedgerService.create_tool_call(enqueue=False)` 创建 ToolCall，并复用 `ToolExecutor.execute_tool_call` 完成权限、策略、审批与 adapter 执行。工具输出通过 `tool.result_observed` 回灌给下一轮模型，最终回复仍通过 `model.delta` 和 `run.completed.result.message` 返回前端；新增回归覆盖模型请求 `project.read_context`、自动补齐 project_id、工具执行成功、结果回灌与最终自然语言回复。同步更新接口契约、前端原型/计划、Harness 架构和开发计划；无新增迁移。 |
| 2026-06-27 | 3.0.221-agent-approval-resume-loop | Agent 审批后恢复对话闭环补齐：新增 `AgentConversationRunner.complete_after_tool_results`，`AgentRunResumeService.resume_run` 在 `needs_human` run 的 blocking ToolCall 已 approve 后，会先通过 Checkpoint Freshness Gate，再复用 `ToolExecutor.execute_tool_call` 执行已批准工具、写入 `tool.result_observed(resumed_after_approval=true)`、清理 `blocking_tool_call_ids_json`，并基于工具结果继续调用模型生成最终回复。`AgentRunResumeRead` 新增 `executed_tool_call_ids`，前端可在 approve 后触发 resume 并继续监听 SSE；新增回归覆盖 approval -> resume -> tool.completed -> model.delta -> run.completed。同步更新接口契约、前端原型/计划、Harness 架构和开发计划；无新增迁移。 |
| 2026-06-27 | 3.0.222-agent-memory-conversation-context | Agent 项目 Memory 对话上下文补齐：`AgentConversationRunner` 在每次模型调用前使用 `MemoryManager.retrieve(profile_name=normal_plan_v1, usage_role=conversation_context)` 检索当前项目 Memory，命中后写入 `memory.context_injected` 事件并创建 `AgentMemoryUsageEvent(active_for_policy=false)`，再把压缩后的 Memory 上下文作为系统消息传给模型；Memory 注入只辅助自然语言规划，不替代高风险 ToolCall 所需的 EvidenceRef/审批/工具结果。新增回归覆盖模型请求消息包含项目 Memory、usage event 落库、事件流包含 `memory.context_injected`；同步接口契约、前端原型/计划、Harness 架构和开发计划；无新增迁移。 |
| 2026-06-27 | 3.0.223-agent-tool-request-repair | Agent 模型工具请求格式自修复补齐：`AgentConversationRunner` 现在对 `agent_tool_request` JSON 做严格类型校验，不再把错误的 `input` 或 `evidence_refs` 静默吞成空对象/数组；当模型工具请求格式不合法时写入 `model.tool_request_invalid`，追加修复提示并进行一次 `model.started(repair_attempt=true)` 调用，修复成功写入 `model.tool_request_repaired` 后继续 ToolCall 生命周期，修复失败写入 `model.tool_request_repair_failed` 并按模型错误终止。新增回归覆盖非法 `evidence_refs:{}` 自动修复为合法工具请求、继续执行工具并生成最终回复；同步接口契约、前端原型/计划、Harness 架构和开发计划；无新增迁移。 |
| 2026-06-27 | 3.0.224-agent-realtime-model-delta | Agent Codex 式实时流式回复补齐：`AgentConversationRunner._stream_model_response` 现在在 DeepSeek stream 仍进行时实时写入普通自然语言 `model.delta`，不再等模型 done 后统一落 EventStore；同时保留疑似 `agent_tool_request` 输出的缓冲判定，避免工具请求 JSON 被前端渲染成 assistant 气泡。新增回归在 fake stream 第二段输出前直接查询 EventStore，证明首个 `model.delta` 已经落库；同步接口契约、前端原型/计划、Harness 架构和开发计划；无新增迁移。 |
| 2026-06-27 | 3.0.225-agent-model-health | Agent 模型配置与 live stream 探测补齐：新增 `AgentModelHealthService`、`AgentModelHealthRead` 与 `GET /api/v1/agents/model-health`，默认 `live=false` 只返回 provider/configured/base_url/default_model 和空探测字段，不调用 DeepSeek 且不暴露 API key；`live=true` 仅 admin 可用，通过极小 `AIService.chat_stream()` 请求返回 reachable、latency_ms、first_delta_received、completed、model、finish_reason 与错误信息，用于定位“前端创建 Run 后没有 assistant 回复”的 provider/key/SSE 链路问题。新增回归覆盖配置检查不触发 stream、live 探测成功、key 缺失短路和路由权限；同步接口契约、前端原型/计划、Harness 架构/开发计划和技术架构；无新增迁移。 |
| 2026-06-28 | 3.0.226-agent-smoke-autocomplete-boundary | Agent smoke auto-complete 边界收口：`AgentRunCreateRequest.auto_complete` 明确为后端 smoke/debug 字段，普通 Codex 式对话必须保持 false 并走 `AIService.chat_stream()`；auto-complete Run 仍写入 `run.completed` 以支持 EventStore/Outbox 回归，但结果改为 `completion_source=smoke_auto_complete`、`model_invoked=false`、`assistant_visible=false`，避免前端把 smoke 结果渲染成真实 assistant 回复。新增回归覆盖 smoke run payload 标记；同步接口契约、前端原型/计划、Harness 架构和开发计划；无新增迁移。 |
| 2026-06-28 | 3.0.235-agent-real-e2e-diagnostic | Agent 真实 DeepSeek/MySQL 端到端诊断脚本补齐：新增 `scripts/agent_conversation_e2e_check.py`，按普通用户路径执行 live model health、`POST /api/v1/agents/runs`、`GET /api/v1/agents/runs/{run_id}/events/snapshot` 轮询和 Run Summary 校准；脚本只在 `model.started`、至少一个 `model.delta`、`run.completed` 与 `assistant_visible=true` 全部成立时返回成功，且不打印 DeepSeek API key。已在当前 MySQL `test_platform_backend` 与 `deepseek-v4-flash` 配置上验证 `result= ok`、assistant 前缀为 `Agent e2e ok.`；同步接口契约、前端原型/计划、Harness 架构和开发计划；无新增接口和迁移。 |
| 2026-06-28 | 3.0.236-agent-launch-audit | Agent 前端联调/上线准备聚合审计补齐：新增 `AgentLaunchAuditService`、`AgentLaunchAuditRead` 与 `GET /api/v1/agents/launch-audit`，按项目权限聚合 `model-health(live=false)`、readiness dashboard、release gate promotion、前端事件契约、后端交付范围和 frontend external scope，输出固定 checks、`ready/status`、model/dashboard/promotion 摘要；该接口不触发 live DeepSeek 调用且不暴露 API key，项目成员可用它判断后端是否已具备前端联调条件，admin 可做全局审计。新增回归覆盖字段契约、权限边界、模型未配置阻断和 Harness 文档契约；同步接口契约、前端原型/计划、技术架构、Harness 架构和开发计划；无新增迁移。 |
| 2026-06-28 | 3.0.237-agent-backend-completion-audit | Agent 后端功能完成度聚合审计补齐：新增 `AgentBackendCompletionAuditService`、`AgentBackendCompletionAuditRead` 与 `GET /api/v1/agents/backend-completion-audit`，按项目权限汇总模型配置、对话流式生成、服务端历史、工具循环、审批恢复、Memory 注入、前端契约面、observability/release gate、文档同步和 live E2E 诊断路径，输出固定 checks、`complete/status`、backend scope、runtime contracts 与 diagnostics 摘要；该接口不触发 live DeepSeek 调用且不暴露 API key，明确 `complete=true` 仅声明后端仓库范围完成，前端交付仍在外部仓库，生产灰度仍由 release gate 控制。新增回归覆盖字段契约、权限边界、模型未配置阻断和 Harness 文档契约；同步接口契约、前端原型/计划、技术架构、Harness 架构和开发计划；无新增迁移。 |
| 2026-06-28 | 3.0.238-agent-scenario-query-first | Agent 场景组合 query-first 工具链补齐：新增 `testcase.query_project_cases` ToolSpec/Backend，用于读取当前项目 HTTP/WebSocket 用例并将脱敏用例详情回灌模型；`AgentConversationRunner` 注入 run context，禁止反问已有 `project_id`，并在 `scenario.compose_draft` 执行前强制要求同一 run 内已有成功的 `testcase.query_project_cases`，否则写入失败 ToolCall、`tool.failed`、`tool.result_observed` 和 `scenario_compose_requires_case_query`，让模型按 Codex harness 闭环纠正为 query -> compose -> final answer。新增回归覆盖 query-first 正常路径、直接 compose 被 guard 阻断后继续纠正、默认环境与候选用例回填；同步接口契约、前端原型/计划、技术架构、Harness 架构和开发计划；无新增迁移。 |
| 2026-06-28 | 3.0.239-scenario-composer-action-repair | 智能场景组合输出兼容继续加固：`ScenarioComposerSkill` 现在会归一化 `before_actions` / `after_actions`，当模型漏掉 `kind` 但可由配置确定动作类型时自动补齐为 `fixed_value`、`delay`、`condition`、`random` 或 `script`，无法推断或配置不合法时丢弃并写入 warnings，避免单个非关键动作导致 `ScenarioCreateRequest` 整体校验失败。新增 `test_scenario_composer_repairs_actions_missing_kind` 回归；真实 DeepSeek/MySQL Agent E2E 已验证 `admin` 账号 user_id=1 路径下 `testcase.query_project_cases -> scenario.compose_draft -> run.completed` 成功，场景组合自验证通过；同步 AI 接口文档、AI 开发记录和 DeepSeek 技术指南；无新增迁移。 |
| 2026-06-28 | 3.0.240-agent-markdown-output-contract | Agent 用户可见回复 Markdown 契约加固：`AgentConversationRunner` 系统提示新增 GitHub Flavored Markdown 输出规则，要求表格表头、分隔行和数据行独占一行；完成 run 前新增 Markdown 正规化兜底，修复模型把表格行用 `| |` 挤在同一行的输出，并在修复时写入 `model.markdown_normalized(replace_content=true)`，最终 `model.completed.content` 与 `run.completed.result.message` 均为可直接渲染的 Markdown。新增回归覆盖压缩表格被修复、summary 和 completed 事件一致、prompt 注入 Markdown 规则；同步接口契约、前端原型/计划、Harness 架构和开发计划；无新增迁移。 |
| 2026-06-29 | 3.0.241-agent-testing-general-answer | Agent 软件测试领域通用回答能力补齐：`AgentConversationRunner` 系统提示新增领域问答模式，明确测试理论、用例设计、接口/WebSocket 测试、断言/提取器、测试数据、环境配置、Mock、缺陷定位、执行诊断、回归策略、CI、风险覆盖、报告解读、测试计划和平台使用建议等无需项目实时事实或平台副作用的问题可直接自然语言回答；超出软件测试领域时说明能力边界，涉及真实项目资源、草稿生成或保存动作仍必须走工具协议。新增回归覆盖通用测试问答 prompt 注入、无 ToolCall 直接完成和最终 assistant 回复；同步接口契约、前端计划、技术架构、Harness 架构和开发计划；无新增迁移。 |
| 2026-06-29 | 3.0.242-agent-scenario-warning-repair | Agent 场景组合 warnings 可修复项闭环补齐：`AgentConversationRunner` 在 `scenario.compose_draft` 工具结果回灌中新增后处理规则，要求模型先分析每个候选用例的用途、请求字段、响应样本、最近执行结果和 warnings，再把硬编码业务字段、未动态绑定、提取器路径、断言 expected、数据集变量等可自动修复项通过下一次 `scenario.compose_draft(input.extra_requirements=...)` 修复并自验证；鉴权令牌、账号密码、密钥或没有平台来源的用户私有输入才作为阻断项交给用户。新增回归覆盖 compose 返回 `companyName 未动态绑定` 与鉴权 warning 时，下一轮模型收到 repair prompt 并再次调用 compose，最终只把 auth token 留给用户配置；同步接口契约、前端计划、技术架构、Harness 架构和开发计划；无新增接口、数据模型或迁移。 |
| 2026-06-29 | 3.0.243-agent-generic-tool-quality-repair | Agent 工具结果质量闭环通用化：`AgentConversationRunner` 不再只识别 `scenario.compose_draft` warnings，而是统一扫描任意成功 ToolCall 输出中的 `warnings`、`issues`、`diagnostics`、`errors` 和 `valid=false`，拆分为可自动修复项、用户/外部配置阻断项和待模型继续判断项，并在工具结果回灌中注入通用质量闭环规则与按工具推荐的安全修复路径。可修复项通过 read/query/draft/validate/dry-run 工具继续修复或验证，例如 `ai_skill.run_draft(input.extra_requirements=...)`、`testcase.validate_schema`、`scenario.compose_draft(input.extra_requirements=...)`；鉴权令牌、账号密码、密钥、审批或无平台来源的私有输入才进入最终用户提示。新增回归覆盖场景组合 warning repair 仍生效，以及普通 `ai_skill.run_draft` 返回可修复 warning 时会再次调用同一 draft 工具修复；同步接口契约、前端计划、技术架构、Harness 架构和开发计划；无新增接口、数据模型或迁移。 |
| 2026-06-29 | 3.0.244-agent-streaming-latency | Agent SSE/LLM 流式输出低延迟优化：`AgentConversationRunner._stream_model_response` 保持首个可见 `model.delta` 立即写入 EventStore，后续极小模型碎片按 80ms 或 120 字符微批提交，减少每 token 一次数据库事务；模型 stream 中的 run cancel 检查改为 200ms 级定期刷新，降低每 chunk 的 DB refresh 开销。`GET /api/v1/agents/runs/{run_id}/events` 对 `queued/running` run 轮询间隔从固定 500ms 优化为 100ms，非活跃状态保持 500ms 和 heartbeat，降低 EventStore 到浏览器的传播延迟。新增回归覆盖首个 delta 在 stream 未结束时可见，以及 30 个小 delta 被合并为少量 `model.delta` 事件且最终回复完整；同步接口契约、前端计划、技术架构、Harness 架构和开发计划；无新增接口、数据模型或迁移。 |
| 2026-06-29 | 3.0.245-agent-stale-run-guard | Agent 陈旧 active run 自动终止与 SSE cursor 防御：新增 `AGENT_RUN_STALE_TIMEOUT_SECONDS` 配置，`AgentRuntimeService` 在 run 详情、列表、conversation、transcript、SSE 事件读取和 snapshot 路径上用最新 EventStore 事件时间判断 `queued/running` run 是否长时间无活动；超过默认 900s 后自动标记 `failed` 并写入 `run.failed(error_code=agent_run_stale_worker_lost)`，避免 worker 崩溃、进程重启或前端错过终态后 UI 无限显示“正在思考”。`list_events` 与 `events/snapshot` 同时新增 run-scoped cursor 防御：当 `Last-Event-ID/after_sequence` 大于当前 run 的 `latest_event_sequence`，视为跨 run cursor 污染并重置为 0 重放当前 run 事件，避免 SSE 连接只返回 heartbeat。新增回归覆盖陈旧 running run 被查询时转为 failed 并产生终态事件，以及超大 cursor 会重放当前 run 的 `run.queued/run.started/run.completed`；同步 `.env.example`、接口契约、前端计划和技术架构；无新增接口、数据模型或迁移。 |
| 2026-06-29 | 3.0.246-agent-behavior-eval-repair | 基于 woagent 行为评测报告修复 Agent 场景组合与工具边界：`AgentConversationRunner` 对“保存正式场景”但 ToolRegistry 无保存工具的请求新增 `unsupported_scenario_save_guard`，直接说明无法保存且不再重新 compose 草稿；工具规划轮静默收流解析，混合自然语言与 `agent_tool_request` 的输出进入工具请求修复，避免内部 JSON 泄露到 `model.delta`；场景 query-first 后若已有候选用例但模型未继续 `scenario.compose_draft`，写入 `model.required_tool_missing` 并静默修复；DeepSeek 已产生 partial content 后断流时写入 `model.stream_interrupted` 并尽量继续解析/完成；失败 ToolCall 的 schema/input/validation 错误也进入修复闭环，支持 datasets schema 类错误自动重试。新增回归覆盖保存短路、混合工具块抑制、query 后缺 compose 自动修复和失败 compose schema 重试；同步接口契约、前端计划和技术架构；无新增接口、数据模型或迁移。 |
| 2026-06-29 | 3.0.247-agent-save-intent-semantic-guard | 完整 live 评测发现 `unsupported_scenario_save_guard` 过宽，会把“不要保存”的场景组合请求误判为保存正式场景并短路 T04/T05/T07。修复方式改为成熟 Agent 常见的语义 guardrail：保存/持久化/发布等关键词只触发结构化意图分类，只有分类确认用户要求把场景持久化为正式实体且 ToolRegistry 无 `scenario.save/create/persist` 能力时，才直接返回无法保存；分类失败或分类为“只生成草稿/不要保存”时继续交给主模型进行 query-first 工具规划。新增回归覆盖明确保存仍短路、明确不要保存不会短路并继续进入主模型；同步接口契约和技术架构。 |
| 2026-06-29 | 3.0.248-agent-loop-runtime-trace | Agent Loop Runtime 可观测性收口：`AgentConversationRunner` 为每次 LLM 调用生成 `iteration_id`、`model_call_id` 和 `loop_step`，并写入 `model.started`、实时/补发 `model.delta`、`model.markdown_normalized`、`model.completed`、`model.stream_interrupted` 以及 intent guard 事件；`model.tool_request_detected` 和 `tool.*` 审计事件在可得时补充 `decision_reason`、`tool_call_id` 和 loop trace，使同一用户问题内的普通回答、工具规划、工具请求修复、必需工具修复、最终总结可被前端和评测区分。query-first guard 进一步要求 `scenario.compose_draft` 之前必须已存在时间顺序更早的成功 `testcase.query_project_cases`，避免后续 query 反向“证明”早先 compose。`scripts/agent_behavior_evaluation.py` 新增 model call/loop step/repair/compaction 指标并修正工具顺序评估；同步接口契约、前端计划、技术架构和两份 Harness 文档；无新增接口、数据模型或迁移。 |
| 2026-06-29 | 3.0.249-agent-loop-stream-repair | 基于 live woagent 评测中的长场景组合链路继续修复 Agent loop：当模型把自然语言说明和单个 fenced `agent_tool_request` 混在一起时，`AgentConversationRunner` 先本地挽救工具块并规范化轻微 `evidence_refs` schema 偏差，写入 `model.tool_request_repaired(repair_strategy=salvaged_fenced_tool_request)`，避免额外 LLM 修格式调用和无谓失败；当工具规划轮为防泄露而静默收流、但最终内容不是工具请求而是普通文本时，只补发一个合并后的可见 `model.delta`，避免按原始 token chunk 大量写入 EventStore/SSE 导致前端长时间“正在思考”；实时可见输出保留首个 delta 立即写入，但后续微批窗口从 80ms/120 字符调为 350ms/240 字符，降低长 final summary 的 EventStore/SSE 写入压力。新增回归覆盖本地挽救不触发 repair model call、静默规划普通文本只产生一个 delta；同步接口契约、前端计划、技术架构和 Harness 文档；无新增接口、数据模型或迁移。 |
| 2026-06-29 | 3.0.250-agent-tool-result-policy | Agent 工具结果闭环模块化：新增 `app/services/agent_tool_result_policy.py`，把 warnings/issues/diagnostics/errors/valid=false 的抽取、可自动修复/用户阻断/待判断分类、按工具推荐修复路径和失败工具重试提示集中到 `ToolResultPolicy`，`AgentConversationRunner` 只负责把 policy 生成的回灌消息送回模型。工具结果回灌和 max-iterations 兜底总结统一加入最终回复预算：如果不再请求工具，默认只输出已完成、已自动修复/验证、剩余阻断项和下一步，不展开完整场景步骤大表或长 JSON，详细结构以 ToolCall/summary/report 详情为准。新增单元测试覆盖 policy 分类、失败工具修复提示和最终回复预算；同步接口契约、前端计划、技术架构和 Harness 文档；无新增接口、数据模型或迁移。 |
| 2026-06-29 | 3.0.251-agent-prompt-cache-stability | Agent prompt cache 稳定性加固：`AgentConversationRunner` 系统提示中的 ToolRegistry 简化清单继续按工具名排序，并改用 `json.dumps(sort_keys=True, separators=(",", ":"))` 输出稳定 JSON，减少同一工具集合下因字段顺序或空白变化导致的多轮 prompt 前缀漂移，让 provider 更容易复用系统提示/工具清单前缀。新增回归覆盖 ToolRegistry 排序、重复构建 `_conversation_system_prompt()` 字符串一致，以及工具 JSON 字段顺序稳定；同步接口契约、前端计划和技术架构；无新增接口、数据模型或迁移。 |
| 2026-06-29 | 3.0.252-agent-history-compaction | Agent 多轮历史上下文预算压缩：`AgentConversationRunner` 构建同一 conversation 的历史消息时，从固定最近 8 轮全量拼接升级为最多读取 12 轮、按估算 token 预算判断是否压缩；超过预算时将较早轮次压成一个 system 摘要，保留最近若干轮截断后的 user/assistant 内容，并写入 `context.history_compacted(strategy=summarize_older_keep_recent)` 事件，避免长历史拖慢每次模型调用或挤占当前工具结果上下文。新增回归覆盖长历史触发压缩、模型 prompt 中包含压缩摘要、EventStore 写入压缩审计事件；同步接口契约、前端计划、技术架构和 Harness 文档；无新增接口、数据模型或迁移。 |
| 2026-06-30 | 3.0.253-agent-skill-registry | Agent Codex-style SkillRegistry 抽取：新增 `app/services/agent_skill_registry.py` 和 `app/agent_skills/*/SKILL.md`，把通用测试问答、场景组合 query-first/保存边界、报告摘要边界从主 Runner prompt 拆为可复用 Skill；`AgentConversationRunner` 系统 prompt 只保留稳定 Skill catalog，每个 run 按 intent 渐进注入相关 Skill 正文；新增 `GET /api/v1/agents/skills` 只暴露 `{name,description}` 元数据，前端新增 `AgentSkill` 类型与 `getAgentSkills()` 映射，测试覆盖 Skill 选择、catalog 路由、prompt 稳定性和前端元数据边界；无新增迁移。 |
| 2026-06-30 | 3.0.254-agent-skill-triggers | Agent Skill 触发规则元数据化：`AgentSkillRegistry` 不再通过 Python `_domain_phrases(skill_name)` 硬编码领域短语，而是从每个 `SKILL.md` frontmatter 读取后端私有 `triggers`，与 `name/description` 一起用于 intent 匹配；新增临时自定义 Skill 单测，证明新增 Skill 只需添加目录与 `SKILL.md`，无需修改 Runner 或注册表路由代码；同步接口契约和架构文档，`GET /api/v1/agents/skills` 仍只返回 `{name,description}`。 |
| 2026-06-30 | 3.0.255-agent-report-summary-tool | Agent `report.read_summary` 从占位 adapter 接入 `TestReportService.list_reports`：工具输入支持 `source_type/status/environment_id/page_size` 过滤，输出最近报告列表、失败报告样本、状态统计、返回页内用例总量与通过率，保持 `read_only/reuse_allowed` ToolSpec 和 `report:view` 权限边界；新增真实 DB 级 Agent tool 回归，验证计划报告和流程报告可被汇总给 Report Skill 使用；无新增迁移。 |
| 2026-06-30 | 3.0.256-agent-tool-handler-manifest | Agent ToolSpec 执行入口收口：内置工具在 `ToolSpec.backend_handler` 声明后端私有 handler 名称，`AgentToolBackend.execute()` 从 `ToolRegistry` 读取 spec 后动态分发，移除平行维护的 execute handler 字典，降低新增工具时 “有 manifest 无执行入口” 的漂移风险；`backend_handler` 不进入 `ToolSpec.to_json()`、模型工具清单或前端契约；新增回归覆盖所有内置 ToolSpec 都能解析到可调用 handler。 |
| 2026-06-30 | 3.0.257-agent-skill-routing-hints | Agent Skill 私有路由 hints 收口：`AgentSkillRegistry` 支持读取 `guard_*` / `routing_*` frontmatter list 并通过 `private_list()` 提供给后端 guard 使用，但不进入 `catalog()` 或 `prompt_block()`；`scenario-composition/SKILL.md` 新增 `guard_scenario_save_intent` 与 `guard_scenario_save_subject`，`AgentConversationRunner` 不再维护 `SCENARIO_SAVE_INTENT_KEYWORDS` Python 短语表，保存正式场景 guard 的预检查从 Skill 私有 metadata 读取；新增回归覆盖私有 hints 不泄露、保存 guard 命中和报告保存不误触发。 |
| 2026-06-30 | 3.0.258-agent-skill-required-tool-routing | Agent 需要平台工具的静默规划路由继续 Skill 化：新增 `project-context/SKILL.md` 承接当前项目上下文、真实用例和实时平台事实读取；`scenario-composition` 与 `report-summary` 增加私有 `routing_requires_tool` hints，`AgentConversationRunner._intent_likely_requires_agent_tool()` 不再维护中央 `platform_keywords` 表，而是根据命中的 Skill 私有 routing hints 判断是否抑制实时自然语言 delta 并等待工具规划。新增回归覆盖项目上下文、报告摘要、场景草稿会进入工具路由，概念性测试问答和“场景测试是什么”不会误触发；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.259-agent-skill-tool-followup-rules | Agent query-first 必需工具规则继续 Codex 化：`scenario-composition/SKILL.md` 新增私有 `routing_required_tool_after_success`，声明 `testcase.query_project_cases` 成功且有候选用例后必须继续 `scenario.compose_draft`；`AgentConversationRunner` 删除场景专用 `_is_scenario_composition_intent` / `_latest_successful_project_case_query` / `_has_successful_scenario_compose` 分支，改为解析 Skill follow-up rule 并用通用 ToolCall 成功检查触发 `model.required_tool_missing(after_tool, required_tool)` 静默修复。同时 `ToolSpec` 新增后端私有 `required_successful_tool_before`、`missing_prerequisite_error_code` 和 `missing_prerequisite_next_action`，`scenario.compose_draft` 的执行前 query-first 校验从 spec 读取，不进入 `to_json()`、模型工具清单或前端契约；新增回归覆盖 ToolSpec 私有前置工具不泄露、follow-up rule 解析、直接 compose 阻断和 query 后漏 compose 自动修复。 |
| 2026-06-30 | 3.0.260-agent-skill-private-prompt-resources | Agent guard/classifier 提示词资源继续 Skill 化：`AgentSkillRegistry` 新增后端私有 `private_value()` 与 `private_resource_text()`，支持从 `SKILL.md` frontmatter 指向同目录私有资源文件；`scenario-composition` 将保存正式场景语义分类 prompt 从 `AgentConversationRunner` 常量迁移到 `save-intent-classifier.md`，Runner 只按 `guard_scenario_save_classifier_prompt` 读取资源并在缺失时安全降级为不短路。新增回归覆盖私有资源可读取、不会进入 `metadata()` / `prompt_block()`，以及保存 guard 仍使用 `requires_scenario_persistence` JSON 分类契约；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.261-agent-toolspec-repair-guidance | Agent 工具结果修复路径继续 ToolSpec 化：`ToolSpec` 新增后端私有 `tool_result_repair_guidance`，`scenario.compose_draft`、`ai_skill.run_draft`、`testcase.validate_schema` 和 `scenario.execute_dry_run` 的推荐修复路径从 `ToolResultPolicy` 的工具名分支迁入各自 ToolSpec；`ToolResultPolicy` 只负责读取 ToolRegistry 元数据和未知工具通用 fallback，避免新增工具时继续修改策略类。该字段不进入 `ToolSpec.to_json()`、模型初始工具清单或前端契约；新增回归覆盖 policy 从 ToolSpec 取 guidance、未知工具 fallback 和私有字段不泄露；同步接口契约、前端计划、技术架构和 Harness 文档；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.262-agent-skill-unsupported-capability-guard | Agent unsupported capability guard 继续 Skill 化：新增通用 `UnsupportedCapabilityGuard` 解析流程，`scenario-composition/SKILL.md` 通过后端私有 `guard_unsupported_capability` 声明保存正式场景 guard 的预检查关键词、缺失工具集合、分类 prompt、分类 JSON 字段、最终消息资源和 `completion_source`；`AgentConversationRunner` 删除保存场景专用 helper，改为解释命中 Skill 的私有 guard 规则，最终回复从 `unsupported-save-message.md` 读取。新增回归覆盖保存 guard 仍短路、否定保存不短路、报告保存不误触发、自定义 Skill 可声明同类 guard 且私有资源不进入 prompt；同步接口契约、前端计划、技术架构和 Harness 文档；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.263-agent-skill-followup-intent-scope | Agent Skill follow-up 路由收窄：`routing_required_tool_after_success` 支持后端私有 `intent_markers`，只有用户目标明确命中生成/创建/组合/执行场景等意图时，`testcase.query_project_cases` 成功后才强制静默修复为 `scenario.compose_draft`；纯项目上下文/资源盘点类问题即使提到“是否已有场景”并查询到用例，也允许模型直接给最终总结，避免误触发 `model.required_tool_missing`、错误进入 required-tool repair 并造成 run failed。新增回归覆盖 project context + case query 不强制 compose、真实场景生成仍保留 query-first 与 missing compose 修复；同步接口契约、技术架构和前端权威文档；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.264-agent-skill-platform-coverage | Agent Skill 平台功能覆盖继续扩展：新增 `http-test-case-design`、`websocket-test-case-design`、`execution-diagnosis`、`defect-triage` 与 `browser-capture-analysis` 五个 Codex-style Agent Skill，使 Harness Loop Agent 对 HTTP 用例设计/校验、WebSocket 长连接用例、执行失败诊断、缺陷草拟/分级和浏览器采集流量清洗/转用例具备独立领域流程与工具边界。HTTP/WebSocket 草稿生成通过现有 `ai_skill.run_draft` 指向正式 AI Skill 包；执行诊断优先复用 `report.read_summary` / `project.read_context`；缺陷与浏览器采集在缺少专用写入工具时只输出草稿或分析，不声称已保存。新增 Registry 覆盖断言和轻量解析验证；同步接口契约与技术架构；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.265-agent-skill-core-module-coverage | Agent Skill 核心模块覆盖继续扩展：新增 `environment-config-management`、`visual-flow-design`、`test-plan-management` 与 `project-permission-admin` 四个 Codex-style Agent Skill，使 Agent 对环境/变量、可视化 Flow DAG、测试计划/发布准入、项目成员/权限/403 诊断具备独立流程和边界。需要真实项目事实时优先复用 `project.read_context` / `report.read_summary`，缺少环境、Flow、测试计划或权限写入 ToolCall 时只给配置建议、设计评审或管理员操作清单，不声称已保存/授权/执行。新增 Registry 选择验证覆盖 13 个内置 Skill；同步接口契约与技术架构；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.266-agent-skill-asset-data-ops-coverage | Agent Skill 资产/数据/证据/运维覆盖继续扩展：新增 `api-definition-import`、`dataset-parameterization`、`media-evidence-management` 与 `agent-runtime-operations` 四个 Codex-style Agent Skill，使 Agent 对 OpenAPI/接口定义导入、数据集 records 参数化、MinIO/缺陷截图证据和 Agent Runtime readiness/runbook/SSE/worker 诊断具备独立流程和边界。接口定义与数据集缺少专用写入 ToolCall 时只输出导入/参数化建议，不声称已保存；媒体证据缺少上传/签名/绑定工具时只输出证据清单；Agent 运维问题区分模型/provider、工具规划、EventStore/SSE、前端 cursor 与 worker stale。新增 Registry 选择验证覆盖 17 个内置 Skill；同步接口契约与技术架构；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.267-agent-skill-cross-cutting-coverage | Agent Skill 横向平台能力覆盖继续扩展：新增 `security-auth-testing`、`mock-service-virtualization`、`ci-release-integration` 与 `report-archive-export` 四个 Codex-style Agent Skill，使 Agent 对鉴权/权限/安全负向测试、Mock/服务虚拟化、CI/CD 流水线/发布门禁、报告导出/归档/趋势/保留周期具备独立流程和边界。真实 token、权限、mock、流水线或报告归档事实必须通过现有工具证据确认；缺少写入或导出工具时只输出设计契约/操作建议，不声称已保存、创建、导出或归档。新增 Registry 选择验证覆盖 21 个内置 Skill；同步接口契约与技术架构；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.268-agent-skill-execution-quality-coverage | Agent Skill 执行质量与平台契约覆盖继续扩展：新增 `batch-execution-scheduling`、`assertion-extractor-binding`、`api-error-contract-debugging` 与 `ai-skill-runtime-governance` 四个 Codex-style Agent Skill，使 Agent 对批量执行/调度/队列/重试、断言/提取器/变量绑定、统一错误响应/request_id/前端错误展示、AI Skill Run/manifest/schema/模型输出修复具备独立流程和边界。真实队列、执行、响应样本、错误日志、AI draft 或 provider 状态必须通过工具或用户证据确认；缺少调度、保存、导出或写入工具时只输出契约和建议，不声称已应用。新增 Registry 选择验证覆盖 25 个内置 Skill；同步接口契约与技术架构；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.269-agent-skill-governance-coverage | Agent Skill 治理能力覆盖继续扩展：新增 `test-asset-lifecycle`、`notification-alerting-config`、`data-privacy-redaction` 与 `migration-compatibility-planning` 四个 Codex-style Agent Skill，使 Agent 对测试资产标签/目录/复制/删除/归档/依赖、通知/告警/SMTP/webhook、敏感数据/PII/token/日志/报告/AI prompt 脱敏、数据库迁移/API 兼容/历史数据/回滚规划具备独立流程和边界。真实资产依赖、通知配置、敏感泄露或迁移状态必须通过工具或用户证据确认；缺少写入、发送、删除或迁移执行工具时只输出契约和建议，不声称已应用。新增 Registry 选择验证覆盖 29 个内置 Skill；同步接口契约与技术架构；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.270-agent-required-followup-root-cause | Agent required follow-up 修复纳入 LoopController：当 Skill 私有 `routing_required_tool_after_success` 命中且模型在成功 `testcase.query_project_cases` 后提前输出自然语言、不继续调用 `scenario.compose_draft` 时，Runner 在 `model.required_tool_missing` 后绑定修复用 decision ContextBuild，写入 `loop.observed`，RootCause 为 `RC_REQUIRED_TOOL_FOLLOWUP_MISSING`、`next_action=repair`，再执行一次静默 required-tool repair。新增回归覆盖 observation、RootCause、mitigation 与 `after_tool/required_tool` 绑定；同步接口契约、技术架构和两份 Harness RootCause 治理契约；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.271-agent-max-iteration-root-cause | Agent max-iteration 停止纳入 LoopController：当工具闭环用满 `run.max_iterations` 后仍需生成最终总结时，Runner 在 `final_summary` 模型调用前绑定 stop 用 decision ContextBuild，写入 `loop.observed`，RootCause 为 `RC_MAX_ITERATIONS`、`next_action=stop`、`mitigation_action=human_review_or_extend_limit`，`observation_json` 记录 `max_iteration_guard`、迭代上限、当前迭代与已执行 ToolCall id。新增回归覆盖 observation、RootCause、mitigation 与事件顺序；同步接口契约、技术架构和两份 Harness 运行时契约；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.272-agent-repair-no-progress-root-cause | Agent repair no-progress 停止纳入 LoopController：当同一 run 内同一工具连续两次以相同 `error_code` 与 `error_message` 失败时，Runner 在第二次 `tool.result_observed` 后绑定 stop 用 decision ContextBuild，写入 `loop.observed`，RootCause 为 `RC_NO_PROGRESS_PURE`、`next_action=stop`、`mitigation_action=stop_or_escalate_repair_strategy`，随后以 `run.failed(error_code=agent_repair_no_progress)` 结束 run，避免无进展修复继续消耗模型与工具调用。新增回归覆盖 RED/GREEN、事件顺序、RootCause、mitigation 与正常 warning 修复不误伤；同步接口契约、技术架构和两份 Harness 运行时契约；无接口形状或迁移变化。 |
| 2026-06-30 | 3.0.273-agent-runtime-root-cause-metrics | Agent runtime RootCause 指标收口：`AgentMetricsService.snapshot` 新增 `tool_prerequisite_missing_total`、`tool_request_format_invalid_total`、`required_tool_followup_missing_total` 与 `max_iterations_total`，按 LoopObservation stop reason 聚合工具前置顺序纠错、工具请求格式修复、required follow-up 修复和迭代上限停止；dashboard `metrics_catalog_complete.required_metric_keys` 同步纳入这些 key，避免运行时纠错原因只存在于事件流和 `loop.observed` 详情。新增 RED/GREEN 回归覆盖 metrics snapshot 与 dashboard catalog，邻近 dashboard/root-cause 回归通过；同步前端契约、技术架构、Harness metrics catalog 与开发计划；无接口路由、数据模型或迁移变化。 |
| 2026-06-30 | 3.0.274-agent-runtime-loop-repair-runbook | Agent runtime loop repair Runbook 收口：新增 `agent_runtime_loop_repair` Runbook catalog，用于诊断 `tool_prerequisite_missing`、`tool_request_format_invalid`、`required_tool_followup_missing`、`max_iterations` 与 `same_failure_no_progress` 等由 Runner 写入的运行时修复/停止 LoopObservation；`diagnose_run` 会返回携带 `observation_id`、`stop_action_reason`、`root_cause_rule_id`、`root_cause_primary`、`mitigation_action` 的 recommendation，并指向 run-scoped loop observations 安全入口。新增 RED/GREEN 回归覆盖单 run 诊断建议，更新 `REQUIRED_RUNBOOKS`、Runbook diagnosis 机器契约、接口契约、技术架构和两份 Harness 文档；无接口路由、数据模型或迁移变化。 |
| 2026-06-30 | 3.0.275-agent-skill-decision-context-metadata | Agent Skill 决策上下文元数据收口：`ContextBuilder.build_metadata_json` 在保留 `policy_refs` 的同时新增 `selected_agent_skills` 与 `matched_agent_skill_routing_rules`，以 name/hash、routing_key、after_tool、required_tool、min_total_fields 和 rule_hash 记录本轮实际选中 Skill 与命中 routing rule 摘要，供 required-tool follow-up、LoopObservation 和 Runbook 解释静默修复来源；私有 frontmatter 原文、Skill 正文和 Skill-local 私有 prompt 资源仍不进入可读 payload。新增 RED/GREEN 回归覆盖 required follow-up repair ContextBuild 元数据；同步接口契约、技术架构和两份 Harness 文档；无接口路由、数据模型或迁移变化。 |
| 2026-06-30 | 3.0.276-agent-runtime-snapshot-decision-context-metadata | Agent RuntimeSnapshot 决策上下文元数据收口：`ContextBuilder.build_metadata_json` 新增 `runtime_snapshot` 摘要，记录 `snapshot_id`、`runtime_hash`、`tool_registry_hash`、`manifest_bundle_hash`、`prompt_bundle_hash`、`policy_version_hash`、`available_tool_names` 与 `tool_count`，让每个 decision ContextBuild 可追溯当时绑定的工具/策略版本，形态上更接近 openai/codex per-turn `TurnContext`。新增 RED/GREEN 回归覆盖 ContextBuild metadata 与 run 当前 snapshot hash 一致；同步接口契约、技术架构和两份 Harness 文档；无接口路由、数据模型或迁移变化。 |
| 2026-06-30 | 3.0.277-agent-permission-context-decision-metadata | Agent PermissionContext 决策上下文元数据收口：`ContextBuilder.build_metadata_json` 新增 `permission_context` 摘要，记录 `actor_user_id`、`project_id`、`access_level`、`project_access`、`implicit_all_project_permissions`、`explicit_permission_codes`、`explicit_permission_count` 与 `permission_hash`，让每个 decision ContextBuild 可追溯当时操作者的项目权限边界，形态上进一步对齐 openai/codex per-turn `approval_policy / permission_profile`。新增 RED/GREEN 回归覆盖普通项目成员 ContextBuild metadata 与显式权限码/hash 一致；同步接口契约、技术架构和两份 Harness 文档；无接口路由、数据模型或迁移变化。 |
| 2026-06-30 | 3.0.278-agent-tool-policy-context-envelope | Agent ToolPolicyContext envelope 收口：`AgentToolCall.policy_reason_json` 新增 `policy_context`，记录 policy version、tool name/version、base/resolved side effect、base/resolved replay policy、approval policy、approval reason、active/volatile/frozen policy evidence 计数、mixed evidence 标记与 `policy_hash`，让每个 ToolCall 可从统一 envelope 追溯审批和 replay policy 判定，形态上继续对齐 openai/codex per-turn tool/approval context。新增 RED/GREEN 回归覆盖 active volatile evidence 将 replay policy 提升为 `require_revalidation` 且 policy hash 与 envelope 一致；同步接口契约、技术架构和两份 Harness 文档；无接口路由、数据模型或迁移变化。 |
| 2026-06-30 | 3.0.279-agent-tool-execution-context-envelope | Agent ToolExecutionContext envelope 收口：ToolExecutor 在成功执行并提交 ToolCall 效果后，将 `policy_reason_json.execution_context` 写回账本，记录 execution context version、tool/run/runtime snapshot、worker、execution/effect state、backend contract/schema hash/effect capability、resolved side effect/replay policy、approval state/lineage/epoch/approved approval、input/output hash、recovery decision 与 `execution_context_hash`，让已执行 ToolCall 可从统一 envelope 追溯审批放行、后端契约和效果提交状态，形态上继续对齐 openai/codex `ToolCtx`/`ApprovalCtx`/sandbox attempt 的执行上下文分层。新增 RED/GREEN 回归覆盖已审批 ToolCall 执行后 envelope/hash 一致且不包含原始 input/output/evidence；同步接口契约、技术架构和两份 Harness 文档；无接口路由、数据模型或迁移变化。 |
| 2026-06-30 | 3.0.280-agent-tool-recovery-execution-context-envelope | Agent ToolRecoveryExecutionContext envelope 收口：`policy_reason_json.execution_context` 从成功执行扩展到 backend capability guard、审批/权限 guard、backend exception 和 eventstore failure recovery 等失败/阻断终态，新增 `tool_status`、`error_code` 与 `error_message_hash`，并在 capability 缺失、权限撤销、审批阻断、工具执行失败、effect 后 eventstore 失败时写入稳定 recovery decision。新增 RED/GREEN 回归覆盖 capability manual_intervention 与 backend failure 都写入 envelope/hash 且不包含原始 input/output/evidence/error message，同时更新成功路径 hash 规则；同步接口契约、技术架构和两份 Harness 文档；无接口路由、数据模型或迁移变化。 |
| 2026-06-30 | 3.0.281-agent-runbook-execution-context-summary | Agent Runbook execution context 摘要收口：`AgentRunbookService.diagnose_run` 在 `tool_call_uncertain` 与 `backend_capability_degraded` recommendation 的 `details.execution_context` 中附带 `policy_reason_json.execution_context` 的白名单摘要，覆盖 execution hash、worker、runtime snapshot、tool status、execution/effect state、backend contract/capability、resolved policy、approval lineage、input/output hash、recovery decision、error code 与 error message hash；明确不复制原始 input/output/evidence/error message。新增 RED/GREEN 回归覆盖 Runbook 诊断能消费 ToolCall execution context 且剔除原始 payload；同步接口契约、技术架构和两份 Harness 文档；无接口路由、数据模型或迁移变化。 |
| 2026-06-30 | 3.0.282-agent-completion-audit-execution-diagnostics | Agent Backend Completion Audit execution diagnostics 验收面收口：`AgentBackendCompletionAuditService.audit` 的 `runtime_contracts` 明确声明 ToolCall execution context 来源、Runbook execution context 白名单摘要来源和摘要字段，`diagnostics` 明确提供 ToolCall Detail 与 Runbook diagnosis 跳转入口，`observability_and_release_gate.details` 同步暴露摘要字段，便于交付验收从完成度审计追到完整执行诊断链。新增 RED/GREEN 回归覆盖 completion audit payload 与 Harness 文档 required contract 均包含 execution diagnostics 子键；同步接口契约、技术架构和两份 Harness 文档；无接口路由、数据模型或迁移变化。 |
