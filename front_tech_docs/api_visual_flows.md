# 可视化编排后端接口与数据结构契约

本文档是可视化编排后端开发的建议实现契约。前端对应实现位于 `src/api/flows.ts` 和 `src/pages/FlowPage.tsx`。

机器可读结构定义见 `api_docs/visual_flow_schema.json`。JSON Schema 用于基础字段校验；跨节点引用、DAG、权限和可执行性仍需业务校验。

## 1. 通用约定

- 基础路径：`/api/v1`
- 认证：`Authorization: Bearer <access_token>`
- 所有查询和写入必须按 `project_id` 做数据权限隔离。
- JSON 响应统一使用：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

- 时间字段使用 ISO 8601 UTC。
- 流程定义使用 camelCase，数据库字段可使用 snake_case。
- 执行必须绑定不可变流程版本快照，不能直接读取持续变化的当前定义。

## 2. 完整流程定义

```json
{
  "schemaVersion": "1.0",
  "id": 12,
  "projectId": 1,
  "environmentId": 3,
  "name": "下单主链路",
  "description": "登录后创建订单",
  "nodes": [
    {
      "id": "node-login",
      "kind": "api_case",
      "name": "用户登录",
      "referenceId": 101,
      "method": "POST",
      "path": "/api/login",
      "position": { "x": 80, "y": 120 },
      "config": {
        "description": "",
        "continueOnFailure": false,
        "inputBindings": [],
        "outputPaths": [
          "response.body.data.token",
          "response.status"
        ]
      }
    },
    {
      "id": "node-order",
      "kind": "api_case",
      "name": "创建订单",
      "referenceId": 102,
      "method": "POST",
      "path": "/api/orders",
      "position": { "x": 350, "y": 120 },
      "config": {
        "continueOnFailure": false,
        "inputBindings": [
          {
            "id": "binding-token",
            "target": "headers.Authorization",
            "sourceNodeId": "node-login",
            "sourcePath": "response.body.data.token",
            "fallback": ""
          }
        ],
        "outputPaths": [
          "response.body.data.order_id"
        ]
      }
    }
  ],
  "edges": [
    {
      "id": "edge-login-order",
      "source": "node-login",
      "target": "node-order",
      "route": "success"
    }
  ],
  "viewport": {
    "zoom": 1
  },
  "updatedAt": "2026-06-07T09:00:00.000Z"
}
```

`id`、`updatedAt` 是持久化元数据。创建流程时可为空；后端应以 URL 和数据库记录为准，不信任请求体中的 `id`、`projectId`、`updatedAt`。

## 3. 数据字段

### 3.1 FlowDefinition

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `schemaVersion` | `"1.0"` | 是 | 数据结构版本 |
| `id` | string/number | 否 | 流程 ID，创建时忽略 |
| `projectId` | number | 是 | 项目 ID，后端必须与查询参数一致 |
| `environmentId` | number | 否 | 默认执行环境 |
| `name` | string | 是 | 流程名称 |
| `description` | string | 是 | 流程说明 |
| `nodes` | FlowNode[] | 是 | 节点列表 |
| `edges` | FlowEdge[] | 是 | 连线列表 |
| `viewport.zoom` | number | 是 | 前端画布缩放，范围 0.6 至 1.4 |
| `updatedAt` | string | 否 | 前端显示用途，后端生成 |

### 3.2 FlowNode

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 是 | 流程版本内唯一节点 ID |
| `kind` | enum | 是 | 节点类型 |
| `name` | string | 是 | 节点显示名称 |
| `referenceId` | string/number | 接口节点必填 | 引用测试用例 ID |
| `method` | string | 否 | 方法快照，仅用于展示 |
| `path` | string | 否 | 路径快照，仅用于展示 |
| `position.x/y` | number | 是 | 画布位置，不参与执行 |
| `config` | FlowNodeConfig | 是 | 节点运行配置 |

节点类型：

| kind | 运行语义 |
| --- | --- |
| `start` | 唯一流程入口，不执行请求 |
| `end` | 流程终点，不执行请求 |
| `api_case` | 按 `referenceId` 执行 HTTP 测试用例 |
| `websocket_case` | 按 `referenceId` 执行 WebSocket 测试用例 |
| `condition` | 计算 `config.condition`，结果必须标准化为 boolean |
| `delay` | 等待 `config.delayMs` 毫秒 |

### 3.3 FlowNodeConfig

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `description` | string | 节点说明 |
| `condition` | string | 条件表达式，仅 condition 使用 |
| `delayMs` | number | 等待毫秒数，仅 delay 使用 |
| `continueOnFailure` | boolean | 节点失败后是否继续计算出边 |
| `inputBindings` | FlowInputBinding[] | 上游输出到当前请求的映射 |
| `outputPaths` | string[] | 声明可被后续节点引用的标准化输出路径 |

### 3.4 FlowEdge

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 是 | 流程版本内唯一连线 ID |
| `source` | string | 是 | 上游节点 ID |
| `target` | string | 是 | 下游节点 ID |
| `route` | enum | 是 | 下游进入条件 |
| `label` | string | 否 | 展示标签 |

route 语义：

| route | 条件 |
| --- | --- |
| `always` | source 完成后始终满足 |
| `success` | source 状态为 passed/success |
| `failure` | source 状态为 failed/error |
| `true` | source 为 condition 且结果为 true |
| `false` | source 为 condition 且结果为 false |

条件节点必须且只能有一条 `true` 和一条 `false` 出边。非条件节点禁止使用 `true`、`false`。

### 3.5 FlowInputBinding

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 是 | 绑定 ID |
| `target` | string | 是 | 当前节点请求目标路径 |
| `sourceNodeId` | string | 是 | 直接上游节点 ID |
| `sourcePath` | string | 是 | 来源节点标准输出路径 |
| `fallback` | any JSON value | 否 | 来源不存在时默认值，类型应与目标字段兼容 |

后端必须使用安全的结构化路径读写工具实现映射，禁止使用字符串拼接或 `eval`。

校验要求：

- `target` 根路径只允许 `pathParams`、`query`、`headers`、`body`、`variables`、`messages`。
- `sourcePath` 必须等于来源节点声明的某个 `outputPaths`，或是其子路径。

条件表达式必须通过受限表达式引擎执行，禁止使用语言原生 `eval`。建议使用 CEL 风格语法，并向表达式只暴露脱敏后的 `outputs`、`variables` 和当前环境元数据。例如：

```text
outputs["node-login"].response.status == 200
```

## 4. 标准化节点输出

建议每个节点执行后生成统一上下文：

```json
{
  "nodeId": "node-login",
  "status": "passed",
  "startedAt": "2026-06-07T09:00:00Z",
  "finishedAt": "2026-06-07T09:00:01Z",
  "durationMs": 1000,
  "response": {
    "status": 200,
    "headers": {},
    "body": {}
  },
  "assertions": [],
  "error": null
}
```

WebSocket 节点可在 `response.messages` 中保存脱敏后的消息。条件节点额外返回 `result: true/false`。等待节点只需返回状态和耗时。

## 5. 校验规则

### 5.1 创建和更新接口

必须执行结构校验：

- 节点 ID、连线 ID 唯一且非空。
- 节点名称非空。
- 接口节点引用存在且属于当前项目。
- 环境属于当前项目。
- 条件表达式非空。
- 等待时间为非负有限数字。
- 连线 source/target 存在。
- 禁止自连接、重复边和循环。
- 输入绑定字段完整。
- 输入绑定来源必须是当前节点直接上游。

允许保存尚未具备开始/结束节点的草稿。

### 5.2 执行接口

除结构校验外必须执行：

- 恰好一个开始节点。
- 至少一个结束节点。
- 开始节点无入边，结束节点无出边。
- 所有节点从开始节点可达。
- 所有节点能到达至少一个结束节点。
- 条件节点具有且仅具有一条 true 和一条 false 出边。
- 普通节点不使用 true/false 路由。

建议错误响应：

```json
{
  "code": 42201,
  "message": "流程校验失败",
  "data": {
    "issues": [
      {
        "code": "dangling_edge",
        "message": "连线引用了不存在的节点",
        "edgeId": "edge-1"
      }
    ]
  }
}
```

## 6. API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/flows?project_id={project_id}` | 查询流程摘要列表 |
| POST | `/flows?project_id={project_id}` | 创建流程和首个版本 |
| GET | `/flows/{flow_id}?project_id={project_id}` | 获取当前完整流程定义 |
| PUT | `/flows/{flow_id}?project_id={project_id}` | 更新流程并创建新版本 |
| POST | `/flows/{flow_id}/execute?project_id={project_id}&environment_id={environment_id}` | 执行已保存流程 |
| POST | `/flows/execute-unsaved?project_id={project_id}&environment_id={environment_id}` | 试运行未保存定义 |

编排页面的“试运行”固定调用 `execute-unsaved`，保证执行的是当前画布定义。按 ID 执行接口用于执行中心、测试计划或其他明确执行已保存版本的场景。

### 6.1 列表响应

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "id": 12,
      "name": "下单主链路",
      "description": "",
      "node_count": 6,
      "current_version": 3,
      "updated_at": "2026-06-07T09:00:00Z"
    }
  ]
}
```

列表默认不返回完整 definition，避免数据量过大。

### 6.2 创建与更新请求

```json
{
  "name": "下单主链路",
  "description": "登录后创建订单",
  "definition": {}
}
```

建议更新接口支持乐观锁：

```json
{
  "expected_version": 3,
  "name": "下单主链路",
  "description": "登录后创建订单",
  "definition": {}
}
```

版本冲突返回 HTTP `409`。

### 6.3 执行响应

```json
{
  "code": 0,
  "message": "流程已进入执行队列",
  "data": {
    "execution_id": 9001,
    "flow_id": 12,
    "flow_version": 3,
    "status": "queued"
  }
}
```

建议使用 `Idempotency-Key` 防止用户重复点击创建重复执行。

## 7. 执行算法

建议执行器步骤：

1. 校验项目权限、环境权限和流程可执行性。
2. 固化流程版本快照和引用测试用例快照。
3. 创建 execution 和每个节点的待执行记录。
4. 从唯一开始节点进入。
5. 节点只有在所有已激活入边的上游完成后才可执行。
6. 执行节点前合并环境变量，并按 `inputBindings` 写入请求副本。
7. 执行节点并保存标准化输出。
8. 根据节点状态/条件结果计算满足的出边。
9. 没有被任何满足出边激活的节点标记为 skipped。
10. 所有已激活路径完成后汇总流程状态。

同一层无依赖节点可以并行执行。后端需要限制单流程和单项目并发数。

`continueOnFailure=false` 时，失败节点不应激活 `always` 和 `success` 出边，只允许激活 `failure` 出边。`continueOnFailure=true` 时，可继续计算全部符合语义的出边。

### 7.1 执行场景处理矩阵

| 场景 | 建议处理 |
| --- | --- |
| 多条出边同时满足 | 激活所有满足条件的下游，允许并行执行 |
| 节点有多条入边 | 等待所有已激活入边的上游进入终态后执行 |
| 某条入边未被分支激活 | 不参与汇合等待 |
| 节点最终没有任何入边被激活 | 标记为 `skipped` |
| 条件表达式返回非 boolean | 条件节点失败 |
| `sourcePath` 不存在且有 fallback | 使用 fallback |
| `sourcePath` 不存在且无 fallback | 当前节点失败，不发送请求 |
| 引用测试用例已删除或跨项目 | 保存/执行校验失败 |
| 环境已删除或跨项目 | 执行校验失败 |
| 多个结束节点 | 任意激活路径可进入对应结束节点；全部激活路径完成后汇总 |
| 没有满足的出边 | 当前路径结束；若流程仍有其他激活路径则继续 |
| 用户取消执行 | 停止调度新节点，运行中节点尽力取消，其余标记 `cancelled` |
| 重复执行请求 | 使用 `Idempotency-Key` 返回同一 execution |

### 7.2 流程状态汇总

建议规则：

- 任一激活节点失败且未被允许继续时，流程为 `failed`。
- 所有激活节点成功或跳过，流程为 `passed`。
- 用户取消后流程为 `cancelled`。
- 节点仍在等待或执行时流程为 `running`。
- 已创建但尚未开始调度时流程为 `queued`。

## 8. 建议数据库结构

### visual_flows

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | bigint PK | 流程 ID |
| `project_id` | bigint FK | 项目 |
| `name` | varchar(200) | 名称 |
| `description` | text | 说明 |
| `status` | varchar(32) | draft/active/archived |
| `current_version` | int | 当前版本 |
| `created_by` / `updated_by` | bigint FK | 操作人 |
| `created_at` / `updated_at` | datetime | 时间 |

### visual_flow_versions

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | bigint PK | 版本 ID |
| `flow_id` | bigint FK | 流程 |
| `version` | int | 递增版本 |
| `definition` | json/jsonb | 完整不可变定义 |
| `definition_hash` | varchar(64) | 内容哈希 |
| `created_by` | bigint FK | 创建人 |
| `created_at` | datetime | 时间 |

### visual_flow_executions

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | bigint PK | 执行 ID |
| `flow_id` / `flow_version_id` | bigint FK | 流程及版本 |
| `project_id` / `environment_id` | bigint FK | 执行范围 |
| `status` | varchar(32) | queued/running/passed/failed/cancelled |
| `trigger_type` | varchar(32) | manual/plan/webhook |
| `trigger_user_id` | bigint FK | 触发人 |
| `context_snapshot` | json/jsonb | 脱敏后的上下文 |
| `started_at` / `finished_at` | datetime | 时间 |

### visual_flow_node_executions

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | bigint PK | 节点执行 ID |
| `execution_id` | bigint FK | 流程执行 |
| `node_id` | varchar(128) | 定义中的节点 ID |
| `status` | varchar(32) | pending/running/passed/failed/skipped/cancelled |
| `attempt` | int | 执行次数 |
| `request_snapshot` | json/jsonb | 脱敏请求 |
| `output_snapshot` | json/jsonb | 标准化脱敏输出 |
| `error` | json/jsonb | 错误信息 |
| `started_at` / `finished_at` | datetime | 时间 |

## 9. 权限与安全

建议权限点：

- `flow:view`
- `flow:create`
- `flow:update`
- `flow:delete`
- `flow:execute`

后端必须校验流程、环境、HTTP 用例和 WebSocket 用例都属于当前项目。环境变量、请求头、Token、密码和响应敏感字段必须按统一规则脱敏，不能写入普通日志或直接返回前端。

建议 HTTP 状态码：

| HTTP 状态 | 场景 |
| --- | --- |
| `400` | 请求 JSON 格式错误 |
| `401` | 未登录或 Token 失效 |
| `403` | 无项目或操作权限 |
| `404` | 流程、环境或引用资产不存在 |
| `409` | 版本冲突或幂等键冲突 |
| `422` | 流程结构或可执行校验失败 |
| `429` | 项目或用户执行并发超限 |

## 10. 后端开发验收清单

- 完成六个流程接口。
- 创建/更新生成不可变版本。
- 实现结构校验与可执行校验。
- 实现 route 路由语义。
- 实现输入绑定的安全路径读写。
- 固化执行时测试用例和流程快照。
- 记录流程及节点执行状态。
- 实现项目权限、环境权限和引用资产权限。
- 实现幂等、并发控制、超时和取消。
- 实现敏感字段脱敏。
