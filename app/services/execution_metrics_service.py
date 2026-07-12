from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session

from app.models.execution_diagnostic import (
    ExecutionMetricDaily,
    ExecutionMetricHourly,
    ExecutionRecordIndex,
)


class ExecutionMetricsService:
    """Recomputable execution rollups and bounded failure-cluster reads."""

    def __init__(self, db: Session):
        self.db = db

    def rebuild_hour(self, *, project_id: int, bucket: datetime) -> int:
        bucket = _hour_bucket(bucket)
        bucket_end = bucket + timedelta(hours=1)
        self.db.execute(
            delete(ExecutionMetricHourly).where(
                ExecutionMetricHourly.project_id == project_id,
                ExecutionMetricHourly.time_bucket == bucket,
            )
        )
        grouped = self.db.execute(
            select(
                ExecutionRecordIndex.environment_id,
                ExecutionRecordIndex.execution_type,
                ExecutionRecordIndex.status,
                ExecutionRecordIndex.failure_signature,
                func.count().label("execution_count"),
                func.coalesce(func.sum(ExecutionRecordIndex.duration_ms), 0).label(
                    "duration_sum_ms"
                ),
                func.coalesce(func.max(ExecutionRecordIndex.duration_ms), 0).label(
                    "duration_max_ms"
                ),
                func.max(ExecutionRecordIndex.source_updated_at).label("watermark"),
            )
            .where(
                ExecutionRecordIndex.project_id == project_id,
                ExecutionRecordIndex.started_at >= bucket,
                ExecutionRecordIndex.started_at < bucket_end,
            )
            .group_by(
                ExecutionRecordIndex.environment_id,
                ExecutionRecordIndex.execution_type,
                ExecutionRecordIndex.status,
                ExecutionRecordIndex.failure_signature,
            )
        ).all()
        for row in grouped:
            self.db.add(
                ExecutionMetricHourly(
                    project_id=project_id,
                    environment_id=row.environment_id,
                    execution_type=row.execution_type,
                    time_bucket=bucket,
                    status=row.status,
                    failure_signature=row.failure_signature,
                    execution_count=int(row.execution_count or 0),
                    duration_sum_ms=int(row.duration_sum_ms or 0),
                    duration_max_ms=int(row.duration_max_ms or 0),
                    watermark=row.watermark,
                )
            )
        self.db.flush()
        return len(grouped)

    def rebuild_day(self, *, project_id: int, bucket: datetime) -> int:
        bucket = _day_bucket(bucket)
        bucket_end = bucket + timedelta(days=1)
        self.db.execute(
            delete(ExecutionMetricDaily).where(
                ExecutionMetricDaily.project_id == project_id,
                ExecutionMetricDaily.time_bucket == bucket,
            )
        )
        grouped = self.db.execute(
            select(
                ExecutionMetricHourly.environment_id,
                ExecutionMetricHourly.execution_type,
                ExecutionMetricHourly.status,
                ExecutionMetricHourly.failure_signature,
                func.sum(ExecutionMetricHourly.execution_count).label(
                    "execution_count"
                ),
                func.sum(ExecutionMetricHourly.duration_sum_ms).label(
                    "duration_sum_ms"
                ),
                func.max(ExecutionMetricHourly.duration_max_ms).label(
                    "duration_max_ms"
                ),
                func.max(ExecutionMetricHourly.watermark).label("watermark"),
            )
            .where(
                ExecutionMetricHourly.project_id == project_id,
                ExecutionMetricHourly.time_bucket >= bucket,
                ExecutionMetricHourly.time_bucket < bucket_end,
            )
            .group_by(
                ExecutionMetricHourly.environment_id,
                ExecutionMetricHourly.execution_type,
                ExecutionMetricHourly.status,
                ExecutionMetricHourly.failure_signature,
            )
        ).all()
        for row in grouped:
            self.db.add(
                ExecutionMetricDaily(
                    project_id=project_id,
                    environment_id=row.environment_id,
                    execution_type=row.execution_type,
                    time_bucket=bucket,
                    status=row.status,
                    failure_signature=row.failure_signature,
                    execution_count=int(row.execution_count or 0),
                    duration_sum_ms=int(row.duration_sum_ms or 0),
                    duration_max_ms=int(row.duration_max_ms or 0),
                    watermark=row.watermark,
                )
            )
        self.db.flush()
        return len(grouped)

    def rebuild_recent(
        self, *, now: datetime | None = None, lookback_hours: int = 2
    ) -> int:
        now = (now or datetime.utcnow()).replace(tzinfo=None)
        changed = self.db.execute(
            select(
                ExecutionRecordIndex.project_id,
                ExecutionRecordIndex.started_at,
            )
            .where(
                ExecutionRecordIndex.source_updated_at
                >= now - timedelta(hours=lookback_hours),
                ExecutionRecordIndex.started_at.is_not(None),
            )
            .order_by(ExecutionRecordIndex.source_updated_at.desc())
            .execution_options(yield_per=1000)
        )
        hour_buckets = {
            (int(row.project_id), _hour_bucket(row.started_at))
            for row in changed
            if row.started_at is not None
        }
        for project_id, bucket in sorted(hour_buckets):
            self.rebuild_hour(project_id=project_id, bucket=bucket)
        day_buckets = {
            (project_id, _day_bucket(bucket)) for project_id, bucket in hour_buckets
        }
        for project_id, bucket in sorted(day_buckets):
            self.rebuild_day(project_id=project_id, bucket=bucket)
        return len(hour_buckets)

    def query_failure_clusters(
        self,
        *,
        project_id: int,
        started_from: datetime,
        started_to: datetime,
        limit: int = 20,
        execution_type: str | None = None,
        environment_id: int | None = None,
        status_filter: str | None = None,
    ) -> dict[str, Any]:
        base_filters = self._index_range_filters(
            project_id=project_id,
            started_from=started_from,
            started_to=started_to,
            execution_type=execution_type,
            environment_id=environment_id,
            status_filter=status_filter,
        )
        filters = list(base_filters)
        filters.append(ExecutionRecordIndex.failure_signature.is_not(None))
        filters.append(ExecutionRecordIndex.failure_signature != "")
        cluster_rows = self.db.execute(
            select(
                ExecutionRecordIndex.failure_signature,
                func.count().label("count"),
                func.count(distinct(ExecutionRecordIndex.resource_id)).label(
                    "distinct_resource_count"
                ),
                func.min(ExecutionRecordIndex.started_at).label("first_seen_at"),
                func.max(ExecutionRecordIndex.started_at).label("last_seen_at"),
            )
            .where(*filters)
            .group_by(ExecutionRecordIndex.failure_signature)
            .order_by(
                func.count().desc(),
                func.max(ExecutionRecordIndex.started_at).desc(),
            )
            .limit(_bounded_limit(limit))
        ).all()
        signatures = [row.failure_signature for row in cluster_rows]
        samples: dict[str, list[str]] = {signature: [] for signature in signatures}
        if signatures:
            ranked = (
                select(
                    ExecutionRecordIndex.failure_signature.label("signature"),
                    ExecutionRecordIndex.execution_type,
                    ExecutionRecordIndex.execution_id,
                    func.row_number()
                    .over(
                        partition_by=ExecutionRecordIndex.failure_signature,
                        order_by=(
                            ExecutionRecordIndex.started_at.desc(),
                            ExecutionRecordIndex.execution_id.desc(),
                        ),
                    )
                    .label("sample_rank"),
                )
                .where(
                    *filters,
                    ExecutionRecordIndex.failure_signature.in_(signatures),
                )
                .subquery()
            )
            sample_rows = self.db.execute(
                select(
                    ranked.c.signature,
                    ranked.c.execution_type,
                    ranked.c.execution_id,
                    ranked.c.sample_rank,
                )
                .where(ranked.c.sample_rank <= 5)
                .order_by(ranked.c.signature, ranked.c.sample_rank)
            ).all()
            for row in sample_rows:
                samples[row.signature].append(
                    f"{row.execution_type}:{row.execution_id}"
                )
        watermark = self.db.scalar(
            select(func.max(ExecutionRecordIndex.source_updated_at)).where(
                *base_filters
            )
        )
        return {
            "failure_clusters": [
                {
                    "failure_signature": row.failure_signature,
                    "count": int(row.count or 0),
                    "distinct_resource_count": int(
                        row.distinct_resource_count or 0
                    ),
                    "first_seen_at": row.first_seen_at,
                    "last_seen_at": row.last_seen_at,
                    "sample_execution_refs": samples[row.failure_signature],
                }
                for row in cluster_rows
            ],
            "watermark": watermark,
        }

    def query_metrics(
        self,
        *,
        project_id: int,
        started_from: datetime,
        started_to: datetime,
        limit: int = 20,
        execution_type: str | None = None,
        environment_id: int | None = None,
        status_filter: str | None = None,
    ) -> dict[str, Any]:
        granularity = (
            "day" if started_to - started_from >= timedelta(days=7) else "hour"
        )
        metric_model = (
            ExecutionMetricDaily if granularity == "day" else ExecutionMetricHourly
        )
        first_bucket = (
            _day_bucket(started_from)
            if granularity == "day"
            else _hour_bucket(started_from)
        )
        filters: list[Any] = [
            metric_model.project_id == project_id,
            metric_model.time_bucket >= first_bucket,
            metric_model.time_bucket < started_to,
        ]
        if execution_type is not None:
            filters.append(metric_model.execution_type == execution_type)
        if environment_id is not None:
            filters.append(metric_model.environment_id == environment_id)
        if status_filter is not None:
            filters.append(metric_model.status == status_filter)
        rows = self.db.scalars(
            select(metric_model)
            .where(*filters)
            .order_by(metric_model.time_bucket.desc())
            .limit(_bounded_limit(limit))
        ).all()
        source_filters = self._index_range_filters(
            project_id=project_id,
            started_from=started_from,
            started_to=started_to,
            execution_type=execution_type,
            environment_id=environment_id,
            status_filter=status_filter,
        )
        watermark = self.db.scalar(
            select(func.max(ExecutionRecordIndex.source_updated_at)).where(
                *source_filters
            )
        )
        return {
            "metrics": [
                {
                    "time_bucket": row.time_bucket,
                    "environment_id": row.environment_id,
                    "execution_type": row.execution_type,
                    "status": row.status,
                    "failure_signature": row.failure_signature,
                    "execution_count": row.execution_count,
                    "duration_sum_ms": row.duration_sum_ms,
                    "duration_max_ms": row.duration_max_ms,
                }
                for row in rows
            ],
            "granularity": granularity,
            "watermark": watermark,
        }

    @staticmethod
    def _index_range_filters(
        *,
        project_id: int,
        started_from: datetime,
        started_to: datetime,
        execution_type: str | None,
        environment_id: int | None,
        status_filter: str | None,
    ) -> list[Any]:
        filters: list[Any] = [
            ExecutionRecordIndex.project_id == project_id,
            ExecutionRecordIndex.started_at >= started_from,
            ExecutionRecordIndex.started_at < started_to,
        ]
        if execution_type is not None:
            filters.append(ExecutionRecordIndex.execution_type == execution_type)
        if environment_id is not None:
            filters.append(ExecutionRecordIndex.environment_id == environment_id)
        if status_filter is not None:
            filters.append(ExecutionRecordIndex.status == status_filter)
        return filters


def _hour_bucket(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0, tzinfo=None)


def _day_bucket(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


def _bounded_limit(value: int) -> int:
    return min(max(int(value), 1), 200)
