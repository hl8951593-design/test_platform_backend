from datetime import datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import case, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from app.models.defect import Defect
from app.models.scenario import TestScenario, TestScenarioRun
from app.models.test_case import TestCase, TestCaseExecution
from app.models.test_plan import TestPlan, TestPlanRun
from app.models.user import User
from app.models.visual_flow import VisualFlow, VisualFlowExecution
from app.models.websocket_test_case import WebSocketTestCase, WebSocketTestCaseExecution
from app.schemas.dashboard import (
    DashboardAIRecommendation,
    DashboardAction,
    DashboardActivityFeedItem,
    DashboardActivityFeedResponse,
    DashboardActivityItem,
    DashboardAutomationEfficiencyItem,
    DashboardDefectPrediction,
    DashboardHealthDimension,
    DashboardHealthProfile,
    DashboardHero,
    DashboardKPI,
    DashboardKPIBreakdown,
    DashboardInsightDetailResponse,
    DashboardInsightItem,
    DashboardInsightMetric,
    DashboardInsightSummary,
    DashboardRiskMatrixItem,
    DashboardScope,
    QualityOverview,
)
from app.services.permission_service import PermissionService


class DashboardService:
    PASSED_STATUSES = {"passed", "success", "completed"}
    FAILED_STATUSES = {"failed", "failure", "error", "timeout"}
    ACTIVITY_STATUS_LABELS = {
        "completed": "完成",
        "error": "失败",
        "failed": "失败",
        "failure": "失败",
        "passed": "通过",
        "queued": "排队中",
        "running": "运行中",
        "success": "通过",
        "timeout": "超时",
    }
    CLOSED_DEFECT_STATUSES = {"closed", "resolved", "done", "已关闭", "已解决"}
    ACTIVITY_SOURCE_LIMIT = 5

    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def quality_overview(
        self,
        *,
        project_id: int,
        current_user: User,
        environment_id: int | None,
        range_value: str,
        version: str | None,
    ) -> QualityOverview:
        self.permission_service.require_project_access(current_user, project_id)
        normalized_range = range_value if range_value in {"today", "7d", "30d"} else "today"
        reference_time = self._reference_time(project_id=project_id, environment_id=environment_id)
        started_from = self._range_start(reference_time=reference_time, range_value=normalized_range)
        started_to = reference_time + timedelta(days=1)

        asset_counts = self._asset_counts(project_id=project_id, environment_id=environment_id)
        http_total = asset_counts["http_total"]
        websocket_total = asset_counts["websocket_total"]
        scenario_total = asset_counts["scenario_total"]
        plan_total = asset_counts["plan_total"]
        execution_stats = self._execution_stats(
            project_id=project_id,
            environment_id=environment_id,
            started_from=started_from,
            started_to=started_to,
        )
        execution_total = execution_stats["total"]
        passed_count = execution_stats["passed"]
        failed_count = execution_stats["failed"]
        pass_rate = round(passed_count * 100 / execution_total, 2) if execution_total else 0.0
        open_defect_count, recent_open_defects = self._open_defect_summary(project_id)
        activity_rows = self._activity_rows(
            project_id=project_id,
            environment_id=environment_id,
            started_from=started_from,
            started_to=started_to,
        )
        risk_count = failed_count + open_defect_count
        health_score = max(round(pass_rate - risk_count * 3, 2), 0.0)

        return QualityOverview(
            generated_at=datetime.now(),
            scope=DashboardScope(
                project_id=project_id,
                environment_id=environment_id,
                range=normalized_range,
                version=version,
            ),
            hero=DashboardHero(
                health_score=health_score,
                insight_title=self._hero_title(health_score),
                insight_summary=f"当前范围内执行 {execution_total} 次，通过 {passed_count} 次，失败 {failed_count} 次。",
                risk_count=risk_count,
                updated_text="刚刚更新",
            ),
            kpis=self._kpis(
                execution_total=execution_total,
                passed_count=passed_count,
                failed_count=failed_count,
                pass_rate=pass_rate,
                http_total=http_total,
                websocket_total=websocket_total,
                scenario_total=scenario_total,
                plan_total=plan_total,
                open_defect_count=open_defect_count,
            ),
            risk_matrix=self._risk_matrix(failed_count=failed_count, open_defect_count=open_defect_count),
            automation_efficiency=self._automation_efficiency(
                http_total=http_total,
                websocket_total=websocket_total,
                scenario_total=scenario_total,
            ),
            health_profile=DashboardHealthProfile(
                score=health_score,
                dimensions=[
                    DashboardHealthDimension(label="通过率", value=int(pass_rate)),
                    DashboardHealthDimension(label="稳定性", value=max(0, 100 - failed_count * 8)),
                    DashboardHealthDimension(label="缺陷控制", value=max(0, 100 - open_defect_count * 10)),
                    DashboardHealthDimension(
                        label="自动化覆盖",
                        value=self._automation_percent(http_total, websocket_total, scenario_total),
                    ),
                ],
            ),
            defect_predictions=self._defect_predictions(
                open_defect_count=open_defect_count,
                failed_count=failed_count,
            ),
            ai_recommendations=self._ai_recommendations(
                failed_count=failed_count,
                open_defect_count=open_defect_count,
                pass_rate=pass_rate,
                execution_rows=activity_rows,
                open_defects=recent_open_defects,
            ),
            activity_feed=self._activity_feed(execution_rows=activity_rows, open_defects=recent_open_defects),
        )

    def _range_start(self, *, reference_time: datetime, range_value: str) -> datetime:
        if range_value == "today":
            return datetime.combine(reference_time.date(), datetime.min.time())
        if range_value == "30d":
            return reference_time - timedelta(days=29)
        return reference_time - timedelta(days=6)

    def _reference_time(self, *, project_id: int, environment_id: int | None) -> datetime:
        max_time_sources = [
            self._max_time_select(
                TestCaseExecution.created_at,
                TestCaseExecution.project_id == project_id,
                self._env_filter(TestCaseExecution, environment_id),
            ),
            self._max_time_select(
                WebSocketTestCaseExecution.created_at,
                WebSocketTestCaseExecution.project_id == project_id,
                self._env_filter(WebSocketTestCaseExecution, environment_id),
            ),
            self._max_time_select(
                TestScenarioRun.started_at,
                TestScenarioRun.project_id == project_id,
                self._env_filter(TestScenarioRun, environment_id),
            ),
            self._max_time_select(
                TestPlanRun.started_at,
                TestPlanRun.project_id == project_id,
                TestPlanRun.is_deleted.is_(False),
                self._env_filter(TestPlanRun, environment_id),
            ),
            self._max_time_select(
                VisualFlowExecution.started_at,
                VisualFlowExecution.project_id == project_id,
                self._env_filter(VisualFlowExecution, environment_id),
            ),
            self._max_time_select(Defect.updated_at, Defect.project_id == project_id),
        ]
        combined = union_all(*max_time_sources).subquery()
        latest = self.db.execute(select(func.max(combined.c.occurred_at))).scalar()
        return latest or datetime.now()

    def _max_time_select(self, column, *filters):
        statement = select(func.max(column).label("occurred_at"))
        for condition in filters:
            if condition is not None:
                statement = statement.where(condition)
        return statement

    def _max_datetime(self, column, *filters) -> datetime | None:
        query = self.db.query(func.max(column))
        for condition in filters:
            if condition is not None:
                query = query.filter(condition)
        return query.scalar()

    def _env_filter(self, model, environment_id: int | None):
        if environment_id is None or not hasattr(model, "environment_id"):
            return None
        return model.environment_id == environment_id

    def _count(self, model, *, project_id: int, environment_id: int | None) -> int:
        query = self.db.query(model).filter(model.project_id == project_id)
        if hasattr(model, "is_deleted"):
            query = query.filter(model.is_deleted.is_(False))
        if environment_id is not None and hasattr(model, "environment_id"):
            query = query.filter(model.environment_id == environment_id)
        return int(query.count())

    def _asset_counts(self, *, project_id: int, environment_id: int | None) -> dict[str, int]:
        http_filters = [TestCase.project_id == project_id]
        websocket_filters = [WebSocketTestCase.project_id == project_id]
        scenario_filters = [TestScenario.project_id == project_id, TestScenario.is_deleted.is_(False)]
        if environment_id is not None:
            http_filters.append(TestCase.environment_id == environment_id)
            websocket_filters.append(WebSocketTestCase.environment_id == environment_id)
            scenario_filters.append(TestScenario.environment_id == environment_id)

        statement = select(
            select(func.count()).select_from(TestCase).where(*http_filters).scalar_subquery().label("http_total"),
            select(func.count())
            .select_from(WebSocketTestCase)
            .where(*websocket_filters)
            .scalar_subquery()
            .label("websocket_total"),
            select(func.count())
            .select_from(TestScenario)
            .where(*scenario_filters)
            .scalar_subquery()
            .label("scenario_total"),
            select(func.count())
            .select_from(TestPlan)
            .where(TestPlan.project_id == project_id, TestPlan.is_deleted.is_(False))
            .scalar_subquery()
            .label("plan_total"),
        )
        row = self.db.execute(statement).one()
        return {
            "http_total": int(row.http_total or 0),
            "websocket_total": int(row.websocket_total or 0),
            "scenario_total": int(row.scenario_total or 0),
            "plan_total": int(row.plan_total or 0),
        }

    def _execution_stats(
        self,
        *,
        project_id: int,
        environment_id: int | None,
        started_from: datetime,
        started_to: datetime,
    ) -> dict[str, int]:
        status_sources = [
            self._status_source_select(
                TestCaseExecution,
                TestCaseExecution.status,
                TestCaseExecution.created_at,
                project_id=project_id,
                environment_id=environment_id,
                started_from=started_from,
                started_to=started_to,
                extra_filters=[TestCaseExecution.scenario_run_id.is_(None)],
            ),
            self._status_source_select(
                WebSocketTestCaseExecution,
                WebSocketTestCaseExecution.status,
                WebSocketTestCaseExecution.created_at,
                project_id=project_id,
                environment_id=environment_id,
                started_from=started_from,
                started_to=started_to,
                extra_filters=[WebSocketTestCaseExecution.scenario_run_id.is_(None)],
            ),
            self._status_source_select(
                TestScenarioRun,
                TestScenarioRun.status,
                TestScenarioRun.started_at,
                project_id=project_id,
                environment_id=environment_id,
                started_from=started_from,
                started_to=started_to,
                extra_filters=[TestScenarioRun.plan_run_id.is_(None)],
            ),
            self._status_source_select(
                TestPlanRun,
                TestPlanRun.status,
                TestPlanRun.started_at,
                project_id=project_id,
                environment_id=environment_id,
                started_from=started_from,
                started_to=started_to,
                extra_filters=[TestPlanRun.is_deleted.is_(False)],
            ),
            self._status_source_select(
                VisualFlowExecution,
                VisualFlowExecution.status,
                VisualFlowExecution.started_at,
                project_id=project_id,
                environment_id=environment_id,
                started_from=started_from,
                started_to=started_to,
            ),
        ]
        statuses = union_all(*status_sources).subquery()
        row = self.db.execute(
            select(
                func.count().label("total"),
                func.coalesce(
                    func.sum(case((statuses.c.status.in_(tuple(self.PASSED_STATUSES)), 1), else_=0)),
                    0,
                ).label("passed"),
                func.coalesce(
                    func.sum(case((statuses.c.status.in_(tuple(self.FAILED_STATUSES)), 1), else_=0)),
                    0,
                ).label("failed"),
            )
        ).one()
        return {
            "total": int(row.total or 0),
            "passed": int(row.passed or 0),
            "failed": int(row.failed or 0),
        }

    def _status_source_select(
        self,
        model,
        status_column,
        time_column,
        *,
        project_id: int,
        environment_id: int | None,
        started_from: datetime,
        started_to: datetime,
        extra_filters: list | None = None,
    ):
        statement = select(status_column.label("status")).where(
            model.project_id == project_id,
            time_column >= started_from,
            time_column <= started_to,
        )
        env_filter = self._env_filter(model, environment_id)
        if env_filter is not None:
            statement = statement.where(env_filter)
        for condition in extra_filters or []:
            statement = statement.where(condition)
        return statement

    def _status_stats(
        self,
        model,
        status_column,
        time_column,
        *,
        project_id: int,
        environment_id: int | None,
        started_from: datetime,
        started_to: datetime,
        extra_filters: list | None = None,
    ) -> dict[str, int]:
        query = self.db.query(
            func.count().label("total"),
            func.coalesce(
                func.sum(case((status_column.in_(tuple(self.PASSED_STATUSES)), 1), else_=0)),
                0,
            ).label("passed"),
            func.coalesce(
                func.sum(case((status_column.in_(tuple(self.FAILED_STATUSES)), 1), else_=0)),
                0,
            ).label("failed"),
        ).filter(
            model.project_id == project_id,
            time_column >= started_from,
            time_column <= started_to,
        )
        env_filter = self._env_filter(model, environment_id)
        if env_filter is not None:
            query = query.filter(env_filter)
        for condition in extra_filters or []:
            query = query.filter(condition)
        row = query.one()
        return {
            "total": int(row.total or 0),
            "passed": int(row.passed or 0),
            "failed": int(row.failed or 0),
        }

    def _activity_rows(
        self,
        *,
        project_id: int,
        environment_id: int | None,
        started_from: datetime,
        started_to: datetime,
        limit: int = 8,
    ) -> list[dict]:
        activity = union_all(
            *self._activity_sources(
                project_id=project_id,
                environment_id=environment_id,
                started_from=started_from,
                started_to=started_to,
                include_defects=False,
            )
        ).subquery()
        rows = self.db.execute(
            select(activity).order_by(activity.c.occurred_at.desc(), activity.c.row_id.desc()).limit(limit)
        ).all()
        return [self._activity_row_from_union(row._mapping) for row in rows]

    def activity_feed(
        self,
        *,
        project_id: int,
        current_user: User,
        environment_id: int | None = None,
        resource_type: str | None = None,
        status_value: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> DashboardActivityFeedResponse:
        self.permission_service.require_project_access(current_user, project_id)
        started_to = date_to or datetime.now()
        started_from = date_from or (started_to - timedelta(days=29))
        if started_to < started_from:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date_to 不能早于 date_from",
            )
        activity = union_all(
            *self._activity_sources(
                project_id=project_id,
                environment_id=environment_id,
                started_from=started_from,
                started_to=started_to,
                include_defects=True,
            )
        ).subquery()
        statement = select(activity)
        raw_type = self._raw_activity_type(resource_type)
        if raw_type == "__execution__":
            statement = statement.where(activity.c.type != "defect")
        elif raw_type == "__none__":
            statement = statement.where(literal(False))
        elif raw_type is not None:
            statement = statement.where(activity.c.type == raw_type)
        if status_value:
            normalized_statuses = self._raw_activity_statuses(status_value)
            statement = statement.where(func.lower(activity.c.status).in_(normalized_statuses))
        filtered = statement.subquery()
        total = int(self.db.scalar(select(func.count()).select_from(filtered)) or 0)
        rows = self.db.execute(
            select(filtered)
            .order_by(filtered.c.occurred_at.desc(), filtered.c.row_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return DashboardActivityFeedResponse(
            page=page,
            page_size=page_size,
            total=total,
            items=[self._public_activity_item(row._mapping) for row in rows],
        )

    def _activity_sources(
        self,
        *,
        project_id: int,
        environment_id: int | None,
        started_from: datetime,
        started_to: datetime,
        include_defects: bool,
    ) -> list:
        sources = [
            self._activity_source_select(
                "http",
                TestCaseExecution,
                TestCaseExecution.created_at,
                ref_column=TestCaseExecution.test_case_id,
                detail_column=TestCaseExecution.error_message,
                name_column=TestCase.name,
                join_target=TestCase,
                join_condition=TestCase.id == TestCaseExecution.test_case_id,
                project_id=project_id,
                environment_id=environment_id,
                started_from=started_from,
                started_to=started_to,
                extra_filters=[TestCaseExecution.scenario_run_id.is_(None)],
            ),
            self._activity_source_select(
                "websocket",
                WebSocketTestCaseExecution,
                WebSocketTestCaseExecution.created_at,
                ref_column=WebSocketTestCaseExecution.websocket_test_case_id,
                detail_column=WebSocketTestCaseExecution.error_message,
                name_column=WebSocketTestCase.name,
                join_target=WebSocketTestCase,
                join_condition=WebSocketTestCase.id == WebSocketTestCaseExecution.websocket_test_case_id,
                project_id=project_id,
                environment_id=environment_id,
                started_from=started_from,
                started_to=started_to,
                extra_filters=[WebSocketTestCaseExecution.scenario_run_id.is_(None)],
            ),
            self._activity_source_select(
                "scenario",
                TestScenarioRun,
                TestScenarioRun.started_at,
                ref_column=TestScenarioRun.scenario_id,
                detail_column=literal(None),
                name_column=TestScenario.name,
                join_target=TestScenario,
                join_condition=TestScenario.id == TestScenarioRun.scenario_id,
                project_id=project_id,
                environment_id=environment_id,
                started_from=started_from,
                started_to=started_to,
                extra_filters=[TestScenarioRun.plan_run_id.is_(None)],
            ),
            self._activity_source_select(
                "plan",
                TestPlanRun,
                TestPlanRun.started_at,
                ref_column=TestPlanRun.plan_id,
                detail_column=literal(None),
                name_column=TestPlanRun.plan_name,
                passed_count_column=TestPlanRun.passed_count,
                target_count_column=TestPlanRun.target_count,
                project_id=project_id,
                environment_id=environment_id,
                started_from=started_from,
                started_to=started_to,
                extra_filters=[TestPlanRun.is_deleted.is_(False)],
            ),
            self._activity_source_select(
                "flow",
                VisualFlowExecution,
                VisualFlowExecution.started_at,
                ref_column=VisualFlowExecution.flow_id,
                detail_column=literal(None),
                name_column=VisualFlow.name,
                join_target=VisualFlow,
                join_condition=VisualFlow.id == VisualFlowExecution.flow_id,
                project_id=project_id,
                environment_id=environment_id,
                started_from=started_from,
                started_to=started_to,
            ),
        ]
        if include_defects:
            sources.append(
                self._activity_source_select(
                    "defect",
                    Defect,
                    Defect.updated_at,
                    ref_column=Defect.id,
                    detail_column=literal(None),
                    name_column=Defect.title,
                    project_id=project_id,
                    environment_id=None,
                    started_from=started_from,
                    started_to=started_to,
                )
            )
        return sources

    def _activity_source_select(
        self,
        source_type: str,
        model,
        time_column,
        *,
        ref_column,
        detail_column,
        project_id: int,
        environment_id: int | None,
        started_from: datetime,
        started_to: datetime,
        name_column=None,
        join_target=None,
        join_condition=None,
        passed_count_column=None,
        target_count_column=None,
        extra_filters: list | None = None,
    ):
        statement = select(
            literal(source_type).label("type"),
            model.id.label("row_id"),
            ref_column.label("ref_id"),
            (name_column if name_column is not None else literal(None)).label("name"),
            model.status.label("status"),
            time_column.label("occurred_at"),
            detail_column.label("detail"),
            (passed_count_column if passed_count_column is not None else literal(None)).label("passed_count"),
            (target_count_column if target_count_column is not None else literal(None)).label("target_count"),
        ).select_from(model)
        if join_target is not None and join_condition is not None:
            statement = statement.outerjoin(join_target, join_condition)
        statement = statement.where(
            model.project_id == project_id,
            time_column >= started_from,
            time_column <= started_to,
        )
        env_filter = self._env_filter(model, environment_id)
        if env_filter is not None:
            statement = statement.where(env_filter)
        for condition in extra_filters or []:
            statement = statement.where(condition)
        return statement

    def _activity_row_from_union(self, row) -> dict:
        source_type = row["type"]
        ref_id = row["ref_id"] or row["row_id"]
        if source_type == "http":
            name = row["name"] or f"HTTP 用例 {ref_id}"
            detail = row["detail"] or "接口用例执行完成"
        elif source_type == "websocket":
            name = row["name"] or f"WebSocket 用例 {ref_id}"
            detail = row["detail"] or "WebSocket 用例执行完成"
        elif source_type == "scenario":
            name = row["name"] or f"场景 {ref_id}"
            detail = f"场景执行状态：{self._activity_status_label(row['status'])}"
        elif source_type == "flow":
            name = row["name"] or f"Flow {ref_id}"
            detail = f"Flow 执行状态：{self._activity_status_label(row['status'])}"
        elif source_type == "defect":
            name = row["name"] or f"缺陷 {ref_id}"
            detail = f"缺陷状态：{row['status']}"
        else:
            name = row["name"] or f"计划 {ref_id}"
            detail = f"计划目标 {row['passed_count'] or 0}/{row['target_count'] or 0} 通过"
        resource_type = self._resource_type(source_type)
        is_failure = str(row["status"] or "").strip().lower() in self.FAILED_STATUSES
        if source_type == "defect":
            action = DashboardAction(
                code="view_defect",
                label="查看缺陷",
                resource_type="defect",
                resource_id=ref_id,
            )
            event_type = "defect.updated"
            run_id = None
            title = f"缺陷更新：{name}"
        else:
            action = DashboardAction(
                code="view_failure_analysis" if is_failure else "view_execution",
                label="查看失败分析" if is_failure else "查看执行详情",
                resource_type="execution",
                resource_id=row["row_id"],
                params={"execution_type": source_type},
            )
            event_type = f"execution.{self._public_activity_status(row['status']) or 'unknown'}"
            run_id = row["row_id"]
            title = f"{name} 执行{self._activity_status_label(row['status'])}"
        return {
            "id": f"activity-{source_type}-{row['row_id']}",
            "event_type": event_type,
            "type": resource_type,
            "resource_id": ref_id,
            "run_id": run_id,
            "name": name,
            "status": row["status"],
            "occurred_at": row["occurred_at"],
            "title": title,
            "detail": detail,
            "action": action,
        }

    @staticmethod
    def _resource_type(source_type: str) -> str:
        return {
            "http": "http_test_case",
            "websocket": "websocket_test_case",
            "scenario": "scenario",
            "flow": "flow",
            "plan": "test_plan",
            "defect": "defect",
        }[source_type]

    @staticmethod
    def _raw_activity_type(resource_type: str | None) -> str | None:
        if resource_type is None:
            return None
        normalized = resource_type.strip().lower()
        mapping = {
            "http_test_case": "http",
            "websocket_test_case": "websocket",
            "scenario": "scenario",
            "flow": "flow",
            "test_plan": "plan",
            "defect": "defect",
            "execution": "__execution__",
            "system_test_case": "__none__",
        }
        if normalized not in mapping:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="不支持的 resource_type",
            )
        return mapping[normalized]

    def _public_activity_item(self, row) -> DashboardActivityFeedItem:
        mapped = self._activity_row_from_union(row)
        return DashboardActivityFeedItem(
            id=mapped["id"],
            event_type=mapped["event_type"],
            occurred_at=mapped["occurred_at"],
            resource_type=mapped["type"],
            resource_id=mapped["resource_id"],
            resource_name=mapped["name"],
            run_id=mapped["run_id"],
            status=(None if mapped["type"] == "defect" else self._public_activity_status(mapped["status"])),
            title=mapped["title"],
            detail=mapped["detail"],
            action=mapped["action"],
        )

    @staticmethod
    def _public_activity_status(value: str | None) -> str | None:
        normalized = str(value or "").strip().lower()
        if normalized in {"passed", "success", "completed"}:
            return "passed"
        if normalized in {"failed", "failure", "error"}:
            return "failed"
        if normalized in {"queued", "pending"}:
            return "queued"
        if normalized in {"running", "cancelled", "timeout"}:
            return normalized
        return None

    @staticmethod
    def _raw_activity_statuses(value: str) -> tuple[str, ...]:
        normalized = value.strip().lower()
        mapping = {
            "queued": ("queued", "pending"),
            "running": ("running",),
            "passed": ("passed", "success", "completed"),
            "failed": ("failed", "failure", "error"),
            "cancelled": ("cancelled",),
            "timeout": ("timeout",),
        }
        if normalized not in mapping:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="不支持的 status",
            )
        return mapping[normalized]

    def insight_detail(
        self,
        *,
        insight_type: str,
        project_id: int,
        current_user: User,
        environment_id: int | None,
        range_value: str,
        page: int = 1,
        page_size: int = 20,
    ) -> DashboardInsightDetailResponse:
        allowed = {
            "risk-analysis",
            "automation-efficiency",
            "health-profile",
            "defect-prediction",
        }
        if insight_type not in allowed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="洞察类型不存在")
        overview = self.quality_overview(
            project_id=project_id,
            current_user=current_user,
            environment_id=environment_id,
            range_value=range_value,
            version=None,
        )
        generated_at = datetime.now()
        if insight_type == "defect-prediction":
            return DashboardInsightDetailResponse(
                insight_type="defect-prediction",
                available=False,
                generated_at=generated_at,
                summary=DashboardInsightSummary(
                    title="缺陷预测暂不可用",
                    description="当前系统尚未部署经过历史数据校准和效果验证的缺陷预测模型。",
                ),
            )

        if insight_type == "health-profile":
            dimensions = overview.health_profile.dimensions
            return DashboardInsightDetailResponse(
                insight_type="health-profile",
                available=True,
                generated_at=generated_at,
                summary=DashboardInsightSummary(
                    title="质量健康画像",
                    description="基于当前筛选范围内的执行、缺陷与自动化资产事实计算。",
                    score=overview.health_profile.score,
                    level=self._score_level(overview.health_profile.score),
                ),
                metrics=[
                    DashboardInsightMetric(
                        key=f"health_{index}",
                        label=dimension.label,
                        value=dimension.value,
                        unit="percent",
                    )
                    for index, dimension in enumerate(dimensions, start=1)
                ],
            )

        if insight_type == "automation-efficiency":
            items = overview.automation_efficiency
            average = round(sum(item.percent for item in items) / len(items), 2) if items else 0.0
            return DashboardInsightDetailResponse(
                insight_type="automation-efficiency",
                available=True,
                generated_at=generated_at,
                summary=DashboardInsightSummary(
                    title="自动化效率",
                    description="覆盖率只使用已保存的接口用例与场景编排资产计算。",
                    score=average,
                    level=self._score_level(average),
                ),
                metrics=[
                    DashboardInsightMetric(
                        key=f"automation_{index}",
                        label=item.label,
                        value=item.percent,
                        unit="percent",
                    )
                    for index, item in enumerate(items, start=1)
                ],
            )

        range_start = self._range_start(reference_time=generated_at, range_value=range_value)
        activity = union_all(
            *self._activity_sources(
                project_id=project_id,
                environment_id=environment_id,
                started_from=range_start,
                started_to=generated_at,
                include_defects=True,
            )
        ).subquery()
        risk_condition = or_(
            activity.c.type == "defect",
            func.lower(activity.c.status).in_(tuple(self.FAILED_STATUSES)),
        )
        high_count = int(
            self.db.scalar(select(func.count()).select_from(activity).where(risk_condition)) or 0
        )
        risk_rows = self.db.execute(
            select(activity)
            .where(risk_condition)
            .order_by(activity.c.occurred_at.desc(), activity.c.row_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        paged = [self._public_activity_item(row._mapping) for row in risk_rows]
        score = max(0.0, 100.0 - high_count * 8)
        return DashboardInsightDetailResponse(
            insight_type="risk-analysis",
            available=True,
            generated_at=generated_at,
            summary=DashboardInsightSummary(
                title="质量风险明细",
                description="风险项来自失败执行和当前缺陷，不包含推测性事件。",
                score=score,
                level="high" if high_count >= 5 else "medium" if high_count else "low",
            ),
            metrics=[
                DashboardInsightMetric(key="risk_count", label="风险项", value=high_count),
            ],
            items=[
                DashboardInsightItem(
                    id=item.id,
                    title=item.title,
                    description=item.detail,
                    level="high" if item.resource_type == "defect" else "medium",
                    resource_type=item.resource_type,
                    resource_id=item.resource_id,
                    action=item.action,
                )
                for item in paged
            ],
            page=page,
            page_size=page_size,
            total=high_count,
        )

    @staticmethod
    def _score_level(score: float) -> str:
        if score < 60:
            return "high"
        if score < 80:
            return "medium"
        return "low"

    def _execution_rows(
        self,
        *,
        project_id: int,
        environment_id: int | None,
        started_from: datetime | None,
        started_to: datetime | None,
    ) -> list[dict]:
        rows: list[dict] = []
        rows.extend(self._http_execution_rows(project_id, environment_id, started_from, started_to))
        rows.extend(self._websocket_execution_rows(project_id, environment_id, started_from, started_to))
        rows.extend(self._scenario_execution_rows(project_id, environment_id, started_from, started_to))
        rows.extend(self._plan_execution_rows(project_id, environment_id, started_from, started_to))
        return sorted(rows, key=lambda row: row["occurred_at"] or datetime.min, reverse=True)

    def _http_execution_rows(self, project_id, environment_id, started_from, started_to, limit: int | None = None) -> list[dict]:
        query = self.db.query(TestCaseExecution).filter(TestCaseExecution.project_id == project_id)
        if environment_id is not None:
            query = query.filter(TestCaseExecution.environment_id == environment_id)
        if started_from is not None:
            query = query.filter(TestCaseExecution.created_at >= started_from)
        if started_to is not None:
            query = query.filter(TestCaseExecution.created_at <= started_to)
        query = query.order_by(TestCaseExecution.created_at.desc())
        if limit is not None:
            query = query.limit(limit)
        return [
            {
                "type": "http",
                "name": f"HTTP 用例 {row.test_case_id or row.id}",
                "status": row.status,
                "occurred_at": row.created_at,
                "detail": row.error_message or "接口用例执行完成",
            }
            for row in query.all()
        ]

    def _websocket_execution_rows(self, project_id, environment_id, started_from, started_to, limit: int | None = None) -> list[dict]:
        query = self.db.query(WebSocketTestCaseExecution).filter(WebSocketTestCaseExecution.project_id == project_id)
        if environment_id is not None:
            query = query.filter(WebSocketTestCaseExecution.environment_id == environment_id)
        if started_from is not None:
            query = query.filter(WebSocketTestCaseExecution.created_at >= started_from)
        if started_to is not None:
            query = query.filter(WebSocketTestCaseExecution.created_at <= started_to)
        query = query.order_by(WebSocketTestCaseExecution.created_at.desc())
        if limit is not None:
            query = query.limit(limit)
        return [
            {
                "type": "websocket",
                "name": f"WebSocket 用例 {row.websocket_test_case_id or row.id}",
                "status": row.status,
                "occurred_at": row.created_at,
                "detail": row.error_message or "WebSocket 用例执行完成",
            }
            for row in query.all()
        ]

    def _scenario_execution_rows(self, project_id, environment_id, started_from, started_to, limit: int | None = None) -> list[dict]:
        query = self.db.query(TestScenarioRun).filter(TestScenarioRun.project_id == project_id)
        if environment_id is not None:
            query = query.filter(TestScenarioRun.environment_id == environment_id)
        if started_from is not None:
            query = query.filter(TestScenarioRun.started_at >= started_from)
        if started_to is not None:
            query = query.filter(TestScenarioRun.started_at <= started_to)
        query = query.order_by(TestScenarioRun.started_at.desc())
        if limit is not None:
            query = query.limit(limit)
        return [
            {
                "type": "scenario",
                "name": self._scenario_name(row),
                "status": row.status,
                "occurred_at": row.started_at,
                "detail": f"场景执行状态：{row.status}",
            }
            for row in query.all()
        ]

    def _plan_execution_rows(self, project_id, environment_id, started_from, started_to, limit: int | None = None) -> list[dict]:
        query = self.db.query(TestPlanRun).filter(
            TestPlanRun.project_id == project_id,
            TestPlanRun.is_deleted.is_(False),
        )
        if environment_id is not None:
            query = query.filter(TestPlanRun.environment_id == environment_id)
        if started_from is not None:
            query = query.filter(TestPlanRun.started_at >= started_from)
        if started_to is not None:
            query = query.filter(TestPlanRun.started_at <= started_to)
        query = query.order_by(TestPlanRun.started_at.desc())
        if limit is not None:
            query = query.limit(limit)
        return [
            {
                "type": "plan",
                "name": row.plan_name,
                "status": row.status,
                "occurred_at": row.started_at,
                "detail": f"计划目标 {row.passed_count}/{row.target_count} 通过",
            }
            for row in query.all()
        ]

    def _open_defect_summary(self, project_id: int) -> tuple[int, list[Defect]]:
        rows = self.db.execute(
            select(
                Defect,
                func.count().over().label("open_count"),
            )
            .where(
                Defect.project_id == project_id,
                ~Defect.status.in_(self.CLOSED_DEFECT_STATUSES),
            )
            .order_by(Defect.updated_at.desc())
            .limit(3)
        ).all()
        if not rows:
            return 0, []
        return int(rows[0].open_count or 0), [row.Defect for row in rows]

    def _kpis(
        self,
        *,
        execution_total: int,
        passed_count: int,
        failed_count: int,
        pass_rate: float,
        http_total: int,
        websocket_total: int,
        scenario_total: int,
        plan_total: int,
        open_defect_count: int,
    ) -> list[DashboardKPI]:
        asset_total = http_total + websocket_total + scenario_total + plan_total
        return [
            DashboardKPI(
                key="execution_total",
                label="执行次数",
                value=execution_total,
                trend="up" if execution_total else "flat",
                breakdown=[
                    DashboardKPIBreakdown(label="通过", value=passed_count),
                    DashboardKPIBreakdown(label="失败", value=failed_count),
                ],
            ),
            DashboardKPI(
                key="pass_rate",
                label="通过率",
                value=pass_rate,
                delta="本周期",
                trend="up" if pass_rate >= 90 else "down",
            ),
            DashboardKPI(key="test_assets", label="测试资产", value=asset_total),
            DashboardKPI(
                key="defect_count",
                label="待处理缺陷",
                value=open_defect_count,
                trend="down" if open_defect_count == 0 else "up",
            ),
        ]

    def _risk_matrix(self, *, failed_count: int, open_defect_count: int) -> list[DashboardRiskMatrixItem]:
        level = "high" if failed_count + open_defect_count >= 5 else "medium" if failed_count or open_defect_count else "stable"
        return [
            DashboardRiskMatrixItem(
                module="企业核心链路",
                api=min(100, failed_count * 25),
                data=min(100, open_defect_count * 20),
                environment=min(100, failed_count * 15),
                level=level,
            )
        ]

    def _automation_efficiency(self, *, http_total: int, websocket_total: int, scenario_total: int) -> list[DashboardAutomationEfficiencyItem]:
        total_cases = http_total + websocket_total
        scenario_percent = self._automation_percent(http_total, websocket_total, scenario_total)
        return [
            DashboardAutomationEfficiencyItem(label="接口自动化", percent=100 if total_cases else 0, saved_hours=0),
            DashboardAutomationEfficiencyItem(label="场景编排", percent=scenario_percent, saved_hours=0),
        ]

    def _automation_percent(self, http_total: int, websocket_total: int, scenario_total: int) -> int:
        total_cases = http_total + websocket_total
        if not total_cases:
            return 0
        return min(100, int(round(scenario_total * 100 / total_cases)))

    def _defect_predictions(self, *, open_defect_count: int, failed_count: int) -> list[DashboardDefectPrediction]:
        # No calibrated prediction model is currently available. Returning no
        # prediction is more honest than presenting a hand-written coefficient
        # as a probability.
        return []

    def _ai_recommendations(
        self,
        *,
        failed_count: int,
        open_defect_count: int,
        pass_rate: float,
        execution_rows: list[dict],
        open_defects: list[Defect],
    ) -> list[DashboardAIRecommendation]:
        if failed_count:
            failed_row = next(
                (
                    row for row in execution_rows
                    if str(row.get("status") or "").strip().lower() in self.FAILED_STATUSES
                ),
                None,
            )
            return [
                DashboardAIRecommendation(
                    id="quality-failed-executions",
                    type="failure_analysis",
                    priority="P0",
                    title="优先处理失败链路",
                    summary=f"当前范围内有 {failed_count} 次失败执行，建议先查看失败聚类和最近运行快照。",
                    recommendation="从最近失败执行开始核对请求、响应、断言与环境快照，再决定是否发起定向回归。",
                    confidence_score=95,
                    risk_level="high",
                    action=failed_row.get("action") if failed_row else None,
                )
            ]
        if open_defect_count:
            defect = open_defects[0] if open_defects else None
            return [
                DashboardAIRecommendation(
                    id="quality-open-defects",
                    type="defect_follow_up",
                    priority="P1",
                    title="推进缺陷关闭",
                    summary=f"当前仍有 {open_defect_count} 个待处理缺陷。",
                    recommendation="优先核对高紧急度缺陷的最新状态与关联执行证据。",
                    confidence_score=100,
                    risk_level="medium",
                    action=(
                        DashboardAction(
                            code="view_defect",
                            label="查看缺陷",
                            resource_type="defect",
                            resource_id=defect.id,
                        )
                        if defect else None
                    ),
                )
            ]
        return [
            DashboardAIRecommendation(
                id="quality-stable-regression",
                type="regression",
                priority="P2",
                title="保持稳定回归",
                summary=f"当前通过率 {pass_rate}%，建议继续维持核心场景每日回归。",
                recommendation="保持现有回归节奏，并在资产或环境变化后执行增量回归。",
                confidence_score=90,
                risk_level="low",
                action=None,
            )
        ]

    def _activity_feed(self, *, execution_rows: list[dict], open_defects: list[Defect]) -> list[DashboardActivityItem]:
        items = [DashboardActivityItem(**row) for row in execution_rows[:5]]
        items.extend([
            DashboardActivityItem(
                id=f"activity-defect-{defect.id}",
                occurred_at=defect.updated_at or defect.created_at,
                event_type="defect.updated",
                type="defect",
                resource_id=defect.id,
                name=defect.title,
                status=defect.status,
                title=f"缺陷待处理：{defect.title}",
                detail=f"状态 {defect.status}，紧急程度 {defect.urgency}",
                action=DashboardAction(
                    code="view_defect",
                    label="查看缺陷",
                    resource_type="defect",
                    resource_id=defect.id,
                ),
            )
            for defect in open_defects[:3]
        ])
        return sorted(items, key=lambda item: item.occurred_at, reverse=True)[:8]

    def _activity_status_label(self, status: str | None) -> str:
        normalized = str(status or "").strip().lower()
        return self.ACTIVITY_STATUS_LABELS.get(normalized, str(status or "未知"))

    def _hero_title(self, health_score: float) -> str:
        if health_score >= 90:
            return "质量状态稳定"
        if health_score >= 70:
            return "质量风险可控"
        return "存在高优先级质量风险"

    def _scenario_name(self, row: TestScenarioRun) -> str:
        if isinstance(row.scenario_snapshot, dict):
            name = row.scenario_snapshot.get("name")
            if isinstance(name, str) and name.strip():
                return name
        return f"场景 {row.scenario_id or row.id}"
