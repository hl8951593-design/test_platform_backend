# 统一执行记录接口文档

本文档说明执行中心对 HTTP、WebSocket、场景组合和可视化 Flow 执行历史的统一只读查询契约。
基础路径为：

```text
http://127.0.0.1:8000/api/v1
```

## 设计边界

- 统一接口只聚合现有执行表，不复制、不迁移、不改写历史记录。
- 列表返回稳定公共字段，详情在 `detail` 中保留协议专属快照和日志。
- 查询需要项目 `report:view` 权限；管理员和项目创建者自动具备该权限。
- 复合展示 ID 格式为 `{execution_type}:{execution_id}`，例如 `scenario:21`。
- 数据库主键仍使用各执行表原有整数 ID，详情路由分别传递类型和整数 ID。

支持的 `execution_type`：

| 值 | 数据来源 |
| --- | --- |
| `http` | `test_case_executions` |
| `websocket` | `websocket_test_case_executions` |
| `scenario` | `test_scenario_runs` |
| `flow` | `visual_flow_executions` |

## 查询统一执行记录

| 项目 | 内容 |
| --- | --- |
| 接口 | `/execution-records?project_id={project_id}` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | `report:view` |
| 说明 | 跨四类执行记录按开始时间倒序分页 |

查询参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `project_id` | 必填 | 项目 ID |
| `execution_type` | 空 | `http`、`websocket`、`scenario`、`flow` |
| `status` | 空 | 精确匹配执行状态 |
| `environment_id` | 空 | 环境 ID |
| `trigger_user_id` | 空 | 执行或触发用户 ID |
| `started_from` | 空 | ISO 8601 开始时间下界 |
| `started_to` | 空 | ISO 8601 开始时间上界 |
| `keyword` | 空 | 按当前资源名称模糊匹配 |
| `page` | `1` | 页码，从 1 开始 |
| `page_size` | `20` | 每页数量，最大 200 |

`started_from` 晚于 `started_to` 时返回 HTTP `400`。

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "id": "scenario:21",
        "execution_type": "scenario",
        "execution_id": 21,
        "project_id": 1,
        "resource_id": 4,
        "resource_name": "Order lifecycle",
        "environment_id": 2,
        "scenario_run_id": null,
        "status": "passed",
        "trigger_type": "manual",
        "trigger_user_id": 9,
        "duration_ms": 1000,
        "error_message": null,
        "dataset_id": "DATA-1",
        "dataset_name": "Customers",
        "record_id": "RECORD-1",
        "record_name": "VIP customer",
        "started_at": "2026-06-15 10:00:00",
        "finished_at": "2026-06-15 10:00:01",
        "created_at": "2026-06-15 10:00:00"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
  }
}
```

HTTP 和 WebSocket 执行没有独立 `started_at` 字段，统一接口使用其 `created_at`。它们没有
持久化 `finished_at`，因此返回 `null`。Flow 耗时根据 `started_at` 和 `finished_at` 计算。

## 查询统一执行详情

| 项目 | 内容 |
| --- | --- |
| 接口 | `/execution-records/{execution_type}/{execution_id}?project_id={project_id}` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | `report:view` |
| 说明 | 返回统一 `summary` 和协议专属 `detail` |

详情结构：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "summary": {},
    "detail": {}
  }
}
```

协议专属内容：

| 类型 | `detail` 关键字段 |
| --- | --- |
| HTTP | `request_snapshot`、`response_snapshot`、`assertion_results`、`attempt_history` |
| WebSocket | `session_snapshot`、`response_snapshot`、`assertion_results`、`attempt_history` |
| 场景 | `scenario_snapshot`、`variables_snapshot`、`step_results`、`events`、dataset record 身份 |
| Flow | `context_snapshot`、`node_executions`；节点保留请求、输出、错误、attempt 和时间 |

资源被删除后，执行记录仍可查询，但 `resource_name` 可能为 `null`。找不到指定项目内的记录时
返回 HTTP `404`。

## 兼容性和迁移

- 原 HTTP、WebSocket、场景和 Flow 执行接口保持不变。
- 原执行详情接口继续可用，统一接口是新增只读入口。
- 本功能不新增表或字段；当前全局 Alembic head 以 [文档索引与维护规范](README.md) 为准。
- 统一列表使用 SQL `UNION ALL` 在数据库内完成筛选、计数、排序和分页。
