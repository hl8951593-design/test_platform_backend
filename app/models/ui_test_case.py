from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class UiTestCase(Base):
    __tablename__ = "ui_test_cases"
    __table_args__ = (
        Index(
            "ix_ui_test_cases_project_deleted_updated",
            "project_id",
            "is_deleted",
            "updated_at",
            "id",
        ),
        Index(
            "ix_ui_test_cases_project_status_updated",
            "project_id",
            "status",
            "updated_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    default_environment_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_environments.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    tags_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "ui_test_case_versions.id",
            name="fk_ui_test_cases_current_version_id",
            use_alter=True,
        ),
        index=True,
        nullable=True,
    )
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project = relationship("Project")
    default_environment = relationship("ProjectEnvironment")
    created_by = relationship("User")
    versions = relationship(
        "UiTestCaseVersion",
        back_populates="ui_test_case",
        cascade="all, delete-orphan",
        foreign_keys="UiTestCaseVersion.ui_test_case_id",
        order_by="UiTestCaseVersion.version_number",
    )
    current_version = relationship(
        "UiTestCaseVersion",
        foreign_keys=[current_version_id],
        post_update=True,
    )


class UiTestCaseVersion(Base):
    __tablename__ = "ui_test_case_versions"
    __table_args__ = (
        UniqueConstraint(
            "ui_test_case_id",
            "version_number",
            name="uq_ui_test_case_versions_case_version",
        ),
        Index(
            "ix_ui_test_case_versions_case_created",
            "ui_test_case_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    ui_test_case_id: Mapped[int] = mapped_column(
        ForeignKey("ui_test_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(32), default="ui-case-v1", nullable=False
    )
    dsl_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    required_secret_refs_json: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False
    )
    based_on_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("ui_test_case_versions.id"), index=True, nullable=True
    )
    change_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    ui_test_case = relationship(
        "UiTestCase",
        back_populates="versions",
        foreign_keys=[ui_test_case_id],
    )
    based_on_version = relationship(
        "UiTestCaseVersion",
        remote_side=[id],
        foreign_keys=[based_on_version_id],
    )
    created_by = relationship("User")
