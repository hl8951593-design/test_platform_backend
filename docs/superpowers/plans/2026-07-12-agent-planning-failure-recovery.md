# Agent Planning Failure Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent registered Tool selections from failing because the model repeats the wrong effect scope, preserve failed Agent runs as structured multi-turn state, and let the Agent diagnose prior runtime failures before creating evidence-backed defects through approval.

**Architecture:** ToolRegistry remains authoritative for required effects; planning canonicalizes the effective scope and audits the model value. Conversation prose history remains completed-only while a separate bounded terminal-run state enters planner context. A new project-scoped read-only Tool exposes safe Agent run diagnostics, and failed-case artifacts carry explicit failure references plus a defect follow-up action.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, unittest, existing Agent Runtime/ToolRegistry/SkillRegistry infrastructure.

## Global Constraints

- Preserve the existing asynchronous worker, SSE, ToolRuntime, approval lineage, permission, and effect-boundary architecture.
- Do not add keyword-specific routing for defect creation or the observed Chinese prompts.
- RuntimeSnapshot Tool and Skill metadata remain authoritative for every in-flight run.
- Persistent Tools never execute without existing project permission checks and human approval.
- Do not expose raw prompts, model messages, Tool payloads, secrets, or unbounded error text in runtime diagnostics.
- Preserve unrelated system-test-case changes in the working tree and stage Agent files explicitly.
- No database migration is permitted for this repair.

---

### Task 1: Canonicalize Effective Effect Scope

**Files:**
- Modify: `tests/test_agent_planning_service.py`
- Modify: `tests/test_agent_capability_plan.py`
- Modify: `app/services/agent_planning_service.py`
- Modify: `app/services/agent_capability_resolver.py`

**Interfaces:**
- Consumes: frozen Tool entries containing `side_effect_class` and `required_permissions`.
- Produces: `ValidatedAgentPlanningDecision.model_requested_effect_scope`, `required_effect_scope`, `requested_effect_scope` as the effective value, and `effect_scope_normalized`.

- [ ] **Step 1: Add the planning regression tests**

```python
def test_business_update_scope_is_normalized_to_persist(self):
    decision = AgentPlanningDecision(
        goal="create a defect from failed evidence",
        action="create",
        target_domain="defect",
        source_domains=["test_case", "execution"],
        selected_skills=["defect-triage"],
        selected_tools=["execution.read_detail", "defect.create_saved"],
        selected_artifact_ids=[],
        required_facts=["failure cause"],
        requested_effect_scope="execute",
        confidence=0.95,
        reason_summary="inspect evidence and create a persisted defect",
    )
    validated = self.service._validate(
        decision,
        skill_index=self.skill_index,
        tool_index=self.tool_index,
        artifact_index=[],
        permissions=["test:execute", "defect:create"],
    )
    self.assertEqual(validated.model_requested_effect_scope, "execute")
    self.assertEqual(validated.required_effect_scope, "persist")
    self.assertEqual(validated.requested_effect_scope, "persist")
    self.assertTrue(validated.effect_scope_normalized)
```

Add a second test asserting an unknown `side_effect_class` still raises `planner_tool_effect_unknown`, and retain the existing missing-permission failure assertion.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_planning_service tests.test_agent_capability_plan -v
```

Expected: the new normalization assertions fail because validation currently raises `planner_effect_scope_exceeded` and the audit fields do not exist.

- [ ] **Step 3: Implement backend-canonical scope derivation**

In `agent_planning_service.py`, add:

```python
def required_effect_scope_for_tools(tool_scopes: dict[str, str]) -> str:
    return max(tool_scopes.values(), key=EFFECT_SCOPE_ORDER.__getitem__, default="observe")
```

Extend the validated dataclass:

```python
model_requested_effect_scope: str
required_effect_scope: str
effect_scope_normalized: bool
```

Replace `planner_effect_scope_exceeded` with canonicalization:

```python
required_scope = required_effect_scope_for_tools(tool_scopes)
model_scope = decision.requested_effect_scope
effective_scope = max((model_scope, required_scope), key=EFFECT_SCOPE_ORDER.__getitem__)
```

Return the effective value in `requested_effect_scope` and include all audit fields in `model_view()`. Add `required_effect_scope` to `_compact_tool()` and derive it when building the RuntimeSnapshot Tool index. Update the planner prompt with the exact side-effect mapping while keeping normalization authoritative.

Ensure `AgentCapabilityResolver.resolve_planning_decision()` accepts the canonical effective value and continues rejecting unavailable Tools and unknown side-effect classes.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all planning and Capability Plan tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- app/services/agent_planning_service.py app/services/agent_capability_resolver.py tests/test_agent_planning_service.py tests/test_agent_capability_plan.py
git commit -m "fix: canonicalize agent tool effect scope"
```

---

### Task 2: Preserve Failed Runs as Structured Conversation State

**Files:**
- Modify: `tests/test_agent_runtime.py`
- Modify: `app/services/agent_runtime_service.py`
- Modify: `app/services/agent_planning_service.py`

**Interfaces:**
- Consumes: recent same-project, same-conversation `AgentRun` rows.
- Produces: `conversation_working_context_v2.recent_run_states` and planner-safe structured run states.

- [ ] **Step 1: Add failed-history regression tests**

Add tests that create a completed run, a failed run with `agent_planning_failed`, and a current follow-up run. Assert:

```python
self.assertEqual(
    working_context["recent_run_states"][-1]["status"],
    "failed",
)
self.assertEqual(
    working_context["recent_run_states"][-1]["error_code"],
    "agent_planning_failed",
)
self.assertNotIn("raw_prompt", json.dumps(working_context))
self.assertNotIn("model_response", json.dumps(working_context))
```

Add a planner request test asserting `_safe_conversation_context()` retains `recent_run_states` but strips `recent_turns[].assistant_message`.

- [ ] **Step 2: Run the runtime/planner tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_runtime tests.test_agent_planning_service -v
```

Expected: failed runs are absent because the current query filters `status == completed`, and the planner-safe context drops run states.

- [ ] **Step 3: Split assistant history from terminal run state**

In `AgentConversationRunner`, query completed runs for `_conversation_history_messages()` and recent terminal runs for `_conversation_working_context()`. Define terminal context statuses from existing `RUN_TERMINAL_STATUSES` and exclude only active `queued/running/paused` rows.

Add a bounded helper:

```python
def _run_state_for_working_context(run: AgentRun) -> dict[str, Any]:
    payload = {
        "run_id": run.run_id,
        "status": run.status,
        "user_intent": _truncate_history_text(run.intent, AGENT_HISTORY_CONTEXT_RECENT_USER_CHARS),
        "last_event_sequence": run.last_event_sequence,
        "current_iteration": run.current_iteration,
        "current_step_index": run.current_step_index,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }
    if run.error_code:
        payload["error_code"] = run.error_code
    if run.error_message:
        payload["error_message"] = _bounded_masked_error(run.error_message)
    return {key: value for key, value in payload.items() if value is not None}
```

Set `schema_version=conversation_working_context_v2`, add `recent_run_states`, and allow only that field plus existing artifact action/handle fields in planner-safe context.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: failed state is visible, assistant history remains completed-only, and sensitive/raw fields stay absent.

- [ ] **Step 5: Commit Task 2**

```powershell
git add -- app/services/agent_runtime_service.py app/services/agent_planning_service.py tests/test_agent_runtime.py tests/test_agent_planning_service.py
git commit -m "fix: carry failed agent runs across turns"
```

---

### Task 3: Add Project-scoped Agent Run Summary Tool

**Files:**
- Modify: `tests/test_agent_platform_tools.py`
- Modify: `tests/test_agent_runtime.py`
- Modify: `app/services/agent_tool_service.py`
- Modify: `app/services/agent_platform_tool_service.py`
- Modify: `app/agent_skills/agent-runtime-operations/SKILL.md`

**Interfaces:**
- Consumes: `{project_id: int, run_id: str}`.
- Produces: a bounded run summary with diagnostic events and ToolCall summaries.

- [ ] **Step 1: Add ToolRegistry and backend regression tests**

Assert the ToolSpec:

```python
spec = ToolRegistry().get("agent.run.read_summary")
self.assertEqual(spec.side_effect_class, "read_only")
self.assertEqual(spec.required_permissions, (ProjectPermission.VIEW_PROJECT.value,))
self.assertEqual(spec.backend_handler, "_agent_run_read_summary")
```

Create a failed AgentRun with planner events and a failed ToolCall, then call the backend and assert:

```python
self.assertEqual(result["run"]["status"], "failed")
self.assertEqual(result["run"]["error_code"], "agent_planning_failed")
self.assertIn("planner.llm_decision_failed", [item["event_type"] for item in result["diagnostic_events"]])
self.assertNotIn("input_json_redacted", json.dumps(result))
self.assertNotIn("output_json_redacted", json.dumps(result))
```

Add a cross-project test expecting HTTP 404 without revealing whether the run exists.

- [ ] **Step 2: Run platform Tool tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_platform_tools tests.test_agent_runtime -v
```

Expected: ToolRegistry lookup returns `None` and the backend handler is missing.

- [ ] **Step 3: Implement the read-only Tool**

Add an input schema with required `project_id` and `run_id`. Register:

```python
"agent.run.read_summary": platform_tool_spec(
    name="agent.run.read_summary",
    summary="Read a bounded project-scoped Agent run diagnostic summary.",
    side_effect_class="read_only",
    required_permissions=(ProjectPermission.VIEW_PROJECT.value,),
    schema_key="agent_run_read_summary_input",
    backend_name="agent-runtime-service",
    backend_operation="read_summary",
    backend_handler="_agent_run_read_summary",
)
```

Implement `_agent_run_read_summary()` with project access validation, exact project/run matching, diagnostic event allowlisting, bounded masked errors, and compact ToolCall summaries. Add `agent.run.read_summary` to `agent-runtime-operations` frontmatter and workflow guidance.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: registry, isolation, bounded output, and Skill contract tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add -- app/services/agent_tool_service.py app/services/agent_platform_tool_service.py app/agent_skills/agent-runtime-operations/SKILL.md tests/test_agent_platform_tools.py tests/test_agent_runtime.py
git commit -m "feat: expose bounded agent run diagnostics"
```

---

### Task 4: Make Failed-case Artifacts Defect-ready

**Files:**
- Modify: `tests/test_agent_runtime.py`
- Modify: `app/services/agent_runtime_service.py`
- Modify: `app/agent_skills/defect-triage/SKILL.md`

**Interfaces:**
- Consumes: `testcase.query_project_cases` output containing `case_status_summary` and `case_attention_rows`.
- Produces: bounded `failed_cases`, `failed_case_count`, `failure_detail_available`, and `create_defect` follow-up action.

- [ ] **Step 1: Add artifact contract regression test**

Build a query output containing 15 cases and four attention rows. Assert:

```python
manifest = _tool_artifact_manifest(call, source_run=run)
self.assertIn("create_defect", manifest["available_followup_actions"])
self.assertEqual(manifest["artifact_summary"]["failed_case_count"], 4)
self.assertEqual(
    [item["id"] for item in manifest["artifact_summary"]["failed_cases"]],
    [8, 10, 12, 53],
)
self.assertFalse(manifest["artifact_summary"]["failure_detail_available"])
```

- [ ] **Step 2: Run runtime tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_runtime -v
```

Expected: the artifact currently exposes counts only and lacks `create_defect`.

- [ ] **Step 3: Implement bounded failure summaries**

Copy only safe fields from `case_attention_rows`: `id`, `name`, `case_type`, `object_ref`, `environment_id`, `last_execution_status`, and `attention_reason`. Sort by numeric id, cap to the existing case projection limit, set `failed_case_count` from the authoritative status summary, and set `failure_detail_available=False` unless execution evidence is present.

Add `create_defect` to follow-up actions. Update `defect-triage` to require execution detail for failure causes and to distinguish negative-test expectations, environment/auth failures, assertion configuration, and confirmed product defects.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: failed count and ids remain authoritative even when normal detail rows are truncated.

- [ ] **Step 5: Commit Task 4**

```powershell
git add -- app/services/agent_runtime_service.py app/agent_skills/defect-triage/SKILL.md tests/test_agent_runtime.py
git commit -m "fix: preserve failed cases for defect triage"
```

---

### Task 5: Verify the Full Planning-to-Approval Flow

**Files:**
- Modify: `tests/test_agent_runtime.py`
- Modify: `tests/test_agent_planning_service.py`

**Interfaces:**
- Consumes: normalized planning decisions, failed-run state, Agent diagnostics Tool, and failed-case artifacts.
- Produces: regression evidence that defect creation reaches approval without executing an unapproved write.

- [ ] **Step 1: Add an integration-style runtime test**

Use a fake AI transport that first returns a planning decision selecting `defect-triage`, evidence reads, and `defect.create_saved` with `requested_effect_scope=execute`, then emits an evidence read ToolCall and a defect create ToolCall. Assert:

```python
self.assertNotEqual(run.error_code, "agent_planning_failed")
plan = capability_plan_service.get_active_plan(run=run)
self.assertEqual(plan.requested_effect_scope, "persist")
self.assertEqual(create_call.status, "planned")
self.assertTrue(create_call.approval_required)
self.assertIsNone(create_call.approved_approval_id)
self.assertIsNone(create_call.output_json_redacted)
self.assertEqual(approval.approval_status, "pending")
```

- [ ] **Step 2: Verify RED if any cross-boundary behavior is missing**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_runtime tests.test_agent_planning_service -v
```

Expected before the final integration glue: failure on the first missing cross-boundary assertion; after Tasks 1-4, no production shortcut may be added merely to satisfy the test.

- [ ] **Step 3: Add only required integration glue**

Ensure the normalized decision survives Capability Plan persistence and reconstruction, the diagnostic Tool is present in frozen snapshots, and the failed-case artifact is selectable by the planner. Do not auto-approve or auto-execute `defect.create_saved`.

- [ ] **Step 4: Run focused Agent regression**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_planning_service tests.test_agent_capability_plan tests.test_agent_platform_tools tests.test_agent_runtime -v
```

Expected: all tests pass with the create Tool stopped at pending approval.

- [ ] **Step 5: Commit Task 5**

```powershell
git add -- app/services/agent_planning_service.py app/services/agent_capability_resolver.py app/services/agent_runtime_service.py app/services/agent_tool_service.py app/services/agent_platform_tool_service.py tests/test_agent_planning_service.py tests/test_agent_capability_plan.py tests/test_agent_platform_tools.py tests/test_agent_runtime.py
git commit -m "test: cover failed-case defect approval flow"
```

---

### Task 6: Documentation, Full Verification, and Real Acceptance

**Files:**
- Modify: `docs/api_agent_frontend_contract.md`
- Modify: `docs/technical_architecture.md`
- Modify: `docs/development_technical_notes.md`
- Modify: `docs/README.md` only through an Agent-specific staged hunk

**Interfaces:**
- Consumes: completed implementation and test evidence.
- Produces: synchronized runtime contract, architecture rules, test baseline, and a real acceptance Run.

- [ ] **Step 1: Update owner documentation**

Document additive planning audit fields, canonical scope semantics, `conversation_working_context_v2`, `agent.run.read_summary`, failed-case artifact fields, project isolation, and approval behavior. State explicitly that failed Agent runs and business execution failures are separate domains.

- [ ] **Step 2: Run focused and full verification**

```powershell
.\.venv\Scripts\python.exe -m compileall -q app tests
.\.venv\Scripts\python.exe -m unittest tests.test_agent_planning_service tests.test_agent_capability_plan tests.test_agent_platform_tools tests.test_agent_runtime -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -q
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic current
git diff --check
```

Expected: compile exit 0, focused and full tests report zero failures, Alembic remains a single `0040_agent_capability_plans (head)`, current matches head, and diff check reports no errors.

- [ ] **Step 3: Restart the local backend and run real DeepSeek acceptance**

Create a new Run in the same project with the target intent. Verify persisted events show:

```text
planner.llm_decision_completed
requested_effect_scope=persist
model_requested_effect_scope in {draft, execute, persist}
required_effect_scope=persist
no planner_effect_scope_exceeded
```

Allow evidence-read Tools to finish. When `defect.create_saved` reaches approval, reject the approval through the existing approval API. Verify no new defect row is created and the Run records the rejection rather than `agent_planning_failed`.

- [ ] **Step 4: Commit implementation documentation and final tests**

```powershell
git add -- app/agent_skills/agent-runtime-operations/SKILL.md app/agent_skills/defect-triage/SKILL.md app/services/agent_planning_service.py app/services/agent_capability_resolver.py app/services/agent_runtime_service.py app/services/agent_tool_service.py app/services/agent_platform_tool_service.py tests/test_agent_planning_service.py tests/test_agent_capability_plan.py tests/test_agent_platform_tools.py tests/test_agent_runtime.py docs/api_agent_frontend_contract.md docs/technical_architecture.md docs/development_technical_notes.md
git commit -m "fix: harden multi-turn agent failure recovery"
```

- [ ] **Step 5: Audit completion against the design**

Re-read `docs/superpowers/specs/2026-07-12-agent-planning-failure-recovery-design.md`. Confirm each goal has direct code, test, or live-run evidence; confirm no system-test-case runtime file is staged; and record remaining unrelated worktree changes without modifying them.
