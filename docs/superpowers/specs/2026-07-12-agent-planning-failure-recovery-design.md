# Agent Planning Failure Recovery Design

## Context

The multi-turn conversation `agent-conv-local-0c481e39-5638-4888-bd0e-f7bddd5eacfe` completed test-case analysis, scenario composition, and scenario persistence, then failed before any ToolCall while handling “inspect failed cases and create corresponding defects.” The failing run `agent-run-fdf826694d274e00ab915956913f928c` selected the registered `defect.create_saved` Tool, but the model emitted `requested_effect_scope=execute` and then `draft`. Because the Tool is `business_update`, the backend requires `persist`; both decisions were rejected and the bounded planning repair terminated the run.

The next run asked why the previous Agent run failed. Conversation history included only `completed` runs, so the failed run and its `agent_planning_failed` terminal state were absent. The model then diagnosed unrelated business execution records instead of the Agent runtime failure.

## Goals

1. A valid selected Tool must not make planning fail merely because the model repeats the ToolRegistry effect scope incorrectly.
2. Backend effect, permission, and approval policies remain authoritative; no persistent Tool executes without its existing permission checks and human approval.
3. A follow-up turn can see the latest failed Agent run as bounded structured state without injecting raw traces, prompts, model responses, or secrets into planning context.
4. The Agent can read a project-scoped runtime summary for a prior Agent run through a registered read-only Tool.
5. A test-case query artifact exposes authoritative failed-case summaries and advertises defect creation as a supported follow-up, while defect creation still requires execution evidence and approval.
6. The complete workflow is verified: analyze cases, locate failure evidence, plan defect creation, reach approval, and stop without an unapproved write.

## Non-goals

- Do not add keyword-specific routing for “缺陷”, individual Tool names, or the observed prompt text.
- Do not weaken unknown Tool, Skill, artifact, permission, project-isolation, input-schema, or approval validation.
- Do not make failed runs part of ordinary assistant prose history as if they had produced a successful assistant reply.
- Do not automatically approve or persist defects during acceptance testing.
- Do not add a database migration; all changes use existing AgentRun, AgentEvent, AgentToolCall, RuntimeSnapshot, and artifact structures.

## Considered Approaches

### A. Prompt-only correction

Add the `business_update -> persist` mapping to the planner prompt and make repair wording more explicit.

This is low cost but still asks the model to duplicate deterministic ToolRegistry data. A future model or Tool class can repeat the mismatch and exhaust the bounded repair again. This approach is rejected as the primary fix, though the prompt will still document the protocol for better model output.

### B. Backend-derived effective scope with structured audit (selected)

Keep the model field for wire compatibility and intent audit, derive every selected Tool’s required scope from its frozen ToolSpec, and canonicalize the effective plan scope to the maximum of the model value and the required Tool scope. Persist both the model value and backend-derived value in the planning decision view. Persistent Tools remain guarded by permissions and human approval.

This removes a redundant failure mode without permitting silent writes. If a model unexpectedly selects a persistent Tool, the result is an approval request visible to the user, not automatic execution.

### C. Independent policy-model authorization

Use a second model call to classify the maximum user-authorized effect scope independently of Tool selection.

This gives stronger semantic separation but adds latency, cost, another failure surface, and still requires deterministic Tool policy and approval. It is deferred until there is evidence that approval plus deterministic Tool policies are insufficient.

## Architecture

### 1. Effective effect scope is backend-canonical

`AgentPlanningDecision.requested_effect_scope` remains accepted for compatibility. Validation calculates:

```text
required_effect_scope = max(scope_for(tool.side_effect_class) for selected tools)
effective_effect_scope = max(model_requested_effect_scope, required_effect_scope)
```

The validated decision exposes:

- `requested_effect_scope`: the backend-canonical effective value used by Capability Plan consumers;
- `model_requested_effect_scope`: the original model value;
- `required_effect_scope`: the minimum derived from selected frozen ToolSpecs;
- `effect_scope_normalized`: whether the backend raised the value.

The planner no longer raises `planner_effect_scope_exceeded` for a registered selected Tool. It still fails for unknown side-effect classes, unavailable references, undeclared Tools, missing permissions, invalid artifacts, incompatible Skill domains, and low confidence.

The compact Tool index includes `required_effect_scope` so the model can usually emit the canonical value on its first attempt. The system prompt documents the side-effect mapping. Normalization is recorded in `planner.llm_decision_completed`; no extra mutable state is required.

### 2. Conversation prose history and terminal run state are separate

Completed runs remain the only source for alternating user/assistant history messages. A second query loads recent terminal run states for the same project and conversation, including `completed`, `failed`, `cancelled`, `migration_blocked`, and `needs_human`.

`conversation_working_context_v2` adds `recent_run_states` entries with only:

- `run_id`, `status`, and bounded `user_intent`;
- `error_code` and a redacted, bounded `error_message` when present;
- `last_event_sequence`, `current_iteration`, `current_step_index`, and `completed_at`.

The planner-safe context admits `recent_run_states` but not assistant prose, raw events, prompts, or Tool outputs. This lets a deictic follow-up such as “why did the previous run fail?” target the Agent runtime rather than unrelated business execution.

### 3. Project-scoped Agent runtime summary Tool

Add a read-only Tool:

```text
agent.run.read_summary
```

Input:

```json
{
  "project_id": 1,
  "run_id": "agent-run-..."
}
```

The backend requires project access and verifies that the run belongs to `project_id`. Output contains:

- run identity, intent, status, error code/message, timing, and iteration state;
- bounded diagnostic events for planner, Tool, approval, and terminal lifecycle events;
- ToolCall summaries containing Tool name, status, side-effect class, approval state, and bounded error metadata;
- no raw model messages, prompt objects, request/response payloads, secrets, or full Tool output.

`agent-runtime-operations` declares the Tool. The Tool uses `read_only`, `replay_safe`, and `project:view`, so it never requires approval.

### 4. Failed-case artifact contract

`test_case_query_snapshot` artifact summaries add authoritative, bounded fields:

- `case_status_summary`;
- `failed_case_count`;
- `failed_cases[]` containing case id, name, type, object reference, environment id, status, and attention reason;
- `failure_detail_available=false` when the query only proves failure status and not the cause.

The artifact advertises `create_defect` as an available follow-up action. The summary must not invent a failure cause. `defect-triage` continues to require `execution.query_records`, `execution.read_detail`, or `report.read_summary` before persistent defect creation.

### 5. Workflow behavior

For the target flow, planning can select `defect-triage`, the failed-case artifact, evidence-read Tools, and `defect.create_saved`. The canonical scope becomes `persist`. The model gathers execution evidence before preparing each defect. Every `defect.create_saved` ToolCall enters the existing approval flow and cannot execute before approval.

If evidence is insufficient, the Agent reports the missing execution detail instead of fabricating a defect cause. Negative tests, environment failures, authentication failures, assertion configuration errors, and confirmed product defects remain distinct classifications.

## Compatibility and Security

- Existing planner JSON remains valid because `requested_effect_scope` is retained.
- New planning fields and Tool output fields are additive.
- Existing Capability Plan persistence continues to store the effective `requested_effect_scope`.
- RuntimeSnapshot remains the authority for Tool effect classes; live registry drift cannot change an in-flight run.
- Project access is checked before runtime summaries are returned.
- Stored errors and events pass through existing sensitive-data masking and bounded-preview rules.
- Persistent Tools retain permission checks, approval lineage, immutable input hashes, and effect-boundary safeguards.

## Implementation Boundaries

Expected production changes:

- `app/services/agent_planning_service.py`
- `app/services/agent_capability_resolver.py`
- `app/services/agent_runtime_service.py`
- `app/services/agent_tool_service.py`
- `app/services/agent_platform_tool_service.py`
- `app/agent_skills/agent-runtime-operations/SKILL.md`
- `app/agent_skills/defect-triage/SKILL.md`

Expected tests:

- `tests/test_agent_planning_service.py`
- `tests/test_agent_capability_plan.py`
- `tests/test_agent_runtime.py`
- `tests/test_agent_platform_tools.py`

Expected documentation sync:

- `docs/api_agent_frontend_contract.md`
- `docs/technical_architecture.md`
- `docs/development_technical_notes.md`

## Verification

1. A unit test proves `defect.create_saved + execute` normalizes to effective `persist` instead of raising.
2. A unit test proves unknown side-effect classes and missing permissions still fail closed.
3. A runtime test proves a failed prior run appears in planner-safe `recent_run_states` while completed assistant history remains unchanged.
4. A platform Tool test proves `agent.run.read_summary` enforces project isolation and returns bounded diagnostic facts.
5. An artifact test proves all four failed cases from an authoritative snapshot remain visible even when detailed rows are projected or truncated.
6. A multi-turn runtime test proves the failed-case-to-defect path reaches `pending` approval without `agent_planning_failed` and without creating a defect before approval.
7. Focused Agent tests, the full unittest suite, `compileall`, `alembic heads/current`, and `git diff --check` pass.
8. A real DeepSeek-backed HTTP conversation repeats the target intent, reaches a Tool/approval state, and the approval is rejected during acceptance so no defect is persisted.

## Success Criteria

- The observed effect-scope mismatch cannot terminate planning for a registered Tool.
- The latest failed Agent run is visible to the next-turn planner as structured state.
- The Agent can diagnose the prior run through a real read-only Tool instead of querying unrelated business executions.
- Failed-case artifacts preserve the authoritative failed count and explicit case references.
- Defect persistence remains permission- and approval-gated.
- No keyword-specific production routing is introduced.
