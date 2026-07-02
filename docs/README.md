# 项目文档索引与维护规范

本文档是后端文档入口，用于帮助开发者和 AI 快速找到当前实现的权威说明，并约束代码、
数据库、接口契约和开发计划同步演进。

## 当前基线

| 项目 | 当前值 |
| --- | --- |
| 最近核对日期 | 2026-07-01 |
| 开发基线 | `3.0.474-agent-observability-dashboard-performance` |
| Alembic head | `0028_agent_memory_staleness_events` |
| 回归命令 | `.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v` |
| 最近完整回归 | 本轮未重跑全量后端 discover；已执行 `.\.venv\Scripts\python.exe -m unittest tests.test_agent_runtime.AgentRuntimeTests`，通过；Windows 本地日志 rollover 仍有既有文件占用告警 |

数字基线只能在实际执行命令后更新。数据库结构以 Alembic migration 和当前模型共同为准，
不能只修改模型而遗漏迁移。

## 文档收敛规则

当前文档已经分散到后端 `docs/`、后端 `front_tech_docs/`、前端 `docs/` 和前端 `api_docs/`。后续维护按以下唯一权威收敛：

| 范围 | 唯一权威 | 说明 |
| --- | --- | --- |
| 后端架构、数据模型、迁移、执行模型 | 本仓库 `docs/technical_architecture.md`、`docs/development_technical_notes.md` | 记录后端当前实现和开发基线 |
| 后端 API 契约 | 本仓库 `docs/api_*.md` 和 `docs/api_agent_frontend_contract.md` | 前端仓库 `api_docs/` 只是联调镜像或便捷副本 |
| 前端当前实现 | `C:\Users\Administrator\PycharmProjects\devtestplatform\docs/` | 前端页面、状态管理、视觉交互和测试基线以该目录为准 |
| Agent 前端原型/专项计划 | 已合并进前端 `docs/agent-runtime-frontend-architecture.md` 与 `docs/frontend-development-plan.md` | 旧 `agent-codex-prototype`、`agent-frontend-development-plan` 只保留为历史入口 |
| 后端 `front_tech_docs/` | 历史快照 | 不再作为前端当前实现的权威来源，新增或修正前端行为时更新前端仓库 |

后续如果发现两个文档描述同一事实，应优先把事实合并到对应唯一权威文档，旧文档改成跳转说明，而不是继续复制整段内容。

## 最高优先级工程约束：后端异步与非阻塞

本平台不是个人单机工具，后续预计会有约 50 人并发使用。所有后端设计和代码变更都必须把
“避免阻塞其他用户和其他功能流程”作为高优先级约束。

- 新增执行类、AI 调用、外部 HTTP/WebSocket 调试、文件/对象存储、批量处理、报告生成等可能耗时的功能时，不得默认在普通 API 请求生命周期内同步等待完整流程结束。
- 能返回任务身份的场景应优先采用 `202 Accepted + execution/run/task id + 状态查询或事件流`，由后台任务或 Worker 执行。
- 已存在的同步链路如果继续保留，必须明确适用边界、超时、并发影响和后续异步化计划。
- 在 `async def` 路由或异步服务中禁止直接调用会长时间阻塞事件循环的同步 I/O、CPU 密集逻辑或无限等待；无法异步化的依赖必须隔离到线程池、进程、任务队列或专用 Worker。
- 任何重试、轮询、批量执行和长连接能力都必须配置超时、退避、并发上限和资源保护，避免一个用户的任务拖慢整个平台。

## 文档分工

| 文档 | 权威范围 |
| --- | --- |
| [技术架构](technical_architecture.md) | 分层、模块关系、执行模型、基础设施和演进边界 |
| [场景执行图谱](scenario_execution_graph.md) | 场景触发、dataset record 展开、步骤执行、变量链路、状态和持久化关系 |
| [场景数据驱动契约](scenario-data-driven-contract.md) | record 展开、请求覆盖与兼容读取规则 |
| [场景运行事件契约](scenario-run-events-contract.md) | SSE 顺序、重连、事件类型与校准边界 |
| [场景运行详情契约](scenario-run-detail-contract.md) | run 身份、步骤结果、快照和运行中字段 |
| [场景变量追踪契约](scenario-variable-tracing-contract.md) | 变量来源、动作写入、绑定与脱敏 |
| [开发进度与计划](development_technical_notes.md) | 当前完成度、风险、优先级、迁移基线和验收计划 |
| [后端日志与排查](logging.md) | request_id、请求日志、执行队列和 AI JSON 修复日志定位 |
| [统一错误响应](api_errors.md) | HTTP 错误 envelope、字段定位、500 request ID 和 OpenAPI 契约 |
| [统一执行记录](api_execution_records.md) | HTTP、WebSocket、场景和 Flow 执行历史的公共列表与详情契约 |
| [测试报告](api_test_reports.md) | 测试计划和 Flow 的报告历史、结构化指标、明细与 HTML 导出 |
| [缺陷跟踪](api_defects.md) | 项目缺陷 CRUD、富文本清洗、状态流转和权限契约 |
| [媒体存储](api_media.md) | MinIO 图片上传、附件绑定、临时访问地址和清理契约 |
| [Agent 前端接口契约](api_agent_frontend_contract.md) | Harness Loop Agent 前端接入接口、SSE、字段契约和限制 |
| `api_*.md` | 已实现接口、请求响应、权限、错误、兼容规则和部署要求 |
| `front_tech_docs/` | 历史前端接入快照；当前前端实现以 `devtestplatform/docs/` 为准 |
| `alembic/versions/` | 数据库结构变更及升级顺序 |
| `tests/` | 可执行行为证据和回归边界 |

发生冲突时，应先核对路由、Schema、Service、Model、migration 和测试，再修正文档。规划中的
能力必须明确标记为“计划中”，不能与已实现接口混写。

## 接口文档

- [认证](api_auth.md)
- [后端日志与排查](logging.md)
- [统一错误响应](api_errors.md)
- [统一执行记录](api_execution_records.md)
- [测试报告](api_test_reports.md)
- [缺陷跟踪](api_defects.md)
- [媒体存储](api_media.md)
- [项目权限](api_project_permissions.md)
- [环境配置](api_environment_configs.md)
- [HTTP 测试用例](api_test_cases.md)
- [WebSocket 测试用例](api_websocket_test_cases.md)
- [场景组合与实时执行](api_scenarios.md)
- [场景组合执行流程图谱](scenario_execution_graph.md)
- [测试计划](api_test_plans.md)
- [可视化流程](api_visual_flows.md)
- [浏览器采集](api_browser_captures.md)
- [AI 能力](api_ai.md)
- [Agent 前端接口契约](api_agent_frontend_contract.md)

## 变更维护契约

完成代码变更前必须逐项判断：

1. 接口字段、状态码、权限或兼容行为变化时，更新对应 `api_*.md`。
2. 跨模块执行顺序、数据关系或基础设施变化时，更新技术架构。
3. 模块状态、风险、开发优先级或测试基线变化时，更新开发进度与计划。
4. 新增表、字段、索引或约束时，创建 Alembic migration，执行 `alembic upgrade head`，
   并在相关 API 文档和开发计划中记录 migration revision。
5. 修改持久化 JSON 结构时，写明旧数据读取、新写入格式和回滚风险。
6. 文档示例必须使用当前响应字段，明确 snake_case/camelCase、同步/异步和 HTTP 状态码。
7. 完成后全局搜索旧术语、旧 migration、旧测试数量和已废弃字段，避免局部更新。

## 场景数据驱动检查点

当前场景数据驱动的执行单位是 dataset record，不是 dataset 本身。每条启用 record 产生一个
独立 run；request override 先应用到请求副本，再解析模板和变量。数据结构与校验细节以
[场景组合接口文档](api_scenarios.md) 为准，测试计划展开语义以
[测试计划接口文档](api_test_plans.md) 为准。
