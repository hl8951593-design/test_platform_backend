import ast
import copy
import hashlib
import secrets
import re
import string
import time
import uuid
from datetime import datetime
from typing import Any, Callable

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.core.sensitive_data import (
    decrypt_sensitive,
    encrypt_sensitive,
    mask_sensitive,
    request_fingerprint,
)
from app.models.project import ProjectEnvironment
from app.db.session import SessionLocal
from app.models.scenario import (
    TestScenario,
    TestScenarioExecution,
    TestScenarioRun,
    TestScenarioRunEvent,
    TestScenarioVersion,
)
from app.models.test_case import TestCase, TestCaseExecution
from app.models.user import User
from app.models.websocket_test_case import WebSocketTestCase, WebSocketTestCaseExecution
from app.schemas.scenario import (
    ScenarioCreateRequest,
    ScenarioDatasetRequest,
    ScenarioPayload,
    ScenarioUpdateRequest,
)
from app.schemas.test_case import TestCaseRequestConfig
from app.schemas.websocket_test_case import WebSocketTestCaseConfig
from app.services.permission_service import PermissionService
from app.services.scenario_script_sandbox import run_scenario_script
from app.services.test_case_service import TestCaseService
from app.services.websocket_test_case_service import WebSocketTestCaseService


class ScenarioService:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def list_scenarios(self, *, project_id: int, current_user: User, keyword: str | None,
                       page: int, page_size: int) -> dict[str, Any]:
        self._require_view(current_user, project_id)
        filters = [TestScenario.project_id == project_id, TestScenario.is_deleted.is_(False)]
        if keyword:
            filters.append(or_(TestScenario.name.contains(keyword), TestScenario.description.contains(keyword)))
        total = self.db.scalar(select(func.count()).select_from(TestScenario).where(*filters)) or 0
        scenarios = list(self.db.scalars(
            select(TestScenario).where(*filters).order_by(TestScenario.updated_at.desc(), TestScenario.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).all())
        return {
            "items": [self._detail(item) for item in scenarios],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_scenario(self, *, project_id: int, scenario_id: int, current_user: User) -> dict[str, Any]:
        self._require_view(current_user, project_id)
        return self._detail(self._get_scenario(project_id, scenario_id))

    def create_scenario(self, *, project_id: int, payload: ScenarioCreateRequest, current_user: User) -> dict[str, Any]:
        self._require_manage(current_user, project_id)
        definition = self._validated_definition(project_id, payload)
        scenario = TestScenario(
            project_id=project_id, environment_id=payload.environment_id, current_version=1,
            name=payload.name, description=payload.description, tags=payload.tags,
            created_by_id=current_user.id, updated_by_id=current_user.id,
        )
        self.db.add(scenario)
        self._flush_unique()
        self.db.add(TestScenarioVersion(
            scenario_id=scenario.id, version=1, definition=definition, created_by_id=current_user.id
        ))
        self._commit_unique()
        self.db.refresh(scenario)
        return self._detail(scenario)

    def update_scenario(self, *, project_id: int, scenario_id: int, payload: ScenarioUpdateRequest,
                        current_user: User) -> dict[str, Any]:
        self._require_manage(current_user, project_id)
        scenario = self._get_scenario(project_id, scenario_id)
        if scenario.current_version != payload.version:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
                "message": "场景版本冲突", "current_version": scenario.current_version,
            })
        definition = self._validated_definition(project_id, payload)
        scenario.current_version += 1
        scenario.environment_id = payload.environment_id
        scenario.name = payload.name
        scenario.description = payload.description
        scenario.tags = payload.tags
        scenario.updated_by_id = current_user.id
        self.db.add(TestScenarioVersion(
            scenario_id=scenario.id, version=scenario.current_version,
            definition=definition, created_by_id=current_user.id,
        ))
        self._commit_unique()
        self.db.refresh(scenario)
        return self._detail(scenario)

    def delete_scenario(self, *, project_id: int, scenario_id: int, current_user: User) -> None:
        self._require_manage(current_user, project_id)
        scenario = self._get_scenario(project_id, scenario_id)
        from app.models.test_plan import TestPlan, TestPlanScenario

        referenced = self.db.scalar(
            select(func.count())
            .select_from(TestPlanScenario)
            .join(TestPlan, TestPlan.id == TestPlanScenario.plan_id)
            .where(TestPlanScenario.scenario_id == scenario_id, TestPlan.is_deleted.is_(False))
        ) or 0
        if referenced:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="场景已被测试计划引用，不能删除")
        version_ids = list(self.db.scalars(
            select(TestScenarioVersion.id).where(
                TestScenarioVersion.scenario_id == scenario.id
            )
        ).all())
        self.db.execute(
            update(TestScenarioRun)
            .where(TestScenarioRun.scenario_id == scenario.id)
            .values(scenario_id=None, scenario_version_id=None)
        )
        self.db.execute(
            update(TestScenarioExecution)
            .where(TestScenarioExecution.scenario_id == scenario.id)
            .values(scenario_id=None, scenario_version_id=None)
        )
        if version_ids:
            self.db.execute(
                delete(TestScenarioVersion).where(TestScenarioVersion.id.in_(version_ids))
            )
        self.db.delete(scenario)
        self.db.commit()

    def execute_scenario(self, *, project_id: int, scenario_id: int, environment_id: int | None,
                         dataset_ids: list[str] | None, idempotency_key: str | None, current_user: User,
                         trigger_type: str = "manual", scenario_version: int | None = None,
                         plan_run_id: int | None = None, deadline: datetime | None = None) -> list[TestScenarioRun]:
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.EXECUTE_TEST.value)
        scenario = self._get_scenario(project_id, scenario_id)
        version = self._get_version(scenario, scenario_version)
        definition = decrypt_sensitive(copy.deepcopy(version.definition))
        self._normalize_definition_datasets(definition)
        self._ensure_trace_metadata(self._execution_steps(definition))
        self._validate_request_overrides(definition)
        selected_environment_id = environment_id or scenario.environment_id
        self._get_environment(project_id, selected_environment_id)
        all_datasets = definition.get("datasets", [])
        datasets = [item for item in all_datasets if item.get("enabled", True)]
        if dataset_ids is not None:
            requested = set(dataset_ids)
            datasets = [item for item in all_datasets if item["id"] in requested]
            if {item["id"] for item in datasets} != requested:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="数据集不存在")
        elif not all_datasets:
            datasets = [{"id": None, "name": None, "variables": {}}]
        datasets = self._expand_dataset_records(datasets)

        runs = []
        for dataset in datasets:
            key_suffix = ":".join(
                item for item in (dataset.get("id"), dataset.get("record_id")) if item
            )
            key = (
                f"{idempotency_key}:{key_suffix}"
                if idempotency_key and key_suffix
                else idempotency_key
            )
            fingerprint = request_fingerprint({
                "scenario_id": scenario.id,
                "scenario_version": version.version,
                "environment_id": selected_environment_id,
                "dataset_id": dataset.get("id"),
                "record_id": dataset.get("record_id"),
                "plan_run_id": plan_run_id,
            })
            existing = self._idempotent(project_id, key, fingerprint)
            if existing:
                runs.append(existing)
                continue
            runs.append(self._execute_dataset(
                scenario=scenario, version=version, definition=definition, environment_id=selected_environment_id,
                dataset=dataset, idempotency_key=key, request_hash=fingerprint,
                current_user=current_user, trigger_type=trigger_type, plan_run_id=plan_run_id,
                deadline=deadline,
            ))
        if runs:
            scenario.last_run_at = datetime.utcnow()
            self.db.commit()
        return runs

    def enqueue_scenario(
        self,
        *,
        project_id: int,
        scenario_id: int,
        environment_id: int | None,
        dataset_ids: list[str] | None,
        idempotency_key: str | None,
        current_user: User,
    ) -> dict[str, Any]:
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.EXECUTE_TEST.value
        )
        scenario = self._get_scenario(project_id, scenario_id)
        version = self._get_version(scenario)
        definition = decrypt_sensitive(copy.deepcopy(version.definition))
        self._normalize_definition_datasets(definition)
        execution_steps = self._execution_steps(definition)
        self._ensure_trace_metadata(execution_steps)
        self._validate_request_overrides(definition)
        selected_environment_id = environment_id or scenario.environment_id
        self._get_environment(project_id, selected_environment_id)
        datasets = self._select_datasets(definition, dataset_ids)
        fingerprint = request_fingerprint({
            "scenario_id": scenario.id,
            "scenario_version": version.version,
            "environment_id": selected_environment_id,
            "records": [
                {
                    "dataset_id": item.get("id"),
                    "record_id": item.get("record_id"),
                }
                for item in datasets
            ],
        })
        existing = self._idempotent_execution(project_id, idempotency_key, fingerprint)
        if existing is not None:
            return self._queued_execution_response(existing, version.version)

        created_at = datetime.utcnow()
        execution = TestScenarioExecution(
            id=str(uuid.uuid4()),
            scenario_id=scenario.id,
            scenario_version_id=version.id,
            project_id=project_id,
            status="queued" if datasets else "passed",
            idempotency_key=idempotency_key,
            request_hash=fingerprint,
            triggered_by_id=current_user.id,
            created_at=created_at,
            finished_at=created_at if not datasets else None,
        )
        self.db.add(execution)
        self.db.flush()
        now = created_at
        for dataset in datasets:
            run_key = (
                f"scenario-execution:{execution.id}:"
                f"{dataset.get('id') or 'default'}:"
                f"{dataset.get('record_id') or 'default'}"
            )
            run = TestScenarioRun(
                execution_id=execution.id,
                scenario_id=scenario.id,
                scenario_version_id=version.id,
                project_id=project_id,
                environment_id=selected_environment_id,
                dataset_id=dataset.get("id"),
                dataset_name=dataset.get("name"),
                record_id=dataset.get("record_id"),
                record_name=dataset.get("record_name"),
                status="queued",
                trigger_type="manual",
                idempotency_key=run_key,
                request_hash=request_fingerprint({
                    "scenario_id": scenario.id,
                    "scenario_version": version.version,
                    "environment_id": selected_environment_id,
                    "dataset_id": dataset.get("id"),
                    "record_id": dataset.get("record_id"),
                    "plan_run_id": None,
                }),
                scenario_snapshot=mask_sensitive(definition),
                variables_snapshot=mask_sensitive(copy.deepcopy(dataset.get("variables") or {})),
                step_results=[
                    self._pending_result(step, index)
                    for index, step in enumerate(execution_steps)
                ],
                triggered_by_id=current_user.id,
                started_at=now,
            )
            self.db.add(run)
            self.db.flush()
            self._append_event(
                run,
                version.version,
                "run_queued",
                {"status": "queued", "total_steps": len(execution_steps)},
                commit=False,
            )
        scenario.last_run_at = now
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self._idempotent_execution(project_id, idempotency_key, fingerprint)
            if existing is None:
                raise
            execution = existing
        self.db.refresh(execution)
        return self._queued_execution_response(execution, version.version)

    @staticmethod
    def execute_queued_execution(execution_id: str) -> None:
        try:
            ScenarioService._execute_queued_execution_unchecked(execution_id)
        except Exception:  # noqa: BLE001
            with SessionLocal() as db:
                execution = db.get(TestScenarioExecution, execution_id)
                if execution is not None and execution.status not in {
                    "passed", "failed", "timeout", "cancelled"
                }:
                    ScenarioService(db)._fail_queued_execution(
                        execution, "Unexpected scenario execution failure"
                    )

    @staticmethod
    def _execute_queued_execution_unchecked(execution_id: str) -> None:
        with SessionLocal() as db:
            service = ScenarioService(db)
            execution = db.get(TestScenarioExecution, execution_id)
            if execution is None or execution.status != "queued":
                return
            user = db.get(User, execution.triggered_by_id)
            version = db.get(TestScenarioVersion, execution.scenario_version_id)
            if user is None or version is None:
                service._fail_queued_execution(execution, "Execution context no longer exists")
                return
            definition = decrypt_sensitive(copy.deepcopy(version.definition))
            service._normalize_definition_datasets(definition)
            service._ensure_trace_metadata(service._execution_steps(definition))
            service._validate_request_overrides(definition)
            execution.status = "running"
            execution.started_at = datetime.utcnow()
            db.commit()
            runs = list(db.scalars(
                select(TestScenarioRun)
                .where(TestScenarioRun.execution_id == execution.id)
                .order_by(TestScenarioRun.id)
            ).all())
            for run in runs:
                dataset = service._find_run_input(
                    definition,
                    dataset_id=run.dataset_id,
                    record_id=run.record_id,
                )
                service._run_dataset(
                    run=run,
                    definition=definition,
                    variables=copy.deepcopy(dataset.get("variables") or {}),
                    request_overrides=copy.deepcopy(
                        dataset.get("request_overrides") or []
                    ),
                    current_user=user,
                    scenario_version=version.version,
                    deadline=None,
                    emit_events=True,
                )
            execution.status = (
                "timeout" if any(run.status == "timeout" for run in runs)
                else "failed" if any(run.status == "failed" for run in runs)
                else "passed"
            )
            execution.finished_at = datetime.utcnow()
            db.commit()

    def list_runs(
        self, *, project_id: int, scenario_id: int | None, current_user: User,
        page: int, page_size: int,
    ) -> dict[str, Any]:
        self._require_view(current_user, project_id)
        filters = [TestScenarioRun.project_id == project_id]
        if scenario_id is not None:
            filters.append(TestScenarioRun.scenario_id == scenario_id)
        total = self.db.scalar(
            select(func.count()).select_from(TestScenarioRun).where(*filters)
        ) or 0
        items = list(self.db.scalars(
            select(TestScenarioRun).where(*filters).order_by(TestScenarioRun.started_at.desc(), TestScenarioRun.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).all())
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get_run(self, *, project_id: int, run_id: int, current_user: User) -> TestScenarioRun:
        self._require_view(current_user, project_id)
        run = self.db.scalar(select(TestScenarioRun).where(
            TestScenarioRun.id == run_id, TestScenarioRun.project_id == project_id
        ))
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="场景运行记录不存在")
        if run.status in {"queued", "running"}:
            run.duration_ms = max(
                int((datetime.utcnow() - run.started_at).total_seconds() * 1000), 0
            )
        return run

    def get_run_detail(self, *, project_id: int, run_id: int, current_user: User) -> dict[str, Any]:
        run = self.get_run(
            project_id=project_id, run_id=run_id, current_user=current_user
        )
        return {
            column.name: getattr(run, column.name)
            for column in TestScenarioRun.__table__.columns
        } | {
            "step_results": self._hydrate_step_result_snapshots(
                run, run.step_results or []
            )
        }

    def delete_run(self, *, project_id: int, run_id: int, current_user: User) -> None:
        self._require_manage(current_user, project_id)
        run = self.db.scalar(select(TestScenarioRun).where(
            TestScenarioRun.id == run_id,
            TestScenarioRun.project_id == project_id,
        ))
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="场景运行记录不存在",
            )
        if run.status in {"queued", "running"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="场景仍在运行，不能删除运行记录",
            )

        execution_id = run.execution_id
        self.db.execute(
            update(TestCaseExecution)
            .where(TestCaseExecution.scenario_run_id == run.id)
            .values(scenario_run_id=None)
        )
        self.db.execute(
            update(WebSocketTestCaseExecution)
            .where(WebSocketTestCaseExecution.scenario_run_id == run.id)
            .values(scenario_run_id=None)
        )
        self.db.execute(
            delete(TestScenarioRunEvent).where(TestScenarioRunEvent.run_id == run.id)
        )
        self.db.delete(run)
        self.db.flush()

        if execution_id is not None:
            remaining_runs = self.db.scalar(
                select(func.count())
                .select_from(TestScenarioRun)
                .where(TestScenarioRun.execution_id == execution_id)
            ) or 0
            if remaining_runs == 0:
                self.db.execute(
                    delete(TestScenarioExecution).where(
                        TestScenarioExecution.id == execution_id,
                        TestScenarioExecution.project_id == project_id,
                    )
                )
        self.db.commit()

    def get_run_events(
        self, *, project_id: int, run_id: int, after_sequence: int, current_user: User
    ) -> tuple[TestScenarioRun, list[TestScenarioRunEvent]]:
        run = self.get_run(project_id=project_id, run_id=run_id, current_user=current_user)
        events = list(self.db.scalars(
            select(TestScenarioRunEvent)
            .where(
                TestScenarioRunEvent.run_id == run.id,
                TestScenarioRunEvent.sequence > after_sequence,
            )
            .order_by(TestScenarioRunEvent.sequence)
        ).all())
        return run, events

    def _execute_dataset(self, *, scenario: TestScenario, version: TestScenarioVersion, definition: dict,
                         environment_id: int, dataset: dict, idempotency_key: str | None, request_hash: str,
                         current_user: User, trigger_type: str, plan_run_id: int | None,
                         deadline: datetime | None) -> TestScenarioRun:
        started_at = datetime.utcnow()
        variables = copy.deepcopy(dataset.get("variables") or {})
        run = TestScenarioRun(
            scenario_id=scenario.id, scenario_version_id=version.id, plan_run_id=plan_run_id,
            project_id=scenario.project_id,
            environment_id=environment_id, dataset_id=dataset.get("id"), dataset_name=dataset.get("name"),
            record_id=dataset.get("record_id"), record_name=dataset.get("record_name"),
            status="running", trigger_type=trigger_type, idempotency_key=idempotency_key,
            request_hash=request_hash, scenario_snapshot=mask_sensitive(definition),
            variables_snapshot=mask_sensitive(variables),
            step_results=[], triggered_by_id=current_user.id, started_at=started_at,
        )
        self.db.add(run)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self._idempotent(scenario.project_id, idempotency_key, request_hash)
            if existing:
                return existing
            raise
        self.db.refresh(run)

        return self._run_dataset(
            run=run,
            definition=definition,
            variables=variables,
            request_overrides=copy.deepcopy(dataset.get("request_overrides") or []),
            current_user=current_user,
            scenario_version=version.version,
            deadline=deadline,
            emit_events=False,
        )

    def _run_dataset(
        self,
        *,
        run: TestScenarioRun,
        definition: dict[str, Any],
        variables: dict[str, Any],
        current_user: User,
        scenario_version: int,
        deadline: datetime | None,
        emit_events: bool,
        request_overrides: list[dict[str, Any]] | None = None,
    ) -> TestScenarioRun:
        started_at = datetime.utcnow()
        run.status = "running"
        run.started_at = started_at
        run.finished_at = None
        if emit_events:
            self._append_event(
                run,
                scenario_version,
                "run_started",
                {
                    "status": "running",
                    "total_steps": len(self._execution_steps(definition)),
                    "started_at": self._iso_utc(started_at),
                },
            )

        ordered_steps = self._execution_steps(definition)
        self._ensure_trace_metadata(ordered_steps)
        results: list[dict[str, Any]] = []
        variable_sources: dict[str, dict[str, Any]] = {}
        global_stop = False
        blocked_nodes: set[str] = set()
        stop_after_nodes: set[str] = set()
        previous_node_id: str | None = None
        previous_step: dict[str, Any] | None = None
        previous_step_index: int | None = None
        overrides_by_step: dict[str, list[dict[str, Any]]] = {}
        for override in request_overrides or []:
            overrides_by_step.setdefault(str(override.get("step_id")), []).append(
                override
            )
        for index, step in enumerate(ordered_steps):
            node_id = str(step["_node_id"])
            node_phase = str(step["_node_phase"])
            if previous_node_id is not None and node_id != previous_node_id:
                if previous_node_id in stop_after_nodes:
                    global_stop = True
            previous_node_id = node_id
            result_index = index if emit_events else index + 1
            if deadline is not None and datetime.utcnow() >= deadline:
                result = self._timeout_result(step, result_index)
                results.append(result)
                if emit_events:
                    self._persist_step_result(
                        run,
                        results,
                        variables,
                        variable_sources,
                        ordered_steps[index + 1:],
                        index + 1,
                    )
                    self._append_event(
                        run,
                        scenario_version,
                        "step_failed",
                        self._step_event_payload(result, step, continue_on_failure=False),
                    )
                stop_after_nodes.add(node_id)
                continue
            if global_stop or (node_id in blocked_nodes and node_phase != "after"):
                result = self._skipped_result(step, result_index)
                results.append(result)
                if emit_events:
                    self._persist_step_result(
                        run,
                        results,
                        variables,
                        variable_sources,
                        ordered_steps[index + 1:],
                        index + 1,
                    )
                    self._append_event(
                        run,
                        scenario_version,
                        "step_skipped",
                        {
                            "step_id": step["id"],
                            "step_index": index,
                            "status": "skipped",
                            "reason": (
                                "previous_node_failed"
                                if global_stop
                                else "before_action_failed"
                            ),
                        },
                    )
                continue
            if emit_events and previous_step is not None:
                self._append_event(
                    run,
                    scenario_version,
                    "transition_started",
                    {
                        "source_step_id": previous_step["id"],
                        "source_step_index": previous_step_index,
                        "target_step_id": step["id"],
                        "target_step_index": index,
                        "reason": self._transition_reason(previous_step, results[-1]),
                    },
                )

            def on_step_started(
                step_started_at: datetime,
                bindings: list[dict[str, Any]],
                current_step: dict[str, Any] = step,
                current_index: int = index,
            ) -> None:
                run.current_step_id = current_step["id"]
                run.current_step_index = current_index
                run.step_results = [
                    *copy.deepcopy(results),
                    self._running_result(
                        current_step, current_index, step_started_at, bindings
                    ),
                    *[
                        self._pending_result(item, pending_index)
                        for pending_index, item in enumerate(
                            ordered_steps[current_index + 1:],
                            start=current_index + 1,
                        )
                    ],
                ]
                self._append_event(
                    run,
                    scenario_version,
                    "step_started",
                    {
                        "step_id": current_step["id"],
                        "step_index": current_index,
                        "name": current_step["name"],
                        "kind": current_step["kind"],
                        "status": "running",
                        "started_at": self._iso_utc(step_started_at),
                        "resolved_bindings": bindings,
                    },
                )

            result = self._execute_step(
                project_id=run.project_id,
                environment_id=run.environment_id,
                step=step,
                request_overrides=overrides_by_step.get(str(step["id"]), []),
                step_index=result_index,
                variable_step_index=index + 1,
                variables=variables,
                previous_results=results,
                current_user=current_user,
                scenario_run_id=run.id,
                deadline=deadline,
                variable_sources=variable_sources,
                on_started=on_step_started if emit_events else None,
            )
            results.append(result)
            if emit_events:
                self._persist_step_result(
                    run,
                    results,
                    variables,
                    variable_sources,
                    ordered_steps[index + 1:],
                    index + 1,
                )
                self._append_event(
                    run,
                    scenario_version,
                    "step_completed" if result["status"] == "passed" else "step_failed",
                    self._step_event_payload(
                        result,
                        step,
                        continue_on_failure=bool(step.get("continue_on_failure", False)),
                    ),
                )
            if result["status"] != "passed" and not step.get("continue_on_failure", False):
                stop_after_nodes.add(node_id)
                if node_phase == "before":
                    blocked_nodes.add(node_id)
            previous_step = step
            previous_step_index = index

        finished_at = datetime.utcnow()
        run.step_results = results
        run.variables_snapshot = self._masked_variables_snapshot(variables, variable_sources)
        run.status = (
            "timeout" if any(item["status"] == "timeout" for item in results)
            else "failed" if any(item["status"] == "failed" for item in results)
            else "passed"
        )
        run.finished_at = finished_at
        run.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        run.current_step_id = None
        run.current_step_index = None
        if emit_events:
            summary = self._run_summary(results)
            if run.status == "passed":
                self._append_event(
                    run,
                    scenario_version,
                    "run_completed",
                    {
                        "status": "passed",
                        "started_at": self._iso_utc(started_at),
                        "finished_at": self._iso_utc(finished_at),
                        "duration_ms": run.duration_ms,
                        "summary": summary,
                    },
                )
            else:
                failed = next(
                    (item for item in results if item["status"] in {"failed", "timeout"}),
                    None,
                )
                self._append_event(
                    run,
                    scenario_version,
                    "run_failed",
                    {
                        "status": run.status,
                        "error_code": "STEP_TIMEOUT" if run.status == "timeout" else "STEP_FAILED",
                        "error_message": (
                            failed.get("error_message") if failed else "Scenario execution failed"
                        ),
                        "failed_step_id": failed.get("step_id") if failed else None,
                        "finished_at": self._iso_utc(finished_at),
                        "duration_ms": run.duration_ms,
                        "summary": summary,
                    },
                )
        else:
            self.db.commit()
        self.db.refresh(run)
        return run

    def _execute_step(self, *, project_id: int, environment_id: int, step: dict, step_index: int,
                      variables: dict[str, Any], previous_results: list[dict], current_user: User,
                      scenario_run_id: int, deadline: datetime | None,
                      variable_sources: dict[str, dict[str, Any]],
                      request_overrides: list[dict[str, Any]] | None = None,
                      variable_step_index: int | None = None,
                      on_started: Callable[[datetime, list[dict[str, Any]]], None] | None = None) -> dict[str, Any]:
        started_at = datetime.utcnow()
        execution = None
        execution_id = None
        error_message = None
        status_value = "passed"
        output = None
        assertion_results: list[dict[str, Any]] = []
        extracted_variables: list[dict[str, Any]] = []
        resolved_bindings: list[dict[str, Any]] = []
        raw_config = copy.deepcopy(step.get("config") or {})
        scenario_context = raw_config.pop("_scenario_context", {}) or {}
        try:
            remaining = (deadline - datetime.utcnow()).total_seconds() if deadline is not None else None
            if remaining is not None and remaining <= 0:
                raise TimeoutError("Scenario execution deadline exceeded")
            config = self._render(raw_config, variables)
            if step["kind"] == "condition":
                config["expression"] = raw_config["expression"]
            resolved_bindings = self._resolved_bindings(
                step=step,
                raw_config=raw_config,
                rendered_config=config,
                scenario_context=scenario_context,
                variables=variables,
                variable_sources=variable_sources,
            )
            if on_started is not None:
                on_started(started_at, resolved_bindings)
            if step["kind"] == "delay":
                delay_seconds = config["duration_ms"] / 1000
                if remaining is not None and delay_seconds > remaining:
                    raise TimeoutError("Scenario execution deadline exceeded")
                time.sleep(delay_seconds)
            elif step["kind"] == "condition":
                passed = self._evaluate_condition(str(config["expression"]), variables, previous_results)
                output = {"result": passed}
                if not passed:
                    status_value = "failed"
                    error_message = "条件判断结果为 false"
            elif step["kind"] == "random":
                random_type = config["type"]
                if random_type == "integer":
                    output = secrets.randbelow(config["max"] - config["min"] + 1) + config["min"]
                elif random_type == "string":
                    alphabet = string.ascii_letters + string.digits
                    output = "".join(secrets.choice(alphabet) for _ in range(config["length"]))
                else:
                    output = str(uuid.uuid4())
                variables[config["output"]] = copy.deepcopy(output)
                variable_sources[config["output"]] = {
                    "source_step_id": step["id"],
                    "source_extraction_id": f"action:{step['id']}",
                    "masked": False,
                }
            elif step["kind"] == "fixed_value":
                output = copy.deepcopy(config["value"])
                variables[config["output"]] = copy.deepcopy(output)
                variable_sources[config["output"]] = {
                    "source_step_id": step["id"],
                    "source_extraction_id": f"action:{step['id']}",
                    "masked": self._trace_masked(config, config["output"]),
                }
            elif step["kind"] == "script":
                missing = [name for name in config["inputs"] if name not in variables]
                if missing:
                    raise ValueError(f"Script inputs are unavailable: {', '.join(missing)}")
                output = run_scenario_script(
                    language=config["language"],
                    code=config["code"],
                    inputs={name: copy.deepcopy(variables[name]) for name in config["inputs"]},
                    outputs=config["outputs"],
                    timeout_ms=config["timeout_ms"],
                )
                for name in config["outputs"]:
                    variables[name] = copy.deepcopy(output.get(name))
                    variable_sources[name] = {
                        "source_step_id": step["id"],
                        "source_extraction_id": f"action:{step['id']}:{name}",
                        "masked": self._trace_masked(config, name),
                    }
            elif step["kind"] == "api_case":
                data = copy.deepcopy(step["case_snapshot"])
                data["environment_id"] = environment_id
                data.update(config)
                data["environment_id"] = environment_id
                self._apply_request_overrides(data, request_overrides or [])
                payload = TestCaseRequestConfig.model_validate(self._render(data, variables))
                existing_case_id = self.db.scalar(
                    select(TestCase.id).where(
                        TestCase.project_id == project_id,
                        TestCase.id == step["reference_id"],
                    )
                )
                execution = TestCaseService(self.db)._execute(  # noqa: SLF001
                    project_id=project_id, test_case_id=existing_case_id, payload=payload,
                    current_user=current_user, scenario_run_id=scenario_run_id, timeout_seconds=remaining,
                )
                execution_id, status_value = execution.id, execution.status
                output = execution.response_snapshot
                error_message = execution.error_message
            else:
                data = copy.deepcopy(step["case_snapshot"])
                data["environment_id"] = environment_id
                data.update(config)
                data["environment_id"] = environment_id
                self._apply_request_overrides(data, request_overrides or [])
                payload = WebSocketTestCaseConfig.model_validate(self._render(data, variables))
                existing_case_id = self.db.scalar(
                    select(WebSocketTestCase.id).where(
                        WebSocketTestCase.project_id == project_id,
                        WebSocketTestCase.id == step["reference_id"],
                    )
                )
                execution = WebSocketTestCaseService(self.db)._execute(  # noqa: SLF001
                    project_id, existing_case_id, payload, current_user,
                    scenario_run_id=scenario_run_id, timeout_seconds=remaining,
                )
                execution_id, status_value = execution.id, execution.status
                output = execution.response_snapshot
                error_message = execution.error_message
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            status_value = "timeout" if isinstance(exc, TimeoutError) else "failed"
            error_message = str(exc)
        if execution is not None:
            assertion_results = getattr(execution, "assertion_results", None) or []
        if status_value == "passed":
            extracted_variables = self._extract_step_variables(
                step=step,
                output=output,
                scenario_context=scenario_context,
                variables=variables,
                variable_sources=variable_sources,
            )
            if step["kind"] in {"random", "fixed_value"}:
                name = str(config["output"])
                extracted_variables.append({
                    "extraction_id": f"action:{step['id']}",
                    "name": name,
                    "path": "",
                    "value": (
                        "***" if variable_sources[name]["masked"] else copy.deepcopy(output)
                    ),
                    "masked": variable_sources[name]["masked"],
                })
            elif step["kind"] == "script":
                for name in config["outputs"]:
                    extracted_variables.append({
                        "extraction_id": f"action:{step['id']}:{name}",
                        "name": name,
                        "path": name,
                        "value": (
                            "***"
                            if variable_sources[name]["masked"]
                            else copy.deepcopy(output.get(name))
                        ),
                        "masked": variable_sources[name]["masked"],
                    })
        finished_at = datetime.utcnow()
        result = {
            "step_id": step["id"], "step_index": step_index, "kind": step["kind"], "name": step["name"],
            "node_id": step.get("_node_id"), "node_index": step.get("_node_index"),
            "node_phase": step.get("_node_phase"),
            "status": status_value if status_value in {"passed", "timeout"} else "failed",
            "message": self._step_message(status_value, error_message),
            "extracted_variables": extracted_variables,
            "resolved_bindings": resolved_bindings,
            "assertion_results": assertion_results,
            "attempt_history": (
                copy.deepcopy(getattr(execution, "attempt_history", None) or [])
                if execution is not None
                else []
            ),
            "execution_id": execution_id, "output": output, "error_message": error_message,
            "request_snapshot": (
                copy.deepcopy(getattr(execution, "request_snapshot", None))
                if execution is not None and step["kind"] == "api_case"
                else copy.deepcopy(getattr(execution, "session_snapshot", None))
                if execution is not None and step["kind"] == "websocket_case"
                else None
            ),
            "response_snapshot": (
                copy.deepcopy(getattr(execution, "response_snapshot", None))
                if execution is not None
                else None
            ),
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(), "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
        }
        variables[f"step_{variable_step_index or step_index}"] = output
        return result

    def _hydrate_step_result_snapshots(
        self,
        run: TestScenarioRun,
        step_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        hydrated: list[dict[str, Any]] = []
        for source in step_results:
            result = copy.deepcopy(source)
            execution_id = result.get("execution_id")
            kind = result.get("kind")
            if not execution_id or (
                result.get("request_snapshot") is not None
                and result.get("response_snapshot") is not None
            ):
                hydrated.append(result)
                continue

            try:
                execution_key = int(execution_id)
            except (TypeError, ValueError):
                hydrated.append(result)
                continue

            execution: TestCaseExecution | WebSocketTestCaseExecution | None = None
            if kind == "websocket_case":
                execution = self.db.get(WebSocketTestCaseExecution, execution_key)
            else:
                execution = self.db.get(TestCaseExecution, execution_key)
                if execution is None and kind not in {"api_case", "delay", "condition"}:
                    execution = self.db.get(WebSocketTestCaseExecution, execution_key)

            if (
                execution is None
                or execution.project_id != run.project_id
                or execution.scenario_run_id != run.id
            ):
                hydrated.append(result)
                continue

            if isinstance(execution, WebSocketTestCaseExecution):
                if result.get("request_snapshot") is None:
                    result["request_snapshot"] = copy.deepcopy(
                        execution.session_snapshot
                    )
            else:
                if result.get("request_snapshot") is None:
                    result["request_snapshot"] = copy.deepcopy(
                        execution.request_snapshot
                    )
            if result.get("response_snapshot") is None:
                result["response_snapshot"] = copy.deepcopy(
                    execution.response_snapshot
                )
            if not result.get("assertion_results"):
                result["assertion_results"] = copy.deepcopy(
                    execution.assertion_results or []
                )
            if not result.get("attempt_history"):
                result["attempt_history"] = copy.deepcopy(
                    getattr(execution, "attempt_history", None) or []
                )
            if not result.get("error_message") and execution.error_message:
                result["error_message"] = execution.error_message
            hydrated.append(result)
        return hydrated

    def _extract_step_variables(
        self,
        *,
        step: dict[str, Any],
        output: Any,
        scenario_context: dict[str, Any],
        variables: dict[str, Any],
        variable_sources: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        traces = []
        extraction_source = output.get("json") if isinstance(output, dict) and "json" in output else output
        for extraction in self._context_items(scenario_context, "extractions", "extractors"):
            extraction_id = self._value(extraction, "id", "extraction_id", "extractionId")
            name = self._value(extraction, "name")
            path = self._value(extraction, "path")
            if not extraction_id or not name or not path:
                continue
            found, value = self._resolve_trace_path(extraction_source, str(path))
            masked = self._trace_masked(extraction, str(name))
            trace = {
                "extraction_id": str(extraction_id),
                "name": str(name),
                "path": str(path),
                "value": "***" if masked and found else value if found else None,
                "masked": masked,
            }
            if not found:
                trace["error"] = "Extraction path not found"
            else:
                variables[str(name)] = copy.deepcopy(value)
                variable_sources[str(name)] = {
                    "source_step_id": step["id"],
                    "source_extraction_id": str(extraction_id),
                    "masked": masked,
                }
            traces.append(trace)
        return traces

    def _resolved_bindings(
        self,
        *,
        step: dict[str, Any],
        raw_config: dict[str, Any],
        rendered_config: dict[str, Any],
        scenario_context: dict[str, Any],
        variables: dict[str, Any],
        variable_sources: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        traces: list[dict[str, Any]] = []
        explicit_targets: set[tuple[str, str]] = set()
        for binding in self._context_items(scenario_context, "bindings", "inputBindings", "input_bindings"):
            target = self._value(binding, "target")
            target_path = self._value(binding, "target_path", "targetPath")
            variable_name = self._value(binding, "name", "variable", "variable_name", "variableName")
            source_step_id = self._value(binding, "source_step_id", "sourceStepId")
            source_extraction_id = self._value(
                binding, "source_extraction_id", "sourceExtractionId"
            )
            if variable_name is None and source_extraction_id is not None:
                variable_name = next(
                    (
                        name for name, source in variable_sources.items()
                        if source.get("source_extraction_id") == str(source_extraction_id)
                    ),
                    None,
                )
            if not target or not target_path or variable_name not in variables:
                continue
            source = variable_sources.get(str(variable_name), {})
            masked = self._trace_masked(binding, str(variable_name)) or bool(source.get("masked"))
            found, final_value = self._resolve_trace_path(
                rendered_config.get(str(target)),
                str(target_path),
            )
            if not found:
                final_value = variables[str(variable_name)]
            binding_id = self._value(binding, "id", "binding_id", "bindingId")
            traces.append({
                "binding_id": str(
                    binding_id
                    or f"implicit:{step['id']}:{target}:{target_path}:{variable_name}"
                ),
                "source_step_id": str(source_step_id or source.get("source_step_id") or ""),
                "source_extraction_id": str(
                    source_extraction_id or source.get("source_extraction_id") or ""
                ),
                "target": str(target),
                "target_path": str(target_path),
                "value": "***" if masked else copy.deepcopy(final_value),
                "masked": masked,
            })
            explicit_targets.add((str(target), str(target_path)))

        for target, target_path, variable_name in self._template_bindings(raw_config):
            if (target, target_path) in explicit_targets or variable_name not in variables:
                continue
            source = variable_sources.get(variable_name, {})
            masked = bool(source.get("masked"))
            found, final_value = self._resolve_trace_path(
                rendered_config.get(target),
                target_path,
            )
            if not found:
                final_value = variables[variable_name]
            traces.append({
                "binding_id": (
                    f"implicit:{step['id']}:{target}:{target_path}:{variable_name}"
                ),
                "source_step_id": str(source.get("source_step_id") or ""),
                "source_extraction_id": str(source.get("source_extraction_id") or ""),
                "target": target,
                "target_path": target_path,
                "value": "***" if masked else copy.deepcopy(final_value),
                "masked": masked,
            })
        return traces

    def _template_bindings(self, config: dict[str, Any]) -> list[tuple[str, str, str]]:
        bindings: list[tuple[str, str, str]] = []

        def walk(value: Any, root: str, parts: list[str]) -> None:
            if isinstance(value, str):
                match = re.fullmatch(r"\{\{\s*([^{}]+?)\s*\}\}", value)
                if match:
                    bindings.append((root, ".".join(parts), match.group(1).strip()))
            elif isinstance(value, dict):
                for key, item in value.items():
                    walk(item, root, [*parts, str(key)])
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, root, [*parts, str(index)])

        for root in ("path", "headers", "query_params", "body", "messages", "subprotocols"):
            if root in config:
                walk(config[root], root, [])
        return bindings

    @staticmethod
    def _context_items(context: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
        for key in keys:
            value = context.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _value(data: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in data:
                return data[key]
        return None

    def _resolve_trace_path(self, data: Any, path: str) -> tuple[bool, Any]:
        if path == "":
            return True, copy.deepcopy(data)
        current = data
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                return False, None
        return True, copy.deepcopy(current)

    @staticmethod
    def _trace_masked(config: dict[str, Any], name: str) -> bool:
        explicit = config.get("masked", config.get("is_secret", config.get("isSecret")))
        if explicit is not None:
            return bool(explicit)
        normalized = name.lower().replace("-", "_")
        return any(item in normalized for item in (
            "authorization", "cookie", "password", "secret", "token", "api_key", "apikey"
        ))

    @staticmethod
    def _step_message(status_value: str, error_message: str | None) -> str:
        if error_message:
            return error_message
        return {
            "passed": "Execution passed",
            "timeout": "Execution timed out",
            "skipped": "Execution skipped",
        }.get(status_value, "Execution failed")

    @staticmethod
    def _execution_steps(definition: dict[str, Any]) -> list[dict[str, Any]]:
        nodes = definition.get("nodes")
        if not isinstance(nodes, list):
            raise RuntimeError("Scenario definition has not been migrated to nodes")
        steps: list[dict[str, Any]] = []
        for node_index, node in enumerate(nodes):
            node_id = str(node.get("id") or "")
            groups = (
                ("before", node.get("before_actions") or []),
                ("test_case", [node.get("test_case")]),
                ("after", node.get("after_actions") or []),
            )
            for phase, items in groups:
                for item in items:
                    if not isinstance(item, dict):
                        raise RuntimeError(
                            f"Scenario node {node_id or node_index} is missing its test_case"
                        )
                    step = copy.deepcopy(item)
                    step["_node_id"] = node_id
                    step["_node_index"] = node_index
                    step["_node_phase"] = phase
                    steps.append(step)
        return steps

    @classmethod
    def _test_case_steps(cls, definition: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            step
            for step in cls._execution_steps(definition)
            if step["_node_phase"] == "test_case"
        ]

    def _select_datasets(
        self, definition: dict[str, Any], dataset_ids: list[str] | None
    ) -> list[dict[str, Any]]:
        all_datasets = definition.get("datasets", [])
        datasets = [item for item in all_datasets if item.get("enabled", True)]
        if dataset_ids is not None:
            requested = set(dataset_ids)
            datasets = [item for item in all_datasets if item["id"] in requested]
            if {item["id"] for item in datasets} != requested:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset does not exist"
                )
        elif not all_datasets:
            datasets = [{"id": None, "name": None, "variables": {}}]
        return self._expand_dataset_records(datasets)

    @staticmethod
    def _normalize_definition_datasets(definition: dict[str, Any]) -> None:
        definition["datasets"] = [
            ScenarioDatasetRequest.model_validate(dataset).model_dump()
            for dataset in definition.get("datasets", [])
        ]

    @staticmethod
    def _expand_dataset_records(
        datasets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        run_inputs: list[dict[str, Any]] = []
        for dataset in datasets:
            if dataset.get("id") is None:
                run_inputs.append({
                    **copy.deepcopy(dataset),
                    "record_id": None,
                    "record_name": None,
                    "request_overrides": [],
                })
                continue
            base = {
                key: copy.deepcopy(value)
                for key, value in dataset.items()
                if key != "records"
            }
            for record in dataset.get("records") or []:
                if not record.get("enabled", True):
                    continue
                run_inputs.append({
                    **copy.deepcopy(base),
                    "record_id": record.get("id"),
                    "record_name": record.get("name"),
                    "request_overrides": copy.deepcopy(
                        record.get("request_overrides") or []
                    ),
                })
        return run_inputs

    def _find_run_input(
        self,
        definition: dict[str, Any],
        *,
        dataset_id: str | None,
        record_id: str | None,
    ) -> dict[str, Any]:
        if dataset_id is None:
            return {
                "id": None,
                "name": None,
                "variables": {},
                "record_id": None,
                "record_name": None,
                "request_overrides": [],
            }
        for item in self._expand_dataset_records(definition.get("datasets", [])):
            if item.get("id") == dataset_id and item.get("record_id") == record_id:
                return item
        raise RuntimeError(
            f"Scenario dataset record no longer exists: {dataset_id}/{record_id}"
        )

    def _idempotent_execution(
        self, project_id: int, key: str | None, request_hash: str
    ) -> TestScenarioExecution | None:
        if not key:
            return None
        existing = self.db.scalar(select(TestScenarioExecution).where(
            TestScenarioExecution.project_id == project_id,
            TestScenarioExecution.idempotency_key == key,
        ))
        if (
            existing is not None
            and existing.request_hash
            and existing.request_hash != request_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key was used for a different scenario execution request",
            )
        return existing

    def _queued_execution_response(
        self, execution: TestScenarioExecution, scenario_version: int
    ) -> dict[str, Any]:
        runs = list(self.db.scalars(
            select(TestScenarioRun)
            .where(TestScenarioRun.execution_id == execution.id)
            .order_by(TestScenarioRun.id)
        ).all())
        return {
            "execution_id": execution.id,
            "scenario_id": execution.scenario_id,
            "scenario_version": scenario_version,
            "status": execution.status,
            "created_at": execution.created_at,
            "runs": [
                {
                    "run_id": run.id,
                    "dataset_id": run.dataset_id,
                    "dataset_name": run.dataset_name,
                    "record_id": run.record_id,
                    "record_name": run.record_name,
                    "status": run.status,
                    "events_url": (
                        f"/api/v1/scenario-runs/{run.id}/events"
                        f"?project_id={run.project_id}"
                    ),
                    "detail_url": (
                        f"/api/v1/scenario-runs/{run.id}"
                        f"?project_id={run.project_id}"
                    ),
                }
                for run in runs
            ],
        }

    def _append_event(
        self,
        run: TestScenarioRun,
        scenario_version: int,
        event: str,
        data: dict[str, Any],
        *,
        commit: bool = True,
    ) -> TestScenarioRunEvent:
        locked_run = self.db.scalar(
            select(TestScenarioRun)
            .where(TestScenarioRun.id == run.id)
            .with_for_update()
        )
        if locked_run is not None:
            run = locked_run
        occurred_at = datetime.utcnow()
        sequence = (run.last_event_sequence or 0) + 1
        payload = {
            "schema_version": 1,
            "sequence": sequence,
            "event": event,
            "run_id": run.id,
            "scenario_id": run.scenario_id,
            "scenario_version": scenario_version,
            "project_id": run.project_id,
            "dataset_id": run.dataset_id,
            "record_id": run.record_id,
            "occurred_at": self._iso_utc(occurred_at),
            **copy.deepcopy(data),
        }
        item = TestScenarioRunEvent(
            run_id=run.id,
            sequence=sequence,
            event=event,
            payload=payload,
            occurred_at=occurred_at,
        )
        run.last_event_sequence = sequence
        self.db.add(item)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        return item

    def _persist_step_result(
        self,
        run: TestScenarioRun,
        results: list[dict[str, Any]],
        variables: dict[str, Any],
        variable_sources: dict[str, dict[str, Any]],
        pending_steps: list[dict[str, Any]],
        pending_start_index: int,
    ) -> None:
        run.step_results = [
            *copy.deepcopy(results),
            *[
                self._pending_result(step, index)
                for index, step in enumerate(
                    pending_steps, start=pending_start_index
                )
            ],
        ]
        run.variables_snapshot = self._masked_variables_snapshot(
            variables, variable_sources
        )

    def _step_event_payload(
        self,
        result: dict[str, Any],
        step: dict[str, Any],
        *,
        continue_on_failure: bool,
    ) -> dict[str, Any]:
        assertions = result.get("assertion_results") or []
        assertion_summary = {
            "total": len(assertions),
            "passed": sum(1 for item in assertions if item.get("passed")),
            "failed": sum(1 for item in assertions if not item.get("passed")),
        }
        output = result.get("output")
        status_code = None
        if isinstance(output, dict):
            status_code = output.get("status_code", output.get("status"))
        payload = {
            "step_id": result["step_id"],
            "step_index": result["step_index"],
            "name": result["name"],
            "kind": result["kind"],
            "execution_id": result.get("execution_id"),
            "status": result["status"],
            "started_at": self._normalize_iso(result.get("started_at")),
            "finished_at": self._normalize_iso(result.get("finished_at")),
            "duration_ms": result.get("duration_ms"),
            "message": result.get("message"),
            "error_message": result.get("error_message") or "",
            "extracted_variables": result.get("extracted_variables") or [],
            "resolved_bindings": result.get("resolved_bindings") or [],
            "attempt_count": len(result.get("attempt_history") or []),
        }
        if result["status"] == "passed":
            payload["status_code"] = status_code
            payload["assertion_summary"] = assertion_summary
        else:
            payload["error_code"] = (
                "TIMEOUT" if result["status"] == "timeout" else "STEP_FAILED"
            )
            payload["continue_on_failure"] = continue_on_failure
        return payload

    @staticmethod
    def _run_summary(results: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "total": len(results),
            "passed": sum(1 for item in results if item["status"] == "passed"),
            "failed": sum(1 for item in results if item["status"] == "failed"),
            "timeout": sum(1 for item in results if item["status"] == "timeout"),
            "skipped": sum(1 for item in results if item["status"] == "skipped"),
        }

    @staticmethod
    def _pending_result(step: dict[str, Any], index: int) -> dict[str, Any]:
        return {
            "step_id": step["id"],
            "step_index": index,
            "kind": step["kind"],
            "name": step["name"],
            "node_id": step.get("_node_id"),
            "node_index": step.get("_node_index"),
            "node_phase": step.get("_node_phase"),
            "status": "pending",
            "extracted_variables": [],
            "resolved_bindings": [],
            "attempt_history": [],
        }

    @staticmethod
    def _running_result(
        step: dict[str, Any],
        index: int,
        started_at: datetime,
        bindings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "step_id": step["id"],
            "step_index": index,
            "kind": step["kind"],
            "name": step["name"],
            "node_id": step.get("_node_id"),
            "node_index": step.get("_node_index"),
            "node_phase": step.get("_node_phase"),
            "status": "running",
            "started_at": ScenarioService._iso_utc(started_at),
            "extracted_variables": [],
            "resolved_bindings": copy.deepcopy(bindings),
            "attempt_history": [],
        }

    @staticmethod
    def _transition_reason(step: dict[str, Any], result: dict[str, Any]) -> str:
        if step["kind"] == "condition":
            output = result.get("output") or {}
            return "condition_true" if output.get("result") else "condition_false"
        return (
            "previous_step_completed"
            if result["status"] == "passed"
            else "previous_step_failed"
        )

    @staticmethod
    def _iso_utc(value: datetime) -> str:
        return value.isoformat(timespec="milliseconds") + "Z"

    @staticmethod
    def _normalize_iso(value: str | None) -> str | None:
        if not value:
            return value
        return value if value.endswith("Z") else value + "Z"

    def _fail_queued_execution(
        self, execution: TestScenarioExecution, error_message: str
    ) -> None:
        execution.status = "failed"
        execution.finished_at = datetime.utcnow()
        runs = list(self.db.scalars(
            select(TestScenarioRun).where(TestScenarioRun.execution_id == execution.id)
        ).all())
        for run in runs:
            if run.status in {"passed", "failed", "timeout", "cancelled"}:
                continue
            run.status = "failed"
            run.finished_at = execution.finished_at
            run.duration_ms = 0
            version = self.db.get(TestScenarioVersion, run.scenario_version_id)
            self._append_event(
                run,
                version.version if version else 0,
                "run_failed",
                {
                    "status": "failed",
                    "error_code": "EXECUTION_CONTEXT_MISSING",
                    "error_message": error_message,
                    "failed_step_id": None,
                    "finished_at": self._iso_utc(execution.finished_at),
                    "duration_ms": 0,
                    "summary": self._run_summary(run.step_results or []),
                },
                commit=False,
            )
        self.db.commit()

    def _validated_definition(self, project_id: int, payload: ScenarioPayload) -> dict:
        self._get_environment(project_id, payload.environment_id)
        nodes = []
        for node_item in payload.nodes:
            node = node_item.model_dump()
            test_case_item = node_item.test_case
            if test_case_item.kind == "api_case":
                asset = self.db.scalar(select(TestCase).where(
                    TestCase.id == test_case_item.reference_id,
                    TestCase.project_id == project_id,
                ))
            else:
                asset = self.db.scalar(select(WebSocketTestCase).where(
                    WebSocketTestCase.id == test_case_item.reference_id,
                    WebSocketTestCase.project_id == project_id,
                ))
            if asset is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"步骤引用用例不存在: {test_case_item.id}",
                )
            node["test_case"].update({
                "name": asset.name,
                "method": asset.method if test_case_item.kind == "api_case" else "WS",
                "path": asset.path,
                "case_snapshot": self._case_snapshot(
                    asset, websocket=test_case_item.kind == "websocket_case"
                ),
            })
            for action in [*node["before_actions"], *node["after_actions"]]:
                action.pop("reference_id", None)
                action.pop("method", None)
                action.pop("path", None)
            nodes.append(node)
        definition = {
            "nodes": nodes,
            "datasets": [item.model_dump() for item in payload.datasets],
        }
        self._ensure_trace_metadata(self._execution_steps(definition))
        self._validate_request_overrides(definition)
        return encrypt_sensitive(definition)

    def _validate_request_overrides(self, definition: dict[str, Any]) -> None:
        self._normalize_definition_datasets(definition)
        steps = {
            str(step.get("id")): step
            for step in self._test_case_steps(definition)
            if step.get("id") is not None
        }
        supported_targets = {
            "api_case": {"path", "headers", "query_params", "body"},
            "websocket_case": {"path", "headers"},
        }
        for dataset in definition.get("datasets", []):
            record_ids: set[str] = set()
            for record in dataset.get("records") or []:
                record_id = str(record.get("id") or "").strip()
                record_name = str(record.get("name") or "").strip()
                if not record_id or not record_name:
                    self._request_override_error(
                        "Dataset record must have an id and name",
                        dataset,
                        (record.get("request_overrides") or [{}])[0],
                        record=record,
                    )
                if record_id in record_ids:
                    self._request_override_error(
                        "Dataset record id must be unique",
                        dataset,
                        (record.get("request_overrides") or [{}])[0],
                        record=record,
                    )
                record_ids.add(record_id)

                seen: set[tuple[str, str, str]] = set()
                overrides = record.get("request_overrides") or []
                for override in overrides:
                    step_id = str(override.get("step_id") or "")
                    target = str(override.get("target") or "")
                    path = str(override.get("path") or "")
                    step = steps.get(step_id)
                    if step is None:
                        self._request_override_error(
                            "Request override step does not exist",
                            dataset,
                            override,
                            record=record,
                        )
                    if target not in supported_targets.get(str(step.get("kind")), set()):
                        self._request_override_error(
                            "Request override target is not supported by the step kind",
                            dataset,
                            override,
                            record=record,
                        )
                    if target == "path" and path:
                        self._request_override_error(
                            "Request path override must use an empty field path",
                            dataset,
                            override,
                            record=record,
                        )
                    if target in {"headers", "query_params", "body"} and not path:
                        self._request_override_error(
                            "Request override field path is required",
                            dataset,
                            override,
                            record=record,
                        )
                    address = (step_id, target, path)
                    if address in seen:
                        self._request_override_error(
                            "Duplicate request override",
                            dataset,
                            override,
                            record=record,
                        )
                    seen.add(address)

                for step_id, step in steps.items():
                    step_overrides = [
                        item
                        for item in overrides
                        if str(item.get("step_id") or "") == step_id
                    ]
                    if not step_overrides:
                        continue
                    request = copy.deepcopy(step.get("case_snapshot") or {})
                    request.update(copy.deepcopy(step.get("config") or {}))
                    try:
                        self._apply_request_overrides(request, step_overrides)
                    except ValueError as exc:
                        failed = getattr(exc, "request_override", step_overrides[0])
                        self._request_override_error(
                            str(exc),
                            dataset,
                            failed,
                            record=record,
                        )

    @staticmethod
    def _request_override_error(
        message: str,
        dataset: dict[str, Any],
        override: dict[str, Any],
        *,
        record: dict[str, Any] | None = None,
    ) -> None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": message,
                "dataset_id": dataset.get("id"),
                "record_id": record.get("id") if record else None,
                "step_id": override.get("step_id"),
                "target": override.get("target"),
                "path": override.get("path", ""),
            },
        )

    def _apply_request_overrides(
        self,
        request: dict[str, Any],
        overrides: list[dict[str, Any]],
    ) -> None:
        for override in overrides:
            target = str(override.get("target") or "")
            path = str(override.get("path") or "")
            value = copy.deepcopy(override.get("value"))
            try:
                if target == "path":
                    request["path"] = value
                elif target in {"headers", "query_params"}:
                    container = request.get(target)
                    if container is None:
                        container = {}
                        request[target] = container
                    if not isinstance(container, dict):
                        raise ValueError(
                            f"Request {target} must be an object before applying an override"
                        )
                    container[path] = value
                elif target == "body":
                    self._set_body_override(request.get("body"), path, value)
            except ValueError as exc:
                exc.request_override = override
                raise

    def _set_body_override(self, body: Any, path: str, value: Any) -> None:
        tokens = self._parse_body_override_path(path)
        current = body
        for position, token in enumerate(tokens):
            final = position == len(tokens) - 1
            if isinstance(current, dict):
                if isinstance(token, int):
                    raise ValueError("Body override array index is invalid")
                if final:
                    current[token] = value
                    return
                if token not in current:
                    raise ValueError("Body override path does not exist")
                current = current[token]
                continue
            if isinstance(current, list):
                if not isinstance(token, int) or token < 0 or token >= len(current):
                    raise ValueError("Body override array index is invalid")
                if final:
                    current[token] = value
                    return
                current = current[token]
                continue
            raise ValueError("Body override path traverses a scalar value")

    @staticmethod
    def _parse_body_override_path(path: str) -> list[str | int]:
        tokens: list[str | int] = []
        index = 0
        expect_segment = True
        while index < len(path):
            if path[index] == ".":
                if expect_segment:
                    raise ValueError("Body override path is invalid")
                expect_segment = True
                index += 1
                continue
            if path[index] == "[":
                closing = path.find("]", index + 1)
                if closing == -1:
                    raise ValueError("Body override array index is invalid")
                raw_index = path[index + 1:closing]
                if not raw_index.isdigit():
                    raise ValueError("Body override array index is invalid")
                tokens.append(int(raw_index))
                expect_segment = False
                index = closing + 1
                continue
            end = index
            while end < len(path) and path[end] not in ".[":
                if path[end] == "]":
                    raise ValueError("Body override path is invalid")
                end += 1
            token = path[index:end]
            if not token or not expect_segment:
                raise ValueError("Body override path is invalid")
            tokens.append(token)
            expect_segment = False
            index = end
        if expect_segment or not tokens:
            raise ValueError("Body override path is invalid")
        return tokens

    def _ensure_trace_metadata(self, steps: list[dict[str, Any]]) -> None:
        extraction_sources: dict[str, dict[str, str]] = {}
        extraction_names: dict[str, str] = {}
        for step in steps:
            config = step.get("config")
            if not isinstance(config, dict):
                continue
            context = config.get("_scenario_context")
            if not isinstance(context, dict):
                context = {}
                config["_scenario_context"] = context

            bindings = [
                copy.deepcopy(item)
                for item in self._context_items(
                    context, "bindings", "inputBindings", "input_bindings"
                )
            ]
            bound_targets: set[tuple[str, str]] = set()
            for binding in bindings:
                source_extraction_id = self._value(
                    binding, "source_extraction_id", "sourceExtractionId"
                )
                variable_name = self._value(
                    binding, "name", "variable", "variable_name", "variableName"
                )
                if variable_name is None and source_extraction_id is not None:
                    variable_name = extraction_names.get(str(source_extraction_id))
                    if variable_name is not None:
                        binding["name"] = variable_name
                source = extraction_sources.get(str(variable_name), {})
                binding.setdefault("source_step_id", source.get("source_step_id", ""))
                binding.setdefault(
                    "source_extraction_id", source.get("source_extraction_id", "")
                )
                target = str(self._value(binding, "target") or "")
                target_path = str(
                    self._value(binding, "target_path", "targetPath") or ""
                )
                if target:
                    bound_targets.add((target, target_path))
                if not self._value(binding, "id", "binding_id", "bindingId"):
                    binding["id"] = self._trace_id(
                        "BIND-AUTO",
                        step.get("id"),
                        binding.get("source_step_id"),
                        binding.get("source_extraction_id"),
                        target,
                        target_path,
                    )

            for target, target_path, variable_name in self._template_bindings(config):
                if (target, target_path) in bound_targets:
                    continue
                source = extraction_sources.get(variable_name)
                if source is None:
                    continue
                bindings.append({
                    "id": self._trace_id(
                        "BIND-AUTO",
                        step.get("id"),
                        source["source_step_id"],
                        source["source_extraction_id"],
                        target,
                        target_path,
                    ),
                    "source_step_id": source["source_step_id"],
                    "source_extraction_id": source["source_extraction_id"],
                    "name": variable_name,
                    "target": target,
                    "target_path": target_path,
                })
                bound_targets.add((target, target_path))
            context["bindings"] = bindings

            extractions = [
                copy.deepcopy(item)
                for item in self._context_items(context, "extractions", "extractors")
            ]
            for extraction in extractions:
                name = self._value(extraction, "name")
                path = self._value(extraction, "path")
                if not name or path is None:
                    continue
                extraction_id = self._value(
                    extraction, "id", "extraction_id", "extractionId"
                )
                if not extraction_id:
                    extraction_id = self._trace_id(
                        "VAR-AUTO", step.get("id"), name, path
                    )
                    extraction["id"] = extraction_id
                source = {
                    "source_step_id": str(step.get("id") or ""),
                    "source_extraction_id": str(extraction_id),
                }
                extraction_sources[str(name)] = source
                extraction_names[str(extraction_id)] = str(name)
            context["extractions"] = extractions

    @staticmethod
    def _trace_id(prefix: str, *parts: Any) -> str:
        raw = "|".join("" if item is None else str(item) for item in parts)
        return f"{prefix}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"

    @staticmethod
    def _masked_variables_snapshot(
        variables: dict[str, Any],
        variable_sources: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        snapshot = copy.deepcopy(variables)
        for name, source in variable_sources.items():
            if source.get("masked") and name in snapshot:
                snapshot[name] = "***"
        return mask_sensitive(snapshot)

    def _detail(self, scenario: TestScenario) -> dict[str, Any]:
        version = self._get_version(scenario)
        definition = decrypt_sensitive(copy.deepcopy(version.definition))
        self._normalize_definition_datasets(definition)
        public_nodes = copy.deepcopy(definition["nodes"])
        for node in public_nodes:
            node["test_case"].pop("case_snapshot", None)
        return {
            "id": scenario.id, "project_id": scenario.project_id, "environment_id": scenario.environment_id,
            "current_version": scenario.current_version, "name": scenario.name, "description": scenario.description,
            "tags": scenario.tags, "nodes": public_nodes, "datasets": mask_sensitive(definition["datasets"]),
            "created_at": scenario.created_at, "updated_at": scenario.updated_at, "last_run_at": scenario.last_run_at,
        }

    def _get_scenario(self, project_id: int, scenario_id: int) -> TestScenario:
        item = self.db.scalar(select(TestScenario).where(
            TestScenario.id == scenario_id, TestScenario.project_id == project_id, TestScenario.is_deleted.is_(False)
        ))
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="场景不存在")
        return item

    def _get_version(self, scenario: TestScenario, version_number: int | None = None) -> TestScenarioVersion:
        version = self.db.scalar(select(TestScenarioVersion).where(
            TestScenarioVersion.scenario_id == scenario.id,
            TestScenarioVersion.version == (version_number or scenario.current_version),
        ))
        if version is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="场景版本不存在")
        return version

    def _case_snapshot(self, case: TestCase | WebSocketTestCase, *, websocket: bool) -> dict[str, Any]:
        if websocket:
            return {
                "path": case.path, "headers": copy.deepcopy(case.headers), "subprotocols": copy.deepcopy(case.subprotocols or []),
                "messages": copy.deepcopy(case.messages or []), "receive_count": case.receive_count,
                "connect_timeout_ms": case.connect_timeout_ms, "receive_timeout_ms": case.receive_timeout_ms,
                "assertions": copy.deepcopy(case.assertions or []), "extractors": copy.deepcopy(case.extractors or []),
                "retry_policy": copy.deepcopy(getattr(case, "retry_policy", None) or {}),
            }
        return {
            "method": case.method, "path": case.path, "headers": copy.deepcopy(case.headers),
            "query_params": copy.deepcopy(case.query_params), "body_type": case.body_type, "body": copy.deepcopy(case.body),
            "assertions": copy.deepcopy(case.assertions or []), "extractors": copy.deepcopy(case.extractors or []),
            "retry_policy": copy.deepcopy(getattr(case, "retry_policy", None) or {}),
        }

    def _get_environment(self, project_id: int, environment_id: int) -> ProjectEnvironment:
        item = self.db.scalar(select(ProjectEnvironment).where(
            ProjectEnvironment.id == environment_id, ProjectEnvironment.project_id == project_id,
            ProjectEnvironment.is_deleted.is_(False),
        ))
        if item is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="执行环境不存在或不属于当前项目")
        return item

    def _idempotent(self, project_id: int, key: str | None, request_hash: str) -> TestScenarioRun | None:
        if not key:
            return None
        existing = self.db.scalar(select(TestScenarioRun).where(
            TestScenarioRun.project_id == project_id, TestScenarioRun.idempotency_key == key
        ))
        if existing is not None and existing.request_hash and existing.request_hash != request_hash:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="幂等键已用于不同的场景执行请求")
        return existing

    def _render(self, value: Any, variables: dict[str, Any]) -> Any:
        if isinstance(value, str):
            matches = list(re.finditer(r"\{\{\s*([^{}]+?)\s*\}\}", value))
            if len(matches) == 1 and matches[0].span() == (0, len(value)):
                found, resolved = self._try_resolve_path(
                    variables, matches[0].group(1)
                )
                return value if not found else copy.deepcopy(resolved)
            return re.sub(
                r"\{\{\s*([^{}]+?)\s*\}\}",
                lambda match: (
                    match.group(0)
                    if not (
                        resolved_pair := self._try_resolve_path(
                            variables, match.group(1)
                        )
                    )[0]
                    else str(resolved_pair[1])
                ),
                value,
            )
        if isinstance(value, dict):
            return {key: self._render(item, variables) for key, item in value.items()}
        if isinstance(value, list):
            return [self._render(item, variables) for item in value]
        return value

    def _resolve_path(self, values: dict[str, Any], path: str) -> Any:
        found, value = self._try_resolve_path(values, path)
        return value if found else None

    @staticmethod
    def _try_resolve_path(values: dict[str, Any], path: str) -> tuple[bool, Any]:
        current: Any = values
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                return False, None
        return True, current

    def _evaluate_condition(self, expression: str, variables: dict[str, Any], results: list[dict]) -> bool:
        expression = re.sub(
            r"\{\{\s*([^{}]+?)\s*\}\}",
            lambda match: repr(self._resolve_path(variables, match.group(1).strip())),
            expression,
        )
        tree = ast.parse(expression, mode="eval")
        allowed = (ast.Expression, ast.BoolOp, ast.UnaryOp, ast.Compare, ast.Name, ast.Load, ast.Constant,
                   ast.Subscript, ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
                   ast.Eq, ast.NotEq, ast.Gt, ast.GtE, ast.Lt, ast.LtE)
        if any(not isinstance(node, allowed) for node in ast.walk(tree)):
            raise ValueError("条件表达式包含不支持的语法")
        return bool(eval(compile(tree, "<scenario-condition>", "eval"), {"__builtins__": {}}, {
            "variables": variables, "steps": results,
            "true": True, "false": False, "null": None,
        }))

    def _skipped_result(self, step: dict, index: int) -> dict:
        now = datetime.utcnow().isoformat()
        return {"step_id": step["id"], "step_index": index, "kind": step["kind"], "name": step["name"],
                "node_id": step.get("_node_id"), "node_index": step.get("_node_index"),
                "node_phase": step.get("_node_phase"),
                "status": "skipped", "message": "Execution skipped",
                "extracted_variables": [], "resolved_bindings": [],
                "attempt_history": [],
                "execution_id": None, "output": None, "error_message": None,
                "started_at": now, "finished_at": now, "duration_ms": 0}

    def _timeout_result(self, step: dict, index: int) -> dict:
        now = datetime.utcnow().isoformat()
        return {"step_id": step["id"], "step_index": index, "kind": step["kind"], "name": step["name"],
                "node_id": step.get("_node_id"), "node_index": step.get("_node_index"),
                "node_phase": step.get("_node_phase"),
                "status": "timeout", "message": "Scenario execution deadline exceeded",
                "extracted_variables": [], "resolved_bindings": [],
                "attempt_history": [],
                "execution_id": None, "output": None,
                "error_message": "Scenario execution deadline exceeded",
                "started_at": now, "finished_at": now, "duration_ms": 0}

    def _commit_unique(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self._raise_name_conflict(exc)

    def _flush_unique(self) -> None:
        try:
            self.db.flush()
        except IntegrityError as exc:
            self._raise_name_conflict(exc)

    def _raise_name_conflict(self, exc: IntegrityError) -> None:
        self.db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="同一项目下场景名称不能重复",
        ) from exc

    def _require_view(self, user: User, project_id: int) -> None:
        self.permission_service.require_project_permission(user, project_id, ProjectPermission.VIEW_SCENARIO.value)

    def _require_manage(self, user: User, project_id: int) -> None:
        self.permission_service.require_project_permission(user, project_id, ProjectPermission.MANAGE_SCENARIO.value)
