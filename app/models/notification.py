from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationReadState(Base):
    __tablename__ = "notification_read_states"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "project_id",
            "notification_id",
            name="uq_notification_read_states_user_project_notification",
        ),
        Index("ix_notification_read_states_project_user", "project_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    notification_id: Mapped[str] = mapped_column(String(128), nullable=False)
    read_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
