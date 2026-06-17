import html
import json
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.models.user import User
from app.repositories.test_report_repository import TestReportRepository
from app.schemas.test_report import (
    ReportSourceType,
    TestReportDetail,
    TestReportPage,
    TestReportSummary,
    TestReportTrend,
    TestReportTrendPoint,
)
from app.services.permission_service import PermissionService


class TestReportService:
    def __init__(self, db: Session):
        self.repository = TestReportRepository(db)
        self.permission_service = PermissionService(db)

    def _require_view(self, current_user: User, project_id: int) -> None:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_REPORT.value,
        )

    @staticmethod
    def _duration_ms(started_at: datetime | None, finished_at: datetime | None) -> int | None:
        if started_at is None or finished_at is None:
            return None
        return max(int((finished_at - started_at).total_seconds() * 1000), 0)

    @staticmethod
    def _summary(values: dict[str, Any]) -> TestReportSummary:
        total = int(values.get("total_count") or 0)
        passed = int(values.get("passed_count") or 0)
        failed = int(values.get("failed_count") or 0)
        skipped = max(total - passed - failed, 0)
        duration_ms = values.get("duration_ms")
        if duration_ms is None:
            duration_ms = TestReportService._duration_ms(
                values.get("started_at"), values.get("finished_at")
            )
        return TestReportSummary(
            id=f"{values['source_type']}:{values['source_id']}",
            source_type=values["source_type"],
            source_id=values["source_id"],
            project_id=values["project_id"],
            name=values["name"],
            status=values["status"],
            trigger_type=values["trigger_type"],
            trigger_user_id=values["trigger_user_id"],
            environment_id=values.get("environment_id"),
            environment_name=values.get("environment_name"),
            total_count=total,
            passed_count=passed,
            failed_count=failed,
            skipped_count=skipped,
            pass_rate=round(passed * 100 / total, 2) if total else 0.0,
            duration_ms=duration_ms,
            started_at=values.get("started_at"),
            finished_at=values.get("finished_at"),
            created_at=values["created_at"],
        )

    def list_reports(
        self,
        *,
        project_id: int,
        current_user: User,
        source_type: ReportSourceType | None,
        status_filter: str | None,
        environment_id: int | None,
        started_from: datetime | None,
        started_to: datetime | None,
        page: int,
        page_size: int,
    ) -> TestReportPage:
        self._require_view(current_user, project_id)
        if started_from is not None and started_to is not None and started_from > started_to:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="started_from must be earlier than or equal to started_to",
            )
        rows, total = self.repository.list_reports(
            project_id=project_id,
            source_type=source_type,
            status=status_filter,
            environment_id=environment_id,
            started_from=started_from,
            started_to=started_to,
            page=page,
            page_size=page_size,
        )
        return TestReportPage(
            items=[self._summary(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    def _columns(model: Any) -> dict[str, Any]:
        return {
            column.name: getattr(model, column.name)
            for column in model.__table__.columns
        }

    def get_report(
        self,
        *,
        project_id: int,
        source_type: ReportSourceType,
        source_id: int,
        current_user: User,
    ) -> TestReportDetail:
        self._require_view(current_user, project_id)
        report = getattr(self, f"_get_{source_type}_report")(
            project_id=project_id,
            source_id=source_id,
        )
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="test report source not found",
            )
        return report

    def get_trends(
        self,
        *,
        project_id: int,
        current_user: User,
        source_type: ReportSourceType | None,
        environment_id: int | None,
        started_from: date | None,
        started_to: date | None,
    ) -> TestReportTrend:
        self._require_view(current_user, project_id)
        end_date = started_to or date.today()
        start_date = started_from or end_date - timedelta(days=29)
        if start_date > end_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="started_from must be earlier than or equal to started_to",
            )
        if end_date - start_date > timedelta(days=365):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="trend range cannot exceed 366 days",
            )
        rows = self.repository.get_daily_trends(
            project_id=project_id,
            source_type=source_type,
            environment_id=environment_id,
            started_from=start_date,
            started_to=end_date,
        )
        points = []
        for row in rows:
            total = int(row.get("total_count") or 0)
            passed = int(row.get("passed_count") or 0)
            failed = int(row.get("failed_count") or 0)
            points.append(TestReportTrendPoint(
                date=row["date"],
                total_count=total,
                passed_count=passed,
                failed_count=failed,
                other_count=max(total - passed - failed, 0),
                pass_rate=round(passed * 100 / total, 2) if total else 0.0,
                avg_duration_ms=row.get("avg_duration_ms"),
            ))
        return TestReportTrend(
            started_from=start_date,
            started_to=end_date,
            points=points,
        )

    def _get_plan_report(self, *, project_id: int, source_id: int):
        run = self.repository.get_plan_run(project_id=project_id, source_id=source_id)
        if run is None:
            return None
        scenario_runs = self.repository.list_plan_scenario_runs(run.id)
        runs_by_id = {item.id: self._columns(item) for item in scenario_runs}
        items = []
        for target in run.target_results or []:
            item = dict(target)
            item["scenario_runs"] = [
                runs_by_id[run_id]
                for run_id in target.get("scenario_run_ids", [])
                if run_id in runs_by_id
            ]
            items.append(item)
        summary = self._summary({
            "source_type": "plan",
            "source_id": run.id,
            "project_id": run.project_id,
            "name": run.plan_name,
            "status": run.status,
            "trigger_type": run.trigger,
            "trigger_user_id": run.operator_id,
            "environment_id": run.environment_id,
            "environment_name": run.environment_name,
            "total_count": run.target_count,
            "passed_count": run.passed_count,
            "failed_count": run.failed_count,
            "duration_ms": run.duration_ms,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "created_at": run.created_at,
        })
        record_count = len(scenario_runs)
        passed_records = sum(item.status == "passed" for item in scenario_runs)
        metrics = {
            "target_count": run.target_count,
            "passed_target_count": run.passed_count,
            "failed_target_count": run.failed_count,
            "scenario_run_count": record_count,
            "passed_scenario_run_count": passed_records,
            "failed_scenario_run_count": record_count - passed_records,
            "pass_rate": summary.pass_rate,
        }
        return TestReportDetail(
            summary=summary,
            metrics=metrics,
            items=items,
            source_snapshot=run.plan_snapshot,
        )

    def _get_flow_report(self, *, project_id: int, source_id: int):
        row = self.repository.get_flow_execution(project_id=project_id, source_id=source_id)
        if row is None:
            return None
        execution, flow_name = row
        nodes = self.repository.list_flow_nodes(execution.id)
        total = len(nodes)
        passed = sum(node.status == "passed" for node in nodes)
        failed = sum(node.status == "failed" for node in nodes)
        summary = self._summary({
            "source_type": "flow",
            "source_id": execution.id,
            "project_id": execution.project_id,
            "name": flow_name or "Deleted flow",
            "status": execution.status,
            "trigger_type": execution.trigger_type,
            "trigger_user_id": execution.trigger_user_id,
            "environment_id": execution.environment_id,
            "environment_name": None,
            "total_count": total,
            "passed_count": passed,
            "failed_count": failed,
            "duration_ms": None,
            "started_at": execution.started_at,
            "finished_at": execution.finished_at,
            "created_at": execution.created_at,
        })
        return TestReportDetail(
            summary=summary,
            metrics={
                "node_count": total,
                "passed_node_count": passed,
                "failed_node_count": failed,
                "skipped_node_count": summary.skipped_count,
                "pass_rate": summary.pass_rate,
            },
            items=[self._columns(node) for node in nodes],
            source_snapshot=execution.context_snapshot,
        )

    @staticmethod
    def render_html(report: TestReportDetail) -> str:
        summary = report.summary
        rows = []
        for index, item in enumerate(report.items, start=1):
            name = item.get("name") or item.get("node_id") or item.get("id") or f"Item {index}"
            item_status = item.get("status", "unknown")
            duration = item.get("duration_ms")
            details = html.escape(
                json.dumps(jsonable_encoder(item), ensure_ascii=False, indent=2)
            )
            rows.append(
                "<tr>"
                f"<td>{index}</td><td>{html.escape(str(name))}</td>"
                f"<td>{html.escape(str(item_status))}</td>"
                f"<td>{html.escape(str(duration if duration is not None else '-'))}</td>"
                f"<td><details><summary>View</summary><pre>{details}</pre></details></td>"
                "</tr>"
            )
        metrics = "".join(
            f"<div class='metric'><strong>{html.escape(str(value))}</strong>"
            f"<span>{html.escape(key.replace('_', ' '))}</span></div>"
            for key, value in report.metrics.items()
        )
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(summary.name)} - Test Report</title>
<style>
body{{font-family:Arial,sans-serif;margin:0;background:#f5f7fb;color:#172033}}
main{{max-width:1200px;margin:32px auto;padding:0 24px}}
h1{{margin-bottom:4px}} .meta{{color:#5b6475;margin-bottom:24px}}
.metrics{{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px}}
.metric{{background:white;border:1px solid #dde2ea;border-radius:8px;padding:14px 18px;min-width:130px}}
.metric strong,.metric span{{display:block}} .metric strong{{font-size:22px}}
.metric span{{font-size:12px;color:#687386;margin-top:4px}}
table{{width:100%;border-collapse:collapse;background:white}}
th,td{{padding:12px;border:1px solid #dde2ea;text-align:left;vertical-align:top}}
th{{background:#eef2f7}} pre{{white-space:pre-wrap;max-width:700px;overflow:auto}}
</style>
</head>
<body><main>
<h1>{html.escape(summary.name)}</h1>
<div class="meta">{html.escape(summary.source_type)} report #{summary.source_id} |
Status: {html.escape(summary.status)} | Pass rate: {summary.pass_rate}%</div>
<section class="metrics">{metrics}</section>
<table><thead><tr><th>#</th><th>Name</th><th>Status</th><th>Duration ms</th><th>Details</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</main></body></html>"""
