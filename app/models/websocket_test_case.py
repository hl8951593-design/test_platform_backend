from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WebSocketTestCase(Base):
    __tablename__ = "websocket_test_cases"
    __table_args__ = (Index("ix_websocket_test_cases_project_id_id", "project_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("project_environments.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    subprotocols: Mapped[list | None] = mapped_column(JSON, nullable=True)
    messages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    receive_count: Mapped[int] = mapped_column(default=1, nullable=False)
    connect_timeout_ms: Mapped[int] = mapped_column(default=10000, nullable=False)
    receive_timeout_ms: Mapped[int] = mapped_column(default=10000, nullable=False)
    assertions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    extractors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    retry_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    last_executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_execution_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    environment_links = relationship("WebSocketTestCaseEnvironment", back_populates="test_case", cascade="all, delete-orphan")

    @property
    def environment_ids(self) -> list[int]:
        ids = [link.environment_id for link in self.environment_links]
        return ids or ([self.environment_id] if self.environment_id is not None else [])


class WebSocketTestCaseEnvironment(Base):
    __tablename__ = "websocket_test_case_environments"
    __table_args__ = (
        UniqueConstraint("websocket_test_case_id", "environment_id", name="uq_websocket_test_case_environments"),
        Index("ix_websocket_case_env_project_environment", "project_id", "environment_id", "websocket_test_case_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    websocket_test_case_id: Mapped[int] = mapped_column(ForeignKey("websocket_test_cases.id"), index=True, nullable=False)
    environment_id: Mapped[int] = mapped_column(ForeignKey("project_environments.id"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    test_case = relationship("WebSocketTestCase", back_populates="environment_links")


class WebSocketTestCaseExecution(Base):
    __tablename__ = "websocket_test_case_executions"
    __table_args__ = (
        Index("ix_websocket_executions_project_created_at", "project_id", "created_at"),
        Index("ix_websocket_executions_case_created_at", "websocket_test_case_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    websocket_test_case_id: Mapped[int | None] = mapped_column(ForeignKey("websocket_test_cases.id"), index=True, nullable=True)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("project_environments.id"), nullable=True)
    scenario_run_id: Mapped[int | None] = mapped_column(ForeignKey("test_scenario_runs.id"), index=True, nullable=True)
    executed_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    session_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    response_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    assertion_results: Mapped[list | None] = mapped_column(JSON, nullable=True)
    attempt_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
