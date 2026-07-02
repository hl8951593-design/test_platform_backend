from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.async_response import public_execution_status
from app.schemas.retry import RetryPolicyConfig


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
BodyType = Literal["none", "json", "form_urlencoded", "multipart", "raw_text", "raw_json"]


class AssertionConfig(BaseModel):
    type: Literal["status_code", "body_contains", "json_equals"]
    expected: Any
    path: str | None = Field(default=None, description="json_equals 使用的点分路径，例如 data.id")
    retry_on_failure: bool = Field(
        default=False,
        description="断言失败时是否允许按 retry_policy 轮询重试",
    )


class ExtractorConfig(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="变量名")
    path: str = Field(min_length=1, description="响应 JSON 点分路径")


class TestCaseRequestConfig(BaseModel):
    environment_id: int | None = Field(default=None, description="默认执行环境 ID")
    environment_ids: list[int] = Field(default_factory=list, description="关联环境 ID 列表")
    method: HttpMethod
    path: str = Field(min_length=1, max_length=512, description="请求路径或完整 URL")
    headers: dict[str, Any] | None = None
    query_params: dict[str, Any] | None = None
    body_type: BodyType = Field(default="json", description="请求体格式")
    body: dict[str, Any] | list[Any] | str | None = None
    assertions: list[AssertionConfig] = Field(default_factory=list)
    extractors: list[ExtractorConfig] = Field(default_factory=list)
    retry_policy: RetryPolicyConfig = Field(default_factory=RetryPolicyConfig)


class TestCaseCreateRequest(TestCaseRequestConfig):
    name: str = Field(min_length=1, max_length=128, description="测试用例名称")
    description: str | None = Field(default=None, description="测试用例描述")


class TestCaseUpdateRequest(TestCaseCreateRequest):
    pass


class UnsavedTestCaseExecuteRequest(TestCaseRequestConfig):
    pass


class BatchExecuteRequest(BaseModel):
    test_case_ids: list[int] = Field(min_length=1, description="按该列表顺序批量执行")
    environment_id: int | None = Field(default=None, description="批量执行时覆盖用例绑定环境")


class TestCaseRead(BaseModel):
    id: int
    project_id: int
    environment_id: int | None
    environment_ids: list[int] = Field(default_factory=list)
    name: str
    description: str | None
    method: str
    path: str
    headers: dict[str, Any] | None
    query_params: dict[str, Any] | None
    body_type: str
    body: dict[str, Any] | list[Any] | str | None
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


class TestCaseExecutionRead(BaseModel):
    id: int
    project_id: int
    test_case_id: int | None
    environment_id: int | None
    executed_by_id: int
    trigger_source: str
    agent_run_id: str | None
    agent_tool_call_id: str | None
    trigger_tool_name: str | None
    status: str
    request_snapshot: dict[str, Any]
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
