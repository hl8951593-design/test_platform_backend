# Agent Skill–Tool Capability Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow valid LLM-selected registered Tools to proceed when selected Skill metadata is incomplete, while preserving fail-closed runtime safety and adding deterministic Skill–Tool alignment diagnostics.

**Architecture:** `AgentPlanningDecisionService` will derive a frozen, non-authoritative Tool–Skill alignment projection instead of rejecting selected Tools that are not declared by selected Skills. Skill declarations remain planning and audit metadata; ToolRegistry, permission, side-effect, schema, approval, object-reference, project-isolation, replay, and worker checks remain execution authorities. Runtime snapshots validate declared Tool names, and planner events expose bounded decision summaries for failed planning attempts.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy, unittest, Markdown contracts.

## Global Constraints

- Preserve existing REST, SSE event types, ToolCall, Approval, WorkerQueue, lease, resume, replay, and reconcile behavior.
- Do not add a database migration.
- Do not add intent keywords or hard-code an assertion-repair Tool sequence.
- Do not weaken unknown Tool, permission, side-effect, schema, object-reference, project-isolation, or approval checks.
- Compute alignment only from the Run's frozen Skill and Tool indexes.
- Preserve unrelated System Test Case working-tree changes.
- Follow RED-GREEN-REFACTOR for every production behavior change.

---

### Task 1: Replace Fatal Skill–Tool Coupling with Alignment Projection

**Files:**
- Modify: `tests/test_agent_planning_service.py`
- Modify: `app/services/agent_planning_service.py`

**Interfaces:**
- Consumes: `AgentPlanningDecision`, frozen `skill_index`, validated selected Skill and Tool names.
- Produces: `AgentToolSkillAlignment`, `derive_tool_skill_alignment(*, selected_skills, selected_tools, skill_index)`, and additive `ValidatedAgentPlanningDecision.alignment` / `model_view()["tool_skill_alignment"]`.

- [ ] **Step 1: Write failing planner alignment tests**

Add tests equivalent to:

```python
def test_registered_tools_do_not_fail_when_selected_skill_does_not_declare_them(self):
    skill_index = [
        {
            "name": "assertion-extractor-binding",
            "owns": ["assertion"],
            "consumes": ["test_case", "execution"],
            "produces": ["assertion"],
            "tool_names": [],
        },
        {
            "name": "http-test-case-design",
            "owns": ["test_case"],
            "consumes": ["execution"],
            "produces": ["test_case"],
            "tool_names": [
                "testcase.update_assertions",
                "testcase.batch_update_assertions",
            ],
        },
    ]
    tool_index = [
        {
            "name": name,
            "side_effect_class": "business_update",
            "required_permissions": ["case:manage"],
        }
        for name in (
            "testcase.update_assertions",
            "testcase.batch_update_assertions",
        )
    ]
    decision = AgentPlanningDecisionService(ai_service=FakeAIService(response(planning_json(
        goal="Repair saved assertions.",
        action="repair",
        target_domain="assertion",
        source_domains=["test_case", "execution"],
        selected_skills=["assertion-extractor-binding"],
        selected_tools=[item["name"] for item in tool_index],
        selected_artifact_ids=[],
        required_facts=["saved_case_assertions"],
        requested_effect_scope="persist",
    )))).decide(
        intent="修复断言",
        conversation_context=None,
        skill_index=skill_index,
        tool_index=tool_index,
        artifact_index=[],
        project_id=1,
        permissions=("case:manage",),
    )
    assert decision.selected_tools == (
        "testcase.update_assertions",
        "testcase.batch_update_assertions",
    )
    assert decision.alignment.aligned_tools == ()
    assert decision.alignment.supporting_skill_candidates_by_tool == {
        "testcase.batch_update_assertions": ("http-test-case-design",),
        "testcase.update_assertions": ("http-test-case-design",),
    }
    assert decision.alignment.unbound_tools == ()


def test_alignment_is_deterministic_and_reports_globally_unbound_registered_tools(self):
    skill_index = [
        {
            "name": "assertion-extractor-binding",
            "tool_names": [],
        },
        {
            "name": "http-test-case-design",
            "tool_names": ["testcase.update_assertions"],
        },
    ]
    alignment = derive_tool_skill_alignment(
        selected_skills=("assertion-extractor-binding",),
        selected_tools=("future.repair", "testcase.update_assertions"),
        skill_index=skill_index,
    )
    assert alignment.model_view() == {
        "selected_skill_declared_tools": [],
        "aligned_tools": [],
        "supporting_skill_candidates_by_tool": {
            "testcase.update_assertions": ["http-test-case-design"],
        },
        "unbound_tools": ["future.repair"],
    }
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_planning_service.AgentPlanningDecisionServiceTests.test_registered_tools_do_not_fail_when_selected_skill_does_not_declare_them tests.test_agent_planning_service.AgentPlanningDecisionServiceTests.test_alignment_is_deterministic_and_reports_globally_unbound_registered_tools
```

Expected: FAIL because `AgentToolSkillAlignment` does not exist and the current validator raises `planner_tool_not_declared_by_skill`.

- [ ] **Step 3: Implement the minimal alignment value and derivation**

Add:

```python
@dataclass(frozen=True)
class AgentToolSkillAlignment:
    selected_skill_declared_tools: tuple[str, ...] = ()
    aligned_tools: tuple[str, ...] = ()
    supporting_skill_candidates_by_tool: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unbound_tools: tuple[str, ...] = ()

    def model_view(self) -> dict[str, Any]:
        return {
            "selected_skill_declared_tools": list(self.selected_skill_declared_tools),
            "aligned_tools": list(self.aligned_tools),
            "supporting_skill_candidates_by_tool": {
                tool_name: list(skill_names)
                for tool_name, skill_names in self.supporting_skill_candidates_by_tool.items()
            },
            "unbound_tools": list(self.unbound_tools),
        }


def derive_tool_skill_alignment(*, selected_skills, selected_tools, skill_index):
    skills = _index_by(skill_index, "name")
    selected_skill_set = set(selected_skills)
    declared_by_skill = {
        name: set(_strings(item.get("tool_names") or item.get("tools")))
        for name, item in skills.items()
    }
    selected_declared = set().union(
        *(declared_by_skill.get(name, set()) for name in selected_skill_set)
    ) if selected_skill_set else set()
    aligned = sorted(set(selected_tools) & selected_declared)
    candidates = {}
    unbound = []
    for tool_name in sorted(set(selected_tools) - selected_declared):
        owners = tuple(sorted(
            name for name, declared in declared_by_skill.items()
            if tool_name in declared
        ))
        if owners:
            candidates[tool_name] = owners
        else:
            unbound.append(tool_name)
    return AgentToolSkillAlignment(
        selected_skill_declared_tools=tuple(sorted(selected_declared)),
        aligned_tools=tuple(aligned),
        supporting_skill_candidates_by_tool=candidates,
        unbound_tools=tuple(unbound),
    )
```

Import `field` from `dataclasses`, add `alignment` with a default factory to `ValidatedAgentPlanningDecision`, expose it in `model_view()`, remove the fatal undeclared-Tool branch, and derive alignment after unknown-reference validation.

- [ ] **Step 4: Run focused and existing planner tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_planning_service
```

Expected: PASS; unknown Tool, permission, effect, domain, confidence, and repair tests remain green.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- app/services/agent_planning_service.py tests/test_agent_planning_service.py
git commit -m "fix: align agent skills and tools without blocking planning"
```

---

### Task 2: Preserve Failed Planning Decision Context

**Files:**
- Modify: `tests/test_agent_planning_service.py`
- Modify: `app/services/agent_planning_service.py`

**Interfaces:**
- Consumes: parsed `AgentPlanningDecision` and `AgentPlanningError`.
- Produces: `_planning_decision_summary(decision: AgentPlanningDecision | None) -> dict[str, Any]` and additive bounded payload fields for `invalid` events and the second repair request.

- [ ] **Step 1: Write failing observability tests**

Add a first invalid decision with a domain mismatch followed by a valid decision. Assert:

```python
invalid_payload = events[0][1]
assert invalid_payload["code"] == "planner_target_domain_incompatible"
assert invalid_payload["selected_skills"] == ["scenario-composition"]
assert invalid_payload["selected_tools"] == ["scenario.compose_draft"]
assert invalid_payload["selected_artifact_id_count"] == 1
assert invalid_payload["target_domain"] == "defect"
assert invalid_payload["source_domains"] == ["test_case", "environment"]

repair_payload = json.loads(ai_service.requests[1].messages[-1].content)
assert repair_payload["validation_error"]["selected_skills"] == ["scenario-composition"]
assert "artifact_index" in repair_payload
assert "selected_artifact_ids" not in json.dumps(repair_payload["validation_error"])
```

- [ ] **Step 2: Run the observability test and verify RED**

Expected: FAIL because invalid events currently contain only the validation error.

- [ ] **Step 3: Implement bounded decision summaries**

Add:

```python
def _planning_decision_summary(decision: AgentPlanningDecision | None) -> dict[str, Any]:
    if decision is None:
        return {}
    return {
        "selected_skills": list(_unique_non_empty(decision.selected_skills)),
        "selected_tools": list(_unique_non_empty(decision.selected_tools)),
        "selected_artifact_id_count": len(_unique_non_empty(decision.selected_artifact_ids)),
        "target_domain": decision.target_domain,
        "source_domains": list(_unique_non_empty(decision.source_domains)),
    }
```

In `decide()`, keep the parsed decision for the current attempt and merge this summary into the `AgentPlanningError.model_view()` passed to `on_event` and the next repair request. Do not include full artifacts, prompts, Tool inputs, provider reasoning, or chain-of-thought.

- [ ] **Step 4: Run the planner suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_planning_service
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add -- app/services/agent_planning_service.py tests/test_agent_planning_service.py
git commit -m "feat: expose bounded agent planning failure context"
```

---

### Task 3: Correct Assertion Skill Metadata and Validate Declared Tools

**Files:**
- Modify: `app/agent_skills/assertion-extractor-binding/SKILL.md`
- Modify: `app/services/agent_skill_registry.py`
- Modify: `app/services/agent_runtime_service.py`
- Modify: `tests/test_agent_runtime.py`

**Interfaces:**
- Consumes: `AgentSkill.tool_names`, `ToolRegistry.list_specs()`.
- Produces: `AgentSkillRegistry.validate_tool_declarations(registered_tool_names: Iterable[str]) -> None` and snapshot-creation fail-fast validation.

- [ ] **Step 1: Write failing Skill metadata and registry tests**

Add tests asserting:

```python
registry = AgentSkillRegistry()
skill = registry.get_skill("assertion-extractor-binding")
assert set(skill.tool_names) == {
    "testcase.query_project_cases",
    "testcase.update_assertions",
    "testcase.batch_update_assertions",
    "websocket_testcase.update_assertions",
    "websocket_testcase.batch_update_assertions",
}
assert "ai_skill.run_draft" not in skill.tool_names

with self.assertRaisesRegex(RuntimeError, "unknown Tool declarations"):
    custom_registry.validate_tool_declarations({"project.read_context"})
```

Also assert `AgentRuntimeService._get_or_create_snapshot()` invokes validation before persisting a new snapshot by patching `AgentSkillRegistry.validate_tool_declarations` and checking the registered Tool-name set.

- [ ] **Step 2: Run tests and verify RED**

Expected: FAIL because the assertion Skill has no Tool declarations and the validation API does not exist.

- [ ] **Step 3: Add Skill Tool declarations**

Add this frontmatter after `produces`:

```yaml
tools:
  - testcase.query_project_cases
  - testcase.update_assertions
  - testcase.batch_update_assertions
  - websocket_testcase.update_assertions
  - websocket_testcase.batch_update_assertions
```

- [ ] **Step 4: Implement registry declaration validation**

Add to `AgentSkillRegistry`:

```python
def validate_tool_declarations(self, registered_tool_names: Iterable[str]) -> None:
    registered = {str(name).strip() for name in registered_tool_names if str(name).strip()}
    unknown = {
        skill.name: sorted(set(skill.tool_names) - registered)
        for skill in self.list_skills()
        if set(skill.tool_names) - registered
    }
    if unknown:
        raise RuntimeError(f"Agent Skill unknown Tool declarations: {unknown}")
```

Import `Iterable` from `collections.abc`. In `_get_or_create_snapshot`, instantiate one `AgentSkillRegistry`, validate it against `{spec.name for spec in self.tool_registry.list_specs()}`, and build `skill_manifests` from that same validated instance.

- [ ] **Step 5: Run focused registry, snapshot, and runtime tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_runtime.AgentRuntimeTests.test_agent_skill_registry_selects_relevant_skills_by_intent tests.test_agent_runtime.AgentRuntimeTests.test_saved_case_assertion_followup_skill_routes_to_assertion_patch_tools tests.test_agent_runtime.AgentRuntimeTests.test_harness_runtime_snapshot_payload_contract_matches_route
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```powershell
git add -- app/agent_skills/assertion-extractor-binding/SKILL.md app/services/agent_skill_registry.py app/services/agent_runtime_service.py tests/test_agent_runtime.py
git commit -m "fix: validate agent skill tool declarations"
```

---

### Task 4: Prove the Multi-turn Assertion Repair Boundary and Sync Contracts

**Files:**
- Modify: `tests/test_agent_runtime.py`
- Modify: `tests/test_agent_capability_plan.py`
- Modify: `docs/technical_architecture.md`
- Modify: `docs/api_agent_frontend_contract.md`
- Modify: `docs/development_technical_notes.md`
- Modify: `docs/README.md` only if its authority/version ledger requires this architecture entry; preserve existing unrelated edits by applying a narrow hunk.

**Interfaces:**
- Consumes: validated planning alignment metadata, existing Capability Plan persistence, ToolCall/Approval lifecycle.
- Produces: regression proving the latest Run does not fail during planning and that assertion writes remain approval-gated.

- [ ] **Step 1: Write the failing runtime regression**

Create a fake planning provider that returns:

```python
{
    "goal": "Repair assertions proven wrong by the previous failure analysis.",
    "action": "repair",
    "target_domain": "assertion",
    "source_domains": ["test_case", "execution"],
    "selected_skills": ["assertion-extractor-binding"],
    "selected_tools": [
        "testcase.query_project_cases",
        "testcase.update_assertions",
        "testcase.batch_update_assertions",
    ],
    "selected_artifact_ids": [],
    "required_facts": ["saved_case_assertions", "latest_execution_failure"],
    "requested_effect_scope": "persist",
    "confidence": 0.98,
    "reason_summary": "Use explicit case facts and approval-gated assertion patches.",
}
```

Run `AgentConversationRunner` with a model ToolCall for `testcase.update_assertions` using a fresh case object reference. Assert:

- Run status becomes `needs_human`, not `failed`;
- `run.error_code != "agent_planning_failed"`;
- Capability Plan contains `tool_skill_alignment`;
- ToolCall is `planned` and `approval_required=True`;
- Approval is `pending`;
- saved assertions remain unchanged before approval;
- no WorkerQueue row exists before approval.

- [ ] **Step 2: Run the regression and verify RED or pre-fix failure**

Expected before Tasks 1–3: `agent_planning_failed`; after Tasks 1–3 the newly added integration assertions should pass.

- [ ] **Step 3: Add Capability Plan persistence assertions**

Extend the existing unified LLM planning persistence test so `plan.intent_decision_json["tool_skill_alignment"]` exactly matches the validated decision's alignment view.

- [ ] **Step 4: Run focused Agent regression suites**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_planning_service tests.test_agent_capability_plan tests.test_agent_runtime
```

Expected: PASS.

- [ ] **Step 5: Update architecture and frontend event contracts**

Document:

- Skill Tool declarations are planning evidence, not authorization;
- registered selected Tools are no longer rejected only for selected-Skill declaration mismatch;
- `tool_skill_alignment` fields and their non-authoritative semantics;
- additive bounded fields on `planner.llm_decision_invalid`;
- unchanged ToolRuntime, Approval, asynchronous worker, and public API safety boundaries;
- the 2026-07-13 implementation entry in the development ledger.

- [ ] **Step 6: Run contract and full verification**

Run focused architecture/document tests discovered by:

```powershell
Select-String -Path tests\test_agent_runtime.py -Pattern 'technical_architecture|api_agent_frontend_contract|development_technical_notes'
```

Then run:

```powershell
.\.venv\Scripts\python.exe -m unittest
```

Expected: all tests PASS; existing documented skips remain unchanged.

- [ ] **Step 7: Commit Task 4**

```powershell
git add -- tests/test_agent_runtime.py tests/test_agent_capability_plan.py docs/technical_architecture.md docs/api_agent_frontend_contract.md docs/development_technical_notes.md
git commit -m "test: cover agent assertion repair capability alignment"
```

Do not stage `docs/README.md` unless the narrow documentation hunk is required and can be isolated from the user's existing System Test Case edits.
