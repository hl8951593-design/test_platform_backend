import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.cron import cron_occurrences, next_cron_time
from app.core.permissions import ProjectPermission
from app.db.session import SessionLocal
from app.models.project import ProjectEnvironment
from app.models.scenario import TestScenario
from app.models.test_plan import TestPlan, TestPlanEnvironment, TestPlanRun, TestPlanScenario
from app.models.user import User
from app.schemas.test_plan import TestPlanCreateRequest, TestPlanPayload, TestPlanUpdateRequest
from app.services.permission_service import PermissionService
from app.services.scenario_service import ScenarioService


class TestPlanService:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def list_plans(self, *, project_id: int, current_user: User, keyword: str | None, enabled: bool | None,
                   trigger_type: str | None, page: int, page_size: int) -> dict[str, Any]:
        self._require_view(current_user, project_id)
        filters = [TestPlan.project_id == project_id, TestPlan.is_deleted.is_(False)]
        if keyword:
            filters.append(or_(TestPlan.name.contains(keyword), TestPlan.description.contains(keyword)))
        if enabled is not None:
            filters.append(TestPlan.enabled.is_(enabled))
        if trigger_type:
            filters.append(TestPlan.trigger_type == trigger_type)
        total = self.db.scalar(select(func.count()).select_from(TestPlan).where(*filters)) or 0
        plans = list(self.db.scalars(
            select(TestPlan).where(*filters).order_by(TestPlan.updated_at.desc(), TestPlan.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).all())
        all_filters = [TestPlan.project_id == project_id, TestPlan.is_deleted.is_(False)]
        statistics = {
            "total": self.db.scalar(select(func.count()).select_from(TestPlan).where(*all_filters)) or 0,
            "enabled": self.db.scalar(select(func.count()).select_from(TestPlan).where(*all_filters, TestPlan.enabled.is_(True))) or 0,
            "scheduled": self.db.scalar(select(func.count()).select_from(TestPlan).where(
                *all_filters, TestPlan.enabled.is_(True), TestPlan.trigger_type == "cron"
            )) or 0,
            "recent_failed": self.db.scalar(select(func.count()).select_from(TestPlanRun).where(
                TestPlanRun.project_id == project_id, TestPlanRun.status == "failed"
            )) or 0,
        }
        return {"items": plans, "total": total, "page": page, "page_size": page_size, "statistics": statistics}

    def get_plan(self, *, project_id: int, plan_id: int, current_user: User) -> TestPlan:
        self._require_view(current_user, project_id)
        return self._get_plan(project_id, plan_id)

    def create_plan(self, *, project_id: int, payload: TestPlanCreateRequest, current_user: User) -> TestPlan:
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.CREATE_PLAN.value)
        plan = TestPlan(project_id=project_id, version=1, created_by_id=current_user.id, updated_by_id=current_user.id)
        self._apply_payload(plan, payload, project_id)
        self.db.add(plan)
        self.db.flush()
        self._replace_bindings(plan)
        self._commit_unique("同一项目下计划名称不能重复")
        self.db.refresh(plan)
        return plan

    def update_plan(self, *, project_id: int, plan_id: int, payload: TestPlanUpdateRequest, current_user: User) -> TestPlan:
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.UPDATE_PLAN.value)
        plan = self._get_plan(project_id, plan_id)
        if plan.version != payload.version:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"message": "计划版本冲突", "current_version": plan.version})
        self._apply_payload(plan, payload, project_id)
        self._replace_bindings(plan)
        plan.version += 1
        plan.updated_by_id = current_user.id
        self._commit_unique("同一项目下计划名称不能重复")
        self.db.refresh(plan)
        return plan

    def set_enabled(self, *, project_id: int, plan_id: int, enabled: bool, version: int | None, current_user: User) -> TestPlan:
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.UPDATE_PLAN.value)
        plan = self._get_plan(project_id, plan_id)
        if version is not None and version != plan.version:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"message": "计划版本冲突", "current_version": plan.version})
        plan.enabled = enabled
        plan.next_run_at = self._calculate_next_run(plan) if enabled else None
        plan.version += 1
        plan.updated_by_id = current_user.id
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def delete_plan(self, *, project_id: int, plan_id: int, current_user: User) -> TestPlan:
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.DELETE_PLAN.value)
        plan = self._get_plan(project_id, plan_id)
        plan.is_deleted = True
        plan.enabled = False
        suffix = f"__deleted_{plan.id}_{int(datetime.utcnow().timestamp())}"
        plan.name = f"{plan.name[:128 - len(suffix)]}{suffix}"
        plan.version += 1
        plan.updated_by_id = current_user.id
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def execute_plan(self, *, project_id: int, plan_id: int, environment_id: int, idempotency_key: str | None,
                     current_user: User, trigger: str = "manual", scheduled_at: datetime | None = None) -> TestPlanRun:
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.RUN_PLAN.value)
        plan = self._get_plan(project_id, plan_id)
        if environment_id not in plan.environment_ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="执行环境未绑定到此计划")
        environment = self._get_environment(project_id, environment_id)
        if idempotency_key:
            existing = self.db.scalar(select(TestPlanRun).where(
                TestPlanRun.project_id == project_id, TestPlanRun.idempotency_key == idempotency_key
            ))
            if existing:
                return existing

        started_at = datetime.utcnow()
        run = TestPlanRun(
            plan_id=plan.id, project_id=project_id, plan_name=plan.name, plan_version=plan.version,
            environment_id=environment.id, environment_name=environment.name, status="running", trigger=trigger,
            idempotency_key=idempotency_key, plan_snapshot=self._snapshot(plan), target_results=[],
            target_count=len(plan.targets), operator_id=current_user.id, scheduled_at=scheduled_at, started_at=started_at,
        )
        self.db.add(run)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(select(TestPlanRun).where(
                TestPlanRun.project_id == project_id, TestPlanRun.idempotency_key == idempotency_key
            ))
            if existing:
                return existing
            raise
        self.db.refresh(run)

        ordered_targets = sorted(plan.targets, key=lambda item: item["sort_order"])
        if plan.execution_mode == "parallel":
            results = self._execute_parallel(
                project_id=project_id, environment_id=environment_id, targets=ordered_targets,
                retry_count=plan.retry_count, run_id=run.id, current_user_id=current_user.id, trigger=trigger,
            )
        else:
            results = []
            for target in ordered_targets:
                result = self._execute_target(
                    project_id=project_id, environment_id=environment_id, target=target,
                    retry_count=plan.retry_count, run_id=run.id, current_user=current_user, trigger=trigger,
                )
                results.append(result)
                if result["status"] != "passed" and plan.failure_policy == "stop":
                    break

        finished_at = datetime.utcnow()
        run.target_results = results
        run.passed_count = sum(item["status"] == "passed" for item in results)
        run.failed_count = sum(item["status"] != "passed" for item in results)
        run.status = "passed" if run.failed_count == 0 and len(results) == len(plan.targets) else "failed"
        run.finished_at = finished_at
        run.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        if run.duration_ms > plan.timeout_minutes * 60 * 1000:
            run.status = "timeout"
        plan.last_run_at = finished_at
        self.db.commit()
        self.db.refresh(run)
        return run

    def run_due_plans(self, *, now: datetime | None = None) -> int:
        current_time = now or datetime.utcnow()
        plans = list(self.db.scalars(
            select(TestPlan)
            .where(
                TestPlan.enabled.is_(True),
                TestPlan.is_deleted.is_(False),
                TestPlan.trigger_type == "cron",
                TestPlan.next_run_at.is_not(None),
                TestPlan.next_run_at <= current_time,
            )
            .with_for_update(skip_locked=True)
        ).all())
        claimed: list[tuple[int, datetime, list[int], int, int]] = []
        for plan in plans:
            scheduled_at = plan.next_run_at or current_time
            claimed.append((plan.project_id, scheduled_at, list(plan.environment_ids), plan.id, plan.created_by_id))
            plan.next_run_at = next_cron_time(plan.cron_expression or "", plan.schedule_timezone, current_time)
        self.db.commit()

        executed = 0
        for project_id, scheduled_at, environment_ids, plan_id, user_id in claimed:
            user = self.db.get(User, user_id)
            if user is None or not user.is_active:
                continue
            for environment_id in environment_ids:
                try:
                    self.execute_plan(
                        project_id=project_id,
                        plan_id=plan_id,
                        environment_id=environment_id,
                        idempotency_key=f"schedule-{plan_id}-{environment_id}-{scheduled_at.isoformat()}",
                        current_user=user,
                        trigger="schedule",
                        scheduled_at=scheduled_at,
                    )
                    executed += 1
                except Exception:  # noqa: BLE001
                    self.db.rollback()
        return executed

    def list_schedule(self, *, project_id: int, current_user: User, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
        self._require_view(current_user, project_id)
        if end_at <= start_at:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="end_at 必须晚于 start_at")
        if end_at - start_at > timedelta(days=90):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="调度查询范围不能超过 90 天")
        plans = list(self.db.scalars(select(TestPlan).where(
            TestPlan.project_id == project_id, TestPlan.enabled.is_(True), TestPlan.is_deleted.is_(False),
            TestPlan.trigger_type == "cron",
        )).all())
        items = []
        for plan in plans:
            for scheduled_at in cron_occurrences(
                plan.cron_expression or "", plan.schedule_timezone, start_at, end_at
            ):
                items.append({
                    "id": f"schedule-{plan.id}-{scheduled_at.isoformat()}",
                    "plan_id": plan.id, "plan_name": plan.name, "trigger_type": "cron",
                    "cron_expression": plan.cron_expression, "schedule_timezone": plan.schedule_timezone,
                    "scheduled_at": scheduled_at, "environment_ids": plan.environment_ids, "enabled": plan.enabled,
                })
        return sorted(items, key=lambda item: item["scheduled_at"])

    def list_runs(self, *, project_id: int, current_user: User, page: int, page_size: int) -> dict[str, Any]:
        self._require_view(current_user, project_id)
        total = self.db.scalar(select(func.count()).select_from(TestPlanRun).where(TestPlanRun.project_id == project_id)) or 0
        items = list(self.db.scalars(
            select(TestPlanRun).options(selectinload(TestPlanRun.operator))
            .where(TestPlanRun.project_id == project_id)
            .order_by(TestPlanRun.started_at.desc(), TestPlanRun.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).all())
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get_run(self, *, project_id: int, run_id: int, current_user: User) -> TestPlanRun:
        self._require_view(current_user, project_id)
        run = self.db.scalar(select(TestPlanRun).options(selectinload(TestPlanRun.operator)).where(
            TestPlanRun.id == run_id, TestPlanRun.project_id == project_id
        ))
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="计划运行记录不存在")
        return run

    def delete_run(self, *, project_id: int, run_id: int, current_user: User) -> None:
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.DELETE_PLAN_HISTORY.value
        )
        run = self.db.scalar(select(TestPlanRun).where(
            TestPlanRun.id == run_id, TestPlanRun.project_id == project_id
        ))
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="计划运行记录不存在")
        self.db.delete(run)
        self.db.commit()

    def clear_runs(self, *, project_id: int, current_user: User) -> int:
        self.permission_service.require_project_permission(
            current_user, project_id, ProjectPermission.DELETE_PLAN_HISTORY.value
        )
        runs = list(self.db.scalars(select(TestPlanRun).where(TestPlanRun.project_id == project_id)).all())
        for run in runs:
            self.db.delete(run)
        self.db.commit()
        return len(runs)

    def import_plans(self, *, project_id: int, payloads: list[TestPlanCreateRequest], current_user: User) -> list[TestPlan]:
        self.permission_service.require_project_permission(current_user, project_id, ProjectPermission.CREATE_PLAN.value)
        result = []
        for payload in payloads:
            data = payload.model_copy(update={"enabled": False})
            result.append(self.create_plan(project_id=project_id, payload=data, current_user=current_user))
        return result

    def export_plans(self, *, project_id: int, current_user: User) -> list[TestPlan]:
        self._require_view(current_user, project_id)
        return list(self.db.scalars(
            select(TestPlan).where(TestPlan.project_id == project_id, TestPlan.is_deleted.is_(False))
            .order_by(TestPlan.id)
        ).all())

    def _apply_payload(self, plan: TestPlan, payload: TestPlanPayload, project_id: int) -> None:
        environment_ids = list(dict.fromkeys(payload.environment_ids))
        for environment_id in environment_ids:
            self._get_environment(project_id, environment_id)
        targets = [self._target_snapshot(project_id, target.kind, target.reference_id, target.sort_order) for target in payload.targets]
        targets.sort(key=lambda item: item["sort_order"])
        for field in ("name", "description", "enabled", "trigger_type", "cron_expression", "schedule_timezone", "webhook_event",
                      "execution_mode", "failure_policy", "retry_count", "timeout_minutes"):
            setattr(plan, field, getattr(payload, field))
        plan.cron_expression = payload.cron_expression if payload.trigger_type == "cron" else None
        plan.webhook_event = payload.webhook_event if payload.trigger_type == "webhook" else None
        plan.environment_ids = environment_ids
        plan.targets = targets
        plan.notification_emails = [str(item) for item in payload.notification_emails]
        plan.tags = payload.tags
        plan.next_run_at = self._calculate_next_run(plan)

    def _target_snapshot(self, project_id: int, kind: str, reference_id: int, sort_order: int) -> dict[str, Any]:
        asset = self.db.scalar(select(TestScenario).where(
            TestScenario.id == reference_id, TestScenario.project_id == project_id, TestScenario.is_deleted.is_(False)
        ))
        if asset is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"自动化场景不存在或不属于当前项目: {reference_id}")
        return {"id": f"{kind}-{reference_id}", "reference_id": reference_id, "kind": kind, "name": asset.name,
                "method": "SCENARIO", "path": None, "sort_order": sort_order, "scenario_version": asset.current_version}

    def _execute_target(self, *, project_id: int, environment_id: int, target: dict, retry_count: int,
                        run_id: int, current_user: User, trigger: str) -> dict[str, Any]:
        started_at = datetime.utcnow()
        error_message = None
        execution_id = None
        scenario_run_ids: list[int] = []
        status_value = "failed"
        attempt = 0
        for attempt in range(1, retry_count + 2):
            try:
                runs = ScenarioService(self.db).execute_scenario(
                    project_id=project_id, scenario_id=target["reference_id"], environment_id=environment_id,
                    dataset_ids=None, idempotency_key=f"plan-run-{run_id}-target-{target['id']}-attempt-{attempt}",
                    current_user=current_user, trigger_type=trigger, scenario_version=target["scenario_version"],
                )
                scenario_run_ids = [run.id for run in runs]
                execution_id = scenario_run_ids[0] if scenario_run_ids else None
                status_value = "passed" if runs and all(run.status == "passed" for run in runs) else "failed"
                if status_value == "passed":
                    break
                error_message = getattr(execution, "error_message", None) or f"目标执行状态为 {status_value}"
            except Exception as exc:  # noqa: BLE001
                self.db.rollback()
                error_message = str(exc)
                status_value = "failed"
        finished_at = datetime.utcnow()
        return {
            "id": f"result-{run_id}-{target['id']}", "target_id": target["id"], "reference_id": target["reference_id"],
            "kind": target["kind"], "name": target["name"], "status": "passed" if status_value == "passed" else "failed",
            "attempt": attempt, "execution_id": execution_id, "started_at": started_at.isoformat(),
            "scenario_run_ids": scenario_run_ids,
            "finished_at": finished_at.isoformat(), "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
            "error_message": error_message,
        }

    def _execute_parallel(self, *, project_id: int, environment_id: int, targets: list[dict], retry_count: int,
                          run_id: int, current_user_id: int, trigger: str) -> list[dict[str, Any]]:
        results_by_id: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=min(len(targets), 8)) as executor:
            futures = {
                executor.submit(
                    self._execute_target_in_new_session,
                    project_id, environment_id, target, retry_count, run_id, current_user_id, trigger,
                ): target["id"]
                for target in targets
            }
            for future in as_completed(futures):
                results_by_id[futures[future]] = future.result()
        return [results_by_id[target["id"]] for target in targets]

    @staticmethod
    def _execute_target_in_new_session(project_id: int, environment_id: int, target: dict, retry_count: int,
                                       run_id: int, current_user_id: int, trigger: str) -> dict[str, Any]:
        with SessionLocal() as db:
            current_user = db.get(User, current_user_id)
            if current_user is None:
                raise RuntimeError("执行用户不存在")
            return TestPlanService(db)._execute_target(
                project_id=project_id, environment_id=environment_id, target=target,
                retry_count=retry_count, run_id=run_id, current_user=current_user, trigger=trigger,
            )

    def _get_plan(self, project_id: int, plan_id: int) -> TestPlan:
        plan = self.db.scalar(select(TestPlan).where(
            TestPlan.id == plan_id, TestPlan.project_id == project_id, TestPlan.is_deleted.is_(False)
        ))
        if plan is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试计划不存在")
        return plan

    def _get_environment(self, project_id: int, environment_id: int) -> ProjectEnvironment:
        environment = self.db.scalar(select(ProjectEnvironment).where(
            ProjectEnvironment.id == environment_id, ProjectEnvironment.project_id == project_id,
            ProjectEnvironment.is_deleted.is_(False),
        ))
        if environment is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"环境不存在或不属于当前项目: {environment_id}")
        return environment

    def _snapshot(self, plan: TestPlan) -> dict[str, Any]:
        return {
            "id": plan.id, "project_id": plan.project_id, "version": plan.version, "name": plan.name,
            "environment_ids": copy.deepcopy(plan.environment_ids), "targets": copy.deepcopy(plan.targets),
            "execution_mode": plan.execution_mode, "failure_policy": plan.failure_policy,
            "retry_count": plan.retry_count, "timeout_minutes": plan.timeout_minutes,
            "trigger_type": plan.trigger_type, "cron_expression": plan.cron_expression,
            "schedule_timezone": plan.schedule_timezone,
        }

    def _calculate_next_run(self, plan: TestPlan) -> datetime | None:
        if not plan.enabled or plan.trigger_type != "cron" or not plan.cron_expression:
            return None
        return next_cron_time(plan.cron_expression, plan.schedule_timezone)

    def _replace_bindings(self, plan: TestPlan) -> None:
        self.db.execute(delete(TestPlanScenario).where(TestPlanScenario.plan_id == plan.id))
        self.db.execute(delete(TestPlanEnvironment).where(TestPlanEnvironment.plan_id == plan.id))
        for environment_id in plan.environment_ids:
            self.db.add(TestPlanEnvironment(
                plan_id=plan.id, project_id=plan.project_id, environment_id=environment_id
            ))
        for target in plan.targets:
            self.db.add(TestPlanScenario(
                plan_id=plan.id, project_id=plan.project_id, scenario_id=target["reference_id"],
                scenario_version_at_bind=target["scenario_version"], sort_order=target["sort_order"],
                name_snapshot=target["name"],
            ))

    def _commit_unique(self, message: str) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message) from exc

    def _require_view(self, user: User, project_id: int) -> None:
        self.permission_service.require_project_permission(user, project_id, ProjectPermission.VIEW_PLAN.value)
