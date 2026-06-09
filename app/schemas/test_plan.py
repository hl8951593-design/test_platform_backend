from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.core.config import settings
from app.core.cron import parse_cron, validate_timezone

TargetKind = Literal["scenario"]
TriggerType = Literal["manual", "cron", "webhook"]


class TestPlanTargetRequest(BaseModel):
    reference_id: int
    kind: TargetKind
    sort_order: int = Field(ge=1)


class TestPlanTargetRead(TestPlanTargetRequest):
    id: str
    name: str
    method: str | None = None
    path: str | None = None
    scenario_version: int | None = None


class TestPlanPayload(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    enabled: bool = False
    trigger_type: TriggerType = "manual"
    cron_expression: str | None = Field(default=None, max_length=128)
    schedule_timezone: str = Field(default=settings.TEST_PLAN_DEFAULT_TIMEZONE, max_length=64)
    webhook_event: str | None = Field(default=None, max_length=128)
    environment_ids: list[int] = Field(min_length=1)
    targets: list[TestPlanTargetRequest] = Field(min_length=1)
    execution_mode: Literal["serial", "parallel"] = "serial"
    failure_policy: Literal["stop", "continue"] = "stop"
    retry_count: int = Field(default=0, ge=0, le=10)
    timeout_minutes: int = Field(default=30, ge=1, le=1440)
    notification_emails: list[EmailStr] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_trigger_and_duplicates(self):
        if self.trigger_type == "cron":
            if not self.cron_expression:
                raise ValueError("Cron 触发必须提供 cron_expression")
            try:
                parse_cron(self.cron_expression)
            except ValueError as exc:
                raise ValueError("cron_expression 不是合法的 5 字段 Cron 表达式") from exc
            validate_timezone(self.schedule_timezone)
        if self.trigger_type == "webhook" and not self.webhook_event:
            raise ValueError("Webhook 触发必须提供 webhook_event")
        if len(set(self.environment_ids)) != len(self.environment_ids):
            raise ValueError("environment_ids 不能重复")
        target_keys = [(target.kind, target.reference_id) for target in self.targets]
        if len(set(target_keys)) != len(target_keys):
            raise ValueError("执行目标不能重复")
        if len(set(target.sort_order for target in self.targets)) != len(self.targets):
            raise ValueError("目标 sort_order 不能重复")
        self.name = self.name.strip()
        self.tags = list(dict.fromkeys(tag.strip() for tag in self.tags if tag.strip()))
        return self


class TestPlanCreateRequest(TestPlanPayload):
    pass


class TestPlanUpdateRequest(TestPlanPayload):
    version: int = Field(ge=1)


class TestPlanEnabledRequest(BaseModel):
    enabled: bool
    version: int | None = Field(default=None, ge=1)


class TestPlanExecuteRequest(BaseModel):
    environment_id: int
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class TestPlanImportRequest(BaseModel):
    plans: list[TestPlanCreateRequest]


class TestPlanRead(BaseModel):
    id: int
    project_id: int
    version: int
    name: str
    description: str | None
    enabled: bool
    trigger_type: str
    cron_expression: str | None
    schedule_timezone: str
    webhook_event: str | None
    environment_ids: list[int]
    targets: list[TestPlanTargetRead]
    execution_mode: str
    failure_policy: str
    retry_count: int
    timeout_minutes: int
    notification_emails: list[str]
    tags: list[str]
    created_by_id: int
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None
    next_run_at: datetime | None

    model_config = {"from_attributes": True}


class TestPlanRunRead(BaseModel):
    id: int
    plan_id: int | None
    plan_name: str
    plan_version: int
    project_id: int
    environment_id: int | None
    environment_name: str | None
    status: str
    trigger: str
    scheduled_at: datetime | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    target_count: int
    passed_count: int
    failed_count: int
    operator: dict
    target_results: list[dict] | None = None
