from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DashboardAssetDailySnapshot(Base):
    __tablename__ = "dashboard_asset_daily_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "scope_key",
            "snapshot_date",
            name="uq_dashboard_asset_snapshot_scope_date",
        ),
        Index(
            "ix_dashboard_asset_snapshot_project_scope_date",
            "project_id",
            "scope_key",
            "snapshot_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    environment_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_environments.id"), nullable=True, index=True
    )
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    http_test_case_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    websocket_test_case_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    system_test_case_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scenario_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scenario_enabled_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defect_open_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defect_total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DashboardAssetEvent(Base):
    __tablename__ = "dashboard_asset_events"
    __table_args__ = (
        Index(
            "ix_dashboard_asset_events_project_occurred",
            "project_id",
            "occurred_at",
            "id",
        ),
        Index(
            "ix_dashboard_asset_events_project_type_event_occurred",
            "project_id",
            "asset_type",
            "event_type",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    environment_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_environments.id"), nullable=True, index=True
    )
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class DashboardAIAnalysisJob(Base):
    __tablename__ = "dashboard_ai_analysis_jobs"
    __table_args__ = (
        Index(
            "ix_dashboard_ai_jobs_project_created",
            "project_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_dashboard_ai_jobs_project_status_updated",
            "project_id",
            "status",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    environment_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_environments.id"), nullable=True, index=True
    )
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    range_value: Mapped[str] = mapped_column(String(16), nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(32), nullable=False)
    focus: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    user_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DashboardRegressionRun(Base):
    __tablename__ = "dashboard_regression_runs"
    __table_args__ = (
        Index(
            "ix_dashboard_regression_runs_project_created",
            "project_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_dashboard_regression_runs_project_status_updated",
            "project_id",
            "status",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("project_environments.id"), nullable=False, index=True
    )
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    target_snapshot: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    child_executions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
