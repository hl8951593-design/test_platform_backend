# Visual Flow API

The visual flow module persists versioned DAG definitions and executes HTTP, WebSocket, condition, delay, start, and end nodes.

## Endpoints

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/v1/flows?project_id={project_id}` | `flow:view` |
| POST | `/api/v1/flows?project_id={project_id}` | `flow:manage` |
| GET | `/api/v1/flows/{flow_id}?project_id={project_id}` | `flow:view` |
| PUT | `/api/v1/flows/{flow_id}?project_id={project_id}` | `flow:manage` |
| POST | `/api/v1/flows/{flow_id}/execute?project_id={project_id}` | `test:execute` |
| POST | `/api/v1/flows/execute-unsaved?project_id={project_id}` | `test:execute` |

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

Execution is currently synchronous, matching the project's existing test-case execution architecture. Celery scheduling, cancellation, and project concurrency limits remain future production work.

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
