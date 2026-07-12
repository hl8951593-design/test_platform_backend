# Agent Skill Orchestration v2 Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the remaining Agent Skill Orchestration v2 work after the first implementation increment: safe capability-denial replan, full Skill contract coverage, diagnostics contract documentation, and full regression verification.

**Architecture:** Keep the existing asynchronous runner, ToolCall ledger, approval policy, schema preflight, object-reference guard, and project isolation intact. Add only a bounded repair/replan path that is triggered when a model falsely denies a capability that exists in the runtime snapshot, and standardize Skill frontmatter contracts so future Skill retrieval can rely on `owns/consumes/produces`.

**Tech Stack:** FastAPI backend, SQLAlchemy models, existing Agent runtime services, Python `unittest`, local Agent Skill markdown registry.

## Global Constraints

- Do not expose all tools to the LLM for every run.
- Do not remove or rename existing ToolSpec names.
- Do not weaken permission, approval, schema preflight, object-reference freshness, project isolation, replay policy, or asynchronous execution semantics.
- Do not add database migrations for Agent Orchestration v2 completion.
- Preserve dirty worktree changes owned by the user; edit only Agent orchestration files, Skill markdown frontmatter, tests, and docs.
- Follow TDD for behavior changes.

---

## File Structure

- Modify: `app/services/agent_runtime_service.py`
  Adds a hidden capability-denial replan path that can turn a false unsupported final answer into a valid `agent_tool_request` while preserving existing ToolRuntime execution.

- Modify: `tests/test_agent_runtime.py`
  Adds regression coverage for automatic replan and full Skill contract declarations.

- Modify: `app/agent_skills/*/SKILL.md`
  Adds `owns`, `consumes`, and `produces` contract fields where missing.

- Modify: `docs/api_agent_frontend_contract.md`, `docs/technical_architecture.md`, `docs/development_technical_notes.md`
  Records completion semantics and frontend-observable events.

---

### Task 1: Add safe capability-denial replan

- [x] Write a failing runner test where the first model response falsely denies defect creation and the hidden repair response emits `defect.create_saved`.
- [x] Verify the test fails because the current guard only replaces the answer with a diagnostic message.
- [x] Implement a bounded `_repair_available_capability_denial(...)` path in `AgentConversationRunner`.
- [x] Wire it into the non-final natural-language completion path before the diagnostic fallback.
- [x] Verify the focused runner test passes and still records `model.capability_denial_guarded`.

### Task 2: Standardize all Skill orchestration contracts

- [x] Write a failing registry test requiring every bundled Skill to declare non-empty `owns`, `consumes`, and `produces`.
- [x] Verify the test fails against currently incomplete Skill frontmatter.
- [x] Add minimal domain contracts to each missing `app/agent_skills/*/SKILL.md`.
- [x] Verify the registry test passes.

### Task 3: Document completion semantics

- [x] Update architecture docs with the safe replan path.
- [x] Update frontend contract docs with `model.capability_denial_replanned`.
- [x] Update development technical notes with completion status and verification commands.

### Task 4: Verification

- [x] Run focused new tests.
- [x] Run `tests.test_agent_runtime`.
- [x] Run `tests.test_agent_platform_tools`.
- [x] Run full unittest discovery.
