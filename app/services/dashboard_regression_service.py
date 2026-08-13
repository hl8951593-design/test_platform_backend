from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.core.sensitive_data import request_fingerprint
from app.db.session import SessionLocal
from app.models.dashboard import DashboardRegressionRun
from app.models.project import Project, ProjectEnvironment
from app.models.scenario import TestScenario, TestScenarioExecution
from app.models.system_test_case import SystemCaseApiRelation, SystemTestCase
from app.models.test_case import TestCase, TestCaseEnvironment, TestCaseExecution
from app.models.test_plan import TestPlan, TestPlanEnvironment, TestPlanRun
from app.models.user import User
from app.models.visual_flow import VisualFlow, VisualFlowExecution
from app.models.websocket_test_case import (
    WebSocketTestCase,
    WebSocketTestCaseEnvironment,
    WebSocketTestCaseExecution,
)
from app.schemas.dashboard import (
    CreateDashboardRegressionRunRequest,
    DashboardRegressionExecutionResource,
    DashboardRegressionRunResponse,
)
from app.services.permission_service import PermissionService
from app.services.scenario_service import ScenarioService
from app.services.test_case_service import TestCaseService
from app.services.test_plan_service import TestPlanService
from app.services.visual_flow_service import VisualFlowService
from app.services.websocket_test_case_service import WebSocketTestCaseService


class DashboardRegressionService:
    ACTIVE_STATUSES = {"queued", "running"}
    SUCCESS_STATUSES = {"passed", "success", "completed"}
    FAILURE_STATUSES = {"failed", "failure", "error", "timeout", "cancelled"}

    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def create_run(
        self,
        *,
        payload: CreateDashboardRegressionRunRequest,
        current_user: User,
    ) -> DashboardRegressionRunResponse:
        permission = (
            ProjectPermission.RUN_PLAN.value
            if payload.scope_type == "test_plan"
            else ProjectPermission.EXECUTE_TEST.value
        )
        self.permission_service.require_project_permission(current_user, payload.project_id, permission)
        self._validate_environment(payload.project_id, payload.environment_id)
        # Serialize duplicate detection and parent creation per project. A plain
        # read-then-insert check can admit two identical active runs concurrently.
        self.db.scalar(
            select(Project.id).where(Project.id == payload.project_id).with_for_update()
        )
        request_snapshot = payload.model_dump(mode="json")
        fingerprint = request_fingerprint(request_snapshot)
        existing = self.db.scalar(
            select(DashboardRegressionRun).where(
                DashboardRegressionRun.project_id == payload.project_id,
                DashboardRegressionRun.created_by_id == current_user.id,
                DashboardRegressionRun.request_hash == fingerprint,
                DashboardRegressionRun.status.in_(tuple(self.ACTIVE_STATUSES)),
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "相同范围的回归任务仍在执行", "run_id": existing.id},
            )
        targets = self._select_targets(payload)
        if not targets:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="当前范围内没有可执行的回归目标",
            )
        now = datetime.now()
        run = DashboardRegressionRun(
            id=f"dashboard-regression-{uuid.uuid4().hex}",
            project_id=payload.project_id,
            environment_id=payload.environment_id,
            created_by_id=current_user.id,
            run_type=self._run_type(payload.scope_type),
            scope_type=payload.scope_type,
            strategy=payload.strategy,
            request_hash=fingerprint,
            request_snapshot=request_snapshot,
            target_snapshot=targets,
            child_executions=[],
            status="queued",
            target_count=len(targets),
            passed_count=0,
            failed_count=0,
            queued_at=now,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return self._to_response(run)

    def get_run(self, *, run_id: str, current_user: User) -> DashboardRegressionRunResponse:
        run = self._run_or_404(run_id)
        self.permission_service.require_project_access(current_user, run.project_id)
        return self._to_response(run)

    @classmethod
    def execute_queued_run(cls, run_id: str) -> None:
        with SessionLocal() as db:
            cls(db)._execute(run_id)

    def _execute(self, run_id: str) -> None:
        run = self._run_or_404(run_id)
        if run.status != "queued":
            return
        run.status = "running"
        run.started_at = datetime.now()
        self.db.commit()
        children: list[dict] = []
        passed_count = 0
        failed_count = 0
        try:
            user = self.db.get(User, run.created_by_id)
            if user is None or not user.is_active:
                raise RuntimeError("回归任务创建用户不存在或已停用")
            for index, target in enumerate(run.target_snapshot or []):
                try:
                    child = self._execute_target(run, target, user, index)
                except Exception as exc:  # noqa: BLE001
                    child = {
                        "resource_type": target.get("resource_type"),
                        "resource_id": target.get("resource_id"),
                        "resource_name": target.get("resource_name"),
                        "status": "failed",
                        "error_message": str(exc)[:1000],
                    }
                children.append(child)
                if str(child.get("status") or "").lower() in self.SUCCESS_STATUSES:
                    passed_count += 1
                else:
                    failed_count += 1
                self.db.expire_all()
                current = self.db.get(DashboardRegressionRun, run_id)
                if current is None:
                    return
                current.child_executions = list(children)
                current.passed_count = passed_count
                current.failed_count = failed_count
                self.db.commit()
                run = current
            run.status = "passed" if failed_count == 0 else "failed"
            run.finished_at = datetime.now()
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            failed_run = self.db.get(DashboardRegressionRun, run_id)
            if failed_run is not None:
                failed_run.status = "failed"
                failed_run.error_message = str(exc)[:2000]
                failed_run.child_executions = list(children)
                failed_run.passed_count = passed_count
                failed_run.failed_count = max(failed_count, failed_run.target_count - passed_count)
                failed_run.finished_at = datetime.now()
                self.db.commit()

    def _execute_target(
        self,
        run: DashboardRegressionRun,
        target: dict,
        user: User,
        index: int,
    ) -> dict:
        resource_type = target["resource_type"]
        resource_id = int(target["resource_id"])
        if resource_type == "http_test_case":
            execution = TestCaseService(self.db).enqueue_saved_case(
                project_id=run.project_id,
                test_case_id=resource_id,
                environment_id=run.environment_id,
                current_user=user,
                trigger_source="dashboard_regression",
            )
            TestCaseService.execute_queued_execution(execution.id)
            self.db.expire_all()
            result = self.db.get(TestCaseExecution, execution.id)
        elif resource_type == "websocket_test_case":
            execution = WebSocketTestCaseService(self.db).enqueue_saved_case(
                project_id=run.project_id,
                test_case_id=resource_id,
                environment_id=run.environment_id,
                current_user=user,
                trigger_source="dashboard_regression",
            )
            WebSocketTestCaseService.execute_queued_execution(execution.id)
            self.db.expire_all()
            result = self.db.get(WebSocketTestCaseExecution, execution.id)
        elif resource_type == "scenario":
            queued = ScenarioService(self.db).enqueue_scenario(
                project_id=run.project_id,
                scenario_id=resource_id,
                environment_id=run.environment_id,
                dataset_ids=None,
                idempotency_key=f"{run.id}:scenario:{resource_id}:{index}",
                current_user=user,
            )
            execution_id = queued["execution_id"]
            ScenarioService.execute_queued_execution(execution_id)
            self.db.expire_all()
            result = self.db.get(TestScenarioExecution, execution_id)
        elif resource_type == "flow":
            execution, _, _ = VisualFlowService(self.db).enqueue_saved(
                project_id=run.project_id,
                flow_id=resource_id,
                environment_id=run.environment_id,
                idempotency_key=f"{run.id}:flow:{resource_id}:{index}",
                current_user=user,
            )
            VisualFlowService.execute_queued_execution(execution.id)
            self.db.expire_all()
            result = self.db.get(VisualFlowExecution, execution.id)
        elif resource_type == "test_plan":
            result = TestPlanService(self.db).create_plan_run(
                project_id=run.project_id,
                plan_id=resource_id,
                environment_id=run.environment_id,
                idempotency_key=f"{run.id}:plan:{resource_id}:{index}",
                current_user=user,
                trigger="dashboard_regression",
                request_context={"dashboard_regression_run_id": run.id},
            )
            result = TestPlanService(self.db).execute_run(result.id)
        else:
            raise RuntimeError(f"不支持的回归目标类型：{resource_type}")
        if result is None:
            raise RuntimeError("子执行记录不存在")
        return {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "resource_name": target.get("resource_name"),
            "execution_id": result.id,
            "status": self._normalize_child_status(result.status),
            "error_message": getattr(result, "error_message", None),
        }

    def _select_targets(self, payload: CreateDashboardRegressionRunRequest) -> list[dict]:
        ids = self._integer_ids(payload.scope_ids)
        if payload.scope_type == "test_plan":
            if not ids:
                raise HTTPException(status_code=422, detail="test_plan 范围必须提供 scope_ids")
            rows = self.db.execute(
                select(TestPlan)
                .join(TestPlanEnvironment, TestPlanEnvironment.plan_id == TestPlan.id)
                .where(
                    TestPlan.project_id == payload.project_id,
                    TestPlan.id.in_(ids),
                    TestPlan.is_deleted.is_(False),
                    TestPlanEnvironment.environment_id == payload.environment_id,
                )
                .order_by(TestPlan.id)
            ).scalars().all()
            return [self._target("test_plan", row.id, row.name) for row in rows]
        if payload.scope_type == "scenario":
            if not ids:
                raise HTTPException(status_code=422, detail="scenario 范围必须提供 scope_ids")
            rows = self.db.scalars(
                select(TestScenario).where(
                    TestScenario.project_id == payload.project_id,
                    TestScenario.id.in_(ids),
                    TestScenario.is_deleted.is_(False),
                ).order_by(TestScenario.id)
            ).all()
            return [self._target("scenario", row.id, row.name) for row in rows]
        if payload.scope_type == "flow":
            if not ids:
                raise HTTPException(status_code=422, detail="flow 范围必须提供 scope_ids")
            rows = self.db.scalars(
                select(VisualFlow).where(
                    VisualFlow.project_id == payload.project_id,
                    VisualFlow.id.in_(ids),
                ).order_by(VisualFlow.id)
            ).all()
            return [self._target("flow", row.id, row.name) for row in rows]
        if payload.scope_type == "test_cases" and not ids:
            raise HTTPException(status_code=422, detail="test_cases 范围必须提供 scope_ids")
        return self._test_case_targets(payload, ids if payload.scope_type == "test_cases" else None)

    def _test_case_targets(
        self,
        payload: CreateDashboardRegressionRunRequest,
        explicit_ids: list[int] | None,
    ) -> list[dict]:
        target_keys: set[tuple[str, int]] = set()
        targets: list[dict] = []

        def append(resource_type: str, resource_id: int, name: str) -> None:
            key = (resource_type, resource_id)
            if key not in target_keys and len(targets) < 200:
                target_keys.add(key)
                targets.append(self._target(resource_type, resource_id, name))

        if payload.scope_type == "smart" and payload.strategy in {"failed_first", "risk_first"}:
            self._append_recent_failures(payload, append)
        if payload.include_system_cases and (payload.strategy == "risk_first" or explicit_ids is not None):
            statement = (
                select(SystemCaseApiRelation.api_case_id, SystemTestCase.title)
                .join(SystemTestCase, SystemTestCase.id == SystemCaseApiRelation.system_case_id)
                .where(SystemTestCase.project_id == payload.project_id)
            )
            if explicit_ids is not None:
                statement = statement.where(SystemTestCase.id.in_(explicit_ids))
            else:
                statement = statement.where(SystemTestCase.priority.in_(("P0", "P1")))
            for api_case_id, title in self.db.execute(statement).all():
                append("http_test_case", int(api_case_id), f"系统用例关联：{title}")

        should_add_all = payload.strategy == "full" or not targets
        if should_add_all or explicit_ids is not None:
            if payload.include_http:
                statement = select(TestCase).where(TestCase.project_id == payload.project_id)
                if explicit_ids is not None:
                    statement = statement.where(TestCase.id.in_(explicit_ids))
                statement = statement.where(
                    or_(
                        TestCase.environment_id == payload.environment_id,
                        select(TestCaseEnvironment.id).where(
                            TestCaseEnvironment.test_case_id == TestCase.id,
                            TestCaseEnvironment.environment_id == payload.environment_id,
                        ).exists(),
                    )
                ).order_by(TestCase.id)
                for row in self.db.scalars(statement).all():
                    append("http_test_case", row.id, row.name)
            if payload.include_websocket:
                statement = select(WebSocketTestCase).where(WebSocketTestCase.project_id == payload.project_id)
                if explicit_ids is not None:
                    statement = statement.where(WebSocketTestCase.id.in_(explicit_ids))
                statement = statement.where(
                    or_(
                        WebSocketTestCase.environment_id == payload.environment_id,
                        select(WebSocketTestCaseEnvironment.id).where(
                            WebSocketTestCaseEnvironment.websocket_test_case_id == WebSocketTestCase.id,
                            WebSocketTestCaseEnvironment.environment_id == payload.environment_id,
                        ).exists(),
                    )
                ).order_by(WebSocketTestCase.id)
                for row in self.db.scalars(statement).all():
                    append("websocket_test_case", row.id, row.name)
        return targets

    def _append_recent_failures(self, payload, append) -> None:
        if payload.include_http:
            rows = self.db.execute(
                select(TestCaseExecution.test_case_id, TestCase.name)
                .join(TestCase, TestCase.id == TestCaseExecution.test_case_id)
                .where(
                    TestCaseExecution.project_id == payload.project_id,
                    TestCaseExecution.environment_id == payload.environment_id,
                    TestCaseExecution.status.in_(("failed", "failure", "error", "timeout")),
                    TestCaseExecution.test_case_id.is_not(None),
                )
                .order_by(TestCaseExecution.created_at.desc())
                .limit(100)
            ).all()
            for resource_id, name in rows:
                append("http_test_case", int(resource_id), name)
        if payload.include_websocket:
            rows = self.db.execute(
                select(WebSocketTestCaseExecution.websocket_test_case_id, WebSocketTestCase.name)
                .join(WebSocketTestCase, WebSocketTestCase.id == WebSocketTestCaseExecution.websocket_test_case_id)
                .where(
                    WebSocketTestCaseExecution.project_id == payload.project_id,
                    WebSocketTestCaseExecution.environment_id == payload.environment_id,
                    WebSocketTestCaseExecution.status.in_(("failed", "failure", "error", "timeout")),
                    WebSocketTestCaseExecution.websocket_test_case_id.is_not(None),
                )
                .order_by(WebSocketTestCaseExecution.created_at.desc())
                .limit(100)
            ).all()
            for resource_id, name in rows:
                append("websocket_test_case", int(resource_id), name)

    def _validate_environment(self, project_id: int, environment_id: int) -> None:
        environment = self.db.scalar(
            select(ProjectEnvironment.id).where(
                ProjectEnvironment.id == environment_id,
                ProjectEnvironment.project_id == project_id,
                ProjectEnvironment.is_deleted.is_(False),
            )
        )
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目环境不存在")

    def _run_or_404(self, run_id: str) -> DashboardRegressionRun:
        run = self.db.get(DashboardRegressionRun, run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="回归任务不存在")
        return run

    @staticmethod
    def _target(resource_type: str, resource_id: int, resource_name: str) -> dict:
        return {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "resource_name": resource_name,
        }

    @staticmethod
    def _integer_ids(values: list[int | str]) -> list[int]:
        result: list[int] = []
        for value in values:
            try:
                parsed = int(value)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"无效的 scope_id：{value}") from exc
            if parsed <= 0:
                raise HTTPException(status_code=422, detail=f"无效的 scope_id：{value}")
            if parsed not in result:
                result.append(parsed)
        return result

    @staticmethod
    def _run_type(scope_type: str) -> str:
        return {
            "test_plan": "test_plan",
            "scenario": "scenario",
            "flow": "flow",
            "test_cases": "batch_test_case",
            "smart": "batch_test_case",
        }[scope_type]

    @staticmethod
    def _normalize_child_status(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"passed", "success", "completed"}:
            return "passed"
        if normalized == "timeout":
            return "timeout"
        if normalized == "cancelled":
            return "cancelled"
        if normalized in {"queued", "pending", "running"}:
            return normalized
        return "failed"

    @staticmethod
    def _to_response(run: DashboardRegressionRun) -> DashboardRegressionRunResponse:
        return DashboardRegressionRunResponse(
            run_id=run.id,
            run_type=run.run_type,
            status=run.status,
            target_count=run.target_count,
            passed_count=run.passed_count,
            failed_count=run.failed_count,
            queued_at=run.queued_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            child_executions=run.child_executions or [],
            error_message=run.error_message,
            poll_after_ms=1000,
            execution_resource=DashboardRegressionExecutionResource(
                resource_type="execution",
                resource_id=run.id,
            ),
        )
