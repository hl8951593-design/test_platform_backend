from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from app.schemas.scenario import ScenarioCreateRequest
from app.schemas.test_case import TestCaseCreateRequest
from app.schemas.websocket_test_case import WebSocketTestCaseCreateRequest


class AIChatFunctionDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=1024)
    parameters: dict[str, Any] = Field(default_factory=dict)


class AIChatToolDefinition(BaseModel):
    type: Literal["function"] = "function"
    function: AIChatFunctionDefinition


class AIChatToolCallFunction(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    arguments: str


class AIChatToolCall(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    type: Literal["function"] = "function"
    function: AIChatToolCallFunction


class AIChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[AIChatToolCall] = Field(default_factory=list)
    tool_call_id: str | None = Field(default=None, max_length=128)
    reasoning_content: str | None = None

    @model_validator(mode="after")
    def validate_role_payload(self):
        if self.role in {"system", "user"} and not (self.content or "").strip():
            raise ValueError(f"{self.role} message requires non-empty content")
        if self.role == "assistant" and not (self.content or "").strip() and not self.tool_calls:
            raise ValueError("assistant message requires content or tool_calls")
        if self.role == "tool" and (not self.tool_call_id or self.content is None):
            raise ValueError("tool message requires tool_call_id and content")
        return self


class AIChatRequest(BaseModel):
    messages: list[AIChatMessage] = Field(min_length=1, description="对话消息列表")
    model: str | None = Field(default=None, description="模型名称，不传则使用系统默认 DeepSeek 模型")
    thinking: Literal["enabled", "disabled"] | None = Field(default=None, description="是否启用思考模式")
    reasoning_effort: Literal["high", "max"] | None = Field(default=None, description="推理强度")
    temperature: float | None = Field(default=None, ge=0, le=2, description="采样温度")
    max_tokens: int | None = Field(default=None, gt=0, description="最大输出 token 数")
    response_format: Literal["text", "json"] = Field(default="text", description="返回文本或 JSON 模式")
    tools: list[AIChatToolDefinition] = Field(default_factory=list)
    tool_choice: Literal["auto", "none"] | None = None
    parallel_tool_calls: bool = False


class AIChatResponse(BaseModel):
    provider: str
    model: str
    content: str
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    tool_calls: list[AIChatToolCall] = Field(default_factory=list)
    reasoning_content: str | None = None


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


class AIAgentArtifactSource(BaseModel):
    artifact_id: str = Field(min_length=1, description="Agent ToolCall artifact id")
    output_hash: str = Field(min_length=1, description="Exact ToolCall output hash")


class AIScenarioComposeRequest(BaseModel):
    requirement: str = Field(min_length=1, description="自然语言场景组合目标")
    case_source: AIAgentArtifactSource | None = Field(
        default=None,
        description="Authoritative testcase.query_project_cases artifact resolved by the backend ledger.",
    )
    environment_reference: str | None = Field(
        default=None,
        description="Project environment object-ref returned by project.read_context.",
    )
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


class AIHttpTestCaseDescriptionSummaryRequest(BaseModel):
    mode: Literal["request", "request_response"] = Field(description="request 表示仅请求信息，request_response 表示包含调试响应")
    test_case_id: int | None = None
    name: str | None = Field(default=None, max_length=128)
    protocol: Literal["http"] = "http"
    environment_id: int | None = None
    environment_ids: list[int] = Field(default_factory=list)
    request: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] | None = None


class AIHttpTestCaseDescriptionSummaryResponse(BaseModel):
    description: str
    source_summary: Literal["request", "request_response"]
    warnings: list[str] = Field(default_factory=list)


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


class AIBrowserCaptureAnalyzeRequest(BaseModel):
    protocol: Literal["http", "websocket"] | None = None
    draft_data: dict[str, Any] = Field(default_factory=dict)
    analysis_focus: list[
        Literal["semantics", "data_structure", "test_points", "risks", "automation"]
    ] = Field(
        default_factory=lambda: ["semantics", "data_structure", "test_points", "risks", "automation"],
        max_length=10,
    )
    include_examples: bool = True


class AIBrowserCaptureAnalysisSummary(BaseModel):
    name: str = ""
    purpose: str = ""
    business_domain: str = ""
    operation_type: str = ""
    confidence: float = 0

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0
        return max(0, min(1, number))


class AIBrowserCaptureAnalysisField(BaseModel):
    path: str = ""
    type: str = ""
    meaning: str = ""
    required: bool = False
    constraints: list[str] = Field(default_factory=list)
    sensitive: bool = False
    dynamic: bool = False
    example: Any = None


class AIBrowserCaptureAnalysisSection(BaseModel):
    description: str = ""
    fields: list[AIBrowserCaptureAnalysisField] = Field(default_factory=list)


class AIBrowserCaptureAnalysisTestPoint(BaseModel):
    category: str = ""
    title: str = ""
    description: str = ""
    priority: Literal["high", "medium", "low"] = "medium"
    test_data: dict[str, Any] = Field(default_factory=dict)
    expected_result: str = ""


class AIBrowserCaptureAnalysisRisk(BaseModel):
    level: Literal["high", "medium", "low"] = "medium"
    title: str = ""
    description: str = ""
    recommendation: str = ""


class AIBrowserCaptureAnalysisAutomation(BaseModel):
    assertions: list[str] = Field(default_factory=list)
    extractors: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    data_setup: list[str] = Field(default_factory=list)
    cleanup: list[str] = Field(default_factory=list)


class AIBrowserCaptureAnalysisResult(BaseModel):
    summary: AIBrowserCaptureAnalysisSummary = Field(default_factory=AIBrowserCaptureAnalysisSummary)
    request: AIBrowserCaptureAnalysisSection = Field(default_factory=AIBrowserCaptureAnalysisSection)
    response: AIBrowserCaptureAnalysisSection = Field(default_factory=AIBrowserCaptureAnalysisSection)
    test_points: list[AIBrowserCaptureAnalysisTestPoint] = Field(default_factory=list)
    risks: list[AIBrowserCaptureAnalysisRisk] = Field(default_factory=list)
    automation: AIBrowserCaptureAnalysisAutomation = Field(default_factory=AIBrowserCaptureAnalysisAutomation)
    warnings: list[str] = Field(default_factory=list)
    model: str | None = None
    analyzed_at: str | None = None

    @model_validator(mode="after")
    def normalize_order(self):
        priority_order = {"high": 0, "medium": 1, "low": 2}
        self.test_points = sorted(
            self.test_points,
            key=lambda item: priority_order.get(item.priority, 99),
        )
        self.risks = sorted(
            self.risks,
            key=lambda item: priority_order.get(item.level, 99),
        )
        return self


class AIBrowserCaptureBatchGenerateRequest(AIBrowserCaptureGenerateRequest):
    entry_ids: list[int] = Field(min_length=1, max_length=50)


class AIBrowserCaptureRelationsRequest(BaseModel):
    entry_ids: list[int] | None = Field(default=None, max_length=100)


class AIBrowserCaptureBatchAnalyzeRequest(BaseModel):
    entry_ids: list[int] = Field(min_length=2, max_length=100)
    include_nodes: bool = True
    include_suggestions: bool = True


class AIBrowserCaptureScenarioRequest(AIBrowserCaptureRelationsRequest):
    name: str | None = Field(default=None, max_length=128)


class AIExecutionDiagnoseRequest(BaseModel):
    protocol: Literal["http", "websocket", "scenario", "flow"]
    draft_data: dict[str, Any]
    evidence: dict[str, Any] = Field(
        validation_alias=AliasChoices("evidence", "execution_data")
    )


class AIGeneratedWebSocketTestCaseResponse(BaseModel):
    project_id: int
    environment_id: int
    environment_ids: list[int]
    source_summary: str
    cases: list[WebSocketTestCaseCreateRequest]
    warnings: list[str] = Field(default_factory=list)
