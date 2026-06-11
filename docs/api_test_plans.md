# 测试计划接口

测试计划绑定一个或多个 Scenario 版本，并在指定环境中手动、Cron 或 Webhook 触发。
基础路径为 `/api/v1`。成功响应统一为 `{code, message, data}`。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/test-plans?project_id={id}` | 分页查询、创建计划 |
| GET/PUT/DELETE | `/test-plans/{plan_id}?project_id={id}` | 详情、更新、软删除 |
| PUT | `/test-plans/{plan_id}/enabled?project_id={id}` | 启停计划 |
| POST | `/test-plans/{plan_id}/execute?project_id={id}` | 创建手动运行，返回 HTTP `202` |
| POST | `/test-plans/webhooks/{event}?project_id={id}` | Webhook 触发，返回 HTTP `202` |
| POST/GET | `/test-plans/import`、`/test-plans/export` | 导入、导出 |
| GET | `/test-plans/schedule?project_id={id}` | 查询未来调度实例 |
| GET/DELETE | `/test-plan-runs?project_id={id}` | 查询、软删除全部运行历史 |
| GET/DELETE | `/test-plan-runs/{run_id}?project_id={id}` | 运行详情、软删除单条历史 |

权限包括 `plan:view`、`plan:create`、`plan:update`、`plan:delete`、`plan:run` 和
`plan:history:delete`。执行目标时仍校验 `test:execute`。

## 请求 Schema

```json
{
  "name": "夜间回归",
  "enabled": true,
  "trigger_type": "cron",
  "cron_expression": "0 2 * * *",
  "schedule_timezone": "Asia/Shanghai",
  "environment_ids": [1],
  "targets": [
    {
      "reference_id": 11,
      "kind": "scenario",
      "sort_order": 1,
      "scenario_version": 3
    }
  ],
  "execution_mode": "serial",
  "failure_policy": "stop",
  "retry_count": 1,
  "timeout_minutes": 30,
  "notification_emails": ["qa@example.com"],
  "tags": ["regression"]
}
```

计划只绑定 Scenario，不直接绑定 HTTP、WebSocket 用例或 Flow。基础用例必须先组合为场景。

`scenario_version` 的规则：

- 创建计划时省略：绑定场景当前版本。
- 更新计划时省略：保留该目标原绑定版本。
- 显式传入：切换到指定的现存版本。
- 修改名称、通知、Cron 等非目标字段不会自动升级场景版本。

更新请求必须额外携带计划 `version`，冲突返回 HTTP `409`。

## 手动执行

```http
POST /api/v1/test-plans/8/execute?project_id=1
```

```json
{
  "environment_id": 2,
  "idempotency_key": "run-20260609-001"
}
```

环境必须属于当前项目、未删除，并且存在于计划的 `environment_ids`。接口创建 `pending`
运行后立即返回 HTTP `202`；客户端通过运行历史接口查询 `pending`、`running`、
`passed`、`failed` 或 `timeout` 状态。

幂等键作用域为项目且不自动过期。同键相同请求返回原运行；同键不同计划版本、环境、触发类型
或请求上下文返回 HTTP `409`。

## Cron 调度可靠性

调度器使用数据库持久化状态机：

```text
锁定到期计划
-> 在同一事务中创建唯一 pending 运行
-> 推进 next_run_at
-> 提交事务
-> 领取 pending 运行并标记 running/heartbeat_at
-> 执行并写入终态
```

进程在推进时间后崩溃不会丢失任务，因为 `pending` 运行已经持久化。调度器每轮同时恢复遗留
`pending` 和超过 `TEST_PLAN_RUN_STALE_SECONDS` 的 `running` 记录。确定性调度幂等键和数据库
唯一约束防止多实例重复创建。

## Webhook

Webhook 计划必须设置 `trigger_type=webhook`、`webhook_event` 和 `enabled=true`。

请求头：

```text
X-Webhook-Timestamp: 1780977600
X-Webhook-Signature: sha256=<hex hmac>
Idempotency-Key: delivery-unique-id
```

签名内容为：

```text
HMAC-SHA256(TEST_PLAN_WEBHOOK_SECRET, timestamp + "." + raw_request_body)
```

时间戳允许偏差由 `TEST_PLAN_WEBHOOK_MAX_AGE_SECONDS` 控制。所有合法接收事件写入
`test_plan_webhook_events`，记录请求摘要、幂等键和生成的运行 ID。同键不同请求体返回 `409`。

## 重试、超时和通知

- `retry_count`：目标失败后的额外重试次数。
- `timeout_minutes`：计划全局截止时间；场景在步骤边界检查截止时间，HTTP/WebSocket 单次请求
  使用剩余时间收紧自身超时。
- `notification_emails`：运行完成后发送邮件。SMTP 未配置时记录告警，不影响运行终态。
- `failure_policy=stop`：串行模式在首个非通过目标后停止。
- `execution_mode=parallel`：每个目标使用独立数据库会话执行。

## 删除与审计

计划和计划运行历史均为软删除。删除运行不会删除场景运行、步骤结果或 HTTP/WebSocket 原始
执行记录，审计关联通过外键保留。默认列表和详情不返回已软删除记录。

## 配置与升级

```env
TEST_PLAN_SCHEDULER_ENABLED=true
TEST_PLAN_SCHEDULER_INTERVAL_SECONDS=30
TEST_PLAN_RUN_STALE_SECONDS=3600
TEST_PLAN_DEFAULT_TIMEZONE=Asia/Shanghai
TEST_PLAN_WEBHOOK_SECRET=replace-with-a-random-secret
TEST_PLAN_WEBHOOK_MAX_AGE_SECONDS=300
SNAPSHOT_ENCRYPTION_KEY=replace-with-a-stable-random-secret
```

邮件配置使用 `SMTP_HOST`、`SMTP_PORT`、`SMTP_USERNAME`、`SMTP_PASSWORD`、
`SMTP_FROM_EMAIL` 和 `SMTP_USE_TLS`。

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```
