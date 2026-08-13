from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.models.execution_diagnostic import (
    ExecutionPayloadArtifact,
    ExecutionRecordIndex,
    ExecutionStepDiagnostic,
)


class ExecutionDiagnosticRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert_execution_index(self, values: dict[str, Any]) -> None:
        if self._dialect_name() == "mysql":
            statement = mysql_insert(ExecutionRecordIndex).values(**values)
            updates = {
                key: statement.inserted[key]
                for key in values
                if key not in {"id", "created_at"}
            }
            self.db.execute(statement.on_duplicate_key_update(**updates))
            return
        existing = self.get_execution_index(
            project_id=int(values["project_id"]),
            execution_type=str(values["execution_type"]),
            execution_id=int(values["execution_id"]),
        )
        self._select_then_update(
            model=ExecutionRecordIndex,
            existing=existing,
            values=values,
        )

    def upsert_step(self, values: dict[str, Any]) -> None:
        if self._dialect_name() == "mysql":
            statement = mysql_insert(ExecutionStepDiagnostic).values(**values)
            updates = {
                key: statement.inserted[key]
                for key in values
                if key not in {"id", "created_at"}
            }
            self.db.execute(statement.on_duplicate_key_update(**updates))
            return
        existing = self.get_step(
            project_id=int(values["project_id"]),
            execution_type=str(values["execution_type"]),
            execution_id=int(values["execution_id"]),
            step_id=str(values["step_id"]),
        )
        self._select_then_update(
            model=ExecutionStepDiagnostic,
            existing=existing,
            values=values,
        )

    def upsert_artifact(self, values: dict[str, Any]) -> None:
        if self._dialect_name() == "mysql":
            statement = mysql_insert(ExecutionPayloadArtifact).values(**values)
            updates = {
                key: statement.inserted[key]
                for key in values
                if key not in {"id", "created_at"}
            }
            self.db.execute(statement.on_duplicate_key_update(**updates))
            return
        existing = self.get_artifact(
            project_id=int(values["project_id"]),
            artifact_ref=str(values["artifact_ref"]),
        )
        self._select_then_update(
            model=ExecutionPayloadArtifact,
            existing=existing,
            values=values,
        )

    def get_artifact(
        self, *, project_id: int, artifact_ref: str
    ) -> ExecutionPayloadArtifact | None:
        return self.db.scalar(
            select(ExecutionPayloadArtifact).where(
                ExecutionPayloadArtifact.project_id == project_id,
                ExecutionPayloadArtifact.artifact_ref == artifact_ref,
            )
        )

    def get_execution_index(
        self, *, project_id: int, execution_type: str, execution_id: int
    ) -> ExecutionRecordIndex | None:
        return self.db.scalar(
            select(ExecutionRecordIndex).where(
                ExecutionRecordIndex.project_id == project_id,
                ExecutionRecordIndex.execution_type == execution_type,
                ExecutionRecordIndex.execution_id == execution_id,
            )
        )

    def get_step(
        self,
        *,
        project_id: int,
        execution_type: str,
        execution_id: int,
        step_id: str,
    ) -> ExecutionStepDiagnostic | None:
        return self.db.scalar(
            select(ExecutionStepDiagnostic).where(
                ExecutionStepDiagnostic.project_id == project_id,
                ExecutionStepDiagnostic.execution_type == execution_type,
                ExecutionStepDiagnostic.execution_id == execution_id,
                ExecutionStepDiagnostic.step_id == step_id,
            )
        )

    def list_all_steps(
        self,
        *,
        project_id: int,
        execution_type: str,
        execution_id: int,
    ) -> list[ExecutionStepDiagnostic]:
        return list(
            self.db.scalars(
                select(ExecutionStepDiagnostic)
                .where(
                    ExecutionStepDiagnostic.project_id == project_id,
                    ExecutionStepDiagnostic.execution_type == execution_type,
                    ExecutionStepDiagnostic.execution_id == execution_id,
                )
                .order_by(
                    ExecutionStepDiagnostic.step_index.asc(),
                    ExecutionStepDiagnostic.id.asc(),
                )
            ).all()
        )

    def count_indexes(
        self, *, project_id: int, execution_type: str, execution_id: int
    ) -> int:
        return int(
            self.db.scalar(
                select(func.count()).select_from(ExecutionRecordIndex).where(
                    ExecutionRecordIndex.project_id == project_id,
                    ExecutionRecordIndex.execution_type == execution_type,
                    ExecutionRecordIndex.execution_id == execution_id,
                )
            )
            or 0
        )

    def list_records_cursor(
        self,
        *,
        project_id: int,
        execution_type: str | None,
        status_filter: str | None,
        environment_id: int | None,
        trigger_user_id: int | None,
        started_from: datetime | None,
        started_to: datetime | None,
        keyword: str | None,
        cursor: ExecutionCursor | None,
        limit: int,
    ) -> list[ExecutionRecordIndex]:
        filters = self._record_filters(
            project_id=project_id,
            execution_type=execution_type,
            status_filter=status_filter,
            environment_id=environment_id,
            trigger_user_id=trigger_user_id,
            started_from=started_from,
            started_to=started_to,
            keyword=keyword,
        )
        if cursor is not None:
            filters.append(
                or_(
                    ExecutionRecordIndex.started_at < cursor.started_at,
                    and_(
                        ExecutionRecordIndex.started_at == cursor.started_at,
                        ExecutionRecordIndex.execution_type > cursor.execution_type,
                    ),
                    and_(
                        ExecutionRecordIndex.started_at == cursor.started_at,
                        ExecutionRecordIndex.execution_type == cursor.execution_type,
                        ExecutionRecordIndex.execution_id < cursor.execution_id,
                    ),
                )
            )
        return list(
            self.db.scalars(
                select(ExecutionRecordIndex)
                .where(*filters)
                .order_by(
                    ExecutionRecordIndex.started_at.desc(),
                    ExecutionRecordIndex.execution_type.asc(),
                    ExecutionRecordIndex.execution_id.desc(),
                )
                .limit(limit)
            ).all()
        )

    def count_records(
        self,
        *,
        project_id: int,
        execution_type: str | None,
        status_filter: str | None,
        environment_id: int | None,
        trigger_user_id: int | None,
        started_from: datetime | None,
        started_to: datetime | None,
        keyword: str | None,
    ) -> int:
        filters = self._record_filters(
            project_id=project_id,
            execution_type=execution_type,
            status_filter=status_filter,
            environment_id=environment_id,
            trigger_user_id=trigger_user_id,
            started_from=started_from,
            started_to=started_to,
            keyword=keyword,
        )
        return int(
            self.db.scalar(
                select(func.count()).select_from(ExecutionRecordIndex).where(*filters)
            )
            or 0
        )

    @staticmethod
    def _record_filters(
        *,
        project_id: int,
        execution_type: str | None,
        status_filter: str | None,
        environment_id: int | None,
        trigger_user_id: int | None,
        started_from: datetime | None,
        started_to: datetime | None,
        keyword: str | None,
    ) -> list[Any]:
        filters: list[Any] = [
            ExecutionRecordIndex.project_id == project_id,
            ExecutionRecordIndex.started_at.is_not(None),
        ]
        if execution_type is not None:
            filters.append(ExecutionRecordIndex.execution_type == execution_type)
        if status_filter is not None:
            public_statuses = {
                "running": ("running", "queued", "pending", "claimed", "launching"),
                "paused": ("paused", "waiting_user"),
                "passed": ("passed", "success", "completed", "assisted"),
                "failed": ("failed", "error", "timeout", "lost"),
            }
            filters.append(
                ExecutionRecordIndex.status.in_(public_statuses[status_filter])
                if status_filter in public_statuses
                else ExecutionRecordIndex.status == status_filter
            )
        if environment_id is not None:
            filters.append(ExecutionRecordIndex.environment_id == environment_id)
        if trigger_user_id is not None:
            filters.append(ExecutionRecordIndex.trigger_user_id == trigger_user_id)
        if started_from is not None:
            filters.append(ExecutionRecordIndex.started_at >= started_from)
        if started_to is not None:
            filters.append(ExecutionRecordIndex.started_at <= started_to)
        if keyword:
            filters.append(
                ExecutionRecordIndex.resource_name.ilike(f"%{keyword.strip()}%")
            )
        return filters

    def _dialect_name(self) -> str:
        bind = self.db.get_bind()
        return str(bind.dialect.name)

    def _select_then_update(
        self, *, model: type, existing: Any | None, values: dict[str, Any]
    ) -> None:
        if existing is None:
            self.db.add(model(**values))
        else:
            for key, value in values.items():
                if key not in {"id", "created_at"}:
                    setattr(existing, key, value)
        self.db.flush()


@dataclass(frozen=True)
class ExecutionCursor:
    started_at: datetime
    execution_type: str
    execution_id: int


def encode_cursor(value: ExecutionCursor) -> str:
    started_at = value.started_at
    if started_at.tzinfo is not None:
        started_at = started_at.astimezone(UTC).replace(tzinfo=None)
    payload = {
        "v": 1,
        "started_at": started_at.isoformat(),
        "execution_type": value.execution_type,
        "execution_id": value.execution_id,
    }
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(encoded).decode().rstrip("=")


def decode_cursor(value: str) -> ExecutionCursor:
    try:
        if not isinstance(value, str) or not value or len(value) > 512:
            raise ValueError("invalid cursor size")
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(
            (value + padding).encode(), altchars=b"-_", validate=True
        )
        payload = json.loads(decoded)
        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise ValueError("unsupported cursor version")
        execution_type = payload.get("execution_type")
        if execution_type not in {"http", "websocket", "scenario", "flow", "ui"}:
            raise ValueError("invalid execution type")
        execution_id = payload.get("execution_id")
        if isinstance(execution_id, bool) or not isinstance(execution_id, int) or execution_id < 1:
            raise ValueError("invalid execution id")
        started_at = datetime.fromisoformat(str(payload.get("started_at") or ""))
        if started_at.tzinfo is not None:
            started_at = started_at.astimezone(UTC).replace(tzinfo=None)
        return ExecutionCursor(
            started_at=started_at,
            execution_type=execution_type,
            execution_id=execution_id,
        )
    except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid execution cursor",
        ) from exc
