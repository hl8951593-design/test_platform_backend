from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, comment="用户名")
    avatar: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="头像")
    account: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False, comment="账号")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False, comment="手机号")
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False, comment="邮箱")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否管理员")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
