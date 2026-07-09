# 通知中心接口契约

状态：已实现
最后核验：2026-07-09

通知中心接口用于顶栏铃铛和通知下拉面板。当前通知列表是读模型：后端从未关闭缺陷、场景运行、测试计划运行等已有事实派生通知项；单条/批量已读状态持久化到 `notification_read_states`。

## 数据模型

```json
{
  "notification_id": "defect:12",
  "title": "缺陷待处理",
  "message": "鉴权变量失效（open）",
  "source": "缺陷中心",
  "severity": "danger",
  "type": "alert",
  "unread": true,
  "occurred_at": "2026-07-08 23:00:00",
  "action_label": "查看缺陷"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `notification_id` | string | 稳定通知 ID，格式如 `defect:{id}`、`scenario-run:{id}`、`plan-run:{id}` |
| `title` | string | 通知标题 |
| `message` | string | 通知摘要 |
| `source` | string | 来源模块 |
| `severity` | string | `info`、`success`、`warning`、`danger` |
| `type` | string | `alert`、`run`、`approval`、`system` |
| `unread` | boolean | 当前用户在当前项目下是否未读 |
| `occurred_at` | datetime | 通知发生时间 |
| `action_label` | string/null | 前端可选操作文案 |

## 查询通知

```http
GET /api/v1/notifications?project_id=1&unread_only=false&type=alert
Authorization: Bearer <access_token>
```

查询参数：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `project_id` | number | 否 | 传入时只查该项目；不传时聚合当前用户可见项目 |
| `unread_only` | boolean | 否 | 是否只返回未读通知 |
| `type` | string | 否 | 通知类型筛选 |

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "notification_id": "scenario-run:1428",
      "title": "场景执行失败",
      "message": "企业信息全链路回归 当前状态：failed",
      "source": "执行中心",
      "severity": "danger",
      "type": "run",
      "unread": true,
      "occurred_at": "2026-07-08 23:00:00",
      "action_label": "查看执行"
    }
  ]
}
```

权限：需要当前用户可访问对应项目；不传 `project_id` 时仅返回当前用户可见项目的数据。

性能约束：

- 通知列表是轻量读模型，缺陷、场景运行和测试计划运行来源只投影列表展示所需列，不得在列表查询中加载 `content_html`、`scenario_snapshot`、`variables_snapshot`、`step_results`、`plan_snapshot`、`target_results` 等大字段。
- 已读状态按当前响应候选 `notification_id[]` 一次性批量读取，不允许按通知逐条查询 `notification_read_states`。
- 该 GET 接口接入后端 10 秒短 TTL 读穿透缓存，缓存 key 包含 DB bind、用户、项目、`unread_only` 和 `type`；单条/全部标记已读会立即清理通知缓存。

## 标记单条已读

```http
POST /api/v1/notifications/{notification_id}/read
Authorization: Bearer <access_token>
```

可选查询参数：`project_id`。不传时后端会根据 `notification_id` 反查项目并校验权限。

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "updated": 1
  }
}
```

## 标记全部已读

```http
POST /api/v1/notifications/read-all?project_id=1
Authorization: Bearer <access_token>
```

`project_id` 可选。传入时只标记该项目当前读模型里的通知；不传时标记当前用户可见项目中的通知。

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "updated": 3
  }
}
```

## 当前通知来源

| 来源 | 通知 ID | 类型 | 未读规则 |
| --- | --- | --- | --- |
| 未关闭缺陷 | `defect:{id}` | `alert` | 默认未读 |
| 失败/运行中/排队中/重试中的场景运行 | `scenario-run:{id}` | `run` | 失败默认未读，运行态默认已读 |
| 已结束测试计划运行 | `plan-run:{id}` | `run` | 失败默认未读，通过默认已读 |

## 持久化

- 已读状态表：`notification_read_states`
- 唯一约束：`user_id + project_id + notification_id`
- 迁移：`0033_notification_read_states`
- 删除项目时会同步删除该项目下的通知已读状态。
