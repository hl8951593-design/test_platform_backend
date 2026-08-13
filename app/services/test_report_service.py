import hashlib
import hmac
import html
import json
import secrets
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session, load_only

from app.core.config import settings
from app.core.permissions import ProjectPermission
from app.core.sensitive_data import redact_sensitive_data
from app.models.defect import Defect
from app.models.test_case import TestCase, TestCaseExecution
from app.models.test_report import TestReportExport
from app.models.user import User
from app.repositories.test_report_repository import TestReportRepository
from app.schemas.test_report import (
    ReportFailureCluster,
    ReportIntelligenceOverview,
    ReportIntelligenceScope,
    ReportIntelligenceSummary,
    ReportRange,
    ReportRecommendation,
    ReportRecommendationAction,
    ReportRiskIndicator,
    ReportSlowTest,
    ReportStabilityHeatmap,
    ReportStabilityHeatmapRow,
    ReportTrendValue,
    ReportSourceType,
    SupplementCaseDraft,
    SupplementCaseDraftRequest,
    SupplementCaseDraftResult,
    TestReportDetail,
    TestReportExportRead,
    TestReportItem,
    TestReportItemDetail,
    TestReportPage,
    TestReportSourceSnapshot,
    TestReportSummary,
    TestReportTrend,
    TestReportTrendPoint,
)
from app.services.permission_service import PermissionService


class TestReportService:
    SLOW_THRESHOLD_MS = 3000
    FAILURE_STATUSES = {"failed", "error", "timeout"}
    PASSED_STATUSES = {"passed", "success", "completed"}
    ACTIVE_STATUSES = {"queued", "pending", "running"}

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
        trigger_user_id = int(values.get("trigger_user_id") or 0)
        return TestReportSummary(
            id=f"{values['source_type']}:{values['source_id']}",
            source_type=values["source_type"],
            source_id=values["source_id"],
            project_id=values["project_id"],
            name=values.get("name") or f"历史 {values['source_type']} 执行",
            status=values["status"],
            trigger_type=values.get("trigger_type") or "manual",
            trigger_user_id=trigger_user_id,
            trigger_user_name=values.get("trigger_user_name") or f"用户 {trigger_user_id}",
            user_name=values.get("trigger_user_name") or f"用户 {trigger_user_id}",
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

    def delete_report(
        self,
        *,
        project_id: int,
        source_type: ReportSourceType,
        source_id: int,
        current_user: User,
    ) -> None:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.DELETE_REPORT.value,
        )
        report_status = self.repository.get_report_status(
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
        )
        if report_status is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="测试报告不存在",
            )
        if report_status.lower() in self.ACTIVE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="报告对应执行仍在运行，不能删除",
            )
        self.repository.hide_report(
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
            deleted_by_id=current_user.id,
        )

    def get_report(
        self,
        *,
        project_id: int,
        source_type: ReportSourceType,
        source_id: int,
        current_user: User,
    ) -> TestReportDetail:
        self._require_view(current_user, project_id)
        report = self._get_report_projection(
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
        )
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="test report source not found",
            )
        return report

    def get_report_item(
        self,
        *,
        project_id: int,
        source_type: ReportSourceType,
        source_id: int,
        item_id: str,
        current_user: User,
    ) -> TestReportItemDetail:
        self._require_view(current_user, project_id)
        detail = getattr(self, f"_get_{source_type}_item_detail")(
            project_id=project_id,
            source_id=source_id,
            item_id=item_id,
        )
        if detail is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="test report item not found",
            )
        return detail

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
        range_value: ReportRange,
    ) -> ReportIntelligenceOverview:
        self._require_view(current_user, project_id)
        days = self._range_days(range_value)
        generated_at = datetime.now()
        started_from = datetime.combine(
            generated_at.date() - timedelta(days=days - 1),
            time.min,
        )
        previous_from = started_from - timedelta(days=days)
        comparison_reports = self.repository.list_report_comparison_periods(
            project_id=project_id,
            environment_id=environment_id,
            current_from=started_from,
            current_to=generated_at,
            previous_from=previous_from,
            previous_to=started_from - timedelta(microseconds=1),
            page_size=1000,
        )
        summaries = [
            self._summary(row)
            for row in comparison_reports
            if row["comparison_period"] == "current"
        ]
        previous_summaries = [
            self._summary(row)
            for row in comparison_reports
            if row["comparison_period"] == "previous"
        ]
        total = sum(item.total_count for item in summaries)
        passed = sum(item.passed_count for item in summaries)
        pass_rate = round(passed * 100 / total, 2) if total else 0.0
        previous_total = sum(item.total_count for item in previous_summaries)
        previous_passed = sum(item.passed_count for item in previous_summaries)
        previous_rate = (
            round(previous_passed * 100 / previous_total, 2)
            if previous_total
            else pass_rate
        )
        slow_tests = self._slow_tests(
            project_id=project_id,
            environment_id=environment_id,
            started_from=started_from,
            started_to=generated_at,
        )
        failure_clusters = self._failure_clusters(summaries)
        open_defects = self._open_defect_count(project_id)
        recommendations = self._report_recommendations(
            failure_clusters=failure_clusters,
            slow_tests=slow_tests,
        )
        trend = self._pass_rate_trend(
            summaries,
            started_on=started_from.date(),
            days=days,
        )
        stability_score = (
            max(round(pass_rate - len(failure_clusters) * 2 - len(slow_tests), 2), 0.0)
            if total
            else 0.0
        )
        return ReportIntelligenceOverview(
            generated_at=generated_at,
            generated_by="rules",
            scope=ReportIntelligenceScope(
                project_id=project_id,
                environment_id=environment_id,
                range=range_value,
                started_at=started_from,
                finished_at=generated_at,
            ),
            summary=ReportIntelligenceSummary(
                pass_rate=pass_rate,
                pass_rate_delta=round(pass_rate - previous_rate, 2),
                failure_cluster_count=len(failure_clusters),
                p0_cluster_count=sum(
                    1 for item in failure_clusters if item.priority == "P0"
                ),
                stability_score=stability_score,
                slow_test_count=len(slow_tests),
                slow_threshold_ms=self.SLOW_THRESHOLD_MS,
                ai_recommendation_count=len(recommendations),
            ),
            pass_rate_trend=trend,
            risk_indicators=self._risk_indicators(
                failure_clusters=failure_clusters,
                slow_tests=slow_tests,
                open_defects=open_defects,
            ),
            failure_clusters=failure_clusters,
            slow_tests=slow_tests,
            stability_heatmap=self._stability_heatmap(trend),
            recommendations=recommendations,
        )

    def create_export(
        self,
        *,
        project_id: int,
        source_type: ReportSourceType,
        source_id: int,
        current_user: User,
    ) -> TestReportExportRead:
        self.get_report(
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
            current_user=current_user,
        )
        token = secrets.token_urlsafe(32)
        export_id = f"export-{secrets.token_hex(16)}"
        expires_at = datetime.now() + timedelta(
            seconds=settings.TEST_REPORT_EXPORT_EXPIRE_SECONDS
        )
        report_export = TestReportExport(
            id=export_id,
            token_hash=self._token_hash(token),
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
            format="html",
            created_by_id=current_user.id,
            expires_at=expires_at,
        )
        self.repository.purge_stale_exports(datetime.now() - timedelta(days=1))
        self.repository.add_export(report_export)
        self.db.commit()
        return TestReportExportRead(
            export_id=export_id,
            download_url=(
                f"{settings.API_V1_PREFIX}/reports/exports/{export_id}/download"
                f"?token={quote(token)}"
            ),
            expires_at=expires_at,
        )

    def consume_export(self, *, export_id: str, token: str) -> tuple[str, str]:
        report_export = self.repository.get_export_for_update(export_id)
        if report_export is None or not hmac.compare_digest(
            report_export.token_hash,
            self._token_hash(token),
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="report export not found",
            )
        now = datetime.now()
        if report_export.consumed_at is not None:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="report export has already been downloaded",
            )
        if report_export.expires_at <= now:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="report export has expired",
            )
        report = self._get_report_projection(
            project_id=report_export.project_id,
            source_type=report_export.source_type,
            source_id=report_export.source_id,
        )
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="test report source not found",
            )
        content = self.render_html(report)
        report_export.consumed_at = now
        self.db.commit()
        filename = f"test-report-{report_export.source_type}-{report_export.source_id}.html"
        return content, filename

    def generate_supplement_case_drafts(
        self,
        *,
        source_type: ReportSourceType,
        source_id: int,
        payload: SupplementCaseDraftRequest,
        current_user: User,
    ) -> SupplementCaseDraftResult:
        report = self.get_report(
            project_id=payload.project_id,
            source_type=source_type,
            source_id=source_id,
            current_user=current_user,
        )
        requested = set(payload.item_ids)
        if payload.scope == "selected" and not requested:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="item_ids is required when scope is selected",
            )
        candidates = [
            item
            for item in report.items
            if (not requested or item.id in requested)
            and (
                payload.scope == "all"
                or payload.scope == "selected"
                or item.failed_count > 0
                or bool(item.warning_flags)
            )
        ]
        missing = requested - {item.id for item in report.items}
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "report item does not exist", "item_ids": sorted(missing)},
            )
        drafts = [
            self._supplement_case_draft(report, item, payload.environment_id)
            for item in candidates[:20]
        ]
        return SupplementCaseDraftResult(
            source_report_id=report.summary.id,
            drafts=drafts,
        )

    @staticmethod
    def _range_days(range_value: ReportRange) -> int:
        return {"today": 1, "7d": 7, "30d": 30}[range_value]

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
            .options(
                load_only(
                    TestCaseExecution.id,
                    TestCaseExecution.test_case_id,
                    TestCaseExecution.executed_by_id,
                    TestCaseExecution.duration_ms,
                    TestCaseExecution.created_at,
                ),
                load_only(TestCase.id, TestCase.name),
                load_only(User.id, User.username, User.account),
            )
            .outerjoin(TestCase, TestCase.id == TestCaseExecution.test_case_id)
            .outerjoin(User, User.id == TestCaseExecution.executed_by_id)
            .filter(TestCaseExecution.project_id == project_id)
            .filter(TestCaseExecution.duration_ms >= self.SLOW_THRESHOLD_MS)
            .filter(TestCaseExecution.created_at >= started_from)
            .filter(TestCaseExecution.created_at <= started_to)
        )
        if environment_id is not None:
            query = query.filter(TestCaseExecution.environment_id == environment_id)
        query = query.order_by(
            TestCaseExecution.duration_ms.desc(),
            TestCaseExecution.id.desc(),
        ).limit(10)
        items = []
        for execution, test_case, owner in query.all():
            duration = int(execution.duration_ms or 0)
            owner_name = (
                (owner.username or owner.account)
                if owner is not None
                else f"用户 {execution.executed_by_id}"
            )
            items.append(ReportSlowTest(
                execution_id=execution.id,
                test_case_id=execution.test_case_id,
                name=(test_case.name if test_case is not None else f"执行记录 {execution.id}"),
                owner_id=owner.id if owner is not None else execution.executed_by_id,
                owner_name=owner_name,
                owner=owner_name,
                risk="high" if duration >= self.SLOW_THRESHOLD_MS * 2 else "medium",
                duration_ms=duration,
                last_executed_at=execution.created_at,
            ))
        return items

    def _failure_clusters(
        self,
        summaries: list[TestReportSummary],
    ) -> list[ReportFailureCluster]:
        failed_items = [
            item
            for item in summaries
            if item.failed_count > 0 or item.status in self.FAILURE_STATUSES
        ]
        return [
            ReportFailureCluster(
                name=item.name,
                count=max(item.failed_count, 1),
                priority="P0" if item.failed_count > 0 else "P1",
                confidence=min(95, 82 + max(item.failed_count, 1) * 3),
                source_type=item.source_type,
                source_id=item.source_id,
            )
            for item in failed_items[:5]
        ]

    def _report_recommendations(
        self,
        *,
        failure_clusters: list[ReportFailureCluster],
        slow_tests: list[ReportSlowTest],
    ) -> list[ReportRecommendation]:
        recommendations: list[ReportRecommendation] = []
        if failure_clusters:
            cluster = failure_clusters[0]
            recommendations.append(ReportRecommendation(
                id="rec-failure-cluster",
                priority="P0" if cluster.priority == "P0" else "P1",
                title="复核失败聚类",
                content=f"优先复核 {cluster.name}，当前聚类失败 {cluster.count} 次。",
                confidence=cluster.confidence,
                action=ReportRecommendationAction(
                    type="open_report",
                    label="查看失败报告",
                    target_id=cluster.source_id,
                    target_type=cluster.source_type,
                ),
                action_label="查看失败报告",
            ))
        if slow_tests:
            slow_test = slow_tests[0]
            recommendations.append(ReportRecommendation(
                id="rec-slow-tests",
                priority="P1",
                title="优化慢用例",
                content=(
                    f"{slow_test.name} 最近执行耗时 {slow_test.duration_ms}ms，"
                    "已超过慢用例阈值。"
                ),
                confidence=88,
                action=ReportRecommendationAction(
                    type="open_execution",
                    label="查看执行详情",
                    target_id=slow_test.execution_id,
                    target_type="api_case",
                ),
                action_label="查看执行详情",
            ))
        if not recommendations:
            recommendations.append(ReportRecommendation(
                id="rec-quality-stable",
                priority="P2",
                title="保持核心链路回归",
                content="当前周期未发现失败聚类或慢用例，建议保持核心链路每日回归。",
                confidence=80,
                action=ReportRecommendationAction(
                    type="open_trends",
                    label="查看趋势",
                ),
                action_label="查看趋势",
            ))
        return recommendations

    def _pass_rate_trend(
        self,
        summaries: list[TestReportSummary],
        *,
        started_on: date,
        days: int,
    ) -> list[ReportTrendValue]:
        buckets: dict[date, list[TestReportSummary]] = {}
        for item in summaries:
            timestamp = item.started_at or item.created_at
            buckets.setdefault(timestamp.date(), []).append(item)
        result = []
        for offset in range(days):
            day = started_on + timedelta(days=offset)
            items = buckets.get(day, [])
            total = sum(item.total_count for item in items)
            passed = sum(item.passed_count for item in items)
            failed = sum(item.failed_count for item in items)
            result.append(ReportTrendValue(
                date=day,
                label=self._weekday_label(day),
                value=round(passed * 100 / total, 2) if total else 0.0,
                total_count=total,
                passed_count=passed,
                failed_count=failed,
            ))
        return result

    @staticmethod
    def _stability_heatmap(
        trend: list[ReportTrendValue],
    ) -> ReportStabilityHeatmap:
        return ReportStabilityHeatmap(
            labels=[item.date.strftime("%m-%d") for item in trend],
            rows=[
                ReportStabilityHeatmapRow(
                    module="报告稳定性",
                    values=[
                        max(1, min(5, int(round(item.value / 20))))
                        if item.total_count
                        else 0
                        for item in trend
                    ],
                )
            ],
        )

    def _risk_indicators(
        self,
        *,
        failure_clusters: list[ReportFailureCluster],
        slow_tests: list[ReportSlowTest],
        open_defects: int,
    ) -> list[ReportRiskIndicator]:
        failed_count = sum(item.count for item in failure_clusters)
        return [
            self._risk_indicator(
                indicator_id="execution_failure_risk",
                name="执行失败风险",
                count=failed_count,
                score=min(100, failed_count * 10),
            ),
            self._risk_indicator(
                indicator_id="slow_execution_risk",
                name="慢执行风险",
                count=len(slow_tests),
                score=min(100, len(slow_tests) * 18),
            ),
            self._risk_indicator(
                indicator_id="open_defect_risk",
                name="未关闭缺陷风险",
                count=open_defects,
                score=min(100, open_defects * 12),
            ),
        ]

    @staticmethod
    def _risk_indicator(
        *,
        indicator_id: str,
        name: str,
        count: int,
        score: int,
    ) -> ReportRiskIndicator:
        return ReportRiskIndicator(
            id=indicator_id,
            name=name,
            count=count,
            score=score,
            level="high" if score >= 70 else "medium" if score >= 35 else "low",
        )

    def _open_defect_count(self, project_id: int) -> int:
        return int(
            self.db.query(Defect)
            .filter(Defect.project_id == project_id)
            .filter(~Defect.status.in_(("closed", "resolved", "done", "已关闭", "已解决")))
            .count()
        )

    @staticmethod
    def _weekday_label(value: date) -> str:
        labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return labels[value.weekday()]

    def _get_report_projection(
        self,
        *,
        project_id: int,
        source_type: ReportSourceType,
        source_id: int,
    ) -> TestReportDetail | None:
        return getattr(self, f"_get_{source_type}_report")(
            project_id=project_id,
            source_id=source_id,
        )

    def _get_plan_report(self, *, project_id: int, source_id: int) -> TestReportDetail | None:
        run = self.repository.get_plan_run(project_id=project_id, source_id=source_id)
        if run is None:
            return None
        scenario_runs = self.repository.list_plan_scenario_runs(run.id)
        runs_by_id = {item.id: item for item in scenario_runs}
        snapshot_targets = {
            str(item.get("id")): item
            for item in (run.plan_snapshot or {}).get("targets", [])
            if isinstance(item, dict)
        }
        items = [
            self._plan_target_item(
                run=run,
                target=target,
                sequence=index,
                runs_by_id=runs_by_id,
                snapshot_target=snapshot_targets.get(str(target.get("target_id")))
                or snapshot_targets.get(str(target.get("id")))
                or {},
            )
            for index, target in enumerate(run.target_results or [], start=1)
            if isinstance(target, dict)
        ]
        operator = run.__dict__.get("operator")
        operator_name = (
            (operator.username or operator.account)
            if operator is not None
            else f"用户 {run.operator_id}"
        )
        summary = self._summary({
            "source_type": "plan",
            "source_id": run.id,
            "project_id": run.project_id,
            "name": run.plan_name,
            "status": run.status,
            "trigger_type": run.trigger,
            "trigger_user_id": run.operator_id,
            "trigger_user_name": operator_name,
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
        assertion_count = sum(item.assertion_count for item in items)
        passed_assertions = sum(item.passed_assertion_count for item in items)
        record_count = len(scenario_runs)
        passed_records = sum(item.status in self.PASSED_STATUSES for item in scenario_runs)
        return TestReportDetail(
            summary=summary,
            metrics={
                "target_count": run.target_count,
                "passed_target_count": run.passed_count,
                "failed_target_count": run.failed_count,
                "scenario_run_count": record_count,
                "passed_scenario_run_count": passed_records,
                "failed_scenario_run_count": sum(
                    item.status in self.FAILURE_STATUSES for item in scenario_runs
                ),
                "assertion_count": assertion_count,
                "passed_assertion_count": passed_assertions,
                "failed_assertion_count": assertion_count - passed_assertions,
                "pass_rate": summary.pass_rate,
            },
            items=items,
            source_snapshot=TestReportSourceSnapshot(
                source_name=run.plan_name,
                source_version=run.plan_version,
            ),
        )

    def _get_flow_report(self, *, project_id: int, source_id: int) -> TestReportDetail | None:
        row = self.repository.get_flow_execution(project_id=project_id, source_id=source_id)
        if row is None:
            return None
        row_values = list(row)
        execution = row_values[0]
        current_flow_name = row_values[1] if len(row_values) > 1 else None
        trigger_user_name = (
            row_values[2]
            if len(row_values) > 2
            else f"用户 {execution.trigger_user_id}"
        )
        environment_name = row_values[3] if len(row_values) > 3 else None
        version_number = row_values[4] if len(row_values) > 4 else None
        context = execution.context_snapshot or {}
        definition = context.get("definition") or {}
        source_name = (
            context.get("sourceName")
            or context.get("source_name")
            or definition.get("name")
            or current_flow_name
            or f"Flow 执行 {execution.id}"
        )
        nodes = self.repository.list_flow_nodes(execution.id)
        items = [
            self._flow_node_item(
                node=node,
                sequence=index,
                context=context,
            )
            for index, node in enumerate(nodes, start=1)
        ]
        total = len(items)
        passed = sum(item.passed_count for item in items)
        failed = sum(item.failed_count for item in items)
        summary = self._summary({
            "source_type": "flow",
            "source_id": execution.id,
            "project_id": execution.project_id,
            "name": source_name,
            "status": execution.status,
            "trigger_type": execution.trigger_type,
            "trigger_user_id": execution.trigger_user_id,
            "trigger_user_name": trigger_user_name,
            "environment_id": execution.environment_id,
            "environment_name": environment_name,
            "total_count": total,
            "passed_count": passed,
            "failed_count": failed,
            "duration_ms": None,
            "started_at": execution.started_at,
            "finished_at": execution.finished_at,
            "created_at": execution.created_at,
        })
        assertion_count = sum(item.assertion_count for item in items)
        passed_assertions = sum(item.passed_assertion_count for item in items)
        return TestReportDetail(
            summary=summary,
            metrics={
                "node_count": total,
                "passed_node_count": passed,
                "failed_node_count": failed,
                "skipped_node_count": summary.skipped_count,
                "assertion_count": assertion_count,
                "passed_assertion_count": passed_assertions,
                "failed_assertion_count": assertion_count - passed_assertions,
                "pass_rate": summary.pass_rate,
            },
            items=items,
            source_snapshot=TestReportSourceSnapshot(
                source_name=source_name,
                source_version=context.get("sourceVersion")
                or context.get("source_version")
                or version_number,
            ),
        )

    def _plan_target_item(
        self,
        *,
        run: Any,
        target: dict[str, Any],
        sequence: int,
        runs_by_id: dict[int, Any],
        snapshot_target: dict[str, Any],
    ) -> TestReportItem:
        target_runs = [
            runs_by_id[run_id]
            for run_id in target.get("scenario_run_ids", [])
            if run_id in runs_by_id
        ]
        if target_runs:
            total = len(target_runs)
            passed = sum(item.status in self.PASSED_STATUSES for item in target_runs)
            failed = sum(item.status in self.FAILURE_STATUSES for item in target_runs)
        else:
            total = 1
            passed = int(target.get("status") in self.PASSED_STATUSES)
            failed = int(target.get("status") in self.FAILURE_STATUSES)
        assertions = []
        for scenario_run in target_runs:
            assertions.extend(self._collect_assertions(scenario_run.step_results or []))
        assertion_count, passed_assertions, failed_assertions = self._assertion_counts(assertions)
        error_message = self._string_or_none(target.get("error_message"))
        warning_flags = []
        if failed:
            warning_flags.append("execution_failed")
        if assertion_count == 0:
            warning_flags.append("no_assertion")
        if int(target.get("attempt") or 1) > 1:
            warning_flags.append("retried")
        target_key = str(
            target.get("target_id")
            or target.get("id")
            or snapshot_target.get("id")
            or sequence
        )
        return TestReportItem(
            id=f"plan-target:{target_key}",
            sequence=sequence,
            item_type="plan_target",
            reference_id=target.get("reference_id") or snapshot_target.get("reference_id"),
            name=target.get("name") or snapshot_target.get("name") or f"计划目标 {sequence}",
            kind=target.get("kind") or snapshot_target.get("kind") or "scenario",
            method=target.get("method") or snapshot_target.get("method"),
            path=target.get("path") or snapshot_target.get("path"),
            status=target.get("status") or "pending",
            status_label=self._status_label(target.get("status") or "pending"),
            attempt=int(target.get("attempt") or 1),
            total_count=total,
            passed_count=passed,
            failed_count=failed,
            skipped_count=max(total - passed - failed, 0),
            pass_rate=round(passed * 100 / total, 2) if total else 0.0,
            assertion_count=assertion_count,
            passed_assertion_count=passed_assertions,
            failed_assertion_count=failed_assertions,
            duration_ms=self._int_or_none(target.get("duration_ms")),
            error_message=error_message,
            warning_flags=warning_flags,
            started_at=target.get("started_at"),
            finished_at=target.get("finished_at"),
            detail_available=bool(target_runs or error_message),
        )

    def _flow_node_item(
        self,
        *,
        node: Any,
        sequence: int,
        context: dict[str, Any],
    ) -> TestReportItem:
        definition = context.get("definition") or {}
        node_definition = next(
            (
                item
                for item in definition.get("nodes", [])
                if isinstance(item, dict) and str(item.get("id")) == str(node.node_id)
            ),
            {},
        )
        referenced_cases = context.get("referencedCases") or context.get("referenced_cases") or {}
        referenced_case = referenced_cases.get(str(node.node_id)) or {}
        request = node.request_snapshot or {}
        output = node.output_snapshot or {}
        assertions = output.get("assertions") if isinstance(output.get("assertions"), list) else []
        assertion_count, passed_assertions, failed_assertions = self._assertion_counts(assertions)
        response_status_code = self._response_status_code(output)
        error = node.error if isinstance(node.error, dict) else {}
        output_error = output.get("error") if isinstance(output.get("error"), dict) else {}
        error_code = self._string_or_none(error.get("code") or output_error.get("code"))
        error_message = self._string_or_none(
            error.get("message") or output_error.get("message") or output.get("error")
        )
        kind = node_definition.get("kind") or referenced_case.get("kind") or "flow_node"
        method = (
            node_definition.get("method")
            or referenced_case.get("method")
            or request.get("method")
        )
        path = (
            node_definition.get("path")
            or referenced_case.get("path")
            or self._path_from_url(request.get("url"))
        )
        status_value = str(node.status or "pending")
        passed = int(status_value in self.PASSED_STATUSES)
        failed = int(status_value in self.FAILURE_STATUSES)
        warning_flags = []
        if kind in {"api_case", "websocket_case"} and assertion_count == 0:
            warning_flags.append("no_assertion")
        if response_status_code is not None and not 200 <= response_status_code < 300:
            warning_flags.append("non_2xx_response")
        if failed or error_message:
            warning_flags.append("execution_failed")
        if int(node.attempt or 1) > 1:
            warning_flags.append("retried")
        duration_ms = self._duration_ms(node.started_at, node.finished_at)
        if duration_ms is None:
            duration_ms = self._int_or_none(output.get("durationMs") or output.get("duration_ms"))
        return TestReportItem(
            id=f"node-execution:{node.id}",
            sequence=sequence,
            item_type="flow_node",
            node_id=node.node_id,
            reference_id=node_definition.get("referenceId")
            or node_definition.get("reference_id")
            or referenced_case.get("referenceId")
            or referenced_case.get("reference_id"),
            name=node_definition.get("name") or referenced_case.get("name") or node.node_id,
            kind=kind,
            method=method,
            path=path,
            status=status_value,
            status_label=self._status_label(status_value),
            attempt=int(node.attempt or 1),
            total_count=1,
            passed_count=passed,
            failed_count=failed,
            skipped_count=max(1 - passed - failed, 0),
            pass_rate=100.0 if passed else 0.0,
            assertion_count=assertion_count,
            passed_assertion_count=passed_assertions,
            failed_assertion_count=failed_assertions,
            response_status_code=response_status_code,
            duration_ms=duration_ms,
            error_code=error_code,
            error_message=error_message,
            warning_flags=list(dict.fromkeys(warning_flags)),
            started_at=node.started_at,
            finished_at=node.finished_at,
            detail_available=bool(node.request_snapshot or node.output_snapshot or node.error),
        )

    def _get_flow_item_detail(
        self,
        *,
        project_id: int,
        source_id: int,
        item_id: str,
    ) -> TestReportItemDetail | None:
        row = self.repository.get_flow_execution(project_id=project_id, source_id=source_id)
        if row is None:
            return None
        execution = row[0]
        context = execution.context_snapshot or {}
        nodes = self.repository.list_flow_nodes(execution.id)
        for sequence, node in enumerate(nodes, start=1):
            item = self._flow_node_item(node=node, sequence=sequence, context=context)
            if item.id != item_id and str(node.id) != item_id:
                continue
            output = node.output_snapshot or {}
            assertions = output.get("assertions") if isinstance(output.get("assertions"), list) else []
            attempts = output.get("attempts") if isinstance(output.get("attempts"), list) else []
            return TestReportItemDetail(
                item=item,
                request=self._standardize_request(node.request_snapshot or {}, item),
                response=self._standardize_response(output, item),
                assertions=redact_sensitive_data(assertions),
                attempts=redact_sensitive_data(attempts),
            )
        return None

    def _get_plan_item_detail(
        self,
        *,
        project_id: int,
        source_id: int,
        item_id: str,
    ) -> TestReportItemDetail | None:
        run = self.repository.get_plan_run(project_id=project_id, source_id=source_id)
        if run is None:
            return None
        scenario_runs = self.repository.list_plan_scenario_runs(run.id)
        runs_by_id = {item.id: item for item in scenario_runs}
        snapshot_targets = {
            str(item.get("id")): item
            for item in (run.plan_snapshot or {}).get("targets", [])
            if isinstance(item, dict)
        }
        for sequence, target in enumerate(run.target_results or [], start=1):
            if not isinstance(target, dict):
                continue
            snapshot_target = (
                snapshot_targets.get(str(target.get("target_id")))
                or snapshot_targets.get(str(target.get("id")))
                or {}
            )
            item = self._plan_target_item(
                run=run,
                target=target,
                sequence=sequence,
                runs_by_id=runs_by_id,
                snapshot_target=snapshot_target,
            )
            if item.id != item_id and str(target.get("id")) != item_id:
                continue
            target_runs = [
                runs_by_id[run_id]
                for run_id in target.get("scenario_run_ids", [])
                if run_id in runs_by_id
            ]
            assertions = []
            for scenario_run in target_runs:
                assertions.extend(self._collect_assertions(scenario_run.step_results or []))
            first_request = self._find_first_dict(
                [item.step_results for item in target_runs],
                {"request", "request_snapshot"},
            )
            first_response = self._find_first_dict(
                [item.step_results for item in target_runs],
                {"response", "response_snapshot", "output_snapshot"},
            )
            attempts = [
                {
                    "run_id": scenario_run.id,
                    "dataset_id": scenario_run.dataset_id,
                    "dataset_name": scenario_run.dataset_name,
                    "record_id": scenario_run.record_id,
                    "record_name": scenario_run.record_name,
                    "status": scenario_run.status,
                    "duration_ms": scenario_run.duration_ms,
                    "started_at": scenario_run.started_at,
                    "finished_at": scenario_run.finished_at,
                }
                for scenario_run in target_runs
            ]
            return TestReportItemDetail(
                item=item,
                request=self._standardize_request(first_request, item),
                response=self._standardize_response(first_response, item),
                assertions=redact_sensitive_data(assertions),
                attempts=redact_sensitive_data(attempts),
            )
        return None

    @staticmethod
    def _standardize_request(
        request: Any,
        item: TestReportItem,
    ) -> dict[str, Any]:
        source = redact_sensitive_data(request if isinstance(request, dict) else {})
        url = source.get("url") or source.get("uri")
        return {
            "method": source.get("method") or item.method,
            "url": url,
            "path": item.path or TestReportService._path_from_url(url),
            "headers": source.get("headers") or {},
            "query": source.get("query") or source.get("query_params") or {},
            "body": source.get("body"),
        }

    @staticmethod
    def _standardize_response(
        output: Any,
        item: TestReportItem,
    ) -> dict[str, Any]:
        source = output if isinstance(output, dict) else {}
        response = source.get("response") if isinstance(source.get("response"), dict) else source
        response = redact_sensitive_data(response)
        return {
            "status_code": item.response_status_code
            or TestReportService._int_or_none(
                response.get("status_code") or response.get("status")
            ),
            "headers": response.get("headers") or {},
            "body": response.get("body")
            if "body" in response
            else response.get("data") or response.get("content") or response.get("messages"),
        }

    @staticmethod
    def _collect_assertions(value: Any) -> list[Any]:
        result: list[Any] = []
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"assertions", "assertion_results", "assertionResults"} and isinstance(item, list):
                    result.extend(item)
                else:
                    result.extend(TestReportService._collect_assertions(item))
        elif isinstance(value, list):
            for item in value:
                result.extend(TestReportService._collect_assertions(item))
        return result

    @staticmethod
    def _assertion_counts(assertions: list[Any]) -> tuple[int, int, int]:
        passed = 0
        for assertion in assertions:
            if not isinstance(assertion, dict):
                continue
            explicit = assertion.get("passed")
            if explicit is None:
                explicit = assertion.get("success")
            if explicit is True or str(assertion.get("status", "")).lower() in {
                "passed",
                "success",
            }:
                passed += 1
        total = len(assertions)
        return total, passed, max(total - passed, 0)

    @staticmethod
    def _find_first_dict(value: Any, keys: set[str]) -> dict[str, Any]:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in keys and isinstance(item, dict):
                    return item
                found = TestReportService._find_first_dict(item, keys)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = TestReportService._find_first_dict(item, keys)
                if found:
                    return found
        return {}

    @staticmethod
    def _response_status_code(output: Any) -> int | None:
        if not isinstance(output, dict):
            return None
        response = output.get("response")
        if not isinstance(response, dict):
            return None
        return TestReportService._int_or_none(
            response.get("status_code") or response.get("status")
        )

    @staticmethod
    def _path_from_url(value: Any) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return urlsplit(value).path or None
        except ValueError:
            return None

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _string_or_none(value: Any) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, dict):
            return str(value.get("message") or value.get("detail") or value)
        return str(value)

    @staticmethod
    def _status_label(value: str) -> str:
        return {
            "passed": "通过",
            "success": "通过",
            "completed": "完成",
            "failed": "失败",
            "error": "异常",
            "timeout": "超时",
            "skipped": "跳过",
            "running": "执行中",
            "queued": "排队中",
            "pending": "等待中",
            "cancelled": "已取消",
        }.get(value.lower(), value or "未知")

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _supplement_case_draft(
        report: TestReportDetail,
        item: TestReportItem,
        environment_id: int | None,
    ) -> SupplementCaseDraft:
        flags = set(item.warning_flags)
        if "non_2xx_response" in flags:
            objective = "验证目标返回非 2xx 状态时，业务链路能够正确识别并处理异常响应"
        elif item.failed_count > 0:
            objective = "补充失败路径验证并确认错误处理、恢复和结果记录符合预期"
        elif "no_assertion" in flags:
            objective = "为当前执行路径补充明确的业务结果断言，避免仅请求成功但结果不可验证"
        else:
            objective = "补充当前执行目标的边界条件和异常分支验证"
        priority = "P0" if item.failed_count > 0 else "P1"
        environment_note = (
            f"使用环境 {environment_id}，并准备可重复执行的测试数据"
            if environment_id is not None
            else "选择与来源报告一致的可用测试环境，并准备可重复执行的测试数据"
        )
        return SupplementCaseDraft(
            id=f"draft-{report.summary.source_type}-{report.summary.source_id}-{item.sequence}",
            title=f"{item.name}补充验证",
            test_objective=objective,
            preconditions=environment_note,
            test_steps=[
                {"sequence": 1, "action": f"按来源报告重放 {item.name} 的基础请求"},
                {"sequence": 2, "action": "构造对应风险条件并执行目标"},
                {"sequence": 3, "action": "校验业务结果、错误信息和执行状态"},
            ],
            expected_result="系统能够稳定识别风险条件，返回明确结果且不泄漏敏感信息",
            priority=priority,
            source_report_id=report.summary.id,
            source_item_ids=[item.id],
            confidence=91 if item.failed_count > 0 else 86,
        )

    @staticmethod
    def render_html(report: TestReportDetail) -> str:
        summary = report.summary
        rows = []
        for item in report.items:
            details = html.escape(
                json.dumps(jsonable_encoder(item), ensure_ascii=False, indent=2)
            )
            rows.append(
                "<tr>"
                f"<td>{item.sequence}</td><td>{html.escape(item.name)}</td>"
                f"<td>{html.escape(item.status_label)}</td>"
                f"<td>{html.escape(str(item.duration_ms if item.duration_ms is not None else '-'))}</td>"
                f"<td><details><summary>查看</summary><pre>{details}</pre></details></td>"
                "</tr>"
            )
        metrics = "".join(
            f"<div class='metric'><strong>{html.escape(str(value))}</strong>"
            f"<span>{html.escape(key.replace('_', ' '))}</span></div>"
            for key, value in report.metrics.items()
        )
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(summary.name)} - 测试报告</title>
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
<div class="meta">{html.escape(summary.source_type)} 报告 #{summary.source_id} |
状态：{html.escape(TestReportService._status_label(summary.status))} |
通过率：{summary.pass_rate}%</div>
<section class="metrics">{metrics}</section>
<table><thead><tr><th>#</th><th>名称</th><th>状态</th><th>耗时(ms)</th><th>详情</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</main></body></html>"""
