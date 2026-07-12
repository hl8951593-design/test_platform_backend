# Agent Skill Orchestration v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Agent skill/tool selection LLM-oriented by retrieving candidate skills/tools from explicit user goals and evidence artifacts instead of letting historical artifact actions collapse the run into one wrong skill.

**Architecture:** Add a small `AgentIntentAction` layer that identifies the user's current target action and evidence domains. Use it inside the existing `AgentSkillPlanner`, `AgentContextManager`, and `AgentCapabilityResolver` so explicit target-domain skills win, evidence-domain read tools remain available, and ToolRuntime continues to enforce permissions, approvals, schema, and object-reference guards.

**Tech Stack:** FastAPI backend, SQLAlchemy models, existing Agent runtime services, Python `unittest`, current ToolRegistry/SkillRegistry.

## Global Constraints

- Do not remove or rename existing ToolSpec names.
- Do not weaken permission, approval, schema preflight, object-reference freshness, project isolation, replay policy, or asynchronous execution semantics.
- Keep current frontend-facing capabilities and run contracts compatible.
- Preserve dirty worktree changes owned by the user; edit only files listed in each task unless a failing test proves a direct dependency.
- Follow TDD: each behavior change starts with a failing test and the failure must be observed before production code is changed.

---

## File Structure

- Create: `app/services/agent_intent_action.py`
  Defines `AgentIntentAction` and deterministic intent/action/domain parsing. This file owns the shared vocabulary used by planner and resolver.

- Modify: `app/services/agent_skill_planner.py`
  Uses `AgentIntentAction` to keep explicit target-domain skills above incompatible artifact actions and to classify artifact actions as evidence when appropriate.

- Modify: `app/services/agent_capability_resolver.py`
  Uses `AgentIntentAction` to include target-domain tools plus evidence-domain read tools.

- Modify: `app/services/agent_context_manager.py`
  Adds first-class task-type mappings for platform skills and carries widened selected skills through the current context plan.

- Modify: `app/services/agent_runtime_service.py`
  Adds a minimal capability-denial guard or route-mismatch observation hook if a final answer claims an available platform action is unsupported.

- Modify: `tests/test_agent_runtime.py`
  Adds cross-domain routing regression tests around the existing Agent runtime test area.

- Modify: `docs/api_agent_frontend_contract.md`, `docs/technical_architecture.md`, `docs/development_technical_notes.md`
  Records the v2 routing semantics after tests pass.

---

### Task 1: Add IntentAction parsing without changing runtime behavior

**Files:**
- Create: `app/services/agent_intent_action.py`
- Modify: `tests/test_agent_runtime.py`

**Interfaces:**
- Produces:
  - `AgentIntentAction`
  - `parse_agent_intent_action(intent: str, *, working_context: dict[str, Any] | None = None) -> AgentIntentAction`
- Consumes: no production callers yet in this task.

- [x] **Step 1: Write failing tests for action/domain parsing**

Add tests near existing `AgentContextManager`/`AgentSkillPlanner` tests in `tests/test_agent_runtime.py`:

```python
def test_agent_intent_action_parses_defect_creation_from_failed_cases(self):
    from app.services.agent_intent_action import parse_agent_intent_action

    action = parse_agent_intent_action("你可以根据失败用例创建对应的缺陷")

    self.assertEqual(action.action, "create")
    self.assertEqual(action.target_domain, "defect")
    self.assertIn("test_case", action.source_domains)
    self.assertTrue(action.explicit)
    self.assertFalse(action.is_deictic_followup)


def test_agent_intent_action_parses_report_to_plan_cross_domain(self):
    from app.services.agent_intent_action import parse_agent_intent_action

    action = parse_agent_intent_action("根据这份报告生成测试计划")

    self.assertEqual(action.action, "create")
    self.assertEqual(action.target_domain, "test_plan")
    self.assertIn("report", action.source_domains)
    self.assertTrue(action.explicit)
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_agent_runtime.AgentRuntimeTests.test_agent_intent_action_parses_defect_creation_from_failed_cases tests.test_agent_runtime.AgentRuntimeTests.test_agent_intent_action_parses_report_to_plan_cross_domain
```

Expected: FAIL or ERROR because `app.services.agent_intent_action` does not exist.

- [x] **Step 3: Implement the minimal parser**

Create `app/services/agent_intent_action.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentIntentAction:
    action: str | None
    target_domain: str | None
    source_domains: tuple[str, ...] = ()
    explicit: bool = False
    is_deictic_followup: bool = False
    reason_codes: tuple[str, ...] = ()


CREATE_TERMS = ("创建", "生成", "新建", "create", "generate")
EXECUTE_TERMS = ("执行", "运行", "run", "execute")
UPDATE_TERMS = ("更新", "修改", "修复", "保存", "update", "fix", "save")
ANALYZE_TERMS = ("分析", "诊断", "总结", "analyze", "diagnose", "summary")
DEICTIC_TERMS = ("它", "这个", "这些", "刚才", "上面", "those", "it", "that")

DOMAIN_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("defect", ("缺陷", "bug", "Bug", "问题单", "工单")),
    ("test_plan", ("测试计划", "计划", "plan")),
    ("visual_flow", ("可视化流程", "流程", "flow")),
    ("scenario", ("场景", "scenario")),
    ("test_case", ("测试用例", "用例", "case", "接口")),
    ("execution", ("执行记录", "执行失败", "运行记录", "execution")),
    ("report", ("报告", "报表", "report")),
    ("media", ("截图", "附件", "图片", "media", "image")),
)


def parse_agent_intent_action(
    intent: str,
    *,
    working_context: dict[str, Any] | None = None,
) -> AgentIntentAction:
    lowered = (intent or "").casefold()
    reason_codes: list[str] = []
    is_deictic = any(term.casefold() in lowered for term in DEICTIC_TERMS)
    if is_deictic:
        reason_codes.append("intent:deictic_followup")

    action = _first_action(lowered, reason_codes)
    mentioned_domains = _mentioned_domains(lowered)
    target_domain = _target_domain_for_action(action, mentioned_domains)
    source_domains = tuple(domain for domain in mentioned_domains if domain != target_domain)
    explicit = bool(action or target_domain)
    if target_domain:
        reason_codes.append(f"intent:target_domain:{target_domain}")
    for domain in source_domains:
        reason_codes.append(f"intent:source_domain:{domain}")

    return AgentIntentAction(
        action=action,
        target_domain=target_domain,
        source_domains=source_domains,
        explicit=explicit,
        is_deictic_followup=is_deictic,
        reason_codes=tuple(reason_codes),
    )


def _first_action(lowered: str, reason_codes: list[str]) -> str | None:
    if any(term.casefold() in lowered for term in CREATE_TERMS):
        reason_codes.append("intent:action:create")
        return "create"
    if any(term.casefold() in lowered for term in EXECUTE_TERMS):
        reason_codes.append("intent:action:execute")
        return "execute"
    if any(term.casefold() in lowered for term in UPDATE_TERMS):
        reason_codes.append("intent:action:update")
        return "update"
    if any(term.casefold() in lowered for term in ANALYZE_TERMS):
        reason_codes.append("intent:action:analyze")
        return "analyze"
    return None


def _mentioned_domains(lowered: str) -> tuple[str, ...]:
    domains: list[str] = []
    for domain, terms in DOMAIN_TERMS:
        if any(term.casefold() in lowered for term in terms):
            domains.append(domain)
    return tuple(dict.fromkeys(domains))


def _target_domain_for_action(action: str | None, mentioned_domains: tuple[str, ...]) -> str | None:
    if not mentioned_domains:
        return None
    if action == "create":
        for preferred in ("defect", "test_plan", "visual_flow", "scenario", "test_case"):
            if preferred in mentioned_domains:
                return preferred
    return mentioned_domains[0]
```

- [x] **Step 4: Run tests to verify they pass**

Run the same command. Expected: both tests PASS.

---

### Task 2: Stop incompatible artifact actions from stealing explicit target-domain routing

**Files:**
- Modify: `app/services/agent_skill_planner.py`
- Modify: `tests/test_agent_runtime.py`

**Interfaces:**
- Consumes: `parse_agent_intent_action`
- Produces: planner behavior where explicit `target_domain=defect` outranks `test_case_query_snapshot.update_assertions`.

- [x] **Step 1: Write failing cross-domain planner test**

Add:

```python
def test_skill_planner_treats_failed_cases_as_evidence_for_defect_creation(self):
    from app.services.agent_skill_planner import AgentSkillPlanner

    working_context = {
        "active_artifact_handles": [
            {
                "artifact_type": "test_case_query_snapshot",
                "artifact_class": "AUTHORITATIVE",
                "artifact_trust": "SOURCE",
                "domain": "test_case",
                "available_followup_actions": [
                    "analyze_cases",
                    "update_assertions",
                    "execute",
                ],
                "artifact_summary": {"project_id": 1, "http_total": 15},
            }
        ]
    }

    plan = AgentSkillPlanner().plan(
        "你可以根据失败用例创建对应的缺陷",
        working_context=working_context,
    )

    self.assertEqual(plan.primary_skill, "defect-triage")
    self.assertIn("defect-triage", plan.allowed_skills)
    self.assertNotEqual(plan.primary_skill, "http-test-case-design")
    self.assertIn("planner:intent_defect_triage", plan.reason_codes)
```

- [x] **Step 2: Run test to verify current failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_agent_runtime.AgentRuntimeTests.test_skill_planner_treats_failed_cases_as_evidence_for_defect_creation
```

Expected: FAIL because current artifact scoring selects `http-test-case-design`.

- [x] **Step 3: Implement semantic artifact compatibility**

In `app/services/agent_skill_planner.py`:

- import `parse_agent_intent_action`;
- parse once near the beginning of `plan`;
- pass the parsed action into `_apply_intent_signals` and `_apply_artifact_context`;
- in `_intent_accepts_artifact_action`, reject `test_case_query_snapshot.update_assertions` when the parsed target domain is not `test_case` and the current intent is not deictic.

Minimal logic:

```python
if artifact_type == "test_case_query_snapshot" and action == "update_assertions":
    intent_action = parse_agent_intent_action(intent)
    if intent_action.target_domain and intent_action.target_domain != "test_case":
        return intent_action.is_deictic_followup
```

Also add a stronger direct candidate when `target_domain == "defect"`:

```python
if intent_action.target_domain == "defect":
    self._add_candidate(... skill_name=DEFECT_SKILL_NAME, score=18, reason="intent_action:target_domain:defect")
```

- [x] **Step 4: Run focused planner test**

Run the same command. Expected: PASS.

---

### Task 3: Include evidence-domain read tools alongside target-domain tools

**Files:**
- Modify: `app/services/agent_capability_resolver.py`
- Modify: `tests/test_agent_runtime.py`

**Interfaces:**
- Consumes: `parse_agent_intent_action`
- Produces: capability plan with target write tools plus evidence read tools.

- [x] **Step 1: Write failing capability/context test**

Add:

```python
def test_context_manager_exposes_defect_create_and_case_evidence_tools(self):
    from app.services.agent_context_manager import AgentContextManager

    working_context = {
        "active_artifact_handles": [
            {
                "artifact_type": "test_case_query_snapshot",
                "artifact_class": "AUTHORITATIVE",
                "artifact_trust": "SOURCE",
                "domain": "test_case",
                "available_followup_actions": ["update_assertions", "execute"],
                "artifact_summary": {"project_id": 1, "http_total": 15},
            }
        ]
    }

    plan = AgentContextManager().route(
        "你可以根据失败用例创建对应的缺陷",
        working_context=working_context,
    )

    self.assertEqual(plan.primary_skill, "defect-triage")
    self.assertIn("defect.create_saved", plan.allowed_tools)
    self.assertIn("defect.query_project_defects", plan.allowed_tools)
    self.assertIn("testcase.query_project_cases", plan.allowed_tools)
```

- [x] **Step 2: Run test to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_agent_runtime.AgentRuntimeTests.test_context_manager_exposes_defect_create_and_case_evidence_tools
```

Expected: FAIL because current routed allowed tools do not include defect create for this working context.

- [x] **Step 3: Implement action-driven capability additions**

In `app/services/agent_capability_resolver.py`:

- import `parse_agent_intent_action`;
- parse using `original_intent or intent`;
- when `target_domain == "defect"`, add `defect.query_project_defects` and `defect.create_saved` for create action;
- when `source_domains` contains `test_case`, add `testcase.query_project_cases`;
- when `source_domains` contains `execution`, add `execution.query_records` and `execution.read_detail`;
- when `source_domains` contains `report`, add `report.read_summary`;
- add reason codes such as `intent_action:target:defect` and `intent_action:evidence:test_case`.

- [x] **Step 4: Run focused test**

Run the same command. Expected: PASS.

---

### Task 4: Make platform skills first-class task types

**Files:**
- Modify: `app/services/agent_context_manager.py`
- Modify: `tests/test_agent_runtime.py`

**Interfaces:**
- Produces stable `task_type` for selected platform skills.

- [x] **Step 1: Write failing task-type test**

Add:

```python
def test_context_manager_uses_first_class_defect_task_type(self):
    from app.services.agent_context_manager import AgentContextManager

    plan = AgentContextManager().route("创建一个缺陷")

    self.assertEqual(plan.primary_skill, "defect-triage")
    self.assertEqual(plan.task_type, "defect_triage")
```

- [x] **Step 2: Run test to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_agent_runtime.AgentRuntimeTests.test_context_manager_uses_first_class_defect_task_type
```

Expected: FAIL because current mapping falls back to `general`.

- [x] **Step 3: Add mappings**

In `SKILL_TASK_TYPES`, add:

```python
"defect-triage": "defect_triage",
"test-plan-management": "test_plan_management",
"visual-flow-design": "visual_flow_design",
"execution-diagnosis": "execution_diagnosis",
```

Keep existing mappings unchanged.

- [x] **Step 4: Run focused test**

Run the same command. Expected: PASS.

---

### Task 5: Add broader cross-domain regression coverage

**Files:**
- Modify: `tests/test_agent_runtime.py`

**Interfaces:**
- Consumes tasks 1-4.
- Produces regression safety for future skills.

- [x] **Step 1: Add execution-to-defect test**

```python
def test_context_manager_routes_execution_failure_to_defect_with_execution_evidence(self):
    from app.services.agent_context_manager import AgentContextManager

    plan = AgentContextManager().route("根据这次执行失败创建缺陷")

    self.assertEqual(plan.primary_skill, "defect-triage")
    self.assertIn("defect.create_saved", plan.allowed_tools)
    self.assertIn("execution.query_records", plan.allowed_tools)
```

- [x] **Step 2: Add report-to-plan test**

```python
def test_context_manager_routes_report_to_test_plan_with_report_evidence(self):
    from app.services.agent_context_manager import AgentContextManager

    plan = AgentContextManager().route("根据这份报告生成测试计划")

    self.assertEqual(plan.primary_skill, "test-plan-management")
    self.assertIn("plan.create_saved", plan.allowed_tools)
    self.assertIn("report.read_summary", plan.allowed_tools)
```

- [x] **Step 3: Add defect-to-regression-case test**

```python
def test_context_manager_routes_defect_to_regression_case_with_defect_evidence(self):
    from app.services.agent_context_manager import AgentContextManager

    plan = AgentContextManager().route("根据这个缺陷生成回归测试用例")

    self.assertEqual(plan.primary_skill, "http-test-case-design")
    self.assertIn("testcase.create_saved", plan.allowed_tools)
    self.assertIn("defect.query_project_defects", plan.allowed_tools)
```

- [x] **Step 4: Run all new cross-domain tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_agent_runtime.AgentRuntimeTests.test_context_manager_routes_execution_failure_to_defect_with_execution_evidence tests.test_agent_runtime.AgentRuntimeTests.test_context_manager_routes_report_to_test_plan_with_report_evidence tests.test_agent_runtime.AgentRuntimeTests.test_context_manager_routes_defect_to_regression_case_with_defect_evidence
```

Expected after tasks 1-4: PASS. If any fail, adjust only the action parser and capability resolver mappings needed for that target/source domain.

---

### Task 6: Add minimal capability-denial protection

**Files:**
- Modify: `app/services/agent_runtime_service.py`
- Modify: `tests/test_agent_runtime.py`

**Interfaces:**
- Produces a guard function such as `_assistant_denies_available_capability(message: str, runtime_tools: Sequence[dict[str, Any]]) -> str | None`.

- [x] **Step 1: Write failing guard test**

Add:

```python
def test_runtime_guard_detects_false_defect_tool_denial(self):
    from app.services.agent_runtime_service import _assistant_denies_available_capability

    reason = _assistant_denies_available_capability(
        "当前平台没有提供直接创建缺陷的接口，只能整理草稿。",
        [{"name": "defect.create_saved"}],
    )

    self.assertEqual(reason, "route_missed_available_defect_create")
```

- [x] **Step 2: Run test to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_agent_runtime.AgentRuntimeTests.test_runtime_guard_detects_false_defect_tool_denial
```

Expected: ERROR because the guard does not exist.

- [x] **Step 3: Implement minimal detection helper**

In `app/services/agent_runtime_service.py`, add a pure helper near other runtime guard helpers:

```python
def _assistant_denies_available_capability(
    message: str,
    runtime_tools: Sequence[dict[str, Any]],
) -> str | None:
    lowered = (message or "").casefold()
    denial_terms = ("没有", "不支持", "无法", "只能", "no direct", "unsupported", "cannot")
    if not any(term.casefold() in lowered for term in denial_terms):
        return None
    tool_names = {
        str(tool.get("name") or tool.get("tool_name") or "")
        for tool in runtime_tools
        if isinstance(tool, dict)
    }
    if "缺陷" in lowered and "defect.create_saved" in tool_names:
        return "route_missed_available_defect_create"
    return None
```

This task only adds the pure helper and unit coverage. Wiring it into final-answer replan can be a later task if the existing runner finalization path needs more careful event semantics.

- [x] **Step 4: Run focused test**

Run the same command. Expected: PASS.

---

### Task 7: Documentation and regression verification

**Files:**
- Modify: `docs/api_agent_frontend_contract.md`
- Modify: `docs/technical_architecture.md`
- Modify: `docs/development_technical_notes.md`

**Interfaces:**
- Consumes passing tests from tasks 1-6.
- Produces updated architecture notes.

- [x] **Step 1: Update architecture docs**

Add a short section stating:

- Skill retrieval is not final routing;
- explicit user target action outranks incompatible artifact actions;
- artifacts can be target or evidence;
- ToolRuntime remains the final authority for writes, approvals, references, and permissions.

- [x] **Step 2: Run focused Agent route tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_agent_runtime
```

Expected: PASS with existing known skips only.

- [x] **Step 3: Run platform tool tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_agent_platform_tools
```

Expected: PASS.

- [x] **Step 4: Run full regression if focused suites pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Expected: PASS with known skips only. If unrelated dirty-worktree tests fail, isolate and report before editing.

---

## Execution Notes

- Use `apply_patch` for all edits.
- Do not commit automatically while the worktree contains unrelated user changes.
- If `rg.exe` is blocked on Windows, use `Get-ChildItem ... | Select-String`.
- Prefer small, pure helper functions so route decisions can be tested without launching the live model provider.
- If a test requires live DeepSeek, it is too broad for this implementation increment; keep route and guard tests deterministic.

## Self-Review

- Spec coverage: Tasks 1-7 cover IntentAction, artifact evidence semantics, candidate target/evidence tools, platform task type mappings, denial guard helper, documentation, and verification.
- Placeholder scan: no TBD/TODO placeholders are used.
- Type consistency: `AgentIntentAction` and `parse_agent_intent_action` are defined in Task 1 and consumed in later tasks.
