from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


CaptureStatus = Literal["capturing", "stopped", "reviewing", "completed"]
EntryStatus = Literal["captured", "review_required", "approved", "imported", "ignored", "failed"]


class BrowserCaptureCreateRequest(BaseModel):
    environment_id: int
    name: str = Field(min_length=1, max_length=128)
    source_url: str | None = Field(default=None, max_length=1024)


class BrowserCaptureUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    status: CaptureStatus | None = None


class BrowserCaptureEntryPayload(BaseModel):
    client_entry_id: str = Field(min_length=1, max_length=64)
    protocol: Literal["http", "websocket"]
    fingerprint: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    method: str = Field(min_length=1, max_length=16)
    path: str = Field(min_length=1, max_length=1024)
    source_url: str = Field(min_length=1, max_length=2048)
    request_data: dict[str, Any] = Field(default_factory=dict)
    response_data: dict[str, Any] | None = None
    draft_data: dict[str, Any] = Field(default_factory=dict)
    status: EntryStatus = "captured"
    captured_at: datetime


class BrowserCaptureEntryBatchRequest(BaseModel):
    entries: list[BrowserCaptureEntryPayload] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_unique_client_ids(self):
        ids = [entry.client_entry_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("同一批次中的 client_entry_id 不能重复")
        return self


class BrowserCaptureEntryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    draft_data: dict[str, Any] | None = None
    status: EntryStatus | None = None
    ai_analysis: dict[str, Any] | None = None
    import_result: dict[str, Any] | None = None


class BrowserCaptureEntryRead(BaseModel):
    id: int
    capture_id: int
    project_id: int
    client_entry_id: str
    protocol: str
    fingerprint: str
    name: str
    method: str
    path: str
    source_url: str
    request_data: dict
    response_data: dict | None
    draft_data: dict
    status: str
    ai_analysis: dict | None
    import_result: dict | None
    captured_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BrowserCaptureRead(BaseModel):
    id: int
    project_id: int
    environment_id: int
    name: str
    source_url: str | None
    status: str
    created_by_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
