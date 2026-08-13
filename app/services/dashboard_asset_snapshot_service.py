from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.models.dashboard import DashboardAssetDailySnapshot, DashboardAssetEvent
from app.models.defect import Defect
from app.models.project import Project, ProjectEnvironment
from app.models.scenario import TestScenario
from app.models.system_test_case import SystemTestCase
from app.models.test_case import TestCase, TestCaseEnvironment
from app.models.user import User
from app.models.websocket_test_case import WebSocketTestCase, WebSocketTestCaseEnvironment
from app.schemas.dashboard import (
    DashboardAutomationTrend,
    DashboardAutomationTrendPoint,
    DashboardDefectTrend,
    DashboardDefectTrendPoint,
    DashboardTestCaseBreakdown,
    DashboardTestCaseTrend,
    DashboardTestCaseTrendPoint,
    DashboardTrendScope,
    ProjectAssetTrendsResponse,
)
from app.services.permission_service import PermissionService


class DashboardAssetSnapshotService:
    CLOSED_DEFECT_STATUSES = {"closed", "resolved", "done", "已关闭", "已解决"}

    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    @staticmethod
    def scope_key(environment_id: int | None) -> str:
        return "project" if environment_id is None else f"environment:{environment_id}"

    def capture_all(self, *, captured_at: datetime | None = None) -> int:
        now = captured_at or datetime.now()
        project_ids = self.db.scalars(
            select(Project.id).where(Project.is_deleted.is_(False))
        ).all()
        captured = 0
        for project_id in project_ids:
            self.capture_scope(project_id=project_id, environment_id=None, captured_at=now)
            captured += 1
            environment_ids = self.db.scalars(
                select(ProjectEnvironment.id).where(
                    ProjectEnvironment.project_id == project_id,
                    ProjectEnvironment.is_deleted.is_(False),
                )
            ).all()
            for environment_id in environment_ids:
                self.capture_scope(
                    project_id=project_id,
                    environment_id=environment_id,
                    captured_at=now,
                )
                captured += 1
        return captured

    def capture_scope(
        self,
        *,
        project_id: int,
        environment_id: int | None,
        captured_at: datetime | None = None,
    ) -> DashboardAssetDailySnapshot:
        now = captured_at or datetime.now()
        self._validate_environment(project_id=project_id, environment_id=environment_id)
        counts = self._current_counts(project_id=project_id, environment_id=environment_id)
        snapshot = self.db.scalar(
            select(DashboardAssetDailySnapshot).where(
                DashboardAssetDailySnapshot.project_id == project_id,
                DashboardAssetDailySnapshot.scope_key == self.scope_key(environment_id),
                DashboardAssetDailySnapshot.snapshot_date == now.date(),
            )
        )
        if snapshot is None:
            snapshot = DashboardAssetDailySnapshot(
                project_id=project_id,
                environment_id=environment_id,
                scope_key=self.scope_key(environment_id),
                snapshot_date=now.date(),
                captured_at=now,
                **counts,
            )
            self.db.add(snapshot)
        else:
            snapshot.environment_id = environment_id
            snapshot.captured_at = now
            for key, value in counts.items():
                setattr(snapshot, key, value)
        self.db.flush()
        return snapshot

    def project_asset_trends(
        self,
        *,
        project_id: int,
        environment_id: int | None,
        range_value: str,
        current_user: User,
    ) -> ProjectAssetTrendsResponse:
        self.permission_service.require_project_access(current_user, project_id)
        if range_value not in {"7d", "30d"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="range 仅支持 7d 或 30d",
            )
        now = datetime.now()
        self._validate_environment(
            project_id=project_id,
            environment_id=environment_id,
        )
        current_snapshot = DashboardAssetDailySnapshot(
            project_id=project_id,
            environment_id=environment_id,
            scope_key=self.scope_key(environment_id),
            snapshot_date=now.date(),
            captured_at=now,
            **self._current_counts(
                project_id=project_id,
                environment_id=environment_id,
            ),
        )

        days = 30 if range_value == "30d" else 7
        start_date = now.date() - timedelta(days=days - 1)
        previous_cutoff = start_date - timedelta(days=1)
        scope_key = self.scope_key(environment_id)
        snapshots = list(self.db.scalars(
            select(DashboardAssetDailySnapshot)
            .where(
                DashboardAssetDailySnapshot.project_id == project_id,
                DashboardAssetDailySnapshot.scope_key == scope_key,
                DashboardAssetDailySnapshot.snapshot_date >= start_date,
                DashboardAssetDailySnapshot.snapshot_date <= now.date(),
            )
            .order_by(DashboardAssetDailySnapshot.snapshot_date.asc())
        ).all())
        snapshots = [
            snapshot
            for snapshot in snapshots
            if snapshot.snapshot_date != now.date()
        ]
        snapshots.append(current_snapshot)
        snapshots.sort(key=lambda snapshot: snapshot.snapshot_date)
        previous = self.db.scalar(
            select(DashboardAssetDailySnapshot)
            .where(
                DashboardAssetDailySnapshot.project_id == project_id,
                DashboardAssetDailySnapshot.scope_key == scope_key,
                DashboardAssetDailySnapshot.snapshot_date <= previous_cutoff,
            )
            .order_by(DashboardAssetDailySnapshot.snapshot_date.desc())
            .limit(1)
        )
        earliest_date = self.db.scalar(
            select(DashboardAssetDailySnapshot.snapshot_date)
            .where(
                DashboardAssetDailySnapshot.project_id == project_id,
                DashboardAssetDailySnapshot.scope_key == scope_key,
            )
            .order_by(DashboardAssetDailySnapshot.snapshot_date.asc())
            .limit(1)
        )
        earliest_date = earliest_date or now.date()
        expected_point_dates = {start_date + timedelta(days=offset) for offset in range(days)}
        snapshot_dates = {item.snapshot_date for item in snapshots}
        historical_complete = (
            previous is not None
            and previous.snapshot_date == previous_cutoff
            and expected_point_dates.issubset(snapshot_dates)
        )
        baseline = previous or current_snapshot
        events = self._event_totals(
            project_id=project_id,
            environment_id=environment_id,
            start_date=start_date,
            end_date=now.date(),
        )

        current_test_cases = self._test_case_total(current_snapshot)
        previous_test_cases = self._test_case_total(baseline)
        current_scenarios = current_snapshot.scenario_count
        previous_scenarios = baseline.scenario_count
        current_open_defects = current_snapshot.defect_open_count
        previous_open_defects = baseline.defect_open_count

        return ProjectAssetTrendsResponse(
            range=range_value,
            scope=DashboardTrendScope(project_id=project_id, environment_id=environment_id),
            test_cases=DashboardTestCaseTrend(
                current=current_test_cases,
                previous=previous_test_cases,
                delta=current_test_cases - previous_test_cases,
                delta_rate=self._delta_rate(current_test_cases, previous_test_cases),
                breakdown=DashboardTestCaseBreakdown(
                    http=current_snapshot.http_test_case_count,
                    websocket=current_snapshot.websocket_test_case_count,
                    system=current_snapshot.system_test_case_count,
                ),
                points=[
                    DashboardTestCaseTrendPoint(
                        date=item.snapshot_date.isoformat(),
                        total=self._test_case_total(item),
                        created=events[item.snapshot_date]["test_case_created"],
                        deleted=events[item.snapshot_date]["test_case_deleted"],
                    )
                    for item in snapshots
                ],
            ),
            automation_flows=DashboardAutomationTrend(
                current=current_scenarios,
                previous=previous_scenarios,
                delta=current_scenarios - previous_scenarios,
                delta_rate=self._delta_rate(current_scenarios, previous_scenarios),
                enabled_count=current_snapshot.scenario_enabled_count,
                points=[
                    DashboardAutomationTrendPoint(
                        date=item.snapshot_date.isoformat(),
                        total=item.scenario_count,
                        created=events[item.snapshot_date]["scenario_created"],
                        enabled=item.scenario_enabled_count,
                        deleted=events[item.snapshot_date]["scenario_deleted"],
                    )
                    for item in snapshots
                ],
            ),
            defects=DashboardDefectTrend(
                current_open=current_open_defects,
                previous_open=previous_open_defects,
                delta=current_open_defects - previous_open_defects,
                delta_rate=self._delta_rate(current_open_defects, previous_open_defects),
                total=current_snapshot.defect_total_count,
                points=[
                    DashboardDefectTrendPoint(
                        date=item.snapshot_date.isoformat(),
                        open=item.defect_open_count,
                        created=events[item.snapshot_date]["defect_created"],
                        closed=events[item.snapshot_date]["defect_closed"],
                        total=item.defect_total_count,
                    )
                    for item in snapshots
                ],
            ),
            historical_data_complete=historical_complete,
            data_complete_from=earliest_date.isoformat() if earliest_date else None,
            generated_at=now,
        )

    def _validate_environment(self, *, project_id: int, environment_id: int | None) -> None:
        if environment_id is None:
            return
        environment = self.db.scalar(
            select(ProjectEnvironment.id).where(
                ProjectEnvironment.id == environment_id,
                ProjectEnvironment.project_id == project_id,
                ProjectEnvironment.is_deleted.is_(False),
            )
        )
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目环境不存在")

    def _current_counts(self, *, project_id: int, environment_id: int | None) -> dict[str, int]:
        http_query = select(TestCase.id).where(TestCase.project_id == project_id)
        websocket_query = select(WebSocketTestCase.id).where(WebSocketTestCase.project_id == project_id)
        scenario_query = select(TestScenario.id).where(
            TestScenario.project_id == project_id,
            TestScenario.is_deleted.is_(False),
        )
        if environment_id is not None:
            http_query = http_query.where(
                or_(
                    TestCase.environment_id == environment_id,
                    exists(
                        select(TestCaseEnvironment.id).where(
                            TestCaseEnvironment.test_case_id == TestCase.id,
                            TestCaseEnvironment.environment_id == environment_id,
                        )
                    ),
                )
            )
            websocket_query = websocket_query.where(
                or_(
                    WebSocketTestCase.environment_id == environment_id,
                    exists(
                        select(WebSocketTestCaseEnvironment.id).where(
                            WebSocketTestCaseEnvironment.websocket_test_case_id == WebSocketTestCase.id,
                            WebSocketTestCaseEnvironment.environment_id == environment_id,
                        )
                    ),
                )
            )
            scenario_query = scenario_query.where(TestScenario.environment_id == environment_id)

        counts = self.db.execute(
            select(
                select(func.count())
                .select_from(http_query.subquery())
                .scalar_subquery()
                .label("http_count"),
                select(func.count())
                .select_from(websocket_query.subquery())
                .scalar_subquery()
                .label("websocket_count"),
                select(func.count())
                .select_from(scenario_query.subquery())
                .scalar_subquery()
                .label("scenario_count"),
                select(func.count())
                .select_from(SystemTestCase)
                .where(SystemTestCase.project_id == project_id)
                .scalar_subquery()
                .label("system_count"),
                select(func.count())
                .select_from(Defect)
                .where(Defect.project_id == project_id)
                .scalar_subquery()
                .label("defect_total"),
                select(func.count())
                .select_from(Defect)
                .where(
                    Defect.project_id == project_id,
                    ~func.lower(Defect.status).in_(
                        tuple(self.CLOSED_DEFECT_STATUSES)
                    ),
                )
                .scalar_subquery()
                .label("open_defects"),
            )
        ).one()
        http_count = int(counts.http_count or 0)
        websocket_count = int(counts.websocket_count or 0)
        scenario_count = int(counts.scenario_count or 0)
        system_count = int(counts.system_count or 0)
        defect_total = int(counts.defect_total or 0)
        open_defects = int(counts.open_defects or 0)
        return {
            "http_test_case_count": http_count,
            "websocket_test_case_count": websocket_count,
            "system_test_case_count": system_count,
            "scenario_count": scenario_count,
            "scenario_enabled_count": scenario_count,
            "defect_open_count": open_defects,
            "defect_total_count": defect_total,
        }

    def _event_totals(
        self,
        *,
        project_id: int,
        environment_id: int | None,
        start_date: date,
        end_date: date,
    ) -> defaultdict[date, defaultdict[str, int]]:
        started_at = datetime.combine(start_date, time.min)
        ended_at = datetime.combine(end_date, time.max)
        statement = select(DashboardAssetEvent).where(
            DashboardAssetEvent.project_id == project_id,
            DashboardAssetEvent.occurred_at >= started_at,
            DashboardAssetEvent.occurred_at <= ended_at,
        )
        if environment_id is not None:
            statement = statement.where(
                or_(
                    DashboardAssetEvent.environment_id == environment_id,
                    DashboardAssetEvent.asset_type.in_(("system_test_case", "defect")),
                )
            )
        totals: defaultdict[date, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
        for event in self.db.scalars(statement).all():
            event_date = event.occurred_at.date()
            if event.asset_type in {"http_test_case", "websocket_test_case", "system_test_case"}:
                if event.event_type in {"created", "deleted"}:
                    totals[event_date][f"test_case_{event.event_type}"] += 1
            elif event.asset_type == "scenario" and event.event_type in {"created", "deleted"}:
                totals[event_date][f"scenario_{event.event_type}"] += 1
            elif event.asset_type == "defect":
                if event.event_type == "created":
                    totals[event_date]["defect_created"] += 1
                elif event.event_type == "closed":
                    totals[event_date]["defect_closed"] += 1
        return totals

    @staticmethod
    def _test_case_total(snapshot: DashboardAssetDailySnapshot) -> int:
        return (
            snapshot.http_test_case_count
            + snapshot.websocket_test_case_count
            + snapshot.system_test_case_count
        )

    @staticmethod
    def _delta_rate(current: int, previous: int) -> float:
        if previous == 0:
            return 0.0
        return round((current - previous) * 100 / previous, 2)
