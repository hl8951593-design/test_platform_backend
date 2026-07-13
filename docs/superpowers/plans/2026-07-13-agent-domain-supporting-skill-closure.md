# Agent Domain Supporting Skill Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent valid composite LLM plans from failing when the target domain is owned by an omitted supporting Skill, while preserving the model's original selection and every existing runtime safety boundary.

**Architecture:** Derive a deterministic `AgentSkillDomainAlignment` from the Run's frozen Skill index. Preserve `model_selected_skills`, append at most one target-domain owner/producer as an effective supporting Skill, and make unmatched target/source domains diagnostic rather than fatal. The closure may add Skill context only; it cannot add Tools, alter effect scope, grant permission, or execute business actions.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy, unittest, Markdown contracts.

## Global Constraints

- The LLM remains the source of goal, action, target/source domains, Tools, artifacts, facts, and requested effect scope.
- Auto-closure may append at most one registered frozen Skill for the target domain.
- Auto-closure must never add or remove a Tool.
- Unknown Skill/Tool/artifact references, confidence, permission, side-effect, Capability Plan, schema, object-reference, project-isolation, Approval, replay, lease, and WorkerQueue checks remain fail-closed.
- Existing REST routes, SSE event types, ToolCall lifecycle, Approval, and asynchronous worker behavior remain compatible.
- No database migration.
- Preserve unrelated System Test Case working-tree changes.
- Follow RED-GREEN-REFACTOR for every production behavior change.

---

### Task 1: Derive Deterministic Domain Alignment and Effective Skills

**Files:**
- Modify: `tests/test_agent_planning_service.py`
- Modify: `app/services/agent_planning_service.py`

**Interfaces:**
- Consumes: frozen `skill_index`, model-selected Skills/Tools, `target_domain`, and `source_domains`.
- Produces: `AgentSkillDomainAlignment`, `derive_skill_domain_alignment(*, model_selected_skills, selected_tools, target_domain, source_domains, skill_index)`, additive `ValidatedAgentPlanningDecision.model_selected_skills`, and effective `selected_skills`.

- [ ] **Step 1: Write the failing latest-Run regression**

Add a test using the observed decision shape:

```python
def test_target_domain_owner_is_added_as_supporting_skill(self):
    skill_index = [
        {
            "name": "assertion-extractor-binding",
            "owns": ["assertion"],
            "consumes": ["test_case", "execution"],
            "produces": ["assertion"],
            "tool_names": [
                "testcase.query_project_cases",
                "testcase.update_assertions",
                "testcase.batch_update_assertions",
            ],
        },
        {
            "name": "execution-diagnosis",
            "owns": ["execution"],
            "consumes": ["test_case"],
            "produces": ["execution", "diagnosis"],
            "tool_names": [
                "execution.query_records",
                "execution.read_detail",
                "execution.diagnose",
            ],
        },
        {
            "name": "http-test-case-design",
            "owns": ["test_case"],
            "consumes": ["execution"],
            "produces": ["test_case"],
            "tool_names": [
                "testcase.query_project_cases",
                "testcase.update_assertions",
                "testcase.batch_update_assertions",
                "testcase.execute_saved",
                "testcase.batch_execute",
            ],
        },
    ]
    decision = AgentPlanningDecisionService(ai_service=FakeAIService(
        response(latest_composite_planning_json()),
    )).decide(
        intent="先分析失败测试用例，分析后，修改断言重新执行",
        conversation_context=None,
        skill_index=skill_index,
        tool_index=latest_composite_tool_index(),
        artifact_index=[],
        project_id=1,
        permissions=("case:view", "case:manage", "test:execute"),
    )
    assert decision.model_selected_skills == (
        "assertion-extractor-binding",
        "execution-diagnosis",
    )
    assert decision.selected_skills == (
        "assertion-extractor-binding",
        "execution-diagnosis",
        "http-test-case-design",
    )
    assert decision.domain_alignment.auto_added_supporting_skills == (
        "http-test-case-design",
    )
    assert decision.domain_alignment.target_aligned is True
```

Define `latest_composite_planning_json()` and `latest_composite_tool_index()` in the test module with the eight observed Tool names and registered side-effect/permission metadata.

- [ ] **Step 2: Run the exact test and verify RED**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_planning_service.AgentPlanningDecisionServiceTests.test_target_domain_owner_is_added_as_supporting_skill
```

Expected: FAIL with `planner_target_domain_incompatible`.

- [ ] **Step 3: Write failing deterministic and non-fatal domain tests**

Add tests proving:

```python
alignment = derive_skill_domain_alignment(
    model_selected_skills=("assertion-extractor-binding",),
    selected_tools=("testcase.update_assertions",),
    target_domain="test_case",
    source_domains=("execution", "unknown_source"),
    skill_index=skill_index,
)
assert alignment.target_skill_candidates[0] == "http-test-case-design"
assert alignment.auto_added_supporting_skills == ("http-test-case-design",)
assert alignment.aligned_source_domains == ("execution",)
assert alignment.unbound_source_domains == ("unknown_source",)
```

Add an owner-versus-producer fixture where both candidates declare the same selected Tool; assert the owner is selected. Add an unbound target fixture; assert `target_aligned=False` without raising a planning error.

- [ ] **Step 4: Implement `AgentSkillDomainAlignment` and closure**

Add:

```python
@dataclass(frozen=True)
class AgentSkillDomainAlignment:
    model_selected_skills: tuple[str, ...] = ()
    effective_selected_skills: tuple[str, ...] = ()
    auto_added_supporting_skills: tuple[str, ...] = ()
    target_domain: str | None = None
    target_aligned: bool = True
    target_skill_candidates: tuple[str, ...] = ()
    aligned_source_domains: tuple[str, ...] = ()
    source_skill_candidates_by_domain: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unbound_source_domains: tuple[str, ...] = ()

    def model_view(self) -> dict[str, Any]:
        return {
            "model_selected_skills": list(self.model_selected_skills),
            "effective_selected_skills": list(self.effective_selected_skills),
            "auto_added_supporting_skills": list(self.auto_added_supporting_skills),
            "target_domain": self.target_domain,
            "target_aligned": self.target_aligned,
            "target_skill_candidates": list(self.target_skill_candidates),
            "aligned_source_domains": list(self.aligned_source_domains),
            "source_skill_candidates_by_domain": {
                domain: list(candidates)
                for domain, candidates in self.source_skill_candidates_by_domain.items()
            },
            "unbound_source_domains": list(self.unbound_source_domains),
        }
```

Implement candidate ordering with this exact key:

```python
(
    0 if target_domain in owns else 1,
    0 if target_domain in produces else 1,
    -len(selected_tool_set & declared_tools),
    -len(source_domain_set & (owns | consumes)),
    skill_name,
)
```

Append only the first target candidate when the model-selected Skills do not already own/produce the target. Recompute target/source alignment over the effective Skills. Remove the fatal target/source-domain branches. Derive Tool alignment from effective Skills.

Add `model_selected_skills` and `domain_alignment` defaults to `ValidatedAgentPlanningDecision`; `model_view()` must expose `model_selected_skills` and `skill_domain_alignment` while preserving existing fields.

- [ ] **Step 5: Run the complete planner suite**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_planning_service
```

Expected: PASS. Update the bounded invalid-decision test to use `planner_confidence_too_low` instead of a domain mismatch, preserving its selected Skill/Tool summary assertions.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- app/services/agent_planning_service.py tests/test_agent_planning_service.py
git commit -m "fix: close agent target domains with supporting skills"
```

---

### Task 2: Propagate Effective Skills into Context and Capability Plan

**Files:**
- Modify: `tests/test_agent_capability_plan.py`
- Modify: `tests/test_agent_runtime.py`
- Modify: `app/services/agent_context_manager.py` only if tests show it does not already consume effective `selected_skills`.

**Interfaces:**
- Consumes: `ValidatedAgentPlanningDecision.selected_skills`, `model_selected_skills`, and `domain_alignment`.
- Produces: Capability Plan `intent_decision_json` with both model/effective Skill facts and `skill_plan_json` whose primary/supporting Skills match the actual model context.

- [ ] **Step 1: Write failing context and persistence tests**

Add a planning decision whose model Skills are assertion/execution and whose effective Skills append HTTP case design. Assert:

```python
context_plan = self.context_manager.route_planning_decision(
    "先分析失败测试用例，分析后，修改断言重新执行",
    decision=decision,
)
assert context_plan.primary_skill == "assertion-extractor-binding"
assert context_plan.supporting_skills == (
    "execution-diagnosis",
    "http-test-case-design",
)
assert [skill.name for skill in context_plan.selected_skills] == list(
    decision.selected_skills
)
```

Extend the unified planning persistence test to assert:

```python
assert plan.intent_decision_json["model_selected_skills"] == [
    "assertion-extractor-binding",
    "execution-diagnosis",
]
assert plan.intent_decision_json["selected_skills"][-1] == "http-test-case-design"
assert plan.skill_plan_json["supporting_skills"][-1] == "http-test-case-design"
assert plan.intent_decision_json["skill_domain_alignment"]["target_aligned"] is True
```

- [ ] **Step 2: Run focused tests and verify RED if propagation is incomplete**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_capability_plan.AgentCapabilityPlanTests.test_runner_persists_unified_llm_planning_decision_without_keyword_reroute tests.test_agent_runtime.AgentRuntimeTests.test_assertion_repair_planning_reaches_approval_with_skill_tool_alignment
```

Expected: FAIL until the fixtures and persisted alignment reflect model/effective Skill separation.

- [ ] **Step 3: Implement the minimal propagation adjustment**

Keep `AgentContextManager.route_planning_decision()` reading effective `decision.selected_skills`. If no production adjustment is required, update only the test fixtures and persistence assertions; do not add duplicate routing logic.

- [ ] **Step 4: Run Capability Plan and AgentRuntime suites**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_capability_plan tests.test_agent_runtime
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add -- tests/test_agent_capability_plan.py tests/test_agent_runtime.py app/services/agent_context_manager.py
git commit -m "test: cover effective agent supporting skill context"
```

Do not stage `app/services/agent_context_manager.py` if it requires no change.

---

### Task 3: Sync Contracts and Verify the Latest Composite Intent

**Files:**
- Modify: `docs/technical_architecture.md`
- Modify: `docs/api_agent_frontend_contract.md`
- Modify: `docs/development_technical_notes.md`
- Modify: `tests/test_agent_runtime.py` with the exact latest decision regression.

**Interfaces:**
- Consumes: domain closure and effective Skill audit metadata.
- Produces: documented additive event/Capability Plan fields and verified latest composite planning behavior.

- [ ] **Step 1: Add the exact latest decision regression**

Use intent `先分析失败测试用例，分析后，修改断言重新执行`, target `test_case`, model Skills assertion/execution, and the eight observed Tools. Assert the Runner creates a Capability Plan instead of `agent_planning_failed`, the effective Skill catalog contains `http-test-case-design`, and no business update executes without Approval.

- [ ] **Step 2: Run the exact regression**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_runtime.AgentRuntimeTests.test_latest_composite_assertion_repair_adds_test_case_supporting_skill
```

Expected: PASS after Tasks 1–2.

- [ ] **Step 3: Update architecture and frontend contracts**

Document `model_selected_skills`, effective `selected_skills`, `skill_domain_alignment`, deterministic target candidate ordering, source-domain diagnostics, and the invariant that closure never adds Tools or bypasses existing runtime safety.

- [ ] **Step 4: Run focused and full verification**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_planning_service tests.test_agent_capability_plan tests.test_agent_runtime
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Expected: all tests PASS with existing documented skips only.

- [ ] **Step 5: Run a read-only live planning acceptance**

Use the latest failed Run's frozen Skill/Tool/artifact indexes and the real planning provider to request the same composite intent. Do not execute ToolCalls. Validate the returned decision locally and assert a Capability Plan-compatible result with no `planner_target_domain_incompatible`; record the model/effective Skill lists and target alignment.

- [ ] **Step 6: Commit Task 3**

```powershell
git add -- tests/test_agent_runtime.py docs/technical_architecture.md docs/api_agent_frontend_contract.md docs/development_technical_notes.md
git commit -m "docs: document agent domain supporting skill closure"
```
