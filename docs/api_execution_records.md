# 统一执行记录接口文档

本文档说明执行中心对 HTTP、WebSocket、场景组合、可视化 Flow 和 Desktop UI 执行历史的统一只读查询契约。
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
- HTTP 与 WebSocket 执行记录会保留业务触发来源：人工点击/接口执行写入 `trigger_source=manual`，Agent 工具执行写入 `trigger_source=agent`，并记录 `agent_run_id`、`agent_tool_call_id` 与 `trigger_tool_name`。统一执行中心如需展示“人工执行/AI 执行”来源，应优先读取协议专属 `detail` 中这些字段；列表公共摘要仍保持既有 `trigger_type` 兼容形态。

支持的 `execution_type`：

| 值 | 数据来源 |
| --- | --- |
| `http` | `test_case_executions` |
| `websocket` | `websocket_test_case_executions` |
| `scenario` | `test_scenario_runs` |
| `flow` | `visual_flow_executions` |
| `ui` | `ui_executions`；创建、活动状态、步骤、终态、诊断和产物均持续投影 |

## 查询统一执行记录

| 项目 | 内容 |
| --- | --- |
| 接口 | `/execution-records?project_id={project_id}` |
| 方法 | `GET` |
| 认证 | `Authorization: Bearer <access_token>` |
| 权限 | `report:view` |
| 说明 | 跨五类执行记录按开始时间倒序分页 |

查询参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `project_id` | 必填 | 项目 ID |
| `execution_type` | 空 | `http`、`websocket`、`scenario`、`flow`、`ui` |
| `status` | 空 | 公共状态筛选；`running` 匹配 `queued/pending/claimed/launching/running`，`paused` 匹配 `paused/waiting_user`，`passed` 匹配 `passed/assisted`，`failed` 匹配 `failed/lost/error/timeout` |
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
持久化 `finished_at`，因此返回 `null`。Flow 耗时根据 `started_at` 和 `finished_at` 计算。UI queued 记录以
`created_at` 作为统一开始排序时间；claim/事件/complete 会持续写入真实 `started_at/finished_at/duration_ms` 与公共状态投影。

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
| UI | `public_id`、delivery/attention、不可变 case/environment 快照、runtime policy、lease/步骤计数、`steps`、`runtime_patches`、`commands`、`artifacts` 和错误摘要；快照不含环境 secret value |

资源被删除后，执行记录仍可查询，但 `resource_name` 可能为 `null`。找不到指定项目内的记录时
返回 HTTP `404`。

## 兼容性和迁移

- 原 HTTP、WebSocket、场景和 Flow 执行接口保持不变。
- UI 执行创建入口为 `/ui-test-cases/{case_id}/execute`；专用 claim/lease/events/complete、SSE、本地运行导入和产物接口均已开放。
- 原执行详情接口继续可用，统一接口是新增只读入口。
- 公共执行详情仍读取原业务表；可重建诊断读模型由 Alembic `0041_execution_diagnostic_read_models` 管理。
- 统一列表使用 SQL `UNION ALL` 在数据库内完成筛选、计数、排序和分页。

## 大规模执行诊断与 Agent 渐进读取

生产环境中的执行记录、场景步骤和响应正文可能达到万级或更大规模。公共 REST 完整详情仍保持原契约；Agent 不再把完整执行 JSON 直接放入模型上下文，而是通过统一诊断投影逐层读取。

### 列表分页

`GET /execution-records` 保留默认的 `pagination_mode=page`，其 `page/page_size/total` 返回结构不变。新客户端可显式使用 `pagination_mode=cursor`：

| 参数 | 默认值 | 约束与语义 |
| --- | --- | --- |
| `cursor` | 空 | 上一页返回的不可解释游标，最大 512 字符 |
| `limit` | `50` | 1 至 200 |
| `include_total` | `false` | 仅为 `true` 时执行精确计数 |

游标顺序固定为 `started_at DESC, execution_type ASC, execution_id DESC`。响应包含 `items/returned/limit/has_more/next_cursor/total`；默认不计数时 `total=null`。游标非法或过长返回 HTTP `422`。项目、状态、环境、触发用户、时间范围和关键字过滤在两种分页模式中保持一致。

### Agent 查询视图

`execution.query_records` 的 `result_view` 支持：

- `records`：默认值，返回记录列表，可选择 page 或 cursor 分页；
- `failure_clusters`：必须传 `started_from/started_to`，按稳定的 `failure_signature` 聚类，只返回计数、不同资源数、首末时间和最多 5 个代表执行引用；
- `metrics`：必须传时间范围，返回小时或日级执行量与耗时汇总。跨度达到 7 天时使用日粒度。

聚类和指标视图默认 `limit=20`，不返回原始请求、响应或步骤正文，并携带最新索引源时间 `watermark`。

### 诊断详情视图

`execution.read_detail` 支持 `summary/failures/steps/step/artifact/full`：

| 视图 | 用途 |
| --- | --- |
| `summary` | 状态、步骤计数、首个失败步骤和失败签名 |
| `failures` | 失败优先的有界步骤证据 |
| `steps` | 有界步骤列表与 continuation |
| `step` | 单一步骤；必须且只能传一个 `selector.step_ids` |
| `artifact` | 按 `selector.artifact_ref/offset/max_bytes` 读取一段外置证据 |
| `full` | 诊断投影的兼容视图，仍受模型预算约束，不等同于公共 REST 原始详情 |

默认模型预算为 12,000 字符，硬上限 24,000。统一 envelope 字段为 `schema_version/projection_version/resource_ref/view/data/evidence_refs/omissions/page/diagnostic_complete/recommended_next_views`。任何未返回内容必须通过 `omissions`、`next_cursor` 或 `artifact_ref` 显式说明，禁止静默截断。

外置证据先统一脱敏，再以确定性 JSON、gzip 和 SHA-256 保存。单段默认 8 KiB，最大 64 KiB；服务在每次读取时校验项目、执行身份、压缩内容和哈希。跨项目或跨执行引用按不存在处理。Agent 只能分块读取；只有通过 `report:view` 权限校验的公共完整详情兼容路径可以恢复完整 artifact。

### 存储与迁移

Alembic revision `0041_execution_diagnostic_read_models` 新增统一执行索引、步骤诊断、payload artifact、小时指标和日指标表。HTTP、WebSocket、场景和 Flow 在原事务内写投影，不增加提交点，也不改变 worker、重试、执行状态、审批或 SSE 语义。`0048_ui_execution_runtime` 的 UI 创建、事件和终态在同一事务持续维护索引与步骤诊断；`0049_ui_execution_artifact_delivery` 把 MinIO UI 产物登记到统一 payload artifact 并提供详情元数据。

`0044_execution_artifact_mediumblob` 将 MySQL 的 artifact `content` 从 64 KiB 上限的 `BLOB` 扩容为 `MEDIUMBLOB`。证据仍先脱敏、确定性 JSON 编码并 gzip 压缩，读取仍受 64 KiB 单段上限约束；扩容只保证较大的压缩证据可以完整持久化，不改变接口返回或分块读取语义。

历史回填：

```powershell
.venv\Scripts\python.exe scripts/backfill_execution_diagnostics.py --project-id 1 --execution-type scenario --batch-size 500
```

场景回滚前恢复引用式旧快照：

```powershell
.venv\Scripts\python.exe scripts/backfill_execution_diagnostics.py --project-id 1 --execution-type scenario --batch-size 500 --restore-legacy-snapshots
```
