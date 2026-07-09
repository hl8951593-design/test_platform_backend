from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.execution_record import ExecutionType


class ExecutionCenterOverviewRead(BaseModel):
    queue_total: int = 0
    running_count: int = 0
    queued_count: int = 0
    failed_blocking_count: int = 0
    retrying_count: int = 0
    worker_online: int = 0
    worker_total: int = 0
    worker_health_rate: int = 0
    avg_duration_ms: int = 0
    avg_wait_seconds: int = 0
    ai_diagnosis_count: int = 0
    auto_fixable_count: int = 0
    refresh_interval_seconds: int = 15


class ExecutionCenterQueueItemRead(BaseModel):
    id: str
    execution_type: ExecutionType
    execution_id: int
    name: str
    trigger: str
    trigger_type: str
    priority: str
    status: str
    worker_id: str | None = None
    progress: int = 0
    eta_seconds: int = 0
    eta_text: str | None = None
    attempt: int = 1
    max_attempts: int = 3
    started_at: datetime | None = None
    updated_at: datetime | None = None


class ExecutionCenterQueuePageRead(BaseModel):
    items: list[ExecutionCenterQueueItemRead] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class ExecutionCenterWorkerRead(BaseModel):
    id: str
    state: str
    load: int
    current_job_id: str | None = None
    current_job_name: str | None = None
    heartbeat_at: datetime
    heartbeat_text: str
    capabilities: list[str] = Field(default_factory=list)


class ExecutionCenterWorkerPageRead(BaseModel):
    items: list[ExecutionCenterWorkerRead] = Field(default_factory=list)


class ExecutionCenterLogItemRead(BaseModel):
    sequence: int
    time: str
    level: str
    message: str
    run_id: str
    worker_id: str | None = None
    created_at: datetime


class ExecutionCenterLogPageRead(BaseModel):
    items: list[ExecutionCenterLogItemRead] = Field(default_factory=list)
    next_after_sequence: int


class ExecutionCenterFailureDiagnosisRead(BaseModel):
    id: str
    run_id: str
    priority: str
    title: str
    confidence: int
    summary: str
    recommendation: str
    can_create_defect: bool = True
    can_view_snapshot: bool = True
    created_at: datetime


class ExecutionCenterFailureDiagnosisPageRead(BaseModel):
    items: list[ExecutionCenterFailureDiagnosisRead] = Field(default_factory=list)


class ExecutionCenterRetryItemRead(BaseModel):
    run_id: str
    name: str
    attempt: int
    max_attempts: int
    backoff_seconds: int
    status: str
    reason: str


class ExecutionCenterRetryPageRead(BaseModel):
    items: list[ExecutionCenterRetryItemRead] = Field(default_factory=list)
