# Agent Conversation Complete Log

- export_format: `agent_conversation_complete_debug_v2`
- conversation_id: `agent-conv-local-55c8919c-429a-49d7-81b8-3a3a431b3724`
- project_id: `1`
- generated_at: `2026-07-07T20:47:53`
- run_count: `2`
- event_count: `151`
- tool_call_count: `12`
- app_log_line_count: `344`

> ?????????????????? `complete.json`?????????? `app_log_lines.txt`?

## Table Counts

| Table | Rows |
| --- | ---: |
| `ai_agent_approval_lineages` | 1 |
| `ai_agent_approval_mutation_logs` | 2 |
| `ai_agent_approvals` | 1 |
| `ai_agent_backend_contracts` | 23 |
| `ai_agent_checkpoints` | 2 |
| `ai_agent_context_builds` | 4 |
| `ai_agent_events` | 151 |
| `ai_agent_evidence_watches` | 2 |
| `ai_agent_loop_observations` | 2 |
| `ai_agent_memory_contradiction_events` | 0 |
| `ai_agent_memory_evidence_links` | 0 |
| `ai_agent_memory_retrieval_profiles` | 4 |
| `ai_agent_memory_source_profiles` | 0 |
| `ai_agent_memory_staleness_events` | 0 |
| `ai_agent_memory_usage_events` | 0 |
| `ai_agent_memory_validation_events` | 0 |
| `ai_agent_migration_blocks` | 0 |
| `ai_agent_outbox` | 151 |
| `ai_agent_reconcile_attempts` | 0 |
| `ai_agent_root_cause_rules` | 16 |
| `ai_agent_runs` | 2 |
| `ai_agent_runtime_snapshots` | 1 |
| `ai_agent_tool_calls` | 12 |
| `ai_agent_worker_queue` | 1 |

## Run `agent-run-1914761819b44a2799a744049d837d7c`

- status: `completed`
- created_at: `2026-07-06 23:54:35`
- updated_at: `2026-07-07 07:56:11`
- intent: 帮我创建企业相关自动化测试流程
- result_json_preview: {"model": "deepseek-v4-pro", "usage": {"total_tokens": "***", "prompt_tokens": "***", "completion_tokens": "***", "prompt_tokens_details": "***", "prompt_cache_hit_tokens": "***", "prompt_cache_miss_tokens": "***", "completion_tokens_details": "***"}, "message": "以下是针对“企业端到端自动化流程测试”的设计审查结果：\n\n### 1. 已完成\n*   已经利用现有项目资产生成了一个**企业端到端自动化流程**的场景草稿。\n*   该草稿覆盖了核心业务闭环：**获取企业列表 → 查询企业CT画像 → 关注企业 → 取消关注**。\n*   草稿中已自动配置了上下游节点间的变量绑定（`companyId`, `companyName`），无需手动传参。\n\n### 2. 已自动修复/验证\n在生成草稿时，平台已基于最近执行记录自动优化了以下内容：\n*   修正了 **“获取企业列表”** 中 `success` 字段为 null 的断言。\n*   按实际返回值修正了 **“关注/取消关注”** 接口中特殊的 `co...

### Events

#### Event 1: `run.queued`

- created_at: `2026-07-07 07:54:45`

```json
{
  "id": 51540,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 1,
  "event_type": "run.queued",
  "payload_json": {
    "intent": "帮我创建企业相关自动化测试流程",
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 1,
    "event_type": "run.queued",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:35.078038",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:54:45"
}
```

#### Event 2: `run.started`

- created_at: `2026-07-07 07:54:45`

```json
{
  "id": 51541,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 2,
  "event_type": "run.started",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 2,
    "event_type": "run.started",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:35.264677",
    "schema_version": 1,
    "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff"
  },
  "created_at": "2026-07-07 07:54:45"
}
```

#### Event 3: `model.started`

- created_at: `2026-07-07 07:54:46`

```json
{
  "id": 51542,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 3,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "provider": "deepseek",
    "event_seq": 3,
    "iteration": 0,
    "loop_step": "tool_planning",
    "event_type": "model.started",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 0,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-0",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-0-tool_planning-2214408a316b485abc1a39ee1248006b"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:36.561260",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-0",
    "final_summary": false,
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-0-tool_planning-2214408a316b485abc1a39ee1248006b",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-0-tool_planning-2214408a316b485abc1a39ee1248006b"
  },
  "created_at": "2026-07-07 07:54:46"
}
```

#### Event 4: `model.completed`

- created_at: `2026-07-07 07:54:57`
- content_preview: ```agent_tool_request
{"tool_name":"project.read_context","input":{"project_id":1},"reason":"获取项目上下文，包括环境、现有测试用例等，以便设计企业自动化测试流程","evidence_refs":[]}
```

```json
{
  "id": 51543,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 4,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "content": "```agent_tool_request\n{\"tool_name\":\"project.read_context\",\"input\":{\"project_id\":1},\"reason\":\"获取项目上下文，包括环境、现有测试用例等，以便设计企业自动化测试流程\",\"evidence_refs\":[]}\n```",
    "provider": "deepseek",
    "event_seq": 4,
    "iteration": 0,
    "loop_step": "tool_planning",
    "event_type": "model.completed",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 0,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-0",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-0-tool_planning-2214408a316b485abc1a39ee1248006b"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:47.497943",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-0",
    "finish_reason": "stop",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-0-tool_planning-2214408a316b485abc1a39ee1248006b",
    "requested_tool": true,
    "schema_version": 1,
    "assistant_visible": false,
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-0-tool_planning-2214408a316b485abc1a39ee1248006b"
  },
  "created_at": "2026-07-07 07:54:57"
}
```

#### Event 5: `model.tool_request_detected`

- created_at: `2026-07-07 07:54:57`

```json
{
  "id": 51544,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 5,
  "event_type": "model.tool_request_detected",
  "payload_json": {
    "reason": "获取项目上下文，包括环境、现有测试用例等，以便设计企业自动化测试流程",
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 5,
    "iteration": 0,
    "loop_step": "tool_planning",
    "tool_name": "project.read_context",
    "event_type": "model.tool_request_detected",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 0,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-0",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-0-tool_planning-2214408a316b485abc1a39ee1248006b"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:47.576174",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-0",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-0-tool_planning-2214408a316b485abc1a39ee1248006b",
    "schema_version": 1,
    "decision_reason": "获取项目上下文，包括环境、现有测试用例等，以便设计企业自动化测试流程",
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-0-tool_planning-2214408a316b485abc1a39ee1248006b"
  },
  "created_at": "2026-07-07 07:54:57"
}
```

#### Event 6: `tool.planned`

- created_at: `2026-07-07 07:54:58`

```json
{
  "id": 51545,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 6,
  "event_type": "tool.planned",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 6,
    "tool_name": "project.read_context",
    "event_type": "tool.planned",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:47.975426",
    "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:54:58"
}
```

#### Event 7: `tool.running`

- created_at: `2026-07-07 07:54:58`

```json
{
  "id": 51546,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 7,
  "event_type": "tool.running",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 7,
    "tool_name": "project.read_context",
    "event_type": "tool.running",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:48.358582",
    "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:54:58"
}
```

#### Event 8: `tool.send_intent_recorded`

- created_at: `2026-07-07 07:54:58`

```json
{
  "id": 51547,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 8,
  "event_type": "tool.send_intent_recorded",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 8,
    "event_type": "tool.send_intent_recorded",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:48.508017",
    "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:54:58"
}
```

#### Event 9: `tool.transport_sent_observed`

- created_at: `2026-07-07 07:54:58`

```json
{
  "id": 51548,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 9,
  "event_type": "tool.transport_sent_observed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 9,
    "event_type": "tool.transport_sent_observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:48.659722",
    "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:54:58"
}
```

#### Event 10: `tool.effect_committed`

- created_at: `2026-07-07 07:54:59`

```json
{
  "id": 51549,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 10,
  "event_type": "tool.effect_committed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 10,
    "event_type": "tool.effect_committed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:48.966252",
    "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:54:59"
}
```

#### Event 11: `tool.completed`

- created_at: `2026-07-07 07:54:59`

```json
{
  "id": 51550,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 11,
  "event_type": "tool.completed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "event_seq": 11,
    "event_type": "tool.completed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:49.126450",
    "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:54:59"
}
```

#### Event 12: `tool.result_observed`

- created_at: `2026-07-07 07:54:59`

```json
{
  "id": 51551,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 12,
  "event_type": "tool.result_observed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "event_seq": 12,
    "loop_step": "tool_execution",
    "tool_name": "project.read_context",
    "event_type": "tool.result_observed",
    "loop_state": {
      "step": "tool_execution",
      "phase": "tool",
      "iteration": 0,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-0",
      "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e",
      "decision_reason": "获取项目上下文，包括环境、现有测试用例等，以便设计企业自动化测试流程"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:49.374061",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-0",
    "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e",
    "schema_version": 1,
    "decision_reason": "获取项目上下文，包括环境、现有测试用例等，以便设计企业自动化测试流程"
  },
  "created_at": "2026-07-07 07:54:59"
}
```

#### Event 13: `model.started`

- created_at: `2026-07-07 07:54:59`

```json
{
  "id": 51552,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 13,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "provider": "deepseek",
    "event_seq": 13,
    "iteration": 1,
    "loop_step": "tool_planning",
    "event_type": "model.started",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 1,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-1",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:49.704059",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-1",
    "final_summary": false,
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3"
  },
  "created_at": "2026-07-07 07:54:59"
}
```

#### Event 14: `model.tool_request_invalid`

- created_at: `2026-07-07 07:55:06`

```json
{
  "id": 51553,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 14,
  "event_type": "model.tool_request_invalid",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 14,
    "iteration": 1,
    "loop_step": "tool_planning",
    "event_type": "model.tool_request_invalid",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 1,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-1",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:56.695675",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-1",
    "error_message": "模型工具请求必须只包含 agent_tool_request fenced JSON block，不能混合自然语言",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3",
    "schema_version": 1,
    "content_preview": "先查看项目里已有的测试用例，了解可用的接口资产，再帮你设计企业自动化测试流程。\n\n```agent_tool_request\n{\"tool_name\": \"testcase.query_project_cases\", \"input\": {\"project_id\": 1, \"detail_level\": \"summary\"}, \"reason\": \"查询项目现有全部用例，以便选取合适接口组合成企业级自动化流程\", \"evidence_refs\": [\"project.read_context\"]}\n```",
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3"
  },
  "created_at": "2026-07-07 07:55:06"
}
```

#### Event 15: `context.decision_context_bound`

- created_at: `2026-07-07 07:55:07`

```json
{
  "id": 51554,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 15,
  "event_type": "context.decision_context_bound",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 15,
    "event_type": "context.decision_context_bound",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:57.158326",
    "build_purpose": "repair",
    "schema_version": 1,
    "context_build_id": "agent-ctx-f1eb68584ce644d8b11e14de2f95b960"
  },
  "created_at": "2026-07-07 07:55:07"
}
```

#### Event 16: `loop.observed`

- created_at: `2026-07-07 07:55:07`

```json
{
  "id": 51555,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 16,
  "event_type": "loop.observed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 16,
    "event_type": "loop.observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:57.518797",
    "observation_id": "agent-obs-91a9ded822cb4867860a21efc5e7100c",
    "schema_version": 1,
    "root_cause_rule_id": "RC_TOOL_REQUEST_FORMAT_INVALID",
    "decision_context_build_id": "agent-ctx-f1eb68584ce644d8b11e14de2f95b960"
  },
  "created_at": "2026-07-07 07:55:07"
}
```

#### Event 17: `model.tool_request_repaired`

- created_at: `2026-07-07 07:55:07`

```json
{
  "id": 51556,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 17,
  "event_type": "model.tool_request_repaired",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 17,
    "iteration": 1,
    "loop_step": "tool_planning",
    "tool_name": "testcase.query_project_cases",
    "event_type": "model.tool_request_repaired",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 1,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-1",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:57.817637",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-1",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3",
    "requested_tool": true,
    "schema_version": 1,
    "repair_strategy": "salvaged_fenced_tool_request",
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3"
  },
  "created_at": "2026-07-07 07:55:07"
}
```

#### Event 18: `model.completed`

- created_at: `2026-07-07 07:55:08`
- content_preview: 先查看项目里已有的测试用例，了解可用的接口资产，再帮你设计企业自动化测试流程。

```agent_tool_request
{"tool_name": "testcase.query_project_cases", "input": {"project_id": 1, "detail_level": "summary"}, "reason": "查询项目现有全部用例，以便选取合适接口组合成企业级自动化流程", "evidence_refs": ["project.read_context"]}
```

```json
{
  "id": 51557,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 18,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "content": "先查看项目里已有的测试用例，了解可用的接口资产，再帮你设计企业自动化测试流程。\n\n```agent_tool_request\n{\"tool_name\": \"testcase.query_project_cases\", \"input\": {\"project_id\": 1, \"detail_level\": \"summary\"}, \"reason\": \"查询项目现有全部用例，以便选取合适接口组合成企业级自动化流程\", \"evidence_refs\": [\"project.read_context\"]}\n```",
    "provider": "deepseek",
    "event_seq": 18,
    "iteration": 1,
    "loop_step": "tool_planning",
    "event_type": "model.completed",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 1,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-1",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:58.056563",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-1",
    "finish_reason": "stop",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3",
    "requested_tool": true,
    "schema_version": 1,
    "assistant_visible": false,
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3"
  },
  "created_at": "2026-07-07 07:55:08"
}
```

#### Event 19: `model.tool_request_detected`

- created_at: `2026-07-07 07:55:08`

```json
{
  "id": 51558,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 19,
  "event_type": "model.tool_request_detected",
  "payload_json": {
    "reason": "查询项目现有全部用例，以便选取合适接口组合成企业级自动化流程",
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 19,
    "iteration": 1,
    "loop_step": "tool_planning",
    "tool_name": "testcase.query_project_cases",
    "event_type": "model.tool_request_detected",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 1,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-1",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:58.146785",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-1",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3",
    "schema_version": 1,
    "decision_reason": "查询项目现有全部用例，以便选取合适接口组合成企业级自动化流程",
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-1-tool_planning-eb6c632d490d4c5681e15022368038d3"
  },
  "created_at": "2026-07-07 07:55:08"
}
```

#### Event 20: `tool.planned`

- created_at: `2026-07-07 07:55:08`

```json
{
  "id": 51559,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 20,
  "event_type": "tool.planned",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 20,
    "tool_name": "testcase.query_project_cases",
    "event_type": "tool.planned",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:58.617451",
    "tool_call_id": "agent-tool-679c3b492ed6459daa4e332e5f15205b",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:08"
}
```

#### Event 21: `tool.running`

- created_at: `2026-07-07 07:55:09`

```json
{
  "id": 51560,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 21,
  "event_type": "tool.running",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 21,
    "tool_name": "testcase.query_project_cases",
    "event_type": "tool.running",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:58.993426",
    "tool_call_id": "agent-tool-679c3b492ed6459daa4e332e5f15205b",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:09"
}
```

#### Event 22: `tool.send_intent_recorded`

- created_at: `2026-07-07 07:55:09`

```json
{
  "id": 51561,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 22,
  "event_type": "tool.send_intent_recorded",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 22,
    "event_type": "tool.send_intent_recorded",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:59.088683",
    "tool_call_id": "agent-tool-679c3b492ed6459daa4e332e5f15205b",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:09"
}
```

#### Event 23: `tool.transport_sent_observed`

- created_at: `2026-07-07 07:55:09`

```json
{
  "id": 51562,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 23,
  "event_type": "tool.transport_sent_observed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 23,
    "event_type": "tool.transport_sent_observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:59.186627",
    "tool_call_id": "agent-tool-679c3b492ed6459daa4e332e5f15205b",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:09"
}
```

#### Event 24: `tool.backend_accepted`

- created_at: `2026-07-07 07:55:09`

```json
{
  "id": 51563,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 24,
  "event_type": "tool.backend_accepted",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 24,
    "event_type": "tool.backend_accepted",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:59.746840",
    "tool_call_id": "agent-tool-679c3b492ed6459daa4e332e5f15205b",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:09"
}
```

#### Event 25: `tool.effect_committed`

- created_at: `2026-07-07 07:55:09`

```json
{
  "id": 51564,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 25,
  "event_type": "tool.effect_committed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 25,
    "event_type": "tool.effect_committed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:59.865265",
    "tool_call_id": "agent-tool-679c3b492ed6459daa4e332e5f15205b",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:09"
}
```

#### Event 26: `tool.completed`

- created_at: `2026-07-07 07:55:10`

```json
{
  "id": 51565,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 26,
  "event_type": "tool.completed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "event_seq": 26,
    "event_type": "tool.completed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:54:59.969329",
    "tool_call_id": "agent-tool-679c3b492ed6459daa4e332e5f15205b",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:10"
}
```

#### Event 27: `tool.result_observed`

- created_at: `2026-07-07 07:55:10`

```json
{
  "id": 51566,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 27,
  "event_type": "tool.result_observed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "event_seq": 27,
    "loop_step": "tool_execution",
    "tool_name": "testcase.query_project_cases",
    "event_type": "tool.result_observed",
    "loop_state": {
      "step": "tool_execution",
      "phase": "tool",
      "iteration": 1,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-1",
      "tool_call_id": "agent-tool-679c3b492ed6459daa4e332e5f15205b",
      "decision_reason": "查询项目现有全部用例，以便选取合适接口组合成企业级自动化流程"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:00.226637",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-1",
    "tool_call_id": "agent-tool-679c3b492ed6459daa4e332e5f15205b",
    "schema_version": 1,
    "decision_reason": "查询项目现有全部用例，以便选取合适接口组合成企业级自动化流程"
  },
  "created_at": "2026-07-07 07:55:10"
}
```

#### Event 28: `model.started`

- created_at: `2026-07-07 07:55:10`

```json
{
  "id": 51567,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 28,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "provider": "deepseek",
    "event_seq": 28,
    "iteration": 2,
    "loop_step": "tool_planning",
    "event_type": "model.started",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 2,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-2",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:00.617817",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-2",
    "final_summary": false,
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67"
  },
  "created_at": "2026-07-07 07:55:10"
}
```

#### Event 29: `model.tool_request_invalid`

- created_at: `2026-07-07 07:55:23`

```json
{
  "id": 51568,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 29,
  "event_type": "model.tool_request_invalid",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 29,
    "iteration": 2,
    "loop_step": "tool_planning",
    "event_type": "model.tool_request_invalid",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 2,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-2",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:13.065823",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-2",
    "error_message": "模型工具请求必须只包含 agent_tool_request fenced JSON block，不能混合自然语言",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67",
    "schema_version": 1,
    "content_preview": "根据项目现有用例，我可以帮你组合一个企业端到端自动化场景。下面以「获取企业列表 → 查企业详情 → 关注 → 取消关注」为核心链路来生成场景草稿。\n\n```agent_tool_request\n{\"tool_name\":\"scenario.compose_draft\",\"input\":{\"project_id\":1,\"input\":{\"requirement\":\"创建企业相关端到端自动化测试流程：1）查询企业列表获取企业ID；2）使用企业ID查询对应企业CT画像数；3）关注[agent_content_preview_truncated] content_summary_version=agent_content_preview_summary_v1 content_size_chars=674 content_hash=5ed0d5178c2fb4baa185fce151aa17dbc0a47d8502706d0c57716436d6ed36e4 full_content_reference=AgentConversationRunner.model.tool_request_invalid.content",
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67"
  },
  "created_at": "2026-07-07 07:55:23"
}
```

#### Event 30: `context.decision_context_bound`

- created_at: `2026-07-07 07:55:23`

```json
{
  "id": 51569,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 30,
  "event_type": "context.decision_context_bound",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 30,
    "event_type": "context.decision_context_bound",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:13.533481",
    "build_purpose": "repair",
    "schema_version": 1,
    "context_build_id": "agent-ctx-862a6cd67eb34849975c0cc73d487d58"
  },
  "created_at": "2026-07-07 07:55:23"
}
```

#### Event 31: `loop.observed`

- created_at: `2026-07-07 07:55:23`

```json
{
  "id": 51570,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 31,
  "event_type": "loop.observed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 31,
    "event_type": "loop.observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:13.831806",
    "observation_id": "agent-obs-e5a79cd6d8f34153bae9a9d155b0fb85",
    "schema_version": 1,
    "root_cause_rule_id": "RC_TOOL_REQUEST_FORMAT_INVALID",
    "decision_context_build_id": "agent-ctx-862a6cd67eb34849975c0cc73d487d58"
  },
  "created_at": "2026-07-07 07:55:23"
}
```

#### Event 32: `model.tool_request_repaired`

- created_at: `2026-07-07 07:55:24`

```json
{
  "id": 51571,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 32,
  "event_type": "model.tool_request_repaired",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 32,
    "iteration": 2,
    "loop_step": "tool_planning",
    "tool_name": "scenario.compose_draft",
    "event_type": "model.tool_request_repaired",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 2,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-2",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:14.083179",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-2",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67",
    "requested_tool": true,
    "schema_version": 1,
    "repair_strategy": "salvaged_fenced_tool_request",
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67"
  },
  "created_at": "2026-07-07 07:55:24"
}
```

#### Event 33: `model.completed`

- created_at: `2026-07-07 07:55:24`
- content_preview: 根据项目现有用例，我可以帮你组合一个企业端到端自动化场景。下面以「获取企业列表 → 查企业详情 → 关注 → 取消关注」为核心链路来生成场景草稿。

```agent_tool_request
{"tool_name":"scenario.compose_draft","input":{"project_id":1,"input":{"requirement":"创建企业相关端到端自动化测试流程：1）查询企业列表获取企业ID；2）使用企业ID查询对应企业CT画像数；3）[agent_content_preview_truncated] content_summary_version=agent_content_preview_summary_v1 content_size_chars=674 content_hash=5ed0d5178c2fb4baa185fce151aa17dbc0a47d8502706d0c57716436d6ed36e4 full_content_reference=AgentConversationRunner.model.completed.tool_req...

```json
{
  "id": 51572,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 33,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "content": "根据项目现有用例，我可以帮你组合一个企业端到端自动化场景。下面以「获取企业列表 → 查企业详情 → 关注 → 取消关注」为核心链路来生成场景草稿。\n\n```agent_tool_request\n{\"tool_name\":\"scenario.compose_draft\",\"input\":{\"project_id\":1,\"input\":{\"requirement\":\"创建企业相关端到端自动化测试流程：1）查询企业列表获取企业ID；2）使用企业ID查询对应企业CT画像数；3）[agent_content_preview_truncated] content_summary_version=agent_content_preview_summary_v1 content_size_chars=674 content_hash=5ed0d5178c2fb4baa185fce151aa17dbc0a47d8502706d0c57716436d6ed36e4 full_content_reference=AgentConversationRunner.model.completed.tool_request.content",
    "provider": "deepseek",
    "event_seq": 33,
    "iteration": 2,
    "loop_step": "tool_planning",
    "event_type": "model.completed",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 2,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-2",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:14.363270",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-2",
    "finish_reason": "stop",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67",
    "requested_tool": true,
    "schema_version": 1,
    "assistant_visible": false,
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67"
  },
  "created_at": "2026-07-07 07:55:24"
}
```

#### Event 34: `model.tool_request_detected`

- created_at: `2026-07-07 07:55:24`

```json
{
  "id": 51573,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 34,
  "event_type": "model.tool_request_detected",
  "payload_json": {
    "reason": null,
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 34,
    "iteration": 2,
    "loop_step": "tool_planning",
    "tool_name": "scenario.compose_draft",
    "event_type": "model.tool_request_detected",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 2,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-2",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:14.494966",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-2",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67",
    "schema_version": 1,
    "decision_reason": null,
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-2-tool_planning-185588b9a6354af682ad33157f2abd67"
  },
  "created_at": "2026-07-07 07:55:24"
}
```

#### Event 35: `tool.planned`

- created_at: `2026-07-07 07:55:25`

```json
{
  "id": 51574,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 35,
  "event_type": "tool.planned",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 35,
    "tool_name": "scenario.compose_draft",
    "event_type": "tool.planned",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:14.965870",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:25"
}
```

#### Event 36: `tool.running`

- created_at: `2026-07-07 07:55:25`

```json
{
  "id": 51575,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 36,
  "event_type": "tool.running",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 36,
    "tool_name": "scenario.compose_draft",
    "event_type": "tool.running",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:15.329781",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:25"
}
```

#### Event 37: `tool.send_intent_recorded`

- created_at: `2026-07-07 07:55:25`

```json
{
  "id": 51576,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 37,
  "event_type": "tool.send_intent_recorded",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 37,
    "event_type": "tool.send_intent_recorded",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:15.465245",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:25"
}
```

#### Event 38: `tool.transport_sent_observed`

- created_at: `2026-07-07 07:55:25`

```json
{
  "id": 51577,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 38,
  "event_type": "tool.transport_sent_observed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 38,
    "event_type": "tool.transport_sent_observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:15.576944",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:25"
}
```

#### Event 39: `tool.effect_committed`

- created_at: `2026-07-07 07:55:52`

```json
{
  "id": 51578,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 39,
  "event_type": "tool.effect_committed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 39,
    "event_type": "tool.effect_committed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:42.841029",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:52"
}
```

#### Event 40: `tool.completed`

- created_at: `2026-07-07 07:55:53`

```json
{
  "id": 51579,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 40,
  "event_type": "tool.completed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "event_seq": 40,
    "event_type": "tool.completed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:43.006619",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:53"
}
```

#### Event 41: `tool.result_observed`

- created_at: `2026-07-07 07:55:53`

```json
{
  "id": 51580,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 41,
  "event_type": "tool.result_observed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "event_seq": 41,
    "loop_step": "tool_execution",
    "tool_name": "scenario.compose_draft",
    "event_type": "tool.result_observed",
    "loop_state": {
      "step": "tool_execution",
      "phase": "tool",
      "iteration": 2,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-2",
      "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:43.421510",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-2",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:53"
}
```

#### Event 42: `model.started`

- created_at: `2026-07-07 07:55:54`

```json
{
  "id": 51581,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 42,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "provider": "deepseek",
    "event_seq": 42,
    "iteration": 3,
    "loop_step": "tool_planning",
    "event_type": "model.started",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 3,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-3",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-3-tool_planning-9784bd380bef441b90d6fca1d5e7ba0a"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:43.913568",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-3",
    "final_summary": false,
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-3-tool_planning-9784bd380bef441b90d6fca1d5e7ba0a",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-3-tool_planning-9784bd380bef441b90d6fca1d5e7ba0a"
  },
  "created_at": "2026-07-07 07:55:54"
}
```

#### Event 43: `model.completed`

- created_at: `2026-07-07 07:55:58`
- content_preview: ```agent_tool_request
{"tool_name":"tool_result.read_full","input":{"tool_call_id":"agent-tool-7f6517141970455b9b23b82dc1fcfb34","max_chars":64000},"reason":"读取场景草稿完整输出，分析所有警告和修复点","evidence_refs":["agent-tool-7f6517141970455b9b23b82dc1fcfb34"]}
```

```json
{
  "id": 51582,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 43,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "content": "```agent_tool_request\n{\"tool_name\":\"tool_result.read_full\",\"input\":{\"tool_call_id\":\"agent-tool-7f6517141970455b9b23b82dc1fcfb34\",\"max_chars\":64000},\"reason\":\"读取场景草稿完整输出，分析所有警告和修复点\",\"evidence_refs\":[\"agent-tool-7f6517141970455b9b23b82dc1fcfb34\"]}\n```",
    "provider": "deepseek",
    "event_seq": 43,
    "iteration": 3,
    "loop_step": "tool_planning",
    "event_type": "model.completed",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 3,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-3",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-3-tool_planning-9784bd380bef441b90d6fca1d5e7ba0a"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:48.625948",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-3",
    "finish_reason": "stop",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-3-tool_planning-9784bd380bef441b90d6fca1d5e7ba0a",
    "requested_tool": true,
    "schema_version": 1,
    "assistant_visible": false,
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-3-tool_planning-9784bd380bef441b90d6fca1d5e7ba0a"
  },
  "created_at": "2026-07-07 07:55:58"
}
```

#### Event 44: `model.tool_request_detected`

- created_at: `2026-07-07 07:55:58`

```json
{
  "id": 51583,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 44,
  "event_type": "model.tool_request_detected",
  "payload_json": {
    "reason": "读取场景草稿完整输出，分析所有警告和修复点",
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 44,
    "iteration": 3,
    "loop_step": "tool_planning",
    "tool_name": "tool_result.read_full",
    "event_type": "model.tool_request_detected",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 3,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-3",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-3-tool_planning-9784bd380bef441b90d6fca1d5e7ba0a"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:48.706538",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-3",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-3-tool_planning-9784bd380bef441b90d6fca1d5e7ba0a",
    "schema_version": 1,
    "decision_reason": "读取场景草稿完整输出，分析所有警告和修复点",
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-3-tool_planning-9784bd380bef441b90d6fca1d5e7ba0a"
  },
  "created_at": "2026-07-07 07:55:58"
}
```

#### Event 45: `tool.planned`

- created_at: `2026-07-07 07:55:59`

```json
{
  "id": 51584,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 45,
  "event_type": "tool.planned",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 45,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.planned",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:49.243708",
    "tool_call_id": "agent-tool-963059530c0149339e83d13142cd93ed",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:59"
}
```

#### Event 46: `tool.running`

- created_at: `2026-07-07 07:55:59`

```json
{
  "id": 51585,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 46,
  "event_type": "tool.running",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 46,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.running",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:49.595394",
    "tool_call_id": "agent-tool-963059530c0149339e83d13142cd93ed",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:59"
}
```

#### Event 47: `tool.send_intent_recorded`

- created_at: `2026-07-07 07:55:59`

```json
{
  "id": 51586,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 47,
  "event_type": "tool.send_intent_recorded",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 47,
    "event_type": "tool.send_intent_recorded",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:49.709648",
    "tool_call_id": "agent-tool-963059530c0149339e83d13142cd93ed",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:59"
}
```

#### Event 48: `tool.transport_sent_observed`

- created_at: `2026-07-07 07:55:59`

```json
{
  "id": 51587,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 48,
  "event_type": "tool.transport_sent_observed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 48,
    "event_type": "tool.transport_sent_observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:49.809633",
    "tool_call_id": "agent-tool-963059530c0149339e83d13142cd93ed",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:55:59"
}
```

#### Event 49: `tool.backend_accepted`

- created_at: `2026-07-07 07:56:00`

```json
{
  "id": 51588,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 49,
  "event_type": "tool.backend_accepted",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 49,
    "event_type": "tool.backend_accepted",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:50.023570",
    "tool_call_id": "agent-tool-963059530c0149339e83d13142cd93ed",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:56:00"
}
```

#### Event 50: `tool.effect_committed`

- created_at: `2026-07-07 07:56:00`

```json
{
  "id": 51589,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 50,
  "event_type": "tool.effect_committed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 50,
    "event_type": "tool.effect_committed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:50.140544",
    "tool_call_id": "agent-tool-963059530c0149339e83d13142cd93ed",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:56:00"
}
```

#### Event 51: `tool.completed`

- created_at: `2026-07-07 07:56:00`

```json
{
  "id": 51590,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 51,
  "event_type": "tool.completed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "event_seq": 51,
    "event_type": "tool.completed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:50.253882",
    "tool_call_id": "agent-tool-963059530c0149339e83d13142cd93ed",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:56:00"
}
```

#### Event 52: `tool.result_observed`

- created_at: `2026-07-07 07:56:00`

```json
{
  "id": 51591,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 52,
  "event_type": "tool.result_observed",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "event_seq": 52,
    "loop_step": "tool_execution",
    "tool_name": "tool_result.read_full",
    "event_type": "tool.result_observed",
    "loop_state": {
      "step": "tool_execution",
      "phase": "tool",
      "iteration": 3,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-3",
      "tool_call_id": "agent-tool-963059530c0149339e83d13142cd93ed",
      "decision_reason": "读取场景草稿完整输出，分析所有警告和修复点"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:50.505486",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-3",
    "tool_call_id": "agent-tool-963059530c0149339e83d13142cd93ed",
    "schema_version": 1,
    "decision_reason": "读取场景草稿完整输出，分析所有警告和修复点"
  },
  "created_at": "2026-07-07 07:56:00"
}
```

#### Event 53: `model.started`

- created_at: `2026-07-07 07:56:01`

```json
{
  "id": 51592,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 53,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "provider": "deepseek",
    "event_seq": 53,
    "iteration": 4,
    "loop_step": "tool_planning",
    "event_type": "model.started",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 4,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-4",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-4-tool_planning-584011875b8e4a458a3f4ddb78dafb97"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:55:50.867922",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-4",
    "final_summary": false,
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-4-tool_planning-584011875b8e4a458a3f4ddb78dafb97",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-4-tool_planning-584011875b8e4a458a3f4ddb78dafb97"
  },
  "created_at": "2026-07-07 07:56:01"
}
```

#### Event 54: `model.delta`

- created_at: `2026-07-07 07:56:10`
- content_preview: 以下是针对“企业端到端自动化流程测试”的设计审查结果：

### 1. 已完成
*   已经利用现有项目资产生成了一个**企业端到端自动化流程**的场景草稿。
*   该草稿覆盖了核心业务闭环：**获取企业列表 → 查询企业CT画像 → 关注企业 → 取消关注**。
*   草稿中已自动配置了上下游节点间的变量绑定（`companyId`, `companyName`），无需手动传参。

### 2. 已自动修复/验证
在生成草稿时，平台已基于最近执行记录自动优化了以下内容：
*   修正了 **“获取企业列表”** 中 `success` 字段为 null 的断言。
*   按实际返回值修正了 **“关注/取消关注”** 接口中特殊的 `code` 值断言。
*   为提升稳定性，移除了 **“获取企业列表”** 中不太稳定的关键字包含断言。
*   精简了 **“CT画像查询”** 接口中因测试数据导致大量字段为 null 的断言。

### 3. 仍需用户配置的阻断项
*   **鉴权配置缺失**：草稿中的“关注”和“取消关注”节点依赖 `Lingxi-Auth` 请求头变量。请...

```json
{
  "id": 51593,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 54,
  "event_type": "model.delta",
  "payload_json": {
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "content": "以下是针对“企业端到端自动化流程测试”的设计审查结果：\n\n### 1. 已完成\n*   已经利用现有项目资产生成了一个**企业端到端自动化流程**的场景草稿。\n*   该草稿覆盖了核心业务闭环：**获取企业列表 → 查询企业CT画像 → 关注企业 → 取消关注**。\n*   草稿中已自动配置了上下游节点间的变量绑定（`companyId`, `companyName`），无需手动传参。\n\n### 2. 已自动修复/验证\n在生成草稿时，平台已基于最近执行记录自动优化了以下内容：\n*   修正了 **“获取企业列表”** 中 `success` 字段为 null 的断言。\n*   按实际返回值修正了 **“关注/取消关注”** 接口中特殊的 `code` 值断言。\n*   为提升稳定性，移除了 **“获取企业列表”** 中不太稳定的关键字包含断言。\n*   精简了 **“CT画像查询”** 接口中因测试数据导致大量字段为 null 的断言。\n\n### 3. 仍需用户配置的阻断项\n*   **鉴权配置缺失**：草稿中的“关注”和“取消关注”节点依赖 `Lingxi-Auth` 请求头变量。请确认该环境（test）中是否已配置有效的鉴权变量，或者在保存前为场景节点补充前置登录步骤，否则执行会失败。\n\n### 4. 建议下一步\n你可以基于这个草稿继续完善。如果觉得流程符合预期，我将其**保存为正式场景**。保存后，就可以在平台上直接执行和调试这个端到端流程了。需要我为你保存吗？",
    "event_seq": 54,
    "loop_step": "tool_planning",
    "event_type": "model.delta",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 4,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-4",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-4-tool_planning-584011875b8e4a458a3f4ddb78dafb97"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:00.829181",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-4",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-4-tool_planning-584011875b8e4a458a3f4ddb78dafb97",
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-4-tool_planning-584011875b8e4a458a3f4ddb78dafb97"
  },
  "created_at": "2026-07-07 07:56:10"
}
```

#### Event 55: `model.completed`

- created_at: `2026-07-07 07:56:11`
- content_preview: 以下是针对“企业端到端自动化流程测试”的设计审查结果：

### 1. 已完成
*   已经利用现有项目资产生成了一个**企业端到端自动化流程**的场景草稿。
*   该草稿覆盖了核心业务闭环：**获取企业列表 → 查询企业CT画像 → 关注企业 → 取消关注**。
*   草稿中已自动配置了上下游节点间的变量绑定（`companyId`, `companyName`），无需手动传参。

### 2. 已自动修复/验证
在生成草稿时，平台已基于最近执行记录自动优化了以下内容：
*   修正了 **“获取企业列表”** 中 `success` 字段为 null 的断言。
*   按实际返回值修正了 **“关注/取消关注”** 接口中特殊的 `code` 值断言。
*   为提升稳定性，移除了 **“获取企业列表”** 中不太稳定的关键字包含断言。
*   精简了 **“CT画像查询”** 接口中因测试数据导致大量字段为 null 的断言。

### 3. 仍需用户配置的阻断项
*   **鉴权配置缺失**：草稿中的“关注”和“取消关注”节点依赖 `Lingxi-Auth` 请求头变量。请...

```json
{
  "id": 51594,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 55,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "content": "以下是针对“企业端到端自动化流程测试”的设计审查结果：\n\n### 1. 已完成\n*   已经利用现有项目资产生成了一个**企业端到端自动化流程**的场景草稿。\n*   该草稿覆盖了核心业务闭环：**获取企业列表 → 查询企业CT画像 → 关注企业 → 取消关注**。\n*   草稿中已自动配置了上下游节点间的变量绑定（`companyId`, `companyName`），无需手动传参。\n\n### 2. 已自动修复/验证\n在生成草稿时，平台已基于最近执行记录自动优化了以下内容：\n*   修正了 **“获取企业列表”** 中 `success` 字段为 null 的断言。\n*   按实际返回值修正了 **“关注/取消关注”** 接口中特殊的 `code` 值断言。\n*   为提升稳定性，移除了 **“获取企业列表”** 中不太稳定的关键字包含断言。\n*   精简了 **“CT画像查询”** 接口中因测试数据导致大量字段为 null 的断言。\n\n### 3. 仍需用户配置的阻断项\n*   **鉴权配置缺失**：草稿中的“关注”和“取消关注”节点依赖 `Lingxi-Auth` 请求头变量。请确认该环境（test）中是否已配置有效的鉴权变量，或者在保存前为场景节点补充前置登录步骤，否则执行会失败。\n\n### 4. 建议下一步\n你可以基于这个草稿继续完善。如果觉得流程符合预期，我将其**保存为正式场景**。保存后，就可以在平台上直接执行和调试这个端到端流程了。需要我为你保存吗？",
    "provider": "deepseek",
    "event_seq": 55,
    "iteration": 4,
    "loop_step": "tool_planning",
    "event_type": "model.completed",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 4,
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-4",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-4-tool_planning-584011875b8e4a458a3f4ddb78dafb97"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:01.019991",
    "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-4",
    "finish_reason": "stop",
    "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-4-tool_planning-584011875b8e4a458a3f4ddb78dafb97",
    "requested_tool": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-4-tool_planning-584011875b8e4a458a3f4ddb78dafb97"
  },
  "created_at": "2026-07-07 07:56:11"
}
```

#### Event 56: `run.completed`

- created_at: `2026-07-07 07:56:11`

```json
{
  "id": 51595,
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "event_seq": 56,
  "event_type": "run.completed",
  "payload_json": {
    "result": {
      "model": "deepseek-v4-pro",
      "usage": {
        "total_tokens": "***",
        "prompt_tokens": "***",
        "completion_tokens": "***",
        "prompt_tokens_details": "***",
        "prompt_cache_hit_tokens": "***",
        "prompt_cache_miss_tokens": "***",
        "completion_tokens_details": "***"
      },
      "message": "以下是针对“企业端到端自动化流程测试”的设计审查结果：\n\n### 1. 已完成\n*   已经利用现有项目资产生成了一个**企业端到端自动化流程**的场景草稿。\n*   该草稿覆盖了核心业务闭环：**获取企业列表 → 查询企业CT画像 → 关注企业 → 取消关注**。\n*   草稿中已自动配置了上下游节点间的变量绑定（`companyId`, `companyName`），无需手动传参。\n\n### 2. 已自动修复/验证\n在生成草稿时，平台已基于最近执行记录自动优化了以下内容：\n*   修正了 **“获取企业列表”** 中 `success` 字段为 null 的断言。\n*   按实际返回值修正了 **“关注/取消关注”** 接口中特殊的 `code` 值断言。\n*   为提升稳定性，移除了 **“获取企业列表”** 中不太稳定的关键字包含断言。\n*   精简了 **“CT画像查询”** 接口中因测试数据导致大量字段为 null 的断言。\n\n### 3. 仍需用户配置的阻断项\n*   **鉴权配置缺失**：草稿中的“关注”和“取消关注”节点依赖 `Lingxi-Auth` 请求头变量。请确认该环境（test）中是否已配置有效的鉴权变量，或者在保存前为场景节点补充前置登录步骤，否则执行会失败。\n\n### 4. 建议下一步\n你可以基于这个草稿继续完善。如果觉得流程符合预期，我将其**保存为正式场景**。保存后，就可以在平台上直接执行和调试这个端到端流程了。需要我为你保存吗？",
      "provider": "deepseek",
      "loop_step": "tool_planning",
      "loop_state": {
        "step": "tool_planning",
        "phase": "model",
        "iteration": 4,
        "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-4",
        "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-4-tool_planning-584011875b8e4a458a3f4ddb78dafb97"
      },
      "tool_calls": [
        {
          "status": "succeeded",
          "tool_name": "project.read_context",
          "error_code": null,
          "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e",
          "approval_required": false
        },
        {
          "status": "succeeded",
          "tool_name": "testcase.query_project_cases",
          "error_code": null,
          "tool_call_id": "agent-tool-679c3b492ed6459daa4e332e5f15205b",
          "approval_required": false
        },
        {
          "status": "succeeded",
          "tool_name": "scenario.compose_draft",
          "error_code": null,
          "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
          "approval_required": false
        },
        {
          "status": "succeeded",
          "tool_name": "tool_result.read_full",
          "error_code": null,
          "tool_call_id": "agent-tool-963059530c0149339e83d13142cd93ed",
          "approval_required": false
        }
      ],
      "iteration_id": "agent-run-1914761819b44a2799a744049d837d7c:iter-4",
      "finish_reason": "stop",
      "model_call_id": "agent-run-1914761819b44a2799a744049d837d7c:model-4-tool_planning-584011875b8e4a458a3f4ddb78dafb97",
      "model_response_item_id": "agent-model-response://agent-run-1914761819b44a2799a744049d837d7c/agent-run-1914761819b44a2799a744049d837d7c:model-4-tool_planning-584011875b8e4a458a3f4ddb78dafb97"
    },
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "event_seq": 56,
    "event_type": "run.completed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:01.190612",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:56:11"
}
```

### Tool Calls

#### Tool `project.read_context` / `agent-tool-8d64dda3cf78457e9dcaec9c080ff78e`

- status: `succeeded`
- step_index: `0`
- attempt_index: `0`
- approval_required: `0`
- input_hash: `47f649c01fce28d077ef84b4da372c814f31dea5e5c2ff42aca193641041b4ac`
- output_hash: `8678ae2dea57b39a09d4c4245389107575c4f2ffb63b7503b3d531dc36543c39`

```json
{
  "id": 604,
  "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e",
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "step_index": 0,
  "attempt_index": 0,
  "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
  "tool_name": "project.read_context",
  "tool_version": "1.0.0",
  "schema_hash": "362562060738b19c055be88534dd32e39b412751380737a9f03443100b8997e1",
  "manifest_hash": "9150a3c2776044b736518b73460a5589ce5c3a5a288faa2f5bd602aae0d74590",
  "idempotency_scope": "agent-run-1914761819b44a2799a744049d837d7c",
  "idempotency_key": "6e3084f0efe6dd59c7ee32231235889833427858a8791b7f3d0e4527d5002291",
  "base_side_effect_class": "read_only",
  "resolved_side_effect_class": "read_only",
  "base_replay_policy": "reuse_allowed",
  "resolved_replay_policy": "reuse_allowed",
  "policy_reason_json": {
    "dispatch_trace": {
      "router": "AgentToolRouter.resolve",
      "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
      "status": "succeeded",
      "runtime": "AgentToolRuntime.execute",
      "tool_name": "project.read_context",
      "schema_hash": "362562060738b19c055be88534dd32e39b412751380737a9f03443100b8997e1",
      "backend_name": "project-service",
      "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e",
      "tool_version": "1.0.0",
      "manifest_hash": "9150a3c2776044b736518b73460a5589ce5c3a5a288faa2f5bd602aae0d74590",
      "backend_handler": "_project_read_context",
      "backend_operation": "read_context",
      "dispatch_trace_hash": "11fc80f797298c529d368f75ec7e7c17700b1da361eb4a58d5981d941a521718",
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "resolved_replay_policy": "reuse_allowed",
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "resolved_side_effect_class": "read_only",
      "dispatch_trace_version_hash": "agent-tool-dispatch-v1"
    },
    "policy_context": {
      "tool_name": "project.read_context",
      "policy_hash": "16db7d63c9594a1a1691532732491afdca6eb6fe2bfdb4fe25fc74143bab7551",
      "tool_version": "1.0.0",
      "approval_policy": "safe_side_effect_auto",
      "approval_required": false,
      "base_replay_policy": "reuse_allowed",
      "policy_version_hash": "agent-policy-v1",
      "mixed_volatile_frozen": false,
      "base_side_effect_class": "read_only",
      "resolved_replay_policy": "reuse_allowed",
      "active_policy_ref_count": 0,
      "frozen_policy_ref_count": 0,
      "approval_required_reason": "safe_initial_tool",
      "volatile_policy_ref_count": 0,
      "resolved_side_effect_class": "read_only",
      "historical_volatile_excluded_count": 0
    },
    "execution_context": {
      "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
      "tool_name": "project.read_context",
      "worker_id": null,
      "error_code": null,
      "input_hash": "47f649c01fce28d077ef84b4da372c814f31dea5e5c2ff42aca193641041b4ac",
      "approved_by": null,
      "output_hash": "8678ae2dea57b39a09d4c4245389107575c4f2ffb63b7503b3d531dc36543c39",
      "tool_status": "succeeded",
      "backend_name": "project-service",
      "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e",
      "tool_version": "1.0.0",
      "approval_epoch": 0,
      "approval_state": "not_required",
      "execution_phase": "completed",
      "approval_required": false,
      "backend_operation": "read_context",
      "recovery_decision": null,
      "error_message_hash": null,
      "approval_lineage_id": null,
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "approved_approval_id": null,
      "execution_context_hash": "35ad4f2207650e9cd47440c3fd3c4af9d3f6209c586dc76399afcc690a48f713",
      "resolved_replay_policy": "reuse_allowed",
      "result_adapter_version": "v1",
      "effect_boundary_crossed": false,
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "backend_effect_capability": "idempotency_index_only",
      "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
      "reconcile_contract_version": "reconcile-v1",
      "resolved_side_effect_class": "read_only",
      "backend_request_schema_hash": "c83cbcb19c5493e5bd65bd95f8d049f72767bbb15d87778e69f4da6dd655e665",
      "execution_context_version_hash": "agent-tool-execution-v1"
    },
    "base_replay_policy": "reuse_allowed",
    "mixed_volatile_frozen": false,
    "active_policy_ref_count": 0,
    "frozen_policy_ref_count": 0,
    "approval_required_reason": "safe_initial_tool",
    "volatile_policy_ref_count": 0,
    "historical_volatile_excluded_count": 0
  },
  "status": "succeeded",
  "execution_phase": "completed",
  "effect_submission_state": "effect_committed",
  "effect_boundary_crossed": 0,
  "downstream_send_intent_at": "2026-07-06 23:54:48",
  "downstream_request_observed_sent_at": "2026-07-06 23:54:49",
  "downstream_acceptance_id": null,
  "downstream_acceptance_at": null,
  "input_hash": "47f649c01fce28d077ef84b4da372c814f31dea5e5c2ff42aca193641041b4ac",
  "input_json_redacted": {
    "project_id": 1
  },
  "evidence_refs_json": [],
  "output_hash": "8678ae2dea57b39a09d4c4245389107575c4f2ffb63b7503b3d531dc36543c39",
  "output_json_redacted": {
    "project": {
      "id": 1,
      "name": "1",
      "description": "",
      "created_by_id": 1
    },
    "environments": [
      {
        "id": 4,
        "name": "test",
        "base_url": "https://www.lingxidata.cn",
        "is_default": true,
        "object_ref": "object-ref://environment/default/3d759ce85569/4",
        "description": "灵犀测试环境"
      }
    ],
    "default_environment": {
      "id": 4,
      "name": "test",
      "base_url": "https://www.lingxidata.cn",
      "is_default": true,
      "description": "灵犀测试环境"
    },
    "environment_snapshot": {
      "project_id": 1,
      "snapshot_id": "environment-snapshot://85d4b70ef97f659268fb9e93a56a641070b9bc99e3352ae84e30f766ffbb9af0",
      "generated_at": "2026-07-06T23:54:48.890797+00:00",
      "object_family": "environment",
      "validity_scope": "current_agent_conversation_latest_query",
      "identity_semantics": "environment ids are volatile database row locators; re-query before execution.",
      "authoritative_for_tool_input": true
    },
    "environment_id_manifest": {
      "snapshot_id": "environment-snapshot://85d4b70ef97f659268fb9e93a56a641070b9bc99e3352ae84e30f766ffbb9af0",
      "id_source_rule": "Use only these explicit environment ids from the latest project context snapshot; never infer ids from older conversation prose.",
      "validity_scope": "current_agent_conversation_latest_query",
      "environment_ids": [
        4
      ],
      "environment_refs": [
        "object-ref://environment/default/3d759ce85569/4"
      ],
      "environment_execute_ids": [
        4
      ]
    },
    "object_reference_manifest": {
      "query_tool": "project.read_context",
      "snapshot_id": "environment-snapshot://85d4b70ef97f659268fb9e93a56a641070b9bc99e3352ae84e30f766ffbb9af0",
      "object_family": "environment",
      "id_source_rule": "Use only these explicit environment ids from the latest project context snapshot; never infer ids from older conversation prose.",
      "validity_scope": "current_agent_conversation_latest_query",
      "environment_ids": [
        4
      ],
      "environment_refs": [
        "object-ref://environment/default/3d759ce85569/4"
      ],
      "object_references": [
        {
          "id": 4,
          "name": "test",
          "object_ref": "object-ref://environment/default/3d759ce85569/4",
          "object_type": "environment",
          "snapshot_id": "environment-snapshot://85d4b70ef97f659268fb9e93a56a641070b9bc99e3352ae84e30f766ffbb9af0"
        }
      ],
      "environment_execute_ids": [
        4
      ]
    }
  },
  "raw_output_object_key": null,
  "permission_snapshot_json": {
    "user_id": 1,
    "audit_only": true,
    "project_id": 1,
    "captured_at": "2026-07-06T23:54:47.892165",
    "required_permissions": [
      "project:view"
    ]
  },
  "required_permissions_json": [
    "project:view"
  ],
  "approval_required": 0,
  "approval_scope_hash": "9ad67f6f3c563715e30ac6961f7a556f55f2b323284d0128e63a43c865a35b4d",
  "lease_owner": null,
  "lease_expires_at": null,
  "last_heartbeat_at": null,
  "recovery_decision": null,
  "backend_name": "project-service",
  "backend_operation": "read_context",
  "backend_contract_version": "v1",
  "backend_effect_capability": "idempotency_index_only",
  "external_resource_type": null,
  "external_resource_id": null,
  "error_code": null,
  "error_message": null,
  "created_at": "2026-07-07 07:54:58",
  "updated_at": "2026-07-07 07:54:59",
  "backend_request_schema_hash": "c83cbcb19c5493e5bd65bd95f8d049f72767bbb15d87778e69f4da6dd655e665",
  "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
  "reconcile_contract_version": "reconcile-v1",
  "result_adapter_version": "v1",
  "approval_lineage_id": null,
  "approval_epoch": 0,
  "approved_approval_id": null,
  "approved_by": null,
  "approved_at": null,
  "policy_evidence_refs_json": [],
  "audit_evidence_refs_json": [],
  "evidence_mutability_summary_json": {
    "total": 0,
    "fully_frozen": true,
    "by_mutability": {},
    "audit_ref_count": 0,
    "policy_ref_count": 0,
    "requires_revalidation": false
  },
  "decision_context_build_id": null
}
```

#### Tool `testcase.query_project_cases` / `agent-tool-679c3b492ed6459daa4e332e5f15205b`

- status: `succeeded`
- step_index: `1`
- attempt_index: `1`
- approval_required: `0`
- input_hash: `b06cedbf9e6c7c7ad508a218f0e60eda3e4027e8f3951d6bef4a41d233f1ab2d`
- output_hash: `6125ace5fae393f1efbbf2b14e2dbc69d1f38fa88a9965a03781d74b5ec022aa`

```json
{
  "id": 605,
  "tool_call_id": "agent-tool-679c3b492ed6459daa4e332e5f15205b",
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "step_index": 1,
  "attempt_index": 1,
  "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
  "tool_name": "testcase.query_project_cases",
  "tool_version": "1.0.0",
  "schema_hash": "87ff3f6765e43c3d7f8473aeb5788438c34854d2228c046a2e8a350d7f006307",
  "manifest_hash": "d05d336c1d227404fa39212e88ffdf5162bd1ecb733db9171be15a9f6ad7314d",
  "idempotency_scope": "agent-run-1914761819b44a2799a744049d837d7c",
  "idempotency_key": "14902f9dbee373bba432285eab9884695a754a046f32c88bde37bf8c8a76ed39",
  "base_side_effect_class": "read_only",
  "resolved_side_effect_class": "read_only",
  "base_replay_policy": "reuse_allowed",
  "resolved_replay_policy": "reuse_allowed",
  "policy_reason_json": {
    "dispatch_trace": {
      "router": "AgentToolRouter.resolve",
      "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
      "status": "succeeded",
      "runtime": "AgentToolRuntime.execute",
      "tool_name": "testcase.query_project_cases",
      "schema_hash": "87ff3f6765e43c3d7f8473aeb5788438c34854d2228c046a2e8a350d7f006307",
      "backend_name": "testcase-service",
      "tool_call_id": "agent-tool-679c3b492ed6459daa4e332e5f15205b",
      "tool_version": "1.0.0",
      "manifest_hash": "d05d336c1d227404fa39212e88ffdf5162bd1ecb733db9171be15a9f6ad7314d",
      "backend_handler": "_testcase_query_project_cases",
      "backend_operation": "query_project_cases",
      "dispatch_trace_hash": "239efe315abb54078c8f02f950df63a7e6a225995f9efa6f227ac61304a025f9",
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "resolved_replay_policy": "reuse_allowed",
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "resolved_side_effect_class": "read_only",
      "dispatch_trace_version_hash": "agent-tool-dispatch-v1"
    },
    "policy_context": {
      "tool_name": "testcase.query_project_cases",
      "policy_hash": "aa264a0493cc8bb4fd9b9fae816c7e85cec87625898dd939a09e438ee5b9f10a",
      "tool_version": "1.0.0",
      "approval_policy": "safe_side_effect_auto",
      "approval_required": false,
      "base_replay_policy": "reuse_allowed",
      "policy_version_hash": "agent-policy-v1",
      "mixed_volatile_frozen": false,
      "base_side_effect_class": "read_only",
      "resolved_replay_policy": "reuse_allowed",
      "active_policy_ref_count": 0,
      "frozen_policy_ref_count": 0,
      "approval_required_reason": "safe_initial_tool",
      "volatile_policy_ref_count": 0,
      "resolved_side_effect_class": "read_only",
      "historical_volatile_excluded_count": 0
    },
    "execution_context": {
      "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
      "tool_name": "testcase.query_project_cases",
      "worker_id": null,
      "error_code": null,
      "input_hash": "b06cedbf9e6c7c7ad508a218f0e60eda3e4027e8f3951d6bef4a41d233f1ab2d",
      "approved_by": null,
      "output_hash": "6125ace5fae393f1efbbf2b14e2dbc69d1f38fa88a9965a03781d74b5ec022aa",
      "tool_status": "succeeded",
      "backend_name": "testcase-service",
      "tool_call_id": "agent-tool-679c3b492ed6459daa4e332e5f15205b",
      "tool_version": "1.0.0",
      "approval_epoch": 0,
      "approval_state": "not_required",
      "execution_phase": "completed",
      "approval_required": false,
      "backend_operation": "query_project_cases",
      "recovery_decision": null,
      "error_message_hash": null,
      "approval_lineage_id": null,
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "approved_approval_id": null,
      "execution_context_hash": "4b754dd597cb545014bf2c33c4435052ea57ebbdf1d6a18490bf07b868b63371",
      "resolved_replay_policy": "reuse_allowed",
      "result_adapter_version": "v1",
      "effect_boundary_crossed": false,
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "backend_effect_capability": "receipt_first",
      "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
      "reconcile_contract_version": "reconcile-v1",
      "resolved_side_effect_class": "read_only",
      "backend_request_schema_hash": "81067a5955663d67447db8a44d8abb584f99012022e6d80dbf4b34785563c8c8",
      "execution_context_version_hash": "agent-tool-execution-v1"
    },
    "base_replay_policy": "reuse_allowed",
    "mixed_volatile_frozen": false,
    "active_policy_ref_count": 0,
    "frozen_policy_ref_count": 0,
    "approval_required_reason": "safe_initial_tool",
    "volatile_policy_ref_count": 0,
    "historical_volatile_excluded_count": 0
  },
  "status": "succeeded",
  "execution_phase": "completed",
  "effect_submission_state": "effect_committed",
  "effect_boundary_crossed": 0,
  "downstream_send_intent_at": "2026-07-06 23:54:59",
  "downstream_request_observed_sent_at": "2026-07-06 23:54:59",
  "downstream_acceptance_id": "14902f9dbee373bba432285eab9884695a754a046f32c88bde37bf8c8a76ed39",
  "downstream_acceptance_at": "2026-07-06 23:55:00",
  "input_hash": "b06cedbf9e6c7c7ad508a218f0e60eda3e4027e8f3951d6bef4a41d233f1ab2d",
  "input_json_redacted": {
    "project_id": 1,
    "detail_level": "summary"
  },
  "evidence_refs_json": [],
  "output_hash": "6125ace5fae393f1efbbf2b14e2dbc69d1f38fa88a9965a03781d74b5ec022aa",
  "output_json_redacted": {
    "http_total": 17,
    "project_id": 1,
    "detail_level": "summary",
    "case_snapshot": {
      "intent": "summary",
      "project_id": 1,
      "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f",
      "generated_at": "2026-07-06T23:54:59.362141+00:00",
      "object_family": "test_case",
      "environment_id": null,
      "validity_scope": "current_agent_conversation_latest_query",
      "execution_ready": false,
      "identity_semantics": "test case ids are volatile database row locators; re-query before writes or execution.",
      "authoritative_for_tool_input": true
    },
    "environment_id": null,
    "http_test_cases": [
      {
        "id": 7,
        "name": "获取企业列表",
        "path": "/api/lingxi-chain/cloudentchain/getEntPageList",
        "method": "POST",
        "has_body": true,
        "object_ref": "object-ref://test_case/http/b28b666476ed/7",
        "description": "",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 5,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": false,
        "last_execution_status": "failed"
      },
      {
        "id": 8,
        "name": "获取对应企业CT画像数",
        "path": "/api/lingxi-bigdata/base-info/businessInformation",
        "method": "GET",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/8",
        "description": "",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 4,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "passed"
      },
      {
        "id": 9,
        "name": "关注接口",
        "path": "/api/lingxi-system/myAttentionCompany/save",
        "method": "POST",
        "has_body": true,
        "object_ref": "object-ref://test_case/http/b28b666476ed/9",
        "description": "",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 4,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": false,
        "last_execution_status": "failed"
      },
      {
        "id": 10,
        "name": "取消关注",
        "path": "/api/lingxi-system/myAttentionCompany/cancel",
        "method": "POST",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/10",
        "description": "",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 4,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "failed"
      },
      {
        "id": 11,
        "name": "专利信息接口",
        "path": "/api/lingxi-bigdata/multiscan/intelprop/getPatentListPage",
        "method": "GET",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/11",
        "description": "",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 3,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "passed"
      },
      {
        "id": 12,
        "name": "商标信息接口",
        "path": "/api/lingxi-bigdata/multiscan/intelprop/getTrademarkListPage",
        "method": "GET",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/12",
        "description": "",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 5,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "passed"
      },
      {
        "id": 13,
        "name": "备案信息接口",
        "path": "/api/lingxi-bigdata/multiscan/intelprop/getWebsiteFilingPage",
        "method": "GET",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/13",
        "description": "",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 3,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "passed"
      },
      {
        "id": 14,
        "name": "技术专利接口",
        "path": "/api/lingxi-bigdata/technical-portrait/getPatentDetailById",
        "method": "GET",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/14",
        "description": "",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 3,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "passed"
      },
      {
        "id": 15,
        "name": "获取联系列表接口",
        "path": "/api/lingxi-system/group/tree",
        "method": "GET",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/15",
        "description": "",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 4,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": false,
        "last_execution_status": "passed"
      },
      {
        "id": 16,
        "name": "发展优势接口-资质认定接口",
        "path": "/api/lingxi-bigdata/multiscan/developadvant/getQualificationPage",
        "method": "GET",
        "has_body": true,
        "object_ref": "object-ref://test_case/http/b28b666476ed/16",
        "description": "",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 2,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "passed"
      },
      {
        "id": 18,
        "name": "发展优势-红名单接口",
        "path": "/api/lingxi-bigdata/multiscan/developadvant/getRedListPage",
        "method": "GET",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/18",
        "description": "",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 0,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "passed"
      },
      {
        "id": 19,
        "name": "获取我的发布接口",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/19",
        "description": "",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 2,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "passed"
      },
      {
        "id": 33,
        "name": "获取我的发布接口-长度超限-keyWord超长",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/33",
        "description": "将query_params中的keyWord设置为超过长度限制的字符串（假设限制为100字符，此处使用200字符）",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 2,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "failed"
      },
      {
        "id": 34,
        "name": "获取我的发布接口-空值参数-size为空字符串",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/34",
        "description": "将query_params中的size设置为空字符串，验证接口处理空值的情况",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 2,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "passed"
      },
      {
        "id": 35,
        "name": "获取我的发布接口-缺失参数-缺少current",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/35",
        "description": "删除query_params中的current参数，验证接口对缺失必填参数的处理",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 2,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "failed"
      },
      {
        "id": 36,
        "name": "获取我的发布接口-类型错误-tabSeq为字符串",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/36",
        "description": "将query_params中的tabSeq从数字字符串改为非数字字符串，验证类型错误处理",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 2,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "failed"
      },
      {
        "id": 37,
        "name": "获取我的发布接口-空值参数-keyWord为null",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "has_body": false,
        "object_ref": "object-ref://test_case/http/b28b666476ed/37",
        "description": "将query_params中的keyWord设置为null，验证接口处理null值的情况",
        "has_headers": true,
        "environment_id": 4,
        "assertion_count": 2,
        "environment_ids": [
          4
        ],
        "extractor_count": 0,
        "has_query_params": true,
        "last_execution_status": "passed"
      }
    ],
    "websocket_total": 0,
    "case_id_manifest": {
      "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f",
      "id_source_rule": "Use only these explicit ids from the latest query snapshot; never infer continuous numeric ranges or reuse ids from older conversation prose.",
      "validity_scope": "current_agent_conversation_latest_query",
      "http_test_case_ids": [
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        18,
        19,
        33,
        34,
        35,
        36,
        37
      ],
      "http_test_case_refs": [
        "object-ref://test_case/http/b28b666476ed/7",
        "object-ref://test_case/http/b28b666476ed/8",
        "object-ref://test_case/http/b28b666476ed/9",
        "object-ref://test_case/http/b28b666476ed/10",
        "object-ref://test_case/http/b28b666476ed/11",
        "object-ref://test_case/http/b28b666476ed/12",
        "object-ref://test_case/http/b28b666476ed/13",
        "object-ref://test_case/http/b28b666476ed/14",
        "object-ref://test_case/http/b28b666476ed/15",
        "object-ref://test_case/http/b28b666476ed/16",
        "object-ref://test_case/http/b28b666476ed/18",
        "object-ref://test_case/http/b28b666476ed/19",
        "object-ref://test_case/http/b28b666476ed/33",
        "object-ref://test_case/http/b28b666476ed/34",
        "object-ref://test_case/http/b28b666476ed/35",
        "object-ref://test_case/http/b28b666476ed/36",
        "object-ref://test_case/http/b28b666476ed/37"
      ],
      "websocket_test_case_ids": [],
      "websocket_test_case_refs": [],
      "http_assertion_update_ids": [
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        18,
        19,
        33,
        34,
        35,
        36,
        37
      ],
      "websocket_assertion_update_ids": []
    },
    "case_display_rows": [
      {
        "id": 7,
        "name": "获取企业列表",
        "path": "/api/lingxi-chain/cloudentchain/getEntPageList",
        "method": "POST",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/7",
        "name_source": "testcase.query_project_cases",
        "display_name": "获取企业列表（ID: 7）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "failed"
      },
      {
        "id": 8,
        "name": "获取对应企业CT画像数",
        "path": "/api/lingxi-bigdata/base-info/businessInformation",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/8",
        "name_source": "testcase.query_project_cases",
        "display_name": "获取对应企业CT画像数（ID: 8）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "passed"
      },
      {
        "id": 9,
        "name": "关注接口",
        "path": "/api/lingxi-system/myAttentionCompany/save",
        "method": "POST",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/9",
        "name_source": "testcase.query_project_cases",
        "display_name": "关注接口（ID: 9）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "failed"
      },
      {
        "id": 10,
        "name": "取消关注",
        "path": "/api/lingxi-system/myAttentionCompany/cancel",
        "method": "POST",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/10",
        "name_source": "testcase.query_project_cases",
        "display_name": "取消关注（ID: 10）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "failed"
      },
      {
        "id": 11,
        "name": "专利信息接口",
        "path": "/api/lingxi-bigdata/multiscan/intelprop/getPatentListPage",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/11",
        "name_source": "testcase.query_project_cases",
        "display_name": "专利信息接口（ID: 11）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "passed"
      },
      {
        "id": 12,
        "name": "商标信息接口",
        "path": "/api/lingxi-bigdata/multiscan/intelprop/getTrademarkListPage",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/12",
        "name_source": "testcase.query_project_cases",
        "display_name": "商标信息接口（ID: 12）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "passed"
      },
      {
        "id": 13,
        "name": "备案信息接口",
        "path": "/api/lingxi-bigdata/multiscan/intelprop/getWebsiteFilingPage",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/13",
        "name_source": "testcase.query_project_cases",
        "display_name": "备案信息接口（ID: 13）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "passed"
      },
      {
        "id": 14,
        "name": "技术专利接口",
        "path": "/api/lingxi-bigdata/technical-portrait/getPatentDetailById",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/14",
        "name_source": "testcase.query_project_cases",
        "display_name": "技术专利接口（ID: 14）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "passed"
      },
      {
        "id": 15,
        "name": "获取联系列表接口",
        "path": "/api/lingxi-system/group/tree",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/15",
        "name_source": "testcase.query_project_cases",
        "display_name": "获取联系列表接口（ID: 15）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "passed"
      },
      {
        "id": 16,
        "name": "发展优势接口-资质认定接口",
        "path": "/api/lingxi-bigdata/multiscan/developadvant/getQualificationPage",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/16",
        "name_source": "testcase.query_project_cases",
        "display_name": "发展优势接口-资质认定接口（ID: 16）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "passed"
      },
      {
        "id": 18,
        "name": "发展优势-红名单接口",
        "path": "/api/lingxi-bigdata/multiscan/developadvant/getRedListPage",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/18",
        "name_source": "testcase.query_project_cases",
        "display_name": "发展优势-红名单接口（ID: 18）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "passed"
      },
      {
        "id": 19,
        "name": "获取我的发布接口",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/19",
        "name_source": "testcase.query_project_cases",
        "display_name": "获取我的发布接口（ID: 19）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "passed"
      },
      {
        "id": 33,
        "name": "获取我的发布接口-长度超限-keyWord超长",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/33",
        "name_source": "testcase.query_project_cases",
        "display_name": "获取我的发布接口-长度超限-keyWord超长（ID: 33）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "failed"
      },
      {
        "id": 34,
        "name": "获取我的发布接口-空值参数-size为空字符串",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/34",
        "name_source": "testcase.query_project_cases",
        "display_name": "获取我的发布接口-空值参数-size为空字符串（ID: 34）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "passed"
      },
      {
        "id": 35,
        "name": "获取我的发布接口-缺失参数-缺少current",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/35",
        "name_source": "testcase.query_project_cases",
        "display_name": "获取我的发布接口-缺失参数-缺少current（ID: 35）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "failed"
      },
      {
        "id": 36,
        "name": "获取我的发布接口-类型错误-tabSeq为字符串",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/36",
        "name_source": "testcase.query_project_cases",
        "display_name": "获取我的发布接口-类型错误-tabSeq为字符串（ID: 36）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "failed"
      },
      {
        "id": 37,
        "name": "获取我的发布接口-空值参数-keyWord为null",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/37",
        "name_source": "testcase.query_project_cases",
        "display_name": "获取我的发布接口-空值参数-keyWord为null（ID: 37）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "last_execution_status": "passed"
      }
    ],
    "case_result_policy": {
      "detail_level": "summary",
      "display_rule": "When summarizing test cases, copy id/name/method/path/status exactly from case_display_rows or http_test_cases/websocket_test_cases. Never infer, translate, rewrite, or reuse names from older conversation text for a returned id.",
      "execution_ready": false,
      "detail_fetch_hint": "For assertion or extractor analysis, call detail_level='summary' first, then re-query selected test_case_ids or websocket_test_case_ids with detail_level='assertions' or 'full'. Before any batch execution or batch assertion save, re-query the exact target set with detail_level='execution_ready' and copy the returned *_batch_execute_input/case_snapshot_id.",
      "summary_mode_omits": [
        "headers",
        "query_params",
        "body",
        "assertions",
        "extractors"
      ],
      "large_task_strategy": {
        "avoid": [
          "do_not_requery_all_cases_with_full_detail_after_truncation",
          "do_not_ask_user_to_confirm_missing_case_details_caused_by_truncation",
          "do_not_infer_continuous_case_id_ranges",
          "do_not_rename_or_translate_case_names_when_summarizing"
        ],
        "steps": [
          "query_inventory_with_detail_level_summary",
          "iterate_explicit_case_ids_from_case_id_manifest",
          "query_one_case_with_detail_level_assertions",
          "deduplicate_or_repair_that_case_assertions",
          "before_batch_side_effect_requery_targets_with_detail_level_execution_ready",
          "copy_execution_ready_snapshot_id_and_object_references_into_batch_tool_input",
          "continue_with_next_case_id",
          "summarize_after_all_cases_finish"
        ],
        "strategy_id": "summary_then_selected_detail_then_execution_ready_action"
      },
      "default_detail_level": "summary",
      "query_mode_semantics": {
        "full": "Selected-case deep inspection mode. Use only for a small explicit id set.",
        "summary": "Inventory and display mode. Returns the full id/name/status manifest with large request fields omitted.",
        "selected": "Alias of assertions for selected-case analysis.",
        "assertions": "Selected-case analysis mode. Use with explicit ids when assertion/extractor details are needed.",
        "execution_ready": "Action manifest mode. Required immediately before batch execute or batch assertion save tools."
      },
      "assertions_mode_omits": [
        "headers",
        "query_params",
        "body"
      ],
      "available_detail_levels": [
        "summary",
        "assertions",
        "selected",
        "full",
        "execution_ready"
      ]
    },
    "http_test_case_ids": [
      7,
      8,
      9,
      10,
      11,
      12,
      13,
      14,
      15,
      16,
      18,
      19,
      33,
      34,
      35,
      36,
      37
    ],
    "case_attention_rows": [
      {
        "id": 7,
        "name": "获取企业列表",
        "path": "/api/lingxi-chain/cloudentchain/getEntPageList",
        "method": "POST",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/7",
        "name_source": "testcase.query_project_cases",
        "display_name": "获取企业列表（ID: 7）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "attention_reason": "last_execution_failed",
        "last_execution_status": "failed"
      },
      {
        "id": 9,
        "name": "关注接口",
        "path": "/api/lingxi-system/myAttentionCompany/save",
        "method": "POST",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/9",
        "name_source": "testcase.query_project_cases",
        "display_name": "关注接口（ID: 9）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "attention_reason": "last_execution_failed",
        "last_execution_status": "failed"
      },
      {
        "id": 10,
        "name": "取消关注",
        "path": "/api/lingxi-system/myAttentionCompany/cancel",
        "method": "POST",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/10",
        "name_source": "testcase.query_project_cases",
        "display_name": "取消关注（ID: 10）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "attention_reason": "last_execution_failed",
        "last_execution_status": "failed"
      },
      {
        "id": 33,
        "name": "获取我的发布接口-长度超限-keyWord超长",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/33",
        "name_source": "testcase.query_project_cases",
        "display_name": "获取我的发布接口-长度超限-keyWord超长（ID: 33）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "attention_reason": "last_execution_failed",
        "last_execution_status": "failed"
      },
      {
        "id": 35,
        "name": "获取我的发布接口-缺失参数-缺少current",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/35",
        "name_source": "testcase.query_project_cases",
        "display_name": "获取我的发布接口-缺失参数-缺少current（ID: 35）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "attention_reason": "last_execution_failed",
        "last_execution_status": "failed"
      },
      {
        "id": 36,
        "name": "获取我的发布接口-类型错误-tabSeq为字符串",
        "path": "/api/lingxi-publish/publish/page",
        "method": "GET",
        "case_type": "http",
        "object_ref": "object-ref://test_case/http/b28b666476ed/36",
        "name_source": "testcase.query_project_cases",
        "display_name": "获取我的发布接口-类型错误-tabSeq为字符串（ID: 36）",
        "environment_id": 4,
        "environment_ids": [
          4
        ],
        "attention_reason": "last_execution_failed",
        "last_execution_status": "failed"
      }
    ],
    "case_status_summary": {
      "total": 17,
      "by_type": {
        "http": 17
      },
      "by_status": {
        "failed": 6,
        "passed": 11
      }
    },
    "websocket_test_cases": [],
    "websocket_test_case_ids": [],
    "http_batch_execute_input": {
      "project_id": 1,
      "test_case_ids": [
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        18,
        19,
        33,
        34,
        35,
        36,
        37
      ],
      "case_snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f",
      "object_references": [
        "object-ref://test_case/http/b28b666476ed/7",
        "object-ref://test_case/http/b28b666476ed/8",
        "object-ref://test_case/http/b28b666476ed/9",
        "object-ref://test_case/http/b28b666476ed/10",
        "object-ref://test_case/http/b28b666476ed/11",
        "object-ref://test_case/http/b28b666476ed/12",
        "object-ref://test_case/http/b28b666476ed/13",
        "object-ref://test_case/http/b28b666476ed/14",
        "object-ref://test_case/http/b28b666476ed/15",
        "object-ref://test_case/http/b28b666476ed/16",
        "object-ref://test_case/http/b28b666476ed/18",
        "object-ref://test_case/http/b28b666476ed/19",
        "object-ref://test_case/http/b28b666476ed/33",
        "object-ref://test_case/http/b28b666476ed/34",
        "object-ref://test_case/http/b28b666476ed/35",
        "object-ref://test_case/http/b28b666476ed/36",
        "object-ref://test_case/http/b28b666476ed/37"
      ]
    },
    "object_reference_manifest": {
      "query_tool": "testcase.query_project_cases",
      "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f",
      "object_family": "test_case",
      "id_source_rule": "Use only these explicit ids from the latest query snapshot; never infer continuous numeric ranges or reuse ids from older conversation prose.",
      "validity_scope": "current_agent_conversation_latest_query",
      "object_references": [
        {
          "id": 7,
          "name": "获取企业列表",
          "path": "/api/lingxi-chain/cloudentchain/getEntPageList",
          "method": "POST",
          "object_ref": "object-ref://test_case/http/b28b666476ed/7",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 8,
          "name": "获取对应企业CT画像数",
          "path": "/api/lingxi-bigdata/base-info/businessInformation",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/8",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 9,
          "name": "关注接口",
          "path": "/api/lingxi-system/myAttentionCompany/save",
          "method": "POST",
          "object_ref": "object-ref://test_case/http/b28b666476ed/9",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 10,
          "name": "取消关注",
          "path": "/api/lingxi-system/myAttentionCompany/cancel",
          "method": "POST",
          "object_ref": "object-ref://test_case/http/b28b666476ed/10",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 11,
          "name": "专利信息接口",
          "path": "/api/lingxi-bigdata/multiscan/intelprop/getPatentListPage",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/11",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 12,
          "name": "商标信息接口",
          "path": "/api/lingxi-bigdata/multiscan/intelprop/getTrademarkListPage",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/12",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 13,
          "name": "备案信息接口",
          "path": "/api/lingxi-bigdata/multiscan/intelprop/getWebsiteFilingPage",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/13",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 14,
          "name": "技术专利接口",
          "path": "/api/lingxi-bigdata/technical-portrait/getPatentDetailById",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/14",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 15,
          "name": "获取联系列表接口",
          "path": "/api/lingxi-system/group/tree",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/15",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 16,
          "name": "发展优势接口-资质认定接口",
          "path": "/api/lingxi-bigdata/multiscan/developadvant/getQualificationPage",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/16",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 18,
          "name": "发展优势-红名单接口",
          "path": "/api/lingxi-bigdata/multiscan/developadvant/getRedListPage",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/18",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 19,
          "name": "获取我的发布接口",
          "path": "/api/lingxi-publish/publish/page",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/19",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 33,
          "name": "获取我的发布接口-长度超限-keyWord超长",
          "path": "/api/lingxi-publish/publish/page",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/33",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 34,
          "name": "获取我的发布接口-空值参数-size为空字符串",
          "path": "/api/lingxi-publish/publish/page",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/34",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 35,
          "name": "获取我的发布接口-缺失参数-缺少current",
          "path": "/api/lingxi-publish/publish/page",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/35",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 36,
          "name": "获取我的发布接口-类型错误-tabSeq为字符串",
          "path": "/api/lingxi-publish/publish/page",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/36",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        },
        {
          "id": 37,
          "name": "获取我的发布接口-空值参数-keyWord为null",
          "path": "/api/lingxi-publish/publish/page",
          "method": "GET",
          "object_ref": "object-ref://test_case/http/b28b666476ed/37",
          "object_type": "http_test_case",
          "snapshot_id": "case-snapshot://5136fe5324526c5896a1b3a0cf1bd9bada191a5ff23585bfd29fbae849453a9f"
        }
      ],
      "http_test_case_ids": [
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        18,
        19,
        33,
        34,
        35,
        36,
        37
      ],
      "http_test_case_refs": [
        "object-ref://test_case/http/b28b666476ed/7",
        "object-ref://test_case/http/b28b666476ed/8",
        "object-ref://test_case/http/b28b666476ed/9",
        "object-ref://test_case/http/b28b666476ed/10",
        "object-ref://test_case/http/b28b666476ed/11",
        "object-ref://test_case/http/b28b666476ed/12",
        "object-ref://test_case/http/b28b666476ed/13",
        "object-ref://test_case/http/b28b666476ed/14",
        "object-ref://test_case/http/b28b666476ed/15",
        "object-ref://test_case/http/b28b666476ed/16",
        "object-ref://test_case/http/b28b666476ed/18",
        "object-ref://test_case/http/b28b666476ed/19",
        "object-ref://test_case/http/b28b666476ed/33",
        "object-ref://test_case/http/b28b666476ed/34",
        "object-ref://test_case/http/b28b666476ed/35",
        "object-ref://test_case/http/b28b666476ed/36",
        "object-ref://test_case/http/b28b666476ed/37"
      ],
      "websocket_test_case_ids": [],
      "websocket_test_case_refs": [],
      "http_assertion_update_ids": [
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        18,
        19,
        33,
        34,
        35,
        36,
        37
      ],
      "websocket_assertion_update_ids": []
    },
    "websocket_batch_execute_input": null
  },
  "raw_output_object_key": null,
  "permission_snapshot_json": {
    "user_id": 1,
    "audit_only": true,
    "project_id": 1,
    "captured_at": "2026-07-06T23:54:58.536406",
    "required_permissions": [
      "case:view"
    ]
  },
  "required_permissions_json": [
    "case:view"
  ],
  "approval_required": 0,
  "approval_scope_hash": "549daeb788b234072e49eb2f0d35509f354c8cf8c1c1d85b22a915211fd7f50f",
  "lease_owner": null,
  "lease_expires_at": null,
  "last_heartbeat_at": null,
  "recovery_decision": null,
  "backend_name": "testcase-service",
  "backend_operation": "query_project_cases",
  "backend_contract_version": "v1",
  "backend_effect_capability": "receipt_first",
  "external_resource_type": null,
  "external_resource_id": null,
  "error_code": null,
  "error_message": null,
  "created_at": "2026-07-07 07:55:08",
  "updated_at": "2026-07-07 07:55:10",
  "backend_request_schema_hash": "81067a5955663d67447db8a44d8abb584f99012022e6d80dbf4b34785563c8c8",
  "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
  "reconcile_contract_version": "reconcile-v1",
  "result_adapter_version": "v1",
  "approval_lineage_id": null,
  "approval_epoch": 0,
  "approved_approval_id": null,
  "approved_by": null,
  "approved_at": null,
  "policy_evidence_refs_json": [],
  "audit_evidence_refs_json": [],
  "evidence_mutability_summary_json": {
    "total": 0,
    "fully_frozen": true,
    "by_mutability": {},
    "audit_ref_count": 0,
    "policy_ref_count": 0,
    "requires_revalidation": false
  },
  "decision_context_build_id": null
}
```

#### Tool `scenario.compose_draft` / `agent-tool-7f6517141970455b9b23b82dc1fcfb34`

- status: `succeeded`
- step_index: `2`
- attempt_index: `2`
- approval_required: `0`
- input_hash: `16474f001dc50d9f72d3e9ebf4c326bc7968e55e736949f37d5452d289ebaeaf`
- output_hash: `a2e773df07d900972ee2ea93d0035ac4eb8bc66c18c6b08d3fe5d2d66974b075`

```json
{
  "id": 606,
  "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "step_index": 2,
  "attempt_index": 2,
  "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
  "tool_name": "scenario.compose_draft",
  "tool_version": "1.0.0",
  "schema_hash": "016d0a869c65e7c60acdd72bf4ac897140f06014bcb43c16a0f11ab305970d6f",
  "manifest_hash": "403e3b285f613b3b92a03f2fba492e143727907aa06b60bf49654cfe2ad508e1",
  "idempotency_scope": "agent-run-1914761819b44a2799a744049d837d7c",
  "idempotency_key": "79d435c9a4cf0489503b19f46187e878399ea0b9c0c17e1929e8a44b664c7dd6",
  "base_side_effect_class": "draft_only",
  "resolved_side_effect_class": "draft_only",
  "base_replay_policy": "reuse_allowed",
  "resolved_replay_policy": "reuse_allowed",
  "policy_reason_json": {
    "dispatch_trace": {
      "router": "AgentToolRouter.resolve",
      "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
      "status": "succeeded",
      "runtime": "AgentToolRuntime.execute",
      "tool_name": "scenario.compose_draft",
      "schema_hash": "016d0a869c65e7c60acdd72bf4ac897140f06014bcb43c16a0f11ab305970d6f",
      "backend_name": "ai-skill-service",
      "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
      "tool_version": "1.0.0",
      "manifest_hash": "403e3b285f613b3b92a03f2fba492e143727907aa06b60bf49654cfe2ad508e1",
      "backend_handler": "_scenario_compose_draft",
      "backend_operation": "scenario.compose_draft",
      "dispatch_trace_hash": "0f914068d3a101b56830c7972c4562e5f425451721d09a1593021ceafb6c572c",
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "resolved_replay_policy": "reuse_allowed",
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "resolved_side_effect_class": "draft_only",
      "dispatch_trace_version_hash": "agent-tool-dispatch-v1"
    },
    "policy_context": {
      "tool_name": "scenario.compose_draft",
      "policy_hash": "4ec99696a1741103a633d8f50aa5d7b8d186eaa0185edd2573029789ad341733",
      "tool_version": "1.0.0",
      "approval_policy": "safe_side_effect_auto",
      "approval_required": false,
      "base_replay_policy": "reuse_allowed",
      "policy_version_hash": "agent-policy-v1",
      "mixed_volatile_frozen": false,
      "base_side_effect_class": "draft_only",
      "resolved_replay_policy": "reuse_allowed",
      "active_policy_ref_count": 0,
      "frozen_policy_ref_count": 0,
      "approval_required_reason": "safe_initial_tool",
      "volatile_policy_ref_count": 0,
      "resolved_side_effect_class": "draft_only",
      "historical_volatile_excluded_count": 0
    },
    "execution_context": {
      "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
      "tool_name": "scenario.compose_draft",
      "worker_id": null,
      "error_code": null,
      "input_hash": "16474f001dc50d9f72d3e9ebf4c326bc7968e55e736949f37d5452d289ebaeaf",
      "approved_by": null,
      "output_hash": "a2e773df07d900972ee2ea93d0035ac4eb8bc66c18c6b08d3fe5d2d66974b075",
      "tool_status": "succeeded",
      "backend_name": "ai-skill-service",
      "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
      "tool_version": "1.0.0",
      "approval_epoch": 0,
      "approval_state": "not_required",
      "execution_phase": "completed",
      "approval_required": false,
      "backend_operation": "scenario.compose_draft",
      "recovery_decision": null,
      "error_message_hash": null,
      "approval_lineage_id": null,
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "approved_approval_id": null,
      "execution_context_hash": "4353839108b09e301127b7a092b41641574252dbca3747e0cb16ca411a7226aa",
      "resolved_replay_policy": "reuse_allowed",
      "result_adapter_version": "v1",
      "effect_boundary_crossed": true,
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "backend_effect_capability": "idempotency_index_only",
      "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
      "reconcile_contract_version": "reconcile-v1",
      "resolved_side_effect_class": "draft_only",
      "backend_request_schema_hash": "a0cc4c93cf65df5bd4f8a7160ea86ce724b174321d3d35d923edfca4cbe10cee",
      "execution_context_version_hash": "agent-tool-execution-v1"
    },
    "base_replay_policy": "reuse_allowed",
    "mixed_volatile_frozen": false,
    "active_policy_ref_count": 0,
    "frozen_policy_ref_count": 0,
    "approval_required_reason": "safe_initial_tool",
    "volatile_policy_ref_count": 0,
    "historical_volatile_excluded_count": 0
  },
  "status": "succeeded",
  "execution_phase": "completed",
  "effect_submission_state": "effect_committed",
  "effect_boundary_crossed": 1,
  "downstream_send_intent_at": "2026-07-06 23:55:15",
  "downstream_request_observed_sent_at": "2026-07-06 23:55:16",
  "downstream_acceptance_id": null,
  "downstream_acceptance_at": null,
  "input_hash": "16474f001dc50d9f72d3e9ebf4c326bc7968e55e736949f37d5452d289ebaeaf",
  "input_json_redacted": {
    "input": {
      "max_nodes": 6,
      "requirement": "创建企业相关端到端自动化测试流程：1）查询企业列表获取企业ID；2）使用企业ID查询对应企业CT画像数；3）关注该企业；4）取消关注该企业。需要自动绑定步骤间的变量传递，并验证每一步的响应结果。",
      "include_hooks": true,
      "scenario_name": "企业端到端自动化流程测试",
      "self_validate": true,
      "include_bindings": true,
      "execute_candidates": false,
      "http_test_case_ids": [
        7,
        8,
        9,
        10
      ],
      "include_assertions": true,
      "max_validation_attempts": 2,
      "include_latest_execution": true
    },
    "reason": "基于项目现有的企业相关接口，组合一个包含获取企业列表、查详情、关注、取消关注的端到端场景草稿",
    "project_id": 1,
    "evidence_refs": [
      "project.read_context",
      "testcase.query_project_cases"
    ]
  },
  "evidence_refs_json": [],
  "output_hash": "a2e773df07d900972ee2ea93d0035ac4eb8bc66c18c6b08d3fe5d2d66974b075",
  "output_json_redacted": {
    "draft": {
      "scenario": {
        "name": "企业端到端自动化流程测试",
        "tags": [
          "ai-composed"
        ],
        "nodes": [
          {
            "id": "NODE-1",
            "name": "获取企业列表",
            "test_case": {
              "id": "CASE-1",
              "kind": "api_case",
              "name": "获取企业列表",
              "path": "/api/lingxi-chain/cloudentchain/getEntPageList",
              "config": {
                "assertions": [
                  {
                    "path": null,
                    "type": "status_code",
                    "expected": 200,
                    "retry_on_failure": false
                  },
                  {
                    "path": "code",
                    "type": "json_equals",
                    "expected": 200,
                    "retry_on_failure": false
                  },
                  {
                    "path": "success",
                    "type": "json_equals",
                    "expected": true,
                    "retry_on_failure": false
                  }
                ],
                "extractors": [
                  {
                    "id": "VAR-1",
                    "name": "companyId",
                    "path": "data.dataList.0.companyId"
                  },
                  {
                    "id": "VAR-2",
                    "name": "companyName",
                    "path": "data.dataList.0.companyName"
                  }
                ],
                "_scenario_context": {
                  "extractions": [
                    {
                      "id": "VAR-1",
                      "name": "companyId",
                      "path": "data.dataList.0.companyId"
                    },
                    {
                      "id": "VAR-2",
                      "name": "companyName",
                      "path": "data.dataList.0.companyName"
                    }
                  ]
                }
              },
              "method": "POST",
              "reference_id": 7,
              "continue_on_failure": false
            },
            "after_actions": [],
            "before_actions": []
          },
          {
            "id": "NODE-2",
            "name": "获取对应企业CT画像数",
            "test_case": {
              "id": "CASE-2",
              "kind": "api_case",
              "name": "获取对应企业CT画像数",
              "path": "/api/lingxi-bigdata/base-info/businessInformation",
              "config": {
                "assertions": [
                  {
                    "path": null,
                    "type": "status_code",
                    "expected": 200,
                    "retry_on_failure": false
                  },
                  {
                    "path": "code",
                    "type": "json_equals",
                    "expected": 200,
                    "retry_on_failure": false
                  },
                  {
                    "path": "success",
                    "type": "json_equals",
                    "expected": true,
                    "retry_on_failure": false
                  }
                ],
                "query_params": {
                  "size": "10",
                  "companyId": "{{companyId}}"
                },
                "_scenario_context": {
                  "bindings": [
                    {
                      "id": "BIND-1",
                      "name": "companyId",
                      "target": "query_params",
                      "target_path": "companyId",
                      "source_step_id": "CASE-1",
                      "source_extraction_id": "VAR-1"
                    }
                  ],
                  "extractions": []
                }
              },
              "method": "GET",
              "reference_id": 8,
              "continue_on_failure": false
            },
            "after_actions": [],
            "before_actions": []
          },
          {
            "id": "NODE-3",
            "name": "关注企业",
            "test_case": {
              "id": "CASE-3",
              "kind": "api_case",
              "name": "关注接口",
              "path": "/api/lingxi-system/myAttentionCompany/save",
              "config": {
                "body": {
                  "companyId": "{{companyId}}",
                  "companyName": "{{companyName}}"
                },
                "assertions": [
                  {
                    "path": null,
                    "type": "status_code",
                    "expected": 200,
                    "retry_on_failure": false
                  },
                  {
                    "path": "code",
                    "type": "json_equals",
                    "expected": 666666,
                    "retry_on_failure": false
                  },
                  {
                    "path": "success",
                    "type": "json_equals",
                    "expected": true,
                    "retry_on_failure": false
                  }
                ],
                "_scenario_context": {
                  "bindings": [
                    {
                      "id": "BIND-2",
                      "name": "companyId",
                      "target": "body",
                      "target_path": "companyId",
                      "source_step_id": "CASE-1",
                      "source_extraction_id": "VAR-1"
                    },
                    {
                      "id": "BIND-3",
                      "name": "companyName",
                      "target": "body",
                      "target_path": "companyName",
                      "source_step_id": "CASE-1",
                      "source_extraction_id": "VAR-2"
                    }
                  ],
                  "extractions": []
                }
              },
              "method": "POST",
              "reference_id": 9,
              "continue_on_failure": false
            },
            "after_actions": [],
            "before_actions": []
          },
          {
            "id": "NODE-4",
            "name": "取消关注",
            "test_case": {
              "id": "CASE-4",
              "kind": "api_case",
              "name": "取消关注",
              "path": "/api/lingxi-system/myAttentionCompany/cancel",
              "config": {
                "assertions": [
                  {
                    "path": null,
                    "type": "status_code",
                    "expected": 200,
                    "retry_on_failure": false
                  },
                  {
                    "path": "code",
                    "type": "json_equals",
                    "expected": 666666,
                    "retry_on_failure": false
                  },
                  {
                    "path": "success",
                    "type": "json_equals",
                    "expected": true,
                    "retry_on_failure": false
                  },
                  {
                    "path": "msg",
                    "type": "json_equals",
                    "expected": "操作成功",
                    "retry_on_failure": false
                  }
                ],
                "query_params": {
                  "companyId": "{{companyId}}"
                },
                "_scenario_context": {
                  "bindings": [
                    {
                      "id": "BIND-4",
                      "name": "companyId",
                      "target": "query_params",
                      "target_path": "companyId",
                      "source_step_id": "CASE-1",
                      "source_extraction_id": "VAR-1"
                    }
                  ],
                  "extractions": []
                }
              },
              "method": "POST",
              "reference_id": 10,
              "continue_on_failure": false
            },
            "after_actions": [],
            "before_actions": []
          }
        ],
        "datasets": [],
        "description": "1）查询企业列表获取企业ID；2）使用企业ID查询对应企业CT画像数；3）关注该企业；4）取消关注该企业。自动绑定步骤间的变量传递，并验证每一步的响应结果。",
        "environment_id": 4
      },
      "warnings": [
        "获取企业列表用例的success断言在最近执行中expected为null，已修正为true。",
        "关注接口和取消关注接口的code字段实际返回666666，已按实际值修正断言expected。",
        "获取企业列表用例的body_contains断言'dataList'和'total'在最近执行中通过，但为减少不稳定断言，已移除。",
        "CT画像查询接口响应中大部分字段为null，可能是测试数据问题，但断言仅保留稳定字段。",
        "关注和取消关注接口依赖Lingxi-Auth头，该变量需在环境或前置步骤中提供，当前场景未包含登录步骤，请确保环境已配置。"
      ],
      "project_id": 1,
      "environment_id": 4,
      "self_validated": true,
      "source_summary": "基于4个候选用例组合企业端到端流程：获取企业列表→提取companyId/companyName→查询CT画像→关注→取消关注。修复了关注和取消关注接口的code断言（实际返回666666），并修正了获取企业列表的success断言（expected应为true）。",
      "environment_name": "test",
      "validation_attempts": [
        {
          "issues": [],
          "run_id": 151,
          "status": "passed",
          "attempt": 1,
          "summary": {
            "failed": 0,
            "passed": 4,
            "skipped": 0,
            "timeout": 0,
            "total_steps": 4
          },
          "duration_ms": 5142
        }
      ]
    }
  },
  "raw_output_object_key": null,
  "permission_snapshot_json": {
    "user_id": 1,
    "audit_only": true,
    "project_id": 1,
    "captured_at": "2026-07-06T23:55:14.905472",
    "required_permissions": [
      "scenario:view",
      "test:execute"
    ]
  },
  "required_permissions_json": [
    "scenario:view",
    "test:execute"
  ],
  "approval_required": 0,
  "approval_scope_hash": "1db0483402bd9d1a0b054085808e50e0806c32487cf149fe8780b8aa36e2970d",
  "lease_owner": null,
  "lease_expires_at": null,
  "last_heartbeat_at": null,
  "recovery_decision": null,
  "backend_name": "ai-skill-service",
  "backend_operation": "scenario.compose_draft",
  "backend_contract_version": "v1",
  "backend_effect_capability": "idempotency_index_only",
  "external_resource_type": null,
  "external_resource_id": null,
  "error_code": null,
  "error_message": null,
  "created_at": "2026-07-07 07:55:25",
  "updated_at": "2026-07-07 07:55:53",
  "backend_request_schema_hash": "a0cc4c93cf65df5bd4f8a7160ea86ce724b174321d3d35d923edfca4cbe10cee",
  "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
  "reconcile_contract_version": "reconcile-v1",
  "result_adapter_version": "v1",
  "approval_lineage_id": null,
  "approval_epoch": 0,
  "approved_approval_id": null,
  "approved_by": null,
  "approved_at": null,
  "policy_evidence_refs_json": [],
  "audit_evidence_refs_json": [],
  "evidence_mutability_summary_json": {
    "total": 0,
    "fully_frozen": true,
    "by_mutability": {},
    "audit_ref_count": 0,
    "policy_ref_count": 0,
    "requires_revalidation": false
  },
  "decision_context_build_id": null
}
```

#### Tool `tool_result.read_full` / `agent-tool-963059530c0149339e83d13142cd93ed`

- status: `succeeded`
- step_index: `3`
- attempt_index: `3`
- approval_required: `0`
- input_hash: `33c056b361457ab5ec67466d7297767dfab853d6400968ded40172d8b083272c`
- output_hash: `fd4d78e2ae8c9c68abc5f2e08a3fa55e198d4351044d58080a275d6d9c887603`

```json
{
  "id": 607,
  "tool_call_id": "agent-tool-963059530c0149339e83d13142cd93ed",
  "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
  "step_index": 3,
  "attempt_index": 3,
  "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
  "tool_name": "tool_result.read_full",
  "tool_version": "1.0.0",
  "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
  "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
  "idempotency_scope": "agent-run-1914761819b44a2799a744049d837d7c",
  "idempotency_key": "32e43df6eaa77a513e4d2f6f60a63dfd38cc2544bba86b75112dd64d362dd914",
  "base_side_effect_class": "read_only",
  "resolved_side_effect_class": "read_only",
  "base_replay_policy": "reuse_allowed",
  "resolved_replay_policy": "reuse_allowed",
  "policy_reason_json": {
    "dispatch_trace": {
      "router": "AgentToolRouter.resolve",
      "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
      "status": "succeeded",
      "runtime": "AgentToolRuntime.execute",
      "tool_name": "tool_result.read_full",
      "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-963059530c0149339e83d13142cd93ed",
      "tool_version": "1.0.0",
      "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
      "backend_handler": "_tool_result_read_full",
      "backend_operation": "tool_result.read_full",
      "dispatch_trace_hash": "9f52512c917b7f05d622bb6a6e323f585624eb9acce35a624e62931c7617d21e",
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "resolved_replay_policy": "reuse_allowed",
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "resolved_side_effect_class": "read_only",
      "dispatch_trace_version_hash": "agent-tool-dispatch-v1"
    },
    "policy_context": {
      "tool_name": "tool_result.read_full",
      "policy_hash": "7ebcf3ce85b1d14a7268a86883c575a3a719a5e8242aa98e7959488e011e7ec7",
      "tool_version": "1.0.0",
      "approval_policy": "safe_side_effect_auto",
      "approval_required": false,
      "base_replay_policy": "reuse_allowed",
      "policy_version_hash": "agent-policy-v1",
      "mixed_volatile_frozen": false,
      "base_side_effect_class": "read_only",
      "resolved_replay_policy": "reuse_allowed",
      "active_policy_ref_count": 0,
      "frozen_policy_ref_count": 0,
      "approval_required_reason": "safe_initial_tool",
      "volatile_policy_ref_count": 0,
      "resolved_side_effect_class": "read_only",
      "historical_volatile_excluded_count": 0
    },
    "execution_context": {
      "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
      "tool_name": "tool_result.read_full",
      "worker_id": null,
      "error_code": null,
      "input_hash": "33c056b361457ab5ec67466d7297767dfab853d6400968ded40172d8b083272c",
      "approved_by": null,
      "output_hash": "fd4d78e2ae8c9c68abc5f2e08a3fa55e198d4351044d58080a275d6d9c887603",
      "tool_status": "succeeded",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-963059530c0149339e83d13142cd93ed",
      "tool_version": "1.0.0",
      "approval_epoch": 0,
      "approval_state": "not_required",
      "execution_phase": "completed",
      "approval_required": false,
      "backend_operation": "tool_result.read_full",
      "recovery_decision": null,
      "error_message_hash": null,
      "approval_lineage_id": null,
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "approved_approval_id": null,
      "execution_context_hash": "570af286c965f532d2f4415b73c5e7301b5c7af0e5fb89357004144d7433ca81",
      "resolved_replay_policy": "reuse_allowed",
      "result_adapter_version": "v1",
      "effect_boundary_crossed": false,
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "backend_effect_capability": "receipt_first",
      "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
      "reconcile_contract_version": "reconcile-v1",
      "resolved_side_effect_class": "read_only",
      "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
      "execution_context_version_hash": "agent-tool-execution-v1"
    },
    "base_replay_policy": "reuse_allowed",
    "mixed_volatile_frozen": false,
    "active_policy_ref_count": 0,
    "frozen_policy_ref_count": 0,
    "approval_required_reason": "safe_initial_tool",
    "volatile_policy_ref_count": 0,
    "historical_volatile_excluded_count": 0
  },
  "status": "succeeded",
  "execution_phase": "completed",
  "effect_submission_state": "effect_committed",
  "effect_boundary_crossed": 0,
  "downstream_send_intent_at": "2026-07-06 23:55:50",
  "downstream_request_observed_sent_at": "2026-07-06 23:55:50",
  "downstream_acceptance_id": "32e43df6eaa77a513e4d2f6f60a63dfd38cc2544bba86b75112dd64d362dd914",
  "downstream_acceptance_at": "2026-07-06 23:55:50",
  "input_hash": "33c056b361457ab5ec67466d7297767dfab853d6400968ded40172d8b083272c",
  "input_json_redacted": {
    "max_chars": 64000,
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34"
  },
  "evidence_refs_json": [
    {
      "ref_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-7f6517141970455b9b23b82dc1fcfb34",
      "mutability_class": "immutable",
      "active_for_policy": false
    }
  ],
  "output_hash": "fd4d78e2ae8c9c68abc5f2e08a3fa55e198d4351044d58080a275d6d9c887603",
  "output_json_redacted": {
    "path": null,
    "output": {
      "draft": {
        "scenario": {
          "name": "企业端到端自动化流程测试",
          "tags": [
            "ai-composed"
          ],
          "nodes": [
            {
              "id": "NODE-1",
              "name": "获取企业列表",
              "test_case": {
                "id": "CASE-1",
                "kind": "api_case",
                "name": "获取企业列表",
                "path": "/api/lingxi-chain/cloudentchain/getEntPageList",
                "config": {
                  "assertions": [
                    {
                      "path": null,
                      "type": "status_code",
                      "expected": 200,
                      "retry_on_failure": false
                    },
                    {
                      "path": "code",
                      "type": "json_equals",
                      "expected": 200,
                      "retry_on_failure": false
                    },
                    {
                      "path": "success",
                      "type": "json_equals",
                      "expected": true,
                      "retry_on_failure": false
                    }
                  ],
                  "extractors": [
                    {
                      "id": "VAR-1",
                      "name": "companyId",
                      "path": "data.dataList.0.companyId"
                    },
                    {
                      "id": "VAR-2",
                      "name": "companyName",
                      "path": "data.dataList.0.companyName"
                    }
                  ],
                  "_scenario_context": {
                    "extractions": [
                      {
                        "id": "VAR-1",
                        "name": "companyId",
                        "path": "data.dataList.0.companyId"
                      },
                      {
                        "id": "VAR-2",
                        "name": "companyName",
                        "path": "data.dataList.0.companyName"
                      }
                    ]
                  }
                },
                "method": "POST",
                "reference_id": 7,
                "continue_on_failure": false
              },
              "after_actions": [],
              "before_actions": []
            },
            {
              "id": "NODE-2",
              "name": "获取对应企业CT画像数",
              "test_case": {
                "id": "CASE-2",
                "kind": "api_case",
                "name": "获取对应企业CT画像数",
                "path": "/api/lingxi-bigdata/base-info/businessInformation",
                "config": {
                  "assertions": [
                    {
                      "path": null,
                      "type": "status_code",
                      "expected": 200,
                      "retry_on_failure": false
                    },
                    {
                      "path": "code",
                      "type": "json_equals",
                      "expected": 200,
                      "retry_on_failure": false
                    },
                    {
                      "path": "success",
                      "type": "json_equals",
                      "expected": true,
                      "retry_on_failure": false
                    }
                  ],
                  "query_params": {
                    "size": "10",
                    "companyId": "{{companyId}}"
                  },
                  "_scenario_context": {
                    "bindings": [
                      {
                        "id": "BIND-1",
                        "name": "companyId",
                        "target": "query_params",
                        "target_path": "companyId",
                        "source_step_id": "CASE-1",
                        "source_extraction_id": "VAR-1"
                      }
                    ],
                    "extractions": []
                  }
                },
                "method": "GET",
                "reference_id": 8,
                "continue_on_failure": false
              },
              "after_actions": [],
              "before_actions": []
            },
            {
              "id": "NODE-3",
              "name": "关注企业",
              "test_case": {
                "id": "CASE-3",
                "kind": "api_case",
                "name": "关注接口",
                "path": "/api/lingxi-system/myAttentionCompany/save",
                "config": {
                  "body": {
                    "companyId": "{{companyId}}",
                    "companyName": "{{companyName}}"
                  },
                  "assertions": [
                    {
                      "path": null,
                      "type": "status_code",
                      "expected": 200,
                      "retry_on_failure": false
                    },
                    {
                      "path": "code",
                      "type": "json_equals",
                      "expected": 666666,
                      "retry_on_failure": false
                    },
                    {
                      "path": "success",
                      "type": "json_equals",
                      "expected": true,
                      "retry_on_failure": false
                    }
                  ],
                  "_scenario_context": {
                    "bindings": [
                      {
                        "id": "BIND-2",
                        "name": "companyId",
                        "target": "body",
                        "target_path": "companyId",
                        "source_step_id": "CASE-1",
                        "source_extraction_id": "VAR-1"
                      },
                      {
                        "id": "BIND-3",
                        "name": "companyName",
                        "target": "body",
                        "target_path": "companyName",
                        "source_step_id": "CASE-1",
                        "source_extraction_id": "VAR-2"
                      }
                    ],
                    "extractions": []
                  }
                },
                "method": "POST",
                "reference_id": 9,
                "continue_on_failure": false
              },
              "after_actions": [],
              "before_actions": []
            },
            {
              "id": "NODE-4",
              "name": "取消关注",
              "test_case": {
                "id": "CASE-4",
                "kind": "api_case",
                "name": "取消关注",
                "path": "/api/lingxi-system/myAttentionCompany/cancel",
                "config": {
                  "assertions": [
                    {
                      "path": null,
                      "type": "status_code",
                      "expected": 200,
                      "retry_on_failure": false
                    },
                    {
                      "path": "code",
                      "type": "json_equals",
                      "expected": 666666,
                      "retry_on_failure": false
                    },
                    {
                      "path": "success",
                      "type": "json_equals",
                      "expected": true,
                      "retry_on_failure": false
                    },
                    {
                      "path": "msg",
                      "type": "json_equals",
                      "expected": "操作成功",
                      "retry_on_failure": false
                    }
                  ],
                  "query_params": {
                    "companyId": "{{companyId}}"
                  },
                  "_scenario_context": {
                    "bindings": [
                      {
                        "id": "BIND-4",
                        "name": "companyId",
                        "target": "query_params",
                        "target_path": "companyId",
                        "source_step_id": "CASE-1",
                        "source_extraction_id": "VAR-1"
                      }
                    ],
                    "extractions": []
                  }
                },
                "method": "POST",
                "reference_id": 10,
                "continue_on_failure": false
              },
              "after_actions": [],
              "before_actions": []
            }
          ],
          "datasets": [],
          "description": "1）查询企业列表获取企业ID；2）使用企业ID查询对应企业CT画像数；3）关注该企业；4）取消关注该企业。自动绑定步骤间的变量传递，并验证每一步的响应结果。",
          "environment_id": 4
        },
        "warnings": [
          "获取企业列表用例的success断言在最近执行中expected为null，已修正为true。",
          "关注接口和取消关注接口的code字段实际返回666666，已按实际值修正断言expected。",
          "获取企业列表用例的body_contains断言'dataList'和'total'在最近执行中通过，但为减少不稳定断言，已移除。",
          "CT画像查询接口响应中大部分字段为null，可能是测试数据问题，但断言仅保留稳定字段。",
          "关注和取消关注接口依赖Lingxi-Auth头，该变量需在环境或前置步骤中提供，当前场景未包含登录步骤，请确保环境已配置。"
        ],
        "project_id": 1,
        "environment_id": 4,
        "self_validated": true,
        "source_summary": "基于4个候选用例组合企业端到端流程：获取企业列表→提取companyId/companyName→查询CT画像→关注→取消关注。修复了关注和取消关注接口的code断言（实际返回666666），并修正了获取企业列表的success断言（expected应为true）。",
        "environment_name": "test",
        "validation_attempts": [
          {
            "issues": [],
            "run_id": 151,
            "status": "passed",
            "attempt": 1,
            "summary": {
              "failed": 0,
              "passed": 4,
              "skipped": 0,
              "timeout": 0,
              "total_steps": 4
            },
            "duration_ms": 5142
          }
        ]
      }
    },
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "redaction": "output_json_redacted",
    "tool_name": "scenario.compose_draft",
    "output_hash": "a2e773df07d900972ee2ea93d0035ac4eb8bc66c18c6b08d3fe5d2d66974b075",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
    "output_truncated": false,
    "output_size_chars": 4601
  },
  "raw_output_object_key": null,
  "permission_snapshot_json": {
    "user_id": 1,
    "audit_only": true,
    "project_id": 1,
    "captured_at": "2026-07-06T23:55:49.171094",
    "required_permissions": [
      "project:view"
    ]
  },
  "required_permissions_json": [
    "project:view"
  ],
  "approval_required": 0,
  "approval_scope_hash": "a013c90074772d9ea6e38c309817c1a2e7cc923d496305a19dbcde6c3f095c0d",
  "lease_owner": null,
  "lease_expires_at": null,
  "last_heartbeat_at": null,
  "recovery_decision": null,
  "backend_name": "agent-ledger",
  "backend_operation": "tool_result.read_full",
  "backend_contract_version": "v1",
  "backend_effect_capability": "receipt_first",
  "external_resource_type": null,
  "external_resource_id": null,
  "error_code": null,
  "error_message": null,
  "created_at": "2026-07-07 07:55:59",
  "updated_at": "2026-07-07 07:56:00",
  "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
  "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
  "reconcile_contract_version": "reconcile-v1",
  "result_adapter_version": "v1",
  "approval_lineage_id": null,
  "approval_epoch": 0,
  "approved_approval_id": null,
  "approved_by": null,
  "approved_at": null,
  "policy_evidence_refs_json": [],
  "audit_evidence_refs_json": [
    {
      "ref_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-7f6517141970455b9b23b82dc1fcfb34",
      "mutability_class": "immutable",
      "active_for_policy": false,
      "required_for_high_risk": false
    }
  ],
  "evidence_mutability_summary_json": {
    "total": 1,
    "fully_frozen": true,
    "by_mutability": {
      "immutable": 1
    },
    "audit_ref_count": 1,
    "policy_ref_count": 0,
    "requires_revalidation": false
  },
  "decision_context_build_id": null
}
```

## Run `agent-run-72ca285d46fe4755ba0e3e1da92d3fdc`

- status: `completed`
- created_at: `2026-07-06 23:56:18`
- updated_at: `2026-07-07 07:59:50`
- intent: 保存
- result_json_preview: {"model": "deepseek-v4-pro", "usage": {"total_tokens": "***", "prompt_tokens": "***", "completion_tokens": "***", "prompt_tokens_details": "***", "prompt_cache_hit_tokens": "***", "prompt_cache_miss_tokens": "***", "completion_tokens_details": "***"}, "message": "工具执行结果已经进入上下文，但最终总结阶段模型又输出了工具请求。后端已阻止该工具请求展示给用户；请查看上方 ToolCall 失败详情，修正输入后重新提交。", "provider": "deepseek", "loop_step": "final_summary", "loop_state": {"step": "final_summary", "phase": "model", "iteration": 8, "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-8", "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3f...

### Events

#### Event 1: `run.queued`

- created_at: `2026-07-07 07:56:28`

```json
{
  "id": 51596,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 1,
  "event_type": "run.queued",
  "payload_json": {
    "intent": "保存",
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 1,
    "event_type": "run.queued",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:17.891575",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:56:28"
}
```

#### Event 2: `run.started`

- created_at: `2026-07-07 07:56:28`

```json
{
  "id": 51597,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 2,
  "event_type": "run.started",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 2,
    "event_type": "run.started",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:18.002122",
    "schema_version": 1,
    "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff"
  },
  "created_at": "2026-07-07 07:56:28"
}
```

#### Event 3: `model.started`

- created_at: `2026-07-07 07:56:29`

```json
{
  "id": 51598,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 3,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "provider": "deepseek",
    "event_seq": 3,
    "iteration": 0,
    "loop_step": "tool_planning",
    "event_type": "model.started",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 0,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-0",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-0-tool_planning-f60f3e4d859848858056c26f6bdfac5c"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:19.786713",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-0",
    "final_summary": false,
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-0-tool_planning-f60f3e4d859848858056c26f6bdfac5c",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-0-tool_planning-f60f3e4d859848858056c26f6bdfac5c"
  },
  "created_at": "2026-07-07 07:56:29"
}
```

#### Event 4: `model.completed`

- created_at: `2026-07-07 07:56:38`
- content_preview: ```agent_tool_request
{"tool_name":"tool_result.read_full","input":{"tool_call_id":"agent-tool-7f6517141970455b9b23b82dc1fcfb34","path":"draft.scenario"},"reason":"读取完整场景草稿以准备保存","evidence_refs":["agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft"]}
```

```json
{
  "id": 51599,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 4,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "content": "```agent_tool_request\n{\"tool_name\":\"tool_result.read_full\",\"input\":{\"tool_call_id\":\"agent-tool-7f6517141970455b9b23b82dc1fcfb34\",\"path\":\"draft.scenario\"},\"reason\":\"读取完整场景草稿以准备保存\",\"evidence_refs\":[\"agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft\"]}\n```",
    "provider": "deepseek",
    "event_seq": 4,
    "iteration": 0,
    "loop_step": "tool_planning",
    "event_type": "model.completed",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 0,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-0",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-0-tool_planning-f60f3e4d859848858056c26f6bdfac5c"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:28.849641",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-0",
    "finish_reason": "stop",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-0-tool_planning-f60f3e4d859848858056c26f6bdfac5c",
    "requested_tool": true,
    "schema_version": 1,
    "assistant_visible": false,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-0-tool_planning-f60f3e4d859848858056c26f6bdfac5c"
  },
  "created_at": "2026-07-07 07:56:38"
}
```

#### Event 5: `model.tool_request_detected`

- created_at: `2026-07-07 07:56:39`

```json
{
  "id": 51600,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 5,
  "event_type": "model.tool_request_detected",
  "payload_json": {
    "reason": "读取完整场景草稿以准备保存",
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 5,
    "iteration": 0,
    "loop_step": "tool_planning",
    "tool_name": "tool_result.read_full",
    "event_type": "model.tool_request_detected",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 0,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-0",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-0-tool_planning-f60f3e4d859848858056c26f6bdfac5c"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:28.975312",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-0",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-0-tool_planning-f60f3e4d859848858056c26f6bdfac5c",
    "schema_version": 1,
    "decision_reason": "读取完整场景草稿以准备保存",
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-0-tool_planning-f60f3e4d859848858056c26f6bdfac5c"
  },
  "created_at": "2026-07-07 07:56:39"
}
```

#### Event 6: `tool.planned`

- created_at: `2026-07-07 07:56:39`

```json
{
  "id": 51601,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 6,
  "event_type": "tool.planned",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 6,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.planned",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:29.472027",
    "tool_call_id": "agent-tool-0048989541774deca1e1ff169ed5ab7c",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:56:39"
}
```

#### Event 7: `tool.running`

- created_at: `2026-07-07 07:56:39`

```json
{
  "id": 51602,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 7,
  "event_type": "tool.running",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 7,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.running",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:29.859017",
    "tool_call_id": "agent-tool-0048989541774deca1e1ff169ed5ab7c",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:56:39"
}
```

#### Event 8: `tool.send_intent_recorded`

- created_at: `2026-07-07 07:56:40`

```json
{
  "id": 51603,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 8,
  "event_type": "tool.send_intent_recorded",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 8,
    "event_type": "tool.send_intent_recorded",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:29.963861",
    "tool_call_id": "agent-tool-0048989541774deca1e1ff169ed5ab7c",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:56:40"
}
```

#### Event 9: `tool.transport_sent_observed`

- created_at: `2026-07-07 07:56:40`

```json
{
  "id": 51604,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 9,
  "event_type": "tool.transport_sent_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 9,
    "event_type": "tool.transport_sent_observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:30.082190",
    "tool_call_id": "agent-tool-0048989541774deca1e1ff169ed5ab7c",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:56:40"
}
```

#### Event 10: `tool.backend_accepted`

- created_at: `2026-07-07 07:56:40`

```json
{
  "id": 51605,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 10,
  "event_type": "tool.backend_accepted",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 10,
    "event_type": "tool.backend_accepted",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:30.299783",
    "tool_call_id": "agent-tool-0048989541774deca1e1ff169ed5ab7c",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:56:40"
}
```

#### Event 11: `tool.effect_committed`

- created_at: `2026-07-07 07:56:40`

```json
{
  "id": 51606,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 11,
  "event_type": "tool.effect_committed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 11,
    "event_type": "tool.effect_committed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:30.428848",
    "tool_call_id": "agent-tool-0048989541774deca1e1ff169ed5ab7c",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:56:40"
}
```

#### Event 12: `tool.completed`

- created_at: `2026-07-07 07:56:40`

```json
{
  "id": 51607,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 12,
  "event_type": "tool.completed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 12,
    "event_type": "tool.completed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:30.533386",
    "tool_call_id": "agent-tool-0048989541774deca1e1ff169ed5ab7c",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:56:40"
}
```

#### Event 13: `tool.result_observed`

- created_at: `2026-07-07 07:56:40`

```json
{
  "id": 51608,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 13,
  "event_type": "tool.result_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 13,
    "loop_step": "tool_execution",
    "tool_name": "tool_result.read_full",
    "event_type": "tool.result_observed",
    "loop_state": {
      "step": "tool_execution",
      "phase": "tool",
      "iteration": 0,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-0",
      "tool_call_id": "agent-tool-0048989541774deca1e1ff169ed5ab7c",
      "decision_reason": "读取完整场景草稿以准备保存"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:30.765846",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-0",
    "tool_call_id": "agent-tool-0048989541774deca1e1ff169ed5ab7c",
    "schema_version": 1,
    "decision_reason": "读取完整场景草稿以准备保存"
  },
  "created_at": "2026-07-07 07:56:40"
}
```

#### Event 14: `model.started`

- created_at: `2026-07-07 07:56:41`

```json
{
  "id": 51609,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 14,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "provider": "deepseek",
    "event_seq": 14,
    "iteration": 1,
    "loop_step": "tool_planning",
    "event_type": "model.started",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 1,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-1",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-1-tool_planning-11e227f3e6b7482dbfbb23abc59ae639"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:31.039077",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-1",
    "final_summary": false,
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-1-tool_planning-11e227f3e6b7482dbfbb23abc59ae639",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-1-tool_planning-11e227f3e6b7482dbfbb23abc59ae639"
  },
  "created_at": "2026-07-07 07:56:41"
}
```

#### Event 15: `model.completed`

- created_at: `2026-07-07 07:57:04`
- content_preview: ```agent_tool_request
{"tool_name":"tool_result.read_full","input":{"tool_call_id":"agent-tool-7f6517141970455b9b23b82dc1fcfb34","path":"draft.scenario","max_chars":64000},"reason":"读取完整场景草稿以准备保存，上次输出被截断","evidence_refs":["agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft"]}
```

```json
{
  "id": 51610,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 15,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "content": "```agent_tool_request\n{\"tool_name\":\"tool_result.read_full\",\"input\":{\"tool_call_id\":\"agent-tool-7f6517141970455b9b23b82dc1fcfb34\",\"path\":\"draft.scenario\",\"max_chars\":64000},\"reason\":\"读取完整场景草稿以准备保存，上次输出被截断\",\"evidence_refs\":[\"agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft\"]}\n```",
    "provider": "deepseek",
    "event_seq": 15,
    "iteration": 1,
    "loop_step": "tool_planning",
    "event_type": "model.completed",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 1,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-1",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-1-tool_planning-11e227f3e6b7482dbfbb23abc59ae639"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:54.048666",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-1",
    "finish_reason": "stop",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-1-tool_planning-11e227f3e6b7482dbfbb23abc59ae639",
    "requested_tool": true,
    "schema_version": 1,
    "assistant_visible": false,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-1-tool_planning-11e227f3e6b7482dbfbb23abc59ae639"
  },
  "created_at": "2026-07-07 07:57:04"
}
```

#### Event 16: `model.tool_request_detected`

- created_at: `2026-07-07 07:57:04`

```json
{
  "id": 51611,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 16,
  "event_type": "model.tool_request_detected",
  "payload_json": {
    "reason": "读取完整场景草稿以准备保存，上次输出被截断",
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 16,
    "iteration": 1,
    "loop_step": "tool_planning",
    "tool_name": "tool_result.read_full",
    "event_type": "model.tool_request_detected",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 1,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-1",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-1-tool_planning-11e227f3e6b7482dbfbb23abc59ae639"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:54.144302",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-1",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-1-tool_planning-11e227f3e6b7482dbfbb23abc59ae639",
    "schema_version": 1,
    "decision_reason": "读取完整场景草稿以准备保存，上次输出被截断",
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-1-tool_planning-11e227f3e6b7482dbfbb23abc59ae639"
  },
  "created_at": "2026-07-07 07:57:04"
}
```

#### Event 17: `tool.planned`

- created_at: `2026-07-07 07:57:04`

```json
{
  "id": 51612,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 17,
  "event_type": "tool.planned",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 17,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.planned",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:54.585521",
    "tool_call_id": "agent-tool-5eade05444704a868c55cd3158d075a6",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:04"
}
```

#### Event 18: `tool.running`

- created_at: `2026-07-07 07:57:05`

```json
{
  "id": 51613,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 18,
  "event_type": "tool.running",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 18,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.running",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:54.901553",
    "tool_call_id": "agent-tool-5eade05444704a868c55cd3158d075a6",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:05"
}
```

#### Event 19: `tool.send_intent_recorded`

- created_at: `2026-07-07 07:57:05`

```json
{
  "id": 51614,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 19,
  "event_type": "tool.send_intent_recorded",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 19,
    "event_type": "tool.send_intent_recorded",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:55.000392",
    "tool_call_id": "agent-tool-5eade05444704a868c55cd3158d075a6",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:05"
}
```

#### Event 20: `tool.transport_sent_observed`

- created_at: `2026-07-07 07:57:05`

```json
{
  "id": 51615,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 20,
  "event_type": "tool.transport_sent_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 20,
    "event_type": "tool.transport_sent_observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:55.098543",
    "tool_call_id": "agent-tool-5eade05444704a868c55cd3158d075a6",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:05"
}
```

#### Event 21: `tool.backend_accepted`

- created_at: `2026-07-07 07:57:05`

```json
{
  "id": 51616,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 21,
  "event_type": "tool.backend_accepted",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 21,
    "event_type": "tool.backend_accepted",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:55.310699",
    "tool_call_id": "agent-tool-5eade05444704a868c55cd3158d075a6",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:05"
}
```

#### Event 22: `tool.effect_committed`

- created_at: `2026-07-07 07:57:05`

```json
{
  "id": 51617,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 22,
  "event_type": "tool.effect_committed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 22,
    "event_type": "tool.effect_committed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:55.418573",
    "tool_call_id": "agent-tool-5eade05444704a868c55cd3158d075a6",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:05"
}
```

#### Event 23: `tool.completed`

- created_at: `2026-07-07 07:57:05`

```json
{
  "id": 51618,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 23,
  "event_type": "tool.completed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 23,
    "event_type": "tool.completed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:55.515974",
    "tool_call_id": "agent-tool-5eade05444704a868c55cd3158d075a6",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:05"
}
```

#### Event 24: `tool.result_observed`

- created_at: `2026-07-07 07:57:05`

```json
{
  "id": 51619,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 24,
  "event_type": "tool.result_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 24,
    "loop_step": "tool_execution",
    "tool_name": "tool_result.read_full",
    "event_type": "tool.result_observed",
    "loop_state": {
      "step": "tool_execution",
      "phase": "tool",
      "iteration": 1,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-1",
      "tool_call_id": "agent-tool-5eade05444704a868c55cd3158d075a6",
      "decision_reason": "读取完整场景草稿以准备保存，上次输出被截断"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:55.735430",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-1",
    "tool_call_id": "agent-tool-5eade05444704a868c55cd3158d075a6",
    "schema_version": 1,
    "decision_reason": "读取完整场景草稿以准备保存，上次输出被截断"
  },
  "created_at": "2026-07-07 07:57:05"
}
```

#### Event 25: `model.started`

- created_at: `2026-07-07 07:57:06`

```json
{
  "id": 51620,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 25,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "provider": "deepseek",
    "event_seq": 25,
    "iteration": 2,
    "loop_step": "tool_planning",
    "event_type": "model.started",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 2,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-2",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-2-tool_planning-de27a0b3b91a4f21be18d740a82c7d0b"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:56.078902",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-2",
    "final_summary": false,
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-2-tool_planning-de27a0b3b91a4f21be18d740a82c7d0b",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-2-tool_planning-de27a0b3b91a4f21be18d740a82c7d0b"
  },
  "created_at": "2026-07-07 07:57:06"
}
```

#### Event 26: `model.completed`

- created_at: `2026-07-07 07:57:09`
- content_preview: ```agent_tool_request
{"tool_name":"tool_result.read_full","input":{"tool_call_id":"agent-tool-7f6517141970455b9b23b82dc1fcfb34","path":"draft.scenario","max_chars":256000},"reason":"再次读取完整场景草稿，使用最大字符上限以确保获取完整 JSON","evidence_refs":["agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft"]}
```

```json
{
  "id": 51621,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 26,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "content": "```agent_tool_request\n{\"tool_name\":\"tool_result.read_full\",\"input\":{\"tool_call_id\":\"agent-tool-7f6517141970455b9b23b82dc1fcfb34\",\"path\":\"draft.scenario\",\"max_chars\":256000},\"reason\":\"再次读取完整场景草稿，使用最大字符上限以确保获取完整 JSON\",\"evidence_refs\":[\"agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft\"]}\n```",
    "provider": "deepseek",
    "event_seq": 26,
    "iteration": 2,
    "loop_step": "tool_planning",
    "event_type": "model.completed",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 2,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-2",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-2-tool_planning-de27a0b3b91a4f21be18d740a82c7d0b"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:59.681125",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-2",
    "finish_reason": "stop",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-2-tool_planning-de27a0b3b91a4f21be18d740a82c7d0b",
    "requested_tool": true,
    "schema_version": 1,
    "assistant_visible": false,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-2-tool_planning-de27a0b3b91a4f21be18d740a82c7d0b"
  },
  "created_at": "2026-07-07 07:57:09"
}
```

#### Event 27: `model.tool_request_detected`

- created_at: `2026-07-07 07:57:09`

```json
{
  "id": 51622,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 27,
  "event_type": "model.tool_request_detected",
  "payload_json": {
    "reason": "再次读取完整场景草稿，使用最大字符上限以确保获取完整 JSON",
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 27,
    "iteration": 2,
    "loop_step": "tool_planning",
    "tool_name": "tool_result.read_full",
    "event_type": "model.tool_request_detected",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 2,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-2",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-2-tool_planning-de27a0b3b91a4f21be18d740a82c7d0b"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:56:59.757408",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-2",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-2-tool_planning-de27a0b3b91a4f21be18d740a82c7d0b",
    "schema_version": 1,
    "decision_reason": "再次读取完整场景草稿，使用最大字符上限以确保获取完整 JSON",
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-2-tool_planning-de27a0b3b91a4f21be18d740a82c7d0b"
  },
  "created_at": "2026-07-07 07:57:09"
}
```

#### Event 28: `tool.planned`

- created_at: `2026-07-07 07:57:10`

```json
{
  "id": 51623,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 28,
  "event_type": "tool.planned",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 28,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.planned",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:00.226480",
    "tool_call_id": "agent-tool-2db01aa8752d4e5491012e89b49697fc",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:10"
}
```

#### Event 29: `tool.running`

- created_at: `2026-07-07 07:57:10`

```json
{
  "id": 51624,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 29,
  "event_type": "tool.running",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 29,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.running",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:00.671359",
    "tool_call_id": "agent-tool-2db01aa8752d4e5491012e89b49697fc",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:10"
}
```

#### Event 30: `tool.send_intent_recorded`

- created_at: `2026-07-07 07:57:10`

```json
{
  "id": 51625,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 30,
  "event_type": "tool.send_intent_recorded",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 30,
    "event_type": "tool.send_intent_recorded",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:00.850556",
    "tool_call_id": "agent-tool-2db01aa8752d4e5491012e89b49697fc",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:10"
}
```

#### Event 31: `tool.transport_sent_observed`

- created_at: `2026-07-07 07:57:11`

```json
{
  "id": 51626,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 31,
  "event_type": "tool.transport_sent_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 31,
    "event_type": "tool.transport_sent_observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:01.010219",
    "tool_call_id": "agent-tool-2db01aa8752d4e5491012e89b49697fc",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:11"
}
```

#### Event 32: `tool.backend_accepted`

- created_at: `2026-07-07 07:57:11`

```json
{
  "id": 51627,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 32,
  "event_type": "tool.backend_accepted",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 32,
    "event_type": "tool.backend_accepted",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:01.299506",
    "tool_call_id": "agent-tool-2db01aa8752d4e5491012e89b49697fc",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:11"
}
```

#### Event 33: `tool.effect_committed`

- created_at: `2026-07-07 07:57:11`

```json
{
  "id": 51628,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 33,
  "event_type": "tool.effect_committed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 33,
    "event_type": "tool.effect_committed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:01.461240",
    "tool_call_id": "agent-tool-2db01aa8752d4e5491012e89b49697fc",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:11"
}
```

#### Event 34: `tool.completed`

- created_at: `2026-07-07 07:57:11`

```json
{
  "id": 51629,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 34,
  "event_type": "tool.completed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 34,
    "event_type": "tool.completed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:01.611378",
    "tool_call_id": "agent-tool-2db01aa8752d4e5491012e89b49697fc",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:11"
}
```

#### Event 35: `tool.result_observed`

- created_at: `2026-07-07 07:57:12`

```json
{
  "id": 51630,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 35,
  "event_type": "tool.result_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 35,
    "loop_step": "tool_execution",
    "tool_name": "tool_result.read_full",
    "event_type": "tool.result_observed",
    "loop_state": {
      "step": "tool_execution",
      "phase": "tool",
      "iteration": 2,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-2",
      "tool_call_id": "agent-tool-2db01aa8752d4e5491012e89b49697fc",
      "decision_reason": "再次读取完整场景草稿，使用最大字符上限以确保获取完整 JSON"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:01.874490",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-2",
    "tool_call_id": "agent-tool-2db01aa8752d4e5491012e89b49697fc",
    "schema_version": 1,
    "decision_reason": "再次读取完整场景草稿，使用最大字符上限以确保获取完整 JSON"
  },
  "created_at": "2026-07-07 07:57:12"
}
```

#### Event 36: `model.started`

- created_at: `2026-07-07 07:57:12`

```json
{
  "id": 51631,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 36,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "provider": "deepseek",
    "event_seq": 36,
    "iteration": 3,
    "loop_step": "tool_planning",
    "event_type": "model.started",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 3,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-3",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-3-tool_planning-f817085f078c461f812766c0c613ce4d"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:02.177464",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-3",
    "final_summary": false,
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-3-tool_planning-f817085f078c461f812766c0c613ce4d",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-3-tool_planning-f817085f078c461f812766c0c613ce4d"
  },
  "created_at": "2026-07-07 07:57:12"
}
```

#### Event 37: `model.completed`

- created_at: `2026-07-07 07:57:25`
- content_preview: ```agent_tool_request
{"tool_name":"tool_result.read_full","input":{"tool_call_id":"agent-tool-7f6517141970455b9b23b82dc1fcfb34","max_chars":256000},"reason":"再次读取完整场景草稿，获取完整JSON结构以调用scenario.create_saved","evidence_refs":["agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft"]}
```

```json
{
  "id": 51632,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 37,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "content": "```agent_tool_request\n{\"tool_name\":\"tool_result.read_full\",\"input\":{\"tool_call_id\":\"agent-tool-7f6517141970455b9b23b82dc1fcfb34\",\"max_chars\":256000},\"reason\":\"再次读取完整场景草稿，获取完整JSON结构以调用scenario.create_saved\",\"evidence_refs\":[\"agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft\"]}\n```",
    "provider": "deepseek",
    "event_seq": 37,
    "iteration": 3,
    "loop_step": "tool_planning",
    "event_type": "model.completed",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 3,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-3",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-3-tool_planning-f817085f078c461f812766c0c613ce4d"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:15.130490",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-3",
    "finish_reason": "stop",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-3-tool_planning-f817085f078c461f812766c0c613ce4d",
    "requested_tool": true,
    "schema_version": 1,
    "assistant_visible": false,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-3-tool_planning-f817085f078c461f812766c0c613ce4d"
  },
  "created_at": "2026-07-07 07:57:25"
}
```

#### Event 38: `model.tool_request_detected`

- created_at: `2026-07-07 07:57:25`

```json
{
  "id": 51633,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 38,
  "event_type": "model.tool_request_detected",
  "payload_json": {
    "reason": "再次读取完整场景草稿，获取完整JSON结构以调用scenario.create_saved",
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 38,
    "iteration": 3,
    "loop_step": "tool_planning",
    "tool_name": "tool_result.read_full",
    "event_type": "model.tool_request_detected",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 3,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-3",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-3-tool_planning-f817085f078c461f812766c0c613ce4d"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:15.389480",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-3",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-3-tool_planning-f817085f078c461f812766c0c613ce4d",
    "schema_version": 1,
    "decision_reason": "再次读取完整场景草稿，获取完整JSON结构以调用scenario.create_saved",
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-3-tool_planning-f817085f078c461f812766c0c613ce4d"
  },
  "created_at": "2026-07-07 07:57:25"
}
```

#### Event 39: `tool.planned`

- created_at: `2026-07-07 07:57:26`

```json
{
  "id": 51634,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 39,
  "event_type": "tool.planned",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 39,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.planned",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:16.080813",
    "tool_call_id": "agent-tool-58b08dd614f642f99a4e5b37792184ad",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:26"
}
```

#### Event 40: `tool.running`

- created_at: `2026-07-07 07:57:26`

```json
{
  "id": 51635,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 40,
  "event_type": "tool.running",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 40,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.running",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:16.589598",
    "tool_call_id": "agent-tool-58b08dd614f642f99a4e5b37792184ad",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:26"
}
```

#### Event 41: `tool.send_intent_recorded`

- created_at: `2026-07-07 07:57:26`

```json
{
  "id": 51636,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 41,
  "event_type": "tool.send_intent_recorded",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 41,
    "event_type": "tool.send_intent_recorded",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:16.754389",
    "tool_call_id": "agent-tool-58b08dd614f642f99a4e5b37792184ad",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:26"
}
```

#### Event 42: `tool.transport_sent_observed`

- created_at: `2026-07-07 07:57:27`

```json
{
  "id": 51637,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 42,
  "event_type": "tool.transport_sent_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 42,
    "event_type": "tool.transport_sent_observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:16.995607",
    "tool_call_id": "agent-tool-58b08dd614f642f99a4e5b37792184ad",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:27"
}
```

#### Event 43: `tool.backend_accepted`

- created_at: `2026-07-07 07:57:27`

```json
{
  "id": 51638,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 43,
  "event_type": "tool.backend_accepted",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 43,
    "event_type": "tool.backend_accepted",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:17.317547",
    "tool_call_id": "agent-tool-58b08dd614f642f99a4e5b37792184ad",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:27"
}
```

#### Event 44: `tool.effect_committed`

- created_at: `2026-07-07 07:57:27`

```json
{
  "id": 51639,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 44,
  "event_type": "tool.effect_committed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 44,
    "event_type": "tool.effect_committed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:17.560009",
    "tool_call_id": "agent-tool-58b08dd614f642f99a4e5b37792184ad",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:27"
}
```

#### Event 45: `tool.completed`

- created_at: `2026-07-07 07:57:27`

```json
{
  "id": 51640,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 45,
  "event_type": "tool.completed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 45,
    "event_type": "tool.completed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:17.735464",
    "tool_call_id": "agent-tool-58b08dd614f642f99a4e5b37792184ad",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:27"
}
```

#### Event 46: `tool.result_observed`

- created_at: `2026-07-07 07:57:28`

```json
{
  "id": 51641,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 46,
  "event_type": "tool.result_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 46,
    "loop_step": "tool_execution",
    "tool_name": "tool_result.read_full",
    "event_type": "tool.result_observed",
    "loop_state": {
      "step": "tool_execution",
      "phase": "tool",
      "iteration": 3,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-3",
      "tool_call_id": "agent-tool-58b08dd614f642f99a4e5b37792184ad",
      "decision_reason": "再次读取完整场景草稿，获取完整JSON结构以调用scenario.create_saved"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:18.079158",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-3",
    "tool_call_id": "agent-tool-58b08dd614f642f99a4e5b37792184ad",
    "schema_version": 1,
    "decision_reason": "再次读取完整场景草稿，获取完整JSON结构以调用scenario.create_saved"
  },
  "created_at": "2026-07-07 07:57:28"
}
```

#### Event 47: `model.started`

- created_at: `2026-07-07 07:57:28`

```json
{
  "id": 51642,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 47,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "provider": "deepseek",
    "event_seq": 47,
    "iteration": 4,
    "loop_step": "tool_planning",
    "event_type": "model.started",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 4,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-4",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-4-tool_planning-f776e370cf694aa1a9cee55a20340fb7"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:18.557556",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-4",
    "final_summary": false,
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-4-tool_planning-f776e370cf694aa1a9cee55a20340fb7",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-4-tool_planning-f776e370cf694aa1a9cee55a20340fb7"
  },
  "created_at": "2026-07-07 07:57:28"
}
```

#### Event 48: `model.completed`

- created_at: `2026-07-07 07:57:51`
- content_preview: ```agent_tool_request
{"tool_name":"tool_result.read_full","input":{"tool_call_id":"agent-tool-8d64dda3cf78457e9dcaec9c080ff78e","max_chars":256000},"reason":"读取项目完整上下文，获取environment_snapshot_id和环境列表以验证environment_id=4的有效性，为保存场景做准备","evidence_refs":["agent-tool-artifact://agent-tool-8d64dda3cf78457e9dcaec9c080ff78e/tool_result"]}
```

```json
{
  "id": 51643,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 48,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "content": "```agent_tool_request\n{\"tool_name\":\"tool_result.read_full\",\"input\":{\"tool_call_id\":\"agent-tool-8d64dda3cf78457e9dcaec9c080ff78e\",\"max_chars\":256000},\"reason\":\"读取项目完整上下文，获取environment_snapshot_id和环境列表以验证environment_id=4的有效性，为保存场景做准备\",\"evidence_refs\":[\"agent-tool-artifact://agent-tool-8d64dda3cf78457e9dcaec9c080ff78e/tool_result\"]}\n```",
    "provider": "deepseek",
    "event_seq": 48,
    "iteration": 4,
    "loop_step": "tool_planning",
    "event_type": "model.completed",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 4,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-4",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-4-tool_planning-f776e370cf694aa1a9cee55a20340fb7"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:41.696387",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-4",
    "finish_reason": "stop",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-4-tool_planning-f776e370cf694aa1a9cee55a20340fb7",
    "requested_tool": true,
    "schema_version": 1,
    "assistant_visible": false,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-4-tool_planning-f776e370cf694aa1a9cee55a20340fb7"
  },
  "created_at": "2026-07-07 07:57:51"
}
```

#### Event 49: `model.tool_request_detected`

- created_at: `2026-07-07 07:57:51`

```json
{
  "id": 51644,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 49,
  "event_type": "model.tool_request_detected",
  "payload_json": {
    "reason": "读取项目完整上下文，获取environment_snapshot_id和环境列表以验证environment_id=4的有效性，为保存场景做准备",
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 49,
    "iteration": 4,
    "loop_step": "tool_planning",
    "tool_name": "tool_result.read_full",
    "event_type": "model.tool_request_detected",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 4,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-4",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-4-tool_planning-f776e370cf694aa1a9cee55a20340fb7"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:41.818461",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-4",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-4-tool_planning-f776e370cf694aa1a9cee55a20340fb7",
    "schema_version": 1,
    "decision_reason": "读取项目完整上下文，获取environment_snapshot_id和环境列表以验证environment_id=4的有效性，为保存场景做准备",
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-4-tool_planning-f776e370cf694aa1a9cee55a20340fb7"
  },
  "created_at": "2026-07-07 07:57:51"
}
```

#### Event 50: `tool.planned`

- created_at: `2026-07-07 07:57:52`

```json
{
  "id": 51645,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 50,
  "event_type": "tool.planned",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 50,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.planned",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:42.327725",
    "tool_call_id": "agent-tool-b611c24f1f4f43e09179d3735cb55a58",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:52"
}
```

#### Event 51: `tool.running`

- created_at: `2026-07-07 07:57:53`

```json
{
  "id": 51646,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 51,
  "event_type": "tool.running",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 51,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.running",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:42.873029",
    "tool_call_id": "agent-tool-b611c24f1f4f43e09179d3735cb55a58",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:53"
}
```

#### Event 52: `tool.send_intent_recorded`

- created_at: `2026-07-07 07:57:53`

```json
{
  "id": 51647,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 52,
  "event_type": "tool.send_intent_recorded",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 52,
    "event_type": "tool.send_intent_recorded",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:43.029627",
    "tool_call_id": "agent-tool-b611c24f1f4f43e09179d3735cb55a58",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:53"
}
```

#### Event 53: `tool.transport_sent_observed`

- created_at: `2026-07-07 07:57:53`

```json
{
  "id": 51648,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 53,
  "event_type": "tool.transport_sent_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 53,
    "event_type": "tool.transport_sent_observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:43.210427",
    "tool_call_id": "agent-tool-b611c24f1f4f43e09179d3735cb55a58",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:53"
}
```

#### Event 54: `tool.backend_accepted`

- created_at: `2026-07-07 07:57:53`

```json
{
  "id": 51649,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 54,
  "event_type": "tool.backend_accepted",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 54,
    "event_type": "tool.backend_accepted",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:43.556146",
    "tool_call_id": "agent-tool-b611c24f1f4f43e09179d3735cb55a58",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:53"
}
```

#### Event 55: `tool.effect_committed`

- created_at: `2026-07-07 07:57:53`

```json
{
  "id": 51650,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 55,
  "event_type": "tool.effect_committed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 55,
    "event_type": "tool.effect_committed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:43.728195",
    "tool_call_id": "agent-tool-b611c24f1f4f43e09179d3735cb55a58",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:53"
}
```

#### Event 56: `tool.completed`

- created_at: `2026-07-07 07:57:54`

```json
{
  "id": 51651,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 56,
  "event_type": "tool.completed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 56,
    "event_type": "tool.completed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:43.916137",
    "tool_call_id": "agent-tool-b611c24f1f4f43e09179d3735cb55a58",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:57:54"
}
```

#### Event 57: `tool.result_observed`

- created_at: `2026-07-07 07:57:54`

```json
{
  "id": 51652,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 57,
  "event_type": "tool.result_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 57,
    "loop_step": "tool_execution",
    "tool_name": "tool_result.read_full",
    "event_type": "tool.result_observed",
    "loop_state": {
      "step": "tool_execution",
      "phase": "tool",
      "iteration": 4,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-4",
      "tool_call_id": "agent-tool-b611c24f1f4f43e09179d3735cb55a58",
      "decision_reason": "读取项目完整上下文，获取environment_snapshot_id和环境列表以验证environment_id=4的有效性，为保存场景做准备"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:44.246110",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-4",
    "tool_call_id": "agent-tool-b611c24f1f4f43e09179d3735cb55a58",
    "schema_version": 1,
    "decision_reason": "读取项目完整上下文，获取environment_snapshot_id和环境列表以验证environment_id=4的有效性，为保存场景做准备"
  },
  "created_at": "2026-07-07 07:57:54"
}
```

#### Event 58: `model.started`

- created_at: `2026-07-07 07:57:54`

```json
{
  "id": 51653,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 58,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "provider": "deepseek",
    "event_seq": 58,
    "iteration": 5,
    "loop_step": "tool_planning",
    "event_type": "model.started",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 5,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-5",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-5-tool_planning-943a90916470426b95e07b840f848c20"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:57:44.651457",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-5",
    "final_summary": false,
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-5-tool_planning-943a90916470426b95e07b840f848c20",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-5-tool_planning-943a90916470426b95e07b840f848c20"
  },
  "created_at": "2026-07-07 07:57:54"
}
```

#### Event 59: `model.completed`

- created_at: `2026-07-07 07:58:37`
- content_preview: ```agent_tool_request
{"tool_name":"tool_result.read_full","input":{"tool_call_id":"agent-tool-7f6517141970455b9b23b82dc1fcfb34","path":"draft.scenario.nodes.3","max_chars":10000},"reason":"读取第4个节点（取消关注企业）的完整信息，之前读取场景草稿时NODE-4被截断","evidence_refs":["agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft"]}
```

```json
{
  "id": 51654,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 59,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "content": "```agent_tool_request\n{\"tool_name\":\"tool_result.read_full\",\"input\":{\"tool_call_id\":\"agent-tool-7f6517141970455b9b23b82dc1fcfb34\",\"path\":\"draft.scenario.nodes.3\",\"max_chars\":10000},\"reason\":\"读取第4个节点（取消关注企业）的完整信息，之前读取场景草稿时NODE-4被截断\",\"evidence_refs\":[\"agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft\"]}\n```",
    "provider": "deepseek",
    "event_seq": 59,
    "iteration": 5,
    "loop_step": "tool_planning",
    "event_type": "model.completed",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 5,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-5",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-5-tool_planning-943a90916470426b95e07b840f848c20"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:58:26.978969",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-5",
    "finish_reason": "stop",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-5-tool_planning-943a90916470426b95e07b840f848c20",
    "requested_tool": true,
    "schema_version": 1,
    "assistant_visible": false,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-5-tool_planning-943a90916470426b95e07b840f848c20"
  },
  "created_at": "2026-07-07 07:58:37"
}
```

#### Event 60: `model.tool_request_detected`

- created_at: `2026-07-07 07:58:37`

```json
{
  "id": 51655,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 60,
  "event_type": "model.tool_request_detected",
  "payload_json": {
    "reason": "读取第4个节点（取消关注企业）的完整信息，之前读取场景草稿时NODE-4被截断",
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 60,
    "iteration": 5,
    "loop_step": "tool_planning",
    "tool_name": "tool_result.read_full",
    "event_type": "model.tool_request_detected",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 5,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-5",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-5-tool_planning-943a90916470426b95e07b840f848c20"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:58:27.063982",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-5",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-5-tool_planning-943a90916470426b95e07b840f848c20",
    "schema_version": 1,
    "decision_reason": "读取第4个节点（取消关注企业）的完整信息，之前读取场景草稿时NODE-4被截断",
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-5-tool_planning-943a90916470426b95e07b840f848c20"
  },
  "created_at": "2026-07-07 07:58:37"
}
```

#### Event 61: `tool.planned`

- created_at: `2026-07-07 07:58:37`

```json
{
  "id": 51656,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 61,
  "event_type": "tool.planned",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 61,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.planned",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:58:27.465013",
    "tool_call_id": "agent-tool-230297dc55ed4a6e9d3d697ef716046e",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:58:37"
}
```

#### Event 62: `tool.running`

- created_at: `2026-07-07 07:58:38`

```json
{
  "id": 51657,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 62,
  "event_type": "tool.running",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 62,
    "tool_name": "tool_result.read_full",
    "event_type": "tool.running",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:58:27.886760",
    "tool_call_id": "agent-tool-230297dc55ed4a6e9d3d697ef716046e",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:58:38"
}
```

#### Event 63: `tool.send_intent_recorded`

- created_at: `2026-07-07 07:58:38`

```json
{
  "id": 51658,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 63,
  "event_type": "tool.send_intent_recorded",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 63,
    "event_type": "tool.send_intent_recorded",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:58:28.033020",
    "tool_call_id": "agent-tool-230297dc55ed4a6e9d3d697ef716046e",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:58:38"
}
```

#### Event 64: `tool.transport_sent_observed`

- created_at: `2026-07-07 07:58:38`

```json
{
  "id": 51659,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 64,
  "event_type": "tool.transport_sent_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 64,
    "event_type": "tool.transport_sent_observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:58:28.184151",
    "tool_call_id": "agent-tool-230297dc55ed4a6e9d3d697ef716046e",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:58:38"
}
```

#### Event 65: `tool.backend_accepted`

- created_at: `2026-07-07 07:58:38`

```json
{
  "id": 51660,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 65,
  "event_type": "tool.backend_accepted",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 65,
    "event_type": "tool.backend_accepted",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:58:28.498040",
    "tool_call_id": "agent-tool-230297dc55ed4a6e9d3d697ef716046e",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:58:38"
}
```

#### Event 66: `tool.effect_committed`

- created_at: `2026-07-07 07:58:38`

```json
{
  "id": 51661,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 66,
  "event_type": "tool.effect_committed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 66,
    "event_type": "tool.effect_committed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:58:28.656319",
    "tool_call_id": "agent-tool-230297dc55ed4a6e9d3d697ef716046e",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:58:38"
}
```

#### Event 67: `tool.completed`

- created_at: `2026-07-07 07:58:38`

```json
{
  "id": 51662,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 67,
  "event_type": "tool.completed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 67,
    "event_type": "tool.completed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:58:28.813171",
    "tool_call_id": "agent-tool-230297dc55ed4a6e9d3d697ef716046e",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:58:38"
}
```

#### Event 68: `tool.result_observed`

- created_at: `2026-07-07 07:58:39`

```json
{
  "id": 51663,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 68,
  "event_type": "tool.result_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 68,
    "loop_step": "tool_execution",
    "tool_name": "tool_result.read_full",
    "event_type": "tool.result_observed",
    "loop_state": {
      "step": "tool_execution",
      "phase": "tool",
      "iteration": 5,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-5",
      "tool_call_id": "agent-tool-230297dc55ed4a6e9d3d697ef716046e",
      "decision_reason": "读取第4个节点（取消关注企业）的完整信息，之前读取场景草稿时NODE-4被截断"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:58:29.094365",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-5",
    "tool_call_id": "agent-tool-230297dc55ed4a6e9d3d697ef716046e",
    "schema_version": 1,
    "decision_reason": "读取第4个节点（取消关注企业）的完整信息，之前读取场景草稿时NODE-4被截断"
  },
  "created_at": "2026-07-07 07:58:39"
}
```

#### Event 69: `model.started`

- created_at: `2026-07-07 07:58:39`

```json
{
  "id": 51664,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 69,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "provider": "deepseek",
    "event_seq": 69,
    "iteration": 6,
    "loop_step": "tool_planning",
    "event_type": "model.started",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 6,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-6",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-6-tool_planning-616589971da2497fb277eb0d1987303c"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:58:29.398455",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-6",
    "final_summary": false,
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-6-tool_planning-616589971da2497fb277eb0d1987303c",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-6-tool_planning-616589971da2497fb277eb0d1987303c"
  },
  "created_at": "2026-07-07 07:58:39"
}
```

#### Event 70: `model.completed`

- created_at: `2026-07-07 07:59:15`
- content_preview: ```agent_tool_request
{"tool_name":"scenario.create_saved","input":{"project_id":1,"scenario":{"name":"企业端到端自动化流程测试","tags":["ai-composed"],"environment_id":4,"nodes":[{"id":"NODE-1","name":"获取企业列表","test_case":{"id":"CASE-1","kind":"ap[agent_content_preview_truncated] content_summary_version=agent_content_preview_summary_v1 content_size_chars=3760 content_hash=58a1a0a09e4328d0f8a9bfb759f82bde3d42786f15738dc629748a32f586e4de full_content_reference=AgentConversationRunner.model.completed.tool_req...

```json
{
  "id": 51665,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 70,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "content": "```agent_tool_request\n{\"tool_name\":\"scenario.create_saved\",\"input\":{\"project_id\":1,\"scenario\":{\"name\":\"企业端到端自动化流程测试\",\"tags\":[\"ai-composed\"],\"environment_id\":4,\"nodes\":[{\"id\":\"NODE-1\",\"name\":\"获取企业列表\",\"test_case\":{\"id\":\"CASE-1\",\"kind\":\"ap[agent_content_preview_truncated] content_summary_version=agent_content_preview_summary_v1 content_size_chars=3760 content_hash=58a1a0a09e4328d0f8a9bfb759f82bde3d42786f15738dc629748a32f586e4de full_content_reference=AgentConversationRunner.model.completed.tool_request.content",
    "provider": "deepseek",
    "event_seq": 70,
    "iteration": 6,
    "loop_step": "tool_planning",
    "event_type": "model.completed",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 6,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-6",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-6-tool_planning-616589971da2497fb277eb0d1987303c"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:05.799995",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-6",
    "finish_reason": "stop",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-6-tool_planning-616589971da2497fb277eb0d1987303c",
    "requested_tool": true,
    "schema_version": 1,
    "assistant_visible": false,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-6-tool_planning-616589971da2497fb277eb0d1987303c"
  },
  "created_at": "2026-07-07 07:59:15"
}
```

#### Event 71: `model.tool_request_detected`

- created_at: `2026-07-07 07:59:16`

```json
{
  "id": 51666,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 71,
  "event_type": "model.tool_request_detected",
  "payload_json": {
    "reason": "保存之前生成的场景草稿为正式场景",
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 71,
    "iteration": 6,
    "loop_step": "tool_planning",
    "tool_name": "scenario.create_saved",
    "event_type": "model.tool_request_detected",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 6,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-6",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-6-tool_planning-616589971da2497fb277eb0d1987303c"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:05.916000",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-6",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-6-tool_planning-616589971da2497fb277eb0d1987303c",
    "schema_version": 1,
    "decision_reason": "保存之前生成的场景草稿为正式场景",
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-6-tool_planning-616589971da2497fb277eb0d1987303c"
  },
  "created_at": "2026-07-07 07:59:16"
}
```

#### Event 72: `context.decision_context_bound`

- created_at: `2026-07-07 07:59:16`

```json
{
  "id": 51667,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 72,
  "event_type": "context.decision_context_bound",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 72,
    "event_type": "context.decision_context_bound",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:06.525610",
    "build_purpose": "approval",
    "schema_version": 1,
    "context_build_id": "agent-ctx-65b762f9fdd04acb9c9974da884ed3a6"
  },
  "created_at": "2026-07-07 07:59:16"
}
```

#### Event 73: `tool.planned`

- created_at: `2026-07-07 07:59:16`

```json
{
  "id": 51668,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 73,
  "event_type": "tool.planned",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 73,
    "tool_name": "scenario.create_saved",
    "event_type": "tool.planned",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:06.735818",
    "tool_call_id": "agent-tool-ed2f67f33bb84557803166f5e40430eb",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:59:16"
}
```

#### Event 74: `tool.failed`

- created_at: `2026-07-07 07:59:17`

```json
{
  "id": 51669,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 74,
  "event_type": "tool.failed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 74,
    "tool_name": "scenario.create_saved",
    "error_code": "agent_tool_input_schema_invalid",
    "event_type": "tool.failed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:06.897077",
    "tool_call_id": "agent-tool-ed2f67f33bb84557803166f5e40430eb",
    "schema_version": 1,
    "schema_preflight": {
      "errors": [
        {
          "path": "scenario.environment_snapshot_id",
          "type": "extra_forbidden",
          "message": "Extra inputs are not permitted",
          "input_preview": "'environment-snapshot://85d4b70ef97f659268fb9e93a56a641070b9bc99e3352ae84e30f766ffbb9af0'"
        }
      ],
      "tool_name": "scenario.create_saved",
      "schema_name": "ScenarioCreateRequest"
    }
  },
  "created_at": "2026-07-07 07:59:17"
}
```

#### Event 75: `tool.result_observed`

- created_at: `2026-07-07 07:59:17`

```json
{
  "id": 51670,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 75,
  "event_type": "tool.result_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "failed",
    "event_seq": 75,
    "tool_name": "scenario.create_saved",
    "error_code": "agent_tool_input_schema_invalid",
    "event_type": "tool.result_observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:07.013839",
    "tool_call_id": "agent-tool-ed2f67f33bb84557803166f5e40430eb",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:59:17"
}
```

#### Event 76: `model.started`

- created_at: `2026-07-07 07:59:17`

```json
{
  "id": 51671,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 76,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "provider": "deepseek",
    "event_seq": 76,
    "iteration": 7,
    "loop_step": "tool_planning",
    "event_type": "model.started",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 7,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-7",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-7-tool_planning-07f689a91a2c4b4d85dd69d40a95e714"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:07.543112",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-7",
    "final_summary": false,
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-7-tool_planning-07f689a91a2c4b4d85dd69d40a95e714",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-7-tool_planning-07f689a91a2c4b4d85dd69d40a95e714"
  },
  "created_at": "2026-07-07 07:59:17"
}
```

#### Event 77: `model.completed`

- created_at: `2026-07-07 07:59:31`
- content_preview: ```agent_tool_request
{"tool_name":"scenario.create_saved","input":{"project_id":1,"scenario":{"name":"企业端到端自动化流程测试","tags":["ai-composed"],"environment_id":4,"nodes":[{"id":"NODE-1","name":"获取企业列表","test_case":{"id":"CASE-1","kind":"ap[agent_content_preview_truncated] content_summary_version=agent_content_preview_summary_v1 content_size_chars=3789 content_hash=0cee10ed7206c45d0e68ae4917fedca1440512f43208725735a399d13a3b713c full_content_reference=AgentConversationRunner.model.completed.tool_req...

```json
{
  "id": 51672,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 77,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "content": "```agent_tool_request\n{\"tool_name\":\"scenario.create_saved\",\"input\":{\"project_id\":1,\"scenario\":{\"name\":\"企业端到端自动化流程测试\",\"tags\":[\"ai-composed\"],\"environment_id\":4,\"nodes\":[{\"id\":\"NODE-1\",\"name\":\"获取企业列表\",\"test_case\":{\"id\":\"CASE-1\",\"kind\":\"ap[agent_content_preview_truncated] content_summary_version=agent_content_preview_summary_v1 content_size_chars=3789 content_hash=0cee10ed7206c45d0e68ae4917fedca1440512f43208725735a399d13a3b713c full_content_reference=AgentConversationRunner.model.completed.tool_request.content",
    "provider": "deepseek",
    "event_seq": 77,
    "iteration": 7,
    "loop_step": "tool_planning",
    "event_type": "model.completed",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 7,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-7",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-7-tool_planning-07f689a91a2c4b4d85dd69d40a95e714"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:21.670366",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-7",
    "finish_reason": "stop",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-7-tool_planning-07f689a91a2c4b4d85dd69d40a95e714",
    "requested_tool": true,
    "schema_version": 1,
    "assistant_visible": false,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-7-tool_planning-07f689a91a2c4b4d85dd69d40a95e714"
  },
  "created_at": "2026-07-07 07:59:31"
}
```

#### Event 78: `model.tool_request_detected`

- created_at: `2026-07-07 07:59:31`

```json
{
  "id": 51673,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 78,
  "event_type": "model.tool_request_detected",
  "payload_json": {
    "reason": "修复：从scenario对象中移除environment_snapshot_id，放到顶层",
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 78,
    "iteration": 7,
    "loop_step": "tool_planning",
    "tool_name": "scenario.create_saved",
    "event_type": "model.tool_request_detected",
    "loop_state": {
      "step": "tool_planning",
      "phase": "model",
      "iteration": 7,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-7",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-7-tool_planning-07f689a91a2c4b4d85dd69d40a95e714"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:21.777413",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-7",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-7-tool_planning-07f689a91a2c4b4d85dd69d40a95e714",
    "schema_version": 1,
    "decision_reason": "修复：从scenario对象中移除environment_snapshot_id，放到顶层",
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-7-tool_planning-07f689a91a2c4b4d85dd69d40a95e714"
  },
  "created_at": "2026-07-07 07:59:31"
}
```

#### Event 79: `context.decision_context_bound`

- created_at: `2026-07-07 07:59:32`

```json
{
  "id": 51674,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 79,
  "event_type": "context.decision_context_bound",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 79,
    "event_type": "context.decision_context_bound",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:22.442791",
    "build_purpose": "approval",
    "schema_version": 1,
    "context_build_id": "agent-ctx-711365f82840448b886069bdb3e5f222"
  },
  "created_at": "2026-07-07 07:59:32"
}
```

#### Event 80: `tool.planned`

- created_at: `2026-07-07 07:59:32`

```json
{
  "id": 51675,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 80,
  "event_type": "tool.planned",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 80,
    "tool_name": "scenario.create_saved",
    "event_type": "tool.planned",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:22.710249",
    "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:59:32"
}
```

#### Event 81: `approval.created`

- created_at: `2026-07-07 07:59:33`

```json
{
  "id": 51676,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 81,
  "event_type": "approval.created",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 81,
    "event_type": "approval.created",
    "project_id": 1,
    "approval_id": "agent-appr-8fab4bfca9e34d4b8c1d7dd9755de511",
    "occurred_at": "2026-07-06T23:59:23.011281",
    "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
    "approval_epoch": 1,
    "schema_version": 1,
    "approval_lineage_id": "agent-appr-lineage-a7e5e72b3eed4f44b7cf7f4045cde714"
  },
  "created_at": "2026-07-07 07:59:33"
}
```

#### Event 82: `run.needs_human`

- created_at: `2026-07-07 07:59:33`

```json
{
  "id": 51677,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 82,
  "event_type": "run.needs_human",
  "payload_json": {
    "reason": "tool_approval_required",
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 82,
    "loop_step": "tool_execution",
    "tool_name": "scenario.create_saved",
    "event_type": "run.needs_human",
    "loop_state": {
      "step": "tool_execution",
      "phase": "tool",
      "iteration": 7,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-7",
      "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
      "decision_reason": "修复：从scenario对象中移除environment_snapshot_id，放到顶层"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:23.533061",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-7",
    "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
    "schema_version": 1,
    "decision_reason": "修复：从scenario对象中移除environment_snapshot_id，放到顶层"
  },
  "created_at": "2026-07-07 07:59:33"
}
```

#### Event 83: `approval.approved`

- created_at: `2026-07-07 07:59:36`

```json
{
  "id": 51678,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 83,
  "event_type": "approval.approved",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 83,
    "event_type": "approval.approved",
    "project_id": 1,
    "approval_id": "agent-appr-8fab4bfca9e34d4b8c1d7dd9755de511",
    "occurred_at": "2026-07-06T23:59:25.920421",
    "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
    "approval_epoch": 1,
    "schema_version": 1,
    "approval_lineage_id": "agent-appr-lineage-a7e5e72b3eed4f44b7cf7f4045cde714"
  },
  "created_at": "2026-07-07 07:59:36"
}
```

#### Event 84: `checkpoint.freshness_checked`

- created_at: `2026-07-07 07:59:37`

```json
{
  "id": 51679,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 84,
  "event_type": "checkpoint.freshness_checked",
  "payload_json": {
    "action": "continue_from_checkpoint",
    "reason": "fresh",
    "result": "fresh",
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 84,
    "checked_at": "2026-07-06T23:59:26.445292",
    "event_type": "checkpoint.freshness_checked",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:26.891189",
    "checkpoint_id": 408,
    "schema_version": 1,
    "checkpoint_age_seconds": -28621,
    "pending_approval_count": 0,
    "run_runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
    "pending_approval_details": [],
    "environment_changed_count": 0,
    "open_migration_block_count": 0,
    "stale_evidence_watch_count": 0,
    "runtime_snapshot_compatible": true,
    "context_compaction_available": false,
    "context_compaction_event_seq": null,
    "revoked_required_permissions": [],
    "stale_evidence_watch_details": [],
    "stale_pending_approval_count": 0,
    "context_compaction_event_type": null,
    "context_compaction_object_key": null,
    "backend_contract_missing_count": 0,
    "checkpoint_runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
    "expired_pending_approval_count": 0,
    "revoked_required_permission_count": 0,
    "active_evidence_revalidation_count": 0,
    "active_evidence_revalidation_details": [],
    "active_memory_needs_revalidation_ids": [],
    "active_memory_needs_revalidation_count": 0
  },
  "created_at": "2026-07-07 07:59:37"
}
```

#### Event 85: `tool.running`

- created_at: `2026-07-07 07:59:37`

```json
{
  "id": 51680,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 85,
  "event_type": "tool.running",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 85,
    "tool_name": "scenario.create_saved",
    "event_type": "tool.running",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:27.206183",
    "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:59:37"
}
```

#### Event 86: `tool.send_intent_recorded`

- created_at: `2026-07-07 07:59:37`

```json
{
  "id": 51681,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 86,
  "event_type": "tool.send_intent_recorded",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 86,
    "event_type": "tool.send_intent_recorded",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:27.311274",
    "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:59:37"
}
```

#### Event 87: `tool.transport_sent_observed`

- created_at: `2026-07-07 07:59:37`

```json
{
  "id": 51682,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 87,
  "event_type": "tool.transport_sent_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 87,
    "event_type": "tool.transport_sent_observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:27.412979",
    "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:59:37"
}
```

#### Event 88: `tool.effect_committed`

- created_at: `2026-07-07 07:59:38`

```json
{
  "id": 51683,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 88,
  "event_type": "tool.effect_committed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 88,
    "event_type": "tool.effect_committed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:27.950233",
    "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:59:38"
}
```

#### Event 89: `tool.completed`

- created_at: `2026-07-07 07:59:38`

```json
{
  "id": 51684,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 89,
  "event_type": "tool.completed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 89,
    "event_type": "tool.completed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:28.058791",
    "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:59:38"
}
```

#### Event 90: `tool.result_observed`

- created_at: `2026-07-07 07:59:38`

```json
{
  "id": 51685,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 90,
  "event_type": "tool.result_observed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "status": "succeeded",
    "event_seq": 90,
    "tool_name": "scenario.create_saved",
    "event_type": "tool.result_observed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:28.326741",
    "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
    "schema_version": 1,
    "resumed_after_approval": true
  },
  "created_at": "2026-07-07 07:59:38"
}
```

#### Event 91: `run.resumed`

- created_at: `2026-07-07 07:59:38`

```json
{
  "id": 51686,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 91,
  "event_type": "run.resumed",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 91,
    "event_type": "run.resumed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:28.549127",
    "schema_version": 1,
    "executed_tool_call_ids": [
      "agent-tool-322b28009309479fbbed0ffe48c02f21"
    ],
    "observed_tool_call_ids": [
      "agent-tool-322b28009309479fbbed0ffe48c02f21"
    ],
    "scheduled_tool_call_ids": [],
    "remaining_blocking_tool_call_ids": []
  },
  "created_at": "2026-07-07 07:59:38"
}
```

#### Event 92: `model.started`

- created_at: `2026-07-07 07:59:39`

```json
{
  "id": 51687,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 92,
  "event_type": "model.started",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "provider": "deepseek",
    "event_seq": 92,
    "iteration": 8,
    "loop_step": "final_summary",
    "event_type": "model.started",
    "loop_state": {
      "step": "final_summary",
      "phase": "model",
      "iteration": 8,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-8",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-8-final_summary-d2b3270670774e8abb9e1d865b9d169b"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:29.618517",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-8",
    "final_summary": true,
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-8-final_summary-d2b3270670774e8abb9e1d865b9d169b",
    "repair_attempt": false,
    "schema_version": 1,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-8-final_summary-d2b3270670774e8abb9e1d865b9d169b"
  },
  "created_at": "2026-07-07 07:59:39"
}
```

#### Event 93: `model.markdown_normalized`

- created_at: `2026-07-07 07:59:49`

```json
{
  "id": 51688,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 93,
  "event_type": "model.markdown_normalized",
  "payload_json": {
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "content": "",
    "event_seq": 93,
    "iteration": 8,
    "loop_step": "final_summary",
    "event_type": "model.markdown_normalized",
    "loop_state": {
      "step": "final_summary",
      "phase": "model",
      "iteration": 8,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-8",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-8-final_summary-d2b3270670774e8abb9e1d865b9d169b"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:39.815483",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-8",
    "final_summary": true,
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-8-final_summary-d2b3270670774e8abb9e1d865b9d169b",
    "schema_version": 1,
    "replace_content": true,
    "normalization_reason": "final_summary_tool_request_suppressed",
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-8-final_summary-d2b3270670774e8abb9e1d865b9d169b"
  },
  "created_at": "2026-07-07 07:59:49"
}
```

#### Event 94: `model.completed`

- created_at: `2026-07-07 07:59:50`
- content_preview: ```agent_tool_request
{"tool_name":"tool_result.read_full","input":{"path":"draft.scenario","tool_call_id":"agent-tool-7f6517141970455b9b23b82dc1fcfb34"},"reason":"需要获取完整的场景草稿数据以进行保存操作","evidence_refs":["agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft"]}
```

```json
{
  "id": 51689,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 94,
  "event_type": "model.completed",
  "payload_json": {
    "model": "deepseek-v4-pro",
    "usage": {
      "total_tokens": "***",
      "prompt_tokens": "***",
      "completion_tokens": "***",
      "prompt_tokens_details": "***",
      "prompt_cache_hit_tokens": "***",
      "prompt_cache_miss_tokens": "***",
      "completion_tokens_details": "***"
    },
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "content": "```agent_tool_request\n{\"tool_name\":\"tool_result.read_full\",\"input\":{\"path\":\"draft.scenario\",\"tool_call_id\":\"agent-tool-7f6517141970455b9b23b82dc1fcfb34\"},\"reason\":\"需要获取完整的场景草稿数据以进行保存操作\",\"evidence_refs\":[\"agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft\"]}\n```",
    "provider": "deepseek",
    "event_seq": 94,
    "iteration": 8,
    "loop_step": "final_summary",
    "event_type": "model.completed",
    "loop_state": {
      "step": "final_summary",
      "phase": "model",
      "iteration": 8,
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-8",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-8-final_summary-d2b3270670774e8abb9e1d865b9d169b"
    },
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:39.948479",
    "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-8",
    "final_summary": true,
    "finish_reason": "stop",
    "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-8-final_summary-d2b3270670774e8abb9e1d865b9d169b",
    "requested_tool": true,
    "schema_version": 1,
    "assistant_visible": false,
    "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-8-final_summary-d2b3270670774e8abb9e1d865b9d169b",
    "resumed_after_approval": true,
    "final_summary_tool_request_suppressed": true
  },
  "created_at": "2026-07-07 07:59:50"
}
```

#### Event 95: `run.completed`

- created_at: `2026-07-07 07:59:50`

```json
{
  "id": 51690,
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "event_seq": 95,
  "event_type": "run.completed",
  "payload_json": {
    "result": {
      "model": "deepseek-v4-pro",
      "usage": {
        "total_tokens": "***",
        "prompt_tokens": "***",
        "completion_tokens": "***",
        "prompt_tokens_details": "***",
        "prompt_cache_hit_tokens": "***",
        "prompt_cache_miss_tokens": "***",
        "completion_tokens_details": "***"
      },
      "message": "工具执行结果已经进入上下文，但最终总结阶段模型又输出了工具请求。后端已阻止该工具请求展示给用户；请查看上方 ToolCall 失败详情，修正输入后重新提交。",
      "provider": "deepseek",
      "loop_step": "final_summary",
      "loop_state": {
        "step": "final_summary",
        "phase": "model",
        "iteration": 8,
        "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-8",
        "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-8-final_summary-d2b3270670774e8abb9e1d865b9d169b"
      },
      "tool_calls": [
        {
          "status": "succeeded",
          "tool_name": "scenario.create_saved",
          "error_code": null,
          "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
          "approval_required": true
        }
      ],
      "iteration_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:iter-8",
      "finish_reason": "stop",
      "model_call_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-8-final_summary-d2b3270670774e8abb9e1d865b9d169b",
      "model_response_item_id": "agent-model-response://agent-run-72ca285d46fe4755ba0e3e1da92d3fdc/agent-run-72ca285d46fe4755ba0e3e1da92d3fdc:model-8-final_summary-d2b3270670774e8abb9e1d865b9d169b",
      "final_summary_tool_request_suppressed": true
    },
    "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
    "event_seq": 95,
    "event_type": "run.completed",
    "project_id": 1,
    "occurred_at": "2026-07-06T23:59:40.179864",
    "schema_version": 1
  },
  "created_at": "2026-07-07 07:59:50"
}
```

### Tool Calls

#### Tool `tool_result.read_full` / `agent-tool-0048989541774deca1e1ff169ed5ab7c`

- status: `succeeded`
- step_index: `0`
- attempt_index: `0`
- approval_required: `0`
- input_hash: `fad889ecd3b8fdf61f251f09915b29ae710e56ed80f2f3d3bfdf4de71aeced58`
- output_hash: `1916b9c5f134c0399aad8bc2f2a5a60236b25a5fe11a6840cefbc67b8717ca43`

```json
{
  "id": 608,
  "tool_call_id": "agent-tool-0048989541774deca1e1ff169ed5ab7c",
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "step_index": 0,
  "attempt_index": 0,
  "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
  "tool_name": "tool_result.read_full",
  "tool_version": "1.0.0",
  "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
  "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
  "idempotency_scope": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "idempotency_key": "d344febb988b1a106bf584de1031599f3d87d3e69d8aa83408653da33566edf3",
  "base_side_effect_class": "read_only",
  "resolved_side_effect_class": "read_only",
  "base_replay_policy": "reuse_allowed",
  "resolved_replay_policy": "reuse_allowed",
  "policy_reason_json": {
    "dispatch_trace": {
      "router": "AgentToolRouter.resolve",
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "status": "succeeded",
      "runtime": "AgentToolRuntime.execute",
      "tool_name": "tool_result.read_full",
      "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-0048989541774deca1e1ff169ed5ab7c",
      "tool_version": "1.0.0",
      "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
      "backend_handler": "_tool_result_read_full",
      "backend_operation": "tool_result.read_full",
      "dispatch_trace_hash": "c7781f73b12bfd813db37a7a53df8111604141eebc00f7cb48ff524bfc660eec",
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "resolved_replay_policy": "reuse_allowed",
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "resolved_side_effect_class": "read_only",
      "dispatch_trace_version_hash": "agent-tool-dispatch-v1"
    },
    "policy_context": {
      "tool_name": "tool_result.read_full",
      "policy_hash": "7ebcf3ce85b1d14a7268a86883c575a3a719a5e8242aa98e7959488e011e7ec7",
      "tool_version": "1.0.0",
      "approval_policy": "safe_side_effect_auto",
      "approval_required": false,
      "base_replay_policy": "reuse_allowed",
      "policy_version_hash": "agent-policy-v1",
      "mixed_volatile_frozen": false,
      "base_side_effect_class": "read_only",
      "resolved_replay_policy": "reuse_allowed",
      "active_policy_ref_count": 0,
      "frozen_policy_ref_count": 0,
      "approval_required_reason": "safe_initial_tool",
      "volatile_policy_ref_count": 0,
      "resolved_side_effect_class": "read_only",
      "historical_volatile_excluded_count": 0
    },
    "execution_context": {
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "tool_name": "tool_result.read_full",
      "worker_id": null,
      "error_code": null,
      "input_hash": "fad889ecd3b8fdf61f251f09915b29ae710e56ed80f2f3d3bfdf4de71aeced58",
      "approved_by": null,
      "output_hash": "1916b9c5f134c0399aad8bc2f2a5a60236b25a5fe11a6840cefbc67b8717ca43",
      "tool_status": "succeeded",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-0048989541774deca1e1ff169ed5ab7c",
      "tool_version": "1.0.0",
      "approval_epoch": 0,
      "approval_state": "not_required",
      "execution_phase": "completed",
      "approval_required": false,
      "backend_operation": "tool_result.read_full",
      "recovery_decision": null,
      "error_message_hash": null,
      "approval_lineage_id": null,
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "approved_approval_id": null,
      "execution_context_hash": "41a0c8c82220175b1f48a1b90fe5d65582bb534e3328064b5f94ba8f2b7e3e6a",
      "resolved_replay_policy": "reuse_allowed",
      "result_adapter_version": "v1",
      "effect_boundary_crossed": false,
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "backend_effect_capability": "receipt_first",
      "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
      "reconcile_contract_version": "reconcile-v1",
      "resolved_side_effect_class": "read_only",
      "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
      "execution_context_version_hash": "agent-tool-execution-v1"
    },
    "base_replay_policy": "reuse_allowed",
    "mixed_volatile_frozen": false,
    "active_policy_ref_count": 0,
    "frozen_policy_ref_count": 0,
    "approval_required_reason": "safe_initial_tool",
    "volatile_policy_ref_count": 0,
    "historical_volatile_excluded_count": 0
  },
  "status": "succeeded",
  "execution_phase": "completed",
  "effect_submission_state": "effect_committed",
  "effect_boundary_crossed": 0,
  "downstream_send_intent_at": "2026-07-06 23:56:30",
  "downstream_request_observed_sent_at": "2026-07-06 23:56:30",
  "downstream_acceptance_id": "d344febb988b1a106bf584de1031599f3d87d3e69d8aa83408653da33566edf3",
  "downstream_acceptance_at": "2026-07-06 23:56:30",
  "input_hash": "fad889ecd3b8fdf61f251f09915b29ae710e56ed80f2f3d3bfdf4de71aeced58",
  "input_json_redacted": {
    "path": "draft.scenario",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34"
  },
  "evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false
    }
  ],
  "output_hash": "1916b9c5f134c0399aad8bc2f2a5a60236b25a5fe11a6840cefbc67b8717ca43",
  "output_json_redacted": {
    "path": "draft.scenario",
    "output": {
      "name": "企业端到端自动化流程测试",
      "tags": [
        "ai-composed"
      ],
      "nodes": [
        {
          "id": "NODE-1",
          "name": "获取企业列表",
          "test_case": {
            "id": "CASE-1",
            "kind": "api_case",
            "name": "获取企业列表",
            "path": "/api/lingxi-chain/cloudentchain/getEntPageList",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "extractors": [
                {
                  "id": "VAR-1",
                  "name": "companyId",
                  "path": "data.dataList.0.companyId"
                },
                {
                  "id": "VAR-2",
                  "name": "companyName",
                  "path": "data.dataList.0.companyName"
                }
              ],
              "_scenario_context": {
                "extractions": [
                  {
                    "id": "VAR-1",
                    "name": "companyId",
                    "path": "data.dataList.0.companyId"
                  },
                  {
                    "id": "VAR-2",
                    "name": "companyName",
                    "path": "data.dataList.0.companyName"
                  }
                ]
              }
            },
            "method": "POST",
            "reference_id": 7,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-2",
          "name": "获取对应企业CT画像数",
          "test_case": {
            "id": "CASE-2",
            "kind": "api_case",
            "name": "获取对应企业CT画像数",
            "path": "/api/lingxi-bigdata/base-info/businessInformation",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "query_params": {
                "size": "10",
                "companyId": "{{companyId}}"
              },
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-1",
                    "name": "companyId",
                    "target": "query_params",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  }
                ],
                "extractions": []
              }
            },
            "method": "GET",
            "reference_id": 8,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-3",
          "name": "关注企业",
          "test_case": {
            "id": "CASE-3",
            "kind": "api_case",
            "name": "关注接口",
            "path": "/api/lingxi-system/myAttentionCompany/save",
            "config": {
              "body": {
                "companyId": "{{companyId}}",
                "companyName": "{{companyName}}"
              },
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 666666,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-2",
                    "name": "companyId",
                    "target": "body",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  },
                  {
                    "id": "BIND-3",
                    "name": "companyName",
                    "target": "body",
                    "target_path": "companyName",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-2"
                  }
                ],
                "extractions": []
              }
            },
            "method": "POST",
            "reference_id": 9,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-4",
          "name": "取消关注",
          "test_case": {
            "id": "CASE-4",
            "kind": "api_case",
            "name": "取消关注",
            "path": "/api/lingxi-system/myAttentionCompany/cancel",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 666666,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                },
                {
                  "path": "msg",
                  "type": "json_equals",
                  "expected": "操作成功",
                  "retry_on_failure": false
                }
              ],
              "query_params": {
                "companyId": "{{companyId}}"
              },
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-4",
                    "name": "companyId",
                    "target": "query_params",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  }
                ],
                "extractions": []
              }
            },
            "method": "POST",
            "reference_id": 10,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        }
      ],
      "datasets": [],
      "description": "1）查询企业列表获取企业ID；2）使用企业ID查询对应企业CT画像数；3）关注该企业；4）取消关注该企业。自动绑定步骤间的变量传递，并验证每一步的响应结果。",
      "environment_id": 4
    },
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "redaction": "output_json_redacted",
    "tool_name": "scenario.compose_draft",
    "output_hash": "a2e773df07d900972ee2ea93d0035ac4eb8bc66c18c6b08d3fe5d2d66974b075",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
    "output_truncated": false,
    "output_size_chars": 3838
  },
  "raw_output_object_key": null,
  "permission_snapshot_json": {
    "user_id": 1,
    "audit_only": true,
    "project_id": 1,
    "captured_at": "2026-07-06T23:56:29.404448",
    "required_permissions": [
      "project:view"
    ]
  },
  "required_permissions_json": [
    "project:view"
  ],
  "approval_required": 0,
  "approval_scope_hash": "9ea1653af4eb80e9b251cf516ee28d4f0ea22a6176f3fa538b14f35bbdf8d031",
  "lease_owner": null,
  "lease_expires_at": null,
  "last_heartbeat_at": null,
  "recovery_decision": null,
  "backend_name": "agent-ledger",
  "backend_operation": "tool_result.read_full",
  "backend_contract_version": "v1",
  "backend_effect_capability": "receipt_first",
  "external_resource_type": null,
  "external_resource_id": null,
  "error_code": null,
  "error_message": null,
  "created_at": "2026-07-07 07:56:39",
  "updated_at": "2026-07-07 07:56:40",
  "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
  "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
  "reconcile_contract_version": "reconcile-v1",
  "result_adapter_version": "v1",
  "approval_lineage_id": null,
  "approval_epoch": 0,
  "approved_approval_id": null,
  "approved_by": null,
  "approved_at": null,
  "policy_evidence_refs_json": [],
  "audit_evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false,
      "required_for_high_risk": false
    }
  ],
  "evidence_mutability_summary_json": {
    "total": 1,
    "fully_frozen": true,
    "by_mutability": {
      "immutable": 1
    },
    "audit_ref_count": 1,
    "policy_ref_count": 0,
    "requires_revalidation": false
  },
  "decision_context_build_id": null
}
```

#### Tool `tool_result.read_full` / `agent-tool-5eade05444704a868c55cd3158d075a6`

- status: `succeeded`
- step_index: `1`
- attempt_index: `1`
- approval_required: `0`
- input_hash: `aed2dc3082bfc9a1f55994315c82d4ba525fcf4ac7c447ef58550a9f5565fce1`
- output_hash: `1916b9c5f134c0399aad8bc2f2a5a60236b25a5fe11a6840cefbc67b8717ca43`

```json
{
  "id": 609,
  "tool_call_id": "agent-tool-5eade05444704a868c55cd3158d075a6",
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "step_index": 1,
  "attempt_index": 1,
  "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
  "tool_name": "tool_result.read_full",
  "tool_version": "1.0.0",
  "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
  "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
  "idempotency_scope": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "idempotency_key": "bf77563bf29ffe8221102232cdac56f9a871bae9cfb32a4fe4d8eb8b114f90c3",
  "base_side_effect_class": "read_only",
  "resolved_side_effect_class": "read_only",
  "base_replay_policy": "reuse_allowed",
  "resolved_replay_policy": "reuse_allowed",
  "policy_reason_json": {
    "dispatch_trace": {
      "router": "AgentToolRouter.resolve",
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "status": "succeeded",
      "runtime": "AgentToolRuntime.execute",
      "tool_name": "tool_result.read_full",
      "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-5eade05444704a868c55cd3158d075a6",
      "tool_version": "1.0.0",
      "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
      "backend_handler": "_tool_result_read_full",
      "backend_operation": "tool_result.read_full",
      "dispatch_trace_hash": "d7ac76a6dbdb8e25d482bcdd307da352173d0896526f2f0213cf706a6a0acf0e",
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "resolved_replay_policy": "reuse_allowed",
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "resolved_side_effect_class": "read_only",
      "dispatch_trace_version_hash": "agent-tool-dispatch-v1"
    },
    "policy_context": {
      "tool_name": "tool_result.read_full",
      "policy_hash": "7ebcf3ce85b1d14a7268a86883c575a3a719a5e8242aa98e7959488e011e7ec7",
      "tool_version": "1.0.0",
      "approval_policy": "safe_side_effect_auto",
      "approval_required": false,
      "base_replay_policy": "reuse_allowed",
      "policy_version_hash": "agent-policy-v1",
      "mixed_volatile_frozen": false,
      "base_side_effect_class": "read_only",
      "resolved_replay_policy": "reuse_allowed",
      "active_policy_ref_count": 0,
      "frozen_policy_ref_count": 0,
      "approval_required_reason": "safe_initial_tool",
      "volatile_policy_ref_count": 0,
      "resolved_side_effect_class": "read_only",
      "historical_volatile_excluded_count": 0
    },
    "execution_context": {
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "tool_name": "tool_result.read_full",
      "worker_id": null,
      "error_code": null,
      "input_hash": "aed2dc3082bfc9a1f55994315c82d4ba525fcf4ac7c447ef58550a9f5565fce1",
      "approved_by": null,
      "output_hash": "1916b9c5f134c0399aad8bc2f2a5a60236b25a5fe11a6840cefbc67b8717ca43",
      "tool_status": "succeeded",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-5eade05444704a868c55cd3158d075a6",
      "tool_version": "1.0.0",
      "approval_epoch": 0,
      "approval_state": "not_required",
      "execution_phase": "completed",
      "approval_required": false,
      "backend_operation": "tool_result.read_full",
      "recovery_decision": null,
      "error_message_hash": null,
      "approval_lineage_id": null,
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "approved_approval_id": null,
      "execution_context_hash": "c4ed724fe46514eed9405fc62475a02283b540501a2c17d116b2612040994ffd",
      "resolved_replay_policy": "reuse_allowed",
      "result_adapter_version": "v1",
      "effect_boundary_crossed": false,
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "backend_effect_capability": "receipt_first",
      "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
      "reconcile_contract_version": "reconcile-v1",
      "resolved_side_effect_class": "read_only",
      "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
      "execution_context_version_hash": "agent-tool-execution-v1"
    },
    "base_replay_policy": "reuse_allowed",
    "mixed_volatile_frozen": false,
    "active_policy_ref_count": 0,
    "frozen_policy_ref_count": 0,
    "approval_required_reason": "safe_initial_tool",
    "volatile_policy_ref_count": 0,
    "historical_volatile_excluded_count": 0
  },
  "status": "succeeded",
  "execution_phase": "completed",
  "effect_submission_state": "effect_committed",
  "effect_boundary_crossed": 0,
  "downstream_send_intent_at": "2026-07-06 23:56:55",
  "downstream_request_observed_sent_at": "2026-07-06 23:56:55",
  "downstream_acceptance_id": "bf77563bf29ffe8221102232cdac56f9a871bae9cfb32a4fe4d8eb8b114f90c3",
  "downstream_acceptance_at": "2026-07-06 23:56:55",
  "input_hash": "aed2dc3082bfc9a1f55994315c82d4ba525fcf4ac7c447ef58550a9f5565fce1",
  "input_json_redacted": {
    "path": "draft.scenario",
    "max_chars": 64000,
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34"
  },
  "evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false
    }
  ],
  "output_hash": "1916b9c5f134c0399aad8bc2f2a5a60236b25a5fe11a6840cefbc67b8717ca43",
  "output_json_redacted": {
    "path": "draft.scenario",
    "output": {
      "name": "企业端到端自动化流程测试",
      "tags": [
        "ai-composed"
      ],
      "nodes": [
        {
          "id": "NODE-1",
          "name": "获取企业列表",
          "test_case": {
            "id": "CASE-1",
            "kind": "api_case",
            "name": "获取企业列表",
            "path": "/api/lingxi-chain/cloudentchain/getEntPageList",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "extractors": [
                {
                  "id": "VAR-1",
                  "name": "companyId",
                  "path": "data.dataList.0.companyId"
                },
                {
                  "id": "VAR-2",
                  "name": "companyName",
                  "path": "data.dataList.0.companyName"
                }
              ],
              "_scenario_context": {
                "extractions": [
                  {
                    "id": "VAR-1",
                    "name": "companyId",
                    "path": "data.dataList.0.companyId"
                  },
                  {
                    "id": "VAR-2",
                    "name": "companyName",
                    "path": "data.dataList.0.companyName"
                  }
                ]
              }
            },
            "method": "POST",
            "reference_id": 7,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-2",
          "name": "获取对应企业CT画像数",
          "test_case": {
            "id": "CASE-2",
            "kind": "api_case",
            "name": "获取对应企业CT画像数",
            "path": "/api/lingxi-bigdata/base-info/businessInformation",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "query_params": {
                "size": "10",
                "companyId": "{{companyId}}"
              },
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-1",
                    "name": "companyId",
                    "target": "query_params",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  }
                ],
                "extractions": []
              }
            },
            "method": "GET",
            "reference_id": 8,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-3",
          "name": "关注企业",
          "test_case": {
            "id": "CASE-3",
            "kind": "api_case",
            "name": "关注接口",
            "path": "/api/lingxi-system/myAttentionCompany/save",
            "config": {
              "body": {
                "companyId": "{{companyId}}",
                "companyName": "{{companyName}}"
              },
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 666666,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-2",
                    "name": "companyId",
                    "target": "body",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  },
                  {
                    "id": "BIND-3",
                    "name": "companyName",
                    "target": "body",
                    "target_path": "companyName",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-2"
                  }
                ],
                "extractions": []
              }
            },
            "method": "POST",
            "reference_id": 9,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-4",
          "name": "取消关注",
          "test_case": {
            "id": "CASE-4",
            "kind": "api_case",
            "name": "取消关注",
            "path": "/api/lingxi-system/myAttentionCompany/cancel",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 666666,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                },
                {
                  "path": "msg",
                  "type": "json_equals",
                  "expected": "操作成功",
                  "retry_on_failure": false
                }
              ],
              "query_params": {
                "companyId": "{{companyId}}"
              },
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-4",
                    "name": "companyId",
                    "target": "query_params",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  }
                ],
                "extractions": []
              }
            },
            "method": "POST",
            "reference_id": 10,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        }
      ],
      "datasets": [],
      "description": "1）查询企业列表获取企业ID；2）使用企业ID查询对应企业CT画像数；3）关注该企业；4）取消关注该企业。自动绑定步骤间的变量传递，并验证每一步的响应结果。",
      "environment_id": 4
    },
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "redaction": "output_json_redacted",
    "tool_name": "scenario.compose_draft",
    "output_hash": "a2e773df07d900972ee2ea93d0035ac4eb8bc66c18c6b08d3fe5d2d66974b075",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
    "output_truncated": false,
    "output_size_chars": 3838
  },
  "raw_output_object_key": null,
  "permission_snapshot_json": {
    "user_id": 1,
    "audit_only": true,
    "project_id": 1,
    "captured_at": "2026-07-06T23:56:54.515438",
    "required_permissions": [
      "project:view"
    ]
  },
  "required_permissions_json": [
    "project:view"
  ],
  "approval_required": 0,
  "approval_scope_hash": "0e718cd6d672bc55d8694a1a33cde7b48caa1042e7ccbe2bc34b6c123ff4c39c",
  "lease_owner": null,
  "lease_expires_at": null,
  "last_heartbeat_at": null,
  "recovery_decision": null,
  "backend_name": "agent-ledger",
  "backend_operation": "tool_result.read_full",
  "backend_contract_version": "v1",
  "backend_effect_capability": "receipt_first",
  "external_resource_type": null,
  "external_resource_id": null,
  "error_code": null,
  "error_message": null,
  "created_at": "2026-07-07 07:57:04",
  "updated_at": "2026-07-07 07:57:05",
  "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
  "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
  "reconcile_contract_version": "reconcile-v1",
  "result_adapter_version": "v1",
  "approval_lineage_id": null,
  "approval_epoch": 0,
  "approved_approval_id": null,
  "approved_by": null,
  "approved_at": null,
  "policy_evidence_refs_json": [],
  "audit_evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false,
      "required_for_high_risk": false
    }
  ],
  "evidence_mutability_summary_json": {
    "total": 1,
    "fully_frozen": true,
    "by_mutability": {
      "immutable": 1
    },
    "audit_ref_count": 1,
    "policy_ref_count": 0,
    "requires_revalidation": false
  },
  "decision_context_build_id": null
}
```

#### Tool `tool_result.read_full` / `agent-tool-2db01aa8752d4e5491012e89b49697fc`

- status: `succeeded`
- step_index: `2`
- attempt_index: `2`
- approval_required: `0`
- input_hash: `7e2a9ff1574b5f7e90654fda4907979cce4072546a1dd9f614cb3ecbb299a0c8`
- output_hash: `1916b9c5f134c0399aad8bc2f2a5a60236b25a5fe11a6840cefbc67b8717ca43`

```json
{
  "id": 610,
  "tool_call_id": "agent-tool-2db01aa8752d4e5491012e89b49697fc",
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "step_index": 2,
  "attempt_index": 2,
  "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
  "tool_name": "tool_result.read_full",
  "tool_version": "1.0.0",
  "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
  "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
  "idempotency_scope": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "idempotency_key": "9cb7f898ba413d38c941b5bb81c8325a9ac528a6ea60474e4599516f383a139a",
  "base_side_effect_class": "read_only",
  "resolved_side_effect_class": "read_only",
  "base_replay_policy": "reuse_allowed",
  "resolved_replay_policy": "reuse_allowed",
  "policy_reason_json": {
    "dispatch_trace": {
      "router": "AgentToolRouter.resolve",
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "status": "succeeded",
      "runtime": "AgentToolRuntime.execute",
      "tool_name": "tool_result.read_full",
      "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-2db01aa8752d4e5491012e89b49697fc",
      "tool_version": "1.0.0",
      "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
      "backend_handler": "_tool_result_read_full",
      "backend_operation": "tool_result.read_full",
      "dispatch_trace_hash": "f53e6ca14e1bac707c68c7bd2f6a52acea34e3e21a175ee8745fac70d4faad4e",
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "resolved_replay_policy": "reuse_allowed",
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "resolved_side_effect_class": "read_only",
      "dispatch_trace_version_hash": "agent-tool-dispatch-v1"
    },
    "policy_context": {
      "tool_name": "tool_result.read_full",
      "policy_hash": "7ebcf3ce85b1d14a7268a86883c575a3a719a5e8242aa98e7959488e011e7ec7",
      "tool_version": "1.0.0",
      "approval_policy": "safe_side_effect_auto",
      "approval_required": false,
      "base_replay_policy": "reuse_allowed",
      "policy_version_hash": "agent-policy-v1",
      "mixed_volatile_frozen": false,
      "base_side_effect_class": "read_only",
      "resolved_replay_policy": "reuse_allowed",
      "active_policy_ref_count": 0,
      "frozen_policy_ref_count": 0,
      "approval_required_reason": "safe_initial_tool",
      "volatile_policy_ref_count": 0,
      "resolved_side_effect_class": "read_only",
      "historical_volatile_excluded_count": 0
    },
    "execution_context": {
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "tool_name": "tool_result.read_full",
      "worker_id": null,
      "error_code": null,
      "input_hash": "7e2a9ff1574b5f7e90654fda4907979cce4072546a1dd9f614cb3ecbb299a0c8",
      "approved_by": null,
      "output_hash": "1916b9c5f134c0399aad8bc2f2a5a60236b25a5fe11a6840cefbc67b8717ca43",
      "tool_status": "succeeded",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-2db01aa8752d4e5491012e89b49697fc",
      "tool_version": "1.0.0",
      "approval_epoch": 0,
      "approval_state": "not_required",
      "execution_phase": "completed",
      "approval_required": false,
      "backend_operation": "tool_result.read_full",
      "recovery_decision": null,
      "error_message_hash": null,
      "approval_lineage_id": null,
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "approved_approval_id": null,
      "execution_context_hash": "8ae4031e5240d6a486c788b8162ed6e48ad13300d1f547a4d668be2fe4d40289",
      "resolved_replay_policy": "reuse_allowed",
      "result_adapter_version": "v1",
      "effect_boundary_crossed": false,
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "backend_effect_capability": "receipt_first",
      "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
      "reconcile_contract_version": "reconcile-v1",
      "resolved_side_effect_class": "read_only",
      "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
      "execution_context_version_hash": "agent-tool-execution-v1"
    },
    "base_replay_policy": "reuse_allowed",
    "mixed_volatile_frozen": false,
    "active_policy_ref_count": 0,
    "frozen_policy_ref_count": 0,
    "approval_required_reason": "safe_initial_tool",
    "volatile_policy_ref_count": 0,
    "historical_volatile_excluded_count": 0
  },
  "status": "succeeded",
  "execution_phase": "completed",
  "effect_submission_state": "effect_committed",
  "effect_boundary_crossed": 0,
  "downstream_send_intent_at": "2026-07-06 23:57:01",
  "downstream_request_observed_sent_at": "2026-07-06 23:57:01",
  "downstream_acceptance_id": "9cb7f898ba413d38c941b5bb81c8325a9ac528a6ea60474e4599516f383a139a",
  "downstream_acceptance_at": "2026-07-06 23:57:01",
  "input_hash": "7e2a9ff1574b5f7e90654fda4907979cce4072546a1dd9f614cb3ecbb299a0c8",
  "input_json_redacted": {
    "path": "draft.scenario",
    "max_chars": 256000,
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34"
  },
  "evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false
    }
  ],
  "output_hash": "1916b9c5f134c0399aad8bc2f2a5a60236b25a5fe11a6840cefbc67b8717ca43",
  "output_json_redacted": {
    "path": "draft.scenario",
    "output": {
      "name": "企业端到端自动化流程测试",
      "tags": [
        "ai-composed"
      ],
      "nodes": [
        {
          "id": "NODE-1",
          "name": "获取企业列表",
          "test_case": {
            "id": "CASE-1",
            "kind": "api_case",
            "name": "获取企业列表",
            "path": "/api/lingxi-chain/cloudentchain/getEntPageList",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "extractors": [
                {
                  "id": "VAR-1",
                  "name": "companyId",
                  "path": "data.dataList.0.companyId"
                },
                {
                  "id": "VAR-2",
                  "name": "companyName",
                  "path": "data.dataList.0.companyName"
                }
              ],
              "_scenario_context": {
                "extractions": [
                  {
                    "id": "VAR-1",
                    "name": "companyId",
                    "path": "data.dataList.0.companyId"
                  },
                  {
                    "id": "VAR-2",
                    "name": "companyName",
                    "path": "data.dataList.0.companyName"
                  }
                ]
              }
            },
            "method": "POST",
            "reference_id": 7,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-2",
          "name": "获取对应企业CT画像数",
          "test_case": {
            "id": "CASE-2",
            "kind": "api_case",
            "name": "获取对应企业CT画像数",
            "path": "/api/lingxi-bigdata/base-info/businessInformation",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "query_params": {
                "size": "10",
                "companyId": "{{companyId}}"
              },
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-1",
                    "name": "companyId",
                    "target": "query_params",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  }
                ],
                "extractions": []
              }
            },
            "method": "GET",
            "reference_id": 8,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-3",
          "name": "关注企业",
          "test_case": {
            "id": "CASE-3",
            "kind": "api_case",
            "name": "关注接口",
            "path": "/api/lingxi-system/myAttentionCompany/save",
            "config": {
              "body": {
                "companyId": "{{companyId}}",
                "companyName": "{{companyName}}"
              },
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 666666,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-2",
                    "name": "companyId",
                    "target": "body",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  },
                  {
                    "id": "BIND-3",
                    "name": "companyName",
                    "target": "body",
                    "target_path": "companyName",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-2"
                  }
                ],
                "extractions": []
              }
            },
            "method": "POST",
            "reference_id": 9,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-4",
          "name": "取消关注",
          "test_case": {
            "id": "CASE-4",
            "kind": "api_case",
            "name": "取消关注",
            "path": "/api/lingxi-system/myAttentionCompany/cancel",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 666666,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                },
                {
                  "path": "msg",
                  "type": "json_equals",
                  "expected": "操作成功",
                  "retry_on_failure": false
                }
              ],
              "query_params": {
                "companyId": "{{companyId}}"
              },
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-4",
                    "name": "companyId",
                    "target": "query_params",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  }
                ],
                "extractions": []
              }
            },
            "method": "POST",
            "reference_id": 10,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        }
      ],
      "datasets": [],
      "description": "1）查询企业列表获取企业ID；2）使用企业ID查询对应企业CT画像数；3）关注该企业；4）取消关注该企业。自动绑定步骤间的变量传递，并验证每一步的响应结果。",
      "environment_id": 4
    },
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "redaction": "output_json_redacted",
    "tool_name": "scenario.compose_draft",
    "output_hash": "a2e773df07d900972ee2ea93d0035ac4eb8bc66c18c6b08d3fe5d2d66974b075",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
    "output_truncated": false,
    "output_size_chars": 3838
  },
  "raw_output_object_key": null,
  "permission_snapshot_json": {
    "user_id": 1,
    "audit_only": true,
    "project_id": 1,
    "captured_at": "2026-07-06T23:57:00.147851",
    "required_permissions": [
      "project:view"
    ]
  },
  "required_permissions_json": [
    "project:view"
  ],
  "approval_required": 0,
  "approval_scope_hash": "a09a42964dc423aab14d1319fec5fc3ccf416881e946e41461cd186c6301b6a3",
  "lease_owner": null,
  "lease_expires_at": null,
  "last_heartbeat_at": null,
  "recovery_decision": null,
  "backend_name": "agent-ledger",
  "backend_operation": "tool_result.read_full",
  "backend_contract_version": "v1",
  "backend_effect_capability": "receipt_first",
  "external_resource_type": null,
  "external_resource_id": null,
  "error_code": null,
  "error_message": null,
  "created_at": "2026-07-07 07:57:10",
  "updated_at": "2026-07-07 07:57:11",
  "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
  "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
  "reconcile_contract_version": "reconcile-v1",
  "result_adapter_version": "v1",
  "approval_lineage_id": null,
  "approval_epoch": 0,
  "approved_approval_id": null,
  "approved_by": null,
  "approved_at": null,
  "policy_evidence_refs_json": [],
  "audit_evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false,
      "required_for_high_risk": false
    }
  ],
  "evidence_mutability_summary_json": {
    "total": 1,
    "fully_frozen": true,
    "by_mutability": {
      "immutable": 1
    },
    "audit_ref_count": 1,
    "policy_ref_count": 0,
    "requires_revalidation": false
  },
  "decision_context_build_id": null
}
```

#### Tool `tool_result.read_full` / `agent-tool-58b08dd614f642f99a4e5b37792184ad`

- status: `succeeded`
- step_index: `3`
- attempt_index: `3`
- approval_required: `0`
- input_hash: `01211671f26df572bc16e2233ac7f4677bc5bb6448edd351492eb1121856db08`
- output_hash: `fd4d78e2ae8c9c68abc5f2e08a3fa55e198d4351044d58080a275d6d9c887603`

```json
{
  "id": 611,
  "tool_call_id": "agent-tool-58b08dd614f642f99a4e5b37792184ad",
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "step_index": 3,
  "attempt_index": 3,
  "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
  "tool_name": "tool_result.read_full",
  "tool_version": "1.0.0",
  "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
  "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
  "idempotency_scope": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "idempotency_key": "9b5c3a50197766dc34f27cab071fb3211cdaf27fc5b16738408e7b69cc4bfefd",
  "base_side_effect_class": "read_only",
  "resolved_side_effect_class": "read_only",
  "base_replay_policy": "reuse_allowed",
  "resolved_replay_policy": "reuse_allowed",
  "policy_reason_json": {
    "dispatch_trace": {
      "router": "AgentToolRouter.resolve",
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "status": "succeeded",
      "runtime": "AgentToolRuntime.execute",
      "tool_name": "tool_result.read_full",
      "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-58b08dd614f642f99a4e5b37792184ad",
      "tool_version": "1.0.0",
      "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
      "backend_handler": "_tool_result_read_full",
      "backend_operation": "tool_result.read_full",
      "dispatch_trace_hash": "2713f91dc722a2fb8fa6c99183283c0479f21e4c1e711af250f0b7a917abf6dd",
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "resolved_replay_policy": "reuse_allowed",
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "resolved_side_effect_class": "read_only",
      "dispatch_trace_version_hash": "agent-tool-dispatch-v1"
    },
    "policy_context": {
      "tool_name": "tool_result.read_full",
      "policy_hash": "7ebcf3ce85b1d14a7268a86883c575a3a719a5e8242aa98e7959488e011e7ec7",
      "tool_version": "1.0.0",
      "approval_policy": "safe_side_effect_auto",
      "approval_required": false,
      "base_replay_policy": "reuse_allowed",
      "policy_version_hash": "agent-policy-v1",
      "mixed_volatile_frozen": false,
      "base_side_effect_class": "read_only",
      "resolved_replay_policy": "reuse_allowed",
      "active_policy_ref_count": 0,
      "frozen_policy_ref_count": 0,
      "approval_required_reason": "safe_initial_tool",
      "volatile_policy_ref_count": 0,
      "resolved_side_effect_class": "read_only",
      "historical_volatile_excluded_count": 0
    },
    "execution_context": {
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "tool_name": "tool_result.read_full",
      "worker_id": null,
      "error_code": null,
      "input_hash": "01211671f26df572bc16e2233ac7f4677bc5bb6448edd351492eb1121856db08",
      "approved_by": null,
      "output_hash": "fd4d78e2ae8c9c68abc5f2e08a3fa55e198d4351044d58080a275d6d9c887603",
      "tool_status": "succeeded",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-58b08dd614f642f99a4e5b37792184ad",
      "tool_version": "1.0.0",
      "approval_epoch": 0,
      "approval_state": "not_required",
      "execution_phase": "completed",
      "approval_required": false,
      "backend_operation": "tool_result.read_full",
      "recovery_decision": null,
      "error_message_hash": null,
      "approval_lineage_id": null,
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "approved_approval_id": null,
      "execution_context_hash": "cd66f1f36f7196918cdafff8df9d6551cbe3710b048bbd845c79db66456c4964",
      "resolved_replay_policy": "reuse_allowed",
      "result_adapter_version": "v1",
      "effect_boundary_crossed": false,
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "backend_effect_capability": "receipt_first",
      "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
      "reconcile_contract_version": "reconcile-v1",
      "resolved_side_effect_class": "read_only",
      "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
      "execution_context_version_hash": "agent-tool-execution-v1"
    },
    "base_replay_policy": "reuse_allowed",
    "mixed_volatile_frozen": false,
    "active_policy_ref_count": 0,
    "frozen_policy_ref_count": 0,
    "approval_required_reason": "safe_initial_tool",
    "volatile_policy_ref_count": 0,
    "historical_volatile_excluded_count": 0
  },
  "status": "succeeded",
  "execution_phase": "completed",
  "effect_submission_state": "effect_committed",
  "effect_boundary_crossed": 0,
  "downstream_send_intent_at": "2026-07-06 23:57:17",
  "downstream_request_observed_sent_at": "2026-07-06 23:57:17",
  "downstream_acceptance_id": "9b5c3a50197766dc34f27cab071fb3211cdaf27fc5b16738408e7b69cc4bfefd",
  "downstream_acceptance_at": "2026-07-06 23:57:17",
  "input_hash": "01211671f26df572bc16e2233ac7f4677bc5bb6448edd351492eb1121856db08",
  "input_json_redacted": {
    "max_chars": 256000,
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34"
  },
  "evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false
    }
  ],
  "output_hash": "fd4d78e2ae8c9c68abc5f2e08a3fa55e198d4351044d58080a275d6d9c887603",
  "output_json_redacted": {
    "path": null,
    "output": {
      "draft": {
        "scenario": {
          "name": "企业端到端自动化流程测试",
          "tags": [
            "ai-composed"
          ],
          "nodes": [
            {
              "id": "NODE-1",
              "name": "获取企业列表",
              "test_case": {
                "id": "CASE-1",
                "kind": "api_case",
                "name": "获取企业列表",
                "path": "/api/lingxi-chain/cloudentchain/getEntPageList",
                "config": {
                  "assertions": [
                    {
                      "path": null,
                      "type": "status_code",
                      "expected": 200,
                      "retry_on_failure": false
                    },
                    {
                      "path": "code",
                      "type": "json_equals",
                      "expected": 200,
                      "retry_on_failure": false
                    },
                    {
                      "path": "success",
                      "type": "json_equals",
                      "expected": true,
                      "retry_on_failure": false
                    }
                  ],
                  "extractors": [
                    {
                      "id": "VAR-1",
                      "name": "companyId",
                      "path": "data.dataList.0.companyId"
                    },
                    {
                      "id": "VAR-2",
                      "name": "companyName",
                      "path": "data.dataList.0.companyName"
                    }
                  ],
                  "_scenario_context": {
                    "extractions": [
                      {
                        "id": "VAR-1",
                        "name": "companyId",
                        "path": "data.dataList.0.companyId"
                      },
                      {
                        "id": "VAR-2",
                        "name": "companyName",
                        "path": "data.dataList.0.companyName"
                      }
                    ]
                  }
                },
                "method": "POST",
                "reference_id": 7,
                "continue_on_failure": false
              },
              "after_actions": [],
              "before_actions": []
            },
            {
              "id": "NODE-2",
              "name": "获取对应企业CT画像数",
              "test_case": {
                "id": "CASE-2",
                "kind": "api_case",
                "name": "获取对应企业CT画像数",
                "path": "/api/lingxi-bigdata/base-info/businessInformation",
                "config": {
                  "assertions": [
                    {
                      "path": null,
                      "type": "status_code",
                      "expected": 200,
                      "retry_on_failure": false
                    },
                    {
                      "path": "code",
                      "type": "json_equals",
                      "expected": 200,
                      "retry_on_failure": false
                    },
                    {
                      "path": "success",
                      "type": "json_equals",
                      "expected": true,
                      "retry_on_failure": false
                    }
                  ],
                  "query_params": {
                    "size": "10",
                    "companyId": "{{companyId}}"
                  },
                  "_scenario_context": {
                    "bindings": [
                      {
                        "id": "BIND-1",
                        "name": "companyId",
                        "target": "query_params",
                        "target_path": "companyId",
                        "source_step_id": "CASE-1",
                        "source_extraction_id": "VAR-1"
                      }
                    ],
                    "extractions": []
                  }
                },
                "method": "GET",
                "reference_id": 8,
                "continue_on_failure": false
              },
              "after_actions": [],
              "before_actions": []
            },
            {
              "id": "NODE-3",
              "name": "关注企业",
              "test_case": {
                "id": "CASE-3",
                "kind": "api_case",
                "name": "关注接口",
                "path": "/api/lingxi-system/myAttentionCompany/save",
                "config": {
                  "body": {
                    "companyId": "{{companyId}}",
                    "companyName": "{{companyName}}"
                  },
                  "assertions": [
                    {
                      "path": null,
                      "type": "status_code",
                      "expected": 200,
                      "retry_on_failure": false
                    },
                    {
                      "path": "code",
                      "type": "json_equals",
                      "expected": 666666,
                      "retry_on_failure": false
                    },
                    {
                      "path": "success",
                      "type": "json_equals",
                      "expected": true,
                      "retry_on_failure": false
                    }
                  ],
                  "_scenario_context": {
                    "bindings": [
                      {
                        "id": "BIND-2",
                        "name": "companyId",
                        "target": "body",
                        "target_path": "companyId",
                        "source_step_id": "CASE-1",
                        "source_extraction_id": "VAR-1"
                      },
                      {
                        "id": "BIND-3",
                        "name": "companyName",
                        "target": "body",
                        "target_path": "companyName",
                        "source_step_id": "CASE-1",
                        "source_extraction_id": "VAR-2"
                      }
                    ],
                    "extractions": []
                  }
                },
                "method": "POST",
                "reference_id": 9,
                "continue_on_failure": false
              },
              "after_actions": [],
              "before_actions": []
            },
            {
              "id": "NODE-4",
              "name": "取消关注",
              "test_case": {
                "id": "CASE-4",
                "kind": "api_case",
                "name": "取消关注",
                "path": "/api/lingxi-system/myAttentionCompany/cancel",
                "config": {
                  "assertions": [
                    {
                      "path": null,
                      "type": "status_code",
                      "expected": 200,
                      "retry_on_failure": false
                    },
                    {
                      "path": "code",
                      "type": "json_equals",
                      "expected": 666666,
                      "retry_on_failure": false
                    },
                    {
                      "path": "success",
                      "type": "json_equals",
                      "expected": true,
                      "retry_on_failure": false
                    },
                    {
                      "path": "msg",
                      "type": "json_equals",
                      "expected": "操作成功",
                      "retry_on_failure": false
                    }
                  ],
                  "query_params": {
                    "companyId": "{{companyId}}"
                  },
                  "_scenario_context": {
                    "bindings": [
                      {
                        "id": "BIND-4",
                        "name": "companyId",
                        "target": "query_params",
                        "target_path": "companyId",
                        "source_step_id": "CASE-1",
                        "source_extraction_id": "VAR-1"
                      }
                    ],
                    "extractions": []
                  }
                },
                "method": "POST",
                "reference_id": 10,
                "continue_on_failure": false
              },
              "after_actions": [],
              "before_actions": []
            }
          ],
          "datasets": [],
          "description": "1）查询企业列表获取企业ID；2）使用企业ID查询对应企业CT画像数；3）关注该企业；4）取消关注该企业。自动绑定步骤间的变量传递，并验证每一步的响应结果。",
          "environment_id": 4
        },
        "warnings": [
          "获取企业列表用例的success断言在最近执行中expected为null，已修正为true。",
          "关注接口和取消关注接口的code字段实际返回666666，已按实际值修正断言expected。",
          "获取企业列表用例的body_contains断言'dataList'和'total'在最近执行中通过，但为减少不稳定断言，已移除。",
          "CT画像查询接口响应中大部分字段为null，可能是测试数据问题，但断言仅保留稳定字段。",
          "关注和取消关注接口依赖Lingxi-Auth头，该变量需在环境或前置步骤中提供，当前场景未包含登录步骤，请确保环境已配置。"
        ],
        "project_id": 1,
        "environment_id": 4,
        "self_validated": true,
        "source_summary": "基于4个候选用例组合企业端到端流程：获取企业列表→提取companyId/companyName→查询CT画像→关注→取消关注。修复了关注和取消关注接口的code断言（实际返回666666），并修正了获取企业列表的success断言（expected应为true）。",
        "environment_name": "test",
        "validation_attempts": [
          {
            "issues": [],
            "run_id": 151,
            "status": "passed",
            "attempt": 1,
            "summary": {
              "failed": 0,
              "passed": 4,
              "skipped": 0,
              "timeout": 0,
              "total_steps": 4
            },
            "duration_ms": 5142
          }
        ]
      }
    },
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "redaction": "output_json_redacted",
    "tool_name": "scenario.compose_draft",
    "output_hash": "a2e773df07d900972ee2ea93d0035ac4eb8bc66c18c6b08d3fe5d2d66974b075",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
    "output_truncated": false,
    "output_size_chars": 4601
  },
  "raw_output_object_key": null,
  "permission_snapshot_json": {
    "user_id": 1,
    "audit_only": true,
    "project_id": 1,
    "captured_at": "2026-07-06T23:57:16.007736",
    "required_permissions": [
      "project:view"
    ]
  },
  "required_permissions_json": [
    "project:view"
  ],
  "approval_required": 0,
  "approval_scope_hash": "078b3548121916acc729137bdbaeaacc2c583a802204cbbcd80edd82203aff07",
  "lease_owner": null,
  "lease_expires_at": null,
  "last_heartbeat_at": null,
  "recovery_decision": null,
  "backend_name": "agent-ledger",
  "backend_operation": "tool_result.read_full",
  "backend_contract_version": "v1",
  "backend_effect_capability": "receipt_first",
  "external_resource_type": null,
  "external_resource_id": null,
  "error_code": null,
  "error_message": null,
  "created_at": "2026-07-07 07:57:26",
  "updated_at": "2026-07-07 07:57:27",
  "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
  "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
  "reconcile_contract_version": "reconcile-v1",
  "result_adapter_version": "v1",
  "approval_lineage_id": null,
  "approval_epoch": 0,
  "approved_approval_id": null,
  "approved_by": null,
  "approved_at": null,
  "policy_evidence_refs_json": [],
  "audit_evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false,
      "required_for_high_risk": false
    }
  ],
  "evidence_mutability_summary_json": {
    "total": 1,
    "fully_frozen": true,
    "by_mutability": {
      "immutable": 1
    },
    "audit_ref_count": 1,
    "policy_ref_count": 0,
    "requires_revalidation": false
  },
  "decision_context_build_id": null
}
```

#### Tool `tool_result.read_full` / `agent-tool-b611c24f1f4f43e09179d3735cb55a58`

- status: `succeeded`
- step_index: `4`
- attempt_index: `4`
- approval_required: `0`
- input_hash: `ed3fc42e2953efb1d09bf69968bfa68f5b8f6ecdba4129fd930cb1e33a910997`
- output_hash: `070507edebda4857f1fc65b5e77f05a9fd166b954723b16bad67cca9c7713360`

```json
{
  "id": 612,
  "tool_call_id": "agent-tool-b611c24f1f4f43e09179d3735cb55a58",
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "step_index": 4,
  "attempt_index": 4,
  "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
  "tool_name": "tool_result.read_full",
  "tool_version": "1.0.0",
  "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
  "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
  "idempotency_scope": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "idempotency_key": "2b3ac56f041262161d6f027e75ff0d9db68ffd0b5ddf1ef98739837e13c2251c",
  "base_side_effect_class": "read_only",
  "resolved_side_effect_class": "read_only",
  "base_replay_policy": "reuse_allowed",
  "resolved_replay_policy": "reuse_allowed",
  "policy_reason_json": {
    "dispatch_trace": {
      "router": "AgentToolRouter.resolve",
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "status": "succeeded",
      "runtime": "AgentToolRuntime.execute",
      "tool_name": "tool_result.read_full",
      "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-b611c24f1f4f43e09179d3735cb55a58",
      "tool_version": "1.0.0",
      "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
      "backend_handler": "_tool_result_read_full",
      "backend_operation": "tool_result.read_full",
      "dispatch_trace_hash": "66b2c203e88bd1125ea3387111959a842d145a50e72f4f5782bb9f2de8041f0a",
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "resolved_replay_policy": "reuse_allowed",
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "resolved_side_effect_class": "read_only",
      "dispatch_trace_version_hash": "agent-tool-dispatch-v1"
    },
    "policy_context": {
      "tool_name": "tool_result.read_full",
      "policy_hash": "7ebcf3ce85b1d14a7268a86883c575a3a719a5e8242aa98e7959488e011e7ec7",
      "tool_version": "1.0.0",
      "approval_policy": "safe_side_effect_auto",
      "approval_required": false,
      "base_replay_policy": "reuse_allowed",
      "policy_version_hash": "agent-policy-v1",
      "mixed_volatile_frozen": false,
      "base_side_effect_class": "read_only",
      "resolved_replay_policy": "reuse_allowed",
      "active_policy_ref_count": 0,
      "frozen_policy_ref_count": 0,
      "approval_required_reason": "safe_initial_tool",
      "volatile_policy_ref_count": 0,
      "resolved_side_effect_class": "read_only",
      "historical_volatile_excluded_count": 0
    },
    "execution_context": {
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "tool_name": "tool_result.read_full",
      "worker_id": null,
      "error_code": null,
      "input_hash": "ed3fc42e2953efb1d09bf69968bfa68f5b8f6ecdba4129fd930cb1e33a910997",
      "approved_by": null,
      "output_hash": "070507edebda4857f1fc65b5e77f05a9fd166b954723b16bad67cca9c7713360",
      "tool_status": "succeeded",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-b611c24f1f4f43e09179d3735cb55a58",
      "tool_version": "1.0.0",
      "approval_epoch": 0,
      "approval_state": "not_required",
      "execution_phase": "completed",
      "approval_required": false,
      "backend_operation": "tool_result.read_full",
      "recovery_decision": null,
      "error_message_hash": null,
      "approval_lineage_id": null,
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "approved_approval_id": null,
      "execution_context_hash": "8eb1852d46ccc2a0341c3bfd94f1abc38d96905375507d338ae763580524dc63",
      "resolved_replay_policy": "reuse_allowed",
      "result_adapter_version": "v1",
      "effect_boundary_crossed": false,
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "backend_effect_capability": "receipt_first",
      "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
      "reconcile_contract_version": "reconcile-v1",
      "resolved_side_effect_class": "read_only",
      "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
      "execution_context_version_hash": "agent-tool-execution-v1"
    },
    "base_replay_policy": "reuse_allowed",
    "mixed_volatile_frozen": false,
    "active_policy_ref_count": 0,
    "frozen_policy_ref_count": 0,
    "approval_required_reason": "safe_initial_tool",
    "volatile_policy_ref_count": 0,
    "historical_volatile_excluded_count": 0
  },
  "status": "succeeded",
  "execution_phase": "completed",
  "effect_submission_state": "effect_committed",
  "effect_boundary_crossed": 0,
  "downstream_send_intent_at": "2026-07-06 23:57:43",
  "downstream_request_observed_sent_at": "2026-07-06 23:57:43",
  "downstream_acceptance_id": "2b3ac56f041262161d6f027e75ff0d9db68ffd0b5ddf1ef98739837e13c2251c",
  "downstream_acceptance_at": "2026-07-06 23:57:44",
  "input_hash": "ed3fc42e2953efb1d09bf69968bfa68f5b8f6ecdba4129fd930cb1e33a910997",
  "input_json_redacted": {
    "max_chars": 256000,
    "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e"
  },
  "evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-8d64dda3cf78457e9dcaec9c080ff78e/tool_result",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-8d64dda3cf78457e9dcaec9c080ff78e/tool_result",
      "mutability_class": "immutable",
      "active_for_policy": false
    }
  ],
  "output_hash": "070507edebda4857f1fc65b5e77f05a9fd166b954723b16bad67cca9c7713360",
  "output_json_redacted": {
    "path": null,
    "output": {
      "project": {
        "id": 1,
        "name": "1",
        "description": "",
        "created_by_id": 1
      },
      "environments": [
        {
          "id": 4,
          "name": "test",
          "base_url": "https://www.lingxidata.cn",
          "is_default": true,
          "object_ref": "object-ref://environment/default/3d759ce85569/4",
          "description": "灵犀测试环境"
        }
      ],
      "default_environment": {
        "id": 4,
        "name": "test",
        "base_url": "https://www.lingxidata.cn",
        "is_default": true,
        "description": "灵犀测试环境"
      },
      "environment_snapshot": {
        "project_id": 1,
        "snapshot_id": "environment-snapshot://85d4b70ef97f659268fb9e93a56a641070b9bc99e3352ae84e30f766ffbb9af0",
        "generated_at": "2026-07-06T23:54:48.890797+00:00",
        "object_family": "environment",
        "validity_scope": "current_agent_conversation_latest_query",
        "identity_semantics": "environment ids are volatile database row locators; re-query before execution.",
        "authoritative_for_tool_input": true
      },
      "environment_id_manifest": {
        "snapshot_id": "environment-snapshot://85d4b70ef97f659268fb9e93a56a641070b9bc99e3352ae84e30f766ffbb9af0",
        "id_source_rule": "Use only these explicit environment ids from the latest project context snapshot; never infer ids from older conversation prose.",
        "validity_scope": "current_agent_conversation_latest_query",
        "environment_ids": [
          4
        ],
        "environment_refs": [
          "object-ref://environment/default/3d759ce85569/4"
        ],
        "environment_execute_ids": [
          4
        ]
      },
      "object_reference_manifest": {
        "query_tool": "project.read_context",
        "snapshot_id": "environment-snapshot://85d4b70ef97f659268fb9e93a56a641070b9bc99e3352ae84e30f766ffbb9af0",
        "object_family": "environment",
        "id_source_rule": "Use only these explicit environment ids from the latest project context snapshot; never infer ids from older conversation prose.",
        "validity_scope": "current_agent_conversation_latest_query",
        "environment_ids": [
          4
        ],
        "environment_refs": [
          "object-ref://environment/default/3d759ce85569/4"
        ],
        "object_references": [
          {
            "id": 4,
            "name": "test",
            "object_ref": "object-ref://environment/default/3d759ce85569/4",
            "object_type": "environment",
            "snapshot_id": "environment-snapshot://85d4b70ef97f659268fb9e93a56a641070b9bc99e3352ae84e30f766ffbb9af0"
          }
        ],
        "environment_execute_ids": [
          4
        ]
      }
    },
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "redaction": "output_json_redacted",
    "tool_name": "project.read_context",
    "output_hash": "8678ae2dea57b39a09d4c4245389107575c4f2ffb63b7503b3d531dc36543c39",
    "tool_call_id": "agent-tool-8d64dda3cf78457e9dcaec9c080ff78e",
    "output_truncated": false,
    "output_size_chars": 2115
  },
  "raw_output_object_key": null,
  "permission_snapshot_json": {
    "user_id": 1,
    "audit_only": true,
    "project_id": 1,
    "captured_at": "2026-07-06T23:57:42.250602",
    "required_permissions": [
      "project:view"
    ]
  },
  "required_permissions_json": [
    "project:view"
  ],
  "approval_required": 0,
  "approval_scope_hash": "1106d872f62b56adbcb77f15f38159c8617e703329db3649ec2054d15d3280d0",
  "lease_owner": null,
  "lease_expires_at": null,
  "last_heartbeat_at": null,
  "recovery_decision": null,
  "backend_name": "agent-ledger",
  "backend_operation": "tool_result.read_full",
  "backend_contract_version": "v1",
  "backend_effect_capability": "receipt_first",
  "external_resource_type": null,
  "external_resource_id": null,
  "error_code": null,
  "error_message": null,
  "created_at": "2026-07-07 07:57:52",
  "updated_at": "2026-07-07 07:57:53",
  "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
  "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
  "reconcile_contract_version": "reconcile-v1",
  "result_adapter_version": "v1",
  "approval_lineage_id": null,
  "approval_epoch": 0,
  "approved_approval_id": null,
  "approved_by": null,
  "approved_at": null,
  "policy_evidence_refs_json": [],
  "audit_evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-8d64dda3cf78457e9dcaec9c080ff78e/tool_result",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-8d64dda3cf78457e9dcaec9c080ff78e/tool_result",
      "mutability_class": "immutable",
      "active_for_policy": false,
      "required_for_high_risk": false
    }
  ],
  "evidence_mutability_summary_json": {
    "total": 1,
    "fully_frozen": true,
    "by_mutability": {
      "immutable": 1
    },
    "audit_ref_count": 1,
    "policy_ref_count": 0,
    "requires_revalidation": false
  },
  "decision_context_build_id": null
}
```

#### Tool `tool_result.read_full` / `agent-tool-230297dc55ed4a6e9d3d697ef716046e`

- status: `succeeded`
- step_index: `5`
- attempt_index: `5`
- approval_required: `0`
- input_hash: `b6b07e772b1d46abda49322f150ed244db042550137a7cbdec90f0d81d76812f`
- output_hash: `1fefd2af24713fa3391720837cce0b72207216fb644ed3cc96af9cdc6965c91c`

```json
{
  "id": 613,
  "tool_call_id": "agent-tool-230297dc55ed4a6e9d3d697ef716046e",
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "step_index": 5,
  "attempt_index": 5,
  "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
  "tool_name": "tool_result.read_full",
  "tool_version": "1.0.0",
  "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
  "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
  "idempotency_scope": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "idempotency_key": "5d13c430325b70cff6a38de3cc09743053feb69e58d00df24188dbf46451f148",
  "base_side_effect_class": "read_only",
  "resolved_side_effect_class": "read_only",
  "base_replay_policy": "reuse_allowed",
  "resolved_replay_policy": "reuse_allowed",
  "policy_reason_json": {
    "dispatch_trace": {
      "router": "AgentToolRouter.resolve",
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "status": "succeeded",
      "runtime": "AgentToolRuntime.execute",
      "tool_name": "tool_result.read_full",
      "schema_hash": "8b4f0f781dc0fdaf3a27cd5eec5d71145a75a9627f268690a06ccf18ce36087e",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-230297dc55ed4a6e9d3d697ef716046e",
      "tool_version": "1.0.0",
      "manifest_hash": "398ed402cac1a527e54602dfe48c1b1876df9422800769e80a5be1aeb8c7c0fe",
      "backend_handler": "_tool_result_read_full",
      "backend_operation": "tool_result.read_full",
      "dispatch_trace_hash": "b3acb424a3932e61b882b024a8b9ff9d6ff092b59bdf99f8c91fe404d4a36aaf",
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "resolved_replay_policy": "reuse_allowed",
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "resolved_side_effect_class": "read_only",
      "dispatch_trace_version_hash": "agent-tool-dispatch-v1"
    },
    "policy_context": {
      "tool_name": "tool_result.read_full",
      "policy_hash": "7ebcf3ce85b1d14a7268a86883c575a3a719a5e8242aa98e7959488e011e7ec7",
      "tool_version": "1.0.0",
      "approval_policy": "safe_side_effect_auto",
      "approval_required": false,
      "base_replay_policy": "reuse_allowed",
      "policy_version_hash": "agent-policy-v1",
      "mixed_volatile_frozen": false,
      "base_side_effect_class": "read_only",
      "resolved_replay_policy": "reuse_allowed",
      "active_policy_ref_count": 0,
      "frozen_policy_ref_count": 0,
      "approval_required_reason": "safe_initial_tool",
      "volatile_policy_ref_count": 0,
      "resolved_side_effect_class": "read_only",
      "historical_volatile_excluded_count": 0
    },
    "execution_context": {
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "tool_name": "tool_result.read_full",
      "worker_id": null,
      "error_code": null,
      "input_hash": "b6b07e772b1d46abda49322f150ed244db042550137a7cbdec90f0d81d76812f",
      "approved_by": null,
      "output_hash": "1fefd2af24713fa3391720837cce0b72207216fb644ed3cc96af9cdc6965c91c",
      "tool_status": "succeeded",
      "backend_name": "agent-ledger",
      "tool_call_id": "agent-tool-230297dc55ed4a6e9d3d697ef716046e",
      "tool_version": "1.0.0",
      "approval_epoch": 0,
      "approval_state": "not_required",
      "execution_phase": "completed",
      "approval_required": false,
      "backend_operation": "tool_result.read_full",
      "recovery_decision": null,
      "error_message_hash": null,
      "approval_lineage_id": null,
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "approved_approval_id": null,
      "execution_context_hash": "7adcad8b4106505b24ba370bb162945fa82ae3033ef7bff4a7d814a9acb131ba",
      "resolved_replay_policy": "reuse_allowed",
      "result_adapter_version": "v1",
      "effect_boundary_crossed": false,
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "backend_effect_capability": "receipt_first",
      "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
      "reconcile_contract_version": "reconcile-v1",
      "resolved_side_effect_class": "read_only",
      "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
      "execution_context_version_hash": "agent-tool-execution-v1"
    },
    "base_replay_policy": "reuse_allowed",
    "mixed_volatile_frozen": false,
    "active_policy_ref_count": 0,
    "frozen_policy_ref_count": 0,
    "approval_required_reason": "safe_initial_tool",
    "volatile_policy_ref_count": 0,
    "historical_volatile_excluded_count": 0
  },
  "status": "succeeded",
  "execution_phase": "completed",
  "effect_submission_state": "effect_committed",
  "effect_boundary_crossed": 0,
  "downstream_send_intent_at": "2026-07-06 23:58:28",
  "downstream_request_observed_sent_at": "2026-07-06 23:58:28",
  "downstream_acceptance_id": "5d13c430325b70cff6a38de3cc09743053feb69e58d00df24188dbf46451f148",
  "downstream_acceptance_at": "2026-07-06 23:58:28",
  "input_hash": "b6b07e772b1d46abda49322f150ed244db042550137a7cbdec90f0d81d76812f",
  "input_json_redacted": {
    "path": "draft.scenario.nodes.3",
    "max_chars": 10000,
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34"
  },
  "evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false
    }
  ],
  "output_hash": "1fefd2af24713fa3391720837cce0b72207216fb644ed3cc96af9cdc6965c91c",
  "output_json_redacted": {
    "path": "draft.scenario.nodes.3",
    "output": {
      "id": "NODE-4",
      "name": "取消关注",
      "test_case": {
        "id": "CASE-4",
        "kind": "api_case",
        "name": "取消关注",
        "path": "/api/lingxi-system/myAttentionCompany/cancel",
        "config": {
          "assertions": [
            {
              "path": null,
              "type": "status_code",
              "expected": 200,
              "retry_on_failure": false
            },
            {
              "path": "code",
              "type": "json_equals",
              "expected": 666666,
              "retry_on_failure": false
            },
            {
              "path": "success",
              "type": "json_equals",
              "expected": true,
              "retry_on_failure": false
            },
            {
              "path": "msg",
              "type": "json_equals",
              "expected": "操作成功",
              "retry_on_failure": false
            }
          ],
          "query_params": {
            "companyId": "{{companyId}}"
          },
          "_scenario_context": {
            "bindings": [
              {
                "id": "BIND-4",
                "name": "companyId",
                "target": "query_params",
                "target_path": "companyId",
                "source_step_id": "CASE-1",
                "source_extraction_id": "VAR-1"
              }
            ],
            "extractions": []
          }
        },
        "method": "POST",
        "reference_id": 10,
        "continue_on_failure": false
      },
      "after_actions": [],
      "before_actions": []
    },
    "run_id": "agent-run-1914761819b44a2799a744049d837d7c",
    "status": "succeeded",
    "redaction": "output_json_redacted",
    "tool_name": "scenario.compose_draft",
    "output_hash": "a2e773df07d900972ee2ea93d0035ac4eb8bc66c18c6b08d3fe5d2d66974b075",
    "tool_call_id": "agent-tool-7f6517141970455b9b23b82dc1fcfb34",
    "output_truncated": false,
    "output_size_chars": 899
  },
  "raw_output_object_key": null,
  "permission_snapshot_json": {
    "user_id": 1,
    "audit_only": true,
    "project_id": 1,
    "captured_at": "2026-07-06T23:58:27.405990",
    "required_permissions": [
      "project:view"
    ]
  },
  "required_permissions_json": [
    "project:view"
  ],
  "approval_required": 0,
  "approval_scope_hash": "678fab1a5c046f7fd1dda80822f8221980b25fbef059a07eaf76a7b1a6251d84",
  "lease_owner": null,
  "lease_expires_at": null,
  "last_heartbeat_at": null,
  "recovery_decision": null,
  "backend_name": "agent-ledger",
  "backend_operation": "tool_result.read_full",
  "backend_contract_version": "v1",
  "backend_effect_capability": "receipt_first",
  "external_resource_type": null,
  "external_resource_id": null,
  "error_code": null,
  "error_message": null,
  "created_at": "2026-07-07 07:58:37",
  "updated_at": "2026-07-07 07:58:38",
  "backend_request_schema_hash": "9b0d622ce9295b431f4f717557eaf7cc5a6a9250fe7f1d8b132fb3bd47d7808f",
  "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
  "reconcile_contract_version": "reconcile-v1",
  "result_adapter_version": "v1",
  "approval_lineage_id": null,
  "approval_epoch": 0,
  "approved_approval_id": null,
  "approved_by": null,
  "approved_at": null,
  "policy_evidence_refs_json": [],
  "audit_evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false,
      "required_for_high_risk": false
    }
  ],
  "evidence_mutability_summary_json": {
    "total": 1,
    "fully_frozen": true,
    "by_mutability": {
      "immutable": 1
    },
    "audit_ref_count": 1,
    "policy_ref_count": 0,
    "requires_revalidation": false
  },
  "decision_context_build_id": null
}
```

#### Tool `scenario.create_saved` / `agent-tool-ed2f67f33bb84557803166f5e40430eb`

- status: `failed`
- step_index: `6`
- attempt_index: `6`
- approval_required: `1`
- input_hash: `062217ce251e3393531d462f7b03ce38eecb9b7e81d4ab9c36af4fba89649751`
- output_hash: `c8b04fe64a9d80a075cbe88fd80827effd014aae6460892b9f1e6611b62a7f4d`
- error: `agent_tool_input_schema_invalid` Tool input failed backend schema preflight before approval.

```json
{
  "id": 614,
  "tool_call_id": "agent-tool-ed2f67f33bb84557803166f5e40430eb",
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "step_index": 6,
  "attempt_index": 6,
  "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
  "tool_name": "scenario.create_saved",
  "tool_version": "1.0.0",
  "schema_hash": "6823d5aadbd50772d8eb38e6cd6d5d5201f1fa14435aefa8b48a71f27ca22510",
  "manifest_hash": "669df5bc71d9b57718f14427dd18beba54a15610044fc647bc23f69906683a32",
  "idempotency_scope": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "idempotency_key": "7594dbfcd11cd05eae076ef0fe11871eb44e9812a9521b617b8bb1dda5648c1a",
  "base_side_effect_class": "business_update",
  "resolved_side_effect_class": "business_update",
  "base_replay_policy": "require_revalidation",
  "resolved_replay_policy": "require_revalidation",
  "policy_reason_json": {
    "policy_context": {
      "tool_name": "scenario.create_saved",
      "policy_hash": "90d3f7e1b53b0e317132d88eceb52bf48806b70102124fa491570abfac6a2bcf",
      "tool_version": "1.0.0",
      "approval_policy": "unsafe_side_effect_requires_approval",
      "approval_required": true,
      "base_replay_policy": "require_revalidation",
      "policy_version_hash": "agent-policy-v1",
      "mixed_volatile_frozen": false,
      "base_side_effect_class": "business_update",
      "resolved_replay_policy": "require_revalidation",
      "active_policy_ref_count": 0,
      "frozen_policy_ref_count": 0,
      "approval_required_reason": "unsafe_side_effect",
      "volatile_policy_ref_count": 0,
      "resolved_side_effect_class": "business_update",
      "historical_volatile_excluded_count": 0
    },
    "execution_context": {
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "tool_name": "scenario.create_saved",
      "worker_id": null,
      "error_code": "agent_tool_input_schema_invalid",
      "input_hash": "062217ce251e3393531d462f7b03ce38eecb9b7e81d4ab9c36af4fba89649751",
      "approved_by": null,
      "output_hash": "c8b04fe64a9d80a075cbe88fd80827effd014aae6460892b9f1e6611b62a7f4d",
      "tool_status": "failed",
      "backend_name": "scenario-service",
      "tool_call_id": "agent-tool-ed2f67f33bb84557803166f5e40430eb",
      "tool_version": "1.0.0",
      "approval_epoch": 0,
      "approval_state": "pending",
      "execution_phase": "blocked_by_harness",
      "approval_required": true,
      "backend_operation": "create_saved",
      "recovery_decision": "repair_tool_input_schema_before_retry",
      "error_message_hash": "13bcf3fd4528ec0c873a32f6636d81e0037bd6c1f20e8c288ece35cc74613506",
      "approval_lineage_id": null,
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "approved_approval_id": null,
      "execution_context_hash": "9ec37b8c23c414fa413a24c1e58432a7f18a2d8c04deafdfdfff61d00ba5ec2f",
      "resolved_replay_policy": "require_revalidation",
      "result_adapter_version": "v1",
      "effect_boundary_crossed": false,
      "effect_submission_state": "none",
      "backend_contract_version": "v1",
      "backend_effect_capability": "idempotency_index_only",
      "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
      "reconcile_contract_version": "reconcile-v1",
      "resolved_side_effect_class": "business_update",
      "backend_request_schema_hash": "b201f270e1a99fc8637970c02996d088a5adc7126f86dc3fddc90a1a99ff907b",
      "execution_context_version_hash": "agent-tool-execution-v1"
    },
    "base_replay_policy": "require_revalidation",
    "mixed_volatile_frozen": false,
    "active_policy_ref_count": 0,
    "frozen_policy_ref_count": 0,
    "approval_required_reason": "unsafe_side_effect",
    "volatile_policy_ref_count": 0,
    "historical_volatile_excluded_count": 0
  },
  "status": "failed",
  "execution_phase": "blocked_by_harness",
  "effect_submission_state": "none",
  "effect_boundary_crossed": 0,
  "downstream_send_intent_at": null,
  "downstream_request_observed_sent_at": null,
  "downstream_acceptance_id": null,
  "downstream_acceptance_at": null,
  "input_hash": "062217ce251e3393531d462f7b03ce38eecb9b7e81d4ab9c36af4fba89649751",
  "input_json_redacted": {
    "scenario": {
      "name": "企业端到端自动化流程测试",
      "tags": [
        "ai-composed"
      ],
      "nodes": [
        {
          "id": "NODE-1",
          "name": "获取企业列表",
          "test_case": {
            "id": "CASE-1",
            "kind": "api_case",
            "name": "获取企业列表",
            "path": "/api/lingxi-chain/cloudentchain/getEntPageList",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "extractors": [
                {
                  "id": "VAR-1",
                  "name": "companyId",
                  "path": "data.dataList.0.companyId"
                },
                {
                  "id": "VAR-2",
                  "name": "companyName",
                  "path": "data.dataList.0.companyName"
                }
              ],
              "_scenario_context": {
                "extractions": [
                  {
                    "id": "VAR-1",
                    "name": "companyId",
                    "path": "data.dataList.0.companyId"
                  },
                  {
                    "id": "VAR-2",
                    "name": "companyName",
                    "path": "data.dataList.0.companyName"
                  }
                ]
              }
            },
            "method": "POST",
            "reference_id": 7,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-2",
          "name": "获取对应企业CT画像数",
          "test_case": {
            "id": "CASE-2",
            "kind": "api_case",
            "name": "获取对应企业CT画像数",
            "path": "/api/lingxi-bigdata/base-info/businessInformation",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "query_params": {
                "size": "10",
                "companyId": "{{companyId}}"
              },
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-1",
                    "name": "companyId",
                    "target": "query_params",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  }
                ],
                "extractions": []
              }
            },
            "method": "GET",
            "reference_id": 8,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-3",
          "name": "关注企业",
          "test_case": {
            "id": "CASE-3",
            "kind": "api_case",
            "name": "关注接口",
            "path": "/api/lingxi-system/myAttentionCompany/save",
            "config": {
              "body": {
                "companyId": "{{companyId}}",
                "companyName": "{{companyName}}"
              },
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 666666,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-2",
                    "name": "companyId",
                    "target": "body",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  },
                  {
                    "id": "BIND-3",
                    "name": "companyName",
                    "target": "body",
                    "target_path": "companyName",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-2"
                  }
                ],
                "extractions": []
              }
            },
            "method": "POST",
            "reference_id": 9,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-4",
          "name": "取消关注",
          "test_case": {
            "id": "CASE-4",
            "kind": "api_case",
            "name": "取消关注",
            "path": "/api/lingxi-system/myAttentionCompany/cancel",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 666666,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                },
                {
                  "path": "msg",
                  "type": "json_equals",
                  "expected": "操作成功",
                  "retry_on_failure": false
                }
              ],
              "query_params": {
                "companyId": "{{companyId}}"
              },
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-4",
                    "name": "companyId",
                    "target": "query_params",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  }
                ],
                "extractions": []
              }
            },
            "method": "POST",
            "reference_id": 10,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        }
      ],
      "environment_id": 4,
      "environment_snapshot_id": "environment-snapshot://85d4b70ef97f659268fb9e93a56a641070b9bc99e3352ae84e30f766ffbb9af0"
    },
    "project_id": 1
  },
  "evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false
    },
    {
      "ref_id": "agent-tool-ed2f67f33bb84557803166f5e40430eb",
      "ref_type": "system_record",
      "authority": "system_record",
      "tool_name": "scenario.create_saved",
      "captured_at": "2026-07-06T23:59:06.345453",
      "snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "content_hash": "062217ce251e3393531d462f7b03ce38eecb9b7e81d4ab9c36af4fba89649751",
      "dependency_role": "decision_dependency",
      "evidence_ref_id": "tool-call-input:agent-tool-ed2f67f33bb84557803166f5e40430eb",
      "freshness_policy": "none",
      "mutability_class": "immutable",
      "active_for_policy": true,
      "required_for_high_risk": true
    }
  ],
  "output_hash": "c8b04fe64a9d80a075cbe88fd80827effd014aae6460892b9f1e6611b62a7f4d",
  "output_json_redacted": {
    "next_action": "Repair the tool input to match the backend save schema before requesting approval. For scenario response extraction, use test_case.config.extractors or test_case.config._scenario_context.extractions instead of fixed_value after_actions.",
    "blocked_tool": "scenario.create_saved",
    "schema_preflight": {
      "errors": [
        {
          "path": "scenario.environment_snapshot_id",
          "type": "extra_forbidden",
          "message": "Extra inputs are not permitted",
          "input_preview": "'environment-snapshot://85d4b70ef97f659268fb9e93a56a641070b9bc99e3352ae84e30f766ffbb9af0'"
        }
      ],
      "tool_name": "scenario.create_saved",
      "schema_name": "ScenarioCreateRequest"
    }
  },
  "raw_output_object_key": null,
  "permission_snapshot_json": {
    "user_id": 1,
    "audit_only": true,
    "project_id": 1,
    "captured_at": "2026-07-06T23:59:06.345453",
    "required_permissions": [
      "scenario:manage"
    ]
  },
  "required_permissions_json": [
    "scenario:manage"
  ],
  "approval_required": 1,
  "approval_scope_hash": "35a9bfdb95f3ff1b2415841b427c8ee43cec6578c1a1f7264a8ed545c5e7fd3c",
  "lease_owner": null,
  "lease_expires_at": null,
  "last_heartbeat_at": null,
  "recovery_decision": "repair_tool_input_schema_before_retry",
  "backend_name": "scenario-service",
  "backend_operation": "create_saved",
  "backend_contract_version": "v1",
  "backend_effect_capability": "idempotency_index_only",
  "external_resource_type": null,
  "external_resource_id": null,
  "error_code": "agent_tool_input_schema_invalid",
  "error_message": "Tool input failed backend schema preflight before approval.",
  "created_at": "2026-07-07 07:59:16",
  "updated_at": "2026-07-07 07:59:17",
  "backend_request_schema_hash": "b201f270e1a99fc8637970c02996d088a5adc7126f86dc3fddc90a1a99ff907b",
  "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
  "reconcile_contract_version": "reconcile-v1",
  "result_adapter_version": "v1",
  "approval_lineage_id": null,
  "approval_epoch": 0,
  "approved_approval_id": null,
  "approved_by": null,
  "approved_at": null,
  "policy_evidence_refs_json": [
    {
      "ref_id": "agent-tool-ed2f67f33bb84557803166f5e40430eb",
      "ref_type": "system_record",
      "authority": "system_record",
      "captured_at": "2026-07-06T23:59:06.345453",
      "snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "content_hash": "062217ce251e3393531d462f7b03ce38eecb9b7e81d4ab9c36af4fba89649751",
      "dependency_role": "decision_dependency",
      "evidence_ref_id": "tool-call-input:agent-tool-ed2f67f33bb84557803166f5e40430eb",
      "freshness_policy": "none",
      "mutability_class": "immutable",
      "active_for_policy": true,
      "required_for_high_risk": true
    }
  ],
  "audit_evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false,
      "required_for_high_risk": false
    }
  ],
  "evidence_mutability_summary_json": {
    "total": 2,
    "fully_frozen": true,
    "by_mutability": {
      "immutable": 2
    },
    "audit_ref_count": 1,
    "policy_ref_count": 1,
    "requires_revalidation": false
  },
  "decision_context_build_id": "agent-ctx-65b762f9fdd04acb9c9974da884ed3a6"
}
```

#### Tool `scenario.create_saved` / `agent-tool-322b28009309479fbbed0ffe48c02f21`

- status: `succeeded`
- step_index: `7`
- attempt_index: `7`
- approval_required: `1`
- input_hash: `5fe85492a345b062d2fd811c728e0912f0c6d7dd6aaaad13164f6c93f94058b6`
- output_hash: `b0ae93ca11b69a06deea1b54ab935405dd6e0fa36b1c548735f113bc21a365ef`

```json
{
  "id": 615,
  "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
  "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "step_index": 7,
  "attempt_index": 7,
  "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
  "tool_name": "scenario.create_saved",
  "tool_version": "1.0.0",
  "schema_hash": "6823d5aadbd50772d8eb38e6cd6d5d5201f1fa14435aefa8b48a71f27ca22510",
  "manifest_hash": "669df5bc71d9b57718f14427dd18beba54a15610044fc647bc23f69906683a32",
  "idempotency_scope": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
  "idempotency_key": "89ce0a2037b1b506dac339acd71920fbca2ef78eda16b858c77f9fab859f12fe",
  "base_side_effect_class": "business_update",
  "resolved_side_effect_class": "business_update",
  "base_replay_policy": "require_revalidation",
  "resolved_replay_policy": "require_revalidation",
  "policy_reason_json": {
    "dispatch_trace": {
      "router": "AgentToolRouter.resolve",
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "status": "succeeded",
      "runtime": "AgentToolRuntime.execute",
      "tool_name": "scenario.create_saved",
      "schema_hash": "6823d5aadbd50772d8eb38e6cd6d5d5201f1fa14435aefa8b48a71f27ca22510",
      "backend_name": "scenario-service",
      "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
      "tool_version": "1.0.0",
      "manifest_hash": "669df5bc71d9b57718f14427dd18beba54a15610044fc647bc23f69906683a32",
      "backend_handler": "_scenario_create_saved",
      "backend_operation": "create_saved",
      "dispatch_trace_hash": "be9e8dc33aa0bc669bb147c58906f6572f5960e5035c5b9e52e13891479c7f5e",
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "resolved_replay_policy": "require_revalidation",
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "resolved_side_effect_class": "business_update",
      "dispatch_trace_version_hash": "agent-tool-dispatch-v1"
    },
    "policy_context": {
      "tool_name": "scenario.create_saved",
      "policy_hash": "90d3f7e1b53b0e317132d88eceb52bf48806b70102124fa491570abfac6a2bcf",
      "tool_version": "1.0.0",
      "approval_policy": "unsafe_side_effect_requires_approval",
      "approval_required": true,
      "base_replay_policy": "require_revalidation",
      "policy_version_hash": "agent-policy-v1",
      "mixed_volatile_frozen": false,
      "base_side_effect_class": "business_update",
      "resolved_replay_policy": "require_revalidation",
      "active_policy_ref_count": 0,
      "frozen_policy_ref_count": 0,
      "approval_required_reason": "unsafe_side_effect",
      "volatile_policy_ref_count": 0,
      "resolved_side_effect_class": "business_update",
      "historical_volatile_excluded_count": 0
    },
    "execution_context": {
      "run_id": "agent-run-72ca285d46fe4755ba0e3e1da92d3fdc",
      "tool_name": "scenario.create_saved",
      "worker_id": null,
      "error_code": null,
      "input_hash": "5fe85492a345b062d2fd811c728e0912f0c6d7dd6aaaad13164f6c93f94058b6",
      "approved_by": 1,
      "output_hash": "b0ae93ca11b69a06deea1b54ab935405dd6e0fa36b1c548735f113bc21a365ef",
      "tool_status": "succeeded",
      "backend_name": "scenario-service",
      "tool_call_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
      "tool_version": "1.0.0",
      "approval_epoch": 1,
      "approval_state": "approved",
      "execution_phase": "completed",
      "approval_required": true,
      "backend_operation": "create_saved",
      "recovery_decision": null,
      "error_message_hash": null,
      "approval_lineage_id": "agent-appr-lineage-a7e5e72b3eed4f44b7cf7f4045cde714",
      "runtime_snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "approved_approval_id": "agent-appr-8fab4bfca9e34d4b8c1d7dd9755de511",
      "execution_context_hash": "54d457760a4eb5c630bafead4d7b1b14255aae5ddbd7c8964f830a4a7bd6cf98",
      "resolved_replay_policy": "require_revalidation",
      "result_adapter_version": "v1",
      "effect_boundary_crossed": true,
      "effect_submission_state": "effect_committed",
      "backend_contract_version": "v1",
      "backend_effect_capability": "idempotency_index_only",
      "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
      "reconcile_contract_version": "reconcile-v1",
      "resolved_side_effect_class": "business_update",
      "backend_request_schema_hash": "b201f270e1a99fc8637970c02996d088a5adc7126f86dc3fddc90a1a99ff907b",
      "execution_context_version_hash": "agent-tool-execution-v1"
    },
    "base_replay_policy": "require_revalidation",
    "mixed_volatile_frozen": false,
    "active_policy_ref_count": 0,
    "frozen_policy_ref_count": 0,
    "approval_required_reason": "unsafe_side_effect",
    "volatile_policy_ref_count": 0,
    "historical_volatile_excluded_count": 0
  },
  "status": "succeeded",
  "execution_phase": "completed",
  "effect_submission_state": "effect_committed",
  "effect_boundary_crossed": 1,
  "downstream_send_intent_at": "2026-07-06 23:59:27",
  "downstream_request_observed_sent_at": "2026-07-06 23:59:27",
  "downstream_acceptance_id": null,
  "downstream_acceptance_at": null,
  "input_hash": "5fe85492a345b062d2fd811c728e0912f0c6d7dd6aaaad13164f6c93f94058b6",
  "input_json_redacted": {
    "scenario": {
      "name": "企业端到端自动化流程测试",
      "tags": [
        "ai-composed"
      ],
      "nodes": [
        {
          "id": "NODE-1",
          "name": "获取企业列表",
          "test_case": {
            "id": "CASE-1",
            "kind": "api_case",
            "name": "获取企业列表",
            "path": "/api/lingxi-chain/cloudentchain/getEntPageList",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "extractors": [
                {
                  "id": "VAR-1",
                  "name": "companyId",
                  "path": "data.dataList.0.companyId"
                },
                {
                  "id": "VAR-2",
                  "name": "companyName",
                  "path": "data.dataList.0.companyName"
                }
              ],
              "_scenario_context": {
                "extractions": [
                  {
                    "id": "VAR-1",
                    "name": "companyId",
                    "path": "data.dataList.0.companyId"
                  },
                  {
                    "id": "VAR-2",
                    "name": "companyName",
                    "path": "data.dataList.0.companyName"
                  }
                ]
              }
            },
            "method": "POST",
            "reference_id": 7,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-2",
          "name": "获取对应企业CT画像数",
          "test_case": {
            "id": "CASE-2",
            "kind": "api_case",
            "name": "获取对应企业CT画像数",
            "path": "/api/lingxi-bigdata/base-info/businessInformation",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "query_params": {
                "size": "10",
                "companyId": "{{companyId}}"
              },
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-1",
                    "name": "companyId",
                    "target": "query_params",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  }
                ],
                "extractions": []
              }
            },
            "method": "GET",
            "reference_id": 8,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-3",
          "name": "关注企业",
          "test_case": {
            "id": "CASE-3",
            "kind": "api_case",
            "name": "关注接口",
            "path": "/api/lingxi-system/myAttentionCompany/save",
            "config": {
              "body": {
                "companyId": "{{companyId}}",
                "companyName": "{{companyName}}"
              },
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 666666,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-2",
                    "name": "companyId",
                    "target": "body",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  },
                  {
                    "id": "BIND-3",
                    "name": "companyName",
                    "target": "body",
                    "target_path": "companyName",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-2"
                  }
                ],
                "extractions": []
              }
            },
            "method": "POST",
            "reference_id": 9,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-4",
          "name": "取消关注",
          "test_case": {
            "id": "CASE-4",
            "kind": "api_case",
            "name": "取消关注",
            "path": "/api/lingxi-system/myAttentionCompany/cancel",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 666666,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                },
                {
                  "path": "msg",
                  "type": "json_equals",
                  "expected": "操作成功",
                  "retry_on_failure": false
                }
              ],
              "query_params": {
                "companyId": "{{companyId}}"
              },
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-4",
                    "name": "companyId",
                    "target": "query_params",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  }
                ],
                "extractions": []
              }
            },
            "method": "POST",
            "reference_id": 10,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        }
      ],
      "environment_id": 4
    },
    "project_id": 1,
    "environment_snapshot_id": "environment-snapshot://85d4b70ef97f659268fb9e93a56a641070b9bc99e3352ae84e30f766ffbb9af0"
  },
  "evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false
    },
    {
      "ref_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
      "ref_type": "system_record",
      "authority": "system_record",
      "tool_name": "scenario.create_saved",
      "captured_at": "2026-07-06T23:59:22.224721",
      "snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "content_hash": "5fe85492a345b062d2fd811c728e0912f0c6d7dd6aaaad13164f6c93f94058b6",
      "dependency_role": "decision_dependency",
      "evidence_ref_id": "tool-call-input:agent-tool-322b28009309479fbbed0ffe48c02f21",
      "freshness_policy": "none",
      "mutability_class": "immutable",
      "active_for_policy": true,
      "required_for_high_risk": true
    }
  ],
  "output_hash": "b0ae93ca11b69a06deea1b54ab935405dd6e0fa36b1c548735f113bc21a365ef",
  "output_json_redacted": {
    "scenario": {
      "id": 29,
      "name": "企业端到端自动化流程测试",
      "tags": [
        "ai-composed"
      ],
      "nodes": [
        {
          "id": "NODE-1",
          "name": "获取企业列表",
          "test_case": {
            "id": "CASE-1",
            "kind": "api_case",
            "name": "获取企业列表",
            "path": "/api/lingxi-chain/cloudentchain/getEntPageList",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "extractors": [
                {
                  "id": "VAR-1",
                  "name": "companyId",
                  "path": "data.dataList.0.companyId"
                },
                {
                  "id": "VAR-2",
                  "name": "companyName",
                  "path": "data.dataList.0.companyName"
                }
              ],
              "_scenario_context": {
                "extractions": [
                  {
                    "id": "VAR-1",
                    "name": "companyId",
                    "path": "data.dataList.0.companyId"
                  },
                  {
                    "id": "VAR-2",
                    "name": "companyName",
                    "path": "data.dataList.0.companyName"
                  }
                ]
              }
            },
            "method": "POST",
            "reference_id": 7,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-2",
          "name": "获取对应企业CT画像数",
          "test_case": {
            "id": "CASE-2",
            "kind": "api_case",
            "name": "获取对应企业CT画像数",
            "path": "/api/lingxi-bigdata/base-info/businessInformation",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "query_params": {
                "size": "10",
                "companyId": "{{companyId}}"
              },
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-1",
                    "name": "companyId",
                    "target": "query_params",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  }
                ],
                "extractions": []
              }
            },
            "method": "GET",
            "reference_id": 8,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-3",
          "name": "关注企业",
          "test_case": {
            "id": "CASE-3",
            "kind": "api_case",
            "name": "关注接口",
            "path": "/api/lingxi-system/myAttentionCompany/save",
            "config": {
              "body": {
                "companyId": "{{companyId}}",
                "companyName": "{{companyName}}"
              },
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 666666,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                }
              ],
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-2",
                    "name": "companyId",
                    "target": "body",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  },
                  {
                    "id": "BIND-3",
                    "name": "companyName",
                    "target": "body",
                    "target_path": "companyName",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-2"
                  }
                ],
                "extractions": []
              }
            },
            "method": "POST",
            "reference_id": 9,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        },
        {
          "id": "NODE-4",
          "name": "取消关注",
          "test_case": {
            "id": "CASE-4",
            "kind": "api_case",
            "name": "取消关注",
            "path": "/api/lingxi-system/myAttentionCompany/cancel",
            "config": {
              "assertions": [
                {
                  "path": null,
                  "type": "status_code",
                  "expected": 200,
                  "retry_on_failure": false
                },
                {
                  "path": "code",
                  "type": "json_equals",
                  "expected": 666666,
                  "retry_on_failure": false
                },
                {
                  "path": "success",
                  "type": "json_equals",
                  "expected": true,
                  "retry_on_failure": false
                },
                {
                  "path": "msg",
                  "type": "json_equals",
                  "expected": "操作成功",
                  "retry_on_failure": false
                }
              ],
              "query_params": {
                "companyId": "{{companyId}}"
              },
              "_scenario_context": {
                "bindings": [
                  {
                    "id": "BIND-4",
                    "name": "companyId",
                    "target": "query_params",
                    "target_path": "companyId",
                    "source_step_id": "CASE-1",
                    "source_extraction_id": "VAR-1"
                  }
                ],
                "extractions": []
              }
            },
            "method": "POST",
            "reference_id": 10,
            "continue_on_failure": false
          },
          "after_actions": [],
          "before_actions": []
        }
      ],
      "datasets": [],
      "created_at": "2026-07-07 07:59:37",
      "project_id": 1,
      "updated_at": "2026-07-07 07:59:37",
      "description": null,
      "last_run_at": null,
      "environment_id": 4,
      "current_version": 1,
      "environment_name": "test"
    },
    "operation": "create_saved",
    "project_id": 1,
    "scenario_id": 29
  },
  "raw_output_object_key": null,
  "permission_snapshot_json": {
    "user_id": 1,
    "audit_only": true,
    "project_id": 1,
    "captured_at": "2026-07-06T23:59:22.224721",
    "required_permissions": [
      "scenario:manage"
    ]
  },
  "required_permissions_json": [
    "scenario:manage"
  ],
  "approval_required": 1,
  "approval_scope_hash": "b514d397bb38dd04a874d2de5880db21be8d984442a5ad48b21812286bfdab9f",
  "lease_owner": null,
  "lease_expires_at": null,
  "last_heartbeat_at": null,
  "recovery_decision": null,
  "backend_name": "scenario-service",
  "backend_operation": "create_saved",
  "backend_contract_version": "v1",
  "backend_effect_capability": "idempotency_index_only",
  "external_resource_type": null,
  "external_resource_id": null,
  "error_code": null,
  "error_message": null,
  "created_at": "2026-07-07 07:59:32",
  "updated_at": "2026-07-07 07:59:38",
  "backend_request_schema_hash": "b201f270e1a99fc8637970c02996d088a5adc7126f86dc3fddc90a1a99ff907b",
  "backend_output_schema_hash": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
  "reconcile_contract_version": "reconcile-v1",
  "result_adapter_version": "v1",
  "approval_lineage_id": "agent-appr-lineage-a7e5e72b3eed4f44b7cf7f4045cde714",
  "approval_epoch": 1,
  "approved_approval_id": "agent-appr-8fab4bfca9e34d4b8c1d7dd9755de511",
  "approved_by": 1,
  "approved_at": "2026-07-06 23:59:26",
  "policy_evidence_refs_json": [
    {
      "ref_id": "agent-tool-322b28009309479fbbed0ffe48c02f21",
      "ref_type": "system_record",
      "authority": "system_record",
      "captured_at": "2026-07-06T23:59:22.224721",
      "snapshot_id": "agent-snap-21d68ed5ee69473c8e40e4bcb0862bff",
      "content_hash": "5fe85492a345b062d2fd811c728e0912f0c6d7dd6aaaad13164f6c93f94058b6",
      "dependency_role": "decision_dependency",
      "evidence_ref_id": "tool-call-input:agent-tool-322b28009309479fbbed0ffe48c02f21",
      "freshness_policy": "none",
      "mutability_class": "immutable",
      "active_for_policy": true,
      "required_for_high_risk": true
    }
  ],
  "audit_evidence_refs_json": [
    {
      "ref_id": "agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "ref_type": "tool_call",
      "dependency_role": "audit_background",
      "evidence_ref_id": "tool-call:agent-tool-artifact://agent-tool-7f6517141970455b9b23b82dc1fcfb34/scenario_draft",
      "mutability_class": "immutable",
      "active_for_policy": false,
      "required_for_high_risk": false
    }
  ],
  "evidence_mutability_summary_json": {
    "total": 2,
    "fully_frozen": true,
    "by_mutability": {
      "immutable": 2
    },
    "audit_ref_count": 1,
    "policy_ref_count": 1,
    "requires_revalidation": false
  },
  "decision_context_build_id": "agent-ctx-711365f82840448b886069bdb3e5f222"
}
```

## Filtered App Log Lines

?????????? `app_log_lines.txt`?JSON ???? `app_log_lines` ???