from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TestScenario(Base):
    __tablename__ = "test_scenarios"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_scenarios_project_name"),
        Index("ix_test_scenarios_project_deleted_updated", "project_id", "is_deleted", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    environment_id: Mapped[int] = mapped_column(ForeignKey("project_environments.id"), nullable=False)
    current_version: Mapped[int] = mapped_column(default=1, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    versions = relationship("TestScenarioVersion", back_populates="scenario", cascade="all, delete-orphan")


class TestScenarioVersion(Base):
    __tablename__ = "test_scenario_versions"
    __table_args__ = (UniqueConstraint("scenario_id", "version", name="uq_test_scenario_versions_scenario_version"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("test_scenarios.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    scenario = relationship("TestScenario", back_populates="versions")


class TestScenarioRun(Base):
    __tablename__ = "test_scenario_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_test_scenario_runs_project_idempotency"),
        Index("ix_test_scenario_runs_project_scenario_started", "project_id", "scenario_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("test_scenarios.id"), index=True, nullable=True)
    scenario_version_id: Mapped[int | None] = mapped_column(ForeignKey("test_scenario_versions.id"), nullable=True)
    plan_run_id: Mapped[int | None] = mapped_column(ForeignKey("test_plan_runs.id"), index=True, nullable=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    environment_id: Mapped[int] = mapped_column(ForeignKey("project_environments.id"), nullable=False)
    dataset_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dataset_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scenario_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    variables_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    step_results: Mapped[list] = mapped_column(JSON, nullable=False)
    triggered_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    triggered_by = relationship("User")
