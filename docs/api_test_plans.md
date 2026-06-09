# 测试计划接口

基础路径：`/api/v1`。所有接口需要 Bearer Token，并使用统一 `{code, message, data}` 响应。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/test-plans?project_id={id}` | 分页查询、新建计划 |
| GET/PUT/DELETE | `/test-plans/{plan_id}?project_id={id}` | 详情、更新、软删除 |
| PUT | `/test-plans/{plan_id}/enabled?project_id={id}` | 启停计划 |
| POST | `/test-plans/{plan_id}/execute?project_id={id}` | 真实手动执行 |
| POST/GET | `/test-plans/import`、`/test-plans/export` | 导入、导出 |
| GET | `/test-plans/schedule?project_id={id}` | 查询时间范围内的真实 Cron 调度实例 |
| GET/DELETE | `/test-plan-runs?project_id={id}` | 查询、清空运行历史 |
| GET/DELETE | `/test-plan-runs/{run_id}?project_id={id}` | 运行详情、删除记录 |

测试计划只绑定已经组合、校验通过的 Scenario，不直接绑定 HTTP 或 WebSocket 基础用例。
基础用例应先在场景组合模块中完成顺序、条件、数据集和步骤失败策略设计。

创建请求中的 `environment_ids` 和 `targets` 均不能为空。目标使用：

```json
{"reference_id": 11, "kind": "scenario", "sort_order": 1}
```

Cron 计划必须提供合法五字段表达式和 IANA 时区：

```json
{
  "trigger_type": "cron",
  "cron_expression": "0 2 * * *",
  "schedule_timezone": "Asia/Shanghai",
  "enabled": true
}
```

计划保存时会校验 Scenario 属于当前项目，并维护：

- `test_plan_scenarios`：计划与自动化场景的真实绑定关系。
- `test_plan_environments`：计划与执行环境的真实绑定关系。
- `targets`、`environment_ids`：用于接口展示和运行快照。

更新请求必须额外传入当前 `version`。版本不一致返回 `409`。

手动执行请求：

```json
{"environment_id": 1, "idempotency_key": "client-generated-key"}
```

执行会保存计划快照和逐场景结果；串行模式支持失败停止，并行模式使用独立数据库会话并发执行。

## 定时执行

应用启动时会启动测试计划调度线程，每隔 `TEST_PLAN_SCHEDULER_INTERVAL_SECONDS` 秒检查到期计划：

```text
查询 enabled Cron 计划
→ 使用数据库行锁领取到期计划
→ 先推进 next_run_at，避免多进程重复领取
→ 对计划绑定的每个环境执行全部绑定 Scenario
→ 保存 trigger=schedule、scheduled_at 的计划运行和场景执行记录
```

调度配置：

```env
TEST_PLAN_SCHEDULER_ENABLED=true
TEST_PLAN_SCHEDULER_INTERVAL_SECONDS=30
TEST_PLAN_DEFAULT_TIMEZONE=Asia/Shanghai
```

`GET /test-plans/schedule` 默认返回未来 14 天调度实例，也支持通过 `start_at` 和 `end_at`
查询最多 90 天范围。

## 权限

使用 `plan:view`、`plan:create`、`plan:update`、`plan:delete`、`plan:run` 和
`plan:history:delete`。执行目标时仍会重复校验原有 `test:execute` 权限。

## 数据库升级

```bash
.venv/bin/python -m alembic upgrade head
```
