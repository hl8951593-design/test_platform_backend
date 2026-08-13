from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


UiExecutionStatus = Literal[
    "queued",
    "assigned",
    "claimed",
    "launching",
    "running",
    "paused",
    "waiting_user",
    "passed",
    "assisted",
    "failed",
    "cancelled",
    "lost",
]
UiExecutionSource = Literal["platform_task", "local_debug", "local_import"]


class UiExecutionRuntimeOptions(BaseModel):
    trace: Literal["off", "on", "retain-on-failure"] = "retain-on-failure"
    screenshot: Literal["off", "only-on-failure", "on-each-step"] = "only-on-failure"

    model_config = ConfigDict(extra="forbid")


class UiExecutionCreateRequest(BaseModel):
    client_request_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    environment_id: int = Field(gt=0)
    requested_device_id: str | None = Field(default=None, min_length=1, max_length=64)
    source: UiExecutionSource = "platform_task"
    runtime_options: UiExecutionRuntimeOptions = Field(
        default_factory=UiExecutionRuntimeOptions
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("client_request_id")
    @classmethod
    def validate_client_request_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("client_request_id 不能为空")
        return normalized

    @field_validator("requested_device_id")
    @classmethod
    def normalize_requested_device_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class UiExecutionAcceptedRead(BaseModel):
    execution_id: str
    status: Literal["queued"]
    delivery_status: str
    created_at: str


class UiExecutionClaimRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    expected_status: Literal["queued", "assigned"] = "queued"
    supported_dsl_versions: list[str] = Field(min_length=1, max_length=16)
    supported_ipc_versions: list[str] = Field(min_length=1, max_length=16)

    model_config = ConfigDict(extra="forbid")


class UiExecutionLeaseRequest(BaseModel):
    lease_id: str = Field(min_length=1, max_length=64)
    lease_version: int = Field(ge=1)

    model_config = ConfigDict(extra="forbid")


class UiExecutionEventItem(BaseModel):
    client_event_id: str = Field(min_length=1, max_length=128)
    client_sequence: int = Field(ge=1)
    event_type: Literal[
        "execution.launching",
        "execution.running",
        "execution.paused",
        "execution.waiting_user",
        "execution.assisted",
        "step.started",
        "step.finished",
        "step.retry",
        "step.skipped",
        "user.intervention",
        "runtime.log",
        "browser.console",
        "browser.page_error",
        "network.summary",
        "audit.note",
    ]
    occurred_at: datetime
    step_id: str | None = Field(default=None, max_length=128)
    level: Literal["debug", "info", "warning", "error"] = "info"
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_step_reference(self):
        if self.event_type.startswith("step.") and not self.step_id:
            raise ValueError("step event requires step_id")
        return self


class UiExecutionEventBatchRequest(UiExecutionLeaseRequest):
    events: list[UiExecutionEventItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_batch_identity(self):
        sequences = [item.client_sequence for item in self.events]
        event_ids = [item.client_event_id for item in self.events]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("event sequences must be unique and increasing")
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("client_event_id must be unique within a batch")
        return self


class UiExecutionRuntimePatchRequest(UiExecutionLeaseRequest):
    command_id: str | None = Field(default=None, min_length=1, max_length=64)
    step_id: str = Field(min_length=1, max_length=128)
    patch_type: Literal["locator", "input", "timeout", "failure_policy"]
    scope: Literal["current_run"] = "current_run"
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=512)


class UiExecutionPatchRequestCreateRequest(BaseModel):
    client_request_id: str = Field(min_length=1, max_length=128)
    step_id: str = Field(min_length=1, max_length=128)
    patch_type: Literal["locator", "input", "timeout", "failure_policy"]
    before: dict[str, Any] | None = None
    after: dict[str, Any] = Field(min_length=1, max_length=4)
    reason: str = Field(min_length=1, max_length=512)
    expires_in_seconds: int | None = Field(default=None, ge=30, le=86400)

    model_config = ConfigDict(extra="forbid")

    @field_validator("client_request_id", "step_id", "reason")
    @classmethod
    def normalize_non_blank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_patch_fields(self):
        expected_fields = {
            "locator": {"locator_by", "locator_value"},
            "input": {"input_value"},
            "timeout": {"timeout_ms"},
            "failure_policy": {"failure_policy"},
        }[self.patch_type]
        if set(self.after) != expected_fields:
            raise ValueError(
                f"{self.patch_type} patch after must contain exactly "
                f"{sorted(expected_fields)}"
            )
        if self.before is not None and set(self.before) != expected_fields:
            raise ValueError(
                f"{self.patch_type} patch before must contain exactly "
                f"{sorted(expected_fields)}"
            )
        return self


class UiExecutionCompleteSummary(BaseModel):
    total_steps: int = Field(ge=0)
    passed_steps: int = Field(ge=0)
    failed_steps: int = Field(ge=0)
    skipped_steps: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    assisted: bool = False

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_counts(self):
        if self.passed_steps + self.failed_steps + self.skipped_steps != self.total_steps:
            raise ValueError("completed step counts must equal total_steps")
        return self


class UiExecutionPrimaryError(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    step_id: str | None = Field(default=None, max_length=128)

    model_config = ConfigDict(extra="forbid")


class UiExecutionCompleteRequest(UiExecutionLeaseRequest):
    final_client_sequence: int = Field(ge=0)
    status: Literal["passed", "assisted", "failed", "cancelled"]
    summary: UiExecutionCompleteSummary
    primary_error: UiExecutionPrimaryError | None = None


class UiExecutionCommandCreateRequest(BaseModel):
    client_request_id: str = Field(min_length=1, max_length=128)
    command_type: Literal["pause", "resume", "cancel"]
    payload: dict[str, Any] = Field(default_factory=dict)
    expires_in_seconds: int | None = Field(default=None, ge=30, le=86400)

    model_config = ConfigDict(extra="forbid")

    @field_validator("client_request_id")
    @classmethod
    def normalize_client_request_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("client_request_id cannot be blank")
        return normalized


class UiExecutionCommandAckRequest(UiExecutionLeaseRequest):
    status: Literal["acknowledged", "rejected"]
    detail: dict[str, Any] = Field(default_factory=dict)


class UiLocalRunStepResult(BaseModel):
    step_id: str = Field(min_length=1, max_length=128)
    attempt: int = Field(default=1, ge=1, le=100)
    status: Literal["passed", "failed", "skipped", "timeout"]
    started_at: datetime
    finished_at: datetime
    duration_ms: int = Field(ge=0, le=86_400_000)
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=4000)
    result: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_timestamps(self):
        if self.finished_at < self.started_at:
            raise ValueError("step finished_at must not precede started_at")
        return self


class UiLocalRunImportRequest(BaseModel):
    client_request_id: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1)
    environment_id: int = Field(gt=0)
    device_id: str | None = Field(default=None, min_length=1, max_length=64)
    status: Literal["passed", "assisted", "failed", "cancelled"]
    summary: UiExecutionCompleteSummary
    primary_error: UiExecutionPrimaryError | None = None
    started_at: datetime
    finished_at: datetime
    steps: list[UiLocalRunStepResult] = Field(default_factory=list, max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("client_request_id", "case_id")
    @classmethod
    def strip_import_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_import(self):
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        if self.status == "failed" and self.primary_error is None:
            raise ValueError("primary_error is required for failed local runs")
        if self.status in {"passed", "assisted"} and self.summary.failed_steps:
            raise ValueError("successful local run cannot contain failed steps")
        if self.status == "passed" and self.summary.assisted:
            raise ValueError("assisted local run must use assisted status")
        identities = [(item.step_id, item.attempt) for item in self.steps]
        if len(identities) != len(set(identities)):
            raise ValueError("local step attempts must be unique")
        return self
