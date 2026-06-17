from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TestCase(Base):
    __tablename__ = "test_cases"
    __table_args__ = (
        Index("ix_test_cases_project_id_id", "project_id", "id"),
        Index("ix_test_cases_project_environment_id", "project_id", "environment_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("project_environments.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="测试用例名称")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="测试用例描述")
    method: Mapped[str] = mapped_column(String(16), nullable=False, comment="请求方法")
    path: Mapped[str] = mapped_column(String(512), nullable=False, comment="请求路径或完整 URL")
    headers: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="请求头")
    query_params: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="Query 参数")
    body_type: Mapped[str] = mapped_column(String(32), default="json", nullable=False, comment="请求体格式")
    body: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True, comment="请求体")
    assertions: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="断言配置")
    extractors: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="变量提取配置")
    retry_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="步骤重试策略")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, comment="创建人")
    last_executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="最近执行时间")
    last_execution_status: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="最近执行状态")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project = relationship("Project")
    environment = relationship("ProjectEnvironment", back_populates="test_cases")
    environment_links = relationship(
        "TestCaseEnvironment",
        back_populates="test_case",
        cascade="all, delete-orphan",
    )
    created_by = relationship("User")

    @property
    def environment_ids(self) -> list[int]:
        environment_ids = [link.environment_id for link in self.environment_links]
        if not environment_ids and self.environment_id is not None:
            return [self.environment_id]
        return environment_ids


class TestCaseEnvironment(Base):
    __tablename__ = "test_case_environments"
    __table_args__ = (
        UniqueConstraint("test_case_id", "environment_id", name="uq_test_case_environments_case_env"),
        Index("ix_test_case_environments_project_environment", "project_id", "environment_id", "test_case_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    test_case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id"), index=True, nullable=False)
    environment_id: Mapped[int] = mapped_column(ForeignKey("project_environments.id"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    test_case = relationship("TestCase", back_populates="environment_links")
    environment = relationship("ProjectEnvironment")


class TestCaseExecution(Base):
    __tablename__ = "test_case_executions"
    __table_args__ = (
        Index("ix_test_case_executions_project_created_at", "project_id", "created_at"),
        Index("ix_test_case_executions_case_created_at", "test_case_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    test_case_id: Mapped[int | None] = mapped_column(ForeignKey("test_cases.id"), index=True, nullable=True)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("project_environments.id"), nullable=True)
    scenario_run_id: Mapped[int | None] = mapped_column(ForeignKey("test_scenario_runs.id"), index=True, nullable=True)
    executed_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, comment="执行人")
    status: Mapped[str] = mapped_column(String(32), nullable=False, comment="执行状态")
    request_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, comment="请求快照")
    response_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="响应快照")
    assertion_results: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="断言结果")
    attempt_history: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="步骤尝试明细")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误信息")
    duration_ms: Mapped[int | None] = mapped_column(nullable=True, comment="耗时毫秒")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    project = relationship("Project")
    test_case = relationship("TestCase")
    environment = relationship("ProjectEnvironment")
    executed_by = relationship("User")
