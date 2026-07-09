from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


DashboardRange = Literal["today", "7d", "30d"]


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
    priority: Literal["P0", "P1", "P2"]
    title: str
    summary: str
    action: str


class DashboardActivityItem(BaseModel):
    occurred_at: datetime
    type: str | None = None
    name: str | None = None
    status: str | None = None
    title: str
    detail: str


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
