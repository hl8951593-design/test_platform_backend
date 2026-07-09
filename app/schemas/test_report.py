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


class ReportIntelligenceSummary(BaseModel):
    pass_rate: float
    pass_rate_delta: float
    failure_cluster_count: int
    p0_cluster_count: int
    stability_score: float
    slow_test_count: int
    slow_threshold_ms: int
    ai_recommendation_count: int


class ReportTrendValue(BaseModel):
    label: str
    value: float


class ReportRiskIndicator(BaseModel):
    name: str
    level: Literal["low", "medium", "high"]
    score: int


class ReportFailureCluster(BaseModel):
    name: str
    count: int
    priority: Literal["P0", "P1", "P2", "P3"]
    confidence: int


class ReportSlowTest(BaseModel):
    test_case_id: int | None = None
    name: str
    owner: str
    risk: Literal["low", "medium", "high"]
    duration_ms: int


class ReportStabilityHeatmapRow(BaseModel):
    module: str
    values: list[int] = Field(default_factory=list)


class ReportAIRecommendation(BaseModel):
    id: str
    priority: Literal["P0", "P1", "P2"]
    content: str
    action_label: str | None = None


class ReportIntelligenceOverview(BaseModel):
    generated_at: datetime
    summary: ReportIntelligenceSummary
    pass_rate_trend: list[ReportTrendValue] = Field(default_factory=list)
    risk_indicators: list[ReportRiskIndicator] = Field(default_factory=list)
    failure_clusters: list[ReportFailureCluster] = Field(default_factory=list)
    slow_tests: list[ReportSlowTest] = Field(default_factory=list)
    stability_heatmap: list[ReportStabilityHeatmapRow] = Field(default_factory=list)
    ai_recommendations: list[ReportAIRecommendation] = Field(default_factory=list)
