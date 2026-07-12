# Agent Execution Diagnostics Scaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Agent execution diagnosis accurate under very large tool outputs, add progressive evidence reads and scalable execution indexes, and remove scenario step-result rewrite amplification without changing existing business or asynchronous execution behavior.

**Architecture:** Keep protocol execution tables as the audit ledger, add deterministic protocol projectors and bounded diagnostic envelopes for the model path, then add a unified execution index, incremental step diagnostics, artifact references, cursor reads, failure clusters, and rollups. Migrate scenario steps through dual-write and compatibility assembly before enabling normalized incremental storage; all public full-detail, SSE, worker, permission, approval, and status contracts remain compatible.

**Tech Stack:** Python 3.12 in `.venv`, FastAPI, Pydantic v2, SQLAlchemy 2, MySQL/Alembic, `unittest`, existing `AIService`, existing execution worker/SSE runtime, gzip/sha256 from the Python standard library.

## Global Constraints

- Preserve current HTTP, WebSocket, scenario, and Flow execution semantics, project isolation, permissions, status transitions, retries, assertions, extractors, approvals, idempotency, workers, and SSE event order.
- Preserve the existing complete `summary + detail` REST response and legacy `execution.read_detail` behavior when `view` is omitted.
- The full redacted ToolCall output remains the ledger; model-facing views default to 12,000 characters and may never exceed the 24,000-character hard limit.
- Never use silent prefix truncation for execution details; every omission must include a reason and a continuation reference or cursor.
- Store small normalized scenario step details in `execution_step_diagnostics.detail_json`; store extracted or oversized sections through artifact references.
- Use deterministic failure classification and aggregation. The LLM may explain clusters but may not perform base counting, paging, or per-record classification.
- Initial artifact storage uses the database adapter. Do not require a new Redis, queue, MinIO, or deployable process.
- Additive rollup scheduling must not participate in execution completion, status calculation, or SSE delivery.
- Preserve unrelated dirty worktree changes. In particular, stage only diagnostic hunks in `app/models/__init__.py` and `docs/README.md`; do not reset, checkout, delete, or commit the existing system-test-case work.
- Use TDD for every task. Each task ends with focused GREEN tests and its own commit.
- Source design: `docs/superpowers/specs/2026-07-12-agent-execution-diagnostics-scaling-design.md`.

---

## File and Responsibility Map

**New focused files**

- `app/schemas/execution_diagnostic.py`: typed query, selector, omission, page, evidence, and envelope contracts.
- `app/services/execution_diagnostic_projection.py`: deterministic HTTP/WebSocket/scenario/Flow semantic projectors and budget fitting.
- `app/services/execution_failure_signature.py`: protocol-neutral failure category and stable signature generation.
- `app/models/execution_diagnostic.py`: unified index, step diagnostic, artifact, hourly metric, and daily metric models.
- `app/repositories/execution_diagnostic_repository.py`: project-scoped index, step, artifact, cursor, cluster, and metric persistence.
- `app/services/execution_diagnostic_service.py`: permission-checked progressive reads and compatibility assembly.
- `app/services/execution_diagnostic_persistence.py`: commit-free staging and idempotent dual-write orchestration.
- `app/services/execution_payload_store.py`: gzip database artifact adapter with chunked project-scoped reads.
- `app/services/execution_metrics_service.py`: idempotent bucket recomputation and failure cluster queries.
- `app/services/execution_metrics_scheduler.py`: optional in-process rollup scheduler, isolated from execution workers.
- `scripts/backfill_execution_diagnostics.py`: resumable history backfill and compatibility snapshot restore.
- `scripts/rebuild_execution_metrics.py`: explicit rollup rebuild command.
- `migrations/versions/0041_execution_diagnostic_read_models.py`: additive schema and indexes.
- `tests/test_execution_diagnostic_projection.py`: semantic and budget regression tests, including run 220 shape.
- `tests/test_execution_diagnostic_service.py`: progressive view, selector, omission, and permission tests.
- `tests/test_execution_diagnostic_storage.py`: model, repository, dual-write, artifact, and backfill tests.
- `tests/test_execution_diagnostic_write_paths.py`: protocol transaction and no-extra-commit tests.
- `tests/test_execution_diagnostic_scaling.py`: cursor stability, query-shape, and 10,000-step linearity tests.

**Existing integration files**

- `app/services/agent_tool_result_projection.py`: route `execution.read_detail` through the semantic projector.
- `app/services/agent_tool_result_policy.py`: retain generic fallback only for unsupported outputs.
- `app/services/agent_tool_service.py`: additive tool input schemas.
- `app/services/agent_platform_tool_service.py`: progressive tool reads and bounded AI diagnosis.
- `app/services/ai_browser_capture_service.py`: assert bounded execution evidence before calling `AIService`.
- `app/services/execution_record_service.py`: preserve full detail and delegate diagnostic reads/compatibility assembly.
- `app/repositories/execution_record_repository.py`: preserve legacy page mode and add index-backed cursor mode.
- `app/schemas/execution_record.py`: additive cursor response fields.
- `app/api/v1/routers/execution_records.py`: optional cursor/include-total parameters; legacy page parameters remain.
- Protocol services/repositories: stage index and step projections inside existing transaction boundaries.
- `app/agent_skills/execution-diagnosis/SKILL.md`: progressive read workflow and evidence-completeness rules.
- Documentation: API contracts, technical architecture, Agent frontend contract, and docs index.

All new tests use `unittest.TestCase`. Use these exact class names: `ExecutionDiagnosticProjectionTests`, `ExecutionDiagnosticServiceTests`, `ExecutionAIDiagnosisTests`, `ExecutionDiagnosticMigrationTests`, `ExecutionDiagnosticStorageTests`, `ExecutionPayloadStoreTests`, `ExecutionDiagnosticWritePathTests`, `ExecutionDiagnosticScalingTests`, and `ExecutionMetricsTests`. Test-only factories referenced below are private functions in the same test module; each returns fully constructed `SimpleNamespace`, model, service, or `MagicMock` objects and performs no external network I/O.

---

### Task 1: Typed Diagnostic Contract, Failure Signatures, and Semantic Projectors

**Files:**
- Create: `app/schemas/execution_diagnostic.py`
- Create: `app/services/execution_failure_signature.py`
- Create: `app/services/execution_diagnostic_projection.py`
- Create: `tests/test_execution_diagnostic_projection.py`

**Interfaces:**
- Consumes: normalized `ExecutionRecordDetail` dictionaries and `ExecutionType` values.
- Produces: `ExecutionDiagnosticQuery`, `CanonicalStepDiagnostic`, `CanonicalExecutionDiagnostic`, `ExecutionDiagnosticEnvelope`, `FailureIdentity`, `ExecutionDiagnosticProjectionService.canonicalize(*, execution_type: ExecutionType, execution: dict[str, Any]) -> CanonicalExecutionDiagnostic`, `canonicalize_step(*, execution_type: ExecutionType, step: dict[str, Any], fallback_index: int) -> CanonicalStepDiagnostic`, and `project(*, execution_type: ExecutionType, execution: dict[str, Any], query: ExecutionDiagnosticQuery) -> ExecutionDiagnosticEnvelope`.

- [ ] **Step 1: Write the failing run-220 semantic-priority test**

```python
def run_220_shape() -> dict:
    return {
        "summary": {"id": "scenario:220", "status": "failed", "duration_ms": 4282},
        "detail": {
            "step_results": [
                {"step_id": "STEP-1", "name": "获取企业列表", "status": "passed", "response_snapshot": {"body": "x" * 167000}},
                {"step_id": "STEP-1-AFTER-1", "name": "获取企业列表-AFTER_ACTIONS-1", "status": "passed"},
                {
                    "step_id": "STEP-2",
                    "name": "获取对应企业CT画像数",
                    "status": "failed",
                    "error_message": "Assertion failed",
                    "response_snapshot": {"status_code": 200, "body": "{\"msg\":\"请求未授权\",\"code\":90001,\"data\":null}"},
                    "assertion_results": [
                        {"assertion": {"type": "status_code", "expected": 200}, "actual": 200, "passed": True},
                        {"assertion": {"type": "json_equals", "path": "code", "expected": 200}, "actual": 90001, "passed": False},
                        {"assertion": {"type": "json_equals", "path": "success", "expected": True}, "actual": None, "passed": False},
                    ],
                    "resolved_bindings": [],
                    "extracted_variables": [],
                },
            ]
        },
    }

def test_failure_view_keeps_first_failure_after_huge_success_output(self):
    query = ExecutionDiagnosticQuery(view="failures", max_chars=12000)
    result = ExecutionDiagnosticProjectionService().project(
        execution_type="scenario", execution=run_220_shape(), query=query
    )
    assert result.data["first_failure"]["step_id"] == "STEP-2"
    assert result.data["first_failure"]["response"]["business_code"] == 90001
    assert result.data["first_failure"]["response"]["message"] == "请求未授权"
    assert result.data["first_failure"]["assertions"][1]["expected"] == 200
    assert result.data["first_failure"]["assertions"][1]["actual"] == 90001
    assert "x" * 1000 not in result.model_dump_json()
    assert len(result.model_dump_json()) <= 12000
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_projection -v`

Expected: FAIL with `ModuleNotFoundError: app.schemas.execution_diagnostic`.

- [ ] **Step 3: Implement exact query and envelope models**

```python
ExecutionDiagnosticView = Literal["summary", "failures", "steps", "step", "artifact", "full"]
ExecutionDiagnosticInclude = Literal["assertions", "response_summary", "bindings", "extractors", "retries", "upstream"]

class ExecutionDiagnosticSelector(BaseModel):
    statuses: list[str] = Field(default_factory=list, max_length=8)
    first_failure: bool = False
    step_ids: list[str] = Field(default_factory=list, max_length=200)
    artifact_ref: str | None = Field(default=None, max_length=128)
    offset: int = Field(default=0, ge=0)

class ExecutionDiagnosticQuery(BaseModel):
    view: ExecutionDiagnosticView = "full"
    selector: ExecutionDiagnosticSelector = Field(default_factory=ExecutionDiagnosticSelector)
    include: list[ExecutionDiagnosticInclude] = Field(default_factory=list, max_length=8)
    cursor: str | None = Field(default=None, max_length=512)
    limit: int = Field(default=20, ge=1, le=200)
    max_chars: int = Field(default=12000, ge=1000, le=24000)

class DiagnosticOmission(BaseModel):
    section: str
    reason: Literal["budget_exceeded", "not_requested", "artifact_externalized", "not_available"]
    reference: str | None = None

class DiagnosticPage(BaseModel):
    next_cursor: str | None = None
    has_more: bool = False

class ExecutionDiagnosticEnvelope(BaseModel):
    schema_version: Literal["execution_diagnostic_v1"] = "execution_diagnostic_v1"
    projection_version: Literal["execution_diagnostic_projection_v1"] = "execution_diagnostic_projection_v1"
    resource_ref: str
    view: ExecutionDiagnosticView
    data: dict[str, Any]
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    omissions: list[DiagnosticOmission] = Field(default_factory=list)
    page: DiagnosticPage = Field(default_factory=DiagnosticPage)
    diagnostic_complete: bool = True
    recommended_next_views: list[ExecutionDiagnosticView] = Field(default_factory=list)

class CanonicalStepDiagnostic(BaseModel):
    step_id: str
    step_index: int
    node_id: str | None = None
    node_phase: str | None = None
    name: str
    kind: str
    status: str
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    assertions: list[dict[str, Any]] = Field(default_factory=list)
    response: dict[str, Any] = Field(default_factory=dict)
    bindings: list[dict[str, Any]] = Field(default_factory=list)
    extractors: list[dict[str, Any]] = Field(default_factory=list)
    retries: dict[str, Any] = Field(default_factory=dict)
    normalized_detail: dict[str, Any] = Field(default_factory=dict)

class CanonicalExecutionDiagnostic(BaseModel):
    resource_ref: str
    execution_type: ExecutionType
    execution_id: int
    summary: dict[str, Any]
    counts: dict[str, int]
    steps: list[CanonicalStepDiagnostic]
    first_failure_step_id: str | None = None
    failure_category: str | None = None
    failure_signature: str | None = None
```

Add a model validator that requires one `step_id` for `view=step`, requires `artifact_ref` for `view=artifact`, and defaults failure statuses to `failed/timeout/error` for `view=failures`.

- [ ] **Step 4: Implement deterministic failure identity and protocol adapters**

```python
@dataclass(frozen=True)
class FailureIdentity:
    category: str
    signature: str

def classify_failure(*, execution_type: str, step: dict[str, Any]) -> FailureIdentity:
    response = response_summary(step)
    failed_assertion = next((item for item in assertion_summaries(step) if not item["passed"]), None)
    message = str(response.get("message") or step.get("error_message") or "").lower()
    category = "authorization" if response.get("business_code") in {401, 403, 90001} or "未授权" in message else "assertion" if failed_assertion else "execution"
    tokens = [execution_type, category, f"HTTP_{response.get('status_code', 'NA')}", f"BUSINESS_{response.get('business_code', 'NA')}"]
    if failed_assertion:
        tokens.extend([str(failed_assertion.get("type") or "unknown"), str(failed_assertion.get("path") or "root")])
    normalized = "_".join(re.sub(r"[^A-Za-z0-9]+", "_", item).strip("_").upper() for item in tokens)
    return FailureIdentity(category=category, signature=normalized)
```

Implement one adapter per protocol. Scenario reads `detail.step_results`; Flow reads `detail.node_executions`; HTTP and WebSocket expose one logical step from the detail row. `canonicalize` builds every step without a model budget; `project` selects and budgets from that canonical structure. Extract only status, duration, error, bounded assertion fields, response `status_code/code/success/msg/message`, binding names/sources, extractor names, and retry summary for model fields. `normalized_detail` retains the complete redacted compatibility structure for persistence, but it never enters a normal diagnostic view. Never copy response bodies, headers, cookies, tokens, or complete message arrays into model-facing fields.

- [ ] **Step 5: Add budget, protocol, security, and completeness tests**

```python
def test_all_protocols_return_common_envelope(self):
    for protocol, execution in protocol_fixtures().items():
        result = projector.project(execution_type=protocol, execution=execution, query=ExecutionDiagnosticQuery(view="summary"))
        assert result.resource_ref.startswith(f"{protocol}:")
        assert set(result.data["counts"]) == {"total", "passed", "failed", "timeout", "skipped"}

def test_budget_omits_low_priority_passed_steps_with_reference(self):
    result = projector.project(execution_type="scenario", execution=large_mixed_execution(), query=ExecutionDiagnosticQuery(view="steps", max_chars=3000))
    assert len(result.model_dump_json()) <= 3000
    assert result.page.has_more or any(item.reason == "budget_exceeded" for item in result.omissions)

def test_projection_never_emits_credentials(self):
    encoded = projector.project(execution_type="http", execution=credential_fixture(), query=ExecutionDiagnosticQuery(view="failures")).model_dump_json()
    assert "Authorization" not in encoded
    assert "Bearer secret" not in encoded
```

- [ ] **Step 6: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_projection -v`

Expected: PASS, including the run-220 regression and all four protocol envelopes.

Commit:

```powershell
git add app/schemas/execution_diagnostic.py app/services/execution_failure_signature.py app/services/execution_diagnostic_projection.py tests/test_execution_diagnostic_projection.py
git commit -m "feat: add semantic execution diagnostic projection"
```

### Task 2: Model-Facing Tool Result Projection

**Files:**
- Modify: `app/services/agent_tool_result_projection.py:1-533`
- Modify: `app/services/agent_tool_result_policy.py:205-240`
- Modify: `tests/test_agent_runtime.py` near existing ToolResultPolicy projection tests

**Interfaces:**
- Consumes: Task 1 `ExecutionDiagnosticProjectionService` and legacy `execution.read_detail` output `{project_id, execution_type, execution_id, execution}`.
- Produces: `ToolResultProjectionService.project_execution_read_detail(output) -> ToolResultProjection` with full ledger size and bounded semantic model output.

- [ ] **Step 1: Write a failing ToolResultPolicy regression**

```python
from tests.test_execution_diagnostic_projection import run_220_shape

def test_execution_detail_projection_keeps_failure_after_167k_success_body(self):
    call = SimpleNamespace(
        tool_call_id="agent-tool-run-220",
        tool_name="execution.read_detail",
        status="succeeded",
        approval_required=False,
        output_json_redacted={"project_id": 1, "execution_type": "scenario", "execution_id": 220, "execution": run_220_shape()},
        output_hash="run-220-hash",
        error_code=None,
        error_message=None,
    )
    payload = ToolResultPolicy().model_payload(call)
    encoded = json.dumps(payload["output"], ensure_ascii=False)
    self.assertTrue(payload["output_compacted_for_model"])
    self.assertFalse(payload["output_truncated"])
    self.assertIn("请求未授权", encoded)
    self.assertIn("90001", encoded)
    self.assertNotIn('"response_snapshot":', encoded)
    self.assertLessEqual(len(encoded), 12000)
```

- [ ] **Step 2: Run the regression and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_runtime.AgentRuntimeTests.test_execution_detail_projection_keeps_failure_after_167k_success_body -v`

Expected: FAIL because `execution.read_detail` falls through to the generic 2,400-character prefix preview.

- [ ] **Step 3: Register the execution projector and choose view semantically**

```python
def project(self, tool_name: str | None, output: Any) -> ToolResultProjection | None:
    if tool_name == "execution.read_detail" and isinstance(output, dict):
        return self.project_execution_read_detail(output)
    # retain existing testcase, scenario draft, and platform query branches

def project_execution_read_detail(self, output: dict[str, Any]) -> ToolResultProjection:
    execution = output.get("execution") if isinstance(output.get("execution"), dict) else {}
    summary = execution.get("summary") if isinstance(execution.get("summary"), dict) else {}
    view = "failures" if summary.get("status") in {"failed", "timeout", "error"} else "summary"
    envelope = ExecutionDiagnosticProjectionService().project(
        execution_type=str(output.get("execution_type")),
        execution=execution,
        query=ExecutionDiagnosticQuery(view=view, max_chars=12000),
    ).model_dump(mode="json")
    return ToolResultProjection(
        model_output=envelope,
        full_output_size_chars=self._json_size(output),
        model_view_chars=self._json_size(envelope),
        compacted=True,
        projection_version="execution_diagnostic_projection_v1",
    )
```

The policy must continue storing `full_output_reference="ToolCall.output_json_redacted"`; do not expose `tool_result.read_full` to the model catalog.

- [ ] **Step 4: Prove generic fallback and existing projections are unchanged**

Run: `.venv\Scripts\python.exe -m unittest tests.test_agent_runtime.AgentRuntimeTests.test_tool_result_policy_bounds_large_outputs_for_model_context tests.test_agent_runtime.AgentRuntimeTests.test_tool_result_policy_projects_query_project_cases_model_view tests.test_agent_platform_tools.AgentPlatformToolTests.test_platform_query_projection_keeps_refs_and_snapshot_for_model -v`

Expected: PASS; unsupported tools still use bounded generic fallback, existing projections retain their current contracts.

- [ ] **Step 5: Run focused suites and commit**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_projection tests.test_agent_platform_tools -v`

Expected: PASS.

Commit:

```powershell
git add app/services/agent_tool_result_projection.py app/services/agent_tool_result_policy.py tests/test_agent_runtime.py
git commit -m "fix: preserve failure evidence in large execution results"
```

### Task 3: Progressive Execution Read Service and Tool Contract

**Files:**
- Create: `app/services/execution_diagnostic_service.py`
- Modify: `app/services/execution_record_service.py:113-261`
- Modify: `app/services/agent_tool_service.py:3095-3129`
- Modify: `app/services/agent_platform_tool_service.py:213-261,864-920`
- Create: `tests/test_execution_diagnostic_service.py`
- Modify: `tests/test_agent_platform_tools.py`

**Interfaces:**
- Consumes: Task 1 projector, existing permission service, `ExecutionRecordService.get_detail`, tool payload IDs/object references.
- Produces: `ExecutionDiagnosticService.read(*, project_id, execution_type, execution_id, query, current_user) -> ExecutionDiagnosticEnvelope`; additive `view/selector/include/cursor/limit/max_chars` tool fields.

- [ ] **Step 1: Write failing selector and legacy-compatibility tests**

```python
def test_read_failure_view_returns_first_failure_and_omissions(self):
    service = build_diagnostic_service(detail=run_220_detail_model())
    result = service.read(project_id=1, execution_type="scenario", execution_id=220, query=ExecutionDiagnosticQuery(view="failures"), current_user=user)
    self.assertEqual(result.data["first_failure"]["step_id"], "STEP-2")

def test_platform_tool_without_view_keeps_legacy_full_output(self):
    result = backend.execute(tool_name="execution.read_detail", payload={"project_id": 1, "execution_type": "scenario", "execution_id": 220}, current_user=user)
    self.assertIn("execution", result)
    self.assertIn("step_results", result["execution"]["detail"])

def test_step_view_requires_exactly_one_step_id(self):
    with self.assertRaises(HTTPException) as raised:
        backend.execute(tool_name="execution.read_detail", payload={"project_id": 1, "execution_type": "scenario", "execution_id": 220, "view": "step", "selector": {"step_ids": []}}, current_user=user)
    self.assertEqual(raised.exception.status_code, 422)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_service -v`

Expected: FAIL because the progressive read service does not exist.

- [ ] **Step 3: Implement permission-checked progressive reads without changing full detail**

```python
class ExecutionDiagnosticService:
    def __init__(self, db: Session):
        self.record_service = ExecutionRecordService(db)
        self.projector = ExecutionDiagnosticProjectionService()

    def read(self, *, project_id: int, execution_type: ExecutionType, execution_id: int, query: ExecutionDiagnosticQuery, current_user: User) -> ExecutionDiagnosticEnvelope:
        detail = self.record_service.get_detail(project_id=project_id, execution_type=execution_type, execution_id=execution_id, current_user=current_user)
        return self.projector.project(
            execution_type=execution_type,
            execution=normalize_response_data(detail),
            query=query,
        )
```

`ExecutionRecordService.get_detail` remains the full authoritative path. Do not modify its public return shape in this task.

- [ ] **Step 4: Extend and validate the Agent tool schema**

```python
"view": {"type": "string", "enum": ["summary", "failures", "steps", "step", "artifact", "full"]},
"selector": {
    "type": "object",
    "properties": {
        "statuses": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "first_failure": {"type": "boolean"},
        "step_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 200},
        "artifact_ref": {"type": "string"},
        "offset": {"type": "integer", "minimum": 0},
    },
},
"include": {"type": "array", "items": {"type": "string", "enum": ["assertions", "response_summary", "bindings", "extractors", "retries", "upstream"]},
"cursor": {"type": "string"},
"limit": {"type": "integer", "minimum": 1, "maximum": 200},
"max_chars": {"type": "integer", "minimum": 1000, "maximum": 24000},
```

In `_execution_read_detail`, if `view` is omitted, execute the current full-detail branch. If present, validate `ExecutionDiagnosticQuery.model_validate(payload_subset)` and return the envelope under `diagnostic` together with `project_id/execution_type/execution_id`.

- [ ] **Step 5: Add summary/failures/steps/step validation and project-isolation tests**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_service tests.test_agent_platform_tools -v`

Expected: PASS; `view=artifact` may return `not_available` until Task 10, but validation and project scoping are active.

- [ ] **Step 6: Commit**

```powershell
git add app/services/execution_diagnostic_service.py app/services/execution_record_service.py app/services/agent_tool_service.py app/services/agent_platform_tool_service.py tests/test_execution_diagnostic_service.py tests/test_agent_platform_tools.py
git commit -m "feat: add progressive execution diagnostic reads"
```

### Task 4: Bounded AI Diagnosis and Skill Workflow

**Files:**
- Modify: `app/services/agent_platform_tool_service.py:230-261`
- Modify: `app/services/ai_browser_capture_service.py:279-301`
- Modify: `app/schemas/ai.py:403-406`
- Modify: `app/agent_skills/execution-diagnosis/SKILL.md`
- Modify: `tests/test_agent_platform_tools.py`
- Create: `tests/test_execution_ai_diagnosis.py`

**Interfaces:**
- Consumes: Task 3 `ExecutionDiagnosticService.read` and `ExecutionDiagnosticEnvelope`.
- Produces: `AIExecutionDiagnoseRequest.evidence` containing a bounded failure/summary envelope; `execution.diagnose` never receives complete raw detail.

- [ ] **Step 1: Write the failing bounded-AI-input test**

```python
@patch("app.services.ai_browser_capture_service.AIService.chat")
def test_execution_diagnosis_sends_bounded_semantic_evidence(self, chat):
    chat.return_value = SimpleNamespace(content='{"summary":"auth failed","probable_causes":[],"evidence":[],"suggestions":[],"risk_level":"high"}', model="test")
    result = backend.execute(tool_name="execution.diagnose", payload={"project_id": 1, "execution_type": "scenario", "execution_id": 220}, current_user=user)
    request = chat.call_args.args[0]
    prompt = request.messages[1].content
    self.assertLessEqual(len(prompt), 16000)
    self.assertIn("请求未授权", prompt)
    self.assertIn("90001", prompt)
    self.assertNotIn("x" * 1000, prompt)
    self.assertEqual(result["source"], "execution.diagnostic")
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_ai_diagnosis -v`

Expected: FAIL because `_execution_diagnose` sends full `execution_data`.

- [ ] **Step 3: Replace full detail with the shared evidence envelope**

```python
evidence = ExecutionDiagnosticService(self.db).read(
    project_id=project_id,
    execution_type=execution_type,
    execution_id=execution_id,
    query=ExecutionDiagnosticQuery(view="failures", include=["assertions", "response_summary", "bindings", "upstream"], max_chars=12000),
    current_user=current_user,
)
request = AIExecutionDiagnoseRequest(
    protocol=execution_type,
    draft_data={"resource_id": evidence.data.get("resource_id"), "resource_name": evidence.data.get("resource_name")},
    evidence=evidence.model_dump(mode="json"),
)
```

Rename `execution_data` to `evidence` in the internal Pydantic request and caller. Before `AIService.chat`, serialize the full user payload and raise HTTP 422 `execution diagnostic evidence exceeds 16000 chars` if it exceeds 16,000 characters; this is a defense-in-depth assertion above the projector's 12,000-character data budget.

- [ ] **Step 4: Update the Execution Diagnosis Skill workflow**

```markdown
1. Query execution references with `execution.query_records`.
2. Read `view=summary` for the selected execution.
3. If terminal status is failed/timeout/error, read `view=failures` before replying.
4. Read `view=step` only when `diagnostic_complete=false` or the user requests exact step evidence.
5. Read `view=artifact` only for an explicit evidence reference; never request full raw output by default.
6. Call `execution.diagnose` only after deterministic evidence is available.
```

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_ai_diagnosis tests.test_agent_platform_tools tests.test_execution_diagnostic_service -v`

Expected: PASS; the captured AI prompt is bounded and contains the run-220 authorization evidence.

Commit:

```powershell
git add app/services/agent_platform_tool_service.py app/services/ai_browser_capture_service.py app/schemas/ai.py app/agent_skills/execution-diagnosis/SKILL.md tests/test_agent_platform_tools.py tests/test_execution_ai_diagnosis.py
git commit -m "fix: bound ai execution diagnosis evidence"
```

### Task 5: Additive Diagnostic Read-Model Schema

**Files:**
- Create: `app/models/execution_diagnostic.py`
- Modify: `app/models/__init__.py` using partial staging only
- Modify: `app/core/config.py`
- Create: `migrations/versions/0041_execution_diagnostic_read_models.py`
- Create: `tests/test_execution_diagnostic_migration.py`

**Interfaces:**
- Consumes: current Alembic head `0040_agent_capability_plans`.
- Produces: `ExecutionRecordIndex`, `ExecutionStepDiagnostic`, `ExecutionPayloadArtifact`, `ExecutionMetricHourly`, and `ExecutionMetricDaily` tables plus exact runtime settings.

- [ ] **Step 1: Write failing model and migration contract tests**

```python
def test_migration_is_additive_and_points_to_current_head(self):
    module = importlib.import_module("migrations.versions.0041_execution_diagnostic_read_models")
    self.assertEqual(module.down_revision, "0040_agent_capability_plans")
    source = inspect.getsource(module.upgrade)
    for table in ("execution_record_index", "execution_step_diagnostics", "execution_payload_artifacts", "execution_metrics_hourly", "execution_metrics_daily"):
        self.assertIn(table, source)
    self.assertNotIn("drop_table", source)

def test_runtime_limits_match_approved_spec(self):
    self.assertEqual(Settings().EXECUTION_DIAGNOSTIC_MODEL_MAX_CHARS, 12000)
    self.assertEqual(Settings().EXECUTION_DIAGNOSTIC_MODEL_HARD_MAX_CHARS, 24000)
    self.assertEqual(Settings().EXECUTION_ARTIFACT_INLINE_THRESHOLD_BYTES, 65536)
```

- [ ] **Step 2: Run the migration test and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_migration -v`

Expected: FAIL because revision 0041 and models do not exist.

- [ ] **Step 3: Implement the SQLAlchemy models and settings**

```python
class ExecutionRecordIndex(Base):
    __tablename__ = "execution_record_index"
    __table_args__ = (
        UniqueConstraint("project_id", "execution_type", "execution_id", name="uq_execution_record_index_identity"),
        Index("ix_execution_record_index_project_started", "project_id", "started_at", "execution_type", "execution_id"),
        Index("ix_execution_record_index_project_status_started", "project_id", "status", "started_at", "execution_id"),
        Index("ix_execution_record_index_project_env_started", "project_id", "environment_id", "started_at", "execution_id"),
        Index("ix_execution_record_index_project_failure_started", "project_id", "failure_signature", "started_at", "execution_id"),
    )
```

Use `BigInteger` for read-model primary and execution IDs, `String(32)` for protocol/status/category, `String(255)` for refs/names, JSON for summaries and `detail_json`, `LargeBinary` for compressed artifact content, and UTC-naive `DateTime` consistently with existing models. Add:

```python
EXECUTION_DIAGNOSTIC_MODEL_MAX_CHARS: int = 12000
EXECUTION_DIAGNOSTIC_MODEL_HARD_MAX_CHARS: int = 24000
EXECUTION_ARTIFACT_INLINE_THRESHOLD_BYTES: int = Field(default=65536, ge=16384, le=1048576)
EXECUTION_ARTIFACT_CHUNK_BYTES: int = Field(default=8192, ge=1024, le=65536)
EXECUTION_NORMALIZED_SCENARIO_STEPS_ENABLED: bool = False
EXECUTION_METRICS_SCHEDULER_ENABLED: bool = True
EXECUTION_METRICS_SCHEDULER_INTERVAL_SECONDS: int = Field(default=60, ge=10, le=3600)
```

- [ ] **Step 4: Implement symmetric migration 0041**

Create all five tables and the exact unique/composite indexes from the models. Downgrade order must drop metrics, artifacts, step diagnostics, and index without modifying any protocol execution table or legacy JSON column.

- [ ] **Step 5: Run migration/schema checks and partially stage the dirty model registry**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_migration -v
.venv\Scripts\alembic.exe heads
```

Expected: PASS; Alembic prints exactly `0041_execution_diagnostic_read_models (head)`.

Stage safely:

```powershell
git add app/models/execution_diagnostic.py app/core/config.py migrations/versions/0041_execution_diagnostic_read_models.py tests/test_execution_diagnostic_migration.py
git add -p app/models/__init__.py
git diff --cached -- app/models/__init__.py
```

Select only the `app.models.execution_diagnostic` import and its five `__all__` names. The cached diff must not contain `SystemTestCase` or `SystemCaseApiRelation` lines.

- [ ] **Step 6: Commit**

```powershell
git commit -m "feat: add execution diagnostic read models"
```

### Task 6: Diagnostic Repository, Idempotent Persistence, and History Backfill

**Files:**
- Create: `app/repositories/execution_diagnostic_repository.py`
- Create: `app/services/execution_diagnostic_persistence.py`
- Create: `scripts/backfill_execution_diagnostics.py`
- Create: `tests/test_execution_diagnostic_storage.py`

**Interfaces:**
- Consumes: Task 5 models, Task 1 canonical projectors/signatures, existing protocol detail dictionaries.
- Produces: `ExecutionDiagnosticPersistence.stage_execution(*, project_id: int, execution_type: ExecutionType, execution_id: int, execution: dict[str, Any]) -> None`, `stage_step(*, project_id: int, execution_type: ExecutionType, execution_id: int, step: dict[str, Any], fallback_index: int) -> None`, project-scoped reads, batch backfill with stable checkpoints, and idempotent upserts. Both staging methods are commit-free.

- [ ] **Step 1: Write failing idempotence and no-commit tests**

```python
def test_stage_execution_is_idempotent_and_does_not_commit(self):
    persistence = ExecutionDiagnosticPersistence(db)
    persistence.stage_execution(project_id=1, execution_type="scenario", execution_id=220, execution=run_220_shape())
    persistence.stage_execution(project_id=1, execution_type="scenario", execution_id=220, execution=run_220_shape())
    self.assertEqual(repository.count_indexes(project_id=1, execution_type="scenario", execution_id=220), 1)
    db.commit.assert_not_called()

def test_step_identity_is_project_scoped(self):
    repository.upsert_step(step_record(project_id=1, execution_id=220, step_id="STEP-2"))
    self.assertIsNone(repository.get_step(project_id=2, execution_type="scenario", execution_id=220, step_id="STEP-2"))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_storage -v`

Expected: FAIL because repository and persistence modules do not exist.

- [ ] **Step 3: Implement dialect-aware idempotent upserts**

```python
class ExecutionDiagnosticRepository:
    def upsert_execution_index(self, values: dict[str, Any]) -> None:
        statement = mysql_insert(ExecutionRecordIndex).values(**values)
        updates = {key: statement.inserted[key] for key in values if key not in {"id", "created_at"}}
        self.db.execute(statement.on_duplicate_key_update(**updates))

    def upsert_step(self, values: dict[str, Any]) -> None:
        statement = mysql_insert(ExecutionStepDiagnostic).values(**values)
        updates = {key: statement.inserted[key] for key in values if key not in {"id", "created_at"}}
        self.db.execute(statement.on_duplicate_key_update(**updates))
```

Provide a SQLite/test fallback using select-then-update so unit tests do not require MySQL. Repository methods may `flush()` when an ID is required but must never call `commit()`.

- [ ] **Step 4: Implement staging and resumable backfill**

```python
class ExecutionDiagnosticPersistence:
    def stage_execution(self, *, project_id: int, execution_type: ExecutionType, execution_id: int, execution: dict[str, Any]) -> None:
        canonical = self.projector.canonicalize(execution_type=execution_type, execution=execution)
        self.repository.upsert_execution_index(self._index_values(project_id=project_id, canonical=canonical, execution=execution))
        for step in canonical.steps:
            self.repository.upsert_step(self._step_values(project_id=project_id, canonical=canonical, step=step))

    def stage_step(self, *, project_id: int, execution_type: ExecutionType, execution_id: int, step: dict[str, Any], fallback_index: int) -> None:
        canonical_step = self.projector.canonicalize_step(execution_type=execution_type, step=step, fallback_index=fallback_index)
        self.repository.upsert_step(self._single_step_values(project_id=project_id, execution_type=execution_type, execution_id=execution_id, step=canonical_step))
```

Implement `_index_values`, `_step_values`, and `_single_step_values` as private pure mapping methods in the same class; their outputs use the exact Task 5 column names and `projection_version="execution_diagnostic_projection_v1"`. The backfill CLI accepts `--project-id`, `--execution-type`, `--after-id`, `--batch-size` (default 500), `--dry-run`, and `--restore-legacy-snapshots`. It processes ascending IDs, commits once per batch, prints the last committed ID, and can be rerun without duplicates.

- [ ] **Step 5: Test dry-run, resume, and duplicate replay**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_storage -v`

Expected: PASS; dry-run writes zero rows, duplicate replay keeps one index/step row, and a resumed batch starts strictly after the last committed ID.

- [ ] **Step 6: Commit**

```powershell
git add app/repositories/execution_diagnostic_repository.py app/services/execution_diagnostic_persistence.py scripts/backfill_execution_diagnostics.py tests/test_execution_diagnostic_storage.py
git commit -m "feat: persist execution diagnostic projections"
```

### Task 7: Scenario Dual-Write Inside Existing Event Transactions

**Files:**
- Modify: `app/services/scenario_service.py:648-890,1509-1628`
- Modify: `tests/test_scenario_realtime_events.py`
- Modify: `tests/test_scenario_semantics.py`
- Create: `tests/test_execution_diagnostic_write_paths.py`

**Interfaces:**
- Consumes: Task 6 `ExecutionDiagnosticPersistence.stage_execution/stage_step`; existing `_append_event` commit boundary.
- Produces: running/completed/skipped scenario step rows and run index updates without additional commits; legacy `run.step_results` remains active in this task.

- [ ] **Step 1: Write failing transaction-boundary and SSE tests**

```python
def test_scenario_step_projection_reuses_event_commit(self):
    service = build_scenario_service_with_counting_session()
    service._persist_step_result(run, [failed_step()], {}, {}, [], 1)
    service._append_event(run, 1, "step_failed", {"step_id": "STEP-2"})
    self.assertEqual(service.db.commit.call_count, 1)
    service.diagnostic_persistence.stage_step.assert_called_once()

def test_dual_write_does_not_change_event_sequence_or_payload(self):
    events = execute_two_step_scenario_with_events()
    self.assertEqual([item.sequence for item in events], list(range(1, len(events) + 1)))
    self.assertEqual(events[-1].event, "run_failed")
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_write_paths tests.test_scenario_realtime_events -v`

Expected: FAIL because scenario execution does not stage diagnostic rows.

- [ ] **Step 3: Stage running and terminal step records before existing commits**

```python
def _persist_step_result(self, run, results, variables, variable_sources, pending_steps, pending_start_index):
    run.step_results = [
        *copy.deepcopy(results),
        *[
            self._pending_result(step, index)
            for index, step in enumerate(pending_steps, start=pending_start_index)
        ],
    ]
    run.variables_snapshot = self._masked_variables_snapshot(variables, variable_sources)
    if results:
        self.diagnostic_persistence.stage_step(
            project_id=run.project_id,
            execution_type="scenario",
            execution_id=run.id,
            step=results[-1],
            fallback_index=len(results) - 1,
        )
```

In `on_step_started`, call the same `stage_step` signature for the running row before `_append_event`; for skipped results, call it before the existing `step_skipped` event commit. Add `ScenarioService._diagnostic_execution_view(run: TestScenarioRun, results: list[dict[str, Any]]) -> dict[str, Any]`, returning `{"summary": {"id": f"scenario:{run.id}", "status": run.status, "duration_ms": run.duration_ms, "resource_id": run.scenario_id, "environment_id": run.environment_id}, "detail": {"step_results": copy.deepcopy(results)}}` without querying the database. At terminal status, call `stage_execution(project_id=run.project_id, execution_type="scenario", execution_id=run.id, execution=self._diagnostic_execution_view(run, results))` before `run_completed/run_failed` commits. Do not add a `commit()` or `flush()` in persistence calls.

- [ ] **Step 4: Cover queued-user/context failures and retry replay**

Stage the failed run index in `_fail_queued_execution` before its existing final commit. Upserts must tolerate the same terminal result being replayed.

- [ ] **Step 5: Run scenario and diagnostic suites**

Run: `.venv\Scripts\python.exe -m unittest tests.test_scenario_realtime_events tests.test_scenario_semantics tests.test_execution_diagnostic_write_paths -v`

Expected: PASS; event sequences, event names, step payloads, status, and commit counts remain unchanged.

- [ ] **Step 6: Commit**

```powershell
git add app/services/scenario_service.py tests/test_scenario_realtime_events.py tests/test_scenario_semantics.py tests/test_execution_diagnostic_write_paths.py
git commit -m "feat: dual write scenario diagnostic steps"
```

### Task 8: HTTP, WebSocket, and Flow Dual-Write Without Extra Commits

**Files:**
- Modify: `app/repositories/test_case_repository.py:220-267`
- Modify: `app/repositories/websocket_test_case_repository.py:129-140`
- Modify: `app/repositories/visual_flow_repository.py:195-256`
- Modify: `app/services/test_case_service.py:348-554`
- Modify: `app/services/websocket_test_case_service.py:210-365`
- Modify: `app/services/visual_flow_service.py:318-432`
- Modify: `tests/test_execution_diagnostic_write_paths.py`
- Modify: `tests/test_step_retry.py`

**Interfaces:**
- Consumes: Task 6 persistence and existing repository create/finish methods.
- Produces: protocol index/step rows staged in the same commit as each existing execution or node write.

- [ ] **Step 1: Write failing per-protocol commit-count tests**

```python
def test_http_terminal_projection_adds_no_commit(self):
    execution = service._execute(project_id=1, test_case_id=7, payload=http_payload(), current_user=user)
    self.assertEqual(counting_db.commit_count, baseline_http_commit_count)
    assert_index_matches(execution, "http")

def test_flow_node_projection_reuses_node_commit(self):
    execution = execute_two_node_flow()
    self.assertEqual(counting_db.commit_count, baseline_flow_commit_count)
    self.assertEqual(repository.count_steps("flow", execution.id), 2)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_write_paths -v`

Expected: FAIL because protocol services do not stage index/step rows.

- [ ] **Step 3: Add optional repository commit control**

```python
def _finish_write(self, entity: Any, *, commit: bool) -> None:
    if commit:
        self.db.commit()
        self.db.refresh(entity)
    else:
        self.db.flush()

def create_execution(self, *, project_id: int, test_case_id: int | None, environment_id: int | None, scenario_run_id: int | None, executed_by_id: int, status: str, request_snapshot: dict, response_snapshot: dict | None, assertion_results: list | None, attempt_history: list | None, error_message: str | None, duration_ms: int | None, trigger_source: str = "manual", agent_run_id: str | None = None, agent_tool_call_id: str | None = None, trigger_tool_name: str | None = None, commit: bool = True) -> TestCaseExecution:
    execution = TestCaseExecution(
        project_id=project_id,
        test_case_id=test_case_id,
        environment_id=environment_id,
        scenario_run_id=scenario_run_id,
        executed_by_id=executed_by_id,
        status=status,
        request_snapshot=request_snapshot,
        response_snapshot=response_snapshot,
        assertion_results=assertion_results,
        attempt_history=attempt_history,
        error_message=error_message,
        duration_ms=duration_ms,
        trigger_source=trigger_source,
        agent_run_id=agent_run_id,
        agent_tool_call_id=agent_tool_call_id,
        trigger_tool_name=trigger_tool_name,
    )
    self.db.add(execution)
    if test_case_id is not None:
        self.db.execute(update(TestCase).where(TestCase.id == test_case_id, TestCase.project_id == project_id).values(last_execution_status=status, last_executed_at=func.now()))
    self._finish_write(execution, commit=commit)
    return execution
```

Add the same `_finish_write(entity, commit)` helper separately to `WebSocketTestCaseRepository` and `VisualFlowRepository`. Add keyword-only `commit: bool = True` to `WebSocketTestCaseRepository.create_execution`, `VisualFlowRepository.create_execution`, `create_node_execution`, and `finish_execution`; replace each current direct `commit/refresh` pair with `_finish_write`. Existing callers remain compatible. Coordinating service paths call with `commit=False`, stage diagnostics, then perform the one existing commit and refresh.

- [ ] **Step 4: Integrate queued, synchronous, exception, retry, and Flow node paths**

For queued execution updates, stage diagnostics immediately before the existing commit. For synchronous creation, create with `commit=False`, stage the index/logical step, then commit once. For Flow, create each node with `commit=False`, stage the node diagnostic, and commit once at the existing node boundary; finish index staging before the existing final commit.

- [ ] **Step 5: Run focused protocol suites**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_write_paths tests.test_step_retry tests.test_execution_records -v`

Expected: PASS; retries, assertion results, durations, queue states, and existing details remain identical.

- [ ] **Step 6: Commit**

```powershell
git add app/repositories/test_case_repository.py app/repositories/websocket_test_case_repository.py app/repositories/visual_flow_repository.py app/services/test_case_service.py app/services/websocket_test_case_service.py app/services/visual_flow_service.py tests/test_execution_diagnostic_write_paths.py tests/test_step_retry.py
git commit -m "feat: index protocol execution diagnostics"
```

### Task 9: Index-Backed Cursor Queries and Optional Exact Counts

**Files:**
- Modify: `app/schemas/execution_record.py`
- Modify: `app/repositories/execution_diagnostic_repository.py`
- Modify: `app/repositories/execution_record_repository.py:122-175`
- Modify: `app/services/execution_record_service.py:62-112`
- Modify: `app/api/v1/routers/execution_records.py`
- Modify: `app/services/agent_tool_service.py:3095-3108`
- Modify: `app/services/agent_platform_tool_service.py:152-211`
- Modify: `tests/test_execution_records.py`
- Modify: `tests/test_agent_platform_tools.py`
- Create: `tests/test_execution_diagnostic_scaling.py`

**Interfaces:**
- Consumes: Task 5 index rows and Task 6 project-scoped repository.
- Produces: versioned cursor codec, `ExecutionRecordCursorPage`, explicit `pagination_mode`, and `include_total` without removing legacy page mode.

- [ ] **Step 1: Write failing stable-cursor and no-count tests**

```python
def test_cursor_page_is_stable_when_newer_record_arrives(self):
    first = service.list_records_cursor(project_id=1, limit=2, cursor=None, include_total=False, current_user=user)
    insert_newer_execution_index()
    second = service.list_records_cursor(project_id=1, limit=2, cursor=first.next_cursor, include_total=False, current_user=user)
    self.assertTrue(set(item.id for item in first.items).isdisjoint(item.id for item in second.items))

def test_cursor_page_skips_exact_count_by_default(self):
    service.list_records_cursor(project_id=1, limit=50, cursor=None, include_total=False, current_user=user)
    repository.count_records.assert_not_called()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_scaling -v`

Expected: FAIL because cursor list APIs do not exist.

- [ ] **Step 3: Implement a strict versioned cursor**

```python
@dataclass(frozen=True)
class ExecutionCursor:
    started_at: datetime
    execution_type: str
    execution_id: int

def encode_cursor(value: ExecutionCursor) -> str:
    payload = {"v": 1, "started_at": value.started_at.isoformat(), "execution_type": value.execution_type, "execution_id": value.execution_id}
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
```

Decode with size limit 512, version check, ISO datetime validation, allowed execution type, positive ID, and HTTP 422 on malformed input. Cursor query orders by `started_at DESC, execution_type ASC, execution_id DESC` and applies a lexicographically equivalent continuation predicate.

```python
continuation = or_(
    ExecutionRecordIndex.started_at < cursor.started_at,
    and_(
        ExecutionRecordIndex.started_at == cursor.started_at,
        ExecutionRecordIndex.execution_type > cursor.execution_type,
    ),
    and_(
        ExecutionRecordIndex.started_at == cursor.started_at,
        ExecutionRecordIndex.execution_type == cursor.execution_type,
        ExecutionRecordIndex.execution_id < cursor.execution_id,
    ),
)
```

- [ ] **Step 4: Add explicit cursor mode without changing legacy paging**

Public/API tool inputs add:

```json
{
  "pagination_mode": "cursor",
  "cursor": null,
  "limit": 50,
  "include_total": false
}
```

When `pagination_mode` is omitted or `page`, execute the existing `UNION ALL + page + total` path and preserve the response. Cursor mode reads `execution_record_index`, returns `items/returned/has_more/next_cursor/total`, and computes `total` only when requested.

- [ ] **Step 5: Run query, OpenAPI, and Agent tool tests**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_scaling tests.test_execution_records tests.test_agent_platform_tools -v`

Expected: PASS; existing page-mode tests remain unchanged and cursor mode does not call count by default.

- [ ] **Step 6: Commit**

```powershell
git add app/schemas/execution_record.py app/repositories/execution_diagnostic_repository.py app/repositories/execution_record_repository.py app/services/execution_record_service.py app/api/v1/routers/execution_records.py app/services/agent_tool_service.py app/services/agent_platform_tool_service.py tests/test_execution_records.py tests/test_agent_platform_tools.py tests/test_execution_diagnostic_scaling.py
git commit -m "feat: add cursor execution history queries"
```

### Task 10: Database Artifact Store and Chunked Evidence Reads

**Files:**
- Create: `app/services/execution_payload_store.py`
- Modify: `app/repositories/execution_diagnostic_repository.py`
- Modify: `app/services/execution_diagnostic_persistence.py`
- Modify: `app/services/execution_diagnostic_service.py`
- Modify: `tests/test_execution_diagnostic_storage.py`
- Modify: `tests/test_execution_diagnostic_service.py`

**Interfaces:**
- Consumes: Task 5 artifact table/settings and project-scoped execution identities.
- Produces: `ArtifactChunk`, `DatabaseExecutionPayloadStore.put(*, project_id: int, execution_type: ExecutionType, execution_id: int, step_id: str | None, section: str, value: Any) -> str`, `read_chunk(*, project_id: int, artifact_ref: str, offset: int, max_bytes: int) -> ArtifactChunk`, `read_all(*, project_id: int, artifact_ref: str) -> Any`, and normalized `detail_json + artifact refs`.

- [ ] **Step 1: Write failing compression, integrity, and isolation tests**

```python
def test_large_response_is_externalized_and_round_trips_by_chunk(self):
    ref = store.put(project_id=1, execution_type="scenario", execution_id=220, step_id="STEP-1", section="response", value={"body": "x" * 100000})
    chunk = store.read_chunk(project_id=1, artifact_ref=ref, offset=0, max_bytes=8192)
    self.assertEqual(chunk.offset, 0)
    self.assertTrue(chunk.has_more)
    self.assertEqual(chunk.sha256, repository.get_artifact(ref).sha256)

def test_artifact_is_hidden_from_other_projects(self):
    with self.assertRaises(HTTPException) as raised:
        store.read_chunk(project_id=2, artifact_ref=ref, offset=0, max_bytes=8192)
    self.assertEqual(raised.exception.status_code, 404)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_storage -v`

Expected: FAIL because the payload store does not exist.

- [ ] **Step 3: Implement deterministic redacted gzip storage**

```python
class ArtifactChunk(BaseModel):
    artifact_ref: str
    offset: int
    next_offset: int | None
    has_more: bool
    raw_size_bytes: int
    sha256: str
    content: str

def put(self, *, project_id: int, execution_type: str, execution_id: int, step_id: str | None, section: str, value: Any) -> str:
    redacted = mask_sensitive(value)
    raw = json.dumps(redacted, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    artifact_ref = f"execution-artifact://{project_id}/{execution_type}/{execution_id}/{digest[:24]}"
    compressed = gzip.compress(raw, compresslevel=6, mtime=0)
    self.repository.upsert_artifact(artifact_ref=artifact_ref, project_id=project_id, execution_type=execution_type, execution_id=execution_id, step_id=step_id, section=section, content_blob=compressed, raw_size_bytes=len(raw), stored_size_bytes=len(compressed), sha256=digest, encoding="gzip+json", redaction_version="sensitive_data_v1")
    return artifact_ref
```

`read_chunk` verifies project ownership, decompresses, verifies sha256, returns a UTF-8-safe slice with `offset/next_offset/has_more/raw_size_bytes/sha256`, and caps `max_bytes` at 65,536. `read_all` verifies the same checksum, decodes the complete JSON value, and is callable only from the permission-checked full-detail compatibility path; Agent tools never call it.

- [ ] **Step 4: Externalize oversized scenario sections during staging**

Before writing `detail_json`, inspect request, response, logs/messages, and retries independently. Values above `EXECUTION_ARTIFACT_INLINE_THRESHOLD_BYTES` are stored and replaced with:

```json
{"artifact_ref":"execution-artifact://1/scenario/220/abc","raw_size_bytes":100011,"externalized":true}
```

Small redacted normalized step content remains inline. The normal projector only returns response summaries and evidence refs.

- [ ] **Step 5: Activate `view=artifact` and omissions**

`ExecutionDiagnosticService.read` validates `artifact_ref` belongs to the requested project/execution, returns one bounded chunk, and includes the next offset. `view=summary/failures/step` returns `artifact_externalized` omissions and refs without reading the blob.

- [ ] **Step 6: Run focused tests and commit**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_storage tests.test_execution_diagnostic_service -v`

Expected: PASS, including sha256, compression, chunk continuation, UTF-8 boundary, missing artifact, and cross-project tests.

Commit:

```powershell
git add app/services/execution_payload_store.py app/repositories/execution_diagnostic_repository.py app/services/execution_diagnostic_persistence.py app/services/execution_diagnostic_service.py tests/test_execution_diagnostic_storage.py tests/test_execution_diagnostic_service.py
git commit -m "feat: add chunked execution evidence artifacts"
```

### Task 11: Failure Clusters and Hourly/Daily Rollups

**Files:**
- Create: `app/services/execution_metrics_service.py`
- Create: `app/services/execution_metrics_scheduler.py`
- Create: `scripts/rebuild_execution_metrics.py`
- Modify: `app/main.py`
- Modify: `app/services/agent_tool_service.py`
- Modify: `app/services/agent_platform_tool_service.py`
- Modify: `app/agent_skills/execution-diagnosis/SKILL.md`
- Create: `tests/test_execution_metrics.py`
- Modify: `tests/test_agent_platform_tools.py`

**Interfaces:**
- Consumes: indexed failure signatures/durations and existing app lifecycle hooks.
- Produces: idempotent `rebuild_bucket`, `query_failure_clusters`, `query_metrics`, watermark-bearing query views, and an isolated scheduler.

- [ ] **Step 1: Write failing deterministic aggregation tests**

```python
def test_failure_cluster_counts_signatures_not_raw_records(self):
    seed_index_rows(signature="AUTHORIZATION_HTTP_200_BUSINESS_90001_JSON_EQUALS_CODE", count=3)
    clusters = service.query_failure_clusters(project_id=1, started_from=hour_start, started_to=hour_end, limit=20)
    self.assertEqual(clusters[0]["count"], 3)
    self.assertLessEqual(len(clusters[0]["sample_execution_refs"]), 5)

def test_rebuild_bucket_is_idempotent(self):
    service.rebuild_hour(project_id=1, bucket=hour_start)
    service.rebuild_hour(project_id=1, bucket=hour_start)
    self.assertEqual(repository.count_hourly_rows(project_id=1, bucket=hour_start), expected_group_count)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_metrics -v`

Expected: FAIL because metrics service and scheduler do not exist.

- [ ] **Step 3: Implement recomputed buckets and bounded representative samples**

`rebuild_hour` deletes/replaces only one project-hour inside one transaction using grouped index queries. `rebuild_day` derives from hourly rows. Cluster queries group by `failure_signature`, count executions and distinct resource IDs, return first/last timestamps, and fetch at most five newest execution refs per group. Empty signatures are excluded from failure clusters.

- [ ] **Step 4: Add explicit query views to `execution.query_records`**

Extend tool input with `result_view: records|failure_clusters|metrics` (default `records`). `failure_clusters` and `metrics` require `started_from/started_to`, default limit 20, never return raw execution payloads, and include `watermark` from the latest indexed source timestamp.

- [ ] **Step 5: Add the isolated lifecycle scheduler and CLI**

```python
class ExecutionMetricsScheduler:
    def start(self) -> None:
        if not settings.EXECUTION_METRICS_SCHEDULER_ENABLED or self._thread is not None:
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="execution-metrics-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
```

Register start/stop alongside the existing scheduler in `app/main.py`. Each iteration opens its own `SessionLocal`, recomputes recently changed buckets idempotently, logs failures, and never calls execution services or changes execution status.

- [ ] **Step 6: Run metrics, lifecycle, and tool tests and commit**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_metrics tests.test_agent_platform_tools -v`

Expected: PASS; scheduler failure leaves execution tables untouched and cluster output remains bounded.

Commit:

```powershell
git add app/services/execution_metrics_service.py app/services/execution_metrics_scheduler.py scripts/rebuild_execution_metrics.py app/main.py app/services/agent_tool_service.py app/services/agent_platform_tool_service.py app/agent_skills/execution-diagnosis/SKILL.md tests/test_execution_metrics.py tests/test_agent_platform_tools.py
git commit -m "feat: add execution failure clusters and rollups"
```

### Task 12: Scenario Normalized-Step Cutover and Compatibility Assembly

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/services/scenario_service.py:500-610,648-890,1555-1575`
- Modify: `app/services/execution_record_service.py:194-225`
- Modify: `app/repositories/execution_diagnostic_repository.py`
- Modify: `app/services/execution_diagnostic_service.py`
- Modify: `scripts/backfill_execution_diagnostics.py`
- Modify: `tests/test_execution_diagnostic_scaling.py`
- Modify: `tests/test_scenario_realtime_events.py`
- Modify: `tests/test_execution_records.py`

**Interfaces:**
- Consumes: dual-written scenario `detail_json + artifact refs`, scenario snapshot ordering, Task 10 artifact reads.
- Produces: `assemble_scenario_step_results`, normalized running/full detail, linear writes, and environment rollback switch.

- [ ] **Step 1: Write failing compatibility and 10,000-step linearity tests**

```python
def test_normalized_steps_assemble_legacy_contract(self):
    result = service.assemble_scenario_step_results(project_id=1, execution_id=220, include_artifacts=True)
    self.assertEqual(result[0]["name"], "获取企业列表")
    self.assertEqual(result[2]["assertion_results"][1]["actual"], 90001)

def test_ten_thousand_steps_do_not_rewrite_growing_run_json(self):
    run = scenario_run(step_results=[])
    for index in range(10000):
        scenario_service._persist_step_result_normalized(run, completed_step(index))
    self.assertEqual(diagnostic_repository.upsert_step.call_count, 10000)
    self.assertEqual(run.step_results, [])
    self.assertEqual(db.commit.call_count, 0)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_scaling -v`

Expected: FAIL because the compatibility assembler and normalized write path do not exist.

- [ ] **Step 3: Implement ordered compatibility assembly**

```python
def assemble_scenario_step_results(self, *, project_id: int, execution_id: int, scenario_snapshot: dict[str, Any], include_artifacts: bool) -> list[dict[str, Any]]:
    rows = self.repository.list_all_steps(project_id=project_id, execution_type="scenario", execution_id=execution_id)
    by_step_id = {row.step_id: self._hydrate_step_detail(row, include_artifacts=include_artifacts) for row in rows}
    ordered = self._scenario_step_descriptors(scenario_snapshot)
    return [by_step_id.get(item["step_id"], self._pending_step_from_descriptor(item)) for item in ordered]

def _hydrate_step_detail(self, row: ExecutionStepDiagnostic, *, include_artifacts: bool) -> dict[str, Any]:
    detail = copy.deepcopy(row.detail_json or {})
    if include_artifacts:
        for field, artifact_ref in (("request_snapshot", row.request_artifact_ref), ("response_snapshot", row.response_artifact_ref)):
            if artifact_ref:
                detail[field] = self.payload_store.read_all(project_id=row.project_id, artifact_ref=artifact_ref)
    return detail

def _pending_step_from_descriptor(self, descriptor: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_id": descriptor["step_id"],
        "step_index": descriptor["step_index"],
        "kind": descriptor["kind"],
        "name": descriptor["name"],
        "node_id": descriptor.get("node_id"),
        "node_index": descriptor.get("node_index"),
        "node_phase": descriptor.get("node_phase"),
        "status": "pending",
        "extracted_variables": [],
        "resolved_bindings": [],
        "attempt_history": [],
    }
```

Implement `_scenario_step_descriptors(scenario_snapshot)` by reusing the existing scenario execution-order rules and returning dictionaries with `step_id/step_index/kind/name/node_id/node_index/node_phase`. Explicit completed/skipped/running rows override generated pending rows. Hydration restores request/response/retry sections from artifacts only for full REST detail; Agent diagnostic views keep references. Task 10's `DatabaseExecutionPayloadStore.read_all` is the only full-artifact API used here.

- [ ] **Step 4: Switch scenario hot writes behind the rollback flag**

When `EXECUTION_NORMALIZED_SCENARIO_STEPS_ENABLED` is true, `_persist_step_result` stages only the changed step and variables/run summary; it does not assign the growing history to `run.step_results`. `ScenarioService.get_run_detail` and `ExecutionRecordService._get_scenario_detail` assemble from normalized steps. When false, retain the Task 7 dual-write path.

After compatibility and load tests pass, change the default setting to:

```python
EXECUTION_NORMALIZED_SCENARIO_STEPS_ENABLED: bool = True
```

- [ ] **Step 5: Implement rollback snapshot restoration**

`scripts/backfill_execution_diagnostics.py --restore-legacy-snapshots` assembles normalized steps, writes the redacted/reference-based list back to `TestScenarioRun.step_results`, commits in batches, and is idempotent. This command is the prerequisite before disabling normalized reads in a rollback after new-format executions exist.

- [ ] **Step 6: Run scaling, scenario, and detail compatibility suites**

Run: `.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_scaling tests.test_scenario_realtime_events tests.test_scenario_semantics tests.test_execution_records -v`

Expected: PASS; 10,000 steps use 10,000 bounded upserts, no growing JSON assignment, and existing detail/SSE semantics remain equivalent.

- [ ] **Step 7: Commit**

```powershell
git add app/core/config.py app/services/scenario_service.py app/services/execution_record_service.py app/repositories/execution_diagnostic_repository.py app/services/execution_diagnostic_service.py scripts/backfill_execution_diagnostics.py tests/test_execution_diagnostic_scaling.py tests/test_scenario_realtime_events.py tests/test_execution_records.py
git commit -m "perf: normalize scenario step result persistence"
```

### Task 13: Documentation, Migration Exercise, Full Verification, and Run-220 Acceptance

**Files:**
- Modify: `docs/api_execution_records.md`
- Modify: `docs/api_agent_frontend_contract.md`
- Modify: `docs/technical_architecture.md`
- Modify: `docs/scenario-run-detail-contract.md`
- Modify: `docs/README.md` using partial staging only
- Test: all focused and full repository suites

**Interfaces:**
- Consumes: completed Tasks 1-12.
- Produces: synchronized public/Agent contracts, verified migration path, full regression evidence, and a repeatable run-220 acceptance fixture.

- [ ] **Step 1: Update exact API and architecture contracts**

Document:

- legacy page mode and new cursor mode;
- `summary/failures/steps/step/artifact/full` views;
- selector/include/budget validation;
- omissions, evidence refs, cursor, completeness, and watermark;
- unified index, step diagnostics, artifact storage, failure signatures, rollups, and compatibility assembly;
- frontend behavior: full detail remains available, while Agent cards should render diagnostic envelope metadata and artifact continuation affordances;
- rollback command and the normalized-step environment switch.

In `docs/README.md`, add links only through `git add -p`; preserve the existing uncommitted system-test-case documentation changes.

- [ ] **Step 2: Run documentation and static contract checks**

Run:

```powershell
git diff --check
.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_migration tests.test_execution_records tests.test_agent_platform_tools -v
```

Expected: no whitespace errors; all contract tests PASS.

- [ ] **Step 3: Exercise migration symmetry on a disposable database**

Run with a disposable MySQL schema configured through `DATABASE_URL`:

```powershell
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\alembic.exe downgrade 0040_agent_capability_plans
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\alembic.exe heads
```

Expected: upgrade/downgrade/upgrade succeeds; the final command prints only `0041_execution_diagnostic_read_models (head)`.

- [ ] **Step 4: Run focused execution/Agent suites**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_execution_diagnostic_projection tests.test_execution_diagnostic_service tests.test_execution_ai_diagnosis tests.test_execution_diagnostic_storage tests.test_execution_diagnostic_write_paths tests.test_execution_diagnostic_scaling tests.test_execution_metrics tests.test_execution_records tests.test_agent_platform_tools tests.test_scenario_realtime_events tests.test_scenario_semantics tests.test_step_retry -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run the complete repository suite**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -v`

Expected: all tests PASS. If the unrelated uncommitted system-test-case work causes a failure, report it separately and do not modify or commit those files as part of this plan.

- [ ] **Step 6: Verify run-220 acceptance facts and budgets**

Run the deterministic fixture and, when the local record still exists, compare it with database execution 220:

```python
assert result.data["first_failure"]["name"] == "获取对应企业CT画像数"
assert result.data["first_failure"]["response"]["status_code"] == 200
assert result.data["first_failure"]["response"]["business_code"] == 90001
assert result.data["first_failure"]["response"]["message"] == "请求未授权"
assert result.data["first_failure"]["assertions"][1]["expected"] == 200
assert result.data["first_failure"]["assertions"][1]["actual"] == 90001
assert result.data["first_failure"]["bindings"] == []
assert len(result.model_dump_json()) <= 12000
```

Expected: all assertions pass; the Agent no longer reports variable binding as the confirmed root cause.

- [ ] **Step 7: Review staged documentation hunks and commit**

```powershell
git add docs/api_execution_records.md docs/api_agent_frontend_contract.md docs/technical_architecture.md docs/scenario-run-detail-contract.md
git add -p docs/README.md
git diff --cached --check
git commit -m "docs: document scalable execution diagnostics"
```

The cached `docs/README.md` diff must include only the execution diagnostics links added by this task.

---

## Spec Coverage Matrix

| Approved spec requirement | Implemented and verified by |
| --- | --- |
| Run-220 evidence and semantic-priority root cause | Tasks 1, 2, 4, 13 |
| 12,000 default / 24,000 hard model budget | Tasks 1, 2, 3, 4 |
| No silent truncation; omissions and continuation | Tasks 1, 3, 10 |
| Full ledger and legacy full-detail compatibility | Tasks 2, 3, 10, 12 |
| HTTP/WebSocket/scenario/Flow projector coverage | Tasks 1, 8 |
| Main index and incremental step diagnostics | Tasks 5, 6, 7, 8 |
| Small `detail_json` and large artifact references | Tasks 5, 10, 12 |
| Project-scoped gzip/checksum/chunk reads | Task 10 |
| Cursor paging and optional exact counts | Task 9 |
| Deterministic failure signatures and clusters | Tasks 1, 11 |
| Hourly/daily rollups with watermark | Task 11 |
| No changed worker, status, retry, approval, or SSE semantics | Tasks 7, 8, 12, 13 |
| Dual-write, history backfill, and rollback restore | Tasks 6, 7, 8, 12 |
| Stop scenario history rewrite amplification | Task 12 |
| Migration symmetry and documentation synchronization | Tasks 5, 13 |

Self-review result: every approved spec section has an owning task and a named verification command; no separate subsystem remains outside this plan.

---

## Completion Checklist

- [ ] Run 220 is diagnosed from current evidence as authorization/business-code failure, not inferred binding failure.
- [ ] Large successful output cannot displace first-failure evidence.
- [ ] Model-facing execution evidence respects 12,000 default and 24,000 hard limits.
- [ ] Omitted data always has an omission record, cursor, or artifact reference.
- [ ] Legacy full detail, page mode, permissions, approvals, workers, status transitions, and SSE remain compatible.
- [ ] HTTP, WebSocket, scenario, and Flow all write/read diagnostic projections.
- [ ] Cursor queries skip exact counts unless requested and remain stable under inserts.
- [ ] Failure clusters and rollups are deterministic, bounded, idempotent, and watermark-bearing.
- [ ] Oversized artifacts are redacted, compressed, checksummed, chunk-readable, and project-isolated.
- [ ] Scenario writes are linear at 10,000 steps and no longer rewrite growing history JSON.
- [ ] Migration symmetry, focused suites, and the complete repository suite pass.
- [ ] Documentation is synchronized without committing unrelated dirty files.
