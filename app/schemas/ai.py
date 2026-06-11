from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.test_case import TestCaseCreateRequest
from app.schemas.websocket_test_case import WebSocketTestCaseCreateRequest


class AIChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, description="消息内容")


class AIChatRequest(BaseModel):
    messages: list[AIChatMessage] = Field(min_length=1, description="对话消息列表")
    model: str | None = Field(default=None, description="模型名称，不传则使用系统默认 DeepSeek 模型")
    thinking: Literal["enabled", "disabled"] | None = Field(default=None, description="是否启用思考模式")
    reasoning_effort: Literal["high", "max"] | None = Field(default=None, description="推理强度")
    temperature: float | None = Field(default=None, ge=0, le=2, description="采样温度")
    max_tokens: int | None = Field(default=None, gt=0, description="最大输出 token 数")
    response_format: Literal["text", "json"] = Field(default="text", description="返回文本或 JSON 模式")


class AIChatResponse(BaseModel):
    provider: str
    model: str
    content: str
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None


class AIProviderRead(BaseModel):
    provider: str
    base_url: str
    default_model: str
    configured: bool


class AITestCaseGenerateRequest(BaseModel):
    interface_text: str = Field(min_length=1, description="前端粘贴的接口文档、curl、URL、请求参数或业务说明")
    request_method: str | None = Field(default=None, description="前端识别到的请求方式，自动识别时可为空")
    generate_count: int = Field(default=3, ge=1, le=10, description="生成测试用例数量")
    include_assertions: bool = Field(default=True, description="是否生成断言")
    extra_requirements: str | None = Field(default=None, description="用户额外生成要求")


class AITestCaseExpandRequest(BaseModel):
    requirement: str = Field(min_length=1, description="自然语言扩写要求")
    generate_count: int = Field(default=5, ge=1, le=10, description="扩写生成数量")
    expansion_types: list[
        Literal[
            "empty_value",
            "invalid_type",
            "extra_param",
            "missing_param",
            "length_overflow",
            "invalid_format",
            "boundary",
            "negative",
            "exception",
            "security",
            "business",
        ]
    ] = Field(
        default_factory=lambda: [
            "empty_value",
            "invalid_type",
            "extra_param",
            "missing_param",
            "length_overflow",
        ],
        description="扩写类型",
    )
    include_assertions: bool = Field(default=True, description="是否生成断言")


class AIGeneratedTestCaseResponse(BaseModel):
    project_id: int
    environment_id: int
    environment_ids: list[int]
    source_summary: str
    cases: list[TestCaseCreateRequest]
    warnings: list[str] = Field(default_factory=list)
    raw_model: str | None = Field(default=None, description="模型原始输出，默认仅调试时使用")


class AIWebSocketTestCaseGenerateRequest(BaseModel):
    websocket_text: str = Field(min_length=1, description="WebSocket 文档、连接地址、消息协议、事件说明或示例消息")
    generate_count: int = Field(default=3, ge=1, le=10)
    include_assertions: bool = True
    extra_requirements: str | None = None


class AIWebSocketTestCaseExpandRequest(BaseModel):
    requirement: str = Field(min_length=1)
    generate_count: int = Field(default=5, ge=1, le=10)
    expansion_types: list[
        Literal[
            "handshake_auth",
            "subprotocol",
            "message_sequence",
            "missing_message_field",
            "invalid_message_value",
            "malformed_message",
            "receive_count",
            "timeout",
            "connection_close",
            "business",
        ]
    ] = Field(
        default_factory=lambda: [
            "handshake_auth",
            "subprotocol",
            "message_sequence",
            "missing_message_field",
            "invalid_message_value",
        ]
    )
    include_assertions: bool = True


class AIBrowserCaptureGenerateRequest(BaseModel):
    generate_count: int = Field(default=5, ge=1, le=10)
    include_assertions: bool = True
    extra_requirements: str | None = None


class AIBrowserCaptureBatchGenerateRequest(AIBrowserCaptureGenerateRequest):
    entry_ids: list[int] = Field(min_length=1, max_length=50)


class AIBrowserCaptureRelationsRequest(BaseModel):
    entry_ids: list[int] | None = Field(default=None, max_length=100)


class AIBrowserCaptureScenarioRequest(AIBrowserCaptureRelationsRequest):
    name: str | None = Field(default=None, max_length=128)


class AIExecutionDiagnoseRequest(BaseModel):
    protocol: Literal["http", "websocket"]
    draft_data: dict[str, Any]
    execution_data: dict[str, Any]


class AIGeneratedWebSocketTestCaseResponse(BaseModel):
    project_id: int
    environment_id: int
    environment_ids: list[int]
    source_summary: str
    cases: list[WebSocketTestCaseCreateRequest]
    warnings: list[str] = Field(default_factory=list)
