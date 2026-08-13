# 非 Agent 业务接口与数据库性能筛查（2026-07-17）

## 范围与方法

- 本轮按要求排除全部 `/api/v1/agents/**` 路由和 Agent Runtime，共筛查 209 个非 Agent 业务路由。
- 证据来自 FastAPI 路由清单、14,295 条非 Agent 请求日志、SQLAlchemy 语句计数、真实 MySQL 8.0.36 只读复测、`EXPLAIN ANALYZE`、模型/迁移索引核对和静态循环查询扫描。
- 线上日志时间包含远程数据库网络、连接池等待、并发轮询和外部 Provider 等因素；服务层复测用于区分 SQL 形状问题与基础设施抖动。

## 主要慢接口与根因

| 接口/路径 | 筛查现象 | 根因 | 处理 |
| --- | --- | --- | --- |
| `GET /scenarios` | 当日样本 P50 约 163 秒；服务层 20 条列表 44 次 SQL、约 2.7 秒 | 每条场景分别读取当前版本和环境，形成 `2N` 查询 | 当前版本和环境改为一次关联读取，响应字段、排序、分页和缺失版本错误语义不变 |
| `GET /execution-center/logs` | 历史 P95 约 37 秒；服务层约 784 毫秒 | 事件查询同时加载 `test_scenario_runs` 的大型场景、变量和步骤 JSON | 只投影 run ID 与时间字段；事件、游标、消息和 worker 映射不变 |
| `GET /dashboard/project-asset-trends` | 服务层至少 10 次 SQL，且 GET 会写入/提交当天快照 | 六类计数逐条查询，读取路径承担读模型写入 | 六类计数合并为一次 SQL；GET 使用内存中的当天实时点，持久化只由快照调度器负责 |
| `GET /ui-executions` | 高频轮询；仓储层 4 次 SQL | 总数、列表、状态分组、交付失败数分开读取 | 窗口总数与列表同查，四类 facet 使用一次条件聚合 |
| `GET /ui-executions/available` | Desktop 高频轮询 | 总数与列表重复扫描同一候选集 | 窗口总数合并到单次候选查询 |
| Desktop token 鉴权/heartbeat | 每次鉴权 3 次 SQL | credential、device、owner 分开加载 | credential -> device -> owner 使用一次 eager join；撤销、过期、owner active 校验不变 |
| `GET /execution-center/workers`、队列 | 设备数或 UI 队列项增大时线性增加 SQL | 每个 Desktop/每个 UI 记录再查活动任务或设备 | 活动 UI 执行按设备批量读取；统一执行投影直接带出 worker public ID |
| 场景保存/更新校验 | 304 节点场景会按节点读取用例 | 用例和数据库连接在循环内查询 | HTTP、WebSocket 用例及环境数据库连接分别批量读取 |
| Flow 校验与执行快照 | 用例节点按节点查询，校验后生成快照时重复查询 | 缺少批量资产读取 | HTTP/WebSocket 用例和环境改为固定批量查询 |

经典 AI Provider 调用和浏览器分析接口的外部推理耗时不属于数据库查询优化范围；本轮没有把外部 Provider 延迟伪装成数据库问题。

## 真实 MySQL 优化后复测

同一远程数据库、同一项目、每项 3 次只读调用，中位数如下：

| 服务操作 | 优化前 | 优化后 |
| --- | --- | --- |
| 场景列表 20 条 | 44 SQL，约 2.7 秒 | 2 SQL，约 138 毫秒 |
| 执行中心日志 100 条 | 3 SQL，约 784 毫秒 | 1 SQL，约 51 毫秒 |
| Dashboard 7 天资产趋势 | 至少 10 SQL，读事务会尝试写入 | 5 SQL，约 145 毫秒，无写入 |
| UI 执行列表 200 条（仓储层） | 4 SQL | 2 SQL，约 74 毫秒 |
| Desktop 可领取执行 100 条（仓储层） | 2 SQL | 1 SQL，约 56 毫秒 |
| 304 节点场景定义校验 | 随节点线性增长，至少 305 SQL | 2 SQL，约 714 毫秒 |

耗时是当前工作站到远程 MySQL 的样本，不作为跨环境 SLA；SQL 次数和响应语义回归才是稳定验收边界。

## 数据库筛查结论

- 当前 schema migration 为 `0050_ui_execution_patch_requests`，MySQL 为 8.0.36。
- 所有业务表均有主键；外键列未发现缺少左前缀索引的情况。场景运行、执行事件、UI 执行和 Dashboard 快照的当前热点查询均能使用既有索引。
- `execution-center/logs` 的 `EXPLAIN ANALYZE` 服务端执行约 0.6 毫秒，慢点来自不必要的大 JSON 传输和 ORM 解码，因此没有新增索引。
- 实例级历史计数显示连接中断、全表 join 和磁盘临时表曾较高，但这些是共享实例累计值，`performance_schema` 当前关闭，不能直接归因到本项目。
- 存在若干冗余/重复索引候选，但表规模当前有限，且缺少写放大与命中率证据。本轮不做批量删索引，避免无证据变更影响写入或其他查询计划。
- 慢查询日志已开启但 `mysql.slow_log` 当前无本项目样本；建议生产环境开启 `performance_schema` 并按 digest、锁等待、临时表和连接错误建立持续观测。

## 兼容性与验证边界

- 没有新增或修改公共路由、请求/响应字段、权限、分页、排序、幂等、状态机或迁移。
- Dashboard GET 不再提交内部写事务；当天返回值仍使用同一实时计数，历史持久化继续由 300 秒快照调度器维护。
- 性能回归覆盖固定 SQL 上限、大字段不进入列表/日志查询、Dashboard GET 无写入，以及原有业务契约。
- 已运行排除文件名含 `agent` 的非 Agent 回归集，共 359 项全部通过；相关 Python 模块编译检查、差异空白检查和 Alembic `current == head == 0050` 均通过。
