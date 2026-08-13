from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ExecutionType = Literal["http", "websocket", "scenario", "flow", "ui"]


class ExecutionRecordSummary(BaseModel):
    id: str
    execution_type: ExecutionType
    execution_id: int
    project_id: int
    resource_id: int | None = None
    resource_name: str | None = None
    environment_id: int | None = None
    scenario_run_id: int | None = None
    status: str
    trigger_type: str
    trigger_user_id: int
    duration_ms: int | None = None
    error_message: str | None = None
    dataset_id: str | None = None
    dataset_name: str | None = None
    record_id: str | None = None
    record_name: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class ExecutionRecordPage(BaseModel):
    items: list[ExecutionRecordSummary] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class ExecutionRecordCursorPage(BaseModel):
    items: list[ExecutionRecordSummary] = Field(default_factory=list)
    pagination_mode: Literal["cursor"] = "cursor"
    returned: int
    limit: int
    has_more: bool
    next_cursor: str | None = None
    total: int | None = None


class ExecutionRecordDetail(BaseModel):
    summary: ExecutionRecordSummary
    detail: dict[str, Any]
