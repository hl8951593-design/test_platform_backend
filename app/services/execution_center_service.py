from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import ProjectPermission
from app.models.scenario import TestScenarioRun, TestScenarioRunEvent
from app.models.ui_execution import UiExecution
from app.models.user import User
from app.repositories.execution_record_repository import ExecutionRecordRepository
from app.schemas.execution_center import (
    ExecutionCenterFailureDiagnosisPageRead,
    ExecutionCenterFailureDiagnosisRead,
    ExecutionCenterLogItemRead,
    ExecutionCenterLogPageRead,
    ExecutionCenterOverviewRead,
    ExecutionCenterQueueItemRead,
    ExecutionCenterQueuePageRead,
    ExecutionCenterRetryItemRead,
    ExecutionCenterRetryPageRead,
    ExecutionCenterWorkerPageRead,
    ExecutionCenterWorkerRead,
)
from app.services.permission_service import PermissionService
from app.repositories.desktop_device_repository import DesktopDeviceRepository
from app.services.desktop_presence_service import desktop_presence_service


class ExecutionCenterService:
    ACTIVE_STATUSES = {"queued", "claimed", "launching", "running", "retrying", "paused", "waiting_user"}
    FAILED_STATUSES = {"failed", "error", "timeout", "lost"}
    TERMINAL_STATUSES = {"passed", "assisted", "failed", "cancelled", "lost", "timeout", "error", "success", "completed"}
    STATUS_ALIASES = {
        "pending": "queued",
        "success": "passed",
        "completed": "passed",
        "timeout": "failed",
        "error": "failed",
        "claimed": "running",
        "launching": "running",
        "waiting_user": "paused",
        "assisted": "passed",
        "lost": "failed",
    }
    TRIGGER_LABELS = {
        "plan": "测试计划",
        "scheduled": "定时任务",
        "manual": "手动执行",
        "agent": "AI Agent",
        "scenario": "场景触发",
        "flow": "Flow 触发",
    }

    def __init__(self, db: Session):
        self.db = db
        self.repository = ExecutionRecordRepository(db)
        self.desktop_repository = DesktopDeviceRepository(db)
        self.permission_service = PermissionService(db)

    def overview(
        self,
        *,
        project_id: int,
        environment_id: int | None,
        current_user: User,
    ) -> ExecutionCenterOverviewRead:
        self._require_view(current_user, project_id)
        rows = self._record_rows(project_id=project_id, environment_id=environment_id, page_size=1000)
        normalized_statuses = [self._normalize_status(row.get("status")) for row in rows]
        running_count = normalized_statuses.count("running")
        queued_count = normalized_statuses.count("queued")
        retrying_count = normalized_statuses.count("retrying")
        failed_blocking_count = normalized_statuses.count("failed")
        queue_total = running_count + queued_count + retrying_count + failed_blocking_count + normalized_statuses.count("paused")
        durations = [
            int(row["duration_ms"])
            for row in rows
            if row.get("duration_ms") is not None and self._normalize_status(row.get("status")) in {"passed", "failed", "cancelled"}
        ]
        server_worker_total = max(int(settings.EXECUTION_WORKER_MAX_WORKERS), 1)
        now = datetime.now()
        desktop_devices = self.desktop_repository.list_for_project(project_id)
        desktop_online = sum(
            1 for device in desktop_devices if self._desktop_device_online(device, now)
        )
        worker_total = server_worker_total + len(desktop_devices)
        worker_online = server_worker_total + desktop_online
        worker_health_rate = round(worker_online / worker_total * 100)
        diagnosis_count = failed_blocking_count

        return ExecutionCenterOverviewRead(
            queue_total=queue_total,
            running_count=running_count,
            queued_count=queued_count,
            failed_blocking_count=failed_blocking_count,
            retrying_count=retrying_count,
            worker_online=worker_online,
            worker_total=worker_total,
            worker_health_rate=worker_health_rate,
            avg_duration_ms=round(sum(durations) / len(durations)) if durations else 0,
            avg_wait_seconds=self._average_wait_seconds(rows),
            ai_diagnosis_count=diagnosis_count,
            auto_fixable_count=min(diagnosis_count, retrying_count + failed_blocking_count),
            refresh_interval_seconds=15,
        )

    def queue(
        self,
        *,
        project_id: int,
        environment_id: int | None,
        page: int,
        page_size: int,
        current_user: User,
    ) -> ExecutionCenterQueuePageRead:
        self._require_view(current_user, project_id)
        rows, total = self.repository.list_records(
            project_id=project_id,
            execution_type=None,
            status=None,
            environment_id=environment_id,
            trigger_user_id=None,
            started_from=None,
            started_to=None,
            keyword=None,
            page=page,
            page_size=page_size,
        )
        return ExecutionCenterQueuePageRead(
            items=[self._queue_item(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    def workers(self, *, project_id: int, current_user: User) -> ExecutionCenterWorkerPageRead:
        self._require_view(current_user, project_id)
        active_items = [
            self._queue_item(row)
            for row in self._record_rows(project_id=project_id, environment_id=None, page_size=1000)
            if row.get("execution_type") != "ui"
            and self._normalize_status(row.get("status")) in {"running", "retrying"}
        ]
        now = datetime.now()
        worker_total = max(int(settings.EXECUTION_WORKER_MAX_WORKERS), 1)
        workers: list[ExecutionCenterWorkerRead] = []
        for index in range(worker_total):
            active_item = active_items[index] if index < len(active_items) else None
            worker_id = self._worker_id(index)
            workers.append(
                ExecutionCenterWorkerRead(
                    id=worker_id,
                    state="busy" if active_item else "idle",
                    load=84 if active_item else 5,
                    current_job_id=active_item.id if active_item else None,
                    current_job_name=active_item.name if active_item else None,
                    heartbeat_at=now,
                    heartbeat_text="实时派生",
                    capabilities=["http", "websocket", "scenario", "flow"],
                    worker_kind="server",
                    online=True,
                )
            )
        desktop_devices = self.desktop_repository.list_for_project(project_id)
        active_ui_by_device: dict[int, UiExecution] = {}
        device_ids = [device.id for device in desktop_devices]
        if device_ids:
            active_ui_executions = self.db.scalars(
                select(UiExecution)
                .where(
                    UiExecution.assigned_device_id.in_(device_ids),
                    UiExecution.status.in_(
                        ("claimed", "launching", "running", "paused", "waiting_user")
                    ),
                )
                .order_by(
                    UiExecution.assigned_device_id.asc(),
                    UiExecution.updated_at.desc(),
                    UiExecution.id.desc(),
                )
            ).all()
            for execution in active_ui_executions:
                if execution.assigned_device_id is not None:
                    active_ui_by_device.setdefault(
                        execution.assigned_device_id, execution
                    )
        for device in desktop_devices:
            online = self._desktop_device_online(device, now)
            active_execution = active_ui_by_device.get(device.id)
            runtime_state = device.runtime_state_json or {}
            capabilities = device.capabilities_json or {}
            browsers = capabilities.get("browsers") or []
            workers.append(
                ExecutionCenterWorkerRead(
                    id=device.public_id,
                    state=("offline" if not online else "busy" if active_execution else "idle"),
                    load=min(max(int(runtime_state.get("current_load") or 0), 0), 100),
                    current_job_id=(
                        f"ui:{active_execution.id}" if active_execution is not None else None
                    ),
                    current_job_name=(
                        str((active_execution.case_snapshot_json or {}).get("case", {}).get("name") or "UI execution")
                        if active_execution is not None
                        else None
                    ),
                    heartbeat_at=device.last_heartbeat_at or device.registered_at,
                    heartbeat_text="Desktop heartbeat" if online else "Desktop offline",
                    capabilities=["ui", *[str(item) for item in browsers]],
                    worker_kind="desktop",
                    device_id=device.public_id,
                    online=online,
                )
            )
        return ExecutionCenterWorkerPageRead(items=workers)

    @staticmethod
    def _desktop_device_online(device: Any, now: datetime) -> bool:
        redis_online = desktop_presence_service.is_online(device.public_id)
        if redis_online is not None:
            return bool(redis_online)
        return bool(
            device.last_heartbeat_at
            and (now - device.last_heartbeat_at).total_seconds()
            < settings.DESKTOP_DEVICE_OFFLINE_AFTER_SECONDS
        )

    def logs(
        self,
        *,
        project_id: int,
        after_sequence: int,
        limit: int,
        current_user: User,
    ) -> ExecutionCenterLogPageRead:
        self._require_view(current_user, project_id)
        rows = self.db.execute(
            select(
                TestScenarioRunEvent,
                TestScenarioRun.id.label("run_id"),
                TestScenarioRun.created_at.label("run_created_at"),
                TestScenarioRun.started_at.label("run_started_at"),
            )
            .join(TestScenarioRun, TestScenarioRun.id == TestScenarioRunEvent.run_id)
            .where(
                TestScenarioRun.project_id == project_id,
                TestScenarioRunEvent.id > after_sequence,
            )
            .order_by(TestScenarioRunEvent.id.asc())
            .limit(limit)
        ).all()
        items: list[ExecutionCenterLogItemRead] = []
        for event, run_id, run_created_at, run_started_at in rows:
            created_at = event.occurred_at or run_created_at or run_started_at
            items.append(
                ExecutionCenterLogItemRead(
                    sequence=event.id,
                    time=created_at.strftime("%H:%M:%S"),
                    level=self._event_level(event.event),
                    message=self._event_message(event),
                    run_id=self._run_id(run_id),
                    worker_id=self._worker_for_execution(run_id, 0),
                    created_at=created_at,
                )
            )
        next_after_sequence = items[-1].sequence if items else after_sequence
        return ExecutionCenterLogPageRead(items=items, next_after_sequence=next_after_sequence)

    def failure_diagnosis(
        self,
        *,
        project_id: int,
        current_user: User,
    ) -> ExecutionCenterFailureDiagnosisPageRead:
        self._require_view(current_user, project_id)
        failed_rows = [
            row
            for row in self._record_rows(project_id=project_id, environment_id=None, page_size=100)
            if self._normalize_status(row.get("status")) == "failed"
        ]
        return ExecutionCenterFailureDiagnosisPageRead(
            items=[self._diagnosis_item(row) for row in failed_rows]
        )

    def retries(self, *, project_id: int, current_user: User) -> ExecutionCenterRetryPageRead:
        self._require_view(current_user, project_id)
        retry_rows = [
            row
            for row in self._record_rows(project_id=project_id, environment_id=None, page_size=100)
            if self._normalize_status(row.get("status")) == "retrying"
        ]
        return ExecutionCenterRetryPageRead(items=[self._retry_item(row) for row in retry_rows])

    def _require_view(self, current_user: User, project_id: int) -> None:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_REPORT.value,
        )

    def _record_rows(self, *, project_id: int, environment_id: int | None, page_size: int) -> list[dict[str, Any]]:
        rows, _ = self.repository.list_records(
            project_id=project_id,
            execution_type=None,
            status=None,
            environment_id=environment_id,
            trigger_user_id=None,
            started_from=None,
            started_to=None,
            keyword=None,
            page=1,
            page_size=page_size,
        )
        return rows

    def _queue_item(self, row: dict[str, Any]) -> ExecutionCenterQueueItemRead:
        status_value = self._normalize_status(row.get("status"))
        execution_id = int(row["execution_id"])
        trigger_type = self._trigger_type(row)
        progress = self._progress(status_value)
        eta_seconds = 0 if status_value in self.TERMINAL_STATUSES else 300
        worker_id = None
        if row["execution_type"] == "ui":
            worker_id = row.get("worker_id")
        elif status_value in {"running", "retrying"}:
            worker_id = self._worker_for_execution(execution_id, 0)
        return ExecutionCenterQueueItemRead(
            id=self._run_id(execution_id),
            execution_type=row["execution_type"],
            execution_id=execution_id,
            name=row.get("resource_name") or f"{row['execution_type']} 执行 {execution_id}",
            trigger=self._trigger_label(trigger_type),
            trigger_type=trigger_type,
            priority=self._priority(status_value),
            status=status_value,
            worker_id=worker_id,
            progress=progress,
            eta_seconds=eta_seconds,
            eta_text=self._eta_text(eta_seconds, status_value),
            attempt=1,
            max_attempts=3,
            started_at=row.get("started_at"),
            updated_at=row.get("finished_at") or row.get("created_at") or row.get("started_at"),
        )

    def _diagnosis_item(self, row: dict[str, Any]) -> ExecutionCenterFailureDiagnosisRead:
        execution_id = int(row["execution_id"])
        name = row.get("resource_name") or f"{row['execution_type']} 执行 {execution_id}"
        return ExecutionCenterFailureDiagnosisRead(
            id=f"diag-{row['execution_type']}-{execution_id}",
            run_id=self._run_id(execution_id),
            priority="P0",
            title="执行失败待诊断",
            confidence=80,
            summary=row.get("error_message") or f"{name} 最近一次执行失败。",
            recommendation="建议先查看执行快照、环境变量和断言结果，再决定是否重试或创建缺陷。",
            can_create_defect=True,
            can_view_snapshot=True,
            created_at=row.get("created_at") or row.get("started_at") or datetime.now(),
        )

    def _retry_item(self, row: dict[str, Any]) -> ExecutionCenterRetryItemRead:
        execution_id = int(row["execution_id"])
        return ExecutionCenterRetryItemRead(
            run_id=self._run_id(execution_id),
            name=row.get("resource_name") or f"{row['execution_type']} 执行 {execution_id}",
            attempt=2,
            max_attempts=3,
            backoff_seconds=30,
            status="retrying",
            reason=row.get("error_message") or "等待重试调度",
        )

    def _average_wait_seconds(self, rows: list[dict[str, Any]]) -> int:
        queued_rows = [
            row for row in rows if self._normalize_status(row.get("status")) == "queued" and row.get("created_at")
        ]
        if not queued_rows:
            return 0
        now = datetime.now()
        waits = [
            max(int((now - row["created_at"]).total_seconds()), 0)
            for row in queued_rows
        ]
        return round(sum(waits) / len(waits)) if waits else 0

    def _trigger_type(self, row: dict[str, Any]) -> str:
        if row["execution_type"] in {"http", "websocket"} and row.get("scenario_run_id") is None:
            return "manual"
        return row.get("scenario_trigger") or "manual"

    def _trigger_label(self, trigger_type: str) -> str:
        return self.TRIGGER_LABELS.get(trigger_type, trigger_type)

    def _normalize_status(self, status_value: str | None) -> str:
        if status_value is None:
            return "queued"
        return self.STATUS_ALIASES.get(status_value, status_value)

    def _priority(self, status_value: str) -> str:
        if status_value == "failed":
            return "P0"
        if status_value in {"running", "retrying"}:
            return "P1"
        if status_value == "queued":
            return "P2"
        return "P3"

    def _progress(self, status_value: str) -> int:
        if status_value in {"passed", "failed", "cancelled"}:
            return 100
        if status_value in {"running", "retrying"}:
            return 50
        return 0

    def _eta_text(self, eta_seconds: int, status_value: str) -> str | None:
        if eta_seconds <= 0 or status_value in self.TERMINAL_STATUSES:
            return None
        minutes = max(round(eta_seconds / 60), 1)
        return f"预计 {minutes}m 后完成"

    def _run_id(self, execution_id: int) -> str:
        return f"RUN-{execution_id}"

    def _worker_for_execution(self, execution_id: int, offset: int) -> str:
        worker_total = max(int(settings.EXECUTION_WORKER_MAX_WORKERS), 1)
        worker_index = (execution_id + offset) % worker_total
        return self._worker_id(worker_index)

    def _worker_id(self, index: int) -> str:
        return f"execution-worker-{index + 1:02d}"

    def _event_level(self, event_name: str) -> str:
        lowered = event_name.lower()
        if "fail" in lowered or "error" in lowered:
            return "error"
        if "retry" in lowered:
            return "warning"
        return "info"

    def _event_message(self, event: TestScenarioRunEvent) -> str:
        payload = event.payload or {}
        if isinstance(payload, dict) and payload.get("message"):
            return str(payload["message"])
        return event.event
