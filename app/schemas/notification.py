from datetime import datetime
from typing import Literal

from pydantic import BaseModel


NotificationSeverity = Literal["info", "success", "warning", "danger"]
NotificationType = Literal["alert", "run", "approval", "system"]


class NotificationItemRead(BaseModel):
    notification_id: str
    title: str
    message: str
    source: str
    severity: NotificationSeverity
    type: NotificationType
    unread: bool
    occurred_at: datetime
    action_label: str | None = None
