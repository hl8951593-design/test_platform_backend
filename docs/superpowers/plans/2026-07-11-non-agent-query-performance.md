# Non-Agent Query Performance Optimization Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Use `superpowers:test-driven-development` for every behavior change and `superpowers:verification-before-completion` before claiming completion.

**Goal:** Reduce SQL volume, transferred payload size, and avoidable sorting cost on the four approved non-Agent business paths without changing response contracts, permissions, idempotency, result ordering, or the existing asynchronous execution architecture.

**Architecture:** Keep all public service and route signatures unchanged. Optimize only the persistence boundary: defer one list-only large column, collapse independent counts into aggregates, replace per-row refresh with one bulk insert/update plus one ordered reload, and add report repository queries that do not execute unused totals. Add two covering indexes through one Alembic revision and mirror them in ORM metadata.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, MySQL 8, SQLite in-memory contract tests, `unittest`.

---

## Guardrails before every task

- Do not inspect or modify Agent runtime, Agent routes, Agent tables, Agent skills, or Agent tests.
- Preserve the existing uncommitted work in `app/services/test_plan_service.py`; the current user change starts at `execute_queued_run()` and must remain byte-for-byte intact.
- Preserve the current user changes in `docs/README.md`, `docs/development_technical_notes.md`, and `docs/technical_architecture.md`; documentation edits must be small additive patches around the current worktree content.
- Never use `git add -A`, `git add .`, `git checkout --`, `git reset --hard`, or a broad formatter.
- Before each commit, run `git diff --check` and inspect `git diff -- <task files>`.
- Stage only the exact files listed for that task.

## Task 1: Lock the scenario-run list projection and add query indexes

**Files:**

- Modify: `app/services/scenario_service.py:14,500-515`
- Modify: `app/models/scenario.py:71-78`
- Modify: `app/models/browser_capture.py:29-33`
- Create: `migrations/versions/0038_non_agent_query_performance_indexes.py`
- Create: `tests/test_non_agent_query_performance.py`

### Step 1: Write failing projection and metadata tests

Add a focused test module that uses `MagicMock` for the scenario service so it can inspect the generated SQL without creating unrelated data:

```python
class ScenarioRunQueryPerformanceTests(unittest.TestCase):
    def test_list_query_defers_snapshot_but_detail_query_keeps_full_entity(self):
        db = MagicMock()
        db.scalar.return_value = 0
        db.scalars.return_value.all.return_value = []
        service = ScenarioService(db)
        service.permission_service.require_project_permission = MagicMock()

        service.list_runs(
            project_id=7,
            scenario_id=None,
            current_user=SimpleNamespace(id=9),
            page=1,
            page_size=20,
        )
        list_statement = db.scalars.call_args.args[0]
        list_sql = str(list_statement.compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertNotIn("scenario_snapshot", list_sql)

        db.reset_mock()
        db.scalar.return_value = SimpleNamespace(status="passed")
        service.get_run(project_id=7, run_id=3, current_user=SimpleNamespace(id=9))
        detail_statement = db.scalar.call_args.args[0]
        detail_sql = str(detail_statement.compile(compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("scenario_snapshot", detail_sql)
```

Also assert the new ORM indexes and migration operations have the exact names and ordered columns:

```python
self.assertEqual(
    [column.name for column in TestScenarioRun.__table__.indexes_by_name[
        "ix_test_scenario_runs_project_started_id"
    ].columns],
    ["project_id", "started_at", "id"],
)
```

If `indexes_by_name` is not available, build `{index.name: index for index in table.indexes}` in the test.

### Step 2: Run the focused test and confirm RED

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_non_agent_query_performance
```

Expected: failure because `scenario_snapshot` is still selected and the new indexes/migration do not exist.

### Step 3: Defer only the hidden scenario snapshot on the list query

Change the ORM import and list statement only:

```python
from sqlalchemy.orm import Session, defer

items = list(self.db.scalars(
    select(TestScenarioRun)
    .options(defer(TestScenarioRun.scenario_snapshot))
    .where(*filters)
    .order_by(TestScenarioRun.started_at.desc(), TestScenarioRun.id.desc())
    .offset((page - 1) * page_size)
    .limit(page_size)
).all())
```

Do not defer `variables_snapshot` or `step_results`; both are returned by the existing response schema. Do not change `get_run()`.

### Step 4: Add matching model indexes

Append these entries to the existing `__table_args__` blocks:

```python
Index("ix_test_scenario_runs_project_started_id", "project_id", "started_at", "id"),
Index("ix_browser_capture_entries_capture_id_order", "capture_id", "id"),
```

### Step 5: Add Alembic revision `0038`

Create a single-head revision:

```python
revision = "0038_non_agent_query_performance_indexes"
down_revision = "0037_browser_capture_analysis_audit_fields"

def upgrade() -> None:
    op.create_index(
        "ix_test_scenario_runs_project_started_id",
        "test_scenario_runs",
        ["project_id", "started_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_browser_capture_entries_capture_id_order",
        "browser_capture_entries",
        ["capture_id", "id"],
        unique=False,
    )

def downgrade() -> None:
    op.drop_index(
        "ix_browser_capture_entries_capture_id_order",
        table_name="browser_capture_entries",
    )
    op.drop_index(
        "ix_test_scenario_runs_project_started_id",
        table_name="test_scenario_runs",
    )
```

### Step 6: Run focused tests and migration-head check

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_non_agent_query_performance
.\.venv\Scripts\python.exe -m alembic heads
```

Expected: tests pass; exactly one head named `0038_non_agent_query_performance_indexes`.

### Step 7: Commit only Task 1 files

```powershell
git add app/services/scenario_service.py app/models/scenario.py app/models/browser_capture.py migrations/versions/0038_non_agent_query_performance_indexes.py tests/test_non_agent_query_performance.py
git commit -m "perf: trim non-agent list query payloads"
```

## Task 2: Collapse test-plan list statistics into bounded SQL

**Files:**

- Modify: `app/services/test_plan_service.py:8,41-68`
- Modify: `tests/test_non_agent_query_performance.py`

### Step 1: Add behavior and SQL-count tests

Use an in-memory SQLite session with `Base.metadata.create_all()` and mock only `permission_service.require_project_permission`. Seed enabled manual, enabled cron, disabled, and failed/non-failed runs. Count `before_cursor_execute` events only around `list_plans()`.

Assertions:

```python
self.assertEqual(result["statistics"], {
    "total": 3,
    "enabled": 2,
    "scheduled": 1,
    "recent_failed": 1,
})
self.assertEqual(result["total"], 3)
self.assertLessEqual(statement_count, 3)
```

Add a filtered case and assert `total` is the filtered count while `statistics` remains project-wide. This prevents a performance change from altering semantics.

### Step 2: Run the focused class and confirm RED

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_non_agent_query_performance.TestPlanQueryPerformanceTests
```

Expected: current implementation exceeds the SQL budget.

### Step 3: Replace four statistics queries with one aggregate statement

Add `case` to the SQLAlchemy import and create one statistics query:

```python
recent_failed = (
    select(func.count())
    .select_from(TestPlanRun)
    .where(
        TestPlanRun.project_id == project_id,
        TestPlanRun.status == "failed",
        TestPlanRun.is_deleted.is_(False),
    )
    .scalar_subquery()
)
statistics_row = self.db.execute(
    select(
        func.count(TestPlan.id).label("total"),
        func.coalesce(func.sum(case((TestPlan.enabled.is_(True), 1), else_=0)), 0).label("enabled"),
        func.coalesce(func.sum(case((
            TestPlan.enabled.is_(True) & (TestPlan.trigger_type == "cron"), 1
        ), else_=0)), 0).label("scheduled"),
        recent_failed.label("recent_failed"),
    ).where(*all_filters)
).one()
```

Set `total` from `statistics_row.total` when no keyword/enabled/trigger filter is active. Execute a separate filtered count only when a filter is active. Keep the list query, order, pagination, and response keys unchanged.

### Step 4: Verify focused and existing plan tests

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_non_agent_query_performance.TestPlanQueryPerformanceTests tests.test_test_plan_semantics
```

Expected: unfiltered path uses two service SQL statements after permission is mocked; filtered path uses three; values match the old implementation.

### Step 5: Inspect overlap and commit narrowly

```powershell
git diff -- app/services/test_plan_service.py
git add app/services/test_plan_service.py tests/test_non_agent_query_performance.py
git commit -m "perf: aggregate test plan list statistics"
```

Confirm the pre-existing `execute_queued_run()` block is still present and not accidentally reverted.

## Task 3: Replace browser-capture per-row refresh with set-based persistence

**Files:**

- Modify: `app/services/browser_capture_service.py:2,105-127`
- Modify: `tests/test_non_agent_query_performance.py`

### Step 1: Add new/update/mixed/order and 100-row query-budget tests

Seed a capture, then cover:

1. all-new entries preserve request order;
2. an existing entry is updated rather than duplicated;
3. mixed existing/new entries preserve request order;
4. a 100-entry all-new batch executes no more than 10 SQL cursor operations and no more than 4 SELECT statements inside `upsert_entries()` after permission and capture lookup are included.

The returned objects must remain live ORM instances with populated integer IDs and normalized payload fields.

### Step 2: Run the browser-capture performance class and confirm RED

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_non_agent_query_performance.BrowserCaptureUpsertPerformanceTests
```

Expected: current implementation performs one refresh SELECT per result and exceeds the SQL budget.

### Step 3: Use a Core executemany insert, ORM batched updates, and one reload

Import `insert`. Keep the existing initial lookup. Split values into existing updates and new row dictionaries:

```python
requested_ids = [entry.client_entry_id for entry in payload.entries]
new_values = []
for entry_payload in payload.entries:
    values = entry_payload.model_dump()
    entry = existing.get(entry_payload.client_entry_id)
    if entry is None:
        new_values.append({"capture_id": capture_id, "project_id": project_id, **values})
    else:
        for key, value in values.items():
            setattr(entry, key, value)

if new_values:
    self.db.execute(insert(BrowserCaptureEntry), new_values)
capture.status = "reviewing"
self.db.commit()

persisted = list(self.db.scalars(
    select(BrowserCaptureEntry).where(
        BrowserCaptureEntry.capture_id == capture_id,
        BrowserCaptureEntry.client_entry_id.in_(requested_ids),
    )
).all())
persisted_by_client_id = {entry.client_entry_id: entry for entry in persisted}
return [persisted_by_client_id[client_id] for client_id in requested_ids]
```

The batch schema already rejects duplicate `client_entry_id` values; do not add new validation or alter conflict behavior. Do not commit inside the loop and do not call `refresh()` per row.

### Step 4: Verify focused and existing capture contracts

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_non_agent_query_performance.BrowserCaptureUpsertPerformanceTests tests.test_browser_capture_plugin_contract
```

Expected: response ordering and update semantics pass; 100-row batch is constant-query.

### Step 5: Commit Task 3 files

```powershell
git add app/services/browser_capture_service.py tests/test_non_agent_query_performance.py
git commit -m "perf: batch browser capture entry upserts"
```

## Task 4: Remove unused report counts and combine comparison windows

**Files:**

- Modify: `app/repositories/test_report_repository.py:73-108`
- Modify: `app/services/test_report_service.py:201-304`
- Modify: `tests/test_non_agent_query_performance.py`
- Modify: `tests/test_test_reports.py`

### Step 1: Add service contract and repository query-budget tests

Add a service unit test proving the overview no longer calls paginated `list_reports()` and still returns identical summary values for current and previous windows.

Add an SQLite integration test with plan and flow executions. Count SQL only around `get_intelligence_overview()` while permission is mocked. Assert:

```python
self.assertLessEqual(statement_count, 5)
self.assertEqual(result.summary.pass_rate, expected_pass_rate)
self.assertEqual(result.summary.pass_rate_delta, expected_delta)
```

Include one report exactly at `started_from` to lock the existing inclusive boundary behavior: it may be present in both current and previous windows, just as the two old `list_reports()` calls allowed.

### Step 2: Run report tests and confirm RED

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_non_agent_query_performance.ReportIntelligenceQueryPerformanceTests tests.test_test_reports
```

Expected: current overview uses eight repository/service SQL statements and calls `list_reports()` three times.

### Step 3: Extract reusable report source and filters

Add private repository helpers so `list_reports()`, latest-reference lookup, and period lookup share the same union and filter semantics:

```python
def _reports(self):
    return union_all(self._plan_select(), self._flow_select()).subquery("test_reports")

@staticmethod
def _filters(reports, *, project_id, source_type=None, status=None,
             environment_id=None, started_from=None, started_to=None):
    ...
```

Keep public `list_reports()` behavior unchanged, including its count query.

### Step 4: Add one-statement latest-reference lookup

```python
def get_latest_report_reference_time(self, *, project_id: int, environment_id: int | None):
    reports = self._reports()
    filters = self._filters(reports, project_id=project_id, environment_id=environment_id)
    return self.db.scalar(
        select(func.coalesce(func.max(reports.c.started_at), func.max(reports.c.created_at)))
        .where(*filters)
    )
```

The service keeps the existing `TestCaseExecution` fallback only when this method returns `None`.

### Step 5: Add one combined current/previous query with per-period limits

Build two ordered, limited derived tables and `UNION ALL` them so each period retains its existing 1000-row cap and the inclusive boundary remains unchanged:

```python
def list_report_comparison_periods(..., page_size: int = 1000):
    reports = self._reports()

    def period_query(label_value: str, started_from: datetime, started_to: datetime):
        filters = self._filters(
            reports,
            project_id=project_id,
            environment_id=environment_id,
            started_from=started_from,
            started_to=started_to,
        )
        return (
            select(reports, literal(label_value).label("comparison_period"))
            .where(*filters)
            .order_by(reports.c.started_at.desc(), reports.c.source_type, reports.c.source_id.desc())
            .limit(page_size)
            .subquery()
        )

    current = period_query("current", current_from, current_to)
    previous = period_query("previous", previous_from, previous_to)
    rows = self.db.execute(
        union_all(select(current), select(previous))
    ).mappings().all()
    return [dict(row) for row in rows]
```

If MySQL or SQLite requires explicit derived-table columns, use `select(*current.c)` and `select(*previous.c)`; verify both dialects through tests and SQL compilation. Split returned rows by `comparison_period` in the service and remove that internal key before `_summary()`.

### Step 6: Update the overview without changing its response model

Replace the three paginated calls with one latest-reference query and one comparison-period query. Leave `_slow_tests()`, `_failure_clusters()`, `_open_defect_count()`, recommendation logic, and all response fields untouched.

### Step 7: Verify focused and existing report tests

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_non_agent_query_performance.ReportIntelligenceQueryPerformanceTests tests.test_test_reports
```

Expected: overview uses at most five SQL statements, no internal count query, and all old result assertions remain valid.

### Step 8: Commit Task 4 files

```powershell
git add app/repositories/test_report_repository.py app/services/test_report_service.py tests/test_non_agent_query_performance.py tests/test_test_reports.py
git commit -m "perf: streamline report intelligence queries"
```

## Task 5: Apply migration, measure contracts, and synchronize documentation

**Files:**

- Modify additively: `docs/README.md`
- Modify additively: `docs/development_technical_notes.md`
- Modify additively: `docs/technical_architecture.md`
- Verify: all Task 1-4 files

### Step 1: Run static and focused verification

```powershell
git diff --check
.\.venv\Scripts\python.exe -m unittest -v tests.test_non_agent_query_performance tests.test_scenario_semantics tests.test_test_plan_semantics tests.test_browser_capture_plugin_contract tests.test_test_reports
.\.venv\Scripts\python.exe -m alembic heads
```

Expected: all pass; one Alembic head at `0038_non_agent_query_performance_indexes`.

### Step 2: Exercise upgrade/downgrade/upgrade on the configured local database

First record the current revision and ensure no long-running audit query remains. Then run:

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic downgrade 0037_browser_capture_analysis_audit_fields
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

Expected: downgrade removes only the two new indexes; final current revision is `0038_non_agent_query_performance_indexes`.

### Step 3: Inspect actual indexes and query plans

Use SQLAlchemy inspection (not raw password output) to assert both index names and ordered columns. Run `EXPLAIN` for:

- scenario runs filtered by `project_id`, ordered by `started_at DESC, id DESC`;
- browser capture entries filtered by `capture_id`, ordered by `id DESC`.

Record whether the new indexes are selected. Do not claim timing improvement from a cold single sample; report SQL-count reductions and transferred-column reduction as deterministic evidence, and include before/after timings only as supplemental evidence.

### Step 4: Run the non-Agent regression set

Select test modules whose names do not contain `agent` or `ai`, then run them as one `unittest` invocation:

```powershell
$modules = Get-ChildItem tests -File -Filter 'test_*.py' |
    Where-Object { $_.BaseName -notmatch '(?i)agent|ai' } |
    ForEach-Object { "tests.$($_.BaseName)" }
.\.venv\Scripts\python.exe -m unittest -b $modules
```

Expected: all selected non-Agent tests pass.

### Step 5: Run the full regression suite

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -b
```

Expected: complete suite passes with only previously known skips. If an unrelated dirty Agent test fails, isolate and report it; do not edit Agent code under this plan.

### Step 6: Update documentation additively

Add a new non-Agent performance increment paragraph to `docs/development_technical_notes.md` and a persistence/read-path note to `docs/technical_architecture.md`. Update `docs/README.md` only after verification with:

- current date `2026-07-11`;
- Alembic head `0038_non_agent_query_performance_indexes`;
- actual test counts from Steps 4-5;
- deterministic SQL budgets: plans `<=3`, capture 100-row batch `<=10`, report overview `<=5`;
- explicit statement that HTTP response contracts and async execution architecture are unchanged.

Do not rewrite or remove the current uncommitted Agent documentation additions.

### Step 7: Final self-review and documentation commit

```powershell
git diff --check
git diff --stat
git status --short
git add docs/README.md docs/development_technical_notes.md docs/technical_architecture.md
git commit -m "docs: record non-agent query performance baseline"
```

Review the complete branch diff against the approved design:

- no Agent file changed by these commits;
- no route/schema field changed;
- no async worker/future/SSE behavior changed;
- no returned list order changed;
- migration has one head and reversible index-only downgrade;
- query budgets are enforced by tests, not only comments.

## Completion criteria

- `GET /scenario-runs` still returns the same fields but its list SELECT omits `scenario_snapshot`.
- Test-plan list uses at most three service SQL statements for filtered requests and at most two for unfiltered requests, excluding the permission check when mocked.
- Browser-capture 100-entry upsert uses at most ten SQL cursor operations and preserves request order.
- Report intelligence overview uses at most five SQL statements and preserves all summary fields and boundary semantics.
- Alembic has exactly one head at `0038_non_agent_query_performance_indexes`; upgrade/downgrade/upgrade succeeds.
- Focused, non-Agent, and full test suites pass.
- Existing asynchronous architecture and all Agent files remain untouched by the implementation.
