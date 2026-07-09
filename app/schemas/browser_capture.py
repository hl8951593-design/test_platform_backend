from datetime import datetime
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, Field, model_validator


CaptureStatus = Literal["capturing", "stopped", "reviewing", "completed"]
EntryStatus = Literal["captured", "analyzing", "review_required", "approved", "imported", "ignored", "failed"]


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

    @model_validator(mode="before")
    @classmethod
    def normalize_plugin_payload(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "protocol" in data:
            data["protocol"] = str(data["protocol"]).lower()
        url = str(data.get("url") or data.get("source_url") or "").strip()
        method = str(data.get("method") or "GET").upper()
        if url:
            parsed = urlsplit(url)
            path = parsed.path or "/"
            query_params = _flatten_query_params(parse_qs(parsed.query, keep_blank_values=True))
            data.setdefault("source_url", url)
            data.setdefault("path", path)
            data.setdefault("name", f"{method} {path}")
        else:
            query_params = {}
            path = str(data.get("path") or "/")
            data.setdefault("source_url", path)
            data.setdefault("name", f"{method} {path}")
        data["method"] = method

        if "request_data" not in data:
            data["request_data"] = {
                "url": url or data.get("source_url"),
                "method": method,
                "headers": data.get("request_headers") or {},
                "query_params": query_params,
                "body_type": data.get("request_body_type") or "json",
                "body": data.get("request_body"),
            }
        if "response_data" not in data and (
            "response_status" in data or "response_headers" in data or "response_body" in data
        ):
            data["response_data"] = {
                "status_code": data.get("response_status"),
                "headers": data.get("response_headers") or {},
                "body": data.get("response_body"),
            }
        if "draft_data" not in data:
            data["draft_data"] = {
                "url": url or data.get("source_url"),
                "request": data.get("request_data") or {},
                "response": data.get("response_data"),
                "duration_ms": data.get("duration_ms"),
            }
        return data


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
    method: str | None = Field(default=None, min_length=1, max_length=16)
    path: str | None = Field(default=None, min_length=1, max_length=1024)
    source_url: str | None = Field(default=None, min_length=1, max_length=2048)
    request_data: dict[str, Any] | None = None
    response_data: dict[str, Any] | None = None
    draft_data: dict[str, Any] | None = None
    status: EntryStatus | None = None
    ai_analysis: dict[str, Any] | None = None
    ai_analysis_model: str | None = Field(default=None, max_length=128)
    ai_analyzed_at: datetime | None = None
    import_result: dict[str, Any] | None = None


class BrowserCaptureImportRequest(BaseModel):
    entry_ids: list[int] = Field(min_length=1, max_length=500)
    environment_id: int
    create_environment_variables: bool = False
    create_scenario: bool = False
    scenario_draft_id: int | None = None


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
    ai_analysis_model: str | None
    ai_analyzed_at: datetime | None
    import_result: dict | None
    captured_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


def _flatten_query_params(values: dict[str, list[str]]) -> dict[str, Any]:
    return {
        key: item[0] if len(item) == 1 else item
        for key, item in values.items()
    }


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
