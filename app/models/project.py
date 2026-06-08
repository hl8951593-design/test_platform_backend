from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_deleted_id", "is_deleted", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="项目名称")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="项目描述")
    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False, comment="项目创建者"
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否删除")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    creator = relationship("User")
    members = relationship("ProjectMember", back_populates="project")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
        Index("ix_project_members_user_active_project", "user_id", "is_active", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    added_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, comment="添加人")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否有效")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project = relationship("Project", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])
    added_by = relationship("User", foreign_keys=[added_by_id])
    permissions = relationship(
        "ProjectMemberPermission",
        back_populates="member",
        cascade="all, delete-orphan",
    )


class ProjectMemberPermission(Base):
    __tablename__ = "project_member_permissions"
    __table_args__ = (
        UniqueConstraint("member_id", "permission_code", name="uq_project_member_permissions_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("project_members.id"), index=True, nullable=False)
    permission_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="权限编码")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    member = relationship("ProjectMember", back_populates="permissions")


class ProjectEnvironment(Base):
    __tablename__ = "project_environments"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_environments_project_name"),
        Index("ix_project_environments_project_deleted_default_id", "project_id", "is_deleted", "is_default", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="环境名称")
    base_url: Mapped[str] = mapped_column(String(512), nullable=False, comment="环境基础地址")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="环境描述")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否默认环境")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否删除")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, comment="创建人")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project = relationship("Project")
    created_by = relationship("User")
    variables = relationship(
        "ProjectEnvironmentVariable",
        back_populates="environment",
        cascade="all, delete-orphan",
    )
    test_cases = relationship("TestCase", back_populates="environment")


class ProjectEnvironmentVariable(Base):
    __tablename__ = "project_environment_variables"
    __table_args__ = (
        UniqueConstraint("environment_id", "name", name="uq_project_environment_variables_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("project_environments.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="变量名")
    value: Mapped[str] = mapped_column(Text, nullable=False, comment="变量值")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否敏感")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    environment = relationship("ProjectEnvironment", back_populates="variables")
