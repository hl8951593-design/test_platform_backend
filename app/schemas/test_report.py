from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ReportSourceType = Literal["plan", "flow"]
ReportRange = Literal["today", "7d", "30d"]


class TestReportSummary(BaseModel):
    id: str
    source_type: ReportSourceType
    source_id: int
    project_id: int
    name: str
    status: str
    trigger_type: str
    trigger_user_id: int
    trigger_user_name: str
    user_name: str
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


class TestReportItem(BaseModel):
    id: str
    sequence: int
    item_type: Literal["plan_target", "flow_node"]
    node_id: str | None = None
    reference_id: int | str | None = None
    name: str
    kind: str
    method: str | None = None
    path: str | None = None
    status: str
    status_label: str
    attempt: int = 1
    total_count: int
    passed_count: int
    failed_count: int
    skipped_count: int
    pass_rate: float
    assertion_count: int = 0
    passed_assertion_count: int = 0
    failed_assertion_count: int = 0
    response_status_code: int | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    warning_flags: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    detail_available: bool = False


class TestReportSourceSnapshot(BaseModel):
    source_name: str
    source_version: int | str | None = None


class TestReportDetail(BaseModel):
    summary: TestReportSummary
    metrics: dict[str, int | float]
    items: list[TestReportItem] = Field(default_factory=list)
    source_snapshot: TestReportSourceSnapshot


class TestReportItemDetail(BaseModel):
    item: TestReportItem
    request: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)
    assertions: list[Any] = Field(default_factory=list)
    attempts: list[dict[str, Any]] = Field(default_factory=list)


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


class ReportIntelligenceScope(BaseModel):
    project_id: int
    environment_id: int | None = None
    range: ReportRange
    started_at: datetime
    finished_at: datetime


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
    date: date
    label: str
    value: float
    total_count: int
    passed_count: int
    failed_count: int


class ReportRiskIndicator(BaseModel):
    id: str
    name: str
    level: Literal["low", "medium", "high"]
    score: int
    count: int


class ReportFailureCluster(BaseModel):
    name: str
    count: int
    priority: Literal["P0", "P1", "P2", "P3"]
    confidence: int
    source_type: ReportSourceType | None = None
    source_id: int | None = None


class ReportSlowTest(BaseModel):
    execution_id: int
    test_case_id: int | None = None
    name: str
    subject_type: Literal["api_case"] = "api_case"
    owner_id: int | None = None
    owner_name: str
    owner: str
    risk: Literal["low", "medium", "high"]
    duration_ms: int
    last_executed_at: datetime


class ReportStabilityHeatmapRow(BaseModel):
    module: str
    values: list[int] = Field(default_factory=list)


class ReportStabilityHeatmap(BaseModel):
    labels: list[str] = Field(default_factory=list)
    rows: list[ReportStabilityHeatmapRow] = Field(default_factory=list)


class ReportRecommendationAction(BaseModel):
    type: Literal["open_report", "open_execution", "open_trends"]
    label: str
    target_id: int | str | None = None
    target_type: str | None = None


class ReportRecommendation(BaseModel):
    id: str
    priority: Literal["P0", "P1", "P2"]
    title: str
    content: str
    confidence: int
    action: ReportRecommendationAction
    action_label: str


class ReportIntelligenceOverview(BaseModel):
    generated_at: datetime
    generated_by: Literal["rules", "model"] = "rules"
    scope: ReportIntelligenceScope
    summary: ReportIntelligenceSummary
    pass_rate_trend: list[ReportTrendValue] = Field(default_factory=list)
    risk_indicators: list[ReportRiskIndicator] = Field(default_factory=list)
    failure_clusters: list[ReportFailureCluster] = Field(default_factory=list)
    slow_tests: list[ReportSlowTest] = Field(default_factory=list)
    stability_heatmap: ReportStabilityHeatmap
    recommendations: list[ReportRecommendation] = Field(default_factory=list)


class TestReportExportCreate(BaseModel):
    project_id: int = Field(gt=0)
    format: Literal["html"] = "html"


class TestReportExportRead(BaseModel):
    export_id: str
    download_url: str
    expires_at: datetime


class SupplementCaseDraftRequest(BaseModel):
    project_id: int = Field(gt=0)
    environment_id: int | None = Field(default=None, gt=0)
    scope: Literal["risk_gaps", "selected", "all"] = "risk_gaps"
    target_case_type: Literal["system_case"] = "system_case"
    item_ids: list[str] = Field(default_factory=list, max_length=100)
    prompt: str = Field(default="", max_length=1000)


class SupplementCaseDraft(BaseModel):
    id: str
    title: str
    test_objective: str
    preconditions: str
    test_steps: list[dict[str, Any]] = Field(default_factory=list)
    expected_result: str
    priority: Literal["P0", "P1", "P2"]
    source_report_id: str
    source_item_ids: list[str]
    confidence: int


class SupplementCaseDraftResult(BaseModel):
    generated_by: Literal["rules"] = "rules"
    source_report_id: str
    drafts: list[SupplementCaseDraft] = Field(default_factory=list)
