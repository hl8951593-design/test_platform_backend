# 场景组合接口

场景将 HTTP/WebSocket 基础用例、等待和条件步骤编排为可版本化的业务流程。基础路径为
`/api/v1`，接口使用 Bearer Token，成功响应统一为 `{code, message, data}`。

## 接口

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET/POST | `/scenarios?project_id={id}` | `scenario:view` / `scenario:manage` | 分页查询、创建场景 |
| GET/PUT/DELETE | `/scenarios/{scenario_id}?project_id={id}` | `scenario:view` / `scenario:manage` | 详情、更新、软删除 |
| POST | `/scenarios/{scenario_id}/execute?project_id={id}` | `test:execute` | 同步执行场景 |
| GET | `/scenario-runs?project_id={id}&scenario_id={id}` | `scenario:view` | 最近 200 条运行 |
| GET | `/scenario-runs/{run_id}?project_id={id}` | `scenario:view` | 运行和步骤详情 |

请求字段同时接受 snake_case 和文档注明的 camelCase 别名；响应统一使用 snake_case。
列表响应结构为 `{items, total, page, page_size}`，`page_size` 最大为 200。

## 场景定义与版本

```json
{
  "name": "登录下单",
  "environmentId": 1,
  "tags": ["P0"],
  "steps": [
    {
      "id": "STEP-1",
      "kind": "api_case",
      "referenceId": 11,
      "name": "登录",
      "method": "POST",
      "path": "/login",
      "configText": "{}",
      "continueOnFailure": false
    }
  ],
  "datasets": [
    {
      "id": "DATA-1",
      "name": "普通用户",
      "enabled": true,
      "variablesText": "{\"username\":\"tester\"}"
    }
  ]
}
```

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

## 环境与幂等

执行环境必须属于当前项目且未删除。没有传执行环境时使用场景绑定环境。

幂等键作用域为当前项目，当前实现不自动过期。每个数据集派生独立键。同一键和相同请求返回
原运行；同一键对应不同场景版本、环境、数据集或计划运行时返回 HTTP `409`。

## 状态与审计

场景运行状态包括 `running`、`passed`、`failed`、`timeout`。步骤还可能为 `skipped`。
关联链如下：

```text
test_plan_runs
  -> test_scenario_runs.plan_run_id
     -> test_case_executions.scenario_run_id
     -> websocket_test_case_executions.scenario_run_id
```

场景快照和变量快照对敏感字段进行掩码。场景版本中的 Authorization、Cookie、Token、
Password、Secret、API Key 等字段使用 `SNAPSHOT_ENCRYPTION_KEY` 加密保存；未配置时使用
`JWT_SECRET_KEY` 派生密钥。生产环境必须配置独立且稳定的加密密钥。

## 错误响应

HTTP 和参数校验错误统一返回：

```json
{
  "code": 409,
  "message": "幂等键已用于不同的场景执行请求",
  "data": "幂等键已用于不同的场景执行请求"
}
```
