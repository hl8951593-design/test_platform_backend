import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models.execution_diagnostic import (
    ExecutionMetricDaily,
    ExecutionMetricHourly,
    ExecutionRecordIndex,
)
from app.services.execution_metrics_scheduler import ExecutionMetricsScheduler
from app.services.execution_metrics_scheduler import execution_metrics_scheduler
from app.services.execution_metrics_service import ExecutionMetricsService


HOUR = datetime(2026, 7, 12, 10, 0, 0)


class ExecutionMetricsTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        for table in (
            ExecutionRecordIndex.__table__,
            ExecutionMetricHourly.__table__,
            ExecutionMetricDaily.__table__,
        ):
            table.create(engine)
        self.db = sessionmaker(bind=engine)()
        self.service = ExecutionMetricsService(self.db)

    def tearDown(self):
        self.db.close()

    def _seed(
        self,
        *,
        count: int,
        signature: str | None,
        project_id: int = 1,
        status: str = "failed",
        resource_id_start: int = 1,
        execution_id_start: int = 100,
    ) -> None:
        for index in range(count):
            started_at = HOUR + timedelta(minutes=index)
            self.db.add(
                ExecutionRecordIndex(
                    project_id=project_id,
                    execution_type="scenario",
                    execution_id=execution_id_start + index,
                    object_ref=f"scenario:{execution_id_start + index}",
                    resource_id=resource_id_start + (index % 2),
                    resource_name="checkout",
                    environment_id=3,
                    status=status,
                    trigger_type="manual",
                    trigger_user_id=7,
                    duration_ms=100 + index,
                    total_steps=3,
                    passed_steps=2 if status == "failed" else 3,
                    failed_steps=1 if status == "failed" else 0,
                    timeout_steps=0,
                    skipped_steps=0,
                    failure_signature=signature,
                    started_at=started_at,
                    finished_at=started_at + timedelta(seconds=1),
                    source_updated_at=started_at + timedelta(seconds=2),
                    projection_version="execution_diagnostic_projection_v1",
                )
            )
        self.db.flush()

    def test_failure_cluster_counts_signatures_not_raw_records(self):
        signature = "AUTHORIZATION_HTTP_200_BUSINESS_90001_JSON_EQUALS_CODE"
        self._seed(count=7, signature=signature)
        self._seed(count=1, signature=None, execution_id_start=200)
        self._seed(count=2, signature=signature, project_id=2)

        result = self.service.query_failure_clusters(
            project_id=1,
            started_from=HOUR,
            started_to=HOUR + timedelta(hours=1),
            limit=20,
        )

        self.assertEqual(len(result["failure_clusters"]), 1)
        cluster = result["failure_clusters"][0]
        self.assertEqual(cluster["failure_signature"], signature)
        self.assertEqual(cluster["count"], 7)
        self.assertEqual(cluster["distinct_resource_count"], 2)
        self.assertEqual(len(cluster["sample_execution_refs"]), 5)
        self.assertEqual(cluster["sample_execution_refs"][0], "scenario:106")
        self.assertEqual(result["watermark"], HOUR + timedelta(minutes=6, seconds=2))

    def test_rebuild_hour_is_idempotent_and_day_derives_from_hourly(self):
        self._seed(count=3, signature="AUTH", status="failed")
        self._seed(
            count=2,
            signature=None,
            status="passed",
            resource_id_start=10,
            execution_id_start=200,
        )

        first = self.service.rebuild_hour(project_id=1, bucket=HOUR)
        second = self.service.rebuild_hour(project_id=1, bucket=HOUR)
        self.assertEqual(first, 2)
        self.assertEqual(second, 2)
        hourly_count = self.db.scalar(
            select(func.count()).select_from(ExecutionMetricHourly)
        )
        self.assertEqual(hourly_count, 2)

        daily_count = self.service.rebuild_day(project_id=1, bucket=HOUR)
        self.assertEqual(daily_count, 2)
        rows = self.db.scalars(select(ExecutionMetricDaily)).all()
        self.assertEqual(sum(row.execution_count for row in rows), 5)
        long_range = self.service.query_metrics(
            project_id=1,
            started_from=HOUR,
            started_to=HOUR + timedelta(days=7),
            limit=20,
        )
        self.assertEqual(long_range["granularity"], "day")
        self.assertEqual(sum(row["execution_count"] for row in long_range["metrics"]), 5)

    def test_query_metrics_is_project_scoped_bounded_and_has_watermark(self):
        self._seed(count=3, signature="AUTH")
        self._seed(count=4, signature="OTHER", project_id=2)
        self.service.rebuild_hour(project_id=1, bucket=HOUR)

        result = self.service.query_metrics(
            project_id=1,
            started_from=HOUR,
            started_to=HOUR + timedelta(hours=1),
            limit=20,
        )

        self.assertEqual(len(result["metrics"]), 1)
        self.assertEqual(result["granularity"], "hour")
        self.assertEqual(result["metrics"][0]["execution_count"], 3)
        self.assertIsNotNone(result["watermark"])

    def test_rebuild_recent_streams_changed_buckets_without_committing(self):
        self._seed(count=3, signature="AUTH")
        self.db.commit = MagicMock()

        rebuilt = self.service.rebuild_recent(
            now=HOUR + timedelta(minutes=30), lookback_hours=2
        )

        self.assertEqual(rebuilt, 1)
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(ExecutionMetricHourly)),
            1,
        )
        self.db.commit.assert_not_called()

    @patch("app.services.execution_metrics_scheduler.SessionLocal")
    def test_scheduler_uses_isolated_session_and_only_rebuilds_metrics(self, session_local):
        db = MagicMock()
        session_local.return_value.__enter__.return_value = db
        scheduler = ExecutionMetricsScheduler()
        with patch(
            "app.services.execution_metrics_scheduler.ExecutionMetricsService"
        ) as service_type:
            service_type.return_value.rebuild_recent.return_value = 3
            rebuilt = scheduler.tick()

        self.assertEqual(rebuilt, 3)
        service_type.return_value.rebuild_recent.assert_called_once()
        db.commit.assert_called_once_with()

    def test_application_registers_metrics_scheduler_lifecycle(self):
        from app.main import create_app

        application = create_app()
        self.assertIn(execution_metrics_scheduler.start, application.router.on_startup)
        self.assertIn(execution_metrics_scheduler.stop, application.router.on_shutdown)


if __name__ == "__main__":
    unittest.main()
