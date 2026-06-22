import json
import re
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


VARIABLE_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"


class ScenarioExecutableRequest(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    kind: Literal[
        "api_case",
        "websocket_case",
        "condition",
        "delay",
        "random",
        "fixed_value",
        "script",
    ]
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
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

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
    def validate_config(self):
        if self.kind in {"api_case", "websocket_case"} and self.reference_id is None:
            raise ValueError("测试用例步骤必须提供 reference_id")
        if self.kind not in {"api_case", "websocket_case"} and self.reference_id is not None:
            raise ValueError("内置步骤不能提供 reference_id")
        if self.kind == "delay":
            duration_ms = self.config.get("duration_ms")
            if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms < 0:
                raise ValueError("等待动作 duration_ms 必须是非负整数")
        if self.kind == "condition" and not str(self.config.get("expression", "")).strip():
            raise ValueError("条件动作必须提供 expression")
        if self.kind == "random":
            random_type = self.config.get("type")
            if random_type not in {"integer", "string", "uuid"}:
                raise ValueError("随机动作 type 必须是 integer、string 或 uuid")
            self._validate_output(self.config.get("output"))
            if random_type == "integer":
                minimum, maximum = self.config.get("min"), self.config.get("max")
                if (
                    not isinstance(minimum, int)
                    or isinstance(minimum, bool)
                    or not isinstance(maximum, int)
                    or isinstance(maximum, bool)
                    or minimum > maximum
                ):
                    raise ValueError("随机整数必须满足 min <= max")
            if random_type == "string":
                length = self.config.get("length")
                if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
                    raise ValueError("随机字符串 length 必须是正整数")
        if self.kind == "fixed_value":
            self._validate_output(self.config.get("output"))
            if "value" not in self.config:
                raise ValueError("固定值动作必须提供 value")
        if self.kind == "script":
            if self.config.get("language") not in {"python", "javascript"}:
                raise ValueError("脚本 language 必须是 python 或 javascript")
            code = self.config.get("code")
            if not isinstance(code, str) or not code.strip():
                raise ValueError("脚本动作必须提供 code")
            timeout_ms = self.config.get("timeout_ms")
            if (
                not isinstance(timeout_ms, int)
                or isinstance(timeout_ms, bool)
                or timeout_ms <= 0
                or timeout_ms > 60000
            ):
                raise ValueError("脚本 timeout_ms 必须在 1 到 60000 之间")
            for field in ("inputs", "outputs"):
                values = self.config.get(field)
                if not isinstance(values, list) or any(
                    not isinstance(value, str) or not re.fullmatch(VARIABLE_NAME_PATTERN, value)
                    for value in values
                ):
                    raise ValueError(f"脚本 {field} 必须是合法变量名数组")
                if len(values) != len(set(values)):
                    raise ValueError(f"脚本 {field} 不能包含重复变量")
        return self

    @staticmethod
    def _validate_output(value: Any) -> None:
        if not isinstance(value, str) or not re.fullmatch(VARIABLE_NAME_PATTERN, value):
            raise ValueError("动作 output 必须是合法变量名")


class ScenarioTestCaseRequest(ScenarioExecutableRequest):
    kind: Literal["api_case", "websocket_case"]


class ScenarioActionRequest(ScenarioExecutableRequest):
    kind: Literal["condition", "delay", "random", "fixed_value", "script"]


class ScenarioNodeRequest(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    before_actions: list[ScenarioActionRequest] = Field(
        default_factory=list,
        validation_alias=AliasChoices("before_actions", "beforeActions"),
    )
    test_case: ScenarioTestCaseRequest = Field(
        validation_alias=AliasChoices("test_case", "testCase")
    )
    after_actions: list[ScenarioActionRequest] = Field(
        default_factory=list,
        validation_alias=AliasChoices("after_actions", "afterActions"),
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @model_validator(mode="after")
    def validate_ids(self):
        ids = [action.id for action in self.before_actions]
        ids.append(self.test_case.id)
        ids.extend(action.id for action in self.after_actions)
        if len(ids) != len(set(ids)):
            raise ValueError("节点内步骤 ID 不能重复")
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

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


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
        if "records" in data:
            data.pop("request_overrides", None)
            data.pop("requestOverrides", None)
            return data
        if "request_overrides" not in data and "requestOverrides" not in data:
            data["records"] = []
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
    nodes: list[ScenarioNodeRequest] = Field(min_length=1)
    datasets: list[ScenarioDatasetRequest] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @model_validator(mode="after")
    def normalize(self):
        self.name = self.name.strip()
        self.tags = list(dict.fromkeys(tag.strip() for tag in self.tags if tag.strip()))
        if len({node.id for node in self.nodes}) != len(self.nodes):
            raise ValueError("节点 ID 不能重复")
        executable_ids = [
            item.id
            for node in self.nodes
            for item in [*node.before_actions, node.test_case, *node.after_actions]
        ]
        if len(executable_ids) != len(set(executable_ids)):
            raise ValueError("场景步骤 ID 不能重复")
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
    nodes: list[dict]
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
