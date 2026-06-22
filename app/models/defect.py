from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Defect(Base):
    __tablename__ = "defects"
    __table_args__ = (
        Index("ix_defects_project_status_updated", "project_id", "status", "updated_at"),
        Index("ix_defects_project_urgency_updated", "project_id", "urgency", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False, comment="缺陷标题")
    assignee: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="指派人")
    bug_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="缺陷类型")
    urgency: Mapped[str] = mapped_column(String(32), nullable=False, comment="紧急程度")
    status: Mapped[str] = mapped_column(String(32), nullable=False, comment="缺陷状态")
    content_html: Mapped[str] = mapped_column(Text, nullable=False, comment="富文本内容")
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, comment="报告人")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project = relationship("Project")
    reporter = relationship("User")
    attachments = relationship(
        "MediaObject",
        back_populates="defect",
        order_by="MediaObject.id",
        passive_deletes=True,
    )

    @property
    def assignee_name(self) -> str | None:
        return self.assignee

    @property
    def reporter_name(self) -> str | None:
        if self.reporter is None:
            return None
        return self.reporter.username or self.reporter.account
