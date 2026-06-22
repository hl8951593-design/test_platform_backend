from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.media import MediaObjectRead


DefectBugType = Literal[
    "functional",
    "ui",
    "performance",
    "security",
    "compatibility",
    "data",
    "other",
]
DefectUrgency = Literal["low", "medium", "high", "critical"]
DefectStatus = Literal["new", "active", "confirmed", "fixed", "verified", "closed", "reopened"]


class DefectBaseRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256, description="Bug 标题")
    assignee: str | None = Field(default=None, max_length=128, description="指派人账号、姓名或用户 ID")
    bug_type: DefectBugType
    urgency: DefectUrgency
    status: DefectStatus = "new"
    content_html: str = Field(min_length=1, description="富文本内容 HTML")


class DefectCreateRequest(DefectBaseRequest):
    media_ids: list[int] = Field(default_factory=list, description="已上传且待绑定的媒体对象 ID")


class DefectUpdateRequest(DefectBaseRequest):
    media_ids: list[int] | None = Field(
        default=None,
        description="完整附件 ID 列表；不传则保留现有附件",
    )


class DefectStatusUpdateRequest(BaseModel):
    status: DefectStatus


class DefectRead(BaseModel):
    id: int
    project_id: int
    title: str
    assignee_name: str | None
    bug_type: str
    urgency: str
    status: str
    content_html: str
    reporter_name: str | None
    attachments: list[MediaObjectRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
