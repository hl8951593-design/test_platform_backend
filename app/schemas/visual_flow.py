from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FlowPosition(BaseModel):
    x: float
    y: float


class FlowInputBinding(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1)
    source_node_id: str = Field(alias="sourceNodeId", min_length=1)
    source_path: str = Field(alias="sourcePath", min_length=1)
    fallback: Any = None

    model_config = ConfigDict(populate_by_name=True)


class FlowNodeConfig(BaseModel):
    description: str = ""
    condition: str | None = None
    delay_ms: int | None = Field(default=None, alias="delayMs", ge=0, le=300000)
    continue_on_failure: bool = Field(default=False, alias="continueOnFailure")
    input_bindings: list[FlowInputBinding] = Field(default_factory=list, alias="inputBindings")
    output_paths: list[str] = Field(default_factory=list, alias="outputPaths")
    case_config: dict[str, Any] | None = Field(default=None, alias="caseConfig")
    case_overrides: dict[str, Any] | None = Field(default=None, alias="caseOverrides")

    model_config = ConfigDict(populate_by_name=True)


class FlowNode(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    kind: Literal["start", "end", "api_case", "websocket_case", "condition", "delay"]
    name: str = Field(min_length=1, max_length=200)
    reference_id: int | str | None = Field(default=None, alias="referenceId")
    method: str | None = None
    path: str | None = None
    position: FlowPosition
    config: FlowNodeConfig = Field(default_factory=FlowNodeConfig)

    model_config = ConfigDict(populate_by_name=True)


class FlowEdge(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    route: Literal["always", "success", "failure", "true", "false"]
    label: str | None = None


class FlowViewport(BaseModel):
    zoom: float = Field(default=1, ge=0.6, le=1.4)


class FlowDefinition(BaseModel):
    schema_version: Literal["1.0"] = Field(default="1.0", alias="schemaVersion")
    id: int | str | None = None
    project_id: int | None = Field(default=None, alias="projectId")
    environment_id: int | None = Field(default=None, alias="environmentId")
    name: str | None = None
    description: str | None = None
    nodes: list[FlowNode] = Field(default_factory=list)
    edges: list[FlowEdge] = Field(default_factory=list)
    viewport: FlowViewport = Field(default_factory=FlowViewport)
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class FlowCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    definition: FlowDefinition


class FlowUpdateRequest(FlowCreateRequest):
    expected_version: int | None = Field(default=None, alias="expectedVersion", ge=1)

    model_config = ConfigDict(populate_by_name=True)


class FlowExecuteUnsavedRequest(BaseModel):
    definition: FlowDefinition


class FlowSummaryRead(BaseModel):
    id: int
    name: str
    description: str | None
    status: str
    node_count: int
    current_version: int
    updated_at: datetime


class FlowDetailRead(BaseModel):
    id: int
    project_id: int
    name: str
    description: str | None
    current_version: int
    definition: dict[str, Any]
    updated_at: datetime


class FlowNodeExecutionRead(BaseModel):
    node_id: str
    status: str
    request_snapshot: dict[str, Any] | None
    output_snapshot: dict[str, Any] | None
    error: dict[str, Any] | None
    started_at: datetime | None
    finished_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class FlowExecutionRead(BaseModel):
    execution_id: int
    flow_id: int | None
    flow_version: int | None
    project_id: int
    environment_id: int | None
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    node_executions: list[FlowNodeExecutionRead] = Field(default_factory=list)
