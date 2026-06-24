# Visual Flow API

The visual flow module persists versioned DAG definitions and executes HTTP, WebSocket, condition, delay, start, and end nodes.

## Endpoints

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/v1/flows?project_id={project_id}` | `flow:view` |
| POST | `/api/v1/flows?project_id={project_id}` | `flow:manage` |
| GET | `/api/v1/flows/{flow_id}?project_id={project_id}` | `flow:view` |
| PUT | `/api/v1/flows/{flow_id}?project_id={project_id}` | `flow:manage` |
| POST | `/api/v1/flows/{flow_id}/execute?project_id={project_id}` | `test:execute`，后端内部提交工作池执行，接口等待完成并返回原执行记录结构 |
| POST | `/api/v1/flows/execute-unsaved?project_id={project_id}` | `test:execute`，当前仍为同步调试入口 |

Flow 列表支持 `keyword`、`status`、`page` 和 `page_size`：

- `keyword` 按名称或描述模糊匹配。
- 不传 `status` 时排除 `archived`；传入时精确匹配该状态。
- `page` 默认 1，`page_size` 默认 20、最大 200。
- 响应 `data` 为 `{items,total,page,page_size}`，每个 item 包含 `status` 和 `node_count`。

`execute-unsaved` accepts either a complete `FlowDefinition` or `{ "definition": FlowDefinition }`.
Execution endpoints accept an optional `environment_id` query parameter and `Idempotency-Key` header.

## Persistence And Validation

- `visual_flows` stores current metadata and the optimistic-lock version.
- `visual_flow_versions` stores immutable definitions and SHA-256 hashes.
- `visual_flow_executions` stores the immutable definition and referenced test-case snapshots.
- `visual_flow_node_executions` stores normalized node outputs, requests, status, timing, and errors.
- Save validates IDs, project-scoped references, bindings, routes, and DAG cycles.
- Execution additionally validates start/end nodes, reachability, terminal directions, and condition routes.
- Flow execution context, request, and output snapshots mask common token, authorization, password, secret, cookie, and API-key fields.

Condition expressions use a restricted Python/CEL-like subset over `outputs` and `variables`. Function calls and arbitrary code execution are rejected.

Saved Flow execution now runs through the shared execution worker internally: the API creates a
`visual_flow_executions` record, submits it to the worker, waits for completion, and returns the original
execution response shape with the final status. Queue state remains a backend scheduling detail. Unsaved Flow
execution remains a synchronous debugging path until task payload persistence is introduced.

## Node-local case editing

HTTP and WebSocket nodes may contain `config.caseConfig` and `config.caseOverrides`.
They are stored only in the flow definition. Execution deep-copies the referenced test case, applies the node-local configuration, then applies input bindings.

The resulting request is executed as a temporary unsaved case. It never updates the referenced case fields, `last_executed_at`, or `last_execution_status`.

Example:

```json
{
  "id": "node-login",
  "kind": "api_case",
  "referenceId": 101,
  "config": {
    "caseConfig": {
      "method": "POST",
      "path": "/login",
      "headers": {"X-Flow-Only": "true"},
      "bodyType": "json",
      "body": {"username": "flow-user"}
    },
    "caseOverrides": {
      "path": "/login-for-this-flow"
    }
  }
}
```

`caseConfig` is applied first and `caseOverrides` is applied second. Input bindings are applied last.
Project ownership, case identity, and execution environment cannot be overridden by a node-local case copy.
