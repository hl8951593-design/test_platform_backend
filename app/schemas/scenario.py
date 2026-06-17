import json
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


class ScenarioStepRequest(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    kind: Literal["api_case", "websocket_case", "delay", "condition"]
    reference_id: int | None = Field(default=None, validation_alias=AliasChoices("reference_id", "referenceId"))
    name: str = Field(min_length=1, max_length=200)
    method: str = ""
    path: str = ""
    config: dict[str, Any] = Field(
        default_factory=dict, validation_alias=AliasChoices("config", "config_text", "configText")
    )
    continue_on_failure: bool = Field(
        default=False, validation_alias=AliasChoices("continue_on_failure", "continueOnFailure")
    )

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("config", mode="before")
    @classmethod
    def parse_config(cls, value):
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("configText 必须是合法 JSON") from exc
            if not isinstance(parsed, dict):
                raise ValueError("configText 必须是 JSON 对象")
            return parsed
        return value

    @model_validator(mode="after")
    def validate_reference(self):
        if self.kind in {"api_case", "websocket_case"} and self.reference_id is None:
            raise ValueError("测试用例步骤必须提供 reference_id")
        if self.kind in {"delay", "condition"} and self.reference_id is not None:
            raise ValueError("内置步骤不能提供 reference_id")
        if self.kind == "delay":
            delay_ms = self.config.get("delayMs", self.config.get("delay_ms", 0))
            is_template = isinstance(delay_ms, str) and "{{" in delay_ms and "}}" in delay_ms
            if not is_template and (not isinstance(delay_ms, int) or delay_ms < 0 or delay_ms > 300000):
                raise ValueError("等待步骤 delayMs 必须在 0 到 300000 之间")
        if self.kind == "condition" and not str(self.config.get("expression", "")).strip():
            raise ValueError("条件步骤必须提供 expression")
        return self


class ScenarioRequestOverride(BaseModel):
    step_id: str = Field(
        min_length=1,
        max_length=128,
        validation_alias=AliasChoices("step_id", "stepId"),
    )
    target: str = Field(min_length=1, max_length=32)
    path: str = Field(default="", max_length=512)
    value: Any

    model_config = ConfigDict(populate_by_name=True)


class ScenarioDatasetRecordRequest(BaseModel):
    id: str | None = Field(default=None, max_length=128)
    name: str | None = Field(default=None, max_length=128)
    enabled: bool = True
    request_overrides: list[ScenarioRequestOverride] = Field(
        default_factory=list,
        validation_alias=AliasChoices("request_overrides", "requestOverrides"),
    )

    model_config = ConfigDict(populate_by_name=True)


class ScenarioDatasetRequest(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    variables: dict[str, Any] = Field(
        default_factory=dict, validation_alias=AliasChoices("variables", "variables_text", "variablesText")
    )
    records: list[ScenarioDatasetRecordRequest] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_records(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if data.get("records"):
            data.pop("request_overrides", None)
            data.pop("requestOverrides", None)
            return data

        dataset_id = str(data.get("id") or "DATA")
        dataset_name = str(data.get("name") or "Record")
        raw_overrides = data.pop(
            "request_overrides", data.pop("requestOverrides", [])
        ) or []
        record_count = max(
            1,
            max(
                (
                    len(item.get("values"))
                    for item in raw_overrides
                    if isinstance(item, dict)
                    and isinstance(item.get("values"), list)
                ),
                default=1,
            ),
        )
        records = []
        for index in range(record_count):
            overrides = []
            for raw_override in raw_overrides:
                if not isinstance(raw_override, dict):
                    overrides.append(raw_override)
                    continue
                override = dict(raw_override)
                values = override.pop("values", None)
                if isinstance(values, list):
                    if index >= len(values):
                        continue
                    override["value"] = values[index]
                overrides.append(override)
            records.append({
                "id": f"{dataset_id}-RECORD-{index + 1}",
                "name": (
                    dataset_name
                    if record_count == 1
                    else f"{dataset_name} #{index + 1}"
                ),
                "enabled": True,
                "request_overrides": overrides,
            })
        data["records"] = records
        return data

    @field_validator("variables", mode="before")
    @classmethod
    def parse_variables(cls, value):
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("variablesText 必须是合法 JSON") from exc
            if not isinstance(parsed, dict):
                raise ValueError("variablesText 必须是 JSON 对象")
            return parsed
        return value


class ScenarioPayload(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    environment_id: int = Field(validation_alias=AliasChoices("environment_id", "environmentId"))
    tags: list[str] = Field(default_factory=list)
    steps: list[ScenarioStepRequest] = Field(min_length=1)
    datasets: list[ScenarioDatasetRequest] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def normalize(self):
        self.name = self.name.strip()
        self.tags = list(dict.fromkeys(tag.strip() for tag in self.tags if tag.strip()))
        if len({step.id for step in self.steps}) != len(self.steps):
            raise ValueError("步骤 ID 不能重复")
        if len({dataset.id for dataset in self.datasets}) != len(self.datasets):
            raise ValueError("数据集 ID 不能重复")
        return self


class ScenarioCreateRequest(ScenarioPayload):
    pass


class ScenarioUpdateRequest(ScenarioPayload):
    version: int = Field(ge=1)


class ScenarioExecuteRequest(BaseModel):
    environment_id: int | None = Field(default=None, validation_alias=AliasChoices("environment_id", "environmentId"))
    dataset_ids: list[str] | None = Field(default=None, validation_alias=AliasChoices("dataset_ids", "datasetIds"))
    idempotency_key: str | None = Field(
        default=None, min_length=1, max_length=128, validation_alias=AliasChoices("idempotency_key", "idempotencyKey")
    )

    model_config = ConfigDict(populate_by_name=True)


class ScenarioRead(BaseModel):
    id: int
    project_id: int
    environment_id: int
    current_version: int
    name: str
    description: str | None
    tags: list[str]
    steps: list[dict]
    datasets: list[dict]
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None


class ScenarioRunRead(BaseModel):
    id: int
    execution_id: str | None = None
    scenario_id: int | None
    project_id: int
    environment_id: int
    dataset_id: str | None
    dataset_name: str | None
    record_id: str | None = None
    record_name: str | None = None
    status: str
    trigger_type: str
    variables_snapshot: dict
    step_results: list[dict]
    current_step_id: str | None = None
    current_step_index: int | None = None
    last_event_sequence: int = 0
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScenarioRunQueuedRead(BaseModel):
    run_id: int
    dataset_id: str | None
    dataset_name: str | None
    record_id: str | None = None
    record_name: str | None = None
    status: str
    events_url: str
    detail_url: str


class ScenarioExecutionQueuedRead(BaseModel):
    execution_id: str
    scenario_id: int
    scenario_version: int
    status: str
    created_at: datetime
    runs: list[ScenarioRunQueuedRead]

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds") + "Z"
