# Agent Unified Capability Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Agent use LLM-produced structured intent and one persisted Capability Plan as the shared authority for routed context, denial repair, ToolRuntime validation, and native structured tool calls.

**Architecture:** Add a provider-independent intent decision service and a persisted capability-plan ledger. The conversation runner obtains and validates intent, resolves a bounded context plan, persists it, and tags model/tool activity with the plan ID; route rebuilds create new revisions. DeepSeek native tool calls normalize into the existing `AgentToolRequest` and asynchronous ToolCall ledger, while fenced JSON remains a compatibility fallback.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, DeepSeek OpenAI-compatible Chat Completions, Python `unittest`.

## Global Constraints

- Preserve all existing ToolSpec names and backend handlers.
- Preserve asynchronous runner, worker queue, EventStore, outbox, approval, resume, reconciliation, idempotency, schema preflight, object-reference freshness, project isolation, and replay policy.
- Do not expose all tools to the model; native tool definitions come only from the active plan.
- New database fields remain nullable for historical rows; new model-driven ToolCalls require a plan ID.
- Native tool calling is capability-gated and fenced JSON remains a tested fallback.
- `AGENT_LLM_INTENT_DECISION_ENABLED` and `AGENT_NATIVE_TOOL_CALLING_ENABLED` default to enabled in runtime configuration; unit tests disable them globally unless a focused test injects a fake provider response.
- Preserve all unrelated dirty-worktree changes.
- Follow RED-GREEN-REFACTOR for every behavior change.
- Because implementation files already contain user-owned uncommitted work, do not create intermediate implementation commits that would absorb unrelated hunks; checkpoint with tests and `git diff --check` instead.

---

### Task 1: Structured LLM intent decision and paraphrase matrix

**Files:**
- Create: `app/services/agent_intent_decision_service.py`
- Modify: `app/services/agent_intent_action.py`
- Modify: `app/services/agent_skill_planner.py`
- Modify: `app/services/agent_capability_resolver.py`
- Modify: `app/services/agent_context_manager.py`
- Modify: `app/core/config.py`
- Test: `tests/test_agent_intent_decision.py`
- Test: `tests/test_agent_runtime.py`

**Interfaces:**
- Produces: `AgentIntentDecision`, `ValidatedAgentIntentDecision`, `AgentIntentDecisionService.decide(...)`, and optional `intent_action` arguments on planner/resolver/context routing.
- Consumes: `AIService.chat`, bounded domain/action metadata, and compact artifact handles.

- [ ] **Step 1: Write failing paraphrase and LLM-override tests**

```python
def test_cross_domain_paraphrases_preserve_target_and_sources():
    cases = {
        "给错误的测试用例创建缺陷": ("create", "defect", ("test_case",)),
        "根据失败用例创建对应的缺陷": ("create", "defect", ("test_case",)),
        "把失败执行转成缺陷": ("create", "defect", ("execution",)),
        "根据报告生成测试计划": ("create", "test_plan", ("report",)),
        "使用这个缺陷生成回归测试用例": ("create", "test_case", ("defect",)),
    }
    for text, expected in cases.items():
        action = parse_agent_intent_action(text)
        assert (action.action, action.target_domain, action.source_domains) == expected

def test_validated_llm_decision_overrides_deterministic_fallback():
    decision = ValidatedAgentIntentDecision(
        action="create", target_domain="defect", source_domains=("test_case",), confidence=0.96, source="llm"
    )
    plan = AgentContextManager().route("ambiguous text", intent_action=decision.as_intent_action())
    assert plan.primary_skill == "defect-triage"
    assert "defect.create_saved" in plan.allowed_tools
```

- [ ] **Step 2: Run tests and verify RED**

Run: `\.venv\Scripts\python.exe -m unittest tests.test_agent_intent_decision`

Expected: FAIL because the intent decision service and route override do not exist, and the original run-518 phrase targets `test_case`.

- [ ] **Step 3: Implement structured decision validation and grammatical fallback**

```python
class AgentIntentDecision(BaseModel):
    action: AgentIntentActionName | None
    target_domain: str | None
    source_domains: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)

class AgentIntentDecisionService:
    def decide(self, *, intent: str, working_context: dict[str, Any] | None, domains: tuple[str, ...]) -> ValidatedAgentIntentDecision:
        response = self.ai_service.chat(self._request(intent, working_context, domains))
        return self.validator.validate_json(response.content)
```

Remove the literal `测试用例 -> test_case` create override. The fallback selects an explicit target following the action predicate and treats preceding domains as evidence; invalid or low-confidence LLM output may only produce a read-only fallback.

The runner honors `AGENT_LLM_INTENT_DECISION_ENABLED`. Existing broad runtime tests patch it off to prevent network access; focused decision tests inject a fake `AIService.chat` response and verify the LLM path directly.

- [ ] **Step 4: Pass the validated decision through planner, resolver, and context manager**

```python
def route(self, intent: str, *, working_context=None, intent_action: AgentIntentAction | None = None):
    skill_plan = self.skill_planner.plan(..., intent_action=intent_action)
    capability_plan = self.capability_resolver.resolve(..., intent_action=intent_action)
```

- [ ] **Step 5: Run focused GREEN tests**

Run: `\.venv\Scripts\python.exe -m unittest tests.test_agent_intent_decision tests.test_agent_runtime.AgentRuntimeTests.test_context_manager_exposes_defect_create_and_case_evidence_tools`

Expected: PASS.

---

### Task 2: Persisted Capability Plan model, migration, and service

**Files:**
- Modify: `app/models/agent.py`
- Modify: `app/models/__init__.py`
- Modify: `app/schemas/agent.py`
- Create: `app/services/agent_capability_plan_service.py`
- Create: `migrations/versions/0040_agent_capability_plans.py`
- Test: `tests/test_agent_capability_plan.py`

**Interfaces:**
- Produces: `AgentCapabilityPlanRecord`, `AgentCapabilityPlanService.create_active_plan(...)`, `get_active_plan(...)`, `supersede_with_plan(...)`, `require_tool_membership(...)`.
- Consumes: `AgentContextPlan.model_view()`, `AgentRun.runtime_snapshot_id`, and ToolRegistry canonical names.

- [ ] **Step 1: Write failing persistence and lineage tests**

```python
def test_capability_plan_persists_and_supersedes_revisions(self):
    first = service.create_active_plan(run=run, iteration=0, context_plan=context_plan, source="llm_intent")
    second = service.supersede_with_plan(current=first, context_plan=expanded, source="route_rebuild")
    self.assertEqual(first.status, "superseded")
    self.assertEqual(second.parent_capability_plan_id, first.capability_plan_id)
    self.assertEqual(second.revision, 1)
    self.assertEqual(run.active_capability_plan_id, second.capability_plan_id)
```

- [ ] **Step 2: Run migration/model tests and verify RED**

Run: `\.venv\Scripts\python.exe -m unittest tests.test_agent_capability_plan`

Expected: FAIL because the model/table/service do not exist.

- [ ] **Step 3: Add the model and additive columns**

```python
class AgentCapabilityPlanRecord(Base):
    __tablename__ = "ai_agent_capability_plans"
    capability_plan_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    iteration: Mapped[int] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(nullable=False)
    parent_capability_plan_id: Mapped[str | None] = mapped_column(String(64))
    runtime_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    intent_decision_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    skill_plan_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    allowed_tools_json: Mapped[list] = mapped_column(JSON, nullable=False)
    tool_aliases_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    required_facts_json: Mapped[list] = mapped_column(JSON, nullable=False)
    reason_codes_json: Mapped[list] = mapped_column(JSON, nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
```

Add `AgentRun.active_capability_plan_id` and `AgentToolCall.capability_plan_id` as nullable indexed strings. Migration `0040` revises `0039_system_test_cases` and performs no data backfill.

- [ ] **Step 4: Implement transactional plan creation and membership validation**

```python
def require_tool_membership(self, *, run: AgentRun, capability_plan_id: str, tool_name: str) -> AgentCapabilityPlanRecord:
    plan = self.get_active_plan(run=run, capability_plan_id=capability_plan_id, for_update=True)
    if tool_name not in plan.allowed_tools_json:
        raise CapabilityPlanToolNotAllowed(tool_name=tool_name, capability_plan_id=capability_plan_id)
    return plan
```

- [ ] **Step 5: Run GREEN tests and migration-head check**

Run: `\.venv\Scripts\python.exe -m unittest tests.test_agent_capability_plan`

Run: `\.venv\Scripts\alembic.exe heads`

Expected: tests PASS and one head is `0040_agent_capability_plans`.

---

### Task 3: Bind runner, model context, events, checkpoints, and ToolCalls to one plan ID

**Files:**
- Modify: `app/services/agent_context_manager.py`
- Modify: `app/services/agent_runtime_service.py`
- Modify: `app/schemas/agent.py`
- Test: `tests/test_agent_runtime.py`
- Test: `tests/test_agent_capability_plan.py`

**Interfaces:**
- Consumes: Task 1 validated intent and Task 2 persistence service.
- Produces: `capability_plan_id` on model trace events, run state, checkpoints, and ToolCalls.

- [ ] **Step 1: Write failing end-to-end plan identity test**

```python
def test_runner_uses_one_capability_plan_for_prompt_guard_and_tool_call(self):
    completed = runner.run(run_id=run.run_id, user_id=user.id)
    plan_id = completed.active_capability_plan_id
    self.assertIsNotNone(plan_id)
    self.assertEqual(tool_call.capability_plan_id, plan_id)
    self.assertTrue(all(e.payload_json.get("capability_plan_id") == plan_id for e in model_events))
```

- [ ] **Step 2: Verify RED**

Run the named test; expect missing `active_capability_plan_id` and event metadata.

- [ ] **Step 3: Create and attach the active plan before the first model call**

```python
intent_decision = intent_decision_service.decide_or_fallback(...)
context_plan = context_manager.route(run.intent, working_context=working_context, intent_action=intent_decision.as_intent_action())
plan_record = capability_plan_service.create_active_plan(run=run, iteration=0, context_plan=context_plan, source=intent_decision.source)
messages = context_manager.build_envelope(context_plan, static_prompt=...).messages
```

Every model-call trace payload includes the active plan ID. Ordinary loop iterations reuse the active plan; route rebuild changes the ID explicitly.

- [ ] **Step 4: Require plan identity when the runner creates a ToolCall**

```python
AgentToolCallCreateRequest(
    run_id=run.run_id,
    capability_plan_id=run.active_capability_plan_id,
    tool_name=tool_request.tool_name,
    ...,
)
```

- [ ] **Step 5: Run focused GREEN and compatibility tests**

Run the new identity test plus existing runner approval, resume, and ToolCall read tests. Expected: PASS with historical nullable compatibility intact.

---

### Task 4: ToolRuntime plan membership and formal capability expansion

**Files:**
- Modify: `app/services/agent_capability_plan_service.py`
- Modify: `app/services/agent_runtime_service.py`
- Test: `tests/test_agent_capability_plan.py`
- Test: `tests/test_agent_runtime.py`

**Interfaces:**
- Produces: `CapabilityPlanToolNotAllowed`, `expand_plan_for_tool(...)`, and expansion events.
- Consumes: active plan, runtime snapshot, validated intent decision, ToolSpec side-effect metadata.

- [ ] **Step 1: Write failing out-of-plan rejection and expansion tests**

```python
def test_out_of_plan_tool_never_reaches_ledger(self):
    with self.assertRaises(CapabilityPlanToolNotAllowed):
        ledger.create_tool_call(payload=outside_plan_payload, current_user=user)
    self.assertIsNone(find_tool_call(outside_plan_payload.tool_name))

def test_valid_expansion_creates_revision_before_retry(self):
    expanded = service.expand_plan_for_tool(current=plan, tool_name="defect.create_saved")
    self.assertEqual(expanded.revision, plan.revision + 1)
    self.assertIn("defect.create_saved", expanded.allowed_tools_json)
```

- [ ] **Step 2: Verify RED**

Expected: the ledger currently accepts any registered tool without plan membership.

- [ ] **Step 3: Enforce membership before schema repair, permission, approval, or ToolCall creation**

Call `require_tool_membership(...)` immediately after locking the run and before `ToolRegistry.get(...)` side effects.

- [ ] **Step 4: Implement bounded expansion**

Expansion validates that the tool exists in the referenced RuntimeSnapshot and matches the validated target action/domain. It persists a new revision, emits `planner.capability_expansion_requested`, `planner.capability_expansion_applied`, or `planner.capability_expansion_rejected`, regenerates context, and requires the model to emit the request again; the original request is never executed.

- [ ] **Step 5: Run GREEN tests**

Run focused membership, expansion, approval, and execution tests. Expected: out-of-plan calls create no ToolCall; valid expansion creates a new plan before a later retry.

---

### Task 5: Capability-denial guard route rebuild with refreshed catalog and schema

**Files:**
- Modify: `app/services/agent_runtime_service.py`
- Modify: `app/services/agent_context_manager.py`
- Modify: `app/services/agent_capability_plan_service.py`
- Test: `tests/test_agent_runtime.py`

**Interfaces:**
- Consumes: active plan, runtime snapshot, plan expansion/rebuild service.
- Produces: generalized route mismatch detection and rebuilt plan context.

- [ ] **Step 1: Write failing guard tests**

```python
def test_guard_rebuilds_hidden_runtime_tool_before_replan(self):
    rebuilt = runner._repair_available_capability_denial(...)
    self.assertNotEqual(run.active_capability_plan_id, old_plan.capability_plan_id)
    self.assertIn("defect.create_saved", rebuilt.plan.allowed_tools)
    self.assertIn('"required":["project_id","defect"]', rebuilt.contract_message.content)
```

Also cover: tool already in plan, tool absent globally, and a non-defect target such as report-to-plan.

- [ ] **Step 2: Verify RED**

Expected: current guard compares only against RuntimeSnapshot and reuses stale messages without the missing schema.

- [ ] **Step 3: Replace snapshot-only guard decisions with active-plan comparison**

```python
if expected_tool in active_plan.allowed_tools_json:
    return replan_same_plan(...)
if expected_tool in runtime_snapshot_tool_names:
    return rebuild_route_and_replan(...)
return unsupported_capability(...)
```

- [ ] **Step 4: Rebuild the full routed envelope**

Append a supersession marker and newly generated Skill plan, tool catalog, capability plan, and exact tool-contract messages from the new plan revision. Never instruct the model to call a tool absent from that revision.

The stale-route branch emits `planner.route_mismatch_detected` with both old and rebuilt plan IDs; the same-plan denial branch emits `model.capability_denial_in_plan`.

- [ ] **Step 5: Run GREEN tests including original run-518 wording**

Expected: the original wording creates a defect plan directly; forced stale-plan tests rebuild and expose the correct nested schema.

---

### Task 6: Provider-neutral native structured tool calling

**Files:**
- Modify: `app/schemas/ai.py`
- Modify: `app/services/ai_service.py`
- Create: `app/services/agent_native_tool_call.py`
- Modify: `app/services/agent_context_manager.py`
- Modify: `app/services/agent_runtime_service.py`
- Modify: `app/core/config.py`
- Test: `tests/test_ai_service.py`
- Test: `tests/test_agent_native_tool_call.py`
- Test: `tests/test_agent_runtime.py`

**Interfaces:**
- Produces: `AIChatToolDefinition`, `AIChatToolCall`, `NativeToolCallAccumulator`, provider alias mapping, and native-to-`AgentToolRequest` normalization.
- Consumes: active plan allowed tools, tool aliases, and RuntimeSnapshot input schemas.

- [ ] **Step 1: Write failing transport and serialization tests**

```python
def test_native_arguments_preserve_html_nested_json_quotes_and_newlines():
    args = {"input": {"project_id": 1, "defect": {"content_html": '<pre>{"code": 90001}\n"quoted"</pre>'}}}
    call = accumulator.feed_fragments(json.dumps(args, ensure_ascii=False))
    self.assertEqual(call.arguments["input"]["defect"]["content_html"], args["input"]["defect"]["content_html"])
```

Cover arbitrary stream chunk boundaries, Unicode, backslashes, malformed arguments, unexpected parallel calls, alias reversal, and fenced fallback.

- [ ] **Step 2: Verify RED**

Expected: `AIChatRequest` has no tools and `AIService` discards `delta.tool_calls`.

- [ ] **Step 3: Extend AI schemas and request payloads**

```python
class AIChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[AIChatToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    reasoning_content: str | None = None

class AIChatRequest(BaseModel):
    tools: list[AIChatToolDefinition] = Field(default_factory=list)
    tool_choice: Literal["auto", "none"] | None = None
    parallel_tool_calls: bool = False
```

Add role-aware validation and serialize with `exclude_none=True`. Preserve reasoning content in provider envelopes without emitting or persisting raw chain-of-thought.

- [ ] **Step 4: Parse streamed native tool-call deltas**

`AIService._chat_stream_once()` yields bounded `tool_call_delta` events. `NativeToolCallAccumulator` concatenates name/argument fragments by index, rejects multiple calls, maps the provider alias to the canonical ToolSpec name, parses arguments with `json.loads`, and returns an `AgentToolRequest`.

- [ ] **Step 5: Build native tool definitions from the active plan**

Each function parameter schema is:

```json
{"type":"object","properties":{"input":TOOL_SPEC_INPUT_SCHEMA,"reason":{"type":"string"},"evidence_refs":{"type":"array","items":{"type":"object"}}},"required":["input"],"additionalProperties":false}
```

Set `parallel_tool_calls=false`. Do not send native tools during final-summary calls.

The runner honors `AGENT_NATIVE_TOOL_CALLING_ENABLED`. Existing fence-based tests patch it off; native-call tests inject provider stream events and never use the network.

- [ ] **Step 6: Normalize native and fenced requests into the same runtime path**

Native requests are parsed before `_parse_tool_request(content)`. Empty text with a valid native call is not treated as an empty model response. Fenced parsing remains unchanged as fallback.

- [ ] **Step 7: Run GREEN tests**

Run AI transport, native accumulator, runner native-call, fenced fallback, approval, and asynchronous execution tests. Expected: native HTML/nested JSON request reaches the same planned ToolCall input without fence repair.

---

### Task 7: Documentation, migration execution, and completion audit

**Files:**
- Modify: `docs/technical_architecture.md`
- Modify: `docs/development_technical_notes.md`
- Modify: `docs/api_agent_frontend_contract.md`
- Modify: `docs/api_ai.md`
- Modify: `docs/README.md`
- Modify: `docs/superpowers/plans/2026-07-12-agent-unified-capability-plan.md`

**Interfaces:**
- Consumes: verified behavior and event/schema names from Tasks 1-6.
- Produces: authoritative architecture, API, migration, and frontend diagnostics documentation.

- [ ] **Step 1: Update docs from verified implementation**

Document plan IDs, intent decisions, plan lineage, new events, additive API fields, native/fallback protocol, migration `0040`, frontend impact, and unchanged asynchronous/approval boundaries.

- [ ] **Step 2: Run focused suites**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_intent_decision
.\.venv\Scripts\python.exe -m unittest tests.test_agent_capability_plan
.\.venv\Scripts\python.exe -m unittest tests.test_agent_native_tool_call
.\.venv\Scripts\python.exe -m unittest tests.test_ai_service
.\.venv\Scripts\python.exe -m unittest tests.test_agent_platform_tools
```

Expected: all PASS.

- [ ] **Step 3: Run Agent regression suite**

Run: `\.venv\Scripts\python.exe -m unittest tests.test_agent_runtime`

Expected: PASS with no network calls.

- [ ] **Step 4: Run full backend discovery and migration checks**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\alembic.exe heads
.\.venv\Scripts\alembic.exe upgrade head
git diff --check
```

Expected: all tests PASS, one migration head, migration succeeds, and no whitespace errors.

- [ ] **Step 5: Audit every success criterion**

Record evidence for structured LLM intent, per-run active plan, shared plan ID, route rebuild, refreshed schemas, out-of-plan rejection/expansion, native serialization, paraphrase matrix, and unchanged async/approval behavior. Do not mark complete if any evidence is missing.
