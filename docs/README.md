# 项目文档索引与维护规范

本文档是后端文档入口，用于帮助开发者和 AI 快速找到当前实现的权威说明，并约束代码、
数据库、接口契约和开发计划同步演进。

## 当前基线

| 项目 | 当前值 |
| --- | --- |
| 最近核对日期 | 2026-06-17 |
| 开发基线 | 2.8 |
| Alembic head | `0018_defects` |
| 回归命令 | `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` |
| 最近完整回归 | 101 项通过 |

数字基线只能在实际执行命令后更新。数据库结构以 Alembic migration 和当前模型共同为准，
不能只修改模型而遗漏迁移。

## 文档分工

| 文档 | 权威范围 |
| --- | --- |
| [技术架构](technical_architecture.md) | 分层、模块关系、执行模型、基础设施和演进边界 |
| [场景执行图谱](scenario_execution_graph.md) | 场景触发、dataset record 展开、步骤执行、变量链路、状态和持久化关系 |
| [开发进度与计划](development_technical_notes.md) | 当前完成度、风险、优先级、迁移基线和验收计划 |
| [统一错误响应](api_errors.md) | HTTP 错误 envelope、字段定位、500 request ID 和 OpenAPI 契约 |
| [统一执行记录](api_execution_records.md) | HTTP、WebSocket、场景和 Flow 执行历史的公共列表与详情契约 |
| [测试报告](api_test_reports.md) | 测试计划和 Flow 的报告历史、结构化指标、明细与 HTML 导出 |
| [缺陷跟踪](api_defects.md) | 项目缺陷 CRUD、富文本清洗、状态流转和权限契约 |
| `api_*.md` | 已实现接口、请求响应、权限、错误、兼容规则和部署要求 |
| `front_tech_docs/` | 前端接入、页面交互和客户端状态管理约定 |
| `alembic/versions/` | 数据库结构变更及升级顺序 |
| `tests/` | 可执行行为证据和回归边界 |

发生冲突时，应先核对路由、Schema、Service、Model、migration 和测试，再修正文档。规划中的
能力必须明确标记为“计划中”，不能与已实现接口混写。

## 接口文档

- [认证](api_auth.md)
- [统一错误响应](api_errors.md)
- [统一执行记录](api_execution_records.md)
- [测试报告](api_test_reports.md)
- [缺陷跟踪](api_defects.md)
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
