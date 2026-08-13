from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


UiCaseStatus = Literal["draft", "active", "disabled"]
UiStepKind = Literal["action", "assertion"]

UI_ACTIONS = frozenset(
    {
        "navigate",
        "reload",
        "go_back",
        "go_forward",
        "click",
        "dblclick",
        "fill",
        "clear",
        "press",
        "select",
        "check",
        "uncheck",
        "hover",
        "focus",
        "blur",
        "scroll_into_view",
        "wait_for",
        "drag_to",
        "upload",
        "download",
        "screenshot",
    }
)
UI_ASSERTIONS = frozenset(
    {
        "visible",
        "hidden",
        "enabled",
        "disabled",
        "editable",
        "checked",
        "unchecked",
        "empty",
        "focused",
        "in_viewport",
        "text",
        "value",
        "attribute",
        "count",
        "url",
        "title",
        "screenshot",
    }
)
UI_LOCATORS = frozenset(
    {"role", "label", "test_id", "text", "placeholder", "alt", "title", "css", "xpath"}
)
SECRET_REFERENCE_RE = re.compile(r"\$\{secret\.([A-Za-z_][A-Za-z0-9_.-]*)\}")


class UiCaseBrowserConfig(BaseModel):
    engine: Literal["chromium"] = "chromium"
    channel: Literal["chromium", "chrome", "msedge"] | None = None
    headless: bool = False
    profile_ref: str | None = Field(default=None, max_length=128)

    model_config = ConfigDict(extra="forbid")

    @field_validator("profile_ref")
    @classmethod
    def validate_profile_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", normalized):
            raise ValueError("profile_ref 必须是本地 Profile 别名，不能是文件路径")
        return normalized


class UiCaseSettings(BaseModel):
    step_timeout_ms: int = Field(default=10000, ge=1000, le=120000)
    navigation_timeout_ms: int = Field(default=30000, ge=1000, le=180000)
    trace: Literal["off", "on", "retain-on-failure"] = "retain-on-failure"
    screenshot: Literal["off", "only-on-failure", "on-each-step"] = "only-on-failure"

    model_config = ConfigDict(extra="forbid")


class UiRecordingLocatorCandidate(BaseModel):
    by: str = Field(min_length=1, max_length=32)
    value: str = Field(min_length=1, max_length=2048)
    recommended: bool = False
    match_count: int | None = Field(default=None, ge=0, le=100000)
    stability: str = Field(default="", max_length=32)
    score: int = Field(default=0, ge=-100000, le=100000)
    exact: bool = False
    within: dict[str, Any] = Field(default_factory=dict, max_length=16)
    filters: dict[str, Any] = Field(default_factory=dict, max_length=16)
    fingerprint_similarity: float | None = Field(default=None, ge=0, le=1)
    actionability: bool | None = None
    reasons: list[str] = Field(default_factory=list, max_length=16)

    model_config = ConfigDict(extra="forbid")

    @field_validator("by")
    @classmethod
    def validate_locator_by(cls, value: str) -> str:
        if value not in UI_LOCATORS:
            raise ValueError("录制候选使用了不受支持的定位器类型")
        return value


class UiRecordingShadowHost(BaseModel):
    tag: str = Field(default="", max_length=40)
    role: str = Field(default="", max_length=80)
    accessible_name: str = Field(default="", max_length=240)
    test_id: str = Field(default="", max_length=240)
    name: str = Field(default="", max_length=160)

    model_config = ConfigDict(extra="forbid")


class UiRecordingTargetFingerprint(BaseModel):
    version: int = Field(default=1, ge=1, le=100)
    tag: str = Field(default="", max_length=40)
    input_type: str = Field(default="", max_length=40)
    role: str = Field(default="", max_length=80)
    accessible_name: str = Field(default="", max_length=240)
    test_id: str = Field(default="", max_length=240)
    label: str = Field(default="", max_length=240)
    text: str = Field(default="", max_length=500)
    placeholder: str = Field(default="", max_length=240)
    name: str = Field(default="", max_length=160)
    form: str = Field(default="", max_length=240)
    landmark: str = Field(default="", max_length=240)
    shadow_root: str = Field(default="", max_length=20)
    shadow_hosts: list[UiRecordingShadowHost] = Field(default_factory=list, max_length=8)
    shadow_contract: str = Field(default="", max_length=240)
    stable_attributes: dict[str, str] = Field(default_factory=dict, max_length=16)

    model_config = ConfigDict(extra="forbid")


class UiRecordingLocatorPlan(BaseModel):
    version: int = Field(default=1, ge=1, le=100)
    primary: UiRecordingLocatorCandidate | None = None
    fallbacks: list[UiRecordingLocatorCandidate] = Field(default_factory=list, max_length=10)

    model_config = ConfigDict(extra="forbid")


class UiRecordingActionState(BaseModel):
    url: str = Field(default="", max_length=4096)
    title: str = Field(default="", max_length=512)
    visible: bool | None = None
    disabled: bool | None = None
    checked: bool | None = None
    text: str = Field(default="", max_length=2000)
    value: str = Field(default="", max_length=4096)

    model_config = ConfigDict(extra="forbid")


class UiRecordingActionEpisode(BaseModel):
    version: int = Field(default=1, ge=1, le=100)
    pre_state: UiRecordingActionState = Field(default_factory=UiRecordingActionState)
    post_state: UiRecordingActionState = Field(default_factory=UiRecordingActionState)
    signals: list[str] = Field(default_factory=list, max_length=16)

    model_config = ConfigDict(extra="forbid")


class UiRecordingValidationLane(BaseModel):
    run: int = Field(ge=1, le=20)
    locator: str = Field(default="", max_length=32)
    identity: str = Field(default="", max_length=32)
    actionability: str = Field(default="", max_length=32)
    session: str = Field(default="", max_length=32)
    variant: str = Field(default="", max_length=32)
    execution: str = Field(default="", max_length=32)
    error: str = Field(default="", max_length=2000)
    target_similarity: float | None = Field(default=None, ge=0, le=1)

    model_config = ConfigDict(extra="forbid")


class UiRecordingNetworkDependency(BaseModel):
    classification: Literal["primary", "dependency", "noise"]
    method: str = Field(min_length=1, max_length=16)
    url: str = Field(min_length=1, max_length=4096)
    resource_type: str = Field(default="", max_length=32)
    elapsed_ms: int = Field(default=0, ge=0, le=3600000)

    model_config = ConfigDict(extra="forbid")


class UiCaseStepOptions(BaseModel):
    wait_until: Literal["domcontentloaded", "load", "networkidle", "commit"] = "domcontentloaded"
    wait_for_network_idle: bool = False
    button: Literal["left", "right", "middle"] = "left"
    modifiers: list[Literal["Alt", "Control", "ControlOrMeta", "Meta", "Shift"]] = Field(
        default_factory=list,
        max_length=4,
    )
    after_click: Literal["none", "popup", "download"] = "none"
    dialog_action: Literal["none", "accept", "dismiss"] = "none"
    dialog_prompt: str = Field(default="", max_length=2000)
    select_by: Literal["value", "label", "index"] = "value"
    target_locator_by: str | None = Field(default=None, max_length=32)
    target_locator_value: str = Field(default="", max_length=2048)
    filename: str = Field(default="", max_length=255)
    full_page: bool = False
    exact: bool = False
    nth: int = Field(default=-1, ge=-1, le=9999)
    frame_locator: str = Field(default="", max_length=2048)
    accessible_name: str = Field(default="", max_length=512)
    assertion_message: str = Field(default="", max_length=1000)
    source_page_url: str = Field(default="", max_length=4096)
    source_frame_url: str = Field(default="", max_length=4096)
    destination_page_url: str = Field(default="", max_length=4096)
    destination_page_title: str = Field(default="", max_length=512)
    page_id: str = Field(default="", max_length=128)
    recording_event_id: str = Field(default="", max_length=128)
    recording_action_id: str = Field(default="", max_length=128)
    locator_candidates: list[UiRecordingLocatorCandidate] = Field(
        default_factory=list,
        max_length=20,
    )
    target_fingerprint: UiRecordingTargetFingerprint | None = None
    locator_plan: UiRecordingLocatorPlan | None = None
    action_episode: UiRecordingActionEpisode | None = None
    target_similarity: float | None = Field(default=None, ge=0, le=1)
    actionability_passed: bool | None = None
    validation_lanes: list[UiRecordingValidationLane] = Field(default_factory=list, max_length=20)
    hard_gate_failures: list[str] = Field(default_factory=list, max_length=32)
    frame_path: list[str] = Field(default_factory=list, max_length=16)
    source_is_main_frame: bool | None = None
    network_dependencies: list[UiRecordingNetworkDependency] = Field(
        default_factory=list,
        max_length=100,
    )

    model_config = ConfigDict(extra="forbid")


class UiCaseStep(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    kind: UiStepKind
    operation: str = Field(min_length=1, max_length=32)
    locator_by: str | None = Field(default=None, max_length=32)
    locator_value: str = Field(default="", max_length=2048)
    input_value: str | int | float | bool | None = None
    timeout_ms: int = Field(default=10000, ge=1000, le=180000)
    failure_policy: Literal[
        "停止运行",
        "重试一次",
        "继续下一步",
        "等待人工处理",
    ] = "停止运行"
    notes: str = Field(default="", max_length=2000)
    enabled: bool = True
    operator: Literal["equals", "contains", "matches", "not_equals"] | None = None
    attribute_name: str | None = Field(default=None, min_length=1, max_length=128)
    baseline_ref: str | None = Field(default=None, min_length=1, max_length=256)
    options: UiCaseStepOptions = Field(default_factory=UiCaseStepOptions)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def normalize_client_and_target_shapes(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        data.setdefault("kind", data.get("type"))
        kind = data.get("kind")
        if "operation" not in data:
            if kind == "action":
                data["operation"] = data.get("action")
            elif kind == "assertion":
                data["operation"] = data.get("assertion")

        locator = data.get("locator")
        if isinstance(locator, dict):
            locator_by = locator.get("by")
            data.setdefault("locator_by", locator_by)
            if locator_by == "role":
                role = str(locator.get("role") or locator.get("value") or "").strip()
                accessible_name = str(locator.get("name") or "").strip()
                locator_value = f"{role}: {accessible_name}" if accessible_name else role
            else:
                locator_value = str(locator.get("value") or "")
            data.setdefault("locator_value", locator_value)

        if "input_value" not in data:
            for candidate in ("url", "value", "expected", "file_alias"):
                if candidate in data:
                    data["input_value"] = data[candidate]
                    break
        if "attribute_name" not in data and "attribute" in data:
            data["attribute_name"] = data["attribute"]

        for field_name in (
            "type",
            "action",
            "assertion",
            "locator",
            "url",
            "value",
            "expected",
            "file_alias",
            "attribute",
            "status",
            "duration_ms",
            "runtime_patch",
        ):
            data.pop(field_name, None)
        return data

    @field_validator("id")
    @classmethod
    def validate_step_id(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,127}", normalized):
            raise ValueError("步骤 id 必须以字母开头，且只能包含字母、数字、下划线和连字符")
        return normalized

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_operation(self):
        allowed = UI_ACTIONS if self.kind == "action" else UI_ASSERTIONS
        if self.operation not in allowed:
            raise ValueError(f"{self.kind} 不支持操作 {self.operation}")

        locator_not_required = (
            self.kind == "action"
            and self.operation in {"navigate", "reload", "go_back", "go_forward", "screenshot"}
        ) or (
            self.kind == "assertion"
            and self.operation in {"url", "title", "screenshot"}
        )
        if not locator_not_required:
            if self.locator_by not in UI_LOCATORS:
                raise ValueError("当前步骤必须提供受支持的 locator_by")
            if not self.locator_value.strip():
                raise ValueError("当前步骤必须提供 locator_value")
        elif self.locator_by is not None and self.locator_by not in UI_LOCATORS:
            raise ValueError("locator_by 不受支持")

        requires_input = (
            self.kind == "action"
            and self.operation in {"navigate", "fill", "press", "select", "upload", "wait_for"}
        ) or (
            self.kind == "assertion"
            and self.operation in {"text", "value", "attribute", "count", "url", "title"}
        )
        if requires_input and self.input_value in (None, ""):
            raise ValueError("当前步骤必须提供 input_value")
        if self.operation == "attribute" and not self.attribute_name:
            raise ValueError("attribute 断言必须提供 attribute_name")
        if self.operation == "count":
            try:
                int(str(self.input_value))
            except (TypeError, ValueError) as exc:
                raise ValueError("count 断言 input_value 必须是整数") from exc
        if self.operation == "upload" and isinstance(self.input_value, str):
            value = self.input_value.strip()
            if not (
                re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_.-]*\}", value)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value)
            ):
                raise ValueError("upload 只能使用文件别名，不能保存本机绝对路径")
        if self.operation == "drag_to":
            if self.options.target_locator_by not in UI_LOCATORS:
                raise ValueError("drag_to 必须提供受支持的 target_locator_by")
            if not self.options.target_locator_value.strip():
                raise ValueError("drag_to 必须提供 target_locator_value")
        if self.operation == "select" and self.options.select_by == "index":
            try:
                int(str(self.input_value))
            except (TypeError, ValueError) as exc:
                raise ValueError("按序号选择时 input_value 必须是整数") from exc
        if self.operation != "navigate" and self.timeout_ms > 120000:
            raise ValueError("非导航步骤 timeout_ms 不能超过 120000")
        if isinstance(self.input_value, str):
            malformed_secret = "${secret." in self.input_value and not SECRET_REFERENCE_RE.search(
                self.input_value
            )
            if malformed_secret:
                raise ValueError("secret 引用格式无效")
        return self


class UiCaseDsl(BaseModel):
    schema_version: Literal["ui-case-v1"] = "ui-case-v1"
    case_id: str | None = Field(default=None, max_length=64)
    version: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, max_length=128)
    project_id: int | None = Field(default=None, gt=0)
    environment_id: int | None = Field(default=None, gt=0)
    browser: UiCaseBrowserConfig = Field(default_factory=UiCaseBrowserConfig)
    settings: UiCaseSettings = Field(default_factory=UiCaseSettings)
    steps: list[UiCaseStep] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_unique_step_ids(self):
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("步骤 id 不能重复")
        return self

    def canonical_dict(self) -> dict[str, Any]:
        canonical_steps: list[dict[str, Any]] = []
        for step in self.steps:
            dumped = step.model_dump(mode="json")
            if dumped.get("options") == UiCaseStepOptions().model_dump(mode="json"):
                dumped.pop("options", None)
            canonical_steps.append(dumped)
        return {
            "schema_version": self.schema_version,
            "browser": self.browser.model_dump(mode="json"),
            "settings": self.settings.model_dump(mode="json"),
            "steps": canonical_steps,
        }


class UiTestCaseValidateRequest(BaseModel):
    default_environment_id: int | None = Field(default=None, gt=0)
    dsl: UiCaseDsl

    model_config = ConfigDict(extra="forbid")


class UiTestCaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=10000)
    status: UiCaseStatus = "draft"
    tags: list[str] = Field(default_factory=list)
    default_environment_id: int = Field(gt=0)
    dsl: UiCaseDsl
    change_summary: str | None = Field(default=None, max_length=512)

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def strip_create_name(cls, value: str) -> str:
        return value.strip()


class UiTestCaseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=10000)
    status: UiCaseStatus | None = None
    tags: list[str] | None = None
    default_environment_id: int | None = Field(default=None, gt=0)

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def strip_update_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个待更新字段")
        return self


class UiTestCaseVersionCreateRequest(BaseModel):
    base_version: int = Field(ge=1)
    dsl: UiCaseDsl
    change_summary: str | None = Field(default=None, max_length=512)

    model_config = ConfigDict(extra="forbid")


class UiTestCaseValidationRead(BaseModel):
    valid: Literal[True] = True
    schema_version: Literal["ui-case-v1"] = "ui-case-v1"
    checksum: str
    step_count: int
    required_secret_refs: list[str]
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    normalized_dsl: dict[str, Any]


class UiTestCaseVersionSummaryRead(BaseModel):
    version: int
    schema_version: str
    checksum: str
    step_count: int
    required_secret_refs: list[str]
    based_on_version: int | None
    change_summary: str | None
    created_by_id: int
    created_at: datetime


class UiTestCaseVersionRead(UiTestCaseVersionSummaryRead):
    dsl: dict[str, Any]


class UiTestCaseListItemRead(BaseModel):
    case_id: str
    project_id: int
    default_environment_id: int | None
    default_environment_name: str | None
    name: str
    description: str | None
    status: UiCaseStatus
    tags: list[str]
    current_version: int
    step_count: int
    checksum: str
    created_by_id: int
    created_at: datetime
    updated_at: datetime


class UiTestCaseRead(UiTestCaseListItemRead):
    current_version_detail: UiTestCaseVersionRead
