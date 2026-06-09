# 场景组合接口

场景组合负责把 HTTP/WebSocket 基础测试用例编排为有序业务场景。测试计划只能绑定场景，
不会直接绑定基础用例。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/api/v1/scenarios?project_id={id}` | 查询、创建场景 |
| GET/PUT/DELETE | `/api/v1/scenarios/{scenario_id}?project_id={id}` | 详情、更新、删除 |
| POST | `/api/v1/scenarios/{scenario_id}/execute?project_id={id}` | 执行场景 |
| GET | `/api/v1/scenario-runs?project_id={id}&scenario_id={id}` | 查询场景运行历史 |
| GET | `/api/v1/scenario-runs/{run_id}?project_id={id}` | 查询步骤执行详情 |

## 场景定义

后端兼容前端 `configText`、`variablesText`、`referenceId`、`continueOnFailure` 和
`environmentId` 字段，并在保存时解析 JSON 字符串。

```json
{
  "name": "登录下单场景",
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
    },
    {
      "id": "STEP-2",
      "kind": "delay",
      "name": "等待",
      "method": "",
      "path": "",
      "configText": "{\"delayMs\": 1000}",
      "continueOnFailure": false
    }
  ],
  "datasets": [
    {
      "id": "DATA-1",
      "name": "普通用户",
      "enabled": true,
      "variablesText": "{\"username\": \"tester\"}"
    }
  ]
}
```

保存时会校验环境和引用用例均属于当前项目。更新必须携带当前 `version`。
每个场景版本会保存完整基础用例快照；基础用例后续被编辑时，旧场景版本仍保持原执行定义。
对外场景详情只返回展示字段，不暴露完整用例快照。

## 数据驱动执行

执行请求：

```json
{
  "environmentId": 1,
  "datasetIds": ["DATA-1"],
  "idempotencyKey": "client-generated-key"
}
```

每个选中或启用数据集生成一条独立运行记录。若没有启用数据集，则使用第一条数据集；
完全没有数据集时使用空变量。

执行流程：

```text
读取不可变场景版本
→ 合并数据集变量
→ 按步骤顺序执行
→ 保存真实 HTTP/WebSocket 执行记录
→ 保存步骤输出和变量快照
→ 失败且 continueOnFailure=false 时将后续步骤标记为 skipped
```

配置中支持变量模板，例如 `{{username}}`、`{{step_1.body.token}}`。条件步骤使用受限表达式：

```json
{"expression": "variables[\"enabled\"] == True"}
```

## 数据关系

```text
test_scenarios
→ test_scenario_versions       不可变步骤和数据集定义
→ test_scenario_runs           每个数据集的一次运行
→ step_results.execution_id    关联 HTTP/WebSocket 原始执行记录

test_plans
→ test_plan_scenarios
→ test_scenarios
```

测试计划绑定时记录 `scenario_version_at_bind`，定时运行始终执行绑定版本。需要使用场景新版本时，
应重新保存测试计划。被有效测试计划引用的场景不能删除。

## 权限

- `scenario:view`：查看场景和运行历史。
- `scenario:manage`：创建、编辑和删除场景。
- `test:execute`：执行场景。
