from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.scenario import ScenarioCreateRequest
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


class AISkillOperationRead(BaseModel):
    name: str
    summary: str
    input_schema: str
    output_schema: str
    input_json_schema: dict[str, Any] = Field(default_factory=dict)
    output_json_schema: dict[str, Any] = Field(default_factory=dict)
    requires_environment: bool = False
    requires_source: bool = False


class AISkillRead(BaseModel):
    id: str
    name: str
    description: str
    version: str
    domain: str
    protocol: str
    operations: list[AISkillOperationRead]


class AISkillRunRequest(BaseModel):
    operation: str = Field(description="Skill operation name, for example generate or expand")
    project_id: int = Field(description="当前项目 ID")
    environment_id: int | None = Field(default=None, description="当前环境 ID；生成类操作通常必填")
    source_id: int | None = Field(default=None, description="源资源 ID；扩写类操作通常为测试用例 ID")
    input: dict[str, Any] = Field(default_factory=dict, description="按 skill operation input_schema 提交的入参")


class AISkillRunQueuedRead(BaseModel):
    run_id: str
    skill_id: str
    operation: str
    status: Literal["queued", "running", "completed", "failed"]


class AIRunEventRead(BaseModel):
    sequence: int
    event: str
    payload: dict[str, Any]
    created_at: str


class AISkillRunRead(BaseModel):
    run_id: str
    skill_id: str
    operation: str
    project_id: int
    status: Literal["queued", "running", "completed", "failed"]
    events: list[AIRunEventRead] = Field(default_factory=list)
    result: Any | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str


class AIScenarioComposeRequest(BaseModel):
    requirement: str = Field(min_length=1, description="自然语言场景组合目标")
    scenario_name: str | None = Field(default=None, max_length=128, description="期望场景名称")
    http_test_case_ids: list[int] = Field(default_factory=list, max_length=50, description="候选 HTTP 测试用例 ID")
    websocket_test_case_ids: list[int] = Field(default_factory=list, max_length=50, description="候选 WebSocket 测试用例 ID")
    include_bindings: bool = Field(default=True, description="是否尝试基于提取器和变量引用生成绑定说明")
    include_assertions: bool = Field(default=True, description="是否根据请求和响应样本补充场景步骤断言")
    include_hooks: bool = Field(default=True, description="是否生成必要的前置和后置动作")
    include_datasets: bool = Field(default=False, description="是否生成数据集草稿")
    include_latest_execution: bool = Field(default=True, description="是否读取候选用例最近一次执行的请求和响应样本")
    execute_candidates: bool = Field(default=False, description="是否在组合前实际执行候选用例以获取请求和响应样本")
    self_validate: bool = Field(default=True, description="生成场景草稿后是否执行未保存场景进行自验证")
    max_validation_attempts: int = Field(default=3, ge=1, le=3, description="自验证失败后的最大生成/修复尝试次数，最多 3 次")
    max_nodes: int = Field(default=10, ge=1, le=50, description="最多组合节点数")
    extra_requirements: str | None = Field(default=None, description="额外组合要求")


class AIScenarioValidationAttemptRead(BaseModel):
    attempt: int
    status: Literal["passed", "failed", "error", "timeout"]
    run_id: int | None = None
    duration_ms: int | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    issues: list[dict[str, Any]] = Field(default_factory=list)


class AIGeneratedScenarioResponse(BaseModel):
    project_id: int
    environment_id: int
    environment_name: str | None = None
    source_summary: str
    scenario: ScenarioCreateRequest
    warnings: list[str] = Field(default_factory=list)
    self_validated: bool = False
    validation_attempts: list[AIScenarioValidationAttemptRead] = Field(default_factory=list)


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
