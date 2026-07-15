# System Test Cases Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first-stage backend contract for the frontend System Test Cases module with strict project isolation.

**Architecture:** Add a focused system-test-case domain beside existing HTTP test cases. The new service owns project permission checks, relation validation, serialization, statistics, and API-candidate projection from existing `test_cases`.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Pydantic v2, Alembic, unittest.

## Global Constraints

- Every query and write must be isolated by `project_id`.
- Preserve existing HTTP test case behavior and async execution architecture.
- Reuse `case:view` and `case:manage` permissions.
- Do not touch Agent modules for this feature.
- First stage includes CRUD, duplicate, batch delete, API candidates, relations, and statistics only.

---

### Task 1: Domain Tests And Persistence

**Files:**
- Create: `tests/test_system_test_cases.py`
- Create: `app/models/system_test_case.py`
- Modify: `app/models/__init__.py`
- Create: `migrations/versions/0039_system_test_cases.py`

**Interfaces:**
- Produces: ORM classes `SystemTestCase` and `SystemCaseApiRelation`.
- Produces: tables `system_test_cases` and `system_case_api_relations`.

- [ ] Write failing tests that import the new model classes and assert table names, project indexes, and relation uniqueness.
- [ ] Run `.\.venv\Scripts\python.exe -m unittest -b tests.test_system_test_cases` and confirm the import fails because the models do not exist.
- [ ] Implement the ORM models and Alembic migration with project-scoped indexes and cascading relation deletion.
- [ ] Run the focused test and confirm it passes.

### Task 2: Schemas And Service Behavior

**Files:**
- Modify: `tests/test_system_test_cases.py`
- Create: `app/schemas/system_test_case.py`
- Create: `app/services/system_test_case_service.py`

**Interfaces:**
- Consumes: `SystemTestCase`, `SystemCaseApiRelation`, existing `TestCase`, `Project`, `ProjectEnvironment`, `User`.
- Produces: `SystemTestCaseService` methods `list_cases`, `get_case`, `create_case`, `update_case`, `delete_case`, `batch_delete`, `duplicate_case`, `list_api_candidates`, `list_relations`, `replace_relations`, and `statistics`.

- [ ] Add failing service tests for project permission use, list filters, create defaults, relation project mismatch rejection, and statistics calculation.
- [ ] Run the focused test and confirm failures are due to missing schema/service.
- [ ] Implement Pydantic schemas with the frontend camelCase field names and enum literals.
- [ ] Implement service methods with project isolation in every query.
- [ ] Run the focused test and confirm it passes.

### Task 3: Router Registration And Contract Tests

**Files:**
- Modify: `tests/test_system_test_cases.py`
- Create: `app/api/v1/routers/system_test_cases.py`
- Modify: `app/api/v1/api.py`

**Interfaces:**
- Consumes: `SystemTestCaseService` and schemas.
- Produces: FastAPI routes under `/api/v1/projects/{project_id}/system-test-cases` and `/api/v1/system-test-cases/{id}`.

- [ ] Add failing route registration tests for all first-stage endpoints.
- [ ] Run the focused test and confirm route assertions fail.
- [ ] Implement the router and register it in `api_router`.
- [ ] Run the focused test and confirm it passes.

### Task 4: Documentation And Verification

**Files:**
- Create: `docs/api_system_test_cases.md`
- Modify: `docs/README.md`
- Modify: `docs/development_technical_notes.md`
- Modify: `docs/technical_architecture.md`

**Interfaces:**
- Produces: documented API contract, migration note, and module architecture note.

- [ ] Add docs for first-stage endpoints, request/response fields, permission rules, and project isolation.
- [ ] Run `.\.venv\Scripts\python.exe -m unittest -b tests.test_system_test_cases`.
- [ ] Run `alembic upgrade head`.
- [ ] Run a broader safe regression selection for non-Agent backend modules.
- [ ] Run `git diff --check`.
