from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


DashboardRange = Literal["today", "7d", "30d"]
AssetTrendRange = Literal["7d", "30d"]
DashboardResourceType = Literal[
    "http_test_case",
    "websocket_test_case",
    "system_test_case",
    "scenario",
    "flow",
    "test_plan",
    "defect",
    "execution",
]
DashboardActionCode = Literal[
    "view_execution",
    "view_failure_analysis",
    "view_test_case",
    "view_scenario",
    "view_flow",
    "view_plan",
    "view_defect",
    "rerun",
    "generate_defect",
    "optimize_assertions",
]


class DashboardAction(BaseModel):
    code: DashboardActionCode
    label: str
    resource_type: DashboardResourceType | None = None
    resource_id: int | str | None = None
    params: dict[str, str | int | bool] = Field(default_factory=dict)


class DashboardScope(BaseModel):
    project_id: int
    environment_id: int | None = None
    range: DashboardRange
    version: str | None = None


class DashboardHero(BaseModel):
    health_score: float
    insight_title: str
    insight_summary: str
    risk_count: int
    updated_text: str


class DashboardKPIBreakdown(BaseModel):
    label: str
    value: int | float | str


class DashboardKPI(BaseModel):
    key: str
    label: str
    value: int | float | str
    delta: str | None = None
    trend: Literal["up", "down", "flat"] | None = None
    breakdown: list[DashboardKPIBreakdown] = Field(default_factory=list)


class DashboardRiskMatrixItem(BaseModel):
    module: str
    api: int
    data: int
    environment: int
    level: Literal["stable", "controlled", "medium", "high"]


class DashboardAutomationEfficiencyItem(BaseModel):
    label: str
    percent: int
    saved_hours: int


class DashboardHealthDimension(BaseModel):
    label: str
    value: int


class DashboardHealthProfile(BaseModel):
    score: float
    dimensions: list[DashboardHealthDimension] = Field(default_factory=list)


class DashboardDefectPrediction(BaseModel):
    module: str
    probability: int
    impact: Literal["low", "medium", "high"]
    reason: str


class DashboardAIRecommendation(BaseModel):
    id: str
    type: str
    priority: Literal["P0", "P1", "P2", "P3"]
    title: str
    summary: str
    recommendation: str
    confidence_score: float = Field(ge=0, le=100)
    risk_level: Literal["critical", "high", "medium", "low"]
    action: DashboardAction | None = None


class DashboardActivityItem(BaseModel):
    id: str
    occurred_at: datetime
    event_type: str
    type: DashboardResourceType
    resource_id: int | str
    run_id: int | str | None = None
    name: str | None = None
    status: str | None = None
    title: str
    detail: str
    action: DashboardAction | None = None


class DashboardActivityFeedItem(BaseModel):
    id: str
    event_type: str
    occurred_at: datetime
    resource_type: DashboardResourceType
    resource_id: int | str
    resource_name: str
    run_id: int | str | None = None
    status: Literal["queued", "running", "passed", "failed", "cancelled", "timeout"] | None = None
    title: str
    detail: str
    action: DashboardAction | None = None


class QualityOverview(BaseModel):
    generated_at: datetime
    scope: DashboardScope
    hero: DashboardHero
    kpis: list[DashboardKPI] = Field(default_factory=list)
    risk_matrix: list[DashboardRiskMatrixItem] = Field(default_factory=list)
    automation_efficiency: list[DashboardAutomationEfficiencyItem] = Field(default_factory=list)
    health_profile: DashboardHealthProfile
    defect_predictions: list[DashboardDefectPrediction] = Field(default_factory=list)
    ai_recommendations: list[DashboardAIRecommendation] = Field(default_factory=list)
    activity_feed: list[DashboardActivityItem] = Field(default_factory=list)


class DashboardTrendScope(BaseModel):
    project_id: int
    environment_id: int | None = None


class DashboardTestCaseBreakdown(BaseModel):
    http: int
    websocket: int
    system: int


class DashboardTestCaseTrendPoint(BaseModel):
    date: str
    total: int
    created: int
    deleted: int = 0


class DashboardTestCaseTrend(BaseModel):
    current: int
    previous: int
    delta: int
    delta_rate: float
    breakdown: DashboardTestCaseBreakdown
    points: list[DashboardTestCaseTrendPoint] = Field(default_factory=list)


class DashboardAutomationTrendPoint(BaseModel):
    date: str
    total: int
    created: int
    enabled: int
    deleted: int = 0


class DashboardAutomationTrend(BaseModel):
    current: int
    previous: int
    delta: int
    delta_rate: float
    enabled_count: int
    points: list[DashboardAutomationTrendPoint] = Field(default_factory=list)


class DashboardDefectTrendPoint(BaseModel):
    date: str
    open: int
    created: int
    closed: int
    total: int


class DashboardDefectTrend(BaseModel):
    current_open: int
    previous_open: int
    delta: int
    delta_rate: float
    total: int
    points: list[DashboardDefectTrendPoint] = Field(default_factory=list)


class ProjectAssetTrendsResponse(BaseModel):
    range: AssetTrendRange
    granularity: Literal["day"] = "day"
    scope: DashboardTrendScope
    test_cases: DashboardTestCaseTrend
    automation_flows: DashboardAutomationTrend
    defects: DashboardDefectTrend
    historical_data_complete: bool
    data_complete_from: str | None = None
    generated_at: datetime


class DashboardActivityFeedResponse(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[DashboardActivityFeedItem] = Field(default_factory=list)


class DashboardAIFocus(BaseModel):
    resource_type: DashboardResourceType | None = None
    resource_ids: list[int | str] = Field(default_factory=list, max_length=100)


class CreateDashboardAIJobRequest(BaseModel):
    project_id: int
    environment_id: int | None = None
    range: DashboardRange = "7d"
    analysis_type: Literal[
        "quality_diagnosis",
        "generate_recommendations",
        "risk_analysis",
        "defect_prediction",
    ]
    focus: DashboardAIFocus | None = None
    user_prompt: str | None = Field(default=None, max_length=4000)


class DashboardAIJobAccepted(BaseModel):
    job_id: str
    status: Literal["queued"]
    analysis_type: str
    created_at: datetime
    poll_after_ms: int


class DashboardEvidence(BaseModel):
    resource_type: DashboardResourceType
    resource_id: int | str
    resource_name: str
    run_id: int | str | None = None
    description: str


class DashboardRecommendation(BaseModel):
    id: str
    type: Literal[
        "failure_analysis",
        "assertion_optimization",
        "environment_fix",
        "regression",
        "defect_creation",
        "coverage_improvement",
    ]
    priority: Literal["P0", "P1", "P2", "P3"]
    risk_level: Literal["critical", "high", "medium", "low"]
    confidence_score: float = Field(ge=0, le=100)
    title: str
    summary: str
    recommendation: str
    evidence: list[DashboardEvidence] = Field(default_factory=list)
    action: DashboardAction | None = None


class DashboardAIJobResult(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    progress: int = Field(ge=0, le=100)
    analysis_type: str
    summary: str | None = None
    recommendations: list[DashboardRecommendation] = Field(default_factory=list)
    evidence: list[DashboardEvidence] = Field(default_factory=list)
    generated_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None


class CreateDashboardRegressionRunRequest(BaseModel):
    project_id: int
    environment_id: int
    scope_type: Literal["smart", "test_plan", "scenario", "flow", "test_cases"]
    scope_ids: list[int | str] = Field(default_factory=list, max_length=200)
    strategy: Literal["failed_first", "risk_first", "full"]
    include_http: bool = True
    include_websocket: bool = True
    include_system_cases: bool = True
    trigger_source: Literal["dashboard"] = "dashboard"


class DashboardRegressionExecutionResource(BaseModel):
    resource_type: DashboardResourceType
    resource_id: int | str


class DashboardRegressionRunResponse(BaseModel):
    run_id: int | str
    run_type: Literal["test_plan", "scenario", "flow", "batch_test_case"]
    status: Literal["queued", "running", "passed", "failed", "cancelled", "timeout"]
    target_count: int
    passed_count: int = 0
    failed_count: int = 0
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    child_executions: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None
    poll_after_ms: int = 1000
    execution_resource: DashboardRegressionExecutionResource


DashboardInsightType = Literal[
    "risk-analysis",
    "automation-efficiency",
    "health-profile",
    "defect-prediction",
]


class DashboardInsightSummary(BaseModel):
    title: str
    description: str
    score: float | None = None
    level: Literal["critical", "high", "medium", "low"] | None = None


class DashboardInsightMetric(BaseModel):
    key: str
    label: str
    value: int | float | str
    unit: str | None = None
    trend: Literal["up", "down", "stable"] | None = None


class DashboardInsightItem(BaseModel):
    id: str
    title: str
    description: str
    score: float | None = None
    level: str | None = None
    resource_type: DashboardResourceType | None = None
    resource_id: int | str | None = None
    action: DashboardAction | None = None


class DashboardInsightDetailResponse(BaseModel):
    insight_type: DashboardInsightType
    available: bool
    generated_at: datetime
    summary: DashboardInsightSummary
    metrics: list[DashboardInsightMetric] = Field(default_factory=list)
    items: list[DashboardInsightItem] = Field(default_factory=list)
    page: int | None = None
    page_size: int | None = None
    total: int | None = None
