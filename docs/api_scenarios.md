# 场景组合接口

场景将 HTTP/WebSocket 基础用例、等待和条件步骤编排为可版本化的业务流程。基础路径为
`/api/v1`，接口使用 Bearer Token。除 SSE 事件流外，成功响应统一使用
`{code, message, data}`，包括 HTTP 202 异步启动响应。

## 接口

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET/POST | `/scenarios?project_id={id}` | `scenario:view` / `scenario:manage` | 分页查询、创建场景 |
| GET/PUT/DELETE | `/scenarios/{scenario_id}?project_id={id}` | `scenario:view` / `scenario:manage` | 详情、更新、删除；被测试计划引用时拒绝删除 |
| POST | `/scenarios/{scenario_id}/execute?project_id={id}` | `test:execute` | 异步启动场景，返回 HTTP 202 |
| GET | `/scenario-runs?project_id={id}&scenario_id={id}` | `scenario:view` | 分页查询运行，`page_size` 最大 200 |
| GET/DELETE | `/scenario-runs/{run_id}?project_id={id}` | `scenario:view` / `scenario:manage` | 运行和步骤详情、删除调试记录 |
| GET | `/scenario-runs/{run_id}/events?project_id={id}` | `scenario:view` | SSE 实时事件和历史重放 |

请求字段同时接受 snake_case 和文档注明的 camelCase 别名；响应统一使用 snake_case。
列表响应结构为 `{items, total, page, page_size}`，`page_size` 最大为 200。

## 场景定义与版本

```json
{
  "name": "登录下单",
  "environmentId": 1,
  "tags": ["P0"],
  "nodes": [
    {
      "id": "NODE-1",
      "name": "登录",
      "beforeActions": [
        {
          "id": "ACTION-1",
          "kind": "fixed_value",
          "name": "设置租户",
          "config": {"output": "tenant_id", "value": 1001},
          "continueOnFailure": false
        }
      ],
      "testCase": {
        "id": "STEP-1",
        "kind": "api_case",
        "referenceId": 11,
        "name": "登录",
        "method": "POST",
        "path": "/login",
        "config": {},
        "continueOnFailure": false
      },
      "afterActions": [
        {
          "id": "ACTION-2",
          "kind": "delay",
          "name": "等待状态稳定",
          "config": {"duration_ms": 1000},
          "continueOnFailure": true
        }
      ]
    }
  ],
  "datasets": [
    {
      "id": "DATA-1",
      "name": "普通用户",
      "enabled": true,
      "variablesText": "{\"username\":\"tester\"}",
      "records": [
        {
          "id": "RECORD-1",
          "name": "VIP customer",
          "enabled": true,
          "request_overrides": [
            {
              "step_id": "STEP-CREATE-ORDER",
              "target": "body",
              "path": "order.customer.profile.level",
              "value": "VIP"
            },
            {
              "step_id": "STEP-CREATE-ORDER",
              "target": "query_params",
              "path": "dry_run",
              "value": false
            }
          ]
        },
        {
          "id": "RECORD-2",
          "name": "Blocked customer",
          "enabled": true,
          "request_overrides": [
            {
              "step_id": "STEP-CREATE-ORDER",
              "target": "body",
              "path": "order.customer.profile.level",
              "value": "BLOCKED"
            }
          ]
        }
      ]
    }
  ]
}
```

### 节点与绑定动作

`nodes[]` 是唯一编排结构。每个节点必须且只能包含一个 `test_case`，主用例仅允许
`api_case` 或 `websocket_case`；`before_actions[]` 和 `after_actions[]` 允许
`condition`、`delay`、`random`、`fixed_value`、`script`。后端拒绝旧的
`steps`、`execution_phase`、`executionPhase` 和 `phase`。

- 节点按数组顺序执行，节点内部固定为 `before_actions -> test_case -> after_actions`。
- 前置动作失败且 `continue_on_failure=false` 时，跳过本节点剩余前置动作和主用例，仍执行全部后置动作。
- 主用例失败后仍执行本节点全部后置动作；单个后置动作失败不会阻止后续后置动作。
- 失败仍如实计入 run 终态；`continue_on_failure` 只控制是否继续，不会改写失败结果。

动作配置：`delay.duration_ms` 为非负整数；`random.type` 支持 `integer`、`string`、
`uuid`；`fixed_value.value` 保留 JSON 原始类型；`script.language` 支持 `python`、
`javascript`。脚本在独立受限子进程执行，只暴露声明的 `inputs`，只回收声明的 `outputs`，
并限制语言、语法、超时、输入输出大小及子进程资源。随机和固定值使用 `config.output` 写入变量，
脚本使用 `config.outputs`。

这是破坏性升级。迁移 `0020_migrate_scenarios_to_nodes.py` 先按旧阶段规则稳定排序：首个
主用例前的动作绑定到首节点前置，用例之间的动作绑定到下一节点前置，末尾动作绑定到末节点
后置。这样旧的 `case -> condition -> case` 会保持执行和失败阻断语义。无法保持全局 teardown
或停止边界的定义仍会阻断升级；运行时不双读、不双写、不猜测。

更新请求必须携带当前 `version`。版本冲突返回 HTTP `409` 和 `current_version`。
每次更新生成不可变的 `test_scenario_versions` 记录。场景版本保存基础用例执行快照，
后续修改基础用例不会改变旧版本。

## 数据集选择

执行请求：

```json
{
  "environmentId": 1,
  "datasetIds": ["DATA-1"],
  "idempotencyKey": "client-generated-key"
}
```

规则是确定的：

- 未传 `datasetIds`：执行全部 `enabled=true` 的数据集。
- 传入非空数组：只执行指定数据集，允许显式选择已停用数据集。
- 传入空数组：不执行任何数据集，返回空运行列表。
- 场景完全没有数据集且未传 `datasetIds`：以空变量执行一次。
- 指定不存在的数据集：返回 HTTP `400`。

## 数据驱动请求覆盖

数据集通过 `records` 描述完整测试输入。默认选择数据集时，dataset 和 record 均启用才会
执行；显式 `datasetIds` 仍可选择已停用数据集，但选中数据集内只执行 `enabled=true` 的
record。每条 record 生成一个独立场景 run。record 的 `request_overrides` 只修改该次运行
的步骤请求副本，不会修改场景版本保存的步骤快照。

支持的 target：

- `path`：替换完整请求路径，`path` 字段必须为空字符串。
- `headers`：按 `path` 指定的请求头名称覆盖值。
- `query_params`：按 `path` 指定的查询参数名称覆盖值，仅 API 步骤支持。
- `body`：覆盖嵌套 JSON 字段，仅 API 步骤支持；支持点路径和数组索引，
  例如 `orders[0].items[2].sku`。

`value` 保留 JSON 类型，包括字符串、数字、布尔值、`null`、对象和数组。执行时先复制
步骤请求并应用 override，再解析数据集变量、上游步骤变量和环境变量，因此 override 的
value 也可以包含 `{{variable}}` 模板。

保存或执行时遇到无效 record 或 override 返回 HTTP `400`。错误数据包含
`dataset_id`、`record_id`、`step_id`、`target` 和 `path`，用于前端定位字段。
以下情况会被拒绝：

- record 缺少 `id` 或 `name`，或同一 dataset 内 record ID 重复。
- `step_id` 不属于当前场景版本。
- target 不受步骤类型支持。
- body 路径不存在、穿过标量，或数组索引无效。
- `target=path` 但字段路径非空。
- 同一 record 存在相同 `step_id + target + path`。

完整覆盖顺序见 [场景数据驱动契约](scenario-data-driven-contract.md)。

兼容规则：

- 旧的 dataset-level `request_overrides` 会兼容读取并迁移为 record。
- 旧 override 的 `values` 数组按索引展开为多条 record；单个 `value` 生成一条 record。
- 数组请求值必须直接放在 `value` 中，例如 `"value": [1, 2]`，不会被拆成多条 record。
- 新的保存结果和详情响应统一使用 `records`。

## 环境与幂等

执行环境必须属于当前项目且未删除。没有传执行环境时使用场景绑定环境。

手工异步执行的幂等键作用域为当前项目，当前实现不自动过期。同一键和相同场景版本、
环境及数据集选择返回原 execution 和全部 run；同一键用于不同请求时返回 HTTP `409`。
测试计划内部按每个数据集和 record 派生 run 幂等键。

## 状态与审计

execution 和场景运行状态包括 `queued`、`running`、`passed`、`failed`、`timeout`；
步骤包括 `pending`、`running`、`passed`、`failed`、`timeout`、`skipped`。
关联链如下：

```text
test_scenario_executions
  -> test_scenario_runs.execution_id
     -> test_scenario_run_events.run_id
test_plan_runs
  -> test_scenario_runs.plan_run_id
     -> test_case_executions.scenario_run_id
     -> websocket_test_case_executions.scenario_run_id
```

场景快照和变量快照对已识别的敏感字段进行掩码。场景版本请求快照中的 Authorization、
Cookie、Token、Password、Secret、API Key 等字段使用 `SNAPSHOT_ENCRYPTION_KEY` 加密保存；
未配置时使用 `JWT_SECRET_KEY` 派生密钥。生产环境必须配置独立且稳定的加密密钥。

`request_overrides[].value` 是通用 JSON 字段，当前不会根据 override 的 header/path 名称
自动判断是否需要字段级加密。敏感覆盖值应使用模板引用环境密钥，不应把密钥明文直接写入
record。运行详情中的最终请求仍按实际请求字段执行脱敏。

## 错误响应

业务校验错误返回 HTTP `400` 或 `409`；Pydantic 请求结构校验返回 HTTP `422`。错误体均使用：

```json
{
  "code": 409,
  "message": "幂等键已用于不同的场景执行请求",
  "data": "幂等键已用于不同的场景执行请求"
}
```

同一项目内场景名称唯一。创建或重命名为已存在名称时返回 HTTP `409`，`message` 和
`data` 为“同一项目下场景名称不能重复”；数据库唯一键在 flush 或 commit 阶段发生竞态时
也转换为同一业务响应，不返回 500。

结构化 `data` 会保留 record 和 override 字段定位信息。完整公共规则见
[统一错误响应契约](api_errors.md)。

## 实时执行

`POST /scenarios/{scenario_id}/execute?project_id={id}` 现在返回 HTTP `202`。
响应不再等待场景执行结束，而是直接返回 `execution_id`、场景版本以及每个数据集
record 对应的 `run_id`、`events_url` 和 `detail_url`。同一个 `idempotency_key` 会返回原
execution 和 run，不会重复启动任务。

响应示例（外层统一响应中的 `data`）：

```json
{
  "execution_id": "550e8400-e29b-41d4-a716-446655440000",
  "scenario_id": 12,
  "scenario_version": 9,
  "status": "queued",
  "created_at": "2026-06-12T08:00:00.000Z",
  "runs": [
    {
      "run_id": 301,
      "dataset_id": "DATA-1",
      "dataset_name": "普通用户",
      "record_id": "RECORD-1",
      "record_name": "VIP customer",
      "status": "queued",
      "events_url": "/api/v1/scenario-runs/301/events?project_id=1",
      "detail_url": "/api/v1/scenario-runs/301?project_id=1"
    }
  ]
}
```

前端通过以下接口订阅单个 run：

```http
GET /scenario-runs/{run_id}/events?project_id={id}
Accept: text/event-stream
Last-Event-ID: 12
```

响应头包含：

```http
Content-Type: text/event-stream
Cache-Control: no-cache, no-transform
Connection: keep-alive
X-Accel-Buffering: no
```

事件已在发送前持久化，`sequence` 在单个 run 内严格递增。支持的事件为
`run_queued`、`run_started`、`step_started`、`step_completed`、
`step_failed`、`step_skipped`、`transition_started`、`run_completed`
、`run_failed` 和 `heartbeat`。断线重连时服务端重放所有大于
`Last-Event-ID` 的事件。客户端应使用 `run_id + sequence` 去重。

`GET /scenario-runs/{run_id}` 在执行期间仍可查询，并返回 `current_step_id`、
`current_step_index`、`last_event_sequence` 以及包含 pending/running 状态的
`step_results`。完整请求、响应、断言、变量提取和绑定信息仍以该详情接口为准。
事件、详情和变量追踪字段分别见 [运行事件契约](scenario-run-events-contract.md)、
[运行详情契约](scenario-run-detail-contract.md) 和
[变量追踪契约](scenario-variable-tracing-contract.md)。

## 数据表与迁移

实时执行由迁移 `0015_add_scenario_realtime_events.py` 引入；record 运行身份由
`0016_add_scenario_run_records.py` 引入；破坏性节点定义迁移由
`0020_migrate_scenarios_to_nodes.py` 引入：

| 表/字段 | 用途 |
| --- | --- |
| `test_scenario_executions` | 一次启动请求及其幂等、场景版本和总状态 |
| `test_scenario_runs.execution_id` | 将数据集 run 归入同一次 execution |
| `test_scenario_runs.record_id/name` | 标识同一数据集内产生该 run 的 record |
| `test_scenario_runs.current_step_id/index` | 运行中快照 |
| `test_scenario_runs.last_event_sequence` | 最近持久化事件序号 |
| `test_scenario_run_events` | SSE 历史、重放和心跳 |

部署新代码前必须执行：

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

可使用以下命令验证：

```powershell
.\.venv\Scripts\python.exe -m alembic current
```

场景执行至少依赖 `0020_scenario_nodes`，当前全局 head 以 [文档索引与维护规范](README.md) 为准。如果未完成 0015/0016，启动执行时会出现
`Table '...test_scenario_executions' doesn't exist` 或缺少 `record_id`、`record_name`
字段的数据库错误；如果 0020 遇到不能可靠迁移的旧定义会主动中止，必须先人工转换或清理。

## 当前限制

- 后台执行当前使用 FastAPI `BackgroundTasks`，任务记录已持久化，但 API 进程异常退出后
  不会自动被其他实例领取。
- 尚未提供取消接口、手工重试、失败步骤恢复和项目级并发限制。
- 事件当前随运行详情保留，尚未实现事件归档、过期清理和
  `EVENT_HISTORY_EXPIRED` 响应。
- SSE 不发送完整请求或响应正文；大字段必须从运行详情和关联用例执行记录读取。
