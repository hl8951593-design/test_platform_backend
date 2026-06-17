from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ReportSourceType = Literal["plan", "flow"]


class TestReportSummary(BaseModel):
    id: str
    source_type: ReportSourceType
    source_id: int
    project_id: int
    name: str
    status: str
    trigger_type: str
    trigger_user_id: int
    environment_id: int | None = None
    environment_name: str | None = None
    total_count: int
    passed_count: int
    failed_count: int
    skipped_count: int
    pass_rate: float
    duration_ms: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class TestReportPage(BaseModel):
    items: list[TestReportSummary] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class TestReportDetail(BaseModel):
    summary: TestReportSummary
    metrics: dict[str, int | float]
    items: list[dict[str, Any]] = Field(default_factory=list)
    source_snapshot: dict[str, Any]


class TestReportTrendPoint(BaseModel):
    date: date
    total_count: int
    passed_count: int
    failed_count: int
    other_count: int
    pass_rate: float
    avg_duration_ms: int | None = None


class TestReportTrend(BaseModel):
    started_from: date
    started_to: date
    interval: Literal["day"] = "day"
    points: list[TestReportTrendPoint] = Field(default_factory=list)
