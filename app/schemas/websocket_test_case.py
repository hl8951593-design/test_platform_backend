from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.async_response import public_execution_status
from app.schemas.retry import RetryPolicyConfig


class WebSocketMessageConfig(BaseModel):
    type: Literal["text", "json"] = "text"
    data: Any


class WebSocketAssertionConfig(BaseModel):
    type: Literal["message_count", "message_contains", "message_json_equals"]
    expected: Any
    message_index: int = Field(default=0, ge=0)
    path: str | None = None
    retry_on_failure: bool = False


class WebSocketExtractorConfig(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    message_index: int = Field(default=0, ge=0)
    path: str = Field(min_length=1)


class WebSocketTestCaseConfig(BaseModel):
    environment_id: int | None = None
    environment_ids: list[int] = Field(default_factory=list)
    path: str = Field(min_length=1, max_length=512, description="ws/wss URL or path")
    headers: dict[str, Any] | None = None
    subprotocols: list[str] = Field(default_factory=list)
    messages: list[WebSocketMessageConfig] = Field(default_factory=list)
    receive_count: int = Field(default=1, ge=0, le=100)
    connect_timeout_ms: int = Field(default=10000, ge=1, le=120000)
    receive_timeout_ms: int = Field(default=10000, ge=1, le=120000)
    assertions: list[WebSocketAssertionConfig] = Field(default_factory=list)
    extractors: list[WebSocketExtractorConfig] = Field(default_factory=list)
    retry_policy: RetryPolicyConfig = Field(default_factory=RetryPolicyConfig)


class WebSocketTestCaseCreateRequest(WebSocketTestCaseConfig):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None


class WebSocketTestCaseUpdateRequest(WebSocketTestCaseCreateRequest):
    pass


class UnsavedWebSocketTestCaseExecuteRequest(WebSocketTestCaseConfig):
    pass


class WebSocketBatchExecuteRequest(BaseModel):
    websocket_test_case_ids: list[int] = Field(min_length=1)
    environment_id: int | None = None


class WebSocketDebugSessionCreateRequest(BaseModel):
    environment_id: int | None = None
    path: str = Field(min_length=1, max_length=512)
    headers: dict[str, Any] | None = None
    subprotocols: list[str] = Field(default_factory=list)
    connect_timeout_ms: int = Field(default=10000, ge=1, le=120000)
    idle_timeout_seconds: int = Field(default=1800, ge=60, le=86400)


class WebSocketDebugSessionSendRequest(WebSocketMessageConfig):
    pass


class WebSocketDebugSessionRead(BaseModel):
    session_id: str
    project_id: int
    status: Literal["connected", "disconnected", "error"]
    url: str
    negotiated_subprotocol: str | None
    created_at: datetime
    last_active_at: datetime
    idle_timeout_seconds: int
    error_message: str | None = None
    latest_sequence: int
    messages: list[dict[str, Any]] = Field(default_factory=list)


class WebSocketTestCaseRead(BaseModel):
    id: int
    project_id: int
    environment_id: int | None
    environment_ids: list[int] = Field(default_factory=list)
    name: str
    description: str | None
    path: str
    headers: dict[str, Any] | None
    subprotocols: list[str] | None
    messages: list[dict[str, Any]] | None
    receive_count: int
    connect_timeout_ms: int
    receive_timeout_ms: int
    assertions: list[dict[str, Any]] | None
    extractors: list[dict[str, Any]] | None
    retry_policy: dict[str, Any] | None
    created_by_id: int
    last_executed_at: datetime | None
    last_execution_status: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("last_execution_status", mode="before")
    @classmethod
    def _hide_internal_pending_status(cls, value):
        return public_execution_status(value)

    model_config = {"from_attributes": True}


class WebSocketTestCaseExecutionRead(BaseModel):
    id: int
    project_id: int
    websocket_test_case_id: int | None
    environment_id: int | None
    executed_by_id: int
    trigger_source: str
    agent_run_id: str | None
    agent_tool_call_id: str | None
    trigger_tool_name: str | None
    status: str
    session_snapshot: dict[str, Any]
    response_snapshot: dict[str, Any] | None
    assertion_results: list[dict[str, Any]] | None
    attempt_history: list[dict[str, Any]] | None
    error_message: str | None
    duration_ms: int | None
    created_at: datetime

    @field_validator("status", mode="before")
    @classmethod
    def _hide_internal_pending_status(cls, value):
        return public_execution_status(value)

    model_config = {"from_attributes": True}
