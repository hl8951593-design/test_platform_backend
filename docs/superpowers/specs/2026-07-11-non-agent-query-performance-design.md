# 非 Agent 业务接口查询性能优化设计

## 1. 目标

本轮只优化非 Agent 业务接口的数据库查询、列表读取和批量写入性能。在不改变现有 HTTP 状态码、响应字段、字段顺序语义、权限校验、幂等行为和异步执行模型的前提下，降低数据库往返次数、避免列表误载未返回的大字段，并为高频排序查询补齐索引。

## 2. 范围

首批实现包含四项：

1. 场景运行历史列表避免加载未返回的 `scenario_snapshot`，并补齐项目级时间排序索引。
2. 测试计划列表合并重复统计 SQL，同时保留筛选分页和 `statistics` 响应结构。
3. 浏览器采集批量 upsert 删除逐条 `refresh`，改为一次提交后批量回查并恢复请求顺序。
4. 报告智能总览减少不必要的分页计数和重复区间读取。

同时新增 Alembic revision `0038_non_agent_query_performance_indexes`：

- `test_scenario_runs(project_id, started_at, id)`
- `browser_capture_entries(capture_id, id)`

## 3. 非目标

- 不查看或修改 Agent Runtime、Agent 路由、Agent 表和 Agent Skill。
- 不在本批次修改场景 SSE、执行 Future 等待、Worker 调度或外部 I/O 事务边界；这些属于下一批并发优化。
- 不删除列表响应字段，不改变默认分页大小，不要求前端同步修改。
- 不引入 Redis、Celery、新进程或新的部署组件。
- 不通过单纯扩大线程池或数据库连接池掩盖瓶颈。

## 4. 当前证据

- 场景运行表当前 186 行，三个主要 JSON 字段累计约 41.7 MB，单行最大约 746 KB。
- `GET /scenario-runs` 默认允许 200 行，并加载模型全部列；列表响应不包含 `scenario_snapshot`。
- 浏览器采集最重批次 40 行约 1 MB JSON；现有 100 条 upsert 实测产生 205 条 SQL。
- 测试计划空列表仍执行 6 条业务 SQL，真实数据库重复测量约 1.45 秒。
- 报告智能总览执行 8 条 SQL，真实数据库测量约 2.27 秒。
- 非 Agent 专项基线为 160 个测试通过。

## 5. 设计

### 5.1 场景运行历史

`ScenarioService.list_runs()` 保持返回 `TestScenarioRun` 实例，但查询增加 `defer(TestScenarioRun.scenario_snapshot)`。`ScenarioRunRead` 当前不读取该字段，因此响应保持不变；详情接口继续加载完整行。

新增组合索引支持以下现有查询：

```sql
WHERE project_id = ?
ORDER BY started_at DESC, id DESC
LIMIT ?, ?
```

当指定 `scenario_id` 时继续使用现有 `(project_id, scenario_id, started_at)` 索引。

### 5.2 测试计划列表统计

列表项查询和筛选总数保持原样。全项目统计改为一个聚合语句，通过 `count` 和 `sum(case(...))` 同时取得：

- `total`
- `enabled`
- `scheduled`

`recent_failed` 作为标量子查询合并进同一个统计语句。没有筛选条件时，分页 `total` 直接复用统计结果；存在关键字、启用状态或触发类型筛选时，保留单独的筛选 count。

### 5.3 浏览器采集批量 upsert

继续先按 `client_entry_id` 一次性读取已有记录。完成新增和更新后：

1. `flush()` 取得所有新增主键。
2. 单次 `commit()`。
3. 按结果主键执行一次批量回查。
4. 使用主键映射恢复请求中的原始顺序。

单条成功/失败语义、字段值和返回顺序不变。目标是 SQL 数量不随批量条数线性增加。

### 5.4 报告智能总览

新增不计算分页总数的内部摘要读取方法。智能总览不需要 `total`，因此不再为当前区间和上一周期分别执行 count。

最新参考时间改为专用 `MAX(started_at)` 聚合，不再调用 `list_reports(page_size=1)`。当前区间和上一周期合并为一次扩大时间窗的摘要查询，再在 Python 中按时间切分。慢用例和缺陷风险查询保持独立，避免改变统计口径。

## 6. 错误与兼容行为

- 数据库异常继续沿用统一异常处理器。
- 所有公开 Schema、路由参数、状态码和消息文本保持不变。
- 索引 migration 只新增索引，不修改列和数据。
- 批量 upsert 仍为单事务；提交失败时整体回滚，与当前行为一致。

## 7. 测试策略

先增加失败测试，再实现：

1. 场景列表 SQL 不选择 `scenario_snapshot`，详情仍包含完整快照。
2. 场景列表查询计划可使用新的项目时间索引，migration upgrade/downgrade 对称。
3. 测试计划统计字段与旧结果一致，且无筛选列表 SQL 数量有固定上限。
4. 浏览器 upsert 分别覆盖新增、更新、混合和顺序保持；100 条输入的 SELECT 数保持常数级。
5. 报告智能总览字段与统计值不变，且不调用带 count 的分页路径。
6. 执行全部非 Agent 专项测试以及完整仓库测试。

## 8. 验收门槛

- 非 Agent 专项测试全部通过。
- 完整仓库测试全部通过。
- `GET /scenario-runs` 的公开响应结构不变，列表 SQL 不再读取 `scenario_snapshot`。
- 测试计划无筛选列表的业务 SQL 从 6 条降至不超过 3 条。
- 100 条浏览器采集 upsert 的 SQL 数从 205 条降至不超过 10 条。
- 报告智能总览 SQL 从 8 条降至不超过 5 条。
- `alembic heads` 只有 `0038_non_agent_query_performance_indexes` 一个 head，upgrade/downgrade 可执行。

## 9. 回滚

- 代码回滚后继续使用原查询和逐条刷新逻辑，不涉及数据格式转换。
- migration downgrade 仅删除新增的两个索引。
- 因公开接口没有变化，回滚不需要前端配合。
