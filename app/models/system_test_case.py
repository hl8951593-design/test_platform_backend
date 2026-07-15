from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SystemTestCase(Base):
    __tablename__ = "system_test_cases"
    __table_args__ = (
        UniqueConstraint("project_id", "case_code", name="uq_system_test_cases_project_code"),
        Index("ix_system_test_cases_project_updated_id", "project_id", "updated_at", "id"),
        Index("ix_system_test_cases_project_status_priority", "project_id", "status", "priority"),
        Index("ix_system_test_cases_project_module", "project_id", "business_module"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    case_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="系统用例编号")
    title: Mapped[str] = mapped_column(String(256), nullable=False, comment="系统用例标题")
    business_module: Mapped[str] = mapped_column(String(128), nullable=False, comment="业务模块")
    test_objective: Mapped[str] = mapped_column(Text, nullable=False, comment="测试目标")
    preconditions: Mapped[str | None] = mapped_column(Text, nullable=True, comment="前置条件")
    test_scenario: Mapped[str | None] = mapped_column(Text, nullable=True, comment="测试场景")
    system_behavior: Mapped[str | None] = mapped_column(Text, nullable=True, comment="系统行为")
    expected_result: Mapped[str | None] = mapped_column(Text, nullable=True, comment="预期结果")
    data_requirements: Mapped[str | None] = mapped_column(Text, nullable=True, comment="数据要求")
    risk_points: Mapped[str | None] = mapped_column(Text, nullable=True, comment="风险点")
    priority: Mapped[str] = mapped_column(String(8), default="P1", nullable=False, comment="优先级")
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, comment="状态")
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False, comment="标签")
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否 AI 生成")
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True, comment="AI 置信度")
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="负责人")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, comment="创建人")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project = relationship("Project")
    created_by = relationship("User")
    relations = relationship(
        "SystemCaseApiRelation",
        back_populates="system_case",
        cascade="all, delete-orphan",
    )


class SystemCaseApiRelation(Base):
    __tablename__ = "system_case_api_relations"
    __table_args__ = (
        UniqueConstraint("system_case_id", "api_case_id", name="uq_system_case_api_relations_case_api"),
        Index("ix_system_case_api_relations_project_case_order", "project_id", "system_case_id", "sort_order"),
        Index("ix_system_case_api_relations_project_api", "project_id", "api_case_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    system_case_id: Mapped[int] = mapped_column(ForeignKey("system_test_cases.id"), index=True, nullable=False)
    api_case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id"), index=True, nullable=False)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="关系类型")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True, comment="推荐置信度")
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False, comment="排序")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project = relationship("Project")
    system_case = relationship("SystemTestCase", back_populates="relations")
    api_case = relationship("TestCase")
