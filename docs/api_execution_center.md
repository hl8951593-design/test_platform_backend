# 执行中心接口文档

本文档说明执行中心页面使用的实时读模型接口。接口基础路径为：

```text
http://127.0.0.1:8000/api/v1
```

## 设计边界

- 执行中心接口是页面聚合读模型，复用统一执行记录、场景运行事件和当前执行工作池配置。
- 不新增执行总表，不复制历史执行数据，不改变 HTTP、WebSocket、场景和 Flow 的执行链路。
- 查询权限为项目 `report:view`；管理员和项目创建者自动具备该权限。
- 当前后端没有独立持久化业务 Worker heartbeat 表，`/workers` 的 Worker 总数来自执行工作池配置，忙碌状态由运行中/重试中执行记录派生。
- 重试、停止、暂停和恢复等控制类接口需要可靠调度器/持久化队列承接，当前文档只声明已实现的读接口。

## 执行中心总览

| 项目 | 内容 |
| --- | --- |
| 接口 | `/execution-center/overview?project_id={project_id}&environment_id={environment_id}` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | `report:view` |
| 说明 | 用于顶部摘要和指标卡；`environment_id` 可选 |

响应字段：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "queue_total": 4,
    "running_count": 1,
    "queued_count": 1,
    "failed_blocking_count": 1,
    "retrying_count": 1,
    "worker_online": 8,
    "worker_total": 8,
    "worker_health_rate": 100,
    "avg_duration_ms": 120000,
    "avg_wait_seconds": 38,
    "ai_diagnosis_count": 1,
    "auto_fixable_count": 1,
    "refresh_interval_seconds": 15
  }
}
```

## 实时执行队列

| 项目 | 内容 |
| --- | --- |
| 接口 | `/execution-center/queue?project_id={project_id}&environment_id={environment_id}&page=1&page_size=10` |
| 方法 | `GET` |
| 权限 | `report:view` |
| 说明 | 基于统一执行记录返回队列展示行；`environment_id` 可选 |

状态值：

| 值 | 说明 |
| --- | --- |
| `queued` | 排队中 |
| `running` | 运行中 |
| `retrying` | 重试中 |
| `passed` | 通过 |
| `failed` | 失败 |
| `cancelled` | 已取消 |
| `paused` | 已暂停 |

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "id": "RUN-1428",
        "execution_type": "scenario",
        "execution_id": 1428,
        "name": "企业信息全链路回归",
        "trigger": "测试计划",
        "trigger_type": "plan",
        "priority": "P1",
        "status": "running",
        "worker_id": "execution-worker-05",
        "progress": 50,
        "eta_seconds": 300,
        "eta_text": "预计 5m 后完成",
        "attempt": 1,
        "max_attempts": 3,
        "started_at": "2026-07-08 14:28:15",
        "updated_at": "2026-07-08 14:28:15"
      }
    ],
    "total": 4,
    "page": 1,
    "page_size": 10
  }
}
```

## Worker 状态

| 项目 | 内容 |
| --- | --- |
| 接口 | `/execution-center/workers?project_id={project_id}` |
| 方法 | `GET` |
| 权限 | `report:view` |
| 说明 | 返回当前执行工作池派生的 Worker 视图 |

Worker 状态：

| 值 | 说明 |
| --- | --- |
| `idle` | 空闲 |
| `busy` | 忙碌 |

## 实时日志

| 项目 | 内容 |
| --- | --- |
| 接口 | `/execution-center/logs?project_id={project_id}&after_sequence=0&limit=100` |
| 方法 | `GET` |
| 权限 | `report:view` |
| 说明 | 当前读取场景运行事件表，使用事件表主键作为全局递增 `sequence` |

响应字段：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "sequence": 101,
        "time": "14:28:15",
        "level": "info",
        "message": "worker assigned",
        "run_id": "RUN-1428",
        "worker_id": "execution-worker-05",
        "created_at": "2026-07-08 14:28:15"
      }
    ],
    "next_after_sequence": 101
  }
}
```

## AI 失败诊断

| 项目 | 内容 |
| --- | --- |
| 接口 | `/execution-center/failure-diagnosis?project_id={project_id}` |
| 方法 | `GET` |
| 权限 | `report:view` |
| 说明 | 由失败执行记录生成诊断展示卡片 |

当前诊断为规则化摘要，不会调用外部模型；后续可接入 AI 根因分析服务并保持字段兼容。

## 重试池

| 项目 | 内容 |
| --- | --- |
| 接口 | `/execution-center/retries?project_id={project_id}` |
| 方法 | `GET` |
| 权限 | `report:view` |
| 说明 | 返回状态为 `retrying` 的执行记录 |

## 最近执行记录

页面底部“最近执行记录”继续使用已有接口：

```http
GET /api/v1/execution-records?project_id=1&page=1&page_size=20
```

详情继续使用：

```http
GET /api/v1/execution-records/{execution_type}/{execution_id}?project_id=1
```
