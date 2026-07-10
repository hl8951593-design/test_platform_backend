import html
import json
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.models.defect import Defect
from app.models.test_case import TestCase, TestCaseExecution
from app.models.user import User
from app.repositories.test_report_repository import TestReportRepository
from app.schemas.test_report import (
    ReportAIRecommendation,
    ReportFailureCluster,
    ReportIntelligenceOverview,
    ReportIntelligenceSummary,
    ReportRiskIndicator,
    ReportSourceType,
    ReportSlowTest,
    ReportStabilityHeatmapRow,
    ReportTrendValue,
    TestReportDetail,
    TestReportPage,
    TestReportSummary,
    TestReportTrend,
    TestReportTrendPoint,
)
from app.services.permission_service import PermissionService


class TestReportService:
    SLOW_THRESHOLD_MS = 3000

    def __init__(self, db: Session):
        self.db = db
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

    def get_intelligence_overview(
        self,
        *,
        project_id: int,
        current_user: User,
        environment_id: int | None,
        range_value: str,
    ) -> ReportIntelligenceOverview:
        self._require_view(current_user, project_id)
        days = self._range_days(range_value)
        reference_time = self._latest_report_reference_time(project_id=project_id, environment_id=environment_id)
        started_from = reference_time - timedelta(days=days - 1)
        comparison_reports = self.repository.list_report_comparison_periods(
            project_id=project_id,
            environment_id=environment_id,
            current_from=started_from,
            current_to=reference_time + timedelta(days=1),
            previous_from=started_from - timedelta(days=days),
            previous_to=started_from,
            page_size=1000,
        )
        summaries = [
            self._summary(row)
            for row in comparison_reports
            if row["comparison_period"] == "current"
        ]
        total = sum(item.total_count for item in summaries)
        passed = sum(item.passed_count for item in summaries)
        failed = sum(item.failed_count for item in summaries)
        pass_rate = round(passed * 100 / total, 2) if total else 0.0
        previous_summaries = [
            self._summary(row)
            for row in comparison_reports
            if row["comparison_period"] == "previous"
        ]
        previous_total = sum(item.total_count for item in previous_summaries)
        previous_passed = sum(item.passed_count for item in previous_summaries)
        previous_rate = round(previous_passed * 100 / previous_total, 2) if previous_total else pass_rate
        slow_tests = self._slow_tests(
            project_id=project_id,
            environment_id=environment_id,
            started_from=started_from,
            started_to=reference_time + timedelta(days=1),
        )
        failure_clusters = self._failure_clusters(summaries, failed)
        p0_count = sum(1 for item in failure_clusters if item.priority == "P0")
        recommendations = self._report_recommendations(failure_clusters=failure_clusters, slow_tests=slow_tests)
        stability_score = max(round(pass_rate - len(failure_clusters) * 2 - len(slow_tests), 2), 0.0)
        return ReportIntelligenceOverview(
            generated_at=datetime.now(),
            summary=ReportIntelligenceSummary(
                pass_rate=pass_rate,
                pass_rate_delta=round(pass_rate - previous_rate, 2),
                failure_cluster_count=len(failure_clusters),
                p0_cluster_count=p0_count,
                stability_score=stability_score,
                slow_test_count=len(slow_tests),
                slow_threshold_ms=self.SLOW_THRESHOLD_MS,
                ai_recommendation_count=len(recommendations),
            ),
            pass_rate_trend=self._pass_rate_trend(summaries, days=days),
            risk_indicators=self._risk_indicators(
                failure_clusters=failure_clusters,
                slow_tests=slow_tests,
                open_defects=self._open_defect_count(project_id),
            ),
            failure_clusters=failure_clusters,
            slow_tests=slow_tests,
            stability_heatmap=self._stability_heatmap(summaries, days=7),
            ai_recommendations=recommendations,
        )

    def _range_days(self, range_value: str) -> int:
        if range_value == "today":
            return 1
        if range_value == "30d":
            return 30
        return 7

    def _latest_report_reference_time(self, *, project_id: int, environment_id: int | None) -> datetime:
        reference_time = self.repository.get_latest_report_reference_time(
            project_id=project_id,
            environment_id=environment_id,
        )
        if reference_time is not None:
            return reference_time
        latest_case_execution = (
            self.db.query(TestCaseExecution)
            .filter(TestCaseExecution.project_id == project_id)
            .order_by(TestCaseExecution.created_at.desc())
            .first()
        )
        if latest_case_execution is not None:
            return latest_case_execution.created_at
        return datetime.now()

    def _slow_tests(
        self,
        *,
        project_id: int,
        environment_id: int | None,
        started_from: datetime,
        started_to: datetime,
    ) -> list[ReportSlowTest]:
        query = (
            self.db.query(TestCaseExecution, TestCase, User)
            .outerjoin(TestCase, TestCase.id == TestCaseExecution.test_case_id)
            .outerjoin(User, User.id == TestCaseExecution.executed_by_id)
            .filter(TestCaseExecution.project_id == project_id)
            .filter(TestCaseExecution.duration_ms >= self.SLOW_THRESHOLD_MS)
            .filter(TestCaseExecution.created_at >= started_from)
            .filter(TestCaseExecution.created_at <= started_to)
        )
        if environment_id is not None:
            query = query.filter(TestCaseExecution.environment_id == environment_id)
        query = query.order_by(TestCaseExecution.duration_ms.desc()).limit(10)
        items = []
        for execution, test_case, owner in query.all():
            duration = int(execution.duration_ms or 0)
            items.append(ReportSlowTest(
                test_case_id=execution.test_case_id,
                name=(test_case.name if test_case is not None else f"执行记录 {execution.id}"),
                owner=(owner.username or owner.account if owner is not None else "未分配"),
                risk="high" if duration >= self.SLOW_THRESHOLD_MS * 2 else "medium",
                duration_ms=duration,
            ))
        return items

    def _failure_clusters(self, summaries: list[TestReportSummary], failed_count: int) -> list[ReportFailureCluster]:
        failed_items = [item for item in summaries if item.failed_count > 0 or item.status in {"failed", "timeout"}]
        clusters = [
            ReportFailureCluster(
                name=item.name,
                count=max(item.failed_count, 1),
                priority="P0" if item.failed_count or failed_count else "P1",
                confidence=min(95, 82 + max(item.failed_count, 1) * 3),
            )
            for item in failed_items[:5]
        ]
        return clusters or [
            ReportFailureCluster(name="暂无失败聚类", count=0, priority="P3", confidence=60)
        ]

    def _report_recommendations(
        self,
        *,
        failure_clusters: list[ReportFailureCluster],
        slow_tests: list[ReportSlowTest],
    ) -> list[ReportAIRecommendation]:
        recommendations: list[ReportAIRecommendation] = []
        risky_clusters = [item for item in failure_clusters if item.count > 0]
        if risky_clusters:
            recommendations.append(ReportAIRecommendation(
                id="rec-failure-cluster",
                priority="P0" if any(item.priority == "P0" for item in risky_clusters) else "P1",
                content=f"优先复核 {risky_clusters[0].name}，当前聚类失败 {risky_clusters[0].count} 次。",
                action_label="查看失败聚类",
            ))
        if slow_tests:
            recommendations.append(ReportAIRecommendation(
                id="rec-slow-tests",
                priority="P1",
                content=f"优化 {slow_tests[0].name}，当前耗时 {slow_tests[0].duration_ms}ms，超过慢用例阈值。",
                action_label="查看慢用例",
            ))
        if not recommendations:
            recommendations.append(ReportAIRecommendation(
                id="rec-quality-stable",
                priority="P2",
                content="当前报告趋势稳定，建议保持核心链路每日回归。",
                action_label="查看趋势",
            ))
        return recommendations

    def _pass_rate_trend(self, summaries: list[TestReportSummary], *, days: int) -> list[ReportTrendValue]:
        buckets: dict[date, list[TestReportSummary]] = {}
        for item in summaries:
            if item.started_at is None:
                continue
            buckets.setdefault(item.started_at.date(), []).append(item)
        ordered_days = sorted(buckets)[-max(days, 1):]
        return [
            ReportTrendValue(
                label=self._weekday_label(day),
                value=self._bucket_pass_rate(buckets[day]),
            )
            for day in ordered_days
        ] or [ReportTrendValue(label="今日", value=0)]

    def _stability_heatmap(self, summaries: list[TestReportSummary], *, days: int) -> list[ReportStabilityHeatmapRow]:
        values = [max(1, min(5, int(round(item.pass_rate / 20)))) for item in summaries[:days]]
        if not values:
            values = [5]
        while len(values) < days:
            values.append(values[-1])
        return [
            ReportStabilityHeatmapRow(module="报告稳定性", values=values[:days]),
            ReportStabilityHeatmapRow(module="执行波动", values=list(reversed(values[:days]))),
        ]

    def _risk_indicators(
        self,
        *,
        failure_clusters: list[ReportFailureCluster],
        slow_tests: list[ReportSlowTest],
        open_defects: int,
    ) -> list[ReportRiskIndicator]:
        risk_score = min(100, open_defects * 12 + sum(item.count for item in failure_clusters) * 10)
        return [
            ReportRiskIndicator(
                name="失败聚类风险",
                level="high" if risk_score >= 70 else "medium" if risk_score >= 35 else "low",
                score=risk_score,
            ),
            ReportRiskIndicator(
                name="慢用例风险",
                level="high" if len(slow_tests) >= 5 else "medium" if slow_tests else "low",
                score=min(100, len(slow_tests) * 18),
            ),
        ]

    def _open_defect_count(self, project_id: int) -> int:
        return int(
            self.db.query(Defect)
            .filter(Defect.project_id == project_id)
            .filter(~Defect.status.in_(("closed", "resolved", "done", "已关闭", "已解决")))
            .count()
        )

    def _bucket_pass_rate(self, items: list[TestReportSummary]) -> float:
        total = sum(item.total_count for item in items)
        passed = sum(item.passed_count for item in items)
        return round(passed * 100 / total, 2) if total else 0.0

    def _weekday_label(self, value: date) -> str:
        labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return labels[value.weekday()]

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
