# LLM-Driven Agent Runtime Architecture Design

## 1. Objective

Rebuild the TestAuto Agent orchestration path so the LLM is the semantic planner, while the backend remains the non-bypassable policy and execution runtime. The system must not decide business intent by adding phrases to a keyword table. It must support future Skills and Tools without adding a new hard-coded routing branch for each capability.

The first end-to-end acceptance case is a real project test scenario: the Agent must use authoritative test-case and environment facts from the selected project, construct an executable scenario with valid saved-case references and evidence-backed data dependencies, pass backend graph/reference/quality validation, and expose the result as an authoritative scenario draft. A list of endpoints or an invented sequence of synthetic nodes is not a valid scenario.

## 2. Non-negotiable constraints

- Preserve the current asynchronous Agent Run, EventStore, ToolCall, worker, Approval, resume, cancellation, and SSE architecture.
- Preserve project isolation and existing REST/SSE response shapes.
- The LLM may choose capabilities, but it cannot invent Tool or Skill names that are not present in the frozen RuntimeSnapshot.
- ToolRuntime remains authoritative for schema validation, permissions, project access, object references, approvals, idempotency, replay policy, and side-effect execution.
- Business writes and real test execution remain subject to the existing approval and preflight policies.
- No raw chain-of-thought is persisted or returned to the frontend.
- Legacy fenced `agent_tool_request` remains a compatibility parser only. It cannot activate a capability, bypass a Capability Plan, or repair a plan mismatch.
- No new phrase-specific routing fixes are permitted for this incident.

## 3. Architectural decision

Use an LLM-owned planning control plane and a backend-owned policy/execution plane.

```text
User turn + conversation artifacts + RuntimeSnapshot indexes
                         |
                         v
              LLM Planning Decision
       (goal, selected Skills, selected Tools,
        required facts, intended side effects)
                         |
                         v
             Runtime Planning Validator
      (registered names, permissions, tool classes,
       project boundary, artifact availability)
                         |
                         v
             Persisted Capability Plan
                         |
                         v
         LLM native Tool Calling loop
                         |
                         v
 ToolRuntime -> Approval/Worker -> EventStore -> LLM
```

The LLM decides semantic meaning and the next useful capability. The backend validates whether that declared plan is representable and safe, persists it, presents the selected native Tool schemas, and executes calls. The backend does not reinterpret the user's business goal through a second keyword-based ontology.

## 4. Unified planning decision

### 4.1 Replace split intent and Skill authority

The current flow can persist an `IntentDecision(target_domain=visual_flow)` while separately selecting `scenario-composition`. That split authority is removed.

Introduce one structured `AgentPlanningDecision` produced by the LLM:

```json
{
  "goal": "construct an executable scenario from the project's saved cases",
  "action": "create_draft",
  "target_domain": "scenario",
  "source_domains": ["test_case", "environment"],
  "selected_skills": ["scenario-composition"],
  "selected_tools": [
    "project.read_context",
    "testcase.query_project_cases",
    "scenario.compose_draft"
  ],
  "required_facts": [
    "project_environment_snapshot",
    "test_case_query_snapshot"
  ],
  "requested_effect_scope": "draft",
  "confidence": 0.92,
  "reason_summary": "The user asked to build a test process from the cases analyzed in this conversation."
}
```

`reason_summary` is a short decision explanation, not model chain-of-thought.

The planning request receives:

- Current user intent and bounded conversation history.
- SOURCE artifact handles and available follow-up actions.
- The complete Skill index with name, description, owns, consumes, produces, and declared Tool names.
- The complete Tool index with name, summary, side-effect class, replay policy, required permissions, and schema hash, but not backend handlers or secrets.
- The current project identifier and user permission summary.

The planning request uses a dedicated profile:

- `thinking=disabled` for bounded structured output.
- `temperature=0`.
- A JSON response schema.
- Enough output budget for the complete decision.
- Validation of non-empty content and `finish_reason=stop`.
- One bounded repair attempt using the validation error and the same indexes.

If both attempts fail, the run terminates as `agent_planning_failed`. It does not fall back to keyword-derived action/domain semantics.

### 4.2 Role of Skill retrieval

Deterministic Skill ranking may remain as retrieval assistance, but not as an authority. It may order or highlight likely Skills in the index. The LLM can select any registered Skill whose declared capability is relevant.

The backend validates:

- Every selected Skill exists in the frozen Skill registry.
- Every selected Tool exists in the RuntimeSnapshot.
- Selected Tools are declared by at least one selected Skill, are core context Tools, or were requested through the runtime capability-extension protocol.
- The declared source and target domains are compatible with Skill `owns/consumes/produces` metadata.

An invalid decision is repaired by the planning model, not silently rewritten by a keyword parser.

## 5. Capability Plan semantics

The Capability Plan becomes an auditable record of the LLM's validated plan. It no longer acts as a deterministic pre-router that decides the meaning of the user request before the LLM sees the available system.

Effect scopes are explicit and ordered:

```text
observe  -> read project facts
derive   -> deterministic validation or analysis
draft    -> create an in-memory/ledger artifact without business persistence
execute  -> create execution records and call test targets
persist  -> create/update/delete/transition business data
```

Tool side-effect classes map to these scopes:

- `read_only -> observe`
- `deterministic_compute -> derive`
- `draft_only -> draft`
- `execution_record -> execute`
- `business_update -> persist`

The planner may select Tools at any scope, but Runtime policy remains authoritative:

- `observe`, `derive`, and `draft` may execute immediately when normal project permissions pass.
- `execute` must pass execution permission, object/environment preflight, idempotency, and the existing execution policy.
- `persist` must pass schema/object preflight and human approval before the business handler runs.

This removes the overloaded `write_authorized` boolean. A classification failure can no longer remove safe draft generation while leaving the model unable to complete the user's task.

## 6. Dynamic capability extension

Every planning/model turn always has an internal native Tool named `runtime.request_capability`. It is a Runtime control Tool, not a business Tool and not part of the public ToolRegistry.

Input:

```json
{
  "tool_names": ["scenario.compose_draft"],
  "reason": "The authoritative case snapshot is now available and the next step is scenario composition."
}
```

Runtime processing:

1. Confirm every requested name exists in the frozen RuntimeSnapshot.
2. Confirm it is declared by a selected or newly selected registered Skill.
3. Confirm the request does not exceed the user's permissions or bypass required approval/preflight.
4. Persist a new Capability Plan revision.
5. Return the new plan id, activated Tool names, rejected Tool names, and structured rejection reasons.
6. On the next LLM turn, expose full native schemas for the activated Tools.

This protocol replaces natural-language capability-denial guessing and plan expansion based on parsing an assistant sentence.

## 7. Capability denial and plan mismatch handling

The current denial guard compares assistant text against globally registered Tools, attempts an expansion, swallows an expansion error, and may then invite an illegal Tool request. That behavior is removed.

New rules:

- A Tool is "available now" only if it is in the active Capability Plan.
- A globally registered but inactive Tool is "requestable", not "available".
- The model requests it with `runtime.request_capability`.
- Capability activation succeeds transactionally or returns a structured Tool result. The model is never told a plan was rebuilt unless a new active revision was committed.
- A direct call to an inactive business Tool returns `agent_capability_not_active` to the model loop. It does not fail the run as `agent_conversation_unhandled_error`.
- `CapabilityPlanToolNotAllowed`, `CapabilityPlanNotActive`, and invalid activation requests have explicit error events and Runbook diagnostics.
- Fenced JSON cannot be used as an alternate activation path.

The existing assistant-text denial detector may remain temporarily as observability only. It may emit a diagnostic event but must not choose a Tool or trigger model repair.

## 8. Real scenario construction

### 8.1 Authoritative inputs

`scenario.compose_draft` must consume authoritative ledger sources rather than reconstructing a scenario from a truncated assistant-visible preview.

Required sources:

- A current `project.read_context` environment snapshot.
- A current `testcase.query_project_cases` SOURCE artifact.
- The full redacted ToolResult resolved server-side by artifact id and output hash.

The Agent-facing compose input adds a source handle:

```json
{
  "project_id": 1,
  "environment_reference": "object-ref://environment/.../4",
  "case_source": {
    "artifact_id": "agent-tool-artifact://.../test_case_query_snapshot",
    "output_hash": "..."
  },
  "requirement": "Construct an executable end-to-end enterprise information test scenario."
}
```

The backend resolves the complete candidate set from the ToolCall ledger. The model does not need to copy 15 large case definitions through a prompt or infer cases missing from a truncated preview.

### 8.2 Scenario node contract

Every generated primary node must reference a real saved TestAuto case:

- HTTP nodes use a valid project-owned `reference_id` or authoritative `object_ref`.
- WebSocket nodes use the matching real saved-case reference type.
- `method` and `path` must match the referenced case unless an explicit scenario override is supported and validated.
- `environment_id` must resolve from the project environment snapshot.
- Assertions originate from the referenced saved case or an explicitly validated scenario override.

Dependencies must be evidence-backed:

- An extractor path must be supported by a saved extractor, response sample, schema, or explicit user-provided contract.
- Every `{{variable}}` used by a downstream request must have exactly one valid upstream source.
- Every binding must name an existing source node/extraction and a real target request location.
- The graph must reject missing sources, cycles, type-incompatible targets, and unresolved templates.
- The generator must not invent a dependency merely to make the scenario look complex.

Independent cases may remain independent when no real data dependency exists. "Real" means executable and evidence-backed, not artificially connected.

### 8.3 Quality gates

Before a draft is returned as AUTHORITATIVE, the backend runs:

1. Project and environment reference validation.
2. Saved-case membership validation.
3. Scenario graph validation.
4. Extractor/binding/template resolution validation.
5. Node request compatibility validation.
6. Assertion and failure-policy validation.
7. Orchestration quality evaluation.

The output contains `scenario_validation` with:

```text
valid
referenced_case_count
unresolved_reference_count
dependency_edge_count
resolved_template_count
unresolved_template_count
extractor_count
binding_count
graph_errors
quality_issues
evidence_sources
```

Only `valid=true` drafts become SOURCE/AUTHORITATIVE `scenario_draft` artifacts. Invalid drafts remain diagnostic draft outputs and automatically return to the LLM for repair within the existing loop budget.

### 8.4 Execution and persistence

Draft generation does not save or execute the scenario.

- Saving uses `scenario.create_saved` or `scenario.update_saved`, existing approval, and save-time quality preflight.
- Real execution uses the saved scenario and `scenario.execute_dry_run`, existing execution permission, object/environment freshness checks, and asynchronous execution records.
- Live execution against an external environment is an explicit acceptance step because real POST requests may have business side effects.

## 9. Context and multi-turn behavior

Conversation context exposes SOURCE artifacts as typed handles. The LLM decides whether a new turn refers to an earlier test-case snapshot, scenario draft, saved scenario, failed run, report, or defect.

The backend does not convert deictic phrases into a hard-coded domain. It provides:

- Artifact type and trust.
- Producing Tool and run.
- Available follow-up actions.
- Object references and hashes.
- Recency and project scope.

The LLM planning decision selects the relevant handles. Runtime validates the selected handles belong to the same user/project/conversation and remain fresh enough for the requested action.

## 10. Error model and observability

Add explicit events and errors:

- `planner.llm_decision_started/completed/invalid/retrying/failed`
- `planner.capability_activation_requested/accepted/rejected`
- `planner.capability_plan_revised`
- `scenario.draft_validation_completed/failed`
- `agent_planning_failed`
- `agent_capability_not_active`
- `agent_capability_activation_rejected`
- `agent_scenario_draft_invalid`

Provider content, raw prompts, secrets, and chain-of-thought remain excluded. Events include plan ids, hashes, selected names, bounded summaries, validation codes, and model-call trace ids.

## 11. Compatibility and migration

- Reuse `ai_agent_capability_plans`; the current JSON columns can hold the new decision and selected indexes.
- Keep `AgentRun.active_capability_plan_id` and `AgentToolCall.capability_plan_id` semantics.
- Keep existing API response fields. New events and validation envelopes are additive.
- Preserve existing business Tool names and handlers.
- Preserve legacy fenced parsing for old model/provider compatibility, but subject it to the same active-plan membership check.
- Keep deterministic intent parsing only for offline diagnostics/evaluation during migration. It must not authorize, deny, select, or activate production capabilities.

No database migration is expected unless implementation proves an existing JSON field cannot represent the new planning decision.

## 12. Verification strategy

### 12.1 Unit and contract tests

- Structured planning disables thinking and rejects empty/length-truncated responses.
- The planner selects registered Skills/Tools from registry indexes without phrase-specific production routing.
- Adding a synthetic registered Skill/Tool in a test makes it selectable without adding backend conditionals.
- Runtime rejects invented Skill/Tool names.
- `draft_only` maps to draft scope and is not treated as persistence.
- Capability activation creates a new plan revision only after validation succeeds.
- Failed activation does not call the business Tool and does not claim the plan was rebuilt.
- Plan membership errors return structured model-observable failures, not unhandled run failures.

### 12.2 Multi-turn Agent tests

- Analyze cases, then request a scenario in the same conversation.
- The new turn selects the test-case SOURCE artifact and scenario Skill through the LLM planner.
- The Tool sequence obtains environment/case facts as needed, then calls `scenario.compose_draft`.
- No duplicate scenario-list query is used as a substitute for case evidence.
- A future unrelated Skill can be selected in a later turn without being locked to the previous Skill.

### 12.3 Real scenario acceptance

Using project 1 and its real configured environment:

- Query the actual saved test cases.
- Generate a scenario draft through the real AI Skill provider.
- Verify every node reference against the database.
- Verify the environment reference.
- Verify all extractors, bindings, and templates.
- Verify the graph and orchestration quality envelope.
- Verify the draft is AUTHORITATIVE and contains no invented case ids or endpoints.
- Save/execute only when separately authorized; otherwise stop after executable static validation.

### 12.4 Regression gates

- Focused planning/capability/scenario tests.
- Full Agent Runtime suite.
- Full repository unittest discovery.
- Compileall and diff checks.
- Alembic single-head/current verification.
- Controlled backend restart.
- A real HTTP AgentRun reproducing the original multi-turn conversation.

## 13. Completion criteria

The architecture change is complete only when all of the following are proven:

1. Production business routing no longer depends on deterministic action/domain keyword fallback.
2. One validated LLM planning decision owns selected Skills, Tools, facts, and requested effect scope.
3. Runtime capability activation is explicit, transactional, plan-revisioned, and model-observable.
4. A plan mismatch cannot be converted into an illegal fenced Tool request or unhandled run failure.
5. Multi-turn requests can change Skills without stale Skill lock-in.
6. The real project scenario acceptance produces an executable, reference-valid, evidence-backed scenario draft rather than a simple endpoint sequence.
7. Existing project isolation, permissions, approvals, asynchronous execution, EventStore, SSE, and business API contracts remain intact.
8. Focused and full regressions pass, and the running backend completes the real verification AgentRun.
