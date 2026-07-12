from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.execution_record import ExecutionType


ExecutionDiagnosticView = Literal[
    "summary", "failures", "steps", "step", "artifact", "full"
]
ExecutionDiagnosticInclude = Literal[
    "assertions",
    "response_summary",
    "bindings",
    "extractors",
    "retries",
    "upstream",
]


class ExecutionDiagnosticSelector(BaseModel):
    statuses: list[str] = Field(default_factory=list, max_length=8)
    first_failure: bool = False
    step_ids: list[str] = Field(default_factory=list, max_length=200)
    artifact_ref: str | None = Field(default=None, max_length=128)
    offset: int = Field(default=0, ge=0)


class ExecutionDiagnosticQuery(BaseModel):
    view: ExecutionDiagnosticView = "full"
    selector: ExecutionDiagnosticSelector = Field(
        default_factory=ExecutionDiagnosticSelector
    )
    include: list[ExecutionDiagnosticInclude] = Field(default_factory=list, max_length=8)
    cursor: str | None = Field(default=None, max_length=512)
    limit: int = Field(default=20, ge=1, le=200)
    max_chars: int = Field(default=12000, ge=1000, le=24000)

    @model_validator(mode="after")
    def validate_view_selector(self):
        if self.view == "step" and len(self.selector.step_ids) != 1:
            raise ValueError("view=step requires exactly one selector.step_ids value")
        if self.view == "artifact" and not self.selector.artifact_ref:
            raise ValueError("view=artifact requires selector.artifact_ref")
        if self.view == "failures" and not self.selector.statuses:
            self.selector.statuses = ["failed", "timeout", "error"]
        return self


class DiagnosticOmission(BaseModel):
    section: str
    reason: Literal[
        "budget_exceeded", "not_requested", "artifact_externalized", "not_available"
    ]
    reference: str | None = None


class DiagnosticPage(BaseModel):
    next_cursor: str | None = None
    has_more: bool = False


class ExecutionDiagnosticEnvelope(BaseModel):
    schema_version: Literal["execution_diagnostic_v1"] = "execution_diagnostic_v1"
    projection_version: Literal[
        "execution_diagnostic_projection_v1"
    ] = "execution_diagnostic_projection_v1"
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
