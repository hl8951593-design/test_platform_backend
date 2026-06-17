from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, String, case, cast, func, literal, select, text, union_all
from sqlalchemy.orm import Session

from app.models.scenario import TestScenarioRun
from app.models.test_plan import TestPlanRun
from app.models.visual_flow import VisualFlow, VisualFlowExecution, VisualFlowNodeExecution


class TestReportRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _plan_select():
        return select(
            literal("plan").label("source_type"),
            TestPlanRun.id.label("source_id"),
            TestPlanRun.project_id.label("project_id"),
            TestPlanRun.plan_name.label("name"),
            TestPlanRun.status.label("status"),
            TestPlanRun.trigger.label("trigger_type"),
            TestPlanRun.operator_id.label("trigger_user_id"),
            TestPlanRun.environment_id.label("environment_id"),
            TestPlanRun.environment_name.label("environment_name"),
            TestPlanRun.target_count.label("total_count"),
            TestPlanRun.passed_count.label("passed_count"),
            TestPlanRun.failed_count.label("failed_count"),
            TestPlanRun.duration_ms.label("duration_ms"),
            TestPlanRun.started_at.label("started_at"),
            TestPlanRun.finished_at.label("finished_at"),
            TestPlanRun.created_at.label("created_at"),
        ).where(TestPlanRun.is_deleted.is_(False))

    @staticmethod
    def _flow_select():
        node_counts = select(
            VisualFlowNodeExecution.execution_id.label("execution_id"),
            func.count(VisualFlowNodeExecution.id).label("total_count"),
            func.sum(
                case((VisualFlowNodeExecution.status == "passed", 1), else_=0)
            ).label("passed_count"),
            func.sum(
                case((VisualFlowNodeExecution.status == "failed", 1), else_=0)
            ).label("failed_count"),
        ).group_by(VisualFlowNodeExecution.execution_id).subquery("flow_node_counts")

        return select(
            literal("flow").label("source_type"),
            VisualFlowExecution.id.label("source_id"),
            VisualFlowExecution.project_id.label("project_id"),
            func.coalesce(VisualFlow.name, literal("Deleted flow")).label("name"),
            VisualFlowExecution.status.label("status"),
            VisualFlowExecution.trigger_type.label("trigger_type"),
            VisualFlowExecution.trigger_user_id.label("trigger_user_id"),
            VisualFlowExecution.environment_id.label("environment_id"),
            cast(None, String(64)).label("environment_name"),
            func.coalesce(node_counts.c.total_count, 0).label("total_count"),
            func.coalesce(node_counts.c.passed_count, 0).label("passed_count"),
            func.coalesce(node_counts.c.failed_count, 0).label("failed_count"),
            cast(None, VisualFlowExecution.id.type).label("duration_ms"),
            VisualFlowExecution.started_at.label("started_at"),
            VisualFlowExecution.finished_at.label("finished_at"),
            VisualFlowExecution.created_at.label("created_at"),
        ).select_from(VisualFlowExecution).outerjoin(
            VisualFlow, VisualFlow.id == VisualFlowExecution.flow_id
        ).outerjoin(
            node_counts, node_counts.c.execution_id == VisualFlowExecution.id
        )

    def list_reports(
        self,
        *,
        project_id: int,
        source_type: str | None,
        status: str | None,
        environment_id: int | None,
        started_from: datetime | None,
        started_to: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        reports = union_all(self._plan_select(), self._flow_select()).subquery("test_reports")
        filters = [reports.c.project_id == project_id]
        if source_type is not None:
            filters.append(reports.c.source_type == source_type)
        if status is not None:
            filters.append(reports.c.status == status)
        if environment_id is not None:
            filters.append(reports.c.environment_id == environment_id)
        if started_from is not None:
            filters.append(reports.c.started_at >= started_from)
        if started_to is not None:
            filters.append(reports.c.started_at <= started_to)

        total = self.db.scalar(
            select(func.count()).select_from(reports).where(*filters)
        ) or 0
        rows = self.db.execute(
            select(reports)
            .where(*filters)
            .order_by(reports.c.started_at.desc(), reports.c.source_type, reports.c.source_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).mappings().all()
        return [dict(row) for row in rows], int(total)

    def get_daily_trends(
        self,
        *,
        project_id: int,
        source_type: str | None,
        environment_id: int | None,
        started_from: date,
        started_to: date,
    ) -> list[dict[str, Any]]:
        plan_rows = select(
            literal("plan").label("source_type"),
            TestPlanRun.project_id.label("project_id"),
            TestPlanRun.environment_id.label("environment_id"),
            TestPlanRun.status.label("status"),
            TestPlanRun.duration_ms.label("duration_ms"),
            TestPlanRun.started_at.label("started_at"),
        ).where(TestPlanRun.is_deleted.is_(False))
        flow_duration = cast(
            func.timestampdiff(
                text("MICROSECOND"),
                VisualFlowExecution.started_at,
                VisualFlowExecution.finished_at,
            ) / 1000,
            Integer,
        )
        flow_rows = select(
            literal("flow").label("source_type"),
            VisualFlowExecution.project_id.label("project_id"),
            VisualFlowExecution.environment_id.label("environment_id"),
            VisualFlowExecution.status.label("status"),
            flow_duration.label("duration_ms"),
            VisualFlowExecution.started_at.label("started_at"),
        )
        reports = union_all(plan_rows, flow_rows).subquery("report_trends")
        filters = [
            reports.c.project_id == project_id,
            reports.c.started_at >= datetime.combine(started_from, datetime.min.time()),
            reports.c.started_at < datetime.combine(started_to + timedelta(days=1), datetime.min.time()),
        ]
        if source_type is not None:
            filters.append(reports.c.source_type == source_type)
        if environment_id is not None:
            filters.append(reports.c.environment_id == environment_id)

        bucket = func.date(reports.c.started_at)
        rows = self.db.execute(
            select(
                bucket.label("date"),
                func.count().label("total_count"),
                func.sum(case((reports.c.status == "passed", 1), else_=0)).label("passed_count"),
                func.sum(
                    case((reports.c.status.in_(("failed", "timeout")), 1), else_=0)
                ).label("failed_count"),
                cast(func.avg(reports.c.duration_ms), Integer).label("avg_duration_ms"),
            )
            .where(*filters)
            .group_by(bucket)
            .order_by(bucket)
        ).mappings().all()
        return [dict(row) for row in rows]

    def get_plan_run(self, *, project_id: int, source_id: int) -> TestPlanRun | None:
        return self.db.scalar(select(TestPlanRun).where(
            TestPlanRun.id == source_id,
            TestPlanRun.project_id == project_id,
            TestPlanRun.is_deleted.is_(False),
        ))

    def list_plan_scenario_runs(self, plan_run_id: int) -> list[TestScenarioRun]:
        return list(self.db.scalars(
            select(TestScenarioRun)
            .where(TestScenarioRun.plan_run_id == plan_run_id)
            .order_by(TestScenarioRun.started_at, TestScenarioRun.id)
        ).all())

    def get_flow_execution(self, *, project_id: int, source_id: int):
        return self.db.execute(
            select(VisualFlowExecution, VisualFlow.name)
            .outerjoin(VisualFlow, VisualFlow.id == VisualFlowExecution.flow_id)
            .where(
                VisualFlowExecution.id == source_id,
                VisualFlowExecution.project_id == project_id,
            )
        ).one_or_none()

    def list_flow_nodes(self, execution_id: int) -> list[VisualFlowNodeExecution]:
        return list(self.db.scalars(
            select(VisualFlowNodeExecution)
            .where(VisualFlowNodeExecution.execution_id == execution_id)
            .order_by(VisualFlowNodeExecution.id)
        ).all())
