from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TestPlan(Base):
    __tablename__ = "test_plans"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_plans_project_name"),
        Index("ix_test_plans_project_deleted_updated", "project_id", "is_deleted", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    cron_expression: Mapped[str | None] = mapped_column(String(128), nullable=True)
    schedule_timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    webhook_event: Mapped[str | None] = mapped_column(String(128), nullable=True)
    environment_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    targets: Mapped[list] = mapped_column(JSON, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(32), default="serial", nullable=False)
    failure_policy: Mapped[str] = mapped_column(String(32), default="stop", nullable=False)
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    timeout_minutes: Mapped[int] = mapped_column(default=30, nullable=False)
    notification_emails: Mapped[list] = mapped_column(JSON, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    created_by = relationship("User", foreign_keys=[created_by_id])
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    scenario_links = relationship("TestPlanScenario", back_populates="plan", cascade="all, delete-orphan")
    environment_links = relationship("TestPlanEnvironment", back_populates="plan", cascade="all, delete-orphan")


class TestPlanScenario(Base):
    __tablename__ = "test_plan_scenarios"
    __table_args__ = (
        UniqueConstraint("plan_id", "scenario_id", name="uq_test_plan_scenarios_plan_scenario"),
        UniqueConstraint("plan_id", "sort_order", name="uq_test_plan_scenarios_plan_order"),
        Index("ix_test_plan_scenarios_project_scenario", "project_id", "scenario_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("test_plans.id"), index=True, nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("test_scenarios.id"), index=True, nullable=False)
    scenario_version_at_bind: Mapped[int] = mapped_column(nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False)
    name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    plan = relationship("TestPlan", back_populates="scenario_links")
    scenario = relationship("TestScenario")


class TestPlanEnvironment(Base):
    __tablename__ = "test_plan_environments"
    __table_args__ = (
        UniqueConstraint("plan_id", "environment_id", name="uq_test_plan_environments_plan_environment"),
        Index("ix_test_plan_environments_project_environment", "project_id", "environment_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("test_plans.id"), index=True, nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    environment_id: Mapped[int] = mapped_column(ForeignKey("project_environments.id"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    plan = relationship("TestPlan", back_populates="environment_links")
    environment = relationship("ProjectEnvironment")


class TestPlanRun(Base):
    __tablename__ = "test_plan_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_test_plan_runs_project_idempotency"),
        Index("ix_test_plan_runs_project_started", "project_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("test_plans.id"), index=True, nullable=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    plan_name: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_version: Mapped[int] = mapped_column(nullable=False)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("project_environments.id"), nullable=True)
    environment_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    plan_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    target_results: Mapped[list] = mapped_column(JSON, nullable=False)
    target_count: Mapped[int] = mapped_column(default=0, nullable=False)
    passed_count: Mapped[int] = mapped_column(default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(default=0, nullable=False)
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    operator = relationship("User")
