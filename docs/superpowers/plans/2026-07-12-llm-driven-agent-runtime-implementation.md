# LLM-Driven Agent Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace keyword-authoritative Agent routing with one validated LLM planning decision and produce reference-valid, evidence-backed scenario drafts from authoritative project artifacts without changing the existing asynchronous Run/EventStore/ToolCall/SSE contracts.

**Architecture:** Add a focused LLM planning control-plane service that selects registered Skills, Tools, source artifacts, and effect scope from frozen indexes. Keep Capability Plan, permissions, approvals, project isolation, idempotency, workers, and ToolRuntime as the execution authority; add an internal native capability-request protocol and a server-side scenario source/validation pipeline so large case data never has to be copied through model-visible previews.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, MySQL/Alembic, unittest, existing DeepSeek-compatible `AIService`, existing Agent EventStore/worker/SSE runtime.

## Global Constraints

- Preserve the current asynchronous Agent Run, EventStore, ToolCall, worker, Approval, resume, cancellation, and SSE architecture.
- Preserve project isolation and all existing REST/SSE response shapes; additive events and validation envelopes are allowed.
- Production business routing must not use phrase-specific action/domain/Skill/Tool keyword fallbacks.
- The LLM may select only Skills and Tools present in the frozen RuntimeSnapshot and may not bypass schema, permissions, approvals, idempotency, project ownership, or object freshness checks.
- `draft_only` is a draft effect, not a business write; execution and persistence retain their existing policy gates.
- Real scenario nodes must reference real saved cases and a real project environment; dependencies must be supported by authoritative extractors, response samples, schemas, or explicit user contracts.
- Preserve legacy fenced Tool parsing only as a compatibility input subject to active-plan membership.
- Do not persist or expose raw chain-of-thought.

---

### Task 1: Unified LLM Planning Decision

**Files:**
- Create: `app/services/agent_planning_service.py`
- Modify: `app/services/agent_intent_decision_service.py:28-165`
- Modify: `app/services/agent_skill_registry.py:154-199`
- Test: `tests/test_agent_planning_service.py`
- Test: `tests/test_agent_intent_decision.py`

**Interfaces:**
- Consumes: `AIService.chat(AIChatRequest) -> AIChatResponse`, `AgentSkillRegistry.list_skills()`, frozen RuntimeSnapshot Tool metadata, and typed conversation artifact handles.
- Produces: `AgentPlanningDecisionService.decide(*, intent, conversation_context, skill_index, tool_index, project_id, permissions) -> ValidatedAgentPlanningDecision` and `ValidatedAgentPlanningDecision.model_view() -> dict[str, Any]`.

- [ ] **Step 1: Write failing planner-profile and structured-decision tests**

```python
def test_planning_request_disables_thinking_and_has_bounded_json_profile(self):
    request = CapturingAIService(valid_planning_json).captured_request
    self.assertEqual(request.thinking, "disabled")
    self.assertEqual(request.response_format, "json")
    self.assertEqual(request.temperature, 0)
    self.assertGreaterEqual(request.max_tokens or 0, 1024)

def test_planning_decision_owns_skills_tools_facts_and_effect_scope(self):
    decision = service.decide(...)
    self.assertEqual(decision.selected_skills, ("scenario-composition",))
    self.assertEqual(decision.selected_tools[-1], "scenario.compose_draft")
    self.assertEqual(decision.required_facts, ("project_environment_snapshot", "test_case_query_snapshot"))
    self.assertEqual(decision.requested_effect_scope, "draft")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_planning_service -v`

Expected: FAIL because `app.services.agent_planning_service` does not exist.

- [ ] **Step 3: Implement the planning models, complete indexes, and bounded repair**

```python
class AgentPlanningDecision(BaseModel):
    goal: str = Field(min_length=1, max_length=1000)
    action: str = Field(min_length=1, max_length=64)
    target_domain: str | None = None
    source_domains: list[str] = Field(default_factory=list)
    selected_skills: list[str] = Field(min_length=1)
    selected_tools: list[str] = Field(default_factory=list)
    selected_artifact_ids: list[str] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    requested_effect_scope: Literal["observe", "derive", "draft", "execute", "persist"]
    confidence: float = Field(ge=0, le=1)
    reason_summary: str = Field(min_length=1, max_length=1000)

class AgentPlanningDecisionService:
    def decide(...):
        for attempt in range(2):
            response = self.ai_service.chat(self._request(..., validation_error=validation_error))
            try:
                if not response.content.strip() or response.finish_reason != "stop":
                    raise AgentPlanningError("planner response is empty or incomplete")
                return self._validate(AgentPlanningDecision.model_validate_json(response.content), ...)
            except (ValidationError, AgentPlanningError) as exc:
                validation_error = bounded_validation_summary(exc)
        raise AgentPlanningFailed("planning decision failed after repair")
```

The request must set `thinking="disabled"`, `temperature=0`, `max_tokens=2048`, `response_format="json"`, include every registered Skill's `name/description/owns/consumes/produces/tools`, include every frozen Tool's `name/summary/side_effect_class/replay_policy/required_permissions/schema_hash`, and include typed artifact handles without Tool outputs or secrets.

- [ ] **Step 4: Validate names and metadata without semantic keyword rewriting**

```python
def _validate(self, decision, *, skill_index, tool_index, artifact_index):
    unknown_skills = set(decision.selected_skills) - set(skill_index)
    unknown_tools = set(decision.selected_tools) - set(tool_index)
    unknown_artifacts = set(decision.selected_artifact_ids) - set(artifact_index)
    if unknown_skills or unknown_tools or unknown_artifacts:
        raise AgentPlanningError(code="planner_unknown_reference", details={...})
    declared_tools = core_context_tools | union(skill_index[name]["tools"] for name in decision.selected_skills)
    if not set(decision.selected_tools) <= declared_tools:
        raise AgentPlanningError(code="planner_tool_not_declared_by_skill", details={...})
    return ValidatedAgentPlanningDecision(...)
```

- [ ] **Step 5: Prove a synthetic future Skill is selectable without a backend branch**

```python
def test_registered_future_skill_requires_no_keyword_router_change(self):
    skill_index = {"future-contract-audit": {"owns": ["contract"], "tools": ["contract.audit"]}}
    tool_index = {"contract.audit": registered_tool("deterministic_compute")}
    decision = service.decide(intent="perform the requested audit", skill_index=skill_index, tool_index=tool_index, ...)
    self.assertEqual(decision.selected_tools, ("contract.audit",))
```

- [ ] **Step 6: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_planning_service tests.test_agent_intent_decision -v`

Expected: PASS; old intent tests remain compatible through a non-authoritative adapter.

Commit: `git commit -m "feat: add unified llm agent planning" -- app/services/agent_planning_service.py app/services/agent_intent_decision_service.py app/services/agent_skill_registry.py tests/test_agent_planning_service.py tests/test_agent_intent_decision.py`

### Task 2: Capability Plan as Validated LLM Plan

**Files:**
- Modify: `app/services/agent_capability_resolver.py:96-322`
- Modify: `app/services/agent_context_manager.py:38-273`
- Modify: `app/services/agent_capability_plan_service.py:30-230,347-386`
- Test: `tests/test_agent_capability_plan.py`

**Interfaces:**
- Consumes: `ValidatedAgentPlanningDecision`, frozen `AgentRuntimeSnapshot`, registered Skill metadata, and Tool side-effect classes.
- Produces: `AgentCapabilityResolver.resolve_planning_decision(...) -> AgentCapabilityPlan`, where `allowed_tools` exactly reflects validated selected Tools plus core context Tools and effect scopes use `observe/derive/draft/execute/persist`.

- [ ] **Step 1: Write failing scope and authority tests**

```python
def test_draft_only_tool_is_allowed_for_draft_scope(self):
    decision = planning_decision(selected_tools=("scenario.compose_draft",), requested_effect_scope="draft")
    plan = resolver.resolve_planning_decision(decision=decision, runtime_tools=runtime_tools)
    self.assertIn("scenario.compose_draft", plan.allowed_tools)

def test_resolver_does_not_replace_llm_selection_from_intent_keywords(self):
    decision = planning_decision(selected_skills=("scenario-composition",), selected_tools=("scenario.compose_draft",))
    plan = resolver.resolve_planning_decision(decision=decision, intent="contains misleading flow vocabulary", ...)
    self.assertEqual(plan.selected_skill_names, ("scenario-composition",))
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_capability_plan.AgentCapabilityPlanTests.test_draft_only_tool_is_allowed_for_draft_scope -v`

Expected: FAIL because the resolver still prunes from `write_authorized` and keyword-derived intent action.

- [ ] **Step 3: Add explicit effect-scope mapping and validated-decision resolver**

```python
TOOL_EFFECT_SCOPES = {
    "read_only": "observe",
    "deterministic_compute": "derive",
    "draft_only": "draft",
    "execution_record": "execute",
    "business_update": "persist",
}

def resolve_planning_decision(self, *, decision, runtime_tools, core_context_tools=...):
    selected = tuple(dict.fromkeys((*core_context_tools, *decision.selected_tools)))
    self._validate_effect_scope(decision.requested_effect_scope, selected, runtime_tools)
    return AgentCapabilityPlan(allowed_tools=selected, required_facts=decision.required_facts, ...)
```

Remove `write_authorized` pruning and `tool_matches_intent_decision` from production authorization. Keep deterministic inference methods callable only from explicit offline diagnostics/evaluation paths.

- [ ] **Step 4: Persist the unified decision without changing the table contract**

```python
payload = {
    "intent_decision_json": decision.model_view(),
    "skill_plan_json": {
        "selected_skill_names": list(decision.selected_skills),
        "selected_artifact_ids": list(decision.selected_artifact_ids),
        "requested_effect_scope": decision.requested_effect_scope,
    },
    "allowed_tools_json": list(capability_plan.allowed_tools),
    "required_facts_json": list(decision.required_facts),
}
```

- [ ] **Step 5: Build context messages and native schemas from the persisted selection**

Update `AgentContextManager.route` to accept the validated planning decision and stop invoking `AgentSkillPlanner` as an independent authority. Deterministic ranking may be included in the planning index as `retrieval_rank`, but it may not set `selected_skills` or `allowed_tools`.

- [ ] **Step 6: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_capability_plan -v`

Expected: PASS including plan hashes, project/run ownership, and supersession behavior.

Commit: `git commit -m "refactor: derive capability plans from llm planning" -- app/services/agent_capability_resolver.py app/services/agent_context_manager.py app/services/agent_capability_plan_service.py tests/test_agent_capability_plan.py`

### Task 3: Transactional Native Capability Activation

**Files:**
- Modify: `app/services/agent_native_tool_call.py:14-123`
- Modify: `app/services/agent_capability_plan_service.py:135-230`
- Modify: `app/services/agent_runtime_service.py:2050-3500`
- Test: `tests/test_agent_native_tool_call.py`
- Test: `tests/test_agent_capability_plan.py`

**Interfaces:**
- Consumes: native `runtime.request_capability` arguments `{tool_names: list[str], reason: str}`, active Capability Plan, RuntimeSnapshot, Skill index, and current permission summary.
- Produces: `CapabilityActivationResult(plan_id, activated_tools, rejected_tools, rejection_reasons)` and a newly committed Capability Plan revision only when all activation validation passes.

- [ ] **Step 1: Write failing native-definition and atomicity tests**

```python
def test_native_definitions_always_include_runtime_capability_request(self):
    definitions = build_native_tool_definitions(allowed_tools=[], ...)
    self.assertIn("runtime_request_capability", [item.function.name for item in definitions])

def test_capability_activation_rejects_atomically(self):
    before = run.active_capability_plan_id
    result = service.request_capabilities(run=run, current=current, tool_names=["scenario.compose_draft", "invented.tool"], ...)
    self.assertFalse(result.accepted)
    self.assertEqual(run.active_capability_plan_id, before)
    self.assertEqual(self.db.query(AgentCapabilityPlanRecord).filter_by(parent_capability_plan_id=before).count(), 0)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_native_tool_call tests.test_agent_capability_plan -v`

Expected: FAIL because the internal Runtime Tool and atomic request API do not exist.

- [ ] **Step 3: Add the internal native control Tool**

```python
RUNTIME_REQUEST_CAPABILITY_ALIAS = "runtime_request_capability"
RUNTIME_REQUEST_CAPABILITY_DEFINITION = AIChatToolDefinition(function=AIChatFunctionDefinition(
    name=RUNTIME_REQUEST_CAPABILITY_ALIAS,
    description="Request activation of registered Tools for the current goal.",
    parameters={"type": "object", "properties": {"tool_names": {...}, "reason": {...}}, "required": ["tool_names", "reason"]},
))
```

Teach `NativeToolCallAccumulator.finalize` to return `NativeCapabilityRequest` for this exact internal alias; it must not resolve through public Tool aliases or invoke a business handler.

- [ ] **Step 4: Implement transactional capability validation and revision**

```python
def request_capabilities(self, *, run, current, tool_names, planning_decision, skill_index, permission_names):
    requested = tuple(dict.fromkeys(tool_names))
    errors = self._validate_activation(requested, snapshot=current.runtime_snapshot, skills=skill_index, permissions=permission_names)
    if errors:
        return CapabilityActivationResult(accepted=False, plan_id=current.capability_plan_id, rejection_reasons=errors)
    return CapabilityActivationResult.from_plan(self._supersede_with_tools(current, requested, source="llm_capability_request"))
```

Validation must prove every Tool exists in the frozen snapshot, is declared by a selected/newly selected registered Skill or is a core context Tool, required permissions are present, and effect scope/approval semantics remain enforceable. Do not compare the Tool name to keyword-derived target/action prefixes.

- [ ] **Step 5: Return structured Tool messages and append activation events**

Append `planner.capability_activation_requested`, `accepted` or `rejected`, and `planner.capability_plan_revised`; feed the bounded result to the next model turn using the provider ToolCall id. Refresh native Tool definitions only after the revised plan commits.

- [ ] **Step 6: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_native_tool_call tests.test_agent_capability_plan -v`

Expected: PASS; failed requests leave plan status and active id unchanged.

Commit: `git commit -m "feat: add transactional capability activation" -- app/services/agent_native_tool_call.py app/services/agent_capability_plan_service.py app/services/agent_runtime_service.py tests/test_agent_native_tool_call.py tests/test_agent_capability_plan.py`

### Task 4: Structured Runtime Plan-Mismatch Recovery

**Files:**
- Modify: `app/services/agent_runtime_service.py:2680-3500,10292-10331`
- Modify: `app/services/agent_runbook_service.py`
- Test: `tests/test_agent_runtime.py`

**Interfaces:**
- Consumes: `CapabilityPlanToolNotAllowed`, `CapabilityPlanNotActive`, invalid activation results, and assistant denial diagnostics.
- Produces: model-observable `agent_capability_not_active` / `agent_capability_activation_rejected` Tool results and explicit Run events without converting recoverable plan mismatch into `agent_conversation_unhandled_error`.

- [ ] **Step 1: Write failing mismatch and denial-observability tests**

```python
def test_inactive_tool_call_returns_model_observable_error(self):
    run = execute_model_call(native_tool="scenario.compose_draft", active_tools=["scenario.query_project_scenarios"])
    self.assertNotEqual(run.status, "failed")
    self.assertIn("agent_capability_not_active", next_model_tool_message(run))

def test_text_denial_does_not_rebuild_capability_plan(self):
    before = run.active_capability_plan_id
    runner.handle_assistant("当前没有 scenario.compose_draft")
    self.assertEqual(run.active_capability_plan_id, before)
    self.assertIn("model.capability_denial_observed", event_types(run))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_runtime.AgentConversationRunnerTests.test_inactive_tool_call_returns_model_observable_error tests.test_agent_runtime.AgentConversationRunnerTests.test_text_denial_does_not_rebuild_capability_plan -v`

Expected: FAIL because denial repair currently attempts `expand_plan_for_tool` and mismatch may escape as an unhandled error.

- [ ] **Step 3: Replace denial repair with diagnostics-only behavior**

Delete production calls from `_repair_available_capability_denial` to `expand_plan_for_tool`. `_guard_available_capability_denial` may append a bounded diagnostic event containing `mentioned_tool`, `active_plan_id`, and `requestable=true`, but it must return the assistant content unchanged and must not synthesize a fenced Tool request.

- [ ] **Step 4: Normalize plan exceptions inside the model loop**

```python
except CapabilityPlanToolNotAllowed as exc:
    result = {"ok": False, "code": "agent_capability_not_active", "tool_name": exc.tool_name,
              "active_plan_id": exc.capability_plan_id,
              "next_action": "call runtime.request_capability"}
    messages.append(provider_tool_result(tool_call_id, result))
    runtime.append_event(run, "planner.capability_call_rejected", result, commit=True)
    continue
```

Map `CapabilityPlanNotActive` and activation validation failures similarly. Reserve `agent_conversation_unhandled_error` for genuinely unknown exceptions.

- [ ] **Step 5: Add Runbook classification and regression proof**

The Runbook must classify these errors as planning/runtime protocol failures with plan ids and Tool names, not backend handler failures. Assert the business Tool handler invocation count remains zero for rejected calls.

- [ ] **Step 6: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_runtime -k capability -v`

Expected: PASS with no illegal fenced repair path.

Commit: `git commit -m "fix: recover agent capability mismatches structurally" -- app/services/agent_runtime_service.py app/services/agent_runbook_service.py tests/test_agent_runtime.py`

### Task 5: Authoritative Scenario Source Resolution

**Files:**
- Create: `app/services/agent_scenario_source_service.py`
- Modify: `app/schemas/ai.py:136-150`
- Modify: `app/services/agent_tool_service.py:126-180,904-982,3428-3488`
- Test: `tests/test_agent_scenario_source.py`
- Test: `tests/test_agent_runtime.py`

**Interfaces:**
- Consumes: `case_source={artifact_id, output_hash}`, `environment_reference`, current user/project, and successful `testcase.query_project_cases` ToolCall ledger output.
- Produces: `ResolvedScenarioSource(project_id, environment_id, http_case_ids, websocket_case_ids, case_snapshots, evidence_sources)` using the full redacted ledger output rather than the compact model preview.

- [ ] **Step 1: Write failing ownership, hash, and full-ledger tests**

```python
def test_resolves_complete_case_source_from_same_project_ledger(self):
    resolved = service.resolve(project_id=1, user_id=user.id, case_source={"artifact_id": artifact_id, "output_hash": output_hash})
    self.assertEqual(len(resolved.case_snapshots), 15)
    self.assertEqual(resolved.http_case_ids, tuple(real_database_case_ids))

def test_rejects_cross_project_or_stale_hash_source(self):
    with self.assertRaises(HTTPException) as raised:
        service.resolve(project_id=2, user_id=user.id, case_source={"artifact_id": project_1_artifact, "output_hash": "stale"})
    self.assertEqual(raised.exception.detail["code"], "agent_scenario_case_source_invalid")
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_scenario_source -v`

Expected: FAIL because the resolver and `case_source` contract do not exist.

- [ ] **Step 3: Add the typed source contract**

```python
class AIAgentArtifactSource(BaseModel):
    artifact_id: str = Field(min_length=1)
    output_hash: str = Field(min_length=1)

class AIScenarioComposeRequest(BaseModel):
    requirement: str
    case_source: AIAgentArtifactSource | None = None
    environment_reference: str | None = None
    ...
```

Keep existing ID fields for compatibility, but when `case_source` is present it is authoritative and explicit copied IDs must be a subset of the resolved source.

- [ ] **Step 4: Resolve and validate the ledger artifact server-side**

Query `AgentToolCall` joined to `AgentRun`; require successful `testcase.query_project_cases`, same project, same user/conversation access, exact `output_hash`, and an artifact id produced by `_tool_call_artifact_manifest`. Read `output_json_redacted` directly, normalize all saved HTTP/WebSocket case ids, and reload current database records to prove project ownership and deletion status.

- [ ] **Step 5: Wire `scenario.compose_draft` to authoritative source and environment**

Use `_resolve_environment_id` for `environment_reference`; stop falling back to the first eight database cases when an authoritative source was supplied. Pass full resolved case ids and evidence metadata to `AISkillService`, and return `evidence_sources` without exposing unredacted secrets.

- [ ] **Step 6: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_scenario_source tests.test_agent_runtime -k scenario_compose -v`

Expected: PASS; truncating the model preview does not reduce the resolved candidate set.

Commit: `git commit -m "feat: resolve authoritative scenario case sources" -- app/services/agent_scenario_source_service.py app/schemas/ai.py app/services/agent_tool_service.py tests/test_agent_scenario_source.py tests/test_agent_runtime.py`

### Task 6: Reference-Valid Evidence-Backed Scenario Quality Gate

**Files:**
- Create: `app/services/agent_scenario_draft_validator.py`
- Modify: `app/services/scenario_graph_validator.py`
- Modify: `app/services/agent_tool_service.py:965-982`
- Modify: `app/services/ai_scenario_composer_service.py`
- Test: `tests/test_agent_scenario_draft_validator.py`
- Test: `tests/test_ai_skills.py`

**Interfaces:**
- Consumes: generated `draft.scenario`, `ResolvedScenarioSource`, real saved case records, environment id, extractors/response samples/schemas, and explicit user contract evidence.
- Produces: `ScenarioDraftValidationResult(valid, scenario, scenario_validation)`; only valid results are eligible for AUTHORITATIVE/SOURCE artifact projection.

- [ ] **Step 1: Write failing real-reference and invented-dependency tests**

```python
def test_valid_draft_references_real_cases_and_environment(self):
    result = validator.validate(draft=real_draft, source=resolved_source)
    self.assertTrue(result.valid)
    self.assertEqual(result.validation["referenced_case_count"], len(real_draft["nodes"]))
    self.assertEqual(result.validation["unresolved_reference_count"], 0)

def test_invented_endpoint_or_binding_is_not_authoritative(self):
    result = validator.validate(draft=draft_with_fake_path_and_unproven_binding, source=resolved_source)
    self.assertFalse(result.valid)
    self.assertIn("node_request_reference_mismatch", issue_codes(result))
    self.assertIn("binding_source_not_evidenced", issue_codes(result))
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_scenario_draft_validator -v`

Expected: FAIL because the quality validator does not exist.

- [ ] **Step 3: Implement reference and request compatibility checks**

For every primary node, resolve the saved HTTP/WebSocket reference in `ResolvedScenarioSource`; require matching case type, method/path or websocket URL contract, project ownership, and environment compatibility. Reject invented ids/endpoints and duplicate ambiguous references.

- [ ] **Step 4: Implement evidence-backed extractor/binding/template checks**

Build an evidence index from saved extractors, redacted latest response samples, response schemas, and explicit requirement contracts. Require each template variable to have exactly one upstream source, each binding target to exist in the downstream request shape, and each edge to be acyclic. Do not create an edge merely because two nodes are sequential; independent real cases remain valid.

- [ ] **Step 5: Return the complete quality envelope and repair loop signal**

```python
scenario_validation = {
    "valid": not errors,
    "referenced_case_count": referenced_count,
    "unresolved_reference_count": unresolved_count,
    "dependency_edge_count": edge_count,
    "resolved_template_count": resolved_templates,
    "unresolved_template_count": unresolved_templates,
    "extractor_count": extractor_count,
    "binding_count": binding_count,
    "graph_errors": graph_errors,
    "quality_issues": issues,
    "evidence_sources": source.evidence_sources,
}
```

Invalid drafts return `agent_scenario_draft_invalid` as a diagnostic Tool result so the existing model loop can repair within its bounded iteration budget. Mark artifact trust AUTHORITATIVE/SOURCE only when `valid=true`.

- [ ] **Step 6: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_scenario_draft_validator tests.test_ai_skills -v`

Expected: PASS for real independent cases, evidenced dependencies, invalid references, cycles, unresolved templates, and request mismatches.

Commit: `git commit -m "feat: validate real agent scenario drafts" -- app/services/agent_scenario_draft_validator.py app/services/scenario_graph_validator.py app/services/agent_tool_service.py app/services/ai_scenario_composer_service.py tests/test_agent_scenario_draft_validator.py tests/test_ai_skills.py`

### Task 7: Runtime Integration, Multi-Turn Skill Switching, and Events

**Files:**
- Modify: `app/services/agent_runtime_service.py:2050-6070`
- Modify: `app/services/agent_context_manager.py`
- Modify: `app/services/agent_tool_result_projection.py`
- Modify: `app/schemas/agent.py`
- Test: `tests/test_agent_runtime.py`

**Interfaces:**
- Consumes: `AgentPlanningDecisionService`, validated Capability Plan, typed conversation artifacts, structured capability results, and scenario validation envelope.
- Produces: unchanged REST/SSE shapes with additive planner/scenario events and a complete multi-turn Tool loop that can select a different Skill on every user turn.

- [ ] **Step 1: Write failing end-to-end runtime regressions**

```python
def test_multiturn_case_analysis_then_real_scenario_changes_skill(self):
    first = run_turn("分析项目测试用例")
    second = run_turn("现在构建一个可执行自动化测试流程", conversation_id=first.conversation_id)
    self.assertEqual(planning_decision(second)["selected_skills"], ["scenario-composition"])
    self.assertIn(case_source_artifact(first), planning_decision(second)["selected_artifact_ids"])
    self.assertEqual(tool_names(second), ["project.read_context", "scenario.compose_draft"])
    self.assertTrue(scenario_validation(second)["valid"])

def test_later_unrelated_turn_is_not_locked_to_previous_skill(self):
    third = run_turn("根据刚才结果生成测试报告", conversation_id=conversation_id)
    self.assertIn("report-summary", planning_decision(third)["selected_skills"])
    self.assertNotIn("scenario-composition", planning_decision(third)["selected_skills"])
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_runtime -k llm_planning -v`

Expected: FAIL because Runtime still calls `_resolve_intent_decision` and independently routes the Skill plan.

- [ ] **Step 3: Replace production intent fallback with the unified planning call**

At the start of each run iteration, build frozen Skill/Tool/artifact indexes, append `planner.llm_decision_started`, invoke the bounded planner, validate, append `completed` or `invalid/retrying/failed`, persist the Capability Plan, and build native definitions from it. If both attempts fail, fail the run with `agent_planning_failed`; never call `parse_agent_intent_action` for production authorization.

- [ ] **Step 4: Preserve typed multi-turn artifact handles**

Expose artifact type/trust, producing Tool/run, available follow-up actions, object references, hashes, recency, and project scope. Validate planner-selected handles against current user/project/conversation and freshness before putting them into required facts or Tool input hints.

- [ ] **Step 5: Project valid scenario drafts as authoritative artifacts**

Update Tool result projection so `scenario.compose_draft` is SOURCE/AUTHORITATIVE only when `draft.scenario_validation.valid is True`; invalid drafts remain diagnostic and are returned to the model for repair.

- [ ] **Step 6: Run Agent Runtime tests and commit**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_runtime -v`

Expected: PASS including existing approval, resume, cancellation, worker, EventStore, and SSE tests.

Commit: `git commit -m "feat: integrate llm-driven agent planning loop" -- app/services/agent_runtime_service.py app/services/agent_context_manager.py app/services/agent_tool_result_projection.py app/schemas/agent.py tests/test_agent_runtime.py`

### Task 8: Documentation, Full Regression, Restart, and Real Acceptance

**Files:**
- Modify: `docs/technical_architecture.md`
- Modify: `docs/api_agent_frontend_contract.md`
- Modify: `docs/api_ai.md`
- Modify: `docs/development_technical_notes.md`
- Modify: `app/agent_skills/scenario-composition/SKILL.md`
- Test: repository-wide existing tests

**Interfaces:**
- Consumes: final implementation and current database/runtime configuration.
- Produces: synchronized backend/frontend contracts, clean regressions, a controlled running backend, and a real AgentRun proving the original conversation now yields a validated scenario draft.

- [ ] **Step 1: Update authoritative documentation**

Document the unified planner, internal `runtime.request_capability`, effect scopes, additive event names, plan mismatch errors, `case_source`/`environment_reference`, `scenario_validation`, frontend Chinese labels, and the rule that invalid drafts are not authoritative artifacts. Preserve existing API paths and SSE payload envelopes.

- [ ] **Step 2: Run focused suites**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_agent_planning_service tests.test_agent_intent_decision tests.test_agent_capability_plan tests.test_agent_native_tool_call tests.test_agent_scenario_source tests.test_agent_scenario_draft_validator tests.test_ai_skills tests.test_agent_runtime -v
```

Expected: all focused tests PASS.

- [ ] **Step 3: Run static and migration gates**

Run:

```powershell
.venv\Scripts\python.exe -m compileall -q app tests
.venv\Scripts\alembic.exe heads
.venv\Scripts\alembic.exe current
git diff --check
```

Expected: compile succeeds; Alembic reports one head and current is at that head; no whitespace errors.

- [ ] **Step 4: Run full repository regression**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -v`

Expected: all repository tests PASS; any skips are pre-existing and explained.

- [ ] **Step 5: Restart the backend through its existing controlled launcher**

Identify the current listener and launcher, stop only the TestAuto backend processes, start the documented backend command hidden, then verify `/api/v1/health` and database connectivity. Do not alter the worker/SSE architecture or start an unrelated server.

- [ ] **Step 6: Execute the real multi-turn Agent acceptance**

Through the real HTTP API and project 1:

1. Start/continue a conversation with `分析项目测试用例`.
2. Send `现在我需要构建一个自动化测试流程` in the same conversation.
3. Poll the asynchronous AgentRun and hydrate ToolCalls/events.
4. Verify planner response completed with `thinking=disabled`, selected `scenario-composition`, selected the real test-case SOURCE artifact, and did not use deterministic keyword fallback.
5. Verify every scenario node reference and environment id against the database.
6. Verify `scenario_validation.valid=true`, zero unresolved references/templates, and no invented endpoint/dependency.
7. Stop before save/live execution unless separately authorized because real POST cases may mutate external business data.

- [ ] **Step 7: Commit documentation and verification evidence**

Commit: `git commit -m "docs: document llm-driven agent runtime" -- docs/technical_architecture.md docs/api_agent_frontend_contract.md docs/api_ai.md docs/development_technical_notes.md app/agent_skills/scenario-composition/SKILL.md`

Record the final test counts, Alembic state, backend health result, real Run id, plan id, selected Skills/Tools, and scenario validation metrics in the completion handoff.
