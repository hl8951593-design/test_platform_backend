import copy
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.sensitive_data import mask_sensitive
from app.schemas.ai import AIRunEventRead, AISkillRunRead, AISkillRunRequest


TERMINAL_RUN_STATUSES = {"completed", "failed"}


class AIRunEventStore:
    def __init__(self):
        self._condition = threading.Condition()
        self._runs: dict[str, dict[str, Any]] = {}

    def create_run(self, *, skill_id: str, payload: AISkillRunRequest, user_id: int) -> AISkillRunRead:
        now = self._now()
        run_id = f"ai-run-{uuid.uuid4().hex}"
        with self._condition:
            self._runs[run_id] = {
                "run_id": run_id,
                "skill_id": skill_id,
                "operation": payload.operation,
                "project_id": payload.project_id,
                "user_id": user_id,
                "status": "queued",
                "events": [],
                "result": None,
                "error_message": None,
                "created_at": now,
                "updated_at": now,
                "next_sequence": 1,
            }
            self._append_locked(run_id, "run.queued", {
                "skill_id": skill_id,
                "operation": payload.operation,
                "project_id": payload.project_id,
            })
            self._condition.notify_all()
            return self.get_run(run_id)

    def get_run(self, run_id: str) -> AISkillRunRead:
        with self._condition:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError(run_id)
            return self._read_locked(run)

    def get_run_user_id(self, run_id: str) -> int:
        with self._condition:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError(run_id)
            return int(run["user_id"])

    def start_run(self, run_id: str) -> None:
        with self._condition:
            self._set_status_locked(run_id, "running")
            self._append_locked(run_id, "run.started", {})
            self._condition.notify_all()

    def complete_run(self, run_id: str, result: Any) -> None:
        with self._condition:
            run = self._runs[run_id]
            run["result"] = mask_sensitive(copy.deepcopy(result))
            self._set_status_locked(run_id, "completed")
            self._append_locked(run_id, "run.completed", {"result": run["result"]})
            self._condition.notify_all()

    def fail_run(self, run_id: str, error_message: str) -> None:
        with self._condition:
            run = self._runs[run_id]
            run["error_message"] = error_message
            self._set_status_locked(run_id, "failed")
            self._append_locked(run_id, "run.failed", {"error_message": error_message})
            self._condition.notify_all()

    def append(self, run_id: str, event: str, payload: dict[str, Any] | None = None) -> AIRunEventRead:
        with self._condition:
            item = self._append_locked(run_id, event, payload or {})
            self._condition.notify_all()
            return item

    def wait_for_events(self, run_id: str, after_sequence: int, timeout_seconds: float = 15) -> tuple[list[AIRunEventRead], str]:
        with self._condition:
            if run_id not in self._runs:
                raise KeyError(run_id)
            self._condition.wait_for(
                lambda: (
                    run_id not in self._runs
                    or self._runs[run_id]["status"] in TERMINAL_RUN_STATUSES
                    or any(item.sequence > after_sequence for item in self._runs[run_id]["events"])
                ),
                timeout=timeout_seconds,
            )
            run = self._runs[run_id]
            events = [item for item in run["events"] if item.sequence > after_sequence]
            return events, str(run["status"])

    def _append_locked(self, run_id: str, event: str, payload: dict[str, Any]) -> AIRunEventRead:
        run = self._runs[run_id]
        item = AIRunEventRead(
            sequence=run["next_sequence"],
            event=event,
            payload=mask_sensitive(copy.deepcopy(payload)),
            created_at=self._now(),
        )
        run["next_sequence"] += 1
        run["events"].append(item)
        run["updated_at"] = item.created_at
        return item

    def _set_status_locked(self, run_id: str, status: str) -> None:
        run = self._runs[run_id]
        run["status"] = status
        run["updated_at"] = self._now()

    def _read_locked(self, run: dict[str, Any]) -> AISkillRunRead:
        return AISkillRunRead(
            run_id=run["run_id"],
            skill_id=run["skill_id"],
            operation=run["operation"],
            project_id=run["project_id"],
            status=run["status"],
            events=list(run["events"]),
            result=copy.deepcopy(run["result"]),
            error_message=run["error_message"],
            created_at=run["created_at"],
            updated_at=run["updated_at"],
        )

    def _now(self) -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class AIRunTrace:
    def __init__(self, store: AIRunEventStore | None = None, run_id: str | None = None):
        self.store = store
        self.run_id = run_id

    def emit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        if self.store is None or self.run_id is None:
            return
        self.store.append(self.run_id, event, payload or {})

    def step_started(self, title: str, **payload: Any) -> None:
        self.emit("step.started", {"title": title, **payload})

    def step_completed(self, title: str, **payload: Any) -> None:
        self.emit("step.completed", {"title": title, **payload})

    def tool_started(self, name: str, **payload: Any) -> None:
        self.emit("tool.started", {"name": name, **payload})

    def tool_completed(self, name: str, **payload: Any) -> None:
        self.emit("tool.completed", {"name": name, **payload})

    def model_started(self, model: str | None = None) -> None:
        self.emit("model.started", {"model": model})

    def model_delta(self, content: str) -> None:
        if content:
            self.emit("model.delta", {"content": content})

    def model_completed(self, **payload: Any) -> None:
        self.emit("model.completed", payload)


ai_run_event_store = AIRunEventStore()
